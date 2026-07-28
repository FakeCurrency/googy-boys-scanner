"""Command-line entry point.

Examples:
    python -m scanner.run                      # scan every configured market
    python -m scanner.run --market asx         # ASX only
    python -m scanner.run --market asx --market nasdaq
    python -m scanner.run --limit 40           # small universe (quick test)
"""

import argparse
import datetime as dt
import json
import pathlib

from . import config, output, scan
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
    # --journal and --alert flags removed 2026-07-20 (hygiene pass): both drove
    # RETIRED systems (the old track-record journal and the legacy email
    # alerter, which read scan files the VIVEK-only pipeline no longer writes).
    # scanner/journal.py remains reachable via close_position.yml for the
    # manual swing/scalp pages only.
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
            # PULSE fully retired (UI 2026-07-03; fetch finally removed
            # 2026-07-20, hygiene pass): this was still a Yahoo macro download
            # on EVERY scheduled scan for a feature nobody renders. The payload
            # keeps an empty "pulse" key one release so stale cached JS can't
            # break. Restore by re-importing scanner.pulse and calling fetch().
            pulse_data = []
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

            # Slim per-market companion (2026-07-20, perf): the journal page
            # only needs symbol -> price + grade/dir to mark positions, but was
            # downloading the FULL scan file (ASX ~1.2MB, NASDAQ ~1.6MB) for
            # that map. This is ~5% of the size; the full file stays canonical.
            slim = {
                "schema_version": vk["schema_version"],
                "generated_at": vk["generated_at"],
                "market": market_key,
                "prices": vk["prices"],
                "rows": {r["symbol"]: {"grade": r["grade"],
                                       "grade_raw": r.get("grade_raw"),
                                       "dir": r["dir"],
                                       "headline_tf": r.get("headline_tf")}
                         for r in vk["results"]},
            }
            (pathlib.Path(args.out) / f"{market_key}_prices.json").write_text(
                json.dumps(slim, separators=(",", ":")) + "\n", encoding="utf-8")

            # Track-record journal RETIRED (owner 2026-07-09): it logged EVERY
            # armed A+/A on every timeframe with no position cap — 200+ open
            # trades whose early expectancy read as noise. The bot book
            # (A+ only, a 30-position ceiling across all markets, one per
            # symbol, 3 per sector) is the only track
            # record now. vivek_journal.py stays: the backtester and the bot
            # runner import its trade-management primitives.

            # VIVEK execution/runner layer (Phase 1–2: dry-run + paper book).
            # Gated by VIVEK_BOT_ENABLED — a no-op (and silent) until switched on.
            # It NEVER places a live order in this phase. Best-effort.
            if config.VIVEK_BOT_ENABLED:
                try:
                    from .broker import vivek_run
                    bk = vivek_run.run_market(market_key, vk["results"], deep_frames, universe)
                    bo = sum(1 for p in bk["open"] if p.get("market") == market_key)
                    bs = sum(1 for p in bk["open"]
                             if p.get("market") == market_key and p.get("direction") == "short")
                    print(f"  bot book: {bo} open · {bs} short"
                          f"{' · DRY-RUN' if config.VIVEK_BOT_DRY_RUN else ''}")
                except Exception as e:
                    print(f"  bot book: skipped ({e})", flush=True)
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
    # Keep the enrichment this run could not recompute (see sectors.carry_forward).
    sec_file = pathlib.Path(args.out) / "sectors.json"
    try:
        carried = _sectors.carry_forward(
            sec, json.loads(sec_file.read_text(encoding="utf-8")))
    except Exception:
        carried = 0  # no previous file / unreadable -> publish what we have
    sec_file.write_text(json.dumps(sec, indent=2), encoding="utf-8")
    print(f"  sectors: ASX {len(sec['markets']['asx']['sectors'])} sectors | "
          f"US {len(sec['markets']['us']['sectors'])} sectors"
          + (f" | carried {carried} field(s) forward" if carried else ""))

    # FX honesty: the ASX book is A$ while NASDAQ/crypto are US$ — the journal
    # converts ASX P&L at this rate so combined totals stop mixing currencies
    # at face value (~50% overstatement). Fail-soft: keep the last-good file.
    try:
        fx_frames = download(["AUDUSD=X"], period="5d")
        fx_df = fx_frames.get("AUDUSD=X")
        rate = float(fx_df["Close"].dropna().iloc[-1]) if fx_df is not None else None
        if rate and 0.4 < rate < 1.2:                  # sanity band for AUD/USD
            (pathlib.Path(args.out) / "fx.json").write_text(json.dumps({
                "audusd": round(rate, 4),
                "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }, indent=2) + "\n", encoding="utf-8")
            print(f"  fx: AUDUSD {rate:.4f}")
    except Exception as e:
        print(f"  fx: skipped ({e})", flush=True)

    # Publish the executing bot's ACTUAL rules (scanner/config.py) so the
    # dashboard risk engine reads the same numbers instead of drifting on its
    # own JS defaults (2026-07-09 — the two engines had already diverged: at
    # that time Python risked 0.35%/10 positions while the JS defaults said
    # 0.25%/5. Both numbers below are read live from config, so don't update
    # that parenthetical when the caps move — it is a record of the drift that
    # motivated publishing them, not a statement about today's rules).
    rules = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "scanner/config.py — single source of truth for bot rules",
        "min_grade": config.VIVEK_BOT_MIN_GRADE,
        "min_rr": config.VIVEK_BOT_MIN_RR,
        "skip_entry_types": list(config.VIVEK_BOT_SKIP_ENTRY_TYPES),
        "prefer_tf": config.VIVEK_BOT_PREFER_TF,
        "allow_shorts": config.VIVEK_BOT_ALLOW_SHORTS,
        "max_positions": config.VIVEK_BOT_MAX_POSITIONS,
        "max_open_total": config.VIVEK_BOT_MAX_OPEN_TOTAL,
        # Sizing (2026-07-28): position_notional > 0 means FIXED-NOTIONAL mode
        # and risk_pct is then a derived per-trade figure, not an input. The
        # journal mirrors these, so publishing them is what keeps the page's
        # dollar P&L on the same basis as the executing bot.
        "position_notional": config.VIVEK_BOT_POSITION_NOTIONAL,
        "max_portfolio_notional": config.VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL,
        "account_equity": config.VIVEK_BOT_ACCOUNT_EQUITY,
        "risk_pct": config.VIVEK_BOT_RISK_PCT,
        "leverage": dict(config.VIVEK_BOT_LEVERAGE),
        "max_daily_loss_pct": config.VIVEK_BOT_MAX_DAILY_LOSS_PCT,
        "exclude_funds": config.VIVEK_BOT_EXCLUDE_FUNDS,
        # Tradeability gates (2026-07: quality-of-fill filters, not strategy)
        "min_price": dict(config.VIVEK_BOT_MIN_PRICE),
        "max_stop_pct": config.VIVEK_BOT_MAX_STOP_PCT,
        "min_stop_pct": config.VIVEK_BOT_MIN_STOP_PCT,
        "max_per_sector": config.VIVEK_BOT_MAX_PER_SECTOR,
        "min_adv": dict(config.VIVEK_BOT_MIN_ADV),
        "max_notional_pct_adv": config.VIVEK_BOT_MAX_NOTIONAL_PCT_ADV,
        "max_hold_days": config.VIVEK_BOT_MAX_HOLD_DAYS,
        "reentry_cooldown_days": config.VIVEK_BOT_REENTRY_COOLDOWN_DAYS,
        "max_data_age_days": config.VIVEK_BOT_MAX_DATA_AGE_DAYS,
        "earnings_buffer_days": config.VIVEK_BOT_EARNINGS_BUFFER_DAYS,
        "max_weekly_loss_pct": config.VIVEK_BOT_MAX_WEEKLY_LOSS_PCT,
        # Cost model (bps) — mirrored by the journal + cloud watcher
        "commission_bps": dict(config.VIVEK_COMMISSION_BPS),
        "slippage_bps": dict(config.VIVEK_SLIPPAGE_BPS),
    }
    (pathlib.Path(args.out) / "bot_rules.json").write_text(
        json.dumps(rules, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
