# PhaseMap backtest — NASDAQ

Generated 2026-11-01 · ruleset v1.3.1 · universe 1427 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 1461 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12552 | +0.7% | +1.5% | +2.0% | 40.7% | 9.6 | -8.6% |
| tier A+ | 1461 | +0.4% | +1.0% | +1.1% | 39.9% | 9.7 | -8.5% |
| tier A | 6987 | +0.6% | +1.5% | +1.9% | 40.3% | 9.9 | -8.8% |
| long | 5872 | +1.0% | +2.4% | +3.8% | 43.1% | 9.2 | -7.9% |
| short | 6680 | +0.4% | +0.8% | +0.4% | 38.6% | 9.9 | -9.2% |
| liquid | 11581 | +0.7% | +1.6% | +2.0% | 41.5% | 9.6 | -8.7% |
| illiquid | 971 | +0.5% | +0.8% | +1.5% | 31.1% | 9.5 | -7.6% |
| price >= $1 | 12506 | +0.7% | +1.5% | +2.0% | 40.7% | 9.6 | -8.6% |
| cents (<$1) | 46 | +5.4% | +3.7% | +8.4% | 45.7% | 7.0 | -21.2% |
| in-sample | 9000 | +0.9% | +1.9% | +2.4% | 41.8% | 9.7 | -8.3% |
| out-of-sample | 3552 | +0.3% | +0.7% | +0.9% | 38.0% | 9.2 | -9.3% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 4020 | 53.9% | +1687.6R | -1604.4R | **+83.2R** | +0.021R | 1.05 | $+19,278 |
| long A+/A, stop at the worst print | 4020 | 53.9% | +1687.6R | -1903.2R | **-215.6R** | -0.054R | 0.89 | $-7,068 |
| long A+/A, engine-native close exits | 4020 | 56.4% | +1787.7R | -1648.5R | **+139.2R** | +0.035R | 1.08 | $+25,448 |
| long A+/A, liquid only | 3695 | 54.7% | +1556.7R | -1443.1R | **+113.7R** | +0.031R | 1.08 | $+20,949 |
| short A+/A | 4385 | 49.2% | +1665.0R | -2072.5R | **-407.5R** | -0.093R | 0.8 | $-42,283 |
| bullish A+ | 681 | 50.7% | +269.8R | -292.6R | **-22.8R** | -0.033R | 0.92 | $-320 |
| bullish A | 3339 | 54.5% | +1417.8R | -1311.8R | **+105.9R** | +0.032R | 1.08 | $+19,598 |
| bullish Watch | 1839 | 56.4% | +796.2R | -720.8R | **+75.4R** | +0.041R | 1.1 | $+13,583 |
| bearish A+ | 779 | 46.7% | +266.1R | -375.6R | **-109.5R** | -0.141R | 0.71 | $-8,539 |
| bearish A | 3606 | 49.7% | +1398.9R | -1696.9R | **-298.0R** | -0.083R | 0.82 | $-33,744 |
| bearish Watch | 2244 | 48.8% | +849.4R | -1031.6R | **-182.2R** | -0.081R | 0.82 | $-16,005 |
| exit: t1 | 5326 | 100.0% | +4431.2R | 0.0R | **+4431.2R** | +0.832R | — | $+485,085 |
| exit: stop | 4479 | 0.0% | +0.0R | -4831.9R | **-4831.9R** | -1.079R | 0.0 | $-488,598 |
| exit: engine_end | 2553 | 42.4% | +550.7R | -568.8R | **-18.1R** | -0.007R | 0.97 | $-20,436 |
| exit: eod | 130 | 36.2% | +16.3R | -28.7R | **-12.4R** | -0.095R | 0.57 | $-1,478 |

Not traded: signal on the last bar 13, stop_too_tight 51

## Baselines (same tickers, same window)
- Random entry, LONG only (11649 samples, seeded) — compare with the **long** cohort: fwd 5: +0.8% · fwd 10: +1.1% · fwd 20: +2.5%
- Random entry, signed to the signals' own mix (4969 long / 6680 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: -0.5% · fwd 10: -0.6% · fwd 20: -1.1%
- Buy & hold (1328 tickers): +78.2% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11343
- Saved capital (hard floor broke first after the stall): 3439
- Cut a winner (T1 was still consumed first): 4661
- Neither within the tracking window: 3243

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
