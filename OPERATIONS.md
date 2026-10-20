# Vivek 5.0 — Operations Runbook

Last updated: 2026-10-14 (REFINE200 #88/#100: every workflow, the cron-job.org
clock, "Who triggers what", and the kill switch / watchdog / alert sections as
they work now). `CLAUDE.md` holds the rules; this file is how to run it and
what to do when something breaks.

---

## Quick reference

| What | Command |
|------|---------|
| Run a VIVEK scan | `python -m scanner.run --market asx` (or nasdaq / crypto; `--limit 40` for a quick slice) |
| Check the kill switch (loss check, flattens only on a breach) | `python -m scanner.broker.kill_switch --dry-run` |
| Audit bot-book integrity (read-only) | `python -m scanner.broker.vivek_run --verify` |
| Rebuild the derived combined book | `python -m scanner.broker.vivek_run --rebuild-combined` |
| Is every open row at the configured notional? (read-only) | `python scripts/resize_book_notional.py --check` — exit 0 yes / 3 rows to restate / 4 an off-target row it cannot restate (Runbook 7) |
| Freshness watchdog (read-only preview) | `python -m scanner.watchdog --dry-run` |
| Decision-pack checkpoints (read-only) | `python scripts/decision_pack.py` |
| Run all tests | `pip install -r requirements-dev.txt && python -m pytest -n 4 --dist loadfile`, then every `node test/*.test.js` |
| Serve the site locally | `python serve.py` (http://localhost:8765) |

---

## How the system runs day-to-day

Two clocks drive everything. **cron-job.org** (free, keeps real time) pings the
site's `/api/heartbeat` and `/api/morning_plays`, which dispatch GitHub Actions
workflows; **GitHub's own crons** are the backups (GitHub runs them late or not
at all: in the week to 5 Oct it ran 5/35 ASX, 8/35 NASDAQ and 41/~168 crypto
scans). Cloudflare Pages serves `public/` on every push to `main`.

### The cron-job.org jobs

Managed from a session with `ops.yml` (`cronjob-list` / `cronjob-get` /
`cronjob-history` / `cronjob-update` …; confirm every change with a read-back).
Each job runs in its market's own timezone, so DST never moves it.

