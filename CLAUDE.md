# Vivek 5.0 — CLAUDE.md

This file is read automatically at the start of every Claude Code session.
Read it fully before touching any code. (Rewritten 2026-07-10 — the previous
version predated the three-lens pivot and half its claims were stale.)

---

## What this project is

A **multi-lens trading scanner** + Claude's paper-trade bot book (PAPER ONLY —
the Bybit/Alpaca clients survive only as the kill switch's flatten path). Owner: Vivek (Melbourne,
Australia). Brand name everywhere: **Vivek 5.0** — never "Googy Boys
Scanner", never "Vivek's Beta Scanner" as the primary name ("BETA SCANNER"
as a subtitle under the wordmark is fine).

**Personal use only (owner, 2026-09-28).** Everything here is for the owner's
own trading. No disclaimers are needed anywhere (the Discord digest included),
there is no paid or Discord business goal, and compliance or "reads like
advice" flags are not wanted.

**The lenses** (see ROADMAP.md for the honest project state). All three feed
the confluence machinery. (A fourth, TURTLE, existed 2026-08-21 → 2026-09-17
and was REMOVED ENTIRELY — see the TURTLE note near the end.) Two more lenses
are REPORT-ONLY and outside confluence: **MOMENTUM** (`scanner/momentum/`,
`momentum.html`, `momentum.yml`) — a 20/50/200-EMA + RSI-divergence screen
published per market after that market's close — and **IGNITION**
(`scanner/ignition/`, coil → breakout on crypto and, since 2026-09-29, the
ASX and, since 2026-10-08, NASDAQ; see IGNITION below).

1. **VIVEK** (`scanner/vivek.py` + `scan.py`) — the core lens. Price
   *reacting* at its 200-SMA on Weekly / 3-Day / Daily(H4-proxy) levels.
   Grades A+/A/B+/WATCH; per-timeframe plans (entry/SL/TP1-3); three entry
   types (reclaim / retest / break); armed vs watching.
2. **PhaseMap** (`phasemap/` package) — the trap lens. Liquidity sweep →
   displacement, zone-based (zones are ALWAYS bands, never single prices).
   **The owner's master spec doc is the single source of truth — NEVER
   change detection maths or zone definitions without asking him.** Bump
   `RULESET_VERSION` in `phasemap/config.py` on ANY parameter change.
   Deterministic output; no LLM anywhere in the scan path.
3. **Specs** (`scanner/spec.py` via `spec_run.py`) — the discovery lens.
   Sub-$0.50 names breaking out of a base on a ≥3× volume spike. Its own
   backtest says it's a shortlist generator, NOT an entry system.

**Multi-lens confluence** is the headline feature: direction-aligned 2+/3-lens
agreements get banners everywhere, a permanent ALERTS page log
(`scanner/confluence_alert.py`, state-deduped — push DELIVERY REMOVED
2026-08-27, see ALERT DELIVERY below) and the deck's WHAT NEEDS MY EYES strip.
(The ★ MY NAMES page was REMOVED 2026-09-21 with the stars — see MY JOURNAL.)

---

## Tech stack

| Layer | What |
|-------|------|
| Scanner engines | Python (`scanner/`, `phasemap/`) — run in GitHub Actions |
| Frontend | Vanilla JS + CSS — static site on **Cloudflare Pages** (`public/`), iOS-style dark theme, PWA with service worker |
| Backend API | Cloudflare Pages Functions (`functions/api/*.js`) — CF **Workers runtime, NOT Node** (no `require`, no fs; env via `context.env`) |
| Scheduler | GitHub Actions cron (`.github/workflows/`) |
| Data source | Stocks: `yfinance` (pinned) — free, ~15 min delayed, survivor-biased history; production-grade provider (EODHD/Norgate) is an open owner decision. **Crypto (since 2026-09-28): exchange daily klines** — Binance's market-data mirror first, then Coinbase, Yahoo only for coins no exchange lists — via `data.fetch()` (see CRYPTO DATA SOURCE) |
| Broker | PAPER ONLY. The scalp-era Bybit execution bot (bracket/reconcile/run) and the AI BOT page were REMOVED 2026-09-17 (see AI BOT below). `bybit_client.py`/`alpaca_client.py` survive only as the kill switch's flatten path |

---

## Repository layout (current)

```
scanner/               VIVEK + Specs engines, bot, alerts
  config.py            ALL tunable constants — never hardcode magic numbers
  vivek.py             VIVEK 5.0 engine (levels W/3D/D, plans, grading, narrative)
  scan.py              scan_vivek_market → public/data/<m>_vivek.json
  run.py               CLI: python -m scanner.run [--market ...]; publishes bot_rules.json
                       (`bot_rules_payload()` — resize_book.yml calls it too)
  spec.py + spec_run.py    Specs lens (asx+nasdaq) → <m>_spec.json
  ignition/            IGNITION lens (crypto + ASX + NASDAQ, REPORT-ONLY): coil -> ignition
                       screen + replay → public/data/ignition/ (see IGNITION)
  confluence_alert.py  multi-lens confluence engine: ALERTS page history log
                       + push-owed state (delivery removed 2026-08-27)
  vivek_backtest.py    walk-forward replay (1D/3D/1W, level_tf cohorts)
  vivek_journal.py     RETIRED as a journal (2026-07-09) — module kept: the
                       backtester + bot runner import its trade primitives
                       (notify/alerts/pulse + broker paper_run/bracket_order/
                       reconcile DELETED 2026-07-20 — see git history)
  universe.py          ASX full (~2,000) · NASDAQ Global Select (~1,430) · crypto top-200 (paged) + extras, pegs filtered
  conviction.py        HIGH CONVICTION — the one four-cell definition every
                       Python reader imports; app.js/chart.js carry the same
                       table as a JSON literal, parity test-pinned (2026-09-20)
  broker/              vivek_bot.py (decision engine: A/A+ four-cell longs, 60 open
                       TOTAL across all markets at $2,500 each, one/symbol, 6/sector
                       PER MARKET — SIZING 2, live from its merge), vivek_run.py (paper book),
                       kill_switch (+ bybit_client/alpaca_client for its
                       flatten path), alert_router/alert_dispatch, vivek_guard.
                       The scalp-era risk stack (risk_manager, circuit_breaker,
                       pre_trade_check, bybit_run/bracket/reconcile, ...) was
                       REMOVED 2026-09-17 with the AI BOT page
phasemap/              PhaseMap package (engine/narrate/output/backtest/tests)
public/                the site (see "Frontend rules")
functions/api/         scan.js + close.js + morning_plays.js (Actions dispatch,
                       KV rate-limited), heartbeat/health, price/quote proxies
                       (journal.js/tick.js/_vivek_manage.js went 2026-09-21)
tests/ + phasemap/tests/ + test/*.test.js   pytest + JS suites — EVERY push (test.yml); counts drift, read test.yml
journal/               bot book + state files committed by Actions
data_universe/         bundled ticker CSVs (fallbacks)
scripts/               CI-side one-offs and helpers, NOT imported by the engine
  reco_note.py         daily auto-written commentary (reco_note.yml)
  resize_book_notional.py      restates the OPEN book at the current fixed
                       notional (run 2026-07-28 → $5,000; → $2,500 by resize_book.yml
                       at the SIZING 2 merge). Dry by default, idempotent, --apply/--check/--kick
```

## Workflows (current)

