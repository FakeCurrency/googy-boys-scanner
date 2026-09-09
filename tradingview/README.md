# TradingView templates (Vivek 5.0 chart layout)

Pine Script v6 sources for the three indicators that make up the chart
layout. Chart-only: nothing in the scanner reads this folder, no test runs
over it, and it is outside every signal path.

| File | Pane | Replaces |
|---|---|---|
| `Final_Top_Script.pine` | price (overlay) | your existing `Final_Top_Script` (same name, same `Fast Length` / `Slow Length` / `Show Background Zone` inputs, plus everything below) |
| `Final_Bottom_MACD.pine` | MACD | your existing `Final_Bottom_MACD` (same 12 / 26 / 9, same status-line order) |
| `Final_RSI_Plus.pine` | RSI+ | the plain `RSI 14 close` pane at the top of your chart |

## Install

1. TradingView, bottom panel, **Pine Editor**, **Open**, **New indicator**.
2. Select all, paste the file, **Save** (keep the name the file uses), **Add to chart**.
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
| MACD pane | `Final_Bottom_MACD`: the four-shade histogram is the only visible change from yours |
| `(D7R) RSI+` pane with the blue / red fill and the two empty-set values | `Final_RSI_Plus`: RSI 14 with a 14 SMA, blue fill while RSI is above the MA and red below, 70 / 75 and 30 / 25 bands, a 50-bar RSI average, extreme columns, and regular divergence marks. The two empty-set symbols in the status line are the bull / bear divergence plots when there is no divergence, exactly as on the 5.0 pane. |

## Chart settings that complete the look

- **Log scale** on the price pane (the 5.0 charts are all log). Click `L` at
  the bottom of the price scale or `Alt+L`.
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
