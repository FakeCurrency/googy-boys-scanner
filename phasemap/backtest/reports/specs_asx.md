# Specs backtest — ASX

Generated 2026-08-30 · engine scanner/spec.py (restored 2026-07-02) · universe 2212 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 8927 | -0.9% | -0.8% | -0.3% | 30.5% | 30.1% | 39.3% | -17.1% |
| grade A+ | 6412 | -0.5% | -0.1% | +0.4% | 28.9% | 29.5% | 41.5% | -17.2% |
| grade A | 2284 | -2.0% | -2.6% | -2.2% | 34.1% | 32.4% | 33.5% | -16.8% |
| grade B | 231 | -1.8% | -2.2% | -1.0% | 39.8% | 24.7% | 35.5% | -16.4% |

## Baseline
- Random entry on the same sub-$0.50 universe (8927 samples, seeded): fwd 5: +0.6% · fwd 10: +1.2% · fwd 20: +3.3%

Analysis only — not financial advice.
