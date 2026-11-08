# PhaseMap backtest — CRYPTO

Generated 2026-11-08 · ruleset v1.3.1 · universe 201 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 257 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1873 | -78.9% | -50.3% | +41.7% | 44.2% | 8.5 | -114.1% |
| tier A+ | 257 | +1.3% | +4.1% | +59.9% | 47.5% | 8.1 | -25.4% |
| tier A | 1181 | -125.4% | -126.2% | +8.1% | 44.8% | 8.8 | -169.3% |
| long | 1011 | +2.2% | +56.4% | +226.0% | 46.8% | 7.3 | -13.6% |
| short | 862 | -173.6% | -175.0% | -174.1% | 41.2% | 10.1 | -232.1% |
| liquid | 1608 | +2.1% | +2.5% | +3.8% | 45.1% | 8.4 | -14.5% |
| illiquid | 265 | -569.8% | -372.1% | +271.5% | 38.5% | 9.2 | -718.5% |
| price >= $1 | 844 | +2.1% | +1.8% | +3.0% | 45.4% | 8.4 | -12.7% |
| cents (<$1) | 1029 | -145.0% | -92.8% | +73.3% | 43.2% | 8.6 | -197.4% |
| in-sample | 1215 | -122.0% | -78.3% | +61.1% | 44.3% | 8.9 | -156.7% |
| out-of-sample | 658 | +2.7% | +3.1% | +4.4% | 44.1% | 7.9 | -35.5% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 753 | 55.9% | +618.7R | -287.2R | **+331.6R** | +0.440R | 2.15 | $+154,325 |
| long A+/A, stop at the worst print | 753 | 55.9% | +618.7R | -352.7R | **+266.1R** | +0.353R | 1.75 | $+145,398 |
| long A+/A, engine-native close exits | 753 | 57.6% | +629.8R | -310.5R | **+319.3R** | +0.424R | 2.03 | $+153,749 |
| long A+/A, liquid only | 639 | 56.7% | +312.2R | -240.6R | **+71.6R** | +0.112R | 1.3 | $+10,093 |
| short A+/A | 685 | 54.9% | +259.9R | -278.5R | **-18.6R** | -0.027R | 0.93 | $-730,538 |
| bullish A+ | 129 | 56.6% | +291.2R | -49.6R | **+241.5R** | +1.872R | 5.87 | $+145,189 |
| bullish A | 624 | 55.8% | +327.6R | -237.6R | **+90.0R** | +0.144R | 1.38 | $+9,137 |
| bullish Watch | 258 | 46.9% | +2883.1R | -114.9R | **+2768.2R** | +10.729R | 25.1 | $+424,484 |
| bearish A+ | 128 | 57.8% | +53.0R | -46.4R | **+6.7R** | +0.052R | 1.14 | $-388 |
| bearish A | 557 | 54.2% | +206.9R | -232.1R | **-25.2R** | -0.045R | 0.89 | $-730,150 |
| bearish Watch | 177 | 57.1% | +75.6R | -63.7R | **+11.9R** | +0.067R | 1.19 | $-904 |
| exit: t1 | 862 | 100.0% | +3765.6R | 0.0R | **+3765.6R** | +4.368R | — | $+698,121 |
| exit: stop | 637 | 0.0% | +0.0R | -654.0R | **-654.0R** | -1.027R | 0.0 | $-839,807 |
| exit: engine_end | 352 | 42.9% | +69.3R | -83.6R | **-14.3R** | -0.041R | 0.83 | $-10,770 |
| exit: eod | 22 | 27.3% | +2.4R | -6.6R | **-4.2R** | -0.190R | 0.37 | $-176 |

## Baselines (same tickers, same window)
- Random entry, LONG only (1780 samples, seeded) — compare with the **long** cohort: fwd 5: +22.2% · fwd 10: +16.1% · fwd 20: +47922.2%
- Random entry, signed to the signals' own mix (918 long / 862 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: +20.4% · fwd 10: +13.3% · fwd 20: +44415.3%
- Buy & hold (138 tickers): +2320.2% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 1747
- Saved capital (hard floor broke first after the stall): 513
- Cut a winner (T1 was still consumed first): 792
- Neither within the tracking window: 442

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
