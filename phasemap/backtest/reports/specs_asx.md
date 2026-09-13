# Specs backtest — ASX

Generated 2026-09-13 · engine scanner/spec.py (restored 2026-07-02) · universe 2045 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1002 | -1.5% | -1.8% | -2.4% | 31.7% | 30.2% | 38.0% | -17.0% |
| grade A+ | 728 | -1.0% | -1.2% | -2.0% | 30.5% | 30.6% | 38.9% | -16.9% |
| grade A | 243 | -3.1% | -3.4% | -3.5% | 33.3% | 29.6% | 37.0% | -17.3% |
| grade B | 31 | -1.8% | -2.1% | -3.9% | 48.4% | 25.8% | 25.8% | -15.8% |

## Baseline
- Random entry on the same sub-$0.50 universe (1002 samples, seeded): fwd 5: +0.5% · fwd 10: +0.4% · fwd 20: +1.2%

Analysis only — not financial advice.
