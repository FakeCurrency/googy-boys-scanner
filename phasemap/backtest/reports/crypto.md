# PhaseMap backtest — CRYPTO

Generated 2026-10-25 · ruleset v1.3.1 · universe 201 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 254 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1820 | -80.5% | -51.1% | +42.4% | 44.0% | 8.5 | -116.7% |
| tier A+ | 254 | +1.1% | +4.1% | +61.0% | 46.9% | 8.0 | -25.5% |
| tier A | 1149 | -128.0% | -128.5% | +7.8% | 44.1% | 8.8 | -173.1% |
| long | 985 | +2.1% | +56.9% | +229.1% | 46.3% | 7.3 | -13.5% |
| short | 835 | -178.1% | -178.8% | -179.1% | 41.2% | 10.0 | -238.6% |
| liquid | 1580 | +2.1% | +2.5% | +3.5% | 44.9% | 8.4 | -14.4% |
| illiquid | 240 | -623.5% | -402.8% | +297.4% | 37.5% | 9.3 | -789.4% |
| price >= $1 | 825 | +2.1% | +1.8% | +2.9% | 45.8% | 8.4 | -12.7% |
| cents (<$1) | 995 | -149.1% | -94.8% | +75.4% | 42.4% | 8.6 | -202.9% |
| in-sample | 1202 | -123.3% | -78.8% | +61.7% | 43.5% | 8.9 | -157.8% |
| out-of-sample | 618 | +3.0% | +3.3% | +4.1% | 44.8% | 7.8 | -36.4% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 738 | 55.3% | +610.5R | -286.1R | **+324.4R** | +0.440R | 2.13 | $+152,077 |
| long A+/A, stop at the worst print | 738 | 55.3% | +610.5R | -356.4R | **+254.1R** | +0.344R | 1.71 | $+142,893 |
| long A+/A, engine-native close exits | 738 | 57.0% | +621.6R | -313.6R | **+308.0R** | +0.417R | 1.98 | $+151,174 |
| long A+/A, liquid only | 634 | 56.0% | +307.3R | -242.4R | **+64.9R** | +0.102R | 1.27 | $+7,793 |
| short A+/A | 664 | 54.5% | +250.4R | -272.7R | **-22.4R** | -0.034R | 0.92 | $-731,775 |
| bullish A+ | 127 | 56.7% | +290.8R | -49.2R | **+241.6R** | +1.902R | 5.91 | $+145,148 |
| bullish A | 611 | 55.0% | +319.7R | -236.9R | **+82.8R** | +0.136R | 1.35 | $+6,930 |
| bullish Watch | 247 | 47.0% | +2878.4R | -110.4R | **+2768.1R** | +11.207R | 26.08 | $+423,927 |
| bearish A+ | 126 | 56.3% | +50.4R | -48.3R | **+2.1R** | +0.016R | 1.04 | $-1,483 |
| bearish A | 538 | 54.1% | +200.0R | -224.4R | **-24.4R** | -0.045R | 0.89 | $-730,293 |
| bearish Watch | 170 | 58.2% | +76.5R | -59.7R | **+16.8R** | +0.099R | 1.28 | $+381 |
| exit: t1 | 835 | 100.0% | +3744.7R | 0.0R | **+3744.7R** | +4.485R | — | $+692,215 |
| exit: stop | 627 | 0.0% | +0.0R | -643.8R | **-643.8R** | -1.027R | 0.0 | $-836,635 |
| exit: engine_end | 351 | 41.9% | +69.5R | -84.5R | **-15.0R** | -0.043R | 0.82 | $-11,198 |
| exit: eod | 6 | 50.0% | +1.7R | -0.7R | **+1.0R** | +0.173R | 2.6 | $+227 |

Not traded: signal on the last bar 1

## Baselines (same tickers, same window)
- Random entry, LONG only (1732 samples, seeded) — compare with the **long** cohort: fwd 5: +1830.7% · fwd 10: +3.6% · fwd 20: +3.8%
- Random entry, signed to the signals' own mix (897 long / 835 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: -1830.3% · fwd 10: -0.9% · fwd 20: -2.5%
- Buy & hold (136 tickers): +2335.2% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 1696
- Saved capital (hard floor broke first after the stall): 509
- Cut a winner (T1 was still consumed first): 761
- Neither within the tracking window: 426

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
