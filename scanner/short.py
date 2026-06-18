"""Bearish pullback scanner — the mirror of signals.py for short setups.

Finds stocks in a confirmed downtrend where price has bounced back up to
a key Fibonacci EMA (resistance test). Entry is short at the EMA, stop
above the recent swing high, target at the nearest support (pivot low).

Scoring mirrors the long scanner out of 13 points:
  bearish_alignment (3) + resistance_touch (3) + confluence (3)
  + compression (2) + weekly_bearish (1) + volume (1)
"""

import numpy as np
import pandas as pd

from . import config
from .indicators import adx as calc_adx, atr, ema, ema_ladder, pivot_lows, rsi as calc_rsi, supertrend

SHORT_CHIP_ORDER = [
    "bearish_alignment", "compression", "resistance_touch",
    "confluence", "weekly_bearish", "volume",
]
SHORT_CHIP_BASE = {
    "bearish_alignment": "FULL BEARISH ALIGNMENT",
    "compression": "EMA COMPRESSION",
    "resistance_touch": "RESISTANCE TOUCH",
    "confluence": "STRONG RESISTANCE CONFLUENCE",
    "weekly_bearish": "WEEKLY BEARISH",
    "volume": "VOLUME EXPANSION",
}
SHORT_POINTS = {
    "bearish_alignment": 3,
    "resistance_touch": 3,
    "confluence": 3,
    "compression": 2,
    "weekly_bearish": 1,
    "volume": 1,
}
SHORT_SCORE_MAX = sum(SHORT_POINTS.values())   # 13
SHORT_GRADE_CUTOFFS = [("A+", 10), ("A", 8), ("B", 5), ("C", 3)]


def _weekly_bearish(df: pd.DataFrame) -> bool:
    try:
        wk = df["Close"].resample("W-FRI").last().dropna()
    except Exception:
        return False
    if len(wk) < config.WEEKLY_SLOW + 2:
        return False
    fast = ema(wk, config.WEEKLY_FAST).iloc[-1]
    slow = ema(wk, config.WEEKLY_SLOW).iloc[-1]
    return bool(wk.iloc[-1] < slow and fast < slow)


def evaluate(df: pd.DataFrame) -> dict | None:
    if df is None or len(df) < config.MIN_HISTORY:
        return None

    emas = ema_ladder(df)
    close = float(df["Close"].iloc[-1])
    if not np.isfinite(close) or close <= 0:
        return None

    ema_last = {p: float(emas[p].iloc[-1]) for p in config.EMA_PERIODS}
    vals = [ema_last[p] for p in config.EMA_PERIODS]
    if not all(np.isfinite(v) and v > 0 for v in vals):
        return None

    # Must be in a downtrend: price below the slow EMA (144)
    downtrend = close < ema_last[144]
    if not downtrend:
        return None

    # 1) Full bearish alignment: each EMA below the next (8 < 13 < 21 < ... < 144)
    bearish_alignment = all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))

    # 2) Resistance touch — price bounced up to within PULLBACK_TOL of a core EMA
    #    and is still at or below the EMA (not broken above it)
    pull_dists = [abs(close - ema_last[p]) / close for p in config.PULLBACK_EMAS]
    nearest_idx = int(np.argmin(pull_dists))
    nearest_ema_val = ema_last[config.PULLBACK_EMAS[nearest_idx]]
    resistance_touch = (min(pull_dists) <= config.PULLBACK_TOL) and (close <= nearest_ema_val * 1.005)

    # 3) EMA compression
    compression = (max(vals) - min(vals)) / close <= config.COMPRESSION_TOL

    # 4) Volume expansion
    vol = float(df["Volume"].iloc[-1])
    avg_vol = float(df["Volume"].iloc[-config.VOLUME_LOOKBACK - 1:-1].mean())
    volume = avg_vol > 0 and vol >= config.VOLUME_MULT * avg_vol

    # 5) Strong resistance confluence — 3+ EMAs clustered near price
    clustered = [v for v in vals if abs(v - close) / close <= config.CONFLUENCE_BAND]
    confluence = len(clustered) >= config.CONFLUENCE_MIN
    confluence_level = float(np.mean(clustered)) if clustered else None

    # 6) Weekly bearish confirmation
    weekly_bearish = _weekly_bearish(df)

    adx_val = float(calc_adx(df, config.ADX_PERIOD).iloc[-1])
    rsi_val = float(calc_rsi(df["Close"], config.RSI_PERIOD).iloc[-1])

    return {
        "close": close,
        "ema_last": ema_last,
        "downtrend": downtrend,
        "bearish_alignment": bearish_alignment,
        "resistance_touch": resistance_touch,
        "compression": compression,
        "volume": volume,
        "confluence": confluence,
        "weekly_bearish": weekly_bearish,
        "resistance_ema": config.PULLBACK_EMAS[nearest_idx],
        "confluence_level": confluence_level,
        "confluence_n": len(clustered),
        "vol": vol,
        "avg_vol": avg_vol,
        "adx_val": round(adx_val, 1),
        "rsi_val": round(rsi_val, 1),
    }


