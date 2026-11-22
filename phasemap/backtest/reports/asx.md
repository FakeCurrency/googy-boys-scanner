# PhaseMap backtest — ASX

Generated 2026-11-22 · ruleset v1.3.1 · universe 2058 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 1999 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 15613 | +0.0% | +0.5% | +0.8% | 30.1% | 10.1 | -13.1% |
| tier A+ | 1999 | -0.4% | +0.0% | +0.3% | 28.9% | 10.3 | -12.0% |
| tier A | 8765 | -0.1% | +0.5% | +0.6% | 30.0% | 10.2 | -13.7% |
| long | 7775 | -0.1% | +0.3% | +0.9% | 29.1% | 8.7 | -11.9% |
| short | 7838 | +0.1% | +0.7% | +0.8% | 31.1% | 11.3 | -14.3% |
| liquid | 4442 | +1.0% | +1.6% | +2.3% | 41.2% | 9.2 | -8.4% |
| illiquid | 11171 | -0.4% | +0.1% | +0.2% | 25.6% | 10.6 | -15.0% |
| price >= $1 | 4989 | +0.5% | +0.8% | +1.1% | 38.8% | 9.1 | -6.6% |
| cents (<$1) | 10624 | -0.2% | +0.4% | +0.7% | 26.0% | 10.8 | -16.2% |
| in-sample | 11018 | +0.0% | +0.6% | +1.0% | 30.4% | 10.3 | -12.6% |
| out-of-sample | 4595 | -0.1% | +0.3% | +0.4% | 29.4% | 9.6 | -14.4% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 5280 | 38.3% | +1864.3R | -2646.5R | **-782.2R** | -0.148R | 0.7 | $-114,017 |
| long A+/A, stop at the worst print | 5280 | 38.3% | +1864.3R | -3089.0R | **-1224.6R** | -0.232R | 0.6 | $-162,903 |
| long A+/A, engine-native close exits | 5280 | 40.1% | +1937.9R | -2767.7R | **-829.8R** | -0.157R | 0.7 | $-115,772 |
| long A+/A, liquid only | 1294 | 53.0% | +531.3R | -529.7R | **+1.6R** | +0.001R | 1.0 | $-1,142 |
| short A+/A | 5442 | 47.4% | +1943.4R | -2561.8R | **-618.4R** | -0.114R | 0.76 | $-96,263 |
| bullish A+ | 933 | 39.0% | +292.6R | -468.9R | **-176.3R** | -0.189R | 0.62 | $-30,412 |
| bullish A | 4347 | 38.2% | +1571.7R | -2177.6R | **-605.9R** | -0.139R | 0.72 | $-83,606 |
| bullish Watch | 2467 | 38.5% | +941.6R | -1245.8R | **-304.1R** | -0.123R | 0.76 | $-50,054 |
| bearish A+ | 1063 | 45.6% | +337.6R | -488.9R | **-151.3R** | -0.142R | 0.69 | $-19,721 |
| bearish A | 4379 | 47.9% | +1605.9R | -2072.9R | **-467.1R** | -0.107R | 0.77 | $-76,542 |
| bearish Watch | 2359 | 48.0% | +889.6R | -1071.0R | **-181.5R** | -0.077R | 0.83 | $-19,674 |
| exit: t1 | 4964 | 100.0% | +4744.3R | 0.0R | **+4744.3R** | +0.956R | — | $+687,982 |
| exit: stop | 5799 | 0.0% | +0.0R | -6445.9R | **-6445.9R** | -1.112R | 0.0 | $-877,423 |
| exit: engine_end | 4618 | 36.0% | +839.0R | -1040.3R | **-201.3R** | -0.044R | 0.81 | $-92,289 |
| exit: eod | 167 | 37.7% | +55.7R | -38.9R | **+16.7R** | +0.100R | 1.43 | $+1,722 |

Not traded: signal on the last bar 13, stop_too_tight 52

## Baselines (same tickers, same window)
- Random entry, LONG only (14975 samples, seeded) — compare with the **long** cohort: fwd 5: +0.3% · fwd 10: +1.1% · fwd 20: +1.7%
- Random entry, signed to the signals' own mix (7137 long / 7838 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: +0.0% · fwd 10: -0.7% · fwd 20: -0.8%
- Buy & hold (1783 tickers): +10.7% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 13905
- Saved capital (hard floor broke first after the stall): 4122
- Cut a winner (T1 was still consumed first): 4375
- Neither within the tracking window: 5408

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
