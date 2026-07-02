"""Reversals scanner — early trend-reversal / base-breakout setups.

Finds beaten-down or basing stocks that are turning up: price reclaiming and
crossing up through its short SMAs (9 over 26), coming off a base, with volume
and RSI confirming — i.e. the *birth* of a new uptrend (the opposite of the Fib
pullback scanner, which finds continuation in an existing uptrend).

Uses the user's own indicators: SMA 9/26/43/200, RSI 14 (+ its MA), Vol 20.
"""

import numpy as np
import pandas as pd

from . import analysis, config
from .grading import grade_from_points, score_chips
from .indicators import pivot_highs, rsi, sma, supertrend

CHIP_ORDER = ["reclaim", "base", "volume", "breakout", "rsi"]
CHIP_BASE = {
    "reclaim": "9 › 26 RECLAIM",
    "base": "BASE / DOWNTREND",
    "volume": "VOLUME SURGE",
    "breakout": "BASE BREAKOUT",
    "rsi": "RSI TURNING UP",
}
_KEY = {"reclaim": "reclaim", "base": "base", "volume": "volume",
        "breakout": "breakout", "rsi": "rsi_sig"}


def evaluate(df: pd.DataFrame) -> dict | None:
    if df is None or len(df) < config.REV_MIN_HISTORY:
        return None
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
    c = float(close.iloc[-1])
    if not np.isfinite(c) or c <= 0:
        return None

    s9, s26, s43, s200 = (sma(close, n) for n in (9, 26, 43, 200))
    s9l, s26l, s43l, s200l = (float(s.iloc[-1]) for s in (s9, s26, s43, s200))
    if not all(np.isfinite(v) and v > 0 for v in (s9l, s26l, s43l, s200l)):
        return None

    # baseline: price has at least reclaimed the 26-SMA
    if c <= s26l:
        return None

    rsi_ = rsi(close, config.REV_RSI_PERIOD)
    rsi_ma = sma(rsi_, config.REV_RSI_MA)
    rsil, rsimal = float(rsi_.iloc[-1]), float(rsi_ma.iloc[-1])

    vol_l = float(vol.iloc[-1])
    vol20 = float(vol.iloc[-config.REV_VOL_LOOKBACK - 1:-1].mean())
    vol5 = float(vol.iloc[-5:].mean())
    vol_max5 = float(vol.iloc[-5:].max())

    # 1) reclaim / fresh 9-over-26 cross, price above, 9 curling up
    above = (s9 > s26).to_numpy()
    recent_cross = False
    if above[-1]:
        win = above[-config.REV_CROSS_LOOKBACK - 1:]
        recent_cross = any(win[k] and not win[k - 1] for k in range(1, len(win)))
    s9_rising = s9l > float(s9.iloc[-config.REV_SLOPE_BARS - 1])
    reclaim = bool(recent_cross and c > s9l and s9_rising)

    # 2) base / downtrend context (room to run)
    hi_win = float(high.iloc[-config.REV_BASE_HIGH_LOOKBACK:].max())
    off_high = (hi_win - c) / hi_win if hi_win > 0 else 0.0
    below200 = bool((close.iloc[-config.REV_BELOW200_LOOKBACK:]
                     < s200.iloc[-config.REV_BELOW200_LOOKBACK:]).any())
    base = bool(off_high >= config.REV_BASE_OFF_HIGH or below200)

    # 3) volume expansion
    volume = bool(vol20 > 0 and (vol5 >= config.REV_VOL_MULT * vol20
                                 or vol_max5 >= config.REV_VOL_SPIKE * vol20))

    # 4) base / trendline breakout
    a, b = config.REV_BREAKOUT_BASE
    base_high = float(high.iloc[-a:-b].max())
    breakout = bool(c >= base_high * config.REV_BREAKOUT_TOL)

    # 5) RSI turning up through its MA, not yet overbought
    lo, hi = config.REV_RSI_BAND
    rsi_up = rsil > float(rsi_.iloc[-3])
    rsi_sig = bool(rsil > rsimal and rsi_up and lo <= rsil <= hi)

    return {
        "close": c, "ok": True,
        "sma": {9: s9l, 26: s26l, 43: s43l, 200: s200l},
        "rsi": rsil, "rsi_ma": rsimal, "rsi_up": rsi_up,
        "vol": vol_l, "vol20": vol20, "vol5": vol5,
        "off_high": off_high, "base_high": base_high, "below200": below200,
        "reclaim": reclaim, "base": base, "volume": volume,
        "breakout": breakout, "rsi_sig": rsi_sig,
        "cross_up": s9l > s26l,
    }


def score_and_grade(sig: dict) -> tuple[int, str | None, list[str]]:
    points, fired = score_chips(sig, CHIP_ORDER, config.REV_POINTS, key_map=_KEY)
    return points, grade_from_points(points, config.REV_GRADE_CUTOFFS), fired


