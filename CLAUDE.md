# Vivek 5.0 — CLAUDE.md

This file is read automatically at the start of every Claude Code session.
Read it fully before touching any code. (Rewritten 2026-07-10 — the previous
version predated the three-lens pivot and half its claims were stale.)

---

## What this project is

A **three-lens trading scanner** + paper-trade journal + execution bot
(paper today, Bybit-gated live path built). Owner: Vivek (Melbourne,
Australia). Brand name everywhere: **Vivek 5.0** — never "Googy Boys
Scanner", never "Vivek's Beta Scanner" as the primary name ("BETA SCANNER"
as a subtitle under the wordmark is fine).

**The lenses** (see ROADMAP.md for the honest project state). Three feed the
confluence machinery; the fourth, TURTLE, is deliberately outside it:

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
4. **TURTLE** (`scanner/turtle.py` via `turtle_run.py`) — the reference lens,
   added 2026-08-21. The 1983 Dennis/Eckhardt breakout system implemented from
   the Original Turtle Trading Rules. **NOT a confluence lens and not in any
   signal path** — it has its own tab, its own nightly workflow and no reader
   anywhere else in the tree. See the TURTLE section below.

**Multi-lens confluence** is the headline feature: direction-aligned 2+/3-lens
agreements get banners everywhere, Discord pings (`scanner/confluence_alert.py`,
triples mention @here; state-deduped), a permanent ALERTS page log, and the
★ MY NAMES page.

---

## Tech stack

| Layer | What |
|-------|------|
| Scanner engines | Python (`scanner/`, `phasemap/`) — run in GitHub Actions |
| Frontend | Vanilla JS + CSS — static site on **Cloudflare Pages** (`public/`), iOS-style dark theme, PWA with service worker |
| Backend API | Cloudflare Pages Functions (`functions/api/*.js`) — CF **Workers runtime, NOT Node** (no `require`, no fs; env via `context.env`) |
| Scheduler | GitHub Actions cron (`.github/workflows/`) |
| Data source | `yfinance` (pinned) — free, ~15 min delayed, survivor-biased history. Production-grade provider (EODHD/Norgate) is an open owner decision |
| Broker | **Bybit** USDT perps: client/bracket/reconcile/kill-switch BUILT + tested, paper/testnet only, live double-gated. IBKR for ASX later |

---

## Repository layout (current)

```
scanner/               VIVEK + Specs engines, bot, alerts
  config.py            ALL tunable constants — never hardcode magic numbers
  vivek.py             VIVEK 5.0 engine (levels W/3D/D, plans, grading, narrative)
  scan.py              scan_vivek_market → public/data/<m>_vivek.json
  run.py               CLI: python -m scanner.run [--market ...]; publishes bot_rules.json
  spec.py + spec_run.py    Specs lens (asx+nasdaq) → <m>_spec.json
  confluence_alert.py  multi-lens Discord pings + ALERTS page history log
  vivek_backtest.py    walk-forward replay (1D/3D/1W, level_tf cohorts)
  vivek_journal.py     RETIRED as a journal (2026-07-09) — module kept: the
                       backtester + bot runner import its trade primitives
                       (notify/alerts/pulse + broker paper_run/bracket_order/
                       reconcile DELETED 2026-07-20 — see git history)
  universe.py          ASX full (~2,000) · NASDAQ Global Select (~1,430) · crypto top-100+extras
  sectorbreadth.py     HORIZON — sector participation + rotation (see below).
                       REPORT-ONLY: it never touches which trades get taken.
  regime.py            REGIME — participation, index-vs-median divergence,
                       sector relative strength, basing counts. Also REPORT-ONLY.
  broker/              vivek_bot.py (decision engine: A+ only, 30 open TOTAL
                       across all markets, one/symbol, 3/sector PER MARKET), vivek_run.py (paper book),
                       bybit_client/bybit_bracket/bybit_reconcile, kill_switch,
                       circuit_breaker, pre_trade_check, ...
phasemap/              PhaseMap package (engine/narrate/output/backtest/tests)
public/                the site (see "Frontend rules")
functions/api/         scan.js + close.js (Actions dispatch, KV rate-limited),
                       journal.js (KV sync store), price/quote/tick proxies
tests/ + phasemap/tests/ + test/*.test.js   1255 pytest (58 files) + 650 JS (16 suites) — EVERY push (test.yml)
journal/               bot book + state files committed by Actions
data_universe/         bundled ticker CSVs (fallbacks)
scripts/               CI-side one-offs and helpers, NOT imported by the engine
  reco_note.py         daily auto-written commentary (reco_note.yml)
  backfill_sector_history.py   replays the engine backwards to rebuild
                       data/sector_history.json (backfill_history.yml)
  resize_book_notional.py      one-off: restates the OPEN book at the current
                       fixed notional. Dry by default, idempotent, --apply
```

## Workflows (current)

