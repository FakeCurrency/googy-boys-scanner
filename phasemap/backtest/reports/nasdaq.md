# PhaseMap backtest — NASDAQ

Generated 2026-08-09 · ruleset v1.3.1 · universe 1427 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12657 | +1.4% | +1.7% | +2.2% | 41.0% | 9.6 | -8.6% |
| tier A+ | 1520 | +1.4% | +1.4% | +1.4% | 41.5% | 9.4 | -8.3% |
| tier A | 7017 | +1.4% | +1.8% | +2.1% | 40.4% | 9.8 | -8.8% |
| long | 5904 | +1.5% | +2.4% | +3.8% | 43.6% | 9.2 | -8.0% |
| short | 6753 | +1.3% | +1.1% | +0.8% | 38.6% | 9.9 | -9.2% |
| liquid | 11669 | +1.4% | +1.8% | +2.3% | 41.7% | 9.6 | -8.7% |
| illiquid | 988 | +0.9% | +0.6% | +1.3% | 32.3% | 9.5 | -8.3% |
| price >= $1 | 12594 | +1.4% | +1.7% | +2.2% | 40.9% | 9.6 | -8.5% |
| cents (<$1) | 63 | +4.2% | -1.9% | +5.1% | 49.2% | 6.7 | -29.8% |
| in-sample | 9644 | +1.4% | +1.9% | +2.5% | 41.9% | 9.7 | -8.4% |
| out-of-sample | 3013 | +1.2% | +1.0% | +0.9% | 38.1% | 9.1 | -9.5% |

## Baselines (same tickers, same window)
- Random entry (11704 samples, seeded): fwd 5: +0.5% · fwd 10: +0.9% · fwd 20: +2.0%
- Buy & hold (1330 tickers): +77.6% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11382
- Saved capital (hard floor broke first after the stall): 3454
- Cut a winner (T1 was still consumed first): 4721
- Neither within the tracking window: 3207

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
