# Specs backtest — ASX

Generated 2026-09-20 · engine scanner/spec.py (restored 2026-07-02) · universe 2046 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1036 | -1.3% | -0.8% | +0.2% | 31.0% | 30.9% | 38.1% | -16.9% |
| grade A+ | 751 | -1.4% | -1.2% | +0.2% | 27.8% | 31.4% | 40.7% | -17.4% |
| grade A | 255 | -1.7% | +0.4% | -0.4% | 37.3% | 30.2% | 32.5% | -15.7% |
| grade B | 30 | +2.5% | +0.4% | +3.6% | 56.7% | 23.3% | 20.0% | -14.4% |

## Baseline
- Random entry on the same sub-$0.50 universe (1036 samples, seeded): fwd 5: -0.1% · fwd 10: +1.9% · fwd 20: +2.9%

Analysis only — not financial advice.
