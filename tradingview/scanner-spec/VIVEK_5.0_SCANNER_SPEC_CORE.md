# VIVEK 5.0 SCANNER - CORE SPECIFICATION (condensed)

**This is the implementable subset of a longer document.** It contains everything needed to
write the screener and nothing else. The full version adds: a complete rule inventory of the
three Pine scripts, the verified semantics of every TradingView built-in with citations, the
Pine source itself, integration instructions for an existing repository, a validation plan,
performance notes and a base-rate study.

| | |
|---|---|
| Version | 1.0 (condensed from the full specification) |
| Date | 22 September 2026 |
| Task | Build a daily screener over ASX (~2,200), NASDAQ (~1,430) and crypto (~100) |
| Deliverable | A ranked shortlist per market for a human to review by eye |

## The screen in one paragraph

On the latest **closed** daily bar, a symbol is a hit if either:

- **RULE A**: the RSI has printed a regular **Bull** or **Bear** divergence within the last
  few sessions, or
- **RULE B**: a 20/50 EMA cross has printed within the last few sessions with a confidence
  score of **2 or 3**.

Mode A = Rule A only. Mode B = Rule A or Rule B. Mode C = both, directions agreeing.

## Read these three things before writing code

1. **Part 5** below is the requirement.
2. **Part 7** below is the list of ways this goes silently wrong. The single most important
   is that RSI divergence has a **5-bar detection lag** that must not be treated as zero.
3. **Part 6** below is a tested Python implementation you can lift wholesale. Its self-test
   passes 18/18 including a no-look-ahead proof.

## Two findings that change the design

- **"Score >= 2" is nearly a no-op.** Measured over 1.95 million simulated symbol-days,
  score 1 is only **2%** of all crosses (score 2 is 37%, score 3 is 61%). The scoring terms
  are correlated with the cross by construction, so raising the threshold cannot make Rule B
  selective. If you need selectivity, add an uncorrelated term such as volume expansion.
- **The two rules have different lags.** Rule B is knowable the day it fires; Rule A is
  knowable 5 bars after the pivot it describes. Two rows both reading "1 bar ago" refer to
  market events 6 bars apart in age. Report both numbers.


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

# PART 6 - PYTHON REFERENCE IMPLEMENTATION

Self-contained: pandas and numpy only, no TradingView dependency, no network. Its
companion self-test passes 18/18 assertions including a causality proof that truncates the
frame at each bar and re-derives the verdict.

Mirrors the Pine line for line. `ScreenConfig.mode` is **1** (Rule A only) or **2** (Rule A
or Rule B); Mode C is mode 2 plus a post-filter on `rules` containing both and the two
directions agreeing.

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

# PART 6B - END-TO-END RUNNER

Ties the module to a data provider, applies the market gates, and publishes the payload.
Verified end to end on synthetic frames with the download stubbed; the download path itself
has never run against a live provider.

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

*End of condensed specification.*
