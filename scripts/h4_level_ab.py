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


def _classify(before: dict, after: dict) -> str:
    """One word for what the switch would do to this name."""
    if before["setup"] != after["setup"]:
        return "appears" if after["setup"] else "disappears"
    if not before["setup"]:
        return "same"
    if before["dir"] != after["dir"]:
        return "flips"
    if before["grade"] != after["grade"]:
        return "regrades"
    if before["tf"] != after["tf"] or before["armed"] != after["armed"]:
        return "shifts"
    return "same"


TRADEABLE = ("A+", "A")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="A/B the H4 level: daily proxy vs a real 4H 200-SMA")
    ap.add_argument("--market", default="asx", choices=("asx", "nasdaq"))
    ap.add_argument("--symbols", help="comma list (yfinance tickers), overrides --market")
    ap.add_argument("--limit", type=int, default=0, help="0 = the whole universe")
    ap.add_argument("--chunk", type=int, default=150,
                    help="symbols per download batch — keeps hourly frames out of memory")
    a = ap.parse_args(argv)

    if a.symbols:
        tickers = [s.strip() for s in a.symbols.split(",") if s.strip()]
        label = "custom"
    else:
        uni = load_universe(a.market, full=True)
        if a.limit:
            uni = uni[: a.limit]
        tickers = [u["yf"] for u in uni]
        label = a.market

    print("=" * 96)
    print(f"H4 LEVEL A/B — {label.upper()}: today's DAILY-200 stand-in vs a REAL 4H 200-SMA")
    print("=" * 96)
    print("Only the H4 level changes. The weekly and 3-day levels are identical in both runs,")
    print("so any name resting on a weekly or 3-day level is untouched by construction.\n")
    print(f"{len(tickers)} symbols, in batches of {a.chunk}\n")

    rows = []          # one small dict per symbol — frames are never kept
    nodata = 0
    for i in range(0, len(tickers), a.chunk):
        batch = tickers[i:i + a.chunk]
        try:
            daily = download(batch, period=config.VIVEK_DATA_PERIOD, interval="1d")
            hourly = download(batch, period=config.VIVEK_H4_PERIOD,
                              interval=config.VIVEK_H4_INTERVAL)
        except Exception as exc:                       # noqa: BLE001
            print(f"  batch {i // a.chunk + 1}: download failed ({type(exc).__name__}) - skipped")
            nodata += len(batch)
            continue
        for t in batch:
            df = daily.get(t)
            h4 = true_h4_sma(hourly.get(t)) if df is not None else None
            if df is None or df.empty or h4 is None:
                nodata += 1
                continue
            before, after = outcome(df), outcome(df, h4)
            rows.append({"t": t, "b": before, "a": after, "k": _classify(before, after)})
        del daily, hourly
        done = min(i + a.chunk, len(tickers))
        print(f"  ... {done}/{len(tickers)} compared ({len(rows)} usable, {nodata} skipped)",
              flush=True)

    n = len(rows)
    if not n:
        print("\nNothing comparable — no data.")
        return 0

    kinds = {}
    for r in rows:
        kinds[r["k"]] = kinds.get(r["k"], 0) + 1
    changed = n - kinds.get("same", 0)

    print("\n" + "=" * 96)
    print("WHAT WOULD CHANGE")
    print("=" * 96)
    print(f"{'outcome':14} {'names':>7}  {'share':>7}   meaning")
    order = [("same", "identical before and after"),
             ("disappears", "a setup you see today would no longer exist"),
             ("appears", "a setup you cannot see today would appear"),
             ("flips", "same name, opposite direction"),
             ("regrades", "same direction, different grade"),
             ("shifts", "same call, different level or armed state")]
    for k, meaning in order:
        c = kinds.get(k, 0)
        print(f"{k:14} {c:>7}  {100*c/n:>6.1f}%   {meaning}")
    print(f"\n{n} names compared, {nodata} skipped for data. {changed} would change "
          f"({100*changed/n:.1f}%).")

    # The set the owner actually trades off: today's A+/A armed names.
    today_set = [r for r in rows
                 if r["b"]["setup"] and r["b"]["armed"] and r["b"]["grade"] in TRADEABLE]
    kept = [r for r in today_set if r["a"]["setup"] and r["a"]["armed"]
            and r["a"]["grade"] in TRADEABLE and r["a"]["dir"] == r["b"]["dir"]]
    lost = [r for r in today_set if r not in kept]
    new_set = [r for r in rows
               if r["a"]["setup"] and r["a"]["armed"] and r["a"]["grade"] in TRADEABLE
               and not (r["b"]["setup"] and r["b"]["armed"] and r["b"]["grade"] in TRADEABLE)]

    print("\n" + "=" * 96)
    print("YOUR TRADEABLE DECK (A+/A and armed) — the list you actually work from")
    print("=" * 96)
    if today_set:
        print(f"  today               {len(today_set):>5}")
        print(f"  survive unchanged   {len(kept):>5}  ({100*len(kept)/len(today_set):.0f}%)")
        print(f"  lost or altered     {len(lost):>5}  ({100*len(lost)/len(today_set):.0f}%)")
    print(f"  newly qualifying    {len(new_set):>5}")
    if today_set:
        after_n = len(kept) + len(new_set)
        print(f"  deck size           {len(today_set)} -> {after_n}")

    # Group the losses by WHY, which is the part that decides whether the change
    # is an improvement or a demolition.
    by_level = {}
    for r in today_set:
        by_level.setdefault(r["b"]["tf"], {"n": 0, "lost": 0})
        by_level[r["b"]["tf"]]["n"] += 1
        if r in lost:
            by_level[r["b"]["tf"]]["lost"] += 1
    print(f"\n  {'level today':14} {'on deck':>8} {'lost':>6}   (weekly/3d cannot move — only h4 can)")
    for tf, d in sorted(by_level.items()):
        print(f"  {tf:14} {d['n']:>8} {d['lost']:>6}")

    def show(title, lst, cap=40):
        if not lst:
            return
        print(f"\n{title} ({len(lst)}):")
        for r in lst[:cap]:
            b, aa = r["b"], r["a"]
            bs = f"{b['grade']} {b['dir'][:5]} {b['tf']}" if b["setup"] else "no setup"
            as_ = f"{aa['grade']} {aa['dir'][:5]} {aa['tf']}" if aa["setup"] else "no setup"
            print(f"  {r['t']:12} {bs:>18}  ->  {as_:<18}")
        if len(lst) > cap:
            print(f"  ... and {len(lst) - cap} more")

    show("LOST from the deck", lost)
    show("NEW on the deck", new_set)
    show("DIRECTION FLIPS (the ones to look at hardest)",
         [r for r in rows if r["k"] == "flips"])

    print("\nNothing was written. This is a measurement, not a change.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
