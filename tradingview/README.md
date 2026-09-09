# TradingView templates (Vivek 5.0 chart layout)

Pine Script v6 sources for the three indicators that make up the chart
layout. Chart-only: nothing in the scanner reads this folder, no test runs
over it, and it is outside every signal path.

| File | Pane | Replaces |
|---|---|---|
| `Final_Top_Script.pine` | price (overlay) | your existing `Final_Top_Script`. Since v5.2 it is titled **Vivek 5.0 Top** on the chart: TradingView had ended up with several saved scripts under the old name and the chart kept attaching to the v1 copy, so the running version was impossible to tell apart. Remove every `Final_Top_Script` from the chart and from *My scripts*, then add this one. |
| `Final_Bottom_MACD.pine` | MACD | your existing `Final_Bottom_MACD` (same 12 / 26 / 9, same status-line order). Titled **Vivek 5.0 MACD** on the chart. |
| `Final_RSI_Plus.pine` | RSI+ | the plain `RSI 14 close` pane at the top of your chart. Titled **Vivek 5.0 RSI+** on the chart. |

## Install

1. TradingView, bottom panel, **Pine Editor**, **Open**, **New indicator**.
2. Select all, paste the file, **Save** under the name the script's `indicator()`
   line uses (`Vivek 5.0 Top` for the overlay), **Add to chart**. Never save a
   new version under a name that already exists in *My scripts*: the chart can
   stay attached to the old copy, which is exactly what happened with v1.
   The header tells you which version is running: `Vivek 5.0 Top 20 50 200
   EMA` plus three prices is current; a long row of numbers after `EMA` is v1.
3. Do the same for the other two files. Remove the old `Final_Top_Script`,
   `Final_Bottom_MACD` and `RSI 14` from the chart, then drag the RSI+ pane
   below MACD if you want the 5.0 order (price, MACD, RSI+).
4. Right-click the chart, **Save layout / Save as template** so it applies to
   every symbol.

These files were written without a Pine compiler available here. If the
editor reports an error on paste, copy the line it names back and it is a
one-line fix.

## What changed against your current template

- **Fast 50 / Slow 200 SMA** became **Fast 20 / Mid 50 / Slow 200 EMA**. Your
  old Fast (50) is now the `Mid Length` input; the old Slow is unchanged.
  `MA type` switches back to SMA if you prefer the 200-SMA the scanner uses.
- The cyan / orange lines became the 5.0 palette: Fast and Mid in two blues,
  Slow in green while Mid is above it and red while below, with the band
  between Mid and Slow filled the same colour.
- `Show Background Zone` is kept and does the same job (green / red regime
  tint) but is OFF by default: on the dark theme it swamped the chart in the
  first live paste. Tick it back on under Background if you want it.
- **v2 (after the first live paste, 2026-09-09):** RSI columns fire only at
  the extremes (75 / 25) instead of 70 / 30; every level prints as a native
  price-scale label instead of a tag in the chart margin (they were being
  clipped by the axis); a level further than `Hide a level further than
  this %` from price (default 100%, i.e. outside half-to-double) is hidden,
  because BTC's all-time low near $100 was stretching the scale down to
  zero; the auto trade box only draws for a signal inside the last 60 bars
  and caps the auto stop at 15% of entry (a crash-bar swing stop was
  putting TP2 / TP3 below zero on a short); pivot levels default to 3 a
  side; inputs are hidden from the status line so the header reads
  `Final_Top_Script 20 50 200 EMA` rather than forty numbers.
- The `BULLISH` label on the golden cross is still there but off by default
  (`Label Mid x Slow crosses`); the 5.0 charts do not show it.

## How each element of the 5.0 screenshots is reproduced

