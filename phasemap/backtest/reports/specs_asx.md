# Specs backtest — ASX

Generated 2026-10-11 · engine scanner/spec.py (restored 2026-07-02) · universe 1923 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 9079 | -1.1% | -1.2% | -1.1% | 30.0% | 30.7% | 39.3% | -17.4% |
| grade A+ | 6509 | -0.8% | -0.7% | -0.7% | 28.2% | 30.0% | 41.8% | -17.6% |
| grade A | 2325 | -2.1% | -2.3% | -2.2% | 33.9% | 33.0% | 33.1% | -17.0% |
| grade B | 245 | -2.0% | -2.1% | -0.8% | 39.2% | 27.3% | 33.5% | -16.8% |

## R model — what trading the signals earned

Entry at the signal close, the engine's stop, its one target booked in full (resting limit), stop gap-aware, closed at the close after 40 bars if neither; house costs; a stop under the house minimum is not a trade. Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | net $ |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 9068 | 41.3% | +3744.6R | -4438.4R | **-693.8R** | -0.077R | $-193,263 |
| ALL SIGNALS, stop at the worst print | 9068 | 41.3% | +3744.6R | -5026.9R | **-1282.3R** | -0.141R | $-299,636 |
| grade A+ | 6500 | 40.8% | +2767.7R | -3171.8R | **-404.0R** | -0.062R | $-116,942 |
| grade A | 2323 | 42.6% | +897.9R | -1157.2R | **-259.3R** | -0.112R | $-69,758 |
| grade B | 245 | 44.1% | +78.9R | -109.5R | **-30.6R** | -0.125R | $-6,563 |

## Baseline
- Random entry on the same sub-$0.50 universe (9079 samples, seeded): fwd 5: +0.3% · fwd 10: +0.5% · fwd 20: +2.4%

Analysis only — not financial advice.