def compute_levels(df: pd.DataFrame, sig: dict) -> dict:
    close = sig["close"]
    entry = close                         # enter on the reclaim / breakout
    swing_low = float(df["Low"].iloc[-config.REV_STOP_LOOKBACK:].min())
    stop = swing_low * (1 - config.STOP_BUFFER)
    if stop >= entry:
        stop = min(sig["sma"][26], entry * config.REV_STOP_FALLBACK_PCT)
    risk = entry - stop

    # target: nearest meaningful resistance (>=10% up), else a 3R measured move.
    piv = pivot_highs(df.iloc[-config.RESIST_LOOKBACK:], config.PIVOT_WINDOW)
    above = piv[piv > close * 1.10]
    if len(above) > 0:
        target, basis = float(above.min()), "resistance"
    else:
        target = entry + 3 * risk if risk > 0 else close * 1.3
        basis = "measured"

    rr = (target - entry) / risk if risk > 0 else 0.0
    trail = float(supertrend(df, config.ATR_PERIOD, config.SUPERTREND_MULT).iloc[-1])
    return {"entry": round(entry, 8), "stop": round(stop, 8), "target": round(target, 8),
            "rr": round(rr, 2), "trail": round(trail, 8), "target_basis": basis}


def build_chips(fired: list[str], sig: dict) -> list[str]:
    chips = []
    for key in fired:
        if key == "base":
            chips.append(f"BASE -{sig['off_high'] * 100:.0f}% OFF HIGH")
        elif key == "volume":
            ratio = sig["vol5"] / sig["vol20"] if sig["vol20"] else 0
            chips.append(f"VOLUME {ratio:.1f}× SURGE")
        else:
            chips.append(CHIP_BASE[key])
    return chips


def _pct(level: float, close: float) -> float:
    return round((level - close) / close * 100, 1) if close else 0.0


def build_detail(df: pd.DataFrame, sig: dict, lv: dict) -> dict:
    close = sig["close"]
    s = sig["sma"]
    ratio = sig["vol5"] / sig["vol20"] if sig["vol20"] else 0.0
    swing_low = float(df["Low"].iloc[-config.REV_STOP_LOOKBACK:].min())
    return {
        "setup_type": "reversal",
        "sma9": round(s[9], 8), "sma9_pct": _pct(s[9], close),
        "sma26": round(s[26], 8), "sma26_pct": _pct(s[26], close),
        "sma43": round(s[43], 8), "sma43_pct": _pct(s[43], close),
        "sma200": round(s[200], 8), "sma200_pct": _pct(s[200], close),
        "cross_up": sig["cross_up"],
        "rsi": round(sig["rsi"], 1), "rsi_ma": round(sig["rsi_ma"], 1), "rsi_up": sig["rsi_up"],
        "volume_ratio": round(ratio, 1), "volume_today": int(sig["vol"]),
        "volume_avg": int(sig["vol20"]), "volume_surge": sig["volume"],
        "off_high_pct": round(sig["off_high"] * 100, 1),
        "base_high": round(sig["base_high"], 8), "base_high_pct": _pct(sig["base_high"], close),
        "broken": sig["breakout"],
        "swing_low": round(swing_low, 8), "swing_low_pct": _pct(swing_low, close),
        "trailing_stop": lv["trail"], "trailing_label": "SuperTrend 3× ATR",
        "trailing_pct": _pct(lv["trail"], close),
        "structure": analysis._structure(df),
        "risk_pct": round((lv["entry"] - lv["stop"]) / lv["entry"] * 100, 1) if lv["entry"] else 0.0,
    }


def narrative(symbol: str, sig: dict, lv: dict, detail: dict, cur: str = "$") -> str:
    p = []
    if sig["reclaim"]:
        p.append(f"{symbol} has reclaimed its short-term moving averages — the 9 has crossed up "
                 f"through the 26 and price is back above both.")
    elif sig["cross_up"]:
        p.append(f"{symbol}'s 9-SMA is above the 26 and price has reclaimed them.")
    if sig["base"]:
        p.append(f"It is coming off a base, {sig['off_high'] * 100:.0f}% below its one-year high, "
                 "so there is room to run.")
    if sig["volume"]:
        p.append(f"Volume is expanding ({detail['volume_ratio']}× the 20-day average) — real participation.")
    if sig["breakout"]:
        p.append(f"Price has broken above the base high at {cur}{sig['base_high']:.4f}.")
    if sig["rsi_sig"]:
        p.append("RSI has turned up through its signal line.")
    p.append(f"Trade idea: entry {cur}{lv['entry']:.4f}, stop {cur}{lv['stop']:.4f}, "
             f"target {cur}{lv['target']:.4f} ({lv['rr']:.2f}:1) — then trail it.")
    return " ".join(p)
