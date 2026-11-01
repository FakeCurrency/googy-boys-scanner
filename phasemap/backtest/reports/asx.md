# PhaseMap backtest — ASX

Generated 2026-11-01 · ruleset v1.3.1 · universe 2060 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 1677 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 13255 | +0.1% | +0.7% | +1.0% | 30.3% | 10.1 | -13.0% |
| tier A+ | 1677 | -0.3% | +0.1% | +0.5% | 29.1% | 10.3 | -12.0% |
| tier A | 7435 | +0.0% | +0.8% | +0.8% | 30.1% | 10.2 | -13.5% |
| long | 6581 | +0.1% | +0.6% | +1.2% | 29.2% | 8.6 | -11.7% |
| short | 6674 | +0.0% | +0.7% | +0.8% | 31.4% | 11.3 | -14.2% |
| liquid | 3842 | +1.1% | +1.7% | +2.2% | 41.1% | 9.3 | -8.3% |
| illiquid | 9413 | -0.4% | +0.2% | +0.5% | 25.9% | 10.5 | -14.9% |
| price >= $1 | 4222 | +0.5% | +0.8% | +1.0% | 38.5% | 9.0 | -6.6% |
| cents (<$1) | 9033 | -0.1% | +0.6% | +0.9% | 26.4% | 10.8 | -16.0% |
| in-sample | 9543 | +0.1% | +0.7% | +1.0% | 30.6% | 10.2 | -12.6% |
| out-of-sample | 3712 | +0.1% | +0.7% | +0.8% | 29.4% | 9.6 | -14.0% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 4475 | 38.5% | +1610.5R | -2207.5R | **-597.0R** | -0.133R | 0.73 | $-75,131 |
| long A+/A, stop at the worst print | 4475 | 38.5% | +1610.5R | -2587.6R | **-977.2R** | -0.218R | 0.62 | $-116,675 |
| long A+/A, engine-native close exits | 4475 | 40.3% | +1671.8R | -2322.9R | **-651.1R** | -0.146R | 0.72 | $-78,176 |
| long A+/A, liquid only | 1106 | 51.6% | +434.7R | -461.7R | **-26.9R** | -0.024R | 0.94 | $-2,712 |
| short A+/A | 4605 | 47.4% | +1648.5R | -2188.2R | **-539.7R** | -0.117R | 0.75 | $-84,543 |
| bullish A+ | 801 | 38.6% | +259.7R | -401.9R | **-142.2R** | -0.178R | 0.65 | $-24,355 |
| bullish A | 3674 | 38.5% | +1350.8R | -1805.6R | **-454.8R** | -0.124R | 0.75 | $-50,776 |
| bullish Watch | 2085 | 39.1% | +792.0R | -1037.7R | **-245.8R** | -0.118R | 0.76 | $-35,181 |
| bearish A+ | 872 | 46.6% | +285.1R | -390.2R | **-105.1R** | -0.121R | 0.73 | $-15,549 |
| bearish A | 3733 | 47.7% | +1363.4R | -1798.0R | **-434.6R** | -0.116R | 0.76 | $-68,994 |
| bearish Watch | 2038 | 48.0% | +778.6R | -929.6R | **-151.0R** | -0.074R | 0.84 | $-19,437 |
| exit: t1 | 4243 | 100.0% | +4052.5R | 0.0R | **+4052.5R** | +0.955R | — | $+596,408 |
| exit: stop | 4928 | 0.0% | +0.0R | -5472.5R | **-5472.5R** | -1.110R | 0.0 | $-744,540 |
| exit: engine_end | 3878 | 36.1% | +726.2R | -862.5R | **-136.3R** | -0.035R | 0.84 | $-68,547 |
| exit: eod | 154 | 37.7% | +50.8R | -27.9R | **+22.8R** | +0.148R | 1.82 | $+2,388 |

Not traded: signal on the last bar 8, stop_too_tight 44

## Baselines (same tickers, same window)
- Random entry, LONG only (12651 samples, seeded) — compare with the **long** cohort: fwd 5: +0.2% · fwd 10: +0.4% · fwd 20: +1.1%
- Random entry, signed to the signals' own mix (5977 long / 6674 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: -0.1% · fwd 10: -0.2% · fwd 20: -0.1%
- Buy & hold (1505 tickers): +19.3% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11779
- Saved capital (hard floor broke first after the stall): 3513
- Cut a winner (T1 was still consumed first): 3724
- Neither within the tracking window: 4542

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
