# PhaseMap backtest — CRYPTO

Generated 2026-10-04 · ruleset v1.3.1 · universe 201 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1878 | +2.4% | +31.5% | -50.3% | 44.7% | 8.5 | -113.9% |
| tier A+ | 257 | +1.3% | +5.2% | +63.0% | 49.8% | 8.0 | -25.2% |
| tier A | 1188 | +2.7% | +2.3% | -138.1% | 44.6% | 8.7 | -168.6% |
| long | 1014 | +3.2% | +56.9% | +71.6% | 47.2% | 7.3 | -13.4% |
| short | 864 | +1.5% | +1.5% | -197.3% | 41.7% | 9.9 | -231.8% |
| liquid | 1641 | +3.1% | +2.9% | +4.2% | 45.5% | 8.3 | -14.8% |
| illiquid | 237 | -2.0% | +229.1% | -423.4% | 38.8% | 9.7 | -800.2% |
| price >= $1 | 865 | +3.2% | +2.9% | +3.4% | 45.9% | 8.3 | -13.3% |
| cents (<$1) | 1013 | +1.8% | +56.2% | -96.9% | 43.6% | 8.6 | -199.8% |
| in-sample | 1259 | +1.8% | +45.4% | -75.0% | 44.4% | 9.0 | -152.0% |
| out-of-sample | 619 | +3.6% | +2.7% | +4.3% | 45.2% | 7.4 | -36.4% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 760 | 56.4% | +627.6R | -286.3R | **+341.3R** | +0.449R | 2.19 | $+154,234 |
| long A+/A, stop at the worst print | 760 | 56.4% | +627.6R | -358.2R | **+269.4R** | +0.355R | 1.75 | $+144,645 |
| long A+/A, engine-native close exits | 760 | 58.2% | +640.0R | -314.8R | **+325.2R** | +0.428R | 2.03 | $+153,280 |
| long A+/A, liquid only | 658 | 57.3% | +323.7R | -244.0R | **+79.7R** | +0.121R | 1.33 | $+9,228 |
| short A+/A | 685 | 54.2% | +257.3R | -281.0R | **-23.7R** | -0.035R | 0.92 | $-732,479 |
| bullish A+ | 125 | 58.4% | +292.8R | -47.1R | **+245.7R** | +1.966R | 6.22 | $+145,882 |
| bullish A | 635 | 56.1% | +334.8R | -239.3R | **+95.5R** | +0.150R | 1.4 | $+8,352 |
| bullish Watch | 254 | 46.9% | +2882.9R | -110.3R | **+2772.6R** | +10.916R | 26.14 | $+424,675 |
| bearish A+ | 132 | 59.1% | +55.5R | -47.3R | **+8.2R** | +0.062R | 1.17 | $-643 |
| bearish A | 553 | 53.0% | +201.8R | -233.7R | **-31.9R** | -0.058R | 0.86 | $-731,836 |
| bearish Watch | 179 | 58.1% | +81.3R | -65.7R | **+15.6R** | +0.087R | 1.24 | $+555 |
| exit: t1 | 872 | 100.0% | +3780.8R | 0.0R | **+3780.8R** | +4.336R | — | $+699,249 |
| exit: stop | 638 | 0.0% | +0.0R | -654.8R | **-654.8R** | -1.026R | 0.0 | $-840,335 |
| exit: engine_end | 344 | 41.9% | +67.6R | -82.2R | **-14.7R** | -0.043R | 0.82 | $-10,966 |
| exit: eod | 24 | 29.2% | +0.8R | -6.3R | **-5.5R** | -0.230R | 0.12 | $-964 |

## Baselines (same tickers, same window)
- Random entry (1764 samples, seeded): fwd 5: +0.8% · fwd 10: +1.7% · fwd 20: +46633.9%
- Buy & hold (138 tickers): +2965.0% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 1755
- Saved capital (hard floor broke first after the stall): 518
- Cut a winner (T1 was still consumed first): 801
- Neither within the tracking window: 436

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
