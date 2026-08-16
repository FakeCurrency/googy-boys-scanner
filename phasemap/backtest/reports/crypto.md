# PhaseMap backtest — CRYPTO

Generated 2026-08-16 · ruleset v1.3.1 · universe 101 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1010 | +2.2% | +1.9% | -141.4% | 40.0% | 10.9 | -888.6% |
| tier A+ | 133 | +0.2% | +0.7% | +117.7% | 43.6% | 11.8 | -19.7% |
| tier A | 626 | +2.6% | +2.0% | -253.1% | 39.5% | 11.4 | -826.1% |
| long | 529 | +1.8% | +1.7% | +43.8% | 41.0% | 8.7 | -14.6% |
| short | 481 | +2.8% | +2.2% | -343.3% | 38.9% | 13.3 | -1849.8% |
| liquid | 834 | +2.8% | +2.0% | +2.7% | 42.6% | 9.2 | -14.3% |
| illiquid | 176 | -0.2% | +1.6% | -824.3% | 27.8% | 21.3 | -5031.6% |
| price >= $1 | 505 | +2.6% | +1.7% | +2.5% | 42.0% | 8.8 | -12.1% |
| cents (<$1) | 505 | +1.9% | +2.1% | -286.7% | 38.0% | 13.2 | -1765.2% |
| in-sample | 769 | +2.1% | +2.3% | -183.4% | 39.1% | 11.6 | -1144.5% |
| out-of-sample | 241 | +2.9% | +0.8% | +1.1% | 42.7% | 8.8 | -72.0% |

## Baselines (same tickers, same window)
- Random entry (871 samples, seeded): fwd 5: +0.6% · fwd 10: +0.3% · fwd 20: +278.3%
- Buy & hold (78 tickers): +472.3% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 927
- Saved capital (hard floor broke first after the stall): 289
- Cut a winner (T1 was still consumed first): 390
- Neither within the tracking window: 248

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
