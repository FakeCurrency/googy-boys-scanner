#!/usr/bin/env python3
"""BEFORE/AFTER: what happens if the engine's "H4" level becomes a REAL 4H 200-SMA?

Owner, 2026-09-19, after the 4H chart plans shipped: "Show me the before and
after on a handful of names."

THE QUESTION. scanner/vivek.py's evaluate() ranks three higher-timeframe 200-SMA
levels -- weekly, 3-day and "h4" -- and trades the strongest one in play. The
"h4" entry has always been the DAILY 200 standing in for a 4H 200, because the
scan only ever downloaded daily bars. Now that hourly bars are being fetched
anyway (for the 4H chart plans), that stand-in could become the real thing.

WHY IT IS NOT A FREE CHANGE. The level sets the direction (above it = long,
below = short), the distance test that decides whether a name is in play at all,
the reaction type, the score and therefore the grade. A different H4 level can
add names, drop names, flip a long to a short and move a grade. That is the
owner's edge, so this measures it rather than arguing about it.

HOW IT MEASURES. It runs the REAL engine twice per symbol -- evaluate(df) as
shipped, then evaluate(df, h4_sma=<true 4H 200-SMA>) -- and puts the two
side by side, through the same score_and_grade and gate the scan uses. Nothing
is written and no config changes; the printed table IS the deliverable.

Runs on a runner: a cloud session's proxy refuses Yahoo outright.

  python3 scripts/h4_level_ab.py --market asx --limit 12
  python3 scripts/h4_level_ab.py --symbols ENR.AX,NOL.AX,FAL.AX,ON,MDLZ
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

# Run straight from a checkout (`python3 scripts/h4_level_ab.py`) — the repo root
# is not on sys.path there. Same bootstrap as scripts/lens_fill_confluence.py.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner import config, vivek                      # noqa: E402
from scanner.data import download                      # noqa: E402
from scanner.indicators import sma                     # noqa: E402
from scanner.universe import load_universe             # noqa: E402


def true_h4_sma(df_1h) -> float | None:
    """The real 4H 200-SMA, from hourly bars, bucketed exactly as the chart and
    the 4H plan do (epoch-anchored 4h)."""
    if df_1h is None or df_1h.empty:
        return None
    h4 = vivek._resample_4h_ohlc(df_1h)
    if h4 is None or len(h4) < config.VIVEK_SMA:
        return None                      # too short for a REAL 200 — never proxy here
    v = float(sma(h4["Close"], config.VIVEK_SMA).iloc[-1])
    return v if np.isfinite(v) and v > 0 else None


def outcome(df, h4=None) -> dict:
    """What the scan would conclude for this frame: level, direction, grade."""
    sig = vivek.evaluate(df) if h4 is None else vivek.evaluate(df, h4_sma=h4)
    if not sig:
        return {"setup": False}
    points, raw_grade, _fired = vivek.score_and_grade(sig)
    plans = vivek.build_plans(df, sig)
    gate_tf = next((tf for tf in ("1W", "3D", "1D")
                    if (plans.get(tf) or {}).get("armed")), None)
    hp = plans.get(gate_tf) or plans.get("1D") or {}
    graded, _why = vivek.gate_grade(raw_grade, sig, float(hp.get("rr") or 0),
                                    armed=gate_tf is not None)
    return {"setup": True, "tf": sig["level_tf"], "level": sig["level"],
            "dir": sig["direction"], "reaction": sig["reaction"],
            "at_level": sig["at_level"], "points": points,
            "grade": graded, "armed": gate_tf is not None, "armed_tf": gate_tf}


def fmt(o: dict) -> str:
    if not o["setup"]:
        return f"{'no setup':>28}"
    return (f"{str(o['grade'] or '-'):>5} {o['dir'][:5]:>5} {o['tf']:>6} "
            f"{o['level']:>9.4f} {o['points']:>3}pts {'armed' if o['armed'] else 'watch':>5}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="A/B the H4 level: daily proxy vs a real 4H 200-SMA")
    ap.add_argument("--market", default="asx", choices=("asx", "nasdaq"))
    ap.add_argument("--symbols", help="comma list (yfinance tickers), overrides --market")
    ap.add_argument("--limit", type=int, default=12)
    a = ap.parse_args(argv)

    if a.symbols:
        tickers = [s.strip() for s in a.symbols.split(",") if s.strip()]
    else:
        uni = load_universe(a.market, full=True)[: a.limit]
        tickers = [u["yf"] for u in uni]

    print("=" * 100)
    print("H4 LEVEL A/B — today's DAILY-200 stand-in vs a REAL 4H 200-SMA")
    print("=" * 100)
    print("BEFORE = what the scanner does today.  AFTER = if the h4 level became a true 4H 200.")
    print("Only the H4 level changes; the weekly and 3-day levels are identical in both runs.\n")

    daily = download(tickers, period=config.VIVEK_DATA_PERIOD, interval="1d")
    hourly = download(tickers, period=config.VIVEK_H4_PERIOD,
                      interval=config.VIVEK_H4_INTERVAL)

    hdr = f"{'symbol':10} {'BEFORE (grade dir tf level pts state)':>40}   {'AFTER':>40}   verdict"
    print(hdr)
    print("-" * len(hdr))

    changed = same = nodata = 0
    flips, added, dropped, regrades = [], [], [], []
    for t in tickers:
        df = daily.get(t)
        if df is None or df.empty:
            print(f"{t:10} {'(no daily data)':>40}")
            nodata += 1
            continue
        h4 = true_h4_sma(hourly.get(t))
        if h4 is None:
            print(f"{t:10} {'(no 4H 200 available — stays on the proxy)':>40}")
            nodata += 1
            continue
        before, after = outcome(df), outcome(df, h4)

        note = []
        if before["setup"] != after["setup"]:
            note.append("APPEARS" if after["setup"] else "DISAPPEARS")
            (added if after["setup"] else dropped).append(t)
        elif before["setup"]:
            if before["dir"] != after["dir"]:
                note.append(f"DIRECTION {before['dir']}->{after['dir']}")
                flips.append(t)
            if before["grade"] != after["grade"]:
                note.append(f"GRADE {before['grade']}->{after['grade']}")
                regrades.append(t)
            if before["tf"] != after["tf"]:
                note.append(f"level {before['tf']}->{after['tf']}")
            if before["armed"] != after["armed"]:
                note.append(f"{'armed' if after['armed'] else 'disarmed'}")
        if note:
            changed += 1
        else:
            same += 1
        print(f"{t:10} {fmt(before):>40}   {fmt(after):>40}   {', '.join(note) or 'no change'}")

    n = changed + same
    print("\n" + "=" * 100)
    print(f"{n} names compared: {same} unchanged, {changed} changed  ({nodata} skipped for data)")
    if n:
        print(f"  {100*changed/n:.0f}% of the names the owner sees would be affected")
    for label, lst in (("direction flipped", flips), ("newly appear", added),
                       ("disappear", dropped), ("grade changed", regrades)):
        if lst:
            print(f"  {label}: {', '.join(lst)}")
    print("\nNothing was written. This is a measurement, not a change.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
