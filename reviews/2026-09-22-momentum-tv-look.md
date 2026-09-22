# Momentum chart — what renders today vs the TradingView template

Phase 0 of the "TV look" pass, 2026-09-22. **Inventory only — no visual code in
this commit.** The complaint being answered is that
`chart.html?s=ELS&m=asx&src=momentum` still reads as a Vivek 5.0 chart with
extra lines glued on, rather than as the owner's own TradingView layout.

The Auto plan maths is NOT in scope. ELS Daily already matches TradingView at
Entry 5.88 / SL 6.76 / TP1 5.00 / TP2 4.12 / TP3 3.23 with a worst error of
$0.0040, pinned by an executed test over the committed daily series.
`momentumPlan` is not to be touched unless a test proves a bug.

---

## 1. Everything that renders on `src=momentum` today

Read off the `_momentum` branch of `public/js/chart.js` at `5178509b6`.

| # | Element | Where it comes from | Verdict |
|---|---|---|---|
| 1 | Candles | `barsToMomentumTF` → `barsToVivekTF` | **KEEP** |
| 2 | Volume histogram, `priceScaleId: "vol"`, margins top .84 | `barsToVivekTF` + the shared `vol` scale | **RESTYLE** — thin strip pinned to the bottom of the PRICE pane, TV-style |
| 3 | EMA 20 / 50 / 200 (Pine-seeded) | `momentumMAs`, lengths from the payload `params` | **RESTYLE** — colours are the 5.0 palette (yellow/blue/amber); TV is blue fast / green slow |
| 4 | Auto plan hairlines SL/ENTRY/TP1-3 | `applyMomentumPlan` → `createPriceLine` | **KEEP + RESTYLE** — TV shows tags on the RIGHT of a filled box, not bare hairlines |
| 5 | Risk + reward shaded bands | `paintMomentumZones`, two baseline series | **RESTYLE** — opacity and direction tinting to match TV (~15–25%) |
| 6 | ATH price line | `paintMomentumAth` | **KEEP** |
| 7 | Scored-cross labels `+N Bullish` / `-N Bearish` | `momentumCrosses` → `candle.setMarkers` | **KEEP** — already on price, already all crosses |
| 8 | Rule A pivot + confirmation markers | `momentumMarkers` from the scan row | **MOVE** — the chips belong in the HEADER; keep the two bar marks small so they cannot collide with the box tags |
| 9 | MACD pane (hist + 2 lines) | `momentumPanes`, `priceScaleId: "macd"` | **RESTYLE** — a scaleMargins band today, needs a real separated pane at ~15% |
| 10 | RSI pane + 70/50/30 guides | `momentumPanes`, `priceScaleId: "rsi"` | **RESTYLE** — same; plus signal line to match RSI+ |
| 11 | Historical Bull/Bear divergence tags | `momentumDivs` → `rsiS.setMarkers` | **KEEP** |
| 12 | Caption "Auto plan from the Pine template" | `.mom-caption` | **KEEP** |
| 13 | Footer metric strip | `renderMomentumFooter` | **RESTYLE** — must read `PLAN · SHORT · ENTRY · SL · TP1-3 · R:R · TF`, never SCORE |
| 14 | `← Momentum` back link | `SRC_BACK` | **KEEP** |
| 15 | D / 3D / W / 4H toggles | `TF_ORDER` + per-TF `build()` | **KEEP** |
| 16 | Session / weekend shading | `shadeRows` | **KEEP** (quiet, TV has banding too) |
| 17 | FLASH bands on event bars | `setFlashes` | **HIDE** — 5.0's "review this bar" cue; on a chart that already marks crosses and divergences it is noise |
| 18 | `⚠ THIN TAPE n%` / degraded / raw-basis chip | `renderDataHonesty` → `#ct-datawarn` | **HIDE** on this mode (one-word chip at most) |
| 19 | `live fallback` note beside the price | `header()`, gated on `d._fallback && !d._vivek && !d._pm` | **HIDE** — every momentum chart is live-built by design, so the badge fires on all of them and means nothing |
| 20 | `LONG` direction badge | `#ct-dir` from `d.dir` | **KEEP** — already set from the Auto plan's own direction |
| 21 | PhaseMap zones / DEMAND / HARD INV / sweep markers / narrative strip | `fetchPhaseMapRec` + `applyPmZones` | **ALREADY HIDDEN** unless `?pm=1` (landed in #23) — verify it still holds |
| 22 | 5.0 SMA 10/20/43/200 | `barsToVivekTF` lines | **ALREADY REPLACED** — `barsToMomentumTF` overwrites `.lines` |
| 23 | 5.0 ENTRY/STOP ladder from the vivek payload | `applyVivekLevels` | **ALREADY ABSENT** — needs `tf.levels`, which the momentum builder never sets |
| 24 | 5.0 `SCORE x/8` footer strip | `footer()` generic branch | **ALREADY ABSENT** — `footer()` routes `_momentum` to its own renderer |

## 2. The three that are already correct, and must stay that way

Items 21–24 were fixed in #23 and are the ones most likely to regress while
restyling, because each is an *absence* rather than a visible thing. Absences
do not show up in a screenshot review. They are pinned by tests and the pins
must survive this pass:

* no PhaseMap fetch at all unless `?pm=1`
* `momentumFallback` never sets `tf.levels`, so `applyVivekLevels` returns early
* `footer()` routes `_momentum` before reaching the generic strip
* `renderVivekFooter` contains no momentum symbol

## 3. The real structural problem

The MACD and RSI "panes" are `scaleMargins` bands on the same plot as the
candles. They do not have their own axes or separators, which is why the price
pane's scale runs to −8 on a $5 stock: the RSI band is claiming 0–100 on a
price axis. TV has three panes with three independent scales.

`lightweight-charts@4.1.3` has no multi-pane API (that arrived in v5), so the
options are (a) separate `createChart` instances stacked and time-synced, or
(b) keep the banding but give each band its OWN price scale id with
`autoScale` and draw visible separators. (b) is the smaller change and keeps
one crosshair; (a) is what actually reproduces TV. Phase 1 decides, and the
owner's rule is explicit: oscillators painted into the price plot is a FAIL.

## 4. Out of scope, stated so it is not silently done

`momentumPlan`, `momentumCrosses`, `momentumDivs`, `emaPine`/`rmaPine`/
`rsiPine`/`macdPine`, the per-timeframe `build()` law, the 4H bucketing, and
every file on the kill list. 4H will not match TradingView until real hourly
bars reach it, and it must NOT be "fixed" by copying the Daily box.
