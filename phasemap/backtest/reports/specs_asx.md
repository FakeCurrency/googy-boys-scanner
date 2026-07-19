# Specs backtest — ASX

Generated 2026-07-19 · engine scanner/spec.py (restored 2026-07-02) · universe 1987 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 9969 | -1.1% | -1.1% | -0.9% | 31.0% | 30.7% | 38.3% | -17.7% |
| grade A+ | 7174 | -0.8% | -0.6% | -0.5% | 29.2% | 30.1% | 40.7% | -17.9% |
| grade A | 2529 | -2.0% | -2.4% | -1.9% | 35.0% | 32.9% | 32.1% | -17.3% |
| grade B | 266 | -1.8% | -1.8% | -1.2% | 40.2% | 26.3% | 33.5% | -17.3% |

## Baseline
- Random entry on the same sub-$0.50 universe (9969 samples, seeded): fwd 5: +0.8% · fwd 10: +1.4% · fwd 20: +1.0%

Analysis only — not financial advice.
