# UI_BACKLOG.md — the 100-item autonomous work list

Owner approved 2026-07-22: Command Deck revamp direction + **mobile parity**
("much cleaner / similar to the PC when I access from my phone"). Sessions work
through this list **without prompting the owner**, in wave order, shipping via
the cloud-push workflow once each item passes the gates (tests green, browser
smoke desktop AND 390px mobile, no console errors). Tick items off in this file
in the same commit that ships them. Items are frontend/infra only — **nothing
here touches signal logic, PhaseMap maths, the bot book schema, or live-money
paths** (those always need the owner; see footer).

Rendering conventions stay: Vivek 5.0 branding, iOS-dark tokens, Melbourne
timestamps on screen, ?v= bumps on every JS/CSS edit, sw.js CACHE bump on
breaking changes.

## Wave 3 — Command Deck, desktop (built responsive from day one)

- [ ] 1. Command bar component: scan status (market · setups · scanned/universe · age · coverage) with live freshness dot, replacing the scan banner + freshness pill.
- [ ] 2. Stat pills in the command bar (A+ / A / Watch counts) replacing the four stat cards.
- [ ] 3. ⨂ Multi-lens pill with live count — **click filters the rows to aligned names**, replacing the confluence banner strip.
- [ ] 4. ◎ At-level pill with live count — click filters to names sitting on a 200-SMA now, replacing the at-level strip.
- [ ] 5. Bot chip in the command bar (open count · today's R · last action) with click-to-expand event list; Journal → link kept.
- [ ] 6. ONE sticky filter toolbar merging view tabs + grade tabs + direction + 🎯/⚡ + entry-type chips + sort into a single line.
- [ ] 7. Sort as a compact cycling control (SCORE ↓ → PRICE → R:R → M.C → A-Z) with direction flip on repeat tap.
- [ ] 8. Toolbar condenses to a slim variant on scroll (labels shrink, counts stay).
- [ ] 9. Single-row topbar: brand + market segments + nav pills + search + SCAN; kill topbar row 2.
- [ ] 10. Clocks collapse to a two-line MEL/NY micro block; China/London move to its tooltip.
- [ ] 11. Retire the rotating trader quote from the topbar (footer keeps it).
- [ ] 12. Row card v2: 76px, grade rail, ticker+dir arrow+mcap+name line, price with day-% beneath, spark, score + R:R stack.
- [ ] 13. Expanded panel v2: horizontal Stop → Entry → TP1/TP2/TP3 ladder cells with % and scale-out notes.
- [ ] 14. Checklist as inline pass/fail chips in the expanded panel; "View chart →" as the primary CTA.
- [ ] 15. Filter-aware empty states ("0 rows: Multi-lens + Shorts — tap a pill to widen").
- [ ] 16. Wave-1 SWR semantics wired into the deck: "updating…" pulses the freshness dot; "update failed — showing cached" turns it amber.
- [ ] 17. Day-change display: use current_pct/day_pct; when null (ASX overnight), derive approx % from the last two spark points and mark it ~.
- [ ] 18. Playwright e2e suite committed to `test/e2e/` covering deck paint, pill filtering, expand, sort — runs in CI from this wave on.

## Wave 4 — Mobile parity (≤680px): same app, smaller

- [ ] 19. Mobile command bar: identical content, status line + horizontally scrollable pill strip (no divergent mobile UI).
- [ ] 20. Sticky mobile toolbar: the same merged filter line as desktop as a thumb-height h-scroll strip (≥40px targets).
- [ ] 21. Stop hiding the company name on phones — second line under ticker instead of `display:none`.
- [ ] 22. Phone row grid: 44px grade rail, right-aligned price + day-%, spark hidden <480px but day-% always kept.
- [ ] 23. Bottom tab bar destination parity with desktop nav (SPECS returns; MORE becomes a bottom sheet).
- [ ] 24. MORE menu as a touch bottom sheet with scrim, not a hover dropdown.
- [ ] 25. Expanded ladder reflows to a 2-row grid on phones (SL+Entry / TP1+TP2+TP3) — never five squished columns.
- [ ] 26. Full-screen mobile search overlay with recent-tickers row and big cancel target.
- [ ] 27. All tap targets ≥44px (star, expand, pills, segment buttons) per iOS HIG.
- [ ] 28. Touch-slop guard so scrolling a row never accidentally expands it.
- [ ] 29. Safe-area inset audit on every page (notch, home indicator), not just the tab bar.
- [ ] 30. dvh-based sticky positioning so iOS URL-bar collapse doesn't jitter the toolbar.
- [ ] 31. 16px minimum font-size on inputs — kills iOS zoom-on-focus in search.
- [ ] 32. Zero horizontal overflow at 320px on every page (automated check).
- [ ] 33. One documented breakpoint scale (320/480/680/880/1200) replacing today's ad-hoc media queries.
- [ ] 34. Mobile screenshot matrix in CI: 360/390/430px for dashboard, journal, phasemap, chart.
- [ ] 35. Active filter pill auto-scrolls into view in the mobile strip.
- [ ] 36. Sort control always reachable on mobile (pinned end of the toolbar strip).
- [ ] 37. theme-color + status-bar styling matched to the deck across pages.
- [ ] 38. Add-to-Home-Screen nudge, shown once, dismissible forever.
- [ ] 39. Star action haptic (navigator.vibrate where supported) + micro-animation.
- [ ] 40. Long-press on a ticker opens a quick-action sheet: Chart / Star / Journal note.

## Wave 5 — Rows, detail & interaction polish

- [ ] 41. Optional dimming for ⚠ FUND/REIT rows (they crowd the A+ list) with a toolbar toggle; default on, persisted.
- [ ] 42. Sticky A+/A/B+ group headers when sorted by score.
- [ ] 43. "+N" overflow chip click expands the row directly.
- [ ] 44. Keyboard: Enter expands the focused row; ←/→ move between grade tabs; / already searches.
- [ ] 45. Copy-debug button relocates into the expanded panel (row right side decluttered).
- [ ] 46. Hover/route prefetch of chart data for the hovered symbol.
- [ ] 47. Expanded panel scan-age chip ticks live (reuses the Wave-1 30s refresher).
- [ ] 48. Row entrance animation only on first paint, not on every filter change (rAF-coalesced renderRows).
- [ ] 49. Spark tooltips: min/max markers on hover (SVG title, no JS lib).
- [ ] 50. Watch tab shows starred names from ALL lenses (parity with ★ MY NAMES counts), clearly badged per lens.

## Wave 6 — Performance & PWA depth

- [ ] 51. Slim the head-cache further (drop chips/entry_types from head rows) so more of NASDAQ fits under the untouched 500KB cap.
- [ ] 52. Purge legacy localStorage keys post-migration (gbs-lens-watchlist, gbs:watch) to protect journal quota headroom.
- [ ] 53. Idle-time prefetch (requestIdleCallback with timer fallback) replaces the fixed 300ms market prefetch.
- [ ] 54. Self-host subset woff2 of Inter + JetBrains Mono — kill the Google Fonts round-trip and its layout shift.
- [ ] 55. sw.js precaches the app shell (styles/app/nav/phasemap-shared/gbs-sync) on install for instant repeat loads.
- [ ] 56. SW update flow: one-tap "Update" applies skipWaiting AND reloads — no manual refresh.
- [ ] 57. Single SVG sprite for per-row icons (star/chevron/copy) — cuts list HTML ~15% at 200 rows.
- [ ] 58. Defer GBSSync.syncIn until after first rows paint.
- [ ] 59. sessionStorage cache for market_caps.json + backtest artifact (stable intraday).
- [ ] 60. Windowed rendering fallback if any market list exceeds 300 rows.
- [ ] 61. First-paint→interactive timing beacon logged to console (before/after evidence for every perf item).
- [ ] 62. Lighthouse budget in CI — build fails if dashboard TTI or CLS regresses past thresholds.
- [ ] 63. Offline state disables the SCAN button and shows why.
- [ ] 64. Align sw.js data strategy with app-level SWR (single source of staleness truth, no double-refetch races).
- [ ] 65. Manifest shortcuts: Scan ASX · Journal · ★ My Names; maskable icon variants.

## Wave 7 — Chart page

- [ ] 66. Chart page adopts the deck header (back + symbol + market, star state synced).
- [ ] 67. Mobile chart: full-bleed canvas with controls in a bottom sheet.
- [ ] 68. Legend chips toggle SMA 10/20/43/200 lines on tap.
- [ ] 69. Entry/SL/TP lines labelled with % from current price (parity with the ladder).
- [ ] 70. Swipe/arrow to next/prev setup in the current filtered list.
- [ ] 71. Canonical shareable chart links (m, s, mode only — strip transient params).
- [ ] 72. PNG export button (canvas snapshot) for sharing a setup.
- [ ] 73. Chart loading skeleton + error state in app style (no blank canvas).

## Wave 8 — Journal & AI Bot pages

- [ ] 74. Journal adopts the deck header + toolbar language.
- [ ] 75. Bot book rows become cards on mobile (no table squish).
- [ ] 76. Equity-curve mini chart from the bot book (the honest track record, nothing else).
- [ ] 77. Per-trade realised-R chips with colour scale in closed list.
- [ ] 78. Close-position flow shows R impact preview before confirming.
- [ ] 79. Journal sync status indicator: synced / local-only / error — the manual book's health at a glance.
- [ ] 80. Weekly digest card: this week's closes, R total, win rate — computed client-side from the bot book.
- [ ] 81. bot.html visual alignment to deck tokens (it forked stylistically); inline styles move to a css file.

## Wave 9 — Cross-page consistency

- [ ] 82. One shared header/nav include on every page (phasemap pages stop hand-rolling theirs).
- [ ] 83. Alerts page: relative times + Melbourne tooltips (Wave-1 convention everywhere).
- [ ] 84. ★ My Names rows use the dashboard row-card language, badged per lens.
- [ ] 85. Specs page chips/badges unify with dashboard classes.
- [ ] 86. PhaseMap pages: token/spacing alignment only (its fresh UX tranche is respected, not rewritten).
- [ ] 87. Styled 404/error page.
- [ ] 88. Favicon + touch icons regenerated from the brand tile.
- [ ] 89. Footer standardised (disclaimer, data source, quote's new home).

## Wave 10 — Accessibility & quality gates (woven in, finished here)

- [ ] 90. Visible focus rings on every interactive element (pills, chips, rows, segments).
- [ ] 91. aria-pressed/aria-expanded on all toggles; aria-live on the results container retained and verified.
- [ ] 92. prefers-reduced-motion: kills shimmer, entrance, chevron spins across ALL new components.
- [ ] 93. Grade + direction conveyed by text/shape, never colour alone (screen-reader labels on rails/arrows).
- [ ] 94. Automated contrast check in CI for every token pair used by new components (≥4.5:1).
- [ ] 95. Node tests for the cache layer (cacheSet/head/SWR/expiry) with mocked localStorage.
- [ ] 96. Screenshot-diff CI job, desktop + 390px, fails on >2% unexpected pixel drift.
- [ ] 97. Zero-console-error policy enforced by the e2e suite.
- [ ] 98. version.json stamped per deploy; app detects SW/asset skew and offers the update toast.
- [ ] 99. window.onerror beacon (console + optional lightweight ping) so client-side crashes are visible.
- [ ] 100. FRONTEND.md: deck architecture, breakpoints, cache layers, conventions — so every future session builds the same way.

---

**Not in this list (owner-gated, never autonomous):** anything in scanner/ or
phasemap/ detection logic, bot book schema or risk rules, live trading gates,
data-provider switch, NASDAQ payload slimming (publish-side schema change),
GBS_SYNC_CODE / Cloudflare Access secrets. These get proposed, not shipped.
