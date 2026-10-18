# PhaseMap backtest — NASDAQ

Generated 2026-10-18 · ruleset v1.3.1 · universe 1429 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 1472 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12499 | +0.7% | +1.5% | +2.0% | 40.6% | 9.6 | -8.6% |
| tier A+ | 1472 | +0.4% | +1.0% | +1.0% | 39.6% | 9.6 | -8.5% |
| tier A | 6960 | +0.7% | +1.5% | +1.9% | 40.2% | 9.9 | -8.7% |
| long | 5840 | +1.1% | +2.4% | +3.8% | 42.8% | 9.2 | -8.0% |
| short | 6659 | +0.4% | +0.8% | +0.4% | 38.6% | 10.0 | -9.2% |
| liquid | 11519 | +0.8% | +1.6% | +2.0% | 41.4% | 9.6 | -8.7% |
| illiquid | 980 | +0.4% | +0.7% | +1.4% | 31.1% | 9.8 | -7.8% |
| price >= $1 | 12445 | +0.7% | +1.5% | +2.0% | 40.5% | 9.6 | -8.5% |
| cents (<$1) | 54 | +3.9% | +1.7% | +5.6% | 48.1% | 6.9 | -23.5% |
| in-sample | 9061 | +0.9% | +1.8% | +2.4% | 41.7% | 9.7 | -8.3% |
| out-of-sample | 3438 | +0.4% | +0.6% | +0.9% | 37.7% | 9.3 | -9.3% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 4002 | 53.7% | +1671.1R | -1603.4R | **+67.7R** | +0.017R | 1.04 | $+17,332 |
| long A+/A, stop at the worst print | 4002 | 53.7% | +1671.1R | -1899.4R | **-228.3R** | -0.057R | 0.88 | $-8,944 |
| long A+/A, engine-native close exits | 4002 | 56.3% | +1771.8R | -1640.3R | **+131.4R** | +0.033R | 1.08 | $+23,921 |
| long A+/A, liquid only | 3673 | 54.5% | +1535.6R | -1446.3R | **+89.3R** | +0.024R | 1.06 | $+18,196 |
| short A+/A | 4376 | 49.7% | +1688.7R | -2049.0R | **-360.4R** | -0.082R | 0.82 | $-37,270 |
| bullish A+ | 693 | 50.8% | +276.1R | -299.1R | **-22.9R** | -0.033R | 0.92 | $-70 |
| bullish A | 3309 | 54.3% | +1395.0R | -1304.3R | **+90.6R** | +0.027R | 1.07 | $+17,402 |
| bullish Watch | 1825 | 56.0% | +786.7R | -719.7R | **+67.0R** | +0.037R | 1.09 | $+13,371 |
| bearish A+ | 776 | 46.8% | +260.4R | -370.5R | **-110.1R** | -0.142R | 0.7 | $-7,719 |
| bearish A | 3600 | 50.3% | +1428.2R | -1678.5R | **-250.3R** | -0.070R | 0.85 | $-29,551 |
| bearish Watch | 2220 | 48.9% | +848.0R | -1021.4R | **-173.4R** | -0.078R | 0.83 | $-15,270 |
| exit: t1 | 5292 | 100.0% | +4417.5R | 0.0R | **+4417.5R** | +0.835R | — | $+485,126 |
| exit: stop | 4449 | 0.0% | +0.0R | -4797.3R | **-4797.3R** | -1.078R | 0.0 | $-486,370 |
| exit: engine_end | 2558 | 42.6% | +554.2R | -567.6R | **-13.4R** | -0.005R | 0.98 | $-21,473 |
| exit: eod | 124 | 40.3% | +22.7R | -28.7R | **-6.0R** | -0.048R | 0.79 | $+880 |

Not traded: signal on the last bar 24, stop_too_tight 52

## Baselines (same tickers, same window)
- Random entry, LONG only (11640 samples, seeded) — compare with the **long** cohort: fwd 5: +0.4% · fwd 10: +0.8% · fwd 20: +1.6%
- Random entry, signed to the signals' own mix (4981 long / 6659 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: -0.0% · fwd 10: -0.1% · fwd 20: -0.1%
- Buy & hold (1331 tickers): +83.4% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11274
- Saved capital (hard floor broke first after the stall): 3405
- Cut a winner (T1 was still consumed first): 4633
- Neither within the tracking window: 3236

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
