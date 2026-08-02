# PhaseMap backtest — NASDAQ

Generated 2026-08-02 · ruleset v1.3.1 · universe 1425 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12644 | +1.4% | +1.7% | +2.2% | 41.2% | 9.5 | -8.6% |
| tier A+ | 1517 | +1.5% | +1.4% | +1.5% | 41.5% | 9.4 | -8.3% |
| tier A | 6997 | +1.4% | +1.8% | +2.1% | 40.7% | 9.8 | -8.8% |
| long | 5888 | +1.5% | +2.4% | +3.8% | 43.8% | 9.2 | -8.0% |
| short | 6756 | +1.3% | +1.1% | +0.8% | 38.9% | 9.9 | -9.2% |
| liquid | 11661 | +1.5% | +1.8% | +2.2% | 41.9% | 9.5 | -8.6% |
| illiquid | 983 | +0.8% | +0.6% | +1.3% | 31.8% | 9.2 | -8.4% |
| price >= $1 | 12582 | +1.4% | +1.7% | +2.2% | 41.1% | 9.5 | -8.5% |
| cents (<$1) | 62 | +4.2% | -2.0% | +5.8% | 50.0% | 6.7 | -29.9% |
| in-sample | 9710 | +1.4% | +1.9% | +2.5% | 42.0% | 9.6 | -8.4% |
| out-of-sample | 2934 | +1.2% | +0.9% | +0.9% | 38.3% | 9.1 | -9.5% |

## Baselines (same tickers, same window)
- Random entry (11740 samples, seeded): fwd 5: +0.6% · fwd 10: +1.0% · fwd 20: +1.9%
- Buy & hold (1330 tickers): +74.9% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11402
- Saved capital (hard floor broke first after the stall): 3448
- Cut a winner (T1 was still consumed first): 4736
- Neither within the tracking window: 3218

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
