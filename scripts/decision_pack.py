#!/usr/bin/env python3
"""Numbers behind the owner's decision pack (REFINE200, 2026-10-14).

    python scripts/decision_pack.py            # from the repo root

Recomputes every live-book and evidence figure quoted in
docs/DECISIONS_2026-10-14.md from the COMMITTED files, so the pack can be
re-read on any later day without re-deriving anything by hand:

  journal/vivek_bot_book.<market>.json    the paper book (closed + open rows)
  public/data/vivek_backtest_longonly.json  the 10y long-only replay
  data/edge_rosters.json (+ its monthly shards)  plain A+ rosters
  data/alert_forward_returns.json         multi-lens alignments
  data/history/asx/<SYMBOL>.json          completed ASX bars (archive)

READ-ONLY: it opens files for reading and prints to stdout. Nothing is
written, nothing is downloaded, and nothing under scanner/broker/ is
imported (tests/test_decision_pack.py pins all three).

THE PRE-REGISTRATION (PREREG below) is FROZEN on 2026-10-14, deliberately
hardcoded beside the code that evaluates it -- the evidence_brief pattern.
The point of writing a threshold down before the data arrives is that it
cannot be moved once the data is in; a test pins the doc's register to these
numbers, so moving one means editing both in plain sight. ASCII prints only.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKETS = ("asx", "nasdaq", "crypto")

# The journal's own definition of a rules exit (journal.js / app.js /
# status.js MECHANICAL_EXITS; parity pinned by the test). Anything else --
# "manual", or no reason at all -- was a hand close.
MECHANICAL_EXITS = ("stop", "time", "trail", "target")

# The hc4-1 cycle as it was defined when the pack was written. Frozen here
# (not read from config) so a later rule change cannot silently redefine the
# cohort the checkpoints judge; the test pins it to config while config's
# cycle tag still says hc4-1.
HC41 = {
    "tag": "hc4-1",
    "grades": ("A+", "A"),
    "cells": {"1W": ("reclaim", "break"), "3D": ("reclaim",), "1D": ("break",)},
    "levels": ("weekly", "3d"),
    "max_hold_days": 28,
    "start": "2026-09-21",
    # rows opened before this carry grade "A+" even when the take was an A
    # (vivek_bot recorded a hard-coded "A+" until 2026-09-24)
    "grade_label_fixed": "2026-09-24",
    "hands_off": "2026-10-14",
}

# FROZEN 2026-10-14. kind:
#   "live"    -- judged on hc4-1 rows closed by the rules
#   "replay"  -- judged on the decision_replay output (not committed yet)
#   "rosters" -- judged on data/edge_rosters.json forward returns
#   "forward" -- judged on an Ignition backtest file's forward bucket
# A live line is read once, on the day the cohort's min_n-th rules close
# lands, over every close up to that day. It trips when the average R is <=
# line (and, where `versus` is set, also <= the versus cohort's average over
# the same days minus `gap`); it clears when the average is >= pass. Anything
# else waits for the one second read (`then`).
PREREG = (
    {"id": "PR-0", "item": "cycle", "kind": "live", "cohort": "all",
     "min_n": 40, "line": -0.25, "pass": 0.00,
     "then": {"min_n": 80, "line": -0.25},
     "action": "owner review of the whole rule set before any further change"},
    {"id": "PR-1", "item": "#2", "kind": "live", "cohort": "cell:3D reclaim",
     "min_n": 20, "line": -0.30, "pass": 0.00,
     "then": {"min_n": 40, "line": -0.15},
     "action": "drop 3D reclaim from the entry cells for new entries"},
    {"id": "PR-2", "item": "#1", "kind": "live", "cohort": "market:asx",
     "versus": "market:nasdaq", "gap": 0.30, "min_n": 15, "line": -0.30,
     "then": {"min_n": 30, "line": -0.30},
     "action": "stop NEW ASX entries; open ASX positions run to their exits"},
    {"id": "PR-3", "item": "#3", "kind": "live", "cohort": "grade:A",
     "versus": "grade:A+", "gap": 0.30, "min_n": 15, "line": -0.30,
     "then": {"min_n": 30, "line": -0.30},
     "action": "bot back to A+ only"},
    {"id": "PR-4", "item": "#4", "kind": "replay", "min_gain": 0.05,
     "action": "weekly-level only, if it beats weekly+3d by >= +0.05R/trade "
               "in ASX and NASDAQ separately and in both halves"},
    {"id": "PR-5", "item": "#137/#153", "kind": "replay", "min_gain": 0.10,
     "min_n": 200,
     "action": "arm 1W/3D on completed candles only, if completed beats "
               "forming by >= +0.10R/trade with >= 200 trades in each arm"},
    {"id": "PR-6", "item": "#36", "kind": "rosters", "since": "2026-09-21",
     "read_on": "2026-10-27", "min_n": 40, "gap_pp": 1.0, "horizon": "20",
     "action": "demote the High-conviction badge to a plain tag (display only)"},
    {"id": "PR-7", "item": "#32", "kind": "replay", "min_gain": 0.03,
     "action": "change the 28-day time stop, only if 21/42/off beats 28 by "
               ">= +0.03R/trade in ASX and NASDAQ separately"},
    {"id": "PR-8", "item": "#47", "kind": "forward", "min_n": 30,
     "action": "drop Ignition's 3x volume rule if, on >= 30 forward trades "
               "in a market, the no-volume-rule variant does at least as well"},
)


# -- loading ---------------------------------------------------------------

def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_book(root=ROOT):
    """(closed, open) rows across every market's canonical book file."""
    closed, opn = [], []
    for m in MARKETS:
        p = os.path.join(root, "journal", f"vivek_bot_book.{m}.json")
        if not os.path.exists(p):
            continue
        b = _load(p)
        for r in b.get("closed") or []:
            closed.append(dict(r, market=r.get("market") or m))
        for r in b.get("open") or []:
            opn.append(dict(r, market=r.get("market") or m))
    return closed, opn


