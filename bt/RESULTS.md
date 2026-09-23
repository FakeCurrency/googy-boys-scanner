# Like-for-like R across the four lenses -- 2026-09-24

One fill rule, one cost table, one notional, one minimum stop, applied to every lens's own signals over the same downloaded bars. The HEADLINE IS LONG ONLY; shorts are in the appendix and are in no win% above it.

- **House fill** (the headline): a stop is a resting order, filled at the stop or at the open of a bar that gapped through it.
- **Worst print** (second column): the SAME trades, a stop filled at the bar's worst print -- the 5.0 backtest's convention. Exit timing is identical, so both columns are one trade set; the difference is purely the fill.
- Costs: the house table, basis points per side -- ASX slippage 5 + commission 2; NASDAQ slippage 4 + commission 1; CRYPTO slippage 8 + commission 6. $ at $1,000 a trade = R x 1,000 x risk / entry. Minimum stop 1% of entry: a closer stop is not a trade in any lens.
- Window: 5y of daily bars; trades entered 2021-11-10 to 2026-09-23. Universe: today's, less the bot's fund/REIT exclusion, identically for all four lenses.

## Coverage

- **ASX**: 1,738 downloaded / 2,046 in the universe (84.9%); 150 funds/REITs excluded, 1,588 names replayed; shards 16/16.
- **NASDAQ**: 119 downloaded / 1,428 in the universe (8.3%); 6 funds/REITs excluded, 113 names replayed; shards 1/12 -- MISSING shards [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11], so the missing names are not in any number below.
- **CRYPTO**: 61 downloaded / 86 in the universe (70.9%); 0 funds/REITs excluded, 61 names replayed; shards 1/1.

Survivorship: every market is replayed on TODAY's universe, so names that delisted, were acquired or went to zero inside the window are missing, and every number below is flattered by that -- none of it is corrected for.

## Headline -- longs only

| lens | fill rule | net R | R/trade | win% | n | $ at $1k |
|---|---|---|---|---|---|---|
| VIVEK 5.0: armed A+/A plans, 1D/3D/1W | house | +739.2 | +0.095 | 51.4% | 7,797 | +$142,731 |
| VIVEK 5.0: armed A+/A plans, 1D/3D/1W | worst print | -108.4 | -0.014 | 45.7% | 7,797 | +$13,548 |
| PhaseMap: bullish A+/A signals | house | -293.1 | -0.055 | 40.9% | 5,281 | +$65,651 |
| PhaseMap: bullish A+/A signals | worst print | -724.2 | -0.137 | 40.9% | 5,281 | +$18,118 |
| Momentum: Rule A + Rule B longs | house | +563.1 | +0.084 | 51.1% | 6,666 | +$59,852 |
| Momentum: Rule A + Rule B longs | worst print | -984.5 | -0.148 | 44.6% | 6,666 | -$39,541 |
| Specs: every signal, A+/A/B | house | -646.9 | -0.072 | 41.6% | 9,018 | -$184,077 |
| Specs: every signal, A+/A/B | worst print | -1,229.7 | -0.136 | 41.6% | 9,018 | -$290,488 |

## VIVEK 5.0 -- the splits that must stay visible (longs)