def score_and_grade(sig: dict) -> tuple[int, str | None, list[str]]:
    points = 0
    fired: list[str] = []
    for key in SHORT_CHIP_ORDER:
        if sig.get(key):
            points += SHORT_POINTS[key]
            fired.append(key)
    grade = None
    for name, cutoff in SHORT_GRADE_CUTOFFS:
        if points >= cutoff:
            grade = name
            break
    return points, grade, fired


def build_chips(fired: list[str], sig: dict) -> list[str]:
    chips = []
    for key in fired:
        if key == "resistance_touch":
            chips.append(f"RESISTANCE TOUCH EMA_{sig['resistance_ema']}")
        elif key == "confluence" and sig.get("confluence_level"):
            chips.append(f"STRONG RESISTANCE CONFLUENCE @ {round(sig['confluence_level'], 8)}")
        else:
            chips.append(SHORT_CHIP_BASE[key])
    return chips


def compute_levels(df: pd.DataFrame, sig: dict) -> dict:
    """Short entry at the resistance EMA, stop above swing high, target at nearest pivot low."""
    entry = sig["ema_last"][sig["resistance_ema"]]

    swing_high = float(df["High"].iloc[-config.SWING_LOOKBACK:].max())
    stop = swing_high * (1 + config.STOP_BUFFER)
    if stop <= entry:
        stop = entry * (1 + 0.03)

    close = sig["close"]
    pivs = pivot_lows(df.iloc[-config.RESIST_LOOKBACK:], config.PIVOT_WINDOW)
    below = pivs[pivs < close * 0.995]
    risk = stop - entry
    if len(below) > 0:
        target = float(below.max())
        target_basis = "support"
    else:
        target = entry - 2 * risk if risk > 0 else close * 0.9
        target_basis = "measured"

    reward = entry - target
    rr = round(reward / risk, 2) if risk > 0 else 0.0
    trail = float(supertrend(df, config.ATR_PERIOD, config.SUPERTREND_MULT).iloc[-1])

    return {
        "entry": round(entry, 8),
        "stop": round(stop, 8),
        "target": round(target, 8),
        "rr": round(rr, 2),
        "trail": round(trail, 8),
        "target_basis": target_basis,
    }


def narrative(symbol: str, sig: dict, lv: dict, cur: str) -> str:
    ema_name = f"EMA {sig['resistance_ema']}"
    risk_pct = (lv["stop"] - lv["entry"]) / lv["entry"] * 100
    return (
        f"{symbol} is in a confirmed downtrend (below EMA 144) and has bounced back up "
        f"to the {ema_name} resistance zone. "
        f"Short entry near {cur}{lv['entry']:.4f}, stop above the swing high at "
        f"{cur}{lv['stop']:.4f} ({risk_pct:.1f}% risk). "
        f"Target {cur}{lv['target']:.4f} ({lv['target_basis']}), R:R {lv['rr']:.1f}:1."
    )
