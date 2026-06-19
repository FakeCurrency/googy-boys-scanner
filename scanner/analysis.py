"""Human-readable analysis + the detailed level breakdown shown when a row is
expanded. All values are derived from the same signal/level computation, so the
text never disagrees with the numbers.
"""

import numpy as np
import pandas as pd

from . import config
from .indicators import pivot_highs, pivot_lows


def _pct_from(level: float, close: float) -> float:
    """How far `level` sits from price (negative = below price)."""
    return round((level - close) / close * 100, 1) if close else 0.0


def _structure(df: pd.DataFrame) -> dict:
    highs = pivot_highs(df.iloc[-config.RESIST_LOOKBACK:], config.PIVOT_WINDOW)
    lows = pivot_lows(df.iloc[-config.RESIST_LOOKBACK:], config.PIVOT_WINDOW)
    sh = [round(float(v), 8) for v in highs.iloc[-3:].tolist()]
    sl = [round(float(v), 8) for v in lows.iloc[-3:].tolist()]

    up = len(sh) >= 2 and sh[-1] > sh[0] and len(sl) >= 2 and sl[-1] > sl[0]
    down = len(sh) >= 2 and sh[-1] < sh[0] and len(sl) >= 2 and sl[-1] < sl[0]
    trend = "HH/HL — Uptrend" if up else "LH/LL — Downtrend" if down else "Mixed / consolidating"
    return {"trend": trend, "swing_highs": sh, "swing_lows": sl}


def build_detail(df: pd.DataFrame, sig: dict, lv: dict) -> dict:
    close = sig["close"]
    ema = sig["ema_last"]

    swing_low = float(df["Low"].iloc[-config.SWING_LOOKBACK:].min())
    swing_high = lv["target"]   # the nearest resistance used for the target

    vol = sig["vol"]
    avg_vol = sig["avg_vol"]
    ratio = vol / avg_vol if avg_vol else 0.0

    spread_pct = (max(ema.values()) - min(ema.values())) / close * 100

    fast_levels = []
    for label, period in (("Pullback", 8), ("Next level", 13), ("Support", 21)):
        v = ema[period]
        fast_levels.append({
            "label": label, "ema": period, "value": round(v, 8),
            "pct": round((close - v) / v * 100, 1) if v else 0.0,   # +ve = price above EMA
        })

    return {
        "swing_low": round(swing_low, 8), "swing_low_pct": _pct_from(swing_low, close),
        "swing_high": round(swing_high, 8), "swing_high_pct": _pct_from(swing_high, close),
        "ema55": round(ema[55], 8), "ema55_pct": _pct_from(ema[55], close),
        "ema89": round(ema[89], 8), "ema89_pct": _pct_from(ema[89], close),
        "trailing_stop": lv["trail"], "trailing_label": "SuperTrend 3× ATR",
        "trailing_pct": _pct_from(lv["trail"], close),
        "volume_ratio": round(ratio, 1), "volume_today": int(vol), "volume_avg": int(avg_vol),
        "volume_expanding": ratio >= config.VOLUME_MULT,
        "ema_spread_pct": round(spread_pct, 1), "ema_aligned": sig["alignment"],
        "fast_levels": fast_levels,
        "structure": _structure(df),
        "risk_pct": round((lv["entry"] - lv["stop"]) / lv["entry"] * 100, 1) if lv["entry"] else 0.0,
    }


def narrative(symbol: str, sig: dict, lv: dict, detail: dict, cur: str = "$") -> str:
    p = []
    if sig["alignment"]:
        p.append(f"{symbol} has all Fibonacci EMAs in full bullish alignment.")
    if sig["compression"]:
        p.append("EMAs are compressed, suggesting a big move is building.")
    if "Uptrend" in detail["structure"]["trend"]:
        p.append("Price making higher highs and higher lows — healthy uptrend structure.")
    if sig["pullback"]:
        pe = sig["pullback_ema"]
        p.append(f"Price has pulled back and is testing the {pe} EMA at {cur}{sig['ema_last'][pe]:.4f}. "
                 "This is a core Fibonacci pullback to a key trend EMA.")
    if sig["confluence"] and sig.get("confluence_level"):
        n = sig.get("confluence_n", 0)
        p.append(f"Strong confluence zone at {cur}{sig['confluence_level']:.4f} where {n} levels cluster.")
    p.append(f"Trade setup: entry {cur}{lv['entry']:.4f}, stop {cur}{lv['stop']:.4f}, "
             f"target {cur}{lv['target']:.4f}. Risk/reward is {lv['rr']:.2f}:1.")
    if sig["weekly"]:
        p.append("Weekly EMAs are bullish.")
    return " ".join(p)
