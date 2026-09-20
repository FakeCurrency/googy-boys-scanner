# Specs backtest — ASX

Generated 2026-09-20 · engine scanner/spec.py (restored 2026-07-02) · universe 2046 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 8989 | -1.2% | -1.2% | -1.1% | 30.0% | 30.6% | 39.4% | -17.5% |
| grade A+ | 6426 | -0.9% | -0.7% | -0.7% | 28.2% | 30.0% | 41.8% | -17.6% |
| grade A | 2315 | -2.0% | -2.2% | -2.1% | 33.9% | 32.9% | 33.2% | -17.0% |
| grade B | 248 | -2.1% | -2.1% | -1.4% | 39.5% | 27.0% | 33.5% | -17.3% |

## Baseline
- Random entry on the same sub-$0.50 universe (8989 samples, seeded): fwd 5: +0.5% · fwd 10: +1.1% · fwd 20: +2.9%

Analysis only — not financial advice.