| lens | fill rule | net R | R/trade | win% | n | $ at $1k |
|---|---|---|---|---|---|---|
| 5.0 1D | house | +216.8 | +0.056 | 50.4% | 3,891 | +$34,639 |
| 5.0 1D | worst print | -310.2 | -0.080 | 43.8% | 3,891 | -$32,922 |
| 5.0 3D | house | +315.9 | +0.126 | 53.2% | 2,500 | +$70,656 |
| 5.0 3D | worst print | +87.8 | +0.035 | 47.5% | 2,500 | +$31,153 |
| 5.0 1W | house | +206.5 | +0.147 | 50.9% | 1,406 | +$37,435 |
| 5.0 1W | worst print | +114.0 | +0.081 | 47.7% | 1,406 | +$15,318 |
| 5.0 all A+/A | house | +739.2 | +0.095 | 51.4% | 7,797 | +$142,731 |
| 5.0 all A+/A | worst print | -108.4 | -0.014 | 45.7% | 7,797 | +$13,548 |
| 5.0 high-conviction cells (any of the four) | house | +429.3 | +0.189 | 51.0% | 2,274 | +$85,832 |
| 5.0 high-conviction cells (any of the four) | worst print | +271.6 | +0.119 | 47.5% | 2,274 | +$50,836 |
| 5.0 not a high-conviction cell | house | +309.9 | +0.056 | 51.6% | 5,523 | +$56,899 |
| 5.0 not a high-conviction cell | worst print | -379.9 | -0.069 | 45.0% | 5,523 | -$37,287 |
| 5.0 cell: 1W reclaim | house | +97.2 | +0.156 | 47.1% | 622 | +$6,507 |
| 5.0 cell: 1W reclaim | worst print | +64.5 | +0.104 | 45.0% | 622 | -$2,460 |
| 5.0 cell: 1W break | house | +32.8 | +0.157 | 56.9% | 209 | +$13,665 |
| 5.0 cell: 1W break | worst print | +24.4 | +0.117 | 52.2% | 209 | +$10,175 |
| 5.0 cell: 3D reclaim | house | +262.9 | +0.226 | 50.2% | 1,161 | +$63,067 |
| 5.0 cell: 3D reclaim | worst print | +170.6 | +0.147 | 47.7% | 1,161 | +$45,080 |
| 5.0 cell: 1D break | house | +36.5 | +0.129 | 58.2% | 282 | +$2,593 |
| 5.0 cell: 1D break | worst print | +12.1 | +0.043 | 48.6% | 282 | -$1,960 |
| 5.0 bot rule (four cells, weekly/3d level) | house | +407.5 | +0.214 | 51.8% | 1,908 | +$87,789 |
| 5.0 bot rule (four cells, weekly/3d level) | worst print | +271.6 | +0.142 | 48.1% | 1,908 | +$58,904 |
| 5.0 grade A+ | house | +210.4 | +0.060 | 50.0% | 3,525 | +$27,101 |
| 5.0 grade A+ | worst print | -161.8 | -0.046 | 44.0% | 3,525 | -$27,893 |
| 5.0 grade A | house | +528.8 | +0.124 | 52.6% | 4,272 | +$115,630 |
| 5.0 grade A | worst print | +53.4 | +0.013 | 47.1% | 4,272 | +$41,441 |

## Momentum -- Rule A vs Rule B by market (longs; live min_signal_score = 2)

| lens | fill rule | net R | R/trade | win% | n | $ at $1k |
|---|---|---|---|---|---|---|
| Momentum Rule A ASX | house | +155.1 | +0.077 | 50.7% | 2,016 | +$15,170 |
| Momentum Rule A ASX | worst print | -423.9 | -0.210 | 43.6% | 2,016 | -$13,716 |
| Momentum Rule A NASDAQ | house | +38.4 | +0.082 | 50.5% | 469 | +$6,634 |
| Momentum Rule A NASDAQ | worst print | -80.4 | -0.171 | 42.6% | 469 | +$464 |
| Momentum Rule A CRYPTO | house | +37.5 | +0.090 | 51.0% | 416 | +$381 |
| Momentum Rule A CRYPTO | worst print | -74.9 | -0.180 | 42.1% | 416 | -$7,140 |
| Momentum Rule A all markets | house | +230.9 | +0.080 | 50.7% | 2,901 | +$22,185 |
| Momentum Rule A all markets | worst print | -579.1 | -0.200 | 43.2% | 2,901 | -$20,393 |
| Momentum Rule B ASX | house | +204.3 | +0.076 | 51.8% | 2,676 | +$23,903 |
| Momentum Rule B ASX | worst print | -301.6 | -0.113 | 46.0% | 2,676 | -$13,936 |
| Momentum Rule B NASDAQ | house | -13.7 | -0.022 | 48.0% | 617 | +$1,213 |
| Momentum Rule B NASDAQ | worst print | -139.5 | -0.226 | 42.6% | 617 | -$8,645 |
| Momentum Rule B CRYPTO | house | +141.5 | +0.300 | 53.2% | 472 | +$12,552 |
| Momentum Rule B CRYPTO | worst print | +35.7 | +0.076 | 47.7% | 472 | +$3,433 |
| Momentum Rule B all markets | house | +332.1 | +0.088 | 51.3% | 3,765 | +$37,668 |
| Momentum Rule B all markets | worst print | -405.4 | -0.108 | 45.7% | 3,765 | -$19,148 |

## Every lens by market (longs)

