# PhaseMap backtest — CRYPTO

Generated 2026-07-19 · ruleset v1.2.0 · universe 101 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 994 | +2.7% | +2.8% | -141.7% | 39.8% | 11.1 | -901.7% |
| tier A+ | 125 | +1.9% | +2.6% | +128.3% | 44.0% | 11.8 | -18.1% |
| tier A | 616 | +3.2% | +3.1% | -253.4% | 39.9% | 11.5 | -838.4% |
| long | 520 | +2.0% | +2.4% | +44.7% | 41.2% | 8.8 | -14.5% |
| short | 474 | +3.5% | +3.2% | -345.9% | 38.4% | 13.5 | -1875.0% |
| liquid | 800 | +2.8% | +2.5% | +3.1% | 42.0% | 9.4 | -13.6% |
| illiquid | 194 | +2.2% | +4.0% | -743.4% | 30.9% | 19.2 | -4564.0% |
| price >= $1 | 509 | +3.1% | +2.2% | +3.0% | 41.8% | 8.8 | -11.9% |
| cents (<$1) | 485 | +2.3% | +3.4% | -294.5% | 37.7% | 13.6 | -1835.5% |
| in-sample | 780 | +2.7% | +3.0% | -179.8% | 39.2% | 11.6 | -1127.8% |
| out-of-sample | 214 | +2.9% | +1.9% | +1.6% | 42.1% | 9.0 | -77.7% |

## Baselines (same tickers, same window)
- Random entry (845 samples, seeded): fwd 5: +150.1% · fwd 10: +148.9% · fwd 20: +253.8%
- Buy & hold (77 tickers): +2878.4% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 910
- Saved capital (hard floor broke first after the stall): 280
- Cut a winner (T1 was still consumed first): 382
- Neither within the tracking window: 248

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
