# PhaseMap backtest — ASX

Generated 2026-08-23 · ruleset v1.3.1 · universe 2212 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 18358 | +0.7% | +0.7% | +0.6% | 30.8% | 10.0 | -11.2% |
| tier A+ | 2278 | +0.2% | +0.2% | +0.2% | 29.1% | 10.9 | -10.4% |
| tier A | 10325 | +0.6% | +0.7% | +0.5% | 31.1% | 10.2 | -11.7% |
| long | 8292 | +0.8% | +0.9% | +0.9% | 30.2% | 9.1 | -10.8% |
| short | 10066 | +0.6% | +0.6% | +0.4% | 31.3% | 10.8 | -11.5% |
| liquid | 6066 | +1.2% | +1.2% | +1.5% | 39.2% | 9.3 | -7.0% |
| illiquid | 12292 | +0.4% | +0.4% | +0.2% | 26.7% | 10.5 | -13.3% |
| price >= $1 | 8086 | +0.7% | +0.6% | +0.6% | 37.1% | 9.2 | -5.2% |
| cents (<$1) | 10272 | +0.7% | +0.8% | +0.6% | 25.9% | 11.0 | -16.0% |
| in-sample | 13791 | +0.7% | +0.7% | +0.8% | 31.0% | 10.2 | -10.8% |
| out-of-sample | 4567 | +0.8% | +0.7% | +0.1% | 30.4% | 9.4 | -12.3% |

## Baselines (same tickers, same window)
- Random entry (17905 samples, seeded): fwd 5: +0.2% · fwd 10: +0.4% · fwd 20: +0.8%
- Buy & hold (2052 tickers): +32.7% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 16210
- Saved capital (hard floor broke first after the stall): 4975
- Cut a winner (T1 was still consumed first): 5241
- Neither within the tracking window: 5994

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
