# PhaseMap backtest — CRYPTO

Generated 2026-11-01 · ruleset v1.3.1 · universe 201 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 261 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1881 | -78.3% | -49.9% | +41.1% | 44.4% | 8.5 | -113.9% |
| tier A+ | 261 | +1.2% | +3.8% | +58.7% | 47.5% | 8.1 | -25.5% |
| tier A | 1190 | -124.2% | -124.8% | +7.9% | 44.9% | 8.8 | -168.4% |
| long | 1013 | +2.2% | +55.9% | +223.8% | 47.2% | 7.3 | -13.6% |
| short | 868 | -172.2% | -173.4% | -172.4% | 41.2% | 10.0 | -231.3% |
| liquid | 1610 | +2.1% | +2.5% | +3.7% | 45.3% | 8.4 | -14.6% |
| illiquid | 271 | -557.2% | -361.1% | +263.3% | 39.1% | 9.1 | -705.6% |
| price >= $1 | 827 | +2.1% | +1.8% | +2.9% | 45.6% | 8.4 | -12.7% |
| cents (<$1) | 1054 | -141.5% | -90.5% | +71.2% | 43.5% | 8.6 | -193.3% |
| in-sample | 1235 | -120.1% | -77.1% | +60.0% | 44.0% | 8.9 | -154.6% |
| out-of-sample | 646 | +2.9% | +3.1% | +4.2% | 45.2% | 7.7 | -35.9% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 757 | 56.3% | +622.9R | -287.3R | **+335.6R** | +0.443R | 2.17 | $+154,181 |
| long A+/A, stop at the worst print | 757 | 56.3% | +622.9R | -358.6R | **+264.3R** | +0.349R | 1.74 | $+144,777 |
| long A+/A, engine-native close exits | 757 | 58.0% | +634.0R | -316.4R | **+317.6R** | +0.419R | 2.0 | $+153,132 |
| long A+/A, liquid only | 641 | 57.1% | +314.6R | -239.3R | **+75.3R** | +0.117R | 1.31 | $+9,947 |
| short A+/A | 692 | 54.6% | +260.5R | -285.2R | **-24.7R** | -0.036R | 0.91 | $-731,370 |
| bullish A+ | 132 | 56.1% | +291.8R | -51.7R | **+240.1R** | +1.819R | 5.64 | $+144,867 |
| bullish A | 625 | 56.3% | +331.1R | -235.6R | **+95.5R** | +0.153R | 1.41 | $+9,313 |
| bullish Watch | 256 | 47.3% | +2882.8R | -114.0R | **+2768.8R** | +10.816R | 25.28 | $+424,462 |
| bearish A+ | 129 | 58.1% | +53.4R | -47.3R | **+6.1R** | +0.048R | 1.13 | $-373 |
| bearish A | 563 | 53.8% | +207.1R | -237.9R | **-30.9R** | -0.055R | 0.87 | $-730,997 |
| bearish Watch | 174 | 57.5% | +76.9R | -63.1R | **+13.7R** | +0.079R | 1.22 | $-236 |
| exit: t1 | 871 | 100.0% | +3773.4R | 0.0R | **+3773.4R** | +4.332R | — | $+698,806 |
| exit: stop | 647 | 0.0% | +0.0R | -664.2R | **-664.2R** | -1.027R | 0.0 | $-840,651 |
| exit: engine_end | 352 | 42.6% | +69.0R | -83.6R | **-14.6R** | -0.042R | 0.83 | $-11,061 |
| exit: eod | 9 | 44.4% | +0.7R | -1.9R | **-1.2R** | -0.130R | 0.38 | $-56 |

Not traded: signal on the last bar 2

## Baselines (same tickers, same window)
- Random entry, LONG only (1816 samples, seeded) — compare with the **long** cohort: fwd 5: +175.8% · fwd 10: +168.2% · fwd 20: +45402.1%
- Random entry, signed to the signals' own mix (948 long / 868 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: -144.0% · fwd 10: -139.7% · fwd 20: +45104.9%
- Buy & hold (139 tickers): +2456.0% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 1748
- Saved capital (hard floor broke first after the stall): 524
- Cut a winner (T1 was still consumed first): 797
- Neither within the tracking window: 427

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