def load_ledger(root, name):
    """Entries of an edge ledger. data/edge_rosters.json may be the single
    v1 file or (REFINE200 #62) a manifest beside monthly shards in
    data/edge_rosters/<YYYY-MM>.json; both layouts read the same, deduped on
    the row key. None when the ledger is absent."""
    p = os.path.join(root, "data", name)
    shard_dir = os.path.splitext(p)[0]
    shards = sorted(os.path.join(shard_dir, f) for f in os.listdir(shard_dir)
                    if f.endswith(".json")) if os.path.isdir(shard_dir) else []
    if not shards and not os.path.exists(p):
        return None
    out, keys = [], set()
    for sp in shards + ([p] if os.path.exists(p) else []):
        doc = _load(sp)
        for e in (doc.get("entries") if isinstance(doc, dict) else None) or []:
            k = e.get("key")
            if k is not None and k in keys:
                continue
            keys.add(k)
            out.append(e)
    return out


# -- small helpers ---------------------------------------------------------

def r_of(row):
    v = row.get("realized_r")
    return v if isinstance(v, (int, float)) and v == v else 0.0


def is_rules(row):
    return str(row.get("exit_reason") or "").strip().lower() in MECHANICAL_EXITS


def cell(row):
    return f"{row.get('timeframe')} {row.get('entry_type')}"


def stats(rows, value=r_of):
    vals = [value(r) for r in rows]
    n = len(vals)
    if not n:
        return {"n": 0, "total": 0.0, "avg": None, "wins": 0, "win_pct": None}
    tot = sum(vals)
    wins = sum(1 for v in vals if v > 0)
    return {"n": n, "total": round(tot, 2), "avg": round(tot / n, 3),
            "wins": wins, "win_pct": round(100.0 * wins / n)}


def fmt(s):
    if not s["n"]:
        return "n=0"
    return (f"n={s['n']:<3} {s['total']:+7.2f}R  avg {s['avg']:+.3f}R  "
            f"win {s['win_pct']}%")


def group(rows, key):
    out = defaultdict(list)
    for r in rows:
        out[key(r)].append(r)
    return dict(out)


