# PhaseMap backtest — CRYPTO

Generated 2026-08-30 · ruleset v1.3.1 · universe 101 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1019 | +2.1% | +2.0% | -142.3% | 41.1% | 10.7 | -894.4% |
| tier A+ | 137 | +0.7% | +1.3% | +114.4% | 45.3% | 11.6 | -104.6% |
| tier A | 630 | +2.5% | +2.0% | -257.9% | 40.8% | 11.1 | -824.3% |
| long | 540 | +1.8% | +1.8% | +43.9% | 44.1% | 8.3 | -14.0% |
| short | 479 | +2.5% | +2.3% | -347.1% | 37.8% | 13.5 | -1893.2% |
| liquid | 835 | +2.6% | +2.0% | +2.6% | 43.7% | 9.0 | -13.5% |
| illiquid | 184 | +0.0% | +1.8% | -787.5% | 29.3% | 20.4 | -4877.5% |
| price >= $1 | 514 | +2.8% | +1.7% | +2.4% | 42.8% | 8.6 | -11.9% |
| cents (<$1) | 505 | +1.5% | +2.3% | -289.7% | 39.4% | 13.0 | -1787.4% |
| in-sample | 767 | +1.7% | +2.1% | -184.1% | 39.2% | 11.6 | -1163.0% |
| out-of-sample | 252 | +3.5% | +1.8% | +1.9% | 46.8% | 8.1 | -67.1% |

## Baselines (same tickers, same window)
- Random entry (877 samples, seeded): fwd 5: +11.3% · fwd 10: +16.9% · fwd 20: +18.2%
- Buy & hold (76 tickers): +503.7% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 936
- Saved capital (hard floor broke first after the stall): 286
- Cut a winner (T1 was still consumed first): 406
- Neither within the tracking window: 244

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
