# Vivek 5.0 — FRONTEND.md

How the static frontend (`public/`) is put together: the deck architecture,
the breakpoint scale, the cache layers, the recs data flow, and the
conventions every page follows. Read this before touching the UI — it is the
map that keeps the pages consistent. (Added 2026-07-24 as UI backlog #100;
refreshed 2026-10-14, REFINE200 #100: the ★ My Names page, the stars, the AI BOT
page and the manual "Me" journal are gone — the journal shows the bot book only.)

Companion docs: `CLAUDE.md` (project-wide rules), `docs/archive/UI_BACKLOG.md` (the 100-item
UI programme this file closes out).

---

## The stack

Vanilla JS + CSS, no framework, no build step. Every page is a hand-written
`.html` file in `public/` that loads shared scripts and one page script. Served
static by Cloudflare Pages; the only server code is the Pages Functions in
`functions/api/*` (a separate Workers runtime — see CLAUDE.md).

```
public/
  index.html          the dashboard (the scanner "deck"), incl. the ⚡ Ignition panel
  chart.html          per-ticker chart (lightweight-charts; js/chart-indicators.js
                      holds the pure indicator maths and loads first)
  journal.html        Claude's paper book — the one track record (bot book only)
  phasemap*.html      PhaseMap lens + insights + key/legend
  specs.html          Specs lens
  momentum.html       MOMENTUM lens (report-only)
  recommendations.html  RECS: deltas, Claude's note, confluence picks
  alerts.html         multi-lens alignment history (a rolling window)
  sectors.html        NEWS & markets (movers, calendar)
  system.html         SYSTEM: the bot's rulebook + backtest evidence
  about.html          HOW IT WORKS
  404.html · offline.html   not-found page · the service worker's offline fallback
  _headers            Cloudflare cache/security headers (?v= assets immutable)
  css/                styles.css (tokens + dashboard) + per-page sheets
  js/                 shared modules + one script per page
  data/               JSON published by the Actions pipeline
  version.json        deploy stamp (skew detection)
```

---

## Deck architecture (the dashboard)

The dashboard is a "command deck": one dense control surface, then the list.
Top to bottom:

