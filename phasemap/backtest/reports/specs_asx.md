# Specs backtest — ASX

Generated 2026-09-20 · engine scanner/spec.py (restored 2026-07-02) · universe 2046 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1208 | -1.2% | -1.8% | -2.0% | 29.1% | 31.2% | 39.7% | -17.5% |
| grade A+ | 886 | -1.1% | -2.0% | -2.1% | 28.1% | 32.3% | 39.6% | -17.8% |
| grade A | 298 | -1.5% | -1.2% | -1.9% | 31.5% | 28.5% | 39.9% | -16.7% |
| grade B | 24 | +0.9% | -1.2% | +0.9% | 33.3% | 25.0% | 41.7% | -17.2% |

## Baseline
- Random entry on the same sub-$0.50 universe (1208 samples, seeded): fwd 5: +0.2% · fwd 10: +0.8% · fwd 20: +0.9%

Analysis only — not financial advice.