def hc41_rules_closes(closed):
    return [r for r in closed if r.get("cycle") == HC41["tag"] and is_rules(r)]


def select(rows, spec):
    """Rows matching a cohort spec: all / cell:<tf type> / market:<m> / grade:<g>.

    Grade cohorts use only rows opened on/after the grade-label fix, because
    an A take opened before it is recorded as A+."""
    if spec == "all":
        return list(rows)
    kind, _, val = spec.partition(":")
    if kind == "cell":
        return [r for r in rows if cell(r) == val]
    if kind == "market":
        return [r for r in rows if r.get("market") == val]
    if kind == "grade":
        return [r for r in rows if r.get("grade") == val
                and str(r.get("entry_date") or "") >= HC41["grade_label_fixed"]]
    raise ValueError(f"unknown cohort {spec!r}")


# -- the pre-registered live checkpoints -----------------------------------

def _exit_day(row):
    return str(row.get("exit_date") or "")


def _read(rows, n):
    """The rows a read at `n` closes sees: every close up to and including
    the day the n-th one landed. None until there are n closes.

    A checkpoint is read ONCE at its n (and once more at its second n), never
    as a rolling number: checking an average every day until it happens to
    cross a line would make the line meaningless. Pinning the read to the day
    the n-th close landed also makes the verdict the same whenever the script
    is run."""
    dated = sorted(rows, key=lambda r: (_exit_day(r), str(r.get("symbol") or "")))
    if len(dated) < n:
        return None
    cutoff = _exit_day(dated[n - 1])
    return [r for r in dated if _exit_day(r) <= cutoff], cutoff


def _trips(pr, pool, rows, cutoff, line):
    s = stats(rows)
    if s["avg"] is None or s["avg"] > line:
        return False, s, None
    if not pr.get("versus"):
        return True, s, None
    vs = stats([r for r in select(pool, pr["versus"]) if _exit_day(r) <= cutoff])
    return vs["avg"] is not None and s["avg"] <= vs["avg"] - pr["gap"], s, vs


def evaluate(pr, closed):
    """Verdict for one live PREREG entry: NOT DUE, TRIPPED, CLEAR or HOLD
    (between the lines at the first read, waiting for the second)."""
    pool = hc41_rules_closes(closed)
    rows = select(pool, pr["cohort"])
    now = stats(rows)
    out = {"id": pr["id"], "n": now["n"], "avg": now["avg"], "min_n": pr["min_n"]}
    first = _read(rows, pr["min_n"])
    if first is None:
        out["verdict"] = "NOT DUE"
        return out
    read, cutoff = first
    tripped, s, vs = _trips(pr, pool, read, cutoff, pr["line"])
    out.update(read_on=cutoff, read_n=s["n"], read_avg=s["avg"],
               versus_avg=vs["avg"] if vs else None)
    if tripped:
        out["verdict"] = "TRIPPED"
        return out
    if "pass" in pr and s["avg"] >= pr["pass"]:
        out["verdict"] = "CLEAR"
        return out
    then = pr.get("then")
    second = _read(rows, then["min_n"]) if then else None
    if then is None:
        out["verdict"] = "CLEAR"
    elif second is None:
        out["verdict"] = "HOLD"
    else:
        read2, cutoff2 = second
        tripped2, s2, vs2 = _trips(pr, pool, read2, cutoff2, then["line"])
        out.update(read_on=cutoff2, read_n=s2["n"], read_avg=s2["avg"],
                   versus_avg=vs2["avg"] if vs2 else None)
        out["verdict"] = "TRIPPED" if tripped2 else "CLEAR"
    return out


# -- report sections -------------------------------------------------------

def headline(closed):
    rules = [r for r in closed if is_rules(r)]
    hand = [r for r in closed if not is_rules(r)]
    return {"all": stats(closed), "rules": stats(rules), "hand": stats(hand),
            "by_cycle": {str(c): {"rules": stats([r for r in rs if is_rules(r)]),
                                  "hand": stats([r for r in rs if not is_rules(r)])}
                         for c, rs in sorted(group(closed, lambda r: r.get("cycle")).items(),
                                             key=lambda kv: str(kv[0]))}}


