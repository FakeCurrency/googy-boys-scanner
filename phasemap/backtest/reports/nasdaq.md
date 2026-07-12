# PhaseMap backtest — NASDAQ

Generated 2026-07-12 · ruleset v1.2.0 · universe 1431 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12687 | +1.8% | +2.1% | +2.6% | 41.1% | 9.6 | -8.2% |
| tier A+ | 1509 | +1.9% | +1.8% | +1.8% | 40.8% | 9.5 | -8.0% |
| tier A | 7042 | +1.8% | +2.2% | +2.5% | 40.6% | 9.8 | -8.4% |
| long | 5917 | +2.0% | +2.9% | +4.3% | 43.9% | 9.2 | -7.6% |
| short | 6770 | +1.7% | +1.5% | +1.1% | 38.6% | 9.9 | -8.7% |
| liquid | 11739 | +1.9% | +2.2% | +2.7% | 41.9% | 9.6 | -8.2% |
| illiquid | 948 | +1.0% | +0.8% | +1.5% | 31.2% | 9.5 | -8.4% |
| price >= $1 | 12618 | +1.8% | +2.1% | +2.6% | 41.1% | 9.6 | -8.1% |
| cents (<$1) | 69 | +4.3% | -0.6% | +3.6% | 42.0% | 7.0 | -27.3% |
| in-sample | 9872 | +1.9% | +2.4% | +3.0% | 41.9% | 9.7 | -7.9% |
| out-of-sample | 2815 | +1.6% | +1.2% | +1.3% | 38.4% | 9.1 | -9.2% |

## Baselines (same tickers, same window)
- Random entry (11744 samples, seeded): fwd 5: +0.4% · fwd 10: +0.9% · fwd 20: +2.0%
- Buy & hold (1334 tickers): +91.5% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11448
- Saved capital (hard floor broke first after the stall): 3480
- Cut a winner (T1 was still consumed first): 4735
- Neither within the tracking window: 3233

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
