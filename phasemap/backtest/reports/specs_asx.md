# Specs backtest — ASX

Generated 2026-08-09 · engine scanner/spec.py (restored 2026-07-02) · universe 2212 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 9581 | -1.1% | -1.1% | -0.8% | 30.7% | 30.5% | 38.8% | -17.5% |
| grade A+ | 6894 | -0.7% | -0.5% | -0.3% | 29.1% | 30.0% | 41.0% | -17.6% |
| grade A | 2436 | -2.2% | -2.6% | -2.1% | 34.5% | 32.5% | 33.0% | -17.1% |
| grade B | 251 | -1.8% | -1.9% | -0.9% | 39.8% | 25.9% | 34.3% | -16.8% |

## Baseline
- Random entry on the same sub-$0.50 universe (9581 samples, seeded): fwd 5: +1.5% · fwd 10: +2.1% · fwd 20: +2.2%

Analysis only — not financial advice.
