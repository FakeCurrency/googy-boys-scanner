# PhaseMap backtest — CRYPTO

Generated 2026-07-05 · ruleset v1.2.0 · universe 101 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1024 | +2.7% | +2.9% | -137.2% | 39.6% | 11.0 | -877.7% |
| tier A+ | 131 | +1.1% | +1.8% | +119.0% | 42.0% | 11.8 | -20.2% |
| tier A | 630 | +3.4% | +3.3% | -247.7% | 40.3% | 11.4 | -822.6% |
| long | 536 | +2.0% | +2.8% | +43.3% | 40.5% | 8.8 | -15.0% |
| short | 488 | +3.5% | +2.9% | -334.9% | 38.5% | 13.4 | -1825.3% |
| liquid | 810 | +2.8% | +2.4% | +2.4% | 41.9% | 9.4 | -14.4% |
| illiquid | 214 | +2.5% | +4.9% | -671.4% | 30.8% | 18.5 | -4145.4% |
| price >= $1 | 506 | +3.0% | +2.2% | +3.0% | 41.9% | 8.8 | -11.9% |
| cents (<$1) | 518 | +2.4% | +3.6% | -275.2% | 37.3% | 13.4 | -1723.5% |
| in-sample | 813 | +2.7% | +3.1% | -172.8% | 39.0% | 11.5 | -1085.1% |
| out-of-sample | 211 | +2.8% | +2.1% | +2.1% | 41.7% | 9.2 | -78.5% |

## Baselines (same tickers, same window)
- Random entry (887 samples, seeded): fwd 5: +0.3% · fwd 10: +3.4% · fwd 20: +3246.3%
- Buy & hold (81 tickers): +3337.5% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 938
- Saved capital (hard floor broke first after the stall): 287
- Cut a winner (T1 was still consumed first): 389
- Neither within the tracking window: 262

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
