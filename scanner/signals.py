"""The signal "chips", plus scoring and grading.

Each chip is a boolean derived from the latest bar. The grade is the sum of the
point weights of the chips that fired (see config.POINTS / config.GRADE_CUTOFFS).
"""

import numpy as np
import pandas as pd

from . import config
from .indicators import adx as calc_adx, ema, ema_ladder, rsi as calc_rsi

# Signal key -> base display label (some get dynamic suffixes in scan.py).
CHIP_ORDER = ["alignment", "compression", "pullback", "confluence", "weekly", "volume", "adx", "rsi_pullback"]
CHIP_BASE = {
    "alignment": "FULL BULLISH ALIGNMENT",
    "compression": "EMA COMPRESSION",
    "pullback": "CORE FIB PULLBACK",
    "confluence": "STRONG FIB CONFLUENCE",
    "weekly": "WEEKLY BULLISH",
    "volume": "VOLUME EXPANSION",
    "adx": "TRENDING MARKET (ADX)",
    "rsi_pullback": "HEALTHY RSI PULLBACK",
}


def _weekly_bullish(df: pd.DataFrame) -> bool:
    """Higher-timeframe confirmation: weekly close above a rising weekly EMA stack."""
    try:
        wk = df["Close"].resample("W-FRI").last().dropna()
    except Exception:
        return False
    if len(wk) < config.WEEKLY_SLOW + 2:
        return False
    fast = ema(wk, config.WEEKLY_FAST).iloc[-1]
    slow = ema(wk, config.WEEKLY_SLOW).iloc[-1]
    return bool(wk.iloc[-1] > slow and fast > slow)


def evaluate(df: pd.DataFrame) -> dict | None:
    """Evaluate every signal for the latest bar. Returns None if data is too thin."""
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

    uptrend = close > ema_last[144]

    # 1) Full bullish alignment.
    alignment = all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))

    # 2) Core Fib pullback — price near a core EMA (from above).
    pull_dists = [abs(close - ema_last[p]) / close for p in config.PULLBACK_EMAS]
    nearest_idx = int(np.argmin(pull_dists))
    nearest_ema = ema_last[config.PULLBACK_EMAS[nearest_idx]]
    # Require price is AT or ABOVE the nearest EMA — abs() distance alone would
    # fire the chip even when price has already broken below the support level.
    pullback = (min(pull_dists) <= config.PULLBACK_TOL) and uptrend and (close >= nearest_ema)

    # 3) EMA compression.
    compression = (max(vals) - min(vals)) / close <= config.COMPRESSION_TOL

    # 4) Volume expansion.
    vol = float(df["Volume"].iloc[-1])
    avg_vol = float(df["Volume"].iloc[-config.VOLUME_LOOKBACK - 1 : -1].mean())
    volume = avg_vol > 0 and vol >= config.VOLUME_MULT * avg_vol

    # 5) Strong Fib confluence — several EMAs clustered around price.
    clustered = [v for v in vals if abs(v - close) / close <= config.CONFLUENCE_BAND]
    confluence = len(clustered) >= config.CONFLUENCE_MIN
    confluence_level = float(np.mean(clustered)) if clustered else None

    # 6) Weekly (higher-timeframe) bullish confirmation.
    weekly = _weekly_bullish(df)

    # 7) ADX — confirms the market is actually trending, not ranging sideways.
    adx_val = float(calc_adx(df, config.ADX_PERIOD).iloc[-1])
    adx_chip = adx_val >= config.ADX_TREND_MIN

    # 8) RSI(21) pullback quality — Fibonacci RSI in the healthy dip zone.
    rsi_val = float(calc_rsi(df["Close"], config.RSI_PERIOD).iloc[-1])
    rsi_pullback = config.RSI_PULLBACK_LOW <= rsi_val <= config.RSI_PULLBACK_HIGH

    return {
        "close": close,
        "ema_last": ema_last,
        "uptrend": uptrend,
        "alignment": alignment,
        "pullback": pullback,
        "compression": compression,
        "volume": volume,
        "confluence": confluence,
        "weekly": weekly,
        "adx": adx_chip,
        "rsi_pullback": rsi_pullback,
        "pullback_ema": config.PULLBACK_EMAS[nearest_idx],
        "confluence_level": confluence_level,
        "confluence_n": len(clustered),
        "vol": vol,
        "avg_vol": avg_vol,
        "adx_val": round(adx_val, 1),
        "rsi_val": round(rsi_val, 1),
    }


def score_and_grade(sig: dict) -> tuple[int, str | None, list[str]]:
    """Return (points, grade, fired_signal_keys) for an evaluated signal dict."""
    points = 0
    fired: list[str] = []
    for key in CHIP_ORDER:
        if sig.get(key):
            points += config.POINTS[key]
            fired.append(key)

    grade = None
    for name, cutoff in config.GRADE_CUTOFFS:
        if points >= cutoff:
            grade = name
            break
    return points, grade, fired
