# PhaseMap backtest — NASDAQ

Generated 2026-11-15 · ruleset v1.3.1 · universe 1425 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 1468 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12740 | +0.7% | +1.5% | +2.0% | 40.3% | 9.6 | -8.6% |
| tier A+ | 1468 | +0.3% | +0.9% | +0.9% | 39.9% | 9.6 | -8.5% |
| tier A | 7077 | +0.7% | +1.5% | +1.9% | 39.9% | 9.8 | -8.7% |
| long | 5921 | +1.1% | +2.4% | +3.8% | 43.2% | 9.2 | -8.0% |
| short | 6819 | +0.4% | +0.7% | +0.4% | 37.7% | 9.9 | -9.1% |
| liquid | 11762 | +0.7% | +1.5% | +2.0% | 41.0% | 9.6 | -8.7% |
| illiquid | 978 | +0.5% | +0.8% | +1.4% | 31.2% | 9.7 | -7.6% |
| price >= $1 | 12691 | +0.7% | +1.5% | +1.9% | 40.2% | 9.6 | -8.5% |
| cents (<$1) | 49 | +4.8% | +2.8% | +6.5% | 42.9% | 7.0 | -21.5% |
| in-sample | 8903 | +0.9% | +1.8% | +2.4% | 41.6% | 9.7 | -8.3% |
| out-of-sample | 3837 | +0.3% | +0.6% | +0.9% | 37.2% | 9.1 | -9.1% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 4059 | 54.0% | +1714.9R | -1627.7R | **+87.2R** | +0.021R | 1.05 | $+19,996 |
| long A+/A, stop at the worst print | 4059 | 54.0% | +1714.9R | -1932.9R | **-218.0R** | -0.054R | 0.89 | $-6,943 |
| long A+/A, engine-native close exits | 4059 | 56.6% | +1815.7R | -1675.8R | **+139.9R** | +0.034R | 1.08 | $+25,696 |
| long A+/A, liquid only | 3727 | 54.9% | +1578.1R | -1467.1R | **+111.0R** | +0.030R | 1.08 | $+21,083 |
| short A+/A | 4450 | 49.0% | +1668.8R | -2087.1R | **-418.3R** | -0.094R | 0.8 | $-43,657 |
| bullish A+ | 694 | 51.0% | +277.7R | -303.2R | **-25.5R** | -0.037R | 0.92 | $-130 |
| bullish A | 3365 | 54.7% | +1437.2R | -1324.5R | **+112.7R** | +0.033R | 1.09 | $+20,126 |
| bullish Watch | 1851 | 56.1% | +802.1R | -733.5R | **+68.6R** | +0.037R | 1.09 | $+11,701 |
| bearish A+ | 773 | 47.0% | +262.2R | -373.9R | **-111.7R** | -0.145R | 0.7 | $-8,554 |
| bearish A | 3677 | 49.4% | +1406.6R | -1713.2R | **-306.6R** | -0.083R | 0.82 | $-35,103 |
| bearish Watch | 2327 | 48.1% | +865.4R | -1061.1R | **-195.7R** | -0.084R | 0.82 | $-17,571 |
| exit: t1 | 5343 | 100.0% | +4454.3R | 0.0R | **+4454.3R** | +0.834R | — | $+486,630 |
| exit: stop | 4542 | 0.0% | +0.0R | -4903.4R | **-4903.4R** | -1.080R | 0.0 | $-496,232 |
| exit: engine_end | 2562 | 42.8% | +554.3R | -566.5R | **-12.2R** | -0.005R | 0.98 | $-20,386 |
| exit: eod | 240 | 38.8% | +42.6R | -39.4R | **+3.2R** | +0.013R | 1.08 | $+458 |

Not traded: signal on the last bar 3, stop_too_tight 50

## Baselines (same tickers, same window)
- Random entry, LONG only (11845 samples, seeded) — compare with the **long** cohort: fwd 5: +0.4% · fwd 10: +0.6% · fwd 20: +1.4%
- Random entry, signed to the signals' own mix (5026 long / 6819 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: -0.0% · fwd 10: -0.1% · fwd 20: -0.2%
- Buy & hold (1328 tickers): +69.7% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11514
- Saved capital (hard floor broke first after the stall): 3488
- Cut a winner (T1 was still consumed first): 4684
- Neither within the tracking window: 3342

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
