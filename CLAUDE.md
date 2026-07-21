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

**The three lenses** (see ROADMAP.md for the honest project state):

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
  broker/              vivek_bot.py (decision engine: A+ only, 10/market,
                       one/symbol, short-slot reserve), vivek_run.py (paper book),
                       bybit_client/bybit_bracket/bybit_reconcile, kill_switch,
                       circuit_breaker, pre_trade_check, ...
phasemap/              PhaseMap package (engine/narrate/output/backtest/tests)
public/                the site (see "Frontend rules")
functions/api/         scan.js + close.js (Actions dispatch, KV rate-limited),
                       journal.js (KV sync store), price/quote/tick proxies
tests/ + phasemap/tests/ + test/*.test.js   ~290 tests — run on EVERY push (test.yml)
journal/               bot book + state files committed by Actions
data_universe/         bundled ticker CSVs (fallbacks)
```

## Workflows (current)

| Workflow | Schedule | Does |
|---|---|---|
| test.yml | every push/PR | pytest + JS tests + syntax gate |
| scan.yml | market-hours crons, SEQUENTIAL markets (weekend = crypto-only) | VIVEK scans + bot book + confluence alert |
| crypto_bot.yml | hourly 24/7 | crypto scan + crypto slice of the bot book |
| confluence.yml | daily 08:45 UTC | post-nightly confluence ping (scan group SOLELY owns the dedupe state) |
| backup_book.yml | daily 21:35 UTC | snapshots the bot book + journal state into `backups/` (keep 30) + uploads the set as a 90-day run artifact (off-tree copy, 2026-07-21) |
| phasemap.yml | nightly 08:30 UTC | PhaseMap + Specs + schema gate (SLIM latest.json + narrations sidecar); no confluence here |
| lens_backtest.yml | weekly Sun | PhaseMap/Specs/VIVEK replays → owns `public/data/vivek_backtest.json` (Insights reads it) |
| vivek_backtest.yml | monthly 1st | LONG-ONLY evidence → `vivek_backtest_longonly.json` ONLY |
| kill_switch.yml | half-hourly 24/7 | loss check on the BOT BOOK per market, open positions re-priced with LIVE quotes (fallback: last-scan marks); broker flatten only if keys set. Hosts the freshness watchdog (scanner/watchdog.py) |
| stop_watcher.yml | 5-min 24/7 | curls /api/tick (cloud watcher for the KV manual journal) |
| close_position.yml | manual | journal_type=bot closes a BOT BOOK position (the real track record); swing/scalp = legacy journals |
| test_alerts.yml | manual | alert-path self-test: forces one test message through every configured channel (`watchdog --test-alert`); run after any alert-secret change, read the job summary |

(Table refreshed 2026-07-20 — discord_digest.yml deleted; notify/alerts/pulse/
paper_run/bracket_order/reconcile modules deleted.)

**Silent-failure protection (2026-07-20, Phase 5):** the committing workflows
(scan/crypto_bot/phasemap/backup_book) run `scripts/assert_staged.sh` after
staging — a scheduled run that stages none of its must-change outputs FAILS
loudly instead of finishing green (the Phase 3 staging bug ran green 5x while
committing nothing). `scanner/watchdog.py` (hosted in kill_switch.yml +
crypto_bot.yml) additionally probes content timestamps + GitHub run history
and alerts on staleness with strict noise rules (first / 6h reminder /
recovery; red runs are GitHub's to email about). Thresholds: config
WATCHDOG_*. When adding a workflow that commits data, give it an
assert_staged call and a WATCHDOG_RUNS entry.

---

## Journals & track record — IMPORTANT

- **The bot book is the ONE AND ONLY track record.** Layout v2 (2026-07-20):
  CANONICAL per-market files `journal/vivek_bot_book.<market>.json` (a market's
  run can only write its own file — cross-market clobber impossible by
  construction); `journal/vivek_bot_book.json` + the public twin are a DERIVED
  combined view (same old schema; regenerate with
  `python -m scanner.broker.vivek_run --rebuild-combined`; audit with
  `--verify` — the scan/close workflows run it as a failing gate). A+ only (grade_raw,
  unsmoothed), max 10/market, one per symbol, daily+weekly loss guards, manual
  close via close_position.yml journal_type=bot.
- The old "track-record journal" (every armed A+/A, every timeframe, no cap —
  it hit 203 open / 12 closed) was **retired 2026-07-09** along with the
  dashboard strip and TRACK page. Do not resurrect it as a headline number.
- Manual journals ("Me" side) live in browser localStorage, synced via
  Cloudflare KV (`gbs-sync.js`, `/api/journal?code=...`). The unified
  watchlist (stars from all lenses) lives INSIDE that store
  (`watchlists`, keys `<lens>:<market>:<TICKER>`, tombstoned un-stars).

---

## Development rules

1. **Git first, always:** other sessions + CI push constantly. Before ANY
   commit: `git stash -q -u; git pull -q --rebase origin main; git stash pop -q`.
   `journal/alert_state.json` gets polluted by local test runs —
   `git checkout -- journal/alert_state.json`, never commit it.
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
python -m pytest -q                      # full gate (~290 tests)
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
