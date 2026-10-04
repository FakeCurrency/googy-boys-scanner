# Specs backtest — ASX

Generated 2026-10-04 · engine scanner/spec.py (restored 2026-07-02) · universe 2048 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 874 | -1.1% | -1.4% | -0.5% | 30.7% | 29.4% | 39.9% | -17.5% |
| grade A+ | 623 | -0.5% | -0.4% | +1.0% | 29.2% | 29.1% | 41.7% | -17.1% |
| grade A | 233 | -2.7% | -4.1% | -4.4% | 33.5% | 30.9% | 35.6% | -18.4% |
| grade B | 18 | -2.7% | -2.1% | -4.5% | 44.4% | 22.2% | 33.3% | -18.1% |

## R model — what trading the signals earned

Entry at the signal close, the engine's stop, its one target booked in full (resting limit), stop gap-aware, closed at the close after 40 bars if neither; house costs; a stop under the house minimum is not a trade. Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | net $ |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 873 | 41.8% | +404.0R | -396.3R | **+7.7R** | +0.009R | $-4,412 |
| ALL SIGNALS, stop at the worst print | 873 | 41.8% | +404.0R | -453.2R | **-49.2R** | -0.056R | $-15,972 |
| grade A+ | 622 | 41.3% | +310.6R | -281.1R | **+29.5R** | +0.047R | $+4,015 |
| grade A | 233 | 42.5% | +87.8R | -108.5R | **-20.7R** | -0.089R | $-8,093 |
| grade B | 18 | 50.0% | +5.6R | -6.7R | **-1.1R** | -0.062R | $-333 |

## Baseline
- Random entry on the same sub-$0.50 universe (874 samples, seeded): fwd 5: -0.1% · fwd 10: +0.6% · fwd 20: +0.9%

Analysis only — not financial advice.
