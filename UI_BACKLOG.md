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

- [ ] 9. Harden the daily note session: verify first scheduled firings, graceful skip when the token is unreachable, note stays dated + honest.
- [x] 10. Day-over-day consensus deltas: localStorage snapshot per day → "breadth shifting long/short" arrows on each market card.
- [x] 11. 14-day consensus history strip per market (client-side snapshots, tiny bars).
- [ ] 12. Note archive: keep prior notes (reco_notes log) and show the last 7 behind a fold.
- [ ] 13. At-level + multi-lens counts on market cards (lazy fetch after first paint).
- [ ] 14. Per-sector breadth: top 3 sectors leaning long/short per market (lazy full-scan fetch).
- [ ] 15. Watchlist-aware: badge movers/cards when a starred name is involved.
- [ ] 16. Per-card deep link: "Open ASX scan →" jumps to the dashboard pre-switched to that market.
- [ ] 17. Recs mobile pass: card order, thumb targets, movers as h-scroll strip.
- [ ] 18. Recs empty/degraded states: per-file fallback messaging when a data file is missing or stale >48h.

## Wave P — Specs + PhaseMap adopt the SCAN layout (owner-promoted)

- [x] 19. Specs page: deck command bar (status + count pills + freshness dot) replacing its current header block.
- [x] 20. Specs page: sticky filter/sort toolbar in the deck language; row cards aligned to dashboard classes.
- [x] 21. PhaseMap list page: deck command bar (status + state/tier pills as click-to-filter) — respecting its existing UX tranche's filters.
- [x] 22. PhaseMap list page: sticky toolbar unification (its stepper/presets restyled into the shared language, behaviour unchanged).
- [ ] 23. Extract the deck bar + pill + toolbar CSS into a shared, documented component block (one source of truth for all pages).
- [ ] 24. e2e smoke for specs + phasemap pages (paint, filter, no console errors, 390px).

## Wave 4 — Mobile parity (≤680px)

- [ ] 25. Mobile command bar: identical content as desktop, h-scroll pill strip, no divergent UI.
- [ ] 26. Sticky mobile toolbar: the merged filter line as a thumb-height h-scroll strip (≥40px targets).
- [x] 27. Company name visible on phones as a second row line (stop `display:none`).
- [x] 28. Phone row grid: 44px grade rail, right-aligned price + day-%, spark hidden <480px but day-% kept.
- [ ] 29. Bottom tab bar refinement: active states, badge counts (A+ count on SCAN, open positions on JOURNAL).
- [ ] 30. MORE / overflow destinations as a touch bottom sheet with scrim (covers SPECS + ALERTS + the MORE set on phones).
- [x] 31. Expanded ladder reflows to a 2-row grid on phones — never five squished columns.
- [ ] 32. Full-screen mobile search overlay with recent-tickers row and big cancel target.
- [x] 33. All tap targets ≥44px (star, expand, pills, segments) per iOS HIG.
- [x] 34. Touch-slop guard: scrolling a row never accidentally expands it.
- [ ] 35. Safe-area inset audit on every page (notch, home indicator).
- [ ] 36. dvh-based sticky positioning (iOS URL-bar collapse must not jitter the toolbar).
- [ ] 37. 16px minimum font-size on inputs (kills iOS zoom-on-focus).
- [ ] 38. Zero horizontal overflow at 320px on every page (automated check in e2e).
- [ ] 39. One documented breakpoint scale (320/480/680/880/1200) replacing ad-hoc media queries.
- [ ] 40. Mobile screenshot matrix in CI: 360/390/430px for dashboard, recs, journal, phasemap, chart.
- [ ] 41. Active filter pill auto-scrolls into view in mobile strips.
- [ ] 42. Sort control always reachable on mobile (pinned end of toolbar strip).
- [ ] 43. theme-color + status-bar styling matched across pages; A2HS nudge shown once.
- [ ] 44. Star action haptic + micro-animation.
- [ ] 45. Long-press ticker quick-action sheet: Chart / Star / Journal.
- [ ] 46. Journal mobile: bot book tables become cards (kills the pre-existing phone overflow).

## Wave 5 — Rows, detail & interaction polish

