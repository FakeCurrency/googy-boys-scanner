# PhaseMap backtest — ASX

Generated 2026-11-15 · ruleset v1.3.1 · universe 2061 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 1396 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 10733 | +0.1% | +0.6% | +0.7% | 30.3% | 10.0 | -13.2% |
| tier A+ | 1396 | -0.0% | -0.0% | +0.6% | 31.0% | 9.9 | -12.1% |
| tier A | 6013 | +0.0% | +0.6% | +0.3% | 30.0% | 10.2 | -13.9% |
| long | 5342 | +0.1% | +0.5% | +1.0% | 29.3% | 8.6 | -11.7% |
| short | 5391 | +0.0% | +0.6% | +0.4% | 31.3% | 11.2 | -14.7% |
| liquid | 3088 | +1.1% | +1.7% | +2.3% | 41.1% | 9.3 | -8.4% |
| illiquid | 7645 | -0.3% | +0.1% | +0.1% | 26.0% | 10.5 | -15.2% |
| price >= $1 | 3409 | +0.4% | +0.8% | +1.0% | 38.4% | 9.0 | -6.8% |
| cents (<$1) | 7324 | -0.1% | +0.5% | +0.6% | 26.6% | 10.7 | -16.2% |
| in-sample | 7637 | +0.1% | +0.5% | +1.0% | 30.7% | 10.2 | -12.6% |
| out-of-sample | 3096 | +0.1% | +0.7% | -0.1% | 29.4% | 9.5 | -14.8% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 3649 | 38.6% | +1330.0R | -1821.8R | **-491.8R** | -0.135R | 0.73 | $-65,987 |
| long A+/A, stop at the worst print | 3649 | 38.6% | +1330.0R | -2132.3R | **-802.3R** | -0.220R | 0.62 | $-99,797 |
| long A+/A, engine-native close exits | 3649 | 40.5% | +1391.6R | -1898.2R | **-506.7R** | -0.139R | 0.73 | $-65,620 |
| long A+/A, liquid only | 892 | 52.5% | +352.7R | -365.2R | **-12.6R** | -0.014R | 0.97 | $-1,639 |
| short A+/A | 3730 | 48.1% | +1319.5R | -1762.2R | **-442.7R** | -0.119R | 0.75 | $-73,343 |
| bullish A+ | 645 | 40.8% | +221.5R | -310.5R | **-89.0R** | -0.138R | 0.71 | $-17,258 |
| bullish A | 3004 | 38.1% | +1108.5R | -1511.3R | **-402.7R** | -0.134R | 0.73 | $-48,728 |
| bullish Watch | 1677 | 38.5% | +611.1R | -848.4R | **-237.2R** | -0.141R | 0.72 | $-28,140 |
| bearish A+ | 748 | 48.1% | +246.1R | -320.2R | **-74.1R** | -0.099R | 0.77 | $-11,643 |
| bearish A | 2982 | 48.1% | +1073.4R | -1442.0R | **-368.6R** | -0.124R | 0.74 | $-61,699 |
| bearish Watch | 1631 | 47.6% | +609.3R | -740.1R | **-130.8R** | -0.080R | 0.82 | $-14,075 |
| exit: t1 | 3422 | 100.0% | +3259.3R | 0.0R | **+3259.3R** | +0.952R | — | $+482,634 |
| exit: stop | 3994 | 0.0% | +0.0R | -4434.1R | **-4434.1R** | -1.110R | 0.0 | $-604,910 |
| exit: engine_end | 3132 | 36.9% | +584.8R | -706.6R | **-121.8R** | -0.039R | 0.83 | $-59,164 |
| exit: eod | 139 | 33.8% | +25.8R | -31.7R | **-5.8R** | -0.042R | 0.82 | $-103 |

Not traded: signal on the last bar 10, stop_too_tight 36

## Baselines (same tickers, same window)
- Random entry, LONG only (10268 samples, seeded) — compare with the **long** cohort: fwd 5: +0.8% · fwd 10: +0.8% · fwd 20: +1.5%
- Random entry, signed to the signals' own mix (4877 long / 5391 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: -0.4% · fwd 10: -0.3% · fwd 20: -0.7%
- Buy & hold (1212 tickers): +17.2% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 9587
- Saved capital (hard floor broke first after the stall): 2856
- Cut a winner (T1 was still consumed first): 3047
- Neither within the tracking window: 3684

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
