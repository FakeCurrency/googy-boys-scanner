# PhaseMap backtest — CRYPTO

Generated 2026-09-13 · ruleset v1.3.1 · universe 101 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1036 | +2.3% | +2.3% | -136.2% | 41.4% | 10.6 | -877.4% |
| tier A+ | 139 | +1.1% | +1.7% | +109.8% | 45.3% | 11.5 | -103.7% |
| tier A | 640 | +2.6% | +2.2% | -246.2% | 40.9% | 11.1 | -807.9% |
| long | 549 | +2.0% | +2.2% | +42.7% | 44.4% | 8.3 | -13.9% |
| short | 487 | +2.7% | +2.4% | -339.8% | 38.0% | 13.4 | -1850.9% |
| liquid | 857 | +2.7% | +2.3% | +3.2% | 44.0% | 9.0 | -13.6% |
| illiquid | 179 | +0.4% | +2.3% | -809.7% | 29.1% | 20.7 | -5012.9% |
| price >= $1 | 523 | +2.9% | +1.9% | +2.8% | 42.8% | 8.6 | -12.1% |
| cents (<$1) | 513 | +1.7% | +2.7% | -278.0% | 40.0% | 12.8 | -1759.6% |
| in-sample | 773 | +1.9% | +2.2% | -182.5% | 39.5% | 11.6 | -1154.1% |
| out-of-sample | 263 | +3.5% | +2.5% | +3.5% | 47.1% | 8.1 | -64.1% |

## Baselines (same tickers, same window)
- Random entry (888 samples, seeded): fwd 5: +141.1% · fwd 10: +140.5% · fwd 20: +239.2%
- Buy & hold (78 tickers): +520.4% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 957
- Saved capital (hard floor broke first after the stall): 290
- Cut a winner (T1 was still consumed first): 417
- Neither within the tracking window: 250

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
