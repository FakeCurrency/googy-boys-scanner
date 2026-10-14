"""Daily Evidence Brief (owner-ruled fast-track, 2026-08-01) — <= 15 lines.

    python scripts/evidence_brief.py            # from the repo root

Report-only, read-only, on demand: reads the COMMITTED artifacts (scan
payloads, funnel history, arriving lists, graduation registry, bot book and
the newest daily backup) and prints a short brief. It writes NOTHING, imports
nothing from scanner/ or broker/, and holds no opinions the artifacts do not
already contain. The 15-line budget is enforced at the end — a brief that
grows stops being one, so overflow is a hard error rather than a drift.

Covers exactly the ruled set: pipeline health (real issues only), funnel
snapshot + direction, arriving names (or zero), graduation events (or zero),
paper book delta vs the newest backup (closes, new stalls, R change), the
cycle w3-1 clock (added at enablement, owner-signed 2026-08-02 - see
RESEARCH-LEDGER.md) and, once it reached n=30, its frozen-protocol VERDICT,
the LIVE cycle's own line (its tag read from bot_rules.json), and one "what
needs human eyes" line whose default answer is nothing.

"New stalls" are the ENGINE's stale_pinged stamps (vivek_run's stale probe:
held >= VIVEK_BOT_STALE_PROBE_DAYS and |unreal_r| below its band), current
book vs the newest backup -- the one definition the journal's STALLED strip
and the status lamp read. The brief used to recompute its own rule (14 days
and no TP1), which named a different cohort (45 vs 35 on 2026-10-14).
"""
from __future__ import annotations

import datetime
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "public", "data")
NOW = datetime.datetime.now(datetime.timezone.utc)

# Cycle w3-1 - the pre-registered 30-close live read (owner-signed 2026-08-02;
# protocol + evidence in RESEARCH-LEDGER.md). These are FROZEN protocol
# numbers, deliberately hardcoded: the brief may not import scanner.config
# (read-only pins), and retuning any of them mid-cycle is what the protocol
# forbids. The band is the w3 cohort's thrice-replicated sim expectancy
# (parity IS/OOS/C3 pessimistic fills; midpoint from the fill study) - the
# frozen reference the live number is judged against at n=30:
# pass >= 0 R/trade AND >= 0 R/slot-month; kill <= -0.05 R/trade.
CYCLE = "w3-1"
CYCLE_TARGET = 30
CYCLE_BAND = "band pess +0.056 / mid +0.10 R/t"
# The n=30 verdict, judged on the FIRST CYCLE_TARGET closes (exit order) with
# the protocol's own frozen lines. w3-1 passed n=30 on 2026-09-16 and ended
# 2026-09-21 (hc4-1 replaced it); the brief kept counting "58/30" with no
# verdict. A KILL is an ISSUE only while the cycle is the LIVE one -- an
# ended cycle's verdict is history, printed every day but never an alarm that
# cannot stop ringing.
CYCLE_PASS_RT = 0.0       # pass: >= 0 R/trade AND >= 0 R/slot-month
CYCLE_KILL_RT = -0.05     # kill: <= -0.05 R/trade
SLOT_MONTH_DAYS = 30.4375


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _age_h(stamp):
    try:
        return (NOW - datetime.datetime.fromisoformat(stamp)).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def _day_stats(cols, day):
    idx = [i for i, t in enumerate(cols["t"]) if t[:10] == day]
    if not idx:
        return None
    n = len(idx)
    return {k: sum(cols[k][i] for i in idx) / n
            for k in ("published", "floor_killed", "arriving")}


def _stalled(book):
    """Symbols the engine's stale probe has stamped (`stale_pinged`). Read,
    never recomputed: the probe owns the definition."""
    return {p.get("symbol") for p in (book or {}).get("open") or [] if p.get("stale_pinged")}


def _cycle_stats(rows):
    """(R/trade, R/slot-month or None) over closed rows; R/slot-month uses
    each row's own hold_days and is None until a close carries one."""
    tot = sum(t.get("realized_r") or 0 for t in rows)
    sm = sum(t.get("hold_days") or 0 for t in rows) / SLOT_MONTH_DAYS
    return tot / len(rows), (tot / sm if sm > 0 else None)


