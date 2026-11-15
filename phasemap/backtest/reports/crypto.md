# PhaseMap backtest — CRYPTO

Generated 2026-11-15 · ruleset v1.3.1 · universe 201 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 264 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1886 | -77.7% | -49.3% | +41.8% | 44.5% | 8.5 | -113.3% |
| tier A+ | 264 | +2.1% | +7.1% | +62.5% | 47.3% | 8.1 | -25.0% |
| tier A | 1187 | -124.2% | -125.1% | +7.8% | 45.1% | 8.8 | -168.4% |
| long | 1024 | +2.4% | +56.3% | +224.3% | 47.3% | 7.3 | -13.5% |
| short | 862 | -172.7% | -173.5% | -173.5% | 41.3% | 10.2 | -232.0% |
| liquid | 1613 | +2.3% | +2.6% | +3.9% | 45.4% | 8.4 | -14.3% |
| illiquid | 273 | -548.7% | -355.9% | +266.1% | 39.6% | 9.3 | -698.0% |
| price >= $1 | 875 | +2.4% | +2.7% | +4.0% | 46.2% | 8.5 | -12.8% |
| cents (<$1) | 1011 | -147.2% | -94.1% | +74.4% | 43.1% | 8.6 | -200.4% |
| in-sample | 1226 | -120.8% | -77.4% | +60.6% | 44.5% | 8.9 | -155.4% |
| out-of-sample | 660 | +3.0% | +4.0% | +5.4% | 44.5% | 7.9 | -35.0% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 766 | 56.3% | +624.2R | -292.3R | **+331.9R** | +0.433R | 2.14 | $+154,229 |
| long A+/A, stop at the worst print | 766 | 56.3% | +624.2R | -358.5R | **+265.7R** | +0.347R | 1.74 | $+145,376 |
| long A+/A, engine-native close exits | 766 | 58.1% | +635.8R | -315.0R | **+320.8R** | +0.419R | 2.02 | $+153,850 |
| long A+/A, liquid only | 645 | 56.7% | +312.7R | -243.8R | **+69.0R** | +0.107R | 1.28 | $+8,966 |
| short A+/A | 684 | 55.0% | +260.1R | -279.0R | **-18.9R** | -0.028R | 0.93 | $-729,531 |
| bullish A+ | 136 | 55.9% | +292.8R | -52.8R | **+240.0R** | +1.765R | 5.55 | $+145,459 |
| bullish A | 630 | 56.3% | +331.4R | -239.5R | **+91.9R** | +0.146R | 1.38 | $+8,770 |
| bullish Watch | 258 | 46.1% | +2881.8R | -118.0R | **+2763.8R** | +10.712R | 24.42 | $+423,763 |
| bearish A+ | 128 | 58.6% | +53.3R | -46.3R | **+7.0R** | +0.055R | 1.15 | $+628 |
| bearish A | 556 | 54.1% | +206.8R | -232.8R | **-25.9R** | -0.047R | 0.89 | $-730,159 |
| bearish Watch | 177 | 59.3% | +77.6R | -62.1R | **+15.5R** | +0.088R | 1.25 | $+594 |
| exit: t1 | 875 | 100.0% | +3773.1R | 0.0R | **+3773.1R** | +4.312R | — | $+698,344 |
| exit: stop | 649 | 0.0% | +0.0R | -666.5R | **-666.5R** | -1.027R | 0.0 | $-839,180 |
| exit: engine_end | 351 | 43.0% | +69.8R | -82.7R | **-12.9R** | -0.037R | 0.84 | $-10,264 |
| exit: eod | 10 | 50.0% | +0.8R | -2.2R | **-1.4R** | -0.139R | 0.37 | $+154 |

Not traded: signal on the last bar 1

## Baselines (same tickers, same window)
- Random entry, LONG only (1783 samples, seeded) — compare with the **long** cohort: fwd 5: +1778.0% · fwd 10: +2.3% · fwd 20: +1782.2%
- Random entry, signed to the signals' own mix (921 long / 862 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: -1777.9% · fwd 10: -1.4% · fwd 20: +1772.4%
- Buy & hold (136 tickers): +2747.8% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 1757
- Saved capital (hard floor broke first after the stall): 527
- Cut a winner (T1 was still consumed first): 802
- Neither within the tracking window: 428

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
