# UI_BACKLOG.md — v2 (2026-07-22 PM) · 100 open items

Owner mandate: work this list top-down **without prompting**, shipping via the
cloud-push workflow once each item passes the gates — node tests green,
`node --check`, Playwright smoke desktop AND 390px mobile, zero console
errors, `?v=` bumps per CLAUDE.md. Tick items in the same commit that ships
them. Frontend/infra only: **never** signal logic, PhaseMap maths, bot book
schema/risk rules, live-money paths, or publish-side payload schema (those get
proposed to the owner, not shipped). Mobile parity is a hard requirement.

**Shipped before v2** (see git history): Waves 1–2 perf (SWR paint, head-cache,
preload, lazy details, single-fetch), Command Deck tranche A (deck bar, filter
pills, single-row topbar), 4-city clocks, MORE-menu fix, journal P&L headline +
fold legibility, RECOMMENDATIONS page v1 (client-side consensus + Claude's
daily note + movers + nav/tab slot), first-paint-only row animation, SW auto-update, specs/phasemap deck parity (19-22), BACK pill in nav, 4-colour bold clock grid.

## Wave 3R — finish the Command Deck (desktop)

- [x] 1. ONE sticky filter toolbar merging view tabs + grade tabs + direction + 🎯/⚡ + entry-type chips into a single line.
- [x] 2. Sort as a compact cycling control (SCORE ↓ → PRICE → R:R → M.C → A-Z) with direction flip on repeat tap.
- [x] 3. Toolbar condenses to a slim variant on scroll (labels shrink, counts stay).
- [x] 4. Row card v2: 76px, ticker + dir arrow + mcap + name line, price with day-% beneath, spark, score + R:R stack.
- [x] 5. Expanded panel v2: horizontal Stop → Entry → TP1/TP2/TP3 ladder cells with % and scale-out notes.
- [x] 6. Checklist as inline pass/fail chips in the expanded panel; "View chart →" as the primary CTA.
- [x] 7. Day-change display: current_pct/day_pct with spark-derived ~fallback when null.
- [x] 8. Playwright e2e suite in `test/e2e/` (deck paint, pill filtering, expand, sort, recs page) wired into test.yml CI.

## Wave R — Recommendations page grows up

- [x] 9. Harden the daily note session: verify first scheduled firings, graceful skip when the token is unreachable, note stays dated + honest.
- [x] 10. Day-over-day consensus deltas: localStorage snapshot per day → "breadth shifting long/short" arrows on each market card.
- [x] 11. 14-day consensus history strip per market (client-side snapshots, tiny bars).
- [x] 12. Note archive: keep prior notes (reco_notes log) and show the last 7 behind a fold.
- [x] 13. At-level + multi-lens counts on market cards (lazy fetch after first paint).
- [x] 14. Per-sector breadth: top 3 sectors leaning long/short per market (lazy full-scan fetch).
- [x] 15. Watchlist-aware: badge movers/cards when a starred name is involved.
- [x] 16. Per-card deep link: "Open ASX scan →" jumps to the dashboard pre-switched to that market.
- [x] 17. Recs mobile pass: card order, thumb targets, movers as h-scroll strip.
- [x] 18. Recs empty/degraded states: per-file fallback messaging when a data file is missing or stale >48h.

## Wave P — Specs + PhaseMap adopt the SCAN layout (owner-promoted)

- [x] 19. Specs page: deck command bar (status + count pills + freshness dot) replacing its current header block.
- [x] 20. Specs page: sticky filter/sort toolbar in the deck language; row cards aligned to dashboard classes.
- [x] 21. PhaseMap list page: deck command bar (status + state/tier pills as click-to-filter) — respecting its existing UX tranche's filters.
- [x] 22. PhaseMap list page: sticky toolbar unification (its stepper/presets restyled into the shared language, behaviour unchanged).
- [x] 23. Extract the deck bar + pill + toolbar CSS into a shared, documented component block (one source of truth for all pages).
- [x] 24. e2e smoke for specs + phasemap pages (paint, filter, no console errors, 390px).