| lens | fill rule | net R | R/trade | win% | n | $ at $1k |
|---|---|---|---|---|---|---|
| VIVEK 5.0 ASX | house | +379.7 | +0.061 | 50.1% | 6,236 | +$57,718 |
| VIVEK 5.0 ASX | worst print | -272.3 | -0.044 | 44.5% | 6,236 | -$38,241 |
| VIVEK 5.0 NASDAQ | house | +158.6 | +0.168 | 56.0% | 945 | +$38,430 |
| VIVEK 5.0 NASDAQ | worst print | +70.6 | +0.075 | 50.2% | 945 | +$26,992 |
| VIVEK 5.0 CRYPTO | house | +200.9 | +0.326 | 57.5% | 616 | +$46,583 |
| VIVEK 5.0 CRYPTO | worst print | +93.4 | +0.152 | 50.8% | 616 | +$24,797 |
| PhaseMap ASX | house | -577.9 | -0.125 | 38.9% | 4,612 | -$81,594 |
| PhaseMap ASX | worst print | -953.4 | -0.207 | 38.9% | 4,612 | -$122,757 |
| PhaseMap NASDAQ | house | -5.0 | -0.015 | 53.7% | 324 | -$222 |
| PhaseMap NASDAQ | worst print | -27.4 | -0.085 | 53.7% | 324 | -$2,667 |
| PhaseMap CRYPTO | house | +289.8 | +0.840 | 56.5% | 345 | +$147,467 |
| PhaseMap CRYPTO | worst print | +256.6 | +0.744 | 56.5% | 345 | +$143,542 |
| Momentum ASX | house | +359.4 | +0.077 | 51.3% | 4,692 | +$39,073 |
| Momentum ASX | worst print | -725.4 | -0.155 | 44.9% | 4,692 | -$27,652 |
| Momentum NASDAQ | house | +24.8 | +0.023 | 49.1% | 1,086 | +$7,847 |
| Momentum NASDAQ | worst print | -219.9 | -0.203 | 42.6% | 1,086 | -$8,181 |
| Momentum CRYPTO | house | +179.0 | +0.202 | 52.1% | 888 | +$12,932 |
| Momentum CRYPTO | worst print | -39.1 | -0.044 | 45.0% | 888 | -$3,708 |
| Specs ASX | house | -643.4 | -0.071 | 41.6% | 9,013 | -$182,259 |
| Specs ASX | worst print | -1,225.9 | -0.136 | 41.6% | 9,013 | -$288,488 |
| Specs NASDAQ | house | -3.5 | -0.691 | 0.0% | 5 | -$1,819 |
| Specs NASDAQ | worst print | -3.8 | -0.764 | 0.0% | 5 | -$2,000 |

## PhaseMap reference -- the engine's own close-only exits (longs)

The house rule stops a PhaseMap trade on the first print through the INVALIDATION_HARD floor; the spec says a wick through is a test and only a CLOSE through kills the setup. This column reads the engine natively (every exit at a close) so the cost of the house rule to this lens is visible.

| lens | fill rule | net R | R/trade | win% | n | $ at $1k |
|---|---|---|---|---|---|---|
| PhaseMap (bullish A+/A) | engine close | -309.0 | -0.059 | 42.8% | 5,281 | +$67,574 |

## Appendix -- shorts (never in a headline number)

| lens | fill rule | net R | R/trade | win% | n | $ at $1k |
|---|---|---|---|---|---|---|
| VIVEK 5.0 shorts | house | -338.1 | -0.074 | 52.3% | 4,550 | -$69,014 |
| VIVEK 5.0 shorts | worst print | -877.9 | -0.193 | 49.3% | 4,550 | -$150,312 |
| PhaseMap shorts | house | -538.9 | -0.104 | 48.4% | 5,192 | -$103,380 |
| PhaseMap shorts | worst print | -5,230.7 | -1.007 | 48.4% | 5,192 | -$2,281,132 |
| Momentum shorts | house | -866.1 | -0.108 | 47.9% | 8,011 | -$63,515 |
| Momentum shorts | worst print | -2,784.1 | -0.348 | 46.0% | 8,011 | -$196,368 |

Specs has no short side. 5.0 shorts come from a separate both-directions replay, because a short holds a timeframe slot a long would otherwise take; the headline 5.0 longs are the long-only replay, as the bot trades.

## Checks

- 5.0 re-score: 17,790 engine trades (both 5.0 replays) re-scored from the fill bar; the worst-print column reproduced the engine's own realized_r on all but 14.
- Refused by the 1% minimum stop: 5.0 7, PhaseMap 26, momentum 207, Specs 6.
- Momentum signals removed by its own gates: {'turnover': 24043, 'price': 5114, 'non-operating listing': 361, 'no volume in the last': 359, 'stop_too_tight': 207, 'no price range in the last': 3}.
- Still open at the end of the data (marked at the last close), longs: VIVEK 5.0 1,250, PhaseMap 57, Momentum 346, Specs 274.
