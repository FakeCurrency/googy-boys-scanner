# PhaseMap backtest — ASX

Generated 2026-09-20 · ruleset v1.3.1 · universe 2046 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 10642 | +0.8% | +0.8% | +0.8% | 30.6% | 10.0 | -12.9% |
| tier A+ | 1365 | +0.2% | +0.2% | +0.7% | 30.1% | 10.3 | -11.6% |
| tier A | 5984 | +0.7% | +0.8% | +0.7% | 30.6% | 10.2 | -13.5% |
| long | 5241 | +0.9% | +1.0% | +1.1% | 29.7% | 8.6 | -11.5% |
| short | 5401 | +0.6% | +0.6% | +0.5% | 31.3% | 11.1 | -14.2% |
| liquid | 3164 | +1.6% | +1.6% | +2.2% | 41.3% | 9.1 | -8.4% |
| illiquid | 7478 | +0.4% | +0.5% | +0.3% | 26.0% | 10.6 | -14.8% |
| price >= $1 | 3430 | +0.9% | +0.9% | +1.1% | 39.0% | 8.8 | -6.6% |
| cents (<$1) | 7212 | +0.7% | +0.8% | +0.7% | 26.5% | 10.8 | -15.9% |
| in-sample | 7915 | +0.7% | +0.8% | +1.0% | 30.8% | 10.2 | -12.3% |
| out-of-sample | 2727 | +0.9% | +0.9% | +0.2% | 29.9% | 9.4 | -14.5% |

## Baselines (same tickers, same window)
- Random entry (10122 samples, seeded): fwd 5: +0.3% · fwd 10: +0.5% · fwd 20: +1.2%
- Buy & hold (1203 tickers): +27.9% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 9489
- Saved capital (hard floor broke first after the stall): 2810
- Cut a winner (T1 was still consumed first): 3029
- Neither within the tracking window: 3650

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
