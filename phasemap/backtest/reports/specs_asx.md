# Specs backtest — ASX

Generated 2026-09-06 · engine scanner/spec.py (restored 2026-07-02) · universe 2043 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1379 | -1.0% | -1.3% | -0.3% | 30.7% | 29.8% | 39.4% | -16.8% |
| grade A+ | 977 | -0.5% | -0.8% | +0.0% | 28.4% | 29.8% | 41.9% | -17.1% |
| grade A | 365 | -2.0% | -2.1% | -1.2% | 35.9% | 30.4% | 33.7% | -16.3% |
| grade B | 37 | -4.1% | -3.6% | +1.9% | 43.2% | 24.3% | 32.4% | -15.3% |

## Baseline
- Random entry on the same sub-$0.50 universe (1379 samples, seeded): fwd 5: +1.0% · fwd 10: +0.9% · fwd 20: +1.5%

Analysis only — not financial advice.
