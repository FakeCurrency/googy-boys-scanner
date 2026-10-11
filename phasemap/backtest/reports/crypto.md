# PhaseMap backtest — CRYPTO

Generated 2026-10-11 · ruleset v1.3.1 · universe 201 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the entry-zone midpoint; "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1880 | +2.7% | +31.7% | -50.1% | 44.0% | 8.4 | -113.5% |
| tier A+ | 251 | +1.3% | +5.0% | +64.4% | 47.8% | 7.9 | -25.4% |
| tier A | 1196 | +3.2% | +2.8% | -136.4% | 44.5% | 8.6 | -166.9% |
| long | 1014 | +3.2% | +56.6% | +70.9% | 46.4% | 7.3 | -13.5% |
| short | 866 | +2.2% | +2.3% | -196.3% | 41.2% | 9.9 | -230.4% |
| liquid | 1634 | +3.1% | +3.0% | +4.0% | 45.1% | 8.3 | -14.5% |
| illiquid | 246 | -0.1% | +221.6% | -404.9% | 37.0% | 9.2 | -770.5% |
| price >= $1 | 854 | +3.3% | +2.9% | +3.3% | 45.7% | 8.3 | -12.9% |
| cents (<$1) | 1026 | +2.2% | +55.7% | -95.2% | 42.7% | 8.5 | -197.3% |
| in-sample | 1264 | +2.3% | +45.4% | -74.7% | 43.7% | 8.9 | -151.0% |
| out-of-sample | 616 | +3.6% | +3.2% | +4.3% | 44.8% | 7.6 | -36.5% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 759 | 55.7% | +621.6R | -290.0R | **+331.6R** | +0.437R | 2.14 | $+152,443 |
| long A+/A, stop at the worst print | 759 | 55.7% | +621.6R | -361.1R | **+260.6R** | +0.343R | 1.72 | $+143,025 |
| long A+/A, engine-native close exits | 759 | 57.3% | +632.7R | -318.2R | **+314.5R** | +0.414R | 1.99 | $+151,332 |
| long A+/A, liquid only | 653 | 56.7% | +318.3R | -245.1R | **+73.2R** | +0.112R | 1.3 | $+8,339 |
| short A+/A | 687 | 53.7% | +259.5R | -282.8R | **-23.3R** | -0.034R | 0.92 | $-731,916 |
| bullish A+ | 124 | 58.9% | +291.9R | -45.9R | **+246.1R** | +1.984R | 6.36 | $+145,857 |
| bullish A | 635 | 55.1% | +329.7R | -244.2R | **+85.6R** | +0.135R | 1.35 | $+6,586 |
| bullish Watch | 254 | 45.3% | +2879.7R | -114.3R | **+2765.4R** | +10.888R | 25.2 | $+422,982 |
| bearish A+ | 126 | 55.6% | +51.1R | -49.2R | **+1.9R** | +0.015R | 1.04 | $-1,811 |
| bearish A | 561 | 53.3% | +208.3R | -233.6R | **-25.2R** | -0.045R | 0.89 | $-730,105 |
| bearish Watch | 179 | 58.1% | +81.2R | -64.7R | **+16.5R** | +0.092R | 1.25 | $+860 |
| exit: t1 | 866 | 100.0% | +3773.0R | 0.0R | **+3773.0R** | +4.357R | — | $+697,539 |
| exit: stop | 644 | 0.0% | +0.0R | -661.1R | **-661.1R** | -1.026R | 0.0 | $-839,933 |
| exit: engine_end | 351 | 40.7% | +68.4R | -86.2R | **-17.8R** | -0.051R | 0.79 | $-12,463 |
| exit: eod | 18 | 11.1% | +0.7R | -4.6R | **-4.0R** | -0.220R | 0.14 | $-775 |

Not traded: signal on the last bar 1

## Baselines (same tickers, same window)
- Random entry (1792 samples, seeded): fwd 5: +1770.1% · fwd 10: +499.0% · fwd 20: +46.1%
- Buy & hold (137 tickers): +3001.4% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 1750
- Saved capital (hard floor broke first after the stall): 528
- Cut a winner (T1 was still consumed first): 786
- Neither within the tracking window: 436

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
