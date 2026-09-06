# PhaseMap backtest — ASX

Generated 2026-09-06 · ruleset v1.3.1 · universe 2043 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 10670 | +0.7% | +0.8% | +0.8% | 30.6% | 10.1 | -12.8% |
| tier A+ | 1338 | +0.3% | +0.3% | +1.1% | 30.0% | 10.5 | -11.5% |
| tier A | 6041 | +0.7% | +0.8% | +0.5% | 30.6% | 10.3 | -13.3% |
| long | 5259 | +0.9% | +0.9% | +1.0% | 30.2% | 8.7 | -11.4% |
| short | 5411 | +0.6% | +0.7% | +0.6% | 31.0% | 11.3 | -14.1% |
| liquid | 3143 | +1.6% | +1.6% | +2.2% | 41.0% | 9.3 | -8.4% |
| illiquid | 7527 | +0.4% | +0.5% | +0.2% | 26.3% | 10.6 | -14.6% |
| price >= $1 | 3451 | +0.9% | +0.9% | +1.1% | 38.6% | 9.1 | -6.5% |
| cents (<$1) | 7219 | +0.6% | +0.8% | +0.7% | 26.8% | 10.7 | -15.8% |
| in-sample | 8008 | +0.7% | +0.8% | +1.0% | 30.9% | 10.3 | -12.3% |
| out-of-sample | 2662 | +0.8% | +0.9% | +0.1% | 29.6% | 9.5 | -14.3% |

## Baselines (same tickers, same window)
- Random entry (10126 samples, seeded): fwd 5: +0.3% · fwd 10: +0.5% · fwd 20: +1.0%
- Buy & hold (1201 tickers): +33.5% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 9505
- Saved capital (hard floor broke first after the stall): 2828
- Cut a winner (T1 was still consumed first): 3049
- Neither within the tracking window: 3628

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
