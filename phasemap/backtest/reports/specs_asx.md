# Specs backtest — ASX

Generated 2026-10-18 · engine scanner/spec.py (restored 2026-07-02) · universe 2051 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 2420 | -0.8% | -1.0% | -0.4% | 30.0% | 30.9% | 39.2% | -18.0% |
| grade A+ | 886 | +1.1% | +1.4% | +2.3% | 13.0% | 30.6% | 56.4% | -16.5% |
| grade A | 184 | -0.7% | -1.0% | +1.8% | 17.4% | 35.3% | 47.3% | -15.2% |
| grade B | 1350 | -2.1% | -2.6% | -2.4% | 42.8% | 30.4% | 26.7% | -19.3% |

## R model — what trading the signals earned

Entry at the signal close, the engine's stop, its one target booked in full (resting limit), stop gap-aware, closed at the close after 40 bars if neither; house costs; a stop under the house minimum is not a trade. Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | net $ |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 2420 | 40.8% | +976.0R | -1208.7R | **-232.8R** | -0.096R | $-64,998 |
| ALL SIGNALS, stop at the worst print | 2420 | 40.8% | +976.0R | -1367.9R | **-391.9R** | -0.162R | $-95,831 |
| grade A+ | 886 | 35.0% | +479.4R | -470.5R | **+8.9R** | +0.010R | $+3,839 |
| grade A | 184 | 39.1% | +119.7R | -105.8R | **+13.9R** | +0.075R | $-262 |
| grade B | 1350 | 44.9% | +376.9R | -632.4R | **-255.5R** | -0.189R | $-68,574 |

## Baseline
- Random entry on the same sub-$0.50 universe (2420 samples, seeded): fwd 5: +0.7% · fwd 10: +1.0% · fwd 20: +1.2%

Analysis only — not financial advice.
