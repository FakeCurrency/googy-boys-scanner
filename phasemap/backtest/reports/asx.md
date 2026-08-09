# PhaseMap backtest — ASX

Generated 2026-08-09 · ruleset v1.3.1 · universe 2212 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 18253 | +0.7% | +0.7% | +0.6% | 30.8% | 10.0 | -11.2% |
| tier A+ | 2315 | +0.3% | +0.3% | +0.2% | 29.0% | 10.8 | -10.3% |
| tier A | 10237 | +0.6% | +0.7% | +0.6% | 31.0% | 10.2 | -11.7% |
| long | 8261 | +0.8% | +0.9% | +0.9% | 30.0% | 9.1 | -10.8% |
| short | 9992 | +0.6% | +0.6% | +0.4% | 31.5% | 10.7 | -11.6% |
| liquid | 5991 | +1.2% | +1.2% | +1.6% | 39.1% | 9.2 | -7.0% |
| illiquid | 12262 | +0.4% | +0.5% | +0.2% | 26.8% | 10.5 | -13.3% |
| price >= $1 | 7993 | +0.7% | +0.6% | +0.6% | 37.1% | 9.1 | -5.1% |
| cents (<$1) | 10260 | +0.7% | +0.8% | +0.7% | 25.9% | 11.0 | -16.0% |
| in-sample | 13820 | +0.7% | +0.7% | +0.8% | 31.0% | 10.2 | -10.8% |
| out-of-sample | 4433 | +0.7% | +0.7% | +0.0% | 30.3% | 9.4 | -12.4% |

## Baselines (same tickers, same window)
- Random entry (17613 samples, seeded): fwd 5: +0.4% · fwd 10: +0.5% · fwd 20: +1.0%
- Buy & hold (2055 tickers): +31.8% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 16112
- Saved capital (hard floor broke first after the stall): 4946
- Cut a winner (T1 was still consumed first): 5210
- Neither within the tracking window: 5956

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
