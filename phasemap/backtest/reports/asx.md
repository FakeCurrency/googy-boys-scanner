# PhaseMap backtest — ASX

Generated 2026-07-26 · ruleset v1.3.1 · universe 93 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 871 | +1.0% | +1.0% | +1.4% | 39.4% | 9.5 | -5.4% |
| tier A+ | 99 | +0.8% | +1.4% | +1.7% | 37.4% | 11.5 | -4.8% |
| tier A | 484 | +1.2% | +1.1% | +1.6% | 41.5% | 9.3 | -5.5% |
| long | 374 | +1.3% | +2.0% | +2.6% | 44.7% | 9.0 | -5.0% |
| short | 497 | +0.8% | +0.2% | +0.5% | 35.4% | 10.0 | -5.7% |
| liquid | 870 | +1.0% | +1.0% | +1.4% | 39.3% | 9.5 | -5.4% |
| illiquid | 1 | +3.8% | +10.0% | +3.5% | 100.0% | 7.0 | -4.2% |
| price >= $1 | 860 | +1.1% | +1.1% | +1.5% | 39.4% | 9.5 | -5.3% |
| cents (<$1) | 11 | -5.4% | -6.4% | -3.1% | 36.4% | 11.5 | -17.0% |
| in-sample | 666 | +1.0% | +1.1% | +1.6% | 39.5% | 9.7 | -5.1% |
| out-of-sample | 205 | +1.0% | +0.5% | +0.7% | 39.0% | 8.9 | -6.4% |

## Baselines (same tickers, same window)
- Random entry (871 samples, seeded): fwd 5: +0.4% · fwd 10: +0.5% · fwd 20: +1.0%
- Buy & hold (93 tickers): +51.4% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 780
- Saved capital (hard floor broke first after the stall): 260
- Cut a winner (T1 was still consumed first): 317
- Neither within the tracking window: 203

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
