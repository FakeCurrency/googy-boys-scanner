"""Entry / Stop / Target levels and the risk-reward read.

- Entry  : the pullback level (the core EMA price has retraced to).
- Stop   : just below the recent swing low / structure.
- Target : the nearest real resistance above (a pivot high); if price is already
           at new highs with no overhead resistance, fall back to a 2R measured move.
- Trail  : SuperTrend value, shown as the Phase-2 trailing stop.
"""

import pandas as pd

from . import config
from .indicators import pivot_highs, supertrend


def compute_levels(df: pd.DataFrame, sig: dict) -> dict:
    close = sig["close"]
    entry = sig["ema_last"][sig["pullback_ema"]]

    # Stop: below the recent swing low. Guarantee it sits below entry.
    swing_low = float(df["Low"].iloc[-config.SWING_LOOKBACK:].min())
    stop = swing_low * (1 - config.STOP_BUFFER)
    if stop >= entry:
        stop = entry * (1 - 0.03)

    # Target: nearest pivot high above price; else a 2R measured move.
    pivots = pivot_highs(df.iloc[-config.RESIST_LOOKBACK:], config.PIVOT_WINDOW)
    above = pivots[pivots > close * 1.005]
    risk = entry - stop
    if len(above) > 0:
        target = float(above.min())
        target_basis = "resistance"
    else:
        target = entry + 2 * risk if risk > 0 else close * 1.1
        target_basis = "measured"

    reward = target - entry
    rr = reward / risk if risk > 0 else 0.0

    trail = float(supertrend(df, config.ATR_PERIOD, config.SUPERTREND_MULT).iloc[-1])

    return {
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "target": round(target, 4),
        "rr": round(rr, 2),
        "trail": round(trail, 4),
        "target_basis": target_basis,
    }
