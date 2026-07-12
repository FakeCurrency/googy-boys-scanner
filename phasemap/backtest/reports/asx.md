# PhaseMap backtest — ASX

Generated 2026-07-12 · ruleset v1.2.0 · universe 1988 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 15455 | +1.3% | +1.4% | +1.3% | 29.8% | 10.1 | -12.7% |
| tier A+ | 1945 | +0.8% | +0.8% | +0.7% | 28.6% | 10.4 | -11.7% |
| tier A | 8698 | +1.2% | +1.3% | +1.2% | 29.7% | 10.3 | -13.3% |
| long | 7717 | +1.3% | +1.4% | +1.5% | 28.9% | 8.8 | -11.4% |
| short | 7738 | +1.3% | +1.4% | +1.2% | 30.7% | 11.3 | -14.0% |
| liquid | 4256 | +2.1% | +2.2% | +2.8% | 41.0% | 9.2 | -8.3% |
| illiquid | 11199 | +0.9% | +1.0% | +0.7% | 25.5% | 10.7 | -14.4% |
| price >= $1 | 4757 | +1.3% | +1.2% | +1.4% | 38.3% | 9.1 | -6.4% |
| cents (<$1) | 10698 | +1.2% | +1.4% | +1.3% | 26.0% | 10.8 | -15.5% |
| in-sample | 12094 | +1.2% | +1.4% | +1.5% | 29.9% | 10.3 | -12.1% |
| out-of-sample | 3361 | +1.4% | +1.3% | +0.6% | 29.4% | 9.4 | -14.9% |

## Baselines (same tickers, same window)
- Random entry (14839 samples, seeded): fwd 5: +0.5% · fwd 10: +0.6% · fwd 20: +0.8%
- Buy & hold (1766 tickers): +32.0% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 13767
- Saved capital (hard floor broke first after the stall): 4040
- Cut a winner (T1 was still consumed first): 4306
- Neither within the tracking window: 5421

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
