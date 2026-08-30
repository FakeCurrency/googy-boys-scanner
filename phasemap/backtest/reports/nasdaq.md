# PhaseMap backtest — NASDAQ

Generated 2026-08-30 · ruleset v1.3.1 · universe 1425 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12602 | +1.4% | +1.7% | +2.2% | 40.9% | 9.5 | -8.6% |
| tier A+ | 1512 | +1.4% | +1.3% | +1.4% | 40.3% | 9.4 | -8.4% |
| tier A | 6991 | +1.4% | +1.8% | +2.1% | 40.6% | 9.8 | -8.8% |
| long | 5880 | +1.5% | +2.4% | +3.8% | 43.5% | 9.2 | -8.0% |
| short | 6722 | +1.3% | +1.1% | +0.8% | 38.7% | 9.9 | -9.2% |
| liquid | 11630 | +1.5% | +1.8% | +2.3% | 41.7% | 9.5 | -8.7% |
| illiquid | 972 | +0.9% | +0.7% | +1.2% | 31.4% | 9.6 | -8.2% |
| price >= $1 | 12551 | +1.4% | +1.7% | +2.2% | 40.9% | 9.6 | -8.6% |
| cents (<$1) | 51 | +5.5% | -0.5% | +8.7% | 51.0% | 6.9 | -28.5% |
| in-sample | 9518 | +1.5% | +1.9% | +2.5% | 41.8% | 9.7 | -8.4% |
| out-of-sample | 3084 | +1.2% | +1.0% | +1.1% | 38.3% | 9.2 | -9.4% |

## Baselines (same tickers, same window)
- Random entry (11750 samples, seeded): fwd 5: +0.5% · fwd 10: +0.9% · fwd 20: +2.1%
- Buy & hold (1327 tickers): +72.2% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11367
- Saved capital (hard floor broke first after the stall): 3447
- Cut a winner (T1 was still consumed first): 4695
- Neither within the tracking window: 3225

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