- [x] 47. FUND/REIT dimming toggle (default on, persisted) — they crowd the A+ list.
- [ ] 48. Sticky A+/A/B+ group headers when sorted by score.
- [ ] 49. "+N" overflow chip click expands the row directly.
- [ ] 50. Keyboard: Enter expands focused row; ←/→ switch grade tabs.
- [ ] 51. Copy-debug button relocates into the expanded panel.
- [ ] 52. Hover prefetch of chart data for the hovered symbol.
- [ ] 53. Expanded panel scan-age chip ticks live with the 30s refresher.
- [ ] 54. Spark min/max markers via SVG titles.
- [ ] 55. Watch tab shows starred names from ALL lenses, badged per lens.

## Wave 6 — Performance & PWA depth (the "smooth + snappy" program)

- [ ] 56. Transition audit: every animation ≤200ms, transform/opacity only, zero layout-shifting transitions site-wide.
- [ ] 57. Input-latency budget: filter/sort/pill interactions paint <50ms on a 200-row list (measured in e2e).
- [ ] 58. Scroll performance audit: no scroll-linked jank (passive listeners, content-visibility on below-fold rows).
- [ ] 59. Slim the head-cache further (drop chips/entry_types) so more of NASDAQ fits the untouched 500KB cap.
- [ ] 60. Purge legacy localStorage keys post-migration (quota headroom protects the journal).
- [ ] 61. Idle-time prefetch (requestIdleCallback + timer fallback) replaces the fixed 300ms market prefetch.
- [ ] 62. Self-host subset woff2 fonts — kill the Google Fonts round-trip and its layout shift.
- [ ] 63. sw.js precaches the app shell on install for instant repeat loads.
- [x] 64. SW update flow: one-tap Update applies AND reloads; background tabs self-heal on controllerchange; 30-min re-check for long-open tabs; apply-on-return via visibilitychange. (Shipped early — owner hit the stale-tab case.)
- [ ] 65. Single SVG sprite for per-row icons (~15% list HTML cut at 200 rows).
- [ ] 66. Defer GBSSync.syncIn until after first rows paint.
- [ ] 67. sessionStorage cache for market_caps + backtest artifacts.
- [ ] 68. Windowed rendering fallback if any list exceeds 300 rows.
- [ ] 69. First-paint→interactive timing beacon (console) for before/after evidence.
- [ ] 70. Lighthouse budget in CI — fail on TTI/CLS regression past thresholds.

## Wave 7 — Chart page

- [ ] 71. Chart page adopts the deck header (back + symbol + market, star synced).
- [ ] 72. Mobile chart: full-bleed canvas, controls in a bottom sheet.
- [ ] 73. Legend chips toggle SMA lines on tap.
- [ ] 74. Entry/SL/TP lines labelled with % from current price.
- [ ] 75. Swipe/arrow to next/prev setup in the current filtered list.
- [ ] 76. Canonical shareable chart links; PNG export button.
- [ ] 77. Chart loading skeleton + error state in app style.
- [ ] 78. Offline state disables SCAN button and says why (also on chart).

## Wave 8 — Journal & AI Bot pages

- [ ] 79. Journal adopts the deck header + toolbar language (P&L headline stays first).
- [ ] 80. Equity-curve mini chart with the P&L headline (bot book only — the honest record).
- [ ] 81. Per-trade realised-R chips with colour scale in closed lists.
- [ ] 82. Close-position flow shows R + $ impact preview before confirming.
- [ ] 83. Journal sync status indicator: synced / local-only / error.
- [ ] 84. Weekly digest card: closes, R total, win rate — client-side from the bot book.
- [ ] 85. bot.html visual alignment to deck tokens; inline styles move to a css file.
- [ ] 86. Journal "new positions" cards link to charts and show entry-type chips consistently.

## Wave 9 — Cross-page consistency

- [ ] 87. One shared header include on every page (phasemap pages stop hand-rolling theirs).
- [ ] 88. Alerts page: relative times + Melbourne tooltips + deck header.
- [ ] 89. ★ My Names rows use the dashboard row-card language, badged per lens.
- [ ] 90. Styled 404/error page; favicon + touch icons regenerated from the brand tile.
- [ ] 91. Footer standardised (disclaimer, data source, quote's home) on all pages.

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
