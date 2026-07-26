# PhaseMap backtest — CRYPTO

Generated 2026-07-26 · ruleset v1.3.1 · universe 101 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1008 | +2.1% | +2.1% | -140.1% | 39.7% | 11.0 | -891.1% |
| tier A+ | 127 | +0.7% | +0.9% | +120.8% | 40.9% | 11.9 | -19.8% |
| tier A | 629 | +2.6% | +2.3% | -248.9% | 40.1% | 11.4 | -822.3% |
| long | 533 | +1.7% | +1.8% | +42.9% | 40.9% | 8.8 | -14.9% |
| short | 475 | +2.6% | +2.5% | -345.5% | 38.3% | 13.4 | -1872.5% |
| liquid | 836 | +2.5% | +2.2% | +2.6% | 41.9% | 9.3 | -14.3% |
| illiquid | 172 | +0.1% | +2.0% | -838.2% | 29.1% | 21.2 | -5147.9% |
| price >= $1 | 510 | +2.4% | +1.5% | +2.3% | 41.8% | 8.8 | -12.5% |
| cents (<$1) | 498 | +1.8% | +2.8% | -286.4% | 37.6% | 13.5 | -1789.2% |
| in-sample | 782 | +2.0% | +2.3% | -180.3% | 39.1% | 11.6 | -1126.0% |
| out-of-sample | 226 | +2.5% | +1.7% | +1.2% | 41.6% | 9.0 | -75.0% |

## Baselines (same tickers, same window)
- Random entry (863 samples, seeded): fwd 5: +2.0% · fwd 10: +1.1% · fwd 20: +114.7%
- Buy & hold (77 tickers): +505.7% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 924
- Saved capital (hard floor broke first after the stall): 289
- Cut a winner (T1 was still consumed first): 386
- Neither within the tracking window: 249

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
