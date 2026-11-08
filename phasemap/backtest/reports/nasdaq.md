# PhaseMap backtest — NASDAQ

Generated 2026-11-08 · ruleset v1.3.1 · universe 1426 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 1468 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12708 | +0.7% | +1.5% | +2.0% | 40.2% | 9.6 | -8.6% |
| tier A+ | 1468 | +0.3% | +0.8% | +1.0% | 39.4% | 9.7 | -8.5% |
| tier A | 7069 | +0.6% | +1.5% | +1.9% | 39.8% | 9.8 | -8.7% |
| long | 5901 | +1.0% | +2.4% | +3.8% | 43.1% | 9.2 | -8.0% |
| short | 6807 | +0.4% | +0.6% | +0.3% | 37.6% | 9.9 | -9.0% |
| liquid | 11744 | +0.7% | +1.5% | +2.0% | 40.9% | 9.6 | -8.6% |
| illiquid | 964 | +0.4% | +0.7% | +1.4% | 31.3% | 9.4 | -7.7% |
| price >= $1 | 12661 | +0.7% | +1.5% | +1.9% | 40.2% | 9.6 | -8.5% |
| cents (<$1) | 47 | +5.0% | +3.2% | +7.7% | 44.7% | 7.0 | -21.1% |
| in-sample | 8916 | +0.8% | +1.8% | +2.4% | 41.6% | 9.7 | -8.4% |
| out-of-sample | 3792 | +0.3% | +0.6% | +0.9% | 36.8% | 9.2 | -9.0% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 4039 | 53.9% | +1698.8R | -1615.7R | **+83.0R** | +0.021R | 1.05 | $+18,512 |
| long A+/A, stop at the worst print | 4039 | 53.9% | +1698.8R | -1915.8R | **-217.0R** | -0.054R | 0.89 | $-8,154 |
| long A+/A, engine-native close exits | 4039 | 56.5% | +1799.5R | -1659.8R | **+139.7R** | +0.035R | 1.08 | $+24,397 |
| long A+/A, liquid only | 3710 | 54.7% | +1564.0R | -1454.7R | **+109.2R** | +0.029R | 1.08 | $+20,234 |
| short A+/A | 4449 | 49.2% | +1665.0R | -2078.4R | **-413.4R** | -0.093R | 0.8 | $-43,473 |
| bullish A+ | 695 | 50.5% | +273.2R | -301.5R | **-28.3R** | -0.041R | 0.91 | $-258 |
| bullish A | 3344 | 54.6% | +1425.5R | -1314.2R | **+111.3R** | +0.033R | 1.08 | $+18,770 |
| bullish Watch | 1836 | 56.4% | +798.9R | -723.1R | **+75.8R** | +0.041R | 1.1 | $+12,884 |
| bearish A+ | 772 | 45.9% | +255.5R | -381.4R | **-125.8R** | -0.163R | 0.67 | $-9,853 |
| bearish A | 3677 | 49.9% | +1409.5R | -1697.1R | **-287.6R** | -0.078R | 0.83 | $-33,620 |
| bearish Watch | 2309 | 49.2% | +873.8R | -1040.5R | **-166.6R** | -0.072R | 0.84 | $-15,340 |
| exit: t1 | 5316 | 100.0% | +4441.4R | 0.0R | **+4441.4R** | +0.835R | — | $+484,970 |
| exit: stop | 4505 | 0.0% | +0.0R | -4861.8R | **-4861.8R** | -1.079R | 0.0 | $-493,143 |
| exit: engine_end | 2554 | 42.7% | +550.8R | -566.6R | **-15.8R** | -0.006R | 0.97 | $-21,036 |
| exit: eod | 258 | 50.0% | +44.2R | -29.4R | **+14.9R** | +0.058R | 1.51 | $+1,793 |

Not traded: signal on the last bar 19, stop_too_tight 56

## Baselines (same tickers, same window)
- Random entry, LONG only (11805 samples, seeded) — compare with the **long** cohort: fwd 5: +0.7% · fwd 10: +1.1% · fwd 20: +2.3%
- Random entry, signed to the signals' own mix (4998 long / 6807 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: -0.4% · fwd 10: -0.4% · fwd 20: -0.9%
- Buy & hold (1329 tickers): +73.2% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11397
- Saved capital (hard floor broke first after the stall): 3453
- Cut a winner (T1 was still consumed first): 4664
- Neither within the tracking window: 3280

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
