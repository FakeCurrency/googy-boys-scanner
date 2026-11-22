# PhaseMap backtest — CRYPTO

Generated 2026-11-22 · ruleset v1.3.1 · universe 201 tickers · history period 5y · zero-lookahead replay through the production SetupEngine.

> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance prototype feed, which has NO delisted-stock history. Every statistic below is computed on survivors only and is therefore optimistic. Do not publish these numbers; re-run on a provider with delisted data (Norgate/EODHD) first.

A **signal** is a displacement confirmation (state DISPLACED). Forward returns are measured from the FILL, counted from the session it filled: the entry-zone midpoint when price traded back through it within 20 sessions, otherwise the signal-bar close (a gapper nobody could buy at the mid). "T1 hit" means the first target zone was CONSUMED within 20 sessions before any hard invalidation.

Tier = the tier a card wears from its first RUNNING session. Anchor context (the A+ condition) is evaluated from the bar after displacement, so the displacement-day card shows A or Watch: 0 of 263 A+ signals showed A+ on that day's card.

| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1886 | -77.7% | -49.2% | +41.6% | 43.9% | 8.6 | -113.1% |
| tier A+ | 263 | +1.7% | +6.2% | +61.8% | 46.0% | 7.9 | -25.2% |
| tier A | 1185 | -124.5% | -125.0% | +7.9% | 44.6% | 8.9 | -168.3% |
| long | 1023 | +2.1% | +55.4% | +223.8% | 46.4% | 7.3 | -13.6% |
| short | 863 | -172.5% | -173.4% | -172.9% | 40.9% | 10.3 | -230.8% |
| liquid | 1603 | +2.1% | +2.3% | +3.6% | 45.2% | 8.4 | -14.4% |
| illiquid | 283 | -528.7% | -339.4% | +256.6% | 36.4% | 9.7 | -671.6% |
| price >= $1 | 874 | +2.2% | +2.3% | +3.8% | 46.0% | 8.5 | -12.9% |
| cents (<$1) | 1012 | -146.8% | -93.8% | +74.3% | 42.1% | 8.8 | -199.6% |
| in-sample | 1226 | -120.6% | -77.1% | +60.9% | 44.2% | 9.0 | -154.8% |
| out-of-sample | 660 | +2.6% | +3.1% | +4.6% | 43.3% | 7.9 | -35.4% |

## R model — what trading the signals earned

Entry = signal close; risk = entry to the INVALIDATION_HARD floor; house fill: the floor is a resting stop (filled at the floor or a gapped open); T1 consumed and the engine dropping the setup exit at that close; end of data marks at the last close; house costs, both legs market fills; second column: stops at the bar's worst print; reference: engine-native close-only exits (DEAD = a close through the floor). Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | PF | net $ |
|---|---|---|---|---|---|---|---|---|
| **long A+/A (headline)** | 762 | 55.6% | +620.5R | -294.7R | **+325.8R** | +0.428R | 2.11 | $+153,407 |
| long A+/A, stop at the worst print | 762 | 55.6% | +620.5R | -362.4R | **+258.1R** | +0.339R | 1.71 | $+144,458 |
| long A+/A, engine-native close exits | 762 | 57.3% | +632.1R | -318.2R | **+313.9R** | +0.412R | 1.99 | $+152,813 |
| long A+/A, liquid only | 636 | 56.4% | +309.4R | -243.7R | **+65.7R** | +0.103R | 1.27 | $+7,851 |
| short A+/A | 685 | 54.7% | +260.2R | -280.4R | **-20.2R** | -0.029R | 0.93 | $-729,777 |
| bullish A+ | 135 | 54.8% | +290.6R | -54.6R | **+236.0R** | +1.748R | 5.33 | $+144,471 |
| bullish A | 627 | 55.8% | +329.9R | -240.1R | **+89.8R** | +0.143R | 1.37 | $+8,936 |
| bullish Watch | 260 | 45.4% | +2880.5R | -121.2R | **+2759.2R** | +10.612R | 23.76 | $+422,796 |
| bearish A+ | 128 | 58.6% | +52.1R | -45.6R | **+6.5R** | +0.051R | 1.14 | $+251 |
| bearish A | 557 | 53.9% | +208.1R | -234.8R | **-26.7R** | -0.048R | 0.89 | $-730,028 |
| bearish Watch | 178 | 59.6% | +77.6R | -61.1R | **+16.5R** | +0.093R | 1.27 | $+724 |
| exit: t1 | 868 | 100.0% | +3769.4R | 0.0R | **+3769.4R** | +4.343R | — | $+696,352 |
| exit: stop | 653 | 0.0% | +0.0R | -670.8R | **-670.8R** | -1.027R | 0.0 | $-838,535 |
| exit: engine_end | 356 | 42.1% | +68.4R | -85.8R | **-17.5R** | -0.049R | 0.8 | $-11,637 |
| exit: eod | 8 | 62.5% | +1.0R | -0.8R | **+0.3R** | +0.032R | 1.34 | $+971 |

Not traded: signal on the last bar 1

## Baselines (same tickers, same window)
- Random entry, LONG only (1746 samples, seeded) — compare with the **long** cohort: fwd 5: +640.8% · fwd 10: +528.8% · fwd 20: +47075.7%
- Random entry, signed to the signals' own mix (883 long / 863 short) — compare with **ALL SIGNALS**, which pools longs with direction-signed shorts: fwd 5: -608.0% · fwd 10: -501.7% · fwd 20: +47057.4%
- Buy & hold (136 tickers): +2662.2% mean total return over the replay window

## The 50% rule, measured
- Signals that stalled (momentum zone touched): 1754
- Saved capital (hard floor broke first after the stall): 528
- Cut a winner (T1 was still consumed first): 792
- Neither within the tracking window: 434

In-sample = signals before 2025-07-01; out-of-sample = after. If a cohort doesn't beat the baselines out-of-sample, the spec says cut it and note it here.

Analysis only — not financial advice.