def projected_closes(opn):
    """A what-if, never a verdict: every open hc4-1 row that has not reached
    TP1 closes at TODAY's mark on the day its 28-day time stop falls due.
    Stops, trails and new entries before then are ignored, so this only says
    which way a checkpoint is leaning, not where it will land."""
    out = []
    for r in opn:
        if r.get("cycle") != HC41["tag"] or r.get("tp1_hit"):
            continue
        try:
            d = dt.date.fromisoformat(r["entry_date"]) + dt.timedelta(days=HC41["max_hold_days"])
        except (KeyError, ValueError):
            continue
        out.append(dict(r, status="closed", exit_reason="time", exit_date=d.isoformat(),
                        realized_r=r.get("unreal_r") or 0.0))
    return out


def time_stop_schedule(opn):
    """Calendar dates the 28-day time stop falls due for hc4-1 rows that have
    not reached TP1 (a runner past TP1 is exempt)."""
    due = Counter()
    for r in opn:
        if r.get("cycle") != HC41["tag"] or r.get("tp1_hit"):
            continue
        try:
            d = dt.date.fromisoformat(r["entry_date"]) + dt.timedelta(days=HC41["max_hold_days"])
        except (KeyError, ValueError):
            continue
        due[d.isoformat()] += 1
    return sorted(due.items())


def mae_report(closed, opn, deep=-0.5):
    hit = [r for r in closed if isinstance(r.get("mae_r"), (int, float)) and r["mae_r"] <= deep]
    still = [r for r in opn if isinstance(r.get("mae_r"), (int, float)) and r["mae_r"] <= deep]
    return {"closed": len(hit), "won": sum(1 for r in hit if r_of(r) > 0),
            "by_exit": dict(Counter(str(r.get("exit_reason")) for r in hit)),
            "open": len(still),
            "open_now_positive": sum(1 for r in still if (r.get("unreal_r") or 0) > 0)}


def review_label(row):
    if "review" not in row:
        return "absent"
    return "flagged" if row["review"] else "clean"


def review_report(closed, opn):
    out = {}
    for name, rows, val in (("closed", closed, r_of),
                            ("open", opn, lambda r: r.get("unreal_r") or 0.0)):
        g = group(rows, review_label)
        out[name] = {k: dict(stats(v, val),
                             risk_usd=round(sum(r.get("risk_usd") or 0 for r in v)),
                             usd=round(sum(val(r) * (r.get("risk_usd") or 0) for r in v)))
                     for k, v in g.items()}
    return out


def p12_readout(closed):
    """P12 (PROPOSALS_2026-09-04): trail/target questions on rules closes."""
    rules = [r for r in closed if is_rules(r)]
    tp1 = [r for r in rules if r.get("tp1_hit")]
    big = [r for r in rules if (r.get("mfe_r") or 0) >= 1.0]
    return {"rules_closes": len(rules),
            "mfe_ge_1r": len(big),
            "mfe_ge_1r_exit_le_0p2r": [r["symbol"] for r in big if r_of(r) <= 0.2],
            "tp1_hits": len(tp1),
            "tp1_avg_mfe": round(statistics.mean(r.get("mfe_r") or 0 for r in tp1), 2) if tp1 else None,
            "tp1_avg_r": round(statistics.mean(r_of(r) for r in tp1), 2) if tp1 else None,
            "tp1_symbols": [r["symbol"] for r in tp1]}