| On the 5.0 charts | Where it comes from now |
|---|---|
| Two blue MAs and a thick red / green MA with a shaded band | `Moving averages` group |
| `Bullish +2` / `-2 Bearish` with an arrow | `Signals` group. Fires on every Fast x Mid cross. Score = 1 for the cross, +1 when the MACD histogram agrees, +1 when price is on the right side of the Slow MA (+1 for RSI > 50 / < 50 if you switch it on). `Minimum score to show` hides the weak ones. |
| Grey boxed `-2 Bearish` | `Boxed signal labels` |
| Vertical green / red columns on the price pane | `RSI extreme columns` (RSI 14 at or above 70 = green, at or below 30 = red). The matching columns on the RSI+ pane come from `Final_RSI_Plus`. `Column on signal bars` adds a column at each signal instead or as well. |
| Dashed grey line from the signal low up to the later high | `Dashed line: last signal to the extreme since` |
| `ATH` / `ATL` text with a green line | `Key levels`, `ATH / ATL of the loaded history` (scroll the chart left once so more history loads if the ATH looks wrong) |
| `2025 Y.O` / `2026 Y.O` | `Yearly opens` (this year first, up to three) |
| `High` / `Low` boxes on the price scale | `Range High / Low` over `Range lookback` bars |
| `Q1 2021 ATH`, `2022 BM Low`, `Q1 2024 ATH`, `2021 ATH` | Hand-drawn on the 5.0 charts. Type them into `Manual levels` (price + name), six slots. |
| The cyan supply band under `Q1 2021 ATH` | `Manual zones` (top, bottom, name, colour), two slots |
| Green / red / grey price tags on the price scale | `Auto support / resistance`: recent pivot highs (red above price), pivot lows (green below), grey once broken. `Levels per side` (max 3) and `Pivot strength` control how many and how major. Every level, target and stop is a native price-scale label; tick **Indicators and financials name labels** (below) to see `TP1`, `SL`, `ATH` beside the numbers. |
| The big translucent rectangles (green + red, blue + red) | On the 5.0 charts these are TradingView's **Long Position** / **Short Position** drawing tool, not an indicator. `Trade box` draws the same thing: `Auto (last signal)` builds it from the latest signal if it is within 60 bars (stop under the swing or by ATR, capped at 15% of entry; targets at 1R / 2R / 3R, never below zero); `Manual` lets you type a posted call, for example CRV short, entry 0.3641, SL 0.403, TP1 0.343, TP2 0.303, TP3 0.233, and get the identical box and ladder. |
| The blue box with a red band on top, drawn from the current price (INJ, ENS, CRV, BTC) | This is the counter-trend call in all four of his recent charts: short the pump at an RSI extreme, stop above the high, target back at the old low. `Reversal box` group: while RSI is at or above 75 the script draws a SHORT box from the current close (blue), stop = the highest high of the last 30 bars + 1 ATR, target = the lowest low of the last 30 bars; at or below 25 it draws the mirror LONG box (green). Once RSI leaves the zone the box freezes and stays until the stop or the target prints, or 60 bars pass. While it is active the trend box is hidden (`Hide the trend box ...`). This is a reconstruction of a pattern in his screenshots, not his script's rules, which are private. |
| A key / legend in the corner | `Key (legend in a chart corner)` group: a table pinned to the top-left (or any corner) listing what every line, arrow, box, tag and column means, with the score rule spelled out, plus three live rows: trend now, last signal (with its score and age) and the current trade box written out as `LONG entry / SL / TP1 / TP2 / TP3`. Text size and corner are inputs; `Live rows` can be switched off. |
| MACD pane | `Final_Bottom_MACD`: the four-shade histogram is the only visible change from yours |
| `(D7R) RSI+` pane with the blue / red fill and the two empty-set values | `Final_RSI_Plus`: RSI 14 with a 14 SMA, blue fill while RSI is above the MA and red below, 70 / 75 and 30 / 25 bands, a 50-bar RSI average, extreme columns, and regular divergence marks. The two empty-set symbols in the status line are the bull / bear divergence plots when there is no divergence, exactly as on the 5.0 pane. |

## Chart settings that complete the look

- **Log scale, always** (the 5.0 charts are all log). Right-click the price
  scale, tick **Logarithmic** (or `Alt+L`). To make it the default for every
  new chart: chart settings (the cog), **Template** menu at the bottom-left of
  the dialog, **Save As Default**. Then save the layout so open charts keep
  it. A Pine script cannot switch the chart's scale itself.
- **Price-scale value labels**: the owner's chart has *Indicators and
  financials value labels* switched OFF, which is why nothing the script
  plots with `display.price_scale` shows on the axis (and why the EMA values
  never appear there). v4 therefore draws the Entry / SL / TP1-3 tags INSIDE
  the pane (`Tags inside the chart for Entry / SL / TP1-3`, on by default;
  `... for every level`, off by default). Turning the chart setting on (chart
  settings, **Scales and lines**, **Labels**) gives the native axis labels as
  well, which is the 5.0 look.
- **Plot budget.** TradingView allows 64 plot slots per script. A `plot()`
  whose colour is a compile-time literal (`#22c55e`, `color.red`) costs ONE
  slot; a colour from an input or a series costs TWO, and `plotshape`,
  `bgcolor`, `fill` (series colour) and `alertcondition` all count. v5 failed
  at 71 and v5.2 at 68 on exactly this, because the axis-label plots used
  input colours. v5.3 gives the axis labels literal colours and drops the
  pivot / manual level axis labels (their lines, names and in-chart tags
  stay): 34 slots. Add a plot only if that number stays under 64.
- **No trade box on a ticker** means the last Fast x Mid cross is older than
  `Auto: only if the signal is within (bars)` (60). It is an age cut-off, not
  a verdict on the trade; the key's *Trade now* row says so. Raise the number
  to see older setups.
- **Indicator name labels on the price scale** are what print `High` and `ATH`
  as boxes beside the values on the 5.0 charts, and with v2 they also name
  `TP1` / `SL` / `Entry` / `R1` / `S1`: chart settings, **Scales and lines**,
  tick **Indicators and financials name labels**. Recommended.
- **Hide the input values in the header**: the scripts already hide them, but
  if `12 26 9 close` still shows, chart settings, **Status line**, untick
  **Indicator arguments**.
- The 5.0 screenshots are on the light theme; every colour in the scripts is
  an input, chosen to read on the dark theme you use. Change them under
  **Style** if you switch themes.
- Check the price scale on your screenshot: the numbers grow downwards
  (27 at the top, 280 at the bottom), which is the **Invert scale** option.
  Right-click the price scale to turn it off if it was not intended.

## Alerts

Each script exposes `alertcondition`s (bullish / bearish signal, golden /
death cross, MACD zero-cross, RSI overbought / oversold entry, divergences).
Create them from the alert dialog with the indicator selected as the
condition.
