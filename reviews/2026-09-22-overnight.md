# Momentum overnight — close-out + audit (2026-09-22)

Report-only throughout. No scan rule, no bot, no confluence, no Discord.

## Visual acceptance — ELS Daily, `src=momentum`, browser-probed

All eleven MUSTs true on the shipped branch. Observations, not screenshots:

| # | check | result |
|---|---|---|
| 1 | three panes, oscillators NOT in the candle plot | 2 `.mom-pane` charts under the price chart |
| 2 | EMA 20/50/200, no SMA 10/20/43 | `EMA 20 · EMA 50 · EMA 200` in the legend |
| 3 | shaded box + right-edge tags | `SL ENTRY TP1 TP2 TP3`, price in the axis label |
| 4 | scored-cross labels on price | `-2 Bearish` / `+3 Bullish` on the bars |
| 5 | ATH line | present, labelled |
| 6 | RSI history + 70/50/30 | Bear tags across the window, three guides |
| 7 | footer, never SCORE 0/8 | `PLAN SHORT ENTRY 5.880 SL 6.762 TP1 4.998 TP2 4.116 TP3 3.234 R:R 3.00 TF 1D` |
| 8 | header direction from the Auto plan | `SHORT` |
| 9 | no PhaseMap | not fetched at all (no `?pm=1`) |
| 10 | caption | "Auto plan from the Pine template — not a 5.0 plan.", exactly one |
| 11 | back link | `← Momentum`, href `?s=` |

BHP 5.0 control: 0 momentum panes, no caption, `SMA 10/20/43/200`, 5.0 footer
intact. Zero page errors on either.

## TF honesty

`1D` 5.880/6.762 · `4H` 6.682/7.342 (own bars, NOT the Daily box) ·
`3D` and `1W` "No Auto box on this TF — no scored cross in 60 bars", which is
the honest answer at those bar sizes and matches the owner's own 3D chart.
4H vs TradingView 6.46/7.39 is **unverified: proxy** — no hourly series in the
repo and pages.dev/Yahoo are blocked, so the 4H figures above come from hourly
bars synthesised off the real daily ones and are NOT a match claim.

## Fences

`test_momentum_fences.py` green. Kill-list paths in the branch diff: none.
`journal/` tree `616d3ceb` before == after. `run.py` writes only
`public/data/momentum/`. TABS = 5, momentum in PRIMARY and on the MORE sheet.

## Scan health (summaries only, nothing changed)

ASX universe 2047 / downloaded 1165 / scanned 298 / 4 hits · NASDAQ 1426 /
1425 / 1157 / 20 hits. Both ran with `reused: 0` — cold cache; next scheduled
run should warm.

## Land note — PR #24

- **PR** https://github.com/FakeCurrency/googy-boys-scanner/pull/24, rebase-merged, 5 commits linear, no merge commit.
- **SHA on main** `6b2ce0131f74db9a59c27f5755b956bd70fbbd92` (base was `af0bfd8b2`, a crypto-bot data commit; rebased onto it, zero overlap).
- **Files** `public/js/chart.js`, `public/css/chart.css`, `public/chart.html`, `public/version.json`, `test/momentum.test.js`, `reviews/2026-09-22-momentum-tv-look.md`, `reviews/2026-09-22-overnight.md`.
- **Tests** pytest 1467 / 83 files green; 23 JS suites green, exit codes written to a file (no pipeline `$?`); momentum 218 → 269 checks.
- **journal/** `d57678b19a286cf4aa4f57824faaf3366da501ef`, identical to main's before and after. Never staged.
- **ELS Daily pins hold: YES** — 5.8800 / 6.7620 / 4.9980 / 4.1160 / 3.2340, all within $0.01.
- **BHP still 5.0: YES** — 0 momentum panes, no Pine caption, SMA 10/20/43/200, 5.0 footer intact.
- Kill-list paths in the diff: none. TABS = 5, momentum in PRIMARY + MORE sheet.

### Queue status at this point

Q0–Q25 done or already true on HEAD. Q26 (pane separator weight) and Q29 (ATH
yields its axis label to SL within 1.5%) shipped in the same PR. Q28 checked
and needed no change: `momentumCrosses` returns all 32 crosses on the ELS
series and the renderer maps every one — only 1 falls in the last 6 months
because the name trended, which is an honest gap rather than a truncation.
Q30 4H present and ≠ Daily (6.682/7.342 vs 5.880/6.762). Q31 3D/1W show the
honest empty-box copy. Q17/Q18 momentum.yml unchanged: own concurrency group,
post-close crons, writes only `public/data/momentum/*.json`, three allowlisted
actions.

**Unverified: proxy** — 4H against TradingView 6.46/7.39. No hourly series in
the repo, Yahoo and pages.dev both blocked, so the 4H figures above come from
hourly bars synthesised off the real daily ones and are NOT a match claim.