def archive_after(root, row, sessions=28):
    """What the completed-bar archive says happened after a close: the first
    of (original stop, TP1/TP2) touched in the next `sessions` bars, and the
    last close in R. ASX only (the archive covers the ASX). None if absent."""
    a = _archive(root, row.get("market", ""), row.get("symbol"))
    if not a:
        return None
    days, bars = a
    j = bisect.bisect_left(days, row.get("exit_date") or "")
    if j >= len(days):
        return None
    # the archive is dividend-adjusted: rescale to the price actually traded
    scale = (row["exit_price"] / bars[j][4]) if days[j] == row.get("exit_date") and bars[j][4] else 1.0
    entry, risk = row["entry"], row["risk"]
    stop0, up = entry - risk, (row["tp2"] if row.get("tp1_hit") else row["tp1"])
    fut = bars[j + 1:j + 1 + sessions]
    first = None
    for b in fut:
        if b[3] * scale <= stop0:
            first = ("orig_stop", b[0])
            break
        if b[2] * scale >= up:
            first = ("tp2" if row.get("tp1_hit") else "tp1", b[0])
            break
    last_r = round((fut[-1][4] * scale - entry) / risk, 2) if fut else None
    return {"sessions": len(fut), "first": first, "last_r": last_r}


def _archive(root, market, symbol):
    p = os.path.join(root, "data", "history", market, f"{symbol}.json")
    if not os.path.exists(p):
        return None
    bars = _load(p).get("bars") or []
    return [b[0] for b in bars], bars


def hand_close_counterfactual(root, closed):
    """What the rules would have done with each ASX hand close, replayed on
    the completed-bar archive from the day after the hand exit: the row's
    stop at the time (stop-first inside a bar), the TP ladder (TP1 moves the
    stop to entry, TP2 to TP1), and the 28-day time stop before TP1. A trade
    the archive runs out on is marked at its last archived close ("open").
    ASX only: the archive holds no NASDAQ or crypto bars."""
    out = []
    for r in closed:
        if is_rules(r) or r.get("market") != "asx":
            continue
        a = _archive(root, "asx", r.get("symbol"))
        if not a:
            continue
        days, bars = a
        j = bisect.bisect_left(days, r.get("exit_date") or "")
        if j >= len(days) or days[j] != r.get("exit_date") or not bars[j][4]:
            continue
        scale = r["exit_price"] / bars[j][4]
        entry, risk = r["entry"], r["risk"]
        if not risk or risk <= 0:
            continue
        scale_out = r.get("scale") or [0.25, 0.5, 0.15]
        tps = [r["tp1"], r["tp2"], r["tp3"]]
        hit = [bool(r.get("tp1_hit")), bool(r.get("tp2_hit")), bool(r.get("tp3_hit"))]
        stop = r["stop"]
        legs = [e for e in r.get("exits") or [] if str(e.get("reason", "")).startswith("tp")]
        booked = sum(e["pct"] for e in legs)
        gross = sum(e["pct"] * (e["price"] - entry) / risk for e in legs)
        d0 = dt.date.fromisoformat(r["entry_date"])
        how = "open"
        for b in bars[j + 1:]:
            o, hi, lo, c = (x * scale for x in b[1:5])
            if lo <= stop:
                gross += (1 - booked) * (min(o, stop) - entry) / risk
                how = "stop"
                break
            for k in range(3):
                if not hit[k] and hi >= tps[k]:
                    hit[k] = True
                    booked += scale_out[k]
                    gross += scale_out[k] * (tps[k] - entry) / risk
                    if k == 0:
                        stop = max(stop, entry)
                    elif k == 1:
                        stop = max(stop, tps[0])
            if not hit[0] and (dt.date.fromisoformat(b[0]) - d0).days >= HC41["max_hold_days"]:
                gross += (1 - booked) * (c - entry) / risk
                how = "time"
                break
        else:
            gross += (1 - booked) * (bars[-1][4] * scale - entry) / risk
        out.append({"symbol": r["symbol"], "exit_date": r["exit_date"],
                    "hand_r": round(r_of(r), 2), "rules_r": round(gross, 2), "how": how})
    return out


