# PhaseMap backtest — NASDAQ

Generated 2026-10-25 · ruleset v1.3.1 · universe 1425 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 1455 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12499 | +0.7% | +1.6% | +2.0% | 40.7% | 9.6 | -8.6% |
| tier A+ | 1455 | +0.4% | +1.1% | +1.0% | 39.3% | 9.6 | -8.4% |
| tier A | 6978 | +0.7% | +1.5% | +2.0% | 40.3% | 9.9 | -8.7% |
| long | 5846 | +1.1% | +2.4% | +3.8% | 43.0% | 9.3 | -7.9% |
| short | 6653 | +0.4% | +0.8% | +0.4% | 38.6% | 9.9 | -9.2% |
| liquid | 11523 | +0.7% | +1.6% | +2.0% | 41.4% | 9.6 | -8.7% |
| illiquid | 976 | +0.5% | +0.8% | +1.4% | 31.6% | 9.7 | -7.6% |
| price >= $1 | 12453 | +0.7% | +1.5% | +2.0% | 40.6% | 9.6 | -8.5% |
| cents (<$1) | 46 | +5.4% | +3.7% | +8.4% | 45.7% | 7.0 | -21.2% |
| in-sample | 9008 | +0.9% | +1.9% | +2.4% | 41.8% | 9.7 | -8.3% |
| out-of-sample | 3491 | +0.4% | +0.7% | +0.9% | 37.6% | 9.3 | -9.2% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 4002 | 54.0% | +1680.1R | -1597.0R | **+83.1R** | +0.021R | 1.05 | $+19,118 |
| long A+/A, stop at the worst print | 4002 | 54.0% | +1680.1R | -1893.9R | **-213.8R** | -0.053R | 0.89 | $-7,154 |
| long A+/A, engine-native close exits | 4002 | 56.7% | +1780.8R | -1637.7R | **+143.1R** | +0.036R | 1.09 | $+25,499 |
| long A+/A, liquid only | 3675 | 54.8% | +1539.5R | -1439.8R | **+99.7R** | +0.027R | 1.07 | $+20,134 |
| short A+/A | 4388 | 49.2% | +1671.9R | -2067.1R | **-395.2R** | -0.090R | 0.81 | $-40,831 |
| bullish A+ | 682 | 50.4% | +267.7R | -295.6R | **-27.9R** | -0.041R | 0.91 | $-621 |
| bullish A | 3320 | 54.8% | +1412.4R | -1301.4R | **+111.0R** | +0.033R | 1.09 | $+19,739 |
| bullish Watch | 1826 | 56.2% | +790.2R | -716.7R | **+73.5R** | +0.040R | 1.1 | $+13,562 |
| bearish A+ | 772 | 46.1% | +256.2R | -368.4R | **-112.2R** | -0.145R | 0.7 | $-8,742 |
| bearish A | 3616 | 49.8% | +1415.7R | -1698.7R | **-283.0R** | -0.078R | 0.83 | $-32,088 |
| bearish Watch | 2217 | 49.2% | +847.6R | -1012.7R | **-165.1R** | -0.074R | 0.84 | $-15,396 |
| exit: t1 | 5300 | 100.0% | +4421.9R | 0.0R | **+4421.9R** | +0.834R | — | $+483,034 |
| exit: stop | 4452 | 0.0% | +0.0R | -4795.9R | **-4795.9R** | -1.077R | 0.0 | $-484,514 |
| exit: engine_end | 2549 | 42.6% | +549.8R | -563.7R | **-13.9R** | -0.005R | 0.98 | $-20,661 |
| exit: eod | 132 | 38.6% | +18.1R | -34.0R | **-15.8R** | -0.120R | 0.53 | $-1,405 |

Not traded: signal on the last bar 14, stop_too_tight 52

## Baselines (same tickers, same window)
- Random entry, LONG only (11597 samples, seeded) — compare with the **long** cohort: fwd 5: +0.6% · fwd 10: +1.1% · fwd 20: +2.0%
- Random entry, signed to the signals' own mix (4944 long / 6653 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: -0.1% · fwd 10: -0.1% · fwd 20: -0.5%
- Buy & hold (1328 tickers): +86.0% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11275
- Saved capital (hard floor broke first after the stall): 3419
- Cut a winner (T1 was still consumed first): 4626
- Neither within the tracking window: 3230

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
