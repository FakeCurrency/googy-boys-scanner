# Specs backtest — ASX

Generated 2026-08-02 · engine scanner/spec.py (restored 2026-07-02) · universe 2212 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 2615 | -1.4% | -1.5% | -1.1% | 30.2% | 31.7% | 38.1% | -17.9% |
| grade A+ | 1896 | -1.1% | -1.2% | -0.8% | 29.1% | 31.1% | 39.8% | -18.2% |
| grade A | 643 | -2.0% | -2.2% | -1.6% | 32.7% | 34.1% | 33.3% | -17.4% |
| grade B | 76 | -1.5% | -1.7% | -4.4% | 36.8% | 26.3% | 36.8% | -15.9% |

## Baseline
- Random entry on the same sub-$0.50 universe (2615 samples, seeded): fwd 5: +0.7% · fwd 10: +0.9% · fwd 20: +5.2%

Analysis only — not financial advice.
