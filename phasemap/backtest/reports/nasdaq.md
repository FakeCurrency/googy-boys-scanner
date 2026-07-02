# PhaseMap backtest — NASDAQ

Generated 2026-07-02 · ruleset v1.2.0 · universe 98 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1126 | +1.1% | +1.7% | +2.6% | 44.7% | 8.9 | -6.6% |
| tier A+ | 122 | +1.6% | +1.8% | +3.1% | 52.5% | 9.0 | -5.4% |
| tier A | 641 | +1.0% | +1.9% | +2.6% | 41.8% | 8.7 | -6.8% |
| long | 500 | +1.3% | +2.9% | +5.2% | 50.4% | 8.8 | -5.9% |
| short | 626 | +1.0% | +0.8% | +0.5% | 40.1% | 8.9 | -7.2% |
| liquid | 1126 | +1.1% | +1.7% | +2.6% | 44.7% | 8.9 | -6.6% |
| price >= $1 | 1126 | +1.1% | +1.7% | +2.6% | 44.7% | 8.9 | -6.6% |
| in-sample | 872 | +1.2% | +2.2% | +3.3% | 46.0% | 9.1 | -6.0% |
| out-of-sample | 254 | +0.7% | -0.0% | -0.1% | 40.2% | 7.9 | -8.5% |

## Baselines (same tickers, same window)
- Random entry (1126 samples, seeded): fwd 5: +0.1% · fwd 10: +0.2% · fwd 20: +1.3%
- Buy & hold (98 tickers): +171.3% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 1002
- Saved capital (hard floor broke first after the stall): 328
- Cut a winner (T1 was still consumed first): 446
- Neither within the tracking window: 228

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
