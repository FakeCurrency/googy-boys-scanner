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
| `makeLiveBoxDraggable` | chart.js | decl only | dead, **KEPT** — see §8 |
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
not even comment deletions. Every deletion below is in `public/js` or
`public/css`.

## 8. PHASE 1 outcome

A second pass counted declarations **per file** (comments stripped), because a
name shared across files hides a dead copy (`isVivek`, `pct`, `YF_TICKER`).
Every deletion is its own commit, pinned by `test/hygiene.test.js`; each pin
was mutation-checked by adding the name back as a string (red), and a
comment-only mention stays green.

**Deleted.** chart.js: `MOM_FIRST_PAINT_BARS`, `entryRelTargets`,
`fetchStockQuote`, `levTag`, `SIM_CRYPTO_MARGIN`/`SIM_CRYPTO_LEVERAGE`/
`SIM_STOCK_SIZE`, `restURL` (a local in makeLive). app.js: `fmtTurn`,
`VIEW_KEYS`. journal.js: `inBatches`, `fav`, `nowTime`, `tradeKey`, `$$`, and
the live-quote chain `priceFor` → `cryptoPrice`/`stockPrice` → `fetchJSON` +
journal.js's own `YF_TICKER`. phasemap-insights.js: `pct`. chart.css: the 13
`.live-pos-box`/`.lpb-*` rules.

**Kept because uncertain.**
- `makeLiveBoxDraggable` (chart.js): no caller, but leaks.test.js pins its
  `resize`/`restore` add/remove pair and counts its teardown. Removing it means
  editing a fence test.
- The chart.js cost model (`COMMISSION_BPS`, `SLIPPAGE_BPS`, `costsFor`,
  `legCost` + the bot_rules.json fetch that fills them): `legCost` has no
  caller, so the whole block is unread. But it carries the TOP100 #28 comment
  on keeping one cost model, and deleting it drops a network request.
- `isHighConviction` (chart.js): a 3-line wrapper with no caller. It sits in
  the HC four-cell area, and tests pin the app.js copy by that name.
- journal.js names tests still slice or stub: `costsFor`, `isVivek`, `today`,
  `markStale`, `sizeOf`, `costR`, `drawMiniEquity`. None has a runtime caller.
  **Finding:** journal_money.test.js asserts `/drawMiniEquity/` with the
  message "the per-book equity curves must still be drawn". But
  `drawEquity` draws those curves, and `drawMiniEquity` is the retired header
  sparkline, so the pin checks the wrong function. journal.js ~1413 has a
  comment making the same mix-up. Left for the owner. Fixing it means editing
  a pin.
- Named IIFEs `syncPrefsUI`, `stickyToolbar`, `purgeLegacyKeys` — alive.

**Checked, nothing to delete.** momentum.css (the `is-bull`/`is-bear` rules are
built as `"is-" + dir`). chart.css `s-*` (built as `s-${state}`). The nine e2e
fixtures (each is served to a page as `/data/`, and they are hashed into the
screenshot cache key). HTML pages (404.html is Cloudflare's not-found page and
offline.html is sw.js's fallback).

**Second pass (nav.js + chart.js only).** ESLint `no-unused-vars` was run as
an independent check. nav.js: nothing. chart.js: the three names already kept
above, plus `const ep = pl.entry` in `applyMomentumPlan`, which P2 (#26)
orphaned when it dropped the `%·R` rung labels. Deleted in its own commit and
pinned inside that function.
