# PhaseMap backtest — CRYPTO

Generated 2026-07-02 · ruleset v1.2.0 · universe 100 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1018 | +2.8% | +2.9% | -138.2% | 39.4% | 10.9 | -883.8% |
| tier A+ | 129 | +1.4% | +2.1% | +119.7% | 42.6% | 11.4 | -20.7% |
| tier A | 629 | +3.4% | +3.2% | -248.3% | 40.4% | 11.2 | -823.9% |
| long | 539 | +2.1% | +2.6% | +42.7% | 40.3% | 8.7 | -15.2% |
| short | 479 | +3.6% | +3.1% | -341.4% | 38.4% | 13.2 | -1859.3% |
| liquid | 804 | +2.9% | +2.3% | +2.1% | 41.7% | 9.2 | -14.6% |
| illiquid | 214 | +2.5% | +4.9% | -671.4% | 30.8% | 18.3 | -4145.4% |
| price >= $1 | 512 | +3.0% | +2.1% | +2.8% | 41.8% | 8.7 | -12.0% |
| cents (<$1) | 506 | +2.5% | +3.6% | -281.6% | 37.0% | 13.3 | -1764.2% |
| in-sample | 809 | +2.7% | +3.0% | -173.9% | 38.9% | 11.3 | -1090.5% |
| out-of-sample | 209 | +3.1% | +2.1% | +1.7% | 41.1% | 9.2 | -80.0% |

## Baselines (same tickers, same window)
- Random entry (896 samples, seeded): fwd 5: +1202.6% · fwd 10: +9.8% · fwd 20: +3223.0%
- Buy & hold (81 tickers): +3073.8% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 932
- Saved capital (hard floor broke first after the stall): 288
- Cut a winner (T1 was still consumed first): 382
- Neither within the tracking window: 262

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
