# Vivek 5.0 — CLAUDE.md

Read at the start of every session; read it fully before touching code. This
is the OPERATING MANUAL: what is true now, the rules that bind, and the owner
rulings that are settled. The long-form record — every incident, measurement
and design argument behind these rules — is `docs/claude-history.md`
(rewritten 2026-10-14, REFINE200 #98; the 2,763-line predecessor sits whole at
its end). Before "fixing" anything pinned below, read its section there.

---

## What this project is

A **multi-lens trading scanner** plus Claude's **paper-trade bot book**. Owner:
Vivek ("Viv", Melbourne). Brand everywhere: **Vivek 5.0** — never "Googy Boys
Scanner", never "Vivek's Beta Scanner" as the primary name ("BETA SCANNER" as a
subtitle under the wordmark is fine). **Personal use only** (2026-09-28): no
disclaimers anywhere (the Discord digest included), no business goal, no
compliance or "reads like advice" flags. **PAPER ONLY**: `bybit_client.py` /
`alpaca_client.py` survive only as the kill switch's flatten path; no keys set.

**Lenses in confluence** (direction-aligned 2+/3 agreements → banners, the
ALERTS log, the deck's ⨂ Multi-lens pill and row chips — all carrying
`PM.CONFLUENCE_UNPROVEN`, an evidence note, not a disclaimer: no edge found):

1. **VIVEK** (`scanner/vivek.py` + `scan.py`) — price reacting at its 200-SMA on
   Weekly / 3-Day / Daily levels (4H plans are display only). Grades
   A+/A/B+/WATCH; plans with entry/SL/TP1-3; entry types reclaim/retest/break;
   armed vs watching. The bot trades it.
2. **PhaseMap** (`phasemap/`) — liquidity sweep → displacement; zones are always
   bands. The owner's master spec is law.
3. **Specs** (`scanner/spec.py`, `spec_run.py`) — sub-$0.50 base breakouts on a
   ≥3× volume spike (ASX + NASDAQ). A shortlist generator, NOT an entry system.

**Report-only, outside confluence and every signal path (test-fenced):**
**MOMENTUM** (`scanner/momentum/`) — a 20/50/200-EMA + RSI-divergence screen
per market after its close; **IGNITION** (`scanner/ignition/`) — coil →
breakout on crypto, ASX and NASDAQ.

---

## Owner rulings — settled; do not re-litigate or re-propose

- **Personal use, no disclaimers, the brand rule** (above). **PAPER ONLY.**
- **PhaseMap spec is law**: never change detection maths or zone definitions
  without asking him; bump `RULESET_VERSION` (`phasemap/config.py`) on ANY
  detection-parameter change; deterministic, no LLM in any scan path.
- **Long only.** Shorts were shown to him with the numbers and declined
  (2026-09-21, "Yeah lets not do shorts").
- **Wide stops already taken keep full size** (2026-07-28). Never run
  `resize_book_notional.py --max-stop-pct`; never re-raise the trim. The rows
  booked over 25% at the fill (CVLT, SMCI, BNB) are managed as taken — never
  closed to "fix" the gate (it binds new entries only).
- **Crypto liquidity floor stays $3M** on single-venue volume ("Keep",
  2026-09-28).
- **Sizing: $2,500 × 60 open, 6 per sector PER MARKET** (2026-09-27), in each
  market's own currency (A$ on the ASX; KEPT 2026-07-29).
