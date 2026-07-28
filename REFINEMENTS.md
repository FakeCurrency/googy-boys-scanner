# Refinement audit — 2026-07-16

Full output of the 12-reviewer code audit (115 raw findings, 107 after dedupe).
Every item cites evidence a reviewer actually read. Sorted impact desc, effort asc.
Impact: 5 = affects trading decisions/money … 1 = cosmetic. Effort: S/M/L.

## 1. Recompute the My-size position sizer when the timeframe switches
**Impact 5 · Effort S · chart**

wireSizeCalc (chart.js:931) captures d.entry/d.stop once at render (line 1343) — the headline Daily plan. Switching to the Weekly/3D tab swaps the footer and Simulate-Buy onto that TF's plan via d._activeLevels (set at line 1584, consumed by the buy handler at line 1100), but the sizer keeps computing shares off the Daily stop, so the 'exact share count for the broker order' is wrong exactly when the user is looking at a wider weekly stop. Re-run the calc from applyVivekLevels with lv.entry/lv.stop; while there, floor units for stock rows below 100 shares too (currently 43.2179-style fractional units are shown for ASX names, line ~955).

*Files: public/js/chart.js*

## 2. Fix manual close after TP1 booking only the TP1 leg
**Impact 5 · Effort S · journal-bot**

journal.js saveClose() (line 955) marks the trade closed and sets t.exit, but ensureClosedR (lines 190-201) only books the full exit when `!t.exits.length` — so a manual trade that already scaled 25% at TP1 (exits=[tp1]) never books the remaining 75% at the exit price. A runner closed at +2R records realized_r ≈ +0.25R (booked_pct stays 0.25), corrupting the Me-side totals, equity curve, head-to-heads and the edge/lens trackers. ensureClosedR needs a branch that books the remaining (1 − booked_pct) at t.exit when exits are non-empty.

*Files: public/js/journal.js*

## 3. Wire bot-page KILL SWITCH to the real kill workflow or relabel it
**Impact 5 · Effort M · journal-bot**

bot.js's kill flow (lines ~660-683) only calls risk.activateKillSwitch() — localStorage — then fakes closure by dimming cards (`c.style.opacity = "0.35"`) and toasts 'Trading disabled', while the actual bot runs in GitHub Actions with a real kill_switch.yml workflow and scanner/broker/kill_switch module that this button never touches. Owner presses KILL believing the book is flat; nothing happened server-side. Either dispatch kill_switch.yml through a CF function (the /api/scan dispatch pattern already exists) or label the button 'demo engine only'.

*Files: public/js/bot.js, public/bot.html, .github/workflows/kill_switch.yml, functions/api/scan.js*

## 4. Stop anchoring to the plan frame's own distant 200-SMA
**Impact 5 · Effort M · vivek-engine**

In _build_levels (vivek.py:257/263) the stop is min(swing_low, level) - 1.0*ATR (VIVEK_ATR_STOP_MULT=1.0), where `level` is the frame's OWN 200-SMA — and scan.py:152 makes the 1D plan the headline regardless of sig['level_tf'], so a name at its 3D/Weekly level with the Daily-200 far away (the XMR pattern: -23% from Daily) gets a stop stretched to that faraway SMA — the AXON 37% stop, which VIVEK_BOT_MAX_STOP_PCT=50.0 (config.py:360) passes. Anchor the stop to `level` only when |entry-level| <= VIVEK_NEAR_TOL (0.04) or a k*ATR cap; otherwise stop = reaction extreme - buffer, and add a per-timeframe stop-% sanity check in gate_grade so the ROW demotes too, not just the bot.

*Files: scanner/vivek.py, scanner/scan.py, scanner/config.py*

## 5. AT THE LEVEL mathematically implies CLEAN REACTION — A+ on proximity alone
**Impact 5 · Effort M · vivek-engine**

For an at-level long, price <= lvl*1.0204 (VIVEK_AT_LEVEL_TOL=0.02) and swing_low <= price, so `touched = swing_low <= lvl*1.02` (vivek.py:117) is guaranteed and reaction='bounce' needs only price > the 12-bar low — the +2 'CLEAN REACTION' chip always accompanies the +2 'AT THE LEVEL' chip (shorts symmetric). Weekly(4)+at_level(2)+reaction(2)=8 hits the A+ cutoff (VIVEK_GRADE_CUTOFFS [('A+',8)…]) with structure 0.0, so 'A+' currently means 'within 2% of the weekly 200-SMA'. Make 'bounce/reject' require a real rebound (e.g. close >= swing_low + 0.5*ATR with the touch within N bars, via _recent_reaction_bar) or require structure >= 0.5 for A+.

*Files: scanner/vivek.py, scanner/config.py*

## 6. Direction flips on a zero-width sign test; hysteresis holds A+ across the flip
**Impact 5 · Effort M · vivek-engine**

Direction is `price >= lvl` -> long else short (vivek.py:115-122) with no dead-band, while grade hysteresis persists only {symbol: grade} (_load_prev_grades, scan.py:57; apply_grade_hysteresis takes no direction) — so a 0.1% wobble through the SMA flips LONG<->SHORT and the held A+ badge follows the flipped read. Add an ATR-scaled direction dead-band inside the at-level band and store prev direction so hysteresis RESETS (never holds) when direction changed since the last scan. This is a different mechanism from the tracked two-scan confirmation gate and complements it.

*Files: scanner/vivek.py, scanner/scan.py*

## 7. Fetch Bybit instrument specs before formatting qty and price
**Impact 5 · Effort M · bot-broker**

bybit_bracket.py _fmt_qty/_fmt_price (lines 40-61) round to hardcoded decimal ladders (e.g. 5 decimals for qty<1, 4 decimals for price>=1), and nothing in the repo ever calls Bybit's get_instruments_info. Bybit rejects any order whose qty is not a multiple of the symbol's qtyStep (BTCUSDT step 0.001 — a computed 0.0175 BTC becomes '0.01750' and is rejected) or whose price is off the tickSize, and minOrderQty/minNotional are never checked. First live/testnet order on most symbols will bounce with retCode 10001. Add a cached instruments_info lookup in bybit_client and floor qty/price to qtyStep/tickSize, skipping below minNotional.

*Files: scanner/broker/bybit_bracket.py, scanner/broker/bybit_client.py*

## 8. Handle ambiguous order-submit timeouts instead of blind retry
**Impact 5 · Effort M · bot-broker**

bybit_client._retry (lines 68-97) retries place_order on ANY exception, and bybit_bracket.submit (lines 140-156) wraps it in a second 3-attempt loop (up to 9 submissions, ~28s of sleeps, even for permanent errors like invalid qty). If attempt 1 times out AFTER Bybit accepted the order, the retry re-sends the same deterministic orderLinkId, Bybit rejects it as duplicate, submit() returns skipped — and a real live order/position exists that the journal never records. On a duplicate-orderLinkId error the code should query the order by orderLinkId and adopt it as success; retries should discriminate retryable retCodes from permanent ones; the nested retry loop should be deleted.

*Files: scanner/broker/bybit_client.py, scanner/broker/bybit_bracket.py*

## 9. Sweep orphan Bybit positions the journal does not know about
**Impact 5 · Effort M · bot-broker**

bybit_reconcile.reconcile_journal (line 70) only iterates j['open'] — a position that exists at Bybit but not in the journal (crash between place_order success and _save, the duplicate-orderLinkId timeout case, or a manual trade) is completely invisible: no alert, no adoption, and vivek_guard/kill-switch session P&L math excludes it while it bleeds real money. After indexing live positions, diff them against journal-tracked bybit_symbols and at minimum fire an alert_dispatch 'orphan position' warning with symbol/size/unrealisedPnl, ideally adopting them into the book as untagged positions.

*Files: scanner/broker/bybit_reconcile.py*

## 10. Wire kill-switch/circuit breakers into the VIVEK path; make the standalone kill-switch read live P&L on the right book
**Impact 5 · Effort M · bot-broker**