| Job id | Name / schedule | Calls | Effect |
|---|---|---|---|
| 8587588 | ASX hourly, :10 11:10–16:10 Sydney, weekdays | `/api/heartbeat?market=asx&stale_min=…` | heals an overdue ASX scan |
| 8587590 | `scan ASX close (Sydney)`, 16:40 Sydney, weekdays | `/api/heartbeat?market=asx&stale_min=15` | **the on-time ASX closing scan** (the 16:10 ping's scan lands ~16:20, so at 16:40 the ASX is stale and heals on final prices) |
| 8587683 | `scan ASX close probe (Sydney)`, 17:20 Sydney, weekdays | `/api/heartbeat?market=asx&stale_min=40` | heals only when no scan stamped at/after 16:40 has landed |
| 8587599 | crypto, :22 every hour UTC, every day | `/api/heartbeat?market=crypto&stale_min=45` | heals crypto when `crypto_bot.yml` was dropped |
| 8587591 | NASDAQ open, 10:40 New York, weekdays | `/api/heartbeat?market=nasdaq…` | the first NASDAQ scan |
| 8587598 | NASDAQ hourly, :10 11:10–16:10 New York, weekdays | `/api/heartbeat?market=nasdaq…` | heals an overdue NASDAQ scan; the 16:10 one is the post-close scan |
| 8424425 | `slot=asx (post-close ladder, UTC)`, every 30 min 06:15–10:45 UTC, Mon–Fri | `/api/morning_plays?slot=asx&key=…` | dispatches morning_plays.yml; the first rung after the ASX closing scan sends the ASX digest |
| 8424432 | `slot=us`, every 30 min 20:15–23:45 UTC, Mon–Fri | `/api/morning_plays?slot=us&key=…` | the NASDAQ + Crypto digest, the same way |

`/api/heartbeat` dispatches `scan.yml` only when that market's
`public/data/<m>_prices.json` is older than `stale_min` (floored per market:
asx/nasdaq 15, crypto 45, all 90), at most 30 heals per market per UTC day,
with a 25-minute heal window per market. `scan.yml`'s gate
(`scripts/scan_gate.py`) then scans only a market that is in its hours (or owes
its closing scan). Each completed morning_plays run also wakes `momentum.yml`.

### Workflows (all 26)

| Workflow | Trigger | What it does |
|---|---|---|
| `scan.yml` | heartbeat dispatches + GitHub superset crons (gate decides) | VIVEK scan of the market(s) in hours + their slice of the paper book + the confluence alert. ASX 11:00–16:45 Sydney, NASDAQ 10:30–16:45 New York, weekdays; never crypto on a schedule |
| `crypto_bot.yml` | `:22` hourly, every day; `:52` freshness backstop | crypto scan + crypto slice of the book; hosts the watchdog (annotates only) |
| `kill_switch.yml` | `15,45` every hour | per-market session-loss check on the book; hosts the watchdog; the `watchdog-alarm` job goes red once per CRITICAL episode |
| `close_position.yml` | manual | closes bot-book positions (`journal_type=bot`, batch up to 60) — Runbook 4 |
| `resize_book.yml` | push touching `.github/resize-kick`; manual (dry run by default) | one-shot restatement of the OPEN book at the configured notional + republished `bot_rules.json` — Runbook 7 |
| `phasemap.yml` | `30 8` UTC (usually lands midnight–4am Melbourne) | PhaseMap + Specs + schema gate |
| `confluence.yml` | when PhaseMap nightly completes; `45 8` UTC backstop | post-nightly confluence check |
| `ignition.yml` | `14 0` UTC + backstops `14 1,2` + intraday `44 5,11,17,21` + Sunday `37 3` replay; push `.github/ignition-kick` | IGNITION crypto screen + mini charts (+ replay) |
| `ignition_asx.yml` | `24 6` UTC Mon–Fri + backstops `24 7,9` + intraday `54 0,2,4` + Sunday `17 2` replay; push `.github/ignition-asx-kick` | IGNITION ASX |
| `ignition_nasdaq.yml` | `34 21` UTC Mon–Fri + backstops `34 22,23` + intraday `54 14,16,18` + Sunday `47 4` replay; push `.github/ignition-nasdaq-kick` | IGNITION NASDAQ |
| `momentum.yml` | `30 6`, `30 21` Mon–Fri, `30 0` daily, `41 */3` backstop; after every morning_plays run | MOMENTUM: screens the newest market due |
| `morning_plays.yml` | dispatched by the cron-job.org ladders; backstop crons `58 5,6`, `50 7,8` (ASX) and `50 21,22` (US), Mon–Fri | the HIGH CONVICTION digest to Discord |
| `alert_returns.yml` | `20 22` UTC + `50 23` backstop | the edge pipeline: forward returns, rosters, book stress, report, `edge_summary.json` |
| `evidence_brief.yml` | `0 21` UTC | read-only evidence brief into the run's step summary |
| `backup_book.yml` | `35 21` UTC + `35 23` backstop | nightly `backups/<stamp>/` + 90-day artifact |
| `lens_backtest.yml` | Sunday `0 8` UTC | PhaseMap/Specs/VIVEK replays → Insights (`vivek_backtest.json`) |
| `vivek_backtest.yml` | 1st of the month `0 8` UTC | long-only evidence `vivek_backtest_longonly.json` |
| `decision_replay.yml` | push touching `.github/replay-kick`; manual | READ-ONLY replay of the live rules + decision variants; artifact + step summary |
| `dispatch_scan.yml` | push touching `.github/scan-kick` | dispatches `scan.yml` (market=all) — how a cloud session triggers a scan |
| `ops.yml` | manual | cron-job.org / Cloudflare actions for a Claude session (a failed action is a green run; read the `OPS RESULT` line) |
| `test.yml` | push to main (path-filtered) / PR | the CI gate (pytest, JS suites, e2e) |
| `test_alerts.yml` | manual | alert-path self-test — sends one test message through every configured channel |
| `commit_sentinel.yml` | every push to main | flags unknown pushers / identities and force-pushes (detection only) |
| `crypto_source_check.yml` | manual; push `.github/crypto-source-kick` | read-only crypto venue check + a dry crypto scan |
| `data_depth.yml` | manual | read-only probe of how much free history each source serves |

---

## Who triggers what

For every scheduled job: what normally starts it, what catches a miss, and
what a missed run looks like from the outside. "Heal" = a cron-job.org ping
through `/api/heartbeat` that dispatches `scan.yml`.

| Job | Primary clock | Backstops | A missed run looks like |
|---|---|---|---|
| ASX intraday scans | cron-job.org **8587588** (hourly :10 Sydney) | GitHub `scan.yml` `7 0-6 * * 1-5` superset; any later heal | deck "Last scanned" for ASX over ~1h in session; status lamp amber past 90 min; watchdog `scan.yml` WARNING after ~12 session-hours |
| ASX closing scan | cron-job.org **8587590** (16:40 Sydney) | **8587683** probe (17:20 Sydney); GitHub `41 5,6` and `57 5,6`; the next heal ("missed closing scan") | the ASX scan stamped before 16:40 (pre-auction prices on the deck and the bot's ASX marks); the ASX digest waits — the ladder keeps retrying until a post-close scan exists |
| NASDAQ scans (incl. the post-close one) | cron-job.org **8587591** (10:40 NY) + **8587598** (hourly :10 NY, the 16:10 ping is the closing scan) | GitHub `37 14,15`, `7 16-21`, closing `47 20,21`; any later heal | NASDAQ "Last scanned" over ~1h in session; the US digest waits for a scan stamped after 16:05 NY |
| Crypto scan + book | GitHub `crypto_bot.yml` `:22` hourly | its own `:52` backstop; cron-job.org **8587599** (heals via `scan.yml` market=crypto when over 45 min) | crypto "Last scanned" over ~1h; `/api/health` goes 503 once the book is 4h old; watchdog `crypto_bot.yml` WARNING at 3h, crypto scan WARNING at 4h |
| Kill switch + watchdog | GitHub `kill_switch.yml` `15,45` | none (crypto_bot also runs the watchdog) | none: the watchdog does not watch `kill_switch.yml`'s own runs (dropped 2026-10-14 — GitHub runs it every 4-7h, so it alarmed on nearly every run) |
| Morning plays — ASX slot | cron-job.org **8424425** ladder (06:15–10:45 UTC) | GitHub `58 5,6`, `50 7,8` | no ASX post in the Discord channel by ~17:30 Melbourne; morning_plays runs that say "not post-close yet" (normal before the closing scan lands) |
| Morning plays — US slot | cron-job.org **8424432** ladder (20:15–23:45 UTC) | GitHub `50 21,22` | no NASDAQ + Crypto post by the Melbourne morning |
| Momentum | each completed morning_plays run (so the ladders) + GitHub `30 6`, `30 21`, `30 0` | GitHub `41 */3` | the Momentum page's stale dot (30 weekday hours stocks / 30 h crypto); no watchdog entry by decision |
| Ignition crypto | GitHub `14 0` UTC | `14 1,2` (skip once today's file is on the branch) | the ⚡ pill shows STALE (run over 26h, or the newest bar older than UTC-yesterday after 06:00 UTC) |
| Ignition ASX | GitHub `24 6` UTC Mon–Fri | `24 7,9` (`scripts/ignition_due.py asx`, also re-runs on a lagging tape) | STALE after 50 weekday hours, or more than half the names behind the last close |
| Ignition NASDAQ | GitHub `34 21` UTC Mon–Fri | `34 22,23` (`ignition_due.py nasdaq`) | as for the ASX |
| Ignition weekly replays | GitHub Sunday `37 3` / `17 2` / `47 4` UTC | a manual dispatch with `backtest` or a kick push | the forward bucket stops growing; `<m>_backtest.json` older than a week |
| PhaseMap + Specs | GitHub `phasemap.yml` `30 8` UTC | none scheduled; dispatch "PhaseMap nightly scan" by hand | PhaseMap page `run_date` a day behind; watchdog WARNING at 26h (run history) / 2 days (`latest.json`) |
| Confluence ping | `workflow_run` when PhaseMap completes | GitHub `45 8` UTC | no new nightly alignments on the ALERTS page; watchdog WARNING at 26h |
| Edge pipeline | GitHub `alert_returns.yml` `20 22` UTC | `50 23` (skips when the ledgers are already updated) | `edge_summary.json` older than a day; watchdog WARNING at 26h |
| Evidence brief | GitHub `evidence_brief.yml` `0 21` UTC | none | no brief in that day's run summary (nothing else depends on it) |
| Nightly backup | GitHub `backup_book.yml` `35 21` UTC | `35 23` (skips when the newest snapshot is at/after the 21:00Z slot) | newest `backups/<stamp>` over 26h → watchdog CRITICAL → a red "Watchdog CRITICAL" run in kill_switch.yml |
| Weekly lens backtest | GitHub `lens_backtest.yml` Sunday `0 8` UTC | none | Insights numbers a week stale; watchdog WARNING after 8 days |
| Monthly long-only backtest | GitHub `vivek_backtest.yml` 1st `0 8` UTC | none | watchdog WARNING after 32 days |

If GitHub's scheduler and cron-job.org are both down, `/api/health` (watched by
the external monitor) is the alarm: it goes 503 once the published book is 4h
old.

---

## Starting and stopping

No manual start is needed. The system is **paper only**: nothing places real
orders, and no broker keys are set.

- **Pause the paper book** (no scans, no new trades): disable `scan.yml` and
  `crypto_bot.yml` in GitHub → Actions → (workflow) → … → Disable workflow, and
  pause the six heartbeat jobs (`ops.yml cronjob-update` with `enabled: false`,
  then `cronjob-get` to confirm) so `/api/heartbeat` stops trying to dispatch a
  disabled workflow.
- **Resume:** re-enable both workflows and the jobs; the next heal catches up.
- The kill switch never liquidates the paper book; it only flattens a broker
  account that holds a market, and none are configured.

---

## Kill switch

`kill_switch.yml` (job `check`, every 30 min) reads the BOT BOOK per market and
measures each market's session the same way the runner's guard does
(`vivek_guard.session_pnl` over the market-local day), with LIVE quotes where it
can get them and the last stamped mark otherwise. It fires when a market's
session loss reaches `VIVEK_BOT_MAX_DAILY_LOSS_PCT` (3%) of
`VIVEK_BOT_ACCOUNT_EQUITY` ($150,000) = **$4,500 per market**. Unlike the
runner's guard it does not value an unpriced position at its stop, and a limit
of 0 switches it off.

When it fires:
1. It flattens only the broker that holds that market
   (`VIVEK_KILL_SWITCH_BROKERS`: ASX paper-only, NASDAQ Alpaca, crypto Bybit) —
   and only if that broker's keys are set (none are).
2. It sends a `kill_switch` CRITICAL alert through the router (no channel is
   configured, so it is logged and annotated).
3. The paper book is NOT modified; the runner's own guard halts new entries for
   that market's session.

---

## Watchdog alerts

`scanner/watchdog.py` runs inside `kill_switch.yml` (every 30 min) and
`crypto_bot.yml` (hourly). It exists because of the 2026-07-20 staging incident:
runs can finish GREEN while committing nothing, and GitHub's cron can silently
skip runs for hours. It covers both with **content probes** (timestamps inside
committed files: the book, the crypto scan, PhaseMap, backups, universes) and
**run-history probes** (`WATCHDOG_RUNS` in config: each workflow's last run in
which its working job actually ran — a gate-skipped run does not count; scan.yml
is judged on market-session hours only).

**How a finding reaches you (2026-10-14).** No alert channel is configured, so:
- every due finding is annotated on the run page — `::error::` for CRITICAL,
  `::warning::` for WARNING, `::notice::` for a recovery;
- a CRITICAL finding is handed ONCE per episode to `kill_switch.yml`'s
  **`watchdog-alarm`** job, which fails ("Watchdog CRITICAL (the kill-switch
  check itself passed)"), so GitHub's failure email carries it. The `check`
  job stays green.

Noise contract: first detection, a reminder every 6h while unresolved, one
recovery notice. If a workflow FAILED outright, GitHub's own email is the alert
and the watchdog stays quiet about it. Thresholds: `WATCHDOG_*` in config.

**What each finding means / what to do:**

- *"bot book updated_at is Nh old"* (CRITICAL) — no run has SAVED the track
  record recently. Runbook 1.
- *"book MISSING / unreadable"* (CRITICAL) — Runbook 2.
- *"<workflow>: last successful run Nh ago"* — the schedule is being skipped
  or the work is being skipped. Check "Who triggers what" for that job's
  primary clock (for scans: is cron-job.org firing? `ops.yml cronjob-history`)
  and dispatch it by hand.
- *"newest backup is Nh old"* (CRITICAL) — dispatch "Backup bot book" today,
  then investigate.
- *"PhaseMap latest.json is N days behind"* — dispatch "PhaseMap nightly scan".

**Must-change gates.** Every workflow that commits data FAILS (red run → email)
when a scheduled run stages none of its must-change outputs
(`scripts/assert_staged.sh`). A red run with "ASSERT-STAGED FAILED" means output
was produced but LOST between the scan step and git — the 2026-07-20 staging
incident pattern. Manual dispatches only warn.

**External heartbeat.** `GET /api/health` returns 200 while the published bot
book is under 4h old, 503 otherwise — served by Cloudflare, no GitHub
involvement. Point a free monitor at it:

1. uptimerobot.com (free) → Add monitor → HTTP(s) →
   `https://googy-boys-scanner.pages.dev/api/health`, every 5 min.
2. Alert after 2–3 consecutive failures (a deploy blip lasts one check).

`?max_h=N` overrides the threshold. `?market=asx|nasdaq|crypto` is a **manual
probe only** ("did THIS market scan?" — it reads `<m>_prices.json`); nothing
automated calls it.

**Prove the alert channels deliver:** Actions → "Alert-path self-test", or
locally `python -m scanner.watchdog --test-alert` with `GBS_SMTP_*` /
`TELEGRAM_*` exported. It prints, per severity, which channels delivered and
why the others did not (Telegram is muted by `config.TELEGRAM_ENABLED = False`;
SMTP is unset). Run it after any alert-secret change. Adding a channel: see
CLAUDE.md "Alerts".

**Mark-sanity guard.** A mark that moves more than `VIVEK_MARK_SANITY_PCT`
(ASX/NASDAQ 35%, crypto 60%) against the last accepted mark does NOT manage the
position: stops/TPs pause, `suspect_price_runs` counts on the row, an `anomaly`
alert fires on the 2nd consecutive hit, and the price is ACCEPTED on the 3rd, so
a real crash is delayed at most two runs. A clean split ratio is restated into
the new basis (R unchanged, recorded under `splits`) rather than read as a crash.
The kill switch drops such quotes the same way. Nothing to do if you see one.

---

## Environment variables and secrets

| Variable | Where | Purpose |
|---|---|---|
| `GH_DISPATCH_TOKEN` | Cloudflare Pages | fine-grained PAT, **this repo only**, "Actions: Read and write" — lets `/api/scan`, `/api/heartbeat` and `/api/morning_plays` dispatch workflows |
| `MORNING_PLAYS_TRIGGER_SECRET` | Cloudflare Pages | the key the cron-job.org digest ladders pass to `/api/morning_plays` |
| `DISCORD_MORNING_WEBHOOK_URL` | GitHub secret | the morning-plays digest's Discord webhook (absent = a green no-op) |
| `CRONJOB_API_KEY`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | GitHub secrets | read only by `ops.yml` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | GitHub secrets | alert channel — muted by `config.TELEGRAM_ENABLED = False` |
| `GBS_SMTP_HOST/PORT/USER/PASS`, `GBS_ALERT_TO`, `GBS_ALERT_FROM` | GitHub secrets | email alert channel — unset (an owner action, REFINE200 #78) |
| `BYBIT_API_KEY`/`SECRET`, `BYBIT_TESTNET`, `ALPACA_*` | GitHub secrets | only the kill switch's flatten path; unset in practice |

Orphaned (nothing reads them; safe to delete): the old Discord alert webhook,
`TICK_SECRET`, `GBS_SYNC_CODE`.

---

## What to do when things break (runbooks)

### Runbook 1 — Watchdog CRITICAL: "bot book updated_at is Nh old"
No run has SAVED the track record recently.
1. Actions: are `crypto_bot` / `scan` runs green but committing nothing (the
   run log's assert_staged line says why), or absent (scheduler outage)?
2. Is cron-job.org firing? `ops.yml cronjob-history` for 8587599 (crypto).
3. Dispatch "Crypto bot" manually. If it commits, the scheduler was skipping;
   it self-heals. If it stages nothing, read that run's log.
4. Never edit the book by hand to "fix" freshness.

### Runbook 2 — Book corrupt or missing
The runner ABORTS on an unreadable book (BookCorruptError) and touches nothing.
1. `python -m scanner.broker.vivek_run --verify` — read-only; lists exactly
   what is wrong (unparseable file, cross-market strays, duplicate opens, stale
   combined view).
2. Stale/missing COMBINED view only → `--rebuild-combined` (the canonical
   per-market files are the record; the combined file is derived).
3. A damaged CANONICAL file → restore it ("Backup and restore" below), then
   `--verify` again, then let the next run proceed.
4. Never hand-edit position rows; never edit a closed row.

### Runbook 3 — Daily/weekly loss guard or the kill switch fired
1. The finding names the market and the limit (`VIVEK_BOT_MAX_DAILY_LOSS_PCT`
   3% / `VIVEK_BOT_MAX_WEEKLY_LOSS_PCT` 6% of $150,000 = $4,500 / $9,000 per
   market; the week is the last 7 calendar days including today). The runner
   halts NEW entries for that market; open positions keep being managed.
2. Read the `guard` block in `journal/vivek_bot_book.<market>.json`. A guard
   that says `unmeasured` could not price part of the book (an unpriced
   position is valued at its stop) or could not read the week — fix the data,
   not the guard.
3. Do nothing to the book. The guard resets with the window. If one position
   gapped, check it for news/corporate action (mark-sanity covers splits).
4. No rule changes mid-cycle — the decision pack's checkpoints decide.

### Runbook 4 — Close one bot-book position by hand (emergencies only)
Since 2026-10-14 the owner does not close positions by hand: hc4-1 is a clean
test of the rules. For a genuine emergency: Actions → "Close position (manual)"
→ `journal_type=bot`, symbol, direction, market, exit price (the live quote),
exit date blank for today; leave `attempt` at 1. The journal page's buttons do
the same through `/api/close` (inside the collapsed "Emergency close" folds;
the exit price must sit within ±50% of the published mark; 60 closes per UTC
day). `swing`/`scalp` edit the RETIRED legacy journals — never use them.

It queues behind any running scan (the `scan` concurrency group; up to ~15
min). If a later arrival evicts it, it re-dispatches itself (up to 3 attempts;
a fresh run appears with `attempt=2`). Attempt 3 failing is loud — close it by
hand at a quieter time. A close that FAILED (red, not cancelled) is a real
error, usually no matching open position; it is never retried.

### Runbook 5 — Frontend stale or site down
1. `https://googy-boys-scanner.pages.dev/api/health` — 200 = the published book
   is under 4h old (the pipeline is fine; a display problem); 503 = Runbook 1.
2. Check the last Actions run, then the Cloudflare Pages deploy
   (`ops.yml cf-deployments`; `site-probe` shows the asset versions live).
3. Hard-reload (Ctrl+Shift+R). The service worker is network-first for data
   and HTML.

### Runbook 6 — Scan produced nothing / garbage
Yahoo outages happen. An empty scan does not touch open positions' management:
held names are refetched first, and a name with no fresh price is counted in
`unpriced_runs` (alerts at 3/10/30) instead of a silent stale mark. A market
whose download came back fully blocked publishes nothing and keeps yesterday's
file. Investigate after two consecutive empty scheduled runs: read the run
log's download errors before touching anything. A bot crash fails the run
after publishing — the log names the layer that failed.

### Runbook 7 — Open-book resize (`resize_book.yml`)
The 2026-09-27 sizing change ($5,000 × 30 → $2,500 × 60) restated the open rows
through `resize_book.yml`, fired by a push that touches `.github/resize-kick`
(`target=2500`; the script refuses unless it equals config). It is a
restatement, not a trade: entry, stop, every R field and every CLOSED row stay
frozen. The resize commit carries the three per-market books, the combined
book, its public twin AND `public/data/bot_rules.json`.

- **Before a resize merge:** confirm no "Scheduled scan", "Crypto bot" or
  "Close position" run is queued or running — a run created before the merge
  runs the OLD workflow at its trigger SHA and can replay the pre-resize book.
  Time it outside both stock sessions and away from :15–:35 (crypto at :22).
- **No CI skip token** in the merge message (`[skip ci]` and friends) — it
  suppresses the push trigger. Confirm a "Resize open book" run exists for the
  merge SHA; if not, dispatch it from main with `apply` = true.
- **Never "Re-run" a scan/crypto/close run created before the merge** — it
  reuses the old SHA and YAML. Dispatch a fresh run instead.
- **1–2 hours after:** dispatch "Resize open book" with `apply` = false. It must
  read `CHECK: 0 open row(s) off the $2,500 target`, and main's
  `bot_rules.json` must show `position_notional` 2500, `max_open_total` 60,
  `max_per_sector` 6. Rows listed → run with `apply` = true (idempotent).
- **`--check` exit codes:** 0 at target; 3 rows to restate; 4 an off-target row
  it cannot restate (named; `--apply` refuses before writing); 2 refused; 1
  crash.
- **Red "NOT applied" run:** evicted, cancelled or timed out; it pushed
  nothing and does not re-dispatch itself — use the steps above.
- **Merged by an automation token** (a GITHUB_TOKEN push triggers nothing):
  dispatch `apply` = true from main by hand.

---

## Key file locations

| File | Purpose |
|------|---------|
| `journal/vivek_bot_book.<market>.json` | CANONICAL per-market track record |
| `journal/vivek_bot_book.json` + `public/data/vivek_bot_book.json` | derived combined view (regenerable) |
| `public/data/bot_rules.json` | the bot's rules + live state (open/closed totals), published each scan and by the resize commit |
| `public/data/<m>_vivek.json` (+ `_detail`, `_prices`) | latest VIVEK scan per market |
| `public/data/phasemap/<m>/latest.json` (+ `narrations.json`, `confluence.json`) | latest PhaseMap per market |
| `public/data/<m>_spec.json` | latest Specs scan |
| `public/data/ignition/<m>.json` (+ `_charts`, `_backtest`) · `public/data/momentum/<m>.json` | the report-only lenses |
| `public/data/vivek_backtest.json` / `vivek_backtest_longonly.json` | weekly / monthly backtest evidence |
| `public/data/edge_summary.json` · `data/alert_forward_returns.json` · `data/edge_rosters/` | the edge ledgers and their summary |
| `data/sector_map.json` | sector cache — a SIGNAL path (it feeds the per-sector cap) |
| `data/research/` | parity / OOS / C3 replays, fill sensitivity, confluence study (research; not on the site) |
| `backups/<timestamp>/` | nightly snapshots (below) |
| `journal/journal.json`, `journal/scalp_journal.json` | FROZEN legacy history — never written |

---

## Backup and restore

**What runs:** `backup_book.yml`, nightly 21:35 UTC (23:35 backstop). It
snapshots the canonical books, the legacy journals, the confluence state and
alert history, the sector map and the funnel history into `backups/<timestamp>/`
(keep 30); the big ledgers (`alert_forward_returns`, `edge_rosters`,
`funnel_history`) ride only the newest 7 snapshots. `scanner/config.py` is
copied for REFERENCE (the rules in force that night) and is never restored. It
commits only that directory and uploads the whole set as a 90-day artifact (the
off-tree copy). The watchdog raises CRITICAL if the newest snapshot is over 26h
old.

**Restore (repo copy):**
```bash
python scripts/backup_journal.py list
python scripts/backup_journal.py restore <backup-dir>   # verifies, asks for "yes", data files only
python -m scanner.broker.vivek_run --rebuild-combined
python -m scanner.broker.vivek_run --verify
```

**Restore (artifact copy, if the tree itself is damaged):** Actions → "Backup
bot book" → a run → download `book-backups-*` → unzip into `backups/` → the same
commands.

**Drill (every ~3 months):** restore the latest snapshot into a scratch clone,
`--rebuild-combined` + `--verify`, confirm "book verify OK" with plausible
counts, discard the clone. A backup never restored is a hope, not a backup.
(2026-07-21: drill on `2026-07-20T22-32-20` — OK, 24 open / 4 closed.)

---

## Alert routing

All scanner alerts go through `alert_router.smart_send()` / `alert_dispatch`,
routed by `ALERT_SEVERITY`, `ALERT_CHANNELS` and `ALERT_RATE_LIMITS` in
`scanner/config.py`:

| Severity | Channels (config) | Live today | Typical events |
|---|---|---|---|
| CRITICAL | telegram + email | none (Telegram muted, SMTP unset) | `kill_switch`, `scan_error`, `vivek_guard` (a loss-guard breach), watchdog CRITICAL (also the red alarm run) |
| WARNING | telegram | none | `anomaly` (mark-sanity), watchdog staleness warnings |
| NOTICE | — | none | `trade_review`, `stale_position`, `scan_dry` |
| INFO | — | log only | `order_placed` |

Until a channel exists every routable event logs "NOBODY WAS TOLD"; the alarms
that reach you are GitHub's red-run emails (including the watchdog alarm run)
and the run-page annotations. Rate-limit state does not survive between runs
(per-run limiter); the watchdog's first/6h/recovery contract prevents storms.
The morning-plays digest is a separate daily post on its own webhook, not an
alert.

---

## Weekly review (~10 minutes)

1. JOURNAL page: open/closed counts, the hc4-1 cell board, anything with
   `suspect_price_runs` or `unpriced_runs` stuck on.
2. `/api/health` returns 200; the external monitor shows no incidents.
3. Actions: any red runs this week? Any watchdog annotations or "Watchdog
   CRITICAL" runs?
4. `backups/` has last night's snapshot; the artifact uploaded.
5. `python scripts/decision_pack.py` — has a pre-registered checkpoint reached
   its read? Read it once, on its day. No rule changes otherwise.

---

## Retired (history)

- **The Bybit live executor, circuit breakers and pre-trade checks** were
  deleted with the AI BOT page on 2026-09-17. Live execution would have to
  rebuild them; only `kill_switch.py`'s flatten path (`bybit_client.py` /
  `alpaca_client.py`) survives. The paper book's protections are the loss
  guards, the 60-open / $150,000 / one-per-symbol / 6-per-sector caps, the
  7-day re-entry cooldown, the 28-day time stop, mark-sanity and the book
  integrity gates.
- `stop_watcher.yml` and `/api/tick` went with the manual journal (2026-09-21);
  the bot book's stops are evaluated by the scans and the kill switch.

---

## Architecture in one paragraph

cron-job.org pings and GitHub Actions crons run the Python lenses and write JSON
into `public/data/`, committed to `main`; Cloudflare Pages serves `public/` as a
static site plus a few Pages Functions (`/api/*`: scan/close dispatch, the
heartbeat healer, the digest trigger, price proxies and the GitHub-independent
`/api/health`). The paper-book runner (`vivek_run.py`) fills A/A+ four-cell long
plans at observed prices into per-market canonical book files — the system's
only track record — under windowed daily/weekly loss guards, slot / notional /
sector caps, mark-sanity and hard integrity gates (corrupt book → loud abort;
post-write `--verify`; must-change staging asserts). A half-hourly kill switch
re-measures each market's session with live quotes, and the watchdog annotates
every stale or missing output and raises one red run per CRITICAL episode.
Nothing trades real money.
