# Specs backtest — ASX

Generated 2026-08-23 · engine scanner/spec.py (restored 2026-07-02) · universe 2212 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 9651 | -1.1% | -1.0% | -0.8% | 30.4% | 30.4% | 39.1% | -17.4% |
| grade A+ | 6937 | -0.7% | -0.5% | -0.3% | 28.8% | 29.9% | 41.3% | -17.6% |
| grade A | 2456 | -2.1% | -2.5% | -2.1% | 34.1% | 32.5% | 33.4% | -17.1% |
| grade B | 258 | -1.9% | -2.0% | -0.8% | 38.8% | 25.2% | 36.0% | -16.8% |

## Baseline
- Random entry on the same sub-$0.50 universe (9651 samples, seeded): fwd 5: +2.2% · fwd 10: +2.3% · fwd 20: +2.7%

Analysis only — not financial advice.
