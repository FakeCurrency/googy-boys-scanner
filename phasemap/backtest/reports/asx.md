# PhaseMap backtest — ASX

Generated 2026-08-30 · ruleset v1.3.1 · universe 2212 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 18319 | +0.7% | +0.7% | +0.6% | 30.9% | 10.0 | -11.2% |
| tier A+ | 2317 | +0.3% | +0.3% | +0.1% | 29.2% | 10.6 | -10.4% |
| tier A | 10262 | +0.6% | +0.7% | +0.5% | 31.1% | 10.3 | -11.7% |
| long | 8268 | +0.8% | +0.9% | +0.9% | 30.3% | 9.1 | -10.8% |
| short | 10051 | +0.6% | +0.6% | +0.4% | 31.4% | 10.7 | -11.5% |
| liquid | 6050 | +1.3% | +1.2% | +1.5% | 39.3% | 9.2 | -6.9% |
| illiquid | 12269 | +0.4% | +0.5% | +0.1% | 26.8% | 10.6 | -13.3% |
| price >= $1 | 8061 | +0.7% | +0.6% | +0.6% | 37.0% | 9.2 | -5.2% |
| cents (<$1) | 10258 | +0.7% | +0.8% | +0.6% | 26.1% | 10.9 | -15.9% |
| in-sample | 13672 | +0.7% | +0.7% | +0.8% | 31.1% | 10.2 | -10.8% |
| out-of-sample | 4647 | +0.8% | +0.7% | +0.1% | 30.4% | 9.4 | -12.2% |

## Baselines (same tickers, same window)
- Random entry (17879 samples, seeded): fwd 5: +0.2% · fwd 10: +0.4% · fwd 20: +4.7%
- Buy & hold (2051 tickers): +35.9% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 16161
- Saved capital (hard floor broke first after the stall): 4956
- Cut a winner (T1 was still consumed first): 5243
- Neither within the tracking window: 5962

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
