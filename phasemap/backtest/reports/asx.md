# PhaseMap backtest — ASX

Generated 2026-09-20 · ruleset v1.3.1 · universe 2046 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 10382 | +0.8% | +0.7% | +0.6% | 30.3% | 10.0 | -13.1% |
| tier A+ | 1356 | +0.2% | +0.1% | +0.8% | 29.7% | 10.4 | -11.6% |
| tier A | 5829 | +0.7% | +0.6% | +0.2% | 30.2% | 10.1 | -13.9% |
| long | 5104 | +1.0% | +0.9% | +1.0% | 29.7% | 8.6 | -11.5% |
| short | 5278 | +0.5% | +0.5% | +0.3% | 30.8% | 11.2 | -14.7% |
| liquid | 3085 | +1.6% | +1.6% | +2.1% | 41.1% | 9.1 | -8.5% |
| illiquid | 7297 | +0.4% | +0.4% | -0.0% | 25.7% | 10.6 | -15.1% |
| price >= $1 | 3368 | +0.9% | +0.9% | +1.0% | 38.5% | 8.8 | -6.6% |
| cents (<$1) | 7014 | +0.7% | +0.7% | +0.4% | 26.3% | 10.8 | -16.2% |
| in-sample | 7713 | +0.7% | +0.7% | +0.9% | 30.5% | 10.2 | -12.4% |
| out-of-sample | 2669 | +0.8% | +0.8% | -0.2% | 29.6% | 9.4 | -15.3% |

## Baselines (same tickers, same window)
- Random entry (9862 samples, seeded): fwd 5: +0.3% · fwd 10: +0.5% · fwd 20: +1.2%
- Buy & hold (1171 tickers): +28.9% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 9247
- Saved capital (hard floor broke first after the stall): 2753
- Cut a winner (T1 was still consumed first): 2928
- Neither within the tracking window: 3566

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
