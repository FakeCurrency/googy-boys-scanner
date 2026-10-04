# PhaseMap backtest — NASDAQ

Generated 2026-10-04 · ruleset v1.3.1 · universe 1431 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12483 | +1.4% | +1.7% | +2.2% | 40.7% | 9.6 | -8.6% |
| tier A+ | 1465 | +1.4% | +1.3% | +1.3% | 39.7% | 9.6 | -8.4% |
| tier A | 6943 | +1.4% | +1.8% | +2.1% | 40.1% | 9.9 | -8.8% |
| long | 5854 | +1.5% | +2.5% | +3.9% | 43.1% | 9.3 | -8.0% |
| short | 6629 | +1.3% | +1.1% | +0.7% | 38.5% | 10.0 | -9.2% |
| liquid | 11504 | +1.4% | +1.8% | +2.3% | 41.5% | 9.6 | -8.7% |
| illiquid | 979 | +0.8% | +0.7% | +1.2% | 30.8% | 9.9 | -7.8% |
| price >= $1 | 12429 | +1.4% | +1.7% | +2.2% | 40.7% | 9.6 | -8.5% |
| cents (<$1) | 54 | +6.0% | +1.1% | +9.5% | 48.1% | 6.9 | -23.5% |
| in-sample | 9174 | +1.5% | +2.0% | +2.6% | 41.7% | 9.8 | -8.3% |
| out-of-sample | 3309 | +1.2% | +0.9% | +1.0% | 38.0% | 9.3 | -9.4% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 4002 | 54.0% | +1691.2R | -1595.0R | **+96.2R** | +0.024R | 1.06 | $+18,706 |
| long A+/A, stop at the worst print | 4002 | 54.0% | +1691.2R | -1891.2R | **-200.0R** | -0.050R | 0.89 | $-7,613 |
| long A+/A, engine-native close exits | 4002 | 56.5% | +1788.9R | -1637.9R | **+151.1R** | +0.038R | 1.09 | $+24,785 |
| long A+/A, liquid only | 3670 | 54.9% | +1555.1R | -1433.8R | **+121.2R** | +0.033R | 1.08 | $+19,673 |
| short A+/A | 4366 | 49.5% | +1668.4R | -2043.8R | **-375.5R** | -0.086R | 0.82 | $-39,653 |
| bullish A+ | 687 | 51.4% | +278.8R | -290.7R | **-11.9R** | -0.017R | 0.96 | $+999 |
| bullish A | 3315 | 54.6% | +1412.4R | -1304.3R | **+108.1R** | +0.033R | 1.08 | $+17,707 |
| bullish Watch | 1837 | 56.4% | +795.8R | -720.2R | **+75.6R** | +0.041R | 1.1 | $+13,863 |
| bearish A+ | 777 | 46.7% | +263.1R | -365.7R | **-102.6R** | -0.132R | 0.72 | $-7,269 |
| bearish A | 3589 | 50.1% | +1405.3R | -1678.2R | **-272.9R** | -0.076R | 0.84 | $-32,384 |
| bearish Watch | 2219 | 49.0% | +846.6R | -1021.2R | **-174.6R** | -0.079R | 0.83 | $-15,208 |
| exit: t1 | 5306 | 100.0% | +4432.9R | 0.0R | **+4432.9R** | +0.835R | — | $+486,497 |
| exit: stop | 4441 | 0.0% | +0.0R | -4788.9R | **-4788.9R** | -1.078R | 0.0 | $-487,171 |
| exit: engine_end | 2571 | 42.7% | +552.4R | -569.0R | **-16.6R** | -0.006R | 0.97 | $-21,218 |
| exit: eod | 106 | 38.7% | +16.8R | -22.4R | **-5.6R** | -0.053R | 0.75 | $-401 |

Not traded: signal on the last bar 7, stop_too_tight 52

## Baselines (same tickers, same window)
- Random entry (11631 samples, seeded): fwd 5: +0.5% · fwd 10: +1.1% · fwd 20: +1.8%
- Buy & hold (1336 tickers): +97.4% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11281
- Saved capital (hard floor broke first after the stall): 3399
- Cut a winner (T1 was still consumed first): 4642
- Neither within the tracking window: 3240

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
