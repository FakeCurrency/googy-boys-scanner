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
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _record_skip(market_key: str) -> None:
    """Note that `market_key` deliberately published nothing this run.

    Read by scan.yml, which otherwise cannot tell this decision apart from the
    silent-staging bug its per-market `assert_staged` exists to catch — see the
    SCAN_SKIP_MARKER block in config.py for the full incident.

    APPEND, never truncate: a full cycle runs `scanner.run` three times in one
    checkout (nasdaq, crypto, asx) and each process must be able to add itself
    without erasing an earlier one's line.

    Best-effort by construction. This is bookkeeping ABOUT a degraded run; a
    read-only filesystem or a lost race on it must never be the thing that takes
    the scan down, which would invert the entire point of the fix.
    """
    try:
        with open(REPO_ROOT / config.SCAN_SKIP_MARKER, "a", encoding="ascii") as fh:
            fh.write(f"{market_key}\n")
    except Exception as e:   # noqa: BLE001 - deliberately total, see docstring
        print(f"  (could not record skip marker for {market_key}: "
              f"{type(e).__name__}) - CI will treat this as a hard miss",
              flush=True)


def _scan_health(market_key: str, published: bool, send=None) -> int:
    """Count CONSECUTIVE dry runs per market and ping ONCE at the threshold.

    A "dry" run is the deliberate keeping-existing-JSON exit above: green by
    design, which the 2026-07-29 Yahoo throttling proved is also invisible by
    design — every ASX scan of a session ran dry and nothing said so. One dry
    run is weather; SCAN_DRY_ALERT_RUNS in a row is an outage worth a NOTICE.

    The counter lives in config.SCAN_HEALTH_FILE, which scan.yml's SHARED
    staging list commits — the same container-death lesson as sectorbreadth's
    ping memory (journal/alert_state.json is NOT staged, so any state kept
    there reads "never fired" every run). Firing EXACTLY at the threshold —
    `==`, not `>=` — is the whole dedupe: one ping per episode, no repeat
    while the outage drags on (the external /api/health monitor owns
    escalation), and the counter resets on the first successful publish.

    Best-effort like _record_skip: health bookkeeping must never take the
    scan down. Returns the consecutive-dry count after this run (0 when
    published), which is also what the tests assert on.
    """
    path = REPO_ROOT / getattr(config, "SCAN_HEALTH_FILE", "data/scan_health.json")
    try:
        try:
            health = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            health = {}
        if not isinstance(health, dict):
            health = {}
        row = health.get(market_key)
        if not isinstance(row, dict):
            row = {}
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if published:
            row = {"dry": 0, "last_publish": now,
                   "last_dry": row.get("last_dry")}
        else:
            row = {"dry": int(row.get("dry") or 0) + 1,
                   "last_publish": row.get("last_publish"), "last_dry": now}
        health[market_key] = row
        output.write_json(path, health, sort_keys=True, newline=True)

        threshold = int(getattr(config, "SCAN_DRY_ALERT_RUNS", 3) or 0)
        if not published and threshold and row["dry"] == threshold:
            if send is None:
                try:
                    from .broker.alert_router import smart_send as send
                except Exception:
                    return row["dry"]
            last = row.get("last_publish") or "unknown"
            send("scan_dry",
                 f"{market_key.upper()} scans running dry",
                 f"{threshold} consecutive scans returned no data - the "
                 f"dashboard is still showing the artefact from {last}. "
                 f"The source (Yahoo) is likely throttling; scheduled runs "
                 f"keep retrying, or press SCAN on the site to force one.")
        return row["dry"]
    except Exception as e:   # noqa: BLE001 - bookkeeping must never kill the scan
        print(f"  (scan-health bookkeeping failed for {market_key}: "
              f"{type(e).__name__})", flush=True)
        return -1


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
    MOVER_MIN_DVOL = getattr(config, "SECTOR_MOVER_MIN_DVOL",
                             {"asx": 1_000_000, "us": 10_000_000})
    # Same idea, keyed by SCAN market rather than page: the sector-breadth
    # surface needs this run's universe (the denominator) and results (the
    # numerator) together, and it is computed after the sector tape is written
    # so it can join the index changes that fetch already pays for.
    breadth_inputs: dict[str, dict] = {}
    regime_blocks: dict[str, dict] = {}
    # TOP100 #67. A market that THREW used to print one line and let main() run
    # to completion, so the process exited 0 — a scan that scanned nothing was
    # indistinguishable in CI from a scan that found nothing, which is the one
    # reading nobody investigates. Collected here, raised at the very END of
    # main() so every publish step below still runs (see the exit block).
    failed_markets: list[tuple[str, str]] = []

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
            low = (cov < getattr(config, "SCAN_COVERAGE_LOW_PCT", 80)
                   and len(universe) > getattr(config, "SCAN_COVERAGE_MIN_UNIVERSE", 50))
            print(f"  coverage: {len(deep_frames)}/{len(universe)} ({cov}%)  "
                  f"{cache_stats['fresh']} fresh{reused_note}"
                  f"{'  !! LOW' if low else ''}", flush=True)
            # Guard: nothing fresh AND nothing cached → the source is fully blocked.
            # Skip rather than clobber yesterday's good JSON.
            if not deep_frames:
                print(f"  no data for {market_key} (download blocked/empty) — "
                      f"keeping existing JSON", flush=True)
                _record_skip(market_key)
                dry = _scan_health(market_key, published=False)
                if dry > 0:
                    print(f"  scan-health: {dry} consecutive dry run(s) for "
                          f"{market_key}", flush=True)
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
                breadth_inputs[market_key] = {"universe": universe}

            # VIVEK (5.0-style 200 SMA reactions) -> <market>_vivek.json — the
            # only scan the app consumes.
            vk = scan.scan_vivek_market(market_key, out_root=args.out,
                                        universe=universe, frames=deep_frames,
                                        pulse_data=pulse_data, progress=False,
                                        from_cache=cache_stats["reused"])
            # v5 payload split (owner-ruled payload diet): summary + detail
            # sidecar in one publish step. ORDER IS THE FENCE: run_market
            # below receives `vk`'s in-memory rows, and split_vivek never
            # mutates its input — the bot sees full plans regardless of what
            # the browser downloads first.
            output.write_vivek_pair(vk, args.out, market_key)
            _scan_health(market_key, published=True)
            # Funnel history (owner-ruled Task 2): append this publish's
            # counts to the report-only trend file. Same posture as regime
            # below — a report artefact must never kill the scan, so the
            # failure is named and the scan walks on.
            try:
                from . import funnelhistory
                funnelhistory.append(market_key, vk, args.out)
            except (OSError, ValueError, TypeError, KeyError) as e:  # report-only
                print(f"  WARNING funnel history append failed: {e.__class__.__name__}: {e}")
            if market_key in breadth_inputs:
                breadth_inputs[market_key]["results"] = vk["results"]
            print(f"  vivek: {len(vk['results'])} setups ({tradeable(vk)} A+/A) · "
                  f"{vk['scanned']}/{vk['universe_size']} scanned")

            # REGIME + RELATIVE STRENGTH (2026-07-28). Computed HERE, inside the
            # market loop, because it reads `deep_frames` — five years of bars
            # for every name, the largest object in the scan — and this is the
            # only point at which they exist. Carrying them out to compute all
            # markets together at the end would hold two full markets of bars
            # alive at once to save nothing. Only the finished block travels.
            # Report-only; a failure costs one panel, never the scan.
            try:
                from . import regime as _regime
                if _regime.wanted(market_key):
                    regime_blocks[market_key] = _regime.compute(
                        market_key, deep_frames, universe,
                        bench=_regime.fetch_benchmark(market_key))
            except Exception as e:                          # noqa: BLE001
                print(f"  regime [{market_key}]: skipped ({e})", flush=True)

            # Slim per-market companion (2026-07-20, perf): the journal page
            # only needs symbol -> price + grade/dir to mark positions, but was
            # downloading the FULL scan file (ASX ~1.2MB, NASDAQ ~1.6MB) for
            # that map. This is ~5% of the size; the full file stays canonical.
            slim = {
                "schema_version": vk["schema_version"],
                "generated_at": vk["generated_at"],
                "market": market_key,
                "prices": vk["prices"],
                # Sparse {symbol: days} — only the marks that are NOT from
                # today's session (TOP100 #24). Absent = fresh. Carried into the
                # slim file because this file IS the journal's price source: the
                # page marks every open position off it, so a fossil close was
                # being drawn as a live price with nothing on screen to say so.
                "price_age": vk.get("price_age") or {},
                "rows": {r["symbol"]: {"grade": r["grade"],
                                       "grade_raw": r.get("grade_raw"),
                                       "dir": r["dir"],
                                       "headline_tf": r.get("headline_tf")}
                         for r in vk["results"]},
            }
            output.write_json(pathlib.Path(args.out) / f"{market_key}_prices.json",
                              slim, indent=None, separators=(",", ":"), newline=True)

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
            # EXCEPTIONS ONLY — the deliberate `continue` above (no data
            # downloaded, keep the existing JSON) is NOT counted here, on
            # purpose. That path is a reported decision rather than a fault, it
            # is already caught on scheduled runs by scan.yml's per-market
            # assert_staged, and failing on it would turn every Yahoo-blocked
            # crypto run red under crypto_bot.yml's plain `bash -e` step.
            failed_markets.append((market_key, f"{type(e).__name__}: {e}"))

    # Sector & index dashboard (ASX + US) with an auto market read.
    from . import sectors as _sectors
    print("Fetching sector dashboard ...", flush=True)
    sec = _sectors.fetch()
    for page_key, (frames, universe) in mover_inputs.items():
        if page_key in sec["markets"]:
            _sectors.enrich(sec["markets"][page_key], frames, universe,
                            MOVER_MIN_DVOL.get(page_key, getattr(
                                config, "SECTOR_MOVER_MIN_DVOL_DEFAULT", 1_000_000)),
                            market_key=page_key)
    # Keep the enrichment this run could not recompute (see sectors.carry_forward).
    sec_file = pathlib.Path(args.out) / "sectors.json"
    try:
        carried = _sectors.carry_forward(
            sec, json.loads(sec_file.read_text(encoding="utf-8")))
    except Exception:
        carried = 0  # no previous file / unreadable -> publish what we have
    output.write_json(sec_file, sec)
    print(f"  sectors: ASX {len(sec['markets']['asx']['sectors'])} sectors | "
          f"US {len(sec['markets']['us']['sectors'])} sectors"
          + (f" | carried {carried} field(s) forward" if carried else ""))

    # SECTOR BREADTH + HORIZON (2026-07-28). Runs LAST of the sector steps so it
    # can read the index tape just written above, and after every market's bot
    # run so `held` reflects today's book. Report-only: nothing it computes
    # reaches a trade decision. Best-effort — a failure here must never cost a
    # scan, and the previous published file simply stands.
    try:
        from . import sectorbreadth as _breadth
        ready = {m: d for m, d in breadth_inputs.items() if d.get("results") is not None}
        payload = _breadth.update(ready, out_dir=args.out) if ready else None
        for market, blk in ((payload or {}).get("markets") or {}).items():
            if market not in ready:
                continue        # carried forward from a previous run, not rescanned
            hz = blk["horizon"]
            print(f"  breadth [{market}]: leaders {', '.join(hz['leaders']) or '-'}"
                  f" | book {blk['book']['open']}/{blk['book']['max_open']}"
                  f"{' AT CAP' if blk['book']['at_cap'] else ''}"
                  f"{'  >> LOOK WIDER' if hz['expand'] else ''}")
            for note in hz["notes"]:
                print(f"    ! {note}")
    except Exception as e:
        print(f"  breadth: skipped ({e})", flush=True)

    # REGIME publish. The blocks were computed per-market above; this is only
    # the merge-and-write, so a market that did not scan keeps its last read
    # rather than being blanked.
    try:
        from . import regime as _regime
        payload = _regime.publish(regime_blocks, out_dir=args.out)
        for market, blk in ((payload or {}).get("markets") or {}).items():
            if market in regime_blocks:
                _regime.report(market, blk)
    except Exception as e:
        print(f"  regime: skipped ({e})", flush=True)

    # FX honesty: the ASX book is A$ while NASDAQ/crypto are US$ — the journal
    # converts ASX P&L at this rate so combined totals stop mixing currencies
    # at face value (~50% overstatement). Fail-soft: keep the last-good file.
    try:
        fx_frames = download(["AUDUSD=X"], period="5d")
        fx_df = fx_frames.get("AUDUSD=X")
        rate = float(fx_df["Close"].dropna().iloc[-1]) if fx_df is not None else None
        if rate and (getattr(config, "FX_AUDUSD_SANITY_MIN", 0.4) < rate
                     < getattr(config, "FX_AUDUSD_SANITY_MAX", 1.2)):
            output.write_json(pathlib.Path(args.out) / "fx.json", {
                "audusd": round(rate, 4),
                "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }, newline=True)
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
        # Exit ladder (TOP100 #33). public/js/journal.js re-typed these three
        # fractions as a JS literal and nothing ever compared the two, so the
        # page's booked-R for every scaled exit rode on a copy that could drift
        # from the executing ladder without a single test failing. Publishing
        # them lets the journal ADOPT the real ones and shout when they differ,
        # which is the same contract every other number here already has.
        "tp_scale": {
            "long": list(config.VIVEK_TP_SCALE_LONG),
            "short": list(config.VIVEK_TP_SCALE_SHORT),
        },
        # Portfolio limits the browser-side risk engine re-declared as its own
        # defaults (TOP100 #34) — published so it can stop guessing.
        "consec_loss_pause": config.CONSEC_LOSS_PAUSE,
        "portfolio_heat_limit_pct": round(config.PORTFOLIO_HEAT_LIMIT * 100, 4),
    }
    output.write_json(pathlib.Path(args.out) / "bot_rules.json", rules, newline=True)

    # TOP100 #67 — the exit, placed HERE rather than inside the loop on purpose.
    # Raising at the throw site would skip the sectors / breadth / HORIZON /
    # REGIME / FX / bot_rules publishes below it, so one market's bad frame
    # would silently stop the OTHER markets' surfaces from updating: a fix that
    # costs more than the defect. Everything publishes first; the process then
    # reports what actually happened.
    #
    # Safe in both callers, checked: scan.yml runs each market as its own
    # process under `set +e` with per-market rc capture and gates on ASX and
    # NASDAQ only, so a crypto failure can never block an ASX commit.
    # crypto_bot.yml runs `python -m scanner.run --market crypto` as a plain
    # `bash -e` step, so a non-zero exit fails the crypto job — which is the
    # whole point: it was green while doing nothing.
    if failed_markets:
        print(f"\n!! {len(failed_markets)} market(s) FAILED to scan "
              f"- data for them is unchanged from the previous run:", flush=True)
        for market_key, why in failed_markets:
            print(f"    {market_key}: {why}", flush=True)
        # stdout, then exit — Actions interleaves stdout and stderr unreliably,
        # so a summary written to stderr can surface above the lines it summarises.
        raise SystemExit(1)


if __name__ == "__main__":
    main()
