# Scanner hygiene map — 2026-09-23

Read-only survey before any deletion. Base: origin/main `2c669b7a7`,
`journal/` tree `c484de77`.

## 1. Tree

- **scanner/** (48 py): engines `vivek.py scan.py spec.py conviction.py reversal.py
  grading.py specgrad.py`; `momentum/` (config ema macd pivots gates screen run);
  `broker/` (vivek_bot vivek_run vivek_guard kill_switch alert_* + bybit/alpaca
  flatten clients); support `config data output universe sectors sectorcache
  marketcaps funnelhistory history_archive scanerrors watchdog`; journals
  `journal journal_common vivek_journal scalp_journal`; backtests `vivek_backtest
  vivek_parity spec_backtest`; `confluence_alert`, `run`, `spec_run`, `analysis`.
- **public/*.html** (15): index recommendations phasemap phasemap-insights
  phasemap-legend specs momentum alerts journal sectors system about chart
  404 offline.
- **public/js** (19): app chart journal momentum nav phasemap phasemap-shared
  phasemap-insights specs recs sectors alerts stalled status system-backtest
  eyes-store cache telemetry sw-register.
- **.github/workflows** (20): scan crypto_bot momentum phasemap confluence
  lens_backtest vivek_backtest alert_returns reco_note backup_book
  close_position kill_switch morning_plays evidence_brief commit_sentinel
  data_depth dispatch_scan ops test test_alerts.

## 2. Lenses alive

VIVEK · PhaseMap · Specs · Momentum (report-only). **TURTLE, AI BOT, HORIZON,
REGIME, MY NAMES, the manual journal: gone.** Every remaining textual hit for
them is a comment recording the removal (e.g. nav.js "the TURTLE tab was
REMOVED 2026-09-17", kill_switch.py "removed with the AI BOT page"). Those are
history-as-law and are **kept**. The 45 "horizon" hits are the English word
(return horizons), not the removed surface.

## 3. Nav contract (live)

PRIMARY `SCAN · RECS · PHASEMAP · SPECS ⚡ · MOMENTUM · ALERTS · JOURNAL`;
MORE `NEWS · SYSTEM · HOW IT WORKS`; OFF_TAB `alerts, momentum`
→ TABS = 7 − 2 = **5**, momentum on the MORE sheet. Not touched.

## 4. Workflows → paths they name

scan / crypto_bot → `<m>_vivek.json`, bot books, scan_health · momentum →
`public/data/momentum/<m>.json` · phasemap → PhaseMap + `<m>_spec.json` ·
confluence → alert_history + confluence_state · lens/vivek_backtest →
`vivek_backtest*.json` · alert_returns → edge ledgers + book_stress · reco_note
→ `reco_note.json` · backup_book → `backups/` · close_position → bot books.
Read-only / no commit: commit_sentinel, data_depth, dispatch_scan,
evidence_brief, kill_switch, ops, test_alerts. **All kept** — idle-looking is
not idle; several are crons or manual safety valves.

## 5. Largest files

chart.js 4,597 · app.js 3,791 · journal.js 1,925 · broker/vivek_run.py 1,682 ·
config.py 1,309 · vivek_backtest.py 1,069 · vivek_parity.py 1,049 · vivek.py 793
· broker/vivek_bot.py 738 · momentum/screen.py 679 · scan.py 635 · phasemap.js
587 · watchdog.py 565 · phasemap/engine/setup_engine.py 555 · morning_plays.py 551.
None is split in this pass: each is long because its job is long, and the two
largest (chart.js, app.js) are single-page controllers whose tests slice
functions out by name — moving code would break those slices for no gain.

## 6. Suspect dead — proof

Reference count across public js+html, `test/`, `tests/`, `phasemap/tests/`,
`functions/`, `scripts/`, `scanner/`, workflows and docs, comments stripped:

| symbol | file | refs | verdict |
|---|---|---|---|
| `fmtTurn` | app.js | decl only | **dead** |
| `entryRelTargets` | chart.js | decl only | **dead** |
| `fetchStockQuote` | chart.js | decl only | **dead** |
| `makeLiveBoxDraggable` | chart.js | decl only | **dead** |
| `inBatches` | journal.js | decl only | **dead** |
| `MOM_FIRST_PAINT_BARS` | chart.js | decl only | **dead** — superseded by P1's `MOM_VIEW_MIN_BARS`; I orphaned it |
| `syncPrefsUI` | app.js | decl only | **ALIVE — named IIFE**, runs on load |
| `stickyToolbar` | app.js | decl only | **ALIVE — named IIFE** |
| `purgeLegacyKeys` | app.js | decl only | **ALIVE — named IIFE** |

The IIFE rows are why a reference count is not proof on its own:
`(function foo(){…})()` runs and is never named again.

Also checked, nothing found: orphaned `mom-*`/`mo-*` CSS classes (0),
commented-out code runs of 10+ lines in `public/js` (0), TODO/FIXME/XXX in
runtime code (0).

## 7. Kill list

`vivek.py scan.py conviction.py spec.py phasemap/engine scanner/momentum/**
scanner/broker/** vivek_bot* bot_rules.json journal/**` — **no edits planned**,
not even comment deletions. All six deletions above are in `public/js`.
