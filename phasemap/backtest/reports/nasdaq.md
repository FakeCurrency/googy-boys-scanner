# PhaseMap backtest — NASDAQ

Generated 2026-08-16 · ruleset v1.3.1 · universe 1427 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12660 | +1.4% | +1.7% | +2.2% | 40.9% | 9.5 | -8.6% |
| tier A+ | 1509 | +1.5% | +1.4% | +1.5% | 41.4% | 9.4 | -8.4% |
| tier A | 7008 | +1.4% | +1.8% | +2.1% | 40.5% | 9.8 | -8.8% |
| long | 5894 | +1.5% | +2.4% | +3.8% | 43.6% | 9.2 | -8.0% |
| short | 6766 | +1.3% | +1.1% | +0.8% | 38.6% | 9.9 | -9.2% |
| liquid | 11676 | +1.4% | +1.8% | +2.3% | 41.7% | 9.6 | -8.7% |
| illiquid | 984 | +0.9% | +0.7% | +1.2% | 32.0% | 9.2 | -8.5% |
| price >= $1 | 12597 | +1.4% | +1.7% | +2.2% | 40.9% | 9.6 | -8.5% |
| cents (<$1) | 63 | +4.2% | -1.9% | +5.1% | 49.2% | 6.7 | -29.8% |
| in-sample | 9608 | +1.4% | +1.9% | +2.5% | 41.8% | 9.7 | -8.4% |
| out-of-sample | 3052 | +1.3% | +1.0% | +1.0% | 38.3% | 9.1 | -9.4% |

## Baselines (same tickers, same window)
- Random entry (11765 samples, seeded): fwd 5: +0.4% · fwd 10: +0.9% · fwd 20: +2.0%
- Buy & hold (1331 tickers): +76.0% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11398
- Saved capital (hard floor broke first after the stall): 3458
- Cut a winner (T1 was still consumed first): 4715
- Neither within the tracking window: 3225

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
