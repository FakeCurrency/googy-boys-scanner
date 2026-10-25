# Specs backtest — ASX

Generated 2026-10-25 · engine scanner/spec.py (restored 2026-07-02) · universe 2049 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1905 | -0.8% | -0.6% | -0.6% | 33.2% | 28.8% | 38.0% | -17.0% |
| grade A+ | 703 | -0.2% | +0.4% | +0.8% | 14.2% | 31.3% | 54.5% | -16.5% |
| grade A | 144 | -0.9% | -0.7% | -0.1% | 14.6% | 40.3% | 45.1% | -15.7% |
| grade B | 1058 | -1.2% | -1.3% | -1.6% | 48.4% | 25.6% | 26.0% | -17.6% |

## R model — what trading the signals earned

Entry at the signal close, the engine's stop, its one target booked in full (resting limit), stop gap-aware, closed at the close after 40 bars if neither; house costs; a stop under the house minimum is not a trade. Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | net $ |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1901 | 44.2% | +840.2R | -878.0R | **-37.8R** | -0.020R | $-16,744 |
| ALL SIGNALS, stop at the worst print | 1901 | 44.2% | +840.2R | -991.1R | **-150.9R** | -0.079R | $-37,158 |
| grade A+ | 700 | 36.4% | +415.1R | -357.4R | **+57.7R** | +0.082R | $+10,981 |
| grade A | 144 | 36.1% | +94.0R | -94.2R | **-0.2R** | -0.002R | $-172 |
| grade B | 1057 | 50.5% | +331.0R | -426.3R | **-95.3R** | -0.090R | $-27,553 |

## Baseline
- Random entry on the same sub-$0.50 universe (1905 samples, seeded): fwd 5: +0.5% · fwd 10: +1.1% · fwd 20: +1.6%

Analysis only — not financial advice.
