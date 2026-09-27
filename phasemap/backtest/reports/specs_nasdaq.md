# Specs backtest — NASDAQ

Generated 2026-09-27 · engine scanner/spec.py (restored 2026-07-02) · universe 1429 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 10 | -6.5% | -9.4% | -1.6% | 20.0% | 30.0% | 50.0% | -35.8% |
| grade A+ | 10 | -6.5% | -9.4% | -1.6% | 20.0% | 30.0% | 50.0% | -35.8% |

## R model — what trading the signals earned

Entry at the signal close, the engine's stop, its one target booked in full (resting limit), stop gap-aware, closed at the close after 40 bars if neither; house costs; a stop under the house minimum is not a trade. Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | net $ |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 10 | 40.0% | +4.7R | -4.5R | **+0.2R** | +0.022R | $-684 |
| ALL SIGNALS, stop at the worst print | 10 | 40.0% | +4.7R | -4.9R | **-0.2R** | -0.025R | $-886 |
| grade A+ | 10 | 40.0% | +4.7R | -4.5R | **+0.2R** | +0.022R | $-684 |

## Baseline
- Random entry on the same sub-$0.50 universe (200 samples, seeded): fwd 5: +2.2% · fwd 10: +2.8% · fwd 20: +7.6%

Analysis only — not financial advice.
