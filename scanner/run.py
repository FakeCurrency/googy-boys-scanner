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
from .data import download, merge_with_cache
from .universe import load_universe

DEFAULT_OUT = pathlib.Path(__file__).resolve().parents[1] / "public" / "data"


def main() -> None:
    parser = argparse.ArgumentParser(description="Fibonacci-EMA market scanner")
    parser.add_argument(
        "--market", action="append", choices=[*config.MARKETS, "all"],
        help="market to scan: asx | nasdaq | crypto | all (repeatable); default = all",
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
        "--legacy-scans", action="store_true",
        help="also run the retired pullback/reversal/spec/short/googy scans "
             "(the app is VIVEK-only now; these are off by default)",
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

    markets = list(config.MARKETS) if (not args.market or "all" in args.market) else args.market
    for market_key in markets:
        market = config.MARKETS[market_key]
        print(f"Scanning {market.label} ...", flush=True)
        try:
            universe = load_universe(market_key, full=not args.curated)
            if args.limit:
                universe = universe[:args.limit]
            # The app is VIVEK-only: download the deep (5y) history VIVEK needs for
            # a Weekly 200 SMA, ONCE. The retired daily scanners are opt-in
            # (--legacy-scans) and reuse a ~1y tail-slice of the same frames — no
            # second Yahoo pass either way.
            dl_period = config.VIVEK_DATA_PERIOD
            print(f"  downloading {len(universe)} tickers ({dl_period}) ...", flush=True)
            fresh = download([u["yf"] for u in universe], period=dl_period)
            # Reuse last-good cached frames for tickers Yahoo dropped this run, so
            # transient throttling no longer shrinks coverage (the cache refreshes
            # with whatever we DID get). Aging is reported honestly per row.
            deep_frames, cache_stats = merge_with_cache(
                market_key, fresh, [u["yf"] for u in universe])
            cov = 100 * len(deep_frames) // max(len(universe), 1)
            reused_note = f" (+{cache_stats['reused']} cached)" if cache_stats["reused"] else ""
            print(f"  coverage: {len(deep_frames)}/{len(universe)} ({cov}%)  "
                  f"{cache_stats['fresh']} fresh{reused_note}"
                  f"{'  ⚠️ LOW' if cov < 80 and len(universe) > 50 else ''}", flush=True)
            # Guard: nothing fresh AND nothing cached → the source is fully blocked.
            # Skip rather than clobber yesterday's good JSON.
            if not deep_frames:
                print(f"  no data for {market_key} (download blocked/empty) — "
                      f"keeping existing JSON", flush=True)
                continue
            pulse_data = pulse.fetch()
            # Sector movers read recent bars; the deep tail is fine for them.
            frames = {t: df.tail(config.DATA_DAILY_BARS) for t, df in deep_frames.items()}
            if market_key in ("asx", "nasdaq"):
                mover_inputs["us" if market_key == "nasdaq" else "asx"] = (frames, universe)

            # VIVEK (5.0-style 200 SMA reactions) -> <market>_vivek.json — the
            # only scan the app consumes.
            vk = scan.scan_vivek_market(market_key, out_root=args.out,
                                        universe=universe, frames=deep_frames,
                                        pulse_data=pulse_data, progress=False,
                                        from_cache=cache_stats["reused"])
            output.write(vk, args.out, name=f"{market_key}_vivek")
            print(f"  vivek: {len(vk['results'])} setups ({tradeable(vk)} A+/A) · "
                  f"{vk['scanned']}/{vk['universe_size']} scanned")

            # VIVEK-native paper-trade journal: snapshot newly-ARMED A/A+ setups
            # at their trigger price and resolve open trades against the same deep
            # frames (no extra download). Best-effort — never break the scan.
            try:
                from . import vivek_journal
                vj = vivek_journal.update(market_key, vk["results"], deep_frames, universe)
                ov = vj.get("expectancy", {}).get("overall", {})
                print(f"  journal: {len(vj['open'])} open · {len(vj['closed'])} closed"
                      f" · expectancy {ov.get('expectancy_r', 0):+.2f}R (n={ov.get('n', 0)})")
            except Exception as e:
                print(f"  journal: skipped ({e})", flush=True)

            # Retired scanners (pullback/reversal/spec/short/googy) — kept behind
            # an opt-in flag for ad-hoc research; not part of the live app.
            if args.legacy_scans:
                pb = scan.scan_market(market_key, out_root=args.out, frames=frames,
                                      pulse_data=pulse_data, universe=universe, progress=False)
                output.write(pb, args.out)
                rv = scan.scan_reversal_market(market_key, out_root=args.out, frames=frames,
                                               pulse_data=pulse_data, universe=universe, progress=False)
                output.write(rv, args.out, name=f"{market_key}_reversal")
                sp = scan.scan_spec_market(market_key, out_root=args.out, frames=frames,
                                           pulse_data=pulse_data, universe=universe, progress=False)
                output.write(sp, args.out, name=f"{market_key}_spec")
                sh = scan.scan_short_market(market_key, out_root=args.out, frames=frames,
                                            pulse_data=pulse_data, universe=universe, progress=False)
                output.write(sh, args.out, name=f"{market_key}_short")
                gg = scan.scan_googy_market(market_key, out_root=args.out, frames=frames,
                                            pulse_data=pulse_data, universe=universe, progress=False)
                output.write(gg, args.out, name=f"{market_key}_googy")
                print(f"  legacy: pullback {len(pb['results'])} · reversal {len(rv['results'])} · "
                      f"spec {len(sp['results'])} · short {len(sh['results'])} · googy {len(gg['results'])}")
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
