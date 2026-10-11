# PhaseMap backtest — NASDAQ

Generated 2026-10-11 · ruleset v1.3.1 · universe 1428 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12432 | +1.4% | +1.7% | +2.2% | 40.8% | 9.6 | -8.6% |
| tier A+ | 1469 | +1.4% | +1.2% | +1.3% | 39.4% | 9.6 | -8.4% |
| tier A | 6930 | +1.4% | +1.8% | +2.1% | 40.3% | 9.9 | -8.8% |
| long | 5817 | +1.5% | +2.5% | +3.9% | 43.2% | 9.3 | -8.0% |
| short | 6615 | +1.3% | +1.1% | +0.7% | 38.7% | 10.0 | -9.2% |
| liquid | 11459 | +1.5% | +1.8% | +2.3% | 41.6% | 9.6 | -8.7% |
| illiquid | 973 | +0.8% | +0.7% | +1.3% | 31.8% | 9.8 | -7.8% |
| price >= $1 | 12378 | +1.4% | +1.7% | +2.2% | 40.8% | 9.6 | -8.5% |
| cents (<$1) | 54 | +6.3% | +1.3% | +9.7% | 48.1% | 6.9 | -23.5% |
| in-sample | 9090 | +1.5% | +2.0% | +2.6% | 41.8% | 9.7 | -8.3% |
| out-of-sample | 3342 | +1.2% | +1.0% | +1.0% | 38.2% | 9.2 | -9.3% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 3998 | 54.1% | +1686.1R | -1592.4R | **+93.7R** | +0.023R | 1.06 | $+19,549 |
| long A+/A, stop at the worst print | 3998 | 54.1% | +1686.1R | -1887.3R | **-201.2R** | -0.050R | 0.89 | $-6,549 |
| long A+/A, engine-native close exits | 3998 | 56.7% | +1784.2R | -1630.5R | **+153.7R** | +0.038R | 1.09 | $+26,106 |
| long A+/A, liquid only | 3670 | 54.9% | +1550.0R | -1432.6R | **+117.4R** | +0.032R | 1.08 | $+20,201 |
| short A+/A | 4359 | 49.3% | +1659.6R | -2044.6R | **-385.0R** | -0.088R | 0.81 | $-40,501 |
| bullish A+ | 689 | 51.4% | +280.3R | -292.0R | **-11.7R** | -0.017R | 0.96 | $+1,179 |
| bullish A | 3309 | 54.6% | +1405.8R | -1300.4R | **+105.4R** | +0.032R | 1.08 | $+18,370 |
| bullish Watch | 1806 | 56.5% | +786.5R | -705.2R | **+81.3R** | +0.045R | 1.12 | $+14,637 |
| bearish A+ | 778 | 46.3% | +254.9R | -371.6R | **-116.7R** | -0.150R | 0.69 | $-8,522 |
| bearish A | 3581 | 50.0% | +1404.7R | -1673.0R | **-268.3R** | -0.075R | 0.84 | $-31,979 |
| bearish Watch | 2210 | 49.4% | +851.6R | -1009.6R | **-158.0R** | -0.071R | 0.84 | $-14,855 |
| exit: t1 | 5297 | 100.0% | +4419.8R | 0.0R | **+4419.8R** | +0.834R | — | $+485,023 |
| exit: stop | 4415 | 0.0% | +0.0R | -4760.5R | **-4760.5R** | -1.078R | 0.0 | $-484,559 |
| exit: engine_end | 2543 | 42.5% | +548.1R | -565.4R | **-17.3R** | -0.007R | 0.97 | $-21,055 |
| exit: eod | 118 | 39.0% | +15.9R | -25.9R | **-10.0R** | -0.084R | 0.62 | $-580 |

Not traded: signal on the last bar 5, stop_too_tight 54

## Baselines (same tickers, same window)
- Random entry (11530 samples, seeded): fwd 5: +0.5% · fwd 10: +1.0% · fwd 20: +2.3%
- Buy & hold (1330 tickers): +87.9% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11231
- Saved capital (hard floor broke first after the stall): 3378
- Cut a winner (T1 was still consumed first): 4633
- Neither within the tracking window: 3220

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