def cycle_verdict(closed):
    """The pre-registered n=CYCLE_TARGET read: (verdict, R/t, R/sm, date of
    the n-th close) on the FIRST CYCLE_TARGET closes in exit order (a stable
    sort, so same-day closes keep the book's close order), or None before n
    is reached. PASS needs >= 0 R/t AND >= 0 R/sm; KILL is <= -0.05 R/t;
    anything between is INCONCLUSIVE."""
    if len(closed) < CYCLE_TARGET:
        return None
    first = sorted(closed, key=lambda t: str(t.get("exit_date") or ""))[:CYCLE_TARGET]
    rt, rsm = _cycle_stats(first)
    if rt <= CYCLE_KILL_RT:
        verdict = "KILL"
    elif rt >= CYCLE_PASS_RT and rsm is not None and rsm >= CYCLE_PASS_RT:
        verdict = "PASS"
    else:
        verdict = "INCONCLUSIVE"
    return verdict, rt, rsm, str(first[-1].get("exit_date") or "?")


def _fmt_stats(rows):
    if not rows:
        return "no closes yet"
    rt, rsm = _cycle_stats(rows)
    return f"exp {rt:+.3f}R/t" + (f", {rsm:+.3f} R/sm" if rsm is not None else "")


def main() -> int:
    lines = []
    issues = []

    # -- pipeline health: speak only when something is actually wrong --------
    ages = {}
    for m in ("asx", "nasdaq", "crypto"):
        vk = _load(os.path.join(DATA, f"{m}_vivek.json")) or {}
        ages[m] = _age_h(vk.get("generated_at"))
    if ages.get("crypto") is None or ages["crypto"] > 3:
        issues.append(f"crypto scan stale ({ages.get('crypto') and round(ages['crypto'], 1)}h)")
    for m in ("asx", "nasdaq"):
        if ages.get(m) is None or ages[m] > 80:   # generous: survives any weekend
            issues.append(f"{m} scan stale ({ages.get(m) and round(ages[m], 1)}h)")
    health = ("ISSUE: " + "; ".join(issues)) if issues else (
        "pipeline OK (asx %.1fh / ndq %.1fh / crypto %.1fh)" % (
            ages["asx"], ages["nasdaq"], ages["crypto"]))
    lines.append(f"# Evidence brief {NOW.strftime('%Y-%m-%d %H:%M')}Z - {health}")

    # -- funnel snapshot + direction ----------------------------------------
    fh = (_load(os.path.join(DATA, "funnel_history.json")) or {}).get("markets", {})
    for m in ("asx", "nasdaq", "crypto"):
        cols = fh.get(m)
        if not cols or not cols.get("t"):
            lines.append(f"funnel {m}: no history"); continue
        days = sorted({t[:10] for t in cols["t"]})
        today, prev = _day_stats(cols, days[-1]), (_day_stats(cols, days[-2]) if len(days) > 1 else None)
        kill_share = today["floor_killed"] / max(today["published"] + today["floor_killed"], 1) * 100
        if prev:
            pk = prev["floor_killed"] / max(prev["published"] + prev["floor_killed"], 1) * 100
            d = kill_share - pk
            trend = "flat" if abs(d) < 2 else ("floor tighter %+.1fpp" % d if d > 0 else "floor looser %+.1fpp" % d)
        else:
            trend = "baseline day"
        lines.append(f"funnel {m}: pub {today['published']:.0f} | kills {today['floor_killed']:.0f} "
                     f"({kill_share:.0f}% of setups, {trend}) | arriving {today['arriving']:.1f}")

    # -- arriving (or zero) --------------------------------------------------
    arr = []
    for m in ("asx", "nasdaq", "crypto"):
        d = _load(os.path.join(DATA, f"{m}_arriving.json")) or {}
        rows = d.get("results") or []
        if rows:
            arr.append(f"{m}: " + ", ".join(
                f"{r['symbol']} {r.get('rvol', '?')}x" + ("(fund)" if r.get("fund") else "")
                for r in rows[:6]))
    lines.append("arriving: " + ("; ".join(arr) if arr else "zero, all markets"))

    # -- graduation (or zero) ------------------------------------------------
    sg = (_load(os.path.join(DATA, "spec_graduation.json")) or {}).get("markets", {})
    gtot = sum(mk.get("graduated_total") or 0 for mk in sg.values())
    watch = {m: len(mk.get("seen") or {}) for m, mk in sg.items()}
    lines.append(f"graduation: {gtot} lifetime (zero new is the default read) | "
                 f"watching {', '.join(f'{m} {n}' for m, n in sorted(watch.items())) or 'none'}")

    # -- paper book delta vs newest backup -----------------------------------
    book = _load(os.path.join(ROOT, "journal", "vivek_bot_book.json")) or {}
    op = book.get("open") or []
    # The book cap is READ, never typed here: it was a literal "/30" until the
    # owner's 2026-09-27 resize to 60 slots. The brief may not import
    # scanner.config, so it takes the number the scan publishes from config
    # (bot_rules.json max_open_total); unreadable or 0 (off) prints no
    # denominator rather than a guessed one.
    rules = _load(os.path.join(DATA, "bot_rules.json")) or {}
    cap = rules.get("max_open_total")
    cap_txt = f"/{cap}" if isinstance(cap, int) and cap > 0 else ""
    open_r = sum(p.get("unreal_r") or 0 for p in op)
    backups = sorted(glob.glob(os.path.join(ROOT, "backups", "*", "journal", "vivek_bot_book.json")))
    prev_book = _load(backups[-1]) if backups else None
    if prev_book:
        bstamp = os.path.basename(os.path.dirname(os.path.dirname(backups[-1])))[:10]
        seen = {f"{t.get('symbol')}|{t.get('exit_date')}" for t in prev_book.get("closed") or []}
        closes = [t for t in book.get("closed") or []
                  if f"{t.get('symbol')}|{t.get('exit_date')}" not in seen]
        closes_txt = ", ".join(f"{t['symbol']} {t.get('realized_r') or 0:+.2f}R" for t in closes) or "none"
        new_stalls = sorted(s for s in _stalled(book) - _stalled(prev_book) if s)
        prev_r = sum(p.get("unreal_r") or 0 for p in prev_book.get("open") or [])
        lines.append(f"book: {len(op)}{cap_txt} open, R {open_r:+.2f} ({open_r - prev_r:+.2f} vs {bstamp} backup) | "
                     f"closes since: {closes_txt} | new stalls: {', '.join(new_stalls) or 'none'}")
    else:
        lines.append(f"book: {len(op)}{cap_txt} open, R {open_r:+.2f} | no backup baseline for deltas")

    # -- cycle w3-1 clock: closes toward the pre-registered n=30 read --------
    # Counted on rows STAMPED cycle=="w3-1" (written at entry by the runner),
    # so pre-gate history can never blur into the cycle. R/slot-month uses
    # each closed row's own hold_days (omitted until a close carries one).
    # Once n=30 is reached the clock becomes the VERDICT on the first 30.
    live = rules.get("cycle_tag") if isinstance(rules.get("cycle_tag"), str) else None
    cyc_closed = [t for t in book.get("closed") or [] if t.get("cycle") == CYCLE]
    cyc_open = sum(1 for p in op if p.get("cycle") == CYCLE)
    v = cycle_verdict(cyc_closed)
    if v is None:
        lines.append(f"cycle {CYCLE}: {len(cyc_closed)}/{CYCLE_TARGET} closed "
                     f"({_fmt_stats(cyc_closed)}) | {cyc_open} open gated | {CYCLE_BAND}")
    else:
        verdict, rt, rsm, nth = v
        state = "" if live is None else ("LIVE, " if live == CYCLE else "ended, ")
        rsm_txt = f", {rsm:+.3f} R/sm" if rsm is not None else ""
        lines.append(f"cycle {CYCLE}: {state}n={CYCLE_TARGET} verdict {verdict} at {nth} "
                     f"({rt:+.3f}R/t{rsm_txt}; pass >= 0 & >= 0 R/sm, kill <= {CYCLE_KILL_RT}) | "
                     f"all {len(cyc_closed)} closed {_fmt_stats(cyc_closed)} | "
                     f"{cyc_open} open gated | {CYCLE_BAND}")
        if verdict == "KILL" and live == CYCLE:
            issues.append(f"cycle {CYCLE} n={CYCLE_TARGET} verdict KILL ({rt:+.3f}R/t)")

    # -- the LIVE cycle (bot_rules.json cycle_tag): the sample being run now --
    # No frozen protocol is recorded for it here, so it gets numbers, never a
    # verdict: closes, R/t (and R/slot-month), open count.
    if live and live != CYCLE:
        lv_closed = [t for t in book.get("closed") or [] if t.get("cycle") == live]
        lv_open = sum(1 for p in op if p.get("cycle") == live)
        lines.append(f"cycle {live} (live): {len(lv_closed)} closed ({_fmt_stats(lv_closed)}) | "
                     f"{lv_open} open")

    # -- the one human line --------------------------------------------------
    lines.append("human eyes today: " + ("; ".join(issues) if issues else "nothing"))

    assert len(lines) <= 15, f"brief overflowed its 15-line budget ({len(lines)})"
    print("\n".join(lines))
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
