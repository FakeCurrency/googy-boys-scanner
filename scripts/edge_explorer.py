#!/usr/bin/env python3
"""Slice the backtest every way that matters, and say which cuts actually help.

Owner, 2026-09-20: "continue with expanding and playing around with filtering
whilst back testing amongst every trade we have back tested ... I want to c what
we're working with ... be creative and see. Provide me a proper table."

Runs against the PUBLISHED report's own trade list, so it needs no re-run and no
network: re-run it after any backtest and it re-reads whatever landed.

WHAT IT CAN AND CANNOT ANSWER, stated up front because the difference matters:

  ENTRY filters (timeframe, trigger, grade, level, market, structure) are exact.
  Each trade already carries the attributes, so filtering is just counting.

  STOP WIDTH is approximated from `mae_r`, the worst excursion each trade saw
  against itself. If a trade's MAE reached -X then a stop at -X would have
  caught it, so the approximation is sound in that direction. What it CANNOT
  see is the path: a trade stopped at -0.5R might have gone on to +3R, and this
  counts that as a -0.5R loss, which is correct, versus a trade that dipped to
  -0.4R and recovered, which it leaves alone, also correct. What it cannot model
  is intrabar order on the bar the stop is hit. Treat it as a strong indication,
  not a measurement.

  EXIT MANAGEMENT (when to move to breakeven, scale-out fractions, time stops)
  is NOT answerable here and the script refuses to guess. Those need the price
  path replayed per trade, which the published report does not carry. Note that
  moving the stop to breakeven at TP1 is ALREADY the shipped rule
  (vivek_bot.manage_position), so it is the baseline, not a variant.

  python3 scripts/edge_explorer.py
  python3 scripts/edge_explorer.py --report public/data/vivek_backtest.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "public" / "data" / "vivek_backtest_longonly.json"


# ── metrics ───────────────────────────────────────────────────────────────────

def stat(trades: list[dict]) -> dict | None:
    n = len(trades)
    if not n:
        return None
    rs = [float(t.get("realized_r") or 0.0) for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [-r for r in rs if r < 0]
    gross_w, gross_l = sum(wins), sum(losses)
    return {
        "n": n,
        "win": 100.0 * len(wins) / n,
        "avg": sum(rs) / n,
        "tot": sum(rs),
        "pf": (gross_w / gross_l) if gross_l else float("inf"),
        "avg_win": (gross_w / len(wins)) if wins else 0.0,
        "avg_loss": (-gross_l / len(losses)) if losses else 0.0,
    }


def line(label: str, s: dict | None, width: int = 30) -> str:
    if not s:
        return f"  {label:<{width}}  {'—':>6}"
    pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    return (f"  {label:<{width}}  {s['n']:>6}  {s['win']:>5.1f}%  {s['avg']:>+7.3f}  "
            f"{s['tot']:>+8.1f}  {pf:>5}  {s['avg_win']:>+6.2f}  {s['avg_loss']:>+6.2f}")


HEAD = (f"  {'cohort':<30}  {'n':>6}  {'win':>6}  {'avg R':>7}  {'tot R':>8}  "
        f"{'PF':>5}  {'avg W':>6}  {'avg L':>6}")


def section(title: str) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)
    print(HEAD)
    print("  " + "-" * 96)


# ── the high-conviction rule, and the widened version under consideration ─────

def hc(t: dict, triggers: set[str]) -> bool:
    if (t.get("timeframe") or "") != "1W":
        return False
    if (t.get("entry_type") or "") not in triggers:
        return False
    if (t.get("grade") or "") in ("A+", "A"):
        return True
    try:
        return float(t.get("structural_tps") or 0) >= 2
    except (TypeError, ValueError):
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Explore backtest filters")
    ap.add_argument("--report", default=str(DEFAULT))
    ap.add_argument("--min-n", type=int, default=60,
                    help="smallest cohort worth drawing a conclusion from")
    a = ap.parse_args(argv)

    rep = json.loads(pathlib.Path(a.report).read_text())
    all_tr = rep.get("trades") or []
    tr = [t for t in all_tr if (t.get("direction") or "") == "long"]
    p = rep.get("params") or {}

    print("=" * 100)
    print("EDGE EXPLORER — every long trade in the published replay")
    print("=" * 100)
    print(f"report     : {a.report}")
    print(f"run        : {rep.get('generated_at')}  status={rep.get('status')}")
    print(f"params     : limit={p.get('limit')}/market  period={p.get('period')}  "
          f"long_only={p.get('long_only')}")
    print(f"trades     : {len(all_tr)} total, {len(tr)} long")
    print(f"min cohort : {a.min_n} (smaller cohorts are printed but not recommended on)")

    base = stat(tr)
    section("0 · BASELINE — every long trade")
    print(line("all longs", base))

    # ── 1. one dimension at a time ───────────────────────────────────────────
    section("1 · ONE FILTER AT A TIME")
    for dim, vals in (("timeframe", ["1W", "3D", "1D"]),
                      ("entry_type", ["reclaim", "break", "retest"]),
                      ("grade", ["A+", "A"]),
                      ("level_tf", sorted({t.get("level_tf") for t in tr if t.get("level_tf")})),
                      ("market", sorted({t.get("market") for t in tr if t.get("market")}))):
        for v in vals:
            print(line(f"{dim} = {v}", stat([t for t in tr if t.get(dim) == v])))
        print("  " + "-" * 96)

    print(line("structural TPs >= 2", stat([t for t in tr if (t.get("structural_tps") or 0) >= 2])))
    print(line("structural TPs < 2", stat([t for t in tr if (t.get("structural_tps") or 0) < 2])))

    # ── 2. timeframe x trigger, the cell that matters ────────────────────────
    section("2 · TIMEFRAME x TRIGGER — where the edge actually lives")
    for tf in ("1W", "3D", "1D"):
        for et in ("reclaim", "break", "retest"):
            print(line(f"{tf} + {et}",
                       stat([t for t in tr if t.get("timeframe") == tf and t.get("entry_type") == et])))
        print("  " + "-" * 96)

    # ── 3. the high-conviction definitions ───────────────────────────────────
    section("3 · HIGH CONVICTION — current vs widened")
    print(line("current   1W reclaim", stat([t for t in tr if hc(t, {"reclaim"})])))
    print(line("widened   1W reclaim+break", stat([t for t in tr if hc(t, {"reclaim", "break"})])))
    print(line("  (1W break alone)", stat([t for t in tr if hc(t, {"break"})])))
    print(line("if retest added too", stat([t for t in tr if hc(t, {"reclaim", "break", "retest"})])))
    print(line("everything else (long)", stat([t for t in tr if not hc(t, {"reclaim", "break"})])))

    # ── 4. high conviction, broken down ──────────────────────────────────────
    section("4 · WIDENED HIGH CONVICTION, BROKEN DOWN — where it works and where it does not")
    hcs = [t for t in tr if hc(t, {"reclaim", "break"})]
    for dim in ("market", "grade", "level_tf"):
        for v in sorted({t.get(dim) for t in hcs if t.get(dim)}):
            print(line(f"{dim} = {v}", stat([t for t in hcs if t.get(dim) == v])))
        print("  " + "-" * 96)
    print(line("exit: target", stat([t for t in hcs if t.get("exit_reason") == "target"])))
    print(line("exit: trail (past TP1)", stat([t for t in hcs if t.get("exit_reason") == "trail"])))
    print(line("exit: stop (never hit TP1)", stat([t for t in hcs if t.get("exit_reason") == "stop"])))
    print(line("exit: eod/other", stat([t for t in hcs
                                        if t.get("exit_reason") not in ("target", "trail", "stop")])))

    # ── 5. combination search ────────────────────────────────────────────────
    section(f"5 · COMBINATION SEARCH — best cuts with at least {a.min_n} trades")
    combos = []
    tfs = [None, "1W", "3D", ("1W", "3D")]
    ets = [None, "reclaim", ("reclaim", "break")]
    grades = [None, "A+", "A"]
    mkts = [None] + sorted({t.get("market") for t in tr if t.get("market")})
    for tf, et, g, mk in itertools.product(tfs, ets, grades, mkts):
        sel = tr
        if tf:
            want = (tf,) if isinstance(tf, str) else tf
            sel = [t for t in sel if t.get("timeframe") in want]
        if et:
            want = (et,) if isinstance(et, str) else et
            sel = [t for t in sel if t.get("entry_type") in want]
        if g:
            sel = [t for t in sel if t.get("grade") == g]
        if mk:
            sel = [t for t in sel if t.get("market") == mk]
        s = stat(sel)
        if s and s["n"] >= a.min_n:
            desc = " + ".join(filter(None, [
                ("/".join(tf) if not isinstance(tf, str) else tf) if tf else "",
                ("/".join(et) if not isinstance(et, str) else et) if et else "",
                g or "", mk or ""])) or "all longs"
            combos.append((s["avg"], desc, s))
    combos.sort(reverse=True, key=lambda x: x[0])
    print("  TOP 12 by expectancy")
    for _, desc, s in combos[:12]:
        print(line(desc, s))
    print("  " + "-" * 96)
    print("  WORST 6 by expectancy")
    for _, desc, s in combos[-6:]:
        print(line(desc, s))

    # ── 6. the stop study ────────────────────────────────────────────────────
    section("6 · STOP WIDTH — what a tighter initial stop would have done (MAE-derived)")
    print("  Each trade is re-scored: if its worst excursion reached the tighter stop it")
    print("  becomes that loss, otherwise it keeps its real result. Ignores intrabar order,")
    print("  so read it as a strong indication rather than a measurement.")
    print("  " + "-" * 96)
    for pop_name, pop in (("all longs", tr), ("widened high conviction", hcs)):
        print(f"  --- {pop_name} ---")
        for cut in (None, -2.0, -1.5, -1.0, -0.75, -0.5):
            if cut is None:
                print(line("as traded", stat(pop)))
                continue
            rescored, changed = [], 0
            for t in pop:
                mae = t.get("mae_r")
                r = float(t.get("realized_r") or 0.0)
                try:
                    reached = mae is not None and float(mae) <= cut
                except (TypeError, ValueError):
                    reached = False
                # A tighter stop can only make an outcome WORSE. A trade that
                # already finished at or below `cut` keeps its real result,
                # slippage included. The first version of this re-scored those
                # to exactly `cut` and so deleted genuine gap losses -- at -1.0R
                # that was 3,304 already-stopped trades being handed back a
                # median 0.09R each, and the "improvement" was entirely that.
                if reached and r > cut:
                    rescored.append({"realized_r": cut})
                    changed += 1
                else:
                    rescored.append({"realized_r": r})
            s = stat(rescored)
            lbl = f"stop at {cut:+.2f}R ({changed} changed)"
            print(line(lbl, s))
        print("  " + "-" * 96)

    # ── 6b. slippage past the stop — a real cost the above made me look at ──
    section("6b · SLIPPAGE — what a stop-out actually costs versus its nominal -1R")
    for pop_name, pop in (("all longs", tr), ("widened high conviction", hcs)):
        st_ = [t for t in pop if t.get("exit_reason") == "stop"]
        if not st_:
            continue
        rs = [float(t.get("realized_r") or 0) for t in st_]
        worst = min(rs)
        excess = sum(r + 1.0 for r in rs if r < -1.0)
        print(f"  {pop_name:<28} {len(st_):>6} stop-outs   "
              f"mean {sum(rs)/len(rs):+.3f}R   worst {worst:+.2f}R   "
              f"slippage beyond -1R totals {excess:+.1f}R")
    print("\n  This is the tail a tighter stop cannot fix — the price gapped through it.")
    print("  It is an argument for position COUNT as the risk dial, not stop width.")

    # ── 7. MAE of winners — how much heat a good trade takes ─────────────────
    section("7 · HEAT — how far the WINNERS went against you first")
    wins = [t for t in hcs if float(t.get("realized_r") or 0) > 0]
    for lo, hi in ((0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0), (1.0, 99.0)):
        sel = [t for t in wins if t.get("mae_r") is not None
               and lo <= -float(t["mae_r"]) < hi]
        pct = 100.0 * len(sel) / len(wins) if wins else 0
        print(f"  winners that dipped {lo:.2f}–{hi:.2f}R against them: "
              f"{len(sel):>5}  ({pct:4.1f}% of winners)")
    print("\n  Read with section 6: the deeper the winners' heat, the more a tight stop costs.")

    print("\n" + "=" * 100)
    print("Nothing was written. Re-run after any backtest to re-read the new report.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