## Wave 4 — Mobile parity (≤680px)

- [x] 25. Mobile command bar: identical content as desktop, h-scroll pill strip, no divergent UI.
- [x] 26. Sticky mobile toolbar: the merged filter line as a thumb-height h-scroll strip (≥40px targets).
- [x] 27. Company name visible on phones as a second row line (stop `display:none`).
- [x] 28. Phone row grid: 44px grade rail, right-aligned price + day-%, spark hidden <480px but day-% kept.
- [x] 29. Bottom tab bar refinement: active states, badge counts (A+ count on SCAN, open positions on JOURNAL).
- [x] 30. MORE / overflow destinations as a touch bottom sheet with scrim (covers SPECS + ALERTS + the MORE set on phones).
- [x] 31. Expanded ladder reflows to a 2-row grid on phones — never five squished columns.
- [x] 32. Full-screen mobile search overlay with recent-tickers row and big cancel target.
- [x] 33. All tap targets ≥44px (star, expand, pills, segments) per iOS HIG.
- [x] 34. Touch-slop guard: scrolling a row never accidentally expands it.
- [x] 35. Safe-area inset audit on every page (notch, home indicator).
- [x] 36. dvh-based sticky positioning (iOS URL-bar collapse must not jitter the toolbar).
- [x] 37. 16px minimum font-size on inputs (kills iOS zoom-on-focus).
- [x] 38. Zero horizontal overflow at 320px on every page (automated check in e2e).
- [x] 39. One documented breakpoint scale (320/480/680/880/1200) replacing ad-hoc media queries.
- [x] 40. Mobile screenshot matrix in CI: 360/390/430px for dashboard, recs, journal, phasemap, chart.
- [x] 41. Active filter pill auto-scrolls into view in mobile strips.
- [x] 42. Sort control always reachable on mobile (pinned end of toolbar strip).
- [x] 43. theme-color + status-bar styling matched across pages; A2HS nudge shown once.
- [x] 44. Star action haptic + micro-animation.
- [x] 45. Long-press ticker quick-action sheet: Chart / Star / Journal.
- [x] 46. Journal mobile: bot book tables become cards (kills the pre-existing phone overflow).

## Wave 5 — Rows, detail & interaction polish

- [x] 47. FUND/REIT dimming toggle (default on, persisted) — they crowd the A+ list.
- [x] 48. Sticky A+/A/B+ group headers when sorted by score.
- [x] 49. "+N" overflow chip click expands the row directly.
- [x] 50. Keyboard: Enter expands focused row; ←/→ switch grade tabs.
- [x] 51. Copy-debug button relocates into the expanded panel.
- [x] 52. Hover prefetch of chart data for the hovered symbol.
- [x] 53. Expanded panel scan-age chip ticks live with the 30s refresher.
- [x] 54. Spark min/max markers via SVG titles.
- [x] 55. Watch tab shows starred names from ALL lenses, badged per lens.

## Wave 6 — Performance & PWA depth (the "smooth + snappy" program)

