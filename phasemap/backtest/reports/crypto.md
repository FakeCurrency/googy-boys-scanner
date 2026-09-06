# PhaseMap backtest — CRYPTO

Generated 2026-09-06 · ruleset v1.3.1 · universe 101 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1038 | +2.2% | +2.3% | -139.5% | 41.5% | 10.6 | -875.9% |
| tier A+ | 134 | +0.7% | +1.3% | +115.5% | 45.5% | 11.6 | -106.9% |
| tier A | 648 | +2.6% | +2.2% | -250.5% | 41.4% | 10.9 | -798.2% |
| long | 554 | +1.9% | +2.1% | +42.9% | 44.4% | 8.3 | -14.2% |
| short | 484 | +2.6% | +2.5% | -343.0% | 38.2% | 13.4 | -1862.2% |
| liquid | 858 | +2.7% | +2.3% | +2.5% | 44.1% | 9.0 | -13.8% |
| illiquid | 180 | +0.0% | +1.9% | -805.5% | 29.4% | 20.6 | -4985.4% |
| price >= $1 | 516 | +2.8% | +1.9% | +2.3% | 43.0% | 8.5 | -12.1% |
| cents (<$1) | 522 | +1.7% | +2.6% | -279.9% | 40.0% | 12.7 | -1729.8% |
| in-sample | 775 | +1.8% | +2.2% | -182.3% | 39.5% | 11.5 | -1151.3% |
| out-of-sample | 263 | +3.7% | +2.5% | +1.8% | 47.5% | 8.1 | -64.3% |

## Baselines (same tickers, same window)
- Random entry (880 samples, seeded): fwd 5: +9.1% · fwd 10: +14.6% · fwd 20: +122.2%
- Buy & hold (77 tickers): +555.6% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 957
- Saved capital (hard floor broke first after the stall): 293
- Cut a winner (T1 was still consumed first): 416
- Neither within the tracking window: 248

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
