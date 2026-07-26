# Specs backtest — ASX

Generated 2026-07-26 · engine scanner/spec.py (restored 2026-07-02) · universe 93 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 6 | +11.2% | +13.0% | +12.6% | 33.3% | 50.0% | 16.7% | -14.9% |
| grade A+ | 3 | -0.1% | -1.8% | -11.2% | 33.3% | 66.7% | 0.0% | -17.4% |
| grade A | 3 | +22.4% | +27.9% | +36.3% | 33.3% | 33.3% | 33.3% | -12.5% |

## Baseline
- Random entry on the same sub-$0.50 universe (200 samples, seeded): fwd 5: +0.3% · fwd 10: -1.0% · fwd 20: -0.7%

Analysis only — not financial advice.
