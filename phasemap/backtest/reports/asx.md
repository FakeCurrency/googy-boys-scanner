# PhaseMap backtest — ASX

Generated 2026-09-13 · ruleset v1.3.1 · universe 2045 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 10846 | +0.7% | +0.8% | +0.7% | 30.5% | 10.2 | -13.1% |
| tier A+ | 1394 | +0.2% | +0.3% | +1.0% | 29.8% | 10.8 | -11.4% |
| tier A | 6130 | +0.7% | +0.7% | +0.4% | 30.4% | 10.3 | -13.8% |
| long | 5323 | +0.9% | +1.0% | +1.0% | 29.8% | 8.8 | -11.5% |
| short | 5523 | +0.5% | +0.6% | +0.4% | 31.2% | 11.4 | -14.6% |
| liquid | 3182 | +1.6% | +1.5% | +2.2% | 41.3% | 9.3 | -8.5% |
| illiquid | 7664 | +0.4% | +0.5% | +0.1% | 26.0% | 10.7 | -15.0% |
| price >= $1 | 3474 | +1.0% | +0.9% | +1.1% | 38.7% | 9.0 | -6.5% |
| cents (<$1) | 7372 | +0.6% | +0.7% | +0.5% | 26.6% | 10.9 | -16.1% |
| in-sample | 8109 | +0.7% | +0.8% | +1.0% | 30.7% | 10.4 | -12.4% |
| out-of-sample | 2737 | +0.7% | +0.9% | -0.2% | 30.1% | 9.5 | -15.2% |

## Baselines (same tickers, same window)
- Random entry (10285 samples, seeded): fwd 5: +0.4% · fwd 10: +0.4% · fwd 20: +2.9%
- Buy & hold (1217 tickers): +27.1% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 9623
- Saved capital (hard floor broke first after the stall): 2889
- Cut a winner (T1 was still consumed first): 3060
- Neither within the tracking window: 3674

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