def stamp_check(root, cutoff="2026-10-05", tol=0.005):
    """#30: do the ASX forward-return stamps in the two edge ledgers agree
    with the completed-bar archive? A stamp is 'early' when the bar it reads
    is dated before `cutoff` (the 2026-10-05 bar-final fix)."""
    res = {}
    cache = {}
    for name in ("edge_rosters.json", "alert_forward_returns.json"):
        entries = load_ledger(root, name)
        if entries is None:
            continue
        c = Counter()
        for e in entries:
            if e.get("market") != "asx":
                continue
            sym = e.get("ticker")
            if sym not in cache:
                cache[sym] = _archive(root, "asx", sym)
            a = cache[sym]
            if not a:
                c["no_archive"] += 1
                continue
            days, bars = a
            bi = bisect.bisect_left(days, e.get("base_day") or "")
            for h in ("1", "5", "10", "20"):
                v = (e.get("fwd") or {}).get(h)
                if v is None:
                    continue
                i = bi + int(h)
                if bi >= len(days) or i >= len(days) or not bars[bi][4]:
                    c["uncheckable"] += 1
                    continue
                when = "early" if days[i] < cutoff else "late"
                c[when] += 1
                if abs(v - (bars[i][4] / bars[bi][4] - 1)) > tol:
                    c[f"{when}_differ"] += 1
        res[name] = dict(c)
    return res


def backtest_replica(root=ROOT, name="vivek_backtest_longonly.json"):
    """The hc4-1 entry rule replayed on a committed backtest's trades."""
    p = os.path.join(root, "public", "data", name)
    if not os.path.exists(p):
        return None
    trades = _load(p).get("trades") or []
    rep = [t for t in trades
           if t.get("direction") == "long"
           and t.get("grade") in HC41["grades"]
           and t.get("entry_type") in HC41["cells"].get(t.get("timeframe"), ())
           and t.get("level_tf") in HC41["levels"]]
    def held(t):
        try:
            return (dt.date.fromisoformat(t["exit_date"]) - dt.date.fromisoformat(t["entry_date"])).days
        except (KeyError, TypeError, ValueError):
            return None
    deep = [t for t in rep if (t.get("mae_r") or 0) <= -0.5]
    won = [t for t in deep if r_of(t) > 0]
    holds = [h for h in (held(t) for t in won) if h is not None]
    stocks = [t for t in rep if t.get("market") != "crypto"]
    return {"n": len(rep), "all": stats(rep),
            "by_market": {k: stats(v) for k, v in group(rep, lambda t: t["market"]).items()},
            "by_grade": {k: stats(v) for k, v in group(rep, lambda t: t["grade"]).items()},
            "by_cell": {k: stats(v) for k, v in group(rep, cell).items()},
            "by_level": {k: stats(v) for k, v in group(rep, lambda t: t["level_tf"]).items()},
            "stocks_by_grade": {k: stats(v) for k, v in group(stocks, lambda t: t["grade"]).items()},
            "stocks_by_cell": {k: stats(v) for k, v in group(stocks, cell).items()},
            "deep_mae": len(deep), "deep_mae_won": len(won),
            "deep_won_hold_median_days": statistics.median(holds) if holds else None,
            "deep_won_held_over_28d": sum(1 for h in holds if h > HC41["max_hold_days"])}


def _signed(e, h):
    v = (e.get("fwd") or {}).get(h)
    if v is None:
        return None
    return v if e.get("side") == "long" else -v


def _dedup(rows):
    seen, out = set(), []
    for x in sorted(rows, key=lambda x: x.get("base_day") or ""):
        k = (x.get("market"), x.get("ticker"), x.get("side"))
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def _mean_se(vals):
    vals = [v for v in vals if v is not None]
    n = len(vals)
    if not n:
        return {"n": 0, "mean_pct": None, "se_pp": None}
    se = statistics.pstdev(vals) / math.sqrt(n) if n > 1 else None
    return {"n": n, "mean_pct": round(100 * statistics.mean(vals), 2),
            "se_pp": round(100 * se, 2) if se is not None else None}


def hc_checkpoint(root=ROOT, since="2026-09-21"):
    """PR-6 / #36: High-conviction vs other A+ longs, first sighting per name."""
    rows = load_ledger(root, "edge_rosters.json")
    if rows is None:
        return None
    ents = [e for e in rows
            if e.get("side") == "long" and (e.get("base_day") or "") >= since]
    out = {}
    for h in ("5", "10", "20"):
        ok = [e for e in ents if (e.get("fwd") or {}).get(h) is not None]
        out[h] = {"hc": _mean_se([_signed(e, h) for e in _dedup([e for e in ok if e.get("hiconv")])]),
                  "other": _mean_se([_signed(e, h) for e in _dedup([e for e in ok if not e.get("hiconv")])])}
    return out


