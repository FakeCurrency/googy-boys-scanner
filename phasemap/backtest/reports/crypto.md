# PhaseMap backtest — CRYPTO

Generated 2026-09-27 · ruleset v1.3.1 · universe 86 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 864 | +2.5% | +2.2% | -171.8% | 42.2% | 9.4 | -223.3% |
| tier A+ | 107 | +0.9% | +1.1% | +141.3% | 46.7% | 9.2 | -16.0% |
| tier A | 544 | +2.9% | +2.2% | -304.2% | 42.1% | 9.7 | -347.0% |
| long | 461 | +2.6% | +2.6% | +39.4% | 45.8% | 7.7 | -12.1% |
| short | 403 | +2.4% | +1.8% | -417.5% | 38.2% | 11.6 | -464.9% |
| liquid | 776 | +2.7% | +2.4% | +3.3% | 43.4% | 9.1 | -13.1% |
| illiquid | 88 | +0.9% | +0.9% | -1699.2% | 31.8% | 12.9 | -2077.2% |
| price >= $1 | 512 | +2.9% | +1.9% | +3.0% | 43.0% | 8.7 | -11.5% |
| cents (<$1) | 352 | +1.9% | +2.8% | -426.8% | 41.2% | 10.5 | -531.4% |
| in-sample | 602 | +2.1% | +2.1% | -242.9% | 40.5% | 10.0 | -292.2% |
| out-of-sample | 262 | +3.4% | +2.6% | +3.7% | 46.2% | 8.3 | -65.1% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 340 | 56.8% | +417.3R | -125.9R | **+291.4R** | +0.857R | 3.32 | $+147,900 |
| long A+/A, stop at the worst print | 340 | 56.8% | +417.3R | -158.7R | **+258.6R** | +0.761R | 2.63 | $+144,027 |
| long A+/A, engine-native close exits | 340 | 58.2% | +421.0R | -135.8R | **+285.2R** | +0.839R | 3.1 | $+147,410 |
| long A+/A, liquid only | 300 | 58.3% | +156.3R | -109.9R | **+46.4R** | +0.155R | 1.42 | $+4,870 |
| short A+/A | 311 | 52.7% | +110.8R | -132.5R | **-21.6R** | -0.070R | 0.84 | $-4,607 |
| bullish A+ | 50 | 52.0% | +255.1R | -20.2R | **+234.9R** | +4.698R | 12.63 | $+143,889 |
| bullish A | 290 | 57.6% | +162.2R | -105.7R | **+56.5R** | +0.195R | 1.53 | $+4,012 |
| bullish Watch | 121 | 47.1% | +44.0R | -51.7R | **-7.7R** | -0.064R | 0.85 | $-3,037 |
| bearish A+ | 57 | 59.6% | +20.7R | -20.5R | **+0.1R** | +0.003R | 1.01 | $+371 |
| bearish A | 254 | 51.2% | +90.2R | -111.9R | **-21.8R** | -0.086R | 0.81 | $-4,978 |
| bearish Watch | 92 | 60.9% | +41.0R | -32.4R | **+8.6R** | +0.093R | 1.26 | $+168 |
| exit: t1 | 393 | 100.0% | +578.9R | 0.0R | **+578.9R** | +1.473R | — | $+195,893 |
| exit: stop | 294 | 0.0% | +0.0R | -302.1R | **-302.1R** | -1.028R | 0.0 | $-50,190 |
| exit: engine_end | 167 | 44.9% | +34.1R | -37.7R | **-3.6R** | -0.021R | 0.91 | $-5,094 |
| exit: eod | 10 | 20.0% | +0.2R | -2.7R | **-2.5R** | -0.252R | 0.07 | $-185 |

## Baselines (same tickers, same window)
- Random entry (838 samples, seeded): fwd 5: +2.3% · fwd 10: +3.4% · fwd 20: +94.9%
- Buy & hold (59 tickers): +1019.9% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 798
- Saved capital (hard floor broke first after the stall): 240
- Cut a winner (T1 was still consumed first): 350
- Neither within the tracking window: 208

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
