# PhaseMap backtest — NASDAQ

Generated 2026-11-22 · ruleset v1.3.1 · universe 1420 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 1464 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12654 | +0.7% | +1.5% | +1.9% | 40.7% | 9.6 | -8.6% |
| tier A+ | 1464 | +0.2% | +0.9% | +0.9% | 39.3% | 9.8 | -8.5% |
| tier A | 7036 | +0.7% | +1.6% | +2.0% | 40.5% | 9.8 | -8.8% |
| long | 5893 | +1.0% | +2.4% | +3.8% | 43.3% | 9.2 | -8.1% |
| short | 6761 | +0.4% | +0.7% | +0.3% | 38.4% | 10.0 | -9.1% |
| liquid | 11692 | +0.7% | +1.6% | +2.0% | 41.5% | 9.6 | -8.7% |
| illiquid | 962 | +0.5% | +0.8% | +1.4% | 30.7% | 9.7 | -7.6% |
| price >= $1 | 12606 | +0.7% | +1.5% | +1.9% | 40.7% | 9.6 | -8.6% |
| cents (<$1) | 48 | +4.2% | +2.0% | +5.8% | 41.7% | 6.8 | -22.0% |
| in-sample | 8806 | +0.8% | +1.8% | +2.4% | 41.5% | 9.8 | -8.3% |
| out-of-sample | 3848 | +0.3% | +0.8% | +0.9% | 38.9% | 9.1 | -9.3% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 4046 | 53.8% | +1703.8R | -1636.1R | **+67.8R** | +0.017R | 1.04 | $+18,045 |
| long A+/A, stop at the worst print | 4046 | 53.8% | +1703.8R | -1943.2R | **-239.3R** | -0.059R | 0.88 | $-9,064 |
| long A+/A, engine-native close exits | 4046 | 56.4% | +1804.5R | -1684.5R | **+120.0R** | +0.030R | 1.07 | $+23,622 |
| long A+/A, liquid only | 3718 | 54.7% | +1570.8R | -1473.9R | **+96.9R** | +0.026R | 1.07 | $+19,823 |
| short A+/A | 4417 | 50.1% | +1706.1R | -2060.7R | **-354.6R** | -0.080R | 0.83 | $-37,994 |
| bullish A+ | 691 | 50.5% | +273.2R | -304.7R | **-31.4R** | -0.045R | 0.9 | $-882 |
| bullish A | 3355 | 54.5% | +1430.6R | -1331.4R | **+99.2R** | +0.030R | 1.07 | $+18,927 |
| bullish Watch | 1836 | 56.1% | +795.0R | -732.7R | **+62.3R** | +0.034R | 1.08 | $+10,478 |
| bearish A+ | 771 | 46.6% | +258.9R | -369.9R | **-111.0R** | -0.144R | 0.7 | $-8,388 |
| bearish A | 3646 | 50.8% | +1447.2R | -1690.8R | **-243.6R** | -0.067R | 0.86 | $-29,606 |
| bearish Watch | 2298 | 49.6% | +896.6R | -1056.7R | **-160.1R** | -0.070R | 0.85 | $-14,417 |
| exit: t1 | 5362 | 100.0% | +4468.6R | 0.0R | **+4468.6R** | +0.833R | — | $+488,335 |
| exit: stop | 4540 | 0.0% | +0.0R | -4897.4R | **-4897.4R** | -1.079R | 0.0 | $-495,291 |
| exit: engine_end | 2537 | 43.0% | +556.4R | -565.4R | **-9.0R** | -0.004R | 0.98 | $-20,285 |
| exit: eod | 158 | 67.7% | +76.6R | -23.3R | **+53.3R** | +0.337R | 3.28 | $+3,354 |

Not traded: signal on the last bar 4, stop_too_tight 53

## Baselines (same tickers, same window)
- Random entry, LONG only (11738 samples, seeded) — compare with the **long** cohort: fwd 5: +0.5% · fwd 10: +0.9% · fwd 20: +1.5%
- Random entry, signed to the signals' own mix (4977 long / 6761 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: -0.1% · fwd 10: -0.2% · fwd 20: -0.6%
- Buy & hold (1326 tickers): +56.9% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11457
- Saved capital (hard floor broke first after the stall): 3491
- Cut a winner (T1 was still consumed first): 4702
- Neither within the tracking window: 3264

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
