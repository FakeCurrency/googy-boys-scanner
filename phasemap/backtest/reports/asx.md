# PhaseMap backtest — ASX

Generated 2026-11-08 · ruleset v1.3.1 · universe 2060 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 1221 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 9491 | +0.0% | +0.6% | +0.9% | 30.1% | 10.2 | -13.0% |
| tier A+ | 1221 | -0.1% | +0.1% | +0.9% | 30.3% | 10.0 | -11.5% |
| tier A | 5312 | -0.0% | +0.6% | +0.7% | 29.9% | 10.5 | -13.5% |
| long | 4734 | +0.0% | +0.4% | +0.8% | 29.3% | 8.8 | -11.8% |
| short | 4757 | -0.0% | +0.7% | +1.1% | 30.9% | 11.5 | -14.1% |
| liquid | 2653 | +1.1% | +1.6% | +2.4% | 40.8% | 9.4 | -8.5% |
| illiquid | 6838 | -0.4% | +0.1% | +0.4% | 26.0% | 10.7 | -14.7% |
| price >= $1 | 2841 | +0.4% | +0.8% | +1.1% | 38.4% | 9.1 | -6.7% |
| cents (<$1) | 6650 | -0.1% | +0.5% | +0.8% | 26.6% | 10.9 | -15.7% |
| in-sample | 6765 | -0.0% | +0.5% | +1.0% | 30.6% | 10.4 | -12.8% |
| out-of-sample | 2726 | +0.1% | +0.7% | +0.7% | 28.9% | 9.8 | -13.4% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 3218 | 38.3% | +1198.4R | -1598.4R | **-399.9R** | -0.124R | 0.75 | $-56,806 |
| long A+/A, stop at the worst print | 3218 | 38.3% | +1198.4R | -1876.8R | **-678.3R** | -0.211R | 0.64 | $-87,249 |
| long A+/A, engine-native close exits | 3218 | 40.2% | +1246.3R | -1680.9R | **-434.6R** | -0.135R | 0.74 | $-58,703 |
| long A+/A, liquid only | 772 | 52.1% | +307.5R | -311.2R | **-3.7R** | -0.005R | 0.99 | $-1,195 |
| short A+/A | 3288 | 47.1% | +1144.1R | -1590.4R | **-446.2R** | -0.136R | 0.72 | $-69,013 |
| bullish A+ | 558 | 40.7% | +202.5R | -267.5R | **-65.0R** | -0.116R | 0.76 | $-15,386 |
| bullish A | 2660 | 37.8% | +995.9R | -1330.9R | **-335.0R** | -0.126R | 0.75 | $-41,420 |
| bullish Watch | 1501 | 37.8% | +586.2R | -762.9R | **-176.7R** | -0.118R | 0.77 | $-25,963 |
| bearish A+ | 660 | 46.4% | +206.7R | -292.2R | **-85.5R** | -0.130R | 0.71 | $-12,539 |
| bearish A | 2628 | 47.3% | +937.4R | -1298.2R | **-360.8R** | -0.137R | 0.72 | $-56,474 |
| bearish Watch | 1442 | 47.9% | +536.1R | -655.3R | **-119.2R** | -0.083R | 0.82 | $-10,541 |
| exit: t1 | 3029 | 100.0% | +2952.0R | 0.0R | **+2952.0R** | +0.975R | — | $+443,093 |
| exit: stop | 3533 | 0.0% | +0.0R | -3946.0R | **-3946.0R** | -1.117R | 0.0 | $-547,306 |
| exit: engine_end | 2758 | 35.2% | +489.8R | -632.7R | **-142.9R** | -0.052R | 0.77 | $-57,808 |
| exit: eod | 129 | 29.5% | +23.1R | -28.3R | **-5.2R** | -0.040R | 0.82 | $-302 |

Not traded: signal on the last bar 6, stop_too_tight 36

## Baselines (same tickers, same window)
- Random entry, LONG only (9133 samples, seeded) — compare with the **long** cohort: fwd 5: +0.1% · fwd 10: +0.9% · fwd 20: +0.4%
- Random entry, signed to the signals' own mix (4376 long / 4757 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: -0.1% · fwd 10: +0.5% · fwd 20: +0.3%
- Buy & hold (1084 tickers): +12.8% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 8432
- Saved capital (hard floor broke first after the stall): 2504
- Cut a winner (T1 was still consumed first): 2666
- Neither within the tracking window: 3262

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
