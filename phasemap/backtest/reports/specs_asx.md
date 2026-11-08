# Specs backtest — ASX

Generated 2026-11-08 · engine scanner/spec.py (restored 2026-07-02) · universe 2060 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1802 | -1.5% | -1.3% | -1.3% | 30.0% | 31.0% | 39.0% | -18.2% |
| grade A+ | 680 | +0.1% | +0.7% | +0.7% | 12.4% | 31.3% | 56.3% | -16.7% |
| grade A | 152 | -1.2% | -2.4% | -0.8% | 17.1% | 38.2% | 44.7% | -17.5% |
| grade B | 970 | -2.8% | -2.6% | -2.8% | 44.3% | 29.7% | 26.0% | -19.4% |

## R model — what trading the signals earned

Entry at the signal close, the engine's stop, its one target booked in full (resting limit), stop gap-aware, closed at the close after 40 bars if neither; house costs; a stop under the house minimum is not a trade. Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | net $ |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 1801 | 41.5% | +764.0R | -882.7R | **-118.7R** | -0.066R | $-45,498 |
| ALL SIGNALS, stop at the worst print | 1801 | 41.5% | +764.0R | -992.1R | **-228.1R** | -0.127R | $-67,775 |
| grade A+ | 680 | 35.4% | +373.9R | -337.9R | **+36.0R** | +0.053R | $+4,691 |
| grade A | 152 | 37.5% | +108.2R | -89.8R | **+18.4R** | +0.121R | $-3,085 |
| grade B | 969 | 46.4% | +281.9R | -454.9R | **-173.0R** | -0.179R | $-47,103 |

## Baseline
- Random entry on the same sub-$0.50 universe (1802 samples, seeded): fwd 5: +0.4% · fwd 10: +0.4% · fwd 20: +0.8%

Analysis only — not financial advice.
