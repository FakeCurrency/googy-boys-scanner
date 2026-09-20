# PhaseMap backtest — CRYPTO

Generated 2026-09-20 · ruleset v1.3.1 · universe 86 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 853 | +2.5% | +2.3% | -172.0% | 42.6% | 9.4 | -225.8% |
| tier A+ | 111 | +1.1% | +1.4% | +137.3% | 48.6% | 9.2 | -15.6% |
| tier A | 531 | +2.9% | +2.4% | -307.3% | 42.4% | 9.7 | -354.8% |
| long | 458 | +2.5% | +2.6% | +39.4% | 45.2% | 7.7 | -12.3% |
| short | 395 | +2.5% | +2.0% | -417.5% | 39.5% | 11.5 | -473.4% |
| liquid | 766 | +2.7% | +2.5% | +3.2% | 43.7% | 9.1 | -13.1% |
| illiquid | 87 | +0.9% | +0.9% | -1699.2% | 32.2% | 12.9 | -2099.1% |
| price >= $1 | 506 | +2.9% | +2.0% | +3.0% | 42.9% | 8.7 | -11.5% |
| cents (<$1) | 347 | +1.9% | +2.8% | -426.9% | 42.1% | 10.5 | -538.4% |
| in-sample | 609 | +2.2% | +2.1% | -240.1% | 41.1% | 9.8 | -288.8% |
| out-of-sample | 244 | +3.3% | +2.9% | +3.5% | 46.3% | 8.3 | -68.8% |

## Baselines (same tickers, same window)
- Random entry (837 samples, seeded): fwd 5: +1.8% · fwd 10: +3.5% · fwd 20: +100.1%
- Buy & hold (58 tickers): +1018.0% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 788
- Saved capital (hard floor broke first after the stall): 238
- Cut a winner (T1 was still consumed first): 349
- Neither within the tracking window: 201

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
