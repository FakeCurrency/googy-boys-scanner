# PhaseMap backtest — CRYPTO

Generated 2026-08-09 · ruleset v1.3.1 · universe 101 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1001 | +2.1% | +2.1% | -142.2% | 39.7% | 11.0 | -896.9% |
| tier A+ | 138 | +0.5% | +1.0% | +113.9% | 42.0% | 12.0 | -18.4% |
| tier A | 614 | +2.6% | +2.2% | -256.8% | 39.7% | 11.4 | -841.7% |
| long | 524 | +1.7% | +1.8% | +44.0% | 40.6% | 8.8 | -14.5% |
| short | 477 | +2.6% | +2.5% | -345.3% | 38.6% | 13.4 | -1864.3% |
| liquid | 825 | +2.6% | +2.2% | +2.8% | 42.1% | 9.3 | -13.8% |
| illiquid | 176 | -0.1% | +1.7% | -824.2% | 28.4% | 21.2 | -5031.5% |
| price >= $1 | 505 | +2.5% | +1.7% | +2.5% | 42.0% | 8.8 | -12.1% |
| cents (<$1) | 496 | +1.7% | +2.6% | -290.2% | 37.3% | 13.5 | -1799.5% |
| in-sample | 772 | +2.1% | +2.3% | -182.6% | 39.1% | 11.6 | -1140.2% |
| out-of-sample | 229 | +2.4% | +1.5% | +1.2% | 41.5% | 9.0 | -73.2% |

## Baselines (same tickers, same window)
- Random entry (852 samples, seeded): fwd 5: +2.7% · fwd 10: +566.9% · fwd 20: +650.1%
- Buy & hold (76 tickers): +468.2% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 918
- Saved capital (hard floor broke first after the stall): 286
- Cut a winner (T1 was still consumed first): 385
- Neither within the tracking window: 247

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
