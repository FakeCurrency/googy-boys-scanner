"""Command-line entry point.

Examples:
    python -m scanner.run                      # scan every configured market
    python -m scanner.run --market asx         # ASX only
    python -m scanner.run --market asx --market nasdaq
    python -m scanner.run --limit 40           # small universe (quick test)
"""

import argparse
import json
import pathlib

from . import config, output, pulse, scan
from .data import download
from .universe import load_universe

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
        "--journal", action="store_true",
        help="after scanning, update the paper-trade journal (forward test)",
    )
    parser.add_argument(
        "--alert", action="store_true",
        help="after scanning, email new A+/A setups (needs GBS_SMTP_* env vars)",
    )
    parser.add_argument(
        "--no-reversal", action="store_true",
        help="skip the Reversals scan (only run the Fib pullback scan)",
    )
    parser.add_argument(
        "--no-spec", action="store_true",
        help="skip the Specs (volume-spike breakout) scan",
    )
    parser.add_argument(
        "--no-short", action="store_true",
        help="skip the Shorts (bearish pullback) scan",
    )
    parser.add_argument(
        "--no-googy", action="store_true",
        help="skip the Googy consolidation breakout scan",
    )
    parser.add_argument(
        "--out", default=str(DEFAULT_OUT),
        help="directory to write <market>.json into",
    )
    args = parser.parse_args()

    def tradeable(payload):
        return sum(1 for r in payload["results"] if r["grade"] in config.TRADEABLE_GRADES)

    # page-market -> (frames, universe) so the sector page can show real
    # stock-level winners/losers & rotation depth (ASX scan -> "asx" page,
    # NASDAQ scan -> "us" page).
    mover_inputs: dict[str, tuple] = {}
    MOVER_MIN_DVOL = {"asx": 1_000_000, "us": 10_000_000}

    markets = args.market or list(config.MARKETS)
    for market_key in markets:
        market = config.MARKETS[market_key]
        print(f"Scanning {market.label} ...", flush=True)
        try:
            universe = load_universe(market_key, full=not args.curated)
            if args.limit:
                universe = universe[:args.limit]
            print(f"  downloading {len(universe)} tickers ...", flush=True)
            frames = download([u["yf"] for u in universe])
            # Guard: a fully-empty download means the data source was blocked
            # (e.g. Yahoo 403/429), not a genuine "no setups" day. Writing now
            # would clobber yesterday's good JSON, so skip this market instead.
            if not frames:
                print(f"  no data for {market_key} (download blocked/empty) — "
                      f"keeping existing JSON", flush=True)
                continue
            pulse_data = pulse.fetch()
            if market_key in ("asx", "nasdaq"):
                mover_inputs["us" if market_key == "nasdaq" else "asx"] = (frames, universe)

            # 1) Fibonacci pullback scan -> <market>.json
            pb = scan.scan_market(market_key, out_root=args.out, frames=frames,
                                  pulse_data=pulse_data, universe=universe, progress=False)
            output.write(pb, args.out)
            print(f"  pullbacks: {len(pb['results'])} setups ({tradeable(pb)} A+/A)")

            # 2) Reversal / base-breakout scan -> <market>_reversal.json
            if not args.no_reversal:
                rv = scan.scan_reversal_market(market_key, out_root=args.out, frames=frames,
                                               pulse_data=pulse_data, universe=universe, progress=False)
                output.write(rv, args.out, name=f"{market_key}_reversal")
                print(f"  reversals: {len(rv['results'])} setups ({tradeable(rv)} A+/A)")

            # 3) Specs / volume-spike breakout scan -> <market>_spec.json
            if not args.no_spec:
                sp = scan.scan_spec_market(market_key, out_root=args.out, frames=frames,
                                           pulse_data=pulse_data, universe=universe, progress=False)
                output.write(sp, args.out, name=f"{market_key}_spec")
                print(f"  specs: {len(sp['results'])} setups ({tradeable(sp)} A+/A)")

            # 4) Shorts / bearish pullback scan -> <market>_short.json
            if not args.no_short:
                sh = scan.scan_short_market(market_key, out_root=args.out, frames=frames,
                                            pulse_data=pulse_data, universe=universe, progress=False)
                output.write(sh, args.out, name=f"{market_key}_short")
                print(f"  shorts: {len(sh['results'])} setups ({tradeable(sh)} A+/A)")

            # 5) Googy consolidation breakout scan -> <market>_googy.json
            if not args.no_googy:
                gg = scan.scan_googy_market(market_key, out_root=args.out, frames=frames,
                                            pulse_data=pulse_data, universe=universe, progress=False)
                output.write(gg, args.out, name=f"{market_key}_googy")
                print(f"  googy: {len(gg['results'])} setups ({tradeable(gg)} A+/A)")
        except Exception as e:
            print(f"  ERROR scanning {market_key}: {e}", flush=True)

    # Sector & index dashboard (ASX + US) with an auto market read.
    from . import sectors as _sectors
    print("Fetching sector dashboard ...", flush=True)
    sec = _sectors.fetch()
    for page_key, (frames, universe) in mover_inputs.items():
        if page_key in sec["markets"]:
            _sectors.enrich(sec["markets"][page_key], frames, universe,
                            MOVER_MIN_DVOL.get(page_key, 1_000_000),
                            market_key=page_key)
    (pathlib.Path(args.out) / "sectors.json").write_text(json.dumps(sec, indent=2), encoding="utf-8")
    print(f"  sectors: ASX {len(sec['markets']['asx']['sectors'])} sectors | "
          f"US {len(sec['markets']['us']['sectors'])} sectors")

    if args.journal:
        from . import journal
        print("Updating paper-trade journal ...", flush=True)
        j = journal._load()
        for market_key in markets:
            j = journal.update_market(market_key, j)
        journal._save(j)
        s = journal.summarize(j)
        sl, ss = s["longs"], s["shorts"]
        print(f"  journal longs:  {sl['open']} open | {sl['closed']} closed | "
              f"win {sl['win_rate']}% | realised {sl['total_r']:+.1f}R")
        print(f"  journal shorts: {ss['open']} open | {ss['closed']} closed | "
              f"win {ss['win_rate']}% | realised {ss['total_r']:+.1f}R")

    if args.alert:
        from . import alerts
        print("Checking for new A+/A setups to alert ...", flush=True)
        alerts.run(markets)


if __name__ == "__main__":
    main()
