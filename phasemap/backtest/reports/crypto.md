# PhaseMap backtest — CRYPTO

Generated 2026-10-18 · ruleset v1.3.1 · universe 201 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 258 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1879 | -78.1% | -49.7% | +41.2% | 44.1% | 8.4 | -113.6% |
| tier A+ | 258 | +1.5% | +4.5% | +60.1% | 47.7% | 8.0 | -25.5% |
| tier A | 1188 | -124.2% | -125.2% | +7.4% | 44.3% | 8.6 | -168.1% |
| long | 1029 | +2.0% | +54.7% | +220.2% | 46.5% | 7.3 | -13.6% |
| short | 850 | -175.2% | -176.8% | -178.4% | 41.2% | 9.9 | -234.7% |
| liquid | 1629 | +2.1% | +2.4% | +3.4% | 45.1% | 8.3 | -14.6% |
| illiquid | 250 | -598.8% | -386.9% | +286.1% | 37.2% | 9.2 | -758.6% |
| price >= $1 | 844 | +2.2% | +1.8% | +2.9% | 45.6% | 8.3 | -12.9% |
| cents (<$1) | 1035 | -143.6% | -92.0% | +72.9% | 42.8% | 8.5 | -195.8% |
| in-sample | 1245 | -119.0% | -76.1% | +59.5% | 43.6% | 8.9 | -152.9% |
| out-of-sample | 634 | +2.8% | +3.0% | +3.7% | 45.0% | 7.5 | -36.5% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 768 | 55.5% | +625.7R | -296.1R | **+329.6R** | +0.429R | 2.11 | $+152,525 |
| long A+/A, stop at the worst print | 768 | 55.5% | +625.7R | -369.6R | **+256.0R** | +0.333R | 1.69 | $+142,615 |
| long A+/A, engine-native close exits | 768 | 57.2% | +636.8R | -324.9R | **+311.9R** | +0.406R | 1.96 | $+151,313 |
| long A+/A, liquid only | 659 | 56.1% | +320.6R | -251.1R | **+69.5R** | +0.105R | 1.28 | $+7,766 |
| short A+/A | 678 | 54.7% | +255.1R | -277.1R | **-22.1R** | -0.033R | 0.92 | $-730,982 |
| bullish A+ | 128 | 58.6% | +293.5R | -47.5R | **+245.9R** | +1.921R | 6.17 | $+146,080 |
| bullish A | 640 | 54.8% | +332.2R | -248.5R | **+83.7R** | +0.131R | 1.34 | $+6,445 |
| bullish Watch | 261 | 45.6% | +2883.5R | -118.0R | **+2765.5R** | +10.596R | 24.44 | $+423,419 |
| bearish A+ | 130 | 56.9% | +52.2R | -49.4R | **+2.9R** | +0.022R | 1.06 | $-1,040 |
| bearish A | 548 | 54.2% | +202.8R | -227.8R | **-25.0R** | -0.046R | 0.89 | $-729,942 |
| bearish Watch | 172 | 58.7% | +77.5R | -59.7R | **+17.8R** | +0.104R | 1.3 | $+748 |
| exit: t1 | 862 | 100.0% | +3769.6R | 0.0R | **+3769.6R** | +4.373R | — | $+697,463 |
| exit: stop | 642 | 0.0% | +0.0R | -659.1R | **-659.1R** | -1.027R | 0.0 | $-839,307 |
| exit: engine_end | 358 | 40.8% | +69.3R | -88.4R | **-19.0R** | -0.053R | 0.78 | $-12,306 |
| exit: eod | 17 | 52.9% | +2.9R | -3.4R | **-0.6R** | -0.032R | 0.84 | $-139 |

## Baselines (same tickers, same window)
- Random entry, LONG only (1806 samples, seeded) — compare with the **long** cohort: fwd 5: +1.6% · fwd 10: +1644.2% · fwd 20: +1434.7%
- Random entry, signed to the signals' own mix (956 long / 850 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: -0.3% · fwd 10: -1640.9% · fwd 20: -1430.2%
- Buy & hold (141 tickers): +2435.7% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 1755
- Saved capital (hard floor broke first after the stall): 523
- Cut a winner (T1 was still consumed first): 789
- Neither within the tracking window: 443

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
