# Specs backtest — NASDAQ

Generated 2026-10-25 · engine scanner/spec.py (restored 2026-07-02) · universe 1425 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 5 | +4.7% | +1.3% | +11.3% | 40.0% | 20.0% | 40.0% | -17.8% |
| grade A+ | 3 | +5.2% | +11.4% | +32.8% | 33.3% | 0.0% | 66.7% | -12.0% |
| grade B | 2 | +3.9% | -13.8% | -21.0% | 50.0% | 50.0% | 0.0% | -26.6% |

## R model — what trading the signals earned

Entry at the signal close, the engine's stop, its one target booked in full (resting limit), stop gap-aware, closed at the close after 40 bars if neither; house costs; a stop under the house minimum is not a trade. Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | net $ |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 5 | 80.0% | +4.7R | -1.0R | **+3.7R** | +0.734R | $+1,134 |
| ALL SIGNALS, stop at the worst print | 5 | 80.0% | +4.7R | -1.1R | **+3.6R** | +0.714R | $+1,114 |
| grade A+ | 3 | 100.0% | +3.9R | 0.0R | **+3.9R** | +1.305R | $+1,158 |
| grade B | 2 | 50.0% | +0.8R | -1.0R | **-0.2R** | -0.122R | $-24 |

## Baseline
- Random entry on the same sub-$0.50 universe (200 samples, seeded): fwd 5: +56.7% · fwd 10: +29.8% · fwd 20: +32.1%

Analysis only — not financial advice.
