# PhaseMap backtest — CRYPTO

Generated 2026-09-20 · ruleset v1.3.1 · universe 101 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 946 | +2.6% | +2.6% | -154.3% | 42.9% | 9.2 | -205.4% |
| tier A+ | 125 | +1.7% | +2.6% | +123.1% | 48.0% | 9.3 | -15.4% |
| tier A | 591 | +2.7% | +2.3% | -275.3% | 42.5% | 9.5 | -321.4% |
| long | 510 | +2.6% | +2.5% | +36.3% | 45.3% | 7.7 | -12.3% |
| short | 436 | +2.7% | +2.6% | -377.5% | 40.1% | 11.2 | -430.4% |
| liquid | 855 | +2.8% | +2.7% | +3.7% | 44.1% | 9.0 | -13.1% |
| illiquid | 91 | +1.1% | +1.1% | -1624.6% | 31.9% | 12.5 | -2007.6% |
| price >= $1 | 526 | +2.9% | +2.2% | +3.1% | 43.0% | 8.5 | -11.9% |
| cents (<$1) | 420 | +2.2% | +3.0% | -350.9% | 42.9% | 10.2 | -446.8% |
| in-sample | 674 | +2.3% | +2.4% | -216.3% | 41.5% | 9.7 | -262.4% |
| out-of-sample | 272 | +3.4% | +2.9% | +4.1% | 46.3% | 8.1 | -63.1% |

## Baselines (same tickers, same window)
- Random entry (909 samples, seeded): fwd 5: +1.1% · fwd 10: +0.9% · fwd 20: +4.2%
- Buy & hold (66 tickers): +1052.1% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 878
- Saved capital (hard floor broke first after the stall): 265
- Cut a winner (T1 was still consumed first): 390
- Neither within the tracking window: 223

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
