# PhaseMap backtest — NASDAQ

Generated 2026-07-26 · ruleset v1.3.1 · universe 1427 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12633 | +1.4% | +1.7% | +2.1% | 41.1% | 9.5 | -8.6% |
| tier A+ | 1516 | +1.5% | +1.4% | +1.5% | 41.4% | 9.5 | -8.3% |
| tier A | 7000 | +1.4% | +1.8% | +2.1% | 40.7% | 9.8 | -8.8% |
| long | 5890 | +1.5% | +2.4% | +3.8% | 43.9% | 9.2 | -8.1% |
| short | 6743 | +1.3% | +1.1% | +0.7% | 38.6% | 9.9 | -9.2% |
| liquid | 11678 | +1.5% | +1.8% | +2.2% | 41.9% | 9.6 | -8.7% |
| illiquid | 955 | +0.8% | +0.6% | +1.2% | 31.2% | 9.4 | -8.5% |
| price >= $1 | 12566 | +1.4% | +1.7% | +2.1% | 41.0% | 9.6 | -8.5% |
| cents (<$1) | 67 | +2.9% | -2.3% | +1.3% | 43.3% | 7.0 | -28.7% |
| in-sample | 9759 | +1.5% | +1.9% | +2.5% | 41.8% | 9.6 | -8.4% |
| out-of-sample | 2874 | +1.2% | +0.9% | +0.9% | 38.5% | 9.2 | -9.6% |

## Baselines (same tickers, same window)
- Random entry (11756 samples, seeded): fwd 5: +0.3% · fwd 10: +0.7% · fwd 20: +1.5%
- Buy & hold (1332 tickers): +76.2% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11402
- Saved capital (hard floor broke first after the stall): 3473
- Cut a winner (T1 was still consumed first): 4710
- Neither within the tracking window: 3219

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
