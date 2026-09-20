# PhaseMap backtest — CRYPTO

Generated 2026-09-20 · ruleset v1.3.1 · universe 101 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 952 | +2.7% | +2.6% | -153.2% | 43.1% | 9.2 | -203.8% |
| tier A+ | 127 | +1.9% | +3.1% | +122.0% | 48.8% | 9.2 | -15.3% |
| tier A | 595 | +2.8% | +2.2% | -273.5% | 42.5% | 9.5 | -318.4% |
| long | 514 | +2.6% | +2.6% | +36.1% | 45.5% | 7.6 | -12.3% |
| short | 438 | +2.7% | +2.6% | -375.7% | 40.2% | 11.2 | -428.6% |
| liquid | 861 | +2.8% | +2.8% | +3.8% | 44.3% | 8.9 | -13.2% |
| illiquid | 91 | +1.1% | +1.1% | -1624.6% | 31.9% | 12.5 | -2007.6% |
| price >= $1 | 527 | +2.9% | +2.2% | +3.2% | 42.9% | 8.5 | -11.9% |
| cents (<$1) | 425 | +2.3% | +3.1% | -346.7% | 43.3% | 10.1 | -441.8% |
| in-sample | 676 | +2.4% | +2.4% | -215.6% | 41.6% | 9.7 | -261.7% |
| out-of-sample | 276 | +3.5% | +3.0% | +4.2% | 46.7% | 8.0 | -62.0% |

## Baselines (same tickers, same window)
- Random entry (912 samples, seeded): fwd 5: +1.6% · fwd 10: +1.7% · fwd 20: +5.0%
- Buy & hold (67 tickers): +1114.0% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 884
- Saved capital (hard floor broke first after the stall): 268
- Cut a winner (T1 was still consumed first): 394
- Neither within the tracking window: 222

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
