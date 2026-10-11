# PhaseMap backtest — ASX

Generated 2026-10-11 · ruleset v1.3.1 · universe 1923 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 14696 | +0.8% | +0.9% | +0.9% | 30.2% | 10.0 | -12.6% |
| tier A+ | 1888 | +0.3% | +0.4% | +0.4% | 28.8% | 10.3 | -11.7% |
| tier A | 8234 | +0.7% | +0.8% | +0.7% | 30.1% | 10.3 | -13.2% |
| long | 7254 | +0.9% | +0.9% | +1.0% | 29.4% | 8.7 | -11.3% |
| short | 7442 | +0.7% | +0.8% | +0.7% | 31.0% | 11.2 | -13.9% |
| liquid | 4366 | +1.6% | +1.6% | +2.2% | 40.5% | 9.2 | -8.2% |
| illiquid | 10330 | +0.4% | +0.5% | +0.3% | 25.9% | 10.6 | -14.5% |
| price >= $1 | 4935 | +1.0% | +1.0% | +1.2% | 38.6% | 9.0 | -6.4% |
| cents (<$1) | 9761 | +0.7% | +0.8% | +0.7% | 26.0% | 10.8 | -15.8% |
| in-sample | 10738 | +0.8% | +0.9% | +1.1% | 30.6% | 10.2 | -12.1% |
| out-of-sample | 3958 | +0.9% | +0.7% | +0.3% | 29.2% | 9.4 | -14.2% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 4943 | 39.0% | +1765.5R | -2432.5R | **-667.0R** | -0.135R | 0.73 | $-86,159 |
| long A+/A, stop at the worst print | 4943 | 39.0% | +1765.5R | -2842.0R | **-1076.5R** | -0.218R | 0.62 | $-128,733 |
| long A+/A, engine-native close exits | 4943 | 40.7% | +1839.5R | -2536.3R | **-696.8R** | -0.141R | 0.73 | $-85,699 |
| long A+/A, liquid only | 1274 | 52.0% | +506.1R | -522.6R | **-16.5R** | -0.013R | 0.97 | $-1,764 |
| short A+/A | 5138 | 46.9% | +1806.8R | -2463.3R | **-656.5R** | -0.128R | 0.73 | $-103,327 |
| bullish A+ | 885 | 39.1% | +276.5R | -437.6R | **-161.1R** | -0.182R | 0.63 | $-27,756 |
| bullish A | 4058 | 39.0% | +1489.0R | -1995.0R | **-505.9R** | -0.125R | 0.75 | $-58,404 |
| bullish Watch | 2281 | 39.1% | +890.2R | -1131.0R | **-240.9R** | -0.106R | 0.79 | $-37,841 |
| bearish A+ | 1000 | 45.5% | +315.5R | -469.8R | **-154.2R** | -0.154R | 0.67 | $-21,948 |
| bearish A | 4138 | 47.2% | +1491.3R | -1993.6R | **-502.2R** | -0.121R | 0.75 | $-81,379 |
| bearish Watch | 2267 | 48.4% | +874.4R | -1023.6R | **-149.2R** | -0.066R | 0.85 | $-24,745 |
| exit: t1 | 4696 | 100.0% | +4502.4R | 0.0R | **+4502.4R** | +0.959R | — | $+631,849 |
| exit: stop | 5435 | 0.0% | +0.0R | -6057.3R | **-6057.3R** | -1.114R | 0.0 | $-804,182 |
| exit: engine_end | 4303 | 36.0% | +782.1R | -957.5R | **-175.4R** | -0.041R | 0.82 | $-82,489 |
| exit: eod | 195 | 40.5% | +52.5R | -35.6R | **+16.8R** | +0.086R | 1.47 | $+2,749 |

Not traded: signal on the last bar 14, stop_too_tight 53

## Baselines (same tickers, same window)
- Random entry (14083 samples, seeded): fwd 5: +0.7% · fwd 10: +1.1% · fwd 20: +1.9%
- Buy & hold (1657 tickers): +32.1% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 13060
- Saved capital (hard floor broke first after the stall): 3844
- Cut a winner (T1 was still consumed first): 4127
- Neither within the tracking window: 5089

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