| Workflow | Schedule | Does |
|---|---|---|
| dispatch_scan.yml | on push to itself or `.github/scan-kick` | turns a PUSH into a real `workflow_dispatch` of scan.yml (`market=all`). **The only way a cloud Claude session can trigger a scan** — these sessions can push but cannot reach api.github.com or POST to /api/scan. Touch `.github/scan-kick`, push, done. `permissions: actions: write`; GITHUB_TOKEN-created dispatches DO start runs (the documented exception to the no-recursive-workflows guard) |
| test.yml | every push/PR | pytest + 15 JS suites + syntax gate. A new `test/*.test.js` needs its own step here or it never runs — **and since 2026-07-28 that rule is a GATE, not a convention** (`test_screenshot_determinism.py::test_every_javascript_suite_has_a_step_in_the_workflow` fails the push instead of letting the suite pass locally and never run) — the newest is `screenshot_sentinel.test.js`. New `tests/*.py` files need NO registration (`pytest` collects the directory). The path filter now includes `scripts/**`, `pytest.ini`, `public/css/**`, `public/*.html` and `.github/workflows/**` — each was read by a suite that did not run when you edited it (TOP100 #48) |
| scan.yml | market-hours crons, SEQUENTIAL markets (weekend = crypto-only); `:47` ASX freshness backstop | VIVEK scans + bot book + confluence alert |
| crypto_bot.yml | `:22` + `:52` all days; the `:22` fire skips weekday scan.yml windows (scan.yml already scans crypto then), `:52` is a freshness backstop that skips when fresh | crypto scan + crypto slice of the bot book |
| confluence.yml | daily 08:45 UTC | post-nightly confluence ping (scan group SOLELY owns the dedupe state) |
| backup_book.yml | daily 21:35 UTC | snapshots the bot book + journal state into `backups/` (keep 30) + uploads the set as a 90-day run artifact (off-tree copy, 2026-07-21) |
| reco_note.yml | daily 08:52 UTC | auto-writes `public/data/reco_note.json` from committed scan data (`scripts/reco_note.py`, author "auto"); never overwrites a same-day hand-written Claude note; commentary only, outside every signal path (2026-07-23 — cloud scheduled Claude sessions can't reach the push token, so CI owns the daily cadence) |
| phasemap.yml | nightly 08:30 UTC | PhaseMap + Specs + schema gate (SLIM latest.json + narrations sidecar); no confluence here |
| lens_backtest.yml | weekly Sun | PhaseMap/Specs/VIVEK replays → owns `public/data/vivek_backtest.json` (Insights reads it) |
| vivek_backtest.yml | monthly 1st | LONG-ONLY evidence → `vivek_backtest_longonly.json` ONLY |
| kill_switch.yml | half-hourly 24/7 | loss check on the BOT BOOK per market, open positions re-priced with LIVE quotes (fallback: last-scan marks); broker flatten only if keys set. Hosts the freshness watchdog (scanner/watchdog.py) |
| stop_watcher.yml | 5-min 24/7 | curls /api/tick (cloud watcher for the KV manual journal). Fails the job on a non-200 EXCEPT 503 — see "The tick endpoint" below |
| close_position.yml | manual | journal_type=bot closes a BOT BOOK position (the real track record); swing/scalp = legacy journals. Auto re-dispatches itself (max 3) if the scan mutex evicts it — 2026-07-28, see below |
| test_alerts.yml | manual | alert-path self-test: forces one test message through every configured channel (`watchdog --test-alert`); run after any alert-secret change, read the job summary |
| backfill_history.yml | manual | replays the real engine backwards to rebuild `data/sector_history.json` (`scripts/backfill_sector_history.py`). `dry_run` defaults TRUE — run that first, the printed post-mortem IS the deliverable. In the `scan` group because it writes a file every scan also writes. Not scheduled: once the gap is filled there is nothing left to fill (2026-07-28, see HORIZON → BACKFILL) |
| evidence_brief.yml | daily 21:00 UTC (7am/8am Melb) | runs `scripts/evidence_brief.py` byte-untouched and delivers the printed brief to the step summary + Discord (owner-ruled 2026-08-01). READ-ONLY: contents read, no git, NOT in the scan mutex, no assert_staged/WATCHDOG entry (it commits nothing). The script's exit 1 ("brief names an ISSUE") stays a GREEN run — the issue reaches the owner inside the brief; the watchdog owns staleness alarms. Pins: `tests/test_evidence_brief_workflow.py` |
| commit_sentinel.yml | every push to main | detection half of branch protection (2026-08-20): checks the AUTHENTICATED PUSHER + every commit's author/committer email against the identity set observed on main's real history (`scripts/commit_sentinel.py`); flags force-pushes and truncated payloads too. DETECTION ONLY — anomaly = green run + Discord WARNING (evidence_brief pattern), never blocks/reverts. NOT in the scan mutex, contents: read, no path filter (the quiet-edit scenario IS a data-file edit). Honest limit recorded in both files: the 2026-08-20 incident commit wore the owner's identity end-to-end, so a perfectly disguised integration is branch protection's job, not this one's. Pins: `tests/test_commit_sentinel.py` |
| turtle.yml | daily 09:30 UTC | the TURTLE lens (`scanner/turtle_run.py`) -> `public/data/<market>_turtle.json` for asx/nasdaq/crypto. Own concurrency group (`turtle`), NOT `scan` -- it writes only its own three files. 09:30 is clear of the 08:30/08:45/08:52 nightly cluster so the two full-universe Yahoo walks are an hour apart. One pathspec per `git add`, ANY-OF assert_staged gated to `schedule` (a single-market dispatch legitimately leaves two files absent), Tier 3 retry loop. WATCHDOG_RUNS 26h at WARNING, not CRITICAL: a stale Turtle file costs a day of signals on a report-only surface and the page prints its own `generated_at`. Pins: `tests/test_turtle.py` |
| alert_returns.yml | daily 22:20 UTC | the EDGE PIPELINE (grown from one script to four, batch-100 2026-08-20), in order: `alert_returns.py` (ingests alignments + stamps 1/5/10/20-SESSION forward returns into `data/alert_forward_returns.json`, enriches blank-only context fields frozen at first write) → `edge_rosters.py` (daily plain-A+ roster baseline, `data/edge_rosters.json`, same imported machinery/plumbing) → `book_stress.py` (uniform-shock tide table vs real stops, `public/data/book_stress.json` — the journal's tide line reads it) → `alert_edge_report.py` printed into the STEP SUMMARY daily (read-only, pinned) → `edge_summary.py` (dedup aligned-vs-baseline headline as `public/data/edge_summary.json`, math IMPORTED from the report, never re-typed) → a SUNDAY-ONLY Discord digest of the report head (BOM-trim + named UA per 2026-08-01; missing webhook degrades, never reds). A SIDE LEDGER on purpose, twice over: alert_history.json is a rolling 800-cap window already evicting at ~14 days (a 20-session return can never mature in it) AND is written inside the scan mutex (a second writer would race it) — so the scripts READ the history, never write it (test-pinned). Idempotent; returns FROZEN at first measurement; commit skips only when ALL FOUR artefacts print their `*_UNCHANGED` sentinel; each staged one-pathspec-at-a-time with `\|\| true` paired to the ANY-OF assert_staged; WATCHDOG_RUNS 26h. Pins: `tests/test_alert_returns.py`, `test_edge_rosters.py`, `test_book_stress.py`, `test_alert_edge_report.py`, `test_edge_summary.py` |

(Table refreshed 2026-07-20 — discord_digest.yml deleted; notify/alerts/pulse/
paper_run/bracket_order/reconcile modules deleted. evidence_brief.yml added
2026-08-01.)

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

Still true after the fix: **Telegram and SMTP are UNCONFIGURED** (empty
secrets), so Discord is the only live channel. Run `test_alerts.yml` after any
alert-secret change and read the job log — it is the only end-to-end proof.

**The `scan` mutex is JOB-scoped, deliberately (2026-07-28 — REFINEMENTS #108,
#109).** scan.yml, crypto_bot.yml and close_position.yml share concurrency
`group: scan` so two writers can never touch the paper book at once
(load-bearing: the 30-position cap is global, so concurrent writers could each
read "23 open" and both open). That group sits on the *scan* / *crypto* / *close*
JOBS, not at workflow level. GitHub keeps only ONE pending run per group and
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

**Silent-failure protection (2026-07-20, Phase 5; extended 2026-07-28 by TOP100
Tier 3).** Callers of `scripts/assert_staged.sh`, in full: scan, crypto_bot,
phasemap, backup_book, reco_note, and — new in Tier 3 — close_position, gated to
`journal_type=bot` only (see "Tier 3" below for why the swing/scalp path must
stay a green no-op). `confluence.yml` deliberately has NO assert_staged and
gates on an UNSTAGED working tree instead; `backfill_history.yml` deliberately
has none at all. Both absences are pinned by tests so they read as decisions
rather than omissions. Every caller runs it after
staging — a scheduled run that stages none of its must-change outputs FAILS
loudly instead of finishing green (the Phase 3 staging bug ran green 5x while
committing nothing). `scanner/watchdog.py` (hosted in kill_switch.yml +
crypto_bot.yml) additionally probes content timestamps + GitHub run history
and alerts on staleness with strict noise rules (first / 6h reminder /
recovery; red runs are GitHub's to email about). Thresholds: config
WATCHDOG_*. When adding a workflow that commits data, give it an
assert_staged call and a WATCHDOG_RUNS entry.

### The tick endpoint — and why a 503 must NOT fail the job (2026-07-28)

**`/api/tick` IS LIVE (corrected 2026-08-18).** The owner set `TICK_SECRET` in both halves at some point after this section was written, and the endpoint proves it: an unauthenticated probe now returns **401** (`tick.js` returns 503 only when the secret is unset), and stop_watcher.yml — the only caller that holds the secret — has been green for hundreds of consecutive runs, which a mismatch could not be. **The cloud stop/target watcher is armed; paper stops no longer depend on a chart page being open.** The paragraph below is kept as the historical record of the blackout and of why the 503 branch exists; its claim that the secret is unset is FALSE as of this correction.

HISTORICAL: `TICK_SECRET` was not set in the
Cloudflare Pages project, and `functions/api/tick.js` fails closed: no secret →
**503**, configured-but-unauthenticated → **401**. An unauthenticated probe of
the live URL returns 503, which is proof of the unset secret rather than an
inference. Consequence, and it is the important half of this section: **paper
stops and targets only fire while a chart page is open on some device.** Closing
it is the owner's action — set `TICK_SECRET` in Cloudflare Pages → Settings →
Environment variables and mirror the identical value as the `TICK_SECRET`
GitHub Actions secret. It is a credential; do not generate or handle one.

- **stop_watcher.yml used to exit 0 on every non-200**, so all 288 daily runs
  showed green against an endpoint that had never worked. Nothing else watched
  it, so "green" was the entire signal and it meant nothing. Making it `exit 1`
  fixed the blind spot and immediately created a worse one: a failure email
  every five minutes, for ever, about a fact only the owner can change. An alarm
  that cannot stop ringing gets muted, and a muted channel is how the original
  blackout happened.
- **000 (NO ANSWER) IS NO LONGER FATAL (2026-08-18, run #776).** The taxonomy
  below drew its line in the wrong place: it treated "the server said 5xx" and
  "nothing answered at all" as the same evidence, and they are not. Every other
  code here is a statement Cloudflare made about its own state, which one runner
  can trust; 000 is the ABSENCE of a statement, and from a single vantage point
  it cannot distinguish a site outage from that runner's egress hiccuping for
  two minutes. Empirically it has been the latter every single time — #277,
  #372, #406 and #776, four for four, with the endpoint answering 401 normally
  throughout #776. Four false "DOWN" alarms on a job that runs 288 times a day
  is precisely how a channel gets muted, which is the blackout this whole
  section exists to prevent. So 000 now behaves like 503: `::warning::` plus a
  step summary, exit 0. **The alarm is not dropped, it moves to the component
  with a SECOND VANTAGE POINT** — `watchdog.probe_endpoints()` in
  kill_switch.yml probes the same URL half-hourly from a different runner and
  raises `tick_unreachable` through the state machine that can say it once,
  remind every `WATCHDOG_RENOTIFY_HOURS`, and **announce recovery** (a red run
  structurally cannot). A blip only this runner saw finds the watchdog seeing
  401 and stays correctly silent; a real outage is seen by both. Stated cost:
  detection of a genuine outage moves from ~5 min to at most 30 — the deliberate
  price of an alarm that is believed when it fires. 401 and 5xx stay fatal.
  Pinned behaviourally in `tests/test_workflow_hardening.py` (000 → exit 0 and
  names the watchdog; 401/500/502 → exit 1; 503 → exit 0; plus a pin that the
  watchdog really does still raise `tick_unreachable`, because a handoff to a
  receiver that stopped listening alerts nobody).
- **The split is the fix: one icon was being asked two questions.** 503 means
  *never switched on* (a standing setup gap) — the job stays green and says so
  loudly on the run page via `::warning::` plus a step summary carrying the
  exact Cloudflare steps. Every OTHER non-200 means *was configured and has now
  broken* (401 = secret mismatch between Cloudflare and GitHub, 000 =
  unreachable, 5xx = down) — still `exit 1`, still an email, because that is a
  real regression worth hearing about the moment it happens.
- **401 stays fatal even though it floods too, and the reason is not symmetry.**
  This job is the ONLY caller that holds the secret, so it is the only thing
  that can see a half-configured setup. To the watchdog's deliberately
  anonymous probe a 401 reads as "configured and correctly refusing an
  anonymous caller" = healthy — right for the prober, wrong for the system,
  because `TICK_SECRET` set in Cloudflare and absent in GitHub means the
  watcher still is not running. Make 401 green and that state goes invisible to
  every channel at once, which is the original blackout in a better disguise.
  It is also the one flood that follows immediately from an action the owner
  just took, so it is feedback rather than ambience. **Set both halves in one
  sitting**; the 503 step summary says so at the point of action.
- **The 200/503/other taxonomy above was never reachable on a curl-level
  failure, and that was the whole of run #372 (2026-08-04).** `Process completed
  with exit code 28` — curl's "operation timed out", not any exit this workflow
  writes. GitHub's default shell is `bash -e {0}`, so the bare
  `code=$(curl ...)` assignment ABORTED THE STEP the instant curl failed:
  upstream of the 3-digit normalisation, of the retry loop, of the 503 branch
  and of the `exit 1` branch alike. The log is the proof — not one `attempt N`
  line printed. So the three tries that exist to absorb a transient were
  unreachable by the most common transient there is, and a single 30-second
  stall was emailed as "stop watcher DOWN" (run #277 on Jul 28 is the same
  signature; those two are the ONLY failures this job has ever had). Fixed with
  `|| true` on that one assignment — which neutralises curl's STATUS without
  appending a second value to its OUTPUT, the distinction from the `|| echo 000`
  that caused the earlier "000000" bug. This job judges on the HTTP code, never
  on curl's exit code. Pinned behaviourally (the shipped run block executed under
  `bash -e` against a curl stubbed to fail exactly as #372's did, asserting it
  reaches `exit 1` and prints `attempt 3` rather than dying with 28) plus two
  source pins, in `tests/test_workflow_hardening.py`.
- **Endpoint health moved to `watchdog.probe_endpoints()`**, which inherits the
  same state machine as every other finding: say it once, remind every
  `WATCHDOG_RENOTIFY_HOURS`, and — the thing a red run structurally cannot do —
  **announce recovery**. Three states, deliberately: 401 → healthy (configured
  and correctly refusing an anonymous caller), 503 → WARNING, 200 → **CRITICAL**,
  because an unauthenticated 200 means the watcher is open to anyone who knows
  the URL and every synced journal is reachable through it. That is a security
  finding, not a freshness one.
- **The probe is UNAUTHENTICATED BY CONSTRUCTION and must stay that way.**
  Sending the real secret to "probe it properly" would make the monitor fire an
  extra unscheduled tick every 30 minutes — the monitor would start moving the
  thing it monitors. `tests/test_watchdog.py::test_tick_probe_is_never_sent_a_credential`
  fails if a credential ever reaches the URL.
- **`WATCHDOG_RUNS["stop_watcher.yml"]` is retained but re-scoped** to one
  question — "is the 5-minute cron still firing at all?" — since a green run no
  longer implies a healthy endpoint. Note the two mechanisms cancelled rather
  than complemented each other while this was broken: `probe_runs` stays silent
  when a workflow's latest run FAILED (on the rule that GitHub emailed already),
  so the watchdog was mute for exactly as long as the inbox was flooded.

---

## Journals & track record — IMPORTANT

- **The bot book is the ONE AND ONLY track record.** Layout v2 (2026-07-20):
  CANONICAL per-market files `journal/vivek_bot_book.<market>.json` (a market's
  run can only write its own file — cross-market clobber impossible by
  construction); `journal/vivek_bot_book.json` + the public twin are a DERIVED
  combined view (same old schema; regenerate with
  `python -m scanner.broker.vivek_run --rebuild-combined`; audit with
  `--verify` — the scan/close workflows run it as a failing gate). A+ only (grade_raw,
  unsmoothed), **max 30 open across ALL markets combined** (owner, 2026-07-28 —
  `VIVEK_BOT_MAX_OPEN_TOTAL`; the per-market cap is set equal to it so one market
  CAN hold the whole book, and `vivek_run._open_elsewhere` counts the sibling
  market files before each decision — fail-closed if one is unreadable), one per
  symbol, **3 per sector PER MARKET** (not global — see below), daily+weekly loss
  guards, manual close via close_position.yml journal_type=bot.
- **The correlation cap is the only limit that is still per-market**
  (REFINEMENTS #113, owner decision). Positions (30), notional ($150,000) and
  one-per-symbol are all cross-market; `decide()` seeds `sector_counts` from the
  single market's `open_book`, so 3 ASX financials + 3 NASDAQ financials is six
  of one real sector with every check passing. Not repaired — tightening what
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
  forward on each 30 stocks and a cap of 150k"): `VIVEK_BOT_POSITION_NOTIONAL`
  = $5,000 a position, `VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL` = $150,000 (the dollar
  twin of the 30-slot cap), `VIVEK_BOT_ACCOUNT_EQUITY` = $150,000. Equity no
  longer sizes positions — it scales the loss guards and the leverage ceiling,
  which is why it had to move with the book. **The dollars RISKED now vary with
  the stop distance** (~$50–$1,250, typically $250–$500); position COUNT is the
  risk dial, not position size. Do not "fix" that by re-clamping `risk_pct` in
  fixed mode — see `tests/test_fixed_notional.py`. Set
  `VIVEK_BOT_POSITION_NOTIONAL = 0` to restore the old 0.35%-risk path exactly.
  The `open_book` projection `run_market` hands `decide()` carries `notional`
  (2026-07-28): `decide()` seeds `open_notional` from it, so omitting the field
  made the $150,000 ceiling count every market's exposure EXCEPT the one it was
  deciding for. Latent while every position is $5,000 and the 30-slot cap binds
  first at exactly $150,000 — but it is a risk cap reading a number it believes
  is complete, so it is fixed rather than noted.
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
  - **Dollar P&L is not a like-for-like series across 2026-07-28. R is.** This
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
- **`VIVEK_BOT_REVIEW_DAILY_LOSS_PCT = 15.0`** — flag when `risk_usd` is ≥ this
  % of `daily_loss_limit()` ($4,500 = equity × `MAX_DAILY_LOSS_PCT`). The number
  sits between two others and cannot sensibly be moved without checking both:
  `MAX_STOP_PCT` caps any NEW position at 25% × $5,000 = $1,250 of risk = **27.8%
  of the guard**, so any threshold ≥ ~28 is dead code that would never fire and
  nobody would notice; a typical A+ plan runs a 5–12% stop = $250–$600 = 6–13%.
  15 flags the genuinely wide half without crying wolf. A test asserts
  `0 < threshold < ceiling` so the dead-code case fails loudly. 0 = off.
- **Three hops, because a flag nobody sees is not a flag.** The ticket carries
  `review` (a list, empty when clean); `_ticket_to_position` copies it onto the
  book row; `vivek_run._notify_reviews` pushes it to Discord. Skip any hop and
  the mark survives only in a log line inside a finished Actions run, which is
  not a place a decision gets made.
- **The push is `trade_review`, NOTICE → Discord only, rate limit 0**
  (`VIVEK_BOT_REVIEW_PUSH`, ON — unlike `VIVEK_BOT_NOTIFY_TRADES` beside it,
  which digests every open/close through every channel including email and stays
  off). Fires AFTER `_save_market_book`, so a dry run is silent and nothing is
  announced that failed to persist. One message per run, not per position,
  because the number worth the message is the COMBINED share: three flagged
  opens at 27% each is 80% of the day gone in one run and nobody sums that by
  hand across three notifications. Rate limit 0 for the same per-EVENT-TYPE
  reason as `sector_run` — markets run sequentially in one job, so a limit could
  only ever drop the second market's flagged open, and losing one is the entire
  failure mode.
- **The message says the trade is already TAKEN.** The choice on offer is not
  take-or-skip but *whose position it is*: leave it and it is the bot's at
  $5,000, or close it in the book and take it yourself sized your own way. A
  message that read like a pre-trade approval request would misdescribe what the
  system actually does, and a test asserts the wording.
- **Front end:** `reviewChip` in `public/js/journal.js` (`.jr-review`,
  journal.css) — amber, outlined, no pulse, deliberately quieter than `.jr-flip`,
  which is a live warning that the chart turned. **It renders on CLOSED rows
  too, on purpose**: the flag records what was known at entry, and how the
  flagged trades actually went is the only evidence that will ever say whether
  15.0 is set sensibly. An absent `review` key (row written before flags
  existed) and an empty list (checked, clean) both render nothing but are NOT the
  same thing — do not collapse them by defaulting the key server-side.
- Tests: `tests/test_review_flags.py` (27) + `test/journal_review.test.js` (9,
  which slices the real `reviewChip` out of the shipped file rather than
  mirroring it, so a rename fails the suite instead of silently testing a copy).

- The old "track-record journal" (every armed A+/A, every timeframe, no cap —
  it hit 203 open / 12 closed) was **retired 2026-07-09** along with the
  dashboard strip and TRACK page. Do not resurrect it as a headline number.
- Manual journals ("Me" side) live in browser localStorage, synced via
  Cloudflare KV (`gbs-sync.js`, `/api/journal?code=...`). The unified
  watchlist (stars from all lenses) lives INSIDE that store
  (`watchlists`, keys `<lens>:<market>:<TICKER>`, tombstoned un-stars).

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
  pipeline is down; 90m is `heartbeat.js`'s `DEFAULT_STALE_MIN`; the 30-position
  cap is read from `bot_rules.json`. Tests parse those two Functions and fail if
  either number moves without this one following.
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
- Tests: `test/status.test.js` (48, registered in test.yml), all logic
  mutation-verified (9 mutations, every one caught, source restored
  byte-identical). Screenshot baselines re-cut at `screenshot-baselines-v19`.

---

## HORIZON — the rotation surface (2026-07-28)

**Why it exists.** Owner post-mortem: ASX consumer discretionaries ran for four
weeks while the market was "SHIT to trade", and the book held none of them. Two
separate failures let that happen and the module addresses both.
(1) The only published sector number was a RAW SETUP COUNT — Materials lists 766
of the ASX's 2,212 names and out-counts everything on every scan regardless of
what it is doing, so the count could never surface a 104-name sector waking up.
(2) The book sat at its 10-slot ceiling for 20 straight sessions, so nothing
could have been taken even had it been seen. A leaderboard alone would have been
half an answer; the panel therefore always shows CAPACITY beside the leaders.

**REPORT-ONLY, deliberately.** `sectorbreadth` is imported by `scanner/run.py`
only, never by `broker/`. It reads the book; nothing reads it back. Every
question it raises — raise the 3-per-sector cap? tilt the ranking? page on
"leading sector, zero held"? — changes which trades get taken and is therefore
the owner's call, not a refactor. Keep it that way.

- **`scanner/sectorbreadth.py`** — `compute()` per market, `update()` publishes.
  Participation rate = A+/A setups ÷ names in the sector; ranked descending by
  rate, then by A+/A count. `run.py` fills `breadth_inputs[market]` only for
  `("asx", "nasdaq")`, so a crypto-only weekend run never calls `update()`.
- **The denominator is NOT the same on both markets** (`names_source`). ASX
  divides by names LISTED in the sector (the universe carries GICS for all
  2,212) — a true participation rate. NASDAQ's symbol file ships no sector
  column, so it divides by the names a scan has CLASSIFIED so far via
  `data/sector_map.json`. Ranking within NASDAQ is sound; the LEVEL is not
  comparable to ASX and drifts down as coverage fills in. The page says so.
- **Unranked rows are published, never ranked, and always carry a reason.**
  `real: false` = not a sector (Unclassified/None — 389 ASX names; on the first
  run that bucket topped the board at 23.4%, the exact failure the module
  exists to correct wearing a different hat). `thin · N` = under
  `SECTOR_BREADTH_MIN_NAMES` (15). `off-directory` = held under a label the
  market's directory does not use, so there is no listing count to divide by —
  this is REFINEMENTS #112 surfacing on the page (ASX `Financial Services` and
  `Insurance` each hold 1 under Yahoo-style labels, and the 3-per-sector cap
  counts them as separate buckets). Bars scale off RANKED rows only.
- **Capacity is stated in BOTH currencies, because they can disagree.** Slots
  and dollars are two different readings of "how full is the book", and the
  panel prints the reconciliation whenever the dollar headroom exceeds the slot
  headroom by more than 25%. That gap was enormous before the resize — 24 of 30
  slots read 80% full while $6.1k of the $150k ceiling read 4% invested,
  because the 24 legacy holdings averaged ~$250 each, sized off the old $10,000
  equity. **The 2026-07-28 resize closed it**: 24 × $5,000 = $120,000, so 80% of
  the slots is now 80% of the notional and the two agree. Keep the divergence
  logic — it is the general case, and the next retune of
  `VIVEK_BOT_POSITION_NOTIONAL` reopens the gap on every row already held. The
  number that answers "how much can I put to work" is still free slots ×
  `VIVEK_BOT_POSITION_NOTIONAL` ($30k today), which `book_state()` publishes as
  `position_notional`. Slots bind first; do not read the notional bar as spare
  room.
- **Coverage is stated, not hidden.** 91 of 216 ASX A+/A sit in names carrying
  no sector at all, so the footnote prints what share of the day's A+/A the
  ranked sectors actually account for whenever the off-rank share tops 10%.
  "Leading sector" is a claim about the part of the tape this board can see.
- **`data/sector_history.json` is the only long sector memory in the system**
  (the 7-day PhaseMap archive was too short to reconstruct July after the
  fact). One row per market per day, capped at 2,000; feeds the trend column.
- **The STREAK is the number that separates a shrug from a miss in progress**
  (2026-07-28). "Consumer Discretionary is third and you hold none" is a fact
  you can wave off once; "for the 19th session running" is not the same
  sentence, and the gap between them is the entire four weeks.
  `unheld_streak()` counts consecutive most-recent SESSIONS a sector led on
  rate while the book held zero of it, rebuilt from history rather than kept as
  a counter so a re-run, a backfill or a skipped day cannot corrupt it. Rows
  exist only for days the scan ran, so a weekend does not break a run.
  `append_history` is called BEFORE `horizon()`, so a first-day leader reads 1.
  - **A run stops at a session whose `held` is null**, not just at a held
    position. Null means reconstructed from before the bot book existed, where
    "held nothing" cannot be told apart from "no book to hold anything" — so the
    streak reports only the part of the run we can stand behind. See BACKFILL.
  - The reconstruction MUST re-apply all three of `compute()`'s exclusions —
    `_NOT_A_SECTOR`, `MIN_NAMES`, rate > 0 — because history stores every
    bucket that had listed names. Today's real ASX row is led by "Unclassified"
    at 91/389 = 23.4%, above every genuine sector. Omitting the `_NOT_A_SECTOR`
    test (the version this shipped with, caught pre-commit) hands it rank 1
    every day, pushes the real third-place sector out of the top three, and
    reports a streak of ZERO for the one sector the surface exists to catch —
    silently, and only for the sector that mattered. Tie-break is
    `(-rate, -ag, name)`, identical to the live sort, so a reconstructed rank
    can never disagree with the rank that was displayed.
- **`SECTOR_BREADTH_RUN_ALERT` (5 sessions) is when the surface stops
  describing and starts shouting**, and it widened `expand`. The old rule fired
  only when the book could not act; a fortnight of leading-with-nothing-held
  and 30 slots FREE is the worse reading — being capped out is at least an
  explanation — and it now raises the banner too. Because both states raise it,
  `horizon()` publishes `expand_why` and the banner prints that instead of the
  old hard-coded "it can barely act", which was a lie in the new case. The
  sustained note is `notes.insert(0, ...)` on purpose: the dashboard strip
  renders only `notes[0]`. Still report-only — it changes the volume, never the
  trades.
- **Both files must stay in `scan.yml`'s scoped `SHARED` staging list.**
  `public/data/sector_breadth.json` is shared, not per-market: a run recomputes
  only the market it scanned and MERGES it in, so an ASX-only run must stage
  the whole file or the NASDAQ block it just carried forward is dropped. Leave
  the history file unstaged and every session starts from day one forever.
- **Front end:** `public/js/horizon.js` + `public/css/horizon.css`, one
  vocabulary in two skins — the full board `#horizon-panel` on sectors.html
  (follows the market buttons) and the compact strip `#horizon-strip` on
  index.html. Both hide themselves silently if the JSON is missing, so a
  market that has never run degrades to nothing rather than to an error.
- Constants: `SECTOR_BREADTH_*` in `scanner/config.py`.
- **The sustained-run alarm pushes to Discord** (2026-07-28, owner decision —
  `sectorbreadth.notify()`). A dashboard only works on the days you open it, and
  the raw ingredients of the July rotation were on the page for four weeks while
  the miss happened anyway. `notify()` fires the first time a sector enters
  `horizon()["sustained"]`, then at most once every
  `SECTOR_BREADTH_RUN_ALERT_REPEAT_DAYS` (7) for as long as the run lasts.
  - **Its own `NOTICE` severity tier**, routed to `["discord"]` only. INFO is
    silent and WARNING would file a market observation beside kill switches and
    order failures at the same volume. Nothing is *wrong* when this fires.
  - **The ping memory lives in `data/sector_history.json`** under
    `hist["alerts"]["sector_run"]`, NOT in `journal/alert_state.json`. The
    router's own state file is not in scan.yml's staging list, so it dies with
    the Actions container — every scan would read "never pinged" and re-fire,
    which for a run that lasts weeks means a ping every scan for a fortnight.
    The history file is committed by the same step that commits the streak the
    alert is derived from, so the memory and the number can never disagree about
    what day it is.
  - **`ALERT_RATE_LIMITS["sector_run"] = 0` on purpose.** The router's limit is
    per EVENT TYPE and scan.yml runs markets sequentially in one job, so ASX
    firing would silently swallow NASDAQ. `notify()` owns the dedupe per market
    AND per sector, which is strictly tighter everywhere it differs.
  - A sector that stops leading, or that the book finally buys, is FORGOTTEN —
    scoped to the market in hand, so a crypto-only weekend cannot wipe ASX
    memory. Report-only: it changes what gets SAID, never what gets taken.

### BACKFILL — filling the memory backwards (2026-07-28)

`scripts/backfill_sector_history.py` + `.github/workflows/backfill_history.yml`.
History only started being written on 2026-07-28, a week after the ASX Consumer
Discretionary rotation it exists to catch had already run: until the gap is
filled the streak can only ever say "1" and the trend column has nothing to
trend. The script replays the REAL engine — `evaluate` → liquidity gate →
`score_and_grade` → hysteresis → `build_plans` → `gate_grade`, scan.py's order,
on frames truncated to each session — and writes rows marked `"r": 1`.

- **UNKNOWN IS NOT ZERO — the one rule the whole thing rests on.** The bot
  book's earliest entry is 2026-06-28; before that, whether the book held a
  sector is not merely unrecorded but *unknowable* — there was no book. Those
  `held` cells are written `null`, never `0`, and **`unheld_streak` now stops at
  a null exactly as it stops at a held position** (`sectorbreadth.py`). Counting
  through a null the way we count through a zero would have manufactured streaks
  of up to six months the first time a backfill landed and fired the Discord
  alarm on every sector at once — the one failure mode that costs that number
  its credibility permanently.
- **Honest about its own error bars.** REAL: the per-name grade, the liquidity
  gate recomputed per session, the sector denominator from the same universe
  file. KNOWN WRONG and bounded: survivorship (today's universe, so delisted
  names are missing), and hysteresis chains once per DAY where live chains once
  per SCAN — which skews A+/A LOW, i.e. wrong in the conservative direction.
  The first `--warmup` sessions are computed then DISCARDED because their
  hysteresis is cold. The still-forming trailing bar is dropped using
  `_bar_is_forming` with **market-local** time (it compares the wall clock
  against the market's own close, so handing it UTC would misjudge every ASX
  session).
- **The replay never writes the repo.** `--rows-out` parks the reconstruction in
  `$RUNNER_TEMP`; `--merge-only` folds it into the history file as it stands
  now. That split is what makes the push retry safe: each attempt re-merges the
  parked rows against a freshly-reset `origin/main`, so a scan that landed
  mid-replay is folded in rather than reverted, and attempt 1 and attempt 5 run
  identical code. Real rows always beat reconstructed ones; a re-run is
  idempotent.
- **Manual only (`workflow_dispatch`), `dry_run` defaulting TRUE**, in the
  `scan` concurrency group. Not scheduled because it is not maintenance — the
  live scan writes today's row every session, so once the gap is filled there is
  nothing left to fill, and a re-run costs ~25 min of a runner for a result that
  does not change. Run the dry pass first: the printed post-mortem (which
  sectors led, for how long, between which dates) is the actual deliverable; the
  file is what keeps it true tomorrow.

---

## REGIME — is the index telling the truth? (2026-07-28)

The owner's framing: *"this scanner and this scanner alone is INSUFFICIENT."*
HORIZON answers "which sector is running"; REGIME answers the question that sits
underneath it — whether the index level is representative of the names in it,
and which sectors are outperforming rather than merely numerous. Built to say,
in one line, the thing the scanner could not previously express: *the index is up
while the median name is down.*

- **`scanner/regime.py`** — `compute(market, frames, universe, bench=...)` per
  market, `publish()` merges and writes `public/data/regime.json`, `report()`
  prints. Computed INSIDE `run.py`'s market loop because it reads `deep_frames`
  (five years of bars for every name, the largest object in the scan) and that is
  the only point at which they exist; only the finished block travels out.
- **Four things, one payload.** (1) Participation — % above the 200-day and the
  50-day, net highs-minus-lows. (2) Divergence — benchmark return vs the MEDIAN
  name's return over the same window; `REGIME_DIVERGENCE_MIN` (2%) is where the
  gap is called wide and the page says the index is being carried by its biggest
  names. (3) Relative strength — each sector's median return against the market
  median, with a top-3 streak so a one-day leader reads differently from a
  thirty-session one. (4) Basing/coiling counts — names compressing but not yet
  triggering, which is the pre-setup population a grade filter cannot show.
- **Benchmarks are per market** (`REGIME_BENCHMARK`: ASX `^AXJO`, NASDAQ
  `^IXIC`). Crypto has no index worth the name here and is not computed.
- **REPORT-ONLY, same as HORIZON.** Nothing in `broker/` imports it. Whether a
  narrow tape should change position sizing or the ranking is the owner's call.
- **Front end:** `public/js/regime.js` + `public/css/regime.css`, two skins from
  one vocabulary — `#regime-panel` on sectors.html (under the HORIZON board) and
  `#regime-strip` on index.html. Both hide silently when the JSON is absent, so
  the surface is invisible until the first scan writes it.
- `public/data/regime.json` is in scan.yml's SHARED staging list (merged
  per-market like sector_breadth.json). It has no history file — it recomputes
  six months from bars every run, so there is nothing to lose.
- Constants: `REGIME_*` in `scanner/config.py` (note: the older
  `REGIME_ADX_THRESHOLD` / `REGIME_RANGING_*` trio belongs to the bot's
  trend/range filter and is unrelated).

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

### The consecutive-loss breaker had never been able to trip (#16)

`check_consecutive_losses` read `t.get("pnl", 0)`. The bot book writes
`realized_r` / `gross_r` / `cost_r` / `risk_usd` and **no `pnl` at all**, so every
closed trade read as exactly breakeven. Now centralised in
`risk_manager.trade_pnl`, which takes an explicit `pnl` when it is a real number
and otherwise derives dollars from `realized_r × risk_usd`. None-safe and
NaN-safe on purpose: `None < 0` raises (taking down the whole pre-trade check),
and a NaN propagates silently through a sum making every comparison False — it
*disarms* a guard rather than tripping it, which is the worse way to fail.

- **The larger finding, unrepaired because it is a trade decision:** every
  consumer of `risk_manager` (`pre_trade_check`, `circuit_breaker`, `bybit_run`,
  `scaling_advisor`, `performance_report`) is handed the SCALP journal. Nothing
  in `vivek_run.py` or `vivek_bot.py` calls any of it, so **the bot book — the one
  and only track record — is guarded by none of these limits**: not portfolio
  heat, not the drawdown breaker, not the consecutive-loss breaker. Wiring that
  up changes which trades get taken, so it is the owner's call.
  `scripts/health_check.py` now REPORTS what those guards would say about the bot
  book without arming any of them.
- `check_consecutive_losses(journal, notify=False)` exists for exactly that
  reporter: a read-only caller must not push "circuit breaker fired — new orders
  paused" to Discord about a book whose entries were never paused.
- **"The last N" means list order, not exit-date order, and is left that way.**
  Same thing for the scalp journal; not the same thing for the bot book, where
  three markets append into one file. Changing what "consecutive" means changes
  when it fires, so it is noted in the docstring, not silently altered.

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

### Reconcile: stale `units`, and a time floor on closed-PnL matching (#19/#20)

`reconcile_journal` never copied the broker's filled `size` into `pos["units"]`,
so a partial fill booked full-size R. Separately, a vanished position was matched
against the account's last 50 closed-PnL records with **no time filter**, so
re-entering a symbol you had traded before resolved the NEW position against the
PREVIOUS trade's record. The floor is the position's own `opened_ts` minus
`BYBIT_RECONCILE_SKEW_MIN` (5 min) for runner-vs-exchange clock skew. Records
Bybit did not date, and pre-2026 rows with no `opened_ts`, bypass the filter
entirely rather than becoming uncloseable.

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

### A hand-closed partial booked only the last rung (#25)

`ensureClosedR` guarded on `if (!t.exits.length && t.exit != null)`, so a trade
that scaled 0.25 at tp1 and was then closed by hand booked **0.25 of its move and
discarded the other 0.75**. Not a display bug: `computeCloseOutcome` reads the
same resolver, so the understated R went into the stats, the equity curve and the
win rate. Direction is asymmetric and therefore worse than a wash — a
partially-scaled WINNER is under-reported (the good part is the tail you cut off)
while a partially-scaled LOSER is flattered.

- The fix sums `exits.map(e => e.frac)` and appends a synthetic exit for the
  `1 - booked` remainder. **The full ladder sums to 0.90 by design**, so even a
  trade that took all three rungs has a 10% runner that was never priced.
- **It is idempotent because it runs on EVERY load, not once at close.** A second
  pass must find the remainder already booked and do nothing; the test that pins
  this calls it six times.
- A legacy row carrying `booked_pct` but an EMPTY `exits` array is NOT booked
  twice — that combination is how rows written before the ladder existed look.

### `_init` is a session cache, and it used to be persisted (#26)

`_init` memoises the per-row sizing derivation. `mjSaveLocal` stringified it, so
it rode out to localStorage AND to the KV sync store — permanently freezing
`risk_usd` at whatever constants happened to be loaded at the moment the row was
first painted. Compounded by the first-paint ordering (#40): that was reliably
the FALLBACK constants, not the published ones.

- Now **non-enumerable** (so `JSON.stringify` cannot see it) and stamped with
  `RULES_GEN`, which `loadBotRules()` bumps. A rules change invalidates every
  cached derivation instead of leaving the page showing sizing from a previous
  ruleset. The `loadMe()` immediately after the bump is what makes the
  invalidation visible rather than merely correct.
- **1R is pinned to the PLAN stop (`risk_stop`), not the CURRENT stop.** Trailing
  a stop to breakeven used to rescale R that had already been banked, which makes
  a trade look better the moment you protect it. Legacy rows with no `risk_stop`
  recover the plan stop exactly from `entry ∓ risk`, on the correct side for
  shorts.

### Max drawdown was a function of row insertion order (#30)

`stats()` walked the trades in STORE order while `series()` beside it sorted by
exit date, so the headline drawdown and the equity curve under it could disagree
about the same set of trades. **Both numbers look plausible, which is why it
survived** — a book with a +5R, a −3R and a −1R reports −$400 in exit order and
−$300 in store order, and nothing on the page tells you which you are reading.
`byExit` now feeds both, copies before sorting (it must not reorder the caller's
array), and treats an unparseable exit date as 0 rather than throwing.

### The offline fallback had drifted, and only shows when nobody can check (#34)

`risk_manager.js` carries `PUBLISHED_DEFAULTS`, a hand-typed mirror of five
`config.py` constants. It is a real fallback, not dead code — `bot.js` fetches
`data/bot_rules.json` and falls through to the mirror only when that fetch fails.
**So the mirror is what the page shows exactly when the person reading it is
least able to verify it.** It had drifted and lived that way for months: Python
risked 0.35% over 30 positions while the JS said 0.25% over 5, and the portfolio
cap read **2.0% against a live `PORTFOLIO_HEAT_LIMIT` of 7%**.

- **The portfolio cap moving 2 → 7 is the one number here worth stating out
  loud.** It is not a loosening of a limit that was binding — nothing in
  `broker/` reads this engine (see Tier 1, the `risk_manager` wiring gap), so no
  trade was ever blocked or allowed by it. It is a *display* correcting to the
  Python that actually governs the book. If the wiring gap is ever closed, this
  is the number that starts binding, at 7%.
- **`maxPortfolioRiskPct` is the only entry that is not a straight copy** —
  Python stores a fraction (0.07), every JS consumer wants a percent (7.0) — and
  the unit conversion is precisely how it ended up at 2.0, a value that was
  neither and had been a plausible cap once.
- `test/risk_defaults.test.js` also asserts **`run.py` still PUBLISHES each
  mirrored key**, which is the half a mirror test normally misses: stop
  publishing one and `bot.js` falls through to the mirror for that key on EVERY
  load rather than only offline, so the fallback silently becomes the value.

### #27 was relabelled, not wired — deliberately

The KILL SWITCH button on bot.html called `risk.activateKillSwitch()` and dimmed
itself. No fetch, no dispatch, nothing server-side. Making it real is a
live-trading gate and therefore **never autonomous**, so the fix went the other
way: the button, its tooltip, its log line and its modal now all say what it
actually does — blocks new entries **in this browser only**, does not close
positions, does not reach a broker, does not stop the server bot — and name
`kill_switch.yml` as the thing that does. A control that looks like it flattens
the book and does not is worse than no control; a control that states its own
scope is honest at the size it really is.

### Tests

`test/journal_money.test.js` (22) and `test/risk_defaults.test.js` (20), both
registered in test.yml. **Both read the SHIPPED artefacts rather than mirroring
them** — the money suite `vm`-slices ~15 real functions out of `public/js/journal.js`
(the pattern from `journal_review`/`journal_stale`), and the defaults suite parses
the real `config.py` and `bot.html` as source. A re-typed fixture drifts in step
with the bug it is supposed to catch. The money suite ends with a **`?v=` floor
check** that fails until `journal.html` requests `journal.js?v=63` or higher,
which turns project rule 2 from a convention into a gate.

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
hardening suite also runs **`bash -n` over all 73 `run:` blocks in all 15
workflows**, the cheapest gate this repo did not have: a YAML parse says nothing
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
Flagged, not taken.

**#61 has a front-end twin, found 2026-07-28 and also flagged rather than
fixed** — `dollarsPerPoint` in `public/js/risk_manager.js` falls back to `1` for
a bare ASX ticker with no `STOCK.AX` class, which is ~43% overstated at 0.6969.
The engine now RECORDS which source it used but changes no arithmetic; see "The
Lighthouse budget was measuring the TAPE" below.

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
  participation counts and `discord.py`'s tradeable list — both REPORT-ONLY, and
  the bot buys `grade_raw`.
- **#65 — the observability half shipped; the caching half is the DECISION, not
  an unfinished edit.** `_fetch_sector` now returns a verdict beside the value —
  `ok` / `none` (the profile came back and genuinely carries no sector) /
  `failed` (the fetch raised) — and `refresh` counts all three, WARNING on any
  `failed` and naming the consequence in the same line: **a sector-less row is
  exempt from the 3-per-sector cap**, so a network flake does not merely lose a
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
"the description was accurate" — see #85, #87 and #88 below, and the retraction
at the end.

### #78/#79 — a cached payload is not a live one, and a poll must know its market

`app.js` painted a cached scan with no age check — the front-end twin of Tier 1's
#24, and the same failure in the same direction: a price from an unknown time ago
presented with the confidence of one from just now. #79 is the sharper half. A
`pollForFreshScan` in flight had no cancellation and applied whatever came back,
so **switching markets mid-poll landed ASX rows on the NASDAQ view** — a page
that is not merely stale but wrong about which market it is showing, with nothing
on screen saying so. The poll now checks the market it was started for before it
applies anything, and drops the payload if the answer changed underneath it.

### #84 — a memo keyed on a generation counter, not on a timestamp

The close preview re-parsed the entire journal out of localStorage on **every
keystroke**. The fix is a one-row memo (`closeRow` + `closeRowGen`) invalidated
by a `mjGen` counter that every writer bumps.

- **The generation counter is what makes it safe, and the discipline is that
  every writer must bump it.** `mjSaveLocal`, `mjSave` and `afterStoreChange`
  each start with `mjGen++`; the cross-tab `storage` listener routes through
  `afterStoreChange` rather than doing its own thing. Add a fourth writer that
  forgets to bump and the modal shows a row that no longer exists in the store —
  a test asserts all three still contain the bump, so the omission fails a push
  rather than surfacing as an unreproducible stale-preview report.
- **The memo is cleared on `closeModal()`, not merely invalidated.** It must not
  outlive the modal: a held row plus a matching generation is indistinguishable
  from a fresh read, so the next open of a DIFFERENT row within the same
  generation would answer from the previous one. `openCloseModal` seeds it from
  the read it just did rather than forcing a second.

### #85 — common-subexpression elimination, and the cache that was deliberately refused

`getCurrentRiskState()` walked the open book **six times per read**, and it is the
most-called method on the engine (`_emit()` after every mutation, every
`subscribe()`, and bot.js's 30s `loadData()`). Now two walks.

- **It is CSE, NOT a cache, and that distinction is the whole design.** No value
  is held across calls, so nothing can go stale. The alternative — memoising the
  result — was rejected because `getPositionUnrealized` reads `pos.current`,
  which `onPrice()`/`onPrices()` move **without any signal a memo could key on**:
  they only `_emit()` when TP1 actually fires, so an ordinary tick moves the
  number and announces nothing. A risk read answering with a price from a minute
  ago is a worse failure than a slow one. `test/statekeep.test.js` pins this
  behaviourally (a price move must land on the very next read) *and* pins the
  comment that says so, because the comment is what stands between the next
  reader and re-introducing the memo.
- **Bit-identical, not merely close.** A risk figure that drifts in the last cent
  is a support ticket nobody can reproduce. The accumulator preserves the exact
  key order the old `reduce` summed in and still rounds once at the end.
- **The hoist made the calls strictly FEWER, never more.** The old
  `atBE || this.getPositionOpenRisk(p) <= 0` short-circuited, so a break-even
  position skipped its second call; hoisting means one call per position instead
  of one *or* two. A test pins the direction with a fixture that deliberately
  contains a break-even row — without one the property is vacuous.
- **The item's "called from bot.js:828 (1s)" is FALSE.** The only 1-second
  interval is `startClocks`'s `tick`, which touches nothing on this engine. The
  real cadence is 30s plus every mutation. The cost per read was real; the
  frequency in the item was not, and the comment in the source now says so, so
  nobody re-derives the urgency from the item.
- **The comment above the method named `updatePrice`/`updatePrices` for months.
  Neither has ever existed.** Corrected to `onPrice()`/`onPrices()`. A test now
  asserts every method the comment cites in backticks is a real method on
  `RiskManager.prototype` — the general form, since the two named regexes beside
  it only catch the instance we already knew about.

### #86 — the layout read is deferred and coalesced, not removed

`ensureActiveVisible` called `getBoundingClientRect()` inside the render path.
The read still has to happen — the strip genuinely needs to know whether the
active chip is off-screen — so it is deferred into a `requestAnimationFrame` and
coalesced behind a `_visRaf` guard: five calls in one frame schedule one frame
and force zero layouts. The reader half was split into `_scrollActiveIntoStrip`,
which has **exactly one caller** on purpose, and a test counts it: a second
caller would be a path that bypasses the coalescing entirely, which is the only
way this regresses.

### #87 — the feed's rows and this session's rows are different things

`bot.js` assigned the status fetch straight onto `LOG` and `JOURNAL` every 30
seconds, so **anything that happened in this browser was erased on the next
refresh** — including the kill-switch confirmation line, which is the one log
entry a person goes looking for to check that the thing they just clicked
actually happened.

- The two halves are now held apart (`FEED_*` / `LOCAL_*`) and composed
  newest-first into the rendered `LOG` / `JOURNAL`. `_ms` maps an unparseable or
  absent timestamp to **0, not NaN**, so undated rows sort to the BACK; NaN would
  make every comparison False and scatter them unpredictably through the list.
  Ties keep the local row first — `concat` puts local first and `Array.prototype
  .sort` is stable, which is spec-required since ES2019 and not an accident of V8.
- **They are merged, never deduped**, deliberately: a locally-closed trade and
  its feed twin are the same trade seen from two sides and will differ in their
  fields, so a dedupe would have to pick a winner and would sometimes pick the
  staler one. The duplicate is visible and self-correcting on the next scan; a
  wrong single row is neither.
- **A failed fetch clears `FEED_LOG` and re-renders the merge** rather than
  blanking the panel, so an outage costs you the server's lines and keeps your
  own. The item called `LOG`/`JOURNAL` "globals" — they are module-scoped `let`s
  inside the page IIFE. The defect was real; the word was not.

### #88 — the `.catch` was catching the wrong thing

`horizon.js` and `regime.js` chained `.then(mount)` **before** `.catch(...)`, so
the catch that exists to handle *"the JSON is not there yet"* was also swallowing
every fault thrown by the renderers inside `mount` — and its handler hides both
hosts. A renderer bug therefore made the surface silently vanish, which is
indistinguishable from the market simply never having run, and it is the failure
mode that keeps a broken panel invisible for weeks.

- **The catch is now scoped to the fetch and the parse only**, with `mount` after
  it. A test asserts the ordering by index and that `.then(mount)` no longer
  precedes it.
- **A renderer fault is REPORTED, not disguised**: `draw()` wraps each surface so
  a throwing strip cannot stop a panel that rendered fine, and `report()`
  re-raises asynchronously via `setTimeout(() => { throw err; }, 0)` rather than
  `console.error`. The async re-raise reaches `window.onerror` and the telemetry
  behind it; a `console.error` reaches a devtools panel nobody has open.
- **`DATA` is module-scoped and `render()` reads it, so the market switch redraws
  from the CURRENT payload.** The item's claim that the buttons get re-bound over
  a stale snapshot is wrong twice over — `mount` binds once behind a `BOUND`
  flag, and the buttons are static HTML — but the stale-snapshot risk it was
  pointing at is real and this is what closes it. `host.hidden = false` was
  already present in all four renderers.
- Both files are covered by **the same parameterised suite**, so the two surfaces
  cannot diverge silently — which is the actual risk with a file pair this close.

**RETRACTED, and must not be re-propagated: "sectors.html has no market
switcher" is NOT a defect.** `renderPanel` columns every market via
`Object.keys(MARKETS)` and never calls `activeMarket()` — the panel is
market-independent by construction. Do not "fix" it by adding a switcher.

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

### Two smaller findings shipped in the same batch

Both are about a number that was right but had **nothing on it saying what it
meant** — the failure mode that survives review because the value looks fine.

- **The backtest's dollar column had no stated basis.** `_sizing_basis()` now
  travels with both `params` call sites in `scanner/vivek_backtest.py`
  (`equity`, `position_notional`, `sizing_mode`), and `build_report` carries a
  caveat naming it and pointing readers at `total_r`. Not a wrong number — a
  right number with no regime attached, which **after the 2026-07-28 resize is
  the difference between two incomparable series** being read as one track
  record. `tests/test_backtest_truth.py` 24 → 31.
- **`dollarsPerPoint` provenance is now recorded** in `public/js/risk_manager.js`
  — `"feed"` / `spec:<symbol>` / `"fallback"` — with a warn log and
  `getUnpricedPositions()`. **The arithmetic is byte-for-byte unchanged**, and
  that is the point: a bare ASX ticker has no `STOCK.AX` class, falls back to
  `1`, and is ~43% overstated at 0.6969. That is the front-end twin of #61's
  live half and it is **position sizing**, so it is FLAGGED FOR VIV, not fixed.
  Latent today only because `vivek_bot_book.json` holds zero positions — it
  becomes real the moment one is opened. `test/risk_manager.test.js` 54 → 65
  (suite 9, with a `captureLog` helper); `bot.html` bumped `risk_manager.js?v=9`
  → `?v=10` per the asset-version rule.

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
   "fix" it back to zero, and do not log per-request there either.
2. **Auth on /api/close, /api/scan, /api/journal is a Cloudflare Access
   decision, not a secret** — all three are called from BROWSER JS (app.js
   SCAN button, stalled.js batch close, gbs-sync), so a tick.js-style shared
   secret would ship in page source and protect nothing. /api/journal also
   has one CI-side reader (`confluence_alert.py` with GBS_SYNC_CODE) that an
   Access policy would break without a service token. The Access write-up
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

## TURTLE — the fourth lens (2026-08-21)

The 1983 Dennis/Eckhardt breakout system, on its own tab at `/turtle.html`.
Owner asked for "a separate set of RULES on a separate TAB", and *separate* is
the load-bearing word: this lens is outside the confluence machinery, outside
the paper book, and outside every signal path in the repo. `scanner/turtle.py`
(engine) + `turtle_run.py` (runner) + `turtle.yml` (nightly) +
`public/{turtle.html,js/turtle.js,css/turtle.css}`.

1. **IT IS BUILT FROM THE ORIGINAL RULES, NOT THE POPULAR SHORT VERSION, AND
   THE DIFFERENCE IS TWO RULES.** (a) **The System 1 filter**: a 20-day
   breakout is SKIPPED when the previous breakout in that market would have
   been a winner — where "loser" means *price moved 2N against it before a
   profitable 10-day exit*, so a trade that drifted out slightly below entry
   without ever going 2N offside counts as a WINNER and blocks the next entry.
   It counts every breakout the market printed, taken or skipped, and it is
   **direction-agnostic** (a losing short enables the next long): one
   chronological chain per market. (b) **The 55-day failsafe**: System 2 is
   never filtered, so a blocked System 1 signal is picked up at 55 days.
   Both are pinned by named tests. Dropping (a) turns System 1 into a plain
   Donchian channel that takes every whipsaw in a range.
2. **The engine is a deterministic REPLAY, and it has to be.** The filter is a
   function of the market's own breakout history, so "is today's 20-day
   breakout takeable" cannot be answered without walking the bars that precede
   it. A `_Shadow` runs beside the real position taking every 20-day breakout
   to keep that memory. Having paid for the walk, the replay also yields each
   name's own record under these rules, which is what the SIGNALS rows show.
3. **`indicators.atr(df, 20)` IS N.** The rules' `N = (19*PDN + TR)/20` is
   Wilder smoothing at period 20, which is exactly what that function computes,
   so `compute_n` calls it rather than re-typing the recurrence. Do not "fix"
   it to a rolling mean: N sets the size, the stop AND the pyramid spacing, so
   the two smoothings diverge three times over. (Also 20 periods, not 14.)
4. **A full four-unit position risks 5% of the account, not 2%, 4% or 8%** —
   entries at 0/+½N/+1N/+3⁄2N, one shared stop ½N BELOW the breakout, so the
   units lose ½N+1N+1½N+2N = 5N. Left on their own 2N stops it would be 8N.
   That halving is the entire purpose of the ½N stop raise. Pinned in BOTH
   `tests/test_turtle.py` and `test/turtle.test.js` because the page PRINTS
   the figure, and 2% and 4% are both plausible-looking wrong answers (a
   research pass produced the 4% one).
5. **Channels are `.shift(1)`.** A 20-day high that includes today's own high
   can never be exceeded by it. Entry tests are strictly `>`, so a flat band
   never breaks out; `>=` would fire every day in a dead range. Both pinned.
6. **Fences, test-enforced**: nothing under `scanner/broker/` may mention
   turtle; `turtle_run` has exactly one `write_json` and may not name the book,
   the bot rules, `sector_map` or `journal/`; no TURTLE_ constant may reach
   `bot_rules.json`; `turtle.js` fetches `data/` only, writes no storage, and
   reads no other lens's file. The freeze is untouched by construction.
7. **The page is four views and THREE OF THEM NEED NO DATA** — RULES, SIZING
   and EVIDENCE render from constants and from what you type, because a rules
   reference that goes blank on a failed fetch is not a reference. Only
   SIGNALS needs the scan file and it says so when absent.
8. **`turtle.js` carries a hand-typed mirror of the config constants** as its
   offline fallback — the risk_manager.js `PUBLISHED_DEFAULTS` shape that
   drifted for months (TOP100 #34). `test/turtle.test.js` parses the real
   `config.py` and fails on any mismatch, plus asserts every `P.<key>` the
   renderers read exists in the mirror. A published `params` block always wins
   over it, key by key.
9. **The EVIDENCE view exists because the ask was "5k to 10M".** It states the
   arithmetic (2,000x = 7.60 natural logs; ~12.9 years at the Turtles' reported
   80%, ~29 at a very good 30%) and the part usually left out: Dennis was down
   ~55% by April 1988 and shut the program; 30-50% drawdowns were routine;
   blended S1+S2 testing showed a worst case nearer -80% than -50%; the ~80%
   average is survivorship-biased. And the structural gap — **the Turtles
   traded ~20 uncorrelated futures with margin, this scans equities and
   crypto**. Diversification is the mechanism that makes the expectancy
   positive, not a garnish, so a Turtle system on correlated single names is a
   materially different and worse strategy. Say this; do not soften it.
10. **The correlation limits (4/6/10/12) are STATED, NOT ENFORCED.** There is
    no correlation matrix in this repo and sector is a poor proxy. Enforcing
    them would be inventing a rule the data cannot support.
11. **Ranking never sorts on the record** — signal today, then open position,
    then proximity, then liquidity. Sorting a scanner by its own backtest is
    how a page becomes a curve fit; `rank_key` is pinned against it.
12. **`#tt-views` scrolls its own overflow.** The shared `.view-tabs` has no
    overflow rule and four labels measure 383px, which pushed the whole page
    sideways at 320px — found by RENDERING it, not by reading it. Scoped by
    id so the fix cannot touch another page. `turtle.html` is now in
    `smoke.e2e.js`'s 320px list.
13. **Both suites are mutation-verified: 15 mutations, 15 caught** (47 pytest,
    53 JS). Two SURVIVED on the first pass and the fixes are worth knowing,
    because both gaps are the kind that re-open easily. (a) *The pyramid used
    entry-N* — every fixture in the file pins N at exactly 2.0, so entry-N and
    current-N are the same number there and the mutation was invisible; the
    test now uses a frame where N DECAYS after entry (2.0 -> 1.38) and asserts
    on the REALIZED second fill. A first attempt asserted on `next_add`, which
    is computed in the output block from `pos["n"]` and is therefore untouched
    by a mutation to the add loop — assert on a fill, not on a projection.
    (b) *`esc()` was tested but never asserted to be CALLED*, so deleting it
    from the row name left everything green while `name` is the one field a
    third-party listings directory controls. There is now a test that walks
    every untrusted field to its render site.
14. **Two defects were found by RENDERING, not by reading**, both in code that
    read fine: a click anywhere inside an expanded row collapsed it (so you
    could not select a number out of the pyramid table, and the `is-open`
    cursor was already promising otherwise), and the keyboard handler built a
    `querySelector` out of `row.dataset.sym` — which is the DECODED symbol, so
    a name carrying a quote made the selector invalid and threw. Real tickers
    never contain one; a hostile fixture does. Rows now carry
    `tabindex`/`role`/`aria-expanded` like the main deck's, and the
    replacement node is found by comparing dataset rather than by building a
    selector.

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
   - **RETIRED 2026-08-13 — do not reinstate.** This rule used to end
     *"`journal/alert_state.json` gets polluted by local test runs —
     `git checkout -- journal/alert_state.json`, never commit it."* That
     stopped being true at `22ddb448c` (2026-08-07), which redirected pytest
     off the live alert/circuit-breaker state entirely; a full pytest run now
     leaves `journal/` byte-clean, verified by `git status` at head. The rule
     is recorded rather than deleted because a habit of blind-checkout-ing a
     state file is worth un-learning explicitly: with the write fixed, that
     `git checkout` now only ever discards a REAL alert-state change written
     by something that meant it.
2. **Version bump:** every edit to ANY `public/js/*.js` or `public/css/*.css`
   bumps its `?v=` in every referencing HTML page. Don't record the numbers
   in docs — read them from the HTML.
3. **Config first:** any new threshold/constant goes in `scanner/config.py`
   (or `phasemap/config.py`) before use. Bot rule constants are published to
   `public/data/bot_rules.json` each scan — the dashboard reads them; never
   hardcode the numbers twice (bot.js warns on drift).
4. **PhaseMap spec is law** (see above). Schema note: published
   `latest.json` is SLIM (narrations in `narrations.json` sidecar); the
   dated snapshot keeps the full spec schema.
5. **Tests gate everything:** `python -m pytest -q` (+ `node test/*.test.js`)
   must be green; CI runs them on every push.
6. **Pinned deps:** `requirements.txt` pins the trade-path packages exactly.
   Bump deliberately (edit pin → pytest → push), never loosen to `>=`.
7. **Atomic writes** for any journal/state JSON (temp + `os.replace`).
8. **Push to `main`** — Cloudflare Pages deploys it; feature branches don't.
9. **ASCII-only prints** in scanner code — Windows consoles are cp1252 and
   choke on arrows/em-dashes.
10. **CF Functions** are Workers runtime: no Node builtins; KV binding
    `JOURNAL_KV` backs sync + the scan/close rate limits.

## Frontend rules

- iOS-style dark theme: tokens in `styles.css :root` (system-blue/green/red,
  radius 18/14/10, soft shadows, frosted top bar). Old terminal values are
  documented in the :root comment for revert.
- One timestamp convention: **Melbourne on screen**, market-local/UTC in
  tooltips (`PM.fmtMelb`).
- Preview: launch config "fib-scanner" (port 8765). `preview_screenshot`
  TIMES OUT on canvas-heavy pages (chart) — verify via `preview_eval` DOM
  checks instead.
- PWA: `sw.js` (network-first for `data/` + HTML, cache-first for `?v=`
  assets; never caches `/api/`). Bump its `CACHE` name on breaking changes.

---

## Secrets

Set: `DISCORD_WEBHOOK_URL` (private #alerts, triples-only via
`DISCORD_CONF_MIN_LENSES`), `BYBIT_*` (testnet), `ALPACA_*` (legacy),
`TELEGRAM_*`, `GH_DISPATCH_TOKEN` (in Cloudflare, not GitHub).
**Pending owner:** `GBS_SYNC_CODE` (activates watchlist-aware pings),
data-provider key, Cloudflare Access.

---

## Running locally

```bash
pip install -r requirements.txt
python -m pytest -q                      # full gate (1255 tests / 58 files, 2026-07-30)
node test/risk_manager.test.js           # + 15 more JS suites, 650 total; see test.yml
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
