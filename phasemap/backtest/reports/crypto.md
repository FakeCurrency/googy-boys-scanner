# PhaseMap backtest — CRYPTO

Generated 2026-07-12 · ruleset v1.2.0 · universe 101 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1013 | +2.1% | +56.3% | -89.3% | 40.0% | 11.0 | -887.9% |
| tier A+ | 134 | -2.8% | +0.7% | +117.3% | 42.5% | 12.0 | -38.1% |
| tier A | 624 | +3.2% | +3.1% | -250.1% | 40.4% | 11.4 | -828.0% |
| long | 529 | +1.9% | +105.6% | +139.2% | 41.6% | 8.9 | -14.8% |
| short | 484 | +2.3% | +2.7% | -338.3% | 38.2% | 13.4 | -1842.1% |
| liquid | 804 | +2.8% | +2.5% | +3.1% | 42.3% | 9.4 | -13.6% |
| illiquid | 209 | -0.8% | +263.6% | -447.9% | 31.1% | 18.7 | -4250.9% |
| price >= $1 | 513 | +3.0% | +2.1% | +3.0% | 41.9% | 8.8 | -11.9% |
| cents (<$1) | 500 | +1.1% | +111.9% | -184.5% | 38.0% | 13.5 | -1786.5% |
| in-sample | 797 | +1.9% | +70.8% | -113.4% | 39.1% | 11.6 | -1107.6% |
| out-of-sample | 216 | +2.9% | +2.1% | +1.7% | 43.1% | 8.9 | -77.1% |

## Baselines (same tickers, same window)
- Random entry (876 samples, seeded): fwd 5: +144.6% · fwd 10: +142.7% · fwd 20: +243.9%
- Buy & hold (78 tickers): +3251.5% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 930
- Saved capital (hard floor broke first after the stall): 289
- Cut a winner (T1 was still consumed first): 391
- Neither within the tracking window: 250

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
