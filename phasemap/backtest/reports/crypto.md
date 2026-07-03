# PhaseMap backtest — CRYPTO

Generated 2026-07-03 · ruleset v1.2.0 · universe 101 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1033 | +2.8% | +2.8% | -136.1% | 39.5% | 11.0 | -870.4% |
| tier A+ | 132 | +1.4% | +2.2% | +117.1% | 42.4% | 11.9 | -20.2% |
| tier A | 637 | +3.3% | +3.0% | -245.2% | 40.2% | 11.3 | -814.0% |
| long | 543 | +2.1% | +2.6% | +42.6% | 40.5% | 8.7 | -15.2% |
| short | 490 | +3.6% | +3.0% | -333.8% | 38.4% | 13.4 | -1818.2% |
| liquid | 819 | +2.9% | +2.3% | +2.1% | 41.8% | 9.4 | -14.7% |
| illiquid | 214 | +2.5% | +4.9% | -671.4% | 30.8% | 18.3 | -4145.4% |
| price >= $1 | 509 | +3.0% | +2.2% | +2.8% | 41.8% | 8.8 | -11.9% |
| cents (<$1) | 524 | +2.6% | +3.5% | -271.9% | 37.2% | 13.3 | -1704.3% |
| in-sample | 822 | +2.7% | +3.0% | -171.1% | 38.9% | 11.4 | -1073.6% |
| out-of-sample | 211 | +3.1% | +2.2% | +1.8% | 41.7% | 9.2 | -78.8% |

## Baselines (same tickers, same window)
- Random entry (897 samples, seeded): fwd 5: +7.8% · fwd 10: +16.2% · fwd 20: +3221.2%
- Buy & hold (81 tickers): +3180.0% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 946
- Saved capital (hard floor broke first after the stall): 293
- Cut a winner (T1 was still consumed first): 390
- Neither within the tracking window: 263

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
