# Specs backtest — ASX

Generated 2026-11-01 · engine scanner/spec.py (restored 2026-07-02) · universe 2060 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1800 | -1.5% | -1.5% | -1.4% | 29.9% | 31.4% | 38.7% | -17.2% |
| grade A+ | 668 | -0.8% | -0.2% | -0.7% | 12.9% | 32.9% | 54.2% | -16.7% |
| grade A | 147 | -1.8% | -2.8% | +0.3% | 12.9% | 39.5% | 47.6% | -15.0% |
| grade B | 985 | -1.9% | -2.1% | -2.2% | 44.0% | 29.2% | 26.8% | -17.9% |

## R model — what trading the signals earned

Entry at the signal close, the engine's stop, its one target booked in full (resting limit), stop gap-aware, closed at the close after 40 bars if neither; house costs; a stop under the house minimum is not a trade. Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | net $ |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1798 | 41.4% | +736.2R | -878.9R | **-142.7R** | -0.079R | $-45,019 |
| ALL SIGNALS, stop at the worst print | 1798 | 41.4% | +736.2R | -991.1R | **-255.0R** | -0.142R | $-66,051 |
| grade A+ | 667 | 36.1% | +365.9R | -338.5R | **+27.3R** | +0.041R | $-4,020 |
| grade A | 146 | 37.0% | +87.7R | -97.5R | **-9.7R** | -0.067R | $-1,372 |
| grade B | 985 | 45.7% | +282.6R | -442.9R | **-160.3R** | -0.163R | $-39,627 |

## Baseline
- Random entry on the same sub-$0.50 universe (1800 samples, seeded): fwd 5: -0.2% · fwd 10: +0.3% · fwd 20: +1.1%

Analysis only — not financial advice.
