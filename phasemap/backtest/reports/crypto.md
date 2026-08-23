# PhaseMap backtest — CRYPTO

Generated 2026-08-23 · ruleset v1.3.1 · universe 101 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1025 | +1.9% | +2.0% | -141.3% | 41.2% | 10.7 | -888.5% |
| tier A+ | 138 | +0.5% | +1.3% | +113.6% | 44.2% | 11.6 | -105.1% |
| tier A | 636 | +2.2% | +2.0% | -254.5% | 41.0% | 11.1 | -814.2% |
| long | 545 | +1.3% | +1.7% | +43.7% | 44.4% | 8.4 | -14.0% |
| short | 480 | +2.6% | +2.3% | -343.4% | 37.5% | 13.5 | -1885.5% |
| liquid | 840 | +2.3% | +2.0% | +2.5% | 43.8% | 9.1 | -13.6% |
| illiquid | 185 | +0.1% | +1.9% | -778.7% | 29.2% | 20.4 | -4851.7% |
| price >= $1 | 513 | +2.5% | +1.7% | +2.4% | 42.5% | 8.6 | -12.0% |
| cents (<$1) | 512 | +1.2% | +2.3% | -286.1% | 39.8% | 13.0 | -1763.3% |
| in-sample | 773 | +1.7% | +2.1% | -182.6% | 39.2% | 11.7 | -1154.1% |
| out-of-sample | 252 | +2.5% | +1.7% | +1.4% | 47.2% | 8.1 | -67.1% |

## Baselines (same tickers, same window)
- Random entry (892 samples, seeded): fwd 5: +1.4% · fwd 10: +2.5% · fwd 20: +120.1%
- Buy & hold (78 tickers): +526.7% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 939
- Saved capital (hard floor broke first after the stall): 288
- Cut a winner (T1 was still consumed first): 404
- Neither within the tracking window: 247

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
