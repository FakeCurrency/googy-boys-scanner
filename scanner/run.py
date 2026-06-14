"""Command-line entry point.

Examples:
    python -m scanner.run                      # scan every configured market
    python -m scanner.run --market asx         # ASX only
    python -m scanner.run --market asx --market nasdaq
    python -m scanner.run --limit 40           # small universe (quick test)
"""

import argparse
import pathlib

from . import config, output, scan

DEFAULT_OUT = pathlib.Path(__file__).resolve().parents[1] / "public" / "data"


def main() -> None:
    parser = argparse.ArgumentParser(description="Fibonacci-EMA market scanner")
    parser.add_argument(
        "--market", action="append", choices=list(config.MARKETS),
        help="market to scan (repeatable); default = all markets",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="cap the universe size (handy for a quick test run)",
    )
    parser.add_argument(
        "--curated", action="store_true",
        help="use the smaller bundled ASX list instead of the full ~2,000-name directory",
    )
    parser.add_argument(
        "--out", default=str(DEFAULT_OUT),
        help="directory to write <market>.json into",
    )
    args = parser.parse_args()

    markets = args.market or list(config.MARKETS)
    for market_key in markets:
        print(f"Scanning {config.MARKETS[market_key].label} ...", flush=True)
        payload = scan.scan_market(market_key, limit=args.limit, full=not args.curated)
        path = output.write(payload, args.out)
        tradeable = sum(1 for r in payload["results"]
                        if r["grade"] in config.TRADEABLE_GRADES)
        print(f"  {len(payload['results'])} setups "
              f"({tradeable} A+/A) from {payload['scanned']} scanned -> {path}")


if __name__ == "__main__":
    main()
