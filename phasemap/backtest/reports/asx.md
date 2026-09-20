# PhaseMap backtest — ASX

Generated 2026-09-20 · ruleset v1.3.1 · universe 2046 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12866 | +0.8% | +0.9% | +0.9% | 30.2% | 10.1 | -12.7% |
| tier A+ | 1663 | +0.1% | +0.3% | +0.4% | 28.9% | 10.4 | -11.9% |
| tier A | 7186 | +0.7% | +0.9% | +0.8% | 30.2% | 10.3 | -13.2% |
| long | 6346 | +0.9% | +1.1% | +1.1% | 29.4% | 8.7 | -11.4% |
| short | 6520 | +0.7% | +0.8% | +0.7% | 31.0% | 11.3 | -13.9% |
| liquid | 3795 | +1.6% | +1.6% | +2.1% | 40.5% | 9.3 | -8.2% |
| illiquid | 9071 | +0.5% | +0.6% | +0.4% | 25.9% | 10.6 | -14.5% |
| price >= $1 | 4266 | +0.9% | +0.9% | +0.9% | 38.0% | 8.9 | -6.6% |
| cents (<$1) | 8600 | +0.8% | +0.9% | +0.9% | 26.3% | 10.8 | -15.7% |
| in-sample | 9619 | +0.7% | +0.9% | +1.0% | 30.3% | 10.2 | -12.2% |
| out-of-sample | 3247 | +1.0% | +1.0% | +0.6% | 29.9% | 9.6 | -14.0% |

## Baselines (same tickers, same window)
- Random entry (12237 samples, seeded): fwd 5: +1.7% · fwd 10: +1.1% · fwd 20: +1.3%
- Buy & hold (1434 tickers): +30.8% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11449
- Saved capital (hard floor broke first after the stall): 3412
- Cut a winner (T1 was still consumed first): 3609
- Neither within the tracking window: 4428

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