- [x] 56. Transition audit: every animation ≤200ms, transform/opacity only, zero layout-shifting transitions site-wide.
- [x] 57. Input-latency budget: filter/sort/pill interactions paint <50ms on a 200-row list (measured in e2e).
- [x] 58. Scroll performance audit: no scroll-linked jank (passive listeners, content-visibility on below-fold rows).
- [x] 59. Slim the head-cache further (drop chips/entry_types) so more of NASDAQ fits the untouched 500KB cap.
- [x] 60. Purge legacy localStorage keys post-migration (quota headroom protects the journal).
- [x] 61. Idle-time prefetch (requestIdleCallback + timer fallback) replaces the fixed 300ms market prefetch.
- [x] 62. Self-host subset woff2 fonts — kill the Google Fonts round-trip and its layout shift.
- [x] 63. sw.js precaches the app shell on install for instant repeat loads.
- [x] 64. SW update flow: one-tap Update applies AND reloads; background tabs self-heal on controllerchange; 30-min re-check for long-open tabs; apply-on-return via visibilitychange. (Shipped early — owner hit the stale-tab case.)
- [x] 65. Single SVG sprite for per-row icons (~15% list HTML cut at 200 rows).
- [x] 66. Defer GBSSync.syncIn until after first rows paint.
- [x] 67. sessionStorage cache for market_caps + backtest artifacts.
- [x] 68. Windowed rendering fallback if any list exceeds 300 rows.
- [x] 69. First-paint→interactive timing beacon (console) for before/after evidence.
- [x] 70. Lighthouse budget in CI — test/e2e/lighthouse.e2e.js runs in the e2e job (reusing Playwright's chromium). Loads the page with ?lite=1 (new app.js measurement mode: no idle prefetch / auto-refresh / background polls) so the trace is deterministic. GATES transfer <5.0MB (pins at 3.50MB) + CLS <1.60 (tripwire above the ~1.06 observed max); TTI printed but NOT gated (swings 9–20s on shared runners — a flaky perf gate would resurrect the failure-emails). CLS 0.5–1.0 flagged as a real finding for a future dedicated pass.

## Wave 7 — Chart page

- [x] 71. Chart header now carries the watchlist ★ (same unified PM.watch store as the dashboard/lens pages — namespaced to the lens you arrived from, persists locally, mirrors to cloud with a sync code) + a coloured market chip (ASX/NASDAQ/CRYPTO). phasemap-shared.js now loads on the chart page so PM.watch is available.
- [x] 72. Mobile chart: canvas goes full-bleed (edge-to-edge, 64vh) and the timeframe controls source-reorder into a thumb-reachable bar directly beneath it; the chart's ResizeObserver repaints to the new dimensions. Footer actions wrap so nothing overflows at 390px.
- [x] 73. Each legend SMA name is a toggle button — tap to hide/show its line (tracked by name so it survives TF switches; aria-pressed + strikethrough reflect state). The legend container stays pointer-events:none for chart panning; only the buttons opt back in.
- [x] 74. ENTRY price line now shows its distance from the current price ("+/-X% vs live" — the trigger distance a trader watches); SL/TP lines keep their entry-relative %/R ladder (the plan's own risk framing). Applied in both the VIVEK and specs/phasemap level-drawing paths.
- [x] 75. Arrow keys already stepped the filtered list; added touch swipe (left → next, right → previous) that ignores touches starting on the chart canvas / draw layer (those own horizontal drag) — swiping the header/toolbar/footer frame changes setup. Needs a clear, mostly-horizontal flick (>60px, 2:1 over vertical).
- [x] 76. Footer "⤴ Share" copies a CANONICAL link (identity params only — market/symbol/lens — dropping the transient filter-list state; uses the native share sheet on mobile). "⭳ PNG" exports the rendered chart via lightweight-charts' takeScreenshot() as &lt;SYM&gt;_&lt;tf&gt;.png.
- [x] 77. App-style shimmering candle skeleton fills the canvas until first paint (or the error state) replaces it — every render path funnels through header()→hideSkeleton(), fail() clears it too. Error state polished (offline-aware, see #78). Shimmer respects prefers-reduced-motion.
- [x] 78. Dashboard SCAN button disables when offline with a "you're offline — reconnect to run a fresh scan" tooltip (never fights the mid-scan spinner; stays disabled if you drop offline mid-scan). Chart page gets a live offline banner + an offline-specific error state ("You're offline" rather than "Chart unavailable"). Both react to online/offline events live.

## Wave 8 — Journal & AI Bot pages

- [x] 79. Journal now uses the shared deck header (topbar deck-top — same as index/specs/phasemap): brand · nav · right-aligned status group (account summary + sync pill). The P&L headline stays the first thing in the body. Account summary drops on mobile (redundant with the P&L headline) so the header never overflows.
- [x] 80. The P&L headline now carries a compact cumulative-$ sparkline of the BOT book's realised curve (the honest record) + its running total-$ · total-R, alongside the open-positions unrealised number.
- [x] 81. Closed-trade R is now a filled colour-scale chip — deeper green the bigger the win (≥2R / ≥1R / >0), red past the full stop (>-1R / ≤-1R), neutral at flat. Asymmetric buckets because wins run open-ended while losses cap near the -1R stop.
- [x] 82. The close-position modal shows a live "Realised R + $ impact" preview that updates as you type the exit price, before you confirm. Computed by cloning the trade and running the EXACT resolver the load path uses (ensureClosedR) — verified preview === actual outcome (+2.59R preview matched the booked +2.59R).
- [x] 83. Always-visible header pill shows the manual-journal sync state — ☁ Synced (green) / 📴 Local only (muted) / ⚠ Sync error (red, on a save/sync failure via the gbs:save-error event). Tapping it opens the (folded) sync settings. All three states verified.
- [x] 84. Weekly digest card at the top: bot book closes in the last 7 days — count, total R, total $, win rate, best close — computed client-side from the book.
- [x] 85. bot.html's 406-line inline &lt;style&gt; block extracted to public/css/bot.css (linked, versioned) — bot.html drops from ~845 to 439 lines. The styles already referenced the shared design tokens (var(--panel/green/red/…)); verified the page renders identically with the external sheet.
- [x] 86. New-position cards now show the entry-type setup chip (Weekly reclaim / Daily retest / …) consistently with the tables, and use the canonical src=journal chart link (was the stale &pm=1).

## Wave 9 — Cross-page consistency

- [x] 87. Every nav page now uses the same deck header structure (topbar deck-top: brand · nav-pills · deck-top-right). The phasemap sub-pages (insights, legend) and mynames/sectors stopped hand-rolling their own pm-topnav layouts. The nav strip itself is the shared include (nav.js injects it into #site-nav on every page); all headers now share one structure. Verified deck header + no 320px overflow on all 7 lens/utility pages.
- [x] 88. Alerts page: on-screen times are now RELATIVE ("4h ago"), with the full Melbourne time + UTC in the tooltip; adopted the shared deck header; chart links use the canonical src=alerts.
- [x] 89. ★ My Names rows now speak the dashboard row-card language: a bordered card with hover lift + accent, a colour-matched market chip (ASX/NASDAQ/CRYPTO) leading each row, and the per-lens status badges (VIVEK/PHASEMAP/SPECS · grade/state/quiet). Chart links use the canonical src=mynames (was the stale &pm=1).
- [x] 90. Styled 404 page (404.html) in the app's language — deck header, brand glyph, clear "back to the scanner" + PhaseMap/Journal actions, shared footer. Regenerated the full icon set from the brand tile (dark rounded square + green chart-up arrow): apple-touch (180), icon-192, icon-512, plus the previously-missing favicon.ico (16/32/48) + favicon-32/16 PNGs, and linked them on every page.
- [x] 91. One shared footer include (nav.js renderFooter): a consistent credit line (data source · ~15 min delayed · refreshed daily) + the standard disclaimer, injected on every nav page that doesn't already ship its own <footer class="site-footer"> (dashboard/journal/bot keep theirs — no double footer). Verified across 10 pages.

## Wave 10 — Accessibility & quality gates

- [ ] 92. Visible focus rings on every interactive element.
- [ ] 93. aria-pressed/aria-expanded on all toggles (pills, chips, folds, rows).
- [ ] 94. prefers-reduced-motion kills shimmer/entrance/chevrons across ALL components.
- [ ] 95. Grade + direction conveyed by text/shape, never colour alone.
- [ ] 96. Automated contrast check in CI for every token pair on new components (≥4.5:1).
- [ ] 97. Node tests for the cache layer (cacheSet/head/SWR/expiry) with mocked localStorage.
- [ ] 98. Screenshot-diff CI job, desktop + 390px, fails on >2% unexpected drift.
- [ ] 99. version.json deploy stamp + SW/asset skew detection; window.onerror beacon.
- [ ] 100. FRONTEND.md: deck architecture, breakpoints, cache layers, recs data flow, conventions.