| Workflow | Schedule | Does |
|---|---|---|
| dispatch_scan.yml | on push to itself or `.github/scan-kick` | turns a PUSH into a real `workflow_dispatch` of scan.yml (`market=all`). **The only way a cloud Claude session can trigger a scan** — these sessions can push but cannot reach api.github.com or POST to /api/scan. Touch `.github/scan-kick`, push, done. `permissions: actions: write`; GITHUB_TOKEN-created dispatches DO start runs (the documented exception to the no-recursive-workflows guard) |
| test.yml | every push/PR | pytest + every `test/*.test.js` suite (count them in test.yml, not here) + syntax gate. A new `test/*.test.js` needs its own step here or it never runs — **and since 2026-07-28 that rule is a GATE, not a convention** (`test_screenshot_determinism.py::test_every_javascript_suite_has_a_step_in_the_workflow` fails the push instead of letting the suite pass locally and never run). New `tests/*.py` files need NO registration (`pytest` collects the directory). The path filter now includes `scripts/**`, `pytest.ini`, `public/css/**`, `public/*.html` and `.github/workflows/**` — each was read by a suite that did not run when you edited it (TOP100 #48) — plus `.github/resize-kick` (2026-09-27: `tests/test_resize_book_workflow.py` reads it, and the push that touches it is the one that restates the open book) |
| scan.yml | **MARKET HOURS ONLY (2026-09-21)** — the crons are a deliberate SUPERSET and the gate job (`scripts/scan_gate.py`, stdlib-only, reads config directly; 2026-10-05) asks the tz database, in the market's own calendar, whether now is inside that market's window (`config.MARKET_SCAN_WINDOWS`: ASX 11:00–16:45 Sydney, NASDAQ 10:30–16:45 New York, weekdays) — or, with no market live, whether one is shut since today's close (`MORNING_PLAYS_SLOT_GATE`, 16:40 Sydney / 16:05 NY) with no scan since: the MISSED CLOSING SCAN, caught up by the next cron or heal (never alongside a live market, so a failing catch-up cannot discard a live scan). At most one stock market per scheduled run, never crypto; a gate crash fails open (`asx nasdaq` on a schedule). Delivers 7 ASX scans 11:07→16:41 and 7 NASDAQ 10:37→16:07 local in every DST regime (three occur; AEST+EST never does) — on paper: GitHub has created ZERO runs of the ASX closing crons since 18 Sep (see THE ASX CLOSE below for the on-time closing scan). `:47` closing backstops per market — DEAD until 2026-10-05 (they land 16:47, past the old gate's window). A HEARTBEAT dispatch (`reason=heartbeat`, market=all) is narrowed to crypto + the due stock market: until 2026-10-05 every heal rescanned ASX+NASDAQ round the clock (65 of 83 heal-started ASX scans 28 Sep–5 Oct ran shut). GitHub's scheduler ran only 6 of those 89 ASX scans — the heartbeat drives most in-session coverage. **THE REAL CLOCK IS cron-job.org (2026-10-06, owner: "I want reliability ... I don't want to pay")**: in the week to 5 Oct GitHub's crons ran 5/35 ASX, 8/35 NASDAQ and 41/~168 crypto scans, so five free cron-job.org jobs ping `/api/heartbeat?market=<m>&stale_min=N` (job ids 8587588 ASX hourly :10 11–16 Sydney, 8587590 ASX close 16:40 Sydney, 8587599 crypto :22 hourly UTC stale_min=45, 8587591 NASDAQ open 10:40 New York, 8587598 NASDAQ hourly :10 11–16 New York; all weekdays except crypto). Each job runs in its MARKET's own timezone (DST-proof), the heartbeat dispatches only when that market's `<m>_prices.json` is stale, and scan_gate keeps it in hours. The heal daily budget is PER MARKET (30) since then, so hourly crypto cannot starve ASX. GitHub's crons stay as a free backup. Manage with ops.yml `cronjob-*`. Pins: `tests/test_scan_windows.py`, `test/heartbeat.test.js` | VIVEK scans + bot book + confluence alert |
| crypto_bot.yml | `:22` + `:52`, EVERY hour, EVERY day (2026-09-21 — the weekday window-ownership gate is GONE; it only existed because scan.yml used to scan crypto too). `:52` is a freshness backstop that skips when fresh | crypto scan + crypto slice of the bot book |
| confluence.yml | `workflow_run` after "PhaseMap nightly scan" completes (2026-10-05) + daily 08:45 UTC as a backstop | post-nightly confluence ping (scan group SOLELY owns the dedupe state). The cron alone started BEFORE phasemap's commit on 12 of 15 nights (both fire late and the 15-min gap shrinks to ~5), so the nightly alignments waited for the next session's scan. Checkout stays `ref: github.ref` (= main under workflow_run), never the triggering run's head_sha (pinned) |
| backup_book.yml | daily 21:35 UTC + 23:35 backstop | snapshots the bot book + journal state into `backups/` (keep 30) + uploads the set as a 90-day run artifact (off-tree copy, 2026-07-21). The 23:35 cron is a SCHEDULER-DROP BACKSTOP (2026-08-27 — the 2026-08-26 21:35 firing was dropped entirely): a local gate skips it when the newest `backups/<stamp>` dir is at/after the most recent 21:00Z SLOT (2026-10-05 — it used to match the UTC calendar DATE, so with the primary landing after UTC midnight a dropped primary + on-time backstop left a ~48h gap, and 09-05→09-28 took two snapshots a night, halving the 30-keep history) |
| reco_note.yml | daily 08:52 UTC | auto-writes `public/data/reco_note.json` from committed scan data (`scripts/reco_note.py`, author "auto"); never overwrites a same-day hand-written Claude note; commentary only, outside every signal path (2026-07-23 — cloud scheduled Claude sessions can't reach the push token, so CI owns the daily cadence) |
| phasemap.yml | nightly 08:30 UTC | PhaseMap + Specs + schema gate (SLIM latest.json + narrations sidecar); no confluence here. GATE COLLECTS, COMMIT ALWAYS LANDS (2026-09-01 — run #63): the must-change asserts used to abort the commit step under bash -e, so one Yahoo-starved market (crypto, byte-unchanged latest.json) discarded ASX's + NASDAQ's staged output with it. The asserts now collect into GATE_FAILED, the commit/push of whatever staged happens regardless, and the step exits red at the end — same alarm, no discard (the turtle.yml 2026-08-21 pattern). Pinned in test_workflow_hardening.py |
| lens_backtest.yml | weekly Sun | PhaseMap/Specs/VIVEK replays → owns `public/data/vivek_backtest.json` (Insights reads it) |
| vivek_backtest.yml | monthly 1st | LONG-ONLY evidence → `vivek_backtest_longonly.json` ONLY |
| kill_switch.yml | half-hourly 24/7 | loss check on the BOT BOOK per market, open positions re-priced with LIVE quotes (fallback: last-scan marks); broker flatten only if keys set. Hosts the freshness watchdog (scanner/watchdog.py) |
| close_position.yml | manual | journal_type=bot closes a BOT BOOK position (the real track record); swing/scalp = legacy journals. `batch` closes up to 60 in one run (= the book cap since 2026-09-27; was 30 — see SIZING 2). Auto re-dispatches itself (max 3) if the scan mutex evicts it — 2026-07-28, see below |
| resize_book.yml | push to main touching `.github/resize-kick` + manual (`apply` defaults FALSE = dry run; apply only from main) — NO cron | ONE-SHOT open-book restatement (2026-09-27, owner-approved — see SIZING 2). `preview` job OUTSIDE the mutex runs `resize_book_notional.py --check --kick` into the step summary: 0 = green no-op, 3 = rows pending, anything else red (a traceback's 1 never reads as "pending"; 4 = an off-target row the script cannot restate, named). `resize` job JOB-scoped in `group: scan`, `ref: main`, 5 attempts that each `git fetch` + `reset --hard origin/main` and RE-RUN the idempotent resize (regenerate, never replay), a `--check` postcondition re-read off disk, `vivek_run --verify`, then REPUBLISHES `public/data/bot_rules.json` from the same checkout (`scanner.run.bot_rules_payload()`, run.py's own writer) so the restated book and the rules describing it land in ONE commit (2026-09-28); one-path `git add` with no `\|\| true`, assert_staged on the three CANONICAL books only (the combined pair and bot_rules.json are DERIVED — staged and diff-checked, never gated: bot_rules.json's `generated_at` would satisfy an any-of gate on every run). `evicted` job turns a cancelled/evicted resize RED with the remedy — deliberately NO auto-redispatch (nothing is lost, only delayed, and the delay is fail-safe) and NO WATCHDOG_RUNS entry (a one-shot must not ring for ever). Pins: `tests/test_resize_book_workflow.py` |
| test_alerts.yml | manual | alert-path self-test: forces one test message through every configured channel (`watchdog --test-alert`); run after any alert-secret change, read the job summary |
| evidence_brief.yml | daily 21:00 UTC (7am/8am Melb) | runs `scripts/evidence_brief.py` byte-untouched and delivers the printed brief to the step summary (the Discord leg was removed 2026-08-27 with the whole channel). READ-ONLY: contents read, no git, NOT in the scan mutex, no assert_staged/WATCHDOG entry (it commits nothing). The script's exit 1 ("brief names an ISSUE") stays a GREEN run — the issue reaches the owner inside the brief; the watchdog owns staleness alarms. Pins: `tests/test_evidence_brief_workflow.py` |
| morning_plays.yml | backstop crons in UTC behind the cron-job.org ladder: `58 5`+`58 6` (ASX, 16:58 local, after the ~16:40 closing scan commits — one per DST regime) plus `50 7`+`50 8` as late backstops · `50 21`+`50 22` (NASDAQ+Crypto, after the post-close scan), Mon–Fri — gated on POST-CLOSE data, see MORNING PLAYS | `scripts/morning_plays.py` posts the day's HIGH-CONVICTION VIVEK 5.0 plays (LONG only, no funds/REITs; clean `SYMBOL -> label` text) to Discord (owner ask 2026-09-08, rescheduled 2026-09-09). TWO market-specific slots ~30 min after each close: ASX in the arvo, NASDAQ+Crypto next morning. DELAY-PROOF (rebuilt 2026-09-10 — the v1 hour-exact gate missed a whole day when GitHub ran the crons 2–5h late): each cron maps to a slot NAME (`--slot`, via `github.event.schedule`) and sends when Melbourne is at/past target AND a per-day marker says it hasn't gone out today, so a late cron still lands and the second DST cron can't double. 7-day ticker de-dup + per-day slot markers share a `.cache` state file (actions/cache, watchdog pattern) — READ-ONLY: reads the COMMITTED `<market>_vivek.json`, no scan/Yahoo/mutex, no git/assert_staged/WATCHDOG (evidence_brief pattern). Its OWN secret `DISCORD_MORNING_WEBHOOK_URL` (NOT the removed alert webhook — see MORNING PLAYS below); absent = warn + exit 0. Delivery failure = exit 1 (loud). Pins: `tests/test_morning_plays.py` |
| ops.yml | manual only | **Claude's standing access (2026-09-10, owner: "you should be able to set up jobs and all to make this hands off").** `scripts/ops.py` runs on a runner (which can reach APIs the cloud session's proxy refuses — api.cron-job.org and api.cloudflare.com both answer HTTP 000 from a session) and Claude dispatches it via the GitHub MCP with an `action` (`cronjob-list/get/history/create/update/delete`, `cf-list-vars/set-var/delete-var/redeploy`, and two READ-ONLY checks added 2026-09-28 after "merged" was mistaken for "live": `cf-deployments` — the last production deploys with the commit each built and its status — and `site-probe`, no credentials, the asset `?v=` tags / version.json / Ignition stamp the LIVE site serves; optional `paths` = up to 10 SITE-RELATIVE GETs, e.g. `/api/price?...`, each summarised as status/ok/source/bars/error) + JSON `args`, then reads the job log. Secrets: `CRONJOB_API_KEY`, `CLOUDFLARE_API_TOKEN` (Pages: Edit), `CLOUDFLARE_ACCOUNT_ID`. REDACTED OUTPUT IS THE ONLY SECURITY PROPERTY: secret values, caller-supplied values and `key=` query params are masked, and `cf-list-vars` prints names + types NEVER values (Cloudflare returns plain_text values in the clear; `GH_DISPATCH_TOKEN` is stored as Text). Read-only to the repo, no git, own concurrency group, no assert_staged/WATCHDOG. **A FAILED action is a GREEN run on purpose (2026-10-06)**: only Claude dispatches ops and reads its log, so a red run only mailed the owner "Run failed: Ops" about Claude's own slip (run #32 passed `job_id` for `id`; `job_id`/`jobId` are now accepted too). Read the `OPS RESULT: OK` / `OPS RESULT: FAILED (exit N)` line that ends the step's output and the step summary (a failure also raises an `::error::` annotation naming the action, never the args), not the run's colour: the run conclusion, the step conclusion and `get_job_logs(failed_only)` all say success now. After any MUTATING action (`cronjob-create/update/delete`, `cf-set-var/delete-var/redeploy`) confirm it with a read-back (`cronjob-get` / `cf-list-vars` / `cf-deployments`) before reporting it done, and pass a credential failure (missing secret, HTTP 401/403) on to the owner yourself, since no email will. Exit codes: 0 ok, 1 HTTP non-2xx, 2 bad args or missing secret, 3 network, 4 an unexpected exception (printed redacted, never as a raw traceback). Note the one honest limit: `args` for `cf-set-var` carries the value through the run's dispatch inputs, which GitHub records. Pins: `tests/test_ops.py` |
| commit_sentinel.yml | every push to main | detection half of branch protection (2026-08-20): checks the AUTHENTICATED PUSHER + every commit's author/committer email against the identity set observed on main's real history (`scripts/commit_sentinel.py`); flags force-pushes and truncated payloads too. DETECTION ONLY — anomaly = green run + step summary + `::warning::` on the run page (the Discord leg was removed 2026-08-27), never blocks/reverts. NOT in the scan mutex, contents: read, no path filter (the quiet-edit scenario IS a data-file edit). Honest limit recorded in both files: the 2026-08-20 incident commit wore the owner's identity end-to-end, so a perfectly disguised integration is branch protection's job, not this one's. Pins: `tests/test_commit_sentinel.py` |
| alert_returns.yml | daily 22:20 UTC + 23:50 backstop | the EDGE PIPELINE (grown from one script to four, batch-100 2026-08-20), in order: `alert_returns.py` (ingests alignments + stamps 1/5/10/20-SESSION forward returns into `data/alert_forward_returns.json`, enriches blank-only context fields frozen at first write) → `edge_rosters.py` (daily plain-A+ roster baseline, `data/edge_rosters.json`, same imported machinery/plumbing) → `book_stress.py` (uniform-shock tide table vs real stops, `public/data/book_stress.json` — the journal's tide line reads it) → `alert_edge_report.py` printed into the STEP SUMMARY daily (read-only, pinned) → `edge_summary.py` (dedup aligned-vs-baseline headline as `public/data/edge_summary.json`, math IMPORTED from the report, never re-typed) (the Sunday-only Discord digest leg was removed 2026-08-27 with the whole channel — the daily STEP SUMMARY is the delivery). A SIDE LEDGER on purpose, twice over: alert_history.json is a rolling 800-cap window already evicting at ~14 days (a 20-session return can never mature in it) AND is written inside the scan mutex (a second writer would race it) — so the scripts READ the history, never write it (test-pinned). Idempotent; returns FROZEN at first measurement — so `stamp()` reads COMPLETED BARS ONLY (2026-10-05): a bar dated on/after the market-local today is ignored until `config.ALERT_RETURNS_BAR_FINAL` (ASX 16:45 Sydney, NASDAQ 16:30 NY — close + delayed feed; crypto never reads today's UTC bar), because the run lands 10:18–13:52 Sydney and had frozen ~1,900 of 4,900 ASX alert stamps (7,700 of 14,755 roster stamps) on the still-forming intraday bar, sign flipped on dozens. FORWARD-ONLY FIX — the contaminated rows are still live and feed edge_summary; clearing/re-stamping them is an OWNER decision, not done; the 23:50 cron is a SCHEDULER-DROP BACKSTOP (2026-08-27) that skips when a ledger's `updated_at` on main is at/after the most recent 22:00Z slot (2026-10-05 — was "any scheduled success since 00:00 UTC" via the Actions API, which counted yesterday's late runs and its own skip-runs; `actions: read` dropped), fail-open; each staged one-pathspec-at-a-time with `\|\| true` paired to the ANY-OF assert_staged; WATCHDOG_RUNS 26h. Pins: `tests/test_alert_returns.py`, `test_edge_rosters.py`, `test_book_stress.py`, `test_alert_edge_report.py`, `test_edge_summary.py` |
| ignition.yml | `14 0` UTC (the new completed crypto bar) + `14 1,2` backstops (skip once today's file is on the branch) + `44 5,11,17,21` intraday; push to `.github/ignition-kick`; manual (`backtest`, `dry_run`) | IGNITION lens (REPORT-ONLY, crypto): screens the coil → ignition shape into `public/data/ignition/crypto.json` + its mini-chart sidecar `crypto_charts.json`; a kick or `backtest: true` also replays full history into `crypto_backtest.json`, committed back to the PUSHED branch (never hard-coded main). Own concurrency group per branch, not in the scan mutex; assert_staged per reported path; no WATCHDOG entry by decision. Pins: `tests/test_ignition_workflow.py` |
| ignition_asx.yml | `24 6` UTC Mon–Fri (after the ASX close in both DST regimes) + `24 7,9` backstops (skip once a file generated after today's close is on the branch — `scripts/ignition_due.py asx`, stdlib only, runs before pip; the close is `config.IGNITION_BAR_FINAL["asx"]`) + `54 0,2,4` intraday; push to `.github/ignition-asx-kick`; manual (`backtest`, `dry_run`) | IGNITION on the ASX (REPORT-ONLY): the STRUCTURAL TWIN of ignition.yml — same steps, same run blocks with `crypto`→`asx` (test-pinned byte-equal, so the crypto suite's executed shell covers it), own gate, own group `ignition-asx-<ref>`, own cache namespace, 300-min timeout for the ~2,000-name replay. Publishes `public/data/ignition/asx.json` + `asx_charts.json` (+ `asx_backtest.json`). Pins: `tests/test_ignition_asx.py` |
| ignition_nasdaq.yml | `34 21` UTC Mon–Fri (past the 16:30 New York bar-final in both DST regimes) + `34 22,23` backstops (still the close's UTC weekday; skip once a file generated after the latest 16:30 New York is on the branch — `scripts/ignition_due.py nasdaq`) + `54 14,16,18` intraday (in session, an hour clear of the close, both regimes, WHEN ON TIME — the gate skips one GitHub delays to at/after 15:30 New York, pinned by executing the gate in `tests/test_ignition_nasdaq.py`); push to `.github/ignition-nasdaq-kick`; manual (`backtest`, `dry_run`) | IGNITION on NASDAQ (REPORT-ONLY, 2026-10-08): the third STRUCTURAL TWIN of ignition.yml — same steps, run blocks byte-equal with `crypto`→`nasdaq` (the TWINS pins in `tests/test_ignition_asx.py`), own gate, own group `ignition-nasdaq-<ref>`, own cache namespace `ignition-nasdaq-frames-`, 300-min timeout for the ~1,430-name replay, no WATCHDOG entry. Publishes `public/data/ignition/nasdaq.json` + `nasdaq_charts.json` (+ `nasdaq_backtest.json`). Pins: `tests/test_ignition_nasdaq.py` |
| crypto_source_check.yml | manual; push to `.github/crypto-source-kick` | READ-ONLY verification of the crypto data-source switch (see CRYPTO DATA SOURCE): venue reachability from a runner, freshness, close gap to Yahoo (ticker collisions), liquidity-floor effect, and a DRY VIVEK crypto scan on exchange klines diffed against the published one — writes nothing, no bot, no mutex, no assert_staged/WATCHDOG (evidence_brief pattern) |
| momentum.yml | `30 6`, `30 21` Mon–Fri + `30 0` daily + a `41 */3` backstop, and after every completed morning_plays.yml run | MOMENTUM lens (REPORT-ONLY): screens ONE market per run — the newest one due per `scripts/momentum_due.py`, read against main — after that market's close, into `public/data/momentum/<market>.json`; nothing else. Own concurrency group (`momentum`), not in the scan mutex; assert_staged on the one path |
| data_depth.yml | manual only | READ-ONLY probe of how much free daily history each source serves (`scripts/data_depth.py`, stdlib only); the printed table is the deliverable. No git, no assert_staged, no WATCHDOG entry |

(Table refreshed 2026-07-20 — discord_digest.yml deleted; notify/alerts/pulse/
paper_run/bracket_order/reconcile modules deleted. evidence_brief.yml added
2026-08-01. resize_book.yml added 2026-09-27.)

### ALERT DELIVERY — the channel was dead behind TWO stacked failures (2026-08-01)

Found live when the evidence brief's first Discord post failed a run out loud
— the one thing the router's own senders never do (they try/log-warning), so
**every Discord alert (stale probes, trade reviews, sector alarms, guard and
kill-switch notices) had been failing silently**. The `test_alerts.yml`
self-test corroborated: `sent via NONE — NOT delivered: telegram,discord,email`.

1. **The stored `DISCORD_WEBHOOK_URL` begins with U+FEFF** (a BOM, invisible
   in the GitHub secrets box). urllib rejects it as `unknown url type:
   ﻿https`. Fixed at the boundary: `config.clean_secret()` trims
   whitespace + BOM/zero-width chars from the ENDS only, and every pasted
   credential routes through it (`alert_dispatch._cred` for Discord/Telegram/
   SMTP; `confluence_alert` + `discord.py` webhook reads; the brief workflow
   inlines the same trim). A `.strip()` alone never removed U+FEFF — it is
   category Cf, not whitespace. Re-pasting the secret also works; the code fix
   makes the next stray paste a non-event. `tests/test_alert_credentials.py`.
2. **Discord's edge 403s Python's default User-Agent as a bot.** With the BOM
   stripped the post reached Discord and got `HTTP Error 403: Forbidden`; a
   named UA (`vivek5-alerts/1.0`, `alert_dispatch._UA`) fixed it — proven by
   the brief's run #3 delivering. Applied at all three post sites
   (alert_dispatch urllib ×2, discord.post_webhook requests, the workflow).

**DISCORD REMOVED ENTIRELY, 2026-08-27 (owner ruling: "get rid of the discord
aspect, I will work on implementing something new in the future").** Everything
above and below in this section is HISTORY — the incidents were real and their
lessons (clean_secret at every credential boundary, named UA, loud dead-sends)
carry over to whatever channel comes next. What was removed: the `_discord`
sender in alert_dispatch, `scanner/discord.py` outright, confluence_alert's
webhook post (the ALERTS page log and the signed push-owed state SURVIVE — an
undelivered alignment holds a NEGATIVE state count, so the replacement
channel's first run pings everything still current), the watchdog's discord
branch, every workflow Discord step/env line, and "discord" from every
ALERT_CHANNELS tier (NOTICE is now channel-less). The router, severities, rate
limits and every page surface stay: the new channel plugs in by adding a
sender to alert_dispatch, wiring it in smart_send/watchdog._dispatch, and
naming itself in config.ALERT_CHANNELS. Pinned in
`tests/test_alert_credentials.py` (no workflow may reference
DISCORD_WEBHOOK_URL; no scanner/scripts code may read it). UNTIL THEN THE ONLY
ALARMS ARE GitHub's own red-run emails plus the run pages' `::warning::`
annotations — Telegram and SMTP remain unconfigured, so `smart_send` logs
"NOBODY WAS TOLD" on every routable event. The owner can delete the
DISCORD_WEBHOOK_URL secret from GitHub + Cloudflare whenever convenient;
nothing reads it.

HISTORY (pre-removal): **Telegram and SMTP are UNCONFIGURED** (empty
secrets), so Discord was the only live channel. `test_alerts.yml` remains the
end-to-end proof harness for whatever channel comes next.

### MORNING PLAYS — a NEW, sanctioned Discord digest (2026-09-08; rescheduled 2026-09-09)

The 2026-08-27 removal killed Discord as the ALERT router. The owner then asked
for the "something new" it foreshadowed: **a daily digest of the HIGH-CONVICTION
VIVEK 5.0 plays across ASX + NASDAQ + Crypto, posted to Discord.**
`scripts/morning_plays.py` + `.github/workflows/morning_plays.yml`. (The name is
historical — ASX now goes out in the AFTERNOON; see the schedule below.)

- **It is NOT a revival of the alert router, by construction.** It is a
  standalone once-a-day content push (reco_note / evidence_brief shape), NOT
  routed through `alert_dispatch`'s severity tiers / rate limits — a digest is
  not an alert. It uses its OWN secret **`DISCORD_MORNING_WEBHOOK_URL`**, a
  distinct name from the removed `DISCORD_WEBHOOK_URL`, which is exactly the
  path `test_no_workflow_references_the_removed_discord_webhook`'s own docstring
  names ("the replacement channel gets its own secret name"). Both credential
  pins still hold unchanged — do NOT weaken them, and do NOT let the LITERAL
  string `DISCORD_WEBHOOK_URL` appear in this workflow (even in a comment: the
  pin is a substring check, and it caught exactly that on the first draft).
- **HIGH CONVICTION is reproduced from app.js `isHighConviction` EXACTLY**: a
  weekly (1W) reclaim that is armed and either A/A+ grade or has >= 2 structural
  TPs. `test_morning_plays.py::test_it_matches_the_shipped_app_js_rule` slices
  the shipped app.js so the two cannot drift silently. If that rule changes in
  app.js, change `morning_plays.is_high_conviction` with it.
- **THE FILTER (owner spec, 2026-09-08, revised same day): LONG only, never a
  SHORT; never a fund/REIT/LIC/preferred (`is_product`).** Default is
  high-conviction longs only -- a tight list (~8/day across the three markets).
  `MORNING_PLAYS_INCLUDE_ALL_APLUS` (config, default False) widens it to also
  include every plain long A+ (~100/day, capped at `MORNING_PLAYS_MAX_ROWS`/
  market with a "+N more" line). Output is CLEAN TEXT, not embeds — **grouped by
  market THEN by label, one symbol per line (owner, 2026-09-17)**: a bold
  `**ASX PLAYS**` header, then `A+ High conviction` once with its symbols under
  it, then `High conviction`, then `A+` (`LABEL_ORDER`); no per-row
  `SYMBOL -> label` arrows (that was the 2026-09-08 shape). Messages
  are chunked to stay under Discord's 2000-char `content` limit (`_chunk`). No
  entry/stop/RR/company-name clutter -- the owner asked for a scannable list.
- **TWO MARKET-SPECIFIC SLOTS, ~30 min after each market's close (owner,
  2026-09-09): ASX at 16:30 Melbourne, NASDAQ + Crypto at 06:30 Melbourne.**
  `config.MORNING_PLAYS_SLOTS` (`{asx:{hour16,markets:(asx,)}, us:{hour6,markets:
  (nasdaq,crypto)}}`) is the single source of truth; `MORNING_PLAYS_MARKETS` (the
  union) and the legacy `MORNING_PLAYS_SCHEDULE` (hour→markets) are derived. Crypto
  trades 24/7 but rides the US slot so both morning markets land in one message.
- **DELAY-PROOF SCHEDULING — rebuilt 2026-09-10 after the FIRST design missed a
  whole day.** The v1 gate sent only when the Melbourne hour was EXACTLY the slot
  hour. On 2026-09-09 GitHub batched the free-tier crons **2–5 HOURS late** (runs
  landed at Melbourne hours 7/8/19/21), so every delayed run saw "not my hour" and
  no-op'd — nothing delivered all day (confirmed in the run logs; the owner
  noticed). The fix mirrors turtle.yml: **morning_plays.yml maps each cron to a
  slot NAME via `github.event.schedule` and passes `--slot`**; `slot_due()` sends
  the slot when Melbourne is **AT OR PAST** its target today **AND** a per-day
  marker says it has not gone out today. "At or past" tolerates any delay; the
  marker (`state["slots"][name]=today` in the sent-list) stops the slot's second
  DST superset cron — and any repeat run — from double-sending. Net: **each slot
  delivers exactly once per day, on the first run at/after its target, however
  late.** The old hour-equality gate survives ONLY as `slot_markets()`, the
  fallback for a bare local `python morning_plays.py` (no `--slot`, no `--force`).
  Pins: `test_slot_due_*`, `test_a_slot_delivers_even_when_the_cron_is_hours_late`,
  `test_the_per_day_marker_makes_the_second_dst_cron_a_silent_noop`.
- **7-DAY DE-DUP (owner ask, 2026-09-09): a ticker SENT within
  `MORNING_PLAYS_DEDUP_DAYS` (7) is skipped**, because the reader charts each
  name and shares it on, and a weekly setup persists for days — so without this
  the same names recur every day. Counted from when SENT (not from when it went
  high-conviction), so a still-valid name reappears once the window passes.
  State is a tiny actions/cache file (`MORNING_PLAYS_SEEN_FILE`,
  `.cache/morning_plays_sent.json`, `{sent, slots}` via `load_state`/`save_state`)
  — the watchdog-state cross-run pattern, so the JOB STAYS READ-ONLY to the repo
  (restored before, saved after, never committed, gitignored). The SAME file holds
  the per-day slot markers (above). **Only ACTUALLY-DELIVERED tickers are
  recorded**: a failed post / non-2xx / dry run / missing webhook records nothing
  AND marks no slot done, so no name is ever silently buried and a failed slot
  retries next run. Keys are market-scoped (`market:SYMBOL`), so an ASX LINK and a
  crypto LINK never collide. Records prune once past the window. Two dedup layers,
  by design: the per-day slot marker prevents same-day doubles; the 7-day ticker
  window prevents cross-day repeats to the reader (who charts each name). **`--force`
  bypasses ALL state (read AND write)** — a manual test must never consume the real
  window, mark a slot done, nor re-send a name already shared today. 0 = repeat freely.
- **READ-ONLY**: reads the COMMITTED `public/data/<market>_vivek.json` (no scan,
  no Yahoo, not in the scan mutex), posts, commits nothing — so no assert_staged
  and no WATCHDOG entry, like evidence_brief. The webhook runs through
  `config.clean_secret` (the 2026-08-01 BOM lesson) and posts with a named UA
  (Discord 403s Python's default). Missing secret = `::warning::` + exit 0 (a
  green setup gap); a genuine delivery failure = exit 1 (loud, since GitHub's
  red-run email is the only alarm).
- **Owner action to switch it on**: create a Discord webhook for the channel he
  wants and add it as the `DISCORD_MORNING_WEBHOOK_URL` Actions secret. Until
  then every run is a green no-op that says so. Constants (schedule, dedup
  window, per-market cap, staleness flag, optional app URL) live in `config.py`
  (`MORNING_PLAYS_*`). Manual `workflow_dispatch`: leave `slot` blank to force-send
  ALL markets (a test, writes no state); set `slot=asx`|`us` to run ONE slot as if
  scheduled — delivers it now AND marks it sent, so a late/dropped cron for that
  slot becomes a no-op instead of a duplicate. Added 2026-09-10 after GitHub ran
  the ASX cron ~3h late (it eventually fires, but the owner wanted it on demand
  without the all-markets force re-sending it).
- **THE POST-CLOSE DATA GATE (2026-09-11) — on time was not enough.** The first
  on-time 06:35 US run (cron-job.org, run #16) read a 1:43pm New York MID-SESSION
  scan — scan.yml's post-close NASDAQ scan (21:07 UTC cron) committed at 07:06
  Melbourne — and posted "nothing new" while MDLZ/ASO/SWKS had set up in the last
  hours of trade (verified by replaying `qualifies()` over the two commits). The
  same trap sat under ASX: its closing scan (06:37 UTC cron) lands 17:4x–18:5x
  AEST, after the 16:35 trigger. `scan_is_post_close()` now gates every `--slot`
  run: it sends only once the gating market's `generated_at` is at/after that
  market's most recent WEEKDAY close (`config.MORNING_PLAYS_SLOT_GATE`: ASX **16:40**
  Sydney — see THE ASX CLOSE below, it was 16:12 until 2026-10-06; NASDAQ **16:05** New York —
  NOT later, because under EST the 21:07 UTC scan is 16:07 NY and is the ONLY
  post-close scan of the day, so a 16:15 gate would silence the US digest all
  winter). **It also refuses while the session the slot OWES is still running
  (2026-10-05, `session_in_progress`)**: a weekday between the gated market's
  open (`config.VIVEK_JOURNAL_SESSION`: ASX 10:00 Sydney, NASDAQ 09:30 NY) and
  today's close gate, for a session that opened at/before the slot's floor on
  that Melbourne date. Without it `latest_close()` fell back to the PREVIOUS
  close and a mid-session scan passed — under AEDT+EST (from 2026-11-02) the
  US floor and the 20:15/20:45Z rungs are 14:30–15:45 New York, so every
  winter digest would have gone out mid-session and marked itself done. A
  session that opens AFTER the floor belongs to the next slot (AEST+EDT:
  23:30–23:59 Melbourne is 09:30–09:59 NY the same date). Cost: a NY holiday
  weekday now waits for 16:05 NY. Before the gate passes the run is a silent no-op that MARKS NOTHING,
  so the next attempt retries; `--force`/`--dry-run` bypass it. The triggers are
  therefore a LADDER, all in UTC because the close scans are: cron-job.org
  (timezone UTC) ASX `06:15..10:45` every 30 min Mon–Fri, US `20:15..23:45`
  every 30 min Mon–Fri (Tue–Sat mornings Melbourne); morning_plays.yml's own
  crons are the late backstop at `50 7`/`50 8` (ASX) and `50 21`/`50 22` (US)
  Mon–Fri. First post-close attempt sends, the per-day marker silences the rest.
  The wall-clock `MORNING_PLAYS_SLOTS` targets (16:30/06:30 Melbourne) survive
  only as a FLOOR. Measured over the prior 8 days the ASX post-close scan lands
  between 06:01 and 08:50 UTC and the NASDAQ one between 21:01 and 22:30 UTC,
  which is why the ladders run that long. Pins: `test_the_real_2026_09_10_scans_*`,
  `test_the_us_gate_accepts_the_winter_21_07_scan_*`,
  `test_the_us_slot_waits_for_a_post_close_scan_*`,
  `test_the_workflow_crons_fire_after_the_close_scans_*`.
- **THE ASX CLOSE — 16:40 Sydney, not 16:12 (2026-10-06, owner: "Fix it
  properly").** The auction prints ~16:10–16:12 but Yahoo's ASX feed shows it
  ~20 min later, and `generated_at` is stamped after a ~4–5 min download.
  Measured: the 2026-10-05 scan stamped 16:32:36 (download from 16:28:52) held
  pre-auction prices on 332 of 1,739 names (19%) and one digest name changed;
  a 16:36 stamp (21 Sep) still had ~11% pre-final. 16:12 was harmless only
  while evening heals rescanned the ASX; once `scan_gate.py` (2026-10-05)
  made the first post-close scan THE close, the deck, the bot's ASX marks and
  the digest sat on pre-auction prices until the next morning. Now the one
  constant `MORNING_PLAYS_SLOT_GATE["asx"]` = 16:40 drives the scan gate, the
  digest gate and the Ignition ASX backstop gate (`scripts/ignition_due.py`
  reads it through `config.IGNITION_BAR_FINAL["asx"]`). **The on-time closing scan is
  cron-job.org job 8587590 `scan ASX close (Sydney)`** (16:40 Sydney Mon–Fri,
  `/api/heartbeat?market=asx&stale_min=15`): the 16:10 hourly ping's scan lands
  ~16:20, so at 16:40 the ASX is stale, the heal dispatches, the gate scans it
  live (window to 16:45) and the download starts after Yahoo shows the auction;
  committed ~16:50, the ladder's 17:15 rung sends the digest in both DST
  regimes. Its one gap: a scan landing 16:26–16:39 is too fresh to heal at
  16:40 yet pre-auction. That is what **job 8587683 `scan ASX close probe (Sydney)`** covers:
  17:20 Sydney Mon–Fri, `/api/heartbeat?market=asx&stale_min=40` (17:20 − 40 =
  16:40, so it heals exactly when no scan stamped at/after the close has
  landed; an over-heal is a gate skip). Further backstops: scan.yml `41 5,6`
  (was `30 5,6`; never delivered since 18 Sep) and `57 5,6` (was `47 5,6`: at
  16:47 the closing scan has not committed yet, so it re-ran the close), and
  any heal (a scan stamped before 16:40 leaves the ASX "owed", caught up once).
  Under AEST ignition_asx's 06:24 UTC primary (16:24) now precedes the close,
  so its gated 07:24 backstop re-screens on final bars. Pins:
  `tests/test_scan_windows.py`, `test_morning_plays.py`, `test_ignition_asx.py`.
- **THE EXTERNAL TRIGGER — `/api/morning_plays` (2026-09-10).** GitHub's free-tier
  cron cannot be made to fire on time: it ran the ASX slot 2–5h late on 09-09 and
  had not fired at all by 19:19 Melbourne on 09-10. The delay-proof gate makes a
  late cron still deliver; only an EXTERNAL scheduler that keeps real time can
  make it deliver at 16:30/06:30. `functions/api/morning_plays.js` (`GET|POST
  ?slot=asx|us`) dispatches morning_plays.yml with the `slot` input using the
  EXISTING `GH_DISPATCH_TOKEN` (it stays in Cloudflare; the pinger never sees a
  GitHub token). **Fails closed, tick.js-style**: no `MORNING_PLAYS_TRIGGER_SECRET`
  → 503, wrong key → 401 (`?key=` or `Authorization: Bearer`); slot validated; a
  KV cooldown (5 min/slot, refunded on a definite failure, kept on timeout —
  scan.js's rule) bounds Actions spam. Because the dispatch runs the real
  `--slot` path, an early/duplicate call is a harmless no-op and GitHub's own
  late cron no-ops once the pinger has delivered. **Schedule the pinger as a
  LADDER after the close scan, not at a single time — see THE POST-CLOSE DATA
  GATE above (the 16:35 / 06:35 single-shot design lasted one morning).** Owner setup: set the
  secret in Cloudflare Pages env vars, then two cron-job.org jobs with the job
  timezone set to UTC, Mon–Fri, every 30 min — ASX 06:15..10:45Z, US
  20:15..23:45Z — hitting the URL with `&key=`. Until the pinger is live,
  GitHub's own cron still delivers — hours late, via the delay-proof gate. A
  Claude Routine was tried as an interim and REJECTED the same hour: Routine-
  fired sessions carry NO MCP connectors (the create_trigger result says so)
  and scheduled cloud sessions cannot reach the push token (reco_note note),
  so one can neither dispatch nor push a kick — do not re-add one.
  Pins: `test/morning_plays_api.test.js` (11).

**THE 2026-08-01 FIX MISSED THE WORKFLOWS' OWN FAILURE PINGS (found
2026-08-27).** Five workflows — scan, crypto_bot, phasemap, backup_book,
turtle — curled the secret RAW in their `Alert on failure` steps. curl parses
`<BOM>https` as a HOSTNAME and what follows the next colon as a port, dies
with `curl: (3) URL rejected: Port number was not a decimal number`, and the
`|| true` on the send swallowed it — so **the red-run Discord ping from those
five workflows had never once delivered**. Proven in the live log of turtle
run #29 (2026-08-24): the scan failure was routine Yahoo throttling, but the
alert about it died silently. All five now trim into `$URL` via an inlined
`clean_secret` one-liner (same char set), post with the named UA and
`--fail`, and a dead send prints `::warning::Discord failure ping did not
deliver` on the run page instead of nothing. Three pins in
`tests/test_alert_credentials.py`: no workflow may hand
`"$DISCORD_WEBHOOK_URL"` to a command, the five must carry the trim, and the
warning line must survive. The secret itself STILL carries its BOM — the
Python paths shrug it off and now the curl paths do too, but re-pasting it
clean remains worth doing in the same sitting as any secrets change.

**The `scan` mutex is JOB-scoped, deliberately (2026-07-28 — REFINEMENTS #108,
#109).** scan.yml, crypto_bot.yml, close_position.yml and (2026-09-27)
resize_book.yml share concurrency `group: scan` so two writers can never touch
the paper book at once (load-bearing: the position cap — 60 since 2026-09-27 —
is global, so concurrent writers could each read "59 open" and both open). That
group sits on the *scan* / *crypto* / *close* / *resize* JOBS, not at workflow
level (confluence.yml is the one WORKFLOW-level member, and never writes the
book). `test_workflow_mutex.py::test_every_job_scoped_member_of_the_group_is_listed_here`
enumerates job-level members from the tree, and
`test_every_workflow_scoped_member_of_the_group_is_listed_here` does the same
against `WORKFLOW_SCOPED` (2026-09-28), so a new writer cannot join the group
at either level without joining the pins. GitHub keeps only ONE pending run per group and
cancels the previously-pending one, so workflow-level scoping put the cheap gate
jobs in the same queue — every `:47` ASX backstop was being evicted by the `:52`
crypto arrival five minutes later, before it could probe, and a manual close
dispatched behind a running scan was deleted outright, run and all. Do not move
these blocks back up to workflow level; `tests/test_workflow_mutex.py` fails if
you do.

**close_position.yml re-dispatches itself if evicted** (owner decision). Because
the mutex is on the job, an eviction now cancels that job and leaves the run
alive, so the `redispatch` job — deliberately OUTSIDE the group — can see it and
`gh workflow run` the same inputs again. Capped at 3 attempts via the `attempt`
input; only fires when the close executed zero steps (an eviction never starts
the job, whereas a human Cancel leaves finished steps behind); waits for the
group's pending slot to clear first so the retry does not evict its evictor.
Its `WATCHED` list and job-name filter include "Resize open book" / `resize`
(2026-09-27): the resize's `preview` runs outside the mutex, so its RUN reads
in_progress while the mutex JOB queues, and an unwatched retry would evict it.

**THE MUTEX SERIALISED THE WRITES, NOT THE READS — writer jobs now check out
the branch TIP (2026-09-27, found building resize_book.yml).** `actions/checkout`
with no `ref` checks out `github.sha`, the commit the run was TRIGGERED on,
fixed when the run is created. A writer job that waited in `scan` behind
another writer therefore loaded a book OLDER than main's, and scan.yml /
crypto_bot.yml's push loops replay their copy of `journal/vivek_bot_book.<m>.json`
over the newer one — silently reverting a manual close, a same-market scan or
the open-book resize (reproduced in a scratch repo: BNB went back to $5,000
with `resized_at` gone, and `--verify` still passed, because it checks
consistency, not whose write won). The `scan`, `crypto` and `close` jobs now
check out `ref: ${{ github.ref }}` (the branch tip when the job STARTS, i.e.
after acquiring the mutex; a branch dispatch stays on its branch) and `resize`
checks out `ref: main`. confluence.yml's job does the same (2026-09-28): as the
workflow-level member its checkout already runs after the lock, and at the
trigger SHA its push loop (`git checkout "$SHA" --`) could replay a stale
`journal/confluence_state.json` / `public/data/phasemap/alert_history.json`
over scan.yml's newer copy. Pinned for every member, JOB- and WORKFLOW-scoped,
by `test_a_queued_writer_reads_main_as_of_acquiring_the_mutex_not_as_of_queueing`.
scan.py's `code_sha` stamp followed (2026-09-28): `_code_sha()` asks
`git rev-parse HEAD` first and falls back to `GITHUB_SHA`, so the deck's
"built from" tooltip names the code that ran, not the trigger
(`tests/test_code_sha.py`). **The one mismatch left is structural:** a queued
run executes its TRIGGER-SHA workflow steps against TIP code, so a commit that
renames a scan output path (in code and in a PATHS / assert_staged list) should
keep the old path written and staged for one cycle — a run queued across that
commit stages and asserts the OLD list against the NEW code, so it would stage
too little or fail its gate once.

**Silent-failure protection (2026-07-20, Phase 5; extended 2026-07-28 by TOP100
Tier 3).** Callers of `scripts/assert_staged.sh`, in full as of 2026-09-28
(re-derive with `grep -n "bash scripts/assert_staged.sh" .github/workflows/*.yml`
— a comment naming it is not a call): scan, crypto_bot, phasemap, backup_book,
reco_note, alert_returns, momentum, ignition + ignition_asx + ignition_nasdaq (once per reported path), and —
new in Tier 3 — close_position, gated to
`journal_type=bot` only (see "Tier 3" below for why the swing/scalp path must
stay a green no-op); and (2026-09-27) resize_book, gated BEHIND its `--check`
exit-3 discriminator so an already-applied re-kick stays an honest green no-op.
`confluence.yml` deliberately has NO assert_staged and
gates on an UNSTAGED working tree instead
(`test_workflow_hardening.py::test_confluence_gates_on_unstaged_rather_than_on_changed`
pins that as a decision rather than an omission); `backfill_history.yml`
deliberately had none at all (it went with HORIZON, 2026-09-20). Every caller runs it after
staging — a scheduled run that stages none of its must-change outputs FAILS
loudly instead of finishing green (the Phase 3 staging bug ran green 5x while
committing nothing). `scanner/watchdog.py` (hosted in kill_switch.yml +
crypto_bot.yml) additionally probes content timestamps + GitHub run history
and alerts on staleness with strict noise rules (first / 6h reminder /
recovery; red runs are GitHub's to email about). Thresholds: config
WATCHDOG_*. When adding a workflow that commits data, give it an
assert_staged call and a WATCHDOG_RUNS entry.

### The tick endpoint (removed 2026-09-21)

`/api/tick` and `stop_watcher.yml` went with the manual journal. Their
write-up is in `docs/claude-history.md`; read its verdict taxonomy (why a 503 or a 000 must
not fail a polled job, and why a 401 must) before building any new polled
endpoint.

---

## Journals & track record — IMPORTANT

- **The bot book is the ONE AND ONLY track record.** Layout v2 (2026-07-20):
  CANONICAL per-market files `journal/vivek_bot_book.<market>.json` (a market's
  run can only write its own file — cross-market clobber impossible by
  construction); `journal/vivek_bot_book.json` + the public twin are a DERIVED
  combined view (same old schema; regenerate with
  `python -m scanner.broker.vivek_run --rebuild-combined`; audit with
  `--verify` — the scan/close workflows run it as a failing gate). A/A+ longs in
  the four cells (grade_raw, unsmoothed — A+ only until 2026-09-21, see THE BOT
  TRADES THE FOUR CELLS), **max 60 open across ALL markets combined** (owner,
  2026-07-28 at 30; 60 since 2026-09-27 — see SIZING 2 —
  `VIVEK_BOT_MAX_OPEN_TOTAL`; the per-market cap is set equal to it so one market
  CAN hold the whole book, and `vivek_run._open_elsewhere` counts the sibling
  market files before each decision — fail-closed if one is unreadable), one per
  symbol, **6 per sector PER MARKET** (3 until 2026-09-27 — $15,000 of one
  sector either way; not global — see below), daily+weekly loss
  guards, manual close via close_position.yml journal_type=bot.
- **The correlation cap is the only limit that is still per-market**
  (REFINEMENTS #113, owner decision; the 2026-09-27 resize kept it per-market).
  Positions (60), notional ($150,000) and one-per-symbol are all cross-market;
  `decide()` seeds `sector_counts` from the single market's `open_book`, so 6 ASX
  financials + 6 NASDAQ financials is twelve of one real sector ($30,000 — the
  same dollars 3 + 3 were at $5,000) with every check passing. Not repaired — tightening what
  gets taken is the owner's call — but `sectorcache.global_sector_load` logs a
  per-scan WARNING naming any sector over the cap once all markets are counted.
  The fix, if wanted, is a `sectors` Counter on `_book_elsewhere` plus a
  `sector_elsewhere` kwarg, mirroring the two ceilings exactly.
- **`data/sector_map.json` IS A SIGNAL PATH** (2026-07-28, owner-authorised —
  REFINEMENTS #38). It used to be display-only, which is why the 3-per-sector
  cap never bound on NASDAQ: `universe._fetch_nasdaq` has no sector column, rows
  with no sector are exempt from the cap, and 0 of 269 scanned rows carried one.
  `vivek_run.run_market` now merges the cache into the rows `decide()` sees
  (`sectorcache.enrich_rows`, straight after the ADV enrichment), and
  `sectorcache._scan_symbols` seeds the fetch list from the OPEN BOOK first
  (rank `-1`) so held sector-less names — which had dropped out of the scan and
  could never acquire a sector — get backfilled. **The book back-fill has three
  sources, in order: today's scan rows → this market's UNIVERSE file → the
  cache** (2026-07-28). The universe leg was missing and it is the only source
  with full coverage — a scan lists the ~336 ASX names that set up, the universe
  carries a sector for all 2,212 — which is why BGA/FPH/AIA sat sector-less
  through every scan while occupying slots and, blank, staying exempt from the
  very cap they should have been filling. **Enrichment only ever writes
  into a blank field:** a sector shipped with the universe (all ASX rows carry
  GICS) wins, and an empty/unreadable cache is a no-op, never a clear. A wrong
  sector here now changes which trades get taken, so treat cache edits as trade
  changes. Crypto is still rescued by synthetic `crypto-major`/`crypto-alt`
  buckets. `decide()` publishes `summary["sector_coverage"]`; expect ~1.0.
  **Open (REFINEMENTS #112, owner decision):** SUN and AFG hold Yahoo-style
  `Insurance` / `Financial Services` where the ASX universe says `Financials`,
  so the cap reads three buckets where there is one. Reported by
  `sectorcache.diverging` as a scan warning; NOT repaired, because overwriting
  a non-blank sector is a trade change.
- **Position sizing is FIXED NOTIONAL** (2026-07-28, owner: "5k position moving
  forward on each 30 stocks and a cap of 150k"; halved to $2,500 × 60 on
  2026-09-27 — see SIZING 2): `VIVEK_BOT_POSITION_NOTIONAL`
  = $2,500 a position (was $5,000), `VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL` = $150,000
  (the dollar twin of the 60-slot cap, as it was of 30 × $5,000),
  `VIVEK_BOT_ACCOUNT_EQUITY` = $150,000. Equity no
  longer sizes positions — it scales the loss guards and the leverage ceiling,
  which is why it had to move with the book. **The dollars RISKED now vary with
  the stop distance** (~$25–$625, typically $125–$250 at $2,500; ~$50–$1,250 /
  $250–$500 at the old $5,000); position COUNT is the
  risk dial, not position size. Do not "fix" that by re-clamping `risk_pct` in
  fixed mode — see `tests/test_fixed_notional.py`. Set
  `VIVEK_BOT_POSITION_NOTIONAL = 0` to restore the old 0.35%-risk path exactly.
  The `open_book` projection `run_market` hands `decide()` carries `notional`
  (2026-07-28): `decide()` seeds `open_notional` from it, so omitting the field
  made the $150,000 ceiling count every market's exposure EXCEPT the one it was
  deciding for. Latent while every position is the same size and the slot cap
  binds first at exactly $150,000 — but it is a risk cap reading a number it
  believes is complete, so it is fixed rather than noted. (Not latent across a
  size cut: on 2026-09-27 the 30 open $5,000 rows filled the $150,000 by
  themselves, so until the open book is restated this ceiling — not the slots —
  refuses every $2,500 entry as `notional_cap`. Fail-safe, and the reason the
  resize runs at merge.)
  - **The book WAS a mixture; the owner chose to end it (2026-07-28).** The
    config landed at 03:34 UTC; the scan already running had checked out before
    it, so the six ASX positions filled at 03:39 were still sized by the old
    path (risk-% off a $10,000 equity: ~$300 notional, $35 risk). All 24 open
    rows were legacy-sized, averaging $256 against the intended $5,000 — an open
    book of $6.1k against a $150,000 target, and because each legacy row still
    occupied a full slot, filling the 6 free slots at $5,000 only reached ~$36k;
    the remaining ~$114k was hostage to those rows closing one at a time over
    weeks. Asked to choose, the owner said **resize now**. Run by
    `scripts/resize_book_notional.py` — see the RESIZE section below for what it
    restated and what it refused to touch. The book is now uniformly
    `fixed_notional`, 24 × $5,000 = **$120,000 of the $150,000 cap**.
  - **Dollar P&L is not a like-for-like series across 2026-07-28 (nor across
    the SIZING 2 resize commit). R is.** This
    is not a caveat, it is arithmetic: R divides by the position's own initial
    risk, so scaling the size cancels out of it. The live proof from the resize
    — total open P&L went **+$50.84 → −$715.16 while total open R did not move
    off +1.452R**. Not one price changed. Under the old flat-$35 risk every
    position contributed to the dollar sum equally, so the dollar total tracked
    the R total; under fixed notional a position's dollar weight is its STOP
    WIDTH, and the widest stops in the book happen to be the losers. Read R.
  - **`sizing_mode` is recorded on every new book row** (`"fixed_notional"` /
    `"risk_pct"`, empty on hand-built tickets). `size_position` always returned
    it and `decide()` splats it onto the ticket, but `_ticket_to_position` was
    not copying it down, so the book kept the numbers of a sizing decision
    without which mode produced them. Audit field only — nothing reads it to
    decide anything, and it is the one honest way to tell a legacy row from a
    new one once either number is retuned.

### RESIZE — restating the legacy book (2026-07-28, `scripts/resize_book_notional.py`)

(The figures below are the 2026-07-28 run. The script's second use is
$5,000 → $2,500 (2026-09-27), applied at merge by resize_book.yml — see SIZING 2
for what changed in it. The ruling not to pass `--max-stop-pct` still stands.)

- **It is a restatement, not a trade.** Nothing was bought, sold or re-marked.
  Every row kept the price it was actually filled at and the stop it was
  actually given; only the size attached to those prices moved. Restated:
  `units`, `notional`, `risk_usd`, `unreal_usd`, `risk_pct`, `leverage`,
  `sizing_mode`. Frozen and verified byte-identical afterwards across 38 fields
  × 24 rows: `entry`, `stop`, `risk`, `tp1/2/3`, `scale`, `last_mark`,
  `mae`/`mfe`, `exits`, `booked_pct`, `tp*_hit`, and every `_r` field.
- **The 12 CLOSED positions were not touched and must never be.** They are the
  only clean dollar track record the book has — the record of what was really
  held at the size it was really held. `resize_market` does not even iterate
  them, and a test asserts the closed list comes back byte-for-byte.
- **It sizes off `entry - risk`, NOT the row's `stop`.** `stop` trails. BGA had
  already taken tp1 and had its stop moved to breakeven, so sizing off the
  stored stop would divide by a zero distance. `risk` is the per-unit risk
  measured at fill and `entry - risk` reproduces the ORIGINAL stop exactly —
  checked against every un-trailed row in the live book, and kept honest by a
  test that asserts the property on whatever book is in the checkout.
- **The numbers come from `vivek_bot.size_position`**, called with
  `notional_target`, not from a scale factor computed in the script. A restated
  row is therefore sized by the same code that sizes a new one and cannot drift
  from it as the sizer is retuned.
- **DRY BY DEFAULT and idempotent.** It writes nothing without `--apply`, and a
  row already at the size the run would give it is skipped, so a second
  `--apply` is a no-op rather than a compounding rescale. It refuses to write at
  all if a frozen field moved (`AssertionError`, per market), then rebuilds the
  DERIVED combined book + public twin via `vivek_run._write_combined()` and runs
  `verify_books()`.
- **WIDE STOPS — the consequence the notional figure hides, and the reason the
  daily guard is now live.** Seven open rows (XLM 49.8%, MDB 45.5%, AXON 36.7%,
  GLBE 36.6%, WLD 27.6%, RNW 26.1%, ADP 25.3%) have stops beyond the
  `VIVEK_BOT_MAX_STOP_PCT = 25` gate every NEW entry must pass — they were
  opened before it bound them. At a flat $5,000 each now risks $1,266–$2,489,
  i.e. **28–55% of the $4,500 daily loss limit in a single name**. Book-wide,
  open risk went **$840 → $23,500 (15.7% of equity)**. Before the resize a
  whole-market stop-out cost ASX $385, 8.6% of its daily limit — the guard was
  mathematically unreachable and therefore decorative. Now ASX $6,478 (144% of
  it), NASDAQ $12,175 (271%), CRYPTO $4,847 (108%). The guard only halts NEW
  entries for the session, it does not liquidate — but it is armed for the first
  time and will fire. `--max-stop-pct 25` trims those seven back to $1,250 risk
  each (the top of the band `size_position`'s own docstring names) for a
  $111.3k book; it is **OFF by default because trimming is an exposure decision
  and therefore the owner's**, not a migration detail.
- **ASKED AND DECLINED — the seven keep full size (2026-07-28, owner: "Disregard
  the daily stop for the positiosn that have already been taken").** Do NOT run
  `--max-stop-pct`, and do not re-raise the trim as a suggestion. The position
  he took is that these were opened under the rules in force at the time and are
  not to be re-cut because a later gate would have stopped them; the guard
  applies to what is taken NEXT. What he asked for instead was to be TOLD before
  the next one — see the review flag below. The consequence stays exactly as
  measured above and is now a known, accepted exposure rather than an oversight:
  a whole-market stop-out still costs ASX 144% / NASDAQ 271% / crypto 108% of a
  day's guard, and the guard still only halts new entries rather than
  liquidating.
- Tests: `tests/test_resize_book_notional.py` (30). Most of them test what the
  script refuses to do, because that is where its whole defence lives.

### SIZING 2 — $2,500 × 60 (2026-09-27, owner-approved)

Approved 2026-09-27; the config and the restated book reach main AT THE MERGE
(restated rows carry `resized_at`). "2026-09-27" elsewhere in this file is that
approval date — main traded 30 × $5,000 until the merge commit.

- **Moved** (`scanner/config.py`): `VIVEK_BOT_POSITION_NOTIONAL` 5,000 → **2,500**;
  `VIVEK_BOT_MAX_POSITIONS` = `VIVEK_BOT_MAX_OPEN_TOTAL` 30 → **60**;
  `VIVEK_BOT_MAX_PER_SECTOR` 3 → **6** (owner: keep the DOLLARS — 6 × $2,500 = 3 ×
  $5,000 = $15,000 of one sector per market); `VIVEK_BOT_REVIEW_DAILY_LOSS_PCT`
  15.0 → **7.5** (owner: flag the same stops — see REVIEW FLAGS). Still each
  market's own currency (the 2026-07-29 ruling recorded in config carries).
- **NOT moved:** equity and `VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL` ($150,000 each;
  guards $4,500/day, $9,000/week per market), `MAX_STOP_PCT` 25, grades, cells,
  level gate, cycle tag `hc4-1`. Entry RULES held but CAPACITY did not (fewer
  `global_cap` / `sector_cap` skips live; `book_full` in `portfolio_sim` /
  `vivek_parity`): hc4-1 rows opened after the merge come from a less-crowded
  book, and both sims read the same constants — split any hc4-1 read or
  slot-bound sim figure at the merge / resize commit, not at the calendar date.
- **A selection change nobody asked for:** `size_vs_adv` refuses a notional above
  2% of ADV (`VIVEK_BOT_MAX_NOTIONAL_PCT_ADV`) — below $250,000 ADV at $5,000,
  below $125,000 now. ASX's $250,000 and NASDAQ's $2,000,000 `VIVEK_BOT_MIN_ADV`
  floors refuse first, so only crypto (floor 0) moves: a coin with $125k–$250k
  ADV is newly takeable. scan.py's $3,000,000 crypto `liquidity_min` (real dollar
  volume) still drops a thin coin before the bot ever sees it.
  - **FIXED 2026-09-28 (owner: "Yeah fix it"):** `vivek_run._enrich_adv` used to
    ignore `volume_is_usd` and stamp crypto `adv_usd` as mean(Close × Volume) —
    but crypto Volume is already USD (Yahoo and the exchange klines alike), so
    that was price × dollar-volume and a coin under ~4c gated far below its real
    liquidity (XDC traded ~$8.4M a day and gated at ~$252k). It could only
    wrongly REFUSE. `run_market` now passes its market in, `_enrich_adv` averages
    `Volume` when the market's `volume_is_usd` is set (Close × Volume otherwise,
    and when no market is passed), matching `scan.py::_liquidity`,
    `vivek_parity._adv_usd_at` and `vivek_backtest`. A trade change that can only
    ADD crypto takes. Pinned equal to `_adv_usd_at` by `tests/test_enrich_adv.py`.
- **Owner ruling: restate the open book NOW** (the July precedent) — until the 30
  open $5,000 rows are restated the $150,000 ceiling is full and every $2,500 entry
  drops as `notional_cap`. The branch carries only the INTENT, `.github/resize-kick`
  (one `target=2500` line; the script refuses, exit 2, unless it equals config),
  and the merge push fires `resize_book.yml` to recompute from MAIN's book under
  the scan mutex — a committed journal would conflict with or clobber newer marks.
- **What the second use changed in the script** (tests 30 → 116): it sizes at
  `signal_entry` (the plan price `decide()` sized at; `entry` fallback) against
  `entry - risk`, so every row restates by exactly ×0.5; `review` flags are
  RESCALED, not recomputed (`risk_usd`/`share_pct`/`note`; never added or
  dropped), the as-taken list kept once in `review_before`; `summary` + `guard`
  are rewritten via `vivek_run._restamp` for the day the stored guard describes,
  so no $5,000 guard dollars linger (the "wrote" line says "guard NOT restamped"
  if `_restamp` swallowed a guard failure); `--check` exits 0 at target /
  3 pending / 4 stuck (an off-target row it cannot size, named; wins over 3 — `--apply`
  refuses with 4 before writing anything) / 2 refused; a no-op `--apply` writes
  nothing. A partial already BANKED on an open row restates with it (dollars are
  `realized_r × risk_usd`): GLBE's tp1 (25%, banked at $5,000) reads $63.68 →
  $31.84, R unchanged, and the report names every such row. Dry run 2026-09-28:
  30 rows, $150,000 → $75,000, open risk $22,400.68 → $11,200.35; a whole-market
  stop-out is ASX 100.4% / NASDAQ 135.4% / crypto 13.1% of the daily guard.
- **Dollar P&L is not like-for-like across the resize commit either. R is.** The
  92 closed $5,000 rows stay as held and read `fixed_notional` too, so journal.js's
  `.jr-oldsize` marker now also underlines a fixed-notional row >1% off the
  PUBLISHED `position_notional` — per cell only; $ totals still mix both sizes.
  ASX rows' tooltip labels both figures A$ (face value, the currency ruling above).
- **Close ceiling 30 → 60**: `functions/api/close.js`, journal.js `CLOSE_ALL_MAX`,
  `vivek_run.CLOSE_BATCH_MAX` (= `VIVEK_BOT_MAX_OPEN_TOTAL`) and close_position.yml's
  "Max 60.", pinned to config by `tests/test_close_ceiling_parity.py` (with status.js
  `FALLBACK_CAP`, journal.js `POSITION_NOTIONAL`, system.html's rulebook cells).
  `bot_rules.json` (the evidence brief now reads its cap there) is republished by
  the resize commit itself (`scanner.run.bot_rules_payload()` → 60 / $2,500 / 6),
  so the restated book and the rules describing it land together; between the
  merge push and that commit both still say $5,000, which is consistent.

### REVIEW FLAGS — "should Claude take this, or should I?" (2026-07-28)

Owner, in the same breath as declining the trim: *"Flag this in the future so i
can verify whether claude or I should take the position or not."* A plan whose
1R loss is a large share of the daily loss guard now arrives marked.

- **A FLAG IS NOT A GATE, and that is the whole design.** `review_flags()` runs
  in `vivek_bot.plan_trade` AFTER every rule has said take; it adds a key and
  returns. Nothing skips, resizes, reorders or closes because of it —
  `evaluate_setup`, the `wide_stop` / `stop_too_tight` / `min_price` /
  `illiquid` / `size_vs_adv` skips and `decide()` are untouched. Changing which
  trades get taken is the owner's call, so the flag tells him there is a
  decision to make and then gets out of the way.
  `tests/test_review_flags.py::test_a_flagged_plan_is_still_taken_because_a_flag_is_not_a_gate`
  pins it, and is the one test in there that must never be "fixed" to agree with
  a future gate.
- **`VIVEK_BOT_REVIEW_DAILY_LOSS_PCT = 7.5`** (15.0 until 2026-09-27, halved with
  the notional — owner: flag the same stops) — flag when `risk_usd` is ≥ this
  % of `daily_loss_limit()` ($4,500 = equity × `MAX_DAILY_LOSS_PCT`). The number
  sits between two others and cannot sensibly be moved without checking both:
  `MAX_STOP_PCT` caps any NEW position at 25% × $2,500 = $625 of risk = **13.9%
  of the guard**, so any threshold ≥ ~14 is dead code that would never fire and
  nobody would notice; a typical A+ plan runs a 5–12% stop = $125–$300 = 3–7%.
  7.5 = $337.50 = a **13.5% stop** on $2,500, the same stop width 15.0 ($675)
  flagged on $5,000 — so the flagged half did not move, and 15.0 left beside
  $2,500 would have needed a 27% stop the 25% gate never admits. A test asserts
  `0 < threshold < ceiling` so the dead-code case fails loudly. 0 = off.
- **Three hops, because a flag nobody sees is not a flag.** The ticket carries
  `review` (a list, empty when clean); `_ticket_to_position` copies it onto the
  book row; `vivek_run._notify_reviews` pushes it through the NOTICE tier
  (channel-less since 2026-08-27). Skip any hop and
  the mark survives only in a log line inside a finished Actions run, which is
  not a place a decision gets made.
- **The push is `trade_review`, NOTICE tier (channel-less since the
  2026-08-27 Discord removal), rate limit 0**
  (`VIVEK_BOT_REVIEW_PUSH`, ON — unlike `VIVEK_BOT_NOTIFY_TRADES` beside it,
  which digests every open/close through every channel including email and stays
  off). Fires AFTER `_save_market_book`, so a dry run is silent and nothing is
  announced that failed to persist. One message per run, not per position,
  because the number worth the message is the COMBINED share: three flagged
  opens at 13% each is ~40% of the day gone in one run (27% / 80% at the
  pre-2026-09-27 $5,000) and nobody sums that by
  hand across three notifications. Rate limit 0 for the same per-EVENT-TYPE
  reason as `sector_run` — markets run sequentially in one job, so a limit could
  only ever drop the second market's flagged open, and losing one is the entire
  failure mode.
- **The message says the trade is already TAKEN.** The choice on offer is not
  take-or-skip but *whose position it is*: leave it and it is the bot's at the
  configured notional (the message reads `VIVEK_BOT_POSITION_NOTIONAL` — $2,500
  since 2026-09-27), or close it in the book and take it yourself sized your own way. A
  message that read like a pre-trade approval request would misdescribe what the
  system actually does, and a test asserts the wording.
- **Front end:** `reviewChip` in `public/js/journal.js` (`.jr-review`,
  journal.css) — amber, outlined, no pulse, deliberately quieter than `.jr-flip`,
  which is a live warning that the chart turned. **It renders on CLOSED rows
  too, on purpose**: the flag records what was known at entry, and how the
  flagged trades actually went is the only evidence that will ever say whether
  7.5 is set sensibly (15.0 before 2026-09-27 — the same 13.5% stop either side,
  so the series is continuous; a restated row keeps its as-taken flag in
  `review_before`). An absent `review` key (row written before flags
  existed) and an empty list (checked, clean) both render nothing but are NOT the
  same thing — do not collapse them by defaulting the key server-side.
- Tests: `tests/test_review_flags.py` (27) + `test/journal_review.test.js` (9,
  which slices the real `reviewChip` out of the shipped file rather than
  mirroring it, so a rename fails the suite instead of silently testing a copy).

- The old "track-record journal" (every armed A+/A, every timeframe, no cap —
  it hit 203 open / 12 closed) was **retired 2026-07-09** along with the
  dashboard strip and TRACK page. Do not resurrect it as a headline number.
- **Manual journals are GONE (2026-09-21).** The "Me" side lived in browser
  localStorage, synced via Cloudflare KV (`gbs-sync.js`, `/api/journal?code=`),
  and the unified watchlist (stars) lived inside that same store. The owner
  takes real trades on a real brokerage account and asked for the whole Me half
  to come out; see MY JOURNAL below. There is now exactly ONE journal on the
  site and it is the bot book.

---

## Two owner-ruled surfaces, 2026-08-01 (read-only, additive)

- **STALLED — the position decision surface** (`public/js/stalled.js` +
  `stalled.css`, `#stalled-strip` at the top of journal.html). Lists exactly
  the rows the stale probe stamped (`stale_pinged`) — symbol/market, days
  held, mark age, unrealized R, grade, and the keep / 28d-time-stop /
  free-the-slot framing, with a summary line (count, combined R, $ at risk as
  % of equity, slots occupied against the global cap). NO new stall logic —
  the engine's stamp is the whole definition — and NO write path; closing
  stays manual via close_position.yml. Day arithmetic uses the book's own
  `summary.updated_day`. Hides when the cohort is empty (e2e fixtures carry
  no stamps, so the screenshot gate is untouched). `test/stalled.test.js`.
- **WHAT NEEDS MY EYES — confluence prominence on the deck** (`renderEyes()`
  in app.js + `eyes.css`, `#eyes-strip` inside `#deck`, ABOVE the pills).
  Owner: "make dual/triple lens agreement and any name that is both A+ and
  multi-lens the loudest thing on the main deck." Ranked chips from the same
  client-computed confluence set the ⨂ pill counts — triple beats dual, A+
  first inside each tier, triples pulse, a triple turns the strip amber-hot,
  "+N more" engages the Multi-lens filter. Partially reverses the Wave 3
  banner retirement BY OWNER RULING (the pill and row chips stay; this is
  additive). The A+ tag claims the DISPLAYED grade — the bot buys grade_raw.
  `test/eyes.test.js`.

Both are pure surface: nothing in `broker/` reads them, no trade changes.

---

## is_product — LIC / preferred honesty, display-only (2026-08-19, Session C)

The fund keyword list structurally misses two listing classes, and both were
dressing as A+ opportunities on the deck: **ASX LICs** whose names carry no
FUND/TRUST/ETF word (AFI, BTI, HM1, RG8 — four A+ on the live scan), and
**NASDAQ preferred lines** (STRF, STRD at A+; STRC, MCHPP at B+). The scanner
now publishes `is_product` on every result row and the UI trusts it.

- **`scan.py::_product_tag`** = the bot's fund WORD LIST under the front end's
  WORD-BOUNDARY matching, plus `config.PRODUCT_NAME_PATTERNS` (preferred
  stock/shares · "InvestmentS Limited/Ltd" PLURAL + "Investment Company/Co" ·
  notes-due · debentures · warrants · rights-lines). Each pattern's rationale
  and its measured near-miss live beside it in config.
- **IT MUST NOT DELEGATE TO `_is_fund_or_reit`, and this was found by test.**
  The bot's matcher is substring (`"ETF" in "NETFLIX"` is True) — the exact bug
  the front end fixed with `\b` on 2026-08-13 while the bot's ringfenced copy
  kept it. The first draft called `_fund_tag()` and the NFLX pin went red:
  delegating republishes the bug as a server-side verdict the UI now trusts.
  The lists are IMPORTED from vivek_bot (mirror rule); only the matching
  discipline differs, deliberately.
- **The LIC pattern is PLURAL-only ("InvestmentS Limited"), and that is the
  false-positive fence**: "Australian Ethical Investment Ltd" is an operating
  fund MANAGER and must not dim. Known accepted borderline: NGI (Navigator
  Global Investments, B+ today). Bare "Depositary Shares" is deliberately NOT
  a pattern — Sanofi/JD/Ryanair ADS are real companies; the preferred patterns
  key on the word "Preferred", never the wrapper.
- **THE FENCE, both directions, pinned in `tests/test_product_flag.py`**:
  nothing under `scanner/broker/` may mention `is_product` or
  `PRODUCT_NAME_PATTERNS` (display honesty must not become a mid-w3-1
  eligibility change), AND the bot's substring matcher must stay byte-shaped
  as it is (a "fix" there is a trade change). `VIVEK_BOT_EXCLUDE_FUNDS`,
  `decide()`, w3-1 gates: untouched.
- **UI contract, three readers, one rule**: `is_product === true` → product;
  `=== false` → operating company (a verdict beats a guess — the keyword
  fallback may NOT overrule it); ABSENT → keyword heuristic, so cached
  payloads keep working. Honoured in `app.js::isFundReit` (deck counts,
  dimming, ranking pick it up transitively), `PM.isFundReit`
  (phasemap-shared), and the Eyes chips via `loadConfluence`'s detail.
- **Eyes strip**: the marker tag now reads **PRODUCT** (STRF is not a "FUND"),
  and leg-strength ranking is completed — the VIVEK leg's SCORE breaks the
  last tie inside a grade band, strictly AFTER count → product penalty →
  grade → PM leg quality. Missing score reads 0 (old payloads degrade to the
  previous order).
- **Measured effect at head**: ASX real A+ 41 → 37 (AFI, BTI, HM1, RG8 dimmed);
  NASDAQ 103 → 101 (STRF, STRD). Screenshot drift 0.00% ×4 — the e2e fixtures
  carry no flag, so the keyword fallback keeps the photographed pages
  byte-identical; no baseline bump.
- Tests: `tests/test_product_flag.py` (13, incl. both fence directions),
  `test/eyes.test.js` 25 → 30, `test/staleview.test.js` 136 → 139.
  12 mutations, every one caught (one survivor found and closed:
  app.js's flag-honour lines had no pin until the mutation exposed it).

---

## RULES vs OWNER — the split that was being pooled (2026-08-19, Session B)

One book, two systems. Measured at head: the RULES took 19 exits (5W-14L,
**-6.97R**); the OWNER took 26 by hand (11W-15L, **+0.09R**). Pooled that reads
`16W-29L -6.88R` and attributes the rules' losses to a book the owner was half
driving. Nothing about how closes happen changed — only what the surfaces admit.

- **The deck strip no longer prints a blended record.** `bookFacts` in
  `public/js/app.js` tallies `rules` and `owner` in the same loop it already
  walked, and the strip reads `... unrealized +3.6R · rules 5W–14L -7.0R · you
  11W–15L +0.1R`. Rules first, because "the bot's record" IS the rules' record.
  The deck is where the next trade gets picked, which is the worst place to
  hide that a record was half hand-driven. When only one side has closed
  anything it names that side rather than printing a hollow `0W-0L` beside it;
  with no closes it still says `record —`.
- **The journal's w3-1 line became an EXIT EVIDENCE strip** (`w3Line` /
  `w3Rows` in `public/js/journal.js`). A cycle counting to 30 closes implies
  the 30 will measure the ruleset; at head **all 3 gated closes are the
  owner's and 0 are the rules'**, so the number is measuring hand-timing. The
  strip states `24 gated open · 3/30 closes · 0 by the rules · 3 by you`, lists
  each gated exit (symbol · market · who + path · R · days held, newest first)
  behind a fold, and says the zero case in words rather than leaving a `0`
  nobody reads.
- **THE STRIP IS INERT, and that is load-bearing.** No button, no link, no
  wording that suggests closing anything, `<details>` shut by default. A
  surface that nudged the owner into more manual closes would MANUFACTURE the
  confound it exists to report. `test/journal_money.test.js` fails if a
  control or a call-to-action verb appears in it.
- **An ABSENT `exit_reason` is a human act**, in all three readers — a row with
  no recorded mechanism was not closed by one. Same rule `deciderSplit` has
  always applied.
- **`MECHANICAL_EXITS` now lives in three files** (`app.js`, `journal.js`,
  `status.js`) and is held together by a parity test in
  `test/staleview.test.js`, plus a **numeric** cross-check that drives the
  shipped `bookFacts` and the shipped `deciderSplit` with one book and asserts
  they land on the same counts and the same R. Identical lists are necessary
  but not sufficient: the failure that actually hurts is two surfaces printing
  different splits for one book with nothing saying which is right.
- **The e2e fixture book was stamped** (8 open + 2 closed rows carry
  `cycle: "w3-1"`, and one closed row's `exit_reason` became `manual`). Before
  this it was 6/6 `stop` with zero cycle stamps, so the screenshot gate
  photographed only the deck's ONE-SIDED degrade and never saw the w3 strip at
  all. The fixture hash is part of the baseline cache key, so editing it
  re-cuts baselines by itself — **no manual key bump was needed** and v19
  stands. Measured drift of the code change against the pre-change baselines:
  index-desktop 0.22%, index-390 0.13%, journal 0.00% (the strip was invisible
  in the old fixtures — which is precisely why they were stamped).
- Tests: `test/journal_money.test.js` 73 → 84, `test/staleview.test.js`
  127 → 136. 11 mutations applied one at a time, every one caught, all three
  sources restored byte-identical.

---

## STATUS — the lamp in the top bar (2026-08-19, owner-ruled Session 1)

`public/js/status.js` + `public/css/status.css`, mounted by the file itself on
every page that carries the shared nav. One lamp, one tap sheet, and the whole
point is that "is the machine working?" stops being a question you answer by
opening GitHub.

- **READ-ONLY BY CONSTRUCTION, and it is gated.** GET only, to published assets
  and `/api/health`. `test/status.test.js` extracts the actual fetch call sites
  and asserts the set is exactly `["/api/health"]`; separate pins ban a `method:`
  in any fetch init and any storage write at all — there is deliberately not
  even a "last opened" flag, because a read-only promise with one exception is
  one nobody can check at a glance.
- **IT MUST NEVER CALL `/api/heartbeat`, and that is not a style rule.** The
  heartbeat endpoint is the HEALER: it dispatches a scan when the book is
  overdue and spends one of its 24/day heal budget doing it. A lamp that polled
  it would fire workflows off page views and burn the budget that exists to
  rescue a dropped cron. The healer's *condition* (book age vs the 90-minute
  mark) is derived instead, and the sheet says it derived rather than probed.
- **Every threshold is borrowed from the component that already acts on it,
  and the borrowing is pinned.** 4h is `health.js`'s `max_h` default
  (= `WATCHDOG_BOOK_MAX_AGE_H`) — the point the external monitor is told the
  pipeline is down; 90m is `heartbeat.js`'s `DEFAULT_STALE_MIN`; the position
  cap (`max_open_total`, 60 since 2026-09-27) is read from `bot_rules.json`,
  with status.js's `FALLBACK_CAP` (pinned to config by
  `tests/test_close_ceiling_parity.py`) only when that fetch fails. Tests parse
  those two Functions and fail if either number moves without this one following.
- **A LOSS-GUARD BREACH IS AMBER, NOT RED.** Red means "the evidence you trade
  on is not arriving". A breach is the machine working correctly and refusing
  new entries, and `heartbeat.js` already paid for the lesson that an alarm
  which fires on successful self-protection is an alarm that gets muted. Pinned
  by a named test; do not "fix" it to red without re-reading that argument.
- **UPTIME IS MEASURED, NEVER ASSERTED.** It is the time-weighted share of the
  window during which the newest scan was inside the 4h line, computed in the
  BROWSER from `public/data/funnel_history.json` — the ledger `scanner/run.py`
  appends to immediately after every successful publish. Three properties carry
  it: the window is CLAMPED to the ledger's own span and labelled when clamped
  (a 30d figure over 19d of history would count the dark before the ledger as
  healthy); `Date.now()` closes the series so the CURRENT gap counts and a dead
  pipeline erodes the number live rather than freezing at 100%; and a gap
  straddling the window start is charged only for its in-window part. Computing
  it server-side was rejected for the second reason — a figure written by the
  scan can only be written while the scan is alive.
- **The funnel ledger now has two readers and no more.** `app.js` (the deck's
  funnel trend) and `status.js` (the `t` column, as the scan-publish ledger).
  `tests/test_funnel_history.py` names both and fails on a third, and the
  property it now gates is that BOTH fetch it lazily — 33 KB paid for by a tap,
  never by a page load across 14 pages.
- **What it does NOT claim to know is printed on the sheet, with the reason.**
  The healer is not probeable read-only; the 5-minute stop-watcher commits
  nothing a browser can read (making it visible needs a committed heartbeat or a
  KV stamp — neither exists); CI failures live in GitHub's API, so "View latest
  failure" is a deep link to the authoritative list rather than a count invented
  here. Absent signals are named, not omitted.
- **The lamp is NOT inside `.nav-pills`** — that strip is `display:none` under
  680px, which is the device this control is for. It mounts into
  `.deck-top-right`, falling back to the header. Sized by measurement: a 30px
  dot on phones leaves the journal header byte-for-byte the height it was
  (0.05% screenshot drift); a 40px labelled chip wrapped it onto a second row
  and cost 54px of page height. See the block comment in `status.css`.
- Tests: `test/status.test.js` (registered in test.yml), all logic
  mutation-verified (9 mutations, every one caught, source restored
  byte-identical). Screenshot baselines re-cut at `screenshot-baselines-v19`.

---

## Risk arithmetic — TOP100 Tier 1 (2026-07-28)

`TOP100.md` is a 100-item audit of the live tree, ranked not by severity but by
what has to be true before the next fix can be trusted. **Tier 0 (1–12)** was
every alert path that could fire into silence; **Tier 1 (13–24)** is the layer
underneath it — the numbers the guards are computed from. Both are shipped. The
items below are the ones that changed a MODEL rather than a line, so reading the
code without them is misleading.

### The guard measures a WINDOW now, off `day_marks` (#13/#14/#15)

`vivek_guard.session_pnl` charged each open position's **whole-life** unrealised
P&L, plus its whole-life banked partial-exit R, to today — every day, until it
closed. The closed leg had always filtered `exit_date == day`; the open leg had
no day filter at all. The live book said so out loud: crypto read
`session_usd = -1827.46` (41% of a $4,500 daily limit spent before the session
had done anything), while ASX read **+**$692.88, meaning a market holding old
winners could take a catastrophic day and not breach. Both directions are the
same bug — the number was not a day's P&L.

- **The fix is a reference price per window.** Every position records the mark it
  carried into each session in `day_marks`, and P&L is measured from that instead
  of from entry. It telescopes exactly: summing every day's window over a
  position's life returns its total P&L, no more and no less.
- **`_stamp_day_ref` must be called BEFORE `_mark_sanity`, and the order is
  load-bearing.** The reference has to be the PREVIOUS run's `last_mark`, so an
  overnight gap is charged to the session it gapped *into*. Stamp it after the
  mark and the gap lands between the two references and escapes the daily guard
  entirely — precisely the move the guard exists to catch. Written once per day
  and never overwritten (crypto runs 48 scans a day), on unpriced runs too.
  `_DAY_MARK_KEEP = 9` covers the widest window (trailing 7 CALENDAR days) on
  crypto with slack and nearly twice over on ASX/NASDAQ.
- **Direction of the change, plainly:** for a book of older positions the daily
  guard gets LOOSER (it no longer arrives pre-breached) and the weekly guard gets
  TIGHTER on names bleeding for a fortnight (their old losses were being counted
  into the window every day and are now counted once). No position, size, stop or
  rule moved. `open_total_usd` still publishes the whole-life number.
- **#15: it fails CLOSED now.** `if price is None: continue` silently disarmed
  the guard during a data outage — the one moment you most want it armed. An
  unpriced position is re-valued at its own STOP (the floor on what it can still
  cost this window) and, if that is enough to breach, the guard halts new entries
  and says `unmeasured` rather than saying all-clear about a book it cannot see.

### Closed-trade P&L is derived when a row carries no `pnl` (#16)

`kill_switch.trade_pnl` takes an explicit `pnl` when it is a real number and
otherwise derives dollars from `realized_r × risk_usd` (the bot book writes no
`pnl`). It is None- and NaN-safe on purpose: a NaN inside a sum makes every
later comparison False and disarms a guard. The rest of this item described
`risk_manager` and its callers, removed 2026-09-17; see `docs/claude-history.md`.

### `VIVEK_KILL_SWITCH_BROKERS` — a book breach is per-market, a flatten is not (#17)

`kill_switch.run_standalone` checks the bot book PER MARKET (three limits, three
verdicts) but a broker flatten is ACCOUNT-WIDE: `close_all_positions()` closes
everything on the account and `cancel_all_orders()` kills every resting order. So
an ASX **paper**-book breach called cancel-all + close-all on Bybit — liquidating
a live crypto book that was inside its own limit, over a loss that happened
somewhere Bybit cannot see. Losing money on the ASX is not a reason to sell your
crypto. The map says which broker actually holds each market (`asx: ()` paper
only, `nasdaq: ("alpaca",)`, `crypto: ("bybit",)`); `()` still alerts, logs and
counts as triggered, it just does not reach for an account holding none of the
positions. **A market missing from the dict falls back to the legacy
try-Bybit-then-Alpaca flatten and logs a WARNING** — deliberately the
over-protective default, so a new market added without a line here is noisy
rather than quietly unguarded.

### Mark-sanity runs only while the market is open (#18)

`_mark_sanity` gives a suspicious mark `ACCEPT_RUNS = 3` challenges before it is
accepted. It was called outside the `is_open` gate, so three closed-market scans
burned the entire budget on prices nobody was quoting — and a genuinely bad mark
on the next open was accepted unchallenged.

### `_restamp` — one writer for `summary` and `guard` (#21)

`close_bot_position` and `_close_time_stop` moved a row from `open` to `closed`,
realised its R and persisted — while `summary` still counted the closed position
as open and `guard` still described a session whose realised total had just
changed. Meant to be brief (the next scan recomputes both), but nothing
guarantees a next scan: close the last position of the day on a Friday and the
book contradicts its own rows all weekend, which is what the dashboard, the
health check and any human reading the file actually see. **Not a trade change** —
`run_market` recomputes the guard itself before `decide()` is ever called, so no
entry decision was ever made against the stale copy. Priced off each position's
own `last_mark` (the same fallback `kill_switch` uses between scans), because a
`price_of` returning None would mark the whole book unpriced and manufacture an
`unmeasured` breach out of a routine close. `notified` is carried forward
verbatim so the recompute cannot re-announce a breach already announced. It never
raises: a stale guard is worse than a fresh one, but a book that failed to save
is worse than both.

### `_side` / `open_count` — the position cap counts ROWS (#22)

**This one touched `scanner/broker/vivek_bot.py`, a file the owner has ringfenced
as never-autonomous. It is flagged, and the argument for shipping it is that it
is monotonically tightening.** The ceiling was tested against `longs + shorts`,
each counted with `==` against a raw `str()`, so any row whose `direction` was not
the exact lowercase string counted as NEITHER — and the book was allowed to run
one position over its own limit per malformed row. `_side()` now reads the field
the way every other consumer means it (stripped, case-folded) and `open_count`
tracks the rows themselves. **Every counter it changes goes UP, never down: no
trade blocked today becomes takeable.** It moves no threshold and touches no
filter, grade or ordering — the caps simply count what they always claimed to.
Pinned by `test_the_direction_repair_can_only_ever_block_more_never_fewer`.
`_side` returns None rather than guessing, because the tree already disagrees with
itself about an unreadable direction (`_exit_hits` defaults LONG,
`_mark_position` defaults SHORT) and a third opinion helps nobody; unclassified
rows are named in a WARNING, not just counted.

### Frame age is measured in the MARKET's calendar, and a cache expires (#23/#24)

- **#23:** `_frame_age_days` used the runner's naive local date, understating ASX
  staleness by a day against `MAX_DATA_AGE_DAYS = 3`. It now takes the market's
  `timezone`, which is what `scan.py` had always done one file over. The tz
  fallback fails CLOSED — an unusable zone must not return 0 ("perfectly fresh").
- **#24, the ceiling:** `merge_with_cache` back-fills tickers Yahoo dropped this
  run from the last-good cache, which is right for the ordinary case. It had NO
  limit, so a ticker Yahoo has not returned since March was handed to the scanner
  as if it were today's bars — its last close published as a live mark, used to
  mark held positions and test their stops. **A fossil price can fabricate a
  stop-out as easily as it can hide one.** `FRAME_CACHE_MAX_AGE_DAYS = 10`,
  generous on purpose (it must clear a multi-day Yahoo gap plus a long weekend;
  only a suspension or delisting should reach it), reported as
  `stats["stale_dropped"]` and a WARNING that NAMES the fossils. Refusing a frame
  can only ever REMOVE a name from the scan, never add one, and a held position
  that loses its frame is counted by `vivek_run`'s `unpriced_runs` (alerting at
  3/10/30) — visibly unpriced beats silently wrong. `0 = off`.
  - `save_frame_cache` refuses to write an EMPTY dict, so a run where Yahoo
    returned nothing leaves the fossil on disk rather than wiping a cache that
    will be useful the moment Yahoo comes back. That guard wins on purpose: the
    fossil is refused at READ time on every later run regardless, so nothing
    reaches the scanner off it and the only cost is disk.
- **#24, the visibility half.** Everything INSIDE the ceiling is still a past
  close presented as a live mark, so the age now travels with the price:
  `scan.py` publishes a sparse `price_age` → `run.py` carries it in the slim
  `<market>_prices.json` → `journal.js` loads it into `scanAge` and badges both
  the manual and the bot `Now` cell (`.jr-stale` — dotted underline, deliberately
  the quietest mark on the page, because the price is still the best number
  available), and the P&L headline counts them.
  - **SPARSE, and the `delete` is the load-bearing half.** Absent means fresh, so
    a healthy ASX run does not write ~2,200 zeros and an old cached page keeps
    working unchanged. But `loadScanMeta` re-runs every three minutes against
    cells that persist, so a name coming back into the scan must actively LOSE
    its key — a badge that never clears is worse than none, because it teaches
    you to read past the ones that are real.
  - The age is computed BEFORE the price snapshot, outside the scoring block. It
    used to sit inside it, so a name that failed `evaluate` published a price and
    NO age — and a held position that has dropped out of the setup list is
    exactly the row that gets priced off cache for weeks.
  - A live quote carries no age BY CONSTRUCTION (it was just fetched), so the
    badge only travels with the scan-snapshot branch of `refreshLive`.
- **#24, the held-position half (2026-09-28, owner: "Fix it") —
  `VIVEK_BOT_MAX_MARK_AGE_H = 2.0`.** Inside the 10-day ceiling the bot still
  MANAGED held positions off a reused frame's last close as if it were live —
  stop/time-stop tested, guard fed, `unpriced_runs` reset — so a coin a venue
  skipped for days froze at an old price with nothing counting the freeze.
  `merge_with_cache` now stamps every fresh frame `attrs["fetched_at"]` (UTC)
  and hands a reused one back as a TAGGED shallow copy (`cache_reused`); the
  cache re-saves the untagged original with its ORIGINAL stamp, so a frame's
  age keeps growing for as long as it is reused (a renewed stamp is the one
  bug that would undo the whole fix — pinned). `data.mark_age_h` reads it: 0
  for anything not back-filled, hours since the original fetch for a reused
  frame, **inf for a reused frame with no stamp** (unknown never reads as
  fresh). In `run_market`, `price_of` — which BOTH management and
  `vivek_guard.check` read — returns None past the limit: the position is
  unpriced (counted, WARNING `[stale_cache]`), and the guard values it at its
  stop (fail closed, #15; a run where many held names are only cache-priced
  can halt that run's new entries, which is the #15 design). 2h tolerates one
  skipped fetch after an on-time run and no more (a stock reusing yesterday's
  frame at the open is unpriced). **Fills are stricter: any reused frame
  skips the fill** (re-tried next run; a stale fill books a price nobody
  traded at) — beside, not instead of, the row-level `VIVEK_BOT_MAX_DATA_AGE_DAYS`
  gate. Scan grading/display is untouched. `0` = off. The first run after the
  deploy reads a cache with no stamps, so any held name reused on that run is
  unpriced once. **A held name the download starved is REFETCHED first
  (2026-10-06):** Yahoo throttled the same ASX batches run after run and PMT
  sat unpriced 7 runs (stop untested all session), so `run_market` now
  fetches held in-universe names whose frame is missing or past the limit
  in the same small direct `data.fetch` as the off-universe stragglers
  (`held_price_kwargs` checks included); only a non-empty frame replaces
  the cached one, so a failed refetch leaves the rule above in charge.
  Pins: `tests/test_stale_cache_marks.py`.
- Tests: `tests/test_data_download.py` (17) + `test/journal_stale.test.js` (13,
  which slices the real helpers out of the shipped file rather than mirroring
  them). **`_ohlc()` in the download tests defaults to TODAY** — it used to be a
  hard-coded past date, harmless until the ceiling existed and then a trap that
  made every reuse test silently exercise the fossil path instead.

---

## Journal arithmetic — TOP100 Tier 2 (2026-07-28, `fa4dafdb`)

Tier 1 fixed the numbers the guards are computed FROM. **Tier 2 (25–40) is the
layer the owner actually reads** — the P&L, the R, the drawdown, and the
hand-typed mirrors that decide what the page shows when a fetch fails. Same rule
as Tier 1: the items below changed a MODEL, so reading the code without them
misleads. The rest of 25–40 are ordinary line fixes and live in the commit body.

### Max drawdown was a function of row insertion order (#30)

`stats()` walked the trades in STORE order while `series()` beside it sorted by
exit date, so the headline drawdown and the equity curve under it could disagree
about the same set of trades. **Both numbers look plausible, which is why it
survived** — a book with a +5R, a −3R and a −1R reports −$400 in exit order and
−$300 in store order, and nothing on the page tells you which you are reading.
`byExit` now feeds both, copies before sorting (it must not reorder the caller's
array), and treats an unparseable exit date as 0 rather than throwing.

### Tests

`test/journal_money.test.js` reads the SHIPPED artefact rather than mirroring
it — it `vm`-slices real functions out of `public/js/journal.js` (the pattern
from `journal_review`/`journal_stale`), because a re-typed fixture drifts in step
with the bug it is supposed to catch. It ends with a **`?v=` floor check** on
`journal.html`'s `journal.js` tag, which turns project rule 2 from a convention
into a gate.

---

## CI honesty — TOP100 Tier 3 (2026-07-28, `a1d2e5b8`)

Tier 0 fixed alerts that fired into silence, Tier 1 and 2 the numbers underneath
them. **Tier 3 is the layer under both: the scheduled jobs that PRODUCE the
numbers, and every way one of them could report success while publishing
nothing.** Read this before editing any workflow — three of the rules below are
now enforced by tests and will fail a push that breaks them.

### `git add a b` is ALL-OR-NOTHING, and it is banned repo-wide

With `b` missing it exits 128 (`pathspec did not match any files`) and stages
**neither**. Verified in a scratch repo, not inferred. Paired with
`2>/dev/null || true` — the form this repo used in five places — it swallows the
message AND the status, and the next line finds an empty index that reads as
"nothing changed", which in these workflows is also the true and common outcome.
One icon, two questions.

- **Stage one path at a time.** `test_workflow_hardening.py` bans the SHAPE by
  counting pathspecs, not the spelling. That distinction was not academic: the
  first version of the test matched `git add $PATHS` and passed while
  `close_position.yml` was staging two literal paths in one call. `git add -A` /
  `git add -u` are a different construct (they name no pathspec, so they cannot
  fail on a missing one) and stay allowed.
- **`|| true` on a `git add` is a PAIRING rule, not a ban.** Allowed only where
  the same step also runs `assert_staged.sh`. Swallowing is genuinely right in
  close_position's ten-path loop — roughly six are legitimately absent on any
  given close — so what was missing there was never the silence, it was
  something downstream that can tell "staged nothing" from "should have staged
  something".

### A bot close that stages nothing is a FAILURE, not a no-op

`Nothing to commit (position not found or already closed).` + `exit 0` was
describing, for `journal_type=bot`, a state that cannot occur: `vivek_run
--close` exits non-zero when no open position matches and the default shell is
`bash -e`, so reaching the commit step means the book WAS edited. An empty index
there was a silent staging loss on the only track record — in the one workflow
whose input is a deliberate human act, and whose loss is the hardest in the repo
to notice (no cron behind it, no freshness badge for "a position you closed by
hand is still showing open").

- **Gated on the journal type, not blanket.** `journal.py --close-manual` prints
  "no open X found - nothing changed" and returns **0**, so for swing/scalp the
  empty index IS the honest no-op the message describes. A blanket gate would
  turn a legitimate outcome red on the legacy pages.
- **The gate names the CANONICAL per-market files and excludes the public
  twin.** `assert_staged.sh` is **ANY-OF** semantics — it passes if at least one
  listed path has a staged diff — so listing a `_write_combined()` derived view
  would let it pass on a run that regenerated the view while the file the close
  actually edited failed to stage.
- **#45/#46/#47:** the close now retries its push five times and `exit 1`s like
  every other writer (it had ONE attempt), regenerating the derived combined
  book after each rebase; the redispatch waits on the right job state and fires
  on `failure` as well as `cancelled`. **`push_exhausted` is the discriminator
  that makes that safe** — contention is worth retrying, a close the integrity
  gate REJECTED is not, and re-dispatching the latter would loop on a bad input.

### `assert_staged` is the WRONG answer where a no-op is legitimate

Nearly added one to `backfill_history.yml` and it would have been a new bug:
`merge_rows` is documented idempotent, so a re-run drops and re-adds its own
reconstructed rows while the output file stays byte-identical — a must-change
gate would fail on exactly the property the script advertises, which is how a
gate gets deleted rather than fixed. The right question is not "did the file
change" but "does the file CONTAIN the reconstruction", which
`_verify_merged()` answers by **re-reading the file off disk** (that is also the
half that catches a write to the wrong path, a truncated write, or an
`os.replace` that did not land). `confluence.yml` is the same family — it gates
on an unstaged working tree instead. **Both absences are pinned by tests**, so
they read as decisions rather than omissions; do not "fix" either.

### #41 — the ASX crons had a four-week hole waiting in October

Every ASX cron was written for AEST (UTC+10), correct only Apr–Oct. Under AEDT
the 10:00–16:00 session becomes 23:00–05:00 UTC — it **opens on the previous UTC
day** — so `7 0-5 * * 1-5` would have covered 11:00–16:00 only and the first
hour of every session, the open, would have had no scan at all. Monday is worse:
its open is *Sunday* 23:00 UTC, which `* * 1-5` excludes outright. Latent in July
and live in October. Fixed the way `kill_switch.yml` fixed the same bug class:
**let cron fire a SUPERSET and let the in-job gate decide with real Melbourne
local time.** The two new 23:xx crons are no-ops under AEST. `test_workflow_dst.py`
(21) pins it. When adding any market-hours cron, add the superset, not the
offset you happen to be in.

### #56 — SHA-pinning was weighed and deliberately NOT done

All 36 `uses:` lines resolve to five distinct **first-party** actions
(`checkout@v4`, `setup-python@v5`, `setup-node@v4`, `cache@v4`,
`upload-artifact@v4`); there are zero third-party actions in the repo. `gh api`
cannot reach any GitHub repo from these sessions (403 even on public first-party
ones) and the one channel that does work routes through a summarising model, so
transcribing five 40-hex SHAs into 36 load-bearing CI lines carries a
catastrophic total failure mode — every workflow *including the test gate* dead
at step 1, on a live trading system, with no green path left to notice. Enforced
on the boundary that actually matters instead: **third-party actions MUST be
40-hex pinned, nothing may float on `@main`/`@master`/`@latest`, and a tripwire
asserts the first-party set is still exactly the five that were reviewed.**
`dependabot.yml` rejected for now (pushes go straight to main, so PRs are noise,
and `pull_request` is in test.yml's triggers so each burns minutes).
The permissions half DID ship: `test.yml` had no block at all and now reads
`contents: read`; `scan.yml`'s cheap `gate` job no longer inherits the
workflow-level write it never needed. **The item's claim that `stop_watcher.yml`
also lacked a block was stale — it has had `contents: read` all along.**

### Also in this tier

**#42** the destructive retry loop (only ever replace a path THIS run generated,
or a sibling's newer copy is deleted and pushed). **#43** a push helper returning
0 after five failed pushes. **#44** timeouts on all 7 previously-unbounded jobs —
one stuck run in the `scan` group silently costs a whole session. **#48** four
path-filter entries the suites READ but CI did not trigger on. **#49** scan.yml
asserts four invariants per market, not just the combined book. **#50** backup
completeness (`sector_history.json` — the only long sector memory — was not
being backed up at all). **#51** `pipefail` on both `| tee` sites: GitHub's
default shell is `bash -e {0}`, so **`-e` is already on but `pipefail` is NOT**.
**#53** the sector-cache warning and a comment that had become false.

### Tests

`tests/test_workflow_hardening.py` (52), `tests/test_workflow_dst.py` (21),
`tests/test_backup_completeness.py` (29); `test_workflow_mutex.py` 11 → 15.
**New `tests/*.py` files need no registration** — `pytest` collects the
directory; only new `test/*.test.js` files need a step in test.yml. The
hardening suite also runs **`bash -n` over every `run:` block in every
workflow**, the cheapest gate this repo did not have: a YAML parse says nothing
about the shell inside the scalars, and a broken `if`/`for`/`fi` is otherwise
discovered by dispatching the workflow — which for a manual close means
discovering it at the moment you are trying to record a real trade.

---

## Engine and backtest truth — TOP100 Tier 4 (2026-07-28, `a724713a`)

Tier 0 fixed alerts that fired into silence, Tier 1 the numbers the guards are
computed FROM, Tier 2 the numbers the owner READS, Tier 3 the jobs that PRODUCE
them. **Tier 4 (57–74) is the layer under all four: where a number is
COMPUTED.** Same rule as the tiers above — the items below changed a MODEL or
recorded a decision, so reading the code without them misleads. The ordinary
line fixes live in the commit body and in TOP100.md per item.

### `risk <= 0` did not catch NaN, and a NaN disarms every guard it touches (#63)

**TRADE-AFFECTING, shipped, and monotonically REMOVING.** `vivek.py` guarded a
plan with `if risk <= 0: return None`. NaN is the only value in Python for which
that test and `if not (risk > 0)` disagree, and NaN is exactly what got in:
`atr = max(atr, entry * 0.001)` *keeps* a NaN (`0.1 > nan` is False, so `max`
returns its first argument) and `swing_low` is a rolling min that is NaN over an
all-missing window.

- **What the NaN does after the plan is built is the reason this outranked
  louder items.** Every gate that should stop it is a `>` or a `<` and all of
  them are False against NaN, so it passes the lot — `gate_grade`'s R:R floor,
  the bot's `wide_stop` and `stop_too_tight`, `size_position`'s `stop_dist <= 0`.
  The row is then booked with `risk_usd = units * NaN`, and a NaN inside a sum
  makes every later comparison False, which **disarms the daily and weekly loss
  guards for the whole book** off one bad ATR bar. A corrupt row does not merely
  mis-price itself; it switches off the thing that limits the damage.
- **`output.py`'s `_finite` NaN-nulling never protected this path.**
  `run.py:177` hands `vivek_run.run_market` the **in-memory** rows, so the
  publish-time scrub only ever cleaned what the browser sees. That is what made
  it a live hazard rather than a display one, and it is worth remembering for
  any future "we already null NaNs" argument.
- Safe to ship autonomously because it can only ever REMOVE a name from
  consideration, never add one: the docstring always promised no plan unless
  risk is positive, so this enforces the stated contract rather than tightening
  it. No threshold, filter, grade or ordering moved.
- The same form was applied depth-only in `_structural_targets`, documented as
  unreachable today (its sole caller now refuses first). Worth having because
  its fallback is *worse* than the bug: `[]` means "no structure, use
  R-multiples", and R-multiples off a NaN risk are NaN TARGETS rather than no
  plan.

### #61 — the backtest half shipped; THE LIVE BOOK IS AN OWNER DECISION

`total_usd` / `max_dd_usd` were adding AUD and USD at face value. Fixed in the
backtest: `config.REPORT_CURRENCY` + `FX_AUDUSD_FALLBACK`, and
`vivek_backtest.fx_rates()` reads the rate the **scan publishes** rather than
fetching its own, so the report and the journal page can never quote different
numbers. The conversion lives in `_risk_usd`, the single point where a trade's
local dollars are produced — `_metrics` multiplies that by `mae_r` too, so
converting in `_dollars` alone would have left the drawdown curve summing A$
troughs into a US$ line.

**The live half is NOT shipped and needs Viv.** `VIVEK_BOT_POSITION_NOTIONAL`
($5,000) is a currency-less number handed straight to `notional = fixed; units =
notional / entry`, and `entry` is quoted in the market's own currency. So an ASX
position is really **A$5,000 = US$3,485** at 0.6969 while a NASDAQ one is
US$5,000 — **the ASX book is ~30% smaller than intended, per position, and has
been since the 2026-07-28 resize.** The same face-value addition is in
`VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL`, in the `risk_usd` the daily/weekly guards
accumulate, and in `VIVEK_BOT_REVIEW_DAILY_LOSS_PCT` (an ASX plan's A$ risk is
compared against a US$ guard, so **ASX under-flags**). The fix is one line —
divide `fixed` by `_fx_of(market)` before sizing — but it makes every future ASX
position **~43% larger in units**, in the ringfenced file. That is position SIZE.
Flagged, not taken. (Owner ruling 2026-07-29, recorded in config.py's SIZING
block: KEPT — the notional is deliberately in each market's own currency; it
carried unchanged to $2,500 on 2026-09-27.)

### Two items closed as FINDINGS, and neither may be "fixed" later

- **#70 — the grade hysteresis counter is correct.** The item is right that
  `vivek.py:570` resets the run counter on an alternating grade and wrong that
  this is a bug. Replaying `scan.py`'s exact feedback loop: `8,7,7,7,7,7` →
  `A+,A+,A+,A+,A,A` (one earned plus exactly `VIVEK_GRADE_HYSTERESIS_MAX_RUNS`
  held, then decay); `8,5,5` → `A+,B+,B+` (a score CRASH demotes immediately,
  because the hold requires `score >= cutoff - margin`); a direction flip kills
  the hold on the spot; a promotion is never held back. Only the oscillating case
  never demotes, and it never demotes because **every 8 genuinely RE-EARNS A+ on
  its own score** — `raw_grade == prev_grade` hits the first early return and
  hysteresis is not consulted at all. The counter bounds how long a grade may be
  held WITHOUT being earned; this one was just earned. Carrying `held_runs`
  through a re-earn — the change I nearly made to tick the box — would demote
  exactly the A+/A boundary wobble the mechanism exists to smooth.
  `test_oscillation_never_demotes_AND_THAT_IS_THE_POINT` is the pin and carries
  the reasoning, so the next reader of `vivek.py:570` reaches it before the edit.
  Still true and still harmless: the held grade inflates `sectorbreadth`'s A+/A
  participation counts (report-only; `discord.py`'s tradeable list read it too
  until that module was deleted 2026-08-27), and
  the bot buys `grade_raw`.
- **#65 — the observability half shipped; the caching half is the DECISION, not
  an unfinished edit.** `_fetch_sector` now returns a verdict beside the value —
  `ok` / `none` (the profile came back and genuinely carries no sector) /
  `failed` (the fetch raised) — and `refresh` counts all three, WARNING on any
  `failed` and naming the consequence in the same line: **a sector-less row is
  exempt from the per-sector cap**, so a network flake does not merely lose a
  label, it quietly widens a correlation limit. Before this, both outcomes were
  the same empty string. What is NOT shipped is caching the `none` verdict:
  `_targets` filters on truthiness, so a cached blank is still "missing" and gets
  re-fetched every run — inert, which is why the observability half could ship
  alone. Making it non-inert means one of two things and **both change which
  trades get taken**: cache the blank and late-arriving sectors are never
  acquired, or treat blank as a bucket the cap counts and start BLOCKING entries
  taken today. `data/sector_map.json` is a signal path. Pinned behaviourally by
  `test_caching_behaviour_is_deliberately_unchanged`.

### `rsi()` reported "maximally overbought" for three different things (#71)

`.fillna(100)` was doing three jobs with one number and only one was right. A
genuine 100 (gains, no losses in the window) is preserved by the replacement,
`out.mask((avg_loss == 0) & (avg_gain > 0), 100.0)`. The other two are now NaN:
the **warm-up** bars, where "not computed yet" was being published as the most
extreme reading the indicator has; and a **halted** series, where `avg_gain` and
`avg_loss` are both zero and RSI is undefined — a name that had not moved a tick
was reading 100. The mask is written on the AVERAGES rather than on the output
because that is where the three cases are still distinguishable; by the time
they are NaN in `out` they are not, which is precisely how one fill came to cover
all three.

**Nothing live moves, and that is proven rather than asserted**, twice over:
`test_no_live_consumer_outcome_changes` runs the real `reversal.evaluate` over
four frames against the shipped `rsi` and a monkeypatched pre-#71 copy and
asserts every derived field is identical; and `evaluate` bails at
`if c <= s26l: return None` — a perfectly flat close IS its own 26-SMA — so a
halted frame is rejected several steps BEFORE the RSI chip under both versions.
This is a correctness fix to a shared indicator ahead of the next consumer.

### `sma_proxy` — the "200-SMA reaction" that was measured on 60 bars (#72)

`sma_window` was published on every plan and read by nothing. It is the tell that
a headline "200-SMA" level was measured against something shorter — a name with
60 weekly bars gets a 60-bar proxy and the row said `200-SMA` either way. Now
`build_tf_plan` publishes `sma_proxy = bool(w < config.VIVEK_SMA)` beside the
window (derived once where the window is chosen, rather than each reader
re-deriving it against a constant it must know), `scan.py` copies both onto the
row from `hp` — **the headline plan, which is what the row displays and what the
bot reads, and which is not always the 1D plan** — and `_report_sma_proxies`
prints counts every run, escalating to a WARNING naming symbols only when a
proxied setup carries `grade_raw in TRADEABLE_GRADES`. A WATCH-grade short
history is a curiosity; an A+ one is a name the bot can buy on a level it has not
really tested. **It is not a filter** — nothing skips, downgrades or reorders,
and the minimum history is still `VIVEK_MIN_WEEKLY_BARS` / `VIVEK_MIN_TF_BARS`.
Refusing a proxied A+ is #89's question and the owner's call; this is the
instrumentation that lets it be answered with counts instead of intuition. Note
the payload's top-level `sma` is only a config echo (always 200) and is NOT this
number; a test says so, because reading it as the window in use is the exact
mistake the field exists to prevent.

### `supertrend` is 25x faster and BIT-IDENTICAL — and it is not vectorisable (#73)

Measured before touching it: **87–100 ms per 1,300-bar frame**, which across the
2,212-name ASX universe is **~3.2 minutes of every scan** for one indicator. Now
**3.4 ms** (192 s → 7.6 s per universe).

- **The item's word "vectorisable" was wrong and the docstring now says so.**
  Each final band is a running min/max whose RESET CONDITION reads the running
  value itself (`close[i-1] > final_upper[i-1]`), and the direction latch reads
  both finished bands, so bar i genuinely needs bar i-1. What cost the 100 ms was
  never the recurrence — it was running the recurrence through `Series.iat`, ~7
  pandas element lookups per bar. The loop is kept and now walks plain numpy
  scalars: same operations, same order, same float64 values. **"Nearly the same
  trail" is worse than a slow one**, so bit-identity was the only acceptable
  outcome for a line that sets trailing stops.
- **Tested against a frozen copy of the pre-#73 loop kept inside the test file** —
  comparing the new code against a re-derivation of itself would prove nothing.
  Bit-identical across 10 lengths including 0/1/2/3 where the seeding lives, four
  tapes, a NaN window, integer prices and a halted frame. Two named tests carry
  reasoning rather than coverage: one asserts BOTH latch directions are actually
  exercised (otherwise the equivalence only covers half the state machine), one
  asserts a NaN band **holds** the trail flat rather than reversing it or going
  NaN (a NaN trail compares False against every price and quietly stops stopping
  anything — `ewm().mean()` skips NaN, so `atr` stays finite through the gap).
- **The `<`/`>` band boundaries are EQUALITY-INERT**, and that is recorded rather
  than chased: at exact float equality both branches assign the same value, so
  `<`→`<=` mutations there are *equivalent mutants*, not test gaps. The one input
  that even reaches exact equality is a fully frozen frame (ATR exactly 0 — a
  halted ASX name), and `test_a_fully_frozen_frame_puts_the_trail_exactly_on_the_close`
  pins that it does not divide, drift or go NaN.

### Also in this tier

**#57** the backtest's "PARITY" docstring described a 1D-plan requirement neither
it nor the live scan had. **#58** it ran the 99-name NASDAQ CSV capped at 60
symbols — the evidence file justifying the edge was computed on **4%** of the
universe the bot trades. **#59** it applied no liquidity gate, and the caveat
existed only in `portfolio_sim`, not in `aggregate`, which is the function whose
output is published. **#68** `not_simulated` omitted `MAX_STOP_PCT`,
`MIN_STOP_PCT`, `MIN_PRICE` and `EARNINGS_BUFFER_DAYS` — the honesty block was
itself incomplete. **#69** drawdown booked P&L only at exit (and `or ""` sorted
missing exit dates to the front), understating intra-trade drawdown. **#60/#66/#67**
every per-ticker exception in the VIVEK and Specs scans was swallowed with no
production output — a name that throws every session was indistinguishable from
one that never sets up — and a market that failed *entirely* printed one line and
exited 0; `scanner/scanerrors.py` is the shared reporter and `run.py` now tracks
market failure. **#62/#64** publishing integrity: `allow_nan=True` meant one NaN
emitted a bare `NaN` token and the browser's `response.json()` rejected the
**entire market file** (blank page for one bad bar), and five publish sites wrote
non-atomically against project rule 7 — all now route through `output.write_json`.
`journal_common.atomic_write` gained a keyword-only `newline`, defaulting None to
keep journal behaviour; `output.py` passes `"\n"` so a local Windows run cannot
rewrite every published artefact with CRLF.

### Tests

`tests/test_backtest_truth.py` (25), `tests/test_engine_truth.py` (62),
`tests/test_publish_integrity.py`, `tests/test_scan_errors.py` — **all four test
the SHIPPED artefact rather than a mirror of it**, and every item in the tier was
mutation-verified (fix reverted, the right tests confirmed red, source restored
and re-grepped). New `tests/*.py` need no registration; `pytest` collects the
directory. Gate at this commit: **1152 pytest across 53 files**, 262 JS across 10
suites, pyflakes at its 9 pre-existing warnings.

---

## The browser layer — TOP100 Tier 5 (2026-07-28)

Tiers 0–4 worked backwards from the alerts to the engine that computes them.
**Tier 5 (75–88) is the last layer: the page itself** — what it escapes, what it
paints as live, what it leaks, and what it does with a fault. Every item here is
front-end only; nothing in `scanner/` or `broker/` moved, and no item changes
which trades get taken. As with the tiers above, only the items that changed a
MODEL or recorded a decision are written up; the line fixes live in the commit
body and in TOP100.md per item.

**Four of these items shipped with their TOP100 entry partly WRONG, and the
correction is recorded beside the tick rather than quietly absorbed.** The
entries were written by reading the code; the fixes were written by running it.
Where they disagree, the tick means "the real defect was found and fixed", not
"the description was accurate" (#85, #87 and #88 described code since removed;
their write-ups and the retraction are in `docs/claude-history.md`).

### #78/#79 — a cached payload is not a live one, and a poll must know its market

`app.js` painted a cached scan with no age check — the front-end twin of Tier 1's
#24, and the same failure in the same direction: a price from an unknown time ago
presented with the confidence of one from just now. #79 is the sharper half. A
`pollForFreshScan` in flight had no cancellation and applied whatever came back,
so **switching markets mid-poll landed ASX rows on the NASDAQ view** — a page
that is not merely stale but wrong about which market it is showing, with nothing
on screen saying so. The poll now checks the market it was started for before it
applies anything, and drops the payload if the answer changed underneath it.

### #86 — the layout read is deferred and coalesced, not removed

`ensureActiveVisible` called `getBoundingClientRect()` inside the render path.
The read still has to happen — the strip genuinely needs to know whether the
active chip is off-screen — so it is deferred into a `requestAnimationFrame` and
coalesced behind a `_visRaf` guard: five calls in one frame schedule one frame
and force zero layouts. The reader half was split into `_scrollActiveIntoStrip`,
which has **exactly one caller** on purpose, and a test counts it: a second
caller would be a path that bypasses the coalescing entirely, which is the only
way this regresses.

### Tests

`test/escaping.test.js` (203), `test/staleview.test.js` (17),
`test/leaks.test.js` (45), `test/statekeep.test.js` (55) — **all four slice the
SHIPPED files and execute the real declarations**, per the standing rule that a
re-typed fixture drifts in step with the bug it is supposed to catch.

- **The sandboxes are built with `new Function(body)()`, NOT `vm.runInContext`,
  and the reason is worth knowing before you copy the pattern.** A `vm` context
  is a separate realm, so its `Array.prototype` differs and every cross-realm
  `deepStrictEqual` fails for reasons that have nothing to do with the code under
  test. `new Function` keeps the same realm while still function-scoping every
  top-level `var`/`let`/`function` in the body, so nothing leaks.
- **`fnSrc()` slices a function by asking the PARSER where it ends** — it walks
  candidate `}` positions and lets `new Function("return (" + cand + ");")`
  decide which one closes the declaration. A hand-rolled brace balancer desyncs
  on the first regex literal or brace-inside-a-string.
- Every item in the tier was mutation-verified: **36 mutations applied one at a
  time to the shipped sources, each confirmed to turn the right tests red**, then
  the sources restored and compared byte-for-byte. One real gap was found that
  way and closed (deleting the "NOT a cache" sentence from #85's comment left the
  suite green).
- **A new `test/*.test.js` file needs its own step in `.github/workflows/test.yml`
  or it never runs.** All four are registered. Gate at this commit: **1160 pytest
  across 53 files, 588 JS assertions across 14 suites**, pyflakes at its 9
  pre-existing warnings.

---

## The screenshot gate was A daily failure email (2026-07-28)

> **CORRECTED THE SAME DAY — this heading used to read "was THE daily failure
> email" and that was wrong.** The defect below is real and worth having fixed,
> but it is not what was going red that week. The gate that was actually failing
> is the LIGHTHOUSE BUDGET, one section down; read both, and read that one first
> if you are chasing a red run today. The two are the same shape — a gate
> measuring something that moves on its own — which is precisely why fixing one
> did not stop the emails and why I believed it had.

`test.yml`'s screenshot-diff step had been failing on the CALENDAR rather than on
any change to the code. Read this before touching
`test/e2e/screenshot-diff.e2e.js` or the baseline cache key.

- **The tell was in the fix history, not the code.** The cache key had been
  bumped nine times, v1 → v10. Ten intentional visual changes in a repo this size
  is implausible; one defect reset ten times is not. Each bump re-cut the
  baseline, bought about a day, and went red again.
- **Measured, with the data held still.** A throwaway probe pinned `/data/` to
  the e2e fixtures — removing the scan output as a variable — and swept only the
  page clock: `journal-desktop` reaches **2.39% drift the moment its cached
  baseline is two days old**, against a 2% budget, and reads exactly 2.39% at 2,
  3, 5 and 7 days. FLAT, not rising. journal.js renders relative ages, so what
  the gate was photographing was a single day-bucket boundary repainting a block
  of rows at once — a step function, which is why "it fails some days" never
  resolved into a pattern anyone chased. `journal-390` sits one row behind at
  1.90%, i.e. it was next.
- **`actions/cache@v4` is what turned a bad day into a permanent state.** An
  exact key with no `restore-keys` persists and is refreshed on access, so the
  baseline never ages out on its own: once past two days, EVERY subsequent run
  fails until the key moves. The gate could not recover by itself, which is
  exactly why it needed a human nine times.
- **Why roughly one email a day and not twenty:** test.yml's path filter
  deliberately excludes `public/data/**`, so the ~20 daily scan commits never
  trigger it. It runs on pushes to code — one or two a day.

### The fix is three layers and only the middle one persists

1. **The page clock is frozen** to the fixture book's own `updated_at`
   (`FROZEN_MS`), installed CONTEXT-level via `ctx.addInitScript` before
   `newPage()` so nothing can read the real clock first. The baseline's AGE stops
   being an input at all. A `Proxy` rather than `class extends Date`, because the
   page parses its own timestamps with `new Date(t.opened_at)` and explicit
   arguments must pass straight through — pin only the zero-arg construction and
   `now()`.
2. **The cache key digests the fixtures** —
   `hashFiles('test/e2e/fixtures/data/*.json')`. `FROZEN_MS` is derived from
   those files, so refreshing them MOVES the clock and legitimately repaints
   every relative-time row. With the digest that cuts a FRESH cache entry, which
   self-baselines and **saves**. This is the only layer that persists.
3. **A `.clock` sentinel inside `__baseline__`** — the floor. It records the
   instant that drew the baseline and lives inside the cached directory so it is
   restored or missed as one unit with the pictures it describes. Two states mean
   "not drawn by this clock": the stamp disagrees with today's `FROZEN_MS`, or
   there is no stamp at all beside PNGs that plainly exist (the shape of a
   pre-freeze baseline restored from an old cache — the one case a key bump
   cannot see). Both **DISCARD and re-cut rather than fail.**

- **The discard-don't-fail asymmetry IS the item, not a softening.** A
  re-baseline costs one run of comparison. A red costs a person's attention on a
  push they cannot act on, and a channel that cries wolf gets muted — which is
  the damage that outlives the bug, because the next red is a genuine one.
  `test_a_baseline_from_a_dead_clock_is_DISCARDED_not_failed` pins the shape
  (no exit, no failure counter, no throw inside the reconcile) precisely because
  the tempting future edit is "make it strict".
- **The sentinel's own limitation is stated in both files rather than hidden.**
  cache@v4 does **not** re-save on a key HIT, so a discard cannot persist: if the
  fixtures ever move without the key moving, every run discards, re-cuts and
  passes — green for ever, comparing nothing. The reset log names that symptom
  and the remedy ("bump the screenshot-baselines key in test.yml") in those
  words, and a test asserts the reset count reaches the run summary so a discard
  LOOP is visible rather than silent.
- **NO `restore-keys` on that cache, ever** — a prefix fallback restores the very
  baseline a bump exists to discard.
- Tests: `test/screenshot_sentinel.test.js` (14 — slices `CLOCK` and
  `reconcileBaselineClock` out of the shipped e2e file and runs them against real
  temp directories, per the standing rule that a re-typed fixture drifts in step
  with the bug) and `tests/test_screenshot_determinism.py` (13), all
  mutation-verified. The JS suite runs in the CHEAP `javascript` job on purpose —
  no browser needed, ~50ms, checked on every push rather than behind a Playwright
  install.
- **One of those tests closes a gap open since Tier 5:**
  `test_every_javascript_suite_has_a_step_in_the_workflow` walks `test/*.test.js`
  and fails if any of them has no `node test/<file>` step. The rule was written
  down in three places and enforced by nothing — an unregistered suite is not a
  weak gate, it is a file full of green assertions that CI never runs.

---

## The Lighthouse budget was measuring the TAPE (2026-07-28)

**This is the gate that was actually sending the daily failure emails.** The
section above fixed a real defect in a different gate and I believed it had
closed this; it had not, and the next run — of the fix commit itself — failed
again. Read this one first if you are chasing a red run.

### How it was found, and what I should have done a day earlier

By **reproducing the job**, which is the whole lesson here. The section above was
diagnosed from the *fix history* (nine cache-key bumps) and never from a failing
run. "This gate has a permanent bug" and "this gate is what went red on Tuesday"
are different claims; only the first was supported.

CI *logs* are not readable from a sandbox session (`gh` and `api.github.com` both
403), which is what made inference tempting. But the `e2e` job is **entirely
reproducible locally** — that is the thing worth remembering:

```bash
git worktree add -f /tmp/ci-repro <sha>          # the exact commit CI ran
export PW_CHROMIUM=/opt/pw-browsers/chromium     # preinstalled; NEVER `npx playwright install`
node test/e2e/smoke.e2e.js                       # and screenshots / lighthouse / screenshot-diff
```

At `9d6221fe`: `javascript` green, `python` green, `e2e` **red on the third of
five steps**, one line — `FAIL transfer 5.00MB < 5.0MB`.

### What 5.00MB was made of

4.15MB of committed scan data (`asx_vivek.json` 2.06, `phasemap/asx/latest.json`
1.38, `vivek_backtest_longonly.json` 0.62, five smaller files 0.30) plus ~0.85MB
of all code, CSS and fonts together.

**The growth was legitimate market breadth, not bloat** — checked rather than
assumed. Live vs fixture `asx_vivek.json` is the same schema with **343 rows
against 204**, every field group scaling with the row count (1.68× the rows,
1.74× the bytes). Nothing regressed. The budget was gated on **how many ASX
stocks happened to set up that day**.

### The two gates are the same shape — that is why one fix did not cover both

Both were measuring something that moves on its own, so both failed on commits
that did not change it. The screenshot gate's moving part was the **calendar**;
this one's is the **tape**.

The delivery mechanism is identical too, and it is worth internalising before
adding any gate that reads `public/data/`: test.yml's path filter **deliberately
excludes** `public/data/**`, so the ~20 daily scan commits never trigger the
gate. The payload grows silently for days and the next unrelated **code** push
wears the red. That exclusion is still correct — it exists so 20 daily commits
don't each pay a Playwright install — but it makes any data-reading gate a
delayed-action fuse pointed at whoever pushes next.

- **Corollary that cost a day: a failing step ABORTS the job.** Lighthouse runs
  two steps before `screenshot-diff`, so at `9d6221fe` the screenshot fix was
  never merely unproven in CI — it was **unexecuted**. A green step later in a
  job tells you nothing if an earlier one is red.

### The fix is two layers, and only one of them is a gate

1. **The gate serves a STAGED root, not `public/`.** A temp dir of symlinks to
   every `public/` entry except `data`, plus one symlink pointing `data` at
   `test/e2e/fixtures/data` — the same fixture set `screenshot-diff` routes to,
   so the two e2e gates now measure and photograph the *same page*. It has to be
   done at the HTTP root rather than with request interception because
   **Lighthouse drives Chrome through `chrome-launcher`, not Playwright**, so
   `ctx.route()` is not available to it. `unstageRoot` unlinks and removes the
   dir in a `finally`, swallowing errors — a leaked temp dir is not worth failing
   a gate over.
2. **The real payload is still measured and is structurally incapable of failing
   the run.** Derived from Lighthouse's own `network-requests` audit rather than
   a hard-coded URL list, so it stays complete as pages add fetches and it
   records 404s (a missing fixture gets named, not silently skipped). It returns
   `null` when the audit is unreadable — **never a zeroed object**, which would
   read as "0MB, all good". Prints every run, raises a `::warning::` past 7MB,
   gates never.

**Slimming a 4.45MB dashboard payload is a product decision, not a CI fix.** That
is precisely why this half reports instead of gating — the CI job's business is
regressions in code, and it had been quietly conscripted into having opinions
about market breadth.

With `/data/` pinned the budget could also come DOWN: **5.0MB → 2.5MB**, against
a now-deterministic 1.86MB baseline. Post-fix: `transfer 1.86MB`, `CLS 0.123`,
`live payload ~5.08MB` across 11 `/data/` requests — which independently
corroborates the 5.00MB measured off live data by a different mechanism.

### Tests, and the one deliberately NOT written

`tests/test_lighthouse_budget.py` (14). Mutation-verified: 19 mutations, one at a
time, every one caught.

- **The pass found a real gap.** `test_the_page_is_loaded_in_measurement_mode`
  asserted `"?lite=1" in src` — and the file's own header comment discusses
  `?lite=1` at length, so stripping the query string off `URL_UNDER_TEST` left
  the gate measuring un-pinned deferred work while the test stayed green **on the
  prose**. It now asserts against the URL constant and against
  `lighthouse(URL_UNDER_TEST,` being the navigation call. TOP100 #34's
  mirror-drift in its cheapest form, and unreachable by reading.
- **The test I nearly wrote and rejected:** asserting `TRANSFER_BUDGET_MB * MB <
  (size of real public/data)`. It reads `public/data/`, so it goes red on a quiet
  tape — rebuilding the exact tape-dependency the fix removes, one level up, in
  the suite that exists to prevent it. The module docstring records this so it
  does not get "added for completeness" later.

### Two verification habits this cost enough to be worth keeping

- **Prove a mechanism in a browser, not with grep.**
  `tests/test_screenshot_determinism.py` can only check that `addInitScript`
  appears in the source — it cannot tell an installed freeze from a decorative
  one. A throwaway probe loaded the real page in two contexts, one frozen and one
  not, and showed the page itself reporting `Date.now() === FROZEN_MS`, the
  Proxy's escape hatches intact (`Date.parse`, `Date.UTC`, `instanceof`, explicit
  args), and the control seeing a real clock already **2.76 days past** the
  freeze — i.e. load-bearing today, not theoretically.
- **A pipeline's `$?` is the LAST command's status.** `node x.js | tail -40; echo
  "RC=$?"` reports `tail`'s exit code, which is always 0. Redirect to a log file
  and echo `$?` immediately, or a failing gate reads as a passing one.

### A smaller finding shipped in the same batch

It is about a number that was right but had **nothing on it saying what it
meant** — the failure mode that survives review because the value looks fine.

- **The backtest's dollar column had no stated basis.** `_sizing_basis()` now
  travels with both `params` call sites in `scanner/vivek_backtest.py`
  (`equity`, `position_notional`, `sizing_mode`), and `build_report` carries a
  caveat naming it and pointing readers at `total_r`. Not a wrong number — a
  right number with no regime attached, which **after the 2026-07-28 resize is
  the difference between two incomparable series** being read as one track
  record. `tests/test_backtest_truth.py` 24 → 31.
- Gate at this commit: **1193 pytest across 55 files, 613 JS assertions across 15
  suites**, all four e2e steps green locally including `screenshot-diff` at 0.00%
  drift on four images.

---

## 2026-08-20 batch — three facts the next session must not re-derive

1. **The three dispatch/sync endpoints are access-logged** (`functions/api/
   _access_log.js`, `alog:*` keys in JOURNAL_KV, 4-day TTL). Best-effort by
   construction — a KV failure can never block a close/scan/journal action —
   and NO request bodies ever. Successful journal GETs COALESCE to one
   `alog:seen:` marker per IP per UTC day: the page polls GET every 60s and
   KV writes are the scarce quota (journal.js's own limiter comments), so
   per-request success logging would burn the budget sync itself needs. The
   api_guards "hit-GET writes" pin was updated to exactly this bound — do not
   "fix" it back to zero, and do not log per-request there either. **UPDATED
   2026-09-21: /api/journal and the coalescing branch are gone with the manual
   journal; the two remaining callers (close, scan) are daily-capped, so every
   call is logged individually and the quota argument is the reason coalescing
   must come BACK WITH any future polled endpoint rather than sit uncalled.**
2. **Auth on /api/close and /api/scan is a Cloudflare Access decision, not a
   secret** — both are called from BROWSER JS (app.js SCAN button, stalled.js
   and the journal's close-all), so a shared secret would ship in page source
   and protect nothing. (/api/journal was the third and its CI-side reader was
   `confluence_alert.py` with GBS_SYNC_CODE; both went 2026-09-21.) The Access write-up
   went to the owner in the 2026-08-20 batch summary; until he configures
   it, the access log above is the compensating control.
3. **`backups/` in-tree commits are LOAD-BEARING — do not drop the commit
   step without rewiring the watchdog.** `watchdog.py` probes the committed
   `backups/` dir's newest snapshot age (`backup_stale`, CRITICAL, 26h) from
   kill_switch.yml/crypto_bot.yml CHECKOUTS; stop committing and that alarm
   rings forever. The commit step's assert_staged is also in the pinned
   caller set. The batch's Task 8 was stopped-and-flagged on exactly this;
   the safe path (drop the dir probe, lean on WATCHDOG_RUNS's run-history
   probe — which deliberately goes SILENT on a failed latest run, a real
   trade-off on a CRITICAL alarm) needs the owner's sign-off.

## HORIZON + REGIME — REMOVED ENTIRELY (2026-09-20)

Owner, pointing at the LOOK WIDER / NARROW strips on the deck: *"Get rid of
it entirely, rip out the guts of it, it's a waste of space and i never look
at it."* Scope confirmed as "Everything": the two deck strips, the two
Sectors-page boards, both Python engines (`scanner/sectorbreadth.py`,
`scanner/regime.py`), their `SECTOR_BREADTH_*` / `REGIME_*` config blocks,
the `run.py` wiring, `public/data/sector_breadth.json` + `regime.json` +
`data/sector_history.json` (and their scan.yml SHARED-list and backup-list
entries), the backfill (`scripts/backfill_sector_history.py` +
`backfill_history.yml`), the `sector_run` NOTICE event, `public/js/horizon.js`
+ `regime.js` + both CSS files, and every test that pinned them
(`test_sector_breadth/test_regime/test_backfill_sector_history.py`,
`test/regime_stretch.test.js`, the #55 backfill block in
`test_workflow_hardening.py`, the #88 suite in `statekeep.test.js`, the
strip pins in `staleview.test.js`). **`sectors.html` STAYS** — it is the
NEWS & MARKETS page (`js/sectors.js`, movers, calendar) with its own
content; only the two panels came off it, and the NEWS nav tab is untouched.
**NEWS page trimmed again 2026-09-27** (owner: "I don't need it"): the
Explain-like-I'm-5 box, Biggest volume, the Indices cards and the US
top-stories TradingView widget are gone; `scanner/sectors.py` no longer
writes `eli5`/`top_volume` (both left `ENRICHED_KEYS`). `indices` is still
FETCHED because `_read` builds the "What happened" sentence from it — it is
just no longer drawn as cards. Pins: `test/hygiene.test.js`,
`tests/test_sectors_carry.py`. Do not re-add them.
**The bot's per-sector correlation cap (6 per market since 2026-09-27;
`sector_map.json` / `sectorcache`) is unrelated and stays** — it is a signal path, not a report surface.
`alert_returns._breadth_series()` now returns `{}` so `breadth200` stays
blank on new ledger rows (frozen values on old rows survive under the
blank-only rule). The HORIZON, BACKFILL and REGIME write-ups are in
`docs/claude-history.md` as history of code that no longer exists — do not re-add any of it;
`git log -- scanner/sectorbreadth.py` at the removal commit has the engines.

## CRYPTO DATA SOURCE — exchange klines, one entry point (2026-09-28, owner-ruled)

Owner: *"Nah make the VIVEK crypto scan and paper bot go to the binance or
bybit. That way it's all in SYNC."* Until this, EVERY crypto bar (scan, bot
marks and stops, kill switch, every lens) came from Yahoo's aggregated
`<SYM>-USD` series; Bybit was wired only as the kill switch's ORDER client.

- **One entry point: `scanner/data.py::fetch(market, tickers, period,
  interval, ref_prices)`** → `({ticker: frame}, report)`. Crypto with
  `config.CRYPTO_DATA_SOURCE = "exchange"` → `scanner/exchange_data.py`
  (public, KEYLESS klines; no credentials, no order paths — test-pinned);
  every other market → `download()` exactly as before. Callers: `run.py` (the
  scan download), `scan.py::_bars` (its fallback + the 4H plans' bars; it forwards every
  identity kwarg),
  `vivek_run.py` (off-universe stragglers + CLI), `kill_switch._live_marks`,
  the IGNITION lens. `tests/test_crypto_source_switch.py` fails if any of
  them stops calling `fetch`. **Revert = one line**: `CRYPTO_DATA_SOURCE =
  "yahoo"`.
- **Venues, MEASURED from a GitHub runner (the kick of 2026-09-28):**
  `data-api.binance.vision` (Binance's market-data mirror) ANSWERS;
  `api.binance.com` → **451**, `api.bybit.com` → **403** (both geo-block US
  hosts — GitHub's runners are US); Coinbase answers. Order:
  `EXCHANGE_KLINE_SOURCES = (binance_vision, binance, bybit, coinbase)`; a
  venue that refuses or errors on the probe coin is dropped for the run.
  First run: 117 coins Binance, 15 Coinbase, 36 Yahoo fallback; coverage
  137 → 168 of 201.
- **THE IDENTITY CHECK — a ticker is not an identity.** The side-by-side run
  found Yahoo pricing a DIFFERENT TOKEN under the same ticker: AERO
  +2,623,839% vs Binance, JUP +96,729%, ARB +35,210%, PRL, SKY, XCN… — so the
  old Yahoo crypto scan had been scanning the wrong instrument for those
  names. Every source's latest close must sit within `CRYPTO_IDENTITY_TOL`
  (0.40) of CoinGecko's current price for the coin (the universe now carries
  `cg_price`), else that source is rejected for that coin and the next tried;
  a coin nothing confirms is LEFT OUT, never scanned as a stranger. The
  report publishes `identity_rejected`.
- **EVERY path a crypto price takes to the book is guarded, not just the
  scan's (pre-merge review, 2026-09-28 — three independent reviewers found
  the same holes; all fixed, `tests/test_crypto_identity_paths.py`, every
  fix mutation-checked):**
  1. **The frame cache never refills a REFUSED coin.** `fetch()` reports
     `refused` (every source priced a different token) and
     `merge_with_cache(..., refused=)` neither back-fills nor re-saves it —
     it used to hand straight back the stranger the check had just refused.
     **And exchange mode has its OWN cache file** (`crypto.exchange.pkl.gz`,
     `ignition-crypto.exchange…`): the pre-switch cache actions/cache
     restores holds Yahoo's wrong-token M / MNT (~$0.0003 for coins at ~$1-2).
  2. **A held coin must reproduce its OWN recorded history.** The kill
     switch and the book's off-universe fetch pass
     `data.held_price_kwargs(positions)`: a venue's frame must close within
     `CRYPTO_ANCHOR_TOL` (0.15) of the position's HISTORY ANCHOR on the
     anchor's date (`exchange_data.anchor_ok`) — on WHATEVER venue answers.
     The anchor is the position's stored `anchor` [date, close]:
     `vivek_run._stamp_identity` writes it (with `data_source`, the venue the
     chart draws) only when `_mark_sanity` ACCEPTS a mark or a position
     opens, and only from an identity-CHECKED frame (`data.anchor_of`, the
     frame's last completed close). **It is a real past close, not a mark**
     (fourth review): the first cut anchored on `day_marks[D]`, but a mark
     only moves when a price is accepted, so after an outage it lagged the
     market, every venue failed it and the position stayed unpriced FOR
     EVER — and Yahoo publishes D−1 late, so a D−1 anchor failed every
     Yahoo coin each morning. `day_marks` survives only as the fallback for
     a row stamped before `anchor` existed (a malformed stored anchor falls
     back too). The kill switch sizes its window from the oldest anchor
     (`held_fetch_period`; an old anchor = the bot stopped marking, exactly
     when the check matters). A same-ticker stranger fails the anchor
     (Binance's AI and MET; a venue re-listing a symbol as a new token); a
     real move since cannot; an outage at one venue falls through to the
     next. A position with no anchor at all is checked against its last mark
     at 0.40. A quote either check refuses leaves the kill switch on its
     stamped mark and the book position unpriced (counted), never on a
     stranger.
  3. **A delisted pair is not a price.** Binance's mirror keeps serving a
     dead pair's frozen klines; a venue whose newest bar is older than
     `EXCHANGE_MAX_BAR_AGE_DAYS` (**1** — crypto trades 24/7 and every venue
     opens today's candle at 00:00 UTC; at 3 a pair frozen two days ago
     still beat a live venue and froze a held coin's mark) is skipped for
     the next venue and named under `stale_rejected`. For a coin left with no frame, `refused` +
     `rejected_venues` let `merge_with_cache` block a cached frame FROM A
     REJECTED VENUE (the stranger, the frozen pair) or of unknown venue,
     while a cached frame from a live venue that merely failed this run
     (LIT's Yahoo series on a throttled run — seen on a real run) refills.
  4. **An OLD reference is answered by a HISTORY ANCHOR — not a wider band,
     not a venue pin.** On a CoinGecko outage the universe comes from the
     snapshot (`cg_stale`) and `data.identity_kwargs()` anchors every coin
     whose last IDENTITY-CHECKED frame is in the frame cache to that frame's
     last completed close; a coin with no such frame keeps the tight 0.40
     band against the old price; one with neither is REFUSED
     (`require_identity`). Frames record how they were checked
     (`attrs["identity"]` = ref / anchor / none) and an unchecked frame is
     never an anchor. **Two designs died in pre-merge review first:** a
     wider [0.2x, 5x] band let a Binance 'MET' 43% under the real one price
     a HELD coin and fire its stop (−2.88R, −4.68R once the sanity guard
     gave in); venue PINS let an unchecked frame become a trusted pin, gave
     a pinned venue no check at all, and froze a held coin's mark when the
     pinned venue was down. `CRYPTO_IDENTITY_TOL_STALE` is gone (test-pinned).
     `unchecked` in the report + a WARNING = frames priced with no evidence
     (a fresh universe coin CoinGecko gave no price, e.g. the FLASH extra).
  5. **The 4H plans were built off OTHER INSTRUMENTS on main, crypto AND
     ASX** — `_attach_h4_plans` asked Yahoo for the bare symbol ("ETH" =
     Ethan Allen, 25.7 on a $2,695 coin; "BHP" = the NYSE ADR) and was
     handed the MarketConfig, so its crypto branch never ran. It now gets
     the market key, asks for `symbol + suffix`, and pins each coin's 4h
     candles to its daily venue where that venue has 4h candles (Coinbase
     has none, so those coins walk the venues), all checked against the row's
     price. Display only; nothing reads a 4H plan to trade. Real run: 15 of
     16 crypto rows now carry a real 4H plan, and ASX 4H plans go from ~4 of
     226 rows to nearly all (the ASX detail file grows ~135KB).
- **What moved, measured:** freshness — at 02:15 UTC exchange bars had the
  prior day complete for 100/100 coins, Yahoo for 0/100 (Yahoo was a day
  behind); median close gap to Yahoo 0.07% (90th pct 1.27%) where the ticker
  IS the same coin; **liquidity — one exchange's quote volume is smaller than
  Yahoo's aggregate: 63/100 coins clear the $3M floor on exchange volume vs
  85/100 on Yahoo's**, so thin alts leave the deck. The floor itself is
  untouched — **put to the owner the same day and he ruled "Keep"**: $3M
  stays, now read on single-venue volume; do not lower it or re-raise it
  without his ask. Open book at the switch: BNB only; no colliding ticker was
  ever traded.
- **Published:** every scan payload gets `data_sources` (mode, per-venue
  counts, refused venues, identity rejections); crypto rows carry
  `data_source`. The chart reads it: a Binance-sourced row draws Binance
  candles + a Binance header quote through `/api/price` / `/api/quote`
  (`_prices.js` now asks the mirror first and PAGES past Binance's 1000-bar
  cap, bounded at 4 pages); anything else draws Yahoo as before.
- **CLOUDFLARE CANNOT REACH BINANCE — the chart reads it from the BROWSER
  (2026-09-28, measured).** `ops.yml site-probe` with `paths` fetched the live
  `/api/price`: BNB and QNT asked `src=binance` came back `source: "yahoo"`, TAO
  came back 502. So `_prices.js`'s Binance leg never answers from the Pages
  Functions, every "Binance" chart had been Yahoo's copy of the coin, and a coin
  whose Yahoo `<SYM>-USD` is a different token (TAO) had nothing. `chart.js`
  `binanceDirectBars` / `binanceDirectPrice` now fetch klines + the header price
  from the reader's browser (mirror, then api.binance.com; paged 4 x 1000 like the
  proxy) for a Binance-sourced row, and the proxy is the FALLBACK — a browser
  that cannot reach Binance gets exactly what it got before. Yahoo-sourced rows
  never touch Binance. Pinned behaviourally in `test/deep_history.test.js`.
  Re-measure with `site-probe` + `paths` before trusting the proxy's Binance leg.
- **Verification without touching main:** `.github/workflows/
  crypto_source_check.yml` (read-only; kick `.github/crypto-source-kick`) runs
  `scripts/crypto_source_compare.py` + `scripts/crypto_scan_dryrun.py` — the
  REAL crypto scan on exchange klines, writing nothing, diffed against the
  published scan. crypto_bot.yml is never dispatched from a branch: its
  commit step pushes to main.
- **Still on Yahoo, by scope:** PhaseMap (spec-governed provider) and the
  momentum lens for crypto — including the same wrong-token tickers above.
  Stocks everywhere. Tests never reach an exchange (`tests/conftest.py`
  refuses every venue unless a test installs its own fake).

## IGNITION — the coil → ignition lens (2026-09-28, owner: "build it") — REPORT-ONLY

**Why it exists.** QNT ran 71 → 373 (intraday) over 24–27 Sep 2026 while the
deck showed nothing. The committed scan history says the scanner HAD it: VIVEK
graded QNT **A, 1D break armed (🎯 High Conviction)** from 24 Sep 18:24 to
25 Sep ~9pm Melbourne at $71.64 (entry 69.73, stop 55.56, 3.0:1). Three things
lost it: (1) the bot's weekly/3d level gate refused a daily-200 row (correct —
do not loosen it on one anecdote); (2) VIVEK deletes a row the moment price
leaves the 4% band, so a setup that WORKS vanishes; (3) nothing looks for the
SHAPE — months of compression, then a close out of the base on a multiple of
volume — as a thing in its own right (Specs does, but only ASX/NASDAQ under
$0.50; the "arriving" list only runs inside the VIVEK branch; PhaseMap read
QNT's 23 Sep poke as a BEARISH sweep).

**Also found chasing it: the crypto universe was never the top 200.**
`CRYPTO_UNIVERSE_SIZE = 200` made the one-page CoinGecko request ask
`per_page=260`; CoinGecko caps it at 250 and silently serves its default 100,
so the universe SHRANK 101 → 86 on 2026-09-20. `universe._fetch_crypto` now
pages at the cap (`tests/test_crypto_universe.py`; the old test pinned the bug).
**The wider universe let PEGS in, so the peg rule grew (2026-09-28).** The
first dry VIVEK crypto scan on exchange data graded **EURCV (a euro
stablecoin) A+ and U ("United Stables") A** — and the OLD 86-name cache
already held USDF, USYC, USTB, EUTBL, EURSAFO and USDGO, pegs and tokenised
cash/T-bill funds the `<X>USD` rule never saw. `universe._is_stable(sym,
name)` now also drops `USD<X>` / `EUR<X>` tickers, an explicit list of
non-dollar fiat pegs and tokenised funds, and CoinGecko NAMES carrying a peg
word (stablecoin(s), stables, USD, dollar, EUR, euro, treasury, T-bill,
money market, government securities/bonds, CLO); a cached snapshot is
re-filtered on load. It only ever REMOVES names, which is what the owner's
original skip rule says pegs are. **Gold/silver tokens (PAXG, XAUT, KAU,
KAG) stay — the metal trends and they were always scanned on purpose**; a
singular "Stable" (the STABLE chain token) stays too. The dry run prints the
rows the rule drops (false positives) and anything still scanned whose year
never left a 30% band (misses). Its first run on a runner: 40 rows dropped,
every one a peg or cash fund; misses YLDS and USAT (x1.00 / x1.01 over a
year) and the yen coin JPYC went onto the explicit list; what remains in the
band is XAUT (gold) and HTX (a real, quiet token). **Re-run
crypto_source_check after any universe change and read that line** — the
explicit list is where a new odd-named peg has to be added. Pins:
`tests/test_universe.py`.

- **Package:** `scanner/ignition/` — `engine.py` (pure, causal features shared
  by the screen AND the replay: one implementation, two readers), `run.py`
  (CLI; exit 0 published / 3 kept the last file / 1 failure), `backtest.py`.
  Publishes ONLY `public/data/ignition/<market>.json` + `<market>_charts.json`
  (+ `<market>_backtest.json`) for each market in `IGNITION_MARKETS`.
  Config: the `IGNITION_*` block — every threshold PRE-REGISTERED before the
  first real run; a change bumps `IGNITION_RULESET_VERSION`.
- **The rule.** COIL (one bar, all four): SMA 9/26/43/200 within 12% of each
  other; ATR%-of-price in the bottom 25% of its 2-year window; 20d volume in
  the bottom 35% of its 2-year window; ≥50% under the 3-year high. TRIGGER
  (completed bar): coiled on any of the 10 bars BEFORE it; close > the 60-bar
  base's highest high; volume ≥ 3× the prior 20-day average; ≤60% over the
  9-SMA; $1M/20d base and $3M trigger-day turnover (crypto volume is already
  USD). One trigger per move (20-bar rearm). PLAN: stop = max(base low, base
  high − 1×ATR(t−1)); exit at the next open after a daily close below the
  9-SMA — NO fixed TP ladder (Specs' ladder averaged a 1.03R win: it cut every
  runner). The 2-year rank window replaced a drafted 1-year one BEFORE any real
  data was seen: a year-long base becomes its own reference and stops ranking
  quiet.
- **States on the page:** IGNITING (fired on one of the last 2 completed bars)
  → RUNNING → CLOSED (kept 20 bars ON PURPOSE — a list of only winners is the
  survivorship this lens exists to stop), COILED (a trigger tomorrow would
  count). `provisional` = the FORMING bar qualifies; never confirmed (QNT's own
  23 Sep poke closed back inside the base). Once the bar after a trigger exists
  the row is priced from ITS OPEN — the replay's fill — so page R and evidence
  R are one number.
- **The replay's honesty rules (each closed an audit finding, 2026-09-28):**
  realised trades only (open/pending are marks beside the stats, never in
  them); the design case (QNT from 2026-09-01) is NEVER scored — it informed
  the thresholds; the baseline is random timing on the SAME coin within ±182
  bars (same season) drawn only from bars the rule could have traded; the
  decision statistic is `versus.random_timing` (primary minus baseline,
  cluster-bootstrapped by entry month — alt ignitions bunch); exit variants
  trade exactly the primary's entries; the sensitivity grid is a robustness
  distribution, never a menu. A FORWARD bucket (from 2026-09-28) is the only
  truly unseen data and accrues from now.
- **Fences (`tests/test_ignition_fences.py`, AST-based, both directions):**
  nothing under `scanner/broker/` (or vivek/scan/conviction/confluence/
  morning_plays/run.py) can reach the lens; the lens imports only config,
  data, output, universe, scanerrors, indicators. NOT confluence, NOT traded.
- **Workflow `ignition.yml`:** own concurrency group PER BRANCH
  (`ignition-<ref>`); crons 00:14 UTC (the new completed crypto bar) + 01:14/
  02:14 backstops that skip once today's file exists + 4 intraday refreshes;
  the backtest runs on a manual dispatch or a push touching
  `.github/ignition-kick`, committing back to the PUSHED branch (never a
  hard-coded main). assert_staged once PER reported path. Deliberately no
  WATCHDOG_RUNS entry (momentum precedent, pinned as a decision).
- **Front end:** the `⚡ Ignition N` pill sits THIRD on the crypto deck
  (after A+ and A, so a 390px phone sees it without swiping; a placeholder
  holds the slot while the file loads, so nothing reflows). N = confirmed
  IGNITING — the panel heading prints the same number from the same function;
  forming-bar breaks show as visible "+N forming" text, never in N. It opens
  `#ignition-panel` (`public/js/ignition.js` + `css/ignition.css`; the
  backtest file is fetched only when the panel opens). **A symbol link carries
  `src=ignition`, and chart.js reads the VENUE off the lens row when VIVEK has
  no row for the coin** (2026-09-28: TAO, Binance-sourced, dead-ended on Yahoo's
  "TAO-USD", which is not Bittensor — `ignitionMeta()` → `pmOnlyFallback` sets
  `VIVEK_CRYPTO_SRC`; pinned in `test/deep_history.test.js`). That alone did
  NOT fix it -- see "Cloudflare cannot reach Binance" under CRYPTO DATA SOURCE. **STALE** (⚠ on the
  pill, a badge in the header): the run is over 26h old, or — 6h past 00:00
  UTC (`STALE_BAR_GRACE_H`; the 00:14 cron lands late, and a mark that lit
  every morning would be learned-to-ignore) — the newest completed bar is
  older than UTC-yesterday. The evidence line only PRINTS the file's numbers
  (realised n, open-not-counted, expectancy, OOS, vs random timing with CI
  and P, top-5 share); JS computes no statistic. A payload fault anywhere
  hides the panel, resets the pill and re-raises; the deck keeps rendering.
  Tests: `test/ignition.test.js` (mutation-verified),
  `tests/test_ignition_frontend.py` (JS market list == config).
- **THE ASX PORT (2026-09-29, owner: "Yes and factor in the converting
  windows from calendar days to trading days and everything else" — after
  DTR ran 0.063 → 0.127 while only VIVEK flagged it, a session late).** Same
  rule, same thresholds, `IGNITION_RULESET_VERSION` unchanged (crypto is
  byte-identical). What differs, all pre-registered before the first ASX
  replay: (1) CALENDAR windows are written in crypto bars and rescaled by
  `engine.bars()` = round(n × `IGNITION_BARS_PER_YEAR[m]` / 365): ASX rank
  window 504, rank/drawdown warm-up 252, drawdown lookback 756, min history
  276, replay max hold 124, random-timing window 126; crypto ×1 exactly.
  CHART-CONVENTION windows (SMA 9/26/43/200, ATR 14, 20-bar volume/RVOL,
  the 60-bar base, coil lookback, rearm, keep, 9-SMA trail) stay in bars —
  the owner reads a 200-SMA as 200 trading days on an ASX chart; a 60-bar
  base is ~3 months there (stricter). (2) Floors A$100k base / A$300k
  trigger day (Close × Volume). (3) Replay cost 1.0% round trip (a tick is
  ~1% of a 9c price). (4) Data-age ceiling 5 days (Easter). (5) Regime line
  = the ASX 200 (`^AXJO`) vs its 200-SMA, fetched beside the universe, never
  screened; the ASX payload's regime block uses generic keys (`label`,
  `above_200`, …) and the replay groups `by_regime`. (6) DTR is the ASX
  DESIGN CASE (never scored; reported under `cases`); forward bucket from
  2026-09-29. (7) The replay drops a name whose turnover never clears both
  floors on one bar (ASX only — a speed-up that changes no trade, pinned).
  Per-market values live in `*_BY_MARKET` dicts read by `engine.mkt()`. The
  deck pill now shows on the ASX deck too; a session market's run-age rule
  counts WEEKDAY hours against `STALE_SESSION_H` = 50 (a Friday screen is
  fresh on Monday; a Monday holiday clears; two dead trading days flag).
  Pins: `tests/test_ignition_asx.py`, `test/ignition.test.js`.
- **MARKET CAP + THE READABLE PANEL (2026-09-30, owner: "VERY HARD on the
  eyes to read ... I need a MARKET cap on each box" and "keep the code clean /
  simple / easy to change").** Caps are DISPLAY only, stamped after the sort
  by `scanner/ignition/mcap.py` (one small module, two functions): every row
  carries `mcap` (market's own currency) / `mcap_asof` / `mcap_src`, never 0.
  Crypto = CoinGecko's cap on the universe row (`cg_mcap`, undated when the
  universe is a `cg_stale` snapshot). ASX = newest of the SHARED cap cache
  (`marketcaps.load_cache()`, READ only — scan.yml's refresh stays its one
  writer) and this lens's previous file, plus ONE Yahoo `marketcaps.fetch_caps`
  call BEFORE the frame download (Yahoo throttles after it) for previous-file
  names whose cap is missing or older than `marketcaps.MAX_AGE_DAYS`; a cap
  failure never fails the run. `scanner.marketcaps` is on the fence
  allowlist. The panel (design chosen by a judged 3-way comparison, then cut
  down for simplicity): trigger cards lead with one big outcome number
  (exit R / R now / "no trade"), a "cap A$198M" chip and 2-3 plain sentences;
  COILED is a table on desktop / two-line rows under 1000px, sorted largest
  cap first (no-cap rows after, engine order) — nothing dropped, no sort
  buttons, no row expansion (phones lose the quiet diagnostics; desktop has
  them in the row tooltip). tabular-nums only inside `.ig-tbl` (it detached
  minus signs in prose). Pins: `tests/test_ignition_mcap.py`,
  `test/ignition.test.js`.
- **MINI CHARTS (2026-10-08, owner: "build both") — DISPLAY ONLY.** Every
  trigger card and COILED row draws a candlestick thumbnail (inline SVG,
  built in the browser by `ignition.js`) from a SIDECAR,
  `public/data/ignition/<market>_charts.json` (`run.charts_path`), written
  by the screen run only — `--backtest` and `--dry-run` never write it, exit
  3 writes neither file. `run.main()` keeps ONE `output.write_json` call
  node: the screen file first, then the sidecar COMPACT (`indent=None`,
  `separators=(",", ":")`, trailing "\n"). `screen_market(...,
  charts_out=dict)` fills it after the payload is built, from the SAME
  post-merge completed frames + forming bars the rows were screened on; the
  screen payload is byte-identical with or without it, and `<market>.json`,
  `<market>_backtest.json`, `engine.py`, `backtest.py` and
  `IGNITION_RULESET_VERSION` did not move. **THE JOIN:** the sidecar's
  `generated_at` is the screen's exact stamp, and the page draws only when
  the two match. Otherwise dashed placeholders, and `ignition.js` `chase()`
  re-reads whichever file is BEHIND without waiting for the deck: a sidecar
  OLDER than the screen is re-read past `CHART_RETRY_MS` (30 s); one NEWER
  than it re-reads the SCREEN at once (30 s floor) through the deck's own
  re-render callback, so the pill and the panel heading move together; ONE
  timer (`CHART_RETRY_MS` + 1 s) re-runs sync() while they still disagree
  and the panel stays open on that market (2026-10-08 review: both
  directions used to wait up to the deck's 5-minute live TTL). Contract,
  top level in order: `schema_version` 1, `lens`, `market`, `generated_at`,
  `bars` (= `IGNITION_CHART_BARS`), `smas` (= `IGNITION_CHART_SMAS`), `rows`
  keyed by the screen row's `yf`, `missing` (sorted `yf`s whose chart could
  not be built — never costs the screen), then `chart_errors` /
  `chart_error_sample` (run.py's `scanerrors.ErrorLog("ignition charts
  [<market>]")`, fed by `thumbs.build(..., on_error=)`: the WHY behind
  `missing`, also printed as its own summary line with the `!!` loud marker;
  no `::warning::` — scanerrors is not an alert channel; never in the
  screen payload). A row: `end` (== the row's
  `last_bar`), `f` (1 = the arrays end with the forming bar), `o h l c`
  (5 significant figures, null only if non-finite), `v` (int 0..100 of the
  window's loudest bar), `ma` (one array per `smas` entry: the SMA on the
  WHOLE frame, sliced; null in warm-up), and optional `b` [i0, i1]
  (inclusive: the 60 bars the row's `base` was measured on — COILED: the 60
  before the last completed bar; a trigger: the 60 before `t`; omitted if it
  starts before the window), `t` (the trigger bar; a provisional row's is
  the forming bar) and `x` (the exit bar; gap_below_stop = `t`+1). Every
  index is computed server-side from the window's own dates; the browser
  derives no engine geometry and reads `base`/`breakout_level`/`stop` off the
  matching screen row. `scanner/ignition/thumbs.py` is ENGINE-GATED (not in
  the fences' `_NOT_ENGINE`: offline, clockless, `IGNITION_*` reads only).
  Four display constants, no ruleset bump: `IGNITION_CHART_BARS` 120 (bars
  on every market, never `engine.bars()` — ~6 months ASX, ~4 crypto),
  `IGNITION_CHART_SMAS` (= `IGNITION_RIBBON_SMAS`, one line to change),
  `IGNITION_CHART_SIG_FIGS` 5, `IGNITION_CHART_VOL_SCALE` 100. Drawn sizes
  (ignition.css): 160px tall on a card; a COILED row 240x72 on desktop,
  380x104 from 1400px (the Name column's spare width; below 1400 a wider
  chart ellipsizes names), full width x 96 in the phone fold. Every Ignition
  workflow (crypto, ASX, NASDAQ) adds the sidecar to `PATHS` beside the screen file (`SCAN_PUBLISHED`), so it
  gets its own `git add`, presence check and `assert_staged` (the fresh stamp
  is why a real publish always stages it). **A failed sidecar write fails the
  run** (main() raises → exit 1 → the red arm; nothing is committed, the
  previous pair stays live). `tests/test_publish_integrity.py` round-trips
  both committed sidecars (they skip until the first post-merge run writes
  them; a new market's sidecar row lands with its port). Pins:
  `tests/test_ignition_thumbs.py`, the fences / workflow / mcap / frontend
  suites, `test/ignition.test.js`.
- **THE NASDAQ PORT (2026-10-08, owner: "build both").** The third market,
  ported by the ASX recipe; same rule, same thresholds, ruleset 1.0.0
  unchanged, crypto and ASX outputs untouched (their caveat strings are
  byte-identical). Pre-registered before the first NASDAQ replay: (1) 252
  bars a year (NYSE/NASDAQ trade ~252 days), so every calendar window
  equals the ASX's (504/252/756/252/276/124/126); chart windows stay in
  bars. (2) Floors US$1,000,000 base / US$3,000,000 trigger day (Close ×
  Volume): the base is `MARKETS["nasdaq"].liquidity_min`, the VIVEK NASDAQ
  scan's own floor, and the trigger asks 3× it, as the ASX's do — equal to
  crypto's numbers by coincidence. (3) Replay cost 0.5% round trip (a flat
  fee each way is ~0.05–0.2% of a ~US$2,500 ticket, plus the spread: a 1c
  tick is 0.1–0.5% of the $2–10 prices beaten-down names trade at; between
  crypto's 0.30 and the ASX's 1.0; the doubled 1.0% stress is published
  anyway). (4) Data-age ceiling 5 days (a holiday next to a weekend peaks at
  4; 5 clears a two-day closure like Sandy 2012). (5) Regime line = the
  NASDAQ Composite (`^IXIC`, every NASDAQ-listed common stock, history to
  1971; `^NDX` is 100 mega-caps, where coils do not live). (6) NO design
  case — no chart informed the port, so every trigger is scored (the caveat
  says so in words). (7) Forward bucket from 2026-10-08. (8) The replay's
  never-liquid prefilter applies (every non-crypto market). **THE UNIVERSE
  IS NASDAQ GLOBAL SELECT (~1,430 names, `universe._fetch_nasdaq_listed`,
  the VIVEK scan's list); the Global Market / Capital Market tiers, where
  most small-cap bases live, are left out — widening is the owner's call**
  (a lens-only tiers pass-through in `run._download`, ~2× the runtime). The
  replay's SURVIVORSHIP caveat says so (`backtest.UNIVERSE_WHY`: "today's
  NASDAQ Global Select (in good standing) listings", missing names that were
  "moved down a tier or put on a deficiency notice" too); the ASX caveat is
  byte-identical (pinned).
  **COMPLETENESS IS GATED:** a market missing from any per-market dict
  silently ran on crypto's value (QNT as a design case, 0.30 cost, a 3-day
  age, a $1M trigger, a BTC regime in the replay) with nothing erroring, so
  `test_every_market_has_an_explicit_entry_in_every_per_market_setting`
  (fences) fails on a missing key. **ONE BACKSTOP GATE FOR BOTH STOCK
  MARKETS:** `scripts/ignition_due.py <market> "<generated_at>" [--now ISO]`
  (stdlib only, fails open, unknown market = run) replaced
  `ignition_asx_due.py`; it reads `config.IGNITION_BAR_FINAL` = {asx: the
  digest's 16:40 Sydney (derived from `MORNING_PLAYS_SLOT_GATE`), nasdaq:
  16:30 New York (`MARKETS` tz + `ALERT_RETURNS_BAR_FINAL`)}, defined after
  `MORNING_PLAYS_SLOT_GATE` because it derives from it. Caps work as on the
  ASX (bare Yahoo symbols, `nasdaq:` cache keys); first-run cap coverage is
  low (only VIVEK A+/A names are cached) and fills on the second run. The
  deck pill shows on the NASDAQ deck (session-market staleness, weekday
  hours); the STALE badge names each market's own workflow ("Ignition scan
  (NASDAQ)"). **THE 16:00–16:30 GAP (2026-10-08 review):** on time the NASDAQ
  crons never land between the bell and the bar-final, but GitHub runs crons
  hours late, and a dispatch or a kick can land anywhere. So (1)
  `run.bar_is_forming` calls a NASDAQ bar FORMING until its
  `IGNITION_BAR_FINAL` (16:30 New York), not the 16:00 bell — scoped by
  `config.IGNITION_FORMING_UNTIL_BAR_FINAL = ("nasdaq",)`; a run in the gap
  publishes today's break as provisional, never confirmed; (2)
  ignition_nasdaq.yml's gate skips an INTRADAY cron that lands at/after 15:30
  New York (read before the download, run.py's clock after it; it also stops
  a run that straddles 16:30 from stamping past it and making
  `ignition_due.py` skip both backstops). Still open on the ASX:
  `bar_is_forming` completes its bar at the 16:00 session close, not its
  16:40 bar-final (the `54 4` intraday cron is 15:54 Sydney under AEDT, so a
  slow download could cross 16:00) — a separate change, since it moves
  pinned ASX tests and the AEST 06:24 UTC primary. Pins:
  `tests/test_ignition_nasdaq.py`, the TWINS pins in
  `tests/test_ignition_asx.py`, `test/ignition.test.js`.
- **What the replay says (exchange data + peg rule, run of 2026-09-28
  03:09 UTC — report-only, READ AS SUGGESTIVE):** 94 realised trades,
  expectancy **+1.19R**, median **−0.76R**, PF 3.08, 34% winners; versus
  random timing on the same coins **+1.15R, 90% CI −0.06..+2.59, P(no edge)
  0.062** — borderline. **The top 5 trades are 108% of the total R (ex-top-5
  −0.10R)**: a fat-tail system whose whole average is a handful of monster
  runs. Pre-2024 (n=44) +0.03R; 2024+ (n=50) +2.21R. BTC above its 200-SMA
  n=82 +1.37R, below n=12 −0.02R (context, not a filter). hold-20 exit
  +1.65R vs the 9-SMA trail's +1.19R; the ladder exit +0.21R (it cuts the
  runners). All 243 grid cells positive (median +1.39R) — overlapping cells,
  a robustness read only.
- **What would have to be true to trade it:** the FORWARD bucket beating
  random timing on its own, not the historical replay alone — and then it is
  the owner's call, like every trade change.

## HIGH CONVICTION — the four-cell rule (2026-09-20)

Owner ruling off the 600-name-per-market long-only replay (8,239 trades):
**HIGH CONVICTION = grade A/A+ with an ARMED plan in any of 1W reclaim
(+0.299R n=691), 1W break (+0.161R n=122), 3D reclaim (+0.196R n=1309) or
1D break (+0.091R n=281)** — together n=2403, +0.212R, PF 1.47. The old rule
(a 1W reclaim that is A/A+ OR has >= 2 structural targets) was one cell plus
a structure branch that measured −0.067R and was dropped ("Drop it"). A
name fires on up to three cells and wears **one 🎯 per cell** ("if it fires
on all 3 have 3"). ONE definition: `scanner/conviction.py` (`HC_CELLS`,
`conviction_cells/count`, `is_high_conviction`, `trade_cell` for backtest
trades); `morning_plays.py` (digest widened to match, `SYM 🎯🎯` lines, most
cells first), `edge_rosters.py` and `vivek_backtest.py` IMPORT it;
`app.js convictionCells`/`hiconvBadge` and `chart.js convictionCells` carry
the same table as a JSON literal that `tests/test_conviction.py` parses out
of the shipped files and compares to `HC_CELLS`. The backtest report now
records `conviction_rule` + `by_conviction_cell_long`; `system-backtest.js`
labels a pre-2026-09-20 report as the OLD rule instead of dressing it in the
new text. Nothing under `scanner/broker/` IMPORTS it
(test-pinned fence) — the bot carries its own copy of the table, see next.

### THE BOT TRADES THE FOUR CELLS (2026-09-21, owner-confirmed; shorts declined)

Owner: *"The paper bot should only take the highest R and conviction plays so
I feel like it needs to take what we're changing the high conviction list
[to] … lets open it to take shorts too."* Shorts were put in front of him
with the numbers (every short cell negative on every market; the four cells
short n=793 −0.360R PF 0.43) and he ruled *"Yeah lets not do shorts."*
Shipped: `VIVEK_BOT_GRADES = ("A+", "A")` replaces the A+-only gate
(`VIVEK_BOT_MIN_GRADE` retired; skip code `not_a_plus` → `grade_excluded`);
`VIVEK_BOT_ENTRY_CELLS` (the deck's table, walked 1W → 3D → 1D, first armed
complete plan whose trigger sits in its cell) replaces `VIVEK_BOT_PREFER_TF`
+ `VIVEK_BOT_SKIP_ENTRY_TYPES` (skip code `weak_entry_type`/`no_armed_plan` →
`no_cell_plan`); a 1W retest no longer blocks a row whose 3D reclaim is
armed. Evidence: bot rule before = +0.094R n=2718 PF 1.18; four cells at
A/A+ = +0.212R n=2403 PF 1.47 (A+ only +0.216R n=1423). UNCHANGED: long-only,
the weekly/3d LEVEL gate (`VIVEK_BOT_LEVEL_TF_ALLOW`, the thrice-replicated
w3 cohort — so a 1D-break plan is only taken on a row reacting at a weekly/3d
level), every size / R:R / liquidity / sector / loss guard (size, slots and the
sector cap moved later, 2026-09-27 — see SIZING 2). **Cycle w3-1
ENDED** with this change: rows it opened keep their `cycle: "w3-1"` tag (the
journal's w3-1 evidence strip still reads them); new rows carry
`VIVEK_BOT_CYCLE_TAG = "hc4-1"` (status.js `CYCLE_TAG` follows).
`bot_rules.json` now publishes `grades` + `entry_cells` + `cycle_tag` and no
longer the retired trio; `system.html`'s rulebook and `vivek_parity` /
`vivek_backtest.portfolio_sim` mirror the cells. Pins:
`tests/test_bot_alignment.py` (bot table == `conviction.HC_CELLS`, shorts
off, level gate standing, retired names gone, every deck-HC row is
bot-takeable and every non-cell is not).

### BOT HONESTY — the stop cap at the fill, the grade as taken (2026-09-24, owner: "change the rule")

`reviews/2026-09-24-bot-vs-cells.md` checked the live gate against the four-cell
sleeve PR #42 measured and found two gaps; both are closed. (1) **The 25% stop cap
is re-read at the FILL** (`vivek_run._ticket_to_position`, logged
`[wide_stop_at_fill]`): `evaluate_setup` tests `VIVEK_BOT_MAX_STOP_PCT` off the
plan entry (the signal close), and a live fill that moved away from it had booked
CVLT 26.6% / SMCI 26.3% / BNB 25.04%. Same cap, same `>`. ENTRY ONLY — those three
stay open and are managed as before; do not "fix" that by closing them. (2)
**`plan_trade` records `decision["grade"]`** (grade_raw, A or A+) instead of a
hard-coded `"A+"`, which had booked every A take since 2026-09-21 as A+ (7 open rows
at the time). A label: no takeability moves. Not added, owner's call: a
same-issuer cap (FWONA + FWONK are one company). Pins: `tests/test_bot_honesty.py`
and the note's predicate block (`tests/test_bot_vs_cells.py`).

## MY JOURNAL — THE "ME" SIDE REMOVED ENTIRELY (2026-09-21)

Owner: *"I want to get rid of the entire 'MY JOURNAL' page ... I no longer am
wasting time taking trades on this scanner, if anything I'll take REAL trades
on my REAL brokerage account ... rip the guts out of the entire journal MY
section. Only keep the Claude paper journal going moving forward."* Scope
confirmed in the same turn: **keep journal.html, delete the Me side**, and
*"Bin the stars too."*

**THE PAGE STAYS AND IS NOW SINGLE-BOOK.** `public/journal.html` renders only
Claude's paper book — stats, equity curve, open/closed tables, the week review,
R distribution, exit quality, the stalled strip, the w3-1 exit-evidence strip,
the tide line, and ONE close-all button. `public/js/journal.js` went 2,704 →
~1,910 lines: gone are `ensureInit`/`finalizeR`/`ensureClosedR` (the manual
sizing + R resolver), `mjLoad`/`mjSave`/`mjSaveLocal`/`mjGen`, `splitMe`,
`loadMe`, `renderBoth`, `renderComparison`, the close modal and its preview
memo, `closeAllMine`, `refreshLive`, the backup/restore controls and the
save-error banner. `state` is `{ bot: {...} }`.

**WHAT ELSE WENT, AND WHY IT WAS NOT OPTIONAL** — each of these existed only to
serve the manual journal, so leaving it would have left a live write path to a
store nothing reads:
  * `public/js/gbs-sync.js` + `functions/api/journal.js` — the localStorage
    journal and its Cloudflare KV sync (`?code=`). The unified watchlist lived
    INSIDE that store, which is why the stars could not outlive it.
  * `functions/api/_vivek_manage.js` — the manual-position management endpoint.
  * `functions/api/tick.js` + `.github/workflows/stop_watcher.yml` — **the cloud
    stop/target watcher watched the KV MANUAL journal, nothing else.** The bot
    book's stops are evaluated by the scan itself and by kill_switch.yml, so the
    paper track record loses NOTHING here; what is gone is a */5 cron, its
    4-tick loop, the kill_switch/crypto_bot piggyback ticks, `TICK_SECRET`'s only
    reader, `watchdog.probe_endpoints()` and the `tick_unreachable` finding. The
    long 503/401/000 taxonomy is in `docs/claude-history.md` — do not
    re-derive it for a new endpoint without re-reading why 000 was made green.
  * The stars: `public/mynames.html`, `public/js/mynames.js`, the ★ nav tab, and
    app.js's `WATCH_KEY`/`isStarred`/`toggleStar`/`lensStars`/`isWatchedAny`/
    `notifyWatchArms`/`syncWatchToggle`/`state.view`/`.t-star` — plus
    `confluence_alert`'s WATCHLIST BYPASS, which read the synced journal via
    `GBS_SYNC_CODE` so starred names could ping below the lens threshold. The
    SIGNED state it shares with the threshold gate is untouched and still
    load-bearing (see that module's docstring).
  * `_access_log.js`'s `coalesceOk` branch — it existed for /api/journal's
    60-second GET poll. `JOURNAL_KV` now backs ONLY the scan/close/morning-plays
    rate limits and the access log; the name is historical.
  * Tests: `test/unit.test.js` and `test/vivek_manage.test.js` deleted;
    `close_all`, `journal_money`, `journal_stale`, `leaks`, `statekeep`,
    `staleview`, `api_guards`, `access_log`, `test_confluence_state`,
    `test_watchdog`, `test_workflow_hardening` pruned to what still ships.
    Several pins were kept but INVERTED — e.g. journal_stale now asserts
    `refreshLive` and `priceFor` stay gone, because a live per-symbol quote must
    pass age 0 rather than `ageOf()`, and that lesson outlives the code.

**`GBS_SYNC_CODE` is orphaned** (nothing reads it) and can be deleted from
GitHub whenever convenient, same as `DISCORD_WEBHOOK_URL` and `TICK_SECRET`.
**What deliberately STAYS**: `/api/close` (the close-all button and the stalled
strip both post to it), `close_position.yml` including its legacy swing/scalp
path, `scanner/journal.py` / `scalp_journal.py`, and every bot-book surface. The
manual side's journal-arithmetic write-ups (Tier 2 #25/#26/#27/#34) are in
`docs/claude-history.md`.

## AI BOT — REMOVED ENTIRELY (2026-09-17)

Owner: *"I want to rip that off the site and all the history it carries. It
means nothing to me and I don't use it. Rip the guts out of it too."* The
`bot.html` page was the SCALP-ERA execution-bot console (status feed frozen at
25 June 2026, futures/CFD markets, the browser risk engine) and none of it
touched the paper book that is the real track record. Gone: `public/bot.html`
+ `js/bot.js` + `css/bot.css` + `js/risk_manager.js` + `data/bot_status.json`;
the nav's AI BOT entry and its pulsing dot (`nav.js`, `styles.css`); and the
guts — `scanner/broker/bybit_run.py` + `bybit_bracket.py` + `bybit_reconcile.py`
(the Bybit execution path), the scalp risk stack (`risk_manager.py`,
`circuit_breaker.py`, `pre_trade_check.py`, `scaling_advisor.py`,
`performance_report.py`) and its analytics (`alert_digest`, `anomaly`,
`attribution`, `expectancy`, `fill_analysis`, `live_vs_backtest`,
`event_calendar`, `journal_utils`), `scripts/health_check.py`, and their tests
(`test_circuit_breaker/pre_trade_check/risk_manager/sizing.py`, the
bracket/reconcile half of `test_order_path.py` — its three kill-switch tests
moved to `tests/test_kill_switch_flatten.py` — the expectancy/health_check
halves of `test_phase7.py`, `test/risk_manager.test.js`,
`test/risk_defaults.test.js`, and the #85/#87 suites of `statekeep.test.js`).
**What deliberately STAYS**: `kill_switch.py` + `kill_switch.yml` (the live
loss guard on the paper book — `trade_pnl` moved into it from risk_manager,
identical arithmetic), `bybit_client.py`/`alpaca_client.py` (its flatten path;
cutting that is a kill-switch decision, not a page removal), `bot_rules.json`
(status.js + journal.js read it), the legacy `journal.py`/`scalp_journal.py`
(close_position.yml's swing/scalp path + `_session_day`), and every `SCALP_*`
/ `BYBIT_*` config constant (inert without readers; not worth a config diff).
Their Tier 1/2/5 write-ups (risk_manager, reconcile, bot.js, risk_manager.js)
are in `docs/claude-history.md`.

## TURTLE — REMOVED ENTIRELY (2026-09-17)

Owner: *"rip OUT the entire TURTLE section/tab and all data associated with
TURTLE from the scanner page. It's redundant to me. I don't use it and never
have."* The fourth lens existed 2026-08-21 → 2026-09-17 and is gone from the
tree: `scanner/turtle.py` + `turtle_run.py` + `turtle_book.py` +
`turtle_portfolio.py`, `turtle.yml`, `public/turtle.html` + `js/turtle.js` +
`css/turtle.css`, the published `public/data/*_turtle.json` /
`turtle_book.json` / `turtle_portfolio.json`, the five `journal/turtle_book*.json`
books, every `TURTLE_*` constant in `config.py` (incl. the dormant futures/CFD
block), the `WATCHDOG_RUNS["turtle.yml"]` entry, the nav tab (`nav.js`), the
chart back-link (`chart.js`), the smoke-test 320px entry, the test.yml step,
`tests/test_turtle*.py` + `test/turtle.test.js`, the ledger/handoff/review
markdowns. The lens was outside every signal path by construction (its fences
were test-pinned), so nothing in `broker/`, the bot book or the confluence
machinery changed. **Do not re-add it.** If the owner ever wants a breakout
system again it starts from `git log -- scanner/turtle.py` at the removal
commit, not from memory — the engine's three audit-found bugs, the ½N stop
5%-risk arithmetic and the System-1 filter are all recorded there.

## Batch-100 (2026-08-20) — the edge-measurement layer, and where its fences are

100 items chasing profitability/transparency/edge, ALL measurement and
display — the w3-1 freeze (live until the first mechanical exits, week of
Sep 4 2026) forbids touching signals, sizing, grading, eligibility or any
`cycle: w3-1` row, so anything trade-affecting stopped at a proposal.
Ledger with per-item statuses: `BATCH100_2026-08-20.md` (83 shipped, 16
proposal-only, 1 verified-no-change). Evidence base: `EDGE_RESEARCH_2026-08-20.md`.
The facts a later session must not re-derive:

1. **The daily edge pipeline lives in alert_returns.yml** (see its table row
   for the five scripts and the sentinel/staging discipline). The design rule
   that holds it together: `edge_rosters.py` and `edge_summary.py` IMPORT
   `alert_returns.py` / `alert_edge_report.py` machinery via importlib —
   re-typing a stat or a stamp is mirror-drift, and tests pin the imports.
   `alert_edge_report.py` stays READ-ONLY (pinned); the committed summary
   artefact exists precisely so the report never needs a write path.
2. **PROPOSALS_2026-09-04.md is the freeze-blocked half** — P1..P15 for the
   Sep 4 checkpoint (tint repoint, the 1D entry-quality decision, short-side
   display honesty, High-conviction demotion, FX sizing boundary, risk_manager
   arming matrix, time-stop DEFENSE, checkpoints Sep 9/Sep 23, full-universe
   backtest calibration, breadth throttle). None deployed; each cites its
   numbers. If a future session is asked to "just do" one of these, the
   evidence and the recommended shape are already written — start there, and
   note P11/P12 exist to PREVENT changes, not make them.
3. **Ledger enrichment writes into BLANK fields only and freezes them**
   (sector / grade_raw / score / is_product / breadth at ingest-day values,
   same-day joins only — no look-ahead). `data/sector_map.json` is still a
   signal path; the ledger copies FROM it and never writes it.
4. **The backtest's new evidence blocks are ADDITIVE** (`by_entry_type_long`,
   `by_direction_entry_type`, `by_timeframe_long`, `mfe_zero_rate`) — schema
   pins assert no existing key moved, and `loadEntryQuality()` still reads
   the longonly file untouched (the repoint is proposal P1, owner's call).
5. **New surfaces are deliberately INERT**: the journal tide line
   (book_stress.json), the deck's held-grade `°` ring (grade vs grade_raw —
   the bot buys grade_raw), the regime stretch/percentile/highs−lows line,
   the status sheet's trigger-mix row (from funnel_history's `trigger`
   column; null until a market's block carries the column — never invent
   "all cron"). No controls, no calls-to-action, engine fences test-pinned.

1. **Git first, always:** other sessions + CI push constantly. Before ANY
   commit: `git stash -q -u; git pull -q --rebase origin main; git stash pop -q`.
   A full pytest run leaves `journal/` byte-clean, so a diff in
   `journal/alert_state.json` after tests is a real alert-state change —
   never discard it with `git checkout`.
2. **Version bump:** every edit to ANY `public/js/*.js` or `public/css/*.css`
   bumps its `?v=` in every referencing HTML page. Don't record the numbers
   in docs — read them from the HTML.
3. **Config first:** any new threshold/constant goes in `scanner/config.py`
   (or `phasemap/config.py`) before use. Bot rule constants are published to
   `public/data/bot_rules.json` each scan — the dashboard reads them; never
   hardcode the numbers twice (status.js + journal.js read it).
4. **PhaseMap spec is law** (see above). Schema note: published
   `latest.json` is SLIM (narrations in `narrations.json` sidecar); the
   dated snapshot keeps the full spec schema.
5. **Tests gate everything:** `python -m pytest -q` (+ `node test/*.test.js`)
   must be green; CI runs them on every push.
6. **Pinned deps:** `requirements.txt` pins the trade-path packages exactly.
   Bump deliberately (edit pin → pytest → push), never loosen to `>=`.
7. **Atomic writes** for any journal/state JSON (temp + `os.replace`).
8. **The owner says what to do; Claude ships it (owner, 2026-09-28).** Work on
   a branch, open a PR, and once the checks are green merge it with **Rebase
   and merge** — never squash, never a merge commit (the owner's `SHIP.bat`
   convention). No need to ask before merging. Production deploys only from
   `main`; other branches get a Cloudflare preview URL, never the live site.
9. **ASCII-only prints** in scanner code — Windows consoles are cp1252 and
   choke on arrows/em-dashes.
10. **CF Functions** are Workers runtime: no Node builtins; KV binding
    `JOURNAL_KV` backs the scan/close/morning-plays rate limits and the access
    log (the name is historical).

## Frontend rules

- iOS-style dark theme: tokens in `styles.css :root` (system-blue/green/red,
  radius 18/14/10, soft shadows, frosted top bar). Old terminal values are
  documented in the :root comment for revert.
- One timestamp convention: **Melbourne on screen**, market-local/UTC in
  tooltips (`PM.fmtMelb`). A zone LABEL is the abbreviation AT THE INSTANT
  (2026-10-05): scan.py/sectors.py publish `now.tzname()` (AEDT/AEST, EDT/EST,
  UTC — the hardcoded "AEST" had mislabelled every summer time; `MarketConfig
  .tz_label` is gone), and app.js `fmtTime` / sectors.js derive it from the
  IANA zone via Intl, treating an old payload's `AEST`/`ET` only as a zone key.
- Chart DAILY-and-above stock bars are re-stamped to their EXCHANGE date at
  00:00Z as they enter chart.js (`yahooBars` → `toExchangeDates`; intraday and
  crypto untouched). Yahoo stamps an ASX daily bar at its 10:00 open, which
  under AEDT is 23:00Z the PREVIOUS day, so markers landed a session late,
  Mondays wore the weekend tint, 3D candles stopped matching the engine's
  buckets and the axis read a day early (2026-10-05). Daily labels (replay,
  ruler, forecast, DIV-ADJ) format in UTC so they agree with the axis.
- Preview: launch config "scanner" (port 8765, `.claude/launch.json`). `preview_screenshot`
  TIMES OUT on canvas-heavy pages (chart) — verify via `preview_eval` DOM
  checks instead.
- PWA: `sw.js` (network-first for `data/` + HTML, cache-first for `?v=`
  assets; never caches `/api/`). Bump its `CACHE` name on breaking changes.

---

## Secrets

Set: `DISCORD_WEBHOOK_URL` (ORPHANED 2026-08-27 — the channel was removed;
nothing reads it, safe for the owner to delete from GitHub + Cloudflare),
`TICK_SECRET` + `GBS_SYNC_CODE` (ORPHANED 2026-09-21 — /api/tick,
stop_watcher.yml and the KV journal went with the manual journal; nothing reads
either, safe to delete from GitHub + Cloudflare),
`BYBIT_*` (testnet), `ALPACA_*` (legacy),
`TELEGRAM_*`, `GH_DISPATCH_TOKEN` (in Cloudflare, not GitHub),
`DISCORD_MORNING_WEBHOOK_URL` (the morning high-conviction digest's own
webhook, distinct from the removed alert webhook — see MORNING PLAYS).
**STANDING ACCESS (ops.yml, 2026-09-10 — ALL THREE SET the same day; `cronjob-list` and `cf-list-vars` both answered HTTP 200 from ops.yml runs #1 and #2):** `CRONJOB_API_KEY`,
`CLOUDFLARE_API_TOKEN` (custom token, Account → Cloudflare Pages → Edit),
`CLOUDFLARE_ACCOUNT_ID` — GitHub Actions secrets read ONLY by ops.yml; set
them once and Claude can create/edit cron-job.org jobs and Cloudflare Pages
env vars itself via `workflow_dispatch` (see the ops.yml row).
**Pending owner:** `MORNING_PLAYS_TRIGGER_SECRET` (arms `/api/morning_plays`,
the on-time external trigger for the plays digest — see MORNING PLAYS),
data-provider key, Cloudflare Access.

---

## Running locally

```bash
pip install -r requirements.txt
python -m pytest -q                      # full gate (counts drift; read the run)
node test/status.test.js                 # one of the JS suites; test.yml lists every one
python -m scanner.run --market asx       # VIVEK scan
python -m phasemap.run --market asx      # PhaseMap scan
python -m scanner.spec_run --market asx  # Specs scan
python -m scanner.vivek_backtest --market asx --limit 10 --period 3y
python serve.py                          # local frontend
```
Local venv: `.venv/Scripts/python.exe` (3.14; CI is 3.12).

**Repo home (2026-07-21): `C:\\dev\\googy-boys-scanner`** — moved OFF OneDrive
after a sync rollback corrupted the working tree + git index mid-session.
Never keep this repo inside a OneDrive/Dropbox-synced path. (The old copy at
Documents is RETIRED; the local `.venv` must be recreated in the new home
when needed: `pip install -r requirements.txt`.)
