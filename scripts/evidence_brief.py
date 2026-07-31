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
paper book delta vs the newest backup (closes, new stalls, R change), and one
"what needs human eyes" line whose default answer is nothing.
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


def _stall_syms(book, at):
    out = set()
    for p in book.get("open") or []:
        try:
            age = (at - datetime.datetime.fromisoformat(
                str(p.get("opened_at")).replace("Z", "+00:00"))).days
        except (TypeError, ValueError):
            continue
        if age >= 14 and not p.get("tp1_hit"):
            out.add(p.get("symbol"))
    return out


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
    open_r = sum(p.get("unreal_r") or 0 for p in op)
    backups = sorted(glob.glob(os.path.join(ROOT, "backups", "*", "journal", "vivek_bot_book.json")))
    prev_book = _load(backups[-1]) if backups else None
    if prev_book:
        bstamp = os.path.basename(os.path.dirname(os.path.dirname(backups[-1])))[:10]
        seen = {f"{t.get('symbol')}|{t.get('exit_date')}" for t in prev_book.get("closed") or []}
        closes = [t for t in book.get("closed") or []
                  if f"{t.get('symbol')}|{t.get('exit_date')}" not in seen]
        closes_txt = ", ".join(f"{t['symbol']} {t.get('realized_r') or 0:+.2f}R" for t in closes) or "none"
        try:
            bat = datetime.datetime.strptime(
                os.path.basename(os.path.dirname(os.path.dirname(backups[-1])))[:19],
                "%Y-%m-%dT%H-%M-%S").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            bat = NOW
        new_stalls = sorted(_stall_syms(book, NOW) - _stall_syms(prev_book, bat))
        prev_r = sum(p.get("unreal_r") or 0 for p in prev_book.get("open") or [])
        lines.append(f"book: {len(op)}/30 open, R {open_r:+.2f} ({open_r - prev_r:+.2f} vs {bstamp} backup) | "
                     f"closes since: {closes_txt} | new stalls: {', '.join(new_stalls) or 'none'}")
    else:
        lines.append(f"book: {len(op)}/30 open, R {open_r:+.2f} | no backup baseline for deltas")

    # -- the one human line --------------------------------------------------
    lines.append("human eyes today: " + ("; ".join(issues) if issues else "nothing"))

    assert len(lines) <= 15, f"brief overflowed its 15-line budget ({len(lines)})"
    print("\n".join(lines))
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
