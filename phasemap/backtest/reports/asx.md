# PhaseMap backtest — ASX

Generated 2026-07-19 · ruleset v1.2.0 · universe 1987 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 15460 | +1.2% | +1.3% | +1.3% | 29.8% | 10.2 | -12.7% |
| tier A+ | 1947 | +0.8% | +0.8% | +0.7% | 28.2% | 10.7 | -11.5% |
| tier A | 8704 | +1.2% | +1.3% | +1.1% | 29.7% | 10.3 | -13.4% |
| long | 7724 | +1.2% | +1.3% | +1.4% | 28.8% | 8.8 | -11.4% |
| short | 7736 | +1.2% | +1.3% | +1.2% | 30.8% | 11.4 | -14.0% |
| liquid | 4247 | +2.2% | +2.2% | +2.7% | 40.9% | 9.2 | -8.3% |
| illiquid | 11213 | +0.9% | +1.0% | +0.7% | 25.6% | 10.7 | -14.4% |
| price >= $1 | 4743 | +1.3% | +1.3% | +1.4% | 38.2% | 9.1 | -6.4% |
| cents (<$1) | 10717 | +1.2% | +1.4% | +1.2% | 26.0% | 10.8 | -15.5% |
| in-sample | 12068 | +1.2% | +1.4% | +1.5% | 29.9% | 10.4 | -12.1% |
| out-of-sample | 3392 | +1.4% | +1.3% | +0.6% | 29.5% | 9.4 | -14.9% |

## Baselines (same tickers, same window)
- Random entry (14824 samples, seeded): fwd 5: +0.3% · fwd 10: +0.4% · fwd 20: +0.8%
- Buy & hold (1769 tickers): +28.0% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 13797
- Saved capital (hard floor broke first after the stall): 4030
- Cut a winner (T1 was still consumed first): 4316
- Neither within the tracking window: 5451

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
