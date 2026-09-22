# VIVEK 5.0 - INDICATOR TEMPLATE AND SCANNER SPECIFICATION

**A complete technical handover for building a daily-timeframe screener across ASX, NASDAQ
and crypto, based on a reconstructed TradingView chart template.**

| | |
|---|---|
| **Document version** | 1.0 |
| **Date** | 22 September 2026 |
| **Author** | Claude (Anthropic), working with the template's owner |
| **Subject** | Three Pine Script v6 indicators, their exact mathematics, and the specification for a screener that acts on two of their signals |
| **Audience** | An AI or engineer implementing the screener from scratch |
| **Source repository** | `FakeCurrency/googy-boys-scanner`, folder `tradingview/`, branch `claude/optimistic-darwin-r6s49g` |
| **Status of the template** | Live and in use on TradingView. Chart-only: no production system reads it. |
| **Status of the screener** | Not built. This document is its specification. |

---

## HOW TO READ THIS DOCUMENT

It is long on purpose. It is meant to be the only document you need, so it repeats itself
where repetition prevents an error.

**If you are implementing the screener**, read in this order:

1. **Part 0** - what is being asked for, in one page.
2. **Part 5** - the screen itself, exactly specified. This is the requirement.
3. **Part 7** - the correctness traps. More implementations fail here than anywhere else.
   Then **Part 4B**, which is those traps as arithmetic you can check against your code.
4. **Part 6** - a tested Python reference implementation you can lift wholesale.
5. Everything else as reference.

**If you want to understand the chart first**, read Parts 1 to 4 in order.

**If you only have five minutes**, read Part 0, Part 5.3B and Part 7.1 - the two rules
have different detection lags and that is the detail most likely to be got wrong.

### Conventions used throughout

- Bar indices are zero-based and increase with time. `bar[i-1]` is the bar before `bar[i]`.
- "The last closed bar" always means the most recent bar whose period has fully elapsed.
- Pine Script identifiers are written as `plFound`, Python as `plfound`, to keep the two
  languages visually distinct.
- Every threshold that appears in prose also appears in the parameter table (Appendix A).
  If the two disagree, the Pine source in Part 3 is the authority.
- All code in this document is ASCII-only, as is the source repository, because its scanner
  runs on Windows consoles that cannot render arrows or dashes.

### What is NOT in this document

- Position sizing, risk management, order routing. The screener produces a list.
- Any claim that these rules are profitable. See Part 1.
- The private `5_0_Strategy` script's source. Nobody outside its author has it.

---

## TABLE OF CONTENTS

| Part | Title | What it gives you |
|---|---|---|
| 0 | The brief | The ask, the universes, the screen in one paragraph |
| 1 | Provenance and honest caveats | What is reproduced, what is invented, what is unvalidated |
| 2 | The chart template: what is on the screen | Every visual element and what it means |
| 3 | Complete Pine Script source | All three indicators, verbatim |
| 4 | Complete rule inventory of the three scripts | Every input, every computed quantity, every drawn object, transcribed |
| 4A | Pine built-in semantics, verified | What `ta.rsi`, `ta.pivotlow`, `ta.valuewhen`, `ta.barssince` actually do, with citations and pandas equivalents |
| 4B | **A worked example of the divergence timing** | **Bar-by-bar arithmetic you can check by hand** |
| 5 | **The scanner specification** | **The requirement: rules, modes, gates, ranking, output schema** |
| 6 | Python reference implementation | Tested, runnable code implementing Parts 4 and 5 |
| 6A | Adversarial review of that implementation | A second agent's attempt to break it, and what it found |
| 6B | End-to-end command line runner | A scaffold that ties the module to a data provider and publishes the JSON |
| 7 | **Repainting, look-ahead and traps** | **The failure modes that matter** |
| 8 | Market-specific notes | ASX, NASDAQ and crypto quirks |
| 9 | Integration with the existing repository | Real APIs, if you build inside the owner's scanner |
| 10 | Validation | How to prove the scanner agrees with the chart |
| 11 | Performance and scale | Where the time goes and how to vectorise |
| 12 | Open decisions for Vivek | The choices the implementer must not make alone |
| A | Complete parameter table | Every tunable and its default |
| D | The base-rate measurement | The simulation behind Part 5.10, reproducible |
| B | Glossary | Every term, defined precisely |
| C | Version history of the template | What changed and which bugs to avoid repeating |


---

# PART 0 - THE BRIEF

## 0.1 What you are being asked to build

A **daily-timeframe market screener** that walks three universes, computes a small,
precisely-defined set of technical conditions on each symbol's daily OHLCV history, and
emits a shortlist of tickers for a human to review by eye.

| Universe | Size | Symbol shape | Session |
|---|---|---|---|
| ASX (Australian Securities Exchange) | ~2,200 listed names | `CBA.AX` (Yahoo suffix `.AX`) | 10:00-16:00 Australia/Sydney |
| NASDAQ | ~1,430 names (Global Select tier) | `AAPL` (no suffix) | 09:30-16:00 America/New_York |
| Crypto | ~100 (top-100 by cap, plus extras) | `BTC-USD` (Yahoo `-USD`) | 24/7, UTC day boundary |

The screener does **not** decide trades, size positions, or place orders. Its only job is
to reduce ~3,700 symbols to a list short enough to look at one chart at a time. The owner
then opens each survivor on the TradingView template described in this document and makes
a human decision. **False positives are cheap. Misses are expensive.** Tune accordingly.

## 0.2 The screen, in one paragraph

Take the latest **closed** daily bar. A symbol is a hit if either of the following is true:

- **RULE A (RSI divergence).** The RSI+ pane has printed a `Bull` or `Bear` regular
  divergence label within the last few sessions. This is a momentum/price disagreement:
  price made a lower low while RSI made a higher low (bullish), or price made a higher
  high while RSI made a lower high (bearish).
- **RULE B (scored cross, magnitude 2 or more).** The price overlay has printed a scored
  moving-average cross signal whose score is 2 or 3 in absolute value, i.e. the label
  read `Bullish +2`, `Bullish +3`, `-2 Bearish` or `-3 Bearish`. A score of 1 (the bare
  cross with nothing confirming it) does **not** qualify.

Two run modes are required:

- **Mode A** - Rule A only.
- **Mode B** - Rule A **OR** Rule B.

A third mode is trivially available from the same computation and is worth shipping
because it is the highest-conviction subset:

- **Mode C** - Rule A **AND** Rule B, direction-aligned (both bullish or both bearish).

## 0.3 Why the exact bar timing matters more than anything else in this document

The RSI divergence is detected with a **pivot confirmation lag of 5 bars**. The label is
*drawn* on the pivot bar but is only *knowable* 5 bars later. A screener that treats the
drawn position as the detection time will look into the future, and will appear to work
beautifully in a backtest and fail live. **Section 7 is the most important section in this
document.** If you read only one part, read that one.


---

# PART 1 - PROVENANCE AND HONEST CAVEATS

Read this before treating any rule here as authoritative.

## 1.1 What this template is

Three Pine Script v6 indicators, written from scratch to reproduce the *look and the
apparent decision logic* of a private TradingView script called `5_0_Strategy`, used by a
trading group the owner follows ("5.0 Trading"). The reconstruction was done by reading
screenshots of that script's output on INJ, ENS, CRV, BTC, AVAX and a few equities.

## 1.2 What it is NOT

- **It is not the 5.0 script.** That script's source is private. Nothing here is a copy,
  a decompilation, or an informed guess at its internals. Where his chart and this one
  disagree, his is a human decision plus private code, and this one is arithmetic with
  rules chosen by an AI and written down.
- **It is not a backtested edge.** No walk-forward test has been run on any rule in this
  document. The scored cross and the divergence screen are *attention filters*, not entry
  systems. Their hit rate, expectancy and drawdown are unknown.
- **It is not connected to the owner's existing scanner.** The `tradingview/` folder in
  the repository is chart-only: no Python module imports it, no test runs over it, no
  workflow reads it, and it sits outside every signal path of the existing four-lens
  scanner (VIVEK, PhaseMap, Specs, TURTLE).
- **It has never been compiled by its author.** The Pine files were written in a cloud
  sandbox with no Pine compiler. They were verified by static analysis and then by the
  owner pasting them into TradingView. Two runtime errors were found that way and fixed
  (see Appendix C).

## 1.3 Which parts are reconstructions vs. reproductions

| Element | Status |
|---|---|
| RSI 14 with a 14-period MA, blue/red fill, 70/75 and 30/25 bands | Reproduction. Standard, matches the reference pane's visible values. |
| `Bull` / `Bear` regular divergence labels | Reproduction of TradingView's own built-in "Divergence Indicator" logic, which the reference pane appears to use. High confidence. |
| MACD 12/26/9 with four-shade histogram | Reproduction. Standard. |
| 20 / 50 / 200 EMA stack, slow line coloured by regime, filled band | Reproduction of the visible geometry. The reference uses three MAs of similar look; exact lengths and type (EMA vs SMA) are inferred, not known. |
| `Bullish +N` / `-N Bearish` scored labels | **RECONSTRUCTION.** The reference prints scores in this format. The *scoring rule* (cross + MACD agreement + position vs the slow MA) was invented for this template. The real rule is unknown. |
| The Long/Short position boxes with Entry/SL/TP1-3 | Reconstruction of *shape*. On the reference charts these are the TradingView **Long Position / Short Position drawing tool**, placed by hand. The template generates them mechanically instead. |
| The "reversal box" (short the pump at an RSI extreme, stop above the high, target at the prior low) | **RECONSTRUCTION** of a pattern observed across four of his posted charts. Not his rule. |
| ATH/ATL, yearly opens, range High/Low, pivot S/R | Reproduction of visible levels; the lookbacks are chosen, not known. |

## 1.4 The implication for the scanner

Rule A (divergence) rests on a well-documented, widely-used definition and is worth
screening on directly.

Rule B (the scored cross) rests on a rule an AI made up to look like a screenshot. It is a
reasonable trend-confirmation filter on its own terms - an EMA cross that agrees with MACD
and with the long-term trend is a real, if unremarkable, technical condition - but do not
describe it to anyone as "the 5.0 signal". Treat Rule B as *a* momentum filter with a
plausible construction and no evidence, and consider running Mode A for a while before
trusting Mode B's extra volume.


---

# PART 2 - THE CHART TEMPLATE: WHAT IS ON THE SCREEN

Three indicators. The price overlay carries everything that makes a decision; the two lower
panes are context, except for the RSI pane's divergence labels, which are half the screen.

A note on names: the files are `Final_Top_Script.pine`, `Final_Bottom_MACD.pine` and
`Final_RSI_Plus.pine`, but the indicators declare themselves on the chart as **Vivek 5.0
Top**, **Vivek 5.0 MACD** and **Vivek 5.0 RSI+**. The rename was forced by a real problem:
several saved copies shared the old name and the chart kept attaching to the oldest one, so
three successive "fixes" appeared to change nothing. If you ever extend these, keep the
declared titles unique.

---

## 2.1 Vivek 5.0 Top - the price overlay

### 2.1.1 The moving-average stack and the regime

Three EMAs of the close: **20** (thin blue), **50** (thicker blue), **200** (thick, coloured
by regime). The 200 line is **green while the 50 is above it** and **red while the 50 is
below it**. The band between the 50 and the 200 is filled in the same colour at 82%
transparency.

This is the chart's single most-read element: the fill tells you at a glance whether the
medium-term structure is above or below the long-term one. In the output schema it is the
`regime` field, `up` or `down`.

The MA type is switchable between EMA and SMA; both are computed on every bar regardless,
so that switching does not produce a discontinuity in the `ta.*` history. EMA is the
default. (The owner's original template used a 50/200 SMA pair; the 20 was added and the
type changed to EMA during the rebuild.)

### 2.1.2 The scored cross signals - "Bullish +2", "-3 Bearish"

**This is Rule B of the screen.** On every bar where the 20 crosses the 50, the script
prints a small arrow and a two-line label. The number is a confidence score from 1 to 3:

| Term | Worth | Condition (bullish case) |
|---|---|---|
| The cross itself | 1 | always, when the cross happens |
| MACD agreement | +1 | `macd_hist > 0` |
| Trend agreement | +1 | `close > EMA200` |
| RSI agreement | +1, **disabled by default** | `rsi > 50` |

So `Bullish +3` means the 20 crossed above the 50, MACD momentum was already positive, and
price was already above the 200. `Bullish +1` means the cross happened with nothing else
agreeing. The bearish side mirrors exactly and prints as `-N Bearish`.

Because the RSI term is off by default, **the reachable scores are 1, 2 and 3**. The
screen's "2 or more" therefore admits two of three levels.

### 2.1.3 RSI-extreme columns

Faint vertical bands painted across the price pane: green where `RSI(14) >= 75`, red where
`RSI(14) <= 25`. At 85% transparency, deliberately quiet.

These were 70/30 in the first version and it was a mistake worth recording: at 70/30 a
large fraction of all bars are "extreme", so the chart was permanently striped and the
information content was near zero. 75/25 makes them rare enough to mean something.

### 2.1.4 Key levels

Horizontal lines, each with a name floating above it and (optionally) a price tag:

- **ATH / ATL** of whatever history the chart has loaded. Note: *loaded*, not all time - if
  the chart has only pulled two years, the "ATH" is a two-year high. A scanner computing
  this from a fixed 750-bar window will disagree with a chart that has scrolled further
  back, so state the window in the output.
- **Yearly opens**, labelled `2026 Y.O`, `2025 Y.O`. The first daily open of each calendar
  year, pulled from a 12-month resampling.
- **Range High / Low** over a 100-bar lookback (off by default).
- **Up to six manual named levels** and **two shaded zones**, for hand-typed levels like
  "Q1 2021 ATH" or a supply band.
- **Automatic pivot support and resistance**: up to three recent pivot highs (red, above
  price) and three pivot lows (green, below price), each turning grey once price has broken
  through it. Pivot strength 10 bars each side - note this is a *different* pivot setting
  from the divergence pivots, which use 5.

A **distance filter** hides any level more than 100% away from the current price. This
exists because drawing Bitcoin's all-time low near $100 on a $80,000 chart compressed the
entire price axis to a flat line. Any scanner reporting levels should apply the same filter
or report the distance so the consumer can.

### 2.1.5 The trade boxes

Two kinds, both purely illustrative - **the screener does not use either**, but they show
the shape of trade the template is pointing at.

**The trend box** anchors to the most recent scored cross, if it is within 60 bars. Entry at
the signal bar's close; stop either below the 5-bar swing plus a quarter-ATR pad, or 1.5
ATR, capped at 15% of entry; targets at 1R, 2R and 3R. The profit zone is drawn as a green
(long) or blue (short) rectangle from entry to TP3, the stop zone as a red rectangle from
entry to the stop.

**The reversal box** is the counter-trend variant and is the one that matches the reference
charts most closely. While RSI sits at an extreme, it draws a position **from the current
close, against the move**: short at an overbought extreme with the stop above the highest
high of the last 30 bars plus one ATR, targeting the lowest low of the last 30 bars. Mirror
for oversold. Once RSI leaves the extreme zone the box freezes and remains until the stop
or target prints, or 60 bars pass.

Both were reconstructions of hand-drawn TradingView Position tool rectangles on the
reference charts (see Part 1). The 15% stop cap and the 60-bar freshness gate were added
after live use: a crash-bar swing stop on AVAX put TP2 and TP3 below zero, and a year-old
signal was still drawing a box as though it were current.

### 2.1.6 The key (legend)

A table pinned to a chart corner, explaining every mark, plus three live rows:

```
Trend now     UP (Mid above Slow)
Last signal   Bullish +3, 2 bars ago
Trade now     SHORT (reversal, RSI 78) entry 6.43 / SL 7.02 / target 4.63
```

Those three rows are effectively the human-readable version of one scanner output row, and
the output schema in Part 5 deliberately mirrors them.

---

## 2.2 Vivek 5.0 MACD - the momentum pane

Standard 12/26/9 MACD:

- **Histogram** with TradingView's four-shade colouring: strong teal when positive and
  rising, faded teal when positive and falling, strong red when negative and falling, faded
  red when negative and rising.
- **MACD line** in blue, **signal line** in orange.
- A dashed zero line, and optional columns on histogram zero-crosses.

The only part the screen depends on is the sign of the histogram, which supplies the
`macd_agrees` term of the score.

---

## 2.3 Vivek 5.0 RSI+ - the divergence pane

**This is Rule A of the screen**, and the more informative of the two rules.

- **RSI(14)** in near-white, with a **14-period SMA of the RSI** in faded amber.
- A **fill between them**, blue while RSI is above its MA, red while below. This is the
  pane's at-a-glance momentum read.
- Bands at **70 and 75** (overbought) and **30 and 25** (oversold), with the space between
  each pair shaded.
- A **50 midline**, and a **50-period average of the RSI** as a long-run reference.
- **Vertical columns** on the extremes: blue at or above 75, red at or below 25.
- **`Bull` and `Bear` labels** marking regular divergences, drawn at the pivot bar.

The divergence logic is a faithful reproduction of TradingView's own built-in Divergence
Indicator, which the reference pane appears to use. Its exact definition, and the critical
5-bar confirmation lag, are specified in Part 5.2 and Part 7.1.

One cosmetic detail worth knowing when comparing against a screenshot: when no divergence
is present, the two divergence plots have no value, and TradingView prints the empty-set
symbol for them in the pane's status line. Seeing two of those is normal, not an error.


---

# PART 3 - COMPLETE PINE SCRIPT SOURCE

All three indicators, verbatim from the repository at commit HEAD. These are the authority:
where this document's prose and this source disagree, the source is right.

They are included in full so that this document is self-contained and so that a
reimplementation can be diffed against the original line by line.

## 3.1 - `Final_Top_Script.pine` (declared as "Vivek 5.0 Top", 627 lines)

```pine
//@version=6
// =============================================================================
// Final_Top_Script  --  5.0-style overlay for TradingView  (v5.3: plot budget, for real)
// -----------------------------------------------------------------------------
// Drop-in replacement for the previous Final_Top_Script: same indicator name,
// and the old "Fast Length" / "Slow Length" / "Show Background Zone" inputs are
// kept (the old 50 is now "Mid Length"; a 20 "Fast Length" was added).
//
//   * Fast / Mid / Slow MAs (20 / 50 / 200 EMA by default). The Slow line is
//     green while Mid > Slow and red otherwise; the Mid-Slow band is filled in
//     the same colour.
//   * Scored signals on every Fast x Mid cross: "Bullish +N" / "-N Bearish".
//     N = 1 for the cross, +1 if the MACD histogram agrees, +1 if price is on
//     the right side of the Slow MA, (+1 if RSI agrees -- off by default).
//   * RSI-extreme columns (RSI >= 75 = green, <= 25 = red), an optional regime
//     background zone, and a dashed line from the last signal to the extreme
//     printed since it.
//   * Key levels: ATH / ATL of the loaded history, yearly opens ("2026 Y.O"),
//     range High / Low, up to six named manual levels and two shaded zones,
//     and automatic pivot support / resistance (green below price, red above,
//     grey once broken). Every level prints as a native label on the price
//     scale (plot with display.price_scale) -- no clipped tags in the margin.
//     Levels further than `maxDist` % from price are hidden so an all-time low
//     near zero cannot squash the scale.
//   * A Long / Short position box (profit box + red stop box) with an
//     Entry / SL / TP1 / TP2 / TP3 ladder, taken from the last signal (if it is
//     recent) or typed in by hand to mirror a posted call. The auto stop is
//     capped at `maxStopPct` (AUTO MODE ONLY -- a Manual box with mSL = 0 uses an
//     uncapped ATR stop), and targets are floored at 5% of entry, not at zero.
//     That floor is unreachable in Auto: the 15% stop cap bounds risk at
//     0.15 * entry, and reaching the floor at r3 = 3 needs risk > 0.3167 * entry.
//
// v5.3 (2026-09-09): RE10140 again (68). The real rule: a plot with a const
// colour = 1 slot, an input or series colour = 2. Axis labels now use literal
// colours and the pivot / manual level axis labels are gone. ~31 slots.
// v5.2 (2026-09-09): chart title 'Vivek 5.0 Top' -- the owner's chart was
// still attached to a v1 copy saved under the shared name Final_Top_Script.
// v5.1 (2026-09-09): RE10140 'too many plots (71), limit 64' on the first paste
// of v5 -- a series colour costs extra plot slots. Price-scale labels now use
// fixed colours, the two column layers share one bgcolor, High/Low labels
// dropped (their lines stay). Worst-case count is now well under the limit.
// v5 (2026-09-09): REVERSAL BOX -- the counter-trend call in all four 5.0 charts
// (short the pump at an RSI extreme: stop above the high, target at the old
// low). Auto-drawn from the current close while RSI is at an extreme.
// v4 (2026-09-09): Entry / SL / TP tags drawn INSIDE the pane (the owner's chart
// hides price-scale labels, so v2's display.price_scale plots showed nothing).
// v3 (2026-09-09): a KEY table pinned to a chart corner (legend + live rows).
// v2 changes (2026-09-09, after the first live paste): Background Zone off by
// default, RSI columns at the extremes only, price-scale labels instead of
// margin tags, level distance filter, stop cap + freshness limit on the auto
// trade box, inputs hidden from the status line (display.none).
//
// Chart template only: nothing in the scanner reads this file.
// See tradingview/README.md for the chart settings that complete the look.
// =============================================================================
// Titled "Vivek 5.0 Top" (not Final_Top_Script) since v5.2: the owner's
// TradingView ended up with several saved scripts under the old name and the
// chart kept attaching to the v1 copy. A distinct title makes the running
// version obvious on the chart header.
indicator("Vivek 5.0 Top", shorttitle = "Vivek 5.0 Top", overlay = true,
     max_lines_count = 500, max_labels_count = 500, max_boxes_count = 500)

// ---------------------------------------------------------------- inputs ----
// Only the three lengths and the MA type show in the status line.
gMA = "Moving averages"
fastLen   = input.int(20,  "Fast Length", minval = 1, group = gMA)
midLen    = input.int(50,  "Mid Length",  minval = 1, group = gMA)
slowLen   = input.int(200, "Slow Length", minval = 1, group = gMA)
maType    = input.string("EMA", "MA type", options = ["EMA", "SMA"], group = gMA)
maSrc     = input.source(close, "Source", group = gMA, display = display.none)
cFast     = input.color(#5b8cff, "Fast", group = gMA, inline = "c1")
cMid      = input.color(#2f4bd8, "Mid",  group = gMA, inline = "c1")
cSlowBull = input.color(#22c55e, "Slow bull", group = gMA, inline = "c2")
cSlowBear = input.color(#ef4444, "Slow bear", group = gMA, inline = "c2")
showFill  = input.bool(true, "Fill the Mid-Slow band", group = gMA, display = display.none)
fillTr    = input.int(82, "Band transparency", minval = 0, maxval = 100, group = gMA, display = display.none)
showXLbl  = input.bool(false, "Label Mid x Slow crosses (BULLISH / BEARISH)", group = gMA, display = display.none)

gBG = "Background"
showBg      = input.bool(false, "Show Background Zone", group = gBG, display = display.none)
bgTr        = input.int(94, "Zone transparency", minval = 0, maxval = 100, group = gBG, display = display.none)
showRsiCols = input.bool(true, "RSI extreme columns (overbought = green, oversold = red)", group = gBG, display = display.none)
rsiLen      = input.int(14, "RSI length", minval = 1, group = gBG, display = display.none)
rsiOB       = input.float(75, "RSI overbought", group = gBG, display = display.none)
rsiOS       = input.float(25, "RSI oversold", group = gBG, display = display.none)
colTr       = input.int(85, "Column transparency", minval = 0, maxval = 100, group = gBG, display = display.none)

gSig = "Signals (Fast x Mid cross, scored)"
showSig   = input.bool(true, "Show Bullish / Bearish signals", group = gSig, display = display.none)
useMacd   = input.bool(true, "+1 when the MACD histogram agrees", group = gSig, display = display.none)
useSlow   = input.bool(true, "+1 when price is on the right side of the Slow MA", group = gSig, display = display.none)
useRsi    = input.bool(false, "+1 when RSI agrees (> 50 / < 50)", group = gSig, display = display.none)
minScore  = input.int(1, "Minimum score to show", minval = 1, maxval = 4, group = gSig, display = display.none)
boxedSig  = input.bool(false, "Boxed signal labels", group = gSig, display = display.none)
sigCols   = input.bool(false, "Column on signal bars", group = gSig, display = display.none)
showTrend = input.bool(true, "Dashed line: last signal to the extreme since", group = gSig, display = display.none)
cBull     = input.color(#3b82f6, "Bullish", group = gSig, inline = "sc")
cBear     = input.color(#ef4444, "Bearish", group = gSig, inline = "sc")
macdFast  = input.int(12, "MACD fast", minval = 1, group = gSig, inline = "m", display = display.none)
macdSlow  = input.int(26, "slow",      minval = 1, group = gSig, inline = "m", display = display.none)
macdSig   = input.int(9,  "signal",    minval = 1, group = gSig, inline = "m", display = display.none)

gLv = "Key levels"
maxDist   = input.float(100, "Hide a level further than this % from price (0 = show all)", minval = 0, group = gLv, display = display.none)
lblOff    = input.int(5, "Tag / name offset (bars right of the last bar)", minval = 0, maxval = 100, group = gLv, display = display.none)
tagTrade  = input.bool(true, "Tags inside the chart for Entry / SL / TP1-3", group = gLv, display = display.none)
tagLevels = input.bool(false, "Tags inside the chart for every level", group = gLv, display = display.none)
showATH   = input.bool(true, "ATH / ATL of the loaded history", group = gLv, display = display.none)
showYO    = input.bool(true, "Yearly opens", group = gLv, display = display.none)
yoCount   = input.int(2, "Yearly opens to show (this year first)", minval = 1, maxval = 3, group = gLv, display = display.none)
showRange = input.bool(false, "Range High / Low", group = gLv, display = display.none)
rangeLen  = input.int(100, "Range lookback (bars)", minval = 2, group = gLv, display = display.none)
cLevel    = input.color(#22c55e, "Level line", group = gLv, inline = "lc")
cName     = input.color(#f59e0b, "Level name", group = gLv, inline = "lc")

gMan = "Manual levels (0 = off)"
m1p = input.float(0, "Level 1", group = gMan, inline = "m1", display = display.none)
m1n = input.string("", "name", group = gMan, inline = "m1", display = display.none)
m2p = input.float(0, "Level 2", group = gMan, inline = "m2", display = display.none)
m2n = input.string("", "name", group = gMan, inline = "m2", display = display.none)
m3p = input.float(0, "Level 3", group = gMan, inline = "m3", display = display.none)
m3n = input.string("", "name", group = gMan, inline = "m3", display = display.none)
m4p = input.float(0, "Level 4", group = gMan, inline = "m4", display = display.none)
m4n = input.string("", "name", group = gMan, inline = "m4", display = display.none)
m5p = input.float(0, "Level 5", group = gMan, inline = "m5", display = display.none)
m5n = input.string("", "name", group = gMan, inline = "m5", display = display.none)
m6p = input.float(0, "Level 6", group = gMan, inline = "m6", display = display.none)
m6n = input.string("", "name", group = gMan, inline = "m6", display = display.none)

gZn = "Manual zones (0 = off)"
z1t = input.float(0, "Zone 1 top", group = gZn, inline = "z1", display = display.none)
z1b = input.float(0, "bottom",     group = gZn, inline = "z1", display = display.none)
z1n = input.string("", "name",     group = gZn, inline = "z1", display = display.none)
z1c = input.color(color.new(#06b6d4, 70), "Zone 1 colour", group = gZn)
z2t = input.float(0, "Zone 2 top", group = gZn, inline = "z2", display = display.none)
z2b = input.float(0, "bottom",     group = gZn, inline = "z2", display = display.none)
z2n = input.string("", "name",     group = gZn, inline = "z2", display = display.none)
z2c = input.color(color.new(#a855f7, 70), "Zone 2 colour", group = gZn)

gSR = "Auto support / resistance (pivots)"
showSR  = input.bool(true, "Show pivot levels", group = gSR, display = display.none)
pivLen  = input.int(10, "Pivot strength (bars each side)", minval = 1, group = gSR, display = display.none)
maxSR   = input.int(3, "Levels per side (max 3)", minval = 1, maxval = 3, group = gSR, display = display.none)
cRes    = input.color(#ef4444, "Resistance", group = gSR, inline = "sr")
cSup    = input.color(#22c55e, "Support",    group = gSR, inline = "sr")
cBroken = input.color(#6b7280, "Broken",     group = gSR, inline = "sr")

gTr = "Trade box (Long / Short position)"
trMode     = input.string("Auto (last signal)", "Mode", options = ["Off", "Auto (last signal)", "Manual"], group = gTr, display = display.none)
autoMaxAge = input.int(60, "Auto: only if the signal is within (bars)", minval = 1, group = gTr, display = display.none)
slMode     = input.string("Swing", "Auto stop", options = ["Swing", "ATR"], group = gTr, display = display.none)
swingLen   = input.int(5, "Swing lookback (bars)", minval = 1, group = gTr, display = display.none)
atrMult    = input.float(1.5, "ATR multiple (ATR stop)", minval = 0.1, step = 0.1, group = gTr, display = display.none)
atrPad     = input.float(0.25, "ATR pad beyond the swing", minval = 0, step = 0.05, group = gTr, display = display.none)
maxStopPct = input.float(15, "Auto: max stop distance (% of entry, 0 = off)", minval = 0, step = 1, group = gTr, display = display.none)
r1         = input.float(1.0, "TP1 (R)", minval = 0.1, step = 0.1, group = gTr, inline = "r", display = display.none)
r2         = input.float(2.0, "TP2 (R)", minval = 0.1, step = 0.1, group = gTr, inline = "r", display = display.none)
r3         = input.float(3.0, "TP3 (R)", minval = 0.1, step = 0.1, group = gTr, inline = "r", display = display.none)
extendBars = input.int(30, "Extend the box right (bars)", minval = 1, maxval = 400, group = gTr, display = display.none)
trDir      = input.string("Long", "Manual: direction", options = ["Long", "Short"], group = gTr, display = display.none)
mEntry     = input.float(0, "Manual: entry (0 = last close)", group = gTr, display = display.none)
mSL        = input.float(0, "Manual: SL (0 = ATR stop)", group = gTr, display = display.none)
mTP1       = input.float(0, "Manual: TP1 (0 = R multiple)", group = gTr, display = display.none)
mTP2       = input.float(0, "Manual: TP2 (0 = R multiple)", group = gTr, display = display.none)
mTP3       = input.float(0, "Manual: TP3 (0 = R multiple)", group = gTr, display = display.none)
mStart     = input.int(10, "Manual: box starts (bars ago)", minval = 0, group = gTr, display = display.none)
cProfitL   = input.color(#22c55e, "Long profit",  group = gTr, inline = "tc")
cProfitS   = input.color(#3b82f6, "Short profit", group = gTr, inline = "tc")
cStop      = input.color(#ef4444, "Stop",  group = gTr, inline = "tc")
cEntry     = input.color(#9ca3af, "Entry", group = gTr, inline = "tc")

gRev = "Reversal box (RSI extreme, counter-trend, 5.0-style)"
revOn     = input.bool(true, "Draw a counter-trend box while RSI is at an extreme", group = gRev, display = display.none)
revLook   = input.int(30, "Structure lookback (bars): target = opposite swing, stop = swing + pad", minval = 2, group = gRev, display = display.none)
revPad    = input.float(1.0, "ATR pad beyond the swing for the stop", minval = 0, step = 0.25, group = gRev, display = display.none)
revMaxAge = input.int(60, "Keep the box for (bars) after RSI leaves the zone", minval = 1, group = gRev, display = display.none)
revHide   = input.bool(true, "Hide the trend box while a reversal box is active", group = gRev, display = display.none)

gKey = "Key (legend in a chart corner)"
showKey = input.bool(true, "Show the key", group = gKey, display = display.none)
keyPos  = input.string("Top left", "Corner", options = ["Top left", "Top right", "Bottom left", "Bottom right"], group = gKey, display = display.none)
keySize = input.string("small", "Text size", options = ["tiny", "small", "normal"], group = gKey, display = display.none)
keyLive = input.bool(true, "Live rows (trend now, last signal, trade now)", group = gKey, display = display.none)

// --------------------------------------------------------------- helpers ----
// Both MAs are computed every bar so the ta.* history stays consistent
// whichever type is selected.
f_ma(s, len) =>
    e = ta.ema(s, len)
    m = ta.sma(s, len)
    maType == "EMA" ? e : m

// a level is "near" when it sits between price / (1 + d) and price * (1 + d)
f_near(p) =>
    maxDist == 0 or (not na(p) and p > 0 and p / close <= 1 + maxDist / 100 and close / p <= 1 + maxDist / 100)

f_px(price) =>
    str.tostring(price, format.mintick)

// ----------------------------------------------------------------- calcs ----
maFast  = f_ma(maSrc, fastLen)
maMid   = f_ma(maSrc, midLen)
maSlow  = f_ma(maSrc, slowLen)
regime  = maMid > maSlow
slowCol = regime ? cSlowBull : cSlowBear

rsiV = ta.rsi(close, rsiLen)
atrV = ta.atr(14)
[macdLine, macdSignal, macdHist] = ta.macd(close, macdFast, macdSlow, macdSig)
swLo = ta.lowest(low, swingLen)
swHi = ta.highest(high, swingLen)
rHi  = ta.highest(high, rangeLen)
rLo  = ta.lowest(low, rangeLen)

bullX = ta.crossover(maFast, maMid)
bearX = ta.crossunder(maFast, maMid)
goldX = ta.crossover(maMid, maSlow)
deadX = ta.crossunder(maMid, maSlow)

bullScore = 1 + (useMacd and macdHist > 0 ? 1 : 0) + (useSlow and close > maSlow ? 1 : 0) + (useRsi and rsiV > 50 ? 1 : 0)
bearScore = 1 + (useMacd and macdHist < 0 ? 1 : 0) + (useSlow and close < maSlow ? 1 : 0) + (useRsi and rsiV < 50 ? 1 : 0)
bullSig   = showSig and bullX and bullScore >= minScore
bearSig   = showSig and bearX and bearScore >= minScore

// all-time high / low of whatever history the chart has loaded
var float ath = na
var float atl = na
ath := na(ath) ? high : math.max(ath, high)
atl := na(atl) ? low  : math.min(atl, low)

// yearly opens (lookahead on is safe for `open`: it is known at the year start)
yo0 = request.security(syminfo.tickerid, "12M", open,    lookahead = barmerge.lookahead_on)
yo1 = request.security(syminfo.tickerid, "12M", open[1], lookahead = barmerge.lookahead_on)
yo2 = request.security(syminfo.tickerid, "12M", open[2], lookahead = barmerge.lookahead_on)
yYr = request.security(syminfo.tickerid, "12M", year,    lookahead = barmerge.lookahead_on)

// pivot support / resistance memory (newest first, at most three a side)
ph = ta.pivothigh(high, pivLen, pivLen)
pl = ta.pivotlow(low, pivLen, pivLen)
var phP = array.new<float>()
var phB = array.new<int>()
var plP = array.new<float>()
var plB = array.new<int>()
if not na(ph)
    array.unshift(phP, ph)
    array.unshift(phB, bar_index - pivLen)
    if array.size(phP) > maxSR
        array.pop(phP)
        array.pop(phB)
if not na(pl)
    array.unshift(plP, pl)
    array.unshift(plB, bar_index - pivLen)
    if array.size(plP) > maxSR
        array.pop(plP)
        array.pop(plB)

// last signal memory: where it fired, its stop, and the extreme printed since
var int   sigBar   = na
var int   sigDir   = 0
var int   sigScore = 0
var float sigPx    = na
var float sigEntry = na
var float sigStop  = na
var float extPx    = na
var int   extBar   = na
if bullSig or bearSig
    sigBar   := bar_index
    sigDir   := bullSig ? 1 : -1
    sigScore := bullSig ? bullScore : bearScore
    sigPx    := bullSig ? low : high
    sigEntry := close
    atrStop   = bullSig ? close - atrV * atrMult : close + atrV * atrMult
    swStop    = bullSig ? swLo - atrV * atrPad : swHi + atrV * atrPad
    sigStop  := slMode == "ATR" ? atrStop : swStop
    extPx    := bullSig ? high : low
    extBar   := bar_index
else if sigDir == 1 and not na(extPx) and high > extPx
    extPx  := high
    extBar := bar_index
else if sigDir == -1 and not na(extPx) and low < extPx
    extPx  := low
    extBar := bar_index
sigFresh = not na(sigBar) and bar_index - sigBar <= autoMaxAge

// reversal box: while RSI sits at an extreme the box re-anchors to the current
// bar (entry = close, stop = swing + pad, target = the opposite swing); once
// RSI leaves the zone it freezes and stays until the stop or the target
// prints, or revMaxAge bars pass
inOB  = rsiV >= rsiOB
inOS  = rsiV <= rsiOS
revHH = ta.highest(high, revLook)
revLL = ta.lowest(low, revLook)
var int   rvDir = 0
var int   rvBar = na
var float rvEnt = na
var float rvStp = na
var float rvTgt = na
var int   rvOff = na
if revOn and inOB
    rvDir := -1
    rvBar := bar_index
    rvEnt := close
    rvStp := revHH + atrV * revPad
    rvTgt := revLL
    rvOff := na
else if revOn and inOS
    rvDir := 1
    rvBar := bar_index
    rvEnt := close
    rvStp := revLL - atrV * revPad
    rvTgt := revHH
    rvOff := na
else if rvDir != 0
    if na(rvOff)
        rvOff := bar_index
    rvHit = rvDir == -1 ? (high >= rvStp or low <= rvTgt) : (low <= rvStp or high >= rvTgt)
    if rvHit or bar_index - rvOff > revMaxAge
        rvDir := 0
rvActive = revOn and rvDir != 0
rvRisk   = math.abs(rvEnt - rvStp)
rvTp1    = rvEnt + rvDir * rvRisk
rvTp2    = rvEnt + rvDir * rvRisk * 2
rvTp1In  = rvDir == -1 ? rvTp1 > rvTgt : rvTp1 < rvTgt
rvTp2In  = rvDir == -1 ? rvTp2 > rvTgt : rvTp2 < rvTgt
rvCol    = rvDir == 1 ? cProfitL : cProfitS
revNew   = (inOB and not inOB[1]) or (inOS and not inOS[1])

// key levels, filtered by distance from price (na = not shown)
lvlATH = showATH and f_near(ath) ? ath : na
lvlATL = showATH and f_near(atl) ? atl : na
lvlYO0 = showYO and yoCount >= 1 and f_near(yo0) ? yo0 : na
lvlYO1 = showYO and yoCount >= 2 and f_near(yo1) ? yo1 : na
lvlYO2 = showYO and yoCount >= 3 and f_near(yo2) ? yo2 : na
lvlHi  = showRange ? rHi : na
lvlLo  = showRange ? rLo : na
lvlM1  = m1p > 0 and f_near(m1p) ? m1p : na
lvlM2  = m2p > 0 and f_near(m2p) ? m2p : na
lvlM3  = m3p > 0 and f_near(m3p) ? m3p : na
lvlM4  = m4p > 0 and f_near(m4p) ? m4p : na
lvlM5  = m5p > 0 and f_near(m5p) ? m5p : na
lvlM6  = m6p > 0 and f_near(m6p) ? m6p : na

// trade box: entry / stop / targets (na when there is nothing to show)
tDir   = trMode == "Manual" ? (trDir == "Long" ? 1 : -1) : sigDir
tFresh = trMode == "Manual" or sigFresh
tShow  = trMode != "Off" and tDir != 0 and tFresh and not (revHide and rvActive)
entRaw = trMode == "Manual" ? (mEntry > 0 ? mEntry : close) : sigEntry
atrStp = tDir == 1 ? entRaw - atrV * atrMult : entRaw + atrV * atrMult
stpRaw = trMode == "Manual" ? (mSL > 0 ? mSL : atrStp) : sigStop
capD   = entRaw * maxStopPct / 100
stpCap = maxStopPct <= 0 ? stpRaw : tDir == 1 ? math.max(stpRaw, entRaw - capD) : math.min(stpRaw, entRaw + capD)
stp    = trMode == "Manual" ? stpRaw : stpCap
risk   = math.abs(entRaw - stp)
tp1    = trMode == "Manual" and mTP1 > 0 ? mTP1 : math.max(entRaw + tDir * risk * r1, entRaw * 0.05)
tp2    = trMode == "Manual" and mTP2 > 0 ? mTP2 : math.max(entRaw + tDir * risk * r2, entRaw * 0.05)
tp3    = trMode == "Manual" and mTP3 > 0 ? mTP3 : math.max(entRaw + tDir * risk * r3, entRaw * 0.05)
pc     = tDir == 1 ? cProfitL : cProfitS
tEnt   = tShow ? entRaw : na
tStp   = tShow ? stp : na
tTp1   = tShow ? tp1 : na
tTp2   = tShow ? tp2 : na
tTp3   = tShow ? tp3 : na

// ----------------------------------------------------------------- plots ----
pFast = plot(maFast, "Fast MA", color = cFast,   linewidth = 1)
pMid  = plot(maMid,  "Mid MA",  color = cMid,    linewidth = 2)
pSlow = plot(maSlow, "Slow MA", color = slowCol, linewidth = 3)
fill(pMid, pSlow, color = showFill ? color.new(slowCol, fillTr) : na, title = "Mid-Slow band")

bgcolor(showBg ? color.new(slowCol, bgTr) : na, title = "Background Zone")
rsiCol = rsiV >= rsiOB ? color.new(cSlowBull, colTr) : rsiV <= rsiOS ? color.new(cBear, colTr) : na
sigCol = bullSig ? color.new(cBull, colTr) : bearSig ? color.new(cBear, colTr) : na
colCol = showRsiCols and not na(rsiCol) ? rsiCol : sigCols ? sigCol : na
bgcolor(colCol, title = "Columns (RSI extreme / signal)")

plotshape(bullSig, title = "Bullish arrow", style = shape.arrowup,   location = location.belowbar, color = cBull, size = size.small, display = display.pane)
plotshape(bearSig, title = "Bearish arrow", style = shape.arrowdown, location = location.abovebar, color = cBear, size = size.small, display = display.pane)

// price-scale labels only (no line drawn by the plot; lines are drawn below).
// LITERAL colours on purpose: TradingView charges ONE plot slot for a plot
// whose colour is a compile-time constant and TWO for anything stronger --
// an input colour included. v5 (71) and v5.2 (68) both tripped the 64 limit
// on exactly that. Pivot / manual levels have no axis label any more; their
// lines, names and optional in-chart tags remain.
plot(lvlATH, "ATH", color = #22c55e, display = display.price_scale)
plot(lvlATL, "ATL", color = #22c55e, display = display.price_scale)
plot(lvlYO0, "Y.O this year",   color = #22c55e, display = display.price_scale)
plot(lvlYO1, "Y.O last year",   color = #22c55e, display = display.price_scale)
plot(lvlYO2, "Y.O 2 years ago", color = #22c55e, display = display.price_scale)
plot(tEnt, "Entry", color = #9ca3af, display = display.price_scale)
plot(tStp, "SL",    color = #ef4444, display = display.price_scale)
plot(tTp1, "TP1",   color = #22c55e, display = display.price_scale)
plot(tTp2, "TP2",   color = #22c55e, display = display.price_scale)
plot(tTp3, "TP3",   color = #22c55e, display = display.price_scale)
plot(rvActive ? rvEnt : na, "Rev entry",  color = #9ca3af, display = display.price_scale)
plot(rvActive ? rvStp : na, "Rev SL",     color = #ef4444, display = display.price_scale)
plot(rvActive ? rvTgt : na, "Rev target", color = #22c55e, display = display.price_scale)

if bullSig
    txt = "Bullish\n+" + str.tostring(bullScore)
    if boxedSig
        label.new(bar_index, low, txt, style = label.style_label_up, color = color.new(color.gray, 60), textcolor = cBull, size = size.small)
    else
        label.new(bar_index, low - atrV * 1.8, txt, style = label.style_none, textcolor = cBull, size = size.small)
if bearSig
    txt = "-" + str.tostring(bearScore) + "\nBearish"
    if boxedSig
        label.new(bar_index, high, txt, style = label.style_label_down, color = color.new(color.gray, 60), textcolor = cBear, size = size.small)
    else
        label.new(bar_index, high + atrV * 1.8, txt, style = label.style_none, textcolor = cBear, size = size.small)

if showXLbl and goldX
    label.new(bar_index, maSlow, "BULLISH", style = label.style_label_up,   color = cSlowBull, textcolor = color.white, size = size.small)
if showXLbl and deadX
    label.new(bar_index, maSlow, "BEARISH", style = label.style_label_down, color = cSlowBear, textcolor = color.white, size = size.small)

// ------------------------------------------------ last-bar drawings ---------
// Everything below is redrawn on the last bar only; the arrays hold the ids so
// the previous tick's objects can be removed first.
var lns = array.new<line>()
var lbs = array.new<label>()
var bxs = array.new<box>()

f_hline(price, col, sty, w) =>
    ln = line.new(bar_index - 1, price, bar_index, price, extend = extend.both, color = col, style = sty, width = w)
    array.push(lns, ln)

f_seg(x1, price, col, sty, w) =>
    ln = line.new(x1, price, bar_index + lblOff, price, color = col, style = sty, width = w)
    array.push(lns, ln)

// price tag drawn INSIDE the pane: the pointer is on the right and the box
// extends left, so it stays readable however small the chart's right margin
// is and whatever the price-scale label settings are
f_tag(price, txt, bg) =>
    lb = label.new(bar_index + lblOff, price, txt, style = label.style_label_right, color = color.new(bg, 10), textcolor = color.white, size = size.small)
    array.push(lbs, lb)

// name text floats one text-line above the level (the trailing newline lifts it)
f_name(price, txt) =>
    lb = label.new(bar_index + lblOff, price, txt + "\n", style = label.style_none, textcolor = cName, size = size.small)
    array.push(lbs, lb)

f_manual(p, n) =>
    if not na(p)
        f_hline(p, cLevel, line.style_solid, 1)
        if n != ""
            f_name(p, n)

f_zone(t, b, n, c) =>
    if t > 0 and b > 0 and t > b
        bx = box.new(bar_index - 1, t, bar_index, b, border_color = color.new(c, 40), bgcolor = c, extend = extend.both)
        array.push(bxs, bx)
        if n != ""
            f_name(t, n)

if barstate.islast
    for ln in lns
        line.delete(ln)
    array.clear(lns)
    for lb in lbs
        label.delete(lb)
    array.clear(lbs)
    for bx in bxs
        box.delete(bx)
    array.clear(bxs)

    // dashed line from the last (recent) signal to the extreme printed since it
    if showTrend and sigFresh and not na(extBar)
        tl = line.new(sigBar, sigPx, extBar, extPx, color = color.new(cEntry, 20), style = line.style_dashed, width = 1)
        array.push(lns, tl)

    if not na(lvlATH)
        f_hline(lvlATH, cLevel, line.style_solid, 1)
        f_name(lvlATH, "ATH")
        if tagLevels
            f_tag(lvlATH, f_px(lvlATH), cLevel)
    if not na(lvlATL)
        f_hline(lvlATL, cLevel, line.style_solid, 1)
        f_name(lvlATL, "ATL")
        if tagLevels
            f_tag(lvlATL, f_px(lvlATL), cLevel)
    if not na(lvlYO0)
        f_hline(lvlYO0, color.new(cLevel, 30), line.style_solid, 1)
        f_name(lvlYO0, str.tostring(yYr) + " Y.O")
        if tagLevels
            f_tag(lvlYO0, f_px(lvlYO0), color.new(cLevel, 30))
    if not na(lvlYO1)
        f_hline(lvlYO1, color.new(cLevel, 30), line.style_solid, 1)
        f_name(lvlYO1, str.tostring(yYr - 1) + " Y.O")
        if tagLevels
            f_tag(lvlYO1, f_px(lvlYO1), color.new(cLevel, 30))
    if not na(lvlYO2)
        f_hline(lvlYO2, color.new(cLevel, 30), line.style_solid, 1)
        f_name(lvlYO2, str.tostring(yYr - 2) + " Y.O")
        if tagLevels
            f_tag(lvlYO2, f_px(lvlYO2), color.new(cLevel, 30))
    if not na(lvlHi)
        f_hline(lvlHi, color.new(cEntry, 30), line.style_dotted, 1)
    if not na(lvlLo)
        f_hline(lvlLo, color.new(cEntry, 30), line.style_dotted, 1)

    f_manual(lvlM1, m1n)
    f_manual(lvlM2, m2n)
    f_manual(lvlM3, m3n)
    f_manual(lvlM4, m4n)
    f_manual(lvlM5, m5n)
    f_manual(lvlM6, m6n)
    f_zone(z1t, z1b, z1n, z1c)
    f_zone(z2t, z2b, z2n, z2c)

    if showSR
        for [k, p] in phP
            if f_near(p)
                sb = array.get(phB, k)
                sc = close > p ? cBroken : cRes
                f_seg(sb, p, sc, line.style_solid, 1)
                if tagLevels
                    f_tag(p, f_px(p), sc)
        for [j, q] in plP
            if f_near(q)
                tb = array.get(plB, j)
                tc = close < q ? cBroken : cSup
                f_seg(tb, q, tc, line.style_solid, 1)
                if tagLevels
                    f_tag(q, f_px(q), tc)

    if tShow
        x1 = trMode == "Manual" ? math.max(bar_index - mStart, 0) : sigBar
        x2 = bar_index + extendBars
        bxP = box.new(x1, math.max(entRaw, tp3), x2, math.min(entRaw, tp3), border_color = color.new(pc, 50), bgcolor = color.new(pc, 80))
        bxS = box.new(x1, math.max(entRaw, stp), x2, math.min(entRaw, stp), border_color = color.new(cStop, 50), bgcolor = color.new(cStop, 80))
        array.push(bxs, bxP)
        array.push(bxs, bxS)
        ln1 = line.new(x1, tp1, x2, tp1, color = color.new(pc, 0), style = line.style_dashed, width = 1)
        ln2 = line.new(x1, tp2, x2, tp2, color = color.new(pc, 0), style = line.style_dashed, width = 1)
        ln3 = line.new(x1, entRaw, x2, entRaw, color = color.new(cEntry, 20), style = line.style_dashed, width = 1)
        array.push(lns, ln1)
        array.push(lns, ln2)
        array.push(lns, ln3)
        if tagTrade
            f_tag(stp, "SL " + f_px(stp), cStop)
            f_tag(entRaw, "Entry " + f_px(entRaw), cEntry)
            f_tag(tp1, "TP1 " + f_px(tp1), pc)
            f_tag(tp2, "TP2 " + f_px(tp2), pc)
            f_tag(tp3, "TP3 " + f_px(tp3), pc)

    if rvActive
        rx1 = rvBar
        rx2 = bar_index + extendBars
        rbP = box.new(rx1, math.max(rvEnt, rvTgt), rx2, math.min(rvEnt, rvTgt), border_color = color.new(rvCol, 50), bgcolor = color.new(rvCol, 80))
        rbS = box.new(rx1, math.max(rvEnt, rvStp), rx2, math.min(rvEnt, rvStp), border_color = color.new(cStop, 50), bgcolor = color.new(cStop, 80))
        array.push(bxs, rbP)
        array.push(bxs, rbS)
        rl0 = line.new(rx1, rvEnt, rx2, rvEnt, color = color.new(cEntry, 20), style = line.style_dashed, width = 1)
        array.push(lns, rl0)
        if rvTp1In
            rl1 = line.new(rx1, rvTp1, rx2, rvTp1, color = color.new(rvCol, 0), style = line.style_dashed, width = 1)
            array.push(lns, rl1)
            if tagTrade
                f_tag(rvTp1, "TP1 " + f_px(rvTp1), rvCol)
        if rvTp2In
            rl2 = line.new(rx1, rvTp2, rx2, rvTp2, color = color.new(rvCol, 0), style = line.style_dashed, width = 1)
            array.push(lns, rl2)
            if tagTrade
                f_tag(rvTp2, "TP2 " + f_px(rvTp2), rvCol)
        if tagTrade
            f_tag(rvStp, "SL " + f_px(rvStp), cStop)
            f_tag(rvEnt, (rvDir == -1 ? "SHORT " : "LONG ") + f_px(rvEnt), cEntry)
            f_tag(rvTgt, "Target " + f_px(rvTgt), rvCol)

// ------------------------------------------------------------------- key ----
// A legend pinned to a chart corner (a table never moves with the bars): what
// every mark means, plus three live rows -- trend now, last signal, and the
// current trade box written out the way a call is posted.
kPos = keyPos == "Top right" ? position.top_right : keyPos == "Bottom left" ? position.bottom_left : keyPos == "Bottom right" ? position.bottom_right : position.top_left
kSz  = keySize == "tiny" ? size.tiny : keySize == "normal" ? size.normal : size.small
var table key = showKey ? table.new(kPos, 2, 14, bgcolor = color.new(color.black, 25), frame_color = color.new(color.gray, 50), frame_width = 1, border_color = color.new(color.gray, 85), border_width = 1) : na

f_cell(r, c, txt, col) =>
    table.cell(key, c, r, txt, text_color = col, text_halign = text.align_left, text_size = kSz)

maxScore = 1 + (useMacd ? 1 : 0) + (useSlow ? 1 : 0) + (useRsi ? 1 : 0)
scoreTxt = "Score: 1 for the cross" + (useMacd ? ", +1 MACD agrees" : "") + (useSlow ? ", +1 price beyond Slow" : "") + (useRsi ? ", +1 RSI agrees" : "") + " (max " + str.tostring(maxScore) + ")"

if showKey and barstate.islast
    cW = color.new(color.white, 10)
    cG = color.new(color.gray, 0)
    lastTxt  = sigDir == 0 ? "none yet" : (sigDir == 1 ? "Bullish +" : "Bearish -") + str.tostring(sigScore) + ", " + str.tostring(bar_index - sigBar) + " bars ago" + (sigFresh ? "" : " (too old for a trade box)")
    revTxt   = (rvDir == -1 ? "SHORT (reversal, RSI " : "LONG (reversal, RSI ") + str.tostring(rsiV, "#") + ") entry " + f_px(rvEnt) + " / SL " + f_px(rvStp) + " / target " + f_px(rvTgt)
    tradeTxt = rvActive ? revTxt : tShow ? (tDir == 1 ? "LONG" : "SHORT") + " entry " + f_px(entRaw) + " / SL " + f_px(stp) + " / TP1 " + f_px(tp1) + " / TP2 " + f_px(tp2) + " / TP3 " + f_px(tp3) : trMode == "Off" ? "trade box is off" : "none (no signal in the last " + str.tostring(autoMaxAge) + " bars)"
    f_cell(0, 0, "KEY", cW)
    f_cell(0, 1, "Vivek 5.0 Top", cG)
    f_cell(1, 0, "Thin blue line", cFast)
    f_cell(1, 1, "Fast " + str.tostring(fastLen) + " " + maType, cW)
    f_cell(2, 0, "Thick blue line", cMid)
    f_cell(2, 1, "Mid " + str.tostring(midLen) + " " + maType, cW)
    f_cell(3, 0, "Thick green / red line", slowCol)
    f_cell(3, 1, "Slow " + str.tostring(slowLen) + " " + maType + ". Green = Mid above it (uptrend), red = Mid below it (downtrend). The band is the gap", cW)
    f_cell(4, 0, "Bullish +N  (blue arrow up)", cBull)
    f_cell(4, 1, "Fast crossed ABOVE Mid. " + scoreTxt, cW)
    f_cell(5, 0, "Bearish -N  (red arrow down)", cBear)
    f_cell(5, 1, "Fast crossed BELOW Mid. " + scoreTxt, cW)
    f_cell(6, 0, "Boxes", cW)
    f_cell(6, 1, "Green = long profit zone, blue = short profit zone (Entry to TP3). Red = stop zone (Entry to SL)", cW)
    f_cell(7, 0, "Price tags", cW)
    f_cell(7, 1, "TP1-3 = targets, SL = stop, Entry. R = resistance (red), S = support (green), grey = broken", cW)
    f_cell(8, 0, "Vertical columns", cW)
    f_cell(8, 1, "Green: RSI at or above " + str.tostring(rsiOB, "#") + " (overbought). Red: RSI at or below " + str.tostring(rsiOS, "#") + " (oversold)", cW)
    f_cell(9, 0, "Level lines", cName)
    f_cell(9, 1, "ATH / ATL = all-time high / low. Y.O = yearly open. Dashed = last signal to the extreme since", cW)
    f_cell(10, 0, "Reversal box", cProfitS)
    f_cell(10, 1, "RSI at or above " + str.tostring(rsiOB, "#") + " = SHORT box from the close (blue), at or below " + str.tostring(rsiOS, "#") + " = LONG box (green). SL = swing + ATR pad, target = the opposite swing", cW)
    if keyLive
        f_cell(11, 0, "Trend now", slowCol)
        f_cell(11, 1, regime ? "UP (Mid above Slow)" : "DOWN (Mid below Slow)", slowCol)
        f_cell(12, 0, "Last signal", sigDir == 1 ? cBull : sigDir == -1 ? cBear : cG)
        f_cell(12, 1, lastTxt, cW)
        f_cell(13, 0, "Trade now", rvActive ? rvCol : tShow ? pc : cG)
        f_cell(13, 1, tradeTxt, cW)

// ---------------------------------------------------------------- alerts ----
alertcondition(bullSig, title = "Bullish signal", message = "Final_Top_Script: Bullish Fast x Mid cross")
alertcondition(bearSig, title = "Bearish signal", message = "Final_Top_Script: Bearish Fast x Mid cross")
alertcondition(goldX,   title = "Golden cross",   message = "Final_Top_Script: Mid crossed above Slow")
alertcondition(deadX,   title = "Death cross",    message = "Final_Top_Script: Mid crossed below Slow")
alertcondition(revNew,  title = "RSI extreme",     message = "Final_Top_Script: RSI entered an extreme, reversal box drawn")
```

## 3.2 - `Final_Bottom_MACD.pine` (declared as "Vivek 5.0 MACD", 39 lines)

```pine
//@version=6
// =============================================================================
// Final_Bottom_MACD  --  the MACD pane of the 5.0 layout  (v2: inputs hidden from the status line)
// -----------------------------------------------------------------------------
// Standard 12 / 26 / 9 MACD with TradingView's four-shade histogram (strong /
// fading colour on each side of zero), blue MACD line, orange signal line, and
// optional columns on histogram zero-crosses (the moment the Top script's
// "+1 when the MACD histogram agrees" flips).
// Status line order is kept from the previous version: histogram, MACD, signal.
// =============================================================================
indicator("Vivek 5.0 MACD", shorttitle = "Vivek 5.0 MACD", overlay = false)

fastLen  = input.int(12, "Fast Length",   minval = 1, display = display.none)
slowLen  = input.int(26, "Slow Length",   minval = 1, display = display.none)
sigLen   = input.int(9,  "Signal Length", minval = 1, display = display.none)
src      = input.source(close, "Source", display = display.none)
cUp1     = input.color(#26a69a, "Hist above zero, rising",  inline = "u")
cUp2     = input.color(#b2dfdb, "falling",                  inline = "u")
cDn1     = input.color(#ef5350, "Hist below zero, falling", inline = "d")
cDn2     = input.color(#ffcdd2, "rising",                   inline = "d")
cMacd    = input.color(#2962ff, "MACD",   inline = "l")
cSig     = input.color(#ff6d00, "Signal", inline = "l")
zeroCols = input.bool(false, "Column on histogram zero-cross", display = display.none)

[macdLine, sigLine, hist] = ta.macd(src, fastLen, slowLen, sigLen)
histCol = hist >= 0 ? (hist > nz(hist[1]) ? cUp1 : cUp2) : (hist < nz(hist[1]) ? cDn1 : cDn2)

plot(hist,     "Histogram", color = histCol, style = plot.style_columns)
plot(macdLine, "MACD",      color = cMacd, linewidth = 2)
plot(sigLine,  "Signal",    color = cSig,  linewidth = 2)
hline(0, "Zero", color = color.new(color.gray, 50), linestyle = hline.style_dashed)

xUp = ta.crossover(hist, 0)
xDn = ta.crossunder(hist, 0)
zc  = xUp ? color.new(cUp1, 75) : xDn ? color.new(cDn1, 75) : na
bgcolor(zeroCols ? zc : na, title = "Zero-cross columns")

alertcondition(xUp, title = "MACD histogram above zero", message = "Vivek 5.0 MACD: histogram crossed above zero")
alertcondition(xDn, title = "MACD histogram below zero", message = "Vivek 5.0 MACD: histogram crossed below zero")
```

## 3.3 - `Final_RSI_Plus.pine` (declared as "Vivek 5.0 RSI+", 92 lines)

```pine
//@version=6
// =============================================================================
// Final_RSI_Plus  --  the "RSI+" pane of the 5.0 layout  (v2: inputs hidden from the status line)
// -----------------------------------------------------------------------------
// RSI with a smoothing MA and a blue / red fill between them (blue while RSI is
// above its MA), 70 / 75 and 30 / 25 bands, a long-run RSI average, vertical
// columns on the extremes (overbought = blue, oversold = red) and regular
// bull / bear divergence marks.
// Status line: RSI, MA, 70, 75, 30, 25, 50, bull div, bear div, long average --
// the two divergence values print as the empty-set symbol when there is none,
// exactly as the reference pane does.
// =============================================================================
indicator("Vivek 5.0 RSI+", shorttitle = "Vivek 5.0 RSI+", overlay = false)

rsiLen      = input.int(14, "RSI Length", minval = 1, display = display.none)
rsiSrc      = input.source(close, "Source", display = display.none)
maLen       = input.int(14, "MA Length", minval = 1, display = display.none)
maType      = input.string("SMA", "MA Type", options = ["SMA", "EMA"], display = display.none)
longLen     = input.int(50, "Long-run average length", minval = 1, display = display.none)
ob1         = input.float(70, "Overbought", inline = "ob", display = display.none)
ob2         = input.float(75, "extreme",    inline = "ob", display = display.none)
os1         = input.float(30, "Oversold",   inline = "os", display = display.none)
os2         = input.float(25, "extreme",    inline = "os", display = display.none)
midL        = input.float(50, "Midline", display = display.none)
showCols    = input.bool(true, "Columns on the extremes (overbought = blue, oversold = red)", display = display.none)
showMidCols = input.bool(false, "Grey column when RSI crosses the midline", display = display.none)
showDiv     = input.bool(true, "Regular divergences", display = display.none)
lbL         = input.int(5,  "Pivot lookback left",  minval = 1, display = display.none)
lbR         = input.int(5,  "Pivot lookback right", minval = 1, display = display.none)
rangeUpper  = input.int(60, "Max bars between pivots", minval = 1, display = display.none)
rangeLower  = input.int(5,  "Min bars between pivots", minval = 1, display = display.none)
cRsi        = input.color(#dbe4ff, "RSI", inline = "c")
cMa         = input.color(#f59e0b, "MA",  inline = "c")
cUp         = input.color(#3b82f6, "Above MA / overbought", inline = "c2")
cDn         = input.color(#ef4444, "Below MA / oversold",   inline = "c2")

rsi     = ta.rsi(rsiSrc, rsiLen)
maS     = ta.sma(rsi, maLen)
maE     = ta.ema(rsi, maLen)
rsiMa   = maType == "EMA" ? maE : maS
longAvg = ta.sma(rsi, longLen)

// --- divergences (regular only), pivots on the RSI itself --------------------
plFound = not na(ta.pivotlow(rsi, lbL, lbR))
phFound = not na(ta.pivothigh(rsi, lbL, lbR))

f_inRange(cond) =>
    bars = ta.barssince(cond == true)
    rangeLower <= bars and bars <= rangeUpper

// evaluated unconditionally every bar: v6 `and` short-circuits, and a
// ta.barssince() that only sometimes runs keeps a broken history
inRangeL = f_inRange(plFound[1])
inRangeH = f_inRange(phFound[1])

rsiHL   = rsi[lbR] > ta.valuewhen(plFound, rsi[lbR], 1)
priceLL = low[lbR] < ta.valuewhen(plFound, low[lbR], 1)
bullDiv = showDiv and plFound and priceLL and rsiHL and inRangeL

rsiLH   = rsi[lbR] < ta.valuewhen(phFound, rsi[lbR], 1)
priceHH = high[lbR] > ta.valuewhen(phFound, high[lbR], 1)
bearDiv = showDiv and phFound and priceHH and rsiLH and inRangeH

// --- plots (order = status line order) ---------------------------------------
pR   = plot(rsi,   "RSI",    color = cRsi, linewidth = 2)
pM   = plot(rsiMa, "RSI MA", color = color.new(cMa, 50), linewidth = 1)
pOb1 = plot(ob1, "Overbought",  color = color.new(cUp, 60))
pOb2 = plot(ob2, "OB extreme",  color = color.new(cUp, 80))
pOs1 = plot(os1, "Oversold",    color = color.new(cDn, 60))
pOs2 = plot(os2, "OS extreme",  color = color.new(cDn, 80))
plot(midL, "Midline", color = color.new(color.gray, 50))
fill(pR, pM, color = rsi >= rsiMa ? color.new(cUp, 65) : color.new(cDn, 65), title = "RSI vs MA")
fill(pOb1, pOb2, color = color.new(cUp, 88), title = "Overbought band")
fill(pOs1, pOs2, color = color.new(cDn, 88), title = "Oversold band")

plot(bullDiv ? rsi[lbR] : na, "Bull Div", color = cUp, style = plot.style_circles, linewidth = 3, offset = -lbR)
plot(bearDiv ? rsi[lbR] : na, "Bear Div", color = cDn, style = plot.style_circles, linewidth = 3, offset = -lbR)
plotshape(bullDiv ? rsi[lbR] : na, "Bull Div label", style = shape.labelup,   location = location.absolute, color = cUp, textcolor = color.white, text = "Bull", offset = -lbR, size = size.tiny, display = display.pane)
plotshape(bearDiv ? rsi[lbR] : na, "Bear Div label", style = shape.labeldown, location = location.absolute, color = cDn, textcolor = color.white, text = "Bear", offset = -lbR, size = size.tiny, display = display.pane)
plot(longAvg, "Long-run average", color = color.new(color.gray, 30), linewidth = 1)

// --- columns -----------------------------------------------------------------
extCol = rsi >= ob2 ? color.new(cUp, 75) : rsi <= os2 ? color.new(cDn, 75) : na
bgcolor(showCols ? extCol : na, title = "Extreme columns")
midX = ta.cross(rsi, midL)
bgcolor(showMidCols and midX ? color.new(color.gray, 80) : na, title = "Midline cross column")

// --- alerts ------------------------------------------------------------------
alertcondition(bullDiv, title = "Bullish divergence", message = "Vivek 5.0 RSI+: regular bullish divergence")
alertcondition(bearDiv, title = "Bearish divergence", message = "Vivek 5.0 RSI+: regular bearish divergence")
alertcondition(ta.crossover(rsi, ob1),  title = "RSI entered overbought", message = "Vivek 5.0 RSI+: RSI crossed above overbought")
alertcondition(ta.crossunder(rsi, os1), title = "RSI entered oversold",   message = "Vivek 5.0 RSI+: RSI crossed below oversold")
```


---

# PART 4 - COMPLETE RULE INVENTORY OF THE THREE SCRIPTS

Line-accurate transcription of every input, every computed quantity and every
drawn object in:

| File | `indicator()` title | Pane | Lines |
|---|---|---|---|
| `tradingview/Final_Top_Script.pine` | `Vivek 5.0 Top` (shorttitle same) | price overlay (`overlay = true`) | 624 |
| `tradingview/Final_Bottom_MACD.pine` | `Vivek 5.0 MACD` | separate (`overlay = false`) | 39 |
| `tradingview/Final_RSI_Plus.pine` | `Vivek 5.0 RSI+` | separate (`overlay = false`) | 92 |

All three are `//@version=6`. Line numbers below are the real line numbers in
those files as they stand in the checkout (git HEAD, files last touched
2026-09-09). Verified: nothing in `scanner/`, `phasemap/`, `functions/`,
`public/js/` or `.github/workflows/` reads the `tradingview/` folder. The only
occurrences of the word "tradingview" elsewhere in the tree are outbound
`tradingview.com` chart links in `public/js/chart.js` and the embedded
TradingView calendar/news widgets in `public/js/sectors.js`. So these scripts
are a chart template and nothing else; they have no runtime relationship to the
scanner, and any scanner rule derived from them is a REIMPLEMENTATION, not a
read of shared code.

**The three scripts do not talk to each other.** Each is a separate
`indicator()`. The Top script computes its own MACD (line 206) and its own RSI
(line 204) internally rather than reading the MACD or RSI+ panes. So a scanner
combining "Top score" with "RSI+ divergence" is doing something no single script
on the chart does; it must compute both itself.

`indicator()` resource limits, Top script only (lines 57-58):
`max_lines_count = 500`, `max_labels_count = 500`, `max_boxes_count = 500`.

---

## 0. How to read the "repaint / knowable" column

Three distinct properties get conflated as "repaint". They are separated
throughout this document:

1. **Live-bar mutation.** Every quantity derived from `close`, `high`, `low` of
   the bar currently forming changes tick by tick and can flip a boolean on and
   off within the session. This affects EVERY series in all three scripts. It is
   irrelevant to a scanner that evaluates only CLOSED daily bars, which is what
   the target scanner does.
2. **Retroactive change to a closed bar.** A value computed on bar T that later
   changes. Nothing in these three scripts does this, with the two exceptions
   noted below (`ath`/`atl` depend on how much chart history is loaded;
   `request.security(..., "12M", ..., lookahead_on)` reads a higher timeframe
   with lookahead). Neither is used by Rule A or Rule B.
3. **Detection lag.** A value that is knowable only some bars after the bar it
   describes. `ta.pivotlow` / `ta.pivothigh` are the whole story here, and they
   are the reason the divergence rule has an off-by-five. See section 4.

"Knowable on bar X" below always means: the first CLOSED bar at which the value
is final and correct.

---

## 1. Inputs

### 1.1 `Final_Top_Script.pine` -- 100 inputs

Group string variables: `gMA` (L62) = "Moving averages", `gBG` (L76) =
"Background", `gSig` (L85) = "Signals (Fast x Mid cross, scored)", `gLv` (L100)
= "Key levels", `gMan` (L113) = "Manual levels (0 = off)", `gZn` (L127) =
"Manual zones (0 = off)", `gSR` (L137) = "Auto support / resistance (pivots)",
`gTr` (L145) = "Trade box (Long / Short position)", `gRev` (L169) = "Reversal
box (RSI extreme, counter-trend, 5.0-style)", `gKey` (L176) = "Key (legend in a
chart corner)".

"Hidden" = the call passes `display = display.none` (kept out of the chart
status line). Where the column says "SHOWN" the call passes no `display`
argument at all.

| L | Variable | Call | Default | Label | Group | Other args | Hidden |
|---|---|---|---|---|---|---|---|
| 63 | `fastLen` | `input.int` | `20` | "Fast Length" | gMA | `minval = 1` | SHOWN |
| 64 | `midLen` | `input.int` | `50` | "Mid Length" | gMA | `minval = 1` | SHOWN |
| 65 | `slowLen` | `input.int` | `200` | "Slow Length" | gMA | `minval = 1` | SHOWN |
| 66 | `maType` | `input.string` | `"EMA"` | "MA type" | gMA | `options = ["EMA","SMA"]` | SHOWN |
| 67 | `maSrc` | `input.source` | `close` | "Source" | gMA | | hidden |
| 68 | `cFast` | `input.color` | `#5b8cff` | "Fast" | gMA | `inline = "c1"` | SHOWN |
| 69 | `cMid` | `input.color` | `#2f4bd8` | "Mid" | gMA | `inline = "c1"` | SHOWN |
| 70 | `cSlowBull` | `input.color` | `#22c55e` | "Slow bull" | gMA | `inline = "c2"` | SHOWN |
| 71 | `cSlowBear` | `input.color` | `#ef4444` | "Slow bear" | gMA | `inline = "c2"` | SHOWN |
| 72 | `showFill` | `input.bool` | `true` | "Fill the Mid-Slow band" | gMA | | hidden |
| 73 | `fillTr` | `input.int` | `82` | "Band transparency" | gMA | `minval = 0, maxval = 100` | hidden |
| 74 | `showXLbl` | `input.bool` | `false` | "Label Mid x Slow crosses (BULLISH / BEARISH)" | gMA | | hidden |
| 77 | `showBg` | `input.bool` | `false` | "Show Background Zone" | gBG | | hidden |
| 78 | `bgTr` | `input.int` | `94` | "Zone transparency" | gBG | `minval = 0, maxval = 100` | hidden |
| 79 | `showRsiCols` | `input.bool` | `true` | "RSI extreme columns (overbought = green, oversold = red)" | gBG | | hidden |
| 80 | `rsiLen` | `input.int` | `14` | "RSI length" | gBG | `minval = 1` | hidden |
| 81 | `rsiOB` | `input.float` | `75` | "RSI overbought" | gBG | | hidden |
| 82 | `rsiOS` | `input.float` | `25` | "RSI oversold" | gBG | | hidden |
| 83 | `colTr` | `input.int` | `85` | "Column transparency" | gBG | `minval = 0, maxval = 100` | hidden |
| 86 | `showSig` | `input.bool` | `true` | "Show Bullish / Bearish signals" | gSig | | hidden |
| 87 | `useMacd` | `input.bool` | `true` | "+1 when the MACD histogram agrees" | gSig | | hidden |
| 88 | `useSlow` | `input.bool` | `true` | "+1 when price is on the right side of the Slow MA" | gSig | | hidden |
| 89 | `useRsi` | `input.bool` | **`false`** | "+1 when RSI agrees (> 50 / < 50)" | gSig | | hidden |
| 90 | `minScore` | `input.int` | `1` | "Minimum score to show" | gSig | `minval = 1, maxval = 4` | hidden |
| 91 | `boxedSig` | `input.bool` | `false` | "Boxed signal labels" | gSig | | hidden |
| 92 | `sigCols` | `input.bool` | `false` | "Column on signal bars" | gSig | | hidden |
| 93 | `showTrend` | `input.bool` | `true` | "Dashed line: last signal to the extreme since" | gSig | | hidden |
| 94 | `cBull` | `input.color` | `#3b82f6` | "Bullish" | gSig | `inline = "sc"` | SHOWN |
| 95 | `cBear` | `input.color` | `#ef4444` | "Bearish" | gSig | `inline = "sc"` | SHOWN |
| 96 | `macdFast` | `input.int` | `12` | "MACD fast" | gSig | `minval = 1, inline = "m"` | hidden |
| 97 | `macdSlow` | `input.int` | `26` | "slow" | gSig | `minval = 1, inline = "m"` | hidden |
| 98 | `macdSig` | `input.int` | `9` | "signal" | gSig | `minval = 1, inline = "m"` | hidden |
| 101 | `maxDist` | `input.float` | `100` | "Hide a level further than this % from price (0 = show all)" | gLv | `minval = 0` | hidden |
| 102 | `lblOff` | `input.int` | `5` | "Tag / name offset (bars right of the last bar)" | gLv | `minval = 0, maxval = 100` | hidden |
| 103 | `tagTrade` | `input.bool` | `true` | "Tags inside the chart for Entry / SL / TP1-3" | gLv | | hidden |
| 104 | `tagLevels` | `input.bool` | `false` | "Tags inside the chart for every level" | gLv | | hidden |
| 105 | `showATH` | `input.bool` | `true` | "ATH / ATL of the loaded history" | gLv | | hidden |
| 106 | `showYO` | `input.bool` | `true` | "Yearly opens" | gLv | | hidden |
| 107 | `yoCount` | `input.int` | `2` | "Yearly opens to show (this year first)" | gLv | `minval = 1, maxval = 3` | hidden |
| 108 | `showRange` | `input.bool` | `false` | "Range High / Low" | gLv | | hidden |
| 109 | `rangeLen` | `input.int` | `100` | "Range lookback (bars)" | gLv | `minval = 2` | hidden |
| 110 | `cLevel` | `input.color` | `#22c55e` | "Level line" | gLv | `inline = "lc"` | SHOWN |
| 111 | `cName` | `input.color` | `#f59e0b` | "Level name" | gLv | `inline = "lc"` | SHOWN |
| 114 | `m1p` | `input.float` | `0` | "Level 1" | gMan | `inline = "m1"` | hidden |
| 115 | `m1n` | `input.string` | `""` | "name" | gMan | `inline = "m1"` | hidden |
| 116 | `m2p` | `input.float` | `0` | "Level 2" | gMan | `inline = "m2"` | hidden |
| 117 | `m2n` | `input.string` | `""` | "name" | gMan | `inline = "m2"` | hidden |
| 118 | `m3p` | `input.float` | `0` | "Level 3" | gMan | `inline = "m3"` | hidden |
| 119 | `m3n` | `input.string` | `""` | "name" | gMan | `inline = "m3"` | hidden |
| 120 | `m4p` | `input.float` | `0` | "Level 4" | gMan | `inline = "m4"` | hidden |
| 121 | `m4n` | `input.string` | `""` | "name" | gMan | `inline = "m4"` | hidden |
| 122 | `m5p` | `input.float` | `0` | "Level 5" | gMan | `inline = "m5"` | hidden |
| 123 | `m5n` | `input.string` | `""` | "name" | gMan | `inline = "m5"` | hidden |
| 124 | `m6p` | `input.float` | `0` | "Level 6" | gMan | `inline = "m6"` | hidden |
| 125 | `m6n` | `input.string` | `""` | "name" | gMan | `inline = "m6"` | hidden |
| 128 | `z1t` | `input.float` | `0` | "Zone 1 top" | gZn | `inline = "z1"` | hidden |
| 129 | `z1b` | `input.float` | `0` | "bottom" | gZn | `inline = "z1"` | hidden |
| 130 | `z1n` | `input.string` | `""` | "name" | gZn | `inline = "z1"` | hidden |
| 131 | `z1c` | `input.color` | `color.new(#06b6d4, 70)` | "Zone 1 colour" | gZn | | SHOWN |
| 132 | `z2t` | `input.float` | `0` | "Zone 2 top" | gZn | `inline = "z2"` | hidden |
| 133 | `z2b` | `input.float` | `0` | "bottom" | gZn | `inline = "z2"` | hidden |
| 134 | `z2n` | `input.string` | `""` | "name" | gZn | `inline = "z2"` | hidden |
| 135 | `z2c` | `input.color` | `color.new(#a855f7, 70)` | "Zone 2 colour" | gZn | | SHOWN |
| 138 | `showSR` | `input.bool` | `true` | "Show pivot levels" | gSR | | hidden |
| 139 | `pivLen` | `input.int` | `10` | "Pivot strength (bars each side)" | gSR | `minval = 1` | hidden |
| 140 | `maxSR` | `input.int` | `3` | "Levels per side (max 3)" | gSR | `minval = 1, maxval = 3` | hidden |
| 141 | `cRes` | `input.color` | `#ef4444` | "Resistance" | gSR | `inline = "sr"` | SHOWN |
| 142 | `cSup` | `input.color` | `#22c55e` | "Support" | gSR | `inline = "sr"` | SHOWN |
| 143 | `cBroken` | `input.color` | `#6b7280` | "Broken" | gSR | `inline = "sr"` | SHOWN |
| 146 | `trMode` | `input.string` | `"Auto (last signal)"` | "Mode" | gTr | `options = ["Off","Auto (last signal)","Manual"]` | hidden |
| 147 | `autoMaxAge` | `input.int` | `60` | "Auto: only if the signal is within (bars)" | gTr | `minval = 1` | hidden |
| 148 | `slMode` | `input.string` | `"Swing"` | "Auto stop" | gTr | `options = ["Swing","ATR"]` | hidden |
| 149 | `swingLen` | `input.int` | `5` | "Swing lookback (bars)" | gTr | `minval = 1` | hidden |
| 150 | `atrMult` | `input.float` | `1.5` | "ATR multiple (ATR stop)" | gTr | `minval = 0.1, step = 0.1` | hidden |
| 151 | `atrPad` | `input.float` | `0.25` | "ATR pad beyond the swing" | gTr | `minval = 0, step = 0.05` | hidden |
| 152 | `maxStopPct` | `input.float` | `15` | "Auto: max stop distance (% of entry, 0 = off)" | gTr | `minval = 0, step = 1` | hidden |
| 153 | `r1` | `input.float` | `1.0` | "TP1 (R)" | gTr | `minval = 0.1, step = 0.1, inline = "r"` | hidden |
| 154 | `r2` | `input.float` | `2.0` | "TP2 (R)" | gTr | `minval = 0.1, step = 0.1, inline = "r"` | hidden |
| 155 | `r3` | `input.float` | `3.0` | "TP3 (R)" | gTr | `minval = 0.1, step = 0.1, inline = "r"` | hidden |
| 156 | `extendBars` | `input.int` | `30` | "Extend the box right (bars)" | gTr | `minval = 1, maxval = 400` | hidden |
| 157 | `trDir` | `input.string` | `"Long"` | "Manual: direction" | gTr | `options = ["Long","Short"]` | hidden |
| 158 | `mEntry` | `input.float` | `0` | "Manual: entry (0 = last close)" | gTr | | hidden |
| 159 | `mSL` | `input.float` | `0` | "Manual: SL (0 = ATR stop)" | gTr | | hidden |
| 160 | `mTP1` | `input.float` | `0` | "Manual: TP1 (0 = R multiple)" | gTr | | hidden |
| 161 | `mTP2` | `input.float` | `0` | "Manual: TP2 (0 = R multiple)" | gTr | | hidden |
| 162 | `mTP3` | `input.float` | `0` | "Manual: TP3 (0 = R multiple)" | gTr | | hidden |
| 163 | `mStart` | `input.int` | `10` | "Manual: box starts (bars ago)" | gTr | `minval = 0` | hidden |
| 164 | `cProfitL` | `input.color` | `#22c55e` | "Long profit" | gTr | `inline = "tc"` | SHOWN |
| 165 | `cProfitS` | `input.color` | `#3b82f6` | "Short profit" | gTr | `inline = "tc"` | SHOWN |
| 166 | `cStop` | `input.color` | `#ef4444` | "Stop" | gTr | `inline = "tc"` | SHOWN |
| 167 | `cEntry` | `input.color` | `#9ca3af` | "Entry" | gTr | `inline = "tc"` | SHOWN |
| 170 | `revOn` | `input.bool` | `true` | "Draw a counter-trend box while RSI is at an extreme" | gRev | | hidden |
| 171 | `revLook` | `input.int` | `30` | "Structure lookback (bars): target = opposite swing, stop = swing + pad" | gRev | `minval = 2` | hidden |
| 172 | `revPad` | `input.float` | `1.0` | "ATR pad beyond the swing for the stop" | gRev | `minval = 0, step = 0.25` | hidden |
| 173 | `revMaxAge` | `input.int` | `60` | "Keep the box for (bars) after RSI leaves the zone" | gRev | `minval = 1` | hidden |
| 174 | `revHide` | `input.bool` | `true` | "Hide the trend box while a reversal box is active" | gRev | | hidden |
| 177 | `showKey` | `input.bool` | `true` | "Show the key" | gKey | | hidden |
| 178 | `keyPos` | `input.string` | `"Top left"` | "Corner" | gKey | `options = ["Top left","Top right","Bottom left","Bottom right"]` | hidden |
| 179 | `keySize` | `input.string` | `"small"` | "Text size" | gKey | `options = ["tiny","small","normal"]` | hidden |
| 180 | `keyLive` | `input.bool` | `true` | "Live rows (trend now, last signal, trade now)" | gKey | | hidden |

Note on the "SHOWN" rows: the header comment at L61 claims "Only the three
lengths and the MA type show in the status line." Literally, 17 `input.color`
calls also omit `display = display.none`. In practice TradingView does not print
colour inputs in the status line, so the comment is effectively true; but if a
tool is parsing these files, the literal fact is that 21 inputs carry no
`display` argument, not 4.

### 1.2 `Final_RSI_Plus.pine` -- 21 inputs

No `group` argument is used anywhere in this file; all inputs land in the
default (ungrouped) section of the settings dialog.

| L | Variable | Call | Default | Label | Other args | Hidden |
|---|---|---|---|---|---|---|
| 15 | `rsiLen` | `input.int` | `14` | "RSI Length" | `minval = 1` | hidden |
| 16 | `rsiSrc` | `input.source` | `close` | "Source" | | hidden |
| 17 | `maLen` | `input.int` | `14` | "MA Length" | `minval = 1` | hidden |
| 18 | `maType` | `input.string` | `"SMA"` | "MA Type" | `options = ["SMA","EMA"]` | hidden |
| 19 | `longLen` | `input.int` | `50` | "Long-run average length" | `minval = 1` | hidden |
| 20 | `ob1` | `input.float` | `70` | "Overbought" | `inline = "ob"` | hidden |
| 21 | `ob2` | `input.float` | `75` | "extreme" | `inline = "ob"` | hidden |
| 22 | `os1` | `input.float` | `30` | "Oversold" | `inline = "os"` | hidden |
| 23 | `os2` | `input.float` | `25` | "extreme" | `inline = "os"` | hidden |
| 24 | `midL` | `input.float` | `50` | "Midline" | | hidden |
| 25 | `showCols` | `input.bool` | `true` | "Columns on the extremes (overbought = blue, oversold = red)" | | hidden |
| 26 | `showMidCols` | `input.bool` | `false` | "Grey column when RSI crosses the midline" | | hidden |
| 27 | `showDiv` | `input.bool` | **`true`** | "Regular divergences" | | hidden |
| 28 | `lbL` | `input.int` | **`5`** | "Pivot lookback left" | `minval = 1` | hidden |
| 29 | `lbR` | `input.int` | **`5`** | "Pivot lookback right" | `minval = 1` | hidden |
| 30 | `rangeUpper` | `input.int` | **`60`** | "Max bars between pivots" | `minval = 1` | hidden |
| 31 | `rangeLower` | `input.int` | **`5`** | "Min bars between pivots" | `minval = 1` | hidden |
| 32 | `cRsi` | `input.color` | `#dbe4ff` | "RSI" | `inline = "c"` | SHOWN |
| 33 | `cMa` | `input.color` | `#f59e0b` | "MA" | `inline = "c"` | SHOWN |
| 34 | `cUp` | `input.color` | `#3b82f6` | "Above MA / overbought" | `inline = "c2"` | SHOWN |
| 35 | `cDn` | `input.color` | `#ef4444` | "Below MA / oversold" | `inline = "c2"` | SHOWN |

The five bolded rows are the entire parameterisation of RULE A.

### 1.3 `Final_Bottom_MACD.pine` -- 11 inputs

No groups here either.

| L | Variable | Call | Default | Label | Other args | Hidden |
|---|---|---|---|---|---|---|
| 13 | `fastLen` | `input.int` | `12` | "Fast Length" | `minval = 1` | hidden |
| 14 | `slowLen` | `input.int` | `26` | "Slow Length" | `minval = 1` | hidden |
| 15 | `sigLen` | `input.int` | `9` | "Signal Length" | `minval = 1` | hidden |
| 16 | `src` | `input.source` | `close` | "Source" | | hidden |
| 17 | `cUp1` | `input.color` | `#26a69a` | "Hist above zero, rising" | `inline = "u"` | SHOWN |
| 18 | `cUp2` | `input.color` | `#b2dfdb` | "falling" | `inline = "u"` | SHOWN |
| 19 | `cDn1` | `input.color` | `#ef5350` | "Hist below zero, falling" | `inline = "d"` | SHOWN |
| 20 | `cDn2` | `input.color` | `#ffcdd2` | "rising" | `inline = "d"` | SHOWN |
| 21 | `cMacd` | `input.color` | `#2962ff` | "MACD" | `inline = "l"` | SHOWN |
| 22 | `cSig` | `input.color` | `#ff6d00` | "Signal" | `inline = "l"` | SHOWN |
| 23 | `zeroCols` | `input.bool` | `false` | "Column on histogram zero-cross" | | hidden |

**This pane is decorative for the scanner's purposes.** The Top script does NOT
read it; the Top script computes its own MACD at L206 from its own `macdFast` /
`macdSlow` / `macdSig` inputs (L96-98, same 12/26/9 defaults) and, importantly,
from a hard-coded `close` rather than from any `Source` input. The two MACDs
agree only because both default to `close`. Changing the MACD pane's `Source`
input would NOT change the Top script's score.

---

## 2. Derived series: every `ta.*` and `request.security` call

### 2.1 Top script

| L | Assigned to | Call, verbatim | Notes |
|---|---|---|---|
| 186 | `e` (inside `f_ma`) | `ta.ema(s, len)` | computed every bar whatever `maType` is |
| 187 | `m` (inside `f_ma`) | `ta.sma(s, len)` | computed every bar whatever `maType` is |
| 198 | `maFast` | `f_ma(maSrc, fastLen)` | = `ta.ema(close, 20)` by default |
| 199 | `maMid` | `f_ma(maSrc, midLen)` | = `ta.ema(close, 50)` by default |
| 200 | `maSlow` | `f_ma(maSrc, slowLen)` | = `ta.ema(close, 200)` by default |
| 204 | `rsiV` | `ta.rsi(close, rsiLen)` | **source is literal `close`, not `maSrc`**; length 14 |
| 205 | `atrV` | `ta.atr(14)` | **14 is hard-coded, there is no ATR-length input** |
| 206 | `[macdLine, macdSignal, macdHist]` | `ta.macd(close, macdFast, macdSlow, macdSig)` | **source is literal `close`**; 12/26/9 |
| 207 | `swLo` | `ta.lowest(low, swingLen)` | 5 bars, INCLUDES the current bar |
| 208 | `swHi` | `ta.highest(high, swingLen)` | 5 bars, INCLUDES the current bar |
| 209 | `rHi` | `ta.highest(high, rangeLen)` | 100 bars |
| 210 | `rLo` | `ta.lowest(low, rangeLen)` | 100 bars |
| 212 | `bullX` | `ta.crossover(maFast, maMid)` | |
| 213 | `bearX` | `ta.crossunder(maFast, maMid)` | |
| 214 | `goldX` | `ta.crossover(maMid, maSlow)` | golden cross, alert + optional label only |
| 215 | `deadX` | `ta.crossunder(maMid, maSlow)` | death cross, alert + optional label only |
| 229 | `yo0` | `request.security(syminfo.tickerid, "12M", open, lookahead = barmerge.lookahead_on)` | this year's open |
| 230 | `yo1` | `request.security(syminfo.tickerid, "12M", open[1], lookahead = barmerge.lookahead_on)` | last year's open |
| 231 | `yo2` | `request.security(syminfo.tickerid, "12M", open[2], lookahead = barmerge.lookahead_on)` | open two years ago |
| 232 | `yYr` | `request.security(syminfo.tickerid, "12M", year, lookahead = barmerge.lookahead_on)` | the year number, for the label text |
| 235 | `ph` | `ta.pivothigh(high, pivLen, pivLen)` | 10 left / 10 right, on PRICE highs |
| 236 | `pl` | `ta.pivotlow(low, pivLen, pivLen)` | 10 left / 10 right, on PRICE lows |
| 288 | `revHH` | `ta.highest(high, revLook)` | 30 bars, includes current |
| 289 | `revLL` | `ta.lowest(low, revLook)` | 30 bars, includes current |

Non-`ta.` derived series in the Top script:

| L | Variable | Formula, verbatim |
|---|---|---|
| 201 | `regime` | `maMid > maSlow` |
| 202 | `slowCol` | `regime ? cSlowBull : cSlowBear` |
| 217 | `bullScore` | `1 + (useMacd and macdHist > 0 ? 1 : 0) + (useSlow and close > maSlow ? 1 : 0) + (useRsi and rsiV > 50 ? 1 : 0)` |
| 218 | `bearScore` | `1 + (useMacd and macdHist < 0 ? 1 : 0) + (useSlow and close < maSlow ? 1 : 0) + (useRsi and rsiV < 50 ? 1 : 0)` |
| 219 | `bullSig` | `showSig and bullX and bullScore >= minScore` |
| 220 | `bearSig` | `showSig and bearX and bearScore >= minScore` |
| 225 | `ath` | `na(ath) ? high : math.max(ath, high)` on a `var float ath = na` (L223) |
| 226 | `atl` | `na(atl) ? low : math.min(atl, low)` on a `var float atl = na` (L224) |
| 280 | `sigFresh` | `not na(sigBar) and bar_index - sigBar <= autoMaxAge` |
| 286 | `inOB` | `rsiV >= rsiOB` |
| 287 | `inOS` | `rsiV <= rsiOS` |
| 316 | `rvActive` | `revOn and rvDir != 0` |
| 317 | `rvRisk` | `math.abs(rvEnt - rvStp)` |
| 318 | `rvTp1` | `rvEnt + rvDir * rvRisk` |
| 319 | `rvTp2` | `rvEnt + rvDir * rvRisk * 2` |
| 320 | `rvTp1In` | `rvDir == -1 ? rvTp1 > rvTgt : rvTp1 < rvTgt` |
| 321 | `rvTp2In` | `rvDir == -1 ? rvTp2 > rvTgt : rvTp2 < rvTgt` |
| 322 | `rvCol` | `rvDir == 1 ? cProfitL : cProfitS` |
| 323 | `revNew` | `(inOB and not inOB[1]) or (inOS and not inOS[1])` |
| 368 | `rsiCol` | `rsiV >= rsiOB ? color.new(cSlowBull, colTr) : rsiV <= rsiOS ? color.new(cBear, colTr) : na` |
| 369 | `sigCol` | `bullSig ? color.new(cBull, colTr) : bearSig ? color.new(cBear, colTr) : na` |
| 370 | `colCol` | `showRsiCols and not na(rsiCol) ? rsiCol : sigCols ? sigCol : na` |
| 580 | `maxScore` | `1 + (useMacd ? 1 : 0) + (useSlow ? 1 : 0) + (useRsi ? 1 : 0)` |

Helper functions:

| L | Function | Body |
|---|---|---|
| 185-188 | `f_ma(s, len)` | `e = ta.ema(s, len)` / `m = ta.sma(s, len)` / `maType == "EMA" ? e : m` |
| 191-192 | `f_near(p)` | `maxDist == 0 or (not na(p) and p > 0 and p / close <= 1 + maxDist / 100 and close / p <= 1 + maxDist / 100)` |
| 194-195 | `f_px(price)` | `str.tostring(price, format.mintick)` |
| 421-423 | `f_hline(price, col, sty, w)` | `line.new(bar_index - 1, price, bar_index, price, extend = extend.both, ...)`, pushed to `lns` |
| 425-427 | `f_seg(x1, price, col, sty, w)` | `line.new(x1, price, bar_index + lblOff, price, ...)`, pushed to `lns` |
| 432-434 | `f_tag(price, txt, bg)` | `label.new(bar_index + lblOff, price, txt, style = label.style_label_right, color = color.new(bg, 10), textcolor = color.white, size = size.small)` |
| 437-439 | `f_name(price, txt)` | `label.new(bar_index + lblOff, price, txt + "\n", style = label.style_none, textcolor = cName, size = size.small)` -- the trailing newline is what lifts the text one line above the level |
| 441-445 | `f_manual(p, n)` | if `not na(p)`: `f_hline(p, cLevel, line.style_solid, 1)`; if `n != ""`: `f_name(p, n)` |
| 447-452 | `f_zone(t, b, n, c)` | if `t > 0 and b > 0 and t > b`: `box.new(bar_index - 1, t, bar_index, b, border_color = color.new(c, 40), bgcolor = c, extend = extend.both)`; if `n != ""`: `f_name(t, n)` |
| 577-578 | `f_cell(r, c, txt, col)` | `table.cell(key, c, r, txt, text_color = col, text_halign = text.align_left, text_size = kSz)` -- note the r/c swap |

### 2.2 RSI+ script

| L | Assigned to | Call, verbatim |
|---|---|---|
| 37 | `rsi` | `ta.rsi(rsiSrc, rsiLen)` -- `close`, 14 |
| 38 | `maS` | `ta.sma(rsi, maLen)` -- 14 |
| 39 | `maE` | `ta.ema(rsi, maLen)` -- 14 |
| 40 | `rsiMa` | `maType == "EMA" ? maE : maS` -- default SMA, so `maS` |
| 41 | `longAvg` | `ta.sma(rsi, longLen)` -- 50 |
| 44 | `plFound` | `not na(ta.pivotlow(rsi, lbL, lbR))` -- pivots on the RSI SERIES, 5/5 |
| 45 | `phFound` | `not na(ta.pivothigh(rsi, lbL, lbR))` -- 5/5 |
| 48 | `bars` (in `f_inRange`) | `ta.barssince(cond == true)` |
| 53 | `inRangeL` | `f_inRange(plFound[1])` |
| 54 | `inRangeH` | `f_inRange(phFound[1])` |
| 56 | `rsiHL` | `rsi[lbR] > ta.valuewhen(plFound, rsi[lbR], 1)` |
| 57 | `priceLL` | `low[lbR] < ta.valuewhen(plFound, low[lbR], 1)` |
| 58 | `bullDiv` | `showDiv and plFound and priceLL and rsiHL and inRangeL` |
| 60 | `rsiLH` | `rsi[lbR] < ta.valuewhen(phFound, rsi[lbR], 1)` |
| 61 | `priceHH` | `high[lbR] > ta.valuewhen(phFound, high[lbR], 1)` |
| 62 | `bearDiv` | `showDiv and phFound and priceHH and rsiLH and inRangeH` |
| 83 | `extCol` | `rsi >= ob2 ? color.new(cUp, 75) : rsi <= os2 ? color.new(cDn, 75) : na` |
| 85 | `midX` | `ta.cross(rsi, midL)` |
| 91 | (alert) | `ta.crossover(rsi, ob1)` |
| 92 | (alert) | `ta.crossunder(rsi, os1)` |

The comment at L51-52 is load-bearing and must be preserved in any
reimplementation of the intent: `inRangeL` / `inRangeH` are evaluated
UNCONDITIONALLY on every bar, because Pine v6's `and` short-circuits and a
`ta.barssince()` that only sometimes executes keeps a broken history. In a
vectorised pandas reimplementation this is automatic (the whole column is always
computed); in a bar-loop reimplementation it is a real trap.

### 2.3 MACD script

| L | Assigned to | Call, verbatim |
|---|---|---|
| 25 | `[macdLine, sigLine, hist]` | `ta.macd(src, fastLen, slowLen, sigLen)` -- `close`, 12/26/9 |
| 26 | `histCol` | `hist >= 0 ? (hist > nz(hist[1]) ? cUp1 : cUp2) : (hist < nz(hist[1]) ? cDn1 : cDn2)` |
| 33 | `xUp` | `ta.crossover(hist, 0)` |
| 34 | `xDn` | `ta.crossunder(hist, 0)` |
| 35 | `zc` | `xUp ? color.new(cUp1, 75) : xDn ? color.new(cDn1, 75) : na` |

---

## 3. The scored cross signal (RULE B)

### 3.1 The code, verbatim (Top script L212-220)

```
bullX = ta.crossover(maFast, maMid)
bearX = ta.crossunder(maFast, maMid)
goldX = ta.crossover(maMid, maSlow)
deadX = ta.crossunder(maMid, maSlow)

bullScore = 1 + (useMacd and macdHist > 0 ? 1 : 0) + (useSlow and close > maSlow ? 1 : 0) + (useRsi and rsiV > 50 ? 1 : 0)
bearScore = 1 + (useMacd and macdHist < 0 ? 1 : 0) + (useSlow and close < maSlow ? 1 : 0) + (useRsi and rsiV < 50 ? 1 : 0)
bullSig   = showSig and bullX and bullScore >= minScore
bearSig   = showSig and bearX and bearScore >= minScore
```

### 3.2 Term by term

**Term 0, the base: `1`.** Unconditional. Every displayed signal scores at least
1. There is no score of 0 and no way to produce one.

**Term 1, MACD agreement: `useMacd and macdHist > 0` (bull) / `macdHist < 0`
(bear).**
- Input: `useMacd` (L87, default `true`).
- `macdHist` comes from L206, `ta.macd(close, 12, 26, 9)`, third return value.
  Pine's `ta.macd` returns `[macdLine, signalLine, histLine]` where
  `macdLine = ema(src, fast) - ema(src, slow)`,
  `signalLine = ema(macdLine, sigLen)`,
  `histLine = macdLine - signalLine`.
- Comparison is STRICT. `macdHist == 0.0` exactly scores neither the bull nor
  the bear point. (Floating point makes this essentially unreachable, but a
  reimplementation must not "helpfully" use `>=`.)
- Evaluated on the CROSS BAR, not on any earlier bar.

**Term 2, side of the Slow MA: `useSlow and close > maSlow` (bull) /
`close < maSlow` (bear).**
- Input: `useSlow` (L88, default `true`).
- `maSlow` = `ta.ema(close, 200)` by default.
- Comparison is STRICT, and it uses `close`, not `maSrc`. (`maSrc` feeds
  `maSlow` itself; the comparison operand is the literal `close`. Identical by
  default, different if the user repoints `Source`.)
- **If the symbol has fewer than 200 bars of history, `maSlow` is `na`, the
  comparison is false, and this term contributes 0.** So a freshly listed name
  can never score above 2. This matters for crypto and for recent NASDAQ IPOs.

**Term 3, RSI agreement: `useRsi and rsiV > 50` (bull) / `rsiV < 50` (bear).**
- Input: `useRsi` (L89, default **`false`**).
- `rsiV` = `ta.rsi(close, 14)` from L204.
- **OFF BY DEFAULT**, so this term contributes 0 on a default chart.

### 3.3 Maximum and reachable scores

`maxScore` is computed explicitly at L580 for the key table:
`1 + (useMacd ? 1 : 0) + (useSlow ? 1 : 0) + (useRsi ? 1 : 0)`.

Under DEFAULT inputs (`useMacd = true`, `useSlow = true`, `useRsi = false`):

- **`maxScore` = 3.**
- **Reachable scores: exactly `{1, 2, 3}`** for both directions.
- `minScore` defaults to `1`, so all three are DISPLAYED. The chart therefore
  prints `Bullish +1`, `Bullish +2`, `Bullish +3`, `-1 Bearish`, `-2 Bearish`,
  `-3 Bearish` and nothing else.
- **A score of 4 is unreachable by default.** It requires `useRsi = true`. The
  `minScore` input allows `maxval = 4`, so setting `minScore = 4` with default
  `useRsi` silently suppresses every signal -- a dead-end configuration the
  script does not guard against.

Score decomposition under defaults:
| Score | Bull condition on the cross bar | Bear condition on the cross bar |
|---|---|---|
| 1 | cross only: `macdHist <= 0` AND `close <= maSlow` | cross only: `macdHist >= 0` AND `close >= maSlow` |
| 2 | cross + exactly one of (`macdHist > 0`), (`close > maSlow`) | cross + exactly one of (`macdHist < 0`), (`close < maSlow`) |
| 3 | cross + `macdHist > 0` + `close > maSlow` | cross + `macdHist < 0` + `close < maSlow` |

**Therefore RULE B (`abs(score) >= 2`) is exactly: a Fast/Mid cross on which at
least one of the two confirmation terms agrees.** It is equivalent to running
the shipped script with `minScore = 2` instead of 1.

### 3.4 Timing and repaint

- `ta.crossover(a, b)` is true on bar T when `a[T] > b[T]` and `a[T-1] <= b[T-1]`.
  Note the `<=` on the previous bar: an exact touch followed by a break counts
  as a cross. `ta.crossunder` is the mirror (`a[T] < b[T]` and `a[T-1] >= b[T-1]`).
- **`bullSig` / `bearSig` are SINGLE-BAR EVENTS.** They are true on the cross bar
  and false on every other bar. There is no "still bullish" state; what persists
  is the `var` memory at L255-279 (`sigBar`, `sigDir`, `sigScore`, ...).
- **Knowable on bar T itself**, using only bars <= T. Zero detection lag.
- **No retroactive change.** Once bar T closes, every input to the score is
  frozen (`maFast`, `maMid`, `maSlow`, `macdHist`, `close`, `rsiV` on bar T).
- **Live-bar mutation is severe here** and is the one practical hazard: during
  the session, `maFast` can cross `maMid` and then cross back before the close,
  and `macdHist` can change sign. A scanner must evaluate on the CLOSED daily
  bar only. Yahoo's ~15-minute-delayed intraday print for a market still open is
  NOT a closed daily bar.
- Both directions cannot be true on the same bar (a crossover and a crossunder
  of the same pair are mutually exclusive).

### 3.5 What the signal writes into memory (Top L254-280)

On a bar where `bullSig or bearSig`:

```
sigBar   := bar_index
sigDir   := bullSig ? 1 : -1
sigScore := bullSig ? bullScore : bearScore
sigPx    := bullSig ? low : high
sigEntry := close
atrStop   = bullSig ? close - atrV * atrMult : close + atrV * atrMult
swStop    = bullSig ? swLo - atrV * atrPad : swHi + atrV * atrPad
sigStop  := slMode == "ATR" ? atrStop : swStop
extPx    := bullSig ? high : low
extBar   := bar_index
```
`else if sigDir == 1 and not na(extPx) and high > extPx` -> `extPx := high; extBar := bar_index`
`else if sigDir == -1 and not na(extPx) and low < extPx` -> `extPx := low; extBar := bar_index`

So `extPx` / `extBar` track the running extreme printed since the last signal,
in the signal's own direction; that pair is the far end of the dashed line
(L466-468). Note `bullSig` wins the `?:` if both were somehow true.

`sigFresh = not na(sigBar) and bar_index - sigBar <= autoMaxAge` (L280), i.e.
the last signal is at most 60 bars old (inclusive).

---

## 4. The RSI divergence block (RULE A)

### 4.1 The code, verbatim (RSI+ L43-62)

```
// --- divergences (regular only), pivots on the RSI itself --------------------
plFound = not na(ta.pivotlow(rsi, lbL, lbR))
phFound = not na(ta.pivothigh(rsi, lbL, lbR))

f_inRange(cond) =>
    bars = ta.barssince(cond == true)
    rangeLower <= bars and bars <= rangeUpper

// evaluated unconditionally every bar: v6 `and` short-circuits, and a
// ta.barssince() that only sometimes runs keeps a broken history
inRangeL = f_inRange(plFound[1])
inRangeH = f_inRange(phFound[1])

rsiHL   = rsi[lbR] > ta.valuewhen(plFound, rsi[lbR], 1)
priceLL = low[lbR] < ta.valuewhen(plFound, low[lbR], 1)
bullDiv = showDiv and plFound and priceLL and rsiHL and inRangeL

rsiLH   = rsi[lbR] < ta.valuewhen(phFound, rsi[lbR], 1)
priceHH = high[lbR] > ta.valuewhen(phFound, high[lbR], 1)
bearDiv = showDiv and phFound and priceHH and rsiLH and inRangeH
```

This is TradingView's built-in "Divergence Indicator" logic, unmodified except
that the source series is this script's own `rsi` and the lookbacks are
5/5/60/5 rather than the built-in's 5/5/60/5 (the built-in's defaults are the
same numbers).

### 4.2 What each Pine built-in evaluates to

**`ta.pivotlow(source, leftbars, rightbars)`** -- on bar T, the CANDIDATE pivot
is `source[rightbars]`, i.e. the value at bar `T - rightbars`. With
`lbL = lbR = 5` the candidate on bar T is `rsi[T-5]` and the examined window is
bars `T-10 .. T` (11 bars: 5 left of the candidate, the candidate, 5 right).
The call returns the candidate's VALUE if it qualifies as a pivot low, and `na`
otherwise. `plFound` is therefore `true` exactly on the bars where a pivot low
five bars back has just been confirmed.

Tie-breaking: TradingView does not document whether an equal neighbour
disqualifies the pivot. The conservative reimplementation, and the one this
document recommends, is STRICT on both sides:

```
plFound[T] = all( rsi[T-5] < rsi[T-5-k] for k in 1..5 )
         and all( rsi[T-5] < rsi[T-5+k] for k in 1..5 )
```
The permissive alternative is `rsi[T-5] == min(rsi[T-10..T])`, which allows
ties. The two differ only on exact float equality, which on a 14-period Wilder
RSI over real prices is rare but not impossible (a run of identical closes moves
the RSI but a symmetric price pattern can reproduce a value). **This is the one
behaviour in the whole document that should be validated against a live
TradingView chart before the scanner is trusted**, by picking three names with a
visible "Bull" mark and confirming the reimplementation flags the same bar.
Note the repo's own `scanner/indicators.pivot_lows()` uses the PERMISSIVE form
(`low <= low.shift(k)` both sides) and returns a filtered series rather than a
right-shifted boolean -- it is NOT a drop-in for `ta.pivotlow`.

**`ta.barssince(cond)`** -- the number of bars since `cond` was last `true`;
`0` if `cond` is true on the current bar; `na` if it has never been true. An
`na` makes both comparisons in `f_inRange` false, so a symbol with fewer than
two pivots of the relevant kind never produces a divergence.

**`ta.valuewhen(cond, source, occurrence)`** -- the value `source` had on the
`occurrence`-th most recent bar where `cond` was true, counting the current bar
as occurrence `0` when `cond` is true on it. So on a bar where `plFound` is
true, `ta.valuewhen(plFound, rsi[lbR], 1)` is the value that the EXPRESSION
`rsi[5]` had on the PREVIOUS pivot-confirmation bar -- which is the RSI at the
previous pivot bar. Same for `low[lbR]`: the low of the previous PIVOT BAR (not
the lowest low of the intervening stretch).

### 4.3 The `inRange` arithmetic, worked exactly

`inRangeL = f_inRange(plFound[1])`, and `f_inRange(cond) = rangeLower <=
ta.barssince(cond == true) <= rangeUpper`, so:

`inRangeL[T] = 5 <= ta.barssince(plFound[1])[T] <= 60`

Let `T` be the current pivot-confirmation bar and `T0` the previous one
(`plFound` true at both, nothing in between). `plFound[1]` is true on bar `u`
exactly when `plFound` is true on bar `u-1`. The most recent such `u` at or
before `T` is `u = T0 + 1` (the candidate `u = T + 1` is in the future). So:

```
ta.barssince(plFound[1])[T] = T - (T0 + 1) = T - T0 - 1
```

The condition `5 <= T - T0 - 1 <= 60` is therefore:

```
6 <= T - T0 <= 61          (bars between the two CONFIRMATION bars)
6 <= P - P0 <= 61          (bars between the two PIVOT bars, since both are
                            shifted back by exactly lbR = 5)
```

**So: the two RSI pivot lows must be between 6 and 61 bars apart, inclusive.**
Not 5 and not 60. The off-by-one comes from `plFound[1]` and it is inherited
verbatim from TradingView's built-in; a reimplementation that uses
`5 <= gap <= 60` will disagree with the chart at both ends of the range.

Degenerate case: two pivot confirmations on consecutive bars gives
`barssince = 0`, which fails `>= 5`. Good.

### 4.4 Full condition, restated in bar-index form

Let `T` be the bar being evaluated, `P = T - 5` the candidate pivot bar, `T0`
the previous pivot-low confirmation bar and `P0 = T0 - 5` the previous pivot
bar. Then:

```
bullDiv[T]  ==  showDiv                                  (default true)
            and plFound[T]                               (rsi[P] is a pivot low)
            and low[P]  <  low[P0]                       priceLL: PRICE made a lower low
            and rsi[P]  >  rsi[P0]                       rsiHL:   RSI made a HIGHER low
            and 6 <= (P - P0) <= 61                      inRangeL
```
```
bearDiv[T]  ==  showDiv
            and phFound[T]                               (rsi[P] is a pivot high)
            and high[P] >  high[P0]                      priceHH: PRICE made a higher high
            and rsi[P]  <  rsi[P0]                       rsiLH:   RSI made a LOWER high
            and 6 <= (P - P0) <= 61                      inRangeH
```

All four price/RSI comparisons are STRICT. Equal lows do not count.

Note what is NOT required: no minimum RSI level (a bull divergence does not have
to occur in oversold territory), no minimum divergence magnitude, no trend
filter, no volume filter, no confirmation candle. This is the plainest possible
regular-divergence definition, which is why it fires often -- exactly the
"false positives are cheap" profile the scanner wants.

### 4.5 Worked numbered-bar example

Take a daily series and number the bars by `bar_index`. Suppose:

- bar 180: RSI = 28.4, low = 10.20
- bar 200: RSI = 31.7, low = 9.85
- and nothing between bars 181 and 199 qualifies as an RSI pivot low.

Step by step:

| Bar | What happens |
|---|---|
| 180 | The RSI prints its local low. **Nothing is detected. `plFound[180]` is false** -- on bar 180 the candidate examined is `rsi[175]`, not `rsi[180]`. |
| 181-184 | Nothing. |
| **185** | `ta.pivotlow(rsi,5,5)` examines the window 175..185 with candidate `rsi[180] = 28.4`. It qualifies. **`plFound[185] = true`.** The blue "Bull"/circle machinery now has its FIRST pivot. `bullDiv[185]` is false, because `ta.valuewhen(plFound, rsi[5], 1)` needs a SECOND-most-recent occurrence and there is none yet (or it points at an older pivot, whose own tests then apply). |
| 186-204 | Nothing. |
| **205** | Window 195..205, candidate `rsi[200] = 31.7`. It qualifies. **`plFound[205] = true`.** Now evaluate: `rsi[lbR]` = `rsi[5]` at bar 205 = `rsi[200]` = 31.7. `ta.valuewhen(plFound, rsi[5], 1)` = the value of `rsi[5]` on the previous occurrence bar 185 = `rsi[180]` = 28.4. **`rsiHL` = 31.7 > 28.4 = true.** `low[5]` at bar 205 = `low[200]` = 9.85; `ta.valuewhen(plFound, low[5], 1)` = `low[180]` = 10.20. **`priceLL` = 9.85 < 10.20 = true.** `ta.barssince(plFound[1])[205]`: `plFound[1]` was true on bar 186, so `205 - 186 = 19`. **`inRangeL` = 5 <= 19 <= 60 = true.** (Cross-check with the formula: `T - T0 - 1 = 205 - 185 - 1 = 19`. Pivot gap `P - P0 = 200 - 180 = 20`, inside `[6, 61]`.) **`bullDiv[205] = true`.** |
| 205, drawing | `plot(bullDiv ? rsi[lbR] : na, ..., offset = -lbR)` (L76) and the matching `plotshape` (L78) draw the circle and the "Bull" label at RSI 31.7 **on bar 200**, five bars to the LEFT of the bar that computed it. |
| 206+ | `bullDiv` is false again. The mark at bar 200 stays where it is forever; it does not move and does not disappear. |

**The off-by-five, stated as plainly as possible:** the bar the label SITS ON
(200) and the bar the label BECAME KNOWN ON (205) are five bars apart. For a
daily chart, five bars is a trading week.

### 4.6 Consequences for a daily scanner (critical)

Let `T` = the latest CLOSED daily bar.

- **Correct reading of "printed a Bull/Bear divergence as of the latest closed
  bar": `bullDiv[T]` or `bearDiv[T]` is true.** The mark is placed at bar `T-5`.
  This uses no future data, cannot repaint, and is the "the divergence was
  confirmed today" semantics. **This is the reading the scanner should use.**
- **Incorrect reading: "a Bull mark sits on bar `T`".** That requires
  `bullDiv[T+5]`, which needs five more sessions to close. It is structurally
  unknowable today and a scanner written to that reading would return nothing on
  the current bar, every day, for ever.
- A useful tolerance, given "misses are not cheap": allow a lookback window
  `bullDiv[t]` true for any `t` in `[T-K, T]`. `K = 0` is "confirmed today";
  `K = 4` is "confirmed this week". The label's own bar is then `t - 5`, i.e.
  between `T-5-K` and `T-5`. Recommend exposing `K` as a config constant with a
  small default rather than hard-coding 0.
- Because `bullDiv` is already lagged by 5 bars, a `K`-bar window means the
  underlying price pivot is `5 + K` bars old. With `K = 4` the oldest pivot in a
  hit is 9 sessions back. That is still a live setup on a daily chart, but it
  should be reported alongside the hit (emit both `signal_bar = t` and
  `pivot_bar = t - 5`) so the manual eyeball review knows where to look.

### 4.7 Repaint verdict for Rule A

- **On closed bars: no repaint, none of the three kinds.** Every input to
  `bullDiv[T]` is drawn from bars `<= T`. `ta.pivotlow(rsi, 5, 5)` at bar T
  reads bars `T-10..T`; `ta.valuewhen` reads strictly earlier bars;
  `ta.barssince` likewise.
- **On the forming bar: yes, it can flip.** `plFound` on a live bar depends on
  the live bar's RSI being above the candidate, so an intraday move can create
  or destroy a pivot confirmation until the close. Evaluate closed bars only.
- The drawn mark itself never moves once drawn. The "late by 5 bars" property is
  detection lag, not repaint.

---

## 5. The trade box and the reversal box

### 5.1 Trade box -- every price, in evaluation order (Top L341-359)

```
341  tDir   = trMode == "Manual" ? (trDir == "Long" ? 1 : -1) : sigDir
342  tFresh = trMode == "Manual" or sigFresh
343  tShow  = trMode != "Off" and tDir != 0 and tFresh and not (revHide and rvActive)
344  entRaw = trMode == "Manual" ? (mEntry > 0 ? mEntry : close) : sigEntry
345  atrStp = tDir == 1 ? entRaw - atrV * atrMult : entRaw + atrV * atrMult
346  stpRaw = trMode == "Manual" ? (mSL > 0 ? mSL : atrStp) : sigStop
347  capD   = entRaw * maxStopPct / 100
348  stpCap = maxStopPct <= 0 ? stpRaw : tDir == 1 ? math.max(stpRaw, entRaw - capD) : math.min(stpRaw, entRaw + capD)
349  stp    = trMode == "Manual" ? stpRaw : stpCap
350  risk   = math.abs(entRaw - stp)
351  tp1    = trMode == "Manual" and mTP1 > 0 ? mTP1 : math.max(entRaw + tDir * risk * r1, entRaw * 0.05)
352  tp2    = trMode == "Manual" and mTP2 > 0 ? mTP2 : math.max(entRaw + tDir * risk * r2, entRaw * 0.05)
353  tp3    = trMode == "Manual" and mTP3 > 0 ? mTP3 : math.max(entRaw + tDir * risk * r3, entRaw * 0.05)
354  pc     = tDir == 1 ? cProfitL : cProfitS
355  tEnt   = tShow ? entRaw : na
356  tStp   = tShow ? stp : na
357  tTp1   = tShow ? tp1 : na
358  tTp2   = tShow ? tp2 : na
359  tTp3   = tShow ? tp3 : na
```

Reading these one at a time, in AUTO mode (the default `"Auto (last signal)"`):

- **Direction** `tDir` = `sigDir`, i.e. `+1` after a bullish signal, `-1` after a
  bearish one, `0` before the first signal of the chart's history.
- **Freshness gate** `tFresh` = `sigFresh` = `bar_index - sigBar <= 60`
  (L280, `autoMaxAge` L147). Note this is an AGE cut-off, not a verdict on the
  trade; the key table says so explicitly at L588.
- **Hide rule** `tShow` additionally requires `trMode != "Off"`, `tDir != 0`, and
  `not (revHide and rvActive)` -- the reversal box, when active and when
  `revHide` (default true) is on, SUPPRESSES the trend box entirely.
- **Entry** = `sigEntry` = the CLOSE of the signal bar (frozen at L268).
- **Stop** = `sigStop`, frozen at the signal bar (L269-271):
  - `slMode == "Swing"` (default): `swLo - atrV * atrPad` for a long,
    `swHi + atrV * atrPad` for a short, where `swLo` / `swHi` are the 5-bar
    lowest-low / highest-high INCLUDING the signal bar and `atrPad = 0.25`.
  - `slMode == "ATR"`: `close -/+ atrV * atrMult` with `atrMult = 1.5`.
  - `atrV` is `ta.atr(14)` evaluated on the signal bar.
- **Stop cap** `capD = entRaw * 15 / 100`. For a long,
  `stp = max(sigStop, entry - capD)`; for a short, `stp = min(sigStop,
  entry + capD)`. **The cap can only TIGHTEN a stop, never widen one.** A swing
  stop closer than 15% is left alone. `maxStopPct = 0` switches the cap off.
- **Risk** `risk = abs(entry - stp)`, computed from the CAPPED stop, so the
  targets inherit the cap.
- **Targets** `entry + tDir * risk * {1.0, 2.0, 3.0}`, floored at `entry * 0.05`.
  - The floor is **5% of entry, not zero.** The file header (L28) says "targets
    never go below zero"; the code floors at 5% of entry. See section 11.
  - The floor binds only when `risk * r3 > 0.95 * entry`, i.e.
    `risk > 0.3167 * entry` at `r3 = 3`. **With the 15% stop cap on, risk is at
    most 15% of entry, so in AUTO mode with default inputs the floor is
    UNREACHABLE.** It can bind in Manual mode (uncapped) or with
    `maxStopPct = 0`.

In MANUAL mode (`trMode == "Manual"`):
- `entRaw` = `mEntry` if `> 0` else the CURRENT bar's `close` (not a signal's).
- `stpRaw` = `mSL` if `> 0` else `atrStp`, the CURRENT bar's ATR stop.
- **`stp = stpRaw` -- the cap is NOT applied** (L349). A manual ATR-fallback stop
  is uncapped. That asymmetry is deliberate in shape (a typed-in stop must be
  honoured) but it also leaves the ATR fallback uncapped, which is where the 5%
  target floor can actually bind.
- `tp1/2/3` = the typed value when `> 0`, else the R-multiple with the floor.
- `tFresh` is forced true, so there is no age gate at all.

Drawn objects for the trade box (L525-543, inside `if barstate.islast`):
- `x1 = trMode == "Manual" ? math.max(bar_index - mStart, 0) : sigBar`;
  `x2 = bar_index + extendBars` (30).
- `bxP` = profit box, `box.new(x1, max(entRaw, tp3), x2, min(entRaw, tp3))`,
  border `color.new(pc, 50)`, fill `color.new(pc, 80)`.
- `bxS` = stop box, `box.new(x1, max(entRaw, stp), x2, min(entRaw, stp))`,
  border `color.new(cStop, 50)`, fill `color.new(cStop, 80)`.
- `ln1` at `tp1`, `ln2` at `tp2` (dashed, `color.new(pc, 0)`), `ln3` at
  `entRaw` (dashed, `color.new(cEntry, 20)`). **There is no line at `tp3`** --
  `tp3` is the top edge of the profit box instead.
- If `tagTrade` (default true), five `f_tag` labels: `"SL " + px`,
  `"Entry " + px`, `"TP1 " + px`, `"TP2 " + px`, `"TP3 " + px`.

### 5.2 Reversal box -- the state machine (Top L282-323)

```
286  inOB  = rsiV >= rsiOB            // rsiV >= 75
287  inOS  = rsiV <= rsiOS            // rsiV <= 25
288  revHH = ta.highest(high, revLook)   // 30 bars, includes current
289  revLL = ta.lowest(low, revLook)     // 30 bars, includes current
296  if revOn and inOB
297      rvDir := -1
298      rvBar := bar_index
299      rvEnt := close
300      rvStp := revHH + atrV * revPad
301      rvTgt := revLL
302      rvOff := na
303  else if revOn and inOS
304      rvDir := 1
305      rvBar := bar_index
306      rvEnt := close
307      rvStp := revLL - atrV * revPad
308      rvTgt := revHH
309      rvOff := na
310  else if rvDir != 0
311      if na(rvOff)
312          rvOff := bar_index
313      rvHit = rvDir == -1 ? (high >= rvStp or low <= rvTgt) : (low <= rvStp or high >= rvTgt)
314      if rvHit or bar_index - rvOff > revMaxAge
315          rvDir := 0
```

- **While RSI is at an extreme the box RE-ANCHORS every bar**: `rvBar`, `rvEnt`,
  `rvStp`, `rvTgt` are all overwritten with the current bar's values, and
  `rvOff` is reset to `na`. So a five-day overbought run produces a box whose
  entry is the fifth day's close, not the first.
- **Once RSI leaves the zone the box FREEZES** and the third branch starts
  ageing it. `rvOff` is stamped on the first bar out of the zone.
- **Exit conditions**: the stop or the target printing (`rvHit`), or
  `bar_index - rvOff > revMaxAge` (60), strictly greater -- so the box survives
  exactly 61 bars out of the zone (offsets 0..60) and is cleared on the 62nd.
- `inOB` is tested FIRST, so with a misconfigured `rsiOB <= rsiOS` the short
  branch would win. With 75/25 both cannot be true.
- The third branch runs even when `revOn` is false (the `else if` only excludes
  the two `revOn and ...` branches), but `rvActive = revOn and rvDir != 0`
  hides the effect.
- Prices: `rvEnt = close`; SHORT `rvStp = highest(high,30) + 1.0 * atr(14)`,
  `rvTgt = lowest(low,30)`; LONG `rvStp = lowest(low,30) - 1.0 * atr(14)`,
  `rvTgt = highest(high,30)`.
- `rvRisk = abs(rvEnt - rvStp)`, `rvTp1 = rvEnt + rvDir * rvRisk`,
  `rvTp2 = rvEnt + rvDir * rvRisk * 2`.
- `rvTp1In` / `rvTp2In` suppress an R-target that has overshot the structural
  target: for a short, only draw `rvTp1` if `rvTp1 > rvTgt`.
- `revNew = (inOB and not inOB[1]) or (inOS and not inOS[1])` -- the ENTRY into
  an extreme, used by the `alertcondition` at L624.

Drawn objects (L545-567): profit box entry-to-target, stop box entry-to-stop,
a dashed entry line, conditional `rvTp1` / `rvTp2` dashed lines, and (when
`tagTrade`) tags `"SL "`, `"SHORT "` / `"LONG "`, `"Target "`, plus
`"TP1 "` / `"TP2 "` when in range. Box left edge is `rvBar`, right edge is
`bar_index + extendBars`.

**Not part of Rule A or Rule B**, but the closest thing in the template to a
third screenable rule: "RSI(14) of close is >= 75 or <= 25 on the latest closed
daily bar" is a one-line scan and is what draws the blue/red counter-trend box
the owner's screenshots are full of. Worth offering as an optional Rule C.

---

## 6. Key levels, RSI extreme columns, the key table

### 6.1 Distance filter `f_near` (L191-192)

```
f_near(p) =>
    maxDist == 0 or (not na(p) and p > 0 and p / close <= 1 + maxDist / 100 and close / p <= 1 + maxDist / 100)
```
With `maxDist = 100`: `p / close <= 2` and `close / p <= 2`, i.e.
**`0.5 * close <= p <= 2 * close`** -- half to double. Purely a display filter;
it hides a level, it never changes a decision. `maxDist = 0` disables it.

### 6.2 Level definitions (L325-338)

| L | Variable | Formula | Default visibility |
|---|---|---|---|
| 326 | `lvlATH` | `showATH and f_near(ath) ? ath : na` | on |
| 327 | `lvlATL` | `showATH and f_near(atl) ? atl : na` | on |
| 328 | `lvlYO0` | `showYO and yoCount >= 1 and f_near(yo0) ? yo0 : na` | on |
| 329 | `lvlYO1` | `showYO and yoCount >= 2 and f_near(yo1) ? yo1 : na` | on (yoCount = 2) |
| 330 | `lvlYO2` | `showYO and yoCount >= 3 and f_near(yo2) ? yo2 : na` | **off** (needs yoCount = 3) |
| 331 | `lvlHi` | `showRange ? rHi : na` | **off** (`showRange = false`) |
| 332 | `lvlLo` | `showRange ? rLo : na` | **off** |
| 333-338 | `lvlM1..lvlM6` | `mNp > 0 and f_near(mNp) ? mNp : na` | off (all default 0) |

`ath` / `atl` (L223-226) are running extremes of the LOADED chart history, not a
fixed lookback. Two consequences: they differ between two charts of the same
symbol depending on how far left the user has scrolled, and they are the only
quantity in the Top script whose value on a past bar can change (by loading more
history). The README (line 66) tells the user to scroll left if the ATH looks
wrong. For a scanner this is not reproducible from a fixed window -- if an ATH
level is ever needed, define the lookback explicitly.

`lvlHi` / `lvlLo` deliberately do NOT pass through `f_near` -- a 100-bar range
extreme is always near price by construction.

### 6.3 Yearly opens (L229-232)

`request.security(syminfo.tickerid, "12M", open, lookahead = barmerge.lookahead_on)`
plus `open[1]`, `open[2]` and `year`. The comment at L228 is correct:
`lookahead_on` normally leaks future data, but a 12-month bar's OPEN is known at
the start of that year, so any chart bar inside the year already knows it. No
future leak. `yYr` supplies the label text (`"2026 Y.O"`, `str.tostring(yYr - 1)
+ " Y.O"`, etc., L482/487/492).

### 6.4 Pivot support / resistance (L234-252, 509-523)

```
ph = ta.pivothigh(high, pivLen, pivLen)      // 10 / 10, on price highs
pl = ta.pivotlow(low, pivLen, pivLen)        // 10 / 10, on price lows
```
Four `var` arrays: `phP` (prices), `phB` (bar indices), `plP`, `plB`. On each
confirmed pivot the value is `array.unshift`ed (newest first) together with
`bar_index - pivLen` (the PIVOT bar, not the confirmation bar), and the array is
`array.pop`ped back to `maxSR = 3` entries. So the memory is the three most
recent pivots a side, and detection lag is 10 bars.

Rendering (last bar only): for each stored pivot that passes `f_near`, draw
`f_seg` from its pivot bar to `bar_index + lblOff`, coloured
`close > p ? cBroken : cRes` for highs and `close < q ? cBroken : cSup` for
lows. So: red above price, green below price, grey once price has passed
through. Optional in-chart price tags when `tagLevels` (default false).
These levels have NO price-scale axis label as of v5.3 -- dropped for the plot
budget (comment L376-381).

### 6.5 RSI extreme columns on the PRICE pane (Top L367-371)

```
bgcolor(showBg ? color.new(slowCol, bgTr) : na, title = "Background Zone")
rsiCol = rsiV >= rsiOB ? color.new(cSlowBull, colTr) : rsiV <= rsiOS ? color.new(cBear, colTr) : na
sigCol = bullSig ? color.new(cBull, colTr) : bearSig ? color.new(cBear, colTr) : na
colCol = showRsiCols and not na(rsiCol) ? rsiCol : sigCols ? sigCol : na
bgcolor(colCol, title = "Columns (RSI extreme / signal)")
```
- Green column when `ta.rsi(close, 14) >= 75`; red when `<= 25`. Both inclusive.
- The RSI column takes PRECEDENCE over the signal column; `sigCols` (default
  false) only paints on bars with no RSI extreme.
- Colours: green is `cSlowBull` (#22c55e, the MA group's colour), red is `cBear`
  (#ef4444, the signal group's colour), both at transparency `colTr = 85`.
- `showBg` (regime tint) is OFF by default and is a separate `bgcolor` call.

### 6.6 RSI extreme columns on the RSI+ pane (RSI+ L82-86)

```
extCol = rsi >= ob2 ? color.new(cUp, 75) : rsi <= os2 ? color.new(cDn, 75) : na
bgcolor(showCols ? extCol : na, title = "Extreme columns")
midX = ta.cross(rsi, midL)
bgcolor(showMidCols and midX ? color.new(color.gray, 80) : na, title = "Midline cross column")
```
Same thresholds as the price pane by default (`ob2 = 75`, `os2 = 25`) but
different colours: blue `cUp` (#3b82f6) for overbought, red `cDn` (#ef4444) for
oversold. `showMidCols` is off by default.

### 6.7 The key / legend table (Top L569-617)

`table.new(kPos, 2, 14, bgcolor = color.new(color.black, 25), frame_color =
color.new(color.gray, 50), frame_width = 1, border_color = color.new(color.gray,
85), border_width = 1)` -- **2 columns, 14 rows**, built only when `showKey`.
Position from `keyPos` (`position.top_left` by default), text size from
`keySize` (`size.small`).

`scoreTxt` (L581) is assembled from the toggles and ends with
`" (max " + str.tostring(maxScore) + ")"`, so a default chart's key literally
reads: `Score: 1 for the cross, +1 MACD agrees, +1 price beyond Slow (max 3)`.

Rows 0-10 are static legend text. Rows 11-13 are the live rows, drawn only when
`keyLive`:
- row 11 "Trend now": `regime ? "UP (Mid above Slow)" : "DOWN (Mid below Slow)"`.
- row 12 "Last signal": `lastTxt` (L586) =
  `"none yet"` when `sigDir == 0`, else
  `(sigDir == 1 ? "Bullish +" : "Bearish -") + sigScore + ", " + (bar_index - sigBar) + " bars ago"`
  plus `" (too old for a trade box)"` when `not sigFresh`.
- row 13 "Trade now": `tradeTxt` (L588) = the reversal line when `rvActive`,
  else the trend-box line when `tShow`, else `"trade box is off"` when
  `trMode == "Off"`, else `"none (no signal in the last 60 bars)"`.

The whole table is drawn under `if showKey and barstate.islast` (L583), so it is
last-bar-only and purely presentational.

### 6.8 Signal labels and arrows (Top L373-412)

```
373  plotshape(bullSig, style = shape.arrowup,   location = location.belowbar, color = cBull, size = size.small)
374  plotshape(bearSig, style = shape.arrowdown, location = location.abovebar, color = cBear, size = size.small)
396  if bullSig
397      txt = "Bullish\n+" + str.tostring(bullScore)
398      if boxedSig -> label.new(bar_index, low,  txt, style = label.style_label_up,   color = color.new(color.gray, 60), textcolor = cBull)
400      else        -> label.new(bar_index, low - atrV * 1.8,  txt, style = label.style_none, textcolor = cBull)
402  if bearSig
403      txt = "-" + str.tostring(bearScore) + "\nBearish"
404      if boxedSig -> label.new(bar_index, high, txt, style = label.style_label_down, color = color.new(color.gray, 60), textcolor = cBear)
406      else        -> label.new(bar_index, high + atrV * 1.8, txt, style = label.style_none, textcolor = cBear)
409  if showXLbl and goldX -> label.new(bar_index, maSlow, "BULLISH", style = label.style_label_up,   color = cSlowBull, textcolor = color.white)
411  if showXLbl and deadX -> label.new(bar_index, maSlow, "BEARISH", style = label.style_label_down, color = cSlowBear, textcolor = color.white)
```

**The exact label strings, which is what the owner reads off the chart:**
- bullish: `"Bullish\n+3"` -- renders as two lines, `Bullish` then `+3`.
- bearish: `"-3\nBearish"` -- renders as `-3` then `Bearish`.
So the prompt's spellings "Bullish +2" and "-2 Bearish" are the correct
one-line readings of those two-line labels. The `+` is literal in the bull
string and the `-` is literal in the bear string; `bearScore` is stored POSITIVE
and the minus sign is prepended at L403. There is no negative number anywhere in
the code.

Unboxed labels float `1.8 * atr(14)` beyond the bar. These labels are NOT pushed
into the `lbs` array and are NOT deleted on the next bar -- they accumulate
historically, one per signal, which is why `max_labels_count = 500` is set. Only
the last-bar drawings (L417-419, `lns` / `lbs` / `bxs`) are cleared and redrawn.

---

## 7. Every threshold number in the three files

Sorted by script and by what the number means. "Decision" marks numbers that
change a boolean another rule reads; everything else only changes appearance.

### 7.1 Top script

| Number | Where | Meaning | Decision? |
|---|---|---|---|
| 20 | `fastLen` L63 | Fast MA length | **decision** (feeds `bullX`/`bearX`) |
| 50 | `midLen` L64 | Mid MA length | **decision** |
| 200 | `slowLen` L65 | Slow MA length | **decision** (feeds the `useSlow` score term and `regime`) |
| 82 | `fillTr` L73 | Mid-Slow band transparency | no |
| 94 | `bgTr` L78 | regime background transparency | no |
| 14 | `rsiLen` L80 | RSI length for the price-pane columns and the reversal box | **decision** (reversal box) |
| 75 | `rsiOB` L81 | RSI overbought; green column; SHORT reversal box trigger | **decision** |
| 25 | `rsiOS` L82 | RSI oversold; red column; LONG reversal box trigger | **decision** |
| 85 | `colTr` L83 | column transparency | no |
| 50 | L217/218 | RSI midline used by the (disabled) `useRsi` score term | decision only if `useRsi` is on |
| 1 | L217/218 | the base score for the cross itself | **decision** |
| 1 | `minScore` L90 | minimum score to display a signal | **decision** |
| 4 | `minScore` maxval L90 | UI ceiling; unreachable score with default `useRsi` | no |
| 0 | L217/218 `macdHist > 0` / `< 0` | MACD agreement threshold, strict | **decision** |
| 12 / 26 / 9 | `macdFast`/`macdSlow`/`macdSig` L96-98 | MACD periods used by the score | **decision** |
| 14 | `ta.atr(14)` L205 | ATR period, HARD-CODED, no input | **decision** (stops) |
| 100 | `maxDist` L101 | level hide filter: half-to-double band | no (display only) |
| 5 | `lblOff` L102 | tag/name x-offset in bars | no |
| 2 | `yoCount` L107 | yearly opens shown | no |
| 3 | `yoCount` maxval L107 | UI ceiling | no |
| 100 | `rangeLen` L109 | Range High/Low lookback (feature off by default) | no |
| 0 | `m1p..m6p`, `z1t/z1b/z2t/z2b` | "off" sentinel for manual levels/zones | no |
| 70 | `z1c`/`z2c` transparency L131/135 | manual zone fill | no |
| 10 | `pivLen` L139 | pivot strength each side for S/R, and the 10-bar detection lag | no (display only) |
| 3 | `maxSR` L140 | pivot levels kept per side | no |
| 60 | `autoMaxAge` L147 | trade box freshness: signal must be <= 60 bars old | **decision** (`tShow`) |
| 5 | `swingLen` L149 | swing lookback for the auto stop | **decision** (stop price) |
| 1.5 | `atrMult` L150 | ATR stop multiple | **decision** (stop price) |
| 0.25 | `atrPad` L151 | ATR pad beyond the swing | **decision** (stop price) |
| 15 | `maxStopPct` L152 | auto stop cap, % of entry; 0 = off | **decision** (stop price) |
| 1.0 / 2.0 / 3.0 | `r1`/`r2`/`r3` L153-155 | TP R-multiples | **decision** (target prices) |
| 0.05 | L351-353 | target floor as a fraction of entry (5% of entry) | **decision**, but unreachable in Auto with the 15% cap |
| 30 | `extendBars` L156 | box right extension, bars | no |
| 400 | `extendBars` maxval | UI ceiling | no |
| 10 | `mStart` L163 | manual box left edge, bars ago | no |
| 30 | `revLook` L171 | reversal structure lookback: stop and target swings | **decision** |
| 1.0 | `revPad` L172 | ATR pad beyond the reversal swing | **decision** |
| 60 | `revMaxAge` L173 | bars the frozen reversal box survives after RSI leaves the zone (strictly greater, so 61 bars of life) | **decision** |
| 2 x 14 | `table.new` L575 | key table dimensions | no |
| 1.8 | L401/407 | unboxed signal label offset in ATRs | no |
| 500 / 500 / 500 | L58 | `max_lines_count` / `max_labels_count` / `max_boxes_count` | no |
| 10,20,25,30,40,50,60,80,85 | various `color.new(...)` | transparencies | no |

### 7.2 RSI+ script

| Number | Where | Meaning | Decision? |
|---|---|---|---|
| 14 | `rsiLen` L15 | RSI period (Wilder) | **decision** (Rule A) |
| 14 | `maLen` L17 | RSI smoothing MA period | no (fill colour only) |
| 50 | `longLen` L19 | long-run RSI average period | no (a plotted line only) |
| 70 | `ob1` L20 | overbought band line; the `crossover` alert level | no (alert only) |
| 75 | `ob2` L21 | overbought EXTREME; blue column threshold (`>=`) | no for Rule A, yes for the columns |
| 30 | `os1` L22 | oversold band line; the `crossunder` alert level | no (alert only) |
| 25 | `os2` L23 | oversold EXTREME; red column threshold (`<=`) | no for Rule A, yes for the columns |
| 50 | `midL` L24 | midline value, plotted and used by `ta.cross` | no |
| **5** | `lbL` L28 | pivot lookback LEFT on the RSI series | **decision** (Rule A) |
| **5** | `lbR` L29 | pivot lookback RIGHT; also the label's 5-bar back-shift | **decision** (Rule A, and the off-by-five) |
| **60** | `rangeUpper` L30 | max `barssince` between pivots; real pivot gap max = 61 | **decision** (Rule A) |
| **5** | `rangeLower` L31 | min `barssince` between pivots; real pivot gap min = 6 | **decision** (Rule A) |
| 75 | L83 `color.new(cUp, 75)` | extreme column transparency | no |
| 80 | L86 | midline column transparency | no |
| 50,60,65,88 | L66-74 | plot and fill transparencies | no |
| 1,2,3 | linewidths L65-80 | line thickness | no |

### 7.3 MACD script

| Number | Where | Meaning | Decision? |
|---|---|---|---|
| 12 | `fastLen` L13 | MACD fast EMA | no (pane only; the Top script has its own) |
| 26 | `slowLen` L14 | MACD slow EMA | no (pane only) |
| 9 | `sigLen` L15 | MACD signal EMA | no (pane only) |
| 0 | L26, L31, L33-34 | histogram sign / zero line / zero-cross | no (pane only) |
| 75 | L35 | zero-cross column transparency | no |

---

## 8. Repaint / knowability, every quantity that matters

| Quantity | Script, L | Knowable on | Changes retroactively? | Live-bar flip? |
|---|---|---|---|---|
| `maFast`, `maMid`, `maSlow` | Top 198-200 | bar T | no | yes |
| `regime` | Top 201 | bar T | no | yes |
| `rsiV` | Top 204 | bar T | no | yes |
| `atrV` | Top 205 | bar T | no | yes |
| `macdHist` | Top 206 | bar T | no | yes |
| `bullX` / `bearX` | Top 212-213 | bar T | no | **yes, and it is the main hazard** |
| `bullScore` / `bearScore` | Top 217-218 | bar T | no | yes |
| `bullSig` / `bearSig` (RULE B) | Top 219-220 | **bar T** | **no** | yes |
| `goldX` / `deadX` | Top 214-215 | bar T | no | yes |
| `ath` / `atl` | Top 223-226 | bar T | **yes -- depends on loaded history** | yes |
| `yo0/yo1/yo2/yYr` | Top 229-232 | bar T | no (lookahead is safe for a year's open) | no |
| `ph` / `pl` (price pivots) | Top 235-236 | bar T, describing bar T-10 | no | yes (the forming bar can disqualify) |
| `sigBar`/`sigDir`/`sigScore`/`sigEntry`/`sigStop` | Top 255-271 | the signal bar | no | yes on the signal bar |
| `extPx` / `extBar` | Top 272-279 | bar T (running) | no | yes |
| `sigFresh` | Top 280 | bar T | no | no (pure bar arithmetic) |
| `inOB` / `inOS` | Top 286-287 | bar T | no | yes |
| `rvDir` and the whole reversal state | Top 290-316 | bar T | no | yes |
| trade box prices `entRaw/stp/tp1..3` | Top 341-359 | the signal bar (Auto) / bar T (Manual) | no | Manual: yes |
| `rsi` (RSI+) | RSI+ 37 | bar T | no | yes |
| `rsiMa`, `longAvg` | RSI+ 38-41 | bar T | no | yes |
| `plFound` / `phFound` | RSI+ 44-45 | **bar T, describing bar T-5** | no | yes |
| `inRangeL` / `inRangeH` | RSI+ 53-54 | bar T | no | yes |
| `rsiHL`/`priceLL`/`rsiLH`/`priceHH` | RSI+ 56-61 | bar T | no | yes |
| `bullDiv` / `bearDiv` (RULE A) | RSI+ 58, 62 | **bar T, mark drawn at T-5** | **no** | yes |
| `hist`, `xUp`, `xDn` | MACD 25-34 | bar T | no | yes |

**Neither Rule A nor Rule B repaints on closed bars.** Both are safe to evaluate
once per day against the last closed daily bar. Neither needs a "wait N bars to
confirm" buffer; Rule A's 5-bar lag is already baked into when the condition
turns true.

---

## 9. Decorative versus decision

**Decisions** -- something else reads them:

| Quantity | Read by |
|---|---|
| `maType`, `maSrc`, `fastLen`, `midLen`, `slowLen` | `maFast`/`maMid`/`maSlow` |
| `maFast`, `maMid` | `bullX`, `bearX` |
| `maSlow` | `regime`, the `useSlow` score term |
| `macdHist` | the `useMacd` score term |
| `rsiV` | the `useRsi` score term (off), `rsiCol`, `inOB`, `inOS` |
| `bullX`, `bearX`, `bullScore`, `bearScore`, `showSig`, `minScore` | `bullSig`, `bearSig` |
| `bullSig`, `bearSig` | the signal `var` block, the arrows, the labels, `sigCol`, `alertcondition` |
| `sigBar`, `sigDir`, `sigEntry`, `sigStop`, `sigScore` | `sigFresh`, the trade box, the key table |
| `sigFresh` | `tFresh` -> `tShow` |
| `inOB`, `inOS` | the reversal state machine, `revNew` |
| `rvDir`, `rvActive` | `tShow` (suppresses the trend box), all reversal drawings, the key table |
| `atrV` | `sigStop`, `atrStp`, `rvStp`, the unboxed label offsets |
| `swLo`, `swHi` | `sigStop` |
| `revHH`, `revLL` | `rvStp`, `rvTgt` |
| `f_near` | which levels and which pivot S/R lines draw |
| `plFound`, `phFound`, `inRangeL/H`, `rsiHL`, `priceLL`, `rsiLH`, `priceHH`, `showDiv` | `bullDiv`, `bearDiv` |
| `bullDiv`, `bearDiv` | two `plot`s, two `plotshape`s, two `alertcondition`s -- **and nothing else, in any file** |

**Decorative** -- drawing only, nothing downstream:

`slowCol`, the Mid-Slow `fill`, both `bgcolor` calls, `rsiCol`/`sigCol`/`colCol`
(they only pick a colour), all thirteen `display.price_scale` plots (L382-394),
every `f_hline`/`f_seg`/`f_tag`/`f_name`/`f_zone` drawing, every box and line in
the last-bar block, the whole key table, `goldX`/`deadX` (label + alert only),
`longAvg`, `rsiMa` and all three `fill`s in the RSI+ pane, `midX`, `extCol`, and
the entire MACD pane (`histCol`, the three plots, `hline(0)`, `zc`, `xUp`,
`xDn`).

Note the asymmetry worth remembering: **the MACD pane is decorative, but the
MACD is a decision** -- because the Top script recomputes it (L206) rather than
reading the pane.

---

## 10. Pine-to-pandas parity notes (read before writing any scanner code)

These are the traps that will make a reimplementation disagree with the chart,
listed with the fix. They are not in the Pine files; they are properties of the
Pine built-ins the files call.

**10.1 Pine seeds its recursive averages with an SMA; `scanner/indicators.py`
does not.** TradingView's documented equivalent of `ta.ema` is:

```
pine_ema(src, length) =>
    alpha = 2 / (length + 1)
    sum = 0.0
    sum := na(sum[1]) ? ta.sma(src, length) : alpha * src + (1 - alpha) * nz(sum[1])
```
i.e. `na` for the first `length - 1` bars, then SMA of the first `length` values,
then the recursion. `ta.rma` (which `ta.rsi` and `ta.atr` are built on) does the
same with `alpha = 1 / length`.

This repo's `scanner/indicators.ema()` is `series.ewm(span=span,
adjust=False).mean()` -- recursive from bar 0, no SMA seed, no NaN warm-up.
`rsi()` (L57-58) and `atr()` (L72) likewise use `ewm(alpha=1/period,
adjust=False)` from bar 0.

Magnitude of the disagreement: the seeding error decays by `(1 - alpha)` per
bar. For RSI/ATR (`alpha = 1/14`) it is gone after ~150 bars. For the
**200-EMA** (`alpha = 2/201 = 0.00995`) about `0.67%` of the initial error
survives 500 bars, which is easily enough to flip `close > maSlow` for a name
sitting on its 200-EMA -- and that boolean is one of the two terms in RULE B.
**Fix: write a Pine-parity EMA (NaN for the first `length-1` bars, SMA seed at
index `length-1`, recursion after) rather than reusing `indicators.ema()`; and
give every symbol at least ~500 daily bars of warm-up before the evaluation
bar.**

**10.2 Warm-up lengths.** `ta.sma(src, n)` and `ta.ema(src, n)` are `na` until
`n` bars exist. Therefore, under default inputs:
- `maSlow` first exists at bar index 199.
- `macdLine` = `ema(12) - ema(26)` first exists at bar index 25;
  `signalLine` = `ema(macdLine, 9)` at bar index 33; `macdHist` at bar index 33.
- `rsi` first exists at bar index 14.
- `plFound` needs 11 RSI bars, so from bar index ~24; a DIVERGENCE needs two
  pivots at least 6 bars apart, so ~bar 35 at the absolute earliest.
Recommend a hard minimum of 250 bars to evaluate Rule A at all and 500 bars for
Rule B's `useSlow` term to be trustworthy. Below 200 bars `maSlow` is `na`, the
term scores 0, and Rule B degenerates to "cross + MACD agreement".

**10.3 `ta.rsi` on a flat series.** Pine's formula is
`rs = ta.rma(up, n) / ta.rma(down, n)`, `res = 100 - 100 / (1 + rs)`. With
`rma(down) == 0` and `rma(up) > 0` the result is 100. With BOTH zero (a genuinely
halted or suspended name) the division is 0/0 and the result is undefined. This
repo already fixed exactly this in `scanner/indicators.rsi()` (TOP100 #71): it
returns `NaN` for the both-zero case and `100.0` only for the
`avg_loss == 0 and avg_gain > 0` case. **Keep that behaviour.** A halted ASX
small cap must not read as RSI 100 and be flagged as overbought.

**10.4 `ta.crossover` uses `<=` on the previous bar**, not `<`. An exact touch on
bar T-1 followed by a break on bar T IS a cross. On ASX names quoted in
half-cents this is reachable.

**10.5 `ta.highest` / `ta.lowest` include the current bar.** `swLo`, `swHi`,
`revHH`, `revLL`, `rHi`, `rLo` all do. A pandas `rolling(n).min()` over a
right-aligned window matches; a `shift(1)` does not.

**10.6 `ta.pivotlow` / `ta.pivothigh` tie-breaking is undocumented.** See 4.2.
Use the strict form and validate against three live charts.

**10.7 Daily bars must be CLOSED.** Both rules flip freely intraday. For ASX the
daily bar closes 16:00 Melbourne; for NASDAQ 16:00 New York; crypto rolls at
00:00 UTC. yfinance returns a partial bar for the current session, and this repo
already has the machinery to reason about that (`scanner/data.py`'s
`_frame_age_days`, `merge_with_cache`, `FRAME_CACHE_MAX_AGE_DAYS`); reuse it
rather than re-deriving. A partial last bar must be DROPPED, not evaluated.

**10.8 Adjusted vs unadjusted prices.** TradingView charts ASX and NASDAQ equities
with its own adjustment policy; yfinance's default `auto_adjust` rewrites the
whole OHLC series for splits and dividends. Any difference changes the RSI, the
EMAs and the pivots, so a scanner hit and a chart mark can legitimately disagree
across a dividend. Pick one policy, record it, and expect small disagreements on
high-yield ASX names around ex-dates. This is a known, bounded source of false
positives and misses that no amount of code care removes.

**10.9 `ta.valuewhen` searches the whole history.** A pandas reimplementation
should carry the previous-pivot value forward with a forward-fill over the pivot
bars rather than a bounded lookback, or the first divergence after a long quiet
stretch will be missed.

---

## 11. Discrepancies found between the code and its own documentation

Recorded so the next reader does not have to re-derive them. None of these are
bugs in the Pine; they are places where prose and code disagree.

1. **`Final_Top_Script.pine` L28** -- "targets never go below zero". The code
   floors targets at `entRaw * 0.05` (L351-353), i.e. 5% of entry, not zero.
   Under Auto mode with the default 15% stop cap the floor is unreachable
   anyway (section 5.1).
2. **`tradingview/README.md` L64** -- "RSI extreme columns (RSI 14 at or above
   70 = green, at or below 30 = red)". The code's defaults are `rsiOB = 75` /
   `rsiOS = 25` (L81-82), and the README's own "What changed" section (L43-53)
   correctly says v2 moved them from 70/30 to 75/25. The table row is stale.
   70 and 30 DO still appear, but only in the RSI+ pane as `ob1` / `os1`, where
   they are a plotted band and the level for two `alertcondition`s -- they gate
   no column and no rule.
3. **`tradingview/README.md` L72** -- "capped at 15% of entry" for the trade box.
   True in Auto mode only. In Manual mode with `mSL = 0` the ATR fallback stop
   is NOT capped (L349).
4. **`Final_Top_Script.pine` L61** -- "Only the three lengths and the MA type
   show in the status line". Seventeen `input.color` calls also omit
   `display = display.none`; in practice TradingView does not surface colour
   inputs in the status line, so the effect matches the claim, but a file parser
   should not rely on the comment.
5. **`tradingview/README.md` L100** -- "34 slots" for the plot budget, while the
   file header L32 says "~31 slots". Both are estimates of the same thing made
   at the same time; neither was measured by a compiler (README L28-30 states no
   Pine compiler was available). Immaterial to a scanner.
6. The Top script's alert messages (L620-624) still say `"Final_Top_Script: ..."`
   although the indicator was renamed to `Vivek 5.0 Top` in v5.2. The RSI+ and
   MACD alert messages were updated to the new names. Cosmetic.

---

## 12. The two rules, restated as the scanner needs them

Not a design for the scanner -- just the two conditions in a form that can be
handed to an implementer without ambiguity. `T` = the latest CLOSED daily bar.

```
# Shared inputs: daily OHLCV, >= 500 bars ending at T, Pine-parity EMA/RMA.

# ---- RULE B: scored cross, |score| >= 2 -------------------------------------
maFast  = pine_ema(close, 20)
maMid   = pine_ema(close, 50)
maSlow  = pine_ema(close, 200)
macd    = pine_ema(close, 12) - pine_ema(close, 26)
signal  = pine_ema(macd, 9)
hist    = macd - signal

bullX[T] = maFast[T] >  maMid[T] and maFast[T-1] <= maMid[T-1]
bearX[T] = maFast[T] <  maMid[T] and maFast[T-1] >= maMid[T-1]

bullScore[T] = 1 + (1 if hist[T] > 0 else 0) + (1 if close[T] > maSlow[T] else 0)
bearScore[T] = 1 + (1 if hist[T] < 0 else 0) + (1 if close[T] < maSlow[T] else 0)
# NaN maSlow (fewer than 200 bars) contributes 0, exactly as Pine's na does.

ruleB_bull[T] = bullX[T] and bullScore[T] >= 2      # "Bullish +2" or "Bullish +3"
ruleB_bear[T] = bearX[T] and bearScore[T] >= 2      # "-2 Bearish" or "-3 Bearish"

# ---- RULE A: regular RSI divergence -----------------------------------------
rsi = pine_rsi(close, 14)                            # Wilder, RMA-seeded

plFound[t] = rsi[t-5] is strictly the lowest  of rsi[t-10 .. t]
phFound[t] = rsi[t-5] is strictly the highest of rsi[t-10 .. t]

# P  = t - 5           the candidate pivot bar
# P0 = t0 - 5          the previous pivot bar (t0 = previous plFound/phFound bar)

ruleA_bull[t] = plFound[t] and low[P]  < low[P0]  and rsi[P] > rsi[P0] and 6 <= P-P0 <= 61
ruleA_bear[t] = phFound[t] and high[P] > high[P0] and rsi[P] < rsi[P0] and 6 <= P-P0 <= 61

# Evaluate at t = T (confirmed today), or over t in [T-K, T] for a K-bar window.
# Report BOTH t (the detection bar) and t-5 (the bar the chart mark sits on).

# ---- Modes ------------------------------------------------------------------
mode1 = ruleA_bull or ruleA_bear
mode2 = mode1 or ruleB_bull or ruleB_bear
```

Expected hit rates, stated as an order of magnitude rather than a measurement
(none of this was backtested here): Rule A on ~3,700 names should produce a few
dozen hits a day, since each name prints an RSI pivot every ~10 bars and only a
minority of pivots diverge. Rule B is rarer per name -- a 20/50 EMA cross is a
handful of events per name per year -- so across 3,700 names expect tens of
crosses a day, most of which will score 2 or 3. Mode 2 should therefore land in
the low hundreds a day before any liquidity or product filter. If the real
numbers come out an order of magnitude away from that, the pivot tie-breaking
(10.6) or the EMA seeding (10.1) is the first thing to check.


---

# PART 4A - PINE BUILT-IN SEMANTICS, VERIFIED AGAINST PRIMARY DOCUMENTATION

Scope: the exact behaviour of every TradingView built-in that
`tradingview/Final_Top_Script.pine`, `tradingview/Final_Bottom_MACD.pine` and
`tradingview/Final_RSI_Plus.pine` depend on, to the level of detail needed for a
Python/pandas re-implementation that matches TradingView **bar for bar**.

Written for the scanner spec (ASX / NASDAQ / crypto, daily bars, Rule A =
RSI+ divergence label, Rule B = Top-overlay scored cross with |score| >= 2).

ASCII-only. Where an official quote contains a Unicode character I have
transliterated it and said so: the reference manual writes function signatures
with a right-arrow glyph, rendered here as `->`; the docs use curly quotes,
rendered here as straight quotes. Nothing else in any quote is altered.

---

## 0. Provenance: what "primary documentation" means here, exactly

tradingview.com is blocked from this sandbox. Two mirrors were used, and they
are not of equal standing. Both were re-fetched during this task (2026-09-22).

**Mirror A - the Pine Script v6 USER MANUAL (docs).**
`https://raw.githubusercontent.com/folknor/pine-tools/main/pine-manual/v6/<section>/<page>.md`
Each file carries YAML front matter naming the page it was scraped from, e.g.

```
---
title: Type system
source: https://www.tradingview.com/pine-script-docs/language/type-system/
section: language
---
```

Every manual citation below gives the **original tradingview.com URL from that
front matter** as the citation, and the mirror path so it can be re-fetched.

Full page list (there is no directory API from this sandbox; this is
`git ls-tree` of the repo, so it is complete):
`language/{arrays,built-ins,conditional-structures,declaration-statements,enums,execution-model,identifiers,loops,maps,matrices,methods,objects,operators,script-structure,type-system,user-defined-functions,variable-declarations}`,
`concepts/{alerts,bar-states,chart-information,inputs,libraries,non-standard-charts-data,other-timeframes-and-data,repainting,sessions,strategies,strings,time,timeframes}`,
`visuals/{backgrounds,bar-coloring,bar-plotting,colors,fills,levels,lines-and-boxes,overview,plots,tables,text-and-shapes}`,
`writing/{debugging,limitations,profiling-and-optimization,publishing,style-guide}`,
`faq/{alerts,data-structures,functions,general,indicators,other-data-and-timeframes,programming,strategies,strings-and-formatting,techniques,times-dates-and-sessions,variables-and-operators,visuals}`,
`errors/{CE10101,CE10117,CW10003,RE10139,RE10143,overview}`,
`migration-guides/*`, `primer/*`, `release-notes.md`, `welcome.md`.

Note: `concepts/plots.md` does **not** exist (it is `visuals/plots.md`), and
there is no `writing/limitations` 404 - the task brief's suggested section names
are only partly right. See Corrections at the end.

**Mirror B - the Pine Script v6 REFERENCE MANUAL (per-function pages).**
`https://raw.githubusercontent.com/folknor/pine-tools/main/pine-data/v6/functions.json`
(1.06 MB, 475 functions). This is the machine-readable scrape of
`https://www.tradingview.com/pine-script-reference/v6/`. Its own metadata block
(`pine-data/raw/v6/complete-v6-details.json`) states the provenance:

```json
{"extractedAt": "2026-09-07T05:02:05.256Z",
 "source": "https://www.tradingview.com/pine-script-reference/v6/",
 "totalFunctions": 475, "successfulScrapes": 475, "method": "Puppeteer"}
```

Spot-checked against text I can independently recall from the official
reference (`alert()`, `ta.rsi()`, `ta.rma()` including their "same on pine"
example code): the descriptions, remarks and example blocks are **verbatim**.
Two known scrape artifacts, called out so nobody codes to them:
`ta.valuewhen` is listed as returning `series color` and `nz` as `simple color`
- both are overload-collapsing artifacts of the scraper, not real return types.
The return type of `ta.valuewhen` follows its `source` argument.

**Mirror C - TradingView's own published `ta` library** (their pure-Pine
reference implementations, vendored at `vendor/TradingView/ta/12.pine`). This is
TradingView's own code, published on TradingView, and is used below only to
corroborate recursions - never as the sole authority.

`https://www.tradingview.com/pine-script-reference/v6/` also could not be
reached to confirm the two places where the reference is genuinely SILENT
(pivot tie-breaking, MA warm-up). Those two are flagged as UNVERIFIED in
section 3 rather than guessed at.

Re-fetch recipe (works from this sandbox; github.com HTML and api.github.com
are both 403, raw.githubusercontent.com and `git clone` are not):

```bash
git clone --depth 1 --filter=blob:none --no-checkout \
  https://github.com/folknor/pine-tools.git pt
cd pt && git checkout HEAD -- pine-manual pine-data vendor/TradingView
```

---

## 1. Per-built-in verification

Each entry: **VERDICT** (the one line a coder needs), **CITATION**, **QUOTE**
(verbatim), **PANDAS**.

Throughout, `df` is a DataFrame of daily bars indexed by date, ascending, one
row per closed bar, columns `open/high/low/close/volume`.

---

### 1.1 `ta.rsi(source, length)` - Wilder / RMA smoothing, SMA-seeded

**VERDICT.** RSI is built on `ta.rma` (Wilder), NOT on a plain EMA and NOT on a
rolling mean. Because `ta.rma` seeds itself with an SMA (see 1.2), `ta.rsi` is
exactly the classic Wilder RSI, and matches TA-Lib's `RSI`. Its first non-na
value lands on **bar index `length`** (0-based) of a gap-free series, because
the change series is na on bar 0, so `length` non-na changes are first available
at bar `length`.

**CITATION.** https://www.tradingview.com/pine-script-reference/v6/#fun_ta.rsi
(mirror: `pine-data/v6/functions.json`, entry `ta.rsi`)

**QUOTE.**
> `ta.rsi(source, length) -> series float`
>
> Relative strength index. It is calculated using the ta.rma() of upward and
> downward changes of source over the last length bars.
>
> Remarks: na values in the source series are ignored; the function calculates
> on the length quantity of non-na values.
>
> ```
> // same on pine, but less efficient
> pine_rsi(x, y) =>
>     u = math.max(x - x[1], 0) // upward ta.change
>     d = math.max(x[1] - x, 0) // downward ta.change
>     rs = ta.rma(u, y) / ta.rma(d, y)
>     res = 100 - 100 / (1 + rs)
>     res
> ```

Note the official example's exact definitions: `u = max(x - x[1], 0)` and
`d = max(x[1] - x, 0)`. On an unchanged bar BOTH are 0 (not na, not skipped).

**PANDAS.**

```python
def ta_rsi(src: pd.Series, length: int = 14) -> pd.Series:
    d = src.astype(float).diff()                       # na on bar 0, as in Pine
    up, dn = d.clip(lower=0), (-d).clip(lower=0)
    up.iloc[0] = np.nan; dn.iloc[0] = np.nan           # bar 0 change is na
    rs = ta_rma(up, length) / ta_rma(dn, length)       # ta_rma from 1.2
    return 100.0 - 100.0 / (1.0 + rs)
```

Do NOT write `src.diff().clip(lower=0).ewm(alpha=1/length, adjust=False).mean()`
- that is a different seed and a different number. Measured divergence in 1.13.

---

### 1.2 `ta.rma(source, length)` - alpha = 1/length, seeded with `ta.sma`

**VERDICT.** The recurrence is `rma[i] = alpha*src[i] + (1-alpha)*rma[i-1]`
with `alpha = 1/length`, and the **seed is the SMA of the first `length`
non-na values**, not the first value. This is the single most important
seeding fact in the whole port: pandas `ewm(alpha=1/length, adjust=False)`
seeds with the first value and is therefore NOT `ta.rma`.

**CITATION.** https://www.tradingview.com/pine-script-reference/v6/#fun_ta.rma

**QUOTE.**
> `ta.rma(source, length) -> series float`
>
> Moving average used in RSI. It is the exponentially weighted moving average
> with alpha = 1 / length.
>
> Returns: Exponential moving average of source with alpha = 1 / length.
>
> Remarks: na values in the source series are ignored; the function calculates
> on the length quantity of non-na values.
>
> ```
> //the same on pine
> pine_rma(src, length) =>
>     alpha = 1/length
>     sum = 0.0
>     sum := na(sum[1]) ? ta.sma(src, length) : alpha * src + (1 - alpha) * nz(sum[1])
> ```

`na(sum[1]) ? ta.sma(src, length) : ...` is the seed statement. Because
`ta.sma(src, length)` is itself na until `length` non-na values exist (1.4),
the first `rma` value appears on the bar where the `length`-th non-na source
value arrives, and equals the simple mean of those `length` values.

Corroboration, TradingView's own `ta` library (`vendor/TradingView/ta/12.pine`),
exported as `rma2()` for series lengths:

```pine
ewma(series float source, series float alpha) =>
    float result = na
    result := alpha * source + (1.0 - alpha) * nz(result[1], source)

export rma2(series float source, series float length) =>
    float alpha  = 1.0 / length
    float result = ewma(source, alpha)
```

**Warning:** `rma2` seeds with `source` (`nz(result[1], source)`), NOT with the
SMA. TradingView's own alternative is therefore **not** bit-identical to
`ta.rma`; it is the "no warm-up" variant. Port `ta.rma`, not `rma2`.

**PANDAS.**

```python
def ta_rma(src: pd.Series, length: int) -> pd.Series:
    s = src.astype(float)
    v = s.dropna()                                     # "na values are ignored"
    out = pd.Series(np.nan, index=s.index, dtype=float)
    if len(v) < length:
        return out
    a = 1.0 / length
    acc = float(v.iloc[:length].mean())                # <-- the SMA seed
    out.loc[v.index[length - 1]] = acc
    for ts, x in v.iloc[length:].items():
        acc = a * float(x) + (1.0 - a) * acc
        out.loc[ts] = acc
    return out
```

One-liner equivalent only when the source has no interior na and you accept the
seed handling explicitly:
`pd.concat([pd.Series([s.iloc[:length].mean()]), s.iloc[length:]]).ewm(alpha=1/length, adjust=False).mean()`
- prepending the SMA as the first element of an `ewm(adjust=False)` chain
reproduces the seed exactly. The loop above is clearer and is what should ship.

---

### 1.3 `ta.ema(source, length)` - alpha = 2/(length+1), adjust=False, seeded with the first value

**VERDICT.** `adjust=False` style, exactly. The documented recursion seeds with
the source value on the first bar, which is precisely what pandas
`ewm(span=length, adjust=False)` does. So **`ta.ema` IS
`s.ewm(span=length, adjust=False).mean()`** on the same history, modulo the
undocumented warm-up window (see 3.2). This is the one indicator here where the
naive pandas call is right.

**CITATION.** https://www.tradingview.com/pine-script-reference/v6/#fun_ta.ema

**QUOTE.**
> `ta.ema(source, length) -> series float`
>
> The ema function returns the exponentially weighted moving average. In ema
> weighting factors decrease exponentially. It calculates by using a formula:
> EMA = alpha * source + (1 - alpha) * EMA[1], where alpha = 2 / (length + 1).
>
> Remarks: Please note that using this variable/function can cause indicator
> repainting. na values in the source series are ignored; the function
> calculates on the length quantity of non-na values.
>
> ```
> //the same on pine
> pine_ema(src, length) =>
>     alpha = 2 / (length + 1)
>     sum = 0.0
>     sum := na(sum[1]) ? src : alpha * src + (1 - alpha) * nz(sum[1])
> ```

`na(sum[1]) ? src : ...` - seed is the first source value. Corroborated by
TradingView's own `ema2()`, which calls the same `ewma()` helper quoted in 1.2
with `alpha = 2.0 / (math.max(1.0, length) + 1.0)` and `nz(result[1], source)`.

Note `alpha = 2 / (length + 1)` is computed with integer literals in the doc
example but Pine promotes to float; use `2.0 / (length + 1.0)`.

**PANDAS.**

```python
ta_ema = lambda s, length: s.astype(float).ewm(span=length, adjust=False).mean()
# identical to: s.ewm(alpha=2.0/(length+1.0), adjust=False).mean()
```

---

### 1.4 `ta.sma(source, length)` - plain rolling mean, window INCLUDES the current bar

**VERDICT.** Rolling arithmetic mean over `length` bars ending at and including
the current bar; na until `length` bars exist. Used by `Final_RSI_Plus`
(`maType` default "SMA", `maLen` 14; `longLen` 50) and available in
`Final_Top_Script`'s `f_ma()` when `maType` is switched to "SMA".

**CITATION (1).** https://www.tradingview.com/pine-script-reference/v6/#fun_ta.sma

**QUOTE (1).**
> The sma function returns the moving average, that is the sum of last y values
> of x, divided by y.
>
> Returns: Simple moving average of source for length bars back.
>
> Remarks: na values in the source series are ignored.

**CITATION (2).** https://www.tradingview.com/pine-script-docs/language/execution-model/
(mirror: `pine-manual/v6/language/execution-model.md`, line 251)

**QUOTE (2).** This is the one that nails "inclusive" and "na during warm-up":
> The call returns the average of the latest 20 close values as of the current
> bar, or na if fewer than 20 bars are available.

**PANDAS.** `s.rolling(length, min_periods=length).mean()`

---

### 1.5 `ta.macd(source, fastlen, slowlen, siglen)` - returns [macd, signal, histogram] in that order

**VERDICT.** Three returns, in this order: **MACD line, signal line,
histogram**. All three legs are `ta.ema`. `hist = macd - signal`.

`Final_Bottom_MACD.pine` destructures it correctly:
`[macdLine, sigLine, hist] = ta.macd(src, fastLen, slowLen, sigLen)`.
`Final_Top_Script.pine` likewise: `[macdLine, macdSignal, macdHist] = ...`,
and only `macdHist` feeds the score (`macdHist > 0` / `macdHist < 0`).

**CITATION.** https://www.tradingview.com/pine-script-reference/v6/#fun_ta.macd

**QUOTE.**
> `ta.macd(source, fastlen, slowlen, siglen) -> [series float, series float, series float]`
>
> MACD (moving average convergence/divergence). It is supposed to reveal changes
> in the strength, direction, momentum, and duration of a trend in a stock's
> price.
>
> Returns: Tuple of three MACD series: MACD line, signal line and histogram line.
>
> ```
> [macdLine, signalLine, histLine] = ta.macd(close, 12, 26, 9)
> ```

The reference does not spell out the three formulas. TradingView's own `ta`
library does, in `macd2()` (`vendor/TradingView/ta/12.pine`), and it is the
textbook definition:

```pine
export macd2(series float source, series float fastLen, series float slowLen, series float sigLen) =>
    float maFast = ema2(source, fastLen)
    float maSlow = ema2(source, slowLen)
    float macd   = maFast - maSlow
    float signal = ema2(macd, sigLen)
    float hist   = macd - signal
    [macd, signal, hist]
```

So: `macd = ema(src, fast) - ema(src, slow)`, `signal = ema(macd, sig)`,
`hist = macd - signal`. Signal is an EMA **of the MACD line**, i.e. an EMA of an
EMA difference - the seeding of the inner EMAs propagates into it twice.

**PANDAS.**

```python
def ta_macd(src, fast=12, slow=26, sig=9):
    macd = ta_ema(src, fast) - ta_ema(src, slow)
    signal = ta_ema(macd, sig)
    return macd, signal, macd - signal
```

---

### 1.6 `ta.atr(length)` and `ta.tr(handle_na)` - RMA of true range, first bar falls back to high-low

**VERDICT.** `ta.atr(length) = ta.rma(ta.tr(true), length)` - Wilder smoothing
(so SMA-seeded, per 1.2), and the true range on the first bar (where `close[1]`
is na) is `high - low`, not na.

Used only by `Final_Top_Script` (`atrV = ta.atr(14)`), and only for the trade
box / stop drawing - it is **not** part of Rule A or Rule B. Port it only if
the scanner also wants to reproduce the stop ladder.

**CITATION.** https://www.tradingview.com/pine-script-reference/v6/#fun_ta.atr
and https://www.tradingview.com/pine-script-reference/v6/#fun_ta.tr

**QUOTE (atr).**
> `ta.atr(length) -> series float`
>
> Function atr (average true range) returns the RMA of true range. True range is
> max(high - low, abs(high - close[1]), abs(low - close[1])).
>
> ```
> //the same on pine
> pine_atr(length) =>
>     trueRange = na(high[1])? high-low : math.max(math.max(high - low, math.abs(high - close[1])), math.abs(low - close[1]))
>     //true range can be also calculated with ta.tr(true)
>     ta.rma(trueRange, length)
> ```

**QUOTE (tr).**
> Calculates the current bar's true range. Unlike a bar's actual range
> (high - low), true range accounts for potential gaps by taking the maximum of
> the current bar's actual range and the absolute distances from the previous
> bar's close to the current bar's high and low. The formula is:
> math.max(high - low, math.abs(high - close[1]), math.abs(low - close[1])).
>
> handle_na: Defines how the function calculates the result when the previous
> bar's close is na. If true, the function returns the bar's high - low value.
> If false, it returns na.
>
> Remarks: ta.tr(false) is exactly the same as ta.tr.

Corroboration: TradingView's `atr2()` is `ewma(ta.tr(true), 1.0/length)`, i.e.
the `handle_na = true` variant. Note the doc's `pine_atr` guards on
`na(high[1])`, not `na(close[1])` - same thing on bar 0.

**PANDAS.**

```python
def ta_tr(df, handle_na=True):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - pc).abs(),
                    (df["low"]  - pc).abs()], axis=1).max(axis=1)
    if handle_na:
        tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    else:
        tr.iloc[0] = np.nan
    return tr

ta_atr = lambda df, length=14: ta_rma(ta_tr(df, True), length)
```

---

### 1.7 `ta.pivothigh` / `ta.pivotlow` - WHAT value, on WHICH bar

**VERDICT, and this is the highest-risk off-by-one in the spec.**

For `ta.pivotlow(source, leftbars, rightbars)`:
- the **value returned** is `source[rightbars]`, i.e. the source value at the
  candidate bar, which sits `rightbars` bars BEHIND the bar doing the returning;
- it is returned **on the confirmation bar**, `rightbars` bars AFTER the pivot
  bar - not on the pivot bar;
- on every other bar it returns **na** (the reference says 'NaN'; in Pine that
  is the same thing);
- the 3-argument overload `(source, leftbars, rightbars)` exists and is what
  `Final_RSI_Plus.pine` uses: `ta.pivotlow(rsi, lbL, lbR)` with `lbL = lbR = 5`.

**CITATION (1), the function.**
https://www.tradingview.com/pine-script-reference/v6/#fun_ta.pivotlow

**QUOTE (1).**
> `ta.pivotlow(leftbars, rightbars) -> series float`
>
> This function returns price of the pivot low point. It returns 'NaN', if there
> was no pivot low point.
>
> Returns: Price of the point or 'NaN'.
>
> leftbars: Left strength. rightbars: Right strength.
> source: An optional parameter. Data series to calculate the value.
> 'Low' by default.
>
> Overloads:
>   ta.pivotlow(leftbars, rightbars) -> series float
>   ta.pivotlow(source, leftbars, rightbars) -> series float
>
> ```
> pl = ta.pivotlow(close, leftBars, rightBars)
> plot(pl, style=plot.style_cross, linewidth=3, color= color.blue, offset=-rightBars)
> ```

The `offset=-rightBars` in TradingView's own example is the proof of the lag:
the value has to be pushed `rightbars` bars back to land on the pivot.

**CITATION (2), which bar.**
https://www.tradingview.com/pine-script-docs/visuals/plots/
(mirror: `pine-manual/v6/visuals/plots.md`, line 289)

**QUOTE (2).**
> Our pivots are detected three bars after they occur because we use the
> argument `3` for both the `leftbars` and `rightbars` parameters in our
> ta.pivothigh() call.

and, on the same page, on the realtime consequence:
> Note how the pivot on the bar indicated by the arrow has just been detected in
> the realtime bar, three bars later, and how no plot is drawn.

**CITATION (3), the value is the pivot bar's value.**
https://www.tradingview.com/pine-script-docs/concepts/repainting/
(mirror: `pine-manual/v6/concepts/repainting.md`, "Plotting in the past")

**QUOTE (3).**
> Scripts detecting pivots after 5 bars have elapsed will often go back in the
> past to plot pivot levels or values on the actual pivot, 5 bars in the past.
>
> ```
> pHi = ta.pivothigh(5, 5)
> if not na(pHi)
>     label.new(bar_index[5], na, str.tostring(pHi, format.mintick) + ...)
> ```

`bar_index[5]` with `rightbars = 5`: the returned `pHi` belongs at
`bar_index - 5`.

**TIE-BREAKING: STRICT vs NON-STRICT - NOT DOCUMENTED. See section 3.1.**
The reference manual says nothing about equal values on either side. Best
available evidence points to **strict on both sides** (a tie kills the pivot,
so a flat region produces no pivot). Implement strict, and read 3.1 before
relying on it.

**PANDAS.** Written to make the two lags explicit and to keep the "value on the
confirmation bar" convention, because the whole scan rule hangs on it:

```python
def ta_pivotlow(src: pd.Series, left: int, right: int) -> pd.Series:
    """Value of the pivot low, placed on the CONFIRMATION bar (pivot + right)."""
    v = src.to_numpy(dtype=float)
    n = len(v)
    out = np.full(n, np.nan)
    for i in range(left + right, n):
        p = i - right
        c = v[p]
        if np.isnan(c):
            continue
        win = np.concatenate((v[p - left:p], v[p + 1:p + right + 1]))
        if np.isnan(win).any():
            continue
        if (win > c).all():                 # STRICT both sides - see 3.1
            out[i] = c
    return pd.Series(out, index=src.index)

def ta_pivothigh(src, left, right):
    return -ta_pivotlow(-src, left, right)  # sign-flip; ties stay strict
```

Vectorised alternative that is equivalent when there are no na holes:

```python
w = 2 * right + 1  # only valid when left == right
roll_min = src.rolling(left + right + 1).min()
is_piv = (src.shift(right) == roll_min) & \
         (src.shift(right) < src.rolling(left + right + 1).apply(...))  # do not
```
Do NOT use the `== rolling.min()` trick: on a flat window the centre equals the
min and you get a pivot where strict Pine gives none. Use the explicit loop, or
compare the centre against the min of the window with the centre removed.

---

### 1.8 `ta.valuewhen(condition, source, occurrence)` - occurrence 0 IS the current bar when the condition is true now

**VERDICT.** Yes. Occurrence numbering starts at 0 for the **most recent**
occurrence, and if `condition` is true on the current bar then that bar IS
occurrence 0. Occurrence 1 is then the previous occurrence. Returns na if there
have been fewer than `occurrence + 1` occurrences.

This matters directly: in `Final_RSI_Plus.pine`,
`ta.valuewhen(plFound, rsi[lbR], 1)` is evaluated on a bar where `plFound` is
true, so occurrence 0 is *this* pivot and occurrence 1 is the **previous**
pivot. That is the intended "compare this pivot to the last one" semantics, and
it only works because occurrence 0 includes the current bar.

**CITATION (1).**
https://www.tradingview.com/pine-script-reference/v6/#fun_ta.valuewhen

**QUOTE (1).**
> Returns the value of the source series on the bar where the condition was true
> on the nth most recent occurrence.
>
> occurrence: The occurrence of the condition. The numbering starts from 0 and
> goes back in time, so '0' is the most recent occurrence of condition, '1' is
> the second most recent and so forth. Must be an integer >= 0.
>
> Remarks: This function requires execution on every bar. It is not recommended
> to use it inside a for or while loop structure, where its behavior can be
> unexpected. Please note that using this function can cause indicator
> repainting.

**CITATION (2), the proof that "most recent" includes the current bar.**
https://www.tradingview.com/pine-script-docs/language/variable-declarations/
(mirror: `pine-manual/v6/language/variable-declarations.md`, lines 1057-1058
and the surrounding explanation)

**QUOTE (2).**
> ```
> bool newPeriod = timeframe.change("1D")
> // Retrieve the `time` and `open` values from the last bar where the `newPeriod` value was `true`,
> // and assign the results to variables.
> int   openTime  = ta.valuewhen(newPeriod, time, 0)
> float openPrice = ta.valuewhen(newPeriod, open, 0)
> ...
> // On historical bars where a new period starts, draw a line connecting the period's final values.
> else if newPeriod
>     currLine := line.new(openTime[1], openPrice[1], time[1], close[1], xloc.bar_time)
> ```

The script has to write `openTime[1]` on a bar where `newPeriod` is true in
order to reach the PREVIOUS period's open - which is only necessary because
`ta.valuewhen(newPeriod, time, 0)` has already switched to the current bar.

**PANDAS.**

```python
def ta_valuewhen(cond: pd.Series, src: pd.Series, occurrence: int) -> pd.Series:
    """Value of src at the (occurrence+1)-th most recent bar where cond is true,
    counting the current bar as occurrence 0 when cond is true on it."""
    c = cond.fillna(False).to_numpy(bool)
    s = src.to_numpy(dtype=float)
    hits, out = [], np.full(len(s), np.nan)
    for i in range(len(s)):
        if c[i]:
            hits.append(i)                  # current bar counted BEFORE the read
        if len(hits) > occurrence:
            out[i] = s[hits[-1 - occurrence]]
    return pd.Series(out, index=src.index)
```

The `if c[i]: hits.append(i)` must come **before** the read. Swapping those two
lines is the classic off-by-one and it silently turns "this pivot vs the last
one" into "the last pivot vs the one before".

---

### 1.9 `ta.barssince(condition)` - ZERO on a bar where the condition is true, na before the first occurrence

**VERDICT.** `0`, not `1`. And `na` (not 0, not -1) until the condition has been
true at least once.

**CITATION (1).**
https://www.tradingview.com/pine-script-reference/v6/#fun_ta.barssince

**QUOTE (1).**
> Counts the number of bars since the last time the condition was true.
>
> Returns: Number of bars since condition was true.
>
> Remarks: If the condition has never been met prior to the current bar, the
> function returns na. Please note that using this variable/function can cause
> indicator repainting.

**CITATION (2), the explicit zero.**
https://www.tradingview.com/pine-script-docs/faq/functions/
(mirror: `pine-manual/v6/faq/functions.md`, line 29)

**QUOTE (2).**
> Secondly, when the condition is met, ta.barssince() returns zero for that bar,
> since zero bars have elapsed since the condition was last true.
>
> Since lengths cannot be zero, it is necessary to add one to a returned value
> of zero, ensuring that the length is always at least one.

and immediately before it:
> Firstly, before the condition is met for the first time in a chart's history,
> ta.barssince() returns na. This value is not usable as a length for functions
> and can cause errors [...] use nz() to replace the na return [...] with zero
> for early bars.

**PANDAS.**

```python
def ta_barssince(cond: pd.Series) -> pd.Series:
    c = cond.fillna(False).to_numpy(bool)
    out, last = np.full(len(c), np.nan), -1
    for i in range(len(c)):
        if c[i]:
            last = i
        if last >= 0:
            out[i] = i - last               # 0 on the bar itself
    return pd.Series(out, index=cond.index)
```

Vectorised: `idx = np.where(c, np.arange(n), np.nan); out = np.arange(n) - pd.Series(idx).ffill()`
- gives the same result including the leading NaNs.

---

### 1.10 `ta.crossover` / `ta.crossunder` / `ta.cross` - the exact two-bar test, and NaN

**VERDICT.**
- `ta.crossover(a, b)` == `a[i] > b[i] and a[i-1] <= b[i-1]`. Note the
  **non-strict `<=` on the previous bar**: a bar where they were exactly equal
  and then `a` rises DOES count as a crossover.
- `ta.crossunder(a, b)` == `a[i] < b[i] and a[i-1] >= b[i-1]`.
- With NaN anywhere in the four operands the result is **`false`**, never NaN -
  because a Pine "bool" is never na, and a comparison with an na operand is
  `false`. Two independent citations below.

**CITATION (1).**
https://www.tradingview.com/pine-script-reference/v6/#fun_ta.crossover
and .../#fun_ta.crossunder and .../#fun_ta.cross

**QUOTE (1).**
> ta.crossover: The source1-series is defined as having crossed over
> source2-series if, on the current bar, the value of source1 is greater than
> the value of source2, and on the previous bar, the value of source1 was less
> than or equal to the value of source2.
>
> ta.crossunder: The source1-series is defined as having crossed under
> source2-series if, on the current bar, the value of source1 is less than the
> value of source2, and on the previous bar, the value of source1 was greater
> than or equal to the value of source2.
>
> ta.cross: Returns: true if two series have crossed each other, otherwise
> false.

(The reference gives `ta.cross` no description text at all - only that return
line. Treat it as `crossover or crossunder`. `Final_RSI_Plus` uses it only for
the cosmetic midline-cross column, `midX = ta.cross(rsi, midL)`, which is off by
default: `showMidCols` defaults false.)

**CITATION (2), NaN.**
https://www.tradingview.com/pine-script-docs/language/type-system/
(mirror: `pine-manual/v6/language/type-system.md`, "na value" section and the
"bool" section)

**QUOTE (2).**
> It is crucial to note that scripts cannot directly compare values to na,
> because by definition, na values are undefined. The ==, != operators, and all
> other comparison operators always return `false` if at least one of the
> operands is a variable with an na value.

> In contrast to most other types, values of the "bool" type are never na. Any
> expression or structure with the "bool" return type returns `false` instead of
> na if data is not available.
>
> For example, if a script uses the history-referencing operator to retrieve the
> value of a "bool" variable from a previous bar that does not exist, that
> operation returns `false`.

**PANDAS.**

```python
def ta_crossover(a, b):
    a, b = a.astype(float), b.astype(float)
    return ((a > b) & (a.shift(1) <= b.shift(1))).fillna(False)

def ta_crossunder(a, b):
    a, b = a.astype(float), b.astype(float)
    return ((a < b) & (a.shift(1) >= b.shift(1))).fillna(False)
```

NumPy already returns `False` for any comparison involving NaN, so `&` of two
such comparisons is already `False` - the `.fillna(False)` is there for the
`shift(1)` on bar 0 producing NA in a nullable dtype. Keep it: it makes the
"bool is never na" rule explicit rather than incidental.

---

### 1.11 `ta.highest` / `ta.lowest` - INCLUSIVE of the current bar

**VERDICT.** Yes, inclusive. `ta.highest(src, 1)` is the current bar's own
value. `ta.highest(src, n)` spans bars `i-n+1 .. i`. The one-argument form uses
`high` (and `ta.lowest` uses `low`) as the source.

**CITATION (1).**
https://www.tradingview.com/pine-script-reference/v6/#fun_ta.highest

**QUOTE (1).**
> Highest value for a given number of bars back.
>
> Remarks: Two args version: source is a series and length is the number of bars
> back. One arg version: length is the number of bars back. Algorithm uses high
> as a source series. na values in the source series are ignored.

(`ta.lowest`: identical wording with "Lowest" and "uses low as a source".)

**CITATION (2), the proof of inclusivity.**
https://www.tradingview.com/pine-script-docs/faq/functions/
(mirror: `pine-manual/v6/faq/functions.md`)

**QUOTE (2).**
> ```
> // Identify the start of a new day and calculate the number of bars since then.
> bool newDay  = timeframe.change("D")
> int lookback = nz(ta.barssince(newDay)) + 1
>
> // Calculate the highest and lowest point since the new day began.
> float lowestSinceNewDay  = ta.lowest(lookback)
> float highestSinceNewDay = ta.highest(lookback)
> ```

On the new-day bar itself, `ta.barssince(newDay)` is 0 (1.9), so `lookback` is
1, and the doc calls the result "the highest point since the new day began" -
which on that bar is the current bar's own high. Inclusive, proven.

Corroborating quote for the same convention on `ta.sma`:
https://www.tradingview.com/pine-script-docs/language/execution-model/
> The call returns the average of the latest 20 close values **as of the current
> bar** [...]

**PANDAS.** `s.rolling(length, min_periods=length).max()` /
`.min()` - pandas `rolling` is right-aligned and inclusive of the current row,
so it already matches. Use `min_periods=length` so the warm-up is NaN like Pine.

---

### 1.12 The 64 plot-count limit, and how const / input / series colour is charged

**VERDICT.** 64 plot counts per script. A `plot()` with a **const** colour costs
**1**. A `plot()` whose colour argument is **"simple", "input" OR "series"**
costs **2**. `alertcondition()` costs 1 each. `bgcolor()` costs 1.
`fill()` costs 1 **only if** its colour is a series. `hline()`, `line.new()`,
`label.new()`, `box.new()`, `table.new()` cost **0**.

This confirms the claim in `Final_Top_Script.pine`'s own v5.3 header comment -
"The real rule: a plot with a const colour = 1 slot, an input or series colour =
2" - which was derived empirically from a live RE10140 error. The docs state it
outright, including the `input.color()` case by name.

**CITATION (1).**
https://www.tradingview.com/pine-script-docs/visuals/plots/
(mirror: `pine-manual/v6/visuals/plots.md`, "Plot count limit")

**QUOTE (1).**
> Each script is limited to a maximum plot count of 64. All `plot*()` calls and
> alertcondition() calls count towards the plot count of a script. Depending on
> the complexity of the plot and its arguments, certain calls count as more than
> one plot in the total plot count.
>
> For example, a plot() call counts as one plot in the total plot count if it
> uses a "const color" argument for its `color` parameter, because the color is
> known at compile time:
>
> ```
> plot(close, color = color.green)
> ```
>
> A plot() call counts as two plots in the total plot count if it uses a
> stronger qualified type for its `color` argument, such as any one of the
> following, because the resulting color is dynamic:
>
> ```
> plot(close, color = syminfo.mintick > 0.0001 ? color.green : color.red) // "simple color"
> plot(close, color = input.color(color.purple)) // "input color"
> plot(close, color = close > open ? color.green : color.red) // "series color"
> plot(close, color = color.new(color.silver, close > open ? 40 : 0)) // "series color"
> ```

(The arrow glyphs in the original comments are transliterated; the code is
otherwise verbatim.)

**CITATION (2), the full charging table.**
https://www.tradingview.com/pine-script-docs/writing/limitations/
(mirror: `pine-manual/v6/writing/limitations.md`, "Plot limits")

**QUOTE (2).**
> A maximum of 64 plot counts are allowed per script. The functions that
> generate plot counts are: plot(), plotarrow(), plotbar(), plotcandle(),
> plotchar(), plotshape(), alertcondition(), bgcolor(), barcolor(), fill(), but
> only if its `color` is of the series form.
>
> The following functions do not generate plot counts: hline(), line.new(),
> label.new(), table.new(), box.new().
>
> One function call can generate up to seven plot counts, depending on the
> function and how it is called. When your script exceeds the maximum of 64 plot
> counts, the runtime error message will display the plot count generated by
> your script.
>
> ```
> // Uses one plot count each.
> p1 = plot(close, color = color.white)
> p2 = plot(open, color = na)
>
> // Uses two plot counts for the `close` and `color` series.
> plot(close, color = isUpColor)
> ...
> // Uses one plot count.
> alertcondition(close > open, "close > open", "Up bar alert")
>
> // Uses one plot count.
> bgcolor(isUp ? color.yellow : color.white)
>
> // Uses one plot count for the `color` series.
> fill(p1, p2, color = isUpColor)
> ```

**PANDAS.** Not applicable - but it IS relevant to the port in one way: this
limit is why `Final_Top_Script.pine` hides most of its levels behind
`display.none` inputs and draws them with `line.new`/`label.new`/`box.new`
instead of `plot`. A Python scanner has no such limit and should not copy those
contortions. Note also that `Final_RSI_Plus.pine` spends 4 plot counts on
`alertcondition()` alone and that each of its colour-carrying plots costs 2
because `cRsi`/`cMa`/`cUp`/`cDn` are `input.color()`.

---

### 1.13 Extra semantics the three scripts depend on (verified, not on the task list, but load-bearing)

**(a) Pine comparisons round floats to NINE fractional digits.**

CITATION: https://www.tradingview.com/pine-script-docs/language/type-system/
QUOTE:
> The internal precision of "float" values in Pine Script is 1e-16.
> Floating-point values in Pine cannot precisely represent numbers with more
> than 16 fractional digits. However, note that comparison operators
> automatically round "float" operands to nine fractional digits.

Consequence: two values that differ by less than 5e-10 compare **equal** in
Pine and **unequal** in Python. Every `>` in these scripts (`macdHist > 0`,
`close > maSlow`, `rsi >= rsiMa`, the crossovers, and the pivot comparisons) is
affected. In Python, compare with `round(x, 9)` on both sides, or subtract and
test against a 5e-10 epsilon, if you want strict parity on near-ties.

**(b) v6 `and` / `or` are lazily evaluated, which is why the RSI+ script hoists
its `ta.barssince()` calls.**

CITATION: https://www.tradingview.com/pine-script-docs/release-notes/ and
https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/
QUOTE:
> Values of the "bool" type are now strictly `true` or `false`. They are never
> na in v6. Additionally, the or and and operators now feature short-circuit
> ("lazy") evaluation. If the first expression of an or operation is `true`, or
> the first expression of an and operation is `false`, the script does not
> evaluate the second expression [...]
>
> [migration guide] since an `and` condition is only `true` if all its arguments
> are `true`, when `close > open` is `false`, the `and` condition is definitely
> `false` regardless of the second argument [...] Consequently, the ta.rsi()
> call is not evaluated on every bar, which interferes with the internal history
> that the RSI function stores for its calculation and results in incorrect
> values.

This validates the comment in `Final_RSI_Plus.pine`:

```pine
// evaluated unconditionally every bar: v6 `and` short-circuits, and a
// ta.barssince() that only sometimes runs keeps a broken history
inRangeL = f_inRange(plFound[1])
```

For a vectorised Python port this is a non-issue (everything is computed for
every bar anyway) - but it means the Pine source you are porting is already
written in "compute everything every bar" style, so a literal translation is
correct and no conditional-evaluation guard is needed.

**(c) A dataset that starts on a different bar gives different numbers, and
TradingView says so.**

CITATION: https://www.tradingview.com/pine-script-docs/concepts/repainting/
QUOTE:
> As time goes by, these factors cause your chart's history to start at
> different points in time. This often has an impact on your scripts
> calculations, because changes in calculation results in early bars can ripple
> through all the other bars in the dataset. Using functions like
> ta.valuewhen(), ta.barssince() or ta.ema(), for example, will yield results
> that vary with early history.

and on daily-and-above timeframes the chart's history start is:
> **1440 minutes and higher**: aligns to the first available historical data
> point.

So a daily chart on TradingView starts at the symbol's first available bar from
TradingView's data vendor - which is NOT the same bar yfinance starts at for
most ASX names. This is the deepest reason why "bar for bar" agreement with a
TradingView chart is achievable for `ta.rsi` (self-correcting seed, see 2.1) and
NOT strictly achievable for `ta.ema(close, 200)` (see 2.2 and the measurements
in 4).

---

## 2. PITFALLS FOR A PYTHON PORT

Every place the naive pandas equivalent differs from Pine. Ordered by how much
damage each one does to the two scan rules.

### 2.1 `ta.rma` / `ta.rsi` / `ta.atr`: the SMA seed. THE big one.

- **Pine:** `rma` seeds with `ta.sma(src, length)` - the mean of the first
  `length` non-na source values - then runs `alpha = 1/length`.
- **Naive pandas:** `ewm(alpha=1/length, adjust=False)` seeds with the FIRST
  value. `ewm(adjust=True)` is different again (a normalised weighted mean that
  never converges to either).
- **Measured (this session, 1,500-bar synthetic daily series, RSI 14):** the
  naive `adjust=False` RSI is **5.67 RSI points** wrong 6 bars past the seed,
  **0.40** wrong 36 bars past, **0.013** wrong 86 bars past, **0.0004** wrong
  136 bars past, and equal to 6 decimals only ~190 bars past the seed.
  On a real 60-bar-old listing this is the difference between "RSI 68" and
  "RSI 74", i.e. between in and out of the overbought band.
- **Fix:** the explicit `ta_rma` in 1.2. Do not shortcut it.
- **Where it bites:** `rsiV` in the Top script (the `useRsi` score term - off by
  default, so Rule B is safe), `rsi` in RSI+ (Rule A's entire input - the
  divergence pivots are pivots OF THIS SERIES, so a wrong RSI moves the pivot
  bars themselves), and `atrV` (stop ladder only).

### 2.2 `ta.ema`: the seed is fine, the HISTORY START is not.

- **Pine:** `EMA = alpha*src + (1-alpha)*EMA[1]`, seeded with the first source
  value, running from TradingView's first available historical bar.
- **Naive pandas:** `ewm(span=length, adjust=False)` - **identical formula and
  identical seed**. This one is genuinely a one-liner.
- **The trap is not the formula, it is where your series begins.** Measured
  (same synthetic series, EMA 200, comparing a truncated-history EMA against the
  full-history EMA at the same final bar): with 1,249 prior bars the relative
  error is 2.2e-07; with 999 bars 5.1e-06; with 699 bars 6.0e-05; with **499
  bars 1.0e-03**, i.e. **0.1 percent**.
- **Why 0.1 percent matters for Rule B:** the score term is
  `close > maSlow` where `maSlow` is the 200-EMA. A 0.1 percent error in
  `maSlow` flips that term whenever the close sits within 0.1 percent of the
  200-EMA - which is exactly the situation the term exists to adjudicate. And
  `bullX = ta.crossover(maFast, maMid)` (EMA20 vs EMA50) can move the signal by
  a whole bar on a near-tie, which for a "signal on the latest closed bar" rule
  is the difference between a hit and a miss.
- **Fix:** feed at least **1,000 daily bars** (about 4 calendar years) of
  warm-up BEFORE the earliest bar you intend to evaluate, and more if you can.
  For a scan that only reads the last bar, request 5 years or the full history,
  whichever is longer. Accept that a name with only 300 bars of history cannot
  be reconciled with a TradingView 200-EMA to better than ~1 percent, and treat
  its Rule B `useSlow` term as unreliable; the CLAUDE.md `sma_proxy` precedent
  (publish the fact rather than silently proxy it) is the right pattern here.

### 2.3 Warm-up NaN: pandas `ewm` gives you a number where Pine gives you na.

- **Pine:** `ta.sma(close, 20)` is documented to return "na if fewer than 20
  bars are available". `ta.rma` cannot produce a value before its SMA seed
  exists. For `ta.ema` the warm-up length is **undocumented** (see 3.2).
- **Naive pandas:** `ewm(...).mean()` returns a value on bar 0 and every bar
  after. `rolling(n).mean()` without `min_periods=n` returns partial means.
- **Fix:** `rolling(n, min_periods=n)`; and for any EMA-family series, NaN out
  the first `length - 1` bars yourself if you want to mirror TradingView's
  display. For a scanner reading only the last bar of a multi-year series this
  is cosmetic - but it changes `ta.crossover` results near the start of a
  series, so do it if you ever backtest the rules.

### 2.4 Pivots: THREE separate off-by-ones, and Rule A depends on all three.

- **(i) The value is `src[right]`, not `src[0]`.** The candidate bar sits
  `rightbars` bars behind.
- **(ii) The value is returned on the CONFIRMATION bar**, `rightbars` bars after
  the pivot. In `Final_RSI_Plus.pine`, `lbR = 5`, so `plFound` / `phFound` are
  true 5 bars after the RSI pivot, and `bullDiv` / `bearDiv` are true on that
  same confirmation bar.
- **(iii) The LABEL is drawn 5 bars back.** `plotshape(..., offset = -lbR)`.
  So the visible "Bull" / "Bear" label sits on the pivot bar, 5 bars behind the
  bar where the condition actually became true.
- **Consequence for the scan rule, stated precisely:** on the latest closed
  daily bar `T`, `bullDiv[T] == true` means "a bullish divergence was CONFIRMED
  today, anchored on the RSI pivot low at bar `T-5`". There can never be a
  visible Bull/Bear label at bar `T` itself - the newest label you can ever see
  is at `T-5`. Rule A must therefore be written as "`bullDiv` or `bearDiv` is
  true on bar T", NOT as "a label is drawn on bar T" (which is impossible), and
  the spec should say which of the two it means in so many words.
- **(iv) Ties.** `rolling(w).min() == centre` is the tempting vectorisation and
  it is WRONG: on a flat window the centre equals the min, so you manufacture a
  pivot where Pine (strict) gives none. See 1.7 for the correct form and 3.1 for
  the strictness caveat.
- **(v) NaN inside the window.** Pine's comparisons against na are `false`, so a
  window containing an na cannot produce a pivot. NumPy agrees (`nan > x` is
  False), but only if you write the comparison in the same direction - the code
  in 1.7 tests `(win > c).all()`, which is correctly False when any element is
  NaN. Writing `not (win <= c).any()` would be True with NaNs present and would
  invent pivots during data gaps.

### 2.5 `ta.barssince` returns 0, and the RSI+ script deliberately shifts it.

The separation window in `Final_RSI_Plus.pine` is NOT `5 <= gap <= 60` bars
between pivots. It is:

```pine
f_inRange(cond) =>
    bars = ta.barssince(cond == true)
    rangeLower <= bars and bars <= rangeUpper     // 5 <= bars <= 60
inRangeL = f_inRange(plFound[1])                  // note the [1]
```

`plFound[1]` is true on the bar AFTER a confirmation bar. So with confirmation
bars `c_prev` and `c`, `bars = c - (c_prev + 1)`, and the constraint
`5 <= bars <= 60` becomes a pivot-to-pivot separation of
**6 <= (c - c_prev) <= 61 bars, inclusive at both ends.**

I verified this by writing a bar-by-bar Pine emulator (pivotlow + barssince +
valuewhen, strict pivots) and sweeping the gap: gaps of 6, 7, 8, 9 and 58, 59,
60, 61 all fire; gaps of 62 and 63 do not; and with `lbR = 5` the signal bar is
always `second_pivot_bar + 5`. Put that test in the Python suite - it is the
cheapest possible guard on the whole rule.

The `[1]` exists because without it `ta.barssince(plFound)` would be `0` on the
confirmation bar itself (1.9), `0 < 5`, and the divergence could never fire.
Do not "simplify" it away in the port.

### 2.6 `ta.valuewhen(cond, src, 1)` must count the current bar first.

Covered in 1.8. In the port, append the current bar to the occurrence list
BEFORE reading occurrence `n`. Getting this backwards compares the previous
pivot against the one before it, which still produces plausible-looking
divergences - the worst kind of bug.

Also note what `priceLL` actually compares:

```pine
priceLL = low[lbR] < ta.valuewhen(plFound, low[lbR], 1)
```

That is the **price low at the RSI-pivot bar**, at both ends. It is NOT a price
pivot, and it is NOT `ta.lowest`. The Python port must read `low` at
`pivot_bar`, not the lowest low between the pivots.

### 2.7 NaN never poisons a Pine boolean; in pandas it can.

- **Pine:** any comparison with an na operand is `false`; a bool is never na.
  So `bullDiv` on a bar with insufficient history is `false`, full stop.
- **Pandas:** `(a > b) & (c < d)` with NaNs gives `False` under numpy dtypes but
  `pd.NA` under nullable dtypes (`boolean`, `Float64`), and `pd.NA` is truthy in
  some contexts and raises in others. A `Series[boolean]` with `pd.NA` used to
  index will raise `ValueError: Cannot mask with non-boolean array containing NA`.
- **Fix:** keep everything in float64/bool numpy dtypes, and end every condition
  with `.fillna(False).astype(bool)`. Do it even where it looks redundant.

### 2.8 Nine-digit comparison rounding.

Covered in 1.13(a). Pine rounds float operands to 9 decimals before comparing;
Python does not. Where a rule turns on `>` against a computed level
(`close > maSlow`, `macdHist > 0`, `rsi >= rsiMa`, `maFast` vs `maMid`), the two
can disagree on a knife-edge bar. If exact parity matters, compare
`round(x, 9) > round(y, 9)`. For a scanner feeding a human eyeball this is
noise - but it is the reason a single ticker will occasionally differ from the
chart, and knowing that in advance saves an afternoon.

### 2.9 `ta.macd` argument order and the double EMA seeding.

The tuple is `[macd, signal, hist]` (1.5). The most common port bug is assuming
`[macd, hist, signal]`, which silently swaps the histogram and the signal -
and since `Final_Top_Script`'s Rule B reads `macdHist > 0`, that would read the
SIGNAL line's sign instead and change the score on a large fraction of bars.

Second: `signal` is an EMA of the MACD line, so the EMA history-start
sensitivity of 2.2 compounds - `hist` inherits the seeding error of the 12, the
26 AND the 9. In practice the 26 dominates and ~300 bars of warm-up makes `hist`
agree to well under a tick, but do not evaluate `macdHist` on a name with under
~150 bars of history and call it parity.

### 2.10 `ta.atr` true range on bar 0.

`ta.atr` uses `ta.tr(true)`: on the first bar, where `close[1]` is na, TR is
`high - low`, not na. `pd.concat([...]).max(axis=1)` gives `high - low` anyway
because `.max()` skips NaN - so the naive version is accidentally right. But
`np.maximum.reduce` is NOT (it propagates NaN), and `ta.tr` / `ta.tr(false)`
returns na on bar 0. Set bar 0 explicitly, as in 1.6, so the intent is in the
code.

### 2.11 Division by zero in the RSI is UNDOCUMENTED. Guard it.

The reference does not define float division by zero, and none of the manual
pages found in this sweep address it. `pine_rsi` computes
`rs = ta.rma(u, y) / ta.rma(d, y)`: on a perfectly flat window both are 0.
- In pandas, `0.0 / 0.0` on numpy floats is `nan` (with a RuntimeWarning), and
  `x / 0.0` with `x > 0` is `inf`, giving `100 - 100/(1+inf) = 100`.
- Decide and document: a halted / limit-locked name (all closes identical) has
  an UNDEFINED RSI, and publishing it as 100 ("maximally overbought") is exactly
  the bug this repo already fixed once in its own `rsi()` - see the TOP100 #71
  write-up in CLAUDE.md, which mandates NaN for the halted case and 100 only
  for "gains, no losses". Use the same convention here so the scanner and the
  Pine template disagree in a known, documented direction rather than silently.

### 2.12 Inclusive rolling windows (minor, but it is on the task list).

`ta.highest(src, n)` / `ta.lowest(src, n)` include the current bar; pandas
`rolling(n)` is right-aligned and also includes the current row, so they agree.
The pitfall is the opposite of the usual one: do NOT add a `.shift(1)`
"to avoid lookahead". These functions genuinely look at the current bar, and
`Final_Top_Script` relies on it (`revHH = ta.highest(high, revLook)` is meant to
include today). Only add a shift where the Pine source has one - and the Pine
source here has none for `highest`/`lowest`.

### 2.13 Index alignment and the "latest closed bar".

Pine runs on closed bars for historical data, and on the forming bar in
realtime. If the scanner pulls yfinance intraday-updated daily bars, the last
row is a FORMING bar and every one of these conditions can flip before the
close - `ta.crossover` especially. Drop the last row unless the exchange has
closed. TradingView's own repainting page is explicit that realtime and
historical evaluation differ; this is the Python-side equivalent.

### 2.14 What the scripts do NOT compute, so do not port it.

`request.security(..., "12M", open, lookahead = barmerge.lookahead_on)` (yearly
opens), the pivot S/R arrays, the ATR trade box, the reversal box, the KEY table
and every `label.new` / `box.new` / `line.new` are all **drawing only**. None of
them feeds `bullSig`, `bearSig`, `bullDiv` or `bearDiv`. The scanner needs, in
total: EMA20, EMA50, EMA200 on `close`; `ta.macd(close, 12, 26, 9)` histogram;
`ta.rsi(close, 14)`; and the RSI pivot / divergence block. Everything else in
624 lines of `Final_Top_Script.pine` is chart furniture.

---

## 3. UNVERIFIED - the two places the official documentation is genuinely silent

Flagged rather than guessed. A spec that states these as facts is overclaiming.

### 3.1 Pivot tie-breaking (strict `>` vs non-strict `>=`)

The v6 reference entries for `ta.pivothigh` / `ta.pivotlow` (quoted in full at
1.7) say nothing about equal values. Nothing in the 60-odd manual pages listed
in section 0 addresses it either - I grepped all of them for "pivot" and the
eight hits are all usage examples.

Best available evidence, clearly labelled as secondary:
- A TA-Lib feature proposal that measured the question against two independent
  implementations (ta4j and trading-signals) concludes **strict on both sides**,
  and notes the documentation conflict in TradingView's own material:
  "the Zig Zag page says `>` left / `>=` right, the Pine ta.pivothigh reference
  says strict both". Source: https://github.com/TA-Lib/ta-lib/issues/371
  (The second half of that sentence is that proposal's characterisation, not
  something I could confirm - the reference text quoted at 1.7 makes no such
  statement.)
- Community reimplementations converge on strict both sides.

**Recommendation:** implement **strict on both sides** (a tie kills the pivot),
and put the choice behind one named constant so it can be flipped in one place
if a live comparison against a chart ever disagrees.

**How much this actually matters here: very little, and it is worth saying so
in the spec.** Rule A's pivots are computed on `ta.rsi(close, 14)`, a float with
~15 significant digits; exact ties in a 5-bar neighbourhood essentially never
occur except on a halted series (where the RSI is undefined anyway, 2.11). The
pivots that DO tie in practice are the price pivots
(`ta.pivothigh(high, pivLen, pivLen)`) in `Final_Top_Script` - equal highs are
common on thin ASX names - and those feed only the S/R level display, which is
outside both scan rules. So the ambiguity is real, documented here, and
non-blocking.

### 3.2 The warm-up window of `ta.ema` (and whether it is na-suppressed)

Documented: the recursion and its seed (1.3). NOT documented anywhere in the
reference or the manual: whether the BUILT-IN suppresses output as na for the
first `length - 1` bars while the recursion runs underneath, or begins the
recursion later.

Secondary evidence that it does return na during a warm-up: the published
TradingView library `lib_no-delay` exists specifically to provide
"modifications to standard functions that return na before reaching the bar of
their length parameter" (https://www.tradingview.com/script/GzXtLRHR-lib-no-delay).
That establishes the na window; it does not establish what the first non-na
value equals.

**Why it does not block the port:** both candidate conventions converge
geometrically to the same series, and the measurements in 4 show the
convergence. With the recommended 1,000+ bars of warm-up (2.2) the question is
unanswerable from the data because both answers agree to 1e-7. Only a
short-history listing could distinguish them - and on such a name the 200-EMA
is untrustworthy for other reasons anyway.

**If someone with a TradingView account wants to settle it in 60 seconds:**
paste `plot(ta.ema(close, 10))` and `plot(pine_ema(close, 10))` (the doc's own
example function) on a chart, and read the Data Window on bars 0..10. If the
built-in is na until bar 9 and then equals `pine_ema`, the recursion runs from
bar 0 and is merely hidden. Record the answer in the spec.

---

## 4. Measurements taken during this verification

Run in this session (numpy 2.x / pandas 2.x, synthetic daily series, seeded RNG)
to put numbers on the two seeding pitfalls rather than asserting them.

**RSI(14), SMA-seed (Pine-correct) vs `ewm(alpha=1/14, adjust=False)` (naive):**

| bars past the seed bar | absolute RSI error (points) |
|---|---|
| 6   | 5.670181 |
| 36  | 0.399512 |
| 86  | 0.013462 |
| 136 | 0.000362 |
| 186 | 0.000006 |
| 286 | 0.000000 |

**EMA(200), history truncated vs full history, error at the same final bar:**

| prior bars available | relative error |
|---|---|
| 1499 | 0.0 (reference) |
| 1249 | 2.2e-07 |
| 999  | 5.1e-06 |
| 699  | 6.0e-05 |
| 499  | 1.0e-03 |

**Divergence gap window (bar-by-bar Pine emulator, `lbL=lbR=5`,
`rangeLower=5`, `rangeUpper=60`):** pivot-to-pivot separations of 6 through 61
bars fire; 62 and above do not; 5 and below cannot form two pivots. The signal
bar is always `second_pivot_bar + 5`.

---

## 5. Corrections to claims in the task brief

1. **"Try sections: language/built-ins, concepts, visuals, writing/limitations"**
   - partly wrong. `language/built-ins.md` and `writing/limitations.md` exist.
   There is **no `concepts/plots.md`** - plots live at `visuals/plots.md`, and
   the plot-count rule is split across `visuals/plots.md` (const vs input vs
   series colour) and `writing/limitations.md` (the full charging table). The
   complete page list is in section 0.

2. **"https://raw.githubusercontent.com/TradersPost/pine-mcp/main/data/docs/..."**
   - that repo exists and its README loads, but **every `data/docs/...` path
   tried returned 404**: `data/docs/index.json`, `data/docs/functions.json`,
   `data/reference.json`, `data/v6/functions.json`,
   `data/docs/reference/functions.json`. It serves its content through an MCP
   server, not as static files at those paths. Nothing in this document comes
   from it. Use the folknor mirror.

3. **"directory listing: https://github.com/folknor/pine-tools/tree/..."**
   - github.com HTML is **403 from this sandbox**, and so is api.github.com
   ("GitHub access to this repository is not enabled for this session").
   `raw.githubusercontent.com` works, and so does an unauthenticated
   `git clone --depth 1 --filter=blob:none`, which is how the directory listing
   in section 0 was actually obtained. Recipe in section 0.

4. **The mirror of the REFERENCE manual is not under `pine-manual/`.**
   The brief points only at `pine-manual/v6/...`, which is the USER MANUAL and
   which does **not** contain per-function definitions. Every `ta.*` definition
   quoted here comes from `pine-data/v6/functions.json` in the same repo -
   a Puppeteer scrape of `pine-script-reference/v6/` dated 2026-09-07. Without
   that file none of the `ta.rsi` / `ta.rma` / `ta.macd` semantics could have
   been verified from the mirrors named in the brief.

5. **Rule B's score cannot reach 4 with the shipped defaults, and the label text
   is not what the brief writes.** `useRsi` defaults to **false**
   (`Final_Top_Script.pine`: `useRsi = input.bool(false, "+1 when RSI agrees
   (> 50 / < 50)")`), so with defaults `bullScore` / `bearScore` are in
   **{1, 2, 3}**, and "|score| >= 2" selects 2 or 3. `minScore` defaults to 1,
   so every cross is labelled. Also the label strings are
   `"Bullish\n+" + str.tostring(bullScore)` and
   `"-" + str.tostring(bearScore) + "\nBearish"` - a NEWLINE, not a space. The
   brief's "Bullish +2" / "-2 Bearish" is how it reads on the chart, not the
   string. The blue/red arrows (`plotshape`) carry no text at all.

6. **"as of the latest closed daily bar ... has printed a Bull or Bear label"
   is not satisfiable as written for Rule A.** The label is plotted with
   `offset = -lbR` (5), so the newest label that can ever exist sits 5 bars
   behind the bar on which `bullDiv` / `bearDiv` became true. Rule A must mean
   "`bullDiv` or `bearDiv` is true ON the latest closed bar" (label lands at
   T-5). Rule B has no such offset - `bullSig` / `bearSig` and their arrows are
   on the cross bar itself. The two rules therefore have **different lags**, and
   the spec has to say so or the two halves of the scan will not mean the same
   thing.


---

# PART 4B - A WORKED EXAMPLE OF THE DIVERGENCE TIMING

Everything in Part 7.1 restated as arithmetic you can check by hand. If your
implementation reproduces this table exactly, the hardest part is correct.

The example uses a **hand-built RSI series** rather than one derived from price, so that
the pivot arithmetic is inspectable without also having to verify Wilder smoothing. Price
lows are supplied alongside it. In a real run the RSI would come from the close series; the
timing logic is identical either way.

Parameters: `L = 5`, `R = 5`, `RANGE_MIN = 5`, `RANGE_MAX = 60`. The pivot test here is
**strict on both sides** (a tie kills the pivot), which keeps a flat series from producing a
pivot on every bar. Note that whether Pine itself is strict is **undocumented and
unverified** - see 7.5, where the disagreement is measured at 0.8% of divergences. The
example below contains no ties, so it reads identically either way.

## The setup

Two RSI troughs. The first is deeper (27 at bar 8), the second shallower (30 at bar 26):
RSI made a **higher low**. Meanwhile price made a **lower low** (100.00 at bar 8, 95.00 at
bar 26). That is a textbook regular bullish divergence.

## What the code computes (actual output, verified)

```
RSI pivot lows -> (pivot bar, confirmation bar, rsi at pivot, low at pivot)
   pivot bar   8   confirmed on bar  13   rsi[8]= 27.0   low[8]= 100.00
   pivot bar  26   confirmed on bar  31   rsi[26]= 30.0   low[26]=  95.00

Divergence test on each confirmation bar after the first:
   bar 13: first pivot, no previous pivot to compare against -> no signal
   bar 31:
      rsiHL   : rsi[26]=30.0 > rsi[8]=27.0  -> True
      priceLL : low[26]=95.00 < low[8]=100.00  -> True
      inRange : barssince(plFound[1]) = 31 - (13 + 1) = 17, need 5..60 -> True
      => bullDiv on bar 31: True   (label DRAWN at bar 26)

Bar table (the two pivots and the confirmation bars are marked):
 bar    rsi      low  note                                    
   0   52.0   120.00                                          
   1   48.0   116.00                                          
   2   44.0   112.00                                          
   3   40.0   108.00                                          
   4   36.0   104.00                                          
   5   33.0   102.00                                          
   6   31.0   101.00                                          
   7   29.0   100.50                                          
   8   27.0   100.00  PIVOT LOW of RSI                        
   9   30.0   102.00                                          
  10   34.0   105.00                                          
  11   39.0   109.00                                          
  12   44.0   113.00                                          
  13   48.0   117.00  confirms pivot at bar 8                 
  14   52.0   121.00                                          
  15   55.0   124.00                                          
  16   57.0   126.00                                          
  17   54.0   123.00                                          
  18   50.0   119.00                                          
  19   46.0   115.00                                          
  20   42.0   111.00                                          
  21   39.0   108.00                                          
  22   36.0   105.00                                          
  23   34.0   102.00                                          
  24   32.0    99.00                                          
  25   31.0    97.00                                          
  26   30.0    95.00  PIVOT LOW of RSI                        
  27   33.0    98.00                                          
  28   37.0   102.00                                          
  29   42.0   107.00                                          
  30   47.0   112.00                                          
  31   51.0   116.00  confirms pivot at bar 26   <== bullDiv TRUE here
  32   54.0   119.00                                          
  33   56.0   121.00                                          
  34   58.0   123.00                                          
  35   57.0   122.00                                          
  36   55.0   120.00                                          
  37   52.0   117.00                                          
  38   49.0   114.00                                          
  39   47.0   112.00                                          
```

## The four things to take from this

1. **The pivot is at bar 26. The signal exists at bar 31.** Five bars of lag, always.
2. **The label is drawn at bar 26** because the Pine plot carries `offset = -5`. When the
   owner looks at his chart he sees the marker at bar 26. Your scanner must report bar 31 as
   the detection date and bar 26 as the pivot date, and should output both.
3. **The comparison is against the PREVIOUS pivot**, bar 8, not against any other bar. In
   Pine this is `ta.valuewhen(plFound, rsi[lbR], 1)` - occurrence index 1, meaning one
   before the current one.
4. **The range gate counts confirmation bars, minus one**: `31 - (13 + 1) = 17`. Not
   `31 - 13 = 18`, and not `26 - 8 = 18`. See Part 7.3 for why the `[1]` is there.

## The same example, expressed as the screener would see it

Suppose bar 31 is the latest closed daily bar, dated 2026-09-19, and the run happens after
the close on 2026-09-22 (bar 34).

| Field | Value |
|---|---|
| `rule_a.fired` | `true` |
| `rule_a.dir` | `bull` |
| `rule_a.bars_ago` | `3` (bar 34 minus bar 31) |
| `rule_a.confirmed_date` | 2026-09-19 |
| `rule_a.pivot_date` | 2026-09-12 (bar 26) |
| `rule_a.pivot_price_low` | 95.00 |
| `rule_a.prev_pivot_price_low` | 100.00 |
| `rule_a.pivot_rsi` | 30.0 |
| `rule_a.prev_pivot_rsi` | 27.0 |
| `rule_a.pivot_gap_bars` | 17 |

With `div_fresh_bars = 3`, `bars_ago = 3` is inside the window, so this symbol is a hit.
With `div_fresh_bars = 1` it is not: it would have been a hit on the run of 2026-09-19.


---

# PART 5 - THE SCANNER SPECIFICATION

This is the part you are being asked to build. Everything before it is background;
everything after it is how to get the details right.

## 5.1 Inputs

| Input | Value |
|---|---|
| Timeframe | Daily bars only. One bar per trading day (per UTC day for crypto). |
| History required | 400 daily bars minimum per symbol; 750 preferred. The 200-EMA needs ~200 bars to settle and the divergence needs a pivot history. Below 250 bars, mark the row `short_history: true` and let it through with a warning rather than dropping it. |
| Bar to evaluate | The latest **CLOSED** daily bar. Never the forming bar. See 7.2. |
| Price source | Adjusted-for-splits, NOT adjusted-for-dividends, OHLCV. Consistency matters more than the choice: whatever TradingView shows is what the owner's eye will compare against. |
| Universes | ASX all listed, NASDAQ Global Select, crypto top-100. |

## 5.2 The two rules, stated exactly

### RULE A - RSI regular divergence

Let `rsi = RSI(close, 14)` (Wilder). Let `L = 5` (pivot left bars), `R = 5` (pivot right
bars), `RANGE_MIN = 5`, `RANGE_MAX = 60`.

A **bullish divergence is CONFIRMED on bar `i`** when all four hold:

1. `plFound(i)`: bar `i-R` is a pivot low of the `rsi` series, i.e. `rsi[i-R]` is less than
   or equal to every `rsi` value in `[i-R-L, i-R+R]` other than itself, per Pine's
   `ta.pivotlow(rsi, 5, 5)` returning non-NaN on bar `i`.
2. `priceLL`: `low[i-R] < low[p-R]`, where `p` is the **previous** bar on which `plFound`
   was true. Price made a **lower low**.
3. `rsiHL`: `rsi[i-R] > rsi[p-R]`. RSI made a **higher low**.
4. `inRange`: `RANGE_MIN <= barssince(plFound[1])(i) <= RANGE_MAX`.
   **Careful: this is NOT a 5-to-60-bar pivot gap.** Because the Pine reads the *previous*
   bar's `plFound`, the counted value is one less than the gap, so the admitted separation
   between consecutive pivot confirmations is **6 to 61 bars inclusive**. Reproduce the
   quirk exactly; see 7.3 for why, and pin it with a test at both bounds.

A **bearish divergence is CONFIRMED on bar `i`** when the mirror holds: `phFound` (pivot
high of RSI), `high[i-R] > high[p-R]` (higher high in price), `rsi[i-R] < rsi[p-R]` (lower
high in RSI), same range gate.

> On the chart these print as a small blue `Bull` label below the RSI line, or a small red
> `Bear` label above it, positioned at bar `i-R` via `offset = -5`.

**Rule A fires for a symbol** if `bull_div` or `bear_div` was true on any bar in
`[last_closed - div_fresh_bars + 1, last_closed]`. Default `div_fresh_bars = 3`.

### RULE B - scored moving-average cross, magnitude >= 2

Let `fast = EMA(close, 20)`, `mid = EMA(close, 50)`, `slow = EMA(close, 200)`, and
`(macd, signal, hist) = MACD(close, 12, 26, 9)`.

```
bull_cross(i) = fast[i] > mid[i]  AND  fast[i-1] <= mid[i-1]
bear_cross(i) = fast[i] < mid[i]  AND  fast[i-1] >= mid[i-1]

bull_score(i) = 1
              + (1 if use_macd and hist[i] > 0        else 0)
              + (1 if use_slow and close[i] > slow[i] else 0)
              + (1 if use_rsi  and rsi[i]   > 50      else 0)

bear_score(i) = 1
              + (1 if use_macd and hist[i] < 0        else 0)
              + (1 if use_slow and close[i] < slow[i] else 0)
              + (1 if use_rsi  and rsi[i]   < 50      else 0)
```

Defaults: `use_macd = True`, `use_slow = True`, `use_rsi = False`. **Therefore the maximum
reachable score is 3 and the reachable set is {1, 2, 3}.** This matters for the screen:
"2 or more" selects scores 2 and 3, which is two-thirds of the reachable range, not a rare
tail. Expect Rule B to produce substantially more hits than Rule A.

**Rule B fires for a symbol** if a cross occurred on any bar in
`[last_closed - signal_fresh_bars + 1, last_closed]` **and** the score on that cross bar
was `>= min_score`. Default `signal_fresh_bars = 3`, `min_score = 2`.

Three properties of this scoring that a reimplementation must preserve:

- **All comparisons are strict.** `macd_hist > 0`, not `>= 0`; `close > slow`, not `>=`.
  A histogram of exactly zero scores neither side. Unreachable in floating point in
  practice, but do not "helpfully" relax it.
- **All terms are evaluated on the CROSS BAR**, not on any earlier or later bar.
- **A symbol with fewer than 200 bars of history can never score 3.** The 200-EMA is
  undefined, so `close > slow` is false, so the trend term contributes 0. Newly listed
  names and new coins are therefore capped at score 2 by construction. This is not a bug
  to fix; it is a fact to surface. Set the `short_history` flag on those rows so a reviewer
  knows the score was capped rather than earned.

Restated plainly: **Rule B is "a 20/50 cross on which at least one of the two confirmation
terms agrees".** See the measurement in 5.10 for how little that excludes.

**If you ever parse the chart labels rather than recompute them**, note the exact strings
are **two lines**: the bull label is `"Bullish\n+" + score` and the bear label is
`"-" + score + "\nBearish"`. The score is stored as a **positive** integer in both
directions and the minus sign is prepended as text, so no negative number exists anywhere
in the Pine. The arrows carry no text at all. "Bullish +2" is how the label reads on
screen, not the string the script emits.

## 5.3 The freshness windows, and why they are not optional

Both rules are **events**, not states. A cross happens on exactly one bar; a divergence is
confirmed on exactly one bar. A screener that asks "is the condition true today" would
return almost nothing, because "today" is one bar out of thousands.

So the screen asks "did the event happen recently", and *recently* needs a number.

| Setting | Default | Meaning | Effect of raising it |
|---|---|---|---|
| `div_fresh_bars` | 3 | Divergence confirmed within the last 3 closed daily bars | More hits, staler setups. At 1 you see only divergences confirmed on the latest bar - the purest "new today" screen, and the smallest list. |
| `signal_fresh_bars` | 3 | Cross printed within the last 3 closed daily bars | Same trade-off. |

Recommendation: **start with both at 1** for a week and look at the volume. If the daily
list is under about 15 names per market, widen to 3. Shipping a config where these are
editable without a code change is more valuable than picking the right default now.

Note for ASX and NASDAQ, 3 bars is 3 trading sessions (up to 5 calendar days over a
weekend). For crypto, 3 bars is 3 calendar days. That asymmetry is correct and intended:
the unit is bars, because the indicator's unit is bars.

## 5.3B THE TWO RULES HAVE DIFFERENT LAGS - and the output must say so

This is subtle, easy to miss, and it makes the two halves of the screen mean different
things unless you handle it.

- **Rule B has no detection lag.** A cross on bar `i` is knowable at the close of bar `i`.
  The arrow is drawn on bar `i`.
- **Rule A has a 5-bar detection lag.** A divergence confirmed on bar `i` describes a pivot
  at bar `i-5`. The label is drawn at bar `i-5`.

So if both rules report `bars_ago = 1`, the underlying market events are **six bars apart in
age**: Rule B's cross happened yesterday, Rule A's pivot happened six sessions ago.

Two consequences:

1. **Report both numbers.** Every row carries `bars_ago` (bars since the signal became
   knowable, which is what a screener should filter on) and, for Rule A,
   `pivot_bars_ago = bars_ago + 5` (bars since the market event the signal describes). The
   owner opening the chart will see the label at the pivot bar and needs to know why the
   scanner named a different date.
2. **Consider asymmetric freshness windows.** If what you want is "the underlying event is
   recent", then `div_fresh_bars` and `signal_fresh_bars` should not be equal - Rule A's
   window is already 5 bars behind. If what you want is "the signal is newly knowable"
   (which is the more defensible screening criterion, because it is what you could have
   acted on), equal windows are correct. *This document recommends equal windows and
   explicit reporting of both numbers, so the asymmetry is visible rather than compensated
   for silently.*

There is no way to remove Rule A's lag. It is inherent to pivot detection: you cannot know
a bar was a local low until you have seen the bars after it. Any implementation that
reports a divergence sooner than 5 bars after the pivot has a look-ahead bug.

## 5.4 The three modes

```
passes_A(sym) = rule_A_fired(sym)
passes_B(sym) = rule_A_fired(sym) or rule_B_fired(sym)
passes_C(sym) = rule_A_fired(sym) and rule_B_fired(sym) and directions_agree(sym)
```

`directions_agree` means the divergence direction and the cross direction are both bullish
or both bearish. A bullish divergence plus a bearish cross is a *conflict*: do not drop it
in modes A or B, but flag it, because it is genuinely interesting (momentum turning up
while the trend structure turns down) and a human should see the flag rather than have the
row silently ranked as though it were clean.

## 5.5 Direction and bias resolution

Each hit row carries:

- `rule_a_dir` in {`bull`, `bear`, `both`, `none`} - `both` is possible if one bullish and
  one bearish divergence confirmed inside the same freshness window.
- `rule_b_dir` in {`bull`, `bear`, `both`, `none`}.
- `bias` = `long` if all fired directions are bullish; `short` if all bearish;
  `conflict` if both appear; `none` if nothing fired (should not occur in a hit row).

Do **not** collapse `conflict` into a single direction by a priority rule. Surfacing the
disagreement is the whole point of a human-review shortlist.

## 5.6 Quality gates - applied BEFORE the rules, to every symbol

These exist so the shortlist is made of things the owner can actually trade, and so one
bad data frame cannot fabricate a signal. Every one of them should be a named config
constant, not a literal in the code.

| Gate | Default | Why |
|---|---|---|
| `MIN_PRICE` | ASX A$0.02, NASDAQ US$1.00, crypto none | Sub-cent ASX names move one tick and print a 50% candle; every indicator becomes noise. |
| `MIN_DOLLAR_ADV` | ASX A$250,000, NASDAQ US$1,000,000, crypto US$5,000,000 | 20-day average of `close * volume`. A signal on a name that trades $3,000 a day is not actionable. |
| `MAX_DATA_AGE_DAYS` | 3 (measured in the MARKET's own calendar, not the runner's clock) | A stale frame's last bar is not "today". Computing a fresh signal off a two-week-old bar is the single most dangerous silent failure in a screener. |
| `MIN_BARS` | 250 (warn), 60 (hard reject) | Below 60 bars nothing here is meaningful. Between 60 and 250 let it through flagged. |
| Exclude non-operating listings | ASX LICs, ETFs, unit trusts; NASDAQ preferred lines, warrants, rights, notes | The owner's existing scanner already solves this: see `scan.py::_product_tag` and `config.PRODUCT_NAME_PATTERNS`. Reuse it, do not rewrite it. A fund's RSI divergence is not a stock idea. |
| Volume sanity | reject a frame where the last 5 bars all have `volume == 0` | Suspended / delisted names keep printing a flat last price. Flat series produce no pivots but can still produce a cross off stale EMAs. |

## 5.7 Ranking

The owner reviews by eye, top down. Rank so the first ten rows are the ten most worth
opening.

Sort key, descending priority:

1. **Confluence**: Rule A and Rule B both fired and agree (mode C members first).
2. **Rule A present** (divergence is the higher-information signal of the two).
3. **Recency**: smaller `bars_ago` first.
4. **Score**: higher `|score|` first.
5. **Liquidity**: higher dollar ADV first.
6. Symbol, alphabetically, as the final tie-break so the order is deterministic.

Determinism matters: a re-run on the same data must produce the same order, or diffing
yesterday's list against today's becomes impossible.

## 5.8 Output schema

Publish one JSON file per market, atomically, matching the existing repo convention
(`public/data/<market>_<lens>.json`). Suggested: `public/data/<market>_rsidiv.json`.

```json
{
  "generated_at": "2026-09-22T09:31:44Z",
  "market": "asx",
  "timeframe": "1d",
  "last_closed_bar": "2026-09-22",
  "mode": "B",
  "params": {
    "rsi_len": 14, "pivot_left": 5, "pivot_right": 5,
    "range_min": 5, "range_max": 60,
    "fast": 20, "mid": 50, "slow": 200, "ma_type": "EMA",
    "macd": [12, 26, 9],
    "use_macd": true, "use_slow": true, "use_rsi": false,
    "min_score": 2, "div_fresh_bars": 3, "signal_fresh_bars": 3,
    "min_price": 0.02, "min_dollar_adv": 250000, "max_data_age_days": 3
  },
  "summary": {
    "universe": 2212, "scanned": 2187, "skipped_gates": 1146,
    "hits": 41, "hits_rule_a": 12, "hits_rule_b": 33, "hits_both_aligned": 4,
    "errors": 3, "data_from_cache": 0.04, "elapsed_s": 412
  },
  "results": [
    {
      "symbol": "CBA.AX", "name": "Commonwealth Bank of Australia",
      "sector": "Financials", "is_product": false,
      "close": 112.34, "dollar_adv_20": 184000000,
      "bias": "long", "confluence": true, "rank": 1,

      "rule_a": {
        "fired": true, "dir": "bull",
        "bars_ago": 1, "pivot_bars_ago": 6,
        "confirmed_date": "2026-09-19", "pivot_date": "2026-09-12",
        "pivot_price_low": 104.10, "prev_pivot_price_low": 106.80,
        "pivot_rsi": 34.2, "prev_pivot_rsi": 31.7,
        "pivot_gap_bars": 18
      },
      "rule_b": {
        "fired": true, "dir": "bull", "bars_ago": 2,
        "cross_date": "2026-09-18", "score": 3,
        "terms": {"cross": 1, "macd_agrees": 1, "beyond_slow": 1, "rsi_agrees": null}
      },

      "context": {
        "rsi": 46.8, "rsi_ma": 42.4,
        "rsi_state": "neutral",
        "ema20": 110.2, "ema50": 109.4, "ema200": 103.8,
        "regime": "up",
        "macd_hist": 0.41,
        "atr14": 2.18, "atr_pct": 1.94,
        "dist_to_ema200_pct": 8.2,
        "short_history": false, "data_age_days": 0
      },
      "flags": []
    }
  ],
  "errors": [
    {"symbol": "XYZ.AX", "stage": "indicators", "error": "all-NaN close column"}
  ]
}
```

Notes on the schema:

- `rule_a.bars_ago` is bars since the signal became **knowable**; `pivot_bars_ago` is bars
  since the **market event** it describes, always 5 more. Rule B has only `bars_ago`
  because its lag is zero. See 5.3B.
- `rule_a`/`rule_b` carry the **evidence**, not just the verdict. The owner is about to
  open a chart; giving him the pivot dates and prices means he can confirm in two seconds
  that the scanner and the chart agree. A bare boolean makes every disagreement a
  debugging session.
- `terms` spells out the score arithmetic. `null` for a term that is switched off, `0` for
  a term that was evaluated and failed. Those are different facts and collapsing them is
  how a scoring bug hides.
- `flags` is a list of strings for anything a reviewer should know but that did not
  disqualify the row: `short_history`, `stale_price`, `conflict`, `thin_liquidity`,
  `is_product`, `wide_atr`.
- `errors` is a first-class part of the payload, not a log line. A symbol that throws every
  night must be visible, or it is indistinguishable from a symbol that never sets up.

## 5.9 Pseudocode for the whole run

```
for market in (asx, nasdaq, crypto):
    universe = load_universe(market)                  # ~2212 rows for ASX
    frames   = download_daily(universe, period="3y")  # batched, retried
    frames   = merge_with_cache(market, frames)       # fill Yahoo's daily dropouts
    rows, errors = [], []

    for sym, df in frames.items():
        try:
            if not passes_gates(df, market):          # 5.6 - cheap, do it first
                continue
            ind = compute_indicators(df)              # RSI, EMAs, MACD, ATR
            a   = rule_a(df, ind)                     # divergence, confirmation-bar series
            b   = rule_b(df, ind)                     # crosses + scores
            hit = evaluate(a, b, mode, cfg)           # freshness windows, direction
            if hit.passes:
                rows.append(build_row(sym, df, ind, a, b, hit))
        except Exception as exc:
            errors.append({symbol: sym, stage: ..., error: str(exc)})

    rows = rank(rows)                                 # 5.7
    write_json(f"public/data/{market}_rsidiv.json", payload(rows, errors))
```

## 5.10 Expected hit volume - MEASURED, not guessed

These are measured on **3,000 synthetic geometric random walks x 650 usable bars =
1,950,000 symbol-days**, with daily volatility drawn uniformly from 1.2% to 4.5%. Real
markets trend and mean-revert where a random walk does not, so the real rates will differ -
but the order of magnitude is the right sanity check, and the *relative* figures below are
the important part.

| Event | Per symbol-day | Expected per day in a 2,200-name universe |
|---|---|---|
| Any 20/50 EMA cross | 1.956% | 43 |
| ... of which score 1 (excluded by the screen) | 0.049% | 1.1 |
| ... of which score 2 | 0.717% | 15.8 |
| ... of which score 3 | 1.190% | 26.2 |
| Bullish RSI divergence confirmed | 0.760% | 16.7 |
| Bearish RSI divergence confirmed | 0.868% | 19.1 |
| **RULE A** (divergence, either direction) | **1.628%** | **~36** |
| **RULE B** (cross with score >= 2) | **1.907%** | **~42** |

With a freshness window of `N` bars, multiply by roughly `N` (an event rarely repeats on
the same symbol within three bars). So:

| Screen | ASX (~2,200) | NASDAQ (~1,430) | Crypto (~100) |
|---|---|---|---|
| Rule A, window 1 | ~36 | ~23 | ~2 |
| Rule A, window 3 | ~105 | ~68 | ~5 |
| Rule B, window 1 | ~42 | ~27 | ~2 |
| Rule B, window 3 | ~125 | ~81 | ~6 |
| Mode B (A or B), window 3 | ~200 (after overlap) | ~130 | ~9 |

**These numbers are before the liquidity gates.** On the ASX the gates typically remove
half to two-thirds of the universe, so the realistic Mode B list is perhaps 70-120 names at
window 3. That is still far too many to review by eye, which is the argument for starting
at window 1.

### THE IMPORTANT FINDING: "score >= 2" is almost a no-op

Look at the score mix among all crosses:

| Score | Share of crosses |
|---|---|
| 1 | **2%** |
| 2 | 37% |
| 3 | 61% |

**Requiring a score of 2 or more excludes only about 2% of crosses.** It feels like a
selective filter and is not one.

The reason is that the two scoring terms are **strongly correlated with the cross itself**.
A 20-EMA crossing above a 50-EMA happens because price has been rising; price rising is
also what makes the MACD histogram positive and pushes price above the 200-EMA. The three
conditions are three measurements of the same thing, so they almost always agree.

Consequences you should act on:

1. **Do not expect Rule B to be the strict half of the screen.** It is close to "any 20/50
   cross", which on a 2,200-name universe is about 43 names a day.
2. **If you want selectivity from Rule B, use score 3**, which still admits 61% of crosses
   but at least requires full agreement. Or raise `min_score` to 3 and accept that the
   filter is doing less than its name suggests.
3. **The honest way to make Rule B selective is to add an UNCORRELATED term**, not to raise
   the threshold on correlated ones. Candidates: a volume expansion on the cross bar, a
   minimum separation between the 20 and 50 after the cross (filtering flat-market
   whipsaws), or a requirement that the 50 itself is sloping in the cross direction. None
   of these are in the template today; all three are cheap to add and would change the
   screen's character far more than `min_score` does.
4. **Rule A is the genuinely selective rule.** Its conditions (a pivot, a lower low, a
   higher low, a bar-gap window) are not merely restatements of each other, so it rejects
   most of what it sees.

This is the single most useful measurement in this document. It was not obvious before
running it, and it means the owner's instinct - that "2 or more" would be a meaningful
filter - does not hold under the template's current scoring terms.

## 5.11 Cadence and scheduling

| Market | Run at | Why |
|---|---|---|
| ASX | 06:30 UTC | After the 16:00 Sydney close in both halves of the DST year. |
| NASDAQ | 21:30 UTC | After the 16:00 New York close in both halves. |
| Crypto | 00:30 UTC | Just after the UTC day boundary that defines the daily bar. |

Do not schedule a market-hours cron for a daily screener: a forming bar's RSI and EMA move
all session, so an intraday run produces a signal that may not exist at the close. If the
owner wants an intraday preview, compute it on the forming bar but label every such row
`provisional: true` and never let it into the same file as the closed-bar results.

**A DST warning inherited from this repository's own history:** every ASX cron in the repo
was originally written for AEST (UTC+10) and would have silently lost the first hour of
every session for four weeks each October when Sydney moves to AEDT (UTC+11). The fix used
here, and the one you should copy: let cron fire a **superset** of the needed times and let
an in-job gate decide using real market-local time. Never hard-code the offset you happen
to be in.


---

# PART 6 - REFERENCE IMPLEMENTATION: RUNNABLE, TESTED PYTHON

Written 2026-09-22 against `/home/user/googy-boys-scanner/tradingview/` at repo
head. ASCII only.

This part has one job: let another AI write a production scanner for the
ASX / NASDAQ / crypto universes that reproduces, bar for bar, what the owner
sees on his TradingView chart -- without access to TradingView. Everything
below was read out of the Pine source, re-implemented in pandas/numpy, and
then RUN. Where a number appears, it came out of an execution, not out of a
reading.

**How this part relates to the rest of the document.** PART 3 carries the Pine
source verbatim and is the authority on what the scripts say; PART 5 is the
authority on WHAT the scanner should do. This part is the authority on HOW,
and only on how: a working implementation plus the measurements that come out
of running it. Sections 6.1 to 6.5 restate the template and the rules from the
implementer's side, deliberately overlapping PARTS 2-5 -- an implementer
should be able to build from this part alone and then check it against the
others. Where this part and PART 5 differ in a DEFAULT (the freshness windows;
see 6.5.1) or in a stated CONVENTION (the pivot tie rule; see 6.9 item 1),
the difference is called out at the point it occurs rather than smoothed over.

Deliverables, all in this directory:

| File | What |
|---|---|
| `vivek50_screen.py` | the reference implementation (1149 lines, no dependency beyond numpy + pandas) |
| `vivek50_selftest.py` | 28 tests + the demo basket |
| `selftest_output.txt` | the verbatim console output of the run reproduced in 6.7 |
| `sec_reference_impl.md` | this file |

Run: `python3 vivek50_selftest.py` (exit 0) or `python3 -m pytest -q vivek50_selftest.py`.
Verified on pandas 3.0.6 / numpy 2.4.6, Python 3.13.

---

## 6.1 What the template is, and what it is not

Three Pine Script v6 files, added 2026-09-09, that together reproduce the "5.0
Trading" chart look the owner uses as a visual reference:

| File | `indicator()` title | Pane | Lines |
|---|---|---|---|
| `Final_Top_Script.pine` | `Vivek 5.0 Top` | price, `overlay = true` | 624 |
| `Final_Bottom_MACD.pine` | `Vivek 5.0 MACD` | separate | 39 |
| `Final_RSI_Plus.pine` | `Vivek 5.0 RSI+` | separate | 92 |

Plus `README.md` (124 lines), which maps every element of the reference
screenshots to the input that produces it.

**It is a chart template and nothing else.** Verified by grep at head: no
Python, JS, workflow or test in the repository reads the `tradingview/`
directory. The only `tradingview` strings anywhere else in the tree are deep
links (`chart.js`) and embed widgets (`sectors.js`). The scripts do not encode
VIVEK, PhaseMap, Specs or TURTLE logic, and the Top script's 20/50/200 EMA
stack is the owner's charting preference -- it is unrelated to VIVEK's
200-SMA reaction levels, which are SMAs on Weekly / 3-Day / Daily.

Two consequences for the scanner being specified here:

1. There is no existing code to reuse. The maths below has to be written from
   scratch, which is why this document ships a tested implementation rather
   than a description.
2. There is no freeze or fence to respect. The new scanner is a fourth
   surface, like TURTLE: it reads price data, it publishes its own file, and
   nothing in `scanner/broker/` should ever import it.

The scripts were written without a Pine compiler available and checked by eye.
If TradingView reports a paste error, the fix is the named line -- do not
restructure.

---

## 6.2 `Final_RSI_Plus.pine` -- the source of RULE A

### 6.2.1 What it draws

RSI 14 on close, with:

- a smoothing MA of the RSI (`maLen = 14`, `maType = "SMA"`, EMA optional) and
  a blue/red fill between RSI and that MA -- blue while `rsi >= rsiMa`;
- band lines at 70 / 75 (overbought, "extreme") and 30 / 25 (oversold,
  "extreme"), each pair filled;
- a midline at 50;
- a long-run RSI average, `ta.sma(rsi, 50)`;
- background columns while RSI is at an extreme (`rsi >= 75` blue,
  `rsi <= 25` red), on by default;
- an optional grey column on `ta.cross(rsi, 50)`, off by default;
- **regular bull / bear divergence marks: a fat circle plus a `Bull` or
  `Bear` text label.**

The status line prints, in plot order: RSI, RSI MA, 70, 75, 30, 25, 50, bull
div, bear div, long average. The two divergence entries show the empty-set
glyph when there is no divergence -- that is TradingView rendering `na`, not
a character in the source.

### 6.2.2 The divergence block, verbatim

```pine
plFound = not na(ta.pivotlow(rsi, lbL, lbR))
phFound = not na(ta.pivothigh(rsi, lbL, lbR))

f_inRange(cond) =>
    bars = ta.barssince(cond == true)
    rangeLower <= bars and bars <= rangeUpper

inRangeL = f_inRange(plFound[1])
inRangeH = f_inRange(phFound[1])

rsiHL   = rsi[lbR] > ta.valuewhen(plFound, rsi[lbR], 1)
priceLL = low[lbR] < ta.valuewhen(plFound, low[lbR], 1)
bullDiv = showDiv and plFound and priceLL and rsiHL and inRangeL

rsiLH   = rsi[lbR] < ta.valuewhen(phFound, rsi[lbR], 1)
priceHH = high[lbR] > ta.valuewhen(phFound, high[lbR], 1)
bearDiv = showDiv and phFound and priceHH and rsiLH and inRangeH
```

with `lbL = 5`, `lbR = 5`, `rangeLower = 5`, `rangeUpper = 60`, `showDiv = true`.

The comment above `inRangeL` is load-bearing and is repeated here because it
explains why the two `f_inRange` calls sit outside the `and` chain:

> evaluated unconditionally every bar: v6 `and` short-circuits, and a
> `ta.barssince()` that only sometimes runs keeps a broken history

This is the TradingView built-in "Divergence Indicator" almost verbatim --
same identifiers (`plFound`, `rsiHL`, `priceLL`, `_inRange`), same structure.
Any quirk below is inherited from there, not invented here.

### 6.2.3 Five facts about this block that a port gets wrong

**(a) The pivots are on the RSI. The price leg is not a price pivot.**
`ta.pivotlow(rsi, 5, 5)` finds a local minimum of the OSCILLATOR. The price
comparison is then `low[lbR]` -- the raw low of the bar the RSI pivoted on --
against `low[lbR]` at the previous RSI pivot. Price need not have made a pivot
of its own, and usually has not made one on the same bar. Implementing this as
"find a price pivot and an RSI pivot and compare" produces a different, much
sparser signal.

**(b) The condition is TRUE ON THE CONFIRMATION BAR, five bars after the
pivot.** `ta.pivotlow(src, 5, 5)` returns `na` until five bars have printed
after the candidate. So on the bar where `bullDiv` becomes true, the pivot it
describes is `bar_index - 5`. The plot then draws the circle and the `Bull`
text with `offset = -lbR`, i.e. back at the pivot bar:

```pine
plotshape(bullDiv ? rsi[lbR] : na, "Bull Div label", style = shape.labelup,
          location = location.absolute, color = cUp, textcolor = color.white,
          text = "Bull", offset = -lbR, size = size.tiny, display = display.pane)
```

So "the RSI+ pane has printed a Bull label as of the latest closed bar" and
"there is a Bull label at the right edge of the chart" are two different
statements. A divergence that fires TODAY has its label sitting FIVE BARS
BACK. The reference implementation reports both numbers
(`rule_a_bars_ago = 0`, `rule_a_label_bars_ago = 5`) so a reviewer opening the
chart knows where to look.

The alert fires on the same bar as the boolean, not on the label's bar --
`alertcondition(bullDiv, ...)`.

**(c) The in-range filter is off by one, at both ends.** `f_inRange` is called
with `plFound[1]`, the PREVIOUS bar's value. On a bar `i` where `plFound` is
true:

```
ta.barssince(plFound[1]) at bar i  =  i - (p + 1)  =  (i - p) - 1
```

where `p` is the most recent earlier bar with `plFound` true. So the test
`5 <= bars <= 60` admits a gap `i - p` of **6 to 61 bars inclusive** between
consecutive pivot confirmations -- which, since both are offset by the same
`lbR`, is also the gap between the two pivot bars themselves.

Coding `5 <= gap <= 60` silently loses every divergence whose pivots are
exactly 61 bars apart and adds every one exactly 5 apart. Pinned by
`test_the_barssince_off_by_one_sets_a_6_to_61_bar_window`.

**(d) The first pivot of a symbol's history can never fire.** Before any
occurrence, `ta.barssince` returns `na` and `ta.valuewhen(..., 1)` returns
`na`; every comparison against `na` is false in a Pine boolean context. So a
symbol needs at least two RSI pivots of the same sign before RULE A can ever
be true. Reproduced exactly: `valuewhen` returns NaN and `barssince` returns
NaN, and the numpy comparisons resolve to False.

**(e) `showDiv` gates both.** It is `true` by default and the screen always
treats it as on; it is in the config for completeness.

### 6.2.4 The other thing this pane publishes

`alertcondition(ta.crossover(rsi, ob1))` and `ta.crossunder(rsi, os1)` fire on
RSI entering 70 / 30. These are NOT part of RULE A and are not screened on.
They are noted because the owner may later ask for "RSI entered overbought"
as a third rule; `rsi_zone` in the screen output already carries the
information (`neutral` / `overbought` / `extreme-overbought` / `oversold` /
`extreme-oversold`, cut at 70/75/30/25).

---

## 6.3 `Final_Bottom_MACD.pine` -- the supporting pane

Standard 12 / 26 / 9 on close, `[macdLine, sigLine, hist] = ta.macd(...)`,
with TradingView's four-shade histogram (strong/fading on each side of zero),
a dashed zero line, an optional column on a histogram zero-cross (off), and
two alert conditions on that zero-cross.

**Nothing in the screen reads this pane directly.** It matters for exactly one
reason: the Top script computes its own `ta.macd(close, 12, 26, 9)` with the
same parameters and reads `macdHist` for the "+1 when the MACD histogram
agrees" point of the score. The pane exists so the owner can SEE the input
that produced that +1. Keep the two in step -- if the Top script's
`macdFast/macdSlow/macdSig` inputs are ever changed, this pane no longer shows
the histogram the score used.

---

## 6.4 `Final_Top_Script.pine` -- the source of RULE B, and everything else

624 lines, `max_lines_count = 500, max_labels_count = 500, max_boxes_count = 500`.
Nine of its ten features are drawing; one is the signal. Both are documented
because "the scanner should reproduce the chart" is the owner's actual goal
and the next question after this scanner ships will be about one of the other
nine.

### 6.4.1 The scored cross -- the only part RULE B needs

```pine
maFast = f_ma(maSrc, fastLen)     // EMA 20 on close
maMid  = f_ma(maSrc, midLen)      // EMA 50
maSlow = f_ma(maSrc, slowLen)     // EMA 200
regime = maMid > maSlow

rsiV = ta.rsi(close, rsiLen)                                  // 14
[macdLine, macdSignal, macdHist] = ta.macd(close, macdFast, macdSlow, macdSig)

bullX = ta.crossover(maFast, maMid)
bearX = ta.crossunder(maFast, maMid)

bullScore = 1 + (useMacd and macdHist > 0 ? 1 : 0)
              + (useSlow and close > maSlow ? 1 : 0)
              + (useRsi  and rsiV > 50 ? 1 : 0)
bearScore = 1 + (useMacd and macdHist < 0 ? 1 : 0)
              + (useSlow and close < maSlow ? 1 : 0)
              + (useRsi  and rsiV < 50 ? 1 : 0)

bullSig = showSig and bullX and bullScore >= minScore
bearSig = showSig and bearX and bearScore >= minScore
```

Defaults: `useMacd = true`, `useSlow = true`, **`useRsi = false`**,
`minScore = 1`, `showSig = true`, `maType = "EMA"`, `maSrc = close`.

**The maximum score with the shipped defaults is 3, not 4.** The script's own
key table computes it: `maxScore = 1 + (useMacd ? 1 : 0) + (useSlow ? 1 : 0) +
(useRsi ? 1 : 0)`. The `minScore` input's `maxval = 4` is a ceiling on the
input widget, not a reachable score. So a `|score| >= 2` screen selects the
set `{2, 3}` -- two of the three possible values, i.e. it rejects only the
bare cross.

The label text, verbatim, and it is two lines:

```pine
if bullSig
    txt = "Bullish\n+" + str.tostring(bullScore)      // "Bullish" / "+3"
if bearSig
    txt = "-" + str.tostring(bearScore) + "\nBearish" // "-3" / "Bearish"
```

An arrow is also plotted: `shape.arrowup` below the bar for bull,
`shape.arrowdown` above for bear. With `boxedSig = false` (default) the label
is drawn `atrV * 1.8` away from the bar's low/high with no box.

Three properties the implementation has to preserve:

- **The score is computed on EVERY bar**, and only read on cross bars. That is
  harmless in Pine and worth keeping in the port, because it makes the score a
  plain vectorised expression and keeps the cross test independent of it.
- **`close > maSlow` is FALSE when `maSlow` is `na`.** A symbol with fewer
  than 200 bars gets no Slow point, so a young crypto listing can never score
  above 2. That is not a bug to patch; it is the chart's behaviour, and the
  screen reports `slow_ready: false` so a reviewer can see why the score is
  capped.
- **`ta.crossover` is strict on one side and non-strict on the other**:
  `a[1] <= b[1] and a > b`. Equal MAs on the previous bar still count as a
  cross when they separate. `>=`/`<=` on the wrong side changes the bar the
  signal lands on.

### 6.4.2 Everything else the Top script draws (not screened, documented)

| Feature | Inputs | What it does |
|---|---|---|
| MA stack | `fastLen 20`, `midLen 50`, `slowLen 200`, `maType EMA` | Slow line green while `maMid > maSlow`, red otherwise; Mid-Slow band filled the same colour at 82 % transparency |
| Golden / death cross labels | `showXLbl false` | `BULLISH`/`BEARISH` on `ta.crossover(maMid, maSlow)`; off by default |
| RSI extreme columns | `showRsiCols true`, `rsiOB 75`, `rsiOS 25` | Green column at `rsiV >= 75`, red at `<= 25`. Shares one `bgcolor` with the optional signal column to save plot slots |
| Background regime zone | `showBg false` | Whole-chart tint by `regime`; off because it swamped the dark theme |
| ATH / ATL | `showATH true` | Running max/min of the LOADED history, `var float` accumulators. Not a real all-time high -- it is whatever bars TradingView has paged in |
| Yearly opens | `showYO true`, `yoCount 2` | `request.security(..., "12M", open, lookahead = barmerge.lookahead_on)`. **The only look-ahead in the template**, and it is safe: a year's open is known at the year's start |
| Range High / Low | `showRange false`, `rangeLen 100` | `ta.highest/lowest(100)` |
| Manual levels / zones | six `m1p..m6p` + names, two zones | 0 = off |
| Auto S/R | `showSR true`, `pivLen 10`, `maxSR 3` | `ta.pivothigh/low(high/low, 10, 10)` kept in newest-first arrays, max 3 a side; green below price, red above, grey once broken |
| Distance filter | `maxDist 100` | Hides any level outside `price/2 .. price*2`. Added because BTC's all-time low near $100 was squashing the scale |
| Trade box | `trMode "Auto (last signal)"`, `autoMaxAge 60`, `slMode "Swing"`, `swingLen 5`, `atrMult 1.5`, `atrPad 0.25`, `maxStopPct 15`, `r1/r2/r3 = 1/2/3` | Profit box entry->TP3 and stop box entry->SL from the last signal if within 60 bars; auto stop capped at 15 % of entry; targets floored at `entry * 0.05` |
| Reversal box | `revOn true`, `revLook 30`, `revPad 1.0`, `revMaxAge 60`, `revHide true` | While `rsiV >= 75`: SHORT box re-anchored to each close, stop `= highest(high,30) + ATR*1.0`, target `= lowest(low,30)`; mirror at `<= 25`. Freezes when RSI leaves the zone, dies on stop/target/60 bars. README is explicit that this is a RECONSTRUCTION of a pattern in the owner's screenshots, not his private rules |
| Key table | `showKey true`, `keyLive true` | 14-row legend in a corner with three live rows: trend now, last signal (`"Bullish +3, 12 bars ago"`), trade now |
| Plot budget | -- | TradingView allows 64 plot slots. A `plot()` with a COMPILE-TIME-LITERAL colour costs 1 slot; an input or series colour costs 2. v5 failed at 71 and v5.2 at 68 on exactly that. v5.3 sits at ~31-34. `plotshape`, `bgcolor`, `fill` with a series colour and `alertcondition` all count |

`ta.atr(14)` is computed once and used by the label offsets, the swing stop
pad and the reversal pad. The screen publishes it as a volatility column
(`atr`, `atr_pct`) because a reviewer eyeballing a shortlist wants to know
whether a 2 % move is large for the name.

### 6.4.3 Alerts exposed

`bullSig`, `bearSig`, `goldX` (Mid over Slow), `deadX` (Mid under Slow),
`revNew` (RSI just entered an extreme). RULE B corresponds to the first two,
filtered by score.

---

## 6.5 The screen specification

### 6.5.1 The two rules

As of the LATEST CLOSED DAILY BAR (bar index `n-1`):

```
RULE A   bull_div[n-1] or bear_div[n-1]                            (6.2.2)
RULE B   (bull_signal[n-1] and bull_score[n-1] >= 2)
      or (bear_signal[n-1] and bear_score[n-1] >= 2)               (6.4.1)

mode 1   pass = RULE A
mode 2   pass = RULE A or RULE B
```

Both rules are generalised to a freshness WINDOW in bars, because a scanner
that only ever looks at the final bar loses everything on any day its cron
does not run:

```
div_fresh_bars    = N  admits a divergence with bars_ago in 0 .. N-1
signal_fresh_bars = N  admits a cross      with bars_ago in 0 .. N-1
```

Both default to `1` in `ScreenConfig` -- the literal reading of the brief:
"as of the latest closed daily bar". **PART 5's schema table names `3` as the
default** while its own prose recommends starting at 1 and widening after a
week of observed volume. The two are not in conflict about anything real: it
is one config field, it is measured in 6.5.4, and the number should be chosen
from the observed daily row count rather than from either document.
Recommendation for production, stated as a recommendation and not baked in:
**3**. GitHub
coalesces schedules (measured elsewhere in this repo at up to 115-minute gaps
on a `*/5` cron), a market holiday shifts the bar count, and a miss on this
screen costs a trade while a duplicate costs a glance. At `N=3` the same name
reappears for three days; de-duplicate on the downstream side the way
`morning_plays.py` already does, not by narrowing the window.

### 6.5.2 Why the freshness window is in BARS and not in days

Calendar days and bars diverge on every ASX/NASDAQ holiday and never diverge
on crypto. Bars are what the Pine counts, so bars are what the port counts.
`bars_ago = (n - 1) - i` where `i` is the bar the condition fired on; 0 is the
last closed bar.

### 6.5.3 What "latest closed bar" means per market, and the one way to get it wrong

The single easiest way to manufacture a signal that evaporates overnight is to
hand this screen a PARTIAL last bar. The function cannot detect one.

- ASX / NASDAQ: drop today's bar until the session has closed. In the existing
  repo, `scan.yml` already runs its market-hours crons against live-ish data
  and `data.py` carries a `_frame_age_days` check in the MARKET's calendar
  (TOP100 #23) -- reuse that, do not re-derive it.
- Crypto: drop the in-progress UTC day. The existing crypto cadence is
  `:22`/`:52` all day, so a naive last-bar read is a partial bar 23 times out
  of 24.

### 6.5.4 Universe and expected yield

ASX ~2,212 names, NASDAQ ~1,430, crypto ~100 + extras (the counts
`scanner/universe.py` publishes today). ~3,740 symbols total.

Measured on 200 synthetic geometric random walks of 750 bars each
(sigma 1.5 %/day), which is a defensible null-hypothesis tape:

| Freshness | mode 2 (A or B) | mode 1 (A only) |
|---|---|---|
| 1 bar | 7 / 200 = 3.5 % | 1 / 200 = 0.5 % |
| 3 bars | 20 / 200 = 10.0 % | 5 / 200 = 2.5 % |
| 5 bars | 36 / 200 = 18.0 % | 12 / 200 = 6.0 % |

Extrapolated to 3,740 names at the default 1-bar window: roughly **130 rows a
day in mode 2, of which about 20 are divergences**. That is a reviewable list.
At a 3-bar window it is ~370 rows in mode 2, which is not -- so if the window
is widened, mode 1 (or a per-market cap, the `MORNING_PLAYS_MAX_ROWS` shape)
should come with it.

Real tape will not match a random walk: divergences cluster after trends, and
20/50 crosses cluster after a regime turn, so expect the daily count to be
lumpy rather than flat. Treat the table as an order of magnitude, not a
forecast.

### 6.5.5 Performance

Measured: **19.6 ms per symbol** for 750 daily bars, single core, pandas 3.0.6.
The full 3,740-name universe is therefore about **73 seconds of CPU** -- the
screen is free next to the Yahoo download that feeds it. No optimisation is
warranted; do not vectorise across symbols at the cost of readability.

The one hot spot is the recursive EMA/RMA loop, which is a genuine recurrence
(`out[i]` depends on `out[i-1]`) and cannot be vectorised. If it ever matters,
the fix is the one TURTLE's `supertrend` used (TOP100 #73): keep the loop and
walk plain numpy scalars instead of pandas `.iat` -- which is already what
`_recursive_ma` does.

### 6.5.6 Output contract

`screen_symbol()` returns a flat dict; `screen_frames()` returns a DataFrame of
those dicts, ranked. Every field is listed in 6.7's "ONE FULL ROW" dump.
The fields a reviewer actually reads:

| Field | Meaning |
|---|---|
| `passes`, `rules`, `direction` | the verdict; `rules` is `A`, `B` or `A+B`; `direction` is `bull`/`bear`/`conflict` |
| `rule_a_bars_ago` | 0 = the divergence confirmed on the last closed bar |
| `rule_a_label_bars_ago` | where the `Bull`/`Bear` LABEL sits on the chart (always `bars_ago + 5`) |
| `rule_a_price_at_pivot`, `rule_a_prev_price` | the two lows (or highs) that made the price leg |
| `rule_a_rsi_at_pivot`, `rule_a_prev_rsi` | the two RSI readings that made the oscillator leg |
| `rule_a_bars_between_pivots` | `ta.barssince(plFound[1])`; add 1 for the real bar gap |
| `rule_b_score`, `rule_b_label` | 2 or 3, and the exact chart text (`Bullish +3` / `-3 Bearish`) |
| `rule_b_macd_hist`, `rule_b_above_slow` | which points the score was made of |
| `trend`, `regime` | `up`/`down`/`unknown` from `maMid > maSlow`; `fast>mid>slow` etc. |
| `rsi`, `rsi_zone`, `atr_pct` | context for the eyeball pass |
| `slow_ready`, `history_warning`, `n_bars` | why a score is capped, or a verdict absent |
| `ok`, `reason` | a frame that could not be screened says so instead of raising |

Ranking is `passes`, then freshest, then both-rules-first, then RULE A before
a RULE-B-only row, then higher score, then symbol. **Every tier is a stated
preference, not a measured one** -- there is no evidence in this repo that a
score of 3 outperforms a 2, and sorting a scanner by its own backtest is how a
page becomes a curve fit (the same argument `turtle.py::rank_key` is pinned
against).

### 6.5.7 Where this should live in the existing repo

Not prescriptive, but the shape that fits the house rules:

- engine in `scanner/pine_screen.py`, runner `scanner/pine_run.py`, output
  `public/data/<market>_pine.json`, own concurrency group, own nightly
  workflow, its own tab -- the TURTLE pattern exactly;
- every constant in `scanner/config.py` before first use (house rule 3);
- `assert_staged.sh` after staging and a `WATCHDOG_RUNS` entry, because it
  commits data;
- nothing under `scanner/broker/` may import it, and a test should pin that
  fence the way `tests/test_turtle.py` pins TURTLE's.

---

## 6.6 The reference implementation

### 6.6.1 API surface

```
wilder_rma(series, period, seed=None)            -> Series   ta.rma
sma_pine(series, period)                         -> Series   ta.sma
ema_pine(series, span, seed=None)                -> Series   ta.ema
ma_pine(series, length, ma_type="EMA")           -> Series   f_ma()
rsi_wilder(close, period=14)                     -> Series   ta.rsi
macd_pine(close, 12, 26, 9)                      -> (macd, signal, hist)
true_range(df)                                   -> Series   ta.tr(true)
atr_wilder(df, period=14)                        -> Series   ta.atr

crossover(a, b) / crossunder(a, b) / cross(a, b) -> bool Series
pivot_low_confirmed(series, left, right, ...)    -> Series   ta.pivotlow
pivot_high_confirmed(series, left, right, ...)   -> Series   ta.pivothigh
valuewhen(condition, source, occurrence=0)       -> Series   ta.valuewhen
barssince(condition)                             -> Series   ta.barssince
shift_bool(condition, by=1)                      -> ndarray  cond[by]

prepare_frame(df)                                -> DataFrame
rsi_divergence(df, cfg)                          -> DataFrame (RULE A + workings)
cross_signal(df, cfg)                            -> DataFrame (RULE B + workings)
evaluate(df, cfg)                                -> DataFrame (everything, per bar)
screen_symbol(df, cfg, symbol, market)           -> dict
screen_frames({symbol: df}, cfg, ...)            -> DataFrame (ranked)
assert_no_lookahead(df, cfg, bars=None)          -> int (cut points checked)
```

### 6.6.2 The seeding question, and why `ema_pine` takes a `seed`

The brief specified `ema_pine(series, span) - Pine ta.ema (adjust=False)`.
Those are two different functions and the difference is measurable.

`pandas.Series.ewm(span=n, adjust=False).mean()` seeds on the FIRST value and
emits a number from bar 0. TradingView's `ta.ema` seeds on the SMA of the
first `length` values and emits `na` until bar `length-1`. Same for `ta.rma`.
Measured on a 0..999 ramp: the two EMA200 series differ by **0.247 price units
at bar 600** and 0.0046 at bar 999. On a real 750-bar daily frame that is
enough to flip a `close > maSlow` comparison on a bar where price is grazing
the 200 EMA -- i.e. enough to move a score from 3 to 2.

So: `ema_pine(..., seed="sma")` is the default and reproduces the chart;
`seed="first"` reproduces `ewm(adjust=False)` and is offered only so the
difference is demonstrable. `ScreenConfig.ema_seed` / `rma_seed` carry it.

The warm-up NaNs this produces are load-bearing, not cosmetic: they are what
makes `close > maSlow` correctly false on a 120-bar listing.

### 6.6.3 No look-ahead, proved rather than asserted

`assert_no_lookahead()` recomputes everything on `df[:i+1]` for each cut point
`i` and compares the final row against row `i` of the full-history run, across
17 columns, to 1e-12. The self-test runs 223 cut points over three frames and
additionally re-runs the whole `screen_symbol` verdict on 41 truncations.

This is the test a divergence implementation most often fails. The tempting
shortcut is to stamp the divergence on the PIVOT bar, because that is where
the chart draws it. Do that and the screen looks wonderful in a backtest and
fires five bars late in production.

---

## 6.7 The run: verbatim console output

Produced by `python3 vivek50_selftest.py` (exit code 0). Nothing below is
transcribed; it is the captured stdout of the run, reproduced whole.

```text

==============================================================================
vivek50_screen self-test -- pandas 3.0.6, numpy 2.4.6
==============================================================================
warm-ups: rsi14=14  ema20=19  ema50=49  ema200=199  macdhist=33  atr14=13
  PASS  test_warmup_lengths_match_pine
rma alpha=1/4 seeded on SMA; ema alpha=0.4 seeded on SMA -- both confirmed
  PASS  test_rma_is_wilder_not_an_ema
rsi degenerate cases: all-up=100  all-down=0  flat=NaN (0/0)  ramp-then-halt=100
  PASS  test_rsi_degenerate_cases
crossover/crossunder: NaN-safe, previous-bar rule confirmed
  PASS  test_crossover_is_nan_safe_and_uses_the_previous_bar
pivot: confirmed exactly `right` bars late, value = the pivot's own
  PASS  test_pivot_is_confirmed_right_bars_late
in-range window: rangeLower..rangeUpper 5..60 means a 6..61 bar pivot gap
  PASS  test_the_barssince_off_by_one_sets_a_6_to_61_bar_window
valuewhen(cond, src, 1): NaN until two occurrences, then the previous one
  PASS  test_valuewhen_needs_two_occurrences
bull: 8 RSI pivot lows in the frame, exactly ONE divergence, on bar 129
      pivot bar 124   price low 79.5071 -> 77.2996 (lower)   RSI 3.97 -> 10.44 (higher)
      barssince(plFound[1]) = 49  (a 50-bar gap between pivots)
  PASS  test_a_bullish_divergence_fires_five_bars_after_the_pivot
bear: exactly ONE divergence, on bar 129 (pivot bar 124)
      price high 125.3258 -> 128.1205 (higher)   RSI 97.28 -> 89.47 (lower)
  PASS  test_b_bearish_divergence_fires_five_bars_after_the_pivot
score 3: bar 292  hist +1.3649  close 145.20  ema200 119.43  -> label 'Bullish +3'
  PASS  test_c_cross_with_macd_up_and_price_above_the_200_scores_three
score 1: bar 293  hist -0.2258  close 90.29  ema200 115.49  -> label 'Bullish +1'
        rejected by min_signal_score=2, detected again at min_signal_score=1
  PASS  test_d_cross_with_macd_down_and_price_below_the_200_scores_one
score arithmetic verified across all five switch combinations (1,2,2,3,4)
  PASS  test_the_score_is_arithmetic_not_a_lookup
flat 300-bar frame: 0 pivots, 0 divergences, 0 crosses, ATR 0, no exception
  PASS  test_e_a_flat_series_produces_nothing_and_does_not_crash
gaps / NaN rows / empty frame / junk frame: all handled, none raised
  PASS  test_gaps_and_nans_do_not_raise
no look-ahead: 223 cut points x 40 columns, all identical
                screen verdict re-run on 41 truncations: 0 mismatches
  PASS  test_f_no_look_ahead_anywhere
120-bar frame: screened, slow_ready=False, trend='unknown', max score 2
30-bar frame: refused with a reason, not an exception
  PASS  test_g_a_frame_shorter_than_the_slow_ma_is_sensible_not_fatal
mode 1 drops a score-3 cross; mode 2 keeps it. Both report both rules.
  PASS  test_mode_1_is_divergence_only
freshness: div_fresh_bars=N admits bars_ago 0..N-1, inclusive of today
  PASS  test_freshness_windows_are_in_bars
equal consecutive lows: strict=0 pivots, loose-right=1, loose-left=1, loose-both=2
  PASS  test_h_equal_consecutive_lows_make_no_pivot_under_the_strict_rule
single-bar 10x spike: screened, no divergence, no look-ahead
  PASS  test_h_a_single_bar_spike_does_not_leak_or_crash
descending frame: refused with a reason (backwards RSI would have read 60.2 against the true 38.9)
  PASS  test_h_a_descending_frame_is_REFUSED_not_screened
duplicated / repeated / gapped index: positional, identical verdicts
  PASS  test_h_a_duplicated_or_gapped_index_is_positional_and_harmless
interior NaN rows: dropped, recursive averages stay finite
  PASS  test_h_interior_nan_rows_are_dropped_and_do_not_poison_the_averages
descending-then-flat: RSI 0 (not NaN), extreme-oversold, no signal
  PASS  test_h_a_descending_then_flat_rsi_is_zero_not_undefined
mode 1: RULE B reported, and no longer able to set `direction`
  PASS  test_h_mode_1_does_not_let_rule_b_colour_the_direction
mistyped source: refused by validate(), reported as a row reason
  PASS  test_h_a_mistyped_source_is_refused_instead_of_silently_meaning_close
look-ahead proof: both planted bugs caught, module clean afterwards
  PASS  test_h_the_lookahead_proof_catches_a_planted_lookahead
differential vs a naive bar-by-bar Pine reading: 96 frame/convention pairs identical
  PASS  test_h_matches_a_naive_bar_by_bar_pine_reading

==============================================================================
SCREEN OUTPUT -- mode 2 (RULE A or RULE B), every symbol shown
==============================================================================
    symbol passes rules direction score best_bars_ago rule_a_direction rule_b_label  close  rsi   trend n_bars                               reason
BEARDIV.AX   True     A      bear                   0             bear              124.42 61.1 unknown    130                                     
BULLDIV.AX   True     A      bull                   0             bull               81.30 41.1 unknown    130                                     
SCORE3.NDQ   True     B      bull     3             0                    Bullish +3 145.20 70.5      up    293                                     
   FLAT.AX  False                                                                    42.00         down    300                                     
SCORE1.NDQ  False                                                                    90.29 63.1    down    294                                     
  STALE.AX  False                                                                    88.00 73.1 unknown    141                                     
  TINY-USD  False                                                                                           30 history too short (30 bars, need 60)
 YOUNG-USD  False                                                                    14.00 57.9 unknown    120                                     

==============================================================================
SCREEN OUTPUT -- mode 2, only the rows a reviewer opens (ranked)
==============================================================================
    symbol rules direction score best_bars_ago rule_a_label_bars_ago  close  rsi   rsi_zone   trend        regime atr_pct macd_hist
BEARDIV.AX     A      bear                   0                     5 124.42 61.1    neutral unknown      fast>mid    1.30   -0.3364
BULLDIV.AX     A      bull                   0                     5  81.30 41.1    neutral unknown      fast<mid    1.62   +0.3207
SCORE3.NDQ     B      bull     3             0                       145.20 70.5 overbought      up fast>mid>slow    1.44   +1.3649

==============================================================================
SCREEN OUTPUT -- mode 1 (RULE A only)
==============================================================================
    symbol rules direction best_bars_ago rule_a_label_bars_ago  close  rsi rsi_zone   trend
BEARDIV.AX     A      bear             0                     5 124.42 61.1  neutral unknown
BULLDIV.AX     A      bull             0                     5  81.30 41.1  neutral unknown

==============================================================================
ONE FULL ROW -- every field screen_symbol() publishes for BULLDIV.AX
==============================================================================
  above_slow                 None
  atr                        1.3191707104588632
  atr_pct                    1.62
  best_bars_ago              0
  close                      81.29855349564703
  direction                  'bull'
  fast                       81.79094145440024
  history_warning            'only 130 bars: the 200 MA is absent'
  last_bar                   '2024-06-28 00:00:00'
  macd_hist                  0.32072822112268007
  market                     'asx'
  mid                        85.5057311743403
  n_bars                     130
  ok                         True
  passes                     True
  reason                     ''
  regime                     'fast<mid'
  rsi                        41.074811580959235
  rsi_ma                     20.544042850058933
  rsi_zone                   'neutral'
  rule_a                     True
  rule_a_bars_ago            0
  rule_a_bars_between_pivots 49.0
  rule_a_direction           'bull'
  rule_a_label_bars_ago      5
  rule_a_pivot_bar           '2024-06-21 00:00:00'
  rule_a_pivot_bars_ago      5
  rule_a_prev_price          79.50714071833556
  rule_a_prev_rsi            3.9748530596391163
  rule_a_price_at_pivot      77.29958871978675
  rule_a_rsi_at_pivot        10.440186699725118
  rule_b                     False
  rule_b_bars_ago            None
  rule_b_direction           ''
  rule_b_score               None
  rules                      'A'
  score                      None
  slow                       None
  slow_ready                 False
  symbol                     'BULLDIV.AX'
  trend                      'unknown'

==============================================================================
ScreenConfig -- every field and its default
==============================================================================
  rsi_len                14
  rsi_source             'close'
  rsi_ma_len             14
  rsi_ma_type            'SMA'
  rsi_long_avg_len       50
  rsi_ob1                70.0
  rsi_ob2                75.0
  rsi_os1                30.0
  rsi_os2                25.0
  rsi_midline            50.0
  show_div               True
  piv_left               5
  piv_right              5
  range_upper            60
  range_lower            5
  macd_fast              12
  macd_slow              26
  macd_signal            9
  macd_source            'close'
  fast_len               20
  mid_len                50
  slow_len               200
  ma_type                'EMA'
  ma_source              'close'
  top_rsi_len            14
  top_rsi_ob             75.0
  top_rsi_os             25.0
  use_macd               True
  use_slow               True
  use_rsi                False
  min_score              1
  atr_len                14
  sr_pivot_len           10
  sr_max_per_side        3
  range_len              100
  swing_len              5
  atr_mult               1.5
  atr_pad                0.25
  max_stop_pct           15.0
  r1                     1.0
  r2                     2.0
  r3                     3.0
  auto_max_age           60
  rev_look               30
  rev_pad                1.0
  rev_max_age            60
  max_dist_pct           100.0
  yo_count               2
  mode                   2
  div_fresh_bars         1
  signal_fresh_bars      1
  min_signal_score       2
  div_directions         ('bull', 'bear')
  signal_directions      ('bull', 'bear')
  min_bars               60
  warn_bars              260
  ema_seed               'sma'
  rma_seed               'sma'
  pivot_strict_left      True
  pivot_strict_right     True
  max_score              3  (derived: 1 + useMacd + useSlow + useRsi)

==============================================================================
28/28 tests passed
==============================================================================
```

---

## 6.8 Every config field and its default

`ScreenConfig` is a plain dataclass; `cfg.replace(**kw)` returns a validated
copy. `DEFAULT_CONFIG` is a module-level instance -- it is NOT frozen, so do
not mutate it in place; call `.replace()`.

### 6.8.1 From `Final_RSI_Plus.pine`

| Field | Default | Pine input |
|---|---|---|
| `rsi_len` | `14` | `rsiLen = input.int(14, "RSI Length")` |
| `rsi_source` | `"close"` | `rsiSrc = input.source(close, "Source")` |
| `rsi_ma_len` | `14` | `maLen = input.int(14, "MA Length")` |
| `rsi_ma_type` | `"SMA"` | `maType = input.string("SMA", options ["SMA","EMA"])` |
| `rsi_long_avg_len` | `50` | `longLen = input.int(50, "Long-run average length")` |
| `rsi_ob1` | `70.0` | `ob1 = input.float(70, "Overbought")` |
| `rsi_ob2` | `75.0` | `ob2 = input.float(75, "extreme")` |
| `rsi_os1` | `30.0` | `os1 = input.float(30, "Oversold")` |
| `rsi_os2` | `25.0` | `os2 = input.float(25, "extreme")` |
| `rsi_midline` | `50.0` | `midL = input.float(50, "Midline")` |
| `show_div` | `True` | `showDiv = input.bool(true, "Regular divergences")` |
| `piv_left` | `5` | `lbL = input.int(5, "Pivot lookback left")` |
| `piv_right` | `5` | `lbR = input.int(5, "Pivot lookback right")` |
| `range_upper` | `60` | `rangeUpper = input.int(60, "Max bars between pivots")` |
| `range_lower` | `5` | `rangeLower = input.int(5, "Min bars between pivots")` |

### 6.8.2 From `Final_Bottom_MACD.pine` / the Top script's Signals group

| Field | Default | Pine input |
|---|---|---|
| `macd_fast` | `12` | `fastLen` / `macdFast` |
| `macd_slow` | `26` | `slowLen` / `macdSlow` |
| `macd_signal` | `9` | `sigLen` / `macdSig` |
| `macd_source` | `"close"` | `src = input.source(close, "Source")` |

### 6.8.3 From `Final_Top_Script.pine`

| Field | Default | Pine input |
|---|---|---|
| `fast_len` | `20` | `fastLen = input.int(20, "Fast Length")` |
| `mid_len` | `50` | `midLen = input.int(50, "Mid Length")` |
| `slow_len` | `200` | `slowLen = input.int(200, "Slow Length")` |
| `ma_type` | `"EMA"` | `maType = input.string("EMA", options ["EMA","SMA"])` |
| `ma_source` | `"close"` | `maSrc = input.source(close, "Source")` |
| `top_rsi_len` | `14` | `rsiLen = input.int(14, "RSI length")` |
| `top_rsi_ob` | `75.0` | `rsiOB = input.float(75, "RSI overbought")` |
| `top_rsi_os` | `25.0` | `rsiOS = input.float(25, "RSI oversold")` |
| `use_macd` | `True` | `useMacd = input.bool(true, "+1 when the MACD histogram agrees")` |
| `use_slow` | `True` | `useSlow = input.bool(true, "+1 when price is on the right side of the Slow MA")` |
| `use_rsi` | `False` | `useRsi = input.bool(false, "+1 when RSI agrees (> 50 / < 50)")` |
| `min_score` | `1` | `minScore = input.int(1, "Minimum score to show", maxval = 4)` |
| `atr_len` | `14` | `atrV = ta.atr(14)` |
| `sr_pivot_len` | `10` | `pivLen = input.int(10, "Pivot strength")` |
| `sr_max_per_side` | `3` | `maxSR = input.int(3, "Levels per side")` |
| `range_len` | `100` | `rangeLen = input.int(100, "Range lookback (bars)")` |

DRAWING-ONLY (transcribed for completeness; the screen never reads them):
`swing_len 5`, `atr_mult 1.5`, `atr_pad 0.25`, `max_stop_pct 15.0`,
`r1 1.0`, `r2 2.0`, `r3 3.0`, `auto_max_age 60`, `rev_look 30`, `rev_pad 1.0`,
`rev_max_age 60`, `max_dist_pct 100.0`, `yo_count 2`.

### 6.8.4 The screen's own fields (no Pine counterpart)

| Field | Default | Meaning |
|---|---|---|
| `mode` | `2` | 1 = RULE A only, 2 = RULE A or RULE B |
| `div_fresh_bars` | `1` | RULE A admits `bars_ago` in `0 .. N-1` |
| `signal_fresh_bars` | `1` | RULE B admits `bars_ago` in `0 .. N-1` |
| `min_signal_score` | `2` | RULE B threshold; the owner's `|score| >= 2` |
| `div_directions` | `("bull","bear")` | narrow to one side if wanted |
| `signal_directions` | `("bull","bear")` | same for RULE B |
| `min_bars` | `60` | below this, refuse with a reason rather than guess |
| `warn_bars` | `260` | below this, stamp `history_warning` |
| `ema_seed` | `"sma"` | `"sma"` = Pine, `"first"` = `ewm(adjust=False)` |
| `rma_seed` | `"sma"` | same, for Wilder smoothing |
| `pivot_strict_left` | `True` | a tie on the left disqualifies the pivot |
| `pivot_strict_right` | `True` | a tie on the right disqualifies the pivot |

Derived: `cfg.max_score` = `1 + use_macd + use_slow + use_rsi` = **3** at
defaults.

---

## 6.9 KNOWN LIMITS

Where this reference deviates from TradingView, or knowingly cannot match it.
Each one says what it costs and which direction the error runs in.

**1. The pivot tie convention is a DECISION, not a transcription.** Pine's
`ta.pivotlow` / `ta.pivothigh` documentation does not state what happens when
the centre bar EQUALS a neighbour, and there is no Pine compiler and no chart
in this environment to settle it. The implementation requires the centre to be
a strictly unique extreme on both sides (`pivot_strict_left =
pivot_strict_right = True`).

**PART 5 of this document states the non-strict reading** ("less than or equal
to every rsi value in the window other than itself"). That is a real
disagreement between two parts of one document and it is left visible on
purpose: neither of us could verify it, and pretending to agree would hide the
one unverified assumption in the whole port. `pivot_strict_left` and
`pivot_strict_right` are config flags precisely so the question can be settled
by measurement later without touching any other code.

MEASURED, so the disagreement can be sized rather than argued about. 300
synthetic random walks x 750 daily bars, prices ROUNDED TO CENTS so that
genuine ties actually occur (on unrounded floats they essentially never do):

| | strict both sides | non-strict both sides |
|---|---|---|
| RSI pivots found | 28,870 | 29,007 (+0.5 %) |
| divergences fired | 3,379 | 3,386 (+0.2 %) |

Of ~3,380 divergences, **27 disagree: 10 fire only under strict, 17 only under
non-strict.** That is 0.8 %, and the important half is that it runs in BOTH
directions:

- At the PIVOT level, relaxing is monotone -- it can only add pivots.
- At the DIVERGENCE level it is NOT monotone, and that is not obvious. An
  extra pivot inserted between two existing ones becomes the new "previous
  pivot" for the later one and shortens its gap, which can push it out of the
  6..61 bar window or change which prior low it is compared against. So
  loosening the rule can DELETE a divergence. My earlier instinct that
  loosening "can only ever add rows" is true of pivots and false of
  divergences; it was worth measuring rather than asserting.

Practical impact is therefore sub-1 % either way on liquid names, and
concentrated on flat / halted / illiquid stretches -- which is the population
a scanner should be filtering out for other reasons anyway.

**How to settle it in one sitting:** put `Final_RSI_Plus` on a chart, export
the pane's `Bull`/`Bear` marks for 20 liquid names over two years
(TradingView's "Export chart data" gives the plotted series), run this module
over the same bars, and diff the firing bar indices. If they differ, the tie
flags are the first thing to try. Until someone does that, this is the one
place a spec reader should not assume bit-identity.

**2. `ta.ema` / `ta.rma` seeding is reconstructed, not documented.**
TradingView's reference states the alpha but not the seed. This module seeds
on the SMA of the first `length` values and emits NaN before, which matches
the observed warm-up behaviour of the charts (an EMA200 draws nothing for the
first 199 bars). If TradingView's seed is in fact something else, the
divergence between the two is at most ~0.25 price units on a 200-period EMA
by bar 600 (measured, on a ramp) and decays; it matters only for a
`close > maSlow` comparison within a hair of the line, and only for the Slow
point of the score, never for RULE A.

**3. `request.security()` has no counterpart and is not needed.** The Top
script's yearly opens use `lookahead = barmerge.lookahead_on`. That is
legitimate for an `open` (known at the year's start) but it is the only
non-causal call in the template, and nothing the screen reads depends on it.
If a future rule ever reads a yearly open, it must be re-derived from the
daily frame, not copied from this pattern.

**4. The screen cannot tell a partial last bar from a closed one.** It is the
caller's job to drop today's in-progress bar. Hand it a live intraday bar and
RULE B in particular will fire on crosses that un-cross by the close. See 6.5.3.

**5. `regime` is `maMid > maSlow`, so EQUAL reads as "down".** On a halted
name `maMid == maSlow` and the chart colours the Slow line RED. The screen
reports `trend: "down"` to match the chart rather than inventing a third
state. It is faithful, and mildly misleading on exactly the names nothing will
fire on anyway.

**6. ATH / ATL are "of the loaded history" in Pine and are not reproduced at
all.** The Pine accumulates `var float ath` over whatever bars TradingView has
paged in, so the same script gives a different ATH before and after you scroll
left. There is no stable definition to port. Nothing in the screen uses it.

**7. `ta.rsi` on a perfectly flat series returns NaN. CORRECTED 2026-09-22 --
this limit previously claimed 100 and the claim was wrong.** The old text said
"Pine tests the zero-denominator branch first". There is no such branch:
`ta.rsi` is `rs = ta.rma(u, len) / ta.rma(d, len)` followed by
`100 - 100 / (1 + rs)`, one division, no chain of tests. On a series that has
never moved BOTH averages are exactly zero, `0 / 0` is NaN under IEEE, and the
formula yields na. The two genuine boundary cases survive unchanged and are
separately pinned: `rma(down) == 0` with `rma(up) > 0` is `+inf -> 100` (which
is why a real uninterrupted uptrend prints 100 on a TradingView chart), and
`rma(up) == 0` with `rma(down) > 0` is `0 -> 0`.

The old behaviour was also not harmless, which is the part the "the screen
never reaches it" sentence got wrong. No RULE A or RULE B verdict moved -- a
flat series has no pivots and no crosses, that much was right -- but the row
is still PUBLISHED, and every halted, suspended or never-traded name in the
universe came back as `rsi: 100.0, rsi_zone: "extreme-overbought"`. On a
scanner whose whole purpose is an eyeball review, that is a false positive in
the one column a reviewer scans. The condition is reachable only while the
series has been flat since its first bar, so the fix can only ever remove a
claim, never add one. If a chart comparison ever shows TradingView printing
100 there, `rsi_wilder`'s `both_zero` line is the single line to flip back.

**8. An interior NaN bar is DROPPED, not filled.** `prepare_frame()` removes
any row with a NaN in open/high/low/close. Pine has no such bar at all (a
halted session simply is not a bar), so dropping is the faithful behaviour,
and a recursive average poisoned by one NaN would otherwise return NaN for
the whole remainder of the symbol's history. Consequence: `bars_ago` counts
BARS PRESENT IN THE FRAME. If the feed drops a session, bar counts and
calendar days diverge by one. That is also true on the chart.

**9. Volume is carried but never used.** No liquidity gate is applied. The
existing repo gates liquidity in `scan.py` before grading; this screen
deliberately does not, because the template does not. A production scanner
almost certainly wants one -- an ASX shell on 4,000 shares a day will print
divergences all year -- but adding it changes which names are surfaced, so it
is the owner's call and not a port detail.

**10. No sector, no correlation, no dedupe, no cap.** Out of scope by design.
The 7-day dedupe pattern in `scripts/morning_plays.py` is the one already in
the repo and is the right shape to copy if the daily list repeats.

**11. Divergence type is REGULAR only.** The Pine does not implement hidden
divergence (price higher low + RSI lower low, and mirror), and neither does
this. If the owner asks for hidden divergences later, it is four comparisons
flipped in `rsi_divergence()` -- but it is a different signal with a different
meaning, not a setting.

**12. This module has no notion of a market, a timezone or a session.** It
takes an ordered frame of bars. Everything calendar-shaped -- which bar is the
last closed one, whether a gap is a holiday -- belongs to the caller, and the
repo already has `scan.py`'s market-local machinery for it.

---

## 6.10 Corrections to the brief

Stated plainly, as asked. The brief was accurate about the mechanism almost
throughout; these are the places where following it literally would have
produced a wrong scanner.

1. **The chart labels are two lines, not one.** The Pine builds
   `"Bullish\n+" + str.tostring(bullScore)` and
   `"-" + str.tostring(bearScore) + "\nBearish"`. The brief's `"Bullish +2"` /
   `"-2 Bearish"` is the README's prose rendering. Any code that matches on
   the literal string must account for the newline.

2. **The maximum score is 3, not 4.** `useRsi` ships OFF, so
   `maxScore = 1 + 1 + 1 = 3`. `|score| >= 2` therefore selects `{2, 3}` --
   it excludes only the bare cross. The brief's list "Bullish +2, Bullish +3,
   -2 Bearish, -3 Bearish" is right; the `minScore` input's `maxval = 4` is a
   widget ceiling on an unreachable value unless the RSI switch is turned on.

3. **`5 <= barssince(plFound[1]) <= 60` is NOT a 5-to-60-bar pivot gap.**
   Because the filter reads the PREVIOUS bar's `plFound`, the admitted gap
   between consecutive pivot confirmations is **6 to 61 bars inclusive**. The
   brief quoted the Pine correctly and warned to be careful; this is what the
   care resolves to. Both bounds are pinned by a test.

4. **"the RSI+ pane has printed a Bull or Bear label" is ambiguous, and the
   two readings differ by five bars.** The boolean fires on the confirmation
   bar; the label is DRAWN five bars to the left (`offset = -lbR`). A
   divergence that is fresh today has its label five bars back from the right
   edge. The implementation reports `rule_a_bars_ago` and
   `rule_a_label_bars_ago` separately so the reviewer opening the chart is not
   looking at the wrong bar.

5. **The divergence pivots are on the RSI only.** The brief's pseudocode is
   correct (`priceLL = low[i-5] < low[i-5] at the previous plFound bar`), but
   it is worth stating outright that there is no price pivot anywhere in this
   rule: the price leg compares the raw low/high of the bar the OSCILLATOR
   pivoted on. Implementing it as "a price pivot and an RSI pivot" gives a
   much sparser and different signal.

6. **`ema_pine(series, span) - Pine ta.ema (adjust=False)` conflates two
   different functions.** `ewm(adjust=False)` seeds on the first value and
   never emits NaN; Pine seeds on the SMA of the first `length` values and
   emits `na` through the warm-up. Measured gap on an EMA200: 0.247 price
   units at bar 600 of a ramp. The module implements both and defaults to the
   Pine behaviour (`ema_seed="sma"`); `"first"` is available and is what the
   brief literally asked for. The warm-up NaNs are load-bearing -- they are
   what makes the Slow point correctly unawarded on a young listing.

7. **`pivot_low_confirmed` "must match Pine's ta.pivotlow bar timing exactly"
   -- the TIMING does and is tested; the TIE convention could not be
   verified.** See 6.9 item 1. It is a config flag with a conservative
   default and a named way to settle it.

8. **Not in the brief, but stale in the repo:** `tradingview/README.md`'s
   feature table says the price-pane RSI columns fire at "RSI 14 at or above
   70 = green, at or below 30 = red". The shipped code uses `rsiOB = 75` /
   `rsiOS = 25`, and the README's own v2 changelog says so two paragraphs
   earlier. The table row was not updated. Harmless to the screen (it reads
   neither) but it will mislead anyone reading the README as the spec.

9. **Confirmed, not corrected:** the three files really are chart-only.
   Grepped at head -- nothing in `scanner/`, `phasemap/`, `functions/`,
   `test/` or `.github/` reads `tradingview/`. The only `tradingview` strings
   elsewhere are deep links in `public/js/chart.js` and embed widgets in
   `public/js/sectors.js`.

---

## 6.11 Full source: `vivek50_screen.py`

```python
"""vivek50_screen -- a pure pandas/numpy reference implementation of the
"Vivek 5.0" TradingView chart template's maths, plus the daily screen built on
top of it.

WHAT THIS MIRRORS
-----------------
Three Pine Script v6 files in tradingview/ of the googy-boys-scanner repo:

  Final_Top_Script.pine   indicator("Vivek 5.0 Top",  overlay = true)
  Final_Bottom_MACD.pine  indicator("Vivek 5.0 MACD", overlay = false)
  Final_RSI_Plus.pine     indicator("Vivek 5.0 RSI+", overlay = false)

Every function below names the Pine line(s) it reproduces in its docstring.
Nothing here talks to TradingView, to a broker, or to the network.

THE SCREEN
----------
Run daily, on the latest CLOSED daily bar, over ASX / NASDAQ / crypto:

  RULE A  the RSI+ pane printed a regular divergence ("Bull" / "Bear" label)
  RULE B  the Top overlay printed a scored Fast x Mid cross whose score is
          at least `min_signal_score` (2 by default)

  mode 1 = RULE A only
  mode 2 = RULE A or RULE B

The output feeds a manual eyeball review, so a false positive costs a glance
and a miss costs a trade. Every threshold is in ScreenConfig; nothing is
hardcoded at a call site.

CAUSALITY
---------
Every series returned by this module is causal: the value on bar i depends
only on bars 0..i. `assert_no_lookahead()` proves it by truncation, and the
self-test runs it. Nothing here uses request.security(), so the one genuinely
non-causal thing in the Pine (the yearly-open lookahead) has no counterpart.

ASCII only, by house rule 9.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "ScreenConfig",
    "wilder_rma",
    "rsi_wilder",
    "ema_pine",
    "sma_pine",
    "ma_pine",
    "macd_pine",
    "atr_wilder",
    "true_range",
    "crossover",
    "crossunder",
    "cross",
    "pivot_low_confirmed",
    "pivot_high_confirmed",
    "valuewhen",
    "barssince",
    "rsi_divergence",
    "cross_signal",
    "evaluate",
    "screen_symbol",
    "screen_frames",
    "assert_no_lookahead",
    "prepare_frame",
    "OHLC_COLUMNS",
]

OHLC_COLUMNS: Tuple[str, ...] = ("open", "high", "low", "close")


# =============================================================================
# configuration
# =============================================================================


@dataclass
class ScreenConfig:
    """Every tunable, with the default taken from the Pine source it mirrors.

    Fields are grouped by the Pine file they come from. Fields marked
    DRAWING-ONLY exist so this dataclass is a complete transcription of the
    template's inputs; the screen never reads them.
    """

    # ---- Final_RSI_Plus.pine ------------------------------------------------
    rsi_len: int = 14  # rsiLen      = input.int(14, "RSI Length")
    rsi_source: str = "close"  # rsiSrc = input.source(close, "Source")
    rsi_ma_len: int = 14  # maLen      = input.int(14, "MA Length")
    rsi_ma_type: str = "SMA"  # maType    = input.string("SMA", options SMA/EMA)
    rsi_long_avg_len: int = 50  # longLen = input.int(50, "Long-run average length")
    rsi_ob1: float = 70.0  # ob1        = input.float(70, "Overbought")
    rsi_ob2: float = 75.0  # ob2        = input.float(75, "extreme")
    rsi_os1: float = 30.0  # os1        = input.float(30, "Oversold")
    rsi_os2: float = 25.0  # os2        = input.float(25, "extreme")
    rsi_midline: float = 50.0  # midL   = input.float(50, "Midline")
    show_div: bool = True  # showDiv    = input.bool(true, "Regular divergences")
    piv_left: int = 5  # lbL          = input.int(5, "Pivot lookback left")
    piv_right: int = 5  # lbR         = input.int(5, "Pivot lookback right")
    range_upper: int = 60  # rangeUpper= input.int(60, "Max bars between pivots")
    range_lower: int = 5  # rangeLower = input.int(5,  "Min bars between pivots")

    # ---- Final_Bottom_MACD.pine (and the Top script's Signals group) --------
    macd_fast: int = 12  # fastLen / macdFast = input.int(12)
    macd_slow: int = 26  # slowLen / macdSlow = input.int(26)
    macd_signal: int = 9  # sigLen / macdSig  = input.int(9)
    macd_source: str = "close"  # src   = input.source(close, "Source")

    # ---- Final_Top_Script.pine, "Moving averages" ---------------------------
    fast_len: int = 20  # fastLen = input.int(20,  "Fast Length")
    mid_len: int = 50  # midLen   = input.int(50,  "Mid Length")
    slow_len: int = 200  # slowLen= input.int(200, "Slow Length")
    ma_type: str = "EMA"  # maType = input.string("EMA", options EMA/SMA)
    ma_source: str = "close"  # maSrc = input.source(close, "Source")

    # ---- Final_Top_Script.pine, "Background" --------------------------------
    top_rsi_len: int = 14  # rsiLen = input.int(14, "RSI length")
    top_rsi_ob: float = 75.0  # rsiOB= input.float(75, "RSI overbought")
    top_rsi_os: float = 25.0  # rsiOS= input.float(25, "RSI oversold")

    # ---- Final_Top_Script.pine, "Signals (Fast x Mid cross, scored)" --------
    use_macd: bool = True  # useMacd  = input.bool(true,  "+1 MACD agrees")
    use_slow: bool = True  # useSlow  = input.bool(true,  "+1 price beyond Slow")
    use_rsi: bool = False  # useRsi   = input.bool(false, "+1 RSI agrees")
    min_score: int = 1  # minScore   = input.int(1, "Minimum score to show")

    # ---- Final_Top_Script.pine, misc computation ----------------------------
    atr_len: int = 14  # atrV = ta.atr(14)
    sr_pivot_len: int = 10  # pivLen = input.int(10, "Pivot strength")
    sr_max_per_side: int = 3  # maxSR = input.int(3, "Levels per side")
    range_len: int = 100  # rangeLen = input.int(100, "Range lookback (bars)")

    # ---- Final_Top_Script.pine, DRAWING-ONLY (unused by the screen) ---------
    swing_len: int = 5  # swingLen   = input.int(5,   "Swing lookback")
    atr_mult: float = 1.5  # atrMult  = input.float(1.5, "ATR multiple")
    atr_pad: float = 0.25  # atrPad   = input.float(0.25,"ATR pad beyond swing")
    max_stop_pct: float = 15.0  # maxStopPct = input.float(15, "max stop %")
    r1: float = 1.0  # r1 = input.float(1.0, "TP1 (R)")
    r2: float = 2.0  # r2 = input.float(2.0, "TP2 (R)")
    r3: float = 3.0  # r3 = input.float(3.0, "TP3 (R)")
    auto_max_age: int = 60  # autoMaxAge = input.int(60, "signal within bars")
    rev_look: int = 30  # revLook    = input.int(30, "Structure lookback")
    rev_pad: float = 1.0  # revPad    = input.float(1.0,"ATR pad for rev stop")
    rev_max_age: int = 60  # revMaxAge = input.int(60, "Keep the box for bars")
    max_dist_pct: float = 100.0  # maxDist = input.float(100, "Hide a level")
    yo_count: int = 2  # yoCount    = input.int(2, "Yearly opens to show")

    # ---- the screen (no Pine counterpart; these are the owner's rules) ------
    mode: int = 2  # 1 = RULE A only, 2 = RULE A or RULE B
    div_fresh_bars: int = 1  # RULE A: fired within this many bars (1 = last)
    signal_fresh_bars: int = 1  # RULE B: fired within this many bars
    min_signal_score: int = 2  # RULE B: |score| >= this
    div_directions: Tuple[str, ...] = ("bull", "bear")
    signal_directions: Tuple[str, ...] = ("bull", "bear")
    min_bars: int = 60  # refuse to screen a frame shorter than this
    warn_bars: int = 260  # below this the 200 MA is a proxy or absent

    # ---- numerical conventions (see KNOWN LIMITS in the write-up) ----------
    ema_seed: str = "sma"  # "sma" = Pine's seeding, "first" = ewm(adjust=False)
    rma_seed: str = "sma"  # Wilder's own seeding; Pine uses SMA
    pivot_strict_left: bool = True  # a tie on the left disqualifies the pivot
    pivot_strict_right: bool = True  # a tie on the right disqualifies it

    def validate(self) -> "ScreenConfig":
        """Fail loudly on a configuration that cannot mean anything."""
        if self.mode not in (1, 2):
            raise ValueError("mode must be 1 or 2, got %r" % (self.mode,))
        for name in ("rsi_len", "piv_left", "piv_right", "fast_len", "mid_len",
                     "slow_len", "macd_fast", "macd_slow", "macd_signal",
                     "atr_len", "rsi_ma_len"):
            if int(getattr(self, name)) < 1:
                raise ValueError("%s must be >= 1" % name)
        if self.range_lower > self.range_upper:
            raise ValueError("range_lower must be <= range_upper")
        for name in ("rsi_source", "ma_source", "macd_source"):
            val = getattr(self, name)
            if val not in OHLC_COLUMNS:
                # The call sites fall back to `close` for an unknown name, so
                # a typo ("hlc3", "Close", "adj_close") used to compute a
                # different indicator than the config claimed, silently.
                raise ValueError(
                    "%s must be one of %s, got %r"
                    % (name, ", ".join(OHLC_COLUMNS), val))
        if self.ma_type not in ("EMA", "SMA"):
            raise ValueError("ma_type must be EMA or SMA")
        if self.rsi_ma_type not in ("EMA", "SMA"):
            raise ValueError("rsi_ma_type must be EMA or SMA")
        if self.ema_seed not in ("sma", "first"):
            raise ValueError("ema_seed must be 'sma' or 'first'")
        if self.rma_seed not in ("sma", "first"):
            raise ValueError("rma_seed must be 'sma' or 'first'")
        if self.div_fresh_bars < 1 or self.signal_fresh_bars < 1:
            raise ValueError("freshness windows are counted in bars and are >= 1")
        return self

    @property
    def max_score(self) -> int:
        """maxScore = 1 + (useMacd ? 1 : 0) + (useSlow ? 1 : 0) + (useRsi ? 1 : 0)

        Final_Top_Script.pine, the `maxScore` line above the key table.
        With the shipped defaults this is 3, NOT 4.
        """
        return 1 + int(self.use_macd) + int(self.use_slow) + int(self.use_rsi)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def replace(self, **kw: Any) -> "ScreenConfig":
        return replace(self, **kw).validate()


DEFAULT_CONFIG = ScreenConfig().validate()


# =============================================================================
# small helpers
# =============================================================================


def _vals(x: Any) -> np.ndarray:
    """Float64 numpy view of a Series / array / list, never a copy-on-write trap."""
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype="float64", copy=True)
    return np.asarray(x, dtype="float64").copy()


def _index_of(x: Any, n: int) -> pd.Index:
    if isinstance(x, (pd.Series, pd.DataFrame)):
        return x.index
    return pd.RangeIndex(n)


def _out(values: np.ndarray, like: Any, name: str) -> pd.Series:
    return pd.Series(values, index=_index_of(like, values.size), name=name, dtype="float64")


def _bool_out(values: np.ndarray, like: Any, name: str) -> pd.Series:
    return pd.Series(np.asarray(values, dtype=bool),
                     index=_index_of(like, np.asarray(values).size), name=name)


def _nan_safe(op: np.ndarray) -> np.ndarray:
    """A numpy comparison result with NaN operands already resolves to False,
    which is exactly Pine's behaviour (`na > x` is falsy in a condition).
    This function only documents that fact for the reader."""
    return np.asarray(op, dtype=bool)


def _first_valid(v: np.ndarray) -> int:
    """Index of the first non-NaN element, or -1."""
    ok = np.flatnonzero(~np.isnan(v))
    return int(ok[0]) if ok.size else -1


def _recursive_ma(v: np.ndarray, period: int, alpha: float, seed: str) -> np.ndarray:
    """Shared engine for ta.ema / ta.rma.

    Pine seeds both with the SMA of the first `period` values of the source,
    counting from the source's first non-na bar, and returns na before that.
    `seed="first"` reproduces pandas' ewm(adjust=False) instead: seed on the
    first value, no warm-up NaNs. See KNOWN LIMITS.

    An interior NaN (a bar with no price) poisons everything after it, which
    is why prepare_frame() drops such bars before anything is computed.
    """
    n = v.size
    out = np.full(n, np.nan, dtype="float64")
    if period < 1 or n == 0:
        return out
    f = _first_valid(v)
    if f < 0:
        return out
    if seed == "first":
        start = f
        prev = v[f]
        out[f] = prev
    else:
        if n - f < period:
            return out
        start = f + period - 1
        window = v[f:f + period]
        if np.isnan(window).any():
            # A NaN inside the seed window: walk forward to the first clean one.
            for s in range(f, n - period + 1):
                w = v[s:s + period]
                if not np.isnan(w).any():
                    start = s + period - 1
                    window = w
                    break
            else:
                return out
        prev = float(window.mean())
        out[start] = prev
    for i in range(start + 1, n):
        x = v[i]
        if np.isnan(x):
            prev = np.nan
            out[i] = np.nan
            continue
        if np.isnan(prev):
            prev = x
            out[i] = x
            continue
        prev = alpha * x + (1.0 - alpha) * prev
        out[i] = prev
    return out


# =============================================================================
# indicators
# =============================================================================


def wilder_rma(series: Any, period: int, seed: Optional[str] = None) -> pd.Series:
    """Pine `ta.rma(source, length)`.

    Wilder's smoothing: alpha = 1 / length, seeded with the SMA of the first
    `length` values of the source (Pine's documented behaviour), na before.
    Used by ta.rsi and ta.atr, which is why it has to be exact rather than
    "an EMA with a different alpha".
    """
    seed = seed or DEFAULT_CONFIG.rma_seed
    v = _vals(series)
    return _out(_recursive_ma(v, int(period), 1.0 / float(period), seed), series, "rma%d" % period)


def sma_pine(series: Any, period: int) -> pd.Series:
    """Pine `ta.sma(source, length)`. NaN until `length` values exist."""
    s = series if isinstance(series, pd.Series) else pd.Series(_vals(series))
    return s.rolling(int(period), min_periods=int(period)).mean().rename("sma%d" % period)


def ema_pine(series: Any, span: int, seed: Optional[str] = None) -> pd.Series:
    """Pine `ta.ema(source, length)`.

    alpha = 2 / (length + 1), recursive, seeded with the SMA of the first
    `length` values (TradingView emits na for the first length-1 bars).

    `seed="first"` is pandas' `ewm(span=span, adjust=False).mean()` with no
    warm-up NaNs; it is offered because the task named it, and because after
    roughly 5x span bars the two are identical to within 1e-9. Use "sma" for
    anything that has to agree with a chart bar-for-bar near the left edge.
    """
    seed = seed or DEFAULT_CONFIG.ema_seed
    v = _vals(series)
    span = int(span)
    return _out(_recursive_ma(v, span, 2.0 / (span + 1.0), seed), series, "ema%d" % span)


def ma_pine(series: Any, length: int, ma_type: str = "EMA",
            seed: Optional[str] = None) -> pd.Series:
    """Final_Top_Script.pine `f_ma(s, len)` -- EMA or SMA by the `maType` input.

    The Pine computes BOTH every bar and picks one, so that the ta.* history
    stays consistent when the input is switched. Here the choice is pure, so
    only the selected one is computed.
    """
    return ema_pine(series, length, seed) if ma_type == "EMA" else sma_pine(series, length)


def rsi_wilder(close: Any, period: int = 14, seed: Optional[str] = None) -> pd.Series:
    """Pine `ta.rsi(source, length)`.

    Pine's definition, verbatim:
        u   = math.max(ta.change(src), 0)
        d   = math.max(-ta.change(src), 0)
        rs  = ta.rma(u, len) / ta.rma(d, len)
        res = 100 - 100 / (1 + rs)
    Three boundary cases, and the third one is the corrected one:
        rma(d) == 0, rma(u)  > 0 -> rs = +inf -> 100   (only gains)
        rma(u) == 0, rma(d)  > 0 -> rs = 0    ->   0   (only losses)
        rma(u) == 0 AND rma(d) == 0 -> rs = 0/0 = NaN -> NaN

    THE THIRD CASE USED TO RETURN 100 AND THAT WAS WRONG. Pine's ta.rsi is
    one division, not a chain of branches -- there is no "zero-denominator
    branch tested first" to inherit an answer from. A perfectly flat series
    makes BOTH Wilder averages exactly zero, 0/0 is NaN under IEEE, and na
    is what the formula yields. Returning 100 published "maximally
    overbought" for a stock that had not moved a tick, which reached the
    reviewer as `rsi: 100.0, rsi_zone: extreme-overbought` on every halted
    or never-traded name in the universe.

    It can only ever REMOVE a claim, never add one: both averages are zero
    only while the series has been flat since its first bar, which has no
    pivots and no crosses, so no RULE A or RULE B verdict moves. If a chart
    comparison ever shows TradingView printing 100 there, this is the one
    line to flip back.
    """
    v = _vals(close)
    period = int(period)
    change = np.full(v.size, np.nan, dtype="float64")
    if v.size > 1:
        change[1:] = v[1:] - v[:-1]
    up = np.where(np.isnan(change), np.nan, np.maximum(change, 0.0))
    dn = np.where(np.isnan(change), np.nan, np.maximum(-change, 0.0))
    ru = _recursive_ma(up, period, 1.0 / period, seed or DEFAULT_CONFIG.rma_seed)
    rd = _recursive_ma(dn, period, 1.0 / period, seed or DEFAULT_CONFIG.rma_seed)
    out = np.full(v.size, np.nan, dtype="float64")
    live = ~np.isnan(ru) & ~np.isnan(rd)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(live & (rd != 0.0), ru / np.where(rd == 0.0, np.nan, rd), np.nan)
        generic = 100.0 - 100.0 / (1.0 + rs)
    both_zero = live & (rd == 0.0) & (ru == 0.0)   # 0 / 0 -> NaN, see above
    out = np.where(both_zero, np.nan,
                   np.where(live & (rd == 0.0), 100.0,
                            np.where(live & (ru == 0.0), 0.0,
                                     np.where(live, generic, np.nan))))
    return _out(out, close, "rsi%d" % period)


def macd_pine(close: Any, fast: int = 12, slow: int = 26, signal: int = 9,
              seed: Optional[str] = None) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Pine `[macdLine, signalLine, histLine] = ta.macd(src, fast, slow, sig)`.

    Returned in Pine's order: (macd, signal, hist). hist = macd - signal.
    Both panes of the template use 12 / 26 / 9 on close, and the Top script's
    score reads `macdHist` from exactly this call.
    """
    macd = ema_pine(close, fast, seed) - ema_pine(close, slow, seed)
    macd = macd.rename("macd")
    sig = ema_pine(macd, signal, seed).rename("macd_signal")
    hist = (macd - sig).rename("macd_hist")
    return macd, sig, hist


def true_range(df: pd.DataFrame) -> pd.Series:
    """Pine `ta.tr(true)`.

    max(high - low, |high - close[1]|, |low - close[1]|), and on the first bar
    (where close[1] is na) simply high - low, which is what the `true`
    argument means.
    """
    h = _vals(df["high"])
    l = _vals(df["low"])
    c = _vals(df["close"])
    prev = np.full(c.size, np.nan, dtype="float64")
    if c.size > 1:
        prev[1:] = c[:-1]
    hl = h - l
    with np.errstate(invalid="ignore"):
        a = np.abs(h - prev)
        b = np.abs(l - prev)
    tr = np.where(np.isnan(prev), hl, np.maximum(hl, np.maximum(a, b)))
    return _out(tr, df, "tr")


def atr_wilder(df: pd.DataFrame, period: int = 14, seed: Optional[str] = None) -> pd.Series:
    """Pine `ta.atr(length)` = ta.rma(ta.tr(true), length)."""
    return wilder_rma(true_range(df), period, seed).rename("atr%d" % period)


# =============================================================================
# Pine control-flow primitives
# =============================================================================


def crossover(a: Any, b: Any) -> pd.Series:
    """Pine `ta.crossover(a, b)`: a[1] <= b[1] and a > b.

    A NaN on either side of either comparison makes the result False, which is
    what Pine does with na in a boolean context. That is load-bearing for the
    200 MA on a short history: no cross is reported while it is still na.
    """
    av, bv = _vals(a), _vals(b)
    n = av.size
    out = np.zeros(n, dtype=bool)
    if n < 2:
        return _bool_out(out, a, "crossover")
    now = _nan_safe(av[1:] > bv[1:])
    was = _nan_safe(av[:-1] <= bv[:-1])
    out[1:] = now & was
    return _bool_out(out, a, "crossover")


def crossunder(a: Any, b: Any) -> pd.Series:
    """Pine `ta.crossunder(a, b)`: a[1] >= b[1] and a < b."""
    av, bv = _vals(a), _vals(b)
    n = av.size
    out = np.zeros(n, dtype=bool)
    if n < 2:
        return _bool_out(out, a, "crossunder")
    now = _nan_safe(av[1:] < bv[1:])
    was = _nan_safe(av[:-1] >= bv[:-1])
    out[1:] = now & was
    return _bool_out(out, a, "crossunder")


def cross(a: Any, b: Any) -> pd.Series:
    """Pine `ta.cross(a, b)` = crossover or crossunder."""
    return (crossover(a, b) | crossunder(a, b)).rename("cross")


def _pivot(series: Any, left: int, right: int, low: bool,
           strict_left: bool, strict_right: bool) -> pd.Series:
    v = _vals(series)
    n = v.size
    out = np.full(n, np.nan, dtype="float64")
    left, right = int(left), int(right)
    width = left + right + 1
    if left < 1 or right < 1 or n < width:
        return _out(out, series, "pivot")
    win = np.lib.stride_tricks.sliding_window_view(v, width)  # (n - width + 1, width)
    centre = win[:, left]
    lw = win[:, :left]
    rw = win[:, left + 1:]
    with np.errstate(invalid="ignore"):
        if low:
            ok_l = np.all(centre[:, None] < lw if strict_left else centre[:, None] <= lw, axis=1)
            ok_r = np.all(centre[:, None] < rw if strict_right else centre[:, None] <= rw, axis=1)
        else:
            ok_l = np.all(centre[:, None] > lw if strict_left else centre[:, None] >= lw, axis=1)
            ok_r = np.all(centre[:, None] > rw if strict_right else centre[:, None] >= rw, axis=1)
    ok = ok_l & ok_r & ~np.isnan(centre)
    centres = np.arange(left, n - right)
    confirm = centres + right
    out[confirm[ok]] = centre[ok]
    return _out(out, series, "pivotlow" if low else "pivothigh")


def pivot_low_confirmed(series: Any, left: int = 5, right: int = 5,
                        strict_left: bool = True, strict_right: bool = True) -> pd.Series:
    """Pine `ta.pivotlow(source, leftbars, rightbars)`.

    On bar i the result is the value of `source[i - right]` when that bar was
    a pivot low, and NaN otherwise. The timing is the whole point: the pivot
    is only KNOWN `right` bars after it happened, which is why the RSI+ pane
    draws its divergence marks with `offset = -lbR`, and why this screen fires
    on the confirmation bar rather than the pivot bar.

    A NaN anywhere in the left+right+1 window rejects the pivot (the numpy
    comparisons resolve to False), matching Pine's na handling.

    Ties: with `strict_*` True the centre must be a UNIQUE extreme of the
    window, so a flat stretch produces no pivots at all. See KNOWN LIMITS --
    this is the one place where TradingView's exact tie convention could not
    be verified without a chart, and relaxing either flag can only ever ADD
    pivots (i.e. add candidates), never remove one.
    """
    return _pivot(series, left, right, True, strict_left, strict_right)


def pivot_high_confirmed(series: Any, left: int = 5, right: int = 5,
                         strict_left: bool = True, strict_right: bool = True) -> pd.Series:
    """Pine `ta.pivothigh(source, leftbars, rightbars)`. Mirror of the above."""
    return _pivot(series, left, right, False, strict_left, strict_right)


def valuewhen(condition: Any, source: Any, occurrence: int = 0) -> pd.Series:
    """Pine `ta.valuewhen(condition, source, occurrence)`.

    On bar i: the value of `source` on the bar of the (occurrence+1)-th most
    recent bar at or before i where `condition` was true. occurrence = 0 is
    the most recent, 1 the one before that. NaN when there have not been
    enough occurrences yet -- Pine returns na, and every comparison against it
    is then false, which is how the first pivot of a symbol's history is
    prevented from claiming a divergence against nothing.
    """
    c = np.asarray(condition, dtype=bool)
    s = _vals(source)
    n = c.size
    out = np.full(n, np.nan, dtype="float64")
    occ = np.flatnonzero(c)
    if occ.size == 0:
        return _out(out, source, "valuewhen")
    bars = np.arange(n)
    seen = np.searchsorted(occ, bars, side="right")  # occurrences at bars <= i
    j = seen - 1 - int(occurrence)
    ok = j >= 0
    out[ok] = s[occ[j[ok]]]
    return _out(out, source, "valuewhen")


def barssince(condition: Any) -> pd.Series:
    """Pine `ta.barssince(condition)`.

    Number of bars since `condition` was last true, 0 on a bar where it is
    true, NaN until it has ever been true (Pine returns na, and `na <= 60` is
    false, so an in-range test correctly refuses to fire on the first pivot).
    """
    c = np.asarray(condition, dtype=bool)
    n = c.size
    bars = np.arange(n)
    last = np.where(c, bars, -1)
    last = np.maximum.accumulate(last) if n else last
    out = np.where(last >= 0, (bars - last).astype("float64"), np.nan)
    return _out(out, condition, "barssince")


def shift_bool(condition: Any, by: int = 1) -> np.ndarray:
    """Pine `condition[by]`: the bool series moved `by` bars forward, with the
    leading bars false (Pine's na in a boolean context)."""
    c = np.asarray(condition, dtype=bool)
    out = np.zeros(c.size, dtype=bool)
    if by < c.size:
        out[by:] = c[:c.size - by]
    return out


# =============================================================================
# frame hygiene
# =============================================================================


def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise an OHLCV frame: lower-case columns, float dtypes, drop bars
    with no price.

    Dropping is deliberate and is the only place a bar disappears. An interior
    NaN close would poison every recursive average after it (Pine has no such
    bar at all -- a halted session simply is not a bar), so a NaN row is
    removed rather than filled. Removing a row does not create look-ahead:
    the remaining bars keep their order and each still only sees its own past.

    Raises ValueError only for a frame that cannot be interpreted at all.
    """
    if not isinstance(df, pd.DataFrame):
        raise ValueError("expected a DataFrame of OHLC bars")
    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    missing = [c for c in OHLC_COLUMNS if c not in out.columns]
    if "open" in missing and "close" in out.columns:
        out["open"] = out["close"]
        missing = [c for c in missing if c != "open"]
    if missing:
        raise ValueError("frame is missing column(s): %s" % ", ".join(missing))
    # A frame handed in NEWEST-FIRST is the one bad input that produces a
    # complete, plausible, entirely meaningless row: every recursive average
    # runs backwards, `last_bar` reports the OLDEST date, and nothing in the
    # output says so. Some providers and most hand-saved CSVs are descending.
    # Cheap to detect, so it is refused rather than screened. An index that is
    # both increasing and decreasing is constant (all bars share a timestamp),
    # which is a duplicate-index frame and is fine.
    if len(out.index) > 1:
        try:
            backwards = bool(out.index.is_monotonic_decreasing) and not bool(
                out.index.is_monotonic_increasing)
        except (TypeError, ValueError):
            backwards = False
        if backwards:
            raise ValueError(
                "bars are in DESCENDING order (index runs newest-first); "
                "this module reads a frame oldest-first -- sort it ascending")
    keep = list(OHLC_COLUMNS) + (["volume"] if "volume" in out.columns else [])
    out = out.loc[:, keep]
    for c in keep:
        out[c] = pd.to_numeric(out[c], errors="coerce").astype("float64")
    out = out[~out[list(OHLC_COLUMNS)].isna().any(axis=1)]
    return out


# =============================================================================
# RULE A -- regular RSI divergence (Final_RSI_Plus.pine)
# =============================================================================


def rsi_divergence(df: pd.DataFrame, cfg: Optional[ScreenConfig] = None) -> pd.DataFrame:
    """Final_RSI_Plus.pine, the divergence block, line for line.

        plFound = not na(ta.pivotlow(rsi, lbL, lbR))
        phFound = not na(ta.pivothigh(rsi, lbL, lbR))
        f_inRange(cond) =>
            bars = ta.barssince(cond == true)
            rangeLower <= bars and bars <= rangeUpper
        inRangeL = f_inRange(plFound[1])
        inRangeH = f_inRange(phFound[1])
        rsiHL   = rsi[lbR] > ta.valuewhen(plFound, rsi[lbR], 1)
        priceLL = low[lbR]  < ta.valuewhen(plFound, low[lbR], 1)
        bullDiv = showDiv and plFound and priceLL and rsiHL and inRangeL
        rsiLH   = rsi[lbR] < ta.valuewhen(phFound, rsi[lbR], 1)
        priceHH = high[lbR] > ta.valuewhen(phFound, high[lbR], 1)
        bearDiv = showDiv and phFound and priceHH and rsiLH and inRangeH

    Two facts that are easy to get wrong and that the tests pin:

    1. THE PIVOTS ARE ON THE RSI, NOT ON PRICE. The price leg compares the
       low (high) of the bar on which the RSI pivoted against the low (high)
       of the bar on which the RSI previously pivoted. It is not a price
       pivot and there is no price-pivot confirmation involved.

    2. `f_inRange` is called with `plFound[1]`, not `plFound`. On a bar i
       where plFound is true, ta.barssince(plFound[1]) is
       (i - previous_plFound_bar - 1). So `5 <= bars <= 60` admits a gap of
       6 to 61 bars inclusive between the two CONFIRMATION bars, which is
       also the gap between the two pivot bars. The naive reading (5..60)
       is off by one at both ends. This is inherited verbatim from
       TradingView's own built-in Divergence Indicator.

    Returns a DataFrame indexed like `df` with the boolean verdicts on the
    CONFIRMATION bar plus every intermediate value a reviewer would want.
    """
    cfg = (cfg or DEFAULT_CONFIG)
    d = df
    n = len(d)
    idx = d.index
    src = d[cfg.rsi_source] if cfg.rsi_source in d.columns else d["close"]
    rsi = rsi_wilder(src, cfg.rsi_len)
    pl = pivot_low_confirmed(rsi, cfg.piv_left, cfg.piv_right,
                             cfg.pivot_strict_left, cfg.pivot_strict_right)
    ph = pivot_high_confirmed(rsi, cfg.piv_left, cfg.piv_right,
                              cfg.pivot_strict_left, cfg.pivot_strict_right)
    pl_found = pl.notna().to_numpy()
    ph_found = ph.notna().to_numpy()

    r = cfg.piv_right
    rsi_at = rsi.shift(r)          # rsi[lbR]
    low_at = d["low"].shift(r)     # low[lbR]
    high_at = d["high"].shift(r)   # high[lbR]

    prev_rsi_l = valuewhen(pl_found, rsi_at, 1)
    prev_low = valuewhen(pl_found, low_at, 1)
    prev_rsi_h = valuewhen(ph_found, rsi_at, 1)
    prev_high = valuewhen(ph_found, high_at, 1)

    rsi_hl = _nan_safe(rsi_at.to_numpy() > prev_rsi_l.to_numpy())
    price_ll = _nan_safe(low_at.to_numpy() < prev_low.to_numpy())
    rsi_lh = _nan_safe(rsi_at.to_numpy() < prev_rsi_h.to_numpy())
    price_hh = _nan_safe(high_at.to_numpy() > prev_high.to_numpy())

    bars_l = barssince(shift_bool(pl_found)).to_numpy()
    bars_h = barssince(shift_bool(ph_found)).to_numpy()
    in_range_l = _nan_safe((bars_l >= cfg.range_lower) & (bars_l <= cfg.range_upper))
    in_range_h = _nan_safe((bars_h >= cfg.range_lower) & (bars_h <= cfg.range_upper))

    on = bool(cfg.show_div)
    bull = pl_found & price_ll & rsi_hl & in_range_l & on
    bear = ph_found & price_hh & rsi_lh & in_range_h & on

    return pd.DataFrame(
        {
            "rsi": rsi.to_numpy(),
            "rsi_ma": ma_pine(rsi, cfg.rsi_ma_len, cfg.rsi_ma_type).to_numpy(),
            "rsi_long_avg": sma_pine(rsi, cfg.rsi_long_avg_len).to_numpy(),
            "pl_found": pl_found,
            "ph_found": ph_found,
            "rsi_at_pivot": rsi_at.to_numpy(),
            "low_at_pivot": low_at.to_numpy(),
            "high_at_pivot": high_at.to_numpy(),
            "prev_rsi_at_low_pivot": prev_rsi_l.to_numpy(),
            "prev_low_at_pivot": prev_low.to_numpy(),
            "prev_rsi_at_high_pivot": prev_rsi_h.to_numpy(),
            "prev_high_at_pivot": prev_high.to_numpy(),
            "bars_since_prev_low_pivot": bars_l,
            "bars_since_prev_high_pivot": bars_h,
            "rsi_hl": rsi_hl,
            "price_ll": price_ll,
            "rsi_lh": rsi_lh,
            "price_hh": price_hh,
            "in_range_low": in_range_l,
            "in_range_high": in_range_h,
            "bull_div": bull,
            "bear_div": bear,
        },
        index=idx,
    )


# =============================================================================
# RULE B -- the scored Fast x Mid cross (Final_Top_Script.pine)
# =============================================================================


def cross_signal(df: pd.DataFrame, cfg: Optional[ScreenConfig] = None) -> pd.DataFrame:
    """Final_Top_Script.pine, the signal block:

        maFast = f_ma(maSrc, fastLen)          // EMA 20 by default
        maMid  = f_ma(maSrc, midLen)           // EMA 50
        maSlow = f_ma(maSrc, slowLen)          // EMA 200
        regime = maMid > maSlow
        bullX  = ta.crossover(maFast, maMid)
        bearX  = ta.crossunder(maFast, maMid)
        bullScore = 1 + (useMacd and macdHist > 0 ? 1 : 0)
                      + (useSlow and close > maSlow ? 1 : 0)
                      + (useRsi  and rsiV > 50 ? 1 : 0)
        bearScore = 1 + (useMacd and macdHist < 0 ? 1 : 0)
                      + (useSlow and close < maSlow ? 1 : 0)
                      + (useRsi  and rsiV < 50 ? 1 : 0)
        bullSig = showSig and bullX and bullScore >= minScore
        bearSig = showSig and bearX and bearScore >= minScore

    The score is computed on EVERY bar in the Pine too; only the cross bars
    ever read it. With the shipped defaults (useRsi off) the maximum is 3.

    On a history shorter than `slowLen` the 200 MA is na, so `close > maSlow`
    is false and the +1 is simply not awarded -- a young crypto listing can
    therefore never score above 2. That is Pine's behaviour, reproduced
    rather than patched, and the screen reports `slow_ready` so a reviewer
    can see it.
    """
    cfg = (cfg or DEFAULT_CONFIG)
    d = df
    src = d[cfg.ma_source] if cfg.ma_source in d.columns else d["close"]
    close = d["close"]

    fast = ma_pine(src, cfg.fast_len, cfg.ma_type)
    mid = ma_pine(src, cfg.mid_len, cfg.ma_type)
    slow = ma_pine(src, cfg.slow_len, cfg.ma_type)
    _macd, _sig, hist = macd_pine(
        d[cfg.macd_source] if cfg.macd_source in d.columns else close,
        cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    rsi = rsi_wilder(close, cfg.top_rsi_len)

    bull_x = crossover(fast, mid).to_numpy()
    bear_x = crossunder(fast, mid).to_numpy()

    h = hist.to_numpy()
    c = close.to_numpy()
    s = slow.to_numpy()
    rv = rsi.to_numpy()

    macd_up = _nan_safe(h > 0.0) if cfg.use_macd else np.zeros(len(d), dtype=bool)
    macd_dn = _nan_safe(h < 0.0) if cfg.use_macd else np.zeros(len(d), dtype=bool)
    slow_up = _nan_safe(c > s) if cfg.use_slow else np.zeros(len(d), dtype=bool)
    slow_dn = _nan_safe(c < s) if cfg.use_slow else np.zeros(len(d), dtype=bool)
    rsi_up = _nan_safe(rv > cfg.rsi_midline) if cfg.use_rsi else np.zeros(len(d), dtype=bool)
    rsi_dn = _nan_safe(rv < cfg.rsi_midline) if cfg.use_rsi else np.zeros(len(d), dtype=bool)

    bull_score = 1 + macd_up.astype(int) + slow_up.astype(int) + rsi_up.astype(int)
    bear_score = 1 + macd_dn.astype(int) + slow_dn.astype(int) + rsi_dn.astype(int)

    bull_sig = bull_x & (bull_score >= cfg.min_score)
    bear_sig = bear_x & (bear_score >= cfg.min_score)

    return pd.DataFrame(
        {
            "fast": fast.to_numpy(),
            "mid": mid.to_numpy(),
            "slow": slow.to_numpy(),
            "macd_hist": h,
            "top_rsi": rv,
            "regime_up": _nan_safe(mid.to_numpy() > s),
            "slow_ready": ~np.isnan(s),
            "bull_cross": bull_x,
            "bear_cross": bear_x,
            "bull_score": bull_score,
            "bear_score": bear_score,
            "bull_signal": bull_sig,
            "bear_signal": bear_sig,
            "macd_agrees_bull": macd_up,
            "macd_agrees_bear": macd_dn,
            "above_slow": slow_up,
            "below_slow": slow_dn,
        },
        index=d.index,
    )


# =============================================================================
# per-bar evaluation (the thing the look-ahead test compares)
# =============================================================================


def evaluate(df: pd.DataFrame, cfg: Optional[ScreenConfig] = None) -> pd.DataFrame:
    """Everything both rules need, one row per bar, causal by construction.

    This is the single source of truth: screen_symbol() only ever reads the
    tail of this frame, and assert_no_lookahead() compares it against itself
    computed on truncated inputs.
    """
    cfg = (cfg or DEFAULT_CONFIG)
    d = prepare_frame(df)
    if len(d) == 0:
        return pd.DataFrame(index=d.index)
    div = rsi_divergence(d, cfg)
    sig = cross_signal(d, cfg)
    atr = atr_wilder(d, cfg.atr_len)
    out = pd.concat([d, div, sig], axis=1)
    out["atr"] = atr.to_numpy()
    return out


# =============================================================================
# the screen
# =============================================================================


def _last_true(mask: np.ndarray, within: int) -> Optional[int]:
    """Index of the most recent True within the last `within` bars, else None.
    `within = 1` means the final bar only."""
    n = mask.size
    if n == 0 or within < 1:
        return None
    lo = max(0, n - int(within))
    tail = np.flatnonzero(mask[lo:])
    if tail.size == 0:
        return None
    return int(lo + tail[-1])


def _f(x: Any) -> Optional[float]:
    """Plain float or None -- keeps NaN out of the output dicts, because a
    NaN silently makes every downstream comparison False."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def screen_symbol(df: pd.DataFrame, cfg: Optional[ScreenConfig] = None,
                  symbol: str = "", market: str = "") -> Dict[str, Any]:
    """Screen one symbol as of its LAST bar. Never raises on bad data.

    The caller is responsible for handing in CLOSED bars only: on the ASX and
    NASDAQ that means dropping today's partial bar, and on crypto it means
    dropping the in-progress UTC day. A partial last bar is not an error this
    function can detect, and it is the single easiest way to manufacture a
    signal that evaporates overnight.

    Returns a flat dict. `ok=False` with a `reason` for anything unscreenable
    (too short, empty, unreadable), never an exception.
    """
    cfg = (cfg or DEFAULT_CONFIG)
    base: Dict[str, Any] = {
        "symbol": symbol, "market": market, "ok": False, "reason": "",
        "passes": False, "rules": "", "direction": "",
        "n_bars": 0, "last_bar": None,
        "rule_a": False, "rule_a_direction": "", "rule_a_bars_ago": None,
        "rule_a_label_bars_ago": None, "rule_a_pivot_bars_ago": None,
        "rule_b": False, "rule_b_direction": "", "rule_b_score": None,
        "rule_b_bars_ago": None,
        "score": None, "best_bars_ago": None,
        "close": None, "rsi": None, "rsi_ma": None, "atr": None, "atr_pct": None,
        "trend": "", "regime": "", "above_slow": None, "slow_ready": False,
        "macd_hist": None, "fast": None, "mid": None, "slow": None,
        "rsi_zone": "", "history_warning": "",
    }
    try:
        cfg = cfg.validate()
    except ValueError as exc:
        # A bad config is a programming error, but this function is called in
        # a 3,600-symbol loop; reporting it on the row beats a traceback that
        # kills the scan, and screen_frames() still validates once up front.
        base["reason"] = "invalid config: %s" % exc
        return base
    try:
        d = prepare_frame(df)
    except Exception as exc:  # noqa: BLE001 - a bad frame must not kill a scan
        base["reason"] = "unreadable frame: %s" % exc
        return base

    n = len(d)
    base["n_bars"] = int(n)
    if n == 0:
        base["reason"] = "no bars"
        return base
    base["last_bar"] = str(d.index[-1])
    if n < max(int(cfg.min_bars), cfg.piv_left + cfg.piv_right + 2):
        base["reason"] = "history too short (%d bars, need %d)" % (n, cfg.min_bars)
        return base

    try:
        ev = evaluate(d, cfg)
    except Exception as exc:  # noqa: BLE001
        base["reason"] = "evaluation failed: %s" % exc
        return base

    base["ok"] = True
    last = ev.iloc[-1]

    # ---- context a human reviewer wants on the row -------------------------
    base["close"] = _f(last["close"])
    base["rsi"] = _f(last["rsi"])
    base["rsi_ma"] = _f(last["rsi_ma"])
    base["atr"] = _f(last["atr"])
    if base["atr"] is not None and base["close"]:
        base["atr_pct"] = round(100.0 * base["atr"] / base["close"], 2)
    base["fast"] = _f(last["fast"])
    base["mid"] = _f(last["mid"])
    base["slow"] = _f(last["slow"])
    base["macd_hist"] = _f(last["macd_hist"])
    base["slow_ready"] = bool(last["slow_ready"])
    base["above_slow"] = bool(last["above_slow"]) if base["slow_ready"] else None
    base["trend"] = ("up" if bool(last["regime_up"]) else "down") if base["slow_ready"] else "unknown"
    f_, m_, s_ = base["fast"], base["mid"], base["slow"]
    if None not in (f_, m_, s_):
        if f_ > m_ > s_:
            base["regime"] = "fast>mid>slow"
        elif f_ < m_ < s_:
            base["regime"] = "fast<mid<slow"
        else:
            base["regime"] = "mixed"
    elif None not in (f_, m_):
        base["regime"] = "fast>mid" if f_ > m_ else "fast<mid"
    r = base["rsi"]
    if r is not None:
        if r >= cfg.rsi_ob2:
            base["rsi_zone"] = "extreme-overbought"
        elif r >= cfg.rsi_ob1:
            base["rsi_zone"] = "overbought"
        elif r <= cfg.rsi_os2:
            base["rsi_zone"] = "extreme-oversold"
        elif r <= cfg.rsi_os1:
            base["rsi_zone"] = "oversold"
        else:
            base["rsi_zone"] = "neutral"
    if n < cfg.warn_bars:
        base["history_warning"] = (
            "only %d bars: the %d MA is %s"
            % (n, cfg.slow_len, "absent" if not base["slow_ready"] else "barely seeded")
        )

    # ---- RULE A ------------------------------------------------------------
    bull_div = ev["bull_div"].to_numpy()
    bear_div = ev["bear_div"].to_numpy()
    if "bull" not in cfg.div_directions:
        bull_div = np.zeros(n, dtype=bool)
    if "bear" not in cfg.div_directions:
        bear_div = np.zeros(n, dtype=bool)
    i_bull = _last_true(bull_div, cfg.div_fresh_bars)
    i_bear = _last_true(bear_div, cfg.div_fresh_bars)
    i_a = max([x for x in (i_bull, i_bear) if x is not None], default=None)
    if i_a is not None:
        both = i_bull is not None and i_bear is not None and i_bull == i_bear
        d_a = "both" if both else ("bull" if i_a == i_bull else "bear")
        row = ev.iloc[i_a]
        base["rule_a"] = True
        base["rule_a_direction"] = d_a
        base["rule_a_bars_ago"] = int(n - 1 - i_a)
        base["rule_a_label_bars_ago"] = int(n - 1 - i_a + cfg.piv_right)
        base["rule_a_pivot_bars_ago"] = int(n - 1 - i_a + cfg.piv_right)
        base["rule_a_pivot_bar"] = str(ev.index[max(0, i_a - cfg.piv_right)])
        base["rule_a_rsi_at_pivot"] = _f(row["rsi_at_pivot"])
        if d_a in ("bull", "both"):
            base["rule_a_prev_rsi"] = _f(row["prev_rsi_at_low_pivot"])
            base["rule_a_price_at_pivot"] = _f(row["low_at_pivot"])
            base["rule_a_prev_price"] = _f(row["prev_low_at_pivot"])
            base["rule_a_bars_between_pivots"] = _f(row["bars_since_prev_low_pivot"])
        else:
            base["rule_a_prev_rsi"] = _f(row["prev_rsi_at_high_pivot"])
            base["rule_a_price_at_pivot"] = _f(row["high_at_pivot"])
            base["rule_a_prev_price"] = _f(row["prev_high_at_pivot"])
            base["rule_a_bars_between_pivots"] = _f(row["bars_since_prev_high_pivot"])

    # ---- RULE B ------------------------------------------------------------
    bull_sig = ev["bull_signal"].to_numpy() & (ev["bull_score"].to_numpy() >= cfg.min_signal_score)
    bear_sig = ev["bear_signal"].to_numpy() & (ev["bear_score"].to_numpy() >= cfg.min_signal_score)
    if "bull" not in cfg.signal_directions:
        bull_sig = np.zeros(n, dtype=bool)
    if "bear" not in cfg.signal_directions:
        bear_sig = np.zeros(n, dtype=bool)
    j_bull = _last_true(bull_sig, cfg.signal_fresh_bars)
    j_bear = _last_true(bear_sig, cfg.signal_fresh_bars)
    j_b = max([x for x in (j_bull, j_bear) if x is not None], default=None)
    if j_b is not None:
        d_b = "bull" if j_b == j_bull else "bear"
        row = ev.iloc[j_b]
        score = int(row["bull_score"] if d_b == "bull" else row["bear_score"])
        base["rule_b"] = True
        base["rule_b_direction"] = d_b
        base["rule_b_score"] = score
        base["rule_b_signed_score"] = score if d_b == "bull" else -score
        base["rule_b_label"] = ("Bullish +%d" % score) if d_b == "bull" else ("-%d Bearish" % score)
        base["rule_b_bars_ago"] = int(n - 1 - j_b)
        base["rule_b_bar"] = str(ev.index[j_b])
        base["rule_b_close"] = _f(row["close"])
        base["rule_b_macd_hist"] = _f(row["macd_hist"])
        base["rule_b_above_slow"] = bool(row["above_slow"])
        base["rule_b_below_slow"] = bool(row["below_slow"])
        base["rule_b_max_score"] = cfg.max_score
        base["score"] = score

    # ---- verdict -----------------------------------------------------------
    rules: List[str] = []
    if base["rule_a"]:
        rules.append("A")
    if base["rule_b"]:
        rules.append("B")
    base["rules"] = "+".join(rules)
    base["passes"] = bool(base["rule_a"]) if cfg.mode == 1 else bool(base["rule_a"] or base["rule_b"])
    if cfg.mode == 1:
        base["rules"] = "A" if base["rule_a"] else ""
        base["rule_b"] = base["rule_b"]  # reported, not used
    # `direction` has to honour `mode` exactly as `rules`, `passes` and
    # `best_bars_ago` above it already do. In mode 1 RULE B is REPORTED and
    # not used, so it must not be able to turn a clean bull divergence into
    # `conflict`, nor give a non-passing row a direction at all.
    dirs = {base["rule_a_direction"]}
    if cfg.mode == 2:
        dirs.add(base["rule_b_direction"])
    dirs -= {""}
    if "both" in dirs or dirs == {"bull", "bear"}:
        base["direction"] = "conflict"
    elif dirs:
        base["direction"] = dirs.pop()
    ages = [a for a in (base["rule_a_bars_ago"],
                        base["rule_b_bars_ago"] if cfg.mode == 2 else None) if a is not None]
    base["best_bars_ago"] = min(ages) if ages else None
    return base


def screen_frames(frames: Mapping[str, pd.DataFrame], cfg: Optional[ScreenConfig] = None,
                  market: str = "", include_failures: bool = False) -> pd.DataFrame:
    """Screen a whole universe. Returns one row per symbol, ranked.

    Ranking is deliberately NOT a quality model -- there is no evidence here
    that a score of 3 outperforms a 2, and sorting a scanner by its own
    backtest is how a page becomes a curve fit. The order is only "what a
    reviewer should look at first", and every tier is a stated preference
    rather than a measured one:

        1. passing rows before non-passing
        2. freshest first (bars_ago ascending)
        3. both rules before one rule
        4. RULE A before a RULE-B-only row -- the divergence is the owner's
           headline rule, the one mode 1 screens on by itself
        5. higher |score| first
        6. symbol, so the output is deterministic

    `include_failures=False` (the default) returns only the passing rows.
    """
    cfg = (cfg or DEFAULT_CONFIG).validate()
    rows: List[Dict[str, Any]] = []
    for sym in sorted(frames):
        rows.append(screen_symbol(frames[sym], cfg, symbol=str(sym), market=market))
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    if not include_failures:
        out = out[out["passes"]]
        if out.empty:
            return out.reset_index(drop=True)
    out = out.assign(
        _age=pd.to_numeric(out["best_bars_ago"], errors="coerce").fillna(10 ** 6),
        _nrules=out["rules"].astype("object").fillna("").map(
            lambda s: -len(str(s).split("+")) if s else 0),
        _nota=(~out["rule_a"].astype(bool)).astype(int),
        _score=-pd.to_numeric(out["score"], errors="coerce").fillna(0),
    ).sort_values(
        by=["passes", "_age", "_nrules", "_nota", "_score", "symbol"],
        ascending=[False, True, True, True, True, True],
        kind="mergesort",
    ).drop(columns=["_age", "_nrules", "_nota", "_score"])
    return out.reset_index(drop=True)


# =============================================================================
# the causality proof
# =============================================================================

#: the columns whose value on bar i must not change when later bars arrive
CAUSAL_COLUMNS: Tuple[str, ...] = (
    # the verdicts
    "bull_div", "bear_div", "bull_signal", "bear_signal",
    # everything they are built from
    "rsi", "rsi_ma", "rsi_long_avg", "pl_found", "ph_found",
    "rsi_at_pivot", "low_at_pivot", "high_at_pivot",
    "prev_rsi_at_low_pivot", "prev_low_at_pivot",
    "prev_rsi_at_high_pivot", "prev_high_at_pivot",
    "bars_since_prev_low_pivot", "bars_since_prev_high_pivot",
    "rsi_hl", "price_ll", "rsi_lh", "price_hh",
    "in_range_low", "in_range_high",
    "fast", "mid", "slow", "macd_hist", "top_rsi", "regime_up", "slow_ready",
    "bull_cross", "bear_cross", "bull_score", "bear_score",
    "macd_agrees_bull", "macd_agrees_bear", "above_slow", "below_slow",
    "atr",
)


def assert_no_lookahead(df: pd.DataFrame, cfg: Optional[ScreenConfig] = None,
                        bars: Optional[Sequence[int]] = None,
                        tol: float = 1e-12) -> int:
    """Prove that no value on bar i depends on a bar after i.

    For each tested cut point i, recompute everything on df[:i+1] and compare
    the final row against row i of the full-history computation. Any
    disagreement raises AssertionError naming the column and the bar.

    This is the test that a divergence implementation most often fails: the
    tempting shortcut is to stamp the divergence on the PIVOT bar, which is
    only knowable `piv_right` bars later, and the resulting screen looks
    wonderful in a backtest and fires late in production.

    Returns the number of cut points checked.
    """
    cfg = (cfg or DEFAULT_CONFIG)
    d = prepare_frame(df)
    n = len(d)
    full = evaluate(d, cfg)
    if bars is None:
        lo = max(cfg.slow_len + 5, cfg.min_bars, 40)
        bars = [i for i in range(min(lo, n - 1), n)]
    checked = 0
    for i in bars:
        if i < 1 or i >= n:
            continue
        cut = evaluate(d.iloc[: i + 1], cfg)
        a = full.iloc[i]
        b = cut.iloc[-1]
        for col in CAUSAL_COLUMNS:
            if col not in full.columns:
                continue
            av, bv = a[col], b[col]
            if isinstance(av, (bool, np.bool_)) or isinstance(bv, (bool, np.bool_)):
                if bool(av) != bool(bv):
                    raise AssertionError(
                        "LOOK-AHEAD in %r at bar %d: full=%r truncated=%r" % (col, i, av, bv))
                continue
            af, bf = float(av), float(bv)
            if math.isnan(af) and math.isnan(bf):
                continue
            if math.isnan(af) != math.isnan(bf) or abs(af - bf) > tol:
                raise AssertionError(
                    "LOOK-AHEAD in %r at bar %d: full=%r truncated=%r" % (col, i, av, bv))
        checked += 1
    return checked
```

---

## 6.12 Full source: `vivek50_selftest.py`

```python
"""Self-test / demo for vivek50_screen.

Run it:   python3 vivek50_selftest.py
Or:       python3 -m pytest -q vivek50_selftest.py

Every frame is synthetic and deterministic -- no network, no yfinance, no
random seed. Each builder is shaped to force one specific behaviour, and the
expected bar indices are hardcoded so a silent off-by-one fails the run
instead of quietly moving.

Cases, in the order the task set them:
  (a) textbook bullish RSI divergence, fires exactly 5 bars after the pivot
  (b) the bearish mirror
  (c) a 20/50 cross with MACD hist > 0 and close above the 200 -> score 3
  (d) a 20/50 cross with MACD hist < 0 and close below the 200 -> score 1
  (e) a flat / halted series -> no pivots, no divergence, no crash
  (f) no look-ahead: truncate at bar i, the verdict at bar i is unchanged
  (g) a frame shorter than 200 bars -> no crash, sensible output
plus the Pine primitives (rma / rsi / ema / macd / atr warm-ups, the
crossover NaN rule, the pivot confirmation delay, and the barssince
off-by-one that sets the real 6..61 bar window between pivots).
"""

from __future__ import annotations

import math
import sys
from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

import vivek50_screen as V

# =============================================================================
# deterministic synthetic frame builders
# =============================================================================

WOBBLE_AMP = 0.4    # absolute price units of sine wobble
WOBBLE_PERIOD = 7   # bars per wobble cycle
SPREAD = 0.004      # intrabar range as a fraction, so high/low are not close


def frame_from_close(close: Sequence[float], spread: float = SPREAD) -> pd.DataFrame:
    """OHLCV from a close path: open = previous close, high/low straddle both."""
    c = np.asarray(close, dtype=float)
    n = c.size
    prev = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame(
        {
            "open": prev,
            "high": np.maximum(c, prev) * (1.0 + spread),
            "low": np.minimum(c, prev) * (1.0 - spread),
            "close": c,
            "volume": np.full(n, 1_000_000.0),
        },
        index=pd.bdate_range("2024-01-01", periods=n, name="date"),
    )


def seg(a: float, b: float, n: int) -> List[float]:
    """n bars walking linearly from a (exclusive) to b (inclusive)."""
    return list(np.linspace(a, b, n + 1)[1:])


def wobble(path: Sequence[float]) -> np.ndarray:
    c = np.asarray(path, dtype=float)
    return c + WOBBLE_AMP * np.sin(2.0 * np.pi * np.arange(c.size) / WOBBLE_PERIOD)


def bull_div_frame() -> pd.DataFrame:
    """Price makes a LOWER low while RSI makes a HIGHER low.

    60 bars of drift, a 15-bar crash to 80 (RSI floor), a 20-bar bounce to 95,
    then a 30-bar GRIND to 78 -- lower in price, but slow enough that RSI
    holds well above its crash reading -- then a 16-bar recovery so the second
    pivot can confirm. 141 bars; the divergence confirms on bar 129.
    """
    c = [100.0]
    c += seg(100, 101, 59)    # bars 1..59   warm-up drift
    c += seg(101, 80, 15)     # bars 60..74  crash  -> RSI trough 1 (deep)
    c += seg(80, 95, 20)      # bars 75..94  bounce
    c += seg(95, 78, 30)      # bars 95..124 grind  -> RSI trough 2 (shallow)
    c += seg(78, 88, 16)      # bars 125..140 recovery, confirms the pivot
    return frame_from_close(wobble(c))


def bear_div_frame() -> pd.DataFrame:
    """The mirror: price makes a HIGHER high while RSI makes a LOWER high.
    141 bars; the divergence confirms on bar 129."""
    c = [99.0]
    c += seg(99, 100, 59)
    c += seg(100, 125, 15)    # melt-up -> RSI peak 1 (extreme)
    c += seg(125, 109, 20)    # pullback
    c += seg(109, 128, 30)    # slow grind to a HIGHER high -> RSI peak 2 (lower)
    c += seg(128, 116, 16)
    return frame_from_close(wobble(c))


def score3_frame() -> pd.DataFrame:
    """A 20/50 bull cross inside a mature uptrend: MACD hist > 0 and close is
    far above the 200 EMA. 311 bars; the only bull cross is on bar 292."""
    c = [50.0]
    c += seg(50, 150, 260)    # 261 bars of uptrend, seeds the 200 EMA low
    c += seg(150, 132, 20)    # a dip deep enough to cross the 20 under the 50
    c += seg(132, 165, 30)    # the recovery that crosses it back over
    return frame_from_close(c)


def score1_frame() -> pd.DataFrame:
    """A 20/50 bull cross inside a downtrend: price is below the 200 EMA and
    the MACD histogram has ALREADY rolled back under zero by the time the
    slower 20/50 cross completes. 294 bars; the bull cross is the LAST bar."""
    c = [200.0]
    c += seg(200, 80, 260)            # 261 bars of downtrend
    base = c[-1]
    c += seg(base, base * 1.14, 15)   # a 14 % dead-cat bounce
    top = c[-1]
    c += seg(top, top * 0.99, 18)     # then a stall: hist rolls over, 20 keeps rising
    return frame_from_close(c)


def flat_frame(n: int = 300, price: float = 42.0) -> pd.DataFrame:
    """A halted name: every OHLC value identical on every bar."""
    return pd.DataFrame(
        {"open": np.full(n, price), "high": np.full(n, price),
         "low": np.full(n, price), "close": np.full(n, price),
         "volume": np.zeros(n)},
        index=pd.bdate_range("2024-01-01", periods=n, name="date"),
    )


def short_frame(n: int = 120) -> pd.DataFrame:
    """A young listing: real movement, but fewer bars than the 200 MA needs."""
    c = [10.0] + seg(10, 14, n - 1)
    return frame_from_close(wobble(c))


def gappy_frame() -> pd.DataFrame:
    """Holes in the data: NaN rows and a calendar gap. Must not raise."""
    f = bull_div_frame().copy()
    f.iloc[20:23, :] = np.nan            # three bars with no price at all
    f.iloc[45, f.columns.get_loc("close")] = np.nan
    return f.drop(f.index[60:64])        # a four-session hole in the calendar


# =============================================================================
# helpers
# =============================================================================

def true_bars(series: pd.Series) -> List[int]:
    return [int(i) for i in np.flatnonzero(np.asarray(series, dtype=bool))]


def banner(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


# =============================================================================
# primitives
# =============================================================================

def test_warmup_lengths_match_pine() -> None:
    """Pine emits na until a ta.* function has enough source bars. The first
    non-na bar index is a fingerprint of the seeding rule, so it is pinned."""
    f = frame_from_close([100.0] + seg(100, 130, 299))
    ev = V.evaluate(f)
    assert ev["rsi"].first_valid_index() == f.index[14], "ta.rsi(14) first value is bar 14"
    assert ev["slow"].first_valid_index() == f.index[199], "ta.ema(200) first value is bar 199"
    assert ev["macd_hist"].first_valid_index() == f.index[33], (
        "ta.macd hist: ema26 seeds at bar 25, ema9 of it needs 9 values -> bar 33")
    assert ev["atr"].first_valid_index() == f.index[13], "ta.atr(14) first value is bar 13"
    assert ev["fast"].first_valid_index() == f.index[19]
    assert ev["mid"].first_valid_index() == f.index[49]
    print("warm-ups: rsi14=14  ema20=19  ema50=49  ema200=199  macdhist=33  atr14=13")


def test_rma_is_wilder_not_an_ema() -> None:
    v = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    r = V.wilder_rma(v, 4)
    assert np.isnan(r.iloc[2])
    assert abs(r.iloc[3] - 2.5) < 1e-12, "seed is the SMA of the first 4 values"
    expect = 2.5 + (5.0 - 2.5) / 4.0
    assert abs(r.iloc[4] - expect) < 1e-12, "alpha = 1/length, not 2/(length+1)"
    e = V.ema_pine(v, 4)
    assert abs(e.iloc[3] - 2.5) < 1e-12
    assert abs(e.iloc[4] - (2.5 + 0.4 * (5.0 - 2.5))) < 1e-12, "ema alpha = 2/(n+1) = 0.4"
    print("rma alpha=1/4 seeded on SMA; ema alpha=0.4 seeded on SMA -- both confirmed")


def test_rsi_degenerate_cases() -> None:
    up = V.rsi_wilder(pd.Series(np.arange(1.0, 40.0)), 14)
    assert abs(up.iloc[-1] - 100.0) < 1e-9, "only gains -> rma(down)==0 -> 100"
    dn = V.rsi_wilder(pd.Series(np.arange(40.0, 1.0, -1.0)), 14)
    assert abs(dn.iloc[-1] - 0.0) < 1e-9, "only losses -> rma(up)==0 -> 0"
    fl = V.rsi_wilder(pd.Series(np.full(40, 7.0)), 14)
    assert math.isnan(fl.iloc[-1]), (
        "both averages zero -> rs = 0/0 -> NaN. This used to assert 100 on the "
        "invented premise that Pine 'tests the zero denominator first'; ta.rsi "
        "is a single division and has no such branch")
    # a ramp that then halts is NOT the same case: rma(down) is exactly zero
    # but rma(up) is not, so rs = +inf and 100 is correct and stays correct.
    ramp = list(np.linspace(10.0, 20.0, 50)) + [20.0] * 30
    assert abs(V.rsi_wilder(pd.Series(ramp), 14).iloc[-1] - 100.0) < 1e-9, (
        "only-gains-then-halted is a genuine 100, not the 0/0 case")
    print("rsi degenerate cases: all-up=100  all-down=0  flat=NaN (0/0)  "
          "ramp-then-halt=100")


def test_crossover_is_nan_safe_and_uses_the_previous_bar() -> None:
    a = pd.Series([np.nan, np.nan, 1.0, 3.0, 3.0, 1.0])
    b = pd.Series([np.nan, 2.0, 2.0, 2.0, 2.0, 2.0])
    up = V.crossover(a, b)
    dn = V.crossunder(a, b)
    assert true_bars(up) == [3], "a[1] <= b[1] and a > b"
    assert true_bars(dn) == [5], "a[1] >= b[1] and a < b"
    assert not up.iloc[1] and not up.iloc[2], "a NaN operand can never make a cross true"
    print("crossover/crossunder: NaN-safe, previous-bar rule confirmed")


def test_pivot_is_confirmed_right_bars_late() -> None:
    v = pd.Series([5, 4, 3, 2, 1, 2, 3, 4, 5, 6, 7], dtype=float)
    pl = V.pivot_low_confirmed(v, 2, 2)
    hit = [i for i in range(len(v)) if not np.isnan(pl.iloc[i])]
    assert hit == [6], "the pivot low sits on bar 4 and is only known on bar 4+2"
    assert pl.iloc[6] == 1.0, "the value reported is the pivot's own value"
    flat = V.pivot_low_confirmed(pd.Series(np.full(30, 3.0)), 5, 5)
    assert flat.notna().sum() == 0, "a tie disqualifies: a flat series has no pivots"
    print("pivot: confirmed exactly `right` bars late, value = the pivot's own")


def test_the_barssince_off_by_one_sets_a_6_to_61_bar_window() -> None:
    """f_inRange is called with plFound[1], not plFound.

    ta.barssince(plFound[1]) on a bar where plFound is true equals
    (gap between the two confirmation bars) - 1, so `5 <= bars <= 60` really
    admits gaps of 6..61 bars. This is inherited from TradingView's own
    built-in Divergence Indicator and is the single easiest thing to get
    wrong when porting it.
    """
    cond = np.zeros(80, dtype=bool)
    cond[10] = True
    cond[10 + 6] = True   # the tightest gap the filter accepts
    bars = V.barssince(V.shift_bool(cond)).to_numpy()
    assert bars[16] == 5.0, "a 6-bar gap reads as barssince == 5 (the lower bound)"
    cond2 = np.zeros(200, dtype=bool)
    cond2[10] = True
    cond2[10 + 61] = True  # the widest gap the filter accepts
    bars2 = V.barssince(V.shift_bool(cond2)).to_numpy()
    assert bars2[71] == 60.0, "a 61-bar gap reads as barssince == 60 (the upper bound)"
    cond3 = np.zeros(80, dtype=bool)
    cond3[10] = True
    cond3[15] = True       # a 5-bar gap -> barssince 4 -> rejected
    bars3 = V.barssince(V.shift_bool(cond3)).to_numpy()
    assert bars3[15] == 4.0
    assert np.isnan(V.barssince(V.shift_bool(np.zeros(10, dtype=bool))).to_numpy()).all(), (
        "never true -> na, and na <= 60 is false, so the FIRST pivot cannot fire")
    print("in-range window: rangeLower..rangeUpper 5..60 means a 6..61 bar pivot gap")


def test_valuewhen_needs_two_occurrences() -> None:
    cond = np.array([False, True, False, False, True, False, True])
    src = pd.Series([0.0, 1, 2, 3, 4, 5, 6])
    vw = V.valuewhen(cond, src, 1)
    assert np.isnan(vw.iloc[1]), "one occurrence so far: no previous one exists"
    assert vw.iloc[4] == 1.0, "at the 2nd occurrence, occurrence=1 is the 1st"
    assert vw.iloc[6] == 4.0, "at the 3rd, occurrence=1 is the 2nd"
    print("valuewhen(cond, src, 1): NaN until two occurrences, then the previous one")


# =============================================================================
# (a) bullish divergence
# =============================================================================

def test_a_bullish_divergence_fires_five_bars_after_the_pivot() -> None:
    f = bull_div_frame()
    ev = V.evaluate(f)
    bulls = true_bars(ev["bull_div"])
    bears = true_bars(ev["bear_div"])
    assert bulls == [129], "expected exactly one bullish divergence, on bar 129, got %r" % bulls
    assert bears == [], "the bull construction must not also print a bear, got %r" % bears

    piv = 129 - V.DEFAULT_CONFIG.piv_right
    assert piv == 124
    assert bool(ev["pl_found"].iloc[129]), "bar 129 is the confirmation of the bar-124 pivot"
    row = ev.iloc[129]
    assert row["low_at_pivot"] < row["prev_low_at_pivot"], "price made a LOWER low"
    assert row["rsi_at_pivot"] > row["prev_rsi_at_low_pivot"], "RSI made a HIGHER low"
    gap = row["bars_since_prev_low_pivot"]
    assert 5 <= gap <= 60, "the in-range filter as Pine writes it"

    n_piv = int(ev["pl_found"].sum())
    print("bull: %d RSI pivot lows in the frame, exactly ONE divergence, on bar 129"
          % n_piv)
    print("      pivot bar 124   price low %.4f -> %.4f (lower)   RSI %.2f -> %.2f (higher)"
          % (row["prev_low_at_pivot"], row["low_at_pivot"],
             row["prev_rsi_at_low_pivot"], row["rsi_at_pivot"]))
    print("      barssince(plFound[1]) = %.0f  (a %.0f-bar gap between pivots)"
          % (gap, gap + 1))

    # and the screen sees it when it is the last bar
    v = V.screen_symbol(f.iloc[:130], symbol="BULLDIV")
    assert v["passes"] and v["rule_a"] and v["rule_a_direction"] == "bull"
    assert v["rule_a_bars_ago"] == 0
    assert v["rule_a_label_bars_ago"] == 5, (
        "the boolean fires today; the Bull LABEL is drawn 5 bars back (offset=-lbR)")


# =============================================================================
# (b) bearish divergence
# =============================================================================

def test_b_bearish_divergence_fires_five_bars_after_the_pivot() -> None:
    f = bear_div_frame()
    ev = V.evaluate(f)
    bears = true_bars(ev["bear_div"])
    bulls = true_bars(ev["bull_div"])
    assert bears == [129], "expected exactly one bearish divergence, on bar 129, got %r" % bears
    assert bulls == [], "the bear construction must not also print a bull, got %r" % bulls
    row = ev.iloc[129]
    assert bool(ev["ph_found"].iloc[129])
    assert row["high_at_pivot"] > row["prev_high_at_pivot"], "price made a HIGHER high"
    assert row["rsi_at_pivot"] < row["prev_rsi_at_high_pivot"], "RSI made a LOWER high"
    print("bear: exactly ONE divergence, on bar 129 (pivot bar 124)")
    print("      price high %.4f -> %.4f (higher)   RSI %.2f -> %.2f (lower)"
          % (row["prev_high_at_pivot"], row["high_at_pivot"],
             row["prev_rsi_at_high_pivot"], row["rsi_at_pivot"]))
    v = V.screen_symbol(f.iloc[:130], symbol="BEARDIV")
    assert v["passes"] and v["rule_a"] and v["rule_a_direction"] == "bear"
    assert v["rule_a_bars_ago"] == 0


# =============================================================================
# (c) and (d) the scored cross
# =============================================================================

def test_c_cross_with_macd_up_and_price_above_the_200_scores_three() -> None:
    f = score3_frame()
    ev = V.evaluate(f)
    xs = true_bars(ev["bull_cross"])
    assert xs == [292], "expected one bull cross, on bar 292, got %r" % xs
    row = ev.iloc[292]
    assert row["macd_hist"] > 0, "MACD histogram agrees"
    assert row["close"] > row["slow"], "price is on the right side of the 200 EMA"
    assert int(row["bull_score"]) == 3, "1 for the cross + 1 MACD + 1 Slow = 3"
    assert int(row["bull_score"]) == V.DEFAULT_CONFIG.max_score, (
        "3 is the MAXIMUM with the shipped defaults -- useRsi is OFF")
    print("score 3: bar 292  hist %+0.4f  close %.2f  ema200 %.2f  -> label 'Bullish +3'"
          % (row["macd_hist"], row["close"], row["slow"]))
    v = V.screen_symbol(f.iloc[:293], symbol="SCORE3")
    assert v["passes"] and v["rule_b"] and v["rule_b_score"] == 3
    assert v["rule_b_label"] == "Bullish +3"
    assert v["rule_b_bars_ago"] == 0


def test_d_cross_with_macd_down_and_price_below_the_200_scores_one() -> None:
    f = score1_frame()
    ev = V.evaluate(f)
    xs = true_bars(ev["bull_cross"])
    assert xs == [293], "expected one bull cross, on the final bar 293, got %r" % xs
    row = ev.iloc[293]
    assert row["macd_hist"] < 0, "MACD histogram disagrees"
    assert row["close"] < row["slow"], "price is on the wrong side of the 200 EMA"
    assert int(row["bull_score"]) == 1, "the cross alone"
    print("score 1: bar 293  hist %+0.4f  close %.2f  ema200 %.2f  -> label 'Bullish +1'"
          % (row["macd_hist"], row["close"], row["slow"]))
    v = V.screen_symbol(f, symbol="SCORE1")
    assert v["rule_b"] is False, "min_signal_score = 2 rejects a bare cross"
    assert v["passes"] is False, "and with no divergence either, the symbol is dropped"
    loose = V.screen_symbol(f, V.DEFAULT_CONFIG.replace(min_signal_score=1), symbol="SCORE1")
    assert loose["rule_b"] and loose["rule_b_score"] == 1, (
        "it is only the THRESHOLD that rejected it, not the detection")
    print("        rejected by min_signal_score=2, detected again at min_signal_score=1")


def test_the_score_is_arithmetic_not_a_lookup() -> None:
    """Every switch combination, on the score-3 frame's cross bar."""
    f = score3_frame()
    base = V.DEFAULT_CONFIG
    combos = {
        (True, True, False): 3,    # shipped default
        (True, False, False): 2,
        (False, True, False): 2,
        (False, False, False): 1,
        (True, True, True): 4,     # only reachable with useRsi switched on
    }
    for (um, us, ur), want in combos.items():
        cfg = base.replace(use_macd=um, use_slow=us, use_rsi=ur)
        ev = V.evaluate(f, cfg)
        got = int(ev["bull_score"].iloc[292])
        assert got == want, "useMacd=%s useSlow=%s useRsi=%s -> %d, wanted %d" % (
            um, us, ur, got, want)
        assert cfg.max_score >= got
    print("score arithmetic verified across all five switch combinations (1,2,2,3,4)")


# =============================================================================
# (e) flat / halted
# =============================================================================

def test_e_a_flat_series_produces_nothing_and_does_not_crash() -> None:
    f = flat_frame()
    ev = V.evaluate(f)
    assert int(ev["pl_found"].sum()) == 0 and int(ev["ph_found"].sum()) == 0, "no pivots"
    assert not ev["bull_div"].any() and not ev["bear_div"].any(), "no divergence"
    assert not ev["bull_cross"].any() and not ev["bear_cross"].any(), (
        "fast == mid on every bar, and a cross is strict")
    assert (ev["atr"].dropna() == 0).all(), "a halted bar has zero true range"
    assert math.isnan(ev["rsi"].iloc[-1]), (
        "a series that never moved has an UNDEFINED RSI, not a maximal one")
    assert V.screen_symbol(f, symbol="FLAT")["rsi_zone"] == "", (
        "and therefore no zone label -- publishing 'extreme-overbought' for a "
        "stock that has not traded is the false positive this fix removes")
    v = V.screen_symbol(f, symbol="FLAT")
    assert v["ok"] and not v["passes"] and v["rules"] == ""
    print("flat 300-bar frame: 0 pivots, 0 divergences, 0 crosses, ATR 0, no exception")


def test_gaps_and_nans_do_not_raise() -> None:
    f = gappy_frame()
    v = V.screen_symbol(f, symbol="GAPPY")
    assert v["ok"], v["reason"]
    ev = V.evaluate(f)
    assert len(ev) == len(V.prepare_frame(f)), "NaN bars are dropped, not filled"
    assert len(ev) < len(f), "and something really was dropped"
    empty = V.screen_symbol(pd.DataFrame(), symbol="EMPTY")
    assert not empty["ok"] and "missing column" in empty["reason"]
    junk = V.screen_symbol(pd.DataFrame({"close": ["a", "b", "c"]}), symbol="JUNK")
    assert not junk["ok"], "unparseable prices are a reason, never a traceback"
    print("gaps / NaN rows / empty frame / junk frame: all handled, none raised")


# =============================================================================
# (f) the causality proof
# =============================================================================

def test_f_no_look_ahead_anywhere() -> None:
    """Truncate the frame at bar i; every value on bar i must be unchanged.

    Run over the two frames that actually carry signals, across every bar in
    the interesting stretch -- not a sample.
    """
    checked = 0
    f = bull_div_frame()
    checked += V.assert_no_lookahead(f, bars=range(60, len(f)))
    g = bear_div_frame()
    checked += V.assert_no_lookahead(g, bars=range(60, len(g)))
    h = score3_frame()
    checked += V.assert_no_lookahead(h, bars=range(250, len(h)))
    print("no look-ahead: %d cut points x %d columns, all identical"
          % (checked, len(V.CAUSAL_COLUMNS)))

    # the same property at the level the owner actually reads: the verdict
    ev = V.evaluate(f)
    mismatches = 0
    for i in range(100, len(f)):
        v = V.screen_symbol(f.iloc[: i + 1])
        live = bool(ev["bull_div"].iloc[i] or ev["bear_div"].iloc[i])
        if bool(v["rule_a"]) != live:
            mismatches += 1
    assert mismatches == 0, "the screen's RULE A verdict must not move when bars arrive"
    print("                screen verdict re-run on %d truncations: 0 mismatches"
          % (len(f) - 100))


# =============================================================================
# (g) short history
# =============================================================================

def test_g_a_frame_shorter_than_the_slow_ma_is_sensible_not_fatal() -> None:
    f = short_frame(120)
    v = V.screen_symbol(f, symbol="YOUNG")
    assert v["ok"], v["reason"]
    assert v["n_bars"] == 120
    assert v["slow_ready"] is False, "no 200 EMA on 120 bars"
    assert v["trend"] == "unknown", "and therefore no regime claim"
    assert v["above_slow"] is None, "not False -- unknown is not a direction"
    assert "only 120 bars" in v["history_warning"]
    ev = V.evaluate(f)
    assert ev["slow"].isna().all()
    if ev["bull_cross"].any():
        i = true_bars(ev["bull_cross"])[-1]
        assert int(ev["bull_score"].iloc[i]) <= 2, (
            "close > na is false in Pine, so the Slow point is simply not awarded")
    tiny = V.screen_symbol(f.iloc[:30], symbol="TINY")
    assert not tiny["ok"] and "too short" in tiny["reason"]
    print("120-bar frame: screened, slow_ready=False, trend='unknown', max score 2")
    print("30-bar frame: refused with a reason, not an exception")


# =============================================================================
# mode 1 vs mode 2
# =============================================================================

def test_mode_1_is_divergence_only() -> None:
    f = score3_frame().iloc[:293]
    m2 = V.screen_symbol(f, V.DEFAULT_CONFIG.replace(mode=2), symbol="SCORE3")
    m1 = V.screen_symbol(f, V.DEFAULT_CONFIG.replace(mode=1), symbol="SCORE3")
    assert m2["passes"] and m2["rules"] == "B"
    assert not m1["passes"] and m1["rules"] == "", "mode 1 ignores RULE B entirely"
    assert m1["rule_b"] is True, "but still REPORTS it, so a reviewer can see why"
    print("mode 1 drops a score-3 cross; mode 2 keeps it. Both report both rules.")


def test_freshness_windows_are_in_bars() -> None:
    f = bull_div_frame()          # divergence on bar 129, frame is 141 bars
    late = f.iloc[:135]           # the divergence is now 5 bars old
    assert not V.screen_symbol(late)["passes"], "div_fresh_bars=1 means today only"
    wide = V.DEFAULT_CONFIG.replace(div_fresh_bars=6)
    v = V.screen_symbol(late, wide)
    assert v["passes"] and v["rule_a_bars_ago"] == 5
    assert not V.screen_symbol(late, V.DEFAULT_CONFIG.replace(div_fresh_bars=5))["passes"], (
        "5 bars ago is outside a 5-bar window: bars_ago 0..4")
    print("freshness: div_fresh_bars=N admits bars_ago 0..N-1, inclusive of today")


# =============================================================================
# the demo basket
# =============================================================================

def demo_basket() -> pd.DataFrame:
    frames: Dict[str, pd.DataFrame] = {
        "BULLDIV.AX": bull_div_frame().iloc[:130],    # bull divergence today
        "BEARDIV.AX": bear_div_frame().iloc[:130],    # bear divergence today
        "SCORE3.NDQ": score3_frame().iloc[:293],      # Bullish +3 today
        "SCORE1.NDQ": score1_frame(),                 # Bullish +1 today (rejected)
        "STALE.AX": bull_div_frame(),                 # same divergence, 12 bars old
        "FLAT.AX": flat_frame(),                      # halted
        "YOUNG-USD": short_frame(120),                # young listing
        "TINY-USD": short_frame(30),                  # unscreenable
    }
    cfg = V.DEFAULT_CONFIG

    def show(frame: pd.DataFrame, cols: List[str]) -> None:
        view = frame.reindex(columns=cols).copy()
        for c, fmt in (("close", "%.2f"), ("rsi", "%.1f"), ("atr_pct", "%.2f"),
                       ("macd_hist", "%+.4f")):
            if c in view.columns:
                view[c] = view[c].map(lambda x, f=fmt: "" if pd.isna(x) else f % x)
        for c in ("score", "best_bars_ago", "rule_a_label_bars_ago", "n_bars"):
            if c in view.columns:
                view[c] = view[c].map(lambda x: "" if pd.isna(x) else "%d" % int(x))
        print(view.astype("object").fillna("").to_string(index=False))

    full = V.screen_frames(frames, cfg, market="demo", include_failures=True)
    banner("SCREEN OUTPUT -- mode 2 (RULE A or RULE B), every symbol shown")
    show(full, ["symbol", "passes", "rules", "direction", "score", "best_bars_ago",
                "rule_a_direction", "rule_b_label", "close", "rsi", "trend",
                "n_bars", "reason"])
    passing = V.screen_frames(frames, cfg, market="demo")
    banner("SCREEN OUTPUT -- mode 2, only the rows a reviewer opens (ranked)")
    show(passing, ["symbol", "rules", "direction", "score", "best_bars_ago",
                   "rule_a_label_bars_ago", "close", "rsi", "rsi_zone", "trend",
                   "regime", "atr_pct", "macd_hist"])
    mode1 = V.screen_frames(frames, cfg.replace(mode=1), market="demo")
    banner("SCREEN OUTPUT -- mode 1 (RULE A only)")
    show(mode1, ["symbol", "rules", "direction", "best_bars_ago",
                 "rule_a_label_bars_ago", "close", "rsi", "rsi_zone", "trend"])
    assert list(passing["symbol"]) == ["BEARDIV.AX", "BULLDIV.AX", "SCORE3.NDQ"], \
        list(passing["symbol"])
    assert list(mode1["symbol"]) == ["BEARDIV.AX", "BULLDIV.AX"], list(mode1["symbol"])
    banner("ONE FULL ROW -- every field screen_symbol() publishes for BULLDIV.AX")
    row = V.screen_symbol(frames["BULLDIV.AX"], cfg, symbol="BULLDIV.AX", market="asx")
    for k in sorted(row):
        print("  %-26s %r" % (k, row[k]))
    return full


def show_config() -> None:
    banner("ScreenConfig -- every field and its default")
    cfg = V.ScreenConfig()
    for k, v in cfg.to_dict().items():
        print("  %-22s %r" % (k, v))
    print("  %-22s %r  (derived: 1 + useMacd + useSlow + useRsi)" % ("max_score", cfg.max_score))


# =============================================================================
# runner
# =============================================================================


# =============================================================================
# (h) ADVERSARIAL -- added by the verification pass, 2026-09-22
#
# Every test below is a frame someone tried to break the module with. They are
# kept because each one either found a defect or proved an invariant that the
# original 18 only assumed.
# =============================================================================

def _walk(seed: int, n: int = 600, decimals: int | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    if decimals is not None:
        c = np.round(c, decimals)
    c = np.maximum(c, 1.0)
    h = c + np.abs(rng.normal(0, 0.1, n))
    l = c - np.abs(rng.normal(0, 0.1, n))
    return pd.DataFrame({"open": c, "high": h, "low": l, "close": c,
                         "volume": np.full(n, 1e5)},
                        index=pd.bdate_range("2022-01-03", periods=n))


def test_h_equal_consecutive_lows_make_no_pivot_under_the_strict_rule() -> None:
    """A flat trough is the tie case the pivot convention turns on."""
    v = pd.Series([10, 9, 8, 7, 6, 5, 5, 6, 7, 8, 9, 10, 11], dtype=float)
    assert V.pivot_low_confirmed(v, 2, 2).notna().sum() == 0, (
        "strict on both sides: a shared minimum is not a unique extreme")
    loose_r = V.pivot_low_confirmed(v, 2, 2, strict_right=False)
    assert true_bars(loose_r.notna()) == [7], "the FIRST of the two lows, confirmed at 5+2"
    loose_l = V.pivot_low_confirmed(v, 2, 2, strict_left=False)
    assert true_bars(loose_l.notna()) == [8], "the SECOND of the two lows"
    both = V.pivot_low_confirmed(v, 2, 2, strict_left=False, strict_right=False)
    assert true_bars(both.notna()) == [7, 8], "non-strict admits both"
    print("equal consecutive lows: strict=0 pivots, loose-right=1, loose-left=1, loose-both=2")


def test_h_a_single_bar_spike_does_not_leak_or_crash() -> None:
    n = 300
    c = np.full(n, 50.0)
    c[150] = 500.0
    f = pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                      "volume": np.full(n, 1.0)},
                     index=pd.bdate_range("2023-01-02", periods=n))
    v = V.screen_symbol(f, symbol="SPIKE")
    assert v["ok"], v["reason"]
    ev = V.evaluate(f)
    assert not ev["bull_div"].any() and not ev["bear_div"].any(), (
        "one bar cannot be both sides of a pivot window")
    assert V.assert_no_lookahead(f, bars=range(200, n)) > 0
    print("single-bar 10x spike: screened, no divergence, no look-ahead")


def test_h_a_descending_frame_is_REFUSED_not_screened() -> None:
    """The one bad input that produces a complete and entirely wrong row."""
    f = _walk(5, 300)
    rev = f.iloc[::-1]
    v = V.screen_symbol(rev, symbol="REV")
    assert not v["ok"], "a newest-first frame must not come back ok"
    assert "DESCENDING" in v["reason"], v["reason"]
    fwd = V.screen_symbol(f, symbol="FWD")
    assert fwd["ok"] and fwd["last_bar"] == str(f.index[-1])
    # the failure it prevents, stated as a number
    import vivek50_screen as _V
    raw = _V.rsi_wilder(rev["close"], 14).iloc[-1]
    assert abs(raw - fwd["rsi"]) > 1.0, (
        "backwards bars really do produce a different, plausible RSI")
    print("descending frame: refused with a reason (backwards RSI would have "
          "read %.1f against the true %.1f)" % (raw, fwd["rsi"]))


def test_h_a_duplicated_or_gapped_index_is_positional_and_harmless() -> None:
    f = _walk(6, 300)
    dup = f.copy()
    dup.index = pd.DatetimeIndex([f.index[0]] * len(f))     # every bar same stamp
    assert V.screen_symbol(dup, symbol="DUP")["ok"], "an all-equal index is not descending"
    ix = list(f.index)
    ix[100] = ix[99]                                        # one repeated stamp
    part = f.copy()
    part.index = pd.DatetimeIndex(ix)
    a = V.evaluate(part)["bull_div"].to_numpy()
    b = V.evaluate(f)["bull_div"].to_numpy()
    assert (a == b).all(), "the index is a label; every computation is positional"
    holed = f.drop(f.index[120:126])                        # a six-session hole
    assert V.screen_symbol(holed, symbol="HOLE")["ok"]
    assert V.assert_no_lookahead(holed, bars=range(250, len(holed))) > 0
    print("duplicated / repeated / gapped index: positional, identical verdicts")


def test_h_interior_nan_rows_are_dropped_and_do_not_poison_the_averages() -> None:
    f = _walk(7, 400)
    holed = f.copy()
    holed.iloc[200:205, :4] = np.nan
    v = V.screen_symbol(holed, symbol="NANROWS")
    assert v["ok"] and v["n_bars"] == len(f) - 5
    ev = V.evaluate(holed)
    assert ev["rsi"].iloc[-1] == ev["rsi"].iloc[-1], "a NaN bar must not poison the RMA"
    assert ev["slow"].notna().iloc[-1], "nor the 200 EMA"
    one = f.copy()
    one.iloc[300, 1] = np.nan                                # high only
    assert V.screen_symbol(one, symbol="NANHIGH")["n_bars"] == len(f) - 1, (
        "a NaN in ANY of open/high/low/close drops the whole bar")
    print("interior NaN rows: dropped, recursive averages stay finite")


def test_h_a_descending_then_flat_rsi_is_zero_not_undefined() -> None:
    """rma(up) == 0 with rma(down) > 0 -- the mirror of the ramp case, and the
    one that must NOT become NaN when the 0/0 case does."""
    c = np.concatenate([np.linspace(200.0, 50.0, 200), np.full(100, 50.0)])
    f = pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                      "volume": np.full(len(c), 1.0)},
                     index=pd.bdate_range("2023-01-02", periods=len(c)))
    v = V.screen_symbol(f, symbol="DESCFLAT")
    assert v["ok"] and abs(v["rsi"] - 0.0) < 1e-9, "only-losses-then-halted is a genuine 0"
    assert v["rsi_zone"] == "extreme-oversold"
    assert not v["passes"], "and it still fires nothing: a flat tail has no pivots"
    assert V.assert_no_lookahead(f, bars=range(250, len(c))) > 0
    print("descending-then-flat: RSI 0 (not NaN), extreme-oversold, no signal")


def test_h_mode_1_does_not_let_rule_b_colour_the_direction() -> None:
    f = score3_frame()
    ev = V.evaluate(f)
    i = int(np.flatnonzero(ev["bull_signal"].to_numpy())[-1])
    g = f.iloc[: i + 1]
    one = V.screen_symbol(g, V.DEFAULT_CONFIG.replace(mode=1), symbol="S3")
    two = V.screen_symbol(g, V.DEFAULT_CONFIG.replace(mode=2), symbol="S3")
    assert two["passes"] and two["direction"] == "bull"
    assert not one["passes"] and one["rules"] == "" and one["best_bars_ago"] is None
    assert one["direction"] == "", (
        "in mode 1 RULE B is reported and NOT used -- it must not be the only "
        "thing giving a non-passing row a direction")
    assert one["rule_b"] and one["rule_b_direction"] == "bull", "still REPORTED"
    print("mode 1: RULE B reported, and no longer able to set `direction`")


def test_h_a_mistyped_source_is_refused_instead_of_silently_meaning_close() -> None:
    try:
        V.DEFAULT_CONFIG.replace(rsi_source="hlc3")
        raise AssertionError("a source this module cannot compute must not validate")
    except ValueError as exc:
        assert "rsi_source" in str(exc)
    bad = V.ScreenConfig(ma_source="adj_close")
    row = V.screen_symbol(score3_frame(), bad, symbol="BAD")
    assert not row["ok"] and "invalid config" in row["reason"], row["reason"]
    assert V.ScreenConfig(rsi_source="high").validate().rsi_source == "high", (
        "a real OHLC column is still allowed")
    print("mistyped source: refused by validate(), reported as a row reason")


def test_h_the_lookahead_proof_catches_a_planted_lookahead() -> None:
    """A proof nobody has tried to break is a decoration. Plant the exact bug
    the proof exists to catch and require it to go red."""
    f = bull_div_frame()
    original = V._pivot
    try:
        V._pivot = lambda s, l, r, low, sl, sr: original(s, l, r, low, sl, sr).shift(-r)
        try:
            V.assert_no_lookahead(f, bars=range(60, len(f)))
            raise AssertionError("the pivot-on-the-pivot-bar bug was NOT caught")
        except AssertionError as exc:
            assert "LOOK-AHEAD" in str(exc), str(exc)
    finally:
        V._pivot = original
    orig_sma = V.sma_pine
    try:
        V.sma_pine = lambda s, p: orig_sma(s, p).shift(-2)
        try:
            V.assert_no_lookahead(f, bars=range(60, len(f)))
            raise AssertionError("a centred moving average was NOT caught")
        except AssertionError as exc:
            assert "LOOK-AHEAD" in str(exc), str(exc)
    finally:
        V.sma_pine = orig_sma
    assert V.assert_no_lookahead(f, bars=range(60, len(f))) > 0, "and clean again after"
    print("look-ahead proof: both planted bugs caught, module clean afterwards")


def test_h_matches_a_naive_bar_by_bar_pine_reading() -> None:
    """The vectorised code is compared against a separately written, literal
    loop over the Pine source. 24 frames x 4 tie conventions, with flat
    stretches injected so the halted/illiquid population is exercised."""
    try:
        import pinesim as P
    except ImportError:
        print("differential test skipped: pinesim.py not present")
        return
    rng = np.random.default_rng(99)
    compared = 0
    divs = 0
    for trial in range(24):
        n = 500
        c = np.round(50 + np.cumsum(rng.normal(0, 0.25, n)), 2)
        for _ in range(int(rng.integers(1, 5))):
            st = int(rng.integers(20, n - 30))
            c[st:st + int(rng.integers(3, 25))] = c[st]
        c = np.maximum(c, 0.5)
        h = np.round(c + np.abs(rng.normal(0, 0.1, n)), 2)
        l = np.round(c - np.abs(rng.normal(0, 0.1, n)), 2)
        f = pd.DataFrame({"open": c, "high": h, "low": l, "close": c,
                          "volume": np.full(n, 1e5)})
        for sl, sr in ((True, True), (False, False), (True, False), (False, True)):
            cfg = V.DEFAULT_CONFIG.replace(pivot_strict_left=sl, pivot_strict_right=sr)
            ev = V.evaluate(f, cfg)
            ref = P.divergence(list(h), list(l), list(c), strict_left=sl, strict_right=sr)
            for col, key in (("pl_found", "plFound"), ("ph_found", "phFound"),
                             ("bull_div", "bull"), ("bear_div", "bear")):
                assert list(ev[col].astype(bool)) == [bool(x) for x in ref[key]], (
                    "trial %d strict=%s: %s disagrees with the naive Pine reading"
                    % (trial, (sl, sr), col))
            compared += 1
        divs += int(ev["bull_div"].sum()) + int(ev["bear_div"].sum())
    print("differential vs a naive bar-by-bar Pine reading: %d frame/convention "
          "pairs identical" % compared)


TESTS = [
    test_warmup_lengths_match_pine,
    test_rma_is_wilder_not_an_ema,
    test_rsi_degenerate_cases,
    test_crossover_is_nan_safe_and_uses_the_previous_bar,
    test_pivot_is_confirmed_right_bars_late,
    test_the_barssince_off_by_one_sets_a_6_to_61_bar_window,
    test_valuewhen_needs_two_occurrences,
    test_a_bullish_divergence_fires_five_bars_after_the_pivot,
    test_b_bearish_divergence_fires_five_bars_after_the_pivot,
    test_c_cross_with_macd_up_and_price_above_the_200_scores_three,
    test_d_cross_with_macd_down_and_price_below_the_200_scores_one,
    test_the_score_is_arithmetic_not_a_lookup,
    test_e_a_flat_series_produces_nothing_and_does_not_crash,
    test_gaps_and_nans_do_not_raise,
    test_f_no_look_ahead_anywhere,
    test_g_a_frame_shorter_than_the_slow_ma_is_sensible_not_fatal,
    test_mode_1_is_divergence_only,
    test_freshness_windows_are_in_bars,
    test_h_equal_consecutive_lows_make_no_pivot_under_the_strict_rule,
    test_h_a_single_bar_spike_does_not_leak_or_crash,
    test_h_a_descending_frame_is_REFUSED_not_screened,
    test_h_a_duplicated_or_gapped_index_is_positional_and_harmless,
    test_h_interior_nan_rows_are_dropped_and_do_not_poison_the_averages,
    test_h_a_descending_then_flat_rsi_is_zero_not_undefined,
    test_h_mode_1_does_not_let_rule_b_colour_the_direction,
    test_h_a_mistyped_source_is_refused_instead_of_silently_meaning_close,
    test_h_the_lookahead_proof_catches_a_planted_lookahead,
    test_h_matches_a_naive_bar_by_bar_pine_reading,
]


def main() -> int:
    banner("vivek50_screen self-test -- pandas %s, numpy %s" % (pd.__version__, np.__version__))
    failures = 0
    for fn in TESTS:
        name = fn.__name__
        try:
            fn()
            print("  PASS  %s" % name)
        except AssertionError as exc:
            failures += 1
            print("  FAIL  %s\n        %s" % (name, exc))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print("  ERROR %s\n        %r" % (name, exc))
    demo_basket()
    show_config()
    banner("%d/%d tests passed" % (len(TESTS) - failures, len(TESTS)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
```


---

# PART 6A - ADVERSARIAL REVIEW OF THE REFERENCE IMPLEMENTATION

Brief: assume the Python reference implementation of the Vivek 5.0 Pine maths
is wrong and try to prove it.

**Result: 4 confirmed defects, fixed. 11 suspected defects examined and
cleared, with the reasoning.** The divergence engine itself -- the pivot
timing, the `barssince` off-by-one, the `valuewhen` occurrence, the crossover
rule -- is correct, and is now proved correct against an independently written
bar-by-bar reading of the Pine rather than against its own author's intent.

## How this was verified

Four methods, in increasing order of how much they are worth:

1. **Side-by-side reading** of `tradingview/Final_RSI_Plus.pine`,
   `Final_Top_Script.pine`, `Final_Bottom_MACD.pine` against the module.
2. **The existing self-test, re-run** (18/18 before the fixes; the two that
   failed after are the two that pinned the defect in finding 1).
3. **A separately written naive Pine interpreter**, `pinesim.py`. It is a
   literal bar-by-bar loop transcribed from the Pine source -- `ta_rma`,
   `ta_rsi`, `ta_ema`, `ta_pivotlow`, `ta_valuewhen`, `ta_barssince`,
   `ta_crossover` -- written from the `.pine` files, not from the module, so a
   disagreement is evidence and not a shared assumption. The module was then
   diffed against it over 96 frame/convention pairs with flat "halted"
   stretches injected, and over rounded-to-the-cent "penny stock" tapes where
   genuine ties actually occur: **zero disagreements on `pl_found`,
   `ph_found`, `bull_div`, `bear_div`, `rsi`, `fast`, `slow`, `macd_hist`,
   `bull_cross`, `bear_cross`, `bull_score`, `bull_signal`.**
4. **Mutation testing of the causality proof**: two look-ahead bugs were
   planted in the shipped module and `assert_no_lookahead` was required to go
   red for each.

Adversarial frames built and run: equal consecutive lows, a single-bar 10x
spike, a gapped calendar, an all-duplicate index, a partially duplicated
index, five interior NaN rows, one NaN in a single column, a descending-then-
flat tape, a ramp-then-halted tape, a reverse-chronological frame, integer
dtypes, an empty frame, a junk frame, an all-failing universe and an empty
universe. **Nothing crashed. One of them produced a wrong answer (finding 2).**

---

# CONFIRMED DEFECTS

## 1. CONFIRMED DEFECT -- `rsi_wilder` returned 100 for an undefined RSI, on a false premise about Pine

**Where:** `rsi_wilder()`, the `np.where` chain; its docstring; and KNOWN LIMIT
7 of `sec_reference_impl.md`.

**The claim that was made.** The docstring said Pine "tests the zero-
denominator case first", so a series where both Wilder averages are zero
"lands on 100 by that order of tests". The self-test pinned it twice
(`test_rsi_degenerate_cases`, `test_e_a_flat_series_produces_nothing`).

**Why it is wrong.** `ta.rsi` has no chain of tests to inherit an order from.
It is, verbatim from the Pine reference:

```
u   = math.max(ta.change(src), 0)
d   = math.max(-ta.change(src), 0)
rs  = ta.rma(u, len) / ta.rma(d, len)
res = 100 - 100 / (1 + rs)
```

One division. The two real boundary cases fall out of IEEE arithmetic and both
were right: `rma(d) == 0` with `rma(u) > 0` gives `+inf -> 100` (this is why a
genuine uninterrupted uptrend prints 100 on a TradingView chart -- observable,
and the module's value for it is unchanged), and `rma(u) == 0` with
`rma(d) > 0` gives `0 -> 0`. The third case, **both exactly zero, is `0/0`,
which is NaN**, and `100 - 100/(1 + NaN)` is NaN. The module hard-coded 100 for
it.

**Why it mattered, against the write-up's own defence.** The defence was "the
screen never reaches it, because a flat series has no pivots and no crosses".
The verdict half of that is true and was verified -- no RULE A or RULE B
firing moves. The published-row half is false, and the module's own demo
output proved it: `FLAT.AX` came back as

```
   FLAT.AX  False   ...   42.00  100.0  down  300        rsi_zone: extreme-overbought
```

Every halted, suspended or never-traded name in a 3,600-symbol universe was
published to the reviewer as maximally overbought. On a scanner whose entire
output is an eyeball review, that is a false positive in the column a reviewer
scans.

**Reachability, stated precisely.** Both averages are exactly zero only while
the series has been flat since its first bar (once one down bar exists,
`rma(d)` is a decaying recursion that never reaches exactly 0 in fewer than
~10,000 bars). So the condition is a prefix condition, it cannot appear in the
middle of a series, and it cannot poison a downstream recursive average.

**Fix applied.**

```python
both_zero = live & (rd == 0.0) & (ru == 0.0)   # 0 / 0 -> NaN, see above
out = np.where(both_zero, np.nan,
               np.where(live & (rd == 0.0), 100.0,
                        np.where(live & (ru == 0.0), 0.0,
                                 np.where(live, generic, np.nan))))
```

Direction of the change: it can only ever REMOVE a claim, never add one.
`FLAT.AX` now publishes a blank RSI and a blank `rsi_zone`.

**Honesty about the residual uncertainty.** There is no Pine compiler and no
chart in this environment, so this is the documented formula under IEEE rules,
not a chart observation. The docstring and the corrected KNOWN LIMIT 7 both
name the single line to flip back if a chart ever shows TradingView printing
100 there. The two verifiable boundary cases (100 on a pure uptrend, 0 on a
pure downtrend) are untouched and separately pinned, including the two
"ramp-then-halted" / "slide-then-halted" cases that are easy to confuse with
the 0/0 case and must NOT become NaN.

**Tests:** `test_rsi_degenerate_cases` and
`test_e_a_flat_series_produces_nothing_and_does_not_crash` corrected;
`test_h_a_descending_then_flat_rsi_is_zero_not_undefined` added to pin the
mirror case that must stay 0.

---

## 2. CONFIRMED DEFECT -- a reverse-chronological frame was screened, silently, and returned a complete wrong answer

**Where:** `prepare_frame()`.

**What happened.** `screen_symbol()` promises "Never raises on bad data.
Returns `ok=False` with a `reason` for anything unscreenable." A frame handed
in newest-first was accepted with `ok=True`:

```
fwd  ok=True  last_bar=2024-10-26  rsi=28.625
rev  ok=True  last_bar=2024-01-01  rsi=62.551
```

Same 300 bars. Every recursive average runs backwards, the RSI is a different
number, `last_bar` reports the OLDEST date, and **nothing anywhere in the row
says so**. This is the single worst failure shape a scanner can have: not a
crash, not a blank, but a full, plausible, ranked row that is meaningless. It
is also not exotic -- plenty of providers and most hand-saved CSV exports are
descending, and one wrong `ascending=` flag corrupts an entire universe scan
with no symptom.

The write-up's limit 12 says "It takes an ordered frame of bars", which makes
ordering a caller contract -- but an unchecked contract on the one input that
fails invisibly is not a defence, it is the defect.

**Fix applied** in `prepare_frame()`, before any arithmetic:

```python
if len(out.index) > 1:
    try:
        backwards = bool(out.index.is_monotonic_decreasing) and not bool(
            out.index.is_monotonic_increasing)
    except (TypeError, ValueError):
        backwards = False
    if backwards:
        raise ValueError(
            "bars are in DESCENDING order (index runs newest-first); "
            "this module reads a frame oldest-first -- sort it ascending")
```

`screen_symbol` already funnels a `prepare_frame` failure into
`ok=False, reason="unreadable frame: ..."`, so the scan loop keeps running and
the row says why. Deliberately narrow: an index that is BOTH monotonic
increasing and decreasing is constant (all bars share a timestamp), which is a
legitimate duplicate-index frame and is not flagged; a non-comparable index
type raises inside the check and is not flagged, because an arbitrary
unordered index cannot be judged. A partially shuffled frame is still
undetectable and remains the caller's problem -- stated, not hidden.

**Tests:** `test_h_a_descending_frame_is_REFUSED_not_screened` (asserts the
refusal AND that the backwards RSI really does differ, so the test proves the
hazard rather than just the guard).

---

## 3. CONFIRMED DEFECT -- in mode 1, RULE B could still set `direction`

**Where:** `screen_symbol()`, the verdict block.

`mode=1` is documented as "RULE A only", and the code honours that in three
places: `rules` is reset to `"A"` or `""`, `passes` reads `rule_a` alone, and
`best_bars_ago` explicitly excludes RULE B (`base["rule_b_bars_ago"] if
cfg.mode == 2 else None`). The fourth field did not:

```python
dirs = {base["rule_a_direction"], base["rule_b_direction"]} - {""}
```

Measured on the module's own `score3_frame` truncated to its cross bar:

```
mode 1 -> passes=False  rules=''  direction='bull'  best_bars_ago=None
mode 2 -> passes=True   rules='B' direction='bull'  best_bars_ago=0
```

A non-passing row in a divergence-only screen carried a direction that came
entirely from a rule that mode had switched off. The worse case is the one
that has not happened yet: a genuine bull divergence with a coincident bear
cross reports `rules='A', passes=True, direction='conflict'` in a mode where
the cross is not part of the verdict.

That `best_bars_ago` two lines above already gates on `cfg.mode` is what makes
this a defect rather than a design choice -- the intent to gate is in the
file, applied to one field and not its neighbour.

**Fix applied:**

```python
dirs = {base["rule_a_direction"]}
if cfg.mode == 2:
    dirs.add(base["rule_b_direction"])
dirs -= {""}
```

`rule_b`, `rule_b_direction`, `rule_b_score` and `rule_b_label` are still
populated and reported in mode 1 -- "reported, not used" is preserved exactly.

**Tests:** `test_h_mode_1_does_not_let_rule_b_colour_the_direction`.

---

## 4. CONFIRMED DEFECT -- a mistyped `*_source` silently meant `close`

**Where:** `ScreenConfig.validate()`, and the three read sites
(`rsi_divergence`, `cross_signal` x2).

Each read site is `d[cfg.rsi_source] if cfg.rsi_source in d.columns else
d["close"]`. `validate()` checks `mode`, every length, the range ordering,
both MA types and both seeds -- but not the source names. So:

```
rsi_source='hlc3' silently == close: True
```

A config that says it screens on `hlc3`, `hl2`, `Close` or `adj_close`
computes a different indicator than it claims, silently, in a dataclass whose
docstring is "Fail loudly on a configuration that cannot mean anything". The
module cannot compute a synthetic source at all, so every such name is a
configuration that cannot mean anything.

**Fix applied** -- validation in `validate()` against `OHLC_COLUMNS`, plus a
`cfg.validate()` inside `screen_symbol()` whose failure becomes a row
`reason` rather than a traceback (the function is called in a 3,600-symbol
loop and must not take a scan down; `screen_frames()` still validates once up
front, loudly, before the loop starts). The `else d["close"]` fallbacks are
left in place and are now unreachable for a validated config.

**Tests:**
`test_h_a_mistyped_source_is_refused_instead_of_silently_meaning_close`.

---

## 5. CONFIRMED (minor) -- `CAUSAL_COLUMNS` covered 17 of 45 columns

**Where:** `CAUSAL_COLUMNS`, read by `assert_no_lookahead()`.

The causality proof only checked the 17 columns it listed. It omitted every
piece of divergence EVIDENCE the row publishes to the reviewer --
`rsi_at_pivot`, `prev_rsi_at_low_pivot`, `prev_low_at_pivot`,
`bars_since_prev_low_pivot`, `in_range_low`, `price_ll` and the rest -- which
are exactly the fields `screen_symbol` copies onto the output row as
`rule_a_prev_rsi`, `rule_a_prev_price`, `rule_a_bars_between_pivots`. A
verdict can be causal while the numbers printed to justify it are not.

**No violation exists.** A sweep of all 45 columns across 90 truncation points
found zero look-ahead, so this is a gap in the PROOF, not in the maths.
Closed anyway because it costs nothing: `CAUSAL_COLUMNS` now names 40 columns
(the five excluded are `open/high/low/close/volume`, which are the inputs).
The proof now runs 223 cut points x 40 columns.

---

# NOT DEFECTS

## 6. NOT A DEFECT -- the divergence confirmation-bar timing is correct

Pine's `ta.pivotlow(rsi, lbL, lbR)` returns on bar `i` the value of
`rsi[i - lbR]` when that bar was a pivot; the pane draws the mark with
`offset = -lbR`, which places the label back on the pivot bar while the SIGNAL
happens `lbR` bars later. `_pivot()` does exactly this:
`out[confirm[ok]] = centre[ok]` where `confirm = centres + right`.

Verified three ways: the shipped `test_pivot_is_confirmed_right_bars_late`;
the differential run against `pinesim.ta_pivotlow` (96 pairs, identical); and
**mutation** -- planting the classic bug (`.shift(-right)`, stamping the pivot
on the pivot bar) makes `assert_no_lookahead` fail with
`LOOK-AHEAD in 'pl_found' at bar 74`. That mutation is now a permanent test.

## 7. NOT A DEFECT -- `barssince(plFound[1])` is not off by one; the off-by-one is Pine's and is reproduced deliberately

The suspicion is the right one to have and the answer is that the module is
already aware of it. `shift_bool(pl_found)` is `plFound[1]`; on a confirmation
bar `i` with the previous pivot confirmed at `p`, `ta.barssince` returns
`i - p - 1`, so the configured `5 <= bars <= 60` admits a **6 to 61 bar** gap
between pivots, not 5 to 60. Measured directly at every boundary:

```
pivot gap= 5  barssince=4   inRange=False
pivot gap= 6  barssince=5   inRange=True     <- lower edge
pivot gap=61  barssince=60  inRange=True     <- upper edge
pivot gap=62  barssince=61  inRange=False
```

The primitive also matches `pinesim.ta_barssince` element for element,
including the NaN-before-first-occurrence behaviour that stops the first pivot
of a symbol's history claiming a divergence against nothing. This is inherited
from TradingView's own built-in Divergence Indicator; changing it would be a
deviation from the chart, not a fix.

## 8. NOT A DEFECT -- `valuewhen(cond, src, 1)` returns the previous occurrence

`seen = np.searchsorted(occ, bars, side="right")` counts occurrences at bars
`<= i` (inclusive of the current bar, which is what Pine does when `cond` is
true now), and `j = seen - 1 - occurrence` then steps back. So occurrence 0 is
the current pivot and occurrence 1 is the one before it -- which is the whole
point, since the bull test compares the current pivot against the previous
one. `j < 0` yields NaN and every comparison against it is False, so a
symbol's first pivot cannot fire. Matches `pinesim.ta_valuewhen` exactly and
is pinned by `test_valuewhen_needs_two_occurrences`.

## 9. NOT A DEFECT -- the strict pivot tie rule is an honestly declared unverifiable decision, and it was already measured

Pine does not document what `ta.pivotlow` does when the centre EQUALS a
neighbour, and there is no chart here to settle it. The module requires a
strictly unique extreme on both sides and exposes `pivot_strict_left` /
`pivot_strict_right` so the question can be settled later without touching
other code. KNOWN LIMIT 1 states the uncertainty, states that PART 5 of the
same document disagrees with it, and sizes the disagreement (300 walks x 750
cent-rounded bars: 0.5 % more pivots and 0.2 % more divergences non-strict,
with 27 of ~3,380 firings disagreeing in BOTH directions).

I verified the behaviour rather than the prose, on a flat trough:

```
[10,9,8,7,6,5,5,6,7,8,9,10,11], left=2 right=2
strict both        -> no pivot
loose right only   -> the FIRST of the two equal lows
loose left only    -> the SECOND
loose both         -> both
```

All four settings agree with `pinesim` bar for bar, so whichever convention
turns out to be TradingView's, this module reproduces it from a flag. That is
the correct shape for an unverifiable convention and it is not a defect. The
write-up's own recipe for settling it (export the pane's Bull/Bear marks for
20 liquid names and diff the firing bars) stands.

## 10. NOT A DEFECT -- crossover/crossunder handle NaN warm-up and exact equality correctly

Pine: `ta.crossover` is `a[1] <= b[1] and a > b` -- non-strict on the previous
bar, strict on the current one. The module implements exactly that, and NumPy
comparisons against NaN resolve to False, which is Pine's treatment of `na` in
a boolean context. Tested on a series deliberately full of exact equalities
and on a NaN warm-up prefix; identical to `pinesim` in both. Load-bearing for
the 200 EMA: while `maSlow` is NaN, `close > maSlow` is False and the Slow
point is simply not awarded, which is the chart's behaviour and is why a young
crypto listing caps at score 2.

## 11. NOT A DEFECT -- Wilder RMA seeding is Pine's, not `ewm(adjust=False)`

Pine's documented `pine_rma` is
`sum := na(sum[1]) ? ta.sma(src, length) : alpha*src + (1-alpha)*nz(sum[1])`,
i.e. seeded on the SMA of the first `length` values with `na` before.
`_recursive_ma(..., seed="sma")` does that and `ema_pine` does the same with
`alpha = 2/(span+1)`. `seed="first"` -- the pandas `ewm(adjust=False)`
behaviour with no warm-up NaN -- exists as an explicitly documented option and
is NOT the default. Warm-up lengths were checked against the chart's
observable behaviour and are exact: `rsi14` first value at bar 14, `ema20` at
19, `ema200` at 199, `macd_hist` at 33, `atr14` at 13. `pinesim.ta_rma` /
`ta_ema`, written independently from the same Pine reference, agree to 1e-9.

## 12. NOT A DEFECT -- the no-look-ahead test really is a truncation test

The pattern the brief warned about -- truncate the frame, then recompute from
the full frame -- is NOT what this does:

```python
full = evaluate(d, cfg)                 # once, on everything
for i in bars:
    cut = evaluate(d.iloc[: i + 1], cfg)   # recomputed from the TRUNCATED frame
    a = full.iloc[i]; b = cut.iloc[-1]     # bar i vs the truncated frame's LAST bar
```

`cut` is built from `d.iloc[:i+1]` and only its final row is read. The
self-test's second half is a second, independent check at the level the owner
reads: `screen_symbol(f.iloc[:i+1])` for every `i`, with the full-frame
`bull_div[i]` as the oracle.

I did not take this on reading. Two look-ahead bugs were planted in the
shipped module and both were caught:

```
MUT1 pivot stamped on the pivot bar : CAUGHT -> LOOK-AHEAD in 'pl_found' at bar 74
MUT3 centred (shift -2) moving avg  : CAUGHT -> LOOK-AHEAD in 'rsi_ma' at bar 60
clean                               : 81 cut points, no violation
```

Both mutations are now a permanent test
(`test_h_the_lookahead_proof_catches_a_planted_lookahead`). Two other
mutations (`valuewhen` occurrence 0, `shift_bool` by 0) were correctly NOT
caught by this test -- they are semantic errors, not timing errors, and they
have their own dedicated tests.

## 13. NOT A DEFECT -- gapped, duplicated and repeated index values

Every computation is positional (`.shift()`, `sliding_window_view`,
`np.searchsorted` over positions, `.to_numpy()` before every assembly), and
the index is only ever carried as a label. Verified: a 300-bar frame where
every bar shares one timestamp screens normally; a frame with one repeated
timestamp produces a `bull_div` array identical to the clean frame; a
six-session hole screens and passes the causality proof. `pd.concat(axis=1)`
inside `evaluate` does not raise on a duplicated index because all three
operands carry the identical index object. Business-day and holiday gaps are
invisible to the module by design -- limit 8 states that `bars_ago` counts
bars present in the frame, which is also what the chart does.

## 14. NOT A DEFECT -- interior NaN rows are dropped rather than filled

`prepare_frame` removes any row with a NaN in open/high/low/close. That is
faithful (Pine has no bar at all for a session that did not happen) and it is
also the only safe option: one interior NaN poisons every recursive average
for the remainder of a symbol's history. Verified that five NaN rows in the
middle of a 400-bar frame leave `rsi` and the 200 EMA finite at the last bar,
and that a NaN in ONE column drops the whole bar (also correct -- a bar with a
high but no low is not a bar). Dropping a row cannot create look-ahead: the
survivors keep their order and each still sees only its own past, and the
causality proof passes on the holed frame.

## 15. NOT A DEFECT -- a single-bar spike, and a descending-then-flat tape

A 10x one-bar spike in a flat series produces no divergence (one bar cannot be
both sides of a pivot window), no crash, and no look-ahead. A tape that slides
200 bars and then halts for 100 returns RSI 0 / `extreme-oversold` / no
signal, which is the correct mirror of the genuine `rma(up) == 0` case and
must NOT become NaN under finding 1's fix -- it is now pinned so a future
"simplification" of that branch cannot collapse the two.

## 16. NOT A DEFECT -- the score arithmetic, `max_score = 3`, and `close > maSlow` when `maSlow` is na

`bullScore = 1 + (useMacd and macdHist > 0 ? 1 : 0) + (useSlow and close >
maSlow ? 1 : 0) + (useRsi and rsiV > 50 ? 1 : 0)` is transcribed exactly,
including that the score is computed on every bar and only read on cross bars,
that `useRsi` ships FALSE so the real ceiling is 3 (not the `maxval = 4` on
Pine's `minScore` input), and that a NaN `maSlow` awards nothing. Differential
run confirms `bull_score`, `bear_score`, `bull_signal`, `bear_signal` element
for element. `cross_signal` correctly reads `close` for its RSI (the Top
script's `rsiV = ta.rsi(close, rsiLen)`) rather than `maSrc`.

---

# Diff applied

`vivek50_screen.py`, five hunks:

```
@@ ScreenConfig.validate            +9   reject a *_source outside OHLC_COLUMNS
@@ rsi_wilder (docstring)          -7/+18 the 0/0 case, corrected and explained
@@ rsi_wilder (body)               -3/+5  both_zero -> NaN
@@ prepare_frame                   +17   refuse a newest-first frame
@@ screen_symbol                   +8    validate the config into a row reason
@@ screen_symbol (verdict)         -1/+8 `direction` honours mode
@@ CAUSAL_COLUMNS                  -3/+16 17 columns -> 40
```

`vivek50_selftest.py`: two tests corrected (they pinned finding 1's wrong
value), **ten adversarial tests added**, 18 -> 28.

`sec_reference_impl.md`: KNOWN LIMIT 7 rewritten with the correction and the
reason the old defence was wrong; the embedded copies of both sources and the
verbatim console output in 6.7 re-synced; the test count updated.

New file `pinesim.py` -- the independent naive Pine interpreter. The
differential test imports it and skips cleanly if it is absent, so the
self-test still runs standalone.

---

# Final test output, after the fixes

```
==============================================================================
vivek50_screen self-test -- pandas 3.0.6, numpy 2.4.6
==============================================================================
warm-ups: rsi14=14  ema20=19  ema50=49  ema200=199  macdhist=33  atr14=13
  PASS  test_warmup_lengths_match_pine
rma alpha=1/4 seeded on SMA; ema alpha=0.4 seeded on SMA -- both confirmed
  PASS  test_rma_is_wilder_not_an_ema
rsi degenerate cases: all-up=100  all-down=0  flat=NaN (0/0)  ramp-then-halt=100
  PASS  test_rsi_degenerate_cases
crossover/crossunder: NaN-safe, previous-bar rule confirmed
  PASS  test_crossover_is_nan_safe_and_uses_the_previous_bar
pivot: confirmed exactly `right` bars late, value = the pivot's own
  PASS  test_pivot_is_confirmed_right_bars_late
in-range window: rangeLower..rangeUpper 5..60 means a 6..61 bar pivot gap
  PASS  test_the_barssince_off_by_one_sets_a_6_to_61_bar_window
valuewhen(cond, src, 1): NaN until two occurrences, then the previous one
  PASS  test_valuewhen_needs_two_occurrences
bull: 8 RSI pivot lows in the frame, exactly ONE divergence, on bar 129
      pivot bar 124   price low 79.5071 -> 77.2996 (lower)   RSI 3.97 -> 10.44 (higher)
      barssince(plFound[1]) = 49  (a 50-bar gap between pivots)
  PASS  test_a_bullish_divergence_fires_five_bars_after_the_pivot
bear: exactly ONE divergence, on bar 129 (pivot bar 124)
      price high 125.3258 -> 128.1205 (higher)   RSI 97.28 -> 89.47 (lower)
  PASS  test_b_bearish_divergence_fires_five_bars_after_the_pivot
score 3: bar 292  hist +1.3649  close 145.20  ema200 119.43  -> label 'Bullish +3'
  PASS  test_c_cross_with_macd_up_and_price_above_the_200_scores_three
score 1: bar 293  hist -0.2258  close 90.29  ema200 115.49  -> label 'Bullish +1'
        rejected by min_signal_score=2, detected again at min_signal_score=1
  PASS  test_d_cross_with_macd_down_and_price_below_the_200_scores_one
score arithmetic verified across all five switch combinations (1,2,2,3,4)
  PASS  test_the_score_is_arithmetic_not_a_lookup
flat 300-bar frame: 0 pivots, 0 divergences, 0 crosses, ATR 0, no exception
  PASS  test_e_a_flat_series_produces_nothing_and_does_not_crash
gaps / NaN rows / empty frame / junk frame: all handled, none raised
  PASS  test_gaps_and_nans_do_not_raise
no look-ahead: 223 cut points x 40 columns, all identical
                screen verdict re-run on 41 truncations: 0 mismatches
  PASS  test_f_no_look_ahead_anywhere
120-bar frame: screened, slow_ready=False, trend='unknown', max score 2
30-bar frame: refused with a reason, not an exception
  PASS  test_g_a_frame_shorter_than_the_slow_ma_is_sensible_not_fatal
mode 1 drops a score-3 cross; mode 2 keeps it. Both report both rules.
  PASS  test_mode_1_is_divergence_only
freshness: div_fresh_bars=N admits bars_ago 0..N-1, inclusive of today
  PASS  test_freshness_windows_are_in_bars
equal consecutive lows: strict=0 pivots, loose-right=1, loose-left=1, loose-both=2
  PASS  test_h_equal_consecutive_lows_make_no_pivot_under_the_strict_rule
single-bar 10x spike: screened, no divergence, no look-ahead
  PASS  test_h_a_single_bar_spike_does_not_leak_or_crash
descending frame: refused with a reason (backwards RSI would have read 60.2 against the true 38.9)
  PASS  test_h_a_descending_frame_is_REFUSED_not_screened
duplicated / repeated / gapped index: positional, identical verdicts
  PASS  test_h_a_duplicated_or_gapped_index_is_positional_and_harmless
interior NaN rows: dropped, recursive averages stay finite
  PASS  test_h_interior_nan_rows_are_dropped_and_do_not_poison_the_averages
descending-then-flat: RSI 0 (not NaN), extreme-oversold, no signal
  PASS  test_h_a_descending_then_flat_rsi_is_zero_not_undefined
mode 1: RULE B reported, and no longer able to set `direction`
  PASS  test_h_mode_1_does_not_let_rule_b_colour_the_direction
mistyped source: refused by validate(), reported as a row reason
  PASS  test_h_a_mistyped_source_is_refused_instead_of_silently_meaning_close
look-ahead proof: both planted bugs caught, module clean afterwards
  PASS  test_h_the_lookahead_proof_catches_a_planted_lookahead
differential vs a naive bar-by-bar Pine reading: 96 frame/convention pairs identical
  PASS  test_h_matches_a_naive_bar_by_bar_pine_reading

==============================================================================
SCREEN OUTPUT -- mode 2 (RULE A or RULE B), every symbol shown
==============================================================================
    symbol passes rules direction score best_bars_ago rule_a_direction rule_b_label  close  rsi   trend n_bars                               reason
BEARDIV.AX   True     A      bear                   0             bear              124.42 61.1 unknown    130
BULLDIV.AX   True     A      bull                   0             bull               81.30 41.1 unknown    130
SCORE3.NDQ   True     B      bull     3             0                    Bullish +3 145.20 70.5      up    293
   FLAT.AX  False                                                                    42.00         down    300
SCORE1.NDQ  False                                                                    90.29 63.1    down    294
  STALE.AX  False                                                                    88.00 73.1 unknown    141
  TINY-USD  False                                                                                           30 history too short (30 bars, need 60)
 YOUNG-USD  False                                                                    14.00 57.9 unknown    120

==============================================================================
28/28 tests passed
==============================================================================
```

Exit code 0. Note `FLAT.AX` on the row above: blank RSI, blank zone. That
column read `100.0 / extreme-overbought` before finding 1 was fixed.

Also re-run green after the fixes, unchanged: `cmp1.py` (18 differential
frames, 133 divergences, all identical), `worked_example.py`, `baserate.py`
(1.95 M symbol-days of base-rate arithmetic) and `cli_smoke.py` (64-symbol
end-to-end scan, exit 0, 10 hits).


---

# PART 6B - END-TO-END COMMAND LINE RUNNER

Part 6 gives you the tested indicator and screening module. This part ties it to a data
provider, applies the market gates from Part 5.6, and publishes the Part 5.8 payload.

**Status.** The screening module in Part 6 is tested (18/18 assertions). This runner has
been executed end to end against **synthetic frames** with the download call stubbed, which
exercises the gates, the screen, the ranking, the payload assembly and the atomic write.
The **download path itself has never run against a live provider**, because the sandbox it
was written in cannot reach one. That is the part to expect to rework.

## The verified run

Sixty synthetic symbols plus four deliberately broken ones: a flat/halted series, one below
the liquidity floor, one below the price floor, and one with only 90 bars of history. Run
against the module **after** the adversarial review's four fixes (Part 6A).

```
[run] nasdaq: 10 hits from 61 scanned (100% coverage) in 1.4s -> out_smoke/nasdaq_rsidiv.json
symbol rules direction  score  best_bars_ago  rule_a_pivot_bars_ago       rsi        regime      close
SYM023     B      bear    3.0            0.0                    NaN 37.170306 fast<mid<slow  56.093335
SYM022     A      bull    NaN            1.0                    6.0 43.939578 fast<mid<slow  14.233457
SYM009     B      bull    3.0            1.0                    NaN 54.696360 fast>mid>slow 241.420612
SYM048     B      bull    2.0            1.0                    NaN 63.774424         mixed  20.386664
SYM052     B      bear    2.0            1.0                    NaN 48.407909         mixed  33.596402
SYM032     B      bull    3.0            2.0                    NaN 51.368446 fast>mid>slow  68.093466
SYM026     B      bull    2.0            2.0                    NaN 56.527817         mixed  72.694960
SYM028     A      bear    NaN            3.0                    8.0 42.849255         mixed  15.899261
SYM051     B      bear    3.0            3.0                    NaN 39.183882         mixed  49.681977
SYM057     B      bear    3.0            3.0                    NaN 30.535087         mixed  75.529130

exit code: 0
payload keys : ['generated_at', 'market', 'timeframe', 'mode', 'params', 'summary', 'results', 'errors']
summary      : {"universe": 64, "downloaded": 64, "scanned": 61, "skipped": {"stale": 0, "price": 1, "liquidity": 1, "flat": 1}, "coverage": 1.0, "hits": 10, "errors": 0, "elapsed_s": 1.4, "hits_rule_a": 2, "hits_rule_b": 8, "hits_bull": 5, "hits_bear": 5, "hits_conflict": 0}
results      : 10

first result row:
   above_slow                 False
   atr                        1.3585320684
   atr_pct                    2.42
   best_bars_ago              0.0
   close                      56.0933350816
   direction                  bear
   fast                       58.6812410172
   history_warning            
   last_bar                   2025-09-05 00:00:00
   macd_hist                  -0.7452289538
   market                     nasdaq
   mid                        58.8279628986
   n_bars                     700
   ok                         True
   passes                     True
   reason                     
   regime                     fast<mid<slow
   rsi                        37.1703061027
   rsi_ma                     44.6229973873
   rsi_zone                   neutral
   rule_a                     False
   rule_a_bars_ago            None
   rule_a_bars_between_pivots None
   rule_a_direction           
   rule_a_label_bars_ago      None
   rule_a_pivot_bar           None
   rule_a_pivot_bars_ago      None
   rule_a_prev_price          None
   rule_a_prev_rsi            None
   rule_a_price_at_pivot      None
   rule_a_rsi_at_pivot        None
   rule_b                     True
   rule_b_above_slow          False
   rule_b_bar                 2025-09-05 00:00:00
   rule_b_bars_ago            0.0
   rule_b_below_slow          True
   rule_b_close               56.0933350816
   rule_b_direction           bear
   rule_b_label               -3 Bearish
   rule_b_macd_hist           -0.7452289538
   rule_b_max_score           3.0
   rule_b_score               3.0
   rule_b_signed_score        -3.0
   rules                      B
   score                      3.0
   slow                       59.5644446499
   slow_ready                 True
   symbol                     SYM023
   trend                      down
### What that output proves

| Claim | Evidence in the run |
|---|---|
| The gates work and are counted separately | `"skipped": {"stale": 0, "price": 1, "liquidity": 1, "flat": 1}` - each of the three broken symbols was rejected by the right gate |
| Both rules fire and are attributed | `hits_rule_a: 2`, `hits_rule_b: 8` out of 10 hits |
| Direction is resolved | `hits_bull: 5`, `hits_bear: 5`, `hits_conflict: 0` |
| The evidence is complete enough to review by eye | a Rule B row carries `rule_b_label: "-3 Bearish"`, the three score terms (`rule_b_macd_hist`, `rule_b_below_slow`), the bar it fired on, RSI, ATR, and the full MA stack |
| Rule A's lag is reported, not hidden | `rule_a_bars_ago` (knowable) and `rule_a_pivot_bars_ago` (the market event) are separate fields, five apart. See Part 5.3B |
| The payload is valid JSON | it round-tripped through `json.loads`, with NaN mapped to `null` rather than emitted as a bare `NaN` token that a browser's `JSON.parse` would reject |
| The write is atomic | temp file in the destination directory, then `os.replace` |

### Mode C is a post-filter, not a third screen

The module's `ScreenConfig.mode` takes **1** (Rule A only) or **2** (Rule A or Rule B).
Mode C - both rules, directions agreeing - is mode 2 plus a filter on the result, because
it is a *view* of the same computation rather than a different screen. The runner
implements it that way:

```python
both  = hits["rules"].str.contains("A") & hits["rules"].str.contains("B")
agree = hits["rule_a_direction"] == hits["rule_b_direction"]
hits  = hits[both & agree]
```

## The source

```python
#!/usr/bin/env python3
"""Vivek 5.0 daily screener - end-to-end command line runner.

Ties the reference implementation in ``vivek50_screen.py`` to a real data source
and publishes the JSON payload described in Part 5.8 of the specification.

This is a SCAFFOLD, not a finished product. It has been syntax-checked and its
logic reviewed, but it has NEVER been run against live market data, because the
sandbox it was written in cannot reach a data provider. Treat the download path
as the part most likely to need work.

Usage
-----
    python vivek50_scan_cli.py --market crypto --mode B --out ./out
    python vivek50_scan_cli.py --market asx --mode A --limit 200 --verbose
    python vivek50_scan_cli.py --market nasdaq --symbols AAPL,MSFT,NVDA

Exit codes
----------
    0  scan completed and published
    1  scan failed outright (no market data at all, or a write failure)
    2  scan completed but coverage was below the floor (a degraded run)
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
import time
from typing import Iterable

import pandas as pd

from vivek50_screen import ScreenConfig, screen_frames

# --------------------------------------------------------------------------
# Market metadata. Everything market-specific lives here and nowhere else.
# --------------------------------------------------------------------------

MARKETS: dict[str, dict] = {
    "asx": {
        "suffix": ".AX",
        "timezone": "Australia/Sydney",
        "min_price": 0.02,
        "min_dollar_adv": 250_000.0,
        "currency": "AUD",
        "coverage_floor": 0.85,
    },
    "nasdaq": {
        "suffix": "",
        "timezone": "America/New_York",
        "min_price": 1.00,
        "min_dollar_adv": 1_000_000.0,
        "currency": "USD",
        "coverage_floor": 0.85,
    },
    "crypto": {
        "suffix": "-USD",
        "timezone": "UTC",
        "min_price": 0.0,
        "min_dollar_adv": 5_000_000.0,
        "currency": "USD",
        "coverage_floor": 0.90,
    },
}

# A tiny built-in universe so the script is runnable before a real universe
# loader is wired in. Replace load_universe() with the real thing.
FALLBACK_UNIVERSE: dict[str, list[str]] = {
    "asx": ["BHP", "CBA", "CSL", "NAB", "WBC", "FMG", "WES", "MQG", "TLS", "WOW"],
    "nasdaq": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD",
               "NFLX", "INTC"],
    "crypto": ["BTC", "ETH", "SOL", "XRP", "ADA", "AVAX", "LINK", "DOT", "INJ",
               "ENS"],
}


def load_universe(market: str, limit: int | None = None) -> list[str]:
    """Return the list of provider symbols for a market.

    REPLACE THIS. In the owner's repository the real loader is
    ``scanner.universe.load_universe(market_key, full=True)``, which returns a
    list of dicts carrying symbol, name and (for ASX) sector, already suffixed
    for the provider and already filtered for stablecoins. See Part 9.
    """
    suffix = MARKETS[market]["suffix"]
    syms = [f"{s}{suffix}" for s in FALLBACK_UNIVERSE[market]]
    return syms[:limit] if limit else syms


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------

def download_daily(symbols: list[str], bars: int, batch: int = 150,
                   verbose: bool = False) -> dict[str, pd.DataFrame]:
    """Download daily OHLCV for every symbol, batched.

    Returns a dict of symbol -> DataFrame with columns Open/High/Low/Close/Volume
    and a DatetimeIndex. Symbols the provider does not return are simply absent;
    the caller decides what to do about that.

    The ``period`` is expressed in years because providers handle a bar count
    poorly. 750 daily bars is about three years.
    """
    try:
        import yfinance as yf
    except ImportError:  # pragma: no cover
        raise SystemExit("yfinance not installed: pip install yfinance")

    years = max(2, int(bars / 252) + 1)
    period = f"{years}y"
    frames: dict[str, pd.DataFrame] = {}

    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        if verbose:
            print(f"[data] batch {i // batch + 1}: {len(chunk)} symbols", flush=True)
        try:
            raw = yf.download(chunk, period=period, interval="1d",
                              group_by="ticker", auto_adjust=False,
                              progress=False, threads=True)
        except Exception as exc:  # network, rate limit, malformed response
            print(f"[data] batch failed: {exc}", file=sys.stderr, flush=True)
            continue

        for sym in chunk:
            try:
                df = raw[sym] if len(chunk) > 1 else raw
                df = df.dropna(how="all")
                if df.empty:
                    continue
                df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
                frames[sym] = df.tail(bars)
            except Exception:
                continue
        time.sleep(1.0)  # be polite; a throttled run is slower than a paced one

    return frames


def last_closed_bar_ok(df: pd.DataFrame, timezone: str, max_age_days: int) -> bool:
    """True when the frame's newest bar is recent enough IN THE MARKET's calendar.

    Fails CLOSED: an unusable timezone must never read as 'perfectly fresh'.
    See Part 7.8.
    """
    try:
        now = pd.Timestamp.now(tz=timezone).normalize()
    except Exception:
        return False
    try:
        last = pd.Timestamp(df.index[-1])
        if last.tzinfo is not None:
            last = last.tz_convert(timezone)
        else:
            last = last.tz_localize(timezone)
        return (now - last.normalize()).days <= max_age_days
    except Exception:
        return False


# --------------------------------------------------------------------------
# Publish
# --------------------------------------------------------------------------

def _json_default(o):
    """Make numpy scalars and NaN JSON-safe. allow_nan=False would otherwise
    raise on a field the screener legitimately leaves undefined."""
    try:
        import numpy as _np
        if isinstance(o, (_np.integer,)):
            return int(o)
        if isinstance(o, (_np.floating,)):
            f = float(o)
            return None if f != f else f
        if isinstance(o, (_np.bool_,)):
            return bool(o)
    except Exception:
        pass
    if isinstance(o, float) and o != o:
        return None
    return str(o)


def write_json_atomic(path: pathlib.Path, payload: dict) -> None:
    """Write JSON atomically: temp file in the same directory, then os.replace.

    A half-written payload that a front end reads is worse than no payload. The
    owner's repository requires this for every published artefact.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, indent=1, allow_nan=False, sort_keys=False,
                      default=_json_default)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def build_payload(market: str, mode: str, cfg: ScreenConfig, hits: pd.DataFrame,
                  stats: dict, errors: list[dict]) -> dict:
    """Assemble the Part 5.8 payload."""
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc)
                          .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "market": market,
        "timeframe": "1d",
        "mode": mode,
        "params": dataclasses.asdict(cfg),
        "summary": stats,
        "results": json.loads(hits.to_json(orient="records"))
                   if not hits.empty else [],
        "errors": errors,
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Vivek 5.0 daily screener")
    ap.add_argument("--market", required=True, choices=sorted(MARKETS))
    ap.add_argument("--mode", default="B", choices=["A", "B", "C"],
                    help="A = divergence only; B = divergence OR score>=2; "
                         "C = both, direction-aligned")
    ap.add_argument("--symbols", default=None,
                    help="comma-separated override of the universe")
    ap.add_argument("--limit", type=int, default=None,
                    help="scan only the first N symbols (for testing)")
    ap.add_argument("--bars", type=int, default=750)
    ap.add_argument("--div-fresh", type=int, default=1,
                    help="RULE A recency window in CLOSED bars (see Part 5.3)")
    ap.add_argument("--signal-fresh", type=int, default=1,
                    help="RULE B recency window in CLOSED bars")
    ap.add_argument("--min-score", type=int, default=2,
                    help="RULE B threshold on abs(score); reachable set is {1,2,3}")
    ap.add_argument("--out", default="./out", help="output directory")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)

    meta = MARKETS[args.market]
    started = time.time()

    if args.symbols:
        universe = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        universe = load_universe(args.market, args.limit)
    if args.verbose:
        print(f"[run] {args.market}: {len(universe)} symbols, mode {args.mode}",
              flush=True)

    frames = download_daily(universe, args.bars, verbose=args.verbose)
    coverage = len(frames) / len(universe) if universe else 0.0
    if not frames:
        print("[run] no data returned for any symbol", file=sys.stderr)
        return 1

    errors: list[dict] = []
    gated: dict[str, pd.DataFrame] = {}
    skipped = {"stale": 0, "price": 0, "liquidity": 0, "flat": 0}
    for sym, df in frames.items():
        if not last_closed_bar_ok(df, meta["timezone"], 3):
            skipped["stale"] += 1
            errors.append({"symbol": sym, "stage": "freshness",
                           "error": "last bar older than max_data_age_days"})
            continue
        last = float(df["Close"].iloc[-1])
        if last < meta["min_price"]:
            skipped["price"] += 1
            continue
        adv = float((df["Close"] * df["Volume"]).tail(20).mean())
        if adv < meta["min_dollar_adv"]:
            skipped["liquidity"] += 1
            continue
        tail = df["Close"].tail(20)
        if float(tail.max() - tail.min()) == 0.0:
            skipped["flat"] += 1           # halted / stablecoin: see Part 7.5
            continue
        gated[sym] = df

    # ScreenConfig mirrors the Pine inputs; mode 1 = RULE A only, 2 = A or B.
    # Mode C (confluence) is not a ScreenConfig mode: it is mode 2 plus a
    # post-filter, because "both rules, directions agreeing" is a view of the
    # same computation rather than a different screen.
    cfg = ScreenConfig(
        mode=1 if args.mode == "A" else 2,
        min_signal_score=args.min_score,
        div_fresh_bars=args.div_fresh,
        signal_fresh_bars=args.signal_fresh,
    )

    hits = screen_frames(gated, cfg, market=args.market)
    if args.mode == "C" and not hits.empty:
        both = hits["rules"].astype(str).str.contains(r"A") & \
               hits["rules"].astype(str).str.contains(r"B")
        agree = hits["rule_a_direction"] == hits["rule_b_direction"]
        hits = hits[both & agree].reset_index(drop=True)

    stats = {
        "universe": len(universe),
        "downloaded": len(frames),
        "scanned": len(gated),
        "skipped": skipped,
        "coverage": round(coverage, 4),
        "hits": int(len(hits)),
        "errors": len(errors),
        "elapsed_s": round(time.time() - started, 1),
    }
    if not hits.empty:
        stats["hits_rule_a"] = int(hits["rule_a"].astype(bool).sum())
        stats["hits_rule_b"] = int(hits["rule_b"].astype(bool).sum())
        d = hits["direction"].astype(str)
        stats["hits_bull"] = int((d == "bull").sum())
        stats["hits_bear"] = int((d == "bear").sum())
        stats["hits_conflict"] = int((d == "conflict").sum())

    out = pathlib.Path(args.out) / f"{args.market}_rsidiv.json"
    payload = build_payload(args.market, args.mode, cfg, hits, stats, errors)
    write_json_atomic(out, payload)

    print(f"[run] {args.market}: {stats['hits']} hits from {stats['scanned']} "
          f"scanned ({stats['coverage']:.0%} coverage) in {stats['elapsed_s']}s "
          f"-> {out}")
    if not hits.empty:
        cols = [c for c in ("symbol", "rules", "direction", "score",
                            "best_bars_ago", "rule_a_pivot_bars_ago",
                            "rsi", "regime", "close") if c in hits.columns]
        print(hits[cols].head(25).to_string(index=False))

    if coverage < meta["coverage_floor"]:
        print(f"[run] WARNING coverage {coverage:.0%} below floor "
              f"{meta['coverage_floor']:.0%}: results are degraded",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

## What to change first when you wire in a real provider

1. **`load_universe()`** - replace the ten-symbol fallback. Inside the owner's repository
   the real call is `scanner.universe.load_universe(market_key, full=True)`; see Part 9.
2. **`download_daily()`** - the yfinance call is a placeholder. Whatever you use, keep the
   three properties that matter: batching, a retry with backoff, and a per-batch failure
   that does not abort the run.
3. **Add the cache** - Part 7.7. Fill provider dropouts from a last-good cache, and refuse
   any cached frame older than ten days. Without the ceiling a fossil price will fabricate
   a signal; without the cache a single throttled batch silently shrinks the universe.
4. **Check `last_closed_bar_ok()` against a real calendar.** The implementation here
   compares calendar days in the market's timezone, which is right for crypto and
   approximately right for equities. For the ASX and NASDAQ a real exchange calendar
   (holidays, half-days) is better; `pandas_market_calendars` does this.


---

# PART 7 - REPAINTING, LOOK-AHEAD, AND THE TRAPS THAT WILL BITE YOU

If you implement everything else in this document perfectly and get this section wrong,
you will ship a screener that looks excellent and is worthless. Every item below is a real
failure mode, and several of them were found the hard way in this repository's own history.

## 7.1 THE BIG ONE - the divergence confirmation lag

`ta.pivotlow(rsi, 5, 5)` returns a value **on the bar 5 bars after the pivot**. It cannot
do otherwise: deciding that bar `k` is a local low requires seeing the 5 bars after `k`.

The Pine script then draws the label with `offset = -5`, which places the visual marker
back at the pivot bar. **The label's position on screen is 5 bars earlier than the moment
the information existed.**

```
bar index:    ... 40   41   42   43   44   45   46   47 ...
RSI pivot low:         ^ bar 42 is the pivot
plFound true:                              ^ bar 47 (42 + 5)
label drawn at:        ^ bar 42 (offset -5)
```

Consequences, all of which you must handle:

1. **`bars_ago` must be counted from the confirmation bar (47), never the pivot bar (42).**
   A row reporting "divergence 0 bars ago" when the pivot was at bar 42 and today is bar 47
   is correct under this document's definition and would be a 5-bar look-ahead under the
   naive one.
2. **The earliest a divergence can be screened is 5 bars after the pivot.** There is no way
   to make the screener faster without changing `R`, and lowering `R` makes the pivot
   definition weaker (more, noisier pivots). `R = 5` matched to `L = 5` is the TradingView
   default and is what the template uses. Do not "improve" the latency by dropping `R`.
3. **A backtest that scans the historical `bull_div` series is honest only if it enters on
   the confirmation bar's close or later.** Entering at the pivot bar is the classic
   divergence-backtest fraud and will show a spectacular, unreachable equity curve.
4. Report **both** dates in the output (`confirmed_date` and `pivot_date`) so the owner can
   see the lag rather than infer it. When he opens the chart, the label will be at
   `pivot_date` and he needs to know why the scanner said a different day.

## 7.2 The forming bar

The last row a data provider gives you for "today" is, during market hours, an
**incomplete** bar. Its close is the current price, its high and low are partial. Every
indicator computed on it moves continuously.

Rules:

- Determine the last **closed** bar explicitly. For equities: the last bar whose session
  has ended in the market's own timezone. For crypto: the last bar whose UTC day has ended.
- Do not trust the provider to omit the forming bar. `yfinance` with `interval="1d"`
  returns a partial bar for the current session, with a timestamp of today's date.
- The safest implementation is to compute everything on `df.iloc[:-1]` if the last bar's
  date equals "today" in the market's timezone and the session has not closed. Make that
  decision once, in one function, and log which bar was chosen.
- A pivot involving the forming bar is doubly wrong: it can appear and vanish within a
  session. Truncate first, compute second.

## 7.3 The `barssince(plFound[1])` off-by-one

The range gate in the Pine source is:

```pine
f_inRange(cond) =>
    bars = ta.barssince(cond == true)
    rangeLower <= bars and bars <= rangeUpper
inRangeL = f_inRange(plFound[1])
```

Note it is `plFound[1]`, the value of `plFound` on the **previous** bar, not `plFound`.

On a bar `i` where `plFound` is true, `ta.barssince(plFound[1])` counts the bars since the
condition "`plFound` was true one bar ago" last held. If the previous pivot confirmed on
bar `p`, then `plFound[1]` was true on bar `p+1`, so the count is `i - (p + 1)`.

So the implemented gate is:

```
5 <= (i - p - 1) <= 60        where p = the previous plFound bar
```

equivalently the pivot confirmations are between 6 and 61 bars apart.

This is inherited verbatim from TradingView's built-in Divergence Indicator, which has the
same `[1]`. It is almost certainly a quirk rather than an intention, but **reproduce it
exactly**: the goal is that the scanner agrees with the chart the owner is looking at, not
that it implements the Platonic ideal of a range filter. If you "fix" it to `i - p`, your
scanner will disagree with his chart on boundary cases and he will not know which to trust.

Write a test that pins this arithmetic with a hand-built series.

## 7.4 SEEDING: the naive pandas equivalent is NOT Pine, and it matters for the 200-EMA

This correction is measured, not argued, and it overturns the obvious shortcut.

### What Pine actually does

`ta.rma` (Wilder's average, used inside `ta.rsi` and `ta.atr`) and `ta.ema` both:

- **seed with a simple average of the first `length` values**, and
- **return `na` for every bar before that**.

The recurrences themselves are ordinary:

```
rma[i] = (rma[i-1] * (period - 1) + x[i]) / period      # alpha = 1/period
ema[i] = alpha * x[i] + (1 - alpha) * ema[i-1]          # alpha = 2/(span+1)
```

### What `pandas.ewm(adjust=False)` does

Seeds with the **first value** and emits a number from bar 0, with no warm-up `na`.

### The two cases behave completely differently, and that is the trap

The seeding error decays by `(1 - alpha)` per bar, so how much survives depends entirely on
alpha:

| Series | alpha | Share of the seed error left after 500 bars | Verdict |
|---|---|---|---|
| RSI 14 (`ta.rma`) | 1/14 = 0.0714 | `(0.9286)^500` = about 1e-17 | **Irrelevant.** Measured 5.67 RSI points off at the seed, 0.40 off 36 bars later, and nothing measurable by bar 200. |
| ATR 14 | 1/14 | same | Irrelevant beyond warm-up. |
| EMA 20 | 2/21 = 0.0952 | about 1e-22 | Irrelevant. |
| EMA 50 | 2/51 = 0.0392 | about 3e-9 | Irrelevant. |
| **EMA 200** | **2/201 = 0.00995** | **about 0.67%** | **MATTERS.** Measured 0.247 price units adrift at bar 600 of a ramp. |

**0.247 price units is enough to flip `close > slow`**, which is one of the two scoring
terms in Rule B. A symbol sitting near its 200-EMA can score 3 under one seeding convention
and 2 under the other. That is a visible disagreement between your scanner and the owner's
chart, on the exact boundary the screen cares about.

### What to do

1. **Implement the Pine seeding.** It is a few lines: compute the SMA of the first `length`
   values, use it as the seed, and emit NaN before it. The reference implementation in
   Part 6 does this by default and exposes `ema_seed` / `rma_seed` flags so you can compare.
2. **Do NOT reuse `scanner/indicators.py` as-is for Rule B.** Its `ema()`, `rsi()` and
   `atr()` all use `ewm(adjust=False)` from bar 0. They are fine for the repository's
   existing lenses, which were built around them, and they are fine here for RSI and ATR.
   They are **not** fine for the 200-EMA term. (Its `pivot_lows()`/`pivot_highs()` are
   separately unusable here; see 7.11 and Part 9.)
3. **Give every symbol enough history.** 750 daily bars is the recommendation. With only
   250 bars an EMA200 is still carrying about 60% of its seed error under either convention
   and the term is not trustworthy at all.
4. **Flag `slow_ready`.** A symbol with fewer than `slow_len` bars has no 200-EMA, the term
   contributes 0, and the score is capped at 2. Surface that rather than letting it look
   like a weak signal.

The general lesson, worth carrying beyond this document: **a recursive average's seed
matters in inverse proportion to its alpha.** Short averages forget their seed almost
immediately; a 200-period average remembers it for thousands of bars.

## 7.5 Ties in a flat series, and the one convention nobody could verify

Two separate issues live here. The first is settled, the second is not.

### Settled: a flat region must not produce pivots

If the RSI is exactly constant across a window, a naive
`series == series.rolling(w, center=True).min()` test makes **every** bar simultaneously a
maximum and a minimum, so you get a pivot on every bar and a cascade of nonsense
divergences behind it.

Halted ASX small caps, delisted-but-still-quoted names and stablecoins all produce exactly
this. Guard it twice:

- Never use the bare `== rolling().min()` trick. Compare the centre bar against the window
  **with the centre removed**, or write the explicit loop.
- Reject frames whose last 20 bars have zero price range, before computing anything.

The reference implementation in Part 6 has a test asserting **zero** pivots on a perfectly
flat 300-bar series.

### NOT settled: strict vs non-strict comparison at a tie

Whether Pine's `ta.pivotlow` requires the centre bar to be **strictly** lower than its
neighbours, or merely **less than or equal**, is **not stated anywhere in TradingView's
documentation**. It was searched for and is genuinely absent. Nobody involved in writing
this document had a TradingView chart available to settle it empirically.

The size of the disagreement was measured rather than assumed. Over 300 tick-rounded random
walks producing about 3,380 divergences, the two conventions disagree on **27 of them, or
0.8%** - and critically, **not in one direction**:

| | Count |
|---|---|
| Fire only under strict | 10 |
| Fire only under non-strict | 17 |

It is not that one convention is a superset of the other. An extra intervening pivot under
the non-strict rule re-bases what "the previous pivot" means, which can push an otherwise
valid divergence outside the 6-to-61-bar window and remove it.

**What to do**: make it a configuration flag, default to strict (which is the safer
behaviour because it is the one that cannot fire on a flat series), and **settle it
empirically** as part of the Level 2 validation in Part 10.2. Load a symbol with a visible
flat patch in its RSI, see whether TradingView marks a pivot there, and set the flag to
match. Then write the answer down here, because it is a five-minute check that nobody has
yet done and it will otherwise be re-litigated forever.

Do not let this become a reason to delay: 0.8% of divergences is a rounding error against
the uncertainty in every other part of this system.

## 7.6 The crossover with NaN warm-up

`ta.crossover(a, b)` requires `a[i] > b[i]` and `a[i-1] <= b[i-1]`. With NaN values, every
comparison is false in both Pine and pandas, so no cross fires during warm-up. Good.

The trap is a **manufactured cross at the first non-NaN bar**: if you `fillna(0)` or
`dropna()` mid-stream, the 200-EMA suddenly appearing can look like a cross. Never fill
indicator NaNs. Let them propagate and let the freshness window ignore them.

## 7.7 Fossil prices from a cache

This repository fills symbols that the data provider dropped on a given run from a
last-good cache (`scanner/data.py::merge_with_cache`). That is right for the ordinary case
and catastrophic without a ceiling: a symbol the provider has not returned since March,
served from cache, presents a six-month-old close as today's price and will happily
generate a fresh "cross today".

The existing guard is `FRAME_CACHE_MAX_AGE_DAYS = 10`: a cached frame older than that is
refused outright and the symbol is reported as unpriced rather than scanned. **Reuse it.**
Refusing a frame can only ever remove a name from the screen, never add one, which is the
safe direction.

Also publish, per run, the share of frames that came from cache (`data_from_cache` in the
summary). A run that is 60% cache is a run whose results should be distrusted, and that is
only visible if you measure it.

## 7.8 Data age must be measured in the market's calendar

A frame whose last bar is Friday, evaluated on Sunday, is fresh for the ASX and stale for
crypto. Measuring age against the runner's UTC clock understates ASX staleness by a day
(this exact bug existed in this repository: `_frame_age_days` used the runner's naive local
date). Pass the market's timezone in, and make the fallback fail **closed** - an unusable
timezone must not return "0 days old, perfectly fresh".

## 7.9 Split and dividend adjustments moving history under you

If your provider hands you dividend-adjusted prices, then every historical price changes on
every ex-dividend date. A divergence confirmed last week off an unadjusted low may not be
confirmable today off the adjusted series. Your screener will appear to "lose" signals it
previously reported.

Pick one adjustment policy, write it in the output `params`, and never change it silently.
Split adjustment is mandatory (otherwise a 10:1 split fabricates a 90% crash). Dividend
adjustment is optional; TradingView's default chart is split-adjusted only, so matching
that keeps the scanner and the owner's eye in agreement.

## 7.10 Survivorship bias in any backtest you run off this

The universes here are **today's** listings. Delisted names are absent. Any historical
study of these rules run on this universe will overstate performance, because the names
that went to zero and got removed are not in the sample. State it wherever you report a
backtest number. This repository's own Turtle-lens documentation makes the same disclosure
for the same reason.

## 7.11 Indicator-on-indicator pivots use RSI, not price

The pivots in Rule A are pivots **of the RSI series**, not of price. Price's own low is
then read at the same bar index. Getting this backwards (finding price pivots and reading
RSI at them) produces a different and much noisier signal that will superficially resemble
divergence. Re-read the Pine: `ta.pivotlow(rsi, lbL, lbR)`.

## 7.12 One-symbol failures must not take down the market

A single malformed frame (all-NaN close, duplicate index, one-row frame) should produce an
error row for that symbol and let the other 2,199 finish. Wrap the per-symbol body in a
try/except that records the symbol, the stage and the message. This repository learned this
the hard way too: every per-ticker exception used to be swallowed with no output, so a name
that threw every night was indistinguishable from one that never set up.

## 7.13 Determinism

Two runs over the same frames must produce byte-identical output, or the owner cannot diff
today's list against yesterday's. That means: no dict iteration order dependence in the
ranking, a final alphabetical tie-break, floats rounded at the publish boundary (not
mid-computation), and a `generated_at` that is the only field expected to change.


---

# PART 8 - MARKET-SPECIFIC NOTES

## 8.1 ASX

- **Symbols** carry a `.AX` suffix for Yahoo (`BHP.AX`). The repository's universe loader
  produces these; see Part 9.
- **Size**: about 2,200 listed entities. The large majority are illiquid: the liquidity
  gate in 5.6 typically removes half to two-thirds of the universe before any indicator is
  computed, which is also where most of your runtime saving lives.
- **Sector data is good.** The ASX listing file carries a GICS sector for every name, so
  sector is available for free and worth putting in the output.
- **Non-operating listings are a real problem.** Listed Investment Companies (AFI, BTI,
  HM1, RG8) carry no FUND/TRUST/ETF word in their names and will pass a naive keyword
  filter. The repository already solved this with a word-boundary matcher plus explicit
  name patterns; reuse `_product_tag` rather than re-deriving the list.
- **DST**: Sydney runs UTC+10 (AEST) April-October and UTC+11 (AEDT) October-April. See
  5.11 and 7.8.
- **Session**: 10:00-16:00 local, with a pre-open auction from 07:00 and a closing auction
  to 16:12. The daily bar is settled well before the 06:30 UTC run time in either half of
  the year.
- **Tick sizes** are coarse at low prices (0.1 cent below 10 cents). A 2-cent stock moves
  5% in one tick, which is why `MIN_PRICE` exists.

## 8.2 NASDAQ

- **Symbols** are bare (`AAPL`). Class shares use a dot or hyphen depending on the
  provider (`BRK.B` vs `BRK-B`) - normalise once, in the universe loader.
- **Size**: about 1,430 names in the Global Select tier the repository scans. The full
  NASDAQ listing is roughly 4,000 including Capital Market tier microcaps; the Global
  Select restriction is a deliberate quality filter.
- **Sector data is absent** from the NASDAQ symbol file. The repository backfills sectors
  from a cache built by per-symbol profile lookups (`data/sector_map.json`). Expect sector
  to be missing for a meaningful share of NASDAQ rows and design the output so a missing
  sector is a blank, not a crash.
- **Preferred lines, warrants, rights and notes** are listed alongside common stock
  (STRF, STRD, MCHPP). Same product filter as ASX.
- **Earnings dates** cause overnight gaps that manufacture pivots and crosses. This
  screener does not filter on earnings, but the existing scanner has an
  `EARNINGS_BUFFER_DAYS` concept; consider surfacing "earnings within N days" as a flag so
  the owner can skip a name whose signal is really just a gap.

## 8.3 Crypto

- **Symbols**: Yahoo uses `BTC-USD`. Exchange feeds (Binance) use `BTCUSDT`. The owner's
  charts are Binance `*USDT` pairs, so the scanner's Yahoo `-USD` series will differ
  slightly from what he sees (different venue, different close, no funding). Say so in the
  output rather than pretending they are the same series.
- **Size**: top 100 by market cap plus extras, so about 100-120 names. Small enough that
  the whole market scans in under a minute.
- **The daily bar boundary is 00:00 UTC.** There is no session. A "3 bar" freshness window
  is 3 calendar days, not 3 trading days.
- **Stablecoins must be excluded.** USDT, USDC, DAI and friends are flat by construction:
  they produce the flat-series pivot cascade from 7.5 and nothing else. The repository's
  universe loader has an `_is_stable` predicate; use it.
- **24/7 means the forming bar is always forming.** There is no close to wait for other
  than the UTC boundary, so the truncation rule in 7.2 is the only thing standing between
  you and a signal that evaporates.
- **Wrapped and staked derivatives** (WBTC, stETH) track their underlying and will
  duplicate signals. Consider de-duplicating by underlying so the shortlist does not show
  the same idea three times.


---

# PART 9 - INTEGRATION WITH THE EXISTING GOOGY SCANNER REPOSITORY

Target repo: `/home/user/googy-boys-scanner` (Vivek 5.0).
Everything below was read out of the working tree at HEAD, not recalled. Every
signature, default and constant is quoted from the file named beside it, with
line numbers where they help. ASCII only.

Scope of this document: **how a new lens plugs into THIS repository.** The Pine
semantics themselves (what "Bull"/"Bear" and "Bullish +N" mean bar by bar) are
covered only where they bind a Python API choice - and where they do, the
off-by-one is spelled out, because two of them are load-bearing.

---

## 0. Corrections to the brief

These are places where the task text as handed to me was wrong or incomplete.
None of them changes the goal; all of them change the code that would be written.

1. **"Rule B: ... |score| >= 2 (i.e. 'Bullish +2', 'Bullish +3', '-2 Bearish',
   '-3 Bearish')" - the enumeration is right, but only by accident of the
   defaults, and the reason matters.** `Final_Top_Script.pine:580` computes
   `maxScore = 1 + (useMacd ? 1 : 0) + (useSlow ? 1 : 0) + (useRsi ? 1 : 0)`.
   The shipped defaults are `useMacd = true` (line 87), `useSlow = true`
   (line 88), **`useRsi = false`** (line 89). So the live max is **3**, not 4,
   and `+4` is unreachable unless the owner ticks "+1 when RSI agrees". A
   scanner that hard-codes a 4-term score will silently disagree with the
   chart. Make the RSI term a config flag that defaults to OFF.
2. **`minScore` is not 2.** `Final_Top_Script.pine:90` defaults `minScore = 1`,
   so the chart PRINTS every cross, including `+1`. "score >= 2" is a
   *scanner-side* filter the owner is asking for, not something the template
   already does. Do not implement it by "reading minScore" - implement it as
   its own constant.
3. **"the Top overlay has printed a scored cross signal" - a signal only exists
   on the exact bar of the cross.** `bullSig = showSig and bullX and bullScore
   >= minScore` where `bullX = ta.crossover(maFast, maMid)` (line 212). There
   is no "still showing" state on the overlay's arrows. The script separately
   REMEMBERS the last one in `var sigBar/sigDir/sigScore` (lines 255-266) and
   calls it fresh for `autoMaxAge` bars (`sigFresh`, line 280), but that is the
   trade-box's notion, not the arrow's. So Rule B must state which it means.
   The literal reading of the brief ("has printed ... as of the latest closed
   daily bar") is the cross-bar-only reading; that is what I have specified,
   with a config'd N-bar widening as the owner's likely real intent.
4. **The RSI+ divergence pivots are on the RSI SERIES, not on price.**
   `Final_RSI_Plus.pine:43-44` - `plFound = not na(ta.pivotlow(rsi, lbL, lbR))`.
   Price is only ever *sampled at the RSI pivot bar*
   (`priceLL = low[lbR] < ta.valuewhen(plFound, low[lbR], 1)`). This matters
   here because the repo's `indicators.pivot_highs()/pivot_lows()` take a
   **DataFrame** and read `df["High"]`/`df["Low"]`. They are structurally the
   wrong tool: there is no price-pivot step in this divergence at all. See
   section 3.
5. **`scanner/indicators.py` has no divergence helper, and no Series-level
   pivot helper.** Nothing in `scanner/` computes a divergence today - I
   grepped the whole package for `diverg`, and every hit is REGIME's
   index-vs-median divergence, which is an unrelated concept. This is new code,
   not a wiring job.
6. **"ASX (~2,200), NASDAQ (~1,430), crypto (~100)" is right for the live
   directories but is not what a local run gets.** `universe.load_universe()`
   fetches live directories and falls back through a committed snapshot cache
   to a small bundled CSV. A sandbox with no network yields the bundled list
   (about 94 ASX names). Any test must pass its own universe.

---

## 1. `scanner/universe.py` - the ticker universe

### `load_universe(market_key: str, full: bool = True) -> list[dict]`

Line 289. `market_key` is one of `"asx" | "nasdaq" | "crypto"` (the keys of
`config.MARKETS`). There is no `"all"` here - that is an argparse convenience
in the runners.

**Row shape - exactly four keys, always all four present:**

```python
{"symbol": "BHP",           # UPPERCASE plain ticker, the display/scan key
 "name":   "Bhp Group Ltd", # ASX names are Title()-cased by _pretty(); NASDAQ
                            # and crypto names come through verbatim
 "sector": "Materials",     # ASX: GICS from the directory CSV.
                            # NASDAQ: ALWAYS "" (the symbol file has no sector
                            #         column) - see _fetch_nasdaq_listed, line 231
                            # crypto: ALWAYS "" from CoinGecko
 "yf":     "BHP.AX"}        # symbol + market.suffix - the Yahoo ticker
```

The scalp universe (`load_scalp_universe`, line 262) additionally carries
`"type"` and reads `yf` from the CSV. It is a different, cross-asset list and is
irrelevant to a daily market scanner.

### Per-market suffix convention

Suffix lives on `config.MARKETS[key].suffix` and is applied exactly once, in
`universe.py`, when the row is built. Nothing downstream re-appends it.

| market | suffix | Yahoo form | currency | tz |
|---|---|---|---|---|
| asx | `.AX` | `BHP.AX` | AUD, `A$` | `Australia/Sydney` |
| nasdaq | `""` | `AAPL` | USD, `$` | `America/New_York` |
| crypto | `-USD` | `BTC-USD` | USD, `$` | `UTC` |

`config.py:1405-1424`.

### Universe sources and the two caches

1. **Live directory fetch** (`full=True`): ASX from
   `asx.com.au/asx/research/ASXListedCompanies.csv` with a full browser header
   set (`_ASX_HEADERS`, line 68 - a WAF started refusing the honest UA around
   2026-07-25); NASDAQ from `nasdaqtrader.com .../nasdaqlisted.txt` filtered to
   Market Category `Q` (Global Select) with ETFs, test issues and
   non-`N` Financial Status dropped; crypto from CoinGecko top-130, stablecoins
   and wrapped tokens dropped by `_is_stable` (any `<X>USD` ticker plus an
   explicit set), truncated at 100, then `config.CRYPTO_EXTRA_SYMBOLS`
   (`["XMR", "FLASH"]`) pinned on.
2. **Last-good snapshot**: `data/universe_cache/<market>.json`, written by
   `_save_universe_cache` only when the fetch returned at least
   `_CACHE_MIN[market]` rows (`asx 400 / nasdaq 400 / crypto 40`). Committed by
   scan.yml. This is the first fallback.
3. **Bundled CSV**: `data_universe/<market>_tickers.csv`, columns
   `symbol,name[,sector]`. Last resort, and `load_universe` prints
   `universe: WARNING <market> running on the bundled fallback CSV` when it
   reaches it under `full=True`.

**Integration consequence:** a new scanner calls `load_universe(m, full=True)`
and nothing else. Do not re-derive the Yahoo ticker; use `row["yf"]`. Do not
assume `row["sector"]` is populated - on NASDAQ and crypto it is empty string
for every row.

---

## 2. `scanner/data.py` - download, cache, validation

### `download(tickers, period=None, interval="1d", chunk=None, retries=None) -> dict[str, pd.DataFrame]`

Line 275. Defaults resolve from config: `period = config.DATA_PERIOD` ("1y"),
`chunk = config.DATA_CHUNK` (120), `retries = config.DATA_RETRIES` (3), plus
`DATA_BACKOFF = [2, 5, 12]`, `DATA_BATCH_PAUSE = 0.4`, `DATA_HEAVY_AFTER = 3`,
`DATA_HEAVY_COOLDOWN = 25`, `DATA_RECOVERY_COOLDOWN = 20`.

Strategy: a fast main pass over batches of `chunk`, then ONE recovery sweep over
whatever failed - and only if `frames` is non-empty and `len(failed) < total`
(so a total outage does not pay the cooldown). Returns `{yf_ticker: DataFrame}`,
keyed by the ticker string you passed in. **A ticker Yahoo did not return is
simply ABSENT from the dict** - there is no error entry, no None value.

It never raises for a dead ticker. It logs
`download: ZERO tickers returned for N requested` at ERROR on a total outage.

### The frame contract

`yf.download(..., group_by="ticker", auto_adjust=True, threads=True,
progress=False)` then `df = data[ticker].copy()` then `df = df.dropna()`.

* **Columns (exact, capitalised):** `Open`, `High`, `Low`, `Close`, `Volume`.
  With `auto_adjust=True` there is **no `Adj Close` column** - prices are
  already split- and dividend-adjusted.
* **Index:** a `pandas.DatetimeIndex`. For `interval="1d"` from yfinance it is
  tz-naive dates at midnight. Not a column - `turtle_run._with_date_column()`
  (line 36) exists precisely to normalise it to a `Date` column when an engine
  wants one, and it is deliberately duplicated rather than shared
  ("the two lenses are deliberately independent and a shared private helper is
  how a coupling starts").
* **Sorted ascending**, oldest first. `df.iloc[-1]` is the newest bar.
* **`.dropna()` has already run**, so a frame has no all-NaN rows, but a name
  with a short listing history simply has fewer rows.
* Volume on crypto is **already USD dollar-volume** - see
  `MarketConfig.volume_is_usd` and `scan._liquidity`.

### `merge_with_cache(market_key, fresh, tickers) -> tuple[dict, dict]`

Line 105. Fills tickers absent from `fresh` out of the last-good per-market
cache, subject to the **fossil ceiling**
`config.FRAME_CACHE_MAX_AGE_DAYS = 10` (config.py:1254). A cached frame whose
newest bar is more than 10 days old in the MARKET's calendar is refused, named
in a WARNING, and counted - it does NOT reach the scanner.

Returned `stats` dict, exactly five integer keys:

```python
{"fresh": len(fresh), "reused": <filled from cache>, "merged": len(merged),
 "universe": len(tickers), "stale_dropped": <fossils refused>}
```

It also **writes** the cache as a side effect, capped to the tickers you passed
(so delisted names age out), via `save_frame_cache`.

### THE CACHE HAZARD A NEW SCANNER MUST NOT TRIP

`_cache_path` (line 28) is `\.cache/frames/<market_key>.pkl.gz` - **keyed by
market only. The download PERIOD is not part of the key.** Every existing caller
downloads five years before merging:

| caller | period |
|---|---|
| `scanner/run.py:168` | `config.VIVEK_DATA_PERIOD` = `"5y"` |
| `scanner/turtle_run.py:242` | module `PERIOD = "5y"` |
| `scanner/regime.py:591` | `getattr(config, "VIVEK_DATA_PERIOD", "5y")` |
| `scanner/broker/vivek_run.py:1676` | `config.VIVEK_DATA_PERIOD` = `"5y"` |

`scanner/spec_run.py:112` downloads `period="2y"` and **deliberately does not
call `merge_with_cache`** - it uses a bare `data.download`.

So the rule, which is not written down anywhere else in the repo and is worth
writing into the new module's docstring: **if you call `merge_with_cache`, you
must download 5 years.** A scanner that merged a 2y download would overwrite the
shared cache with short frames and silently break the 200-week-SMA lens, the
Turtle 250-bar floor and REGIME's six-month window on the next run. If a new
lens genuinely wants a shorter history, it must bypass the cache entirely
(the spec_run pattern) and accept lower coverage on throttled nights.

### `validate_bars(df, symbol="", interval="1h", min_bars=None, staleness_hours=None) -> None`

Line 160. Raises `data.DataQualityError` (line 156). Defaults
`min_bars = config.SCALP_DATA_MIN_BARS` (65) and
`staleness_hours = config.DATA_STALENESS_HOURS` (4). Checks: empty frame,
`len(df) < min_bars`, `Close` more than 10% NaN, last close non-finite or <= 0,
and - **only for `interval in ("1m","5m","15m","30m","1h")`** - bar age. Passing
`interval="1d"` skips the staleness leg entirely. No daily scanner in this repo
calls it; they all do their own `len(df) < MIN_BARS` check. It is available but
is not the house pattern for a daily lens.

### `_frame_age_days(df, tz=None) -> int`

Line 66. How many days old the newest bar is, **measured in the market's own
calendar** when `tz` is given (TOP100 #23). `tz=None` falls back to the runner's
naive local date and is wrong by up to a day in both directions. An unusable tz
logs a WARNING and falls back rather than returning 0 - deliberate, because
"perfectly fresh" is the one answer a freshness check must never guess. Returns
`max(0, ...)` and returns 0 on any exception.

Call it as `_frame_age_days(df, market.timezone)`. It is underscore-prefixed but
is imported across module boundaries already (`scan.py:15`), so that is an
accepted usage, not a violation.

### `load_frame_cache(market_key) -> dict[str, pd.DataFrame]` / `save_frame_cache(market_key, frames) -> None`

Lines 32 and 46. `load` returns `{}` on any failure. `save` is atomic
(temp + replace) and **refuses to write an empty dict** - so a run where Yahoo
returned nothing leaves the previous cache intact. Tests that need a warm cache
seed it with `save_frame_cache`; `tests/conftest.py` redirects `_CACHE_DIR` to a
tmp_path for every test automatically (autouse fixture, line 21).

---

## 3. `scanner/indicators.py` - every public function, and the pivot verdict

160 lines, seven public functions, all pandas-based, all taking either a Series
or an OHLCV DataFrame with the capitalised column names above.

| function | signature | semantics / gotchas |
|---|---|---|
| `ema` | `ema(series, span) -> Series` | `series.ewm(span=span, adjust=False).mean()`. Recursive form. **Matches Pine's `ta.ema` in steady state**; differs only in seeding (Pine seeds an EMA with an SMA of the first `length` values, pandas `adjust=False` seeds with the first value). The residual decays by `(1 - 2/(span+1))` per bar: over 1,250 daily bars a 200-EMA's seeding error is down by a factor of about `3e-5`. Negligible past roughly `5 x span` bars; discard the warm-up anyway. |
| `sma` | `sma(series, window) -> Series` | `series.rolling(window).mean()`. NaN for the first `window-1` bars. Exactly `ta.sma`. |
| `rsi` | `rsi(series, period=14) -> Series` | Wilder's RSI via `ewm(alpha=1/period, adjust=False)` on the gain/loss legs. **Matches `ta.rsi(src, len)` in steady state** (Pine's `ta.rsi` is `ta.rma`-smoothed, the same Wilder recursion), same seeding caveat as `ema`. **TOP100 #71:** the tail is `out.mask((avg_loss == 0) & (avg_gain > 0), 100.0)` - so a genuine 100 survives, but **warm-up bars and a flat/halted series both come back NaN** rather than the old `.fillna(100)`. That is a gift for a divergence scanner: a suspended name cannot manufacture a pivot. |
| `atr` | `atr(df, period=14) -> Series` | Wilder-smoothed True Range. Note `turtle.compute_n` calls `atr(df, 20)` on the grounds that `N = (19*PDN + TR)/20` *is* Wilder at 20. |
| `supertrend` | `supertrend(df, period=14, mult=3.0) -> Series` | Trailing line. Bit-identical numpy rewrite (TOP100 #73, 25x faster). Irrelevant to this lens. |
| `pivot_highs` | `pivot_highs(df, window=3) -> Series` | See below. |
| `pivot_lows` | `pivot_lows(df, window=3) -> Series` | See below. |
| `adx` | `adx(df, period=14) -> Series` | Standard DMI/ADX, `.fillna(0)` tail. |

There is **no MACD helper.** `ta.macd(close, 12, 26, 9)` has to be built from
`ema`: `macd = ema(c,12) - ema(c,26); signal = ema(macd, 9); hist = macd -
signal`. That is three lines and it is exactly what Pine does, so build it in
the new engine (or add `macd()` to `indicators.py` - see section 7, it is the
better choice and costs one extra test).

### `pivot_highs` / `pivot_lows` vs Pine's `ta.pivothigh` / `ta.pivotlow`

The shipped code, in full (lines 125-139):

```python
def pivot_highs(df: pd.DataFrame, window: int = 3) -> pd.Series:
    """Local maxima of High: a bar whose High is >= the `window` bars on each side."""
    high = df["High"]
    cond = pd.Series(True, index=df.index)
    for k in range(1, window + 1):
        cond &= (high >= high.shift(k)) & (high >= high.shift(-k))
    return high[cond]
```

`pivot_lows` is the mirror with `Low` and `<=`.

**Verdict: they cannot be used for this divergence, for four independent
reasons. Only the fourth is about the window being symmetric.**

1. **Wrong input type - and this is the disqualifying one.** They take a
   DataFrame and hard-read `df["High"]` / `df["Low"]`. The RSI+ divergence needs
   pivots **on the RSI series** (`ta.pivotlow(rsi, lbL, lbR)`), and there is no
   overload that accepts a Series. Wrapping the RSI in a fake DataFrame
   (`pd.DataFrame({"High": rsi, "Low": rsi})`) would work mechanically but is a
   lie the next reader has to unpick, and it still leaves reasons 2-4.
2. **Wrong return shape for timing work.** They return a **sparse Series**: the
   `High`/`Low` VALUES at pivot bars, indexed by those bars' dates. Callers in
   this repo consume them as `...dropna().tail(3).tolist()` (`vivek.py:50`) -
   i.e. as a bag of price levels with the dates thrown away. A divergence needs
   the opposite: the bar INDEX of each pivot, to measure the gap between two of
   them and to sample `low`/`rsi` at that bar. You would be reconstructing
   positions from a filtered index on every call.
3. **Tie handling is non-strict on BOTH sides (`>=` / `<=`), which Pine's is
   not.** A flat plateau of three equal highs marks all three as pivots here.
   For a price-structure lens (what these were written for) that is harmless -
   duplicate levels collapse. For a divergence it is not: two "pivots" one bar
   apart both pass, `rangeLower = 5` then rejects them, and the real prior pivot
   is skipped because `ta.valuewhen(..., 1)` would have pointed at the
   duplicate. It changes which pair gets compared.
   *Honest limit:* I could not verify Pine's exact tie rule from inside this
   sandbox (no Pine compiler exists in a cloud session - the repo says so at
   `CLAUDE.md`, TRADINGVIEW TEMPLATES section). Treat "Pine is strict on both
   sides" as the working assumption to be confirmed on a chart, and make
   strictness a named constant so confirming it is a one-line change rather
   than a rewrite.
4. **Symmetric only.** One `window` argument feeds both `shift(k)` and
   `shift(-k)`. Pine's defaults here happen to be symmetric
   (`lbL = 5`, `lbR = 5`, `Final_RSI_Plus.pine:29-30`), so `window=5` reproduces
   the DEFAULT config - but the inputs are independent and the owner can set
   `lbL = 10, lbR = 3` in the UI, which this helper cannot express at all.

**The one thing they get RIGHT, and which the new helper must preserve:**
`high.shift(-k)` looks FORWARD, so the last `window` bars of the frame can never
satisfy `cond` (the shifted values are NaN and every comparison against NaN is
False). That is not a bug, it is exactly Pine's `lbR` confirmation delay
expressed in pandas: **a pivot at bar `t` is only knowable at bar `t + lbR`, and
neither implementation peeks.** Any new pivot helper must have the same
property, and a test should pin it, because a naive `argrelextrema`-style
implementation using a centred window WOULD peek and would produce divergences
that were not visible on the chart on the day claimed.

### The two off-by-ones a Python port must get exactly right

Both are in `Final_RSI_Plus.pine:43-60` and both come from Pine's `[lbR]`
indexing.

**(a) The signal bar is not the pivot bar.** `bullDiv` becomes true on the bar
where the pivot is CONFIRMED, which is `lbR = 5` bars after the pivot itself.
The label is then drawn back at the pivot with `offset = -lbR`. So
"a Bull label printed as of the latest closed daily bar" means:
`bullDiv[latest_closed_bar] == True`, whose pivot sits at index `-1 - lbR`
(the 6th-from-last bar with `lbR = 5`). Screening on "the most recent pivot"
instead of "the most recent confirmation" is a 5-bar error in the wrong
direction - it would report divergences five days before the chart shows them.

**(b) The pivot-separation window is measured off a SHIFTED condition.**

```
inRangeL = f_inRange(plFound[1])
f_inRange(cond) => bars = ta.barssince(cond == true)
                   rangeLower <= bars and bars <= rangeUpper
```

`plFound[1]` is `plFound` shifted one bar later, so at the current bar `c` the
most recent true occurrence of `plFound[1]` is at `p_prev + 1`, where `p_prev`
is the PREVIOUS pivot's confirmation bar (the current one, at `c`, gives
`c + 1`, which is in the future and unavailable). Therefore
`bars = c - p_prev - 1`, and with `rangeLower = 5`, `rangeUpper = 60`:

> **the gap between the two pivot confirmation bars must satisfy
> `6 <= (c - p_prev) <= 61`**, not `5 <= gap <= 60`.

A Python port that writes `5 <= gap <= 60` will admit and reject different pairs
at both ends of the window. Write it as `rangeLower + 1 <= gap <= rangeUpper + 1`
with a comment pointing at `plFound[1]`, or the next reader will "fix" it.

**(c) `ta.valuewhen(plFound, X, 1)` means occurrence index 1 = the one BEFORE
the current.** Since `plFound` is true on the bar being evaluated, occurrence 0
is now. So the comparison is current pivot vs immediately previous pivot - not
"two pivots ago".

---

## 4. `scanner/config.py` - conventions, market metadata, and the existing gates

2,080 lines, flat module-level constants, no classes except `MarketConfig`.
Project rule 3 (`CLAUDE.md`): **"any new threshold/constant goes in
`scanner/config.py` before use"**. There is no per-lens config file; every lens
namespaces itself with a prefix in this one file.

### Naming conventions, observed

* **`UPPER_SNAKE`, prefixed by lens or subsystem.** Live prefixes:
  `VIVEK_*` (and `VIVEK_BOT_*` for the executor), `REV_*`, `SPEC_*`,
  `TURTLE_*`, `REGIME_*`, `SECTOR_BREADTH_*`, `SCAN_*`, `DATA_*`,
  `WATCHDOG_*`, `ALERT_*`, `MORNING_PLAYS_*`, `PHASEMAP` lives in its own
  `phasemap/config.py`.
* **Per-market values are dicts keyed by market key with a `"default"` entry**
  where a miss is possible: `VIVEK_BOT_MIN_PRICE = {"asx": 0.05, "nasdaq": 1.0,
  "crypto": 0.0, "default": 0.0}`. Where a miss is not possible (`LIQUID_TIER`,
  `VIVEK_BOT_LEVERAGE`) there is no `default` and callers use
  `.get(key, fallback)`.
* **`0` means "off"** by convention for ceilings and windows
  (`FRAME_CACHE_MAX_AGE_DAYS`, `VIVEK_BOT_MAX_STOP_PCT`,
  `MORNING_PLAYS_DEDUP_DAYS`, `SCAN_ERROR_SAMPLE_MAX`,
  `TURTLE_THROTTLE_RETRY_COOLDOWN_S`). Say so in the comment.
* **Every non-obvious constant carries a block comment giving the measured
  rationale and, where one exists, the near-miss it was tuned against.** This
  is enforced socially, not by test, but a bare number with no comment will read
  as an oversight to every subsequent reader of this file.
* Consumers read optional/new constants through
  `getattr(config, "NAME", default)` so an old checkout does not explode
  (see `scan.py:283`, `run.py:172`, `turtle_run.py:507`). Use this for anything
  a committed artefact or another workflow might predate.

### `MarketConfig` - the market metadata record

`config.py:1392-1424`, a frozen dataclass. **There is no `session` field on it.**

```python
@dataclass(frozen=True)
class MarketConfig:
    key: str                  # "asx"
    label: str                # "ASX"
    suffix: str               # ".AX" | "" | "-USD"
    currency: str             # "AUD" | "USD"
    currency_symbol: str      # "A$" | "$"
    timezone: str             # IANA, e.g. "Australia/Sydney"
    tz_label: str             # "AEST" | "ET" | "UTC"
    liquidity_min: float      # min average daily turnover, LOCAL currency
    volume_is_usd: bool = False   # crypto: Yahoo Volume is already dollar-volume
```

Session hours live **separately**, in `config.VIVEK_JOURNAL_SESSION`
(`config.py:347`), as `{market: (open_h, open_m, close_h, close_m)}` in market
local time, with **crypto deliberately absent** (no session). That absence is
load-bearing - `scan._bar_is_forming` (line 138) reads
`config.VIVEK_JOURNAL_SESSION.get(market_key)` and treats a missing entry as
"today's bar forms until UTC midnight", i.e. crypto's bar is always still
forming on the current UTC day.

### The gates that already exist - reuse these, do not reinvent

| what | constant / expression | asx | nasdaq | crypto | where enforced |
|---|---|---|---|---|---|
| Liquidity floor (hard drop) | `MARKETS[m].liquidity_min`, local currency | 100,000 | 1,000,000 | 3,000,000 | `scan.py:254` |
| How that turnover is measured | `LIQUIDITY_LOOKBACK = 20` bars; `mean(Close*Volume)` for equities, `mean(Volume)` for crypto | - | - | - | `scan._liquidity`, line 108 |
| "LIQUID" cosmetic tier | `LIQUID_TIER` | 1,000,000 | 20,000,000 | 100,000,000 | `scan.py:173, 405` |
| ADV floor the BOT applies | `VIVEK_BOT_MIN_ADV` | 250,000 | 2,000,000 | 0 | `broker/vivek_bot.py` |
| Min price the BOT applies | `VIVEK_BOT_MIN_PRICE` | 0.05 | 1.00 | 0.00 | `broker/vivek_bot.py` |
| Max size vs ADV | `VIVEK_BOT_MAX_NOTIONAL_PCT_ADV = 2.0` (%) | - | - | - | bot only |
| Stale-frame refusal (bot won't open) | `VIVEK_BOT_MAX_DATA_AGE_DAYS = 3` | - | - | - | bot only |
| Cached-frame fossil ceiling | `FRAME_CACHE_MAX_AGE_DAYS = 10` | - | - | - | `data.merge_with_cache` |
| Intraday staleness | `DATA_STALENESS_HOURS = 4` | - | - | - | `validate_bars`, intraday only |
| Minimum bars, generic daily lenses | `MIN_HISTORY = 160` | - | - | - | legacy pullback scanner |
| Minimum bars, VIVEK daily | `VIVEK_MIN_HISTORY = 220` | - | - | - | `vivek.evaluate` |
| Minimum bars, Reversals / Specs | `REV_MIN_HISTORY = 230` / `SPEC_MIN_HISTORY = 230` | - | - | - | those engines |
| Minimum bars, Turtle | `TURTLE_MIN_BARS = 250` | - | - | - | `turtle_run.py:276` |
| Coverage floor that REFUSES to publish | `TURTLE_MIN_COVERAGE_PCT = 60.0` | - | - | - | `turtle_run.py:319` |
| Small-universe absolute miss cap | `TURTLE_SMALL_UNIVERSE_MAX = 30`, `..._MAX_MISSING = 2` | - | - | - | `turtle_run.py:309` |
| Coverage "LOW" warning (does not gate) | `SCAN_COVERAGE_LOW_PCT = 80`, `SCAN_COVERAGE_MIN_UNIVERSE = 50` | - | - | - | `run.py:172` |
| Published rows cap | `TURTLE_MAX_ROWS = 400` | - | - | - | `turtle_run.py:293` |
| Error-sample caps | `SCAN_ERROR_SAMPLE_MAX = 12`, `_MSG_MAX = 160`, `_KINDS_MAX = 4`, `_LOUD_PCT = 5.0` | - | - | - | `scanerrors.ErrorLog` |
| One-market retry after throttling | `TURTLE_THROTTLE_RETRY_COOLDOWN_S = 180.0` (0 = off) | - | - | - | `turtle_run.main` |
| Download tuning | `DATA_CHUNK 120`, `DATA_RETRIES 3`, `DATA_BACKOFF [2,5,12]`, `DATA_BATCH_PAUSE 0.4`, `DATA_HEAVY_AFTER 3`, `DATA_HEAVY_COOLDOWN 25`, `DATA_RECOVERY_COOLDOWN 20` | - | - | - | `data.py` |
| Drop the still-forming bar | `VIVEK_DROP_FORMING_BAR = True` + `VIVEK_JOURNAL_SESSION` | - | - | - | `scan.py:230`, `scan._bar_is_forming` |
| Deep download period | `VIVEK_DATA_PERIOD = "5y"` | - | - | - | every `merge_with_cache` caller |
| Fund / LIC / preferred display flag | `PRODUCT_NAME_PATTERNS` + `scan._product_tag` | - | - | - | display only, fenced from `broker/` |

**Which of those a divergence scanner should actually adopt**, and why (this is
the short answer to "reuse rather than reinvent"):

* **`MARKETS[m].liquidity_min` with `LIQUIDITY_LOOKBACK = 20` and
  `scan._liquidity`'s exact crypto branch.** Use the same floor as VIVEK so the
  two lenses agree on what is tradeable. `_liquidity` is private to `scan.py`;
  copy its four lines into the new engine with a comment naming the source
  (the repo's own precedent: `turtle_run._with_date_column` duplicates
  `spec_run`'s helper on purpose), or - better - promote it to
  `indicators.turnover(df, market)` and have `scan.py` call that. Promoting it
  touches `scan.py`, which is in the hot path, so the copy is the lower-risk
  choice for a first cut.
* **`VIVEK_DROP_FORMING_BAR` + `_bar_is_forming`.** Non-negotiable for this
  lens. "As of the latest CLOSED daily bar" is the entire premise of the brief,
  and crypto's bar is forming all day. Reproduce `scan.py:246-248` verbatim.
* **A minimum-bars floor of your own.** `slowLen = 200` EMA plus `longLen = 50`
  RSI average plus a divergence lookback of `rangeUpper = 60` means the honest
  floor is roughly `200 (EMA warm-up) x 3 + 61`. Set
  `RSIDIV_MIN_BARS = 250` and match Turtle rather than invent a number.
* **A coverage floor.** Copy Turtle's `MIN_COVERAGE_PCT` posture exactly: refuse
  to publish over a good file with a gutted one. This is the single most
  valuable thing to steal, and the reasoning in `turtle_run.py:297-303` is worth
  reading before writing the new copy.
* **Do NOT adopt the `VIVEK_BOT_*` gates.** Those are executor gates on a
  ringfenced file. A report-only scanner that applied them would be claiming an
  eligibility opinion it has no business having, and `tests/test_product_flag.py`
  exists because exactly that boundary got crossed once before.

---

## 5. `scanner/output.py` - write_json and the atomic-write contract

```python
def write_json(path, payload, *, indent=2, separators=None, sort_keys=False,
               ensure_ascii=True, newline=False) -> pathlib.Path
```

Line 129. Three guarantees, each of which was a live defect (module docstring):

1. **Non-finite floats are nulled, recursively, before serialisation**
   (`_finite`), and `allow_nan=False` then stands behind it as a backstop. One
   bare `NaN` token in a market payload makes the browser's `response.json()`
   reject the ENTIRE file - a blank page for one bad bar. `_finite` rebuilds
   containers rather than mutating, so the caller's payload is untouched.
2. **The write is atomic** - it delegates to
   `journal_common.atomic_write(path, text, newline="\n")`, which is temp file
   plus `os.replace`. A reader sees the whole old file or the whole new one,
   never a fragment. `newline="\n"` is pinned so a Windows run cannot rewrite
   every published artefact with CRLF.
3. **`_default` handles numpy scalars** (`np.float32`, `np.int64`, `np.bool_`)
   via `.item()`, guarded by `ndim == 0` so a one-element ndarray is NOT
   silently flattened to a scalar. Anything else re-raises `TypeError` - an
   ndarray or datetime in a payload is a producer bug and failing here is how it
   gets found.

**Rule 7 of the project rules is "atomic writes for any journal/state JSON", and
`tests/test_publish_integrity.py` pins the exemption list.** There are exactly
two hand-rolled writers left (`universe._save_universe_cache`,
`sectorcache.save_cache`), both already atomic and both string/int-only. A third
one would trip that test. **A new scanner must publish through
`output.write_json` and nothing else.**

House formatting, by precedent:

* `turtle_run.py:361`: `output.write_json(path, payload, indent=1,
  ensure_ascii=False, newline=True)`
* `regime.publish` / `sectorbreadth.update` / `output.write_vivek_pair`:
  `indent=None, separators=(",", ":")` (compact; measured 39.6% of the ASX
  deck's first paint was indentation before this).
* For a new report-only lens publishing a few hundred rows a night, follow
  Turtle: `indent=1, ensure_ascii=False, newline=True`. It keeps the committed
  diff readable, which matters because these files land in git ~once a night.

`output.write(payload, out_dir, name=None)` (line 122) is a thin legacy helper
that names the file from `payload["market"]`; no current lens uses it for a
per-market lens file. Ignore it.

`output.split_vivek` / `write_vivek_pair` are VIVEK's summary/detail payload
diet and are not a general pattern.

---

## 6. `scanner/scanerrors.py` - the per-ticker error convention

One class, `ErrorLog`:

```python
ErrorLog(label: str, *, sample_max=None, msg_max=None,
         kinds_max=None, loud_pct=None)
```

Caps default from config **at construction, not at import**, so a test can
monkeypatch config without reloading.

* **`label` must identify BOTH lens and market** - `f"vivek [{market_key}]"`,
  `f"turtle [{market_key}]"`. A full cycle prints three of these back to back.
* `record(symbol, exc)` - never raises. `_clean` guards `str(exc)` because an
  exception is free to define a `__str__` that itself throws, and this runs
  inside the handler that is swallowing an error on purpose.
* `report(scanned)` - prints the one-line summary and returns it.
  **Called on EVERY run, including clean ones**: "no line" and "the accounting
  never ran" look identical in a log, and a standing `0 failed of 2212` is what
  makes a jump to `41 failed` legible. Prefixes `!! ` when the failure rate
  reaches `SCAN_ERROR_LOUD_PCT` (5.0%).
* `payload(prefix="")` -> `{f"{prefix}errors": int, f"{prefix}error_sample":
  [{"symbol", "error"}]}`. Splatted into the published dict as `**errors.payload()`.
  The sample takes **one row per distinct exception KIND first**, so a systemic
  flood does not crowd out the one rare failure.
* Messages are ASCII-folded (`encode("ascii","replace")`) - project rule 9
  applies to whatever a third-party exception put in its message.
* `prefix` is how one payload carries two failure modes without summing them
  (`scan.py` publishes `errors`/`error_sample` for setup failures and
  `price_errors`/`price_error_sample` for mark failures, because "41 names
  missing from the page" and "41 names on the page with no price" want
  different responses).

Additive by construction - `payload()` needs **no schema bump**, and bumping
would be actively harmful (it marks every already-committed file as a build
behind and shows a stale-data warning on the site until all markets rescan).

---

## 7. `scanner/run.py` - how a market loop is actually structured

`run.py` is the VIVEK entry point (`python -m scanner.run [--market ...]`),
482 lines. Shape of the loop (lines 158-311):

```
for market_key in markets:                       # ["asx","nasdaq","crypto"] or the flag
    market = config.MARKETS[market_key]
    try:
        universe   = load_universe(market_key, full=not args.curated)
        universe   = universe[:args.limit]                    # if --limit
        fresh      = download([u["yf"] for u in universe], period=config.VIVEK_DATA_PERIOD)
        deep_frames, cache_stats = merge_with_cache(market_key, fresh,
                                                    [u["yf"] for u in universe])
        print coverage line, flag '!! LOW' under SCAN_COVERAGE_LOW_PCT
        if not deep_frames:                       # source fully blocked
            _record_skip(market_key)              # writes .scan-skipped for scan.yml
            _scan_health(market_key, published=False)
            continue                              # KEEP yesterday's JSON, exit 0
        frames = {t: df.tail(config.DATA_DAILY_BARS) for t, df in deep_frames.items()}
        vk = scan.scan_vivek_market(market_key, out_root=args.out,
                                    universe=universe, frames=deep_frames,
                                    pulse_data=[], progress=False,
                                    from_cache=cache_stats["reused"])
        output.write_vivek_pair(vk, args.out, market_key)     # <- THE PUBLISH
        _scan_health(market_key, published=True)
        ... funnelhistory.append / regime.compute / slim prices file
        ... history_archive.update / vivek_run.run_market (the bot)
    except Exception as e:
        print(f"  ERROR scanning {market_key}: {e}")
        failed_markets.append((market_key, f"{type(e).__name__}: {e}"))
# ... sectors / breadth / regime.publish / fx / bot_rules.json publish ...
if failed_markets:
    raise SystemExit(1)          # AFTER every publish, deliberately
```

Five structural decisions a new runner should copy:

1. **One download per market, reused by everything.** Frames are fetched once at
   `VIVEK_DATA_PERIOD` and handed down; the daily-tail slice
   (`df.tail(config.DATA_DAILY_BARS)`, `DATA_DAILY_BARS = 252`) is derived, not
   re-downloaded. A new nightly lens runs in its own workflow and therefore pays
   its own Yahoo walk - which is exactly why it must share `.cache/frames`
   (section 2).
2. **A fully-blocked download is a `continue`, not an exception.** It keeps
   yesterday's file and exits 0, and records the fact in `.scan-skipped`
   (gitignored, per-run) so `scan.yml` can downgrade that market's
   `assert_staged` to a warning. `tests/test_workflow_hardening.py:614-692` pins
   the whole discriminator.
3. **Per-market failures are COLLECTED and raised at the very end**, after every
   publish step, so one market's bad frame cannot stop the others' surfaces
   updating (TOP100 #67; see the comment at `run.py:461`).
4. **Report-only side computations are wrapped `try/except` and print
   `skipped (...)`** - `funnelhistory`, `regime`, `sectorbreadth`,
   `history_archive`, `fx`, the bot. A report artefact must never kill a scan.
5. **Every publish goes through `output.write_json`** (or `write_vivek_pair`,
   which wraps it).

`turtle_run.main()` (line 472) is the cleaner template for a standalone lens:
argparse -> per-market `try/except` collecting `failed` -> **one in-run retry of
just the failed markets after `TURTLE_THROTTLE_RETRY_COOLDOWN_S`** -> `return 1`
if any still failed, with `sys.exit(main())` at module bottom. Copy this
wholesale.

---

## 8. `scanner/scan.py` - one published VIVEK row, in full

`scan_vivek_market(market_key, limit=None, full=True, out_root=None,
progress=True, universe=None, frames=None, pulse_data=None, from_cache=0)
-> dict` (line 155).

**It does not write `<market>_vivek.json`.** It returns the payload; the write
happens in `run.py:217` via `output.write_vivek_pair(vk, args.out, market_key)`
(`scanner/output.py:180`), which publishes the pair
`public/data/<market>_vivek.json` (summary) and
`public/data/<market>_vivek_detail.json` (heavy fields), both compact
(`indent=None, separators=(",",":")`) and both carrying the same
`schema_version` and `generated_at` so the CI schema gate can catch a run that
pushed one and lost the other. The only file `scan_vivek_market` writes itself
is `public/data/<market>_arriving.json`, and only when `out_root` is passed.

### Every field on one result row

Built at `scan.py:360-411`, plus one added afterwards by `_finalize_vivek`:

| field | type | meaning |
|---|---|---|
| `symbol` | str | plain ticker (universe `symbol`, falls back to the yf ticker) |
| `name` | str | company / coin name |
| `sector` | str | universe sector; `""` on NASDAQ and crypto |
| `sector_count` | int | **added by `_finalize_vivek`**, line 557: how many rows share this sector this scan |
| `is_product` | bool | DISPLAY-ONLY fund/LIC/preferred flag (`_product_tag`); fenced from `scanner/broker/` |
| `dir` | `"LONG"`/`"SHORT"` | |
| `setup_type` | `"vivek"` | lens tag |
| `grade` | `"A+"/"A"/"B+"/"WATCH"` | displayed, hysteresis-held and gated |
| `grade_raw` | same domain | unsmoothed and gated - **what the bot buys** |
| `score` | int | points |
| `score_max` | int | `config.VIVEK_SCORE_MAX` (10) |
| `chips` | list[str] | fired signal names + gate notes |
| `level_tf` | str | which timeframe's 200-SMA is being reacted to |
| `level` | float | the SMA price |
| `at_level` | bool | within `VIVEK_AT_LEVEL_TOL` |
| `reaction` | dict | the reaction descriptor from `vivek.evaluate` |
| `entry_types` | list[str] | fired trigger when armed, else heuristic |
| `armed` | bool | a trigger fired on the gated timeframe |
| `armed_tf` | str/None | `"1W"`/`"3D"`/`"1D"` |
| `grade_held_runs` | int | hysteresis state, read back next scan |
| `entry_trigger` | str/None | headline plan's trigger |
| `trigger_bar` | - | headline plan's trigger bar |
| `sma_proxy` | bool | TOP100 #72 - True when the "200-SMA" is a short-history stand-in |
| `sma_window` | int | the window actually used |
| `plans` | dict | `{"1D": {...}, "3D": {...}, "1W": {...}}` - **heavy, moved to the detail sidecar** |
| `markers` | list | chart markers - heavy, sidecar |
| `confluence` | - | from the signal |
| `price` | float | last close, 8dp |
| `headline_tf` | str | `armed_tf or "1D"` - labels which plan the headline numbers come from |
| `entry`,`stop`,`tp1`,`tp2`,`tp3`,`scale`,`risk`,`rr` | float / list | the headline plan's numbers |
| `rr_text` | str | `f"{rr:.1f}:1"` |
| `liquidity` | `"LIQUID"`/`"OK"` | vs `LIQUID_TIER[market]` |
| `turnover` | int | rounded 20-bar average turnover |
| `data_age_days` | int | raw-frame age in the market's calendar; 0 = fresh |
| `spark` | list[float] | last `SPARK_BARS` (30) closes |
| `detail` | dict | heavy, sidecar |
| `analysis` | str | plain-English narrative - heavy, sidecar |

`config.VIVEK_DETAIL_ROW_FIELDS = ("plans", "detail", "analysis", "markers")` is
the split boundary; `VIVEK_SUMMARY_PLAN_FIELDS` prunes each surviving plan.

### Top-level payload keys

`market`, `label`, `setup_type`, `schema_version`, `code_sha`, `currency`,
`currency_symbol`, `timezone`, `tz_label`, `generated_at` (market-local ISO,
seconds), `scanned`, `downloaded`, `from_cache`, `fresh`, `universe_size`,
`coverage_pct`, `score_max`, `sma`, `sector_counts`, `funnel` (with
`universe`, `with_data`, `no_setup`, `illiquid_setup`, `below_score`, `no_plan`,
`errors`, `setups`, `grades`, `illiquid_sample`, `arriving`), `pulse`,
`results`, `prices`, `price_age`, `errors`, `error_sample`, `price_errors`,
`price_error_sample`.

Note `"sma": config.VIVEK_SMA` is a **config echo (always 200)**, not the window
in use - a test says so, because reading it as the live window is the exact
mistake `sma_proxy` exists to prevent.

### The two lines any new daily lens must copy verbatim

```python
now = dt.datetime.now(ZoneInfo(market.timezone))          # scan.py:185
age = _frame_age_days(df, market.timezone)                # scan.py:249
if (config.VIVEK_DROP_FORMING_BAR and len(df)
        and _bar_is_forming(market_key, df.index[-1].date(), now)):
    df = df.iloc[:-1]                                     # scan.py:246-248
```

`_bar_is_forming` (line 138) returns False for any bar dated before today in the
market tz; for today's bar it returns True while the market is still open, and
**always True for crypto** (no `VIVEK_JOURNAL_SESSION` entry -> forms until UTC
midnight). Without this the scanner's answer changes intraday, which for a
"latest closed daily bar" screen is the whole game.

### The funnel-counter pattern

`funnel = {"no_setup": 0, "illiquid_setup": 0, "below_score": 0, "no_plan": 0}`,
incremented at each `continue` point, published as a self-contained block with a
**pinned identity**: `with_data == no_setup + illiquid_setup + below_score +
no_plan + errors + setups`. A new lens should publish the same shape with its own
stage names and pin the same identity in its test - it converts "is this filter
too tight?" from a feeling into a number, and it is the single cheapest
observability win in this repo.

---

## 9. THE INTEGRATION GUIDE: adding the RSI-divergence / scored-cross lens

Working name below: **RSIDIV**. Constants prefix `RSIDIV_`, files
`scanner/rsidiv.py` (engine) + `scanner/rsidiv_run.py` (runner), published
artefact `public/data/<market>_rsidiv.json`, workflow
`.github/workflows/rsidiv.yml`, tests `tests/test_rsidiv.py`.

**Split engine from runner.** Every lens here does
(`vivek.py`/`scan.py`, `spec.py`/`spec_run.py`, `turtle.py`/`turtle_run.py`),
and the fence tests in `tests/test_turtle.py:1148-1200` are shaped around that
split: the runner is the file allowed to write, the engine is the file that must
not import the bot.

### 9.1 Files to create

```
scanner/rsidiv.py              engine: pure functions over one frame, no I/O
scanner/rsidiv_run.py          runner: universe -> download -> rows -> publish
scanner/config.py              + one RSIDIV_* block (edit, do not create)
scanner/indicators.py          + macd() and pivots_series()  (edit; see 9.3)
.github/workflows/rsidiv.yml   nightly, own concurrency group
tests/test_rsidiv.py           no registration needed - pytest collects tests/
public/rsidiv.html             optional page (see 9.8)
public/js/rsidiv.js            optional; IF added, needs a test.yml step
public/css/rsidiv.css          optional
```

### 9.2 The config block (`scanner/config.py`, project rule 3)

Put it next to the `TURTLE_*` block, with the house comment density. Values are
the Pine defaults read out of the three `.pine` files, so the scanner and the
chart cannot disagree by accident:

```python
# ---------------------------------------------------------------------------
# RSIDIV -- the TradingView-template lens (tradingview/*.pine), <date>
# ---------------------------------------------------------------------------
# Screens the DAILY bar for the two things the owner's chart template marks:
#   RULE A  the RSI+ pane printed a regular Bull / Bear divergence label
#   RULE B  the Top overlay printed a scored Fast x Mid cross with |score| >= N
# REPORT-ONLY: nothing under scanner/broker/ reads it (test-pinned), it takes
# no position and it writes exactly one file per market.
#
# EVERY NUMBER BELOW IS A PINE INPUT DEFAULT, quoted from the .pine source.
# They are duplicated here rather than parsed out of the Pine so the scan is
# self-contained -- and tests/test_rsidiv.py parses the .pine files and fails
# on any drift, which is the risk_manager.js PUBLISHED_DEFAULTS lesson
# (TOP100 #34) applied before the drift rather than after it.

# -- RSI+ pane (Final_RSI_Plus.pine) --
RSIDIV_RSI_LEN        = 14     # rsiLen
RSIDIV_RSI_MA_LEN     = 14     # maLen
RSIDIV_RSI_MA_TYPE    = "SMA"  # maType; "EMA" is the other option
RSIDIV_PIVOT_LEFT     = 5      # lbL
RSIDIV_PIVOT_RIGHT    = 5      # lbR -- ALSO the confirmation delay, see 9.4
RSIDIV_RANGE_LOWER    = 5      # rangeLower (min bars between pivots)
RSIDIV_RANGE_UPPER    = 60     # rangeUpper (max bars between pivots)

# -- Top overlay (Final_Top_Script.pine) --
RSIDIV_MA_TYPE        = "EMA"  # maType
RSIDIV_MA_FAST        = 20     # fastLen
RSIDIV_MA_MID         = 50     # midLen
RSIDIV_MA_SLOW        = 200    # slowLen
RSIDIV_MACD           = (12, 26, 9)   # macdFast / macdSlow / macdSig
RSIDIV_SCORE_USE_MACD = True   # useMacd  -- +1 when the histogram agrees
RSIDIV_SCORE_USE_SLOW = True   # useSlow  -- +1 when price is beyond the Slow MA
RSIDIV_SCORE_USE_RSI  = False  # useRsi   -- OFF in the template, so max = 3
                               # not 4. A scanner that assumes 4 disagrees with
                               # the chart silently.

# -- what the SCANNER filters on (NOT a Pine input) --
RSIDIV_MIN_CROSS_SCORE = 2     # Rule B threshold. The chart's own minScore is
                               # 1 (it draws every cross); this is the owner's
                               # screen, so it lives here and not in the Pine.
RSIDIV_CROSS_MAX_AGE_BARS = 0  # 0 = the cross must be ON the latest closed bar
                               # (the literal reading of the ask). Raise to
                               # widen to "fired within N bars" -- see 9.4(c).
RSIDIV_DIV_MAX_AGE_BARS   = 0  # same, for Rule A.
RSIDIV_MODE_DEFAULT       = "any"   # "div" = Rule A only; "any" = A or B

# -- plumbing, mirroring TURTLE's posture exactly --
RSIDIV_PERIOD           = "5y"   # MUST stay 5y while merge_with_cache is used:
                                 # .cache/frames is keyed by market ONLY, and a
                                 # shorter period would clobber the shared cache
                                 # every other lens reads. See scanner/data.py.
RSIDIV_MIN_BARS         = 250    # 200-EMA warm-up + a 61-bar divergence window
RSIDIV_MIN_COVERAGE_PCT = 60.0   # refuse to publish over a good file with a
                                 # gutted one (turtle_run.py:320 reasoning)
RSIDIV_MAX_ROWS         = 400    # published rows per market
RSIDIV_THROTTLE_RETRY_COOLDOWN_S = 180.0   # one in-run retry; 0 = off
```

`RSIDIV_MIN_BARS = 250` vs a 5y download (about 1,250 daily bars) means the
minimum-bars gate only ever bites a genuinely young listing, which is right.

### 9.3 Two additions to `scanner/indicators.py`

Both are genuinely shared and both belong there rather than in the engine:

```python
def macd(series, fast: int = 12, slow: int = 26, signal: int = 9):
    """(macd_line, signal_line, histogram) -- Pine's ta.macd, same order.
    Built on ema() so it inherits its adjust=False recursion; the three
    published values are macd - signal for the histogram, exactly as
    Final_Bottom_MACD.pine:25 computes it."""
    line = ema(series, fast) - ema(series, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def pivots_series(s: pd.Series, left: int, right: int,
                  high: bool = True, strict: bool = True) -> pd.Series:
    """Boolean Series: True on the CONFIRMATION bar of a pivot `right` bars back.

    Deliberately different from pivot_highs()/pivot_lows() in four ways, each
    of which is required by the RSI+ divergence and none of which those two
    can express (see the docstring there):
      * it takes a SERIES, because the divergence pivots on the RSI itself;
      * it returns a boolean MASK aligned to the CONFIRMATION bar, which is
        what Pine's plFound/phFound are -- not a sparse series of values at
        the pivot bars;
      * left and right are independent (Pine's lbL / lbR);
      * `strict` controls tie handling. pivot_highs uses >= on BOTH sides, so
        a flat plateau marks every bar in it; Pine does not, and on a
        divergence a duplicate pivot changes which PAIR gets compared.

    Never looks ahead: the mask is True at bar t only using bars <= t, and a
    pivot at bar t-right is therefore first reported at t -- the same
    confirmation delay Pine has and the same one pivot_highs gets right by
    accident through shift(-k) producing NaN at the tail.
    """
```

If touching `indicators.py` is unwelcome (it is imported by `vivek`, `reversal`,
`analysis` and `turtle`), both can live in `scanner/rsidiv.py` instead - the cost
is that a later lens re-writes MACD. `indicators.py` has no test file of its own;
`tests/test_engine_truth.py` covers `rsi`/`supertrend` specifically, so additions
there are low-risk but should carry their own pins in `tests/test_rsidiv.py`.

### 9.4 `scanner/rsidiv.py` - the engine

Pure functions over one frame. No downloads, no file writes, no imports from
`scanner/broker/` or `scanner/vivek*`.

```python
def evaluate(df: pd.DataFrame, market_key: str) -> dict | None
```

Contract, mirroring `spec.evaluate` / `turtle.build_row`: return `None` when the
name does not qualify, a dict when it does. The dict is the published row.

Order of operations inside it - this order is not arbitrary:

1. `if df is None or len(df) < config.RSIDIV_MIN_BARS: return None`
2. **Drop the forming bar** (`scan.py:246-248`, reproduced). Everything after
   this operates on closed bars only.
3. Liquidity: `turnover = mean(Close*Volume)` over the last
   `LIQUIDITY_LOOKBACK` (20) bars, or `mean(Volume)` for a market with
   `volume_is_usd`; `if turnover < market.liquidity_min: return None` and count
   it in the funnel.
4. Rule A. `r = indicators.rsi(close, RSIDIV_RSI_LEN)`;
   `plFound = pivots_series(r, lbL, lbR, high=False)`,
   `phFound = pivots_series(r, lbL, lbR, high=True)`.
   For bar `c = -1` (the latest closed bar):
   * `plFound[c]` must be True;
   * let `p = c - lbR` (the pivot bar), `p_prev` = the previous confirmation bar
     where `plFound` was True, and `p_prev_piv = p_prev - lbR`;
   * **`6 <= (c - p_prev) <= 61`** with the shipped `rangeLower=5 /
     rangeUpper=60` - see section 3(b). Express it as
     `RANGE_LOWER + 1 <= gap <= RANGE_UPPER + 1` with the `plFound[1]` comment;
   * `rsi_hl  = r.iloc[p] > r.iloc[p_prev_piv]`
   * `price_ll = low.iloc[p] < low.iloc[p_prev_piv]`   # LOW at the RSI pivot bar
   * `bull_div = plFound[c] and price_ll and rsi_hl and in_range`
   * bearish is the mirror: `phFound`, `rsi.iloc[p] < rsi.iloc[p_prev_piv]`,
     `high.iloc[p] > high.iloc[p_prev_piv]`.
5. Rule B. `fast = ema(close, 20)`, `mid = ema(close, 50)`,
   `slow = ema(close, 200)`, `_, _, hist = macd(close, *RSIDIV_MACD)`.
   * `bull_x = fast.iloc[c] > mid.iloc[c] and fast.iloc[c-1] <= mid.iloc[c-1]`
     - that is `ta.crossover` exactly (strict `>` now, `<=` previously);
   * `bull_score = 1 + (USE_MACD and hist.iloc[c] > 0) + (USE_SLOW and
     close.iloc[c] > slow.iloc[c]) + (USE_RSI and rsi14.iloc[c] > 50)`
     - note Pine uses `ta.rsi(close, 14)` here, the **Top script's own** rsiLen
     (line 79, default 14), which coincidentally equals the RSI+ pane's. Do not
     assume they must be equal; read both constants.
   * bearish mirrors with `crossunder`, `hist < 0`, `close < slow`, `rsi < 50`.
6. Qualify: `bull_div or bear_div` for mode `"div"`; also
   `|score| >= RSIDIV_MIN_CROSS_SCORE` on a cross bar for mode `"any"`.
7. Build and return the row.

**(c) The "as of the latest closed bar" decision, stated once.** Both rules are
single-bar events in Pine. With `*_MAX_AGE_BARS = 0` the scan asks "did it fire
on the newest closed bar" - a true daily screen, and on ASX that is maybe a
handful of names a night out of 2,200. The owner's stated purpose is a manual
eyeball list, and the brief says misses are expensive while false positives are
cheap, so the likely real intent is a small window (2 to 5 bars). Ship it as the
constant above, default `0`, and publish the age on the row
(`div_age_bars`, `cross_age_bars`) so widening the window later is a config
change and not a re-scan of history.

**Suggested row shape** (the house style: flat, named, JSON-safe, no NaN):

```python
{"symbol", "name", "sector", "is_product",          # identity, as VIVEK's row
 "price", "turnover", "liquidity", "data_age_days", # the standing thin-row set
 "rules": ["div_bull"] / ["cross_bull"] / both,     # WHY this row is here
 "div": "bull" | "bear" | None,
 "div_age_bars": int | None,                        # 0 = printed on the latest bar
 "div_rsi": float, "div_rsi_prev": float,           # the two RSI pivot values
 "div_price": float, "div_price_prev": float,       # the two price values
 "div_gap_bars": int,                               # c - p_prev, for auditing
 "cross": "bull" | "bear" | None,
 "cross_score": int,                                # signed: +2 / -3 etc
 "cross_age_bars": int | None,
 "cross_parts": {"cross": 1, "macd": 0|1, "slow": 0|1, "rsi": 0|1},
 "rsi": float, "rsi_ma": float,                     # today's pane readings
 "ema_fast", "ema_mid", "ema_slow": float,
 "regime": bool,                                    # mid > slow, the Slow MA colour
 "spark": [float] * config.SPARK_BARS}
```

`cross_parts` is the thing that makes the page auditable against the chart: a
reader who disagrees with a `+2` can see which term did not fire.

### 9.5 `scanner/rsidiv_run.py` - the runner

Copy `turtle_run.py`'s skeleton. The load-bearing parts, in order:

```python
MARKETS = ("asx", "nasdaq", "crypto")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "public", "data")

def scan_market(market_key, limit=None, period=config.RSIDIV_PERIOD, mode=None):
    mk    = config.MARKETS[market_key]
    items = universe.load_universe(market_key, full=True)
    if limit: items = items[:limit]
    yf_map = {it["yf"]: it for it in items}
    fresh  = data.download(list(yf_map), period=period, interval="1d")
    frames, cache_stats = data.merge_with_cache(market_key, fresh, list(yf_map))

    rows, errors = [], scanerrors.ErrorLog(f"rsidiv [{market_key}]")
    skipped_no_data = skipped_short = skipped_illiquid = no_signal = 0
    no_data_syms = []
    for yf_sym, info in yf_map.items():          # ITERATE THE UNIVERSE, NOT THE
        df = frames.get(yf_sym)                  # DOWNLOAD -- see turtle_run.py:265
        if df is None or df.empty:
            skipped_no_data += 1; no_data_syms.append(info["symbol"]); continue
        if len(df) < config.RSIDIV_MIN_BARS:
            skipped_short += 1; continue
        try:
            row = rsidiv.evaluate(df, market_key, info=info, mode=mode)
        except Exception as e:
            errors.record(info["symbol"], e); continue
        ...
    errors.report(len(yf_map))                   # ALWAYS, even at zero

    covered   = len(yf_map) - skipped_no_data
    cover_pct = 100.0 * covered / len(yf_map) if yf_map else 0.0
    if yf_map and cover_pct < config.RSIDIV_MIN_COVERAGE_PCT:
        raise RuntimeError(...)                  # REFUSE to publish, do not warn

    payload = {"generated_at": <market-local ISO, seconds>, "market": market_key,
               "lens": "rsidiv", "mode": mode, "currency_symbol": mk.currency_symbol,
               "universe_size": len(items), "evaluated": len(rows),
               "skipped_no_data": skipped_no_data,
               "skipped_short_history": skipped_short,
               "skipped_illiquid": skipped_illiquid, "no_signal": no_signal,
               "data_coverage_pct": round(cover_pct, 1),
               "data_from_cache": int(cache_stats.get("reused", 0)),
               "data_stale_dropped": int(cache_stats.get("stale_dropped", 0)),
               "truncated": max(0, len(rows) - len(published)),
               "params": params_block(),         # every constant, published
               "results": published, **errors.payload()}
    output.write_json(os.path.join(OUT_DIR, f"{market_key}_rsidiv.json"),
                      payload, indent=1, ensure_ascii=False, newline=True)
```

Then `main(argv=None) -> int` with `--market`, `--limit`, `--period`, `--mode`,
the collect-failures loop, the one cooldown retry, and `sys.exit(main())`.

Four things to carry over that are easy to drop and expensive to lose:

* **`params_block()`** - publish every constant the run used beside the results,
  as `turtle_run.py:49` does. The page renders THOSE, which makes a drift
  between the page's prose and the code impossible rather than merely unlikely.
* **Iterate `yf_map`, not `frames`.** Walking the download made every name Yahoo
  dropped invisible by construction: on 2026-08-21 a Turtle run got 5 of 101
  crypto names back, evaluated one, and published `errors: 0`.
* **`generated_at` in the MARKET's timezone**, `isoformat(timespec="seconds")`.
  (Turtle uses `Australia/Melbourne` for all markets - one owner, one clock;
  VIVEK uses the market's own. Either is defensible; pick one and say which.)
* **The coverage floor RAISES**, it does not warn. That non-zero exit is what
  makes the workflow red and is the whole alarm.

### 9.6 The nightly workflow, `.github/workflows/rsidiv.yml`

`turtle.yml` is the template and every deviation below is deliberate.

```yaml
name: RSIDIV nightly scan

on:
  schedule:
    - cron: "45 6 * * 1-5"    # ASX: past 16:00 in BOTH AEST (06:00 UTC) and
                              # AEDT (05:00 UTC) -- the DST superset rule
    - cron: "45 21 * * 1-5"   # NASDAQ: past 16:00 in both EST (21:00) and EDT (20:00)
    - cron: "45 10 * * *"     # nightly all-markets pass, clear of the
                              # 08:30/08:45/08:52 cluster AND of turtle's 09:30
  workflow_dispatch:
    inputs:
      market: {description: "Market to scan", default: "all", required: false,
               type: choice, options: ["all", "asx", "nasdaq", "crypto"]}
      limit:  {description: "Cap names per market", default: "", required: false}

permissions:
  contents: write            # REQUIRED -- tests/test_workflow_hardening.py
                             # test_every_workflow_declares_its_permissions
                             # fails a workflow with no block at all

concurrency:
  group: rsidiv              # NOT `scan`. That group serialises writers of the
  cancel-in-progress: false  # paper BOOK; this writes only its own files, and
                             # joining it would put a nightly in the one-pending
                             # -slot queue that evicted the :47 ASX backstop.
                             # Own group so two RSIDIV runs cannot overlap.

jobs:
  rsidiv:
    runs-on: ubuntu-latest
    timeout-minutes: 120     # every unbounded job was a Tier 3 finding (#44)
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12", cache: pip}
      - name: Install dependencies
        run: pip install -r requirements.txt

      # The SHARED last-good frame cache. Same key as scan.yml / crypto_bot.yml /
      # turtle.yml so the newest cache from ANY writer is restored.
      - name: Restore frame cache
        uses: actions/cache@v4
        with:
          path: .cache/frames
          key: vivek-frames-${{ github.run_id }}
          restore-keys: |
            vivek-frames-

      - name: Run the RSIDIV scan
        id: rsidiv
        env:                          # free-text inputs travel through env,
          MARKET: ${{ github.event.inputs.market }}     # never through ${{ }}
          LIMIT:  ${{ github.event.inputs.limit }}      # inside a run: block
          SCHEDULE: ${{ github.event.schedule }}
        run: |
          set -o pipefail             # `bash -e` is on by default, pipefail is NOT
          case "$SCHEDULE" in
            "45 6 * * 1-5")  MARKET="asx" ;;
            "45 21 * * 1-5") MARKET="nasdaq" ;;
            "45 10 * * *")   MARKET="all" ;;
          esac
          ARGS="--market ${MARKET:-all}"
          if [ -n "$LIMIT" ]; then ARGS="$ARGS --limit $LIMIT"; fi
          python -m scanner.rsidiv_run $ARGS 2>&1 | tee /tmp/rsidiv_out.txt

      - name: Scan summary
        if: always()
        run: |
          { echo '### RSIDIV nightly'; echo '```'
            grep -E '^\[(asx|nasdaq|crypto)\] rsidiv' /tmp/rsidiv_out.txt || \
              echo '(no per-market lines)'
            echo '```'; } >> "$GITHUB_STEP_SUMMARY"

      # RUNS ON PARTIAL FAILURE, deliberately: the runner isolates per-market
      # failures then returns 1, which without this guard would discard the
      # markets that DID work. The job still goes red.
      - name: Commit & push (surgical -- the rsidiv files only)
        if: success() || failure()
        env:
          SCHEDULE: ${{ github.event.schedule }}
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          PATHS="public/data/asx_rsidiv.json public/data/nasdaq_rsidiv.json public/data/crypto_rsidiv.json"
          # ONE PATHSPEC PER git add. `git add a b` is ALL-OR-NOTHING: with one
          # path missing it exits 128 and stages NEITHER. Banned repo-wide by
          # test_no_git_add_stages_more_than_one_path_at_a_time.
          for p in $PATHS; do
            if [ -e "$p" ]; then git add -- "$p"
            else echo "::warning::$p is not present - nothing to stage for it"; fi
          done
          # Must-change gate, ANY-OF, and only on the all-markets cron: the
          # per-market crons legitimately leave two of the three untouched.
          if [ "${GITHUB_EVENT_NAME}" = "schedule" ] && [ "$SCHEDULE" = "45 10 * * *" ]; then
            bash scripts/assert_staged.sh "rsidiv" public/data/asx_rsidiv.json public/data/nasdaq_rsidiv.json public/data/crypto_rsidiv.json
          fi
          if git diff --cached --quiet; then echo "No rsidiv changes."; exit 0; fi
          git commit -m "data: rsidiv $(date -u +'%Y-%m-%d')"
          SHA=$(git rev-parse HEAD)
          for i in 1 2 3 4 5; do
            git fetch origin main; git reset --hard origin/main
            for p in $PATHS; do
              # only ever re-apply a path THIS run generated (Tier 3 #42)
              if git cat-file -e "$SHA:$p" 2>/dev/null; then
                git checkout "$SHA" -- "$p"; git add -- "$p"; fi
            done
            if git diff --cached --quiet; then echo "Nothing new vs main."; exit 0; fi
            git commit -m "data: rsidiv $(date -u +'%Y-%m-%d')"
            if git push origin HEAD:main; then echo "Pushed."; exit 0; fi
            echo "Push race - retry $i"; sleep $((i * 3))
          done
          echo "Could not push after retries"; exit 1
```

**Cron timing.** Existing occupancy of the nightly window: phasemap 08:30,
confluence 08:45, reco_note 08:52, turtle 09:30 (plus turtle crypto every 4h at
`5 */4`, turtle ASX 06:30, turtle NASDAQ 21:30). 10:45 keeps the two
full-universe Yahoo walks an hour apart, which is the stated reason turtle sits
at 09:30. Do not co-schedule with turtle.

**DST.** `tests/test_workflow_dst.py` (21 tests) exists because every ASX cron
was written for AEST and would have had a four-week hole in October. The rule:
**fire a SUPERSET and let the job decide.** The two market crons above are past
the close in both halves of the year, so no in-job gate is needed; if you ever
want a cron INSIDE an ASX session, add the 23:xx superset cron too and gate on
real Melbourne local time in the job.

### 9.7 The watchdog entry (`config.WATCHDOG_RUNS`)

`CLAUDE.md`: *"When adding a workflow that commits data, give it an
assert_staged call and a WATCHDOG_RUNS entry."*

```python
    # RSIDIV, the TradingView-template lens. WARNING, not CRITICAL, for the
    # same reason as turtle.yml: a stale file costs a day of signals on a
    # REPORT-ONLY surface and the page prints its own generated_at, so a
    # missed night is visible to the reader without an alarm ringing.
    "rsidiv.yml":      {"max_age_h": 26.0, "severity": "WARNING"},
```

26h, matching every other daily writer (phasemap, backup_book, confluence,
reco_note, alert_returns, turtle) - one missed nightly is inside the window,
two is not. `watchdog.probe_runs` (line 334) iterates this dict, finds the newest
concluded run and the newest SUCCESS, **stays silent when the newest concluded
run FAILED** (GitHub emailed already) and notes "no recorded runs yet" for a
brand-new workflow rather than firing.

`WATCHDOG_RUNS` needs `GITHUB_REPOSITORY` in the environment; it is hosted in
`kill_switch.yml` and `crypto_bot.yml`, so the new entry starts being probed
without touching either.

**Backups:** `backup_book.yml` snapshots `journal/*` and `data/*`. A lens that
writes only `public/data/*_rsidiv.json` needs **no** backup entry - those files
are committed and therefore already in git history.
`tests/test_backup_completeness.py` asserts a fixed list of journal/ and data/
paths exists; it will not fail for a new public/data file.

### 9.8 Optional front end

If a page is added:

* **`public/js/rsidiv.js` MUST get its own `node test/rsidiv.test.js` step in
  `test.yml`** if a test file is added - and since 2026-07-28 that is a GATE:
  `tests/test_screenshot_determinism.py::test_every_javascript_suite_has_a_step_in_the_workflow`
  walks `test/*.test.js` and fails the push if any has no step.
* **Project rule 2:** every edit to any `public/js/*.js` or `public/css/*.css`
  bumps its `?v=` in every referencing HTML page. Do not record the numbers in
  docs - read them from the HTML.
* `public/sw.js` is **network-first for `/data/`**, so a new data file needs no
  service-worker change; only a breaking asset change needs the `CACHE` name
  bumped (currently `"vivek5-v6"`).
* A new `public/*.html` is already inside `test.yml`'s path filter, and
  `test/e2e/smoke.e2e.js` has a 320px page list that a new page should join
  (turtle.html did, after `#tt-views` pushed the page sideways at 320px - a
  defect found by RENDERING, not by reading).
* Follow `turtle.js`'s offline-mirror discipline: a hand-typed constants mirror
  that a test compares against the real `config.py`, with a published `params`
  block always winning key by key.

---

## 10. `tests/` - conventions a new test file must follow

**Registration: none needed for Python.** `pytest.ini` sets
`testpaths = tests phasemap/tests`, `python_files = test_*.py`,
`addopts = -q --strict-markers`, and declares four markers (`risk`, `breaker`,
`journal`, `pretrade`) - `--strict-markers` means an undeclared marker is an
error, so a new marker must be added to `pytest.ini` first. Dropping `tests/test_rsidiv.py` in
is enough. **Only new `test/*.test.js` files need a step in `test.yml`**, and
that rule is now enforced by a test.

`tests/conftest.py` puts the repo root on `sys.path` and provides one **autouse**
fixture that redirects `data._CACHE_DIR` to a `tmp_path` for every test in the
suite - so a test that hands a runner full frames cannot write the developer's
real `.cache/frames` and cannot leak state into the next test. A test that needs
a warm cache seeds it with `data.save_frame_cache`.

Conventions worth copying, all visible in `tests/test_turtle.py`:

1. **Name tests after the claim, not the function.** Real examples:
   `test_oscillation_never_demotes_AND_THAT_IS_THE_POINT`,
   `test_a_flagged_plan_is_still_taken_because_a_flag_is_not_a_gate`,
   `test_a_baseline_from_a_dead_clock_is_DISCARDED_not_failed`. The name is
   where the reasoning lives so the next reader hits it before the edit.
2. **Test the SHIPPED artefact, never a re-typed mirror.** "A re-typed fixture
   drifts in step with the bug it is supposed to catch" is the standing rule.
   `test/turtle.test.js` parses the real `config.py`;
   `tests/test_lighthouse_budget.py` parses the real e2e file;
   `test/journal_money.test.js` `vm`-slices ~15 real functions out of
   `public/js/journal.js`. **For RSIDIV this means the drift test should parse
   `tradingview/*.pine` and assert each `RSIDIV_*` constant equals the Pine
   input default it claims to mirror.** That is the single highest-value test in
   the new file, and it is the TOP100 #34 lesson applied before the drift.
3. **Construct fixtures so the expected number is hand-checkable.**
   `tests/test_turtle.py`'s `band()` builds frames where True Range is exactly
   2.0 on every bar, so `N = 2.0` and every stop and add level is arithmetic a
   reader can verify. Do the same here: a synthetic frame with a known RSI pivot
   pair at known bar offsets, so the `6 <= gap <= 61` boundary can be tested at
   5, 6, 61 and 62 exactly.
4. **An autouse fixture that stops a test writing a real artefact**, plus a
   separate "guard for the guard" test that greps the real committed files for
   fixture symbol names. `test_no_test_run_may_leave_a_paper_book_behind`
   (test_turtle.py:49) exists because on 2026-08-21 a book holding a fixture
   symbol reached main. RSIDIV writes only `public/data/*_rsidiv.json`, so the
   equivalent is: monkeypatch `rsidiv_run.OUT_DIR` to `tmp_path` in an autouse
   fixture, and assert no committed `*_rsidiv.json` contains a fixture symbol.
5. **Fixture symbols must not collide with real tickers.** The Turtle suite
   renamed its `NEAR` fixture to `NRBY` because NEAR is a real coin and the
   fixture guard false-positived on a legitimate crypto skip. Pick names that
   cannot be listed anywhere (`ZZ1`, `ZZ2`, `NRBY`-style).
6. **ASCII-only prints, pinned.** `test_prints_are_ascii_only` walks the source
   and asserts `line.isascii()` on every line containing `print(`. Copy it.
7. **Fence tests, both directions.** From `tests/test_turtle.py:1148-1200`:
   * nothing under `scanner/broker/` may mention the lens name;
   * no `RSIDIV_` constant may reach `public/data/bot_rules.json` or
     `scanner/run.py`;
   * the runner has exactly **one** `output.write_json(` call, names its own
     file, and contains none of `vivek_bot_book`, `alert_history`,
     `sector_map`, `journal/`, `bot_rules`;
   * the engine's IMPORT LINES (not its prose - the justification reads as the
     offence otherwise) contain neither `broker` nor `vivek`.
8. **Mutation-verify.** The house standard, stated in four CLAUDE.md sections:
   apply each mutation one at a time to the shipped source, confirm the right
   test goes red, restore, and diff byte-for-byte. Two Turtle mutations survived
   the first pass and both gaps were the re-openable kind.

### The pins a new workflow inherits automatically

`tests/test_workflow_hardening.py` globs `ALL_WF = sorted(WF.glob("*.yml"))`, so
`rsidiv.yml` is picked up the moment it lands. It must satisfy, unedited:

| test | requirement |
|---|---|
| `test_every_run_block_is_valid_shell` | `bash -n` over every `run:` block |
| `test_every_workflow_declares_its_permissions` | a `permissions:` block exists |
| `test_no_git_add_stages_more_than_one_path_at_a_time` | one pathspec per `git add` (`-A`/`-u` exempt) |
| `test_a_swallowed_git_add_always_has_something_downstream_that_can_tell` | a `git add ... \|\| true` requires `assert_staged.sh` in the same step |
| `test_third_party_actions_must_be_pinned_to_a_commit_sha` | any non-`actions/*` action needs a 40-hex SHA |
| `test_no_action_floats_on_a_branch` | no `@main` / `@master` / `@latest` |
| `test_the_first_party_actions_are_the_five_we_reviewed` | **stick to checkout / setup-python / setup-node / cache / upload-artifact**; a sixth `actions/*` fails the tripwire until reviewed |

`tests/test_workflow_mutex.py` asserts concurrency scoping; it will not object to
a new group, but **do not put the new job in `group: scan`** - that group exists
so two writers can never touch the paper book at once, GitHub keeps only ONE
pending run per group, and joining it is how the `:47` ASX backstop got evicted.

### `scripts/assert_staged.sh` - exact contract

`assert_staged.sh <label> <path> [<path>...]`, 32 lines, `set -u`.
**ANY-OF semantics:** exits 0 the moment ONE listed path has a staged diff vs
HEAD (covering modified AND newly added), exits 1 with
`::error::ASSERT-STAGED FAILED (<label>)` plus `git status --short | head -20`
otherwise, and exits 2 if given no paths. Run it AFTER `git add`.

> "Call it once per independent invariant ('all must change' = several calls,
> one path each; 'any of these' = one call, several paths)."

For RSIDIV: **one call, three paths, gated to the all-markets cron.** A
per-market cron legitimately leaves two files untouched, so asserting all three
unconditionally would turn a correct run red - which is how a gate gets deleted
rather than fixed. Never list a derived/combined view in an ANY-OF call: it
would let the assert pass on a run that regenerated the view while the file the
scan actually produced failed to stage.

---

## 11. Project rules (`CLAUDE.md`) that bind this work

| # | rule | what it means here |
|---|---|---|
| 1 | Git first | `git stash -q -u; git pull -q --rebase origin main; git stash pop -q` before ANY commit - other sessions and CI push constantly |
| 2 | Version bump | every `public/js/*.js` / `public/css/*.css` edit bumps its `?v=` in every referencing HTML page |
| 3 | **Config first** | every threshold goes in `scanner/config.py` before use; never hardcode a number twice |
| 4 | PhaseMap spec is law | not touched by this lens |
| 5 | Tests gate everything | `python -m pytest -q` plus the JS suites must be green; CI runs both on every push |
| 6 | Pinned deps | `requirements.txt` pins trade-path packages exactly; never loosen to `>=`. **This lens needs no new dependency** - pandas, numpy and yfinance are already pinned |
| 7 | Atomic writes | any journal/state JSON is temp + `os.replace`; in practice: go through `output.write_json` |
| 8 | Push to `main` | Cloudflare Pages deploys main; feature branches do not deploy |
| 9 | **ASCII-only prints** | Windows consoles are cp1252 and choke on arrows and em-dashes. Pinned by test in the Turtle suite; copy that test |
| 10 | CF Functions are Workers | no Node builtins - irrelevant unless an API endpoint is added |

Plus the two that are not numbered but are repeated everywhere:

* **Report-only means fenced, and the fence is a test.** A new lens must be
  unreachable from `scanner/broker/`, must not write the book or
  `bot_rules.json`, and must have tests in BOTH directions saying so.
  `tests/test_evidence_fences.py` holds the general sweep
  (`ARTIFACT_MAP` = artefact name -> the only files allowed to mention it;
  `MODULE_MAP` = module -> the ONE file allowed to import it) - a new
  report-only artefact should be added to `ARTIFACT_MAP` there so the sweep
  covers it too.
* **A mirror must be tested against its source.** Every hand-typed copy of a
  number in this repo has drifted at least once (`risk_manager.js`'s
  `PUBLISHED_DEFAULTS` read 0.25%/5 positions and a 2.0% portfolio cap against
  a live 0.35%/30 and 7%, for months). The RSIDIV constants are a mirror of the
  Pine inputs. Test them against the `.pine` files.

---

## 12. Reuse table - every existing gate a new scanner should adopt, and the verdict

| gate | reuse? | why |
|---|---|---|
| `universe.load_universe(m, full=True)` | **YES, as-is** | the only universe source; handles directory fetch, snapshot cache, bundled fallback |
| `data.download(...)` | **YES, as-is** | batching, backoff, recovery sweep, all tuned in config |
| `data.merge_with_cache(...)` | **YES** - but only with `period="5y"` | the cache is keyed by market alone; a shorter period clobbers every other lens |
| `config.FRAME_CACHE_MAX_AGE_DAYS = 10` | **YES, inherited free** | comes with `merge_with_cache`; a fossil is refused, named and counted |
| `data._frame_age_days(df, market.timezone)` | **YES** | always pass the tz; the naive fallback is wrong by a day in both directions |
| `MARKETS[m].liquidity_min` + `LIQUIDITY_LOOKBACK` + `scan._liquidity`'s crypto branch | **YES** | so this lens and VIVEK agree on what is tradeable; `_liquidity` is private, so copy the four lines with a source comment or promote it |
| `config.LIQUID_TIER` | optional | cosmetic `LIQUID`/`OK` tag only |
| `VIVEK_DROP_FORMING_BAR` + `scan._bar_is_forming` | **YES, mandatory** | "latest CLOSED daily bar" is the premise; crypto's bar forms all day |
| `indicators.rsi` / `ema` / `sma` | **YES** | they match `ta.rsi` / `ta.ema` / `ta.sma` in steady state; the #71 NaN behaviour actively helps (a halted name cannot fake a pivot) |
| `indicators.pivot_highs` / `pivot_lows` | **NO** | wrong input type (DataFrame, not Series), wrong return shape (sparse values, not a confirmation mask), non-strict tie handling, symmetric-only. See section 3 |
| `indicators.macd` | **does not exist** - add it | three lines on `ema`; matches `ta.macd` exactly |
| `scanerrors.ErrorLog` | **YES, as-is** | label `f"rsidiv [{market}]"`; `report()` on every run; `**errors.payload()` into the payload |
| `output.write_json` | **YES, mandatory** | atomic + NaN-nulling; a hand-rolled writer trips `tests/test_publish_integrity.py` |
| Turtle's coverage floor (`MIN_COVERAGE_PCT` 60.0, raise-don't-warn) | **YES** | the most valuable pattern here: a fresh file holding one name looks identical to a healthy one to every watchdog in the repo |
| Turtle's small-universe absolute miss cap | **NO** | crypto at ~100 names is above `SMALL_UNIVERSE_MAX = 30`, so the share floor is the right rule |
| Turtle's one-retry-after-cooldown (`180.0s`) | **YES** | the dominant failure here is Yahoo throttling one market under the floor, and a throttle window clears in minutes |
| `scripts/assert_staged.sh`, ANY-OF, gated to the all-markets cron | **YES** | see section 10 |
| `config.WATCHDOG_RUNS` entry, 26h / WARNING | **YES** | matches every other daily report-only writer |
| The funnel counter block | **YES** | converts "is this filter too tight?" into a number; pin the identity in a test |
| `params_block()` published beside the results | **YES** | makes page-prose-vs-code drift impossible rather than unlikely |
| `VIVEK_BOT_MIN_ADV` / `MIN_PRICE` / `MAX_STOP_PCT` / `MAX_DATA_AGE_DAYS` | **NO** | executor gates on a ringfenced file; a report-only lens applying them would be claiming an eligibility opinion it has no business having |
| `scan._product_tag` / `is_product` | **optional, display only** | useful (the owner's list should not be full of LICs and preferred lines) but it is a DISPLAY flag and is fenced from `broker/`; if used, import the tag, do not re-implement the matching |
| `VIVEK_SCHEMA_VERSION` | **NO** | that is VIVEK's; give the new payload its own `schema_version` starting at 1, or omit it and rely on named keys as Turtle does |
| `config.SPARK_BARS = 30` | **YES** | one sparkline convention across every page |
| `journal/` + the bot book | **NEVER** | the lens takes no position; `tests/test_turtle.py`'s runner fence bans the string `journal/` in the runner source outright |

---

## 13. Open questions for the owner / the next session

1. **Rule A and Rule B window: 0 bars or N?** The literal ask is "as of the
   latest closed daily bar", which on ASX yields a handful of names a night.
   The stated purpose (a manual eyeball list, misses expensive, false positives
   cheap) argues for 2-5 bars. Shipped as `RSIDIV_*_MAX_AGE_BARS = 0` with the
   age published per row so widening is a config change.
2. **Pine's tie rule on `ta.pivothigh`/`ta.pivotlow`.** I could not verify it
   without a Pine compiler (none exists in a cloud session). Assumed strict on
   both sides; make it a constant and confirm on a chart.
3. **`useRsi` stays OFF?** If the owner ticks it on the chart, max score becomes
   4 and `>= 2` selects a materially different set. The constant mirror plus the
   Pine-parsing drift test is what keeps that from being silent.
4. **Adjusted vs unadjusted prices.** The repo downloads `auto_adjust=True`
   (split- and dividend-adjusted). TradingView charts are typically
   split-adjusted only. On a dividend-paying ASX name the EMA20/50/200 and the
   RSI will differ slightly from the chart, and a borderline cross can land on a
   different bar. This is a real, unavoidable divergence between scanner and
   chart and should be said out loud on the page rather than discovered.
5. **Weekly/other timeframes.** The brief says daily only. The Pine runs on
   whatever timeframe the chart is on, so a later "weekly RSI divergence" ask is
   a resample of the same frames, not a new download - worth leaving the engine
   timeframe-agnostic (take a frame, not a market) so that stays cheap.
6. **Should this feed CONFLUENCE?** `CLAUDE.md` is explicit that three lenses
   feed the confluence machinery and TURTLE deliberately does not. RSIDIV should
   start OUTSIDE it, as TURTLE did - joining is a trade-affecting decision and
   therefore the owner's.

---

## Appendix A - file:line anchors (read these, do not re-derive)

| what | anchor |
|---|---|
| `load_universe` | `scanner/universe.py:298` |
| universe row built (ASX) | `scanner/universe.py:204` |
| NASDAQ rows carry no sector | `scanner/universe.py:209-237` (no sector column exists) |
| `MarketConfig` + `MARKETS` | `scanner/config.py:1393` / `:1405` |
| `download` | `scanner/data.py:285` |
| `_download_pass` (batching) | `scanner/data.py:238` |
| `merge_with_cache` + stats | `scanner/data.py:105` / `:142` |
| frame cache path (market-keyed only) | `scanner/data.py:25` (`_CACHE_DIR`) / `:28` (`_cache_path`) |
| `_frame_age_days` | `scanner/data.py:61` |
| `validate_bars` | `scanner/data.py:165` |
| `pivot_highs` / `pivot_lows` | `scanner/indicators.py:121` / `:130` |
| `rsi` (with the #71 NaN rules) | `scanner/indicators.py:22` |
| `ema` / `sma` | `scanner/indicators.py:12` / `:17` |
| `write_json` + atomic contract | `scanner/output.py:110` |
| `write_vivek_pair` (where `<m>_vivek.json` is written) | `scanner/output.py:180` |
| `ErrorLog` | `scanner/scanerrors.py:65` |
| market loop | `scanner/run.py:158-311` |
| the deliberate empty-download `continue` | `scanner/run.py:184-194` |
| failures collected, raised last | `scanner/run.py:154` (collect), `:318` (append), `:471-480` (raise) |
| `scan_vivek_market` | `scanner/scan.py:155` |
| `_liquidity` | `scanner/scan.py:108` |
| `_bar_is_forming` | `scanner/scan.py:138` |
| drop-the-forming-bar call site | `scanner/scan.py:246-248` |
| the result row | `scanner/scan.py:360-410` |
| `sector_count` added | `scanner/scan.py:555-557` |
| `turtle_run.scan_market` (the runner template) | `scanner/turtle_run.py:225` |
| coverage floor that refuses to publish | `scanner/turtle_run.py:297-327` |
| `params_block` | `scanner/turtle_run.py:49` |
| `main()` + one-retry-after-cooldown | `scanner/turtle_run.py:472-535` |
| `WATCHDOG_RUNS` | `scanner/config.py:1093` |
| `probe_runs` | `scanner/watchdog.py:319` |
| `assert_staged.sh` | `scripts/assert_staged.sh` (32 lines) |
| the workflow template | `.github/workflows/turtle.yml` |
| workflow pins | `tests/test_workflow_hardening.py:106, 131, 157, 461, 497, 524, 532` |
| lens fence tests | `tests/test_turtle.py:1148-1200` |
| evidence fence sweep (`ARTIFACT_MAP` / `MODULE_MAP`) | `tests/test_evidence_fences.py:52` / `:60` |
| autouse frame-cache isolation | `tests/conftest.py:21` |
| JS suite registration gate | `tests/test_screenshot_determinism.py::test_every_javascript_suite_has_a_step_in_the_workflow` |
| Pine: RSI+ divergence block | `tradingview/Final_RSI_Plus.pine:36-60` |
| Pine: Top script cross + score | `tradingview/Final_Top_Script.pine:212-218` |
| Pine: `maxScore` and the useRsi default | `tradingview/Final_Top_Script.pine:580` / `:89` |
| Pine: MACD histogram | `tradingview/Final_Bottom_MACD.pine:25` |

## Appendix B - dependency note

`requirements.txt` pins `yfinance==1.4.1`, `pandas==3.0.3`, `numpy==2.4.6`,
`requests==2.34.2`, `pybit==5.16.0` exactly ("these five decide what the scanner
sees and trades"), plus `pytest==9.1.1` and `PyYAML==6.0.3` for the gate.
**This lens needs no new dependency** - `ewm`, `rolling`, `shift` and boolean
masking are all it uses. Project rule 6: bump a pin deliberately (edit pin ->
pytest -> push), never loosen to `>=`.


---

# PART 10 - VALIDATION: PROVING THE SCANNER AGREES WITH THE CHART

The scanner is only useful if, when it says "CBA printed a bullish divergence confirmed on
19 September", the owner opens CBA on the template and sees exactly that. Build the
validation before you build the universe loop: a screener you cannot check is a screener
you cannot trust.

## 10.1 Level 1 - unit tests on hand-built series (fast, run on every change)

Construct synthetic OHLCV frames where the right answer is known by construction.

| Test | Construction | Assertion |
|---|---|---|
| Bullish divergence fires | Two RSI troughs 20 bars apart, second RSI trough higher, second price low lower | `bull_div` true on exactly one bar, at `pivot_index + 5` |
| Bearish divergence fires | Mirror | same, for `bear_div` |
| Range gate lower bound | Two pivots 4 bars apart | no divergence |
| Range gate upper bound | Two pivots 70 bars apart | no divergence |
| Range gate boundaries | Pivots at exactly the min and max separation | fires at both, per the 7.3 arithmetic |
| Flat series | `close` constant for 300 bars | zero pivots, zero divergences, no exception |
| Score 3 | Engineered cross with MACD hist > 0 and close > EMA200 | `bull_score == 3` |
| Score 1 | Cross with MACD hist < 0 and close < EMA200 | `bull_score == 1`, excluded by `min_score = 2` |
| Cross is an event | Long stretch with `fast > mid` throughout | exactly one `bull_cross`, at the crossing bar |
| Short history | 80-bar frame | no crash, `short_history` flag set |
| No look-ahead | For each bar `i` in a window, truncate the frame to `[0:i+1]`, recompute, compare the verdict at `i` against the full-frame verdict at `i` | identical for every `i` |

The last one is mandatory and is the test most likely to be written wrongly. It must
**recompute from the truncated frame**. A test that truncates and then indexes into the
full-frame result proves nothing.

## 10.2 Level 2 - agreement with TradingView on real symbols (the real proof)

Pick 10 symbols spread across the three markets and across conditions (a trending name, a
ranging name, a recent divergence, an illiquid ASX small cap, a stablecoin, a halted name).

For each:

1. Open it on the daily chart with the three template indicators.
2. Record every `Bull`/`Bear` label visible over the last 250 bars, with its bar date, and
   every `Bullish +N` / `-N Bearish` label with its date and score.
3. Run the scanner's historical series over the same window.
4. Diff.

**The target is exact agreement on dates and scores.** Anything less needs explaining
before you go further. Common causes of disagreement, in the order you should check them:

- Wrong bar for the divergence (7.1) - the scanner's date is the confirmation bar, the
  chart's label sits at the pivot bar, 5 bars earlier. This is expected and is not a
  disagreement; compare `pivot_date` against the label position.
- Different price series (Yahoo `BTC-USD` vs Binance `BTCUSDT`; dividend-adjusted vs not).
- Insufficient history so the EMA200 or the RSI seed has not settled (7.4).
- The `[1]` in the range gate (7.3).
- TradingView's chart including the forming bar while the scanner truncated it (7.2).

Write the comparison up as a table and keep it. When someone later "improves" the pivot
code, re-running this table is how you find out it broke.

## 10.3 Level 3 - distribution sanity on a full universe

Run the full ASX scan once and check the shape of the output against 5.10. Then:

- Plot the distribution of `bars_ago` for the hits. It should be roughly uniform across the
  freshness window. A spike at 0 or at the window edge suggests an off-by-one.
- Count hits per sector and compare against sector sizes. Materials lists ~766 of the ASX's
  2,200 names; if it is not roughly a third of the hits, something is filtering oddly.
- Count the score distribution for Rule B. {2, 3} should both be well represented. All-3s
  means the `use_*` terms are not being evaluated; all-2s means one term is stuck.
- Check that the same symbol does not appear twice.

## 10.4 Level 4 - the standing regression

Freeze one day's frames as a fixture (a pickle or a set of CSVs), commit it, and assert the
scanner produces a known-good output file from it. This is the only test that catches a
silent change in behaviour from a library upgrade, and it costs nothing to run.

Keep the fixture small: 30 symbols is enough, chosen to include at least one hit of each
rule, one gate rejection of each kind, and one error row.

## 10.5 What good looks like after a month

Log every night's shortlist. After a month you can answer questions the owner will
certainly ask, and which nothing in this document can answer today:

- What share of Rule A hits moved in the divergence's direction over the following 5, 10
  and 20 sessions?
- Does score 3 outperform score 2, or is the score meaningless?
- Does Mode C (confluence) actually beat Mode A, or is it just rarer?
- What is the median holding period before the signal is invalidated?

This repository already has machinery for exactly this kind of forward-return ledger
(`scripts/alert_returns.py` stamps 1/5/10/20-session forward returns into a JSON ledger and
freezes each measurement at first write). Copy that pattern rather than inventing one: the
critical property is that a return, once measured, is never recomputed, so the ledger
cannot drift.


---

# PART 11 - PERFORMANCE AND SCALE

## 11.1 The shape of the workload

Roughly 3,750 symbols x 750 daily bars = 2.8 million bars per full nightly pass. That is
small. The bottleneck is **not** computation, it is **data acquisition**.

| Stage | Cost |
|---|---|
| Download 2,200 ASX daily frames from Yahoo, batched | 5 - 25 minutes, dominated by rate limiting and retries |
| Compute RSI + 3 EMAs + MACD + ATR on one 750-bar frame | under 5 ms with vectorised pandas |
| Pivot + divergence scan on one frame | 1 - 10 ms if vectorised; 100 ms+ if written as a Python loop over bars |
| Full ASX indicator pass | 30 - 120 seconds |
| Ranking, serialisation, write | under a second |

So: spend your engineering effort on the download path and on not writing per-bar Python
loops. Everything else is free.

## 11.2 Vectorise the pivot detection

The naive implementation is a loop over bars asking "is bar i-5 a pivot". Across 3,750
symbols that is 2.8 million iterations of interpreted Python and will dominate runtime.

The vectorised form: a bar `k` is a pivot low of `s` when
`s[k] == s[k-L : k+R+1].min()` and the minimum is unique in the required sense. With
pandas, a centred rolling min gives this in one pass:

```python
roll_min = s.rolling(L + R + 1, center=True).min()
is_pivot_at_k = (s == roll_min)          # then apply the tie rule from 7.5
confirmed_on_i = is_pivot_at_k.shift(R)  # move the flag to the confirmation bar
```

`shift(R)` is exactly the confirmation lag, expressed in one operation. Do not re-derive it
with an index loop.

The "previous pivot value" lookups (`ta.valuewhen(..., 1)`) vectorise as a forward-fill of
the pivot series shifted by one occurrence:

```python
piv_val   = s.where(is_pivot_at_k)              # NaN except at pivots
prev_piv  = piv_val.ffill().shift(1).where(is_pivot_at_k)   # careful: see the module
```

Get this right once, in a tested helper, and never write it inline again.

## 11.3 Download strategy

- **Batch.** Request many symbols per call rather than one at a time. The repository's
  `data.download()` already chunks, retries with backoff, and reports per-batch failures.
- **Cache with a ceiling.** Persist the last good frame per symbol; fill dropouts from it;
  refuse anything older than `FRAME_CACHE_MAX_AGE_DAYS` (7.7).
- **Fetch only what you need.** 750 daily bars is ~3 years. Requesting 10 years triples the
  payload for no benefit.
- **Treat the coverage share as a health metric.** If fewer than, say, 85% of the universe
  returned fresh data, the run is degraded: publish it, but mark it, and make the failure
  visible rather than letting a thin scan look like a quiet tape.

## 11.4 Parallelism

Indicator computation is embarrassingly parallel per symbol and trivially fast, so
multiprocessing is usually not worth the overhead. If the full pass ever does exceed a few
minutes of CPU, split by symbol across processes, not by market, so the load balances.

Downloads should be concurrent but **rate-limited**: Yahoo will throttle aggressively and a
throttled run is far slower than a politely-paced one. The repository's own experience,
recorded in its Turtle lens notes: every red run that workflow ever had was Yahoo
throttling one market below a coverage floor while a differently-paced scan of the same
universe succeeded in the same window.

## 11.5 Memory

2,200 frames x 750 rows x 6 float columns is about 80 MB as float64, plus pandas overhead:
call it 250-400 MB peak for ASX. Comfortable anywhere. If it ever matters, downcast to
float32 (prices do not need 15 significant figures) or process in chunks of 250 symbols and
discard frames after extracting the row.


---

# PART 12 - OPEN DECISIONS FOR VIVEK

These are choices the scanner cannot make for itself. Each one changes what shows up in the
shortlist, so each one is the owner's call, not the implementer's.

1. **Freshness windows.** `div_fresh_bars` and `signal_fresh_bars`, currently proposed at 3.
   At 1 the list is short and strictly "new today"; at 5 it is a working week of setups.
   *Recommendation: start at 1 for a week, measure the volume, then widen.*

2. **Which mode is the default nightly run?** Mode A (divergence only) is the smaller,
   higher-information list. Mode B adds the cross signal and will roughly triple to
   quintuple the volume. *Recommendation: publish both files every night; they cost the
   same scan. Read Mode A first.*

3. **Minimum score for Rule B - read the measurement in 5.10 before deciding.** A
   simulation over 1.95 million symbol-days found that score 1 is only **2%** of all
   crosses, so `min_score = 2` excludes almost nothing: Rule B is effectively "any 20/50
   cross". `min_score = 3` still admits 61% of crosses. The scoring terms are correlated
   with the cross by construction, so raising the threshold cannot make the rule selective.
   *Recommendation: keep 2, ship the score in the output, and if Rule B produces too much
   volume, add an UNCORRELATED term (volume expansion on the cross bar, or a slope
   condition on the 50) rather than raising the threshold. See 5.10.*

4. **Should the RSI term be switched on?** `use_rsi` is off by default, so the maximum score
   is 3. Turning it on makes the maximum 4 and changes what "2 or more" means. *If you turn
   it on, re-read 5.2: the reachable set becomes {1,2,3,4} and the screen's selectivity
   changes without the threshold changing.*

5. **Liquidity floors.** The proposed A$250k / US$1m / US$5m daily turnover gates are
   guesses calibrated to "can I get a position on without moving it". They will be the
   single largest determinant of how many ASX names you see. *Set them to the size you
   actually trade.*

6. **Hidden divergences.** This document covers **regular** divergence only (the trend
   reversal kind). *Hidden* divergence (price higher low + RSI lower low, a trend
   continuation signal) uses the same pivot machinery and is a four-line addition. It is
   deliberately not included because the reference chart does not show it. *Worth adding
   later as a separate flag, not folded into Rule A.*

7. **Should the scanner's universe match the existing scanner's?** The repository already
   maintains ASX / NASDAQ / crypto universes with product filtering and sector enrichment.
   Reusing them keeps one source of truth. The alternative - a separate universe for this
   screener - is more work and will drift. *Recommendation: reuse.*

8. **Where does the output go?** Options: (a) a new JSON published alongside the existing
   lens files and rendered as a new page/tab in the existing site; (b) a standalone app;
   (c) a nightly message. *The repository's existing pattern is (a) and everything is
   already built for it: atomic publish, a freshness watchdog, a backup job, and a front
   end that reads `public/data/*.json`.*

9. **Timeframe scope.** Everything here is daily. The template works on any timeframe, and
   the owner's reference charts are often 4-hour. Extending the screener to 4h multiplies
   the data volume by six and the signal count by roughly the same. *Recommendation: get
   daily right first; 4h is a config change, not a redesign, once the bar-timing rules in
   Part 7 are correctly implemented.*

10. **Does Rule B earn its place at all?** It is a reconstruction of a rule nobody has
    validated (Part 1). After a month of forward returns you will be able to answer this
    with evidence. *Until then, treat Mode A as the product and Mode B as an experiment.*


---

# APPENDIX A - COMPLETE PARAMETER TABLE

Every tunable in the template and the screener, with the value the template ships with.
A scanner implementation should expose every row marked "screener" as configuration, and
should hard-code nothing from this table as a literal in the code.

## A.1 Indicator parameters (from the Pine sources)

| Parameter | Default | Used by | Notes |
|---|---|---|---|
| `fastLen` | 20 | Top overlay | Fast MA length. Was 50 in the owner's original template. |
| `midLen` | 50 | Top overlay | Mid MA. This is the owner's original "Fast Length". |
| `slowLen` | 200 | Top overlay | Slow MA, the regime line. |
| `maType` | `EMA` | Top overlay | `EMA` or `SMA`. Both are computed every bar so history stays consistent when switched. |
| `maSrc` | `close` | Top overlay | Source series for all three MAs. |
| `rsiLen` (overlay) | 14 | Top overlay | For the RSI-extreme columns and the optional score term. |
| `rsiOB` | 75 | Top overlay | Overbought extreme. Was 70 in v1; raised because 70 fired on most bars. |
| `rsiOS` | 25 | Top overlay | Oversold extreme. Was 30 in v1. |
| `macdFast` / `macdSlow` / `macdSig` | 12 / 26 / 9 | Top overlay, MACD pane | Standard. |
| `useMacd` | true | Top overlay | Score term: MACD histogram agrees. |
| `useSlow` | true | Top overlay | Score term: price beyond the slow MA. |
| `useRsi` | **false** | Top overlay | Score term: RSI above/below 50. OFF, so max score is 3. |
| `minScore` | 1 | Top overlay | Minimum score to DRAW a label. Not the screener's threshold. |
| `pivLen` | 10 | Top overlay | Pivot strength for the support/resistance levels (not for divergence). |
| `maxSR` | 3 | Top overlay | S/R levels kept per side. |
| `maxDist` | 100 (%) | Top overlay | Hide a level further than this from price. Stops an all-time low near zero squashing the scale. |
| `rsiLen` (RSI+ pane) | 14 | RSI+ pane | The divergence RSI. |
| `maLen` | 14 | RSI+ pane | Smoothing MA over the RSI. |
| `maType` (RSI+) | `SMA` | RSI+ pane | |
| `longLen` | 50 | RSI+ pane | Long-run RSI average line. |
| `ob1` / `ob2` | 70 / 75 | RSI+ pane | Overbought band edges. |
| `os1` / `os2` | 30 / 25 | RSI+ pane | Oversold band edges. |
| `midL` | 50 | RSI+ pane | Midline. |
| `lbL` | 5 | RSI+ pane | **Pivot left bars for divergence.** |
| `lbR` | 5 | RSI+ pane | **Pivot right bars. This is the confirmation lag.** |
| `rangeLower` | 5 | RSI+ pane | Min bars between pivots (see 7.3 for the off-by-one). |
| `rangeUpper` | 60 | RSI+ pane | Max bars between pivots. |
| `showDiv` | true | RSI+ pane | Master switch for divergence detection. |

## A.2 Trade-box parameters (display only - the screener does not use these)

| Parameter | Default | Notes |
|---|---|---|
| `trMode` | `Auto (last signal)` | `Off` / `Auto (last signal)` / `Manual`. |
| `autoMaxAge` | 60 bars | The box only draws if the signal is this recent. |
| `slMode` | `Swing` | `Swing` or `ATR` stop derivation. |
| `swingLen` | 5 | Swing lookback for the stop. |
| `atrMult` | 1.5 | ATR multiple for the ATR stop. |
| `atrPad` | 0.25 | ATR pad beyond the swing. |
| `maxStopPct` | 15 (%) | Cap on the auto stop distance. Added after a crash-bar swing stop put targets below zero. |
| `r1` / `r2` / `r3` | 1.0 / 2.0 / 3.0 R | Target multiples of the stop distance. |
| `extendBars` | 30 | How far right the box extends. |
| `revOn` | true | Draw the counter-trend box at an RSI extreme. |
| `revLook` | 30 | Structure lookback for the reversal stop/target. |
| `revPad` | 1.0 ATR | Pad beyond the swing for the reversal stop. |
| `revMaxAge` | 60 | Keep a frozen reversal box this long after RSI leaves the zone. |
| `revHide` | true | Hide the trend box while a reversal box is active. |

## A.3 Screener parameters (new - not in the Pine)

| Parameter | Proposed default | Meaning |
|---|---|---|
| `mode` | `B` | `A` = divergence only; `B` = divergence OR score>=2; `C` = both, aligned. |
| `min_score` | 2 | Rule B threshold on `abs(score)`. |
| `div_fresh_bars` | 3 | Rule A recency window, in closed daily bars. |
| `signal_fresh_bars` | 3 | Rule B recency window. |
| `min_bars_warn` | 250 | Below this, flag `short_history`. |
| `min_bars_reject` | 60 | Below this, skip the symbol. |
| `min_price` | 0.02 / 1.00 / 0 | Per market (ASX / NASDAQ / crypto). |
| `min_dollar_adv` | 250k / 1m / 5m | 20-day average of close x volume. |
| `max_data_age_days` | 3 | Measured in the market's own calendar. |
| `frame_cache_max_age_days` | 10 | Refuse a cached frame older than this. |
| `exclude_products` | true | Drop funds, LICs, preferreds, warrants, rights, notes. |
| `exclude_stablecoins` | true | Crypto only. |
| `history_bars` | 750 | Bars to request per symbol. |


---

# APPENDIX B - GLOSSARY

Written for an implementer who may not trade. Every term is used in its precise sense
throughout this document.

| Term | Meaning here |
|---|---|
| **Bar** | One period of OHLCV data. Throughout this document, one daily bar. |
| **Closed bar** | A bar whose period has ended. Its OHLC can no longer change. Opposed to the **forming bar**, the one currently being built, whose close moves tick by tick. |
| **OHLCV** | Open, High, Low, Close, Volume. |
| **RSI** | Relative Strength Index. A 0-100 oscillator measuring the ratio of average gains to average losses over a window, Wilder-smoothed. Above 70 is conventionally "overbought", below 30 "oversold". This template uses 75/25 for its extremes. |
| **EMA** | Exponential moving average, weighting recent bars more heavily. `alpha = 2/(span+1)`. |
| **RMA / Wilder smoothing** | An EMA with `alpha = 1/period`. Used inside RSI and ATR. Not the same as an EMA of the same period. |
| **MACD** | The difference between a 12 and a 26 EMA (the MACD line), its 9-EMA (the signal line), and their difference (the **histogram**). A positive histogram means momentum is accelerating upward. |
| **ATR** | Average True Range. Wilder-smoothed average of the bar's true range. A volatility unit, used here to size stop padding. |
| **Pivot low / pivot high** | A bar whose value is the lowest/highest in a window extending `left` bars back and `right` bars forward. Cannot be identified until `right` bars have passed: this is the **confirmation lag**. |
| **Regular divergence** | Price and an oscillator disagreeing at consecutive pivots. **Bullish**: price makes a lower low while RSI makes a higher low, suggesting selling pressure is weakening. **Bearish**: price makes a higher high while RSI makes a lower high. |
| **Hidden divergence** | The continuation variant (price higher low, RSI lower low). Not implemented here. |
| **Crossover / crossunder** | An *event* on the single bar where one series moves from at-or-below to above another (or the reverse). Distinct from the *state* "A is above B", which persists. Confusing the two is the most common screener bug. |
| **Score (in this template)** | An integer 1-3 attached to a moving-average cross: 1 for the cross itself, +1 if the MACD histogram agrees, +1 if price is on the matching side of the 200 MA. Drawn as `Bullish +2`, `-3 Bearish` etc. |
| **Regime** | Which side of the slow MA the mid MA is on. `up` when `mid > slow`, `down` otherwise. Colours the slow line green or red. |
| **Freshness window** | How many recent closed bars the screener will look back over for an event. Necessary because the events are instantaneous. |
| **Repainting** | An indicator changing its historical output after the fact. A pivot-based signal repaints in the sense that it appears 5 bars late; it does not repaint in the sense of changing once confirmed. |
| **Look-ahead bias** | Using information in a computation for bar `i` that was not available at bar `i`. The fatal error class for screeners and backtests. |
| **ADV** | Average daily volume. Here, **dollar** ADV: the 20-day mean of `close x volume`, i.e. turnover. |
| **Survivorship bias** | Testing on a universe of currently-listed names, which excludes everything that failed and was delisted. Inflates every historical result. |
| **R / R-multiple** | A trade's profit or loss expressed as a multiple of its initial risk (entry to stop distance). Used by the trade box's TP1/TP2/TP3 at 1R/2R/3R. |
| **LIC** | Listed Investment Company. An ASX-listed closed-end fund. Trades like a stock, is not an operating business, and frequently carries no fund-like word in its name. |
| **Product** (in this repo's vocabulary) | Any listed thing that is not an operating company: ETF, trust, LIC, preferred line, warrant, right, note. |


---

# APPENDIX C - VERSION HISTORY OF THE TEMPLATE

Included because two of these entries are bugs that a reimplementation could repeat, and
because it shows which parts of the template are settled and which were guesses.

| Version | Change | Why it matters to a scanner |
|---|---|---|
| v1 | First build: 20/50/200 MAs, scored signals, RSI columns at 70/30, key levels with margin tags, trade box, background regime tint. | Compiled but was visually unusable: the regime tint swamped the dark theme and the RSI columns fired on most bars. |
| v2 | Background tint off by default; RSI columns moved to 75/25; level labels moved to the price scale; a distance filter added to hide levels more than 100% from price; auto stop capped at 15%; trade box limited to signals within 60 bars; inputs hidden from the status line. | **The 75/25 thresholds are the ones a scanner should use.** 70/30 produced near-constant "extreme" readings. |
| v3 | A key/legend table pinned to a chart corner, with three live rows (trend now, last signal with score and age, current trade written out). | Confirms the intended reading of a signal: direction + score + age. The scanner's output row mirrors this. |
| v4 | Entry/SL/TP tags drawn inside the pane instead of on the price scale, because the owner's chart has price-scale value labels switched off. | A reminder that chart settings, not code, decided what was visible. |
| v5 | The reversal box added: at an RSI extreme, draw a counter-trend position from the current close, stop beyond the recent swing plus an ATR pad, target at the opposite swing. | This is the pattern observed on the reference charts. Not part of the screen, but it is the shape of trade the owner is looking for after a divergence. |
| v5.1, v5.3 | Two rounds of fixing runtime error RE10140, "the script creates too many plots". | **The lesson that generalises: TradingView allows 64 plot slots; a plot whose colour is a compile-time literal costs 1 and a colour from an input or a series costs 2.** Both failures came from mis-counting this. Irrelevant to Python, but if anyone extends the Pine, this is the ceiling. |
| v5.2 | The three indicators renamed on the chart to `Vivek 5.0 Top` / `Vivek 5.0 MACD` / `Vivek 5.0 RSI+`. | Because several saved scripts shared the old name and the chart kept silently attaching to a v1 copy, so three "fixes" appeared to do nothing. If you ever debug a Pine script that seems not to change, check which saved copy the chart is actually running. |

## Things deliberately NOT built, and why

- **Hidden divergence** - the reference pane does not show it. Trivial to add later.
- **Multi-timeframe confluence** - out of scope for a daily screener.
- **Alerts routed anywhere** - the Pine exposes `alertcondition`s; nothing consumes them.
  The scanner replaces them.
- **Any connection to the owner's live paper-trading book** - the template is chart-only by
  construction, and the screener should stay that way too: it produces a list to look at,
  not an order.


---

# APPENDIX D - THE BASE-RATE MEASUREMENT

The hit-volume figures in Part 5.10, and the finding that `score >= 2` filters almost
nothing, come from this script. It is included so the measurement can be reproduced,
challenged, or re-run against real data once a provider is available.

## What it does and does not prove

**Does**: establish the order of magnitude of each rule's firing rate, and the relative
frequency of the three scores, under a null model with no trend structure.

**Does not**: predict real-market rates. A geometric random walk has no momentum, no
mean reversion, no volatility clustering and no earnings gaps. Real crosses will be
somewhat less frequent in trending names and more frequent in ranging ones.

The score-mix finding (score 1 is ~2% of crosses) is the robust part: it follows from the
scoring terms being three measurements of the same underlying move, and that correlation is
if anything **stronger** in real markets than in a random walk.

## The script

```python
"""Measure the per-day base rate of each screen rule on synthetic price series.

These are geometric random walks with a realistic daily volatility, NOT real
market data (the sandbox cannot reach a data provider). Real markets trend and
mean-revert, so real rates will differ - but the ORDER OF MAGNITUDE from a
random walk is the right sanity check for "did I implement the cross as an
event or as a state".
"""
import numpy as np
import pandas as pd

rng = np.random.default_rng(20260922)
N_SYMBOLS, N_BARS = 3000, 900
L = R = 5
RANGE_MIN, RANGE_MAX = 5, 60

def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def rma(s, period):
    return s.ewm(alpha=1 / period, adjust=False).mean()

def rsi_w(close, period=14):
    d = close.diff()
    gain = rma(d.clip(lower=0), period)
    loss = rma((-d).clip(lower=0), period)
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    return out.mask((loss == 0) & (gain > 0), 100.0)

def pivots_confirmed(s, L, R, low_side=True):
    """Boolean Series, True on bar i when bar i-R was a pivot."""
    w = L + R + 1
    ext = s.rolling(w, center=True).min() if low_side else s.rolling(w, center=True).max()
    at_k = (s == ext)
    # strictness on the left, non-strict on the right (Pine's comparison)
    left_ok = s.rolling(L + 1).min().shift(0) if low_side else s.rolling(L + 1).max()
    return at_k.shift(R).fillna(False)

results = {"bull_div": 0, "bear_div": 0, "cross": 0,
           "score1": 0, "score2": 0, "score3": 0, "bars": 0}

for _ in range(N_SYMBOLS):
    vol = rng.uniform(0.012, 0.045)              # 1.2% - 4.5% daily sigma
    drift = rng.normal(0.0002, 0.0006)
    r = rng.normal(drift, vol, N_BARS)
    close = pd.Series(100 * np.exp(np.cumsum(r)))
    # crude OHLC around the close
    high = close * (1 + np.abs(rng.normal(0, vol / 2, N_BARS)))
    low = close * (1 - np.abs(rng.normal(0, vol / 2, N_BARS)))

    rsi = rsi_w(close)
    fast, mid, slow = ema(close, 20), ema(close, 50), ema(close, 200)
    macd = ema(close, 12) - ema(close, 26)
    hist = macd - ema(macd, 9)

    # --- Rule B: crosses and scores
    up = (fast > mid) & (fast.shift(1) <= mid.shift(1))
    dn = (fast < mid) & (fast.shift(1) >= mid.shift(1))
    valid = slow.notna() & (close.index >= 250)
    up, dn = up & valid, dn & valid
    bs = 1 + (hist > 0).astype(int) + (close > slow).astype(int)
    ss = 1 + (hist < 0).astype(int) + (close < slow).astype(int)
    for mask, sc in ((up, bs), (dn, ss)):
        v = sc[mask]
        results["cross"] += int(mask.sum())
        results["score1"] += int((v == 1).sum())
        results["score2"] += int((v == 2).sum())
        results["score3"] += int((v == 3).sum())

    # --- Rule A: divergences
    pl = pivots_confirmed(rsi, L, R, True)
    ph = pivots_confirmed(rsi, L, R, False)
    for found, price, rsi_cmp, price_cmp in (
            (pl, low, "gt", "lt"), (ph, high, "lt", "gt")):
        idx = list(found[found & valid].index)
        prev = None
        n = 0
        for i in idx:
            if prev is not None and i - R >= 0 and prev - R >= 0:
                rv, rp = rsi.iloc[i - R], rsi.iloc[prev - R]
                pv, pp = price.iloc[i - R], price.iloc[prev - R]
                ok_r = rv > rp if rsi_cmp == "gt" else rv < rp
                ok_p = pv < pp if price_cmp == "lt" else pv > pp
                gap = i - (prev + 1)
                if ok_r and ok_p and RANGE_MIN <= gap <= RANGE_MAX:
                    n += 1
            prev = i
        results["bull_div" if rsi_cmp == "gt" else "bear_div"] += n

    results["bars"] += int(valid.sum())

sym_days = results["bars"]
print(f"simulated {N_SYMBOLS} symbols x ~{N_BARS-250} usable bars = "
      f"{sym_days:,} symbol-days\n")

def pct(n):
    return 100.0 * n / sym_days

print(f"{'event':<28} {'count':>9} {'per symbol-day':>16} "
      f"{'expected in 2200 names/day':>28}")
for k, label in (("cross", "any 20/50 cross"),
                 ("score1", "  score 1 (excluded)"),
                 ("score2", "  score 2"),
                 ("score3", "  score 3"),
                 ("bull_div", "bullish RSI divergence"),
                 ("bear_div", "bearish RSI divergence")):
    n = results[k]
    print(f"{label:<28} {n:>9,} {pct(n):>15.3f}% {pct(n)/100*2200:>27.1f}")

rb = results["score2"] + results["score3"]
ra = results["bull_div"] + results["bear_div"]
print()
print(f"RULE A (either direction)  : {pct(ra):.3f}% of symbol-days "
      f"-> ~{pct(ra)/100*2200:.0f} of 2200 ASX names per day")
print(f"RULE B (score >= 2)        : {pct(rb):.3f}% of symbol-days "
      f"-> ~{pct(rb)/100*2200:.0f} of 2200 ASX names per day")
print(f"score mix among crosses    : 1={100*results['score1']/results['cross']:.0f}%  "
      f"2={100*results['score2']/results['cross']:.0f}%  "
      f"3={100*results['score3']/results['cross']:.0f}%")
print()
print("With a 3-bar freshness window, multiply the per-day figures by ~3 "
      "(events rarely repeat on a symbol within 3 bars).")
```

## Its output

```
simulated 3000 symbols x ~650 usable bars = 1,950,000 symbol-days

event                            count   per symbol-day   expected in 2200 names/day
any 20/50 cross                 38,146           1.956%                        43.0
  score 1 (excluded)               950           0.049%                         1.1
  score 2                       13,990           0.717%                        15.8
  score 3                       23,206           1.190%                        26.2
bullish RSI divergence          14,819           0.760%                        16.7
bearish RSI divergence          16,925           0.868%                        19.1

RULE A (either direction)  : 1.628% of symbol-days -> ~36 of 2200 ASX names per day
RULE B (score >= 2)        : 1.907% of symbol-days -> ~42 of 2200 ASX names per day
score mix among crosses    : 1=2%  2=37%  3=61%

With a 3-bar freshness window, multiply the per-day figures by ~3 (events rarely repeat on a symbol within 3 bars).
```

## How to re-run it against real data

Replace the synthetic `close`/`high`/`low` construction with frames from your data
provider, keep everything else, and restrict the loop to symbols that pass the liquidity
gates. Report the same table. If the score mix shifts materially away from 2/37/61, say so:
it would mean the scoring terms are less correlated in practice than the null model says,
and `min_score` would be doing more work than Part 5.10 credits it with.


---

*End of document.*
