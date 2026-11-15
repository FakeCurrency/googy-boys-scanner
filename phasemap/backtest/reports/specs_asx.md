# Specs backtest — ASX

Generated 2026-11-15 · engine scanner/spec.py (restored 2026-07-02) · universe 2061 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1921 | -1.7% | -1.7% | -1.6% | 30.3% | 31.3% | 38.4% | -18.0% |
| grade A+ | 715 | +0.0% | +0.1% | -0.1% | 14.3% | 30.9% | 54.8% | -16.7% |
| grade A | 141 | -1.7% | -2.9% | -0.3% | 9.9% | 40.4% | 49.6% | -17.2% |
| grade B | 1065 | -2.9% | -2.7% | -2.8% | 43.8% | 30.3% | 25.8% | -18.9% |

## R model — what trading the signals earned

Entry at the signal close, the engine's stop, its one target booked in full (resting limit), stop gap-aware, closed at the close after 40 bars if neither; house costs; a stop under the house minimum is not a trade. Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | net $ |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1920 | 40.9% | +805.2R | -954.4R | **-149.2R** | -0.078R | $-51,821 |
| ALL SIGNALS, stop at the worst print | 1920 | 40.9% | +805.2R | -1091.0R | **-285.8R** | -0.149R | $-74,476 |
| grade A+ | 714 | 35.2% | +415.0R | -371.2R | **+43.8R** | +0.061R | $+2,760 |
| grade A | 141 | 31.9% | +77.1R | -88.4R | **-11.3R** | -0.080R | $-5,152 |
| grade B | 1065 | 45.9% | +313.2R | -494.9R | **-181.7R** | -0.171R | $-49,429 |

## Baseline
- Random entry on the same sub-$0.50 universe (1921 samples, seeded): fwd 5: +0.9% · fwd 10: +1.6% · fwd 20: +1.6%

Analysis only — not financial advice.
