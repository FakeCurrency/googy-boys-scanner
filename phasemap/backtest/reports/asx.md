# PhaseMap backtest — ASX

Generated 2026-10-18 · ruleset v1.3.1 · universe 2051 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 1607 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 12853 | +0.1% | +0.7% | +1.0% | 30.1% | 10.1 | -13.0% |
| tier A+ | 1607 | -0.1% | +0.3% | +1.2% | 30.2% | 10.3 | -11.5% |
| tier A | 7257 | +0.1% | +0.8% | +0.7% | 30.0% | 10.3 | -13.5% |
| long | 6367 | +0.1% | +0.5% | +1.0% | 29.0% | 8.7 | -11.7% |
| short | 6486 | +0.1% | +0.8% | +0.9% | 31.1% | 11.3 | -14.1% |
| liquid | 3709 | +1.0% | +1.6% | +2.2% | 40.8% | 9.2 | -8.3% |
| illiquid | 9144 | -0.3% | +0.3% | +0.5% | 25.7% | 10.7 | -14.8% |
| price >= $1 | 4027 | +0.5% | +0.8% | +1.0% | 38.2% | 9.0 | -6.6% |
| cents (<$1) | 8826 | -0.1% | +0.6% | +0.9% | 26.3% | 10.8 | -15.9% |
| in-sample | 9356 | +0.1% | +0.7% | +1.2% | 30.5% | 10.3 | -12.5% |
| out-of-sample | 3497 | -0.0% | +0.6% | +0.3% | 28.9% | 9.7 | -14.1% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 4335 | 38.4% | +1565.5R | -2164.1R | **-598.6R** | -0.138R | 0.72 | $-79,491 |
| long A+/A, stop at the worst print | 4335 | 38.4% | +1565.5R | -2526.1R | **-960.5R** | -0.222R | 0.62 | $-119,004 |
| long A+/A, engine-native close exits | 4335 | 40.3% | +1638.7R | -2255.8R | **-617.1R** | -0.142R | 0.73 | $-79,172 |
| long A+/A, liquid only | 1072 | 51.5% | +420.2R | -442.5R | **-22.4R** | -0.021R | 0.95 | $-2,814 |
| short A+/A | 4497 | 47.6% | +1624.3R | -2123.8R | **-499.5R** | -0.111R | 0.76 | $-84,029 |
| bullish A+ | 758 | 40.8% | +257.7R | -363.0R | **-105.3R** | -0.139R | 0.71 | $-20,090 |
| bullish A | 3577 | 37.9% | +1307.8R | -1801.1R | **-493.3R** | -0.138R | 0.73 | $-59,401 |
| bullish Watch | 2008 | 38.1% | +748.1R | -1014.6R | **-266.5R** | -0.133R | 0.74 | $-38,877 |
| bearish A+ | 846 | 47.2% | +280.2R | -377.4R | **-97.2R** | -0.115R | 0.74 | $-16,278 |
| bearish A | 3651 | 47.7% | +1344.0R | -1746.4R | **-402.3R** | -0.110R | 0.77 | $-67,751 |
| bearish Watch | 1958 | 47.6% | +737.0R | -890.9R | **-153.9R** | -0.079R | 0.83 | $-18,873 |
| exit: t1 | 4080 | 100.0% | +3918.1R | 0.0R | **+3918.1R** | +0.960R | — | $+577,978 |
| exit: stop | 4767 | 0.0% | +0.0R | -5310.6R | **-5310.6R** | -1.114R | 0.0 | $-725,648 |
| exit: engine_end | 3791 | 36.0% | +713.1R | -854.5R | **-141.4R** | -0.037R | 0.83 | $-75,340 |
| exit: eod | 160 | 34.4% | +43.6R | -28.2R | **+15.4R** | +0.096R | 1.54 | $+1,739 |

Not traded: signal on the last bar 12, stop_too_tight 43

## Baselines (same tickers, same window)
- Random entry, LONG only (12326 samples, seeded) — compare with the **long** cohort: fwd 5: +0.4% · fwd 10: +1.0% · fwd 20: +2.7%
- Random entry, signed to the signals' own mix (5840 long / 6486 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: +0.3% · fwd 10: +0.1% · fwd 20: +1.3%
- Buy & hold (1468 tickers): +19.8% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 11421
- Saved capital (hard floor broke first after the stall): 3364
- Cut a winner (T1 was still consumed first): 3589
- Neither within the tracking window: 4468

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
