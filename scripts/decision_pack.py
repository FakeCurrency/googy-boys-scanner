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
imported (tests/test_decision_pack.py pins all three). STDLIB-ONLY: the two
scanner modules it reads, scanner.time_stop and scanner.config (the rules-exit
list, the holiday table), are standard library only, and the test walks the
whole import tree.

THE PRE-REGISTRATION (PREREG below) is FROZEN on 2026-10-14, deliberately
hardcoded beside the code that evaluates it -- the evidence_brief pattern.
The point of writing a threshold down before the data arrives is that it
cannot be moved once the data is in; a test pins the doc's register to these
numbers, so moving one means editing both in plain sight. ASCII prints only.
Two register changes were set on 3 Nov 2026 (NEXT100 #5, owner-approved,
each written before the data it judges): PR-1 carries its replay-veto read
(`veto`), which holds its first-read trip for one FINAL re-read at its second
n; and hc4-2's live lines are read by ENTRY COHORT (`"read": "entry"`): the
cycle's first n entries, each at its time-stop horizon, instead of the first
n closes (in close order the quick losers land first).

OPEN ROWS AND THE TIME STOP (NEXT100 #4). An open row is valued at what it
has booked (`realized_r`: a runner's TP legs, less the entry cost) PLUS its
open part at today's mark (`unreal_r`). Every projected or scheduled
time-stop day is scanner.time_stop.time_stop_due's -- the engine's day
max_hold + 1, a stock's weekend rolled to the Monday -- and
scanner.config.MARKET_HOLIDAYS flags the ones that land on a shut market.

THE REPLAY SUMMARY (NEXT100 #6). Beside every checkpoint read the pack prints
the standard error of the read's mean R (sample SD / sqrt n), the ISO weeks
its entries span, and the replay's figure for the same cohort entered in the
same ISO weeks, read from data/research/decision_replay/summary.json (the
decision replay writes it; until it is committed the line says so). Schema 1,
the live-rules arm only:

    {"schema": 1,
     "generated_at": "2026-11-03T10:00:00Z",   # ISO timestamp
     "run": {...},                             # free-form: run id, code, window
     "trades": [{"m": "asx",                   # market: asx | nasdaq | crypto
                 "s": "BHP",                   # symbol
                 "cell": "3D reclaim",         # 1W reclaim | 1W break | 3D reclaim | 1D break
                 "grade": "A+",                # A+ | A
                 "entry": "2026-09-28",        # entry date, YYYY-MM-DD
                 "exit": "2026-10-20",         # exit date, or null while still open
                 "r": -0.42,                   # R of the trade (a mark when open)
                 "reason": "stop"}]}           # exit reason (stop, time, trail, ...)

A same-weeks figure averages the CLOSED trades (exit set) of the cohort
(all / cell / market / grade, as the live line spells it) entered in the
read's ISO weeks; trades still open are counted apart.
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
if ROOT not in sys.path:          # runnable as `python scripts/decision_pack.py`
    sys.path.insert(0, ROOT)
from scanner import config  # noqa: E402  (stdlib-only constants)
from scanner.config import MARKET_HOLIDAYS  # noqa: E402  (stdlib-only)
from scanner.time_stop import time_stop_due  # noqa: E402  (stdlib-only: the one definition)

MARKETS = ("asx", "nasdaq", "crypto")
REPLAY_SUMMARY = "data/research/decision_replay/summary.json"   # NEXT100 #6, schema above

# The ONE definition of a rules exit (NEXT100 #9): config.VIVEK_BOT_RULES_EXITS,
# which the site reads from bot_rules.json (journal.js / app.js / status.js
# MECHANICAL_EXITS are its offline fallbacks; parity pinned by the tests).
# Anything else -- "manual", or no reason at all -- was a hand close. Config's
# list is APPEND-ONLY (tests/test_rules_exits.py), so the frozen checkpoints
# below never lose a reason they counted.
MECHANICAL_EXITS = config.VIVEK_BOT_RULES_EXITS

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

# The hc4-2 cycle (owner approved items 2, 3, 4, 6 and 7 of the hc4-2
# proposal on 2026-11-02). Same grades, cells, levels and time stop as hc4-1;
# the changes are in how a row is graded and filled (see the doc). Frozen here
# for the same reason HC41 is; the test pins it to config while it runs.
# d14_*: the day-14 what-if (PR-16) -- the stamp day and the best-R floor.
HC42 = {
    "tag": "hc4-2",
    "grades": ("A+", "A"),
    "cells": {"1W": ("reclaim", "break"), "3D": ("reclaim",), "1D": ("break",)},
    "levels": ("weekly", "3d"),
    "max_hold_days": 28,
    "start": "2026-11-02",
    "d14_days": 14,
    "d14_mfe_floor": 0.5,
}

# FROZEN 2026-10-14. kind:
#   "live"    -- judged on hc4-1 rows closed by the rules
#   "replay"  -- judged on the decision_replay output (not committed yet)
#   "rosters" -- judged on data/edge_rosters.json forward returns
#   "forward" -- judged on an Ignition backtest file's forward bucket
#   "shadow"  -- judged on the book's day-14 stamps (hc4-2 on): the what-if
#                cut set beside the rules' own result, per market
# A live line is read once, on the day the cohort's min_n-th rules close
# lands, over every close up to that day. It trips when the average R is <=
# line (and, where `versus` is set, also <= the versus cohort's average over
# the same days minus `gap`); it clears when the average is >= pass. Anything
# else waits for the one second read (`then`).
# "read": "entry" (hc4-2's lines, set 3 Nov 2026, NEXT100 #5) reads the
# line's first min_n ENTRIES instead, each at its time-stop horizon (see
# horizon_value), on the day the last of them gets there; a versus cohort is
# its entries up to the cohort's last entry date. No "read" = close order.
# "veto" (PR-1, set 3 Nov 2026): the replay-veto read; a first-read trip
# holds for one FINAL re-read at then.min_n with then.line.
PREREG = (
    {"id": "PR-0", "item": "cycle", "kind": "live", "cohort": "all",
     "min_n": 40, "line": -0.25, "pass": 0.00,
     "then": {"min_n": 80, "line": -0.25},
     "action": "owner review of the whole rule set before any further change"},
    {"id": "PR-1", "item": "#2", "kind": "live", "cohort": "cell:3D reclaim",
     "min_n": 20, "line": -0.30, "pass": 0.00,
     "then": {"min_n": 40, "line": -0.15},
     # set 3 Nov 2026 (NEXT100 #5, owner-approved): the replay-veto read. The
     # first read tripped (-0.433R over 21); the replay has the cohort at or
     # over min_avg, so the trip HOLDS for one final re-read at then.min_n
     # closes with then.line -- no second veto.
     "veto": {"read_on": "2026-11-03", "replay_avg": 0.054, "replay_n": 689,
              "min_avg": 0.05, "source": "3 Nov decision replay, hc4-2 code"},
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
    # -- hc4-2, FROZEN 2026-11-02 (owner approved item 7: the draft in the
    # hc4-2 proposal, written before the cycle's first entry). An entry with
    # no "cycle" key judges hc4-1; these judge hc4-2's rules closes. "shadow"
    # is judged on the day-14 stamps (`d14`) the book writes from hc4-2 on.
    {"id": "PR-9", "item": "hc4-2", "cycle": "hc4-2", "kind": "live", "read": "entry", "cohort": "all",
     "min_n": 40, "line": -0.25, "pass": 0.00,
     "then": {"min_n": 80, "line": -0.25},
     "action": "owner review of the whole rule set before any further change"},
    {"id": "PR-10", "item": "hc4-2", "cycle": "hc4-2", "kind": "live", "read": "entry", "cohort": "cell:1W reclaim",
     "min_n": 20, "line": -0.30, "pass": 0.00,
     "then": {"min_n": 40, "line": -0.15},
     "action": "drop 1W reclaim from the entry cells for new entries"},
    {"id": "PR-11", "item": "hc4-2", "cycle": "hc4-2", "kind": "live", "read": "entry", "cohort": "cell:1W break",
     "min_n": 20, "line": -0.30, "pass": 0.00,
     "then": {"min_n": 40, "line": -0.15},
     "action": "drop 1W break from the entry cells for new entries"},
    {"id": "PR-12", "item": "hc4-2", "cycle": "hc4-2", "kind": "live", "read": "entry", "cohort": "cell:3D reclaim",
     "min_n": 20, "line": -0.30, "pass": 0.00,
     "then": {"min_n": 40, "line": -0.15},
     "action": "drop 3D reclaim from the entry cells for new entries"},
    {"id": "PR-13", "item": "hc4-2", "cycle": "hc4-2", "kind": "live", "read": "entry", "cohort": "cell:1D break",
     "min_n": 20, "line": -0.30, "pass": 0.00,
     "then": {"min_n": 40, "line": -0.15},
     "action": "drop 1D break from the entry cells for new entries"},
    {"id": "PR-14", "item": "hc4-2", "cycle": "hc4-2", "kind": "live", "read": "entry", "cohort": "market:asx",
     "versus": "market:nasdaq", "gap": 0.30, "min_n": 15, "line": -0.30,
     "then": {"min_n": 30, "line": -0.30},
     "action": "stop NEW ASX entries; open ASX positions run to their exits"},
    {"id": "PR-15", "item": "hc4-2", "cycle": "hc4-2", "kind": "live", "read": "entry", "cohort": "grade:A",
     "versus": "grade:A+", "gap": 0.30, "min_n": 15, "line": -0.30,
     "then": {"min_n": 30, "line": -0.30},
     "action": "bot back to A+ only"},
    {"id": "PR-16", "item": "#4", "cycle": "hc4-2", "kind": "shadow", "min_n": 40,
     "min_gain": 0.05, "day": 14, "floor": 0.5,
     "action": "propose a day-14 cut for the next cycle (exit a pre-TP1 trade whose "
               "best R by day 14 is under +0.5R), if it beats the rules by >= "
               "+0.05R/trade in ASX and NASDAQ separately"},
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


def cycle_rules_closes(closed, tag):
    return [r for r in closed if r.get("cycle") == tag and is_rules(r)]


def hc41_rules_closes(closed):
    return cycle_rules_closes(closed, HC41["tag"])


def cycle_of(pr):
    """The cycle a register entry judges: hc4-1 unless it names one."""
    return pr.get("cycle", HC41["tag"])


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


def read_mode(pr):
    """How a live line is read: "close" (the day its n-th rules close lands;
    hc4-1's lines) or "entry" (its first n entries at their horizon; hc4-2's,
    set 3 Nov 2026)."""
    return pr.get("read", "close")


def _entry_day(row):
    return str(row.get("entry_date") or "")


HAND = "hand"   # horizon_value: closed by hand before its horizon


def horizon_value(row, is_open):
    """What one entry counts in an entry-cohort read (NEXT100 #5): (R, day)
    once it has reached its horizon, None while it has not, or HAND when it
    was closed by hand before it (it leaves the cohort). The horizon is the
    time stop's day: a row the book stamped there (`horizon`, written on the
    first in-session run a still-open runner is held past max_hold days)
    counts the stamp's R on the stamp's day; a row closed by the rules before
    it counts its realised R on its exit day."""
    h = row.get("horizon")
    if (isinstance(h, dict) and isinstance(h.get("r"), (int, float))
            and not isinstance(h["r"], bool) and math.isfinite(h["r"])):
        return h["r"], str(h.get("day") or "")
    if is_open:
        return None
    if not is_rules(row):
        return HAND
    return r_of(row), _exit_day(row)


def horizon_entries(tag, closed, opn=()):
    """Every entry of cycle `tag` an entry-cohort read sees, as (row, value)
    in entry order -- entry_date, then opened_at, then symbol -- closed rows
    before open ones on a full tie. Rows closed by hand before their horizon
    are left out."""
    out = []
    for rows, is_open in ((closed, False), (opn, True)):
        for r in rows or ():
            if r.get("cycle") != tag:
                continue
            v = horizon_value(r, is_open)
            if v != HAND:
                out.append((r, v))
    out.sort(key=lambda e: (_entry_day(e[0]), str(e[0].get("opened_at") or ""),
                            str(e[0].get("symbol") or "")))
    return out


def _close_reader(pr, closed):
    """(now, read) for a close-order line: read(n, line) is the read at the
    day the n-th rules close landed, None before it."""
    pool = cycle_rules_closes(closed, cycle_of(pr))
    rows = select(pool, pr["cohort"])
    now = stats(rows)

    def read(n, line):
        got = _read(rows, n)
        if got is None:
            return None
        rows_n, cutoff = got
        tripped, s, vs = _trips(pr, pool, rows_n, cutoff, line)
        return {"tripped": tripped, "s": s, "vs": vs, "day": cutoff,
                "rows": rows_n, "value": r_of, "at": n, "line": line}
    return {"n": now["n"], "avg": now["avg"]}, read


def _entry_reader(pr, closed, opn):
    """(now, read) for an entry-cohort line: read(n, line) reads the line's
    first n entries once every one of them -- and, with `versus`, every
    versus entry dated up to the cohort's last entry -- has its horizon
    value, on the latest of their horizon days; None before that."""
    ents = horizon_entries(cycle_of(pr), closed, opn)
    val = {id(r): v for r, v in ents if v is not None}
    rows = select([r for r, _ in ents], pr["cohort"])
    vrows = select([r for r, _ in ents], pr["versus"]) if pr.get("versus") else []

    def value(r):
        return val[id(r)][0]

    def read(n, line):
        cohort = rows[:n]
        if len(cohort) < n:
            return None
        last = _entry_day(cohort[-1])
        vs_rows = [r for r in vrows if _entry_day(r) <= last]
        if any(id(r) not in val for r in cohort + vs_rows):
            return None
        day = max(val[id(r)][1] for r in cohort + vs_rows)
        s = stats(cohort, value)
        tripped, vs = False, None
        if s["avg"] is not None and s["avg"] <= line:
            if not pr.get("versus"):
                tripped = True
            else:
                vs = stats(vs_rows, value)
                tripped = vs["avg"] is not None and s["avg"] <= vs["avg"] - pr["gap"]
        return {"tripped": tripped, "s": s, "vs": vs, "day": day,
                "rows": cohort, "value": value, "at": n, "line": line}
    valued = [r for r in rows if id(r) in val]
    return {"n": len(valued), "avg": stats(valued, value)["avg"], "entries": len(rows)}, read


def vetoes(pr):
    """True when the entry carries a replay-veto read at or over its line."""
    v = pr.get("veto")
    return isinstance(v, dict) and v["replay_avg"] >= v["min_avg"]


def veto_reason(pr, unit, final):
    """The words evaluate() puts beside a vetoed line (journal.js
    prVetoReason prints the same string)."""
    v, then = pr["veto"], pr["then"]
    if final:
        return (f"final re-read at {then['min_n']} {unit} after the replay veto "
                f"(line {then['line']:+.2f}R; no second veto)")
    return (f"replay veto: {v['source']} (read {v['read_on']}) has the cohort at "
            f"{v['replay_avg']:+.3f}R a trade over {v['replay_n']}, at or over "
            f"{v['min_avg']:+.2f}R, so the trip holds for one final re-read at "
            f"{then['min_n']} {unit} with the line at {then['line']:+.2f}R")


def _evaluate(pr, closed, opn=()):
    """evaluate() plus the reads behind its verdict, in order (the first,
    then the second or the veto's re-read once it has landed)."""
    entry = read_mode(pr) == "entry"
    now, read = _entry_reader(pr, closed, opn) if entry else _close_reader(pr, closed)
    out = {"id": pr["id"], "n": now["n"], "avg": now["avg"], "min_n": pr["min_n"]}
    if entry:
        out["entries"] = now["entries"]
    first = read(pr["min_n"], pr["line"])
    if first is None:
        out["verdict"] = "NOT DUE"
        return out, []

    def put(rd):
        out.update(read_on=rd["day"], read_n=rd["s"]["n"], read_avg=rd["s"]["avg"],
                   versus_avg=rd["vs"]["avg"] if rd["vs"] else None)
    put(first)
    then = pr.get("then")
    if first["tripped"]:
        if not vetoes(pr):
            out["verdict"] = "TRIPPED"
            return out, [first]
        # the replay veto: the trip holds for ONE final re-read (no second veto)
        unit = "entries" if entry else "closes"
        second = read(then["min_n"], then["line"])
        if second is None:
            out.update(verdict="HOLD", reason=veto_reason(pr, unit, False))
            return out, [first]
        put(second)
        out.update(verdict="TRIPPED" if second["tripped"] else "CLEAR",
                   reason=veto_reason(pr, unit, True))
        return out, [first, second]
    if "pass" in pr and first["s"]["avg"] >= pr["pass"]:
        out["verdict"] = "CLEAR"
        return out, [first]
    second = read(then["min_n"], then["line"]) if then else None
    if then is None:
        out["verdict"] = "CLEAR"
    elif second is None:
        out["verdict"] = "HOLD"
    else:
        put(second)
        out["verdict"] = "TRIPPED" if second["tripped"] else "CLEAR"
        return out, [first, second]
    return out, [first]


def evaluate(pr, closed, opn=()):
    """Verdict for one live PREREG entry: NOT DUE, TRIPPED, CLEAR or HOLD
    (between the lines at the first read waiting for the second, or a trip
    held by the replay veto for its re-read). Close-order lines read only
    the rules closes in `closed`; entry-cohort lines also read `opn`."""
    return _evaluate(pr, closed, opn)[0]


SHADOW_MARKETS = ("asx", "nasdaq")


def whatif_d14(row, floor):
    """The day-14 cut's R for one closed row (hc4-2 item 4). The cut applies
    when the book stamped the row at day 14 (`d14`), TP1 had not been hit by
    then, and the best R so far was under `floor`: it exits at the stamp's R
    less the row's own round-trip cost (`cost_r`). Every other row keeps the
    rules' result -- a trade stopped before day 14 is not a trade the cut
    would have touched."""
    d = row.get("d14")
    if (isinstance(d, dict) and not d.get("tp1_hit")
            and isinstance(d.get("mfe_r"), (int, float)) and d["mfe_r"] < floor
            and isinstance(d.get("r"), (int, float))):
        return round(d["r"] - float(row.get("cost_r") or 0), 4)
    return r_of(row)


def evaluate_shadow(pr, closed, opn=()):
    """Verdict for a "shadow" entry (PR-16): read ONCE on the day the cycle's
    min_n-th rules close lands, over every rules close up to that day. It
    trips -- the cut is proposed -- when the cut's average beats the rules'
    by min_gain or more in the ASX and NASDAQ separately; otherwise CLEAR.
    `opn` is accepted for evaluate()'s signature and not read: the shadow
    stays a close-order read (NEXT100 #5 left PR-16 unchanged)."""
    pool = cycle_rules_closes(closed, cycle_of(pr))
    out = {"id": pr["id"], "n": len(pool), "min_n": pr["min_n"]}
    first = _read(pool, pr["min_n"])
    if first is None:
        out["verdict"] = "NOT DUE"
        return out
    read, cutoff = first
    by = {}
    for m in SHADOW_MARKETS:
        rows = [r for r in read if r.get("market") == m]
        rules = stats(rows)
        cut = stats(rows, value=lambda r: whatif_d14(r, pr["floor"]))
        gain = (round(cut["avg"] - rules["avg"], 3)
                if rules["avg"] is not None and cut["avg"] is not None else None)
        by[m] = {"n": rules["n"], "rules_avg": rules["avg"], "cut_avg": cut["avg"], "gain": gain}
    passed = all(by[m]["gain"] is not None and by[m]["gain"] >= pr["min_gain"]
                 for m in SHADOW_MARKETS)
    out.update(read_on=cutoff, read_n=len(read), by_market=by,
               verdict="TRIPPED" if passed else "CLEAR")
    return out


# -- how sure a read is (NEXT100 #6) ----------------------------------------

def iso_week(day):
    """'2026-W40' for an ISO date, None for anything else."""
    try:
        y, w, _ = dt.date.fromisoformat(str(day or "")[:10]).isocalendar()
    except ValueError:
        return None
    return f"{y}-W{w:02d}"


def read_spread(rows, value=r_of):
    """The standard error of a read's mean R (sample SD / sqrt n; None
    under two rows) and the distinct ISO weeks its entries span. The frozen
    lines do not move: this only says how much a read could be noise, and
    whether it is one window's verdict."""
    vals = [value(r) for r in rows]
    se = round(statistics.stdev(vals) / math.sqrt(len(vals)), 3) if len(vals) > 1 else None
    weeks = sorted({w for w in (iso_week(_entry_day(r)) for r in rows) if w})
    return {"n": len(vals), "se": se, "weeks": weeks}


def load_replay_summary(root=ROOT):
    """The committed decision-replay summary (schema 1, the module
    docstring), or None while it is absent. ValueError when the file is
    there but is not schema 1."""
    p = os.path.join(root, *REPLAY_SUMMARY.split("/"))
    if not os.path.exists(p):
        return None
    doc = _load(p)
    if not (isinstance(doc, dict) and doc.get("schema") == 1 and isinstance(doc.get("trades"), list)):
        raise ValueError(f"{REPLAY_SUMMARY} is not a schema-1 replay summary")
    return doc


def replay_cohort(trades, spec):
    """The replay trades a live cohort spec names (all / cell / market / grade)."""
    if spec == "all":
        return list(trades)
    kind, _, val = spec.partition(":")
    key = {"cell": "cell", "market": "m", "grade": "grade"}.get(kind)
    if key is None:
        raise ValueError(f"unknown cohort {spec!r}")
    return [t for t in trades if isinstance(t, dict) and t.get(key) == val]


def replay_same_weeks(summary, spec, weeks):
    """The replay's figure for a live read's cohort entered in the same ISO
    weeks: n, average R and its standard error over the CLOSED trades (exit
    set, a finite r), and how many of those weeks' trades were still open."""
    wk = set(weeks)
    rows = [t for t in replay_cohort(summary.get("trades") or [], spec)
            if iso_week(t.get("entry")) in wk]
    done = [t for t in rows if t.get("exit")]
    vals = [float(t["r"]) for t in done
            if isinstance(t.get("r"), (int, float)) and not isinstance(t["r"], bool)
            and math.isfinite(t["r"])]
    n = len(vals)
    return {"n": n, "avg": round(sum(vals) / n, 3) if n else None,
            "se": round(statistics.stdev(vals) / math.sqrt(n), 3) if n > 1 else None,
            "open": len(rows) - len(done)}


def spread_text(rd, spec, replay):
    """One line of #6 beside a read: its SE, its ISO entry weeks, and the
    replay's same-cohort, same-weeks figure (or why there is none)."""
    sp = read_spread(rd["rows"], rd["value"])
    wk = sp["weeks"]
    span = ", ".join(wk) if len(wk) <= 4 else f"{wk[0]} .. {wk[-1]}"
    se = "-" if sp["se"] is None else f"{sp['se']:.3f}R"
    text = f"se {se}, {len(wk)} ISO entry week{'' if len(wk) == 1 else 's'} ({span or '-'})"
    if isinstance(replay, str):
        return f"{text}; replay same weeks: {replay}"
    f = replay_same_weeks(replay, spec, wk)
    if not f["n"]:
        fig = "no closed replay trade of this cohort entered in those weeks"
    else:
        fse = "-" if f["se"] is None else f"{f['se']:.3f}R"
        fig = f"n={f['n']} avg {f['avg']:+.3f}R (se {fse})"
    if f["open"]:
        fig += f", {f['open']} still open in the replay (left out)"
    return f"{text}; replay same weeks: {fig}"


# -- report sections -------------------------------------------------------

def headline(closed):
    rules = [r for r in closed if is_rules(r)]
    hand = [r for r in closed if not is_rules(r)]
    return {"all": stats(closed), "rules": stats(rules), "hand": stats(hand),
            "by_cycle": {str(c): {"rules": stats([r for r in rs if is_rules(r)]),
                                  "hand": stats([r for r in rs if not is_rules(r)])}
                         for c, rs in sorted(group(closed, lambda r: r.get("cycle")).items(),
                                             key=lambda kv: str(kv[0]))}}


def unreal_of(row):
    """The open part of an open row at today's mark (unreal_r; 0 if unpriced)."""
    v = row.get("unreal_r")
    return v if isinstance(v, (int, float)) and v == v else 0.0


def open_r(row):
    """An OPEN row's R at today's mark: what it has booked (realized_r: a
    runner's TP legs, less the entry cost) plus its open part (unreal_r,
    already scaled to the fraction still held). NEXT100 #4: the pack used to
    read unreal_r alone and missed the runners' booked R."""
    return r_of(row) + unreal_of(row)


def _hold_days(row):
    """The frozen time-stop length of the row's cycle (HC41 / HC42)."""
    return (HC42 if row.get("cycle") == HC42["tag"] else HC41)["max_hold_days"]


def due_day(row):
    """The engine's time-stop day for an open row, ISO, or None (past TP1,
    no entry date): scanner.time_stop.time_stop_due, the ONE definition --
    day max_hold + 1, a stock's weekend rolled to the Monday."""
    d = time_stop_due(row, _hold_days(row))
    return d.isoformat() if d else None


def projected_closes(opn):
    """A what-if, never a verdict: every open hc4-1 row that has not reached
    TP1 closes at TODAY's mark (booked + open) on the day its time stop falls
    due. Stops, trails and new entries before then are ignored, so this only
    says which way a checkpoint is leaning, not where it will land."""
    out = []
    for r in opn:
        if r.get("cycle") != HC41["tag"]:
            continue
        d = due_day(r)
        if d is None:
            continue
        out.append(dict(r, status="closed", exit_reason="time", exit_date=d,
                        realized_r=open_r(r)))
    return out


def time_stop_schedule(opn, tag=HC41["tag"]):
    """Days the time stop falls due for a cycle's open rows that have not
    reached TP1 (a runner past TP1 is exempt), as [(day, n)]."""
    due = Counter(d for d in (due_day(r) for r in opn if r.get("cycle") == tag) if d)
    return sorted(due.items())


def holiday_stops(opn, holidays=None):
    """Open pre-TP1 rows whose time stop falls on a full-day closure of their
    market (MARKET_HOLIDAYS). The engine does not model holidays, so each
    would book at a stale close on a shut market. Report only:
    [{"day", "market", "symbol", "cycle", "holiday"}] by day."""
    holidays = MARKET_HOLIDAYS if holidays is None else holidays
    out = []
    for r in opn:
        d = due_day(r)
        name = (holidays.get(r.get("market")) or {}).get(d) if d else None
        if name:
            out.append({"day": d, "market": r.get("market"), "symbol": r.get("symbol"),
                        "cycle": r.get("cycle"), "holiday": name})
    return sorted(out, key=lambda x: (x["day"], str(x["market"]), str(x["symbol"])))


def holiday_marks(rows, holidays=None):
    """Audit: rows (open or closed) with a day_marks entry dated on a
    full-day closure of their own market -- a session the book stamped on a
    shut market. {(market, day): sorted symbols}."""
    holidays = MARKET_HOLIDAYS if holidays is None else holidays
    out = defaultdict(set)
    for r in rows:
        shut = holidays.get(r.get("market")) or {}
        for day in (r.get("day_marks") or {}):
            if str(day)[:10] in shut:
                out[(r.get("market"), str(day)[:10])].add(str(r.get("symbol")))
    return {k: sorted(v) for k, v in sorted(out.items())}


def mae_report(closed, opn, deep=-0.5):
    hit = [r for r in closed if isinstance(r.get("mae_r"), (int, float)) and r["mae_r"] <= deep]
    still = [r for r in opn if isinstance(r.get("mae_r"), (int, float)) and r["mae_r"] <= deep]
    return {"closed": len(hit), "won": sum(1 for r in hit if r_of(r) > 0),
            "by_exit": dict(Counter(str(r.get("exit_reason")) for r in hit)),
            "open": len(still),
            "open_now_positive": sum(1 for r in still if open_r(r) > 0)}


def review_label(row):
    if "review" not in row:
        return "absent"
    return "flagged" if row["review"] else "clean"


def review_report(closed, opn):
    out = {}
    for name, rows, val in (("closed", closed, r_of), ("open", opn, open_r)):
        g = group(rows, review_label)
        out[name] = {k: dict(stats(v, val),
                             risk_usd=round(sum(r.get("risk_usd") or 0 for r in v)),
                             usd=round(sum(val(r) * (r.get("risk_usd") or 0) for r in v)))
                     for k, v in g.items()}
    return out


def p12_readout(closed):
    """P12 (docs/archive/PROPOSALS_2026-09-04.md): trail/target questions on rules closes."""
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


# -- the owner's "20 more" (2 Nov): report-only readouts -------------------

def _open_on(root, row):
    """The exit day's OPEN from the completed-bar archive, in the prices the
    book traded: the archive is dividend-adjusted, so it is rescaled by the
    mark the book carried into that session (day_marks[exit day], the prior
    close as traded) over the archive's prior close. None without the bar,
    the prior bar, or a plausible scale (a split is not a dividend)."""
    a = _archive(root, row.get("market", ""), row.get("symbol"))
    if not a:
        return None
    days, bars = a
    j = bisect.bisect_left(days, row.get("exit_date") or "")
    if j >= len(days) or days[j] != row.get("exit_date") or j == 0:
        return None
    o, prev_close = bars[j][1], bars[j - 1][4]
    if not (isinstance(o, (int, float)) and o > 0 and isinstance(prev_close, (int, float))
            and prev_close > 0):
        return None
    carried = (row.get("day_marks") or {}).get(row.get("exit_date"))
    scale = (carried / prev_close) if isinstance(carried, (int, float)) and carried > 0 else 1.0
    if not 0.8 <= scale <= 1.25:
        return None
    return o * scale


def stop_audit(root, closed):
    """#4 How far past its stop each stop-out filled, in R, and why. The book
    fills a stop at the scan that sees it (hourly, on ~15-min-delayed data);
    a resting stop order would fill AT the stop, or at the open when the bar
    gapped through it. Where the archive has the exit day's bar (ASX), the
    distance splits into the GAP (stop to the open, unavoidable) and the LAG
    (resting fill to the actual fill: what a resting stop would have saved)."""
    out = {}
    for mk in MARKETS:
        rows = [r for r in closed if r.get("market") == mk and r.get("exit_reason") == "stop"]
        slips, gaps, lags, exit_r = [], [], [], []
        for r in rows:
            try:
                entry, risk, px = float(r["entry"]), float(r["risk"]), float(r["exit_price"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (risk > 0 and px > 0):
                continue
            long_ = r.get("direction", "long") != "short"
            sign = 1.0 if long_ else -1.0
            stop = r.get("stop")
            stop = float(stop) if isinstance(stop, (int, float)) and stop > 0 else entry - sign * risk
            slips.append(sign * (stop - px) / risk)
            exit_r.append(r_of(r))
            o = _open_on(root, r)
            if o is None:
                continue
            rest = min(o, stop) if long_ else max(o, stop)
            gaps.append(sign * (stop - rest) / risk)
            lags.append(sign * (rest - px) / risk)
        if slips:
            out[mk] = {"n": len(slips), "avg_exit_r": round(sum(exit_r) / len(exit_r), 3),
                       "slip_total": round(sum(slips), 2), "slip_avg": round(sum(slips) / len(slips), 3),
                       "with_bar": len(gaps), "gap_total": round(sum(gaps), 2),
                       "lag_total": round(sum(lags), 2)}
    return out


def mae_cut_whatif(closed, cut=-0.5, tag=None):
    """#5 What-if, never a verdict: every rules close whose recorded MAE
    reached `cut` R is booked at `cut` less its own costs instead. Before
    slippage (a stop-like cut fills past its level too), and MAE is folded
    from scan marks only, so an intrabar dip a scan never saw is missed."""
    rows = [r for r in closed if is_rules(r) and (tag is None or r.get("cycle") == tag)]

    def hit(r):
        m = r.get("mae_r")
        return isinstance(m, (int, float)) and m == m and m <= cut

    def cut_r(r):
        return round(cut - float(r.get("cost_r") or 0.0), 4)

    def block(rs):
        h = [r for r in rs if hit(r)]
        return {"n": len(rs), "hit": len(h), "winners_cut": sum(1 for r in h if r_of(r) > 0),
                "rules_total": round(sum(r_of(r) for r in rs), 2),
                "cut_total": round(sum(cut_r(r) if hit(r) else r_of(r) for r in rs), 2)}

    out = block(rows)
    out["by_market"] = {mk: block([r for r in rows if r.get("market") == mk])
                        for mk in MARKETS if any(r.get("market") == mk for r in rows)}
    return out


def _held(row, end):
    try:
        return max(0, (dt.date.fromisoformat(str(end)[:10])
                       - dt.date.fromisoformat(str(row["entry_date"])[:10])).days)
    except (KeyError, TypeError, ValueError):
        return 0


def r_per_slot_month(rows, today=None):
    """R per slot-month: R earned per position-slot held for a month (30.4375
    days), the decision replay's pass metric. A closed row holds its slot
    entry to exit; an open row (``today`` given) to today, at its mark --
    booked plus open (open_r)."""
    tot = days = 0.0
    for r in rows:
        if r.get("status") == "open":
            if today is None:
                continue
            tot += open_r(r)
            days += _held(r, today)
        else:
            tot += r_of(r)
            days += _held(r, r.get("exit_date"))
    sm = days / 30.4375
    return {"n": len(rows), "slot_months": round(sm, 2),
            "r_per_slot_month": round(tot / sm, 4) if sm > 0 else None}


def book_today(opn, closed):
    """The book's own latest market day (deterministic, not the wall clock)."""
    days = [str(r.get("last_mark_day") or "")[:10] for r in opn]
    days += [str(r.get("exit_date") or "")[:10] for r in closed]
    days = [d for d in days if d]
    return max(days) if days else None


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
    w(f"open rows at today's marks (#4: booked + open): booked "
      f"{sum(r_of(r) for r in opn):+.2f}R + open {sum(unreal_of(r) for r in opn):+.2f}R "
      f"= {sum(open_r(r) for r in opn):+.2f}R")
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

    def schedule(tag):
        cum = len(cycle_rules_closes(closed, tag))
        w(f"time stops due ({tag}, pre-TP1; scanner.time_stop's day, a stock's weekend "
          f"rolled to the Monday):")
        for d, n in time_stop_schedule(opn, tag):
            cum += n
            shut = [x for x in holiday_stops(opn) if x["day"] == d and x["cycle"] == tag]
            flag = "".join(f"  ! {len(g)} on a {mk.upper()} holiday ({g[0]['holiday']})"
                           for mk, g in sorted(group(shut, lambda x: x["market"]).items()))
            w(f"  {d} {n:2}  -> {cum} {tag} closes if nothing stops out first{flag}")

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
            w(f"  {label:6} {str(k):12} open {len(o):2} at {sum(open_r(r) for r in o):+6.2f}R "
              f"(booked {sum(r_of(r) for r in o):+5.2f}R) | closed {fmt(stats(c))}")
    schedule(HC41["tag"])

    w("")
    w(f"## hc4-2 (rules closes only; the cycle since {HC42['start']})")
    h2 = [r for r in closed + opn if r.get("cycle") == HC42["tag"]]
    h2c = cycle_rules_closes(closed, HC42["tag"])
    w(f"rows {len(h2)}: closed {sum(1 for r in h2 if r.get('status') == 'closed')} "
      f"(rules {len(h2c)}), open {sum(1 for r in h2 if r.get('status') == 'open')}")
    for label, key in (("cell", cell), ("market", lambda r: r.get("market"))):
        g = group(h2, key)
        for k in sorted(g, key=str):
            o = [r for r in g[k] if r.get("status") == "open"]
            c = [r for r in g[k] if r.get("status") == "closed" and is_rules(r)]
            w(f"  {label:6} {str(k):12} open {len(o):2} at {sum(open_r(r) for r in o):+6.2f}R "
              f"| closed {fmt(stats(c))}")
    stamped = [r for r in h2 if isinstance(r.get("d14"), dict)]
    w(f"day-14 stamps (#4, report only): {len(stamped)} rows; on closed rules closes the "
      f"cut would apply to {sum(1 for r in h2c if whatif_d14(r, HC42['d14_mfe_floor']) != r_of(r))}")
    w(f"horizon stamps (NEXT100 #5, what an entry-cohort read counts for a runner): "
      f"{sum(1 for r in h2 if isinstance(r.get('horizon'), dict))} rows")
    if any(r.get("status") == "open" for r in h2):
        schedule(HC42["tag"])

    w("")
    w("## Market holidays (scanner.config.MARKET_HOLIDAYS; report only, the engine does "
      "not model them)")
    shut = holiday_stops(opn)
    if shut:
        for (d, mk), g in sorted(group(shut, lambda x: (x["day"], x["market"])).items()):
            w(f"  ! time stop on a shut market: {d} {mk} {g[0]['holiday']}: {len(g)} "
              f"({', '.join(str(x['symbol']) for x in g)}) -- would book at a stale close")
    else:
        w("  no open row's time stop falls on a market holiday")
    marks = holiday_marks(closed + opn)
    w("  audit, day_marks dated on a market holiday (a session stamped on a shut market): "
      + ("; ".join(f"{mk} {d} {(MARKET_HOLIDAYS.get(mk) or {}).get(d)}: {len(s)} rows"
                   for (mk, d), s in marks.items()) or "none"))

    try:
        replay = load_replay_summary(root)
    except ValueError as exc:
        replay = f"unreadable ({exc})"
    if replay is None:
        replay = "no committed replay summary yet"

    def reads_text(pr, reads, indent):
        for i, rd in enumerate(reads):
            word = "entries" if read_mode(pr) == "entry" else "closes"
            label = "first read" if i == 0 else "re-read"
            w(f"{indent}{label} {rd['day']} at {rd['at']} {word} (line {rd['line']:+.2f}R): "
              f"n={rd['s']['n']} avg {rd['s']['avg']:+.3f}R | {spread_text(rd, pr['cohort'], replay)}")

    w("")
    w("## Pre-registered checkpoints (hc4-1 frozen 2026-10-14, hc4-2 frozen 2026-11-02; "
      "PR-1's veto and hc4-2's entry-cohort reads set 2026-11-03)")
    for pr in PREREG:
        tag = cycle_of(pr)
        if pr["kind"] == "live":
            v, reads = _evaluate(pr, closed, opn)
            avg = f"{v['avg']:+.3f}R" if v["avg"] is not None else "-"
            read = ""
            if v.get("read_on"):
                vs = f" vs {v['versus_avg']:+.3f}R" if v.get("versus_avg") is not None else ""
                read = f"  read {v['read_on']}: n={v['read_n']} avg {v['read_avg']:+.3f}R{vs}"
            count = (f"entries {v['entries']}/{v['min_n']} ({v['n']} at the horizon)"
                     if read_mode(pr) == "entry" else f"n={v['n']}/{v['min_n']}")
            w(f"  {pr['id']:5} {tag} {pr['item']:5} {pr['cohort']:16} {count} "
              f"avg {avg}  line {pr['line']:+.2f}R{read}  -> {v['verdict']}")
            if v.get("reason"):
                w(f"        {v['reason']}")
            reads_text(pr, reads, "        ")
        elif pr["kind"] == "shadow":
            v = evaluate_shadow(pr, closed)
            read = ""
            if v.get("read_on"):
                read = "  read " + v["read_on"] + ": " + "; ".join(
                    f"{m} n={b['n']} rules {b['rules_avg'] if b['rules_avg'] is not None else '-'}"
                    f" cut {b['cut_avg'] if b['cut_avg'] is not None else '-'}"
                    for m, b in v["by_market"].items())
            w(f"  {pr['id']:5} {tag} {pr['item']:5} day-14 cut (shadow) n={v['n']}/{v['min_n']}"
              f"{read}  -> {v['verdict']}")
        else:
            w(f"  {pr['id']:5} {tag} {pr['item']:9} {pr['kind']}: {pr['action']}")
    w("  what-if, hc4-1 (open rows close at today's marks, booked + open, on their "
      "time-stop day):")
    proj = closed + projected_closes(opn)
    for pr in PREREG:
        if pr["kind"] == "live" and cycle_of(pr) == HC41["tag"]:
            v, reads = _evaluate(pr, proj)
            read = (f"read {v['read_on']}: n={v['read_n']} avg {v['read_avg']:+.3f}R"
                    if v.get("read_on") else f"n={v['n']}/{v['min_n']}")
            w(f"    {pr['id']} {read} -> {v['verdict']}")
            reads_text(pr, reads, "      ")

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
    w("## Stops: how far past the stop they filled (2 Nov list #4)")
    for mk, a in stop_audit(root, closed).items():
        line = (f"  {mk:7} n={a['n']:<3} avg exit {a['avg_exit_r']:+.3f}R | past the stop "
                f"{a['slip_total']:+.2f}R (avg {a['slip_avg']:+.3f}R)")
        if a["with_bar"]:
            line += (f" | {a['with_bar']} with the day's bar: gap {a['gap_total']:+.2f}R, "
                     f"scan lag {a['lag_total']:+.2f}R (what a resting stop would save)")
        else:
            line += " | no archived bar (the archive is ASX only)"
        w(line)

    w("")
    w("## What-if: cut at -0.5R adverse (2 Nov list #5; report only, before slippage)")
    for label, tag in (("all cycles", None), (HC41["tag"], HC41["tag"]), (HC42["tag"], HC42["tag"])):
        m = mae_cut_whatif(closed, tag=tag)
        w(f"  {label:10} rules n={m['n']:<3} reached -0.5R {m['hit']:<3} (winners among them "
          f"{m['winners_cut']}) | rules {m['rules_total']:+.2f}R -> cut {m['cut_total']:+.2f}R")
        for mk, b in m["by_market"].items():
            w(f"    {mk:7} n={b['n']:<3} hit {b['hit']:<3} | {b['rules_total']:+.2f}R -> "
              f"{b['cut_total']:+.2f}R")

    w("")
    today = book_today(opn, closed)
    w(f"## R per slot-month (2 Nov list #6; the replay's pass metric; book day {today})")
    for tag in sorted({r.get("cycle") for r in closed} | {r.get("cycle") for r in opn}, key=str):
        cr = [r for r in closed if r.get("cycle") == tag and is_rules(r)]
        op = [r for r in opn if r.get("cycle") == tag]
        a, b = r_per_slot_month(cr), r_per_slot_month(cr + op, today)
        if not (a["n"] or b["n"]):
            continue
        ra = "-" if a["r_per_slot_month"] is None else f"{a['r_per_slot_month']:+.4f}"
        rb = "-" if b["r_per_slot_month"] is None else f"{b['r_per_slot_month']:+.4f}"
        w(f"  cycle {str(tag):6} rules closes n={a['n']:<3} {ra} R/slot-month | with "
          f"{len(op)} open at today's marks {rb}")
    h1 = [r for r in closed if r.get("cycle") == HC41["tag"] and is_rules(r)]
    for mk, rows in sorted(group(h1, lambda r: r.get("market")).items(), key=lambda kv: str(kv[0])):
        v = r_per_slot_month(rows)["r_per_slot_month"]
        w(f"    {HC41['tag']} {str(mk):7} n={len(rows):<3} "
          f"{'-' if v is None else f'{v:+.4f}'} R/slot-month")

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
