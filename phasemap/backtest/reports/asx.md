# PhaseMap backtest — ASX

Generated 2026-07-03 · ruleset v1.2.0 · universe 1987 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 15369 | +1.3% | +1.3% | +1.3% | 29.7% | 10.2 | -12.7% |
| tier A+ | 1910 | +0.8% | +0.9% | +0.8% | 28.6% | 10.4 | -11.7% |
| tier A | 8656 | +1.2% | +1.2% | +1.2% | 29.4% | 10.4 | -13.3% |
| long | 7690 | +1.3% | +1.4% | +1.4% | 28.7% | 8.9 | -11.3% |
| short | 7679 | +1.2% | +1.3% | +1.2% | 30.7% | 11.4 | -14.0% |
| liquid | 4249 | +2.1% | +2.1% | +2.7% | 40.4% | 9.3 | -8.3% |
| illiquid | 11120 | +0.9% | +1.0% | +0.8% | 25.6% | 10.7 | -14.4% |
| price >= $1 | 4736 | +1.3% | +1.3% | +1.4% | 37.8% | 9.3 | -6.4% |
| cents (<$1) | 10633 | +1.2% | +1.4% | +1.3% | 26.1% | 10.8 | -15.5% |
| in-sample | 12088 | +1.2% | +1.4% | +1.5% | 29.8% | 10.4 | -12.1% |
| out-of-sample | 3281 | +1.4% | +1.2% | +0.6% | 29.5% | 9.4 | -15.0% |

## Baselines (same tickers, same window)
- Random entry (14736 samples, seeded): fwd 5: +0.3% · fwd 10: +0.5% · fwd 20: +4.3%
- Buy & hold (1748 tickers): +40.6% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 13704
- Saved capital (hard floor broke first after the stall): 4007
- Cut a winner (T1 was still consumed first): 4288
- Neither within the tracking window: 5409

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
