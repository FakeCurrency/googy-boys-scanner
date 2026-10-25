# PhaseMap backtest — ASX

Generated 2026-10-25 · ruleset v1.3.1 · universe 2049 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 1432 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 10815 | +0.0% | +0.6% | +0.8% | 30.0% | 10.1 | -13.0% |
| tier A+ | 1432 | -0.3% | +0.2% | +1.0% | 29.9% | 10.3 | -11.5% |
| tier A | 6088 | +0.0% | +0.6% | +0.4% | 29.7% | 10.3 | -13.6% |
| long | 5370 | +0.1% | +0.6% | +1.0% | 29.2% | 8.6 | -11.6% |
| short | 5445 | -0.1% | +0.6% | +0.5% | 30.8% | 11.4 | -14.3% |
| liquid | 3094 | +1.1% | +1.6% | +2.1% | 40.6% | 9.3 | -8.4% |
| illiquid | 7721 | -0.4% | +0.2% | +0.2% | 25.8% | 10.5 | -14.8% |
| price >= $1 | 3395 | +0.4% | +0.7% | +0.9% | 37.8% | 8.9 | -6.6% |
| cents (<$1) | 7420 | -0.1% | +0.5% | +0.7% | 26.5% | 10.8 | -15.9% |
| in-sample | 7841 | -0.0% | +0.5% | +1.0% | 30.5% | 10.3 | -12.5% |
| out-of-sample | 2974 | +0.1% | +0.8% | +0.1% | 28.7% | 9.5 | -14.2% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 3691 | 38.1% | +1322.0R | -1838.6R | **-516.6R** | -0.140R | 0.72 | $-64,018 |
| long A+/A, stop at the worst print | 3691 | 38.1% | +1322.0R | -2160.8R | **-838.8R** | -0.227R | 0.61 | $-98,096 |
| long A+/A, engine-native close exits | 3691 | 40.1% | +1380.1R | -1920.9R | **-540.8R** | -0.147R | 0.72 | $-64,245 |
| long A+/A, liquid only | 916 | 50.8% | +345.5R | -391.3R | **-45.8R** | -0.050R | 0.88 | $-4,246 |
| short A+/A | 3804 | 47.3% | +1318.2R | -1831.7R | **-513.5R** | -0.135R | 0.72 | $-81,254 |
| bullish A+ | 662 | 40.2% | +217.4R | -326.0R | **-108.6R** | -0.164R | 0.67 | $-18,814 |
| bullish A | 3029 | 37.7% | +1104.6R | -1512.6R | **-408.0R** | -0.135R | 0.73 | $-45,204 |
| bullish Watch | 1667 | 39.1% | +614.5R | -826.8R | **-212.3R** | -0.127R | 0.74 | $-26,495 |
| bearish A+ | 767 | 47.1% | +250.2R | -342.9R | **-92.7R** | -0.121R | 0.73 | $-14,394 |
| bearish A | 3037 | 47.4% | +1067.9R | -1488.7R | **-420.8R** | -0.139R | 0.72 | $-66,860 |
| bearish Watch | 1613 | 47.6% | +597.2R | -744.5R | **-147.2R** | -0.091R | 0.8 | $-13,818 |
| exit: t1 | 3430 | 100.0% | +3257.9R | 0.0R | **+3257.9R** | +0.950R | — | $+485,968 |
| exit: stop | 4044 | 0.0% | +0.0R | -4501.5R | **-4501.5R** | -1.113R | 0.0 | $-609,960 |
| exit: engine_end | 3161 | 36.0% | +562.9R | -718.5R | **-155.7R** | -0.049R | 0.78 | $-63,292 |
| exit: eod | 140 | 40.7% | +31.1R | -21.5R | **+9.6R** | +0.069R | 1.45 | $+1,699 |

Not traded: signal on the last bar 6, stop_too_tight 34

## Baselines (same tickers, same window)
- Random entry, LONG only (10352 samples, seeded) — compare with the **long** cohort: fwd 5: +1.1% · fwd 10: +1.4% · fwd 20: +4.7%
- Random entry, signed to the signals' own mix (4907 long / 5445 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: +1.0% · fwd 10: +1.2% · fwd 20: +2.5%
- Buy & hold (1228 tickers): +19.6% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 9626
- Saved capital (hard floor broke first after the stall): 2868
- Cut a winner (T1 was still consumed first): 3029
- Neither within the tracking window: 3729

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
