# PhaseMap backtest — CRYPTO

Generated 2026-08-02 · ruleset v1.3.1 · universe 101 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 981 | +2.1% | +2.1% | -144.8% | 39.6% | 11.1 | -914.9% |
| tier A+ | 128 | +0.5% | +0.8% | +123.0% | 40.6% | 11.9 | -19.1% |
| tier A | 608 | +2.6% | +2.3% | -258.3% | 39.8% | 11.5 | -851.2% |
| long | 514 | +1.6% | +1.8% | +44.7% | 40.7% | 8.8 | -14.6% |
| short | 467 | +2.6% | +2.4% | -353.6% | 38.3% | 13.5 | -1908.0% |
| liquid | 808 | +2.5% | +2.1% | +2.7% | 41.8% | 9.3 | -13.9% |
| illiquid | 173 | +0.1% | +2.0% | -838.2% | 28.9% | 21.2 | -5118.1% |
| price >= $1 | 504 | +2.4% | +1.5% | +2.5% | 41.5% | 8.7 | -12.2% |
| cents (<$1) | 477 | +1.8% | +2.6% | -301.2% | 37.5% | 13.6 | -1866.9% |
| in-sample | 758 | +2.0% | +2.2% | -186.0% | 39.2% | 11.7 | -1160.9% |
| out-of-sample | 223 | +2.4% | +1.4% | +1.2% | 40.8% | 8.8 | -75.0% |

## Baselines (same tickers, same window)
- Random entry (798 samples, seeded): fwd 5: +83.0% · fwd 10: +2.8% · fwd 20: +10.2%
- Buy & hold (75 tickers): +493.4% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 899
- Saved capital (hard floor broke first after the stall): 281
- Cut a winner (T1 was still consumed first): 376
- Neither within the tracking window: 242

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
