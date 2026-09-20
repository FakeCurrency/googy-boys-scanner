# PhaseMap backtest — NASDAQ

Generated 2026-09-20 · ruleset v1.3.1 · universe 1426 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12508 | +1.4% | +1.7% | +2.2% | 40.8% | 9.6 | -8.6% |
| tier A+ | 1472 | +1.4% | +1.3% | +1.3% | 39.6% | 9.6 | -8.3% |
| tier A | 6946 | +1.4% | +1.8% | +2.1% | 40.3% | 9.8 | -8.8% |
| long | 5831 | +1.5% | +2.5% | +3.9% | 43.2% | 9.2 | -8.0% |
| short | 6677 | +1.3% | +1.1% | +0.7% | 38.6% | 9.9 | -9.1% |
| liquid | 11526 | +1.5% | +1.8% | +2.3% | 41.6% | 9.6 | -8.6% |
| illiquid | 982 | +0.8% | +0.8% | +1.2% | 31.0% | 9.6 | -7.7% |
| price >= $1 | 12455 | +1.4% | +1.7% | +2.1% | 40.7% | 9.6 | -8.5% |
| cents (<$1) | 53 | +6.3% | +1.1% | +7.5% | 49.1% | 6.9 | -23.4% |
| in-sample | 9295 | +1.5% | +2.0% | +2.6% | 41.7% | 9.7 | -8.3% |
| out-of-sample | 3213 | +1.2% | +1.0% | +1.0% | 38.0% | 9.2 | -9.3% |

## Baselines (same tickers, same window)
- Random entry (11652 samples, seeded): fwd 5: +0.5% · fwd 10: +0.9% · fwd 20: +2.0%
- Buy & hold (1334 tickers): +80.3% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11304
- Saved capital (hard floor broke first after the stall): 3396
- Cut a winner (T1 was still consumed first): 4645
- Neither within the tracking window: 3263

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
