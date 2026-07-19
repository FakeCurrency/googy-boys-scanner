# PhaseMap backtest — NASDAQ

Generated 2026-07-19 · ruleset v1.2.0 · universe 1428 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12627 | +1.8% | +2.1% | +2.6% | 41.1% | 9.6 | -8.2% |
| tier A+ | 1508 | +1.9% | +1.9% | +1.9% | 41.2% | 9.5 | -7.9% |
| tier A | 7001 | +1.8% | +2.2% | +2.5% | 40.5% | 9.8 | -8.4% |
| long | 5888 | +2.0% | +2.9% | +4.3% | 43.9% | 9.2 | -7.7% |
| short | 6739 | +1.7% | +1.5% | +1.1% | 38.6% | 9.9 | -8.6% |
| liquid | 11670 | +1.9% | +2.3% | +2.7% | 41.9% | 9.6 | -8.2% |
| illiquid | 957 | +0.9% | +0.8% | +1.5% | 30.6% | 9.4 | -8.3% |
| price >= $1 | 12560 | +1.8% | +2.2% | +2.6% | 41.0% | 9.6 | -8.1% |
| cents (<$1) | 67 | +4.0% | -0.9% | +3.4% | 43.3% | 7.0 | -27.7% |
| in-sample | 9787 | +1.9% | +2.4% | +3.0% | 41.8% | 9.7 | -7.9% |
| out-of-sample | 2840 | +1.6% | +1.3% | +1.3% | 38.5% | 9.2 | -9.2% |

## Baselines (same tickers, same window)
- Random entry (11739 samples, seeded): fwd 5: +0.4% · fwd 10: +0.9% · fwd 20: +1.9%
- Buy & hold (1332 tickers): +90.2% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11402
- Saved capital (hard floor broke first after the stall): 3463
- Cut a winner (T1 was still consumed first): 4717
- Neither within the tracking window: 3222

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