- **Deck header** (`.topbar.deck-top`) — brand · market switch · nav · clocks
  (Melbourne + New York, HH:MM, repainted once a minute) · actions. Solid
  background, no backdrop blur; on phones two rows (brand + actions, then the
  market switch) (UI100, 2026-10-20). The SAME header structure is now on every page (backlog #87): brand,
  the nav-pills mount, and a right-aligned `.deck-top-right` group. `js/nav.js`
  injects the nav into `#site-nav` and appends the shared footer — it is the one
  shared header/footer include.
- **Deck** (`.deck`) — status line (freshness; the coverage pill shows only
  when degraded) + click-to-filter **pills** (`.fpill`: ⚡ Ignition (first, on
  the crypto/ASX/NASDAQ decks), ⨂ Multi-lens, ◎ At level) + the quiet ⊘ products
  toggle + the one-line book summary. The A+/A shortcut pills and the top pick
  went with UI100 (the toolbar carries the grade counts); each pill is a filter
  toggle carrying `aria-pressed`.
- **Toolbar** (`.toolbar`) — one sticky line: grade tabs (A+/A/WATCH, counted
  on the side showing — Longs by default), VIVEK filter chips, and a cycling sort. Pins under the header
  and slims on scroll.
- **Rows** (`#results`) — one `.row-wrap` per result: grade group, ticker,
  direction arrow, sparkline, price, R:R, confluence chips, the SMA-proxy chip
  and the market cap (with its date when over 30 days old). Rows are keyboard-operable
  (`role=button`, `tabindex=0`, `aria-expanded`, Enter/Space to expand). Grade
  is always the letter and direction always an arrow shape (▲/▼) — never colour
  alone (backlog #95). Large lists window at 300 rows (`state._showAll`).

`app.js` is the dashboard controller: SWR paint, filtering, sort, rows, search,
the deck pills, live clocks. The deck reads the entry-quality tints and the
position cap from `data/bot_rules.json` (it no longer downloads a backtest file
for three chips). On nav pages `nav.js`'s `window.VivekBook` is the one shared
read of the bot book + rules: app.js and recs.js read through it with
`{fresh:true}` on their own refresh; chart.js (no nav.js) keeps its own.

---

## Breakpoint scale

Design desktop-first; the responsive tiers narrow it. The load-bearing tiers:

| max-width | what changes |
|-----------|--------------|
| 1760 / 1600 | wide-desktop grid reflows (stat/section columns) |
| 1200 / 880  | stats collapse to 2-up, then 1-up |
| 768 / 680   | tablet: nav + toolbar tighten |
| 600 / 560   | **the phone tier** — the big one: single-column, bottom-tab nav, cards instead of tables, full-bleed chart, controls to thumb-reach |

Above 680px the nav pills take their own header row (per-header width bands);
at ≤680px they are hidden and the bottom tab bar owns navigation. Two hard test
widths are gated in CI: **390px** (modern phone) and **320px**
(the narrowest supported). `test/e2e/smoke.e2e.js` fails on any horizontal
overflow at 320px across index/recs/phasemap/specs/journal; the screenshot
matrix (`screenshots.e2e.js`) shoots 360/390/430. Any new component MUST hold
320px with no page overflow — tables scroll inside `.jr-table-wrap`/equivalent,
they don't stretch the page.

---

## Cache layers

Four cooperating layers keep paint instant without ever serving stale trades:

1. **`js/cache.js` (`window.GBSCache`)** — the SWR scan cache (unit-tested in
   `test/cache.test.js`, backlog #97). `set/get` is a 5-min TTL full cache;
   `getStale` returns an EXPIRED payload so a cold load paints the last scan
   instantly while the fresh fetch runs; `setHead/getHead` is a slim always-
   written entry (stats + first 60 rows, heavy per-row fields stripped) so a
   market whose full payload tops the **500KB cap** still paints. The 500KB cap
   is a safety rail on the shared localStorage quota and is never raised.
2. **`sessFetch` (app.js)** — per-session `sessionStorage` cache for small
   side files (backtests, market caps) so a tab revisit doesn't refetch.
3. **Slim head-cache key** — `gbs:cache:head:` vs the full `gbs:cache:`; head
   payloads are marked `_head`, shown only under the "updating…" flag, and NEVER
   enter `state.cache`.
4. **`sw.js`** — the service worker: network-first for `data/` + HTML (fresh
   data always wins; data keyed by PATH with the query dropped, `/data/` capped at
   40 entries), cache-first for `?v=` assets (immutable — every edit bumps `?v=`;
   older `?v=` copies are evicted), never caches `/api/`. App-shell precached on
   install. Bump its `CACHE` name (`vivek5-v9` since 2026-10-14) on a scheme
   change. `public/_headers` serves `/js /css /vendor /fonts` immutable for a
   year, so a missed `?v=` bump pins the old file.

---

## Recs data flow (`recommendations.html` + `recs.js`)

Three stacked sources, freshest-wins:

1. **Deltas / breadth** — computed client-side from the committed `*_vivek.json`
   scans (same files the dashboard reads); 14-day breadth history in
   `gbs:reco:hist` (localStorage).
2. **Claude's note** — a dated hand-written read at `data/reco_note.json`,
   authored by the `reco_note.yml` CI job (a cloud Claude session can't reach the
   push token, so CI owns the daily cadence). Read-state archived in
   `gbs:reco:notes` so it survives the daily overwrite.
3. **Confluence enrichment** — the SAME engine as the dashboard's ⨂ pill
   (`PM.loadConfluence`), lazily pulled per market for at-level / multi-lens.

Degraded/stale states are explicit — the page never pretends a missing source
is empty.

---

## Conventions

- **Versioning** — every edit to a `public/js/*.js` or `public/css/*.css` bumps
  its `?v=N` in EVERY referencing HTML page. Read the numbers from the HTML, not
  from docs. `sw.js` cache-firsts on the `?v=` so a stale asset can't linger.
- **Design tokens** — colours/spacing live in `styles.css :root`
  (`--bg/panel/text/muted/green/red/blue/…`). Never hardcode a hex that a token
  covers. TEXT uses the `-ink` twins (`--blue-ink`, `--red-ink`,
  `--purple-ink`): the base blue/red/purple fail AA as text (2026-10-13 UI
  review); fills and borders stay on the base tokens. A CI gate (`test/contrast.test.js`, #96) holds text tokens to WCAG AA
  (≥4.5:1) and accent/UI colours to ≥3:1 on the dark surfaces.
- **Timestamps** — Melbourne on screen, market-local/UTC in the tooltip
  (`PM.fmtMelb`). Relative times ("4h ago") for logs, full time in the tooltip.
- **Accessibility** — one universal `:focus-visible` ring (green + halo);
  toggles carry `aria-pressed`, disclosures `aria-expanded`;
  `prefers-reduced-motion` zeroes ALL animation/transition durations.
- **UX top-10 (2026-07-26)** — CLS pass (space reserved pre-data + metric-
  matched font fallbacks; lighthouse gate at <0.50), the status lamp
  (`status.js`, fed by `/api/health`), first-visit onboarding (`gbs:onboarded`),
  recs morning read, proportional plan axis in row detail, intent prefetch +
  view transitions + scroll restore (nav.js/app.js), chart mobile control
  sheet. (The ★ arm/trigger notifications went with the stars, 2026-09-21.)
- **Screenshot-diff fixtures** — `test/e2e/fixtures/data/` freezes all /data/
  requests during the diff so live scan commits can't drift the shots.
- **Telemetry** (`js/telemetry.js`, #99) — loaded first in `<head>` on every
  page: a `window.onerror`/`unhandledrejection` beacon (ring buffer +
  `window.__gbsErrors()`), plus `version.json` skew detection (offers a refresh
  when a new deploy lands while a tab is open; the SW `controllerchange` is the
  same signal).
- **Shared chrome** — `nav.js` owns the nav strip and the footer include; don't
  hand-roll either. The brand block is uniform across pages.

---

## Testing gates (what CI runs on every push — `test.yml`)

- **JS unit** — every `test/*.test.js` (each needs its own step in test.yml —
  a test enforces it): the SWR cache, design-token contrast, escaping, the
  journal money maths, the status lamp, the Ignition panel, the Functions and
  more; most slice the SHIPPED functions out of `public/js` and run them.
  `node --check` on every shipped script; Functions are checked as modules.
- **E2E** (Playwright) — `smoke.e2e.js` walks the daily flows (deck paint, pill
  filter, row expand, sort, recs, specs, phasemap) desktop + 390px + a 320px
  overflow sweep on the fixture data set, failing on any uncaught page error;
  `screenshots.e2e.js` shoots the 360/390/430 matrix; `screenshot-diff.e2e.js`
  compares four views against cached baselines with the page clock frozen;
  `lighthouse.e2e.js` is a regression tripwire (CLS 0.5 + a 1.7 MB transfer
  budget on a staged fixture root, loaded with `?lite=1`).

Local: serve `public/` on a static server and point Playwright at the pre-
installed chromium (`PW_CHROMIUM` / `CHROME_PATH`). Canvas-heavy pages (chart)
time out on screenshots — verify them via DOM checks, not screenshots.

---

## UX-20 additions (2026-07-26)

- **⌘K palette** (`nav.js`) — every nav page gets Ctrl/Cmd-K: commands (pages,
  markets, page-registered actions via `window.GBSPalette.register`) + a
  cross-market setup search indexed lazily from the slim `*_prices.json`
  files. The mobile MORE sheet's SEARCH row opens the same overlay.
- **Chart page** (`chart.js`) — 🔔 tap-to-set price alerts (one-shot, stored in
  `gbs:palerts:<market>:<sym>`; the dashboard re-checks the store on every
  scan), ▶ REPLAY bar-by-bar scrubber, ⚖ VS relative-strength overlay (rebased
  dashed line, persisted per market), and session/weekend shading (hidden-scale
  histogram under the flash bands).
- **Journal** — calendar week review with ‹ › paging, the R-distribution
  histogram, and per-row 📤 trade-card PNG export (canvas). (Since 2026-09-21
  the journal is the bot book only; since 2026-10-14 its close buttons sit in
  collapsed "Emergency close" folds — the owner no longer closes by hand.)
- **Dashboard** — per-setup position sizing in the row detail (shares the
  chart's `gbs:mysize-*` store), row density modes (`body.density-compact`),
  SECTOR in the sort cycle (grouped headers), and a ⚠ partial-scan pill when
  a payload's universe reads far below the market's typical size.
- **PWA round 2** — manifest shortcuts + dedicated maskable icons,
  `offline.html` as the SW's navigation last-resort (precached).
- **NOT done: splitting `app.js` into lazy modules** (chart.js's pure
  indicator maths did move to `js/chart-indicators.js`, REFINE200 #96). Deliberate: the detail
  builders share ~20 closures with the main IIFE, and the intent (don't pay
  for unused work) is already served by lazy detail render, row windowing,
  `?lite=1`, SWR + head-start fetch. Revisit only with a build step.

## Universe resilience (2026-07-26)

`scanner/universe.py` retries directory fetches (3x, backoff) and snapshots
every successful full fetch to `data/universe_cache/<market>.json` (committed
by scan.yml/crypto_bot.yml). A failed fetch falls back to the last-good
snapshot BEFORE the bundled CSV — after a Saturday ASX scan silently ran on
93 names when asx.com.au flaked. The ASX cache + `data_universe/asx_tickers.csv`
were seeded from a mirror of the official directory (2,212 names, GICS
sectors); the next successful live fetch replaces both organically. The
dashboard's ⚠ partial-scan pill is the client-side tripwire.