def roster_market_20(root=ROOT):
    """#1: plain A+ long 20-session returns by market, first sighting per name."""
    rows = load_ledger(root, "edge_rosters.json")
    if rows is None:
        return None
    ents = [e for e in rows
            if e.get("side") == "long" and (e.get("fwd") or {}).get("20") is not None]
    return {m: _mean_se([_signed(e, "20") for e in _dedup([e for e in ents if e["market"] == m])])
            for m in MARKETS}


# -- printing --------------------------------------------------------------

def main(argv=None, root=ROOT, out=sys.stdout):
    closed, opn = load_book(root)
    w = lambda s="": out.write(s + "\n")  # noqa: E731

    w("# Decision pack numbers (scripts/decision_pack.py)")
    w(f"book: {len(closed)} closed, {len(opn)} open")
    h = headline(closed)
    w(f"all closes    {fmt(h['all'])}")
    w(f"rules closes  {fmt(h['rules'])}")
    w(f"hand closes   {fmt(h['hand'])}")
    for c, v in h["by_cycle"].items():
        w(f"  cycle {c:6} rules {fmt(v['rules'])} | hand {fmt(v['hand'])}")
    cf = hand_close_counterfactual(root, closed)
    if cf:
        w(f"ASX hand closes the archive can replay: {len(cf)}; taken by hand "
          f"{sum(x['hand_r'] for x in cf):+.2f}R, rules would have made "
          f"{sum(x['rules_r'] for x in cf):+.2f}R ({dict(Counter(x['how'] for x in cf))})")

    w("")
    w("## hc4-1 (rules closes only)")
    hc = [r for r in closed + opn if r.get("cycle") == HC41["tag"]]
    hcc = hc41_rules_closes(closed)
    w(f"rows {len(hc)}: closed {sum(1 for r in hc if r.get('status') == 'closed')} "
      f"(rules {len(hcc)}), open {sum(1 for r in hc if r.get('status') == 'open')}")
    for label, key in (("cell", cell), ("market", lambda r: r.get("market")),
                       ("grade", lambda r: r.get("grade")), ("level", lambda r: r.get("level_tf"))):
        g = group(hc, key)
        for k in sorted(g, key=str):
            o = [r for r in g[k] if r.get("status") == "open"]
            c = [r for r in g[k] if r.get("status") == "closed" and is_rules(r)]
            w(f"  {label:6} {str(k):12} open {len(o):2} unreal {sum(r.get('unreal_r') or 0 for r in o):+6.2f}R"
              f" | closed {fmt(stats(c))}")
    cum = len(hcc)
    w("time stops due (hc4-1, pre-TP1):")
    for d, n in time_stop_schedule(opn):
        cum += n
        w(f"  {d} {n:2}  -> {cum} hc4-1 closes if nothing stops out first")

    w("")
    w("## Pre-registered checkpoints (frozen 2026-10-14)")
    for pr in PREREG:
        if pr["kind"] == "live":
            v = evaluate(pr, closed)
            avg = f"{v['avg']:+.3f}R" if v["avg"] is not None else "-"
            read = ""
            if v.get("read_on"):
                vs = f" vs {v['versus_avg']:+.3f}R" if v.get("versus_avg") is not None else ""
                read = f"  read {v['read_on']}: n={v['read_n']} avg {v['read_avg']:+.3f}R{vs}"
            w(f"  {pr['id']} {pr['item']:5} {pr['cohort']:16} n={v['n']}/{v['min_n']} "
              f"avg {avg}  line {pr['line']:+.2f}R{read}  -> {v['verdict']}")
        else:
            w(f"  {pr['id']} {pr['item']:9} {pr['kind']}: {pr['action']}")
    w("  what-if (open rows close at today's marks on their time-stop day):")
    proj = closed + projected_closes(opn)
    for pr in PREREG:
        if pr["kind"] == "live":
            v = evaluate(pr, proj)
            read = (f"read {v['read_on']}: n={v['read_n']} avg {v['read_avg']:+.3f}R"
                    if v.get("read_on") else f"n={v['n']}/{v['min_n']}")
            w(f"    {pr['id']} {read} -> {v['verdict']}")

    w("")
    w("## Live book by market / cell / level (all cycles)")
    for label, key in (("market", lambda r: r.get("market")), ("cell", cell),
                       ("level", lambda r: r.get("level_tf"))):
        g = group(closed, key)
        for k in sorted(g, key=str):
            w(f"  {label:6} {str(k):12} all {fmt(stats(g[k]))} | rules "
              f"{fmt(stats([r for r in g[k] if is_rules(r)]))}")

    w("")
    w("## #34 MAE: closes that were ever -0.5R or worse")
    m = mae_report(closed, opn)
    w(f"  closed {m['closed']}, won {m['won']}, by exit {m['by_exit']}; "
      f"open {m['open']} (now positive {m['open_now_positive']})")

    w("")
    w("## #35 review flags")
    rv = review_report(closed, opn)
    for side in ("closed", "open"):
        for k, v in sorted(rv[side].items()):
            w(f"  {side:6} {k:8} {fmt(v)}  risk ${v['risk_usd']:,}  P&L ${v['usd']:,}")

    w("")
    w("## #32 time-stop exits")
    t = [r for r in closed if str(r.get("exit_reason")) == "time"]
    w(f"  {fmt(stats(t))}")
    for r in t:
        a = archive_after(root, r)
        tail = (f" | next {a['sessions']} sessions: first {a['first']}, last {a['last_r']:+.2f}R"
                if a and a["last_r"] is not None else "")
        w(f"  {r['market']:6} {r['symbol']:6} {r.get('exit_date')} {r_of(r):+.2f}R{tail}")

    w("")
    w("## #33 P12 readout")
    p = p12_readout(closed)
    w(f"  rules closes {p['rules_closes']}; MFE >= 1R: {p['mfe_ge_1r']}, of which exited "
      f"<= +0.2R: {p['mfe_ge_1r_exit_le_0p2r']}")
    w(f"  TP1 hit: {p['tp1_hits']} {p['tp1_symbols']} avg MFE {p['tp1_avg_mfe']}R, "
      f"avg realised {p['tp1_avg_r']}R")
    for r in [r for r in closed if is_rules(r) and r.get("tp1_hit")]:
        a = archive_after(root, r)
        if a:
            w(f"  after breakeven exit {r['symbol']}: first {a['first']}, last {a['last_r']:+.2f}R "
              f"({a['sessions']} sessions)")

    w("")
    w("## Backtest replica of hc4-1 (vivek_backtest_longonly.json, no time stop)")
    b = backtest_replica(root)
    if b:
        w(f"  all {fmt(b['all'])}")
        for part in ("by_market", "by_grade", "by_cell", "by_level", "stocks_by_grade", "stocks_by_cell"):
            for k, v in sorted(b[part].items()):
                w(f"  {part:15} {k:12} {fmt(v)}")
        w(f"  MAE <= -0.5R: {b['deep_mae']}, still won {b['deep_mae_won']}; those winners held "
          f"median {b['deep_won_hold_median_days']} days, {b['deep_won_held_over_28d']} over 28 days")

    w("")
    w("## #36 High conviction vs other A+ longs (rosters since 2026-09-21)")
    hcp = hc_checkpoint(root)
    if hcp:
        for hz, v in hcp.items():
            w(f"  {hz:>2} sessions  HC {v['hc']}  other {v['other']}")
    w("## #1 plain A+ long rosters, 20 sessions, by market")
    rm = roster_market_20(root)
    if rm:
        for k, v in rm.items():
            w(f"  {k:6} {v}")

    w("")
    w("## #30 ASX ledger stamps vs the completed-bar archive (differ = > 0.5pp)")
    for name, c in stamp_check(root).items():
        w(f"  {name:28} {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
