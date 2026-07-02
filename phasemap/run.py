"""PhaseMap CLI — nightly scan entry point.

Usage:
    python -m phasemap.run                      # full ASX universe (yfinance prototype)
    python -m phasemap.run --limit 50           # first 50 tickers
    python -m phasemap.run --tickers BHP,CBA    # specific tickers
    python -m phasemap.run --out path/to/dir    # override output dir
"""

import argparse
import csv
import datetime
import os
import sys
import zoneinfo

from phasemap.config import CONFIG, PRODUCT_NAME, RULESET_VERSION
from phasemap.data.provider import YFinanceProvider
from phasemap.engine.scanner import scan_ticker, sort_records
from phasemap.narrate.renderer import render
from phasemap.output.writer import build_snapshot, write_snapshot

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASX_UNIVERSE_CSV = os.path.join(REPO_ROOT, "data_universe", "asx_tickers.csv")


def load_universe(path: str = ASX_UNIVERSE_CSV) -> list:
    """Full ASX-listed directory (~2,000 names incl. microcaps) via the
    repo's universe loader; falls back to the bundled curated CSV."""
    try:
        from scanner.universe import load_universe as repo_universe
        items = repo_universe("asx", full=True)
        if items:
            return [it["symbol"] for it in items]
    except Exception:
        pass
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [row["symbol"].strip() for row in csv.DictReader(f)
                if row.get("symbol", "").strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog=f"{PRODUCT_NAME} scanner")
    ap.add_argument("--tickers", help="comma-separated tickers (no .AX suffix)")
    ap.add_argument("--limit", type=int, help="scan only the first N of the universe")
    ap.add_argument("--out", help="output directory override")
    ap.add_argument("--period", default="2y", help="history period for yfinance")
    args = ap.parse_args(argv)

    tickers = (args.tickers.split(",") if args.tickers else load_universe())
    if args.limit:
        tickers = tickers[:args.limit]

    provider = YFinanceProvider(tickers, period=args.period)
    provider.fetch_all()

    results = []
    for t in provider.universe():
        df = provider.get_daily_bars(t)
        if df is None:
            continue
        for rec, _eng in scan_ticker(t, df):
            rec["narration"] = render(rec)
            results.append(rec)

    tz = zoneinfo.ZoneInfo(CONFIG.timezone)
    run_date = datetime.datetime.now(tz).date().isoformat()
    snap = build_snapshot(run_date, universe_size=len(tickers),
                          results=sort_records(results))
    out_dir = args.out or os.path.join(REPO_ROOT, CONFIG.output_dir)
    path = write_snapshot(snap, out_dir)

    by_state = {}
    for r in results:
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1
    print(f"{PRODUCT_NAME} v{RULESET_VERSION} — {run_date}")
    print(f"universe: {len(tickers)}  results: {len(results)}  states: {by_state}")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
