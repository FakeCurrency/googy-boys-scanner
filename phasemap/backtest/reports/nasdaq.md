# PhaseMap backtest — NASDAQ

Generated 2026-09-27 · ruleset v1.3.1 · universe 1429 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12514 | +1.4% | +1.7% | +2.2% | 40.7% | 9.6 | -8.6% |
| tier A+ | 1475 | +1.4% | +1.3% | +1.3% | 39.7% | 9.5 | -8.3% |
| tier A | 6967 | +1.3% | +1.8% | +2.1% | 40.0% | 9.9 | -8.8% |
| long | 5851 | +1.5% | +2.5% | +3.9% | 43.3% | 9.2 | -8.0% |
| short | 6663 | +1.3% | +1.0% | +0.7% | 38.4% | 10.0 | -9.1% |
| liquid | 11535 | +1.4% | +1.8% | +2.3% | 41.5% | 9.6 | -8.7% |
| illiquid | 979 | +0.8% | +0.8% | +1.2% | 31.1% | 9.4 | -7.8% |
| price >= $1 | 12460 | +1.4% | +1.7% | +2.1% | 40.7% | 9.6 | -8.5% |
| cents (<$1) | 54 | +6.3% | +1.1% | +8.7% | 48.1% | 6.9 | -23.5% |
| in-sample | 9252 | +1.4% | +1.9% | +2.6% | 41.6% | 9.7 | -8.3% |
| out-of-sample | 3262 | +1.2% | +1.0% | +1.1% | 38.1% | 9.3 | -9.3% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 4005 | 54.0% | +1676.2R | -1597.9R | **+78.3R** | +0.020R | 1.05 | $+16,870 |
| long A+/A, stop at the worst print | 4005 | 54.0% | +1676.2R | -1893.1R | **-216.9R** | -0.054R | 0.89 | $-9,400 |
| long A+/A, engine-native close exits | 4005 | 56.7% | +1778.8R | -1629.2R | **+149.7R** | +0.037R | 1.09 | $+23,984 |
| long A+/A, liquid only | 3672 | 54.8% | +1546.7R | -1435.5R | **+111.2R** | +0.030R | 1.08 | $+18,464 |
| short A+/A | 4402 | 49.1% | +1664.3R | -2070.0R | **-405.7R** | -0.092R | 0.8 | $-41,842 |
| bullish A+ | 691 | 52.0% | +280.6R | -289.8R | **-9.2R** | -0.013R | 0.97 | $+1,102 |
| bullish A | 3314 | 54.5% | +1395.7R | -1308.1R | **+87.6R** | +0.026R | 1.07 | $+15,768 |
| bullish Watch | 1833 | 56.9% | +804.9R | -707.5R | **+97.4R** | +0.053R | 1.14 | $+15,902 |
| bearish A+ | 782 | 45.9% | +257.2R | -374.9R | **-117.8R** | -0.151R | 0.69 | $-8,269 |
| bearish A | 3620 | 49.8% | +1407.1R | -1695.1R | **-288.0R** | -0.080R | 0.83 | $-33,573 |
| bearish Watch | 2221 | 49.4% | +851.9R | -1016.0R | **-164.1R** | -0.074R | 0.84 | $-14,503 |
| exit: t1 | 5316 | 100.0% | +4425.7R | 0.0R | **+4425.7R** | +0.833R | — | $+486,362 |
| exit: stop | 4441 | 0.0% | +0.0R | -4786.5R | **-4786.5R** | -1.078R | 0.0 | $-485,910 |
| exit: engine_end | 2591 | 42.5% | +554.0R | -581.2R | **-27.2R** | -0.011R | 0.95 | $-22,721 |
| exit: eod | 113 | 42.5% | +17.6R | -23.7R | **-6.0R** | -0.053R | 0.74 | $-1,304 |

Not traded: signal on the last bar 5, stop_too_tight 48

## Baselines (same tickers, same window)
- Random entry (11608 samples, seeded): fwd 5: +0.6% · fwd 10: +1.0% · fwd 20: +1.9%
- Buy & hold (1336 tickers): +92.0% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11318
- Saved capital (hard floor broke first after the stall): 3398
- Cut a winner (T1 was still consumed first): 4656
- Neither within the tracking window: 3264

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
