# Specs backtest — ASX

Generated 2026-08-16 · engine scanner/spec.py (restored 2026-07-02) · universe 2212 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 9629 | -1.1% | -1.0% | -0.8% | 30.5% | 30.5% | 39.0% | -17.4% |
| grade A+ | 6920 | -0.7% | -0.5% | -0.3% | 28.9% | 29.9% | 41.1% | -17.6% |
| grade A | 2454 | -2.1% | -2.5% | -2.1% | 34.2% | 32.5% | 33.3% | -17.1% |
| grade B | 255 | -1.9% | -2.0% | -0.9% | 39.2% | 25.5% | 35.3% | -16.7% |

## Baseline
- Random entry on the same sub-$0.50 universe (9629 samples, seeded): fwd 5: +7.8% · fwd 10: +8.3% · fwd 20: +4.4%

Analysis only — not financial advice.
