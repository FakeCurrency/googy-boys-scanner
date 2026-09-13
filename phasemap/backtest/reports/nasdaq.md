# PhaseMap backtest — NASDAQ

Generated 2026-09-13 · ruleset v1.3.1 · universe 1423 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12485 | +1.4% | +1.7% | +2.2% | 40.9% | 9.6 | -8.6% |
| tier A+ | 1471 | +1.4% | +1.4% | +1.4% | 40.6% | 9.6 | -8.3% |
| tier A | 6948 | +1.4% | +1.8% | +2.1% | 40.3% | 9.9 | -8.8% |
| long | 5802 | +1.5% | +2.5% | +3.9% | 43.4% | 9.2 | -8.0% |
| short | 6683 | +1.3% | +1.1% | +0.7% | 38.7% | 9.9 | -9.1% |
| liquid | 11526 | +1.5% | +1.8% | +2.3% | 41.7% | 9.6 | -8.6% |
| illiquid | 959 | +0.9% | +0.7% | +1.1% | 31.5% | 9.4 | -7.9% |
| price >= $1 | 12440 | +1.4% | +1.7% | +2.2% | 40.9% | 9.6 | -8.5% |
| cents (<$1) | 45 | +6.0% | -0.9% | +8.6% | 53.3% | 6.8 | -26.7% |
| in-sample | 9325 | +1.5% | +2.0% | +2.6% | 41.9% | 9.7 | -8.3% |
| out-of-sample | 3160 | +1.2% | +0.9% | +1.0% | 38.0% | 9.2 | -9.4% |

## Baselines (same tickers, same window)
- Random entry (11595 samples, seeded): fwd 5: +0.5% · fwd 10: +0.9% · fwd 20: +1.7%
- Buy & hold (1331 tickers): +79.4% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11268
- Saved capital (hard floor broke first after the stall): 3382
- Cut a winner (T1 was still consumed first): 4657
- Neither within the tracking window: 3229

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
