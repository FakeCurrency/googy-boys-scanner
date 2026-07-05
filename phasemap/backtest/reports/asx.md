# PhaseMap backtest — ASX

Generated 2026-07-05 · ruleset v1.2.0 · universe 1988 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 15462 | +1.3% | +1.3% | +1.3% | 29.8% | 10.2 | -12.8% |
| tier A+ | 1937 | +0.8% | +0.9% | +0.8% | 28.8% | 10.5 | -11.6% |
| tier A | 8709 | +1.2% | +1.1% | +1.1% | 29.5% | 10.3 | -13.4% |
| long | 7726 | +1.3% | +1.4% | +1.4% | 28.8% | 8.8 | -11.3% |
| short | 7736 | +1.2% | +1.2% | +1.1% | 30.8% | 11.4 | -14.1% |
| liquid | 4253 | +2.1% | +2.1% | +2.8% | 40.9% | 9.2 | -8.3% |
| illiquid | 11209 | +0.9% | +0.9% | +0.7% | 25.6% | 10.7 | -14.4% |
| price >= $1 | 4758 | +1.3% | +1.2% | +1.3% | 38.2% | 9.2 | -6.4% |
| cents (<$1) | 10704 | +1.3% | +1.3% | +1.2% | 26.1% | 10.8 | -15.6% |
| in-sample | 12157 | +1.2% | +1.3% | +1.4% | 29.9% | 10.4 | -12.2% |
| out-of-sample | 3305 | +1.4% | +1.2% | +0.6% | 29.5% | 9.4 | -14.9% |

## Baselines (same tickers, same window)
- Random entry (14832 samples, seeded): fwd 5: +0.5% · fwd 10: +1.4% · fwd 20: +2.6%
- Buy & hold (1761 tickers): +40.4% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 13767
- Saved capital (hard floor broke first after the stall): 4028
- Cut a winner (T1 was still consumed first): 4315
- Neither within the tracking window: 5424

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