- **No hand closes from 2026-10-14** ("I'm no longer going to close anything by
  hand"): hc4-1 is the first clean test of the rules alone. No rule changes
  mid-cycle; trade-affecting proposals go in `docs/DECISIONS_2026-10-14.md` and
  land together as cycle hc4-2. Which trades get taken is always his call.
- **Removed features stay removed** (write-ups in `docs/claude-history.md`):
  the Discord ALERT router (2026-08-27); the AI BOT page + scalp-era Bybit
  execution and risk stack (2026-09-17); TURTLE (2026-09-17); HORIZON + REGIME
  (2026-09-20); the MY JOURNAL "Me" side, stars, KV journal sync, `/api/tick`,
  `stop_watcher.yml` (2026-09-21); the NEWS page's ELI5 box, biggest-volume
  list, indices cards and TradingView widget (2026-09-27; `sectors.html`
  stays); WHAT NEEDS MY EYES (2026-10-09); the Reversals/Fib engine (REFINE200);
  the 2026-07-09 "track-record journal" (every armed A+/A, uncapped) as a
  headline number.
- **Discord carries only the morning-plays digest**, on its own secret
  `DISCORD_MORNING_WEBHOOK_URL`. The removed alert webhook's secret name must
  never appear in a workflow, even in a comment (`tests/test_alert_credentials.py`).
- **`TELEGRAM_ENABLED` stays False** — the owner's scalp-era mute.
- **No SHA-pinning of the five first-party actions** (TOP100 #56); third-party
  actions must be 40-hex pinned; nothing floats on `@main`/`@latest`.
- **Reliability without paying** (2026-10-06): free cron-job.org jobs are the
  real clock. **The ASX close is 16:40 Sydney** ("Fix it properly").
- **Crypto prices come from exchange klines** (2026-09-28).
- **HIGH CONVICTION = the four cells** (2026-09-20, "Drop it" to the structure
  branch), one 🎯 per cell; the bot trades them at A/A+ (2026-09-21).
- **Review flags inform, never gate.**
- **Findings, not bugs — do not "fix"**: grade hysteresis never demoting an
  oscillating A+/A (TOP100 #70: each 8 re-earns A+); caching a blank sector
  (#65); the SUN/AFG sector-label divergence (owner decision).
- **Open owner decisions** (do not decide them): data provider (EODHD/Norgate),
  Cloudflare Access on `/api/close` + `/api/scan`, an alert channel (SMTP),
  yfinance 1.4.1 → 1.7.0, widening Ignition NASDAQ past Global Select, every
  OWNER item in the decision pack.

## Project rules

1. **Git first, always:** other sessions + CI push constantly. Before ANY
   commit: `git stash -q -u; git pull -q --rebase origin main; git stash pop -q`.
   A full pytest run leaves `journal/` byte-clean, so a diff in
   `journal/alert_state.json` after tests is a real alert-state change —
   never discard it with `git checkout`.
2. **Version bump:** every edit to ANY `public/js/*.js` or `public/css/*.css`
   bumps its `?v=` in every referencing HTML page (assets are cached immutable
   for a year — a missed bump pins the old file). Read numbers from the HTML.
3. **Config first:** every threshold lives in `scanner/config.py` (or
   `phasemap/config.py`) before use. Bot rules publish to
   `public/data/bot_rules.json` each scan; JS mirrors of config are
   parity-pinned (`tests/test_js_config_mirrors.py`) — never type a number twice.
4. **PhaseMap spec is law.** Published `latest.json` is SLIM and compact
   (narrations in the `narrations.json` sidecar); dated snapshots keep the full
   spec schema.
5. **Tests gate everything:** pytest + every `node test/*.test.js` green; CI
   runs them on every push.
6. **Pinned deps:** `requirements.txt` (production) pins the trade path exactly;
   `requirements-dev.txt` adds test tooling. Bump deliberately, never `>=`.
7. **Atomic writes** for journal/state/published JSON (temp + `os.replace`;
   publish through `output.write_json`).
8. **The owner says what to do; Claude ships it** (2026-09-28). Branch, open a
   PR, and once checks are green merge with **Rebase and merge** — never
   squash, never a merge commit (the owner's `SHIP.bat` convention). No need
   to ask before merging. Production deploys only from `main`.
9. **ASCII-only prints/logs** in scanner code (cp1252 consoles; test-guarded).
10. **CF Functions are the Workers runtime**: no Node builtins, env via
    `context.env`. KV `JOURNAL_KV` backs the scan/close/morning-plays limiters
    and the access log (the name is historical).

---

## Tech stack and layout

| Layer | What |
|---|---|
| Engines | Python 3.12 (`scanner/`, `phasemap/`) in GitHub Actions |
| Site | Vanilla JS + CSS on **Cloudflare Pages** (`public/`, no build step), iOS-style dark theme, PWA |
| API | Pages Functions `functions/api/*.js` (Workers runtime) |
| Clocks | **cron-job.org** (primary, via `/api/heartbeat` + `/api/morning_plays`) + GitHub crons (backups) |
| Data | stocks: `yfinance` (pinned; ~15 min delayed, survivor-biased); crypto: exchange daily klines via `data.fetch`, identity-checked |

```
scanner/            config.py (ALL constants) · vivek.py · scan.py · run.py (CLI, publishes bot_rules.json)
                    data.py + exchange_data.py (the one fetch path) · universe.py · conviction.py
                    confluence_alert.py · vivek_backtest.py + vivek_parity.py · vivek_journal.py
                    (trade primitives + the one close writer) · spec*.py · ignition/ · momentum/
                    watchdog.py · sectorcache.py · marketcaps.py · history_archive.py
scanner/broker/     vivek_bot.py (decisions, RINGFENCED) · vivek_run.py (the paper book) ·
                    vivek_guard.py · kill_switch.py (+ bybit/alpaca flatten) · alert_router/dispatch
phasemap/           PhaseMap package (engine/narrate/output/backtest/tests)
public/             the site; public/data/ = published JSON
functions/api/      scan, close, heartbeat, health, morning_plays, price/quote
journal/            the bot book (canonical per-market files) + state
data/               sector_map.json (a SIGNAL path), edge ledgers, history archive,
                    universe cache, research/ (parity/fill/confluence studies; not on the site)
scripts/            CI-side tools (gates, edge pipeline, ops, digest, resize, decision pack)
tests/ · test/      pytest · JS suites (+ test/e2e Playwright)
docs/               claude-history.md · DECISIONS_2026-10-14.md · REFINE200 ledger ·
                    REPO_SIZE.md · archive/ (dated working notes)
reviews/            dated reviews (tests read some; do not move)
```

**Docs:** `README.md`, `ROADMAP.md` (honest state), `OPERATIONS.md` (runbooks
+ **who triggers what**), `HEALTHCHECK.md` (owner's daily check), `FRONTEND.md`
(site architecture). `docs/archive/` holds TOP100, REFINEMENTS, BATCH100,
PROPOSALS_2026-09-04, the handoffs, the N30 pack and the research ledger;
references like "TOP100 #48", "REFINEMENTS #108" or "P12" are item numbers in
them.

---

## Workflows (26)

| Workflow | Trigger | Does |
|---|---|---|
| `scan.yml` | heartbeat dispatches (cron-job.org) + superset crons; gate `scripts/scan_gate.py` | VIVEK scan of the market(s) in hours + their book slice + confluence alert. Hours = `config.MARKET_SCAN_WINDOWS` (ASX 11:00–16:45 Sydney, NASDAQ 10:30–16:45 NY, weekdays) + a missed closing scan; ≤1 stock market per scheduled run, never crypto; gate crash fails open |
| `crypto_bot.yml` | `:22` hourly every day + `:52` backstop | crypto scan + crypto book slice; hosts the watchdog |
| `kill_switch.yml` | `15,45 * * * *` | job `check`: per-market session-loss check + watchdog; job `watchdog-alarm`: one red run per CRITICAL episode |
| `close_position.yml` | manual | `journal_type=bot` closes (batch ≤ 60); re-dispatches itself (max 3) if the mutex evicts it |
| `resize_book.yml` | push touching `.github/resize-kick`; manual (dry by default) | one-shot open-book restatement + `bot_rules.json`, one commit |
| `confluence.yml` | `workflow_run` after PhaseMap + `45 8` backstop | post-nightly confluence pass (alert log + signed state) |
| `phasemap.yml` | `30 8` UTC (lands hours late) | PhaseMap + Specs + schema gate; healthy markets always land |
| `ignition.yml` · `_asx` · `_nasdaq` | crypto `14 0`, ASX `24 6`, NASDAQ `34 21` + backstops, intraday, a Sunday replay; push `.github/ignition[-asx\|-nasdaq]-kick` | IGNITION screen + chart sidecar (+ replay); structural twins |
| `momentum.yml` | `30 6`, `30 21` Mon–Fri, `30 0`, `41 */3`, after each morning_plays run | MOMENTUM, the newest market due |
| `morning_plays.yml` | cron-job.org ladders via `/api/morning_plays`; backstops `58 5,6`, `50 7,8`, `50 21,22` Mon–Fri | HIGH CONVICTION digest to Discord |
| `alert_returns.yml` | `20 22` + `50 23` backstop | the edge pipeline |
| `evidence_brief.yml` | `0 21` | read-only brief → step summary |
| `reco_note.yml` | `52 8` | auto `reco_note.json` (never over a same-day hand note) |
| `backup_book.yml` | `35 21` + `35 23` backstop | `backups/<stamp>/` (keep 30) + 90-day artifact |
| `lens_backtest.yml` | Sunday `0 8` | replays → `vivek_backtest.json` |
| `vivek_backtest.yml` | 1st `0 8` | `vivek_backtest_longonly.json` |
| `decision_replay.yml` | push `.github/replay-kick`; manual | READ-ONLY parity replay + V1–V8 → summary + artifact; red if `public/data` moved |
| `dispatch_scan.yml` | push `.github/scan-kick` | a real `scan.yml` dispatch — how a cloud session triggers a scan |
| `ops.yml` | manual | cron-job.org + Cloudflare actions |
| `test.yml` · `test_alerts.yml` | push (path-filtered)/PR · manual | the CI gate · alert-path self-test |
| `commit_sentinel.yml` | every push to main | unknown pushers/identities, force-pushes; detection only |
| `crypto_source_check.yml` · `data_depth.yml` | manual (+ `.github/crypto-source-kick`) | read-only venue check + dry crypto scan · history-depth probe |

Exact crons, backstops and what a missed run looks like: `OPERATIONS.md` →
"Who triggers what".

### Scheduling — the real clock is cron-job.org

GitHub's free scheduler runs crons late or not at all (week to 5 Oct: 5/35 ASX,
8/35 NASDAQ, 41/~168 crypto), so free cron-job.org jobs ping the site (each in
its market's timezone, DST-proof) and GitHub's crons are backups. Manage with
`ops.yml cronjob-*`.

| Job id | Schedule | Hits |
|---|---|---|
| 8587588 | ASX hourly, :10 11–16 Sydney, weekdays | `/api/heartbeat?market=asx&stale_min=…` |
| 8587590 | `scan ASX close (Sydney)` 16:40, weekdays | `…market=asx&stale_min=15` — the on-time closing scan |
| 8587683 | `scan ASX close probe (Sydney)` 17:20, weekdays | `…market=asx&stale_min=40` — heals only if no scan stamped ≥16:40 |
| 8587599 | crypto :22 hourly UTC, daily | `…market=crypto&stale_min=45` |
| 8587591 | NASDAQ open 10:40 New York, weekdays | `…market=nasdaq…` |
| 8587598 | NASDAQ hourly :10 11–16 New York, weekdays | `…market=nasdaq…` |
| 8424425 | `slot=asx (post-close ladder, UTC)` every 30 min 06:15–10:45 UTC Mon–Fri | `/api/morning_plays?slot=asx&key=…` |
| 8424432 | `slot=us` every 30 min 20:15–23:45 UTC Mon–Fri | `/api/morning_plays?slot=us&key=…` |

### CI and workflow rules (each test-pinned)

- **The `scan` mutex serialises book writers and is JOB-scoped** (`scan`,
  `crypto`, `close`, `resize` jobs; `confluence.yml` is the one WORKFLOW-level
  member). Never move it up: GitHub keeps one pending run per group, so
  workflow scope let gate jobs evict each other (`tests/test_workflow_mutex.py`).
- **Writer jobs check out the branch TIP** (`ref: ${{ github.ref }}`; resize
  `ref: main`) — a queued job otherwise replays a stale book over newer writes.
  A commit renaming an output path keeps the old path written for one cycle.
- **Must-change gate:** every committing workflow runs
  `scripts/assert_staged.sh` after staging (ANY-OF: list canonical files, never
  only a derived view): scan, crypto_bot, phasemap, backup_book, reco_note,
  alert_returns, momentum, the ignition twins (per path), close_position
  (`journal_type=bot`), resize_book (behind `--check` exit 3). `confluence.yml`
  gates on an unstaged tree instead (pinned decision). A new committing
  workflow also needs a `WATCHDOG_RUNS` entry unless pinned otherwise
  (momentum, ignition, read-only workflows).
- **`git add a b` is all-or-nothing and banned** — one pathspec per call;
  `|| true` only beside assert_staged. A bot close that stages nothing fails.
- **Market-hours crons fire a SUPERSET; the in-job gate decides** in the
  market's own calendar. `bash -e` is on, `pipefail` is not (set it on every
  `| tee`); every `run:` block passes `bash -n`. No CI skip token on a merge
  that must fire a push workflow.
- **Ops: read the log, not the colour.** A failed `ops.yml` action is a GREEN
  run; read `OPS RESULT: OK|FAILED (exit N)`. Actions:
  `cronjob-list/get/history/create/update/delete` (update merges into the live schedule),
  `cf-list-vars/set-var/delete-var/redeploy`, read-only `cf-deployments` and
  `site-probe` (`paths` = up to 10 site GETs). Confirm mutations with a
  read-back; "merged" is not "live". Output is redacted. Pass a credential
  failure (missing secret, 401/403) to the owner yourself.
- **Every job carries `timeout-minutes`** (TOP100 #44): one stuck run in the
  `scan` group silently costs a whole session.
- **Routines can't help** (no MCP connectors, no push token); a cloud session
  triggers work by pushing a kick file.

---

## The bot book — the one and only track record

- **Layout:** canonical `journal/vivek_bot_book.<market>.json` (a market's run
  writes only its own); `journal/vivek_bot_book.json` + the public twin are a
  DERIVED view (`python -m scanner.broker.vivek_run --rebuild-combined`;
  `--verify` is a failing gate in the scan/close workflows). An unreadable book
  aborts the runner. **Never hand-edit rows; never edit a closed row.**
- **What it takes** (cycle `hc4-1`, since 2026-09-21): `grade_raw` A/A+, LONG,
  the first armed complete plan walking `VIVEK_BOT_ENTRY_CELLS` 1W (reclaim,
  break) → 3D (reclaim) → 1D (break), on a row reacting at a weekly/3d level
  (`VIVEK_BOT_LEVEL_TF_ALLOW`). Funds/REITs out (the bot's own ringfenced
  substring matcher). Gates: min price, min ADV and ≤2% of ADV, R:R ≥ 1.5,
  stop 1–25% (re-read at the FILL), NASDAQ earnings buffer 3 days on the
  market's date, 7-day re-entry cooldown, data ≤3 days old; a fill off a reused
  cache frame is skipped and retried. Cells pinned equal to
  `conviction.HC_CELLS` (`tests/test_bot_alignment.py`).
- **Capacity:** 60 open across ALL markets (`VIVEK_BOT_MAX_OPEN_TOTAL`),
  $150,000 notional, one per symbol cross-market, **6 per sector PER MARKET**
  (`sectorcache.global_sector_load` warns when one real sector exceeds it summed
  across markets). Sibling books are read fail-closed. A plan refused at the
  fill releases its slot to the next-ranked row (`VIVEK_BOT_REFILL_PASSES` 2).
- **Sizing:** fixed $2,500 (`VIVEK_BOT_POSITION_NOTIONAL`; 0 = old risk-% path),
  units = notional / entry, market currency. Dollars at risk vary with the stop
  (~$25–$625): position COUNT is the risk dial — never re-clamp `risk_pct` in
  fixed mode. New rows store `risk_usd` at the fill (`risk_usd_basis: "fill"`)
  and `sizing_mode`. Equity ($150,000) only scales guards and leverage.
- **Compare R, not dollars**: $ P&L is not like-for-like across the 2026-07-28
  resize or the SIZING 2 resize commit (restated rows carry `resized_at`);
  split any hc4-1 read there, not at a calendar date.
- **Management:** TP ladder + trail, 28-day time stop, mark-sanity
  (`VIVEK_MARK_SANITY_PCT` 35%/60%; pauses on a suspect mark, alerts on the 2nd
  hit, accepts on the 3rd; only while the market is open). A split accepted by
  mark-sanity is restated (prices ÷ ratio, units × ratio, R unchanged, audited
  in `splits`). MAE/MFE fold every accepted mark and exit fill. Held names with
  a missing/stale frame are refetched first; a mark off a reused cache frame
  older than `VIVEK_BOT_MAX_MARK_AGE_H` (2h) is UNPRICED (`unpriced_runs`).
- **Closes:** one writer (`vivek_journal._close_remaining`) for stop, time stop
  and hand close; new closes drop `unreal_*`/`day_marks`; stops record
  `stop_slip_r`. Hand closes are emergencies only (`close_position.yml`
  `journal_type=bot`, or the journal's collapsed "Emergency close" folds →
  `/api/close`); `swing`/`scalp` edit the retired legacy journals.
  `vivek_run._restamp` is the one writer of `summary` + `guard` after a close.
- **A bot-run crash fails the scan run after publishing.** Broker code reads
  `config.NAME` directly, never `getattr` with a default
  (`tests/test_bot_config_reads.py`).
- **`scanner/broker/vivek_bot.py` is RINGFENCED** (never autonomous): only
  mechanical or monotonically TIGHTENING changes, flagged in the commit.
- **`data/sector_map.json` is a SIGNAL path**: `vivek_run` merges sectors into
  the rows `decide()` sees (blank fields only; scan rows → universe file →
  cache), seeded from the open book. A sector-less row is exempt from the cap,
  so cache edits are trade changes. Crypto uses `crypto-major`/`crypto-alt`.
- **`bot_rules.json`** carries rules AND state (`open_total`, `closed_total`,
  `entry_quality`; `null` = unreadable); unenforced limits sit under
  `not_enforced`. Readers: status.js, journal.js, the deck, the evidence brief.
  Moving the cap or the notional also moves the close ceilings and fallbacks
  (`close.js`, journal.js, `vivek_run.CLOSE_BATCH_MAX`, close_position.yml,
  status.js `FALLBACK_CAP`, system.html) — `tests/test_close_ceiling_parity.py`
  names every one.

**Loss guards** (`vivek_guard.py`): daily 3% / weekly 6% of equity per market
($4,500 / $9,000). P&L is WINDOWED off `day_marks` (each position's mark
carried into the session), so windows telescope to whole-life P&L;
`_stamp_day_ref` runs BEFORE `_mark_sanity` so an overnight gap lands in the
session it gapped into. Closed trades are windowed too. Weekly = 7 calendar
days incl. today. **Fail closed:** an unpriced position is valued at its stop;
an unreadable week is an `unmeasured` breach; NaN-safe. A breach halts NEW
entries; it never liquidates. The status lamp shows it AMBER (the machine
working), not red.

**Kill switch** (`kill_switch.py`, half-hourly): each market's session over the
market-local day via `vivek_guard.session_pnl` (live quote, else `last_mark`);
it does NOT value unpriced rows at the stop; limit 0 = off. A breach flattens
only the broker holding that market (`VIVEK_KILL_SWITCH_BROKERS`; asx is
paper-only; a missing market falls back to Bybit-then-Alpaca with a WARNING).
No keys are set, so it alerts and logs; it never edits the book.

**Review flags.** `review_flags()` runs in `plan_trade` AFTER every rule said
take and only adds a key — **a flag is not a gate**
(`test_a_flagged_plan_is_still_taken_because_a_flag_is_not_a_gate` must never
be "fixed"). Flag when 1R ≥ `VIVEK_BOT_REVIEW_DAILY_LOSS_PCT` (7.5) % of the
daily limit ($337.50 = a 13.5% stop at $2,500; asserted below the ~13.9% the
25% stop cap allows). Ticket → book row → `_notify_reviews` (NOTICE, rate 0,
one message per run, worded as ALREADY TAKEN). Renders on closed rows too; an
absent `review` is not an empty list; restated rows keep `review_before`.

**Resizing** (`scripts/resize_book_notional.py`, run by `resize_book.yml`): a
restatement, not a trade — entry, stop, `risk`, TPs, marks, exits and `_r`
fields frozen and verified; CLOSED rows never touched; sized off
`signal_entry` against `entry - risk` (the ORIGINAL stop) via
`vivek_bot.size_position`; review flags rescaled; dry by default, idempotent;
`--check` exits 0 at target / 3 pending / 4 un-restatable row / 2 refused.

**Cycles and the decision pack.** **w3-1** (2026-08-02 → 2026-09-21, the
weekly/3d gate) ENDED; its n=30 read is a KILL (−0.192R/trade). **hc4-1**
(`VIVEK_BOT_CYCLE_TAG`) is live; the journal's per-cell board reads
`cycle_tag` + `entry_cells` from `bot_rules.json`. `docs/DECISIONS_2026-10-14.md`
holds the OWNER items and a frozen register PR-0..PR-8, pinned to `PREREG` in
`scripts/decision_pack.py` (`tests/test_decision_pack.py`; moving a line means
editing both). Each checkpoint is read ONCE on the day its n-th hc4-1 rules
close lands (+ one second read), never rolling; `python scripts/decision_pack.py`
prints verdicts. Approved changes land together as **hc4-2** (earliest: the
PR-0 read, ~27 Oct). **Rules vs owner:** an absent `exit_reason` is a human
act; `MECHANICAL_EXITS` (app.js, journal.js, status.js) is parity-pinned; the
two records print separately, never pooled; evidence strips stay INERT (no
controls or calls-to-action).

---

## Data and engine truths

- **One fetch entry point:**
  `scanner/data.py::fetch(market, tickers, period, interval, ref_prices)` for
  every caller. Stocks → `download()`; crypto with
  `CRYPTO_DATA_SOURCE = "exchange"` → `exchange_data.py` (keyless; revert = one
  line). Venues from a US runner: `data-api.binance.vision` answers,
  `api.binance.com` 451 / `api.bybit.com` 403, Coinbase answers (no 4h). Probed
  on BTC; a refusing venue is dropped for the run.
- **A ticker is not an identity.** A source's latest close must sit within
  `CRYPTO_IDENTITY_TOL` (0.40) of CoinGecko's price or it is rejected for that
  coin (nothing confirms → left out, never refilled from cache; exchange mode
  has its own cache file). A HELD coin must reproduce its stored `anchor`
  [date, close] within `CRYPTO_ANCHOR_TOL` (0.15) — a real past close, never a
  mark. Bars older than `EXCHANGE_MAX_BAR_AGE_DAYS` (1) skip the venue. On a
  CoinGecko outage coins anchor to their last checked cached close, else are
  REFUSED. Quantised Yahoo crypto series are refused. PhaseMap and Momentum
  crypto stay on Yahoo by scope.
- **Cloudflare cannot reach Binance**: the chart fetches Binance bars/quotes
  from the BROWSER (proxy as fallback; server Binance off unless
  `PRICES_TRY_BINANCE=1`); a fallback series outside the identity band shows
  "price source unavailable".
- **Frame cache:** back-fills dropped tickers up to `FRAME_CACHE_MAX_AGE_DAYS`
  (10), never past (a fossil can fabricate a stop-out); never saves an empty
  dict; a reused frame is a tagged copy whose ORIGINAL `fetched_at` keeps
  ageing (`data.mark_age_h`, unknown = inf). Rows publish a sparse `price_age`.
- **Bar-final:** `config.BAR_FINAL` is the one table (ASX 16:40 Sydney — the
  auction reaches Yahoo ~20 min late; NASDAQ 16:30 New York); the Ignition,
  Momentum/Specs and digest ASX gates derive from it. Exceptions: the ledger's
  ASX 16:45 and the US digest's 16:05. Shared clock `scripts/_marketclock.py`;
  pins `tests/test_bar_final.py`. Frame ages use the market's calendar.
- **NaN discipline:** guard with `not (x > 0)`, never `x <= 0` (#63 — a NaN risk
  passed every gate and disarmed the guards; publish-time scrubbing never
  reached the in-memory rows the bot reads). Publish via `output.write_json`.
  `rsi()` is NaN in warm-up and on halted series. `supertrend` is a numpy loop,
  bit-identical to the old one (not vectorisable) — keep it.
- **`sma_proxy`** marks a plan measured on < 200 bars; reported, never filtered.
- **`is_product`** (`scan.py::_product_tag`): display-only fund/LIC/preferred
  verdict, word-boundary matched (the bot's substring matcher finds "ETF" in
  "NETFLIX"); LIC pattern plural only. `true`/`false` beat the keyword guess,
  absent falls back to it. Fenced both ways (`tests/test_product_flag.py`).
- **HIGH CONVICTION**: `scanner/conviction.py` is the one definition; Python
  readers import it, app.js/chart.js carry it as a JSON literal pinned by
  `tests/test_conviction.py`.
- **Universe:** crypto pages CoinGecko at its 250 cap. The peg rule only ever
  REMOVES names (ticker shapes, an explicit list, name words, a behavioural
  dollar-peg net); gold/silver tokens stay. Re-run `crypto_source_check` after
  a universe change. Failed directory fetches fall back to
  `data/universe_cache/`.
- **The published payload** is `scan.published()`: a COPY with caps/sectors on
  rows — never the rows the bot reads. Caps > 30 days old show their date.

---

## Lenses

**PhaseMap.** `phasemap.run` exits 0 published / 3 carried (no new completed
bar; records re-published with `carried_from`) / 4 refused (coverage <
`PUBLISH_MIN_COVERAGE` 0.5; last good files kept) / 1 failed. `phasemap.yml`'s
scan step never fails; commits gate per market; a bad market turns the run red
after the healthy ones land. Header: `run_date` (Melbourne), `as_of` (newest
completed bar), `fetched`, `carried_from`. Chart files rewrite only on byte
change; 2 dated snapshots kept; `--limit`/`--tickers` write to scratch unless
`--publish`. Publishing knobs live outside `PhaseMapConfig` (no RULESET bump).
The tree must not mention `IGNITION_`. Inverted-looking grades and crypto on
Yahoo are OWNER (spec) items.

**IGNITION** (REPORT-ONLY). COIL: SMA 9/26/43/200 within 12%, ATR% bottom 25%
and 20d volume bottom 35% of a 2-year window, ≥50% under the 3-year high.
TRIGGER (completed bar): coiled in the prior 10 bars, close > the 60-bar base
high, volume ≥ 3× its 20-day average, ≤60% over the 9-SMA, turnover floors.
Stop = max(base low, base high − 1 ATR); exit next open after a close under
the 9-SMA; no TP ladder. States IGNITING → RUNNING → CLOSED (kept 20 bars) and
COILED; `provisional` = the forming bar qualifies. A last-bar trigger prices
off the forming OPEN (at/under the stop = `gap_below_stop`, no trade). Any
threshold change bumps `IGNITION_RULESET_VERSION` (1.0.0). Calendar windows
rescale by `engine.bars()`; every market needs an entry in every
`*_BY_MARKET` dict (gated).

| | crypto | ASX | NASDAQ (Global Select only) |
|---|---|---|---|
| bars/yr · floors base / trigger day | 365 · $1M / $3M | 252 · A$100k / A$300k | 252 · US$1M / US$3M |
| cost RT · data-age ceiling | 0.30% · 3d | 1.0% · 5d | 0.5% · 5d |
| regime · design case (never scored) | BTC · QNT | `^AXJO` · DTR | `^IXIC` · none |
| forward bucket from | 2026-09-28 | 2026-09-29 | 2026-10-08 |
| replay vs random timing | +1.15R, CI −0.06..+2.59, P 0.062 | +0.42R, CI +0.12..+0.73, P 0.009 | +0.06R, P 0.24 — "no edge shown" |

Replay honesty: realised trades only; baseline = random timing on the same name
within ±182 bars, draws filed by their parent trade's date; the statistic is
`versus.random_timing`; the grid is robustness, never a menu; trail-26 is the
pre-registered forward comparison; a Sunday cron per market replays so the
forward bucket fills. Trading it needs the forward bucket to beat random timing
AND the owner's ruling. Fences (`tests/test_ignition_fences.py`, both ways):
nothing in `broker/`, vivek, scan, conviction, confluence, morning_plays or
run.py reaches the lens. NASDAQ bars count as forming until 16:30 New York. A
stale stock tape (> `IGNITION_LAG_RERUN_SHARE` lagging) reruns a backstop and
shows STALE. Mini charts: `<market>_charts.json`, display only, drawn only when
its `generated_at` equals the screen's; a failed sidecar write fails the run;
contract in `scanner/ignition/thumbs.py`. Porting a market: the
`port-ignition` skill.

**MOMENTUM** (REPORT-ONLY): one market per run, the newest due
(`scripts/momentum_due.py`, stdlib): stocks from their bar-final until the next
open, crypto from 00:30 UTC; completed bars only; own group, assert_staged on
its one path, no WATCHDOG entry; shorts labelled from its own replay.

**Specs:** keeps the last good file on an outage (exit 3), skips stale frames,
drops forming bars. Retiring it is an OWNER item.

**Confluence:** `confluence_alert.py` writes the ALERTS log
(`public/data/phasemap/alert_history.json`, a rolling 800-row window) and the
SIGNED push-owed state (`journal/confluence_state.json`; an undelivered
alignment holds a negative count, so a future channel's first run pings what is
still current). Push delivery went with Discord.

---

## Evidence pipeline (`alert_returns.yml`, daily)

`alert_returns.py` (1/5/10/20-session forward returns →
`data/alert_forward_returns.json`) → `edge_rosters.py` (daily A+ roster
baseline: monthly shards `data/edge_rosters/<YYYY-MM>.json`, no cap;
`data/edge_rosters.json` is the summary the backstop reads) → `book_stress.py`
→ `alert_edge_report.py` (step summary, read-only) → `edge_summary.py`
(`public/data/edge_summary.json`, schema 2: per market, excess vs index,
counted exclusions).

- A SIDE LEDGER: the scripts READ `alert_history.json`, never write it; the
  rosters and summary IMPORT the report's maths — never re-type a statistic.
- Returns FREEZE at first measurement and read COMPLETED bars only
  (`ALERT_RETURNS_BAR_FINAL`). New stamps carry `stamped_at`, `base_bar`,
  `price_source`, `bench` (`ALERT_RETURNS_BENCHMARK`). Weekend stock alerts file
  under Monday; crypto prices via `data.fetch`; base bar within 5 days; context
  fields blank-only and frozen. `clean()` drops weekend copies and wrong-token
  crypto rows; `EDGE_SECTOR_ALIASES` is analysis-only.
- The pre-2026-10-05 ASX stamp "contamination" does NOT reproduce (0 of 10,777
  checkable stamps differ) — closed. Open: 67 post-fix stamps reading the 13 Oct
  bar differ; pruning old weekend / wrong-token rows is an OWNER call.
- `evidence_brief.py` (exit 1 = names an issue, still green) prints the w3-1
  verdict, the live cycle's line and the engine's `stale_pinged` stalls.

---

## Alerts, watchdog and the digest

- **Router** (`alert_router.smart_send` → `alert_dispatch`): tables live ONLY
  in config (`ALERT_SEVERITY`, `ALERT_CHANNELS`, `ALERT_RATE_LIMITS`); every key
  needs a literal emitter (`tests/test_alert_blackout.py`). **No channel is
  configured**, so `smart_send` logs "NOBODY WAS TOLD"; the alarms are GitHub's
  red-run emails and run-page annotations. A new channel = a sender in
  `alert_dispatch`, wired in `smart_send`/`watchdog._dispatch`, named in
  `ALERT_CHANNELS`, proven with `test_alerts.yml`.
- **Every credential goes through `config.clean_secret`** (ends stripped of
  BOM/zero-width chars; `_secrets.js cleanSecret()` is the Functions twin).
  Discord 403s Python's default User-Agent: use a named UA.
- **Watchdog** (`scanner/watchdog.py`): content probes + run-history probes
  (`WATCHDOG_RUNS`, judged by each workflow's working `job`; scan.yml
  session-aware). Findings are annotated (`::error::` CRITICAL / `::warning::` /
  `::notice::` recovery; first / 6h / recovery). Never make the watchdog step
  fail (the cache would never save); the `watchdog-alarm` job carries the red.
  The committed `backups/` dir is load-bearing for its `backup_stale` probe.
- **Morning plays** (`scripts/morning_plays.py`): HIGH CONVICTION longs, no
  funds, grouped by market then label, one symbol per line. Slots: ASX after
  its close, NASDAQ + Crypto the next Melbourne morning (`MORNING_PLAYS_SLOTS`
  targets are a FLOOR). A `--slot` run sends only on a POST-CLOSE scan
  (`MORNING_PLAYS_SLOT_GATE`: ASX 16:40, US 16:05 NY) once the owed session has
  ended; a per-day slot marker stops doubles; a 7-day de-dup records only
  DELIVERED names; `--force` touches no state. State is an actions/cache file
  (job read-only). Missing secret = green warning; failed delivery = exit 1.
  `/api/morning_plays` (`MORNING_PLAYS_TRIGGER_SECRET`, fails closed 503/401,
  5-min KV cooldown per slot) is driven by the cron-job.org ladders. Manual
  dispatch: `slot` blank = force-send every market (a test, writes no state);
  `slot=asx|us` = run that slot now AND mark it sent.

---

## Site and Functions

- **`/api/health`** — the ALARM: 200 while the published book is < 4h old
  (`max_h`), else 503; GitHub-independent; `?market=` is a manual probe; its
  `breached:[{market,kind}]` feeds the status lamp.
- **`/api/heartbeat`** — the HEALER: dispatches a scan only when overdue;
  `stale_min` floored per market (`STALE_FLOOR_MIN` asx/nasdaq 15, crypto 45,
  all 90 — check the cron-job.org jobs before raising one); 25-min heal window;
  **30 heals per market per UTC day**; 200 when it heals, 503 only when it
  cannot heal, 400 on an unknown market.
- **`/api/scan`, `/api/close`** — same-origin JSON POST only (415 non-JSON, 403
  cross-site; no Origin/Sec-Fetch-Site = non-browser, allowed to the limits).
  `/api/scan` needs `market` ∈ asx|nasdaq|crypto|all. `/api/close` takes
  `{journal_type:"bot", closes:[...]}`, exit within ±50% of `last_mark`, 60
  closes per UTC day. Limiters refuse 503 on a KV error. The access log keeps
  every 2xx and one refused marker per IP per hour, never bodies. Cloudflare
  Access is the real auth (pending).
- **`/api/price`, `/api/quote`**: one upstream round; never cache an empty
  (→ 502 no-store); bare tickers are stocks.
- **`public/_headers`**: `/js /css /vendor /fonts` immutable for a year;
  replacing Cache-Control needs `! Cache-Control` first. Syntax-check Functions
  with `node --input-type=module --check < f`.
- **Status lamp** (`status.js`): READ-ONLY — GET only to published assets and
  `/api/health` (pinned), no storage writes; it must NEVER call
  `/api/heartbeat` (page views would fire heals). Thresholds are borrowed from
  health.js (4h), heartbeat.js (90m) and `bot_rules.json`, and pinned. Uptime
  is measured in the browser from `funnel_history.json` (two readers only:
  app.js, status.js). Routine stalls don't light it; it mounts in
  `.deck-top-right`, never inside `.nav-pills`.

## Frontend rules

- Tokens in `styles.css :root`. **Text uses the `-ink` tokens**
  (`--blue-ink #4da3ff`, `--red-ink #ff6961`, `--purple-ink #da8fff`) — the base colours fail
  WCAG AA as text; fills/borders/white-on-colour stay on the base tokens
  (`test/contrast.test.js`).
- **Melbourne on screen**, market-local/UTC in tooltips (`PM.fmtMelb`); zone
  labels are the abbreviation at the instant (AEDT/AEST, EDT/EST).
- Chart: daily+ stock bars re-stamped to their EXCHANGE date; intraday stock
  bars on the exchange's clock; 4H plans on UTC 4H bins; MACD/RSI keep one
  point per candle (charts sync by bar index).
- An element `hidden` by default with a class-level `display` needs
  `.x[hidden] { display: none; }` (no global `[hidden]` rule).
- Nav pills hidden ≤680px; every page uses `topbar deck-top`. `nav.js` owns nav,
  footer, `tipPop()` and `window.VivekBook` (the one shared book + rules read on
  a nav page; app.js, recs.js and chart.js keep their own fetches).
- **The journal is the bot book only**; a failed book load says so, never a
  fake empty book. Its STALLED strip lists exactly the rows the engine stamped
  `stale_pinged` (no stall logic of its own).
- **A fetch result is applied only to the market it was started for** (TOP100
  #78/#79 and REFINE200 race guards on the deck, Specs, Momentum, PhaseMap): a
  poll that lands after a market switch is dropped; a cached payload is painted
  with its age, never as live.
- PWA: `sw.js` network-first for `data/` + HTML (keyed by path, `/data/` capped
  at 40), cache-first for `?v=` assets, never `/api/`; bump `CACHE` (now
  `vivek5-v9`) on scheme changes. `public/version.json` is the deploy stamp.
- Preview: launch config "scanner" (`python serve.py 8765 public`); canvas pages
  time out on screenshots — verify by DOM. The `run-googy-boys-scanner` skill
  drives the site headless.

## Tests & CI

- `pip install -r requirements-dev.txt`; CI runs
  `pytest -n auto --dist loadfile -rs --durations=15` (no extra `-q`), pyflakes over tests, `bash -n`
  over workflow `run:` blocks, every JS suite and the e2e job.
  `pytest -m "not slow"` skips replay-heavy tests locally.
- **No test may reach Yahoo or an exchange** (`tests/conftest.py`;
  `tests/test_network_guards.py`). Corpus tests read `tests/fixtures/history/`.
- **A new `test/*.test.js` needs its own `node test/<file>` step** in test.yml
  (gated); new `tests/*.py` need none. Gates carry `if: success() || failure()`.
- **The path filter lists every path a suite reads** (incl. `CLAUDE.md`,
  `.claude/skills/**`, `docs/DECISIONS_*`, `reviews/**`, journal/, data/);
  `public/data/**` stays OUT (~20 scan commits a day), so gate on fixtures — a
  gate reading `public/data/` is a delayed fuse on the next code push.
- **Tests read the SHIPPED artefact**: slice real functions from
  `public/js/*.js` (`new Function(body)()`, one realm; `fnSrc()` lets the parser
  find a function's end). Mutation-verify new pins.
- **Screenshot gate**: clock frozen to the fixtures' `FROZEN_MS`; the key
  digests the fixtures + Playwright version (`screenshot-baselines-v24`); a
  `.clock` sentinel discards (never fails) a foreign baseline; NO
  `restore-keys`; > 2% drift on a deliberate change → bump the key, record it.
- **Lighthouse gate** serves a STAGED root on the fixtures: 1.7 MB transfer,
  CLS 0.5; the live payload is reported, never gated.
- **Reproduce a red e2e job** instead of inferring:
  `git worktree add -f /tmp/ci-repro <sha>`, then
  `PW_CHROMIUM=/opt/pw-browsers/chromium node test/e2e/smoke.e2e.js` (never
  `npx playwright install`). `cmd | tail; echo $?` reports `tail`'s status.

## Secrets

GitHub: `DISCORD_MORNING_WEBHOOK_URL`; `CRONJOB_API_KEY`,
`CLOUDFLARE_API_TOKEN` (Pages: Edit), `CLOUDFLARE_ACCOUNT_ID` (ops.yml only;
set 2026-09-10); `BYBIT_*` (testnet), `ALPACA_*` (legacy), `TELEGRAM_*`
(muted). Cloudflare: `GH_DISPATCH_TOKEN` (repo-scoped PAT; stored as Text —
never print values), `MORNING_PLAYS_TRIGGER_SECRET` (SET; the ladders use it
daily). **Orphaned, safe to delete:** the old Discord alert webhook secret,
`TICK_SECRET`, `GBS_SYNC_CODE`. **Pending owner:** a data-provider key,
Cloudflare Access, an alert channel.

## Running locally

```bash
pip install -r requirements-dev.txt
python -m pytest -n 4 --dist loadfile      # full gate (counts drift; read the run)
for f in test/*.test.js; do node "$f" >/dev/null || echo "FAIL $f"; done
python -m scanner.run --market asx         # VIVEK scan (--limit 40 for a quick slice)
python -m phasemap.run --market asx        # PhaseMap (--limit writes to scratch)
python -m scanner.broker.vivek_run --verify   # book integrity, read-only
python scripts/decision_pack.py            # decision-pack checkpoints, read-only
python serve.py                            # local site on :8765
```

Owner's machine: `C:\dev\googy-boys-scanner` (moved OFF OneDrive after a sync
rollback corrupted the tree — never use a synced folder); `.venv` is 3.14, CI
3.12. The check-in skill (`.claude/skills/vivek5-checkin/`) answers "how's the
scanner?"; its copies of config windows/gates and the cron-job.org ids above
are pinned by `tests/test_vivek5_checkin.py`. A check-in never calls
`/api/heartbeat`, `/api/scan`, `/api/close` or `/api/morning_plays`, never
re-sends the digest, and asks before any mutating ops action.

---

## REFINE200 (2026-10-14)

Owner: *"Give me 200 things worth refining and fixing. Then just go ahead and
do it."* Ledger: `docs/REFINE200_2026-10-14.md`; trade-affecting items are in
the decision pack `docs/DECISIONS_2026-10-14.md`. No trade rule moved.

- **Bot/guards:** slot release on a refused fill, `risk_usd` at the fill, split
  restatement, market-date earnings check, ADV without the forming bar, one
  close writer, stop slippage, direct config reads, a crash fails the run;
  windowed closing day, 7-day week, fail-closed unreadable week, NaN-safety;
  the kill switch measures the guard's window (`trade_pnl` removed).
- **Evidence:** benchmark-excess returns, per-market summary, exclusions,
  monthly roster shards, `stamped_at`, the frozen PR-0..PR-8 register,
  `decision_replay.yml`, honest backtest/parity (causal mask, house fills,
  level gate, one chronological book, cooldown).
- **Data/lenses:** BTC venue probe, quantised-crypto refusal, more pegs out,
  caps on rows; PhaseMap outage floor + carry-forward + per-market outcomes;
  Ignition stale-tape reruns, "no edge shown", weekly replays, trail-26;
  Momentum/Specs on completed bars and BAR_FINAL.
- **Ops/site:** watchdog annotations + alarm job, one bar-final table, ledger
  backups, Python 3.12, `requirements-dev.txt`, xdist, network-refusing tests;
  same-origin endpoints, close price band, healer floors, `_headers`, one book
  read per page, emergency-close folds, the hc4-1 cell board, a capped SW.
- **Docs/repo:** this rewrite; notes → `docs/archive/`; research →
  `data/research/`; orphans and `.bat` launchers deleted; OPERATIONS "Who
  triggers what"; `docs/REPO_SIZE.md`.
- **Owner actions outstanding:** Cloudflare Access (#55), an alert channel
  (#78), the checkpoints, yfinance 1.7.0 (#84), deleting
  `journal/vivek_journal.json` + `data/notified_signals.json` (an agent's
  delete was blocked).
