# PhaseMap backtest — ASX

Generated 2026-10-04 · ruleset v1.3.1 · universe 2048 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 9006 | +0.7% | +0.8% | +0.9% | 30.1% | 10.1 | -12.6% |
| tier A+ | 1155 | +0.1% | -0.1% | +0.5% | 30.4% | 10.0 | -11.8% |
| tier A | 5087 | +0.7% | +0.7% | +0.8% | 29.7% | 10.5 | -12.9% |
| long | 4472 | +1.0% | +1.1% | +1.2% | 30.0% | 8.7 | -11.4% |
| short | 4534 | +0.5% | +0.4% | +0.7% | 30.2% | 11.5 | -13.8% |
| liquid | 2550 | +1.7% | +1.7% | +2.2% | 40.7% | 9.3 | -8.3% |
| illiquid | 6456 | +0.3% | +0.4% | +0.4% | 25.9% | 10.7 | -14.3% |
| price >= $1 | 2887 | +0.9% | +0.8% | +0.9% | 37.6% | 9.0 | -6.7% |
| cents (<$1) | 6119 | +0.7% | +0.8% | +0.9% | 26.5% | 10.9 | -15.4% |
| in-sample | 6634 | +0.7% | +0.7% | +0.9% | 30.4% | 10.3 | -12.3% |
| out-of-sample | 2372 | +1.0% | +1.0% | +0.8% | 29.2% | 9.6 | -13.4% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 3066 | 38.4% | +1128.5R | -1533.3R | **-404.8R** | -0.132R | 0.74 | $-43,604 |
| long A+/A, stop at the worst print | 3066 | 38.4% | +1128.5R | -1800.3R | **-671.8R** | -0.219R | 0.63 | $-70,969 |
| long A+/A, engine-native close exits | 3066 | 40.4% | +1176.1R | -1606.9R | **-430.8R** | -0.141R | 0.73 | $-43,347 |
| long A+/A, liquid only | 742 | 51.6% | +286.5R | -306.2R | **-19.7R** | -0.027R | 0.94 | $-1,568 |
| short A+/A | 3151 | 46.2% | +1084.6R | -1576.4R | **-491.8R** | -0.156R | 0.69 | $-78,580 |
| bullish A+ | 549 | 40.6% | +186.5R | -262.7R | **-76.2R** | -0.139R | 0.71 | $-15,612 |
| bullish A | 2517 | 37.9% | +942.1R | -1270.6R | **-328.6R** | -0.131R | 0.74 | $-27,992 |
| bullish Watch | 1390 | 39.6% | +572.9R | -688.9R | **-116.0R** | -0.083R | 0.83 | $-15,162 |
| bearish A+ | 603 | 46.3% | +194.5R | -276.8R | **-82.3R** | -0.136R | 0.7 | $-14,686 |
| bearish A | 2548 | 46.2% | +890.1R | -1299.6R | **-409.5R** | -0.161R | 0.68 | $-63,895 |
| bearish Watch | 1360 | 47.2% | +503.0R | -634.7R | **-131.7R** | -0.097R | 0.79 | $-14,839 |
| exit: t1 | 2856 | 100.0% | +2789.0R | 0.0R | **+2789.0R** | +0.977R | — | $+409,349 |
| exit: stop | 3404 | 0.0% | +0.0R | -3811.3R | **-3811.3R** | -1.120R | 0.0 | $-511,975 |
| exit: engine_end | 2594 | 35.5% | +476.5R | -602.9R | **-126.4R** | -0.049R | 0.79 | $-50,506 |
| exit: eod | 113 | 40.7% | +23.6R | -19.1R | **+4.5R** | +0.039R | 1.23 | $+948 |

Not traded: signal on the last bar 6, stop_too_tight 33

## Baselines (same tickers, same window)
- Random entry (8569 samples, seeded): fwd 5: +0.3% · fwd 10: +2.0% · fwd 20: +1.7%
- Buy & hold (1017 tickers): +25.9% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 8043
- Saved capital (hard floor broke first after the stall): 2420
- Cut a winner (T1 was still consumed first): 2552
- Neither within the tracking window: 3071

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
