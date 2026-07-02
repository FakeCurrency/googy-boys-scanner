"""PhaseMap backtest CLI.

    python -m phasemap.backtest --market asx --period 5y
    python -m phasemap.backtest --market nasdaq --period 5y --write-stats
    python -m phasemap.backtest --market asx --limit 300      # quick pass

Writes phasemap/backtest/reports/<market>.md and (with --write-stats)
phasemap/backtest/stats/<market>.json, which the nightly scan reads to fill
the narration {stats} slot.
"""

import argparse
import json
import sys

from phasemap.backtest.harness import (buy_hold_baseline, random_baseline,
                                       run_ticker)
from phasemap.backtest.report import write_report, write_stats
from phasemap.config import PRODUCT_NAME, RULESET_VERSION
from phasemap.data.provider import YFinanceProvider
from phasemap.run import load_symbols


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog=f"{PRODUCT_NAME} backtest")
    ap.add_argument("--market", default="asx", choices=["asx", "nasdaq", "crypto"])
    ap.add_argument("--period", default="5y", help="history depth (yfinance range)")
    ap.add_argument("--limit", type=int, help="first N tickers only (quick pass)")
    ap.add_argument("--write-stats", action="store_true",
                    help="also write the {stats} artefact for the nightly scan")
    args = ap.parse_args(argv)

    symbols = load_symbols(args.market)
    if args.limit:
        symbols = dict(sorted(symbols.items())[:args.limit])
    print(f"{PRODUCT_NAME} backtest v{RULESET_VERSION} - {args.market} "
          f"({len(symbols)} tickers, {args.period})")

    provider = YFinanceProvider({t: v["yf"] for t, v in symbols.items()},
                                period=args.period)
    provider.fetch_all()

    frames, signals = {}, []
    for t in provider.universe():
        df = provider.get_daily_bars(t)
        if df is None:
            continue
        frames[t] = df
        signals.extend(run_ticker(t, df, args.market,
                                  volume_is_usd=(args.market == "crypto")))
    signals.sort(key=lambda s: (s["signal_date"], s["ticker"], s["direction"]))

    rnd = random_baseline(frames, len(signals), args.market)
    bh = buy_hold_baseline(frames)
    report = write_report(args.market, signals, rnd, bh,
                          universe_size=len(symbols), period=args.period)
    print(f"signals: {len(signals)}  report: {report}")
    if args.write_stats:
        print("stats:", write_stats(args.market, signals))

    graded = [s for s in signals if s["tier"] in ("A+", "A")]
    hit = sum(1 for s in graded if s.get("t1_hit"))
    print(json.dumps({"signals": len(signals), "graded": len(graded),
                      "t1_hit_pct": round(100 * hit / len(graded), 1) if graded else None},
                     indent=None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
