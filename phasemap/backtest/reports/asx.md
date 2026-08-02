# PhaseMap backtest — ASX

Generated 2026-08-02 · ruleset v1.3.1 · universe 2212 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 15558 | +0.7% | +0.7% | +0.7% | 31.0% | 10.0 | -11.3% |
| tier A+ | 1936 | +0.2% | +0.1% | +0.6% | 29.6% | 10.9 | -10.5% |
| tier A | 8774 | +0.7% | +0.8% | +0.7% | 31.3% | 10.1 | -11.7% |
| long | 7042 | +0.9% | +1.0% | +1.1% | 30.3% | 9.1 | -10.9% |
| short | 8516 | +0.5% | +0.5% | +0.5% | 31.6% | 10.6 | -11.6% |
| liquid | 5015 | +1.3% | +1.3% | +1.7% | 39.8% | 9.2 | -7.1% |
| illiquid | 10543 | +0.4% | +0.5% | +0.3% | 26.9% | 10.5 | -13.3% |
| price >= $1 | 6689 | +0.7% | +0.6% | +0.7% | 37.4% | 9.0 | -5.2% |
| cents (<$1) | 8869 | +0.7% | +0.8% | +0.8% | 26.2% | 11.0 | -15.9% |
| in-sample | 11868 | +0.7% | +0.7% | +0.9% | 31.1% | 10.2 | -11.0% |
| out-of-sample | 3690 | +0.7% | +0.7% | +0.3% | 30.7% | 9.4 | -12.4% |

## Baselines (same tickers, same window)
- Random entry (14975 samples, seeded): fwd 5: +0.3% · fwd 10: +4.0% · fwd 20: +1.1%
- Buy & hold (1743 tickers): +26.0% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 13745
- Saved capital (hard floor broke first after the stall): 4221
- Cut a winner (T1 was still consumed first): 4479
- Neither within the tracking window: 5045

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
