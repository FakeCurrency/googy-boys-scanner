# Specs backtest — ASX

Generated 2026-07-05 · engine scanner/spec.py (restored 2026-07-02) · universe 1988 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 9944 | -1.1% | -1.1% | -0.9% | 31.0% | 30.8% | 38.1% | -17.8% |
| grade A+ | 7166 | -0.8% | -0.6% | -0.5% | 29.2% | 30.2% | 40.6% | -17.9% |
| grade A | 2512 | -2.0% | -2.5% | -1.9% | 35.3% | 33.1% | 31.6% | -17.4% |
| grade B | 266 | -1.8% | -1.8% | -1.0% | 41.0% | 26.3% | 32.7% | -17.1% |

## Baseline
- Random entry on the same sub-$0.50 universe (9944 samples, seeded): fwd 5: +0.6% · fwd 10: +1.1% · fwd 20: +2.5%

Analysis only — not financial advice.
