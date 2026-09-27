# PhaseMap backtest — ASX

Generated 2026-09-27 · ruleset v1.3.1 · universe 2047 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 9281 | +0.7% | +0.7% | +0.9% | 30.2% | 10.1 | -12.9% |
| tier A+ | 1216 | +0.3% | +0.1% | +0.8% | 30.4% | 10.1 | -11.6% |
| tier A | 5205 | +0.6% | +0.5% | +0.5% | 30.0% | 10.4 | -13.5% |
| long | 4589 | +1.0% | +1.1% | +1.1% | 29.8% | 8.7 | -11.5% |
| short | 4692 | +0.5% | +0.4% | +0.6% | 30.6% | 11.3 | -14.2% |
| liquid | 2657 | +1.7% | +1.7% | +2.2% | 41.2% | 9.3 | -8.5% |
| illiquid | 6624 | +0.3% | +0.4% | +0.3% | 25.8% | 10.6 | -14.6% |
| price >= $1 | 2933 | +0.9% | +0.8% | +1.0% | 37.9% | 8.9 | -6.7% |
| cents (<$1) | 6348 | +0.6% | +0.7% | +0.8% | 26.6% | 10.8 | -15.7% |
| in-sample | 6886 | +0.7% | +0.7% | +1.0% | 30.4% | 10.3 | -12.4% |
| out-of-sample | 2395 | +0.8% | +0.9% | +0.4% | 29.6% | 9.5 | -14.3% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 3140 | 38.2% | +1146.8R | -1575.3R | **-428.6R** | -0.136R | 0.73 | $-48,841 |
| long A+/A, stop at the worst print | 3140 | 38.2% | +1146.8R | -1848.2R | **-701.5R** | -0.223R | 0.62 | $-77,381 |
| long A+/A, engine-native close exits | 3140 | 40.3% | +1196.9R | -1650.1R | **-453.2R** | -0.144R | 0.73 | $-48,583 |
| long A+/A, liquid only | 776 | 51.3% | +299.7R | -328.8R | **-29.1R** | -0.037R | 0.91 | $-1,460 |
| short A+/A | 3257 | 46.9% | +1119.4R | -1609.7R | **-490.3R** | -0.151R | 0.7 | $-78,885 |
| bullish A+ | 562 | 40.6% | +191.5R | -270.8R | **-79.2R** | -0.141R | 0.71 | $-15,355 |
| bullish A | 2578 | 37.7% | +955.2R | -1304.6R | **-349.3R** | -0.136R | 0.73 | $-33,486 |
| bullish Watch | 1435 | 38.4% | +572.1R | -729.3R | **-157.2R** | -0.110R | 0.78 | $-17,873 |
| bearish A+ | 651 | 47.2% | +209.0R | -292.9R | **-83.9R** | -0.129R | 0.71 | $-13,671 |
| bearish A | 2606 | 46.8% | +910.4R | -1316.8R | **-406.4R** | -0.156R | 0.69 | $-65,214 |
| bearish Watch | 1412 | 46.2% | +504.3R | -664.4R | **-160.2R** | -0.113R | 0.76 | $-17,119 |
| exit: t1 | 2947 | 100.0% | +2842.5R | 0.0R | **+2842.5R** | +0.965R | — | $+418,160 |
| exit: stop | 3520 | 0.0% | +0.0R | -3939.8R | **-3939.8R** | -1.119R | 0.0 | $-529,274 |
| exit: engine_end | 2666 | 35.6% | +481.0R | -613.6R | **-132.6R** | -0.050R | 0.78 | $-50,314 |
| exit: eod | 111 | 30.6% | +19.0R | -25.3R | **-6.4R** | -0.057R | 0.75 | $-1,290 |

Not traded: signal on the last bar 3, stop_too_tight 34

## Baselines (same tickers, same window)
- Random entry (8889 samples, seeded): fwd 5: +0.3% · fwd 10: +0.4% · fwd 20: +1.3%
- Buy & hold (1043 tickers): +22.4% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 8303
- Saved capital (hard floor broke first after the stall): 2490
- Cut a winner (T1 was still consumed first): 2647
- Neither within the tracking window: 3166

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
