# Vivek 5.0 — FRONTEND.md

How the static frontend (`public/`) is put together: the deck architecture,
the breakpoint scale, the cache layers, the recs data flow, and the
conventions every page follows. Read this before touching the UI — it is the
map that keeps the pages consistent. (Added 2026-07-24 as UI backlog #100.)

Companion docs: `CLAUDE.md` (project-wide rules), `UI_BACKLOG.md` (the 100-item
UI programme this file closes out).

---

## The stack

Vanilla JS + CSS, no framework, no build step. Every page is a hand-written
`.html` file in `public/` that loads shared scripts and one page script. Served
static by Cloudflare Pages; the only server code is the Pages Functions in
`functions/api/*` (a separate Workers runtime — see CLAUDE.md).

```
public/
  index.html          the dashboard (the scanner "deck")
  chart.html          per-ticker chart (lightweight-charts)
  journal.html        paper-trade journal (bot book vs you)
  phasemap*.html      PhaseMap lens + insights + key/legend
  specs.html          Specs lens
  alerts.html         multi-lens alignment history
  mynames.html        ★ My Names (cross-lens watchlist)
  sectors.html        news / rotation
  bot.html            AI bot terminal (its own institutional styling)
  404.html            styled not-found page
  css/                styles.css (tokens + dashboard) + per-page sheets
  js/                 shared modules + one script per page
  data/               scan JSON published by the Actions pipeline
  version.json        deploy stamp (skew detection)
```

---

## Deck architecture (the dashboard)

The dashboard is a "command deck": one dense control surface, then the list.
Top to bottom:

- **Deck header** (`.topbar.deck-top`) — brand · market switch · nav · clocks ·
  actions. The SAME header structure is now on every page (backlog #87): brand,
  the nav-pills mount, and a right-aligned `.deck-top-right` group. `js/nav.js`
  injects the nav into `#site-nav` and appends the shared footer — it is the one
  shared header/footer include.
- **Deck** (`.deck`) — status line (freshness) + click-to-filter **pills**
  (`.fpill`: A+, A, ⨂ Multi-lens, ◎ At level, top pick). The pills replaced the
  old stat cards / banner strips; each is a filter toggle carrying `aria-pressed`.
- **Toolbar** (`.toolbar`) — one sticky line: grade tabs (A+/A/WATCH), the ★
  watch toggle, the ⚠ FUNDS dimmer, VIVEK filter chips, and a cycling sort. Pins
  under the header and slims on scroll.
- **Rows** (`#results`) — one `.row-wrap` per result: grade group, ticker,
  direction arrow, sparkline, price, R:R, ★. Rows are keyboard-operable
  (`role=button`, `tabindex=0`, `aria-expanded`, Enter/Space to expand). Grade
  is always the letter and direction always an arrow shape (▲/▼) — never colour
  alone (backlog #95). Large lists window at 300 rows (`state._showAll`).

`app.js` is the dashboard controller: SWR paint, filtering, sort, rows, search,
the deck pills, live clocks, cross-lens stars (via `PM.watch`).

---

## Breakpoint scale

Design desktop-first; the responsive tiers narrow it. The load-bearing tiers:

| max-width | what changes |
|-----------|--------------|
| 1760 / 1600 | wide-desktop grid reflows (stat/section columns) |
| 1200 / 880  | stats collapse to 2-up, then 1-up |
| 768 / 680   | tablet: nav + toolbar tighten |
| 600 / 560   | **the phone tier** — the big one: single-column, bottom-tab nav, cards instead of tables, full-bleed chart, controls to thumb-reach |

Two hard test widths are gated in CI: **390px** (modern phone) and **320px**
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
   is a safety rail — it protects the manual journal's shared localStorage quota
   and is never raised.
2. **`sessFetch` (app.js)** — per-session `sessionStorage` cache for small
   side files (backtests, market caps) so a tab revisit doesn't refetch.
3. **Slim head-cache key** — `gbs:cache:head:` vs the full `gbs:cache:`; head
   payloads are marked `_head`, shown only under the "updating…" flag, and NEVER
   enter `state.cache`.
4. **`sw.js`** — the service worker: network-first for `data/` + HTML (fresh
   data always wins), cache-first for `?v=` assets (immutable — every edit bumps
   `?v=`), never caches `/api/`. App-shell precached on install. Bump its `CACHE`
   name on a breaking change.

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
  covers. A CI gate (`test/contrast.test.js`, #96) holds text tokens to WCAG AA
  (≥4.5:1) and accent/UI colours to ≥3:1 on the dark surfaces.
- **Timestamps** — Melbourne on screen, market-local/UTC in the tooltip
  (`PM.fmtMelb`). Relative times ("4h ago") for logs, full time in the tooltip.
- **Accessibility** — one universal `:focus-visible` ring (green + halo);
  toggles carry `aria-pressed`, disclosures `aria-expanded`;
  `prefers-reduced-motion` zeroes ALL animation/transition durations.
- **Telemetry** (`js/telemetry.js`, #99) — loaded first in `<head>` on every
  page: a `window.onerror`/`unhandledrejection` beacon (ring buffer +
  `window.__gbsErrors()`), plus `version.json` skew detection (offers a refresh
  when a new deploy lands while a tab is open; the SW `controllerchange` is the
  same signal).
- **Shared chrome** — `nav.js` owns the nav strip and the footer include; don't
  hand-roll either. The brand block is uniform across pages.

---

## Testing gates (what CI runs on every push — `test.yml`)

- **JS unit** — risk engine (46), unit (65), watcher parity (21), SWR cache
  (13), design-token contrast (33). `node --check` on every shipped script.
- **E2E** (Playwright) — `smoke.e2e.js` walks the daily flows (deck paint, pill
  filter, row expand, sort, recs, specs, phasemap) desktop + 390px + a 320px
  overflow sweep, failing on any uncaught page error; `screenshots.e2e.js` shoots
  the 360/390/430 matrix; `lighthouse.e2e.js` is a regression tripwire (CLS +
  transfer-weight budgets, loaded with `?lite=1` for determinism).

Local: serve `public/` on a static server and point Playwright at the pre-
installed chromium (`PW_CHROMIUM` / `CHROME_PATH`). Canvas-heavy pages (chart)
time out on screenshots — verify them via DOM checks, not screenshots.
