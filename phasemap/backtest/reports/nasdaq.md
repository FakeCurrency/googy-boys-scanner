# PhaseMap backtest — NASDAQ

Generated 2026-09-06 · ruleset v1.3.1 · universe 1426 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12517 | +1.4% | +1.7% | +2.2% | 40.9% | 9.6 | -8.6% |
| tier A+ | 1489 | +1.4% | +1.4% | +1.5% | 40.7% | 9.4 | -8.4% |
| tier A | 6936 | +1.4% | +1.9% | +2.1% | 40.4% | 9.9 | -8.8% |
| long | 5822 | +1.5% | +2.5% | +3.9% | 43.3% | 9.2 | -8.0% |
| short | 6695 | +1.3% | +1.1% | +0.8% | 38.9% | 9.9 | -9.1% |
| liquid | 11543 | +1.5% | +1.8% | +2.3% | 41.7% | 9.6 | -8.6% |
| illiquid | 974 | +0.9% | +0.8% | +1.2% | 31.6% | 9.6 | -8.2% |
| price >= $1 | 12467 | +1.4% | +1.8% | +2.2% | 40.9% | 9.6 | -8.5% |
| cents (<$1) | 50 | +5.9% | -0.6% | +8.5% | 52.0% | 6.9 | -28.7% |
| in-sample | 9397 | +1.5% | +2.0% | +2.6% | 41.8% | 9.7 | -8.3% |
| out-of-sample | 3120 | +1.2% | +1.0% | +1.0% | 38.2% | 9.2 | -9.4% |

## Baselines (same tickers, same window)
- Random entry (11684 samples, seeded): fwd 5: +0.4% · fwd 10: +0.9% · fwd 20: +2.2%
- Buy & hold (1329 tickers): +84.5% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11302
- Saved capital (hard floor broke first after the stall): 3408
- Cut a winner (T1 was still consumed first): 4666
- Neither within the tracking window: 3228

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
