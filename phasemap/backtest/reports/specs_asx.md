# Specs backtest — ASX

Generated 2026-07-02 · engine scanner/spec.py (restored 2026-07-02) · universe 1987 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 5296 | -1.1% | -0.9% | -0.8% | 30.8% | 31.2% | 38.0% | -17.9% |
| grade A+ | 3826 | -0.8% | -0.5% | -0.5% | 29.0% | 30.6% | 40.5% | -18.0% |
| grade A | 1323 | -1.9% | -2.2% | -1.5% | 35.1% | 33.6% | 31.3% | -17.5% |
| grade B | 147 | -2.1% | -1.5% | -1.5% | 38.8% | 27.2% | 34.0% | -17.1% |

## Baseline
- Random entry on the same sub-$0.50 universe (5296 samples, seeded): fwd 5: +0.4% · fwd 10: +0.5% · fwd 20: +1.8%

Analysis only — not financial advice.
