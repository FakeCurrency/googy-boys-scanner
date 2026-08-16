# PhaseMap backtest — ASX

Generated 2026-08-16 · ruleset v1.3.1 · universe 2212 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 18239 | +0.7% | +0.7% | +0.6% | 30.7% | 10.0 | -11.2% |
| tier A+ | 2292 | +0.3% | +0.2% | +0.3% | 28.8% | 10.7 | -10.4% |
| tier A | 10259 | +0.7% | +0.7% | +0.5% | 31.0% | 10.2 | -11.7% |
| long | 8265 | +0.8% | +0.8% | +0.8% | 30.1% | 9.0 | -10.8% |
| short | 9974 | +0.6% | +0.6% | +0.4% | 31.1% | 10.8 | -11.5% |
| liquid | 5961 | +1.3% | +1.2% | +1.5% | 38.9% | 9.3 | -7.0% |
| illiquid | 12278 | +0.4% | +0.5% | +0.1% | 26.7% | 10.5 | -13.3% |
| price >= $1 | 7983 | +0.7% | +0.6% | +0.6% | 37.0% | 9.2 | -5.1% |
| cents (<$1) | 10256 | +0.7% | +0.8% | +0.6% | 25.8% | 10.9 | -15.9% |
| in-sample | 13760 | +0.7% | +0.7% | +0.8% | 30.8% | 10.2 | -10.8% |
| out-of-sample | 4479 | +0.8% | +0.7% | +0.0% | 30.3% | 9.4 | -12.4% |

## Baselines (same tickers, same window)
- Random entry (17638 samples, seeded): fwd 5: +0.2% · fwd 10: +0.6% · fwd 20: +0.7%
- Buy & hold (2048 tickers): +30.6% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 16108
- Saved capital (hard floor broke first after the stall): 4964
- Cut a winner (T1 was still consumed first): 5186
- Neither within the tracking window: 5958

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
