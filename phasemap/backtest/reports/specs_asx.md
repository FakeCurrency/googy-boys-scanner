# Specs backtest — ASX

Generated 2026-11-22 · engine scanner/spec.py (restored 2026-07-02) · universe 2058 · period 5y · zero-lookahead slice replay, one signal per fire-streak.

> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. Sub-$0.50 specs delist *constantly* — this cohort is missing its casualties and every number below is optimistic. Directional use only.

A **signal** = the first day a fire-streak passes every mandatory gate (3× volume spike, beaten-down base, breakout, rising 9-SMA, not over-extended). Entry at the signal close; stop/target from the engine's own levels; a bar tagging both counts as a stop (pessimistic).

| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |
|---|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 9888 | -1.2% | -1.2% | -1.2% | 30.3% | 31.4% | 38.4% | -17.8% |
| grade A+ | 3716 | +0.1% | +0.3% | +0.9% | 12.5% | 32.3% | 55.2% | -16.9% |
| grade A | 806 | -1.2% | -1.1% | -0.1% | 14.9% | 37.2% | 47.9% | -15.2% |
| grade B | 5366 | -2.1% | -2.4% | -2.8% | 44.9% | 29.9% | 25.2% | -18.9% |

## R model — what trading the signals earned

Entry at the signal close, the engine's stop, its one target booked in full (resting limit), stop gap-aware, closed at the close after 40 bars if neither; house costs; a stop under the house minimum is not a trade. Dollars at a flat $1,000 per position.

| cohort | trades | win | R won | R lost | net R | per trade | net $ |
|---|---|---|---|---|---|---|---|
| ALL SIGNALS | 9876 | 41.3% | +4037.7R | -4935.1R | **-897.5R** | -0.091R | $-232,654 |
| ALL SIGNALS, stop at the worst print | 9876 | 41.3% | +4037.7R | -5585.9R | **-1548.2R** | -0.157R | $-353,817 |
| grade A+ | 3711 | 34.2% | +1979.1R | -2030.5R | **-51.4R** | -0.014R | $-3,400 |
| grade A | 803 | 35.7% | +476.5R | -473.1R | **+3.4R** | +0.004R | $-5,163 |
| grade B | 5362 | 47.1% | +1582.1R | -2431.6R | **-849.5R** | -0.158R | $-224,090 |

## Baseline
- Random entry on the same sub-$0.50 universe (9888 samples, seeded): fwd 5: +0.3% · fwd 10: +0.8% · fwd 20: +5.7%

Analysis only — not financial advice.