vivek_run.py imports only vivek_bot and vivek_guard (lines 42-45) — the entire hardened risk stack (pre_trade_check's 12 gates, circuit_breaker consecutive-loss/drawdown/anomaly, kill_switch flatten) is wired ONLY into bybit_run/paper_run, the legacy scalp path. The VIVEK book — the only track record and the thing headed live — has a single daily-loss guard: no consecutive-loss pause, no portfolio heat, no notional cap. The standalone kill-switch is doubly broken: kill_switch.py line 95 reads scalp_journal.json, so once VIVEK trades on Bybit it monitors the wrong book yet its close_all_positions() would flatten VIVEK's positions on a scalp-journal breach; and run_standalone (lines 92-113) just sums STORED unreal_pnl — no reconcile, no price or position fetch — so the 30-min kill_switch.yml workflow (crons at :15/:45) sees P&L frozen at the last run and can never 'catch moves between scans' as its own docstring (lines 9-10) claims; a position collapsing between scans produces zero reaction. Point check_and_kill/check_all at vivek_bot_book.json, call them from run_market, and when BYBIT_API_KEY is present have run_standalone call bc.get_positions() (or reconcile_journal) to refresh unrealisedPnl before check_and_kill.

*Files: scanner/broker/vivek_run.py, scanner/broker/kill_switch.py, scanner/broker/circuit_breaker.py, .github/workflows/kill_switch.yml*

## 11. Replace GitHub cron with Cloudflare Worker cron — schedules barely fire
**Impact 5 · Effort M · ci-pipeline**

Actual run history shows GitHub's best-effort cron is delivering a small fraction of the schedule, hours late: stop_watcher.yml is '*/5 * * * *' (288/day) but fired FIVE times on 2026-07-15 (gh run list: 07:25, 12:06, 16:52, 20:37, 23:44 UTC — 3-6h gaps), so paper stops/targets are effectively unenforced server-side for hours; scan.yml defines ~16 weekday fires but 07-15 got 5, with nothing between 12:02 and 17:51 UTC — the entire first 4.5h of the NASDAQ session ran on the 12:02 pre-open scan; crypto_bot.yml (hourly) fired ~5x/day; phasemap's 08:30 cron ran at 12:58 (07-15) and 17:01 (07-13). Every run succeeds in 10-15 min, so this is pure scheduler throttling. The fix plumbing already exists: functions/api/scan.js already POSTs to /actions/workflows/.../dispatches with GH_DISPATCH_TOKEN, and /api/tick exists — a free Cloudflare Worker with cron triggers (to-the-minute reliability) should hit /api/tick every 1-5 min and dispatch scan/crypto_bot/phasemap on their intended cadence, keeping GH cron only as fallback.

*Files: .github/workflows/stop_watcher.yml, .github/workflows/scan.yml, .github/workflows/crypto_bot.yml, .github/workflows/phasemap.yml, functions/api/scan.js, functions/api/tick.js*

## 12. Sanitize symbol/market in /api/close — CI command injection
**Impact 5 · Effort M · security**

close.js only length-caps the attacker-controlled fields (`symbol: String(body.symbol).slice(0,20)`, `market: String(body.market||'').slice(0,20)`) with no character filter, and close_position.yml interpolates them straight into a shell run block: `--symbol "${{ github.event.inputs.symbol }}"` / `--market "${{ github.event.inputs.market }}"`. A public POST with symbol like `x";id;"` (fits in 20 chars) breaks out of the quotes and runs arbitrary commands on a runner that has `permissions: contents: write` plus access to repo secrets (Discord webhook, Bybit/GH tokens). This is an unauthenticated public endpoint. Add a strict regex (e.g. `^[A-Za-z0-9.\-]+$`) in close.js and/or pass inputs via `env:` in the workflow instead of inline `${{ }}`.

*Files: functions/api/close.js, .github/workflows/close_position.yml*

## 13. Bot's MDB position is unpriceable — mark frozen since universe swap
**Impact 5 · Effort M · data-correctness**

The bot book holds MDB (1W long, opened 2026-06-30, entry 335.93, stop 183.12) but MDB is not in the current NASDAQ universe (load_universe('nasdaq', full=True) = 1,429 symbols, MDB absent), and vivek_run.py only downloads universe tickers (line ~441), so price_of() returns None: git history shows unreal_r moving until 07-07 (0.144) then stone-frozen at 0.154 in every run since 07-10. With price=None the stop, time-stop and marks all skip (line 278: 'if is_open and price is not None'), so the position can never close and squats one of 10 NASDAQ slots forever. Download the union of universe + open-book yf tickers each run.

*Files: scanner/broker/vivek_run.py, public/data/vivek_bot_book.json, scanner/universe.py*

## 14. Stop the AI Bot page presenting the dead June bot_status.json as the live book
**Impact 5 · Effort L · journal-bot, ci-pipeline, data-correctness**

public/data/bot_status.json is frozen at generated_at 2026-06-25T14:32:00+10:00 (equity $10,342.18, 3 open positions, a 12-trade journal) and nothing writes it any more — its producer, the crypto scalp/bybit_run pipeline, last committed 'data: crypto scalp' on 2026-06-26 and is invoked by NO current workflow (scanner/broker/bybit_run.py only READS htf_bias from it). Yet bot.js:21 fetches it as STATUS_URL, seeds the RiskManager's 'real starting equity' from it (init(), ~line 561, and bot.js:16-19, 559), and loads d.journal, d.log, d.positions and d.equity_curve — so bot.html renders 'Execution Log · live', 'Bybit Testnet · WS connected · 38ms', 'Today's Performance' showing June-25 P&L, and /NQ/GC/CL positions no system in this repo trades, while the real track record (journal/vivek_bot_book.json, 24 open / 2 closed) never appears on the page. Related stale copy: risk_manager.js line 14 still says 'the 2% position-sizing rule' (hard rule is 0.25%), and the roadmap card marks 'Full paper journal + export' as todo though CSV/Excel/HTML exports are built. public/data also still ships the pipeline's other dead outputs (expectancy.json, performance.json, events.json, attribution.json, fill_analysis.json — all stamped Jul 2). Feed the page from the real book/status or badge the whole terminal as a seeded demo, and delete the dead JSONs.

*Files: public/bot.html, public/js/bot.js, public/data/bot_status.json, public/js/risk_manager.js, scanner/broker/bybit_run.py*

## 15. Stop crypto tier-2/3 fallback charts being hijacked by the scalp live stream
**Impact 4 · Effort S · chart**

The live-stream guard at chart.js:1756 is `!d._vivek && market crypto`, which pmOnlyFallback charts (_pm:true, _vivek:false, line 598) pass — so any crypto ticker without a live VIVEK plan (journal names, alerts, watchlist) gets curTF forced to '1H' (line 1761), its deliberately built 1D/3D/1W SMA views become unreachable, the toggle turns into 15M/30M/1H, and makeLive pours computeScalp's 7 BB/KC lines into the 4 series created from the 1D block's SMA-10/20/43/200 (applyAll, ~2172) — mislabeled overlays, no legend (legend only runs inside applyTF), and PhaseMap zone bands never get data (applyPmZones only runs from applyTF). Exclude `d._pm`/`d._fallback` from the pair guard so these charts keep the intended D/3D/W view.

*Files: public/js/chart.js*

## 16. Show the plan's scan age in the chart header
**Impact 4 · Effort S · chart**

asx_vivek.json carries top-level `generated_at` (verified) and per-row `data_age_days`, but fetchResultMeta (chart.js:2685-2705) copies only currency_symbol off the file and header() renders no 'as of' anywhere — so a live-ticking header price sits next to Entry/SL/TP levels that may be from a scan many hours old, with no way to tell. Given the known read-flip-within-hours behaviour, plan age is decision-relevant: surface 'plan as of <Melbourne time>' (site convention) near the grade, amber-tinted when stale.

*Files: public/js/chart.js, public/chart.html*

## 17. Tag bot-book trades with lens so lens tracker isn't all UNTAGGED
**Impact 4 · Effort S · journal-bot**

Every trade in journal/vivek_bot_book.json lacks a `lens` field (verified: Counter({None: 26})), so renderLensTracker (journal.js line 700, `t.lens || "untagged"`) buckets the ENTIRE only-track-record under 'UNTAGGED' — the table that's supposed to judge VIVEK vs PhaseMap vs Specs says nothing about any of them. Since vivek_bot.py only trades the VIVEK lens, either stamp lens='vivek' in splitBot() or publish the field from the bot runner; the lens chip in NEW POSITIONS boxes is missing for bot rows for the same reason.

*Files: public/js/journal.js, scanner/broker/vivek_bot.py, journal/vivek_bot_book.json*

## 18. Fix rules form zeroing risk engine after server-rule adoption
**Impact 4 · Effort S · journal-bot**

On a fresh browser bot.js adopts risk_pct=0.35 and max_positions=10 from bot_rules.json (lines 541-554), but bot.html's selects only offer 0.25/0.5/1/1.5/2 % and 2-5 positions, so populateRulesForm's `el.value = 0.35` leaves the select with value "" — and the next 'Save Rules' click runs collectRules' Number("") = 0, persisting risk_pct 0 / max_positions 0 and setting the engine's maxRiskPerTradePct to 0 (sizing calculator then recommends 0 units for everything). Add the adopted values as options dynamically or clamp collectRules to reject empty/zero.

*Files: public/js/bot.js, public/bot.html*

## 19. Price open crypto positions live instead of hourly scan snapshots
**Impact 4 · Effort S · journal-bot**

refreshLive (journal.js line 865) always prefers scanPrice — for crypto that's crypto_vivek.json refreshed only hourly by crypto_bot.yml — so the 20s refresh loop repaints the same hour-old number, and manage()'s TP/stop auto-management on manual crypto trades fires up to an hour late while Binance live quotes are one cheap request away (the close modal already fetches them, so its prefill visibly disagrees with the table's 'Now'). Prefer priceFor() for crypto groups with scanPrice as the fallback; the head-to-head note 'your side updates live' becomes true again.

*Files: public/js/journal.js*

## 20. Publish the crypto PhaseMap replay on the INSIGHTS page
**Impact 4 · Effort S · lens-pages**

public/data/phasemap/stats/crypto.json is generated weekly (fresh: 2026-07-12, full cohorts incl. tier A+/A, liquid/illiquid, long/short) but phasemap-insights.js only fetches stats/asx.json, stats/nasdaq.json and stats/specs_asx.json — the crypto artifact is never shown anywhere. The PhaseMap page has a CRYPTO market tab and the crypto bot trades hourly, so the owner is reading crypto setups with zero replay evidence on the page whose whole job is 'every lens's honest numbers'. Add a crypto grab and a crypto line to the liquidity/A+/edge-vs-random findings.

*Files: public/js/phasemap-insights.js, public/phasemap-insights.html*

## 21. Grade hysteresis ratchets forever, silently lowering the bot's A+ bar to 7
**Impact 4 · Effort S · vivek-engine**

_load_prev_grades (scan.py:49-61) reads the PUBLISHED grade — which is itself post-hysteresis — so a hold renews every scan: with VIVEK_GRADE_HYSTERESIS=1 (config.py:272) a name scoring 7 satisfies 7 >= 8-1 indefinitely and stays A+ for weeks, and the VIVEK_BOT_MIN_GRADE='A+' bot trades it, making the effective bot cutoff 7 not 8. Publish a raw_grade field alongside grade and feed hysteresis from raw_grade (or cap consecutive holds), so a hold survives one noisy scan but not a genuine decay.

*Files: scanner/scan.py, scanner/vivek.py*

## 22. Reclaim trigger re-fires for six bars and arms both directions at the level
**Impact 4 · Effort S · vivek-engine**

detect_trigger's pierce scan is `any(low[i] <= level for i in range(last-k, last+1))` (vivek.py:394) — it INCLUDES the trigger bar and the prior VIVEK_TRIGGER_LOOKBACK=5, so one touch keeps the setup 'armed reclaim' for ~6 consecutive daily scans with entry = each day's close (drifting up to 4% off the level), and a name oscillating at the SMA satisfies reclaim-long one day and reclaim-short the next. Make reclaim a crossing event: previous close on the wrong side of the level, last close back through — it fires once, at the level, and the stale re-arms (and the both-direction arming) disappear.

*Files: scanner/vivek.py*

## 23. Remove the $40 CFD brokerage from Bybit closed-PnL math
**Impact 4 · Effort S · bot-broker**

bybit_reconcile.py line 126 computes pnl = closedPnl - BROK_RT where BROK_RT = SCALP_BROKERAGE_EACH_WAY*2 = $40 (config.py line 450) — an ASX-CFD fee model applied to crypto perps whose closedPnl already includes exchange trading fees (Bybit taker round-trip on a ~$5k position is ~$5.50). With SCALP_RISK_PER_TRADE=$100 (config.py line 681) that phantom $40 is 0.4R per trade — enough to flip the recorded expectancy of the whole live book negative. Also inconsistent: r_val (line 131) uses gross closedPnl while pnl is net. Replace BROK_RT with a Bybit-specific fee constant of ~0 (fees already netted) or read actual fees from the execution list.

*Files: scanner/broker/bybit_reconcile.py, scanner/config.py*

## 24. Guard against publishing an empty snapshot and mass-pruning charts
**Impact 4 · Effort S · phasemap-pkg**

In phasemap/run.py, a Yahoo outage/rate-limit night yields an empty provider cache (provider.py fetch_all silently `continue`s on missing symbols), so run_market builds a snapshot with results=[] — which validate_snapshot accepts — overwrites latest.json, and then prune_stale_files(chart_dir, charted=set()) deletes every chart file for that market (498 asx / 582 nasdaq today). The job exits 0, the schema gate passes an empty results list, the commit step pushes the wipe, and the fresh run_date keeps the stale badge green while the tab shows 'Nothing matches this view'. Add a collapse guard: refuse to overwrite latest.json (and skip pruning) when results drop to zero or fall more than ~50% below the previous latest.json, exiting non-zero so the Discord failure alert fires.

*Files: phasemap/run.py, phasemap/data/provider.py*

## 25. Isolate per-ticker failures so one bad ticker can't kill markets
**Impact 4 · Effort S · phasemap-pkg**

The run_market loop (run.py lines 144-163) has no try/except: any scan_ticker exception or a renderer KeyError (render() does template.format(**slots), which raises if e.g. a DISPLACED record ships without TARGET zones, leaving t1_low unfilled) aborts the whole market after charts were partially rewritten and before any snapshot is written. In phasemap.yml a failed ASX then fails the gate (line 73), the commit step never runs, and the same night's successful NASDAQ/crypto snapshots are discarded too. Wrap the per-ticker body in try/except that logs and continues, count failures, and fail the run only above a threshold.

*Files: phasemap/run.py, phasemap/narrate/renderer.py, .github/workflows/phasemap.yml*

## 26. Age-gate and caveat the {stats} claim in published narrations
**Impact 4 · Effort S · phasemap-pkg**

load_stats (run.py lines 36-49) gates on sample size and ruleset_version but ignores the 'generated' date (currently 2026-07-12) and the survivorship_bias:true flag the file carries — if the weekly lens_backtest quietly stops, 77 ASX + 72 NASDAQ narrations will keep asserting 'reached its first target zone within 20 sessions 30% of the time' from ever-older numbers, and report.py's own banner says these survivor-only figures should not be published as-is. Add a max-age check (e.g. reject stats older than ~30 days) and append a short survivor-only-history qualifier in _stats_text while the feed is yfinance.

*Files: phasemap/run.py, phasemap/narrate/renderer.py, phasemap/backtest/report.py*

## 27. Scope scan/crypto_bot commit PATHS — wholesale public/data reverts other lenses
**Impact 4 · Effort S · ci-pipeline**

scan.yml:184 and crypto_bot.yml:73 commit PATHS containing the whole 'public/data' tree, and their retry loop does 'git reset --hard origin/main; git rm -rq public/data; git checkout $SHA -- public/data' — so if phasemap.yml or lens_backtest.yml pushes to main while a scan is running, the scan's push restores the ENTIRE public/data (including phasemap/latest.json, vivek_backtest.json) from its own stale checkout, silently reverting the fresh nightly snapshot for a full day. phasemap.yml:124 already does this correctly (scoped to public/data/phasemap + spec files), phasemap runs in a DIFFERENT concurrency group ('phasemap' vs 'scan'), and cron throttling now makes phasemap land mid-NASDAQ-session (12:58-17:01 UTC pushes observed), so the collision window is real and unpredictable. List the exact files each job writes, as phasemap.yml does.

*Files: .github/workflows/scan.yml, .github/workflows/crypto_bot.yml*

## 28. Add Discord failure alerting — zero if:failure() steps exist
**Impact 4 · Effort S · ci-pipeline**

grep confirms no workflow among all 10 has an 'if: failure()' step; the only failure signal is GitHub's default email. The DISCORD_WEBHOOK_URL secret is already wired into scan.yml:163 and phasemap.yml:86 for confluence pings, so a 5-line 'notify on failure' step (workflow name + run URL) costs nothing. Worse, stop_watcher.yml:38 deliberately masks HTTP failures ('::warning' then exit 0), so a dead /api/tick endpoint — which silently disables paper stop enforcement — would never notify anyone by any channel. Add failure pings to scan/crypto_bot/phasemap/lens_backtest, and make stop_watcher alert (once, deduped) after N consecutive non-200s.

*Files: .github/workflows/scan.yml, .github/workflows/phasemap.yml, .github/workflows/crypto_bot.yml, .github/workflows/stop_watcher.yml, .github/workflows/lens_backtest.yml*

## 29. Tighten dashboard staleness thresholds from days to session-aware hours
**Impact 4 · Effort S · ci-pipeline**

The VIVEK feed's stale warnings are calibrated to a nightly pipeline, not the hourly one: app.js:987 flags the dataset only at '>= 2 days', app.js:633 marks a row stale at mins > 1440, and phasemap-shared.js staleBadgeHTML uses 48h/30h. On 07-15 the site served 12:02 UTC pre-open NASDAQ data for the first 4.5 hours of the session (see cron-throttling evidence) with zero visible warning — prices, grades and armed/watching states were hours old while the market traded. generated_at is already in every payload; add a page-level banner when data age exceeds ~2x expected cadence while that market's session is open (e.g. 'NASDAQ data is 4h old — market is open').

*Files: public/js/app.js, public/js/phasemap-shared.js*

## 30. Make /api/tick fail closed — it is open by default and mutates KV
**Impact 4 · Effort S · security**

tick.js `authorised()` returns true whenever TICK_SECRET is unset (`if (!env.TICK_SECRET) return true;`), and CLAUDE.md/stop_watcher.yml document the secret as optional ("Leave unset to run open"). While unset, any anonymous caller drives runTick(), which lists EVERY `journal:` key in KV, fires N upstream Yahoo/Binance fetches per open position, and writes auto-closes back to KV. An attacker can spam it to exhaust upstream quotas (banning the Pages egress IP) and force stop/target evaluation on strangers' journals at will. Require the secret (fail closed) or gate the endpoint behind Cloudflare Access.

*Files: functions/api/tick.js, .github/workflows/stop_watcher.yml*

## 31. Fix VIVEK trigger tooltips overstating reclaim edge 2.4x
**Impact 4 · Effort S · data-correctness**

app.js VK_ENTRY_Q (line ~971) hardcodes 'Best trigger — backtest ≈+1.6R avg, ~56% win (long-only)' for reclaim and 'flat-to-negative' for retest, but the current vivek_backtest_longonly.json by_entry_type says reclaim = +0.658R avg / 59.7% win and retest = +0.147R / PF 1.33 (positive). Every VIVEK filter chip shows a 2.4x-inflated edge claim. Read the numbers from the JSON at runtime (as phasemap-insights.js already does) instead of constants.

*Files: public/js/app.js, public/data/vivek_backtest_longonly.json*

## 32. Long-only backtest has never run on schedule; evidence ossifying
**Impact 4 · Effort S · data-correctness**

vivek_backtest_longonly.json is still the 2026-06-28 manual run (generated_at 2026-06-28T08:55:44Z; gh run list shows only workflow_dispatch runs on 06-28, zero schedule runs) because the monthly cron '0 8 1 * *' was committed 2026-07-02 — one day after July's only fire date — so the first scheduled refresh is Aug 1. The 'bot-relevant evidence' (system.html calls it that) predates the NASDAQ universe expansion and current entry rules. Dispatch it once now and/or add a second monthly cron (e.g. the 15th).

*Files: .github/workflows/vivek_backtest.yml, public/data/vivek_backtest_longonly.json, public/system.html*

## 33. Fix AT-LEVEL strip: undefined tooltip and dead '+119 more' cap
**Impact 4 · Effort M · dashboard**

app.js:1122 renders the tooltip as `(${r.dist_pct}% away)` but dist_pct lives at r.detail.dist_pct (verified against nasdaq_vivek.json), so every chip's hover says 'undefined% away'. Also 131/249 NASDAQ and 108/205 ASX results are at_level, so the strip caps at 12 (all A+ in payload order, duplicating the A+ tab) and hides the rest behind a non-clickable '+119 more' span (app.js:1118-1126). Fix the field path, and make the strip actionable: prioritise weekly-TF/nearest names and turn '+N more' into an at-level filter chip in #vk-filters.

*Files: public/js/app.js*

## 34. Deduplicate lens fetches: loadConfluence re-downloads just-parsed payloads and double-renders the list
**Impact 4 · Effort M · dashboard, mobile-perf**

PM.loadConfluence (phasemap-shared.js:258-261) fetches data/<market>_vivek.json with cache:'no-cache' even though applyPayload (app.js:1146-1160) just loaded that exact file into state.data (app.js:1250, 1152) — nasdaq_vivek.json is 1.55MB, and the double-download repeats on every market switch, every 5-min auto-refresh, and every scan poll (~18MB/hr extra just sitting open on mobile); phasemap latest.json (1,216,022 B) is fetched on top, and the .then rebuilds the whole list via innerHTML, replaying the rowIn entrance animation (styles.css:530 comment: 'replays on every list render') so the list visibly animates twice per load. Worse, mynames.js:103-116 fetches vivek+phasemap+spec per market AND calls loadConfluence(m) which fetches the same three files again — with 3 markets starred that is ~8MB of JSON fetched and parsed twice. Let loadConfluence accept pre-fetched/already-parsed payloads (only fetching the two small lens files when needed) and patch confluence chips in place instead of a full innerHTML rebuild.

*Files: public/js/phasemap-shared.js, public/js/app.js, public/js/mynames.js*

## 35. Stop persisting full 1MB+ scan payloads to localStorage
**Impact 4 · Effort M · mobile-perf**

app.js cacheSet (line 52) stringifies the entire scan payload per market and prefetchMarkets (line 1730) warms all three — nasdaq_vivek.json is 1,586,221 B and asx 1,309,315 B, so ~2M characters (~4MB as UTF-16) sit in the same ~5MB iOS quota as the manual journal; gbs-sync.js line 53 silently catches quota failures on journal saves, so scan-cache bloat can silently drop journal writes. The SW already keeps last-good copies in Cache Storage (sw.js networkFirst on /data/), making this layer redundant — keep the in-memory state.cache and drop the localStorage copies, or store only the slim fields the rows need. prefetchMarkets also ignores cacheGet (checks only state.cache), so it re-downloads markets that localStorage already has fresh.

*Files: public/js/app.js, public/js/gbs-sync.js*

## 36. Grade gate arms on the 1D plan while the bot trades the 1W plan
**Impact 4 · Effort M · vivek-engine**

scan.py:152-160 grades armed/R:R from plans['1D'] only, but the bot's primary is the Weekly plan (VIVEK_BOT_PREFER_TF='1W', config.py:341) and _pick_plan (vivek_bot.py:76) never even considers '3D' plans that build_plans produces. A weekly-armed/daily-quiet setup gets 'WATCHING (no trigger)' -> B+ -> invisible to the A+-only bot, and 3d-level signals are traded on plans anchored to a different SMA than the one that fired. Gate on the best armed plan (or the sig['level_tf']-matched plan) and add '3D' to _pick_plan's fallback order.

*Files: scanner/scan.py, scanner/broker/vivek_bot.py, scanner/config.py*

## 37. Make the H4 proxy window per-market honest, not just relabelled
**Impact 4 · Effort M · vivek-engine**

The chip literally says 'H4 200 SMA' (vivek.py:181) for what is the Daily-200: a true H4-200 spans ~33 calendar days on 24/7 crypto (200x4h/24h) and ~123/133 trading days on NASDAQ/ASX sessions — on crypto the current proxy is off by ~6x, which is exactly why community H4 levels didn't match (the XMR gap needed the 3D bolt-on). A drop-in fix needing no intraday data: per-market VIVEK_H4_PROXY_DAYS ({crypto: 33, nasdaq: 123, asx: 133}) as a daily-close SMA window for the h4 level, and until then label the chip 'D200 (H4 proxy)' in the chip and narrative.

*Files: scanner/vivek.py, scanner/config.py*

## 38. Fix sector cap: empty NASDAQ sectors and unseeded legacy book rows
**Impact 5 · Effort M · bot-broker · FIXED 2026-07-28 (owner-authorised: "wire it in, and backfill the legacy ASX rows")**

The VIVEK_BOT_MAX_PER_SECTOR=3 correlation cap is a silent no-op almost everywhere. **Impact raised 4 → 5 on 2026-07-28:** the book became a 30-position ceiling that any ONE market may fill on its own, so a fully-NASDAQ book now has no correlation control at all — the exact "30 miners" outcome the owner said the cap was there to prevent, when he chose to leave it at 3.

**Fixed since this was written:** crypto now gets synthetic `crypto-major`/`crypto-alt` buckets keyed off the symbol (`_sector_key`), so its cap binds despite an empty stored sector; and `plan_trade`'s ticket now persists `row["sector"]` (vivek_bot.py:289), so positions opened from 2026-07-20 onward seed the cross-run counter correctly.

**Still broken (verified against the live book, 2026-07-28):**

1. **NASDAQ rows reach `decide()` with no sector** — `universe._fetch_nasdaq` hardcodes `sector: ""` (the NASDAQ trader file has no sector column), so 0 of 269 scanned rows and 10 of 10 open positions carry one. `decide()`'s guard `max_sector and sector and ...` exempts them, so the cap never binds on NASDAQ. **This is a wiring gap, not a data gap** (corrected 2026-07-28 — an earlier draft of this item said a fallback grouping had to be invented): `scanner/sectorcache.py` already maintains `data/sector_map.json`, keyed `nasdaq:AAON -> {"sector": ...}`, refreshed by its own scan.yml step, and it covers **269 of those same 269 rows — 100%**. It was scoped display-only ("nothing in any signal path reads this"), so nothing merges it into the rows the bot sees. The fix is to merge it in before `decide()` and let the existing cap do its job; no new source and no invented grouping needed.
2. **Legacy ASX rows are invisible to the seeding** — the 8 ASX positions opened before the 2026-07-20 ticket fix still carry `sector:''`, so the counter starts low and ASX can take 3 *more* in a sector a legacy row already occupies. Needs a one-off backfill from the universe cache.

**Done 2026-07-28 (visibility):** `decide()` logs a warning when the cap is configured but under half the rows carry a sector, and publishes `summary["sector_coverage"]` / `summary["max_per_sector"]` so the blindness is visible instead of assumed-fixed.

**FIXED 2026-07-28 (the wiring itself, on the owner's authorisation).** `data/sector_map.json` stopped being display-only:

- `sectorcache.sector_map_for(market, cache)` + `enrich_rows(rows, market, cache)` merge the cache into the rows `run_market()` hands `decide()`, right after the ADV enrichment. **Enrichment only ever writes into a BLANK field** — a sector shipped with the universe (every ASX row carries GICS) always wins over best-effort Yahoo data, and an empty or unreadable cache degrades to a no-op rather than clearing sectors that were already right. That last direction matters more than the first: blanking a sector switches the cap OFF for that row.
- The backfill for (2) is the same code path plus a seeding change: `sectorcache._scan_symbols()` now reads the open book first and queues held sector-less names at rank `-1`, ahead of every scan grade. Before this the fetch list was built from scan results only, so a holding that had dropped out of the scan could never acquire a sector — it occupied a slot while staying exempt from the cap it should have been filling. Three NASDAQ positions were in exactly that state.
- Pinned end-to-end in `tests/test_sector_cache.py::test_enriched_rows_make_the_sector_cap_bind`: four Technology A+ setups, un-enriched all four are taken, enriched three are and `skip_reasons["sector_cap"]` is 1.

**Consequence to watch:** this is now a SIGNAL path. A wrong sector in the cache changes which trades get taken, and the cache is best-effort Yahoo data with no verification step. The module docstring and the test file both say so.

*Files: scanner/sectorcache.py, scanner/broker/vivek_run.py, scanner/broker/vivek_bot.py, tests/test_sector_cache.py*

## 39. Reconcile exit detection relies on wrong Bybit closed-pnl fields
**Impact 4 · Effort M · bot-broker**

bybit_reconcile.py line 117 reads closed_rec.get('exitType') but Bybit V5 /v5/position/closed-pnl records carry execType (Trade/BustTrade/AdlTrade...), not exitType — and execType cannot distinguish takeProfit from StopLoss anyway, so every live exit will land as reason 'unknown' (note the reason_map's own inconsistent casing: 'takeProfit' vs 'StopLoss'). The side matching (line 39, wanted_side='Buy' for longs) assumes closed-pnl side is the OPENING side; if Bybit reports the closing order's side, every closed long is missed and stays 'pending' forever, holding a book slot. The order-path tests can't catch this because their mocks (tests/test_order_path.py lines 134-136) fabricate the code's own assumed schema. Match records by closing-order timestamps/symbol and derive stop-vs-target from the closing order's stopOrderType via get_order_status; validate one real testnet payload into a fixture.

*Files: scanner/broker/bybit_reconcile.py, tests/test_order_path.py*

## 40. Stop sizing three market books off the same $10k equity
**Impact 4 · Effort M · bot-broker**

run_market (vivek_run.py line 140) uses config.VIVEK_BOT_ACCOUNT_EQUITY=10,000 independently for asx, nasdaq AND crypto, and vivek_guard.check computes the 3% daily-loss limit per market against that full figure — so one real account funding all three books faces up to 9% aggregate daily loss, 30 concurrent positions, and per-market 5x/5x/3x notional caps that stack across books. Equity is also static: realized losses never shrink sizing (risk_manager.account_size exists but is unused here). Since the book file already holds all markets, add a cross-market heat check summing risk_usd over book['open'], and derive equity as base plus cumulative realized P&L (or wallet_balance() for crypto when keys exist).

*Files: scanner/broker/vivek_run.py, scanner/broker/vivek_guard.py, scanner/config.py*

## 41. Expire stale GTC entries and sync partial-fill size from broker
**Impact 4 · Effort M · bot-broker**

bybit_bracket.submit places Limit entries with timeInForce='GTC' (line 131) and nothing ever cancels them: a never-filled entry becomes broker_status='pending' in reconcile (bybit_reconcile.py lines 154-156) forever, while still counting against max_positions, portfolio heat and the daily trade cap (pre_trade_check.py lines 70-72) — zombie orders permanently eat capacity. Partial fills have the same drift: reconcile reads live avgPrice/unrealisedPnl but never copies live 'size' back into pos['units'] (lines 81-109), so risk_usd and current_r keep using the intended full size after a 30% fill. Cancel entry orders older than N sessions via cancel_order, and set pos['units']=float(live['size']) with risk_usd recomputed on every reconcile.

*Files: scanner/broker/bybit_bracket.py, scanner/broker/bybit_reconcile.py, scanner/broker/pre_trade_check.py*

## 42. Stamp run_date from the data, not the delayed cron wall-clock
**Impact 4 · Effort M · phasemap-pkg**

run.py sets run_date = now(Melbourne).date(), but the 08:30 UTC cron actually fires 3-8.5h late (recent starts: 11:35, 11:48, 17:01, 12:51, 12:58 UTC); the 2026-07-13 17:01 UTC run stamped itself 2026-07-14 (03:01 Melbourne), so no market has a 2026-07-13.json and the next night silently overwrote 2026-07-14.json — a hole plus a replaced day in the archive the backtest treats as the record. It also blanks the FLASHED cue (phasemap.js line 88 compares sweep/displacement_date === run_date, and no bar can carry tomorrow's date), and contradicts writer.py's 'same input => byte-identical output' determinism claim. Derive run_date from the newest bar date across the scan and never overwrite an existing dated snapshot.

*Files: phasemap/run.py, phasemap/output/writer.py, public/js/phasemap.js*

## 43. Rate-limit /api/journal and raise the minimum sync-code length
**Impact 4 · Effort M · security**

Unlike scan/close, journal.js has NO rate limiting on GET or PUT, and both accept any code with `code.length < 4` rejected — so a 4-char minimum. The KV key is a deterministic SHA-256 of `gbs-journal:`+code (keyFor), so an attacker can unthrottled-enumerate short/common codes: each guess is one KV GET that returns another user's full journal, and PUT lets them overwrite it (only guarded by an array check + 2MB cap). Add a per-IP KV cooldown like scan.js and lift the minimum to ~8 chars server-side (client journal.js also only enforces 4).

*Files: functions/api/journal.js*

## 44. Fix JS unit tests asserting hand-copied mirrors that already drifted
**Impact 4 · Effort M · code-quality**

test/unit.test.js never loads chart.js or journal.js — it tests local copies ('Mirrors journal.js mjCalc exactly', 'BINANCE_MAP from chart.js — must stay in sync'). The drift already happened: the test's 12-coin BINANCE_MAP and isCrypto(sym,market) no longer exist in chart.js, which now has `const BINANCE_MAP = {}` (line 86) and `isCryptoMarket(assetType)` (line 123) — CI green means nothing for the real fill/P&L code. Extract these pure functions into a requireable module (as risk_manager.js already is, and test/vivek_manage.test.js imports the real _vivek_manage.js) so the tests exercise shipped code.

*Files: test/unit.test.js, public/js/chart.js, public/js/journal.js*

## 45. Reconcile three contradictory freshness claims on one page
**Impact 3 · Effort S · dashboard**

The header timer counts down from 5:00 (AUTO_REFRESH_S = 5*60, app.js:14), the scan-sub line says 'auto-refreshes hourly' (app.js:1138), and the footer says 'refreshed daily after each market close' (index.html:170) — while scan.yml actually runs every 30 min in market hours. Whoever trusts the footer thinks prices are a day old; whoever trusts the sub thinks hourly. Pick one phrasing driven by the actual cadence per market and delete the other two claims (the #scan-fresh badge already shows true age).

*Files: public/js/app.js, public/index.html*

## 46. Hide or fix the M.C sort where cap data is absent
**Impact 3 · Effort S · dashboard**

market_caps.json contains 395 asx and 223 nasdaq keys but zero crypto keys (verified), so on CRYPTO the M.C sort button highlights, shows a direction arrow, and does nothing (mcapOf returns 0 for every row, app.js:952, 231) — the list silently stays in the previous order while claiming to be cap-sorted; on NASDAQ 26 of 249 names have no cap and sink unpredictably. Hide the M.C chip when state.caps has no keys for the active market (or extend the caps builder to crypto), and sort null-cap names last explicitly.

*Files: public/js/app.js, public/data/market_caps.json*

## 47. Clear stale stat cards and banners on load failure
**Impact 3 · Effort S · dashboard**

load()'s catch (app.js:1256-1262) only replaces #scan-title and #results, so after a failed fetch on market switch the stat cards, grade-tab counts, #scan-sub label, vk-filters, AT-LEVEL strip and confluence banner all still show the PREVIOUS market's numbers — with chip links hardcoded to the old m=<market> — under the newly selected market button. Reset or dim those surfaces in the error path, and add a retry button to the placeholder.

*Files: public/js/app.js*

## 48. Make drawing and measure tools usable on touch devices
**Impact 3 · Effort S · chart**

The drawing canvas (.draw-layer, chart.css:111) sets pointer-events but not touch-action, so on iOS a measure drag or trendline placement competes with page scroll and gets pointer-cancelled mid-gesture — the repo already knows the fix (.live-pos-box sets touch-action:none, chart.css:268). The draw buttons are 28x26px (chart.css:95-97), well under the 44px iOS target the recent iOS revamp standardised elsewhere, and the hover-to-delete trash button (chart.js:2092+) has no touch path. Add touch-action:none to .draw-layer while a tool is active and grow the buttons on the mobile breakpoint.

*Files: public/css/chart.css, public/js/chart.js*

## 49. Split edge tracker by side so manual trades don't pollute bot evidence
**Impact 3 · Effort S · journal-bot**

renderEdgeTracker and renderLensTracker both pool `[...state.bot.closed, ...state.me.closed]` into the same cells (journal.js lines ~646 and ~689), so the forward-expectancy table that the new 30-closed-bot-trades review checkpoint depends on is contaminated by discretionary manual trades — a few bad Me closes can flip a setup cell's sign while the bot book is the only official track record. Add a Claude/Me/Both toggle or per-side sub-rows, mirroring the ⚠ thin-sample convention already in place.

*Files: public/js/journal.js, public/journal.html*

## 50. Stop watchlist fabricating TRAP_SET/LONG for snapshot-less stars
**Impact 3 · Effort S · lens-pages**

phasemap.js filtered() (watchlist branch) pushes { direction: "bullish", state: "TRAP_SET", regime: "ROTATION" } for any starred name with no snapshot, and PM.headBadgesHTML renders those as real LONG + 'TRAP SET' + 'ROTATION' badges right next to the 'NO ACTIVE SETUP' tag — a contradictory, direction-misleading card. specs.js does the same with a fabricated grade 'B' and '0/11' score block. Snap-less entries are real: phasemap-shared.js _migrateOnce creates snap:null entries for all legacy stars. Render a neutral placeholder card (ticker + stale tag + chart link only) instead of fake state/tier/grade.

*Files: public/js/phasemap.js, public/js/specs.js*

## 51. Pass src= on ALERTS, MY NAMES and banner chart links
**Impact 3 · Effort S · lens-pages**

chart.js has SRC_BACK entries for alerts/mynames and its comment claims those pages pass src=..., but alerts.js rowHTML builds 'chart.html?m=...&pm=1&dir=...', mynames.js builds 'chart.html?m=...&pm=1', and PM.confluenceBannerHTML likewise omits src — so the chart's back-link stays the default '← Dashboard' (chart.html line 21) and prev/next stepping never engages. Acting on an alert then hitting back dumps you on the scanner instead of the alert log you were triaging. Append src=alerts / src=mynames (and src for the banner's host page) to those hrefs.

*Files: public/js/alerts.js, public/js/mynames.js, public/js/phasemap-shared.js*

## 52. Make MY NAMES unstar re-render locally, not refetch everything
**Impact 3 · Effort S · lens-pages**

The .mn-unstar handler calls build(), which re-awaits GBSSync.syncIn() (a network round-trip) and re-fetches every scan file for every active market — vivek + phasemap latest + spec + PM.loadConfluence (which itself fetches the same three files again), so one unstar on a 3-market watchlist triggers ~12+ fetches and a full innerHTML wipe that resets scroll position mid-list. Cache scans/confl from the first build and have unstar just update the store and re-render rows from cache.

*Files: public/js/mynames.js*

## 53. Publish browser-facing scan and PhaseMap JSON compact instead of indent=2
**Impact 3 · Effort S · mobile-perf, phasemap-pkg**

scanner/output.py:11 writes with indent=2 and phasemap/output/writer.py serialise() (line 98) does the same: nasdaq_vivek.json is 1,586,221 B on disk versus ~1.03MB compact (results key alone is 959,801 B compact), and asx latest.json is 992,628 bytes vs 581,938 compact (41% smaller; nasdaq the same) — ~35-41% pure whitespace that every mobile client downloads, JSON.parses on the main thread, and the SW duplicates into Cache Storage. Dated archival snapshots can stay pretty for humans; the browser-facing files (mkt_vivek.json, phasemap latest.json, narrations.json) should use compact separators=(',',':') like write_chart_json already does — determinism is unaffected. Same slim-payload theme as the narrations sidecar split.

*Files: scanner/output.py, phasemap/output/writer.py*

## 54. Drop permanent will-change and cap row entrance animation work
**Impact 3 · Effort S · mobile-perf**

styles.css:543 puts will-change: transform on every .row-wrap permanently — the NASDAQ WATCH tab renders 159 rows (156 B+ + 3 WATCH counted from nasdaq_vivek.json), i.e. 159 pinned compositor layers on a phone; and since stagger is capped at 12 (app.js:448), rows 13+ all run the 460ms rowIn transform+opacity animation simultaneously on every tab/sort/market switch. Remove will-change (the hover transition self-promotes), animate only the first screenful, and add content-visibility:auto to .row-wrap (currently zero uses of content-visibility/contain in public/css) so offscreen rows skip layout/paint while scrolling.

*Files: public/css/styles.css, public/js/app.js*

## 55. Add eviction to the service worker data cache
**Impact 3 · Effort S · mobile-perf**

sw.js uses one cache ('vivek5-v1') and networkFirst put()s every /data/ response with no eviction: 582 NASDAQ + 498 ASX per-ticker phasemap chart files (~24KB each), scalp charts, and dated snapshots up to 1.6MB each (public/data is 50MB on disk) accumulate until a manual CACHE bump. An active chart-browsing phone accrues tens of MB of stale per-ticker JSON in Cache Storage. Split /data/ into its own cache and trim it (e.g. LRU-cap per-ticker chart entries) or skip caching data/phasemap/charts/ and data/charts/ entirely — the chart page always network-fetches them anyway.

*Files: public/sw.js*

## 56. Add viewport-fit=cover to journal, about and system pages
**Impact 3 · Effort S · mobile-perf**

The mobile bottom tab bar (styles.css:1570-1586) pads with env(safe-area-inset-bottom), but env() returns 0 unless the page's viewport meta has viewport-fit=cover — journal.html:5, about.html and system.html are the only three pages missing it (all others have it). In the installed PWA on a notched iPhone, the journal page — a daily-use page — renders its five tab targets flush under the home indicator, causing mis-taps; body padding-bottom (line 1586) is also 64px short there.

*Files: public/journal.html, public/about.html, public/system.html*

## 57. W+H4 confluence point fires without either SMA being near price
**Impact 3 · Effort S · vivek-engine**

vivek.py:145 computes confluence as |daily_sma - weekly_sma|/price <= VIVEK_NEAR_TOL — the two SMAs near EACH OTHER, though the comment (and chip 'W+H4 CONFLUENCE') claims 'near price together'; a name in play at its 3D level with Weekly+Daily clustered 10% away still collects the +1, which can be the point that tips 7->8 into A+ and hence into the bot. Require both |price-weekly| and |price-daily| <= VIVEK_NEAR_TOL * price.

*Files: scanner/vivek.py*

## 58. Update watchlist 'last seen' date when snapshots refresh
**Impact 3 · Effort S · phasemap-pkg**

PM.watch.refresh (phasemap-shared.js lines 239-246) updates e.snap on every page load while a setup is live but never touches e.date, which is set only at star time (line 233); the stale card then renders 'NO ACTIVE SETUP · last seen {entry.date}' (phasemap.js lines 97/124) — a name starred on 07-03 that stayed in the scan until yesterday reads 'last seen 2026-07-03'. Have refresh() also stamp the current run_date (and match on direction rather than results.find by ticker alone, which grabs an arbitrary record when both directions exist).

*Files: public/js/phasemap-shared.js, public/js/phasemap.js*

## 59. Stop /api/tick from leaking other users' trades in its response
**Impact 3 · Effort S · security**

runTick() returns `{ journals, closed, details }` where `details` is pushed one row per closed/scaled trade across ALL journals in KV — `{ symbol, dir, kind, fill }` (tick.js lines 228/230/247) — plus a `journals` count of how many synced journals exist. Combined with the open-by-default auth, an anonymous caller gets a live feed of every user's closing paper trades and fills. Return only aggregate counts (or scope details to the caller's own journal), never cross-journal symbol/direction/fill data.

*Files: functions/api/tick.js*

## 60. Refresh Insights fallback text — it contradicts the live artefacts
**Impact 3 · Effort S · data-correctness**

phasemap-insights.html's hand-written fallback (last touched with 07-02 figures) asserts 'NASDAQ: A+ setups hit T1 52.5% vs 41.8% for plain A — the badge earns its keep', but the current stats/nasdaq.json (generated 2026-07-12) shows 40.8% vs 40.6% — the A+ edge vanished after the universe expansion; the specs fallback (5,296 signals, random +1.8%) also drifted (now 9,951 and +2.9%). Any client whose stats fetch fails (offline PWA, blocked fetch) reads claims the latest replay contradicts. Regenerate the static block as a lens_backtest.yml step, or neutralise the hard numbers in the fallback copy.

*Files: public/phasemap-insights.html, public/js/phasemap-insights.js, public/data/phasemap/stats/nasdaq.json, .github/workflows/lens_backtest.yml*

## 61. NASDAQ Specs feed is structurally empty; page still offers the tab
**Impact 3 · Effort S · data-correctness**

nasdaq_spec.json has results: [] in every commit checked back to 07-04 (both the old 98-name universe and today's 1,430 Global Select universe), because SPEC_MAX_PRICE = 0.50 (config.py line 199) is applied in USD to an index with a ~$4 minimum-bid listing rule — the filter can never match. specs.js still renders a NASDAQ tab (MARKETS = ['asx','nasdaq']) that will always be empty. Either give NASDAQ a market-appropriate price cap (e.g. $5) or drop/label the tab so the empty state isn't mistaken for 'no setups today'.

*Files: scanner/config.py, public/data/nasdaq_spec.json, public/js/specs.js, scanner/spec_run.py*

## 62. Stop Watch view silently dropping starred names not in scan
**Impact 3 · Effort M · dashboard**

buildList (app.js:917-918) filters current scan results by isStarred, so a starred name that falls out of the next scan vanishes from the Watch view with no trace, and the watch-count badge (app.js:375, 1588) counts only in-scan stars — star 10 names, the tab may say 4. toggleStar already saves a snapshot (symbol/name/grade/dir/price, app.js:176-178) into PM.watch precisely for this: render stub rows for off-scan stars ('no longer in scan — last seen A+ LONG @ …') or at least a '+N starred names not in this scan → MY NAMES' link.

*Files: public/js/app.js*

## 63. Fix measure/OHLC/drawings desync on live-streamed charts
**Impact 3 · Effort M · chart**

Every chart tool reads tfs[curTF].candles — updateOHLC (chart.js:1619), timeAtLogical for measure spans/dates (1854), drawKey persistence (1993) — but on the live crypto path the visible data is makeLive's 1000 streamed bars (KEEP=1000, ~2158) while tfs['1H'] holds barsToTF's static 120-bar slice, so measure dates/spans and prev-close %-change are computed against the wrong bars; live.switchTo (2241) also changes interval without updating curTF, so 15M drawings save under the ':1H' key and PER_BAR_DAYS falls back 4x off. Either point the tool helpers at the live controller's bar array, or (if the fallback-hijack fix removes the last live-stream surface) this folds into the chart.js dead-code sweep.

*Files: public/js/chart.js*

## 64. Hydrate journal.js sizing constants (incl. equity) from bot_rules.json instead of a hardcoded mirror
**Impact 3 · Effort M · journal-bot, data-correctness**

journal.js lines 43-49 hardcode a second copy of the bot's numbers — EQUITY = 10000, RISK_PCT = 0.35, RISK_MIN = 0.25, RISK_MAX = 0.5, LEVERAGE {5,5,3}, COMMISSION/SLIPPAGE bps, deriving START_CAPITAL = 30k — with a comment 'mirrors scanner/broker/vivek_bot.py + config', duplicating scanner/config.py (VIVEK_BOT_ACCOUNT_EQUITY = 10_000, VIVEK_BOT_RISK_PCT = 0.35). This is the exact double-hardcoding bot_rules.json was published to kill (bot.js and the SYSTEM page already hydrate from it; journal.js doesn't even warn), and these constants size every manual trade's risk_usd, so drift directly mis-states $ P&L. bot_rules.json doesn't even carry an equity field to read, and bot.js only reconciles 3 of ~20 published keys (risk_pct/max_positions/min_rr), reporting drift as a console.warn nobody sees. Add account equity to run.py's publish dict, hydrate journal.js from bot_rules.json, and surface drift as a visible banner.

*Files: public/js/journal.js, public/data/bot_rules.json, scanner/run.py, public/js/bot.js*

## 65. Show open unrealized P&L in the comparison overview
**Impact 3 · Effort M · journal-bot**

renderComparison (journal.js lines 630-638) builds every row from CLOSED trades only — with the live book at 24 open / 2 closed, 'Account value', 'Total $' and 'who's ahead' reflect two stopped-out trades and ignore the entire working book, even though bot open rows already carry server-marked unreal_usd (and Me rows are priced every 20s). Add an 'Open P&L' row (and/or a marked-to-market account value) so the daily glance actually answers who's ahead.

*Files: public/js/journal.js, public/journal.html*

## 66. Reclaim 1.7GB local git garbage; curb 24MB-per-night chart churn
**Impact 3 · Effort M · ci-pipeline**

git count-objects -v shows the local .git is 3.5GB: a 1.77GB pack (matches GitHub diskUsage 1.83GB) plus 1.63GB of garbage — 32 orphaned .idx files with no .pack and a leftover tmp_pack_AYKhvB from an aborted gc/fetch; 'git gc --prune=now' reclaims that immediately. History growth is driven by 382 'data:' commits in 30 days: each of 209 scan commits rewrites ~2.9MB (asx_vivek 1.29MB + nasdaq_vivek 1.59MB), and each nightly phasemap commit rewrites the 24MB charts tree (1,121 per-ticker JSONs) plus ~4MB of snapshots. CI is insulated (checkout@v4 is depth-1) but every local session pays via the mandated git-fetch-first rule. Move per-ticker chart JSON to Cloudflare KV/R2 (the site already has Functions) or squash the data history periodically.

*Files: .git, public/data/phasemap/charts, .github/workflows/phasemap.yml*

## 67. Extract the 6 duplicated commit-race retry loops into a composite action
**Impact 3 · Effort M · ci-pipeline**

The same ~25-line fetch/reset/rm/checkout/push retry loop is copy-pasted in scan.yml:196, phasemap.yml:135, crypto_bot.yml:83, lens_backtest.yml:69 and twice-effectively in vivek_backtest.yml:62 (commit_push), and the copies have already drifted: vivek_backtest's version omits the 'git rm' step, and PATHS scoping differs per file (the cause of the revert-race finding). Meanwhile close_position.yml:70 — a user-initiated trading action — has NO retry at all, just 'git pull --rebase; git push' over generated public/data, exactly the modify/delete-conflict pattern the other workflows' comments warn about; one mid-scan race and the manual close silently fails. A composite action (.github/actions/data-push) taking 'paths' and 'message' inputs fixes drift and gives close_position the safe path.

*Files: .github/workflows/scan.yml, .github/workflows/phasemap.yml, .github/workflows/crypto_bot.yml, .github/workflows/lens_backtest.yml, .github/workflows/vivek_backtest.yml, .github/workflows/close_position.yml*

## 68. Add rate limiting to the price/quote proxies
**Impact 3 · Effort M · security**

price.js and quote.js do no throttling at all (no JOURNAL_KV use) — they validate the symbol regex but then proxy freely to Yahoo/Binance. The site is public, so anyone can use it as a free unlimited market-data relay; sustained hammering gets the shared Cloudflare Pages egress IP rate-limited or banned by Yahoo/Binance, which silently breaks live prices and charts for every real user. Apply a per-IP KV cooldown (mirroring the scan.js pattern) to both proxies.

*Files: functions/api/price.js, functions/api/quote.js*

## 69. Fix the racy, bypassable daily-cap counters in scan/close
**Impact 3 · Effort M · security**

Both limiters do a non-atomic read-modify-write: `used = parseInt(await KV.get(dayKey)||'0'); ... KV.put(dayKey, String(used+1))` (scan.js 66/75, close.js 60/65). A concurrent burst all read the same `used`, all pass the DAILY_CAP check, and all dispatch — so the 40/60 caps are not enforced under load. The per-key cooldown is also trivially bypassed by rotating the key: close keys on `ratelimit:close:${symbol}` (new symbol = fresh window) and scan keys per-market (only 4 buckets). This amplifies the close.js injection finding (many crafted dispatches). Track the counter with a bounded approach that tolerates KV's lack of atomic increment (e.g. shorter windows / per-IP buckets).

*Files: functions/api/scan.js, functions/api/close.js*

## 70. Test the unified watchlist store and bot.js — zero JS coverage
**Impact 3 · Effort M · code-quality**

test.yml loads exactly three things: risk_manager.js, gbs-sync.js, and functions/api/_vivek_manage.js. phasemap-shared.js's PM.watch (lines 166-260: tombstoned un-stars, legacy gbs-lens-watchlist/gbs:watch migration, merge into the KV-synced store) mutates state that replicates to every device, and bot.js (766 lines, incl. the bot_rules.json drift warning) renders the only track record — neither has a single test. Add vm-loaded tests for watch.toggle/has/migration and the bot.js rules-drift check.

*Files: public/js/phasemap-shared.js, public/js/bot.js, .github/workflows/test.yml*

## 71. Rewrite README.md — it still describes the pre-pivot Fib scanner
**Impact 3 · Effort M · code-quality**

README (last commit 2026-07-02) documents the retired Fib pullback scoring (line 19), reversal.py as a live feature (line 36), calls journal/journal.json 'the trustworthy track record' (lines 137-138) — directly contradicting the bot-book-only decision — and gives Firebase deploy instructions (lines 168-174) though firebase.json was deleted and hosting is Cloudflare Pages. The repo front page misstates what the track record is; the CLAUDE/ROADMAP rewrite never touched it.

*Files: README.md*

## 72. Consolidate esc() (6 copies, one unsafe) and price-precision (5 copies, one divergent)
**Impact 3 · Effort M · code-quality**

esc is redefined in app.js:158, chart.js:78, journal.js:20, alerts.js:7, phasemap-shared.js:21 (no null-guard, renders 'undefined') and sectors.js:38 — which escapes only &<> and is interpolated into an attribute at line 69 (`data-countdown="${esc(ev.when)}"`), so a quote in feed data breaks out of the attribute. The dp-tier expression `a>=100?2:a>=1?3:...` appears at app.js:192, chart.js:690/1387/2541 and a divergent copy at chart.js:1934 that drops the 0.1 and 0.001 tiers — the measure-tool label shows a $0.50 price at 5dp while everything else shows 4dp. Put esc() and decimals() in one core script loaded by every page (chart.html/journal.html don't load phasemap-shared.js today, so PM.esc alone can't cover them).

*Files: public/js/sectors.js, public/js/chart.js, public/js/app.js, public/js/journal.js, public/js/alerts.js, public/js/phasemap-shared.js*

## 73. Cut the 4x full-list innerHTML re-render cascade on load
**Impact 3 · Effort L · dashboard**

On first paint renderRows runs up to 4 times — applyPayload (app.js:1146), the async confluence .then (1154), loadCaps (1232), and GBSSync.syncIn (1757) — each rebuilding every row via one innerHTML string; each rebuild replays the .46s staggered entrance animation (styles.css:546-547) and snaps any expanded detail panel shut (the 'open' class dies with the old DOM, app.js:1598), so a trade plan you're reading closes under you ~1s after opening it. Worse, rowHtml eagerly embeds detailHtmlVivek + debugDetailHtml for every row (app.js:508-513) even though debug panels are display:none for non-debug users (styles.css:1096) — the NASDAQ WATCH tab is 159 rows of that. Render detail panels lazily on first expand, patch confluence/caps/star deltas in place, and only animate on genuine list changes.

*Files: public/js/app.js, public/css/styles.css*

## 74. Give the notification bell feedback when permission is denied
**Impact 2 · Effort S · dashboard**

wireNotifyBell (app.js:1738-1745) requests permission on click, and when the browser returns 'denied' (or the user previously blocked it) the only outcome is paint() re-setting opacity to 0.45 — the bell looks like a button that does nothing, with no explanation that notifications are blocked at browser level. Surface a toast (flashScan exists but is trapped inside bind()'s scope — hoist it) saying alerts are blocked and how to re-enable, and reflect the 'denied' state in the bell's title.

*Files: public/js/app.js*

## 75. Pause live-quote polling when the tab is hidden or market closed
**Impact 2 · Effort S · chart**

startStockLive polls /api/quote every 20s forever (chart.js:1257) and the LIVE-box duration timer re-renders every 30s (~2469); there is no visibilitychange/document.hidden handling anywhere in chart.js (verified by grep), so a chart left open in a background tab or installed PWA fires ~4,300 Cloudflare Function invocations a day per tab, including all night for ASX names. Gate the interval on document.hidden and consider a slower cadence outside market hours.

*Files: public/js/chart.js*

## 76. Streamline the Specs chart boot path and honour the PhaseMap-overlay comment
**Impact 2 · Effort S · chart**

Every mode=spec chart open does two guaranteed-404 fetches before rendering: data/charts/<m>_spec/SYM.json then data/charts/<m>/SYM.json (boot, chart.js:2734-2749) — public/data/charts has no asx/nasdaq dirs at all — before finally reaching liveFallback's real data/spec_charts/ file, slowing first paint on every Specs open. Also the comment at lines 50-53 claims the PhaseMap record 'is ALWAYS fetched so zones ride along wherever a setup exists', but fetchPhaseMapRec is only called in the isVivek branch (2726), so Specs charts — the very multi-lens confluence case — never get zone bands. Route spec mode straight to fallbackFromLive and fetch the PhaseMap record there too.

*Files: public/js/chart.js*

## 77. Keep expanded SPECS rows open across re-renders
**Impact 2 · Effort S · lens-pages**

specs.js render() always rebuilds every row with the detail panel hidden, and render() is re-invoked asynchronously when PM.loadConfluence resolves (~after first paint) and on every star click — so a row you just expanded snaps shut when confluence arrives, and starring one row collapses all open rows. Track open symbols in state (e.g. a Set keyed by symbol) and restore hidden=false on rebuild.

*Files: public/js/specs.js*

## 78. Fix ABOUT's 'two timeframes' text contradicting the 3-Day level
**Impact 2 · Effort S · lens-pages**

about.html 'The setup' still says the level "is read on two timeframes — Weekly (primary...) and Daily / H4 (timing)", but two sections later 'Levels change with timeframe' says "Daily, 3-Day & Weekly each carry their own plan" (and scanner/vivek.py grades W/3D/D). The intro predates the 3-Day addition; update it to three timeframes so the rulebook page agrees with itself.

*Files: public/about.html*

## 79. Render the NEWS timestamp in Melbourne time per site convention
**Impact 2 · Effort S · lens-pages**

sectors.js formats generated_at with dt.toLocaleDateString(undefined, ...) / toLocaleTimeString(undefined, ...) — the viewer's local timezone — while the site convention (CLAUDE.md, PM.fmtMelb, used by specs.js and alerts.js) is Melbourne on screen; Discord community visitors abroad see a different clock than the 'AEST' event times shown lower on the same page. While there: the dark() helper on line 7 is dead code (theme is hardcoded "dark" in mountWidgets) and its comment still says 'terminal theme' post iOS revamp.

*Files: public/js/sectors.js, public/sectors.html*

## 80. Give PhaseMap's watchlist tab a real empty state, not dev commands
**Impact 2 · Effort S · lens-pages**

phasemap.js render() shows the generic "Nothing matches this view right now." for every view including ★ WATCHLIST, while specs.js already has the better pattern ("Nothing starred yet — hit ☆ on any row..."); a first-time user gets no hint how names arrive there. The load() failure path also prints "Run: python -m phasemap.run --market crypto" into the page — a developer command shown to community visitors; replace with a plain 'scan not available yet' message.

*Files: public/js/phasemap.js*

## 81. Publish a slim backtest summary for the Insights page
**Impact 2 · Effort S · mobile-perf**

phasemap-insights.js:19 fetches data/vivek_backtest.json (916,110 B raw, 76KB gz) but reads only vb.results and vb.params aggregates — the trades array (655,261 B, 72% of the file) is never touched by any client code (only journal.js's own data.trades, unrelated). Have the weekly backtest also write a vivek_backtest_summary.json with generated_at/params/coverage/results and point Insights at it: the page's data payload drops ~99% and the figures appear near-instantly on mobile.

*Files: public/js/phasemap-insights.js, scanner/vivek_backtest.py*

## 82. Defer head scripts; long-cache /vendor/ and /icons/ in _headers
**Impact 2 · Effort S · mobile-perf**

chart.html:16 loads vendor/lightweight-charts-4.1.3.js (160KB) as a synchronous head script, blocking chart-page first paint on mobile, and every page loads js/nav.js synchronously in head (index.html:19); marking vendor + chart.js and nav.js as defer preserves execution order (deferred scripts run in document order) while unblocking render. Separately, _headers has rules only for /js/* and /css/* (86400) — /vendor/* and /icons/* fall to the /* rule (max-age=0, must-revalidate), so the filename-versioned 160KB library revalidates on every view whenever the SW isn't controlling (first visit, private browsing); give them max-age=31536000, immutable.

*Files: public/chart.html, public/index.html, public/_headers*

## 83. Complete the manifest: shortcuts, screenshots, dedicated maskable icon
**Impact 2 · Effort S · mobile-perf**

manifest.json has only name/icons/display basics — no shortcuts (long-press app icon could jump straight to alerts.html, journal.html, phasemap.html), no screenshots (Android shows a bare install sheet instead of the rich UI), no id, and icon-512 declares purpose 'any maskable' on one asset (manifest.json:13), which the spec discourages: the chart-line glyph has no maskable safe-zone padding, so Android's circle mask can clip it. Add 3-4 shortcuts with 96px icons, two phone-form-factor screenshots, an id, and a padded icon-512-maskable.png.

*Files: public/manifest.json, public/icons/icon-512.png*

## 84. Narrative omits armed/trigger state and mis-describes SMA-anchored stops
**Impact 2 · Effort S · vivek-engine**

narrative() (vivek.py:625-651) reads identically for an ARMED A+ and a WATCH row — it says 'enter $X…' with no trigger sentence and never names the fired trigger (reclaim/retest/break) even though the bot skips retests (VIVEK_BOT_SKIP_ENTRY_TYPES=['retest']); it also asserts the stop is '(beyond the reaction)' even when _build_levels anchored it at the distant Daily-200 (the AXON case). Add one sentence of trigger state ('ARMED — reclaim closed back above the level on <trigger_bar>' vs 'WATCHING — no trigger yet'), name the entry type, and make the stop clause state its actual anchor; build_detail should carry `armed` too.

*Files: scanner/vivek.py*

## 85. Fix the 'on the CRYPTO' stats sentence in live narrations
**Impact 2 · Effort S · phasemap-pkg**

_stats_text (renderer.py lines 45-47) interpolates stats['market'] verbatim, so 4 currently-published crypto narrations end '…41% of the time on the CRYPTO.' (verified in public/data/phasemap/crypto/narrations.json). Map the market label per venue ('on the ASX' / 'on the NASDAQ' / 'in crypto') before formatting.

*Files: phasemap/narrate/renderer.py*

## 86. Use price-aware decimals and skip-unchanged writes for chart candles
**Impact 2 · Effort S · phasemap-pkg**

write_chart_json rounds every market to 8dp, so ASX files carry values like 41.46315153 (BHP.json) — ten significant digits for a stock that ticks in cents — across 1,121 files / 23MB, and the last nightly data commit rewrote 1,216 chart files (~24MB of fresh blobs into a .git already at 3.5GB). Reuse the renderer's fmt_price tiering (2dp >= $2, 3-4dp small caps, 8dp only sub-$0.10/crypto) and skip the os.replace when the serialised payload is byte-identical to the existing file; the engine reads raw frames so display rounding can't touch detection.

*Files: phasemap/run.py*

## 87. Stop weekend duplicate snapshots wasting the 7-file dated archive window
**Impact 2 · Effort S · phasemap-pkg, ci-pipeline**

Saturday/Sunday runs re-emit closed stock markets unchanged as new dated files — nasdaq 2026-07-11.json vs 2026-07-12.json differ by exactly 1 byte (1,392,591 vs 1,392,592), asx similarly — so prune_dated_snapshots(keep_last=7) (run.py:89, verified present) retains only ~5 distinct trading days while each weekend day commits ~2.9MB of near-duplicate blobs into git history; the asx dir currently holds 7 dated files at ~1.2-1.5MB each (~9.5MB) deployed to the CDN, and no public/js file references dated filenames — they serve only the backtest's archival record. Skip writing the dated copy when the market's newest bar date equals the previous dated snapshot's (crypto keeps its daily cadence), or raise keep_last to cover 7 trading days; consider moving the archive out of the deploy tree.

*Files: phasemap/run.py, phasemap/output/writer.py, public/data/phasemap/asx*

## 88. Delete scan.yml's weekend crypto cron — crypto_bot already covers it
**Impact 2 · Effort S · ci-pipeline**

scan.yml:17 runs a weekend crypto-only scan at '0 2,8,14,20 * * 0,6' (via the gate override at lines 53-58), but crypto_bot.yml:15 already runs the identical 'scanner.run --market crypto' hourly every day — including at exactly 02/08/14/20 — and both share the 'scan' concurrency group, so on weekend hours the same scan queues and runs twice back-to-back with two commits and double Yahoo load. The gate's weekend override and the extra cron are pure duplication now; deleting them also removes 8 scheduled fires/weekend competing for the repo's evidently throttled schedule budget. While there, fix the stale comment at scan.yml:43 referencing 'crypto_scalp.yml' (deleted; it's crypto_bot.yml).

*Files: .github/workflows/scan.yml, .github/workflows/crypto_bot.yml*

## 89. Fix marketcaps: dead source files, non-atomic cache write, no pruning
**Impact 2 · Effort S · ci-pipeline**

scanner/marketcaps.py:33-42 _SCAN_FILES still lists asx.json, asx_reversal.json, nasdaq.json and nasdaq_reversal.json — four retired outputs that no longer exist in public/data (verified by listing), so half the plumbing is dead and only vivek+spec files actually feed the cache. save_cache (line 70-79) writes with plain write_text, violating the repo's own atomic-write rule 7: the refresh step is continue-on-error (scan.yml:95-96) and data/market_caps.json is committed by scan.yml:184, so a crash mid-write ships a truncated JSON that load_cache (line 61-67) silently swallows into {}, resetting cap freshness for every alert. Also entries for symbols that drop off the A+/A lists are never pruned, so the cache only grows. Trim _SCAN_FILES, use temp+os.replace, and drop entries absent from the last N scans.

*Files: scanner/marketcaps.py, .github/workflows/scan.yml*

## 90. Stop returning raw upstream error bodies to the browser
**Impact 2 · Effort S · security**

Error paths echo upstream internals to the client: scan.js returns `GitHub rejected the request (${res.status}). ${detail}` and `Network error reaching GitHub: ${err}` (lines 117/127) where `detail` is 200 chars of GitHub's raw response; close.js returns `GitHub error ${res.status}: ${detail}` (line 95); quote.js/price.js return `String(err.message)` (quote.js 50, price.js 69). This leaks backend topology and GitHub API responses (which can carry token/permission hints) to any anonymous caller. Log the detail server-side and return a generic message with a status code only.

*Files: functions/api/scan.js, functions/api/close.js, functions/api/quote.js*

## 91. Add anti-framing / CSP headers to block clickjacking
**Impact 2 · Effort S · security**

public/_headers sets `X-Content-Type-Options: nosniff` but no `X-Frame-Options`/CSP `frame-ancestors` and no `Referrer-Policy`. The site can therefore be embedded in a hostile iframe and its action controls (the SCAN button → /api/scan, and the journal close-position button → /api/close) clickjacked into triggering Actions dispatches on a logged-in user's behalf. Add `X-Frame-Options: DENY` (or CSP `frame-ancestors 'none'`) and a `Referrer-Policy` to the `/*` block.

*Files: public/_headers*

## 92. Delete scanner/notify.py — 451 dead lines only a comment references
**Impact 2 · Effort S · code-quality**

Nothing imports scanner.notify; its only invocation is commented out in scan.yml (lines 168-177, marked 'retired pullback/reversal/short scans'); last touched 2026-06-24. It's the single largest dead module in scanner/ and its Telegram-digest docs linger in OPERATIONS.md. Delete the module and the commented workflow block.

*Files: scanner/notify.py, .github/workflows/scan.yml*

## 93. Delete reversal.py + analysis.py pair; fix stale --legacy-scans references
**Impact 2 · Effort S · code-quality**

No file imports reversal; analysis.py is imported only by reversal.py (reversal.py:14), so both (274 lines) are unreachable. run.py:68-70 comments that retired scanners are 'opt-in (--legacy-scans)' but argparse defines no such flag, and scripts/backup_journal.py:37 still backs up public/data/asx_reversal.json, which no longer exists in public/data/. Delete both modules, the comment, and the stale backup entry.

*Files: scanner/reversal.py, scanner/analysis.py, scanner/run.py, scripts/backup_journal.py*

## 94. Drop dead GBS_SMTP secrets block or wire --alert; decide alerts.py
**Impact 2 · Effort S · code-quality**

scan.yml lines 100-104 inject five SMTP secrets into every 30-minute scan step, but scanner/run.py only emails under --alert (lines 208-211) and no workflow or .bat passes --alert — the env block has been a no-op forever. Either add --alert to the workflow or delete the block and retire alerts.py (176 lines, now only a manually-documented command in OPERATIONS.md/README) since Discord confluence pings replaced email.

*Files: .github/workflows/scan.yml, scanner/alerts.py, scanner/run.py*

## 95. Alert history rolls off after ~25 days despite 'permanent log' billing
**Impact 2 · Effort S · data-correctness**

alert_history.json holds 352 entries spanning 2026-07-05 to 07-16 (~32/day measured), and confluence_alert.py trims to HISTORY_CAP = 800 — roughly 25 days of retention — while alerts.js line 1 sells the page as the log that 'doesn't scroll away' (CLAUDE.md calls it a permanent log) with no truncation indicator. Either archive trimmed entries to dated monthly files the page can lazy-load, or render a 'showing last N days' note when entries hit the cap.

*Files: scanner/confluence_alert.py, public/data/phasemap/alert_history.json, public/js/alerts.js*

## 96. Normalise generated_at: five writers, four timestamp formats
**Impact 2 · Effort S · data-correctness**

scan.py writes market-local offsets (nasdaq_vivek -04:00, asx +10:00, crypto +00:00), run.py and vivek_backtest.py write 'Z' via strftime, spec_run.py writes Melbourne +10:00, phasemap stats write a bare date ('2026-07-12', parsed as UTC midnight by Date.parse), and the book/journal files use 'updated_at' where scans use 'generated_at'. All currently parse, but bare dates lose 24h of precision for freshness display and the Z-vs-offset mix breaks any string-level comparison or grep. Standardise on UTC ISO with 'Z' plus one key name, keeping market-local only in tz_label for tooltips (matching the Melbourne-on-screen convention).

*Files: scanner/scan.py, scanner/run.py, scanner/spec_run.py, scanner/vivek_backtest.py, phasemap/output.py*

## 97. Add Enter/arrow keys and dedupe to the search overlay
**Impact 2 · Effort M · dashboard**

The '/' overlay is keyboard-opened but mouse-only after that: initKeyboard (app.js:1287-1321) handles only /, Escape, Ctrl+Shift+D and j/k, and the search input has no keydown handler, so typing an exact ticker and pressing Enter does nothing. A starred name that's also a VIVEK hit renders twice (graded row at 1508-1516 plus a ★ row at 1542-1547) — the dead `const seen = new Set(rows.map(() => 0))` at line 1538 looks like an unfinished dedupe. Wire Enter to open the top hit, arrows to move a highlight, and skip watchlist/journal rows whose symbol already appeared.

*Files: public/js/app.js*

## 98. Delete ~350 lines of unreachable app.js render code and a zombie interval
**Impact 2 · Effort M · dashboard**

The payload still ships pulse:12 items, so refreshPulseLive (app.js:326-333) creates a perpetual 90s setInterval whose _pulsePass early-returns every tick because #pulse-track was removed from index.html in July — dead code that still runs. Also unreachable since the app went VIVEK-only (dataFile always returns *_vivek.json, app.js:1198): detailHtmlReversal (770-827), detailHtmlGoogy (829-911), the generic detailHtml body plus heroStrip/priceStrip/chipsBar (517-589, 711-768), renderLegend's non-vivek branch with EMA_COLOR/SMA_COLOR (18-22, 344-349), the .scan-btn handler and syncPrefsUI query (143-146, 1423-1433 — zero .scan-btn elements exist in index.html), the unused bestRR (367), and the always-true `state.mode !== "pullback"` checks (475, 1509).

*Files: public/js/app.js, public/index.html*

## 99. Delete the retired scalp/reversal/short/position dead code and stale data from chart.js
**Impact 2 · Effort M · chart**

chart.js still carries branches for data files that no longer exist: modeDir '_rev'/'_short' (line 47), '_reversal'/'_short' suffixes in wireScanNav (2574) and fetchResultMeta (2687), data/scalp.json fetches (2576, 2689 — file absent from public/data), the mode!=='pullback' check (2582, mirrored in app.js:475/1551), TF_ORDER's '1M'/'3M' which no producer emits (line 16), and the entire renderPosition path (2476-2558 plus posId at 103) — no page links '?pos=' anywhere (verified). public/data/charts/ contains only a stale scalp/ dir (~3MB, last data commit 2026-06-26) still shipped to the CDN. After fixing the fallback-hijack guard, the computeScalp/barsToTF/makeLive stack (~lines 120-230, 2156-2250) has no reachable caller either — several hundred lines off the page's biggest JS file.

*Files: public/js/chart.js, public/data/charts/scalp, public/js/app.js*

## 100. Reconnect or retire the orphaned /api/close endpoint
**Impact 2 · Effort M · journal-bot**

functions/api/close.js says it 'receives a manual position-close request from the journal UI' and dispatches close_position.yml, but no file in public/ references /api/close (verified by grep) — the caller died with the retired track journal, leaving a maintained, rate-limited endpoint with zero users while the journal page offers no way to force-close a bot-book position between scans (the Close button is Me-side only). Either add a 'request close' action on Claude's open rows targeting journal_type=bot_book, or delete the dead endpoint + workflow input.

*Files: functions/api/close.js, .github/workflows/close_position.yml, public/js/journal.js*

## 101. Retire or rewire health.json and refresh debug.html's pre-pivot panels
**Impact 2 · Effort M · lens-pages, data-correctness**

public/data/health.json was last written 2026-06-27 ('data: scan' commits) and no code writes it any more, yet three consumers still read it: scripts/health_check.py check #1 compares its age against HEALTH_SCAN_STALE_WARN_H = 2 hours (permanently CRITICAL if ever run), bybit_run.py loads signal-count anomaly baselines from it, and debug.html's Scan Health section renders its lone 'scalp' entry (generated 2026-06-26, three weeks stale) with an 'OK' chip because the fetch succeeded. debug.html's Raw Scan JSON dropdown is equally pre-pivot: six of its eight options — data/asx.json, nasdaq.json, asx_reversal.json, asx_short.json, scalp.json, scalp_crypto.json — 404 (public/data actually has asx_vivek.json, nasdaq_vivek.json, crypto_vivek.json, nasdaq_spec.json, phasemap/<m>/latest.json, sectors.json, bot_rules.json). Point the freshness check at the per-market <m>_vivek.json generated_at (which is maintained), delete or regenerate health.json, refresh the dropdown to the three-lens files, and make the health chip warn on stale generated_at.

*Files: public/debug.html, public/data/health.json, scripts/health_check.py, scanner/broker/bybit_run.py*

## 102. Self-host Inter/JetBrains Mono so the installed app works offline
**Impact 2 · Effort M · mobile-perf**

All pages load 9 font weights from fonts.googleapis.com/fonts.gstatic.com (index.html:14-17), and sw.js:59 deliberately skips cross-origin requests — so the offline PWA (the stated point of sw.js) renders in system fallback fonts, and every cold mobile load pays two extra TLS connections. The sw.js woff2 cache-first rule (line 73 regex) is currently dead code because no same-origin fonts exist; dropping subset woff2 files into public/fonts/ with a local @font-face makes that rule live and removes both CDN round-trips. All 5 Inter + 4 mono weights are genuinely used (400-800 all appear in css), so keep the weights, just move them.

*Files: public/index.html, public/sw.js, public/css/styles.css*

## 103. Add deterministic phrasing variants to the narration templates
**Impact 2 · Effort M · phasemap-pkg**

The current ASX snapshot's 552 narrations collapse to just 18 skeletons once numbers are masked: 161 STALLED cards are the identical 'touched the 50% area…' sentence and 202 NASDAQ SWEPT cards are the identical 'ran the … highs' sentence with only prices swapped, so the ALL view reads like a mail-merge. Add 2-3 alternative phrasings per (state, direction) in TEMPLATES chosen by hash(ticker + sweep_date) % n — still fully deterministic and slot-filled, so the spec's no-freestyle guardrail holds.

*Files: phasemap/narrate/templates.py, phasemap/narrate/renderer.py*

## 104. Retire the write-only legacy fib journal (journal.py path)
**Impact 2 · Effort M · code-quality**

scanner/journal.py (distinct from the already-retired vivek_journal) writes journal/journal.json and public/data/journal.json, but grep finds ZERO readers of either file in public/js, HTML, or functions/ — and its only automated caller is `scanner.run --journal` in the local .bat files; both JSONs were last committed 2026-06-27. The site deploys a stale, unread journal artifact every push. Remove journal.py, tests/test_journal_pnl.py's jj section, the --journal flag, and both JSON files.

*Files: scanner/journal.py, journal/journal.json, public/data/journal.json, tests/test_journal_pnl.py*

## 105. Split chart.js data/trade layers out of the 2,758-line monolith
**Impact 2 · Effort L · code-quality**

chart.js is 148KB in one IIFE mixing at least seven concerns (its own section markers: PhaseMap overlay line 50, Binance live data 81, VIVEK plans 309, PhaseMap-only chart 582, sim buy/sell 858, Yahoo proxy 918, prev/next nav 2561); app.js adds 1,809 lines — together ~240KB unminified on a mobile PWA, and the size is why helpers keep getting re-copied (three of the five dp-tier copies are inside chart.js alone). First cut: extract the Binance/Yahoo data-fetch layer and the sim/position trade logic into separate scripts chart.html loads before chart.js.

*Files: public/js/chart.js, public/js/app.js, public/chart.html*

## 106. Drop header links duplicated by the new shared nav
**Impact 1 · Effort S · lens-pages**

mynames.html still carries explicit JOURNAL and ALERTS howto-links immediately beside the #site-nav mount, but nav.js PRIMARY already renders JOURNAL and ALERTS pills — the header now shows both destinations twice. Also phasemap-insights.html mounts #site-nav *after* its custom '← PhaseMap' / 'KEY & LEGEND' links, the reverse order of phasemap.html and specs.html, so the pill row jumps position between sibling pages. Remove the duplicates and normalise the ordering.

*Files: public/mynames.html, public/phasemap-insights.html*

## 107. Remove broken local .bat scan pipeline and stale scan.log
**Impact 1 · Effort S · code-quality**

Refresh Data.bat and scan_scheduled.bat (tracked, untouched since 2026-06-16) run `scanner.run --journal` — feeding the dead legacy journal — and the root scan.log shows the last local scheduled run crashed on 2026-06-16 (ModuleNotFoundError: pandas); scans have run in GitHub Actions since. 'Start Fib Scanner.bat' also still brands the app 'Vivek's Beta Scanner', against the CLAUDE.md naming rule. Delete the two scan .bats and scan.log; keep/rename only the local-server launcher.

*Files: Refresh Data.bat, scan_scheduled.bat, Start Fib Scanner.bat, scan.log*

---

# Found after the audit

Items discovered during ordinary work rather than by the 2026-07-16 reviewer
sweep. Same format, numbering continues.

## 108. Stop the freshness backstops from cancelling each other in the scan queue
**Impact 5 · Effort S · ops · FIXED 2026-07-28**

GitHub allows exactly ONE pending run per concurrency group: queue a second and the previously-pending one is cancelled. `scan` was applied at WORKFLOW level in scan.yml and crypto_bot.yml, so during ASX mornings four arrivals per hour (:07 scan, :22 crypto, :47 ASX backstop, :52 crypto backstop) contended for a one-slot queue while a full 3-market cycle takes 40-80 min. Whenever a scan was in progress the :47 ASX backstop went pending and the :52 crypto arrival evicted it five minutes later — deterministically, before its gate job could run a single curl. Both backstops exist to catch dropped runs; each was reliably dropping the other. Consistent with the observed record: 07-27 produced 7 scan commits against ~15 scheduled crons, and crypto_bot committed 6 times against 48 scheduled fires. The self-defeating shape is general — adding crons to a saturated one-slot queue raises the cancellation rate rather than the coverage rate.

**Fixed:** the mutex moved from workflow level onto the JOBS that write the book (`scan.scan`, `crypto_bot.crypto`). Gate jobs only curl and write nothing, so they now always execute and decide; a backstop that answers "fresh, skip" costs zero queue slots instead of evicting whatever was waiting. Mutual exclusion between writers — load-bearing now that the 30-position cap is global and two concurrent writers could each read "23 open" and both open — is unchanged. Not verifiable from this sandbox (api.github.com is proxy-blocked, so run history cannot be read directly); confirm from the Actions run list that :47/:52 runs now appear and conclude rather than vanishing.

*Files: .github/workflows/scan.yml, .github/workflows/crypto_bot.yml*

## 109. A manual close could be deleted by the scan queue with no trace
**Impact 5 · Effort S · ops · FIXED 2026-07-28 (owner: "make it re-dispatch itself if evicted")**

The #108 mechanic applied to the one workflow a human triggers by hand. `close_position.yml` held `group: scan` at WORKFLOW level, so a close dispatched while a scan was running went pending — and the next scheduled arrival (`:22`/`:47`/`:52`, four an hour during ASX mornings) cancelled the whole run. Not a failure, not a red X: a run that never existed. The operator sees a dispatch confirmation, the position stays open, and the only track record silently disagrees with what he believes he did. Worse than #108 by a wide margin, because a backstop that misses a cycle self-corrects on the next fire and a close never fires again on its own.

**Fixed** in three parts:

1. The mutex moved onto the `close` job. Mutual exclusion is unchanged — that job is the book writer — but the eviction now cancels one JOB and leaves the run alive.
2. A `redispatch` job, deliberately NOT in the group (the whole point: it has to outlive what was evicted), runs on `always() && needs.close.result == 'cancelled'` and re-dispatches the same inputs. `workflow_dispatch` is one of the two events `GITHUB_TOKEN` is permitted to raise — the anti-recursion rule exempts it — so `gh workflow run` from inside Actions genuinely starts a new run.
3. Bounds, because a retry loop on the track record is its own hazard. An `attempt` input caps the chain at 3. The job re-dispatches ONLY when the close executed zero steps, which is an eviction's signature — a human hitting Cancel on a close that was already running leaves finished steps behind, and resurrecting that would override a deliberate stop. Before re-queueing it waits (bounded ~200s) for the group's pending slot to clear, so the retry does not evict the sibling that evicted it and start a ping-pong.

`tests/test_workflow_mutex.py` (11 tests) pins all of it, including that every dispatch input is threaded through the retry — a retry that silently dropped `market` or `journal_type` would close the wrong book and look like a legitimate outcome — and that the wait loop's workflow-name filter still matches real `name:` fields.

*Files: .github/workflows/close_position.yml, tests/test_workflow_mutex.py, requirements.txt*

## 110. Fixed-notional position sizing ($5,000 x 30 slots, $150,000 book)
**Impact 5 · Effort M · bot-broker · SHIPPED 2026-07-28 (owner: "5k position moving forward on each 30 stocks and a cap of 150k")**

Not a defect — an owner decision, recorded here because it changes what every trade looks like and because the reasoning has to survive the person who wrote it.

Sizing was risk-derived: 0.35% of a $10,000 equity, i.e. the same ~$35 risked on every trade with the position size floating on the stop distance. It is now the mirror image — a fixed $5,000 of notional per position, 30 slots, $150,000 total.

**The trade-off, stated plainly: the dollars RISKED per trade now vary.** A 2% stop on $5,000 risks $100; a 12% stop risks $600. The stop-width rules bound it to roughly $50-$1,250, typically $250-$500. That is the direct consequence of fixing size instead of risk, and it must not be "fixed" later by re-clamping `risk_pct` in fixed mode — `tests/test_fixed_notional.py` (22 tests) pins the behaviour and says so in its docstring. **Position COUNT, not position size, is the risk dial now.**

**`VIVEK_BOT_ACCOUNT_EQUITY` moved 10,000 -> 150,000, which was forced, not incidental.** Equity no longer sizes positions but still scales the daily/weekly loss guards and the leverage ceiling; leaving it at 10,000 against a $150,000 book would have set the daily kill switch at $300 on 30 live positions. The move is what broke `test_kill_switch_book.py::test_run_standalone_fires_on_book_loss` (an $800 loss stopped tripping a limit that had become $4,500) — both affected tests now pin equity themselves, because they test the guard arithmetic, not the book size.

`VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL = 150_000` is the dollar twin of the 30-slot cap and is enforced in `decide()` the same way `max_open_total` is: **off unless the runner passes it together with `notional_elsewhere`**, and fail-closed if a sibling market file is unreadable. Defaulting it from config would have silently capped the backtester and every other caller that never supplies the cross-market figure, evaluating a real ceiling against a fabricated zero. Setting `VIVEK_BOT_POSITION_NOTIONAL = 0` restores the risk-% path exactly, and a test pins that revert route.

*Files: scanner/config.py, scanner/broker/vivek_bot.py, scanner/broker/vivek_run.py, scanner/run.py, public/js/journal.js, public/js/bot.js, public/journal.html, public/system.html, tests/test_fixed_notional.py, tests/test_vivek.py, tests/test_kill_switch_book.py*

## 111. confluence.yml is the last workflow-scoped member of the scan mutex
**Impact 2 · Effort S · ops**

After #108 and #109, `confluence.yml` (daily 08:45 UTC) is the only remaining `group: scan` block at workflow level, so it is still deleted outright rather than cancelled-in-place if anything queues while it waits — one lost confluence ping, and no run in the list to explain it. Left alone deliberately: unlike a close it is not a human act on the track record, and unlike a backstop it has no cheap gate job to protect, so job-scoping alone changes how it dies rather than whether it does. Fixing it properly means either the #109 re-dispatch pattern or accepting the miss; it also evicts others when IT queues, which job-scoping does not address either.

*Files: .github/workflows/confluence.yml*

## 112. Two held ASX positions use a taxonomy the sector cap can't reconcile
**Impact 4 · Effort S · bot-broker · OWNER DECISION**

Found while verifying the #38 back-fill. SUN carries `sector: "Insurance"` and AFG `"Financial Services"` — Yahoo-style labels — while the ASX universe file this market scans from ships GICS and says `"Financials"` for both of those exact symbols, which is also what the back-fill wrote onto CCP. The per-sector cap buckets on the string, so it currently reads three separate sectors where there is one, and would allow 3 Financials + 3 Insurance + 3 Financial Services = **nine correlated financials** in a 30-slot book while reporting the cap as enforced.

Only these two rows are affected: the 8 rows back-filled on 2026-07-28 came straight from `data/universe_cache/asx.json` and match it exactly, and the 7 NASDAQ rows match `data/sector_map.json` exactly. SUN and AFG predate that path and were seeded from whatever their opening scan row carried.

**Not fixed autonomously** — rewriting a non-blank sector changes which trades get taken, and the #38 authorisation covered filling blanks. The fix if the owner wants it is one rule, not a synonym table: *the market's own universe file is the canonical taxonomy, so a stored sector that disagrees with it for the same symbol loses.* That is the same principle already in `enrich_rows` (the universe beats the best-effort cache), applied to disagreement rather than to absence. Effect would be to tighten the cap, never loosen it.

**Made visible meanwhile:** `sectorcache.diverging(positions, rows)` returns `SYM=stored->universe` for every held position whose sector the current scan contradicts, and `vivek_run.run_market` logs it as a WARNING naming the symbols on every scan. Blank-filling is unaffected — that fills nothing-shaped holes, this would overwrite an answer.

*Files: scanner/sectorcache.py, scanner/broker/vivek_run.py, tests/test_sector_cache.py*
