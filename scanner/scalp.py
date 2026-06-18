"""Intraday scalp scanner — 1h bars with 4h trend confirmation.

Universe: top ASX liquid stocks, NASDAQ mega-caps, and key commodity futures.
Setup: SMA pullback/bounce on 1h, confirmed by the 4h trend direction.
Stop: 1.5× ATR(14 on 1h) — tight, intraday-appropriate.
Target: 3× ATR from entry → automatic 2:1 R:R.
"""

import numpy as np
import pandas as pd

from .indicators import atr, rsi as calc_rsi

SCALP_SMAS = [9, 26, 43]
SCALP_ATR_PERIOD = 14
SCALP_ATR_STOP_MULT = 1.5    # stop = entry ± 1.5× ATR
SCALP_ATR_TARGET_MULT = 3.0  # target = entry ± 3× ATR  (2:1 R:R)
SCALP_MIN_BARS = 55          # minimum 1h bars for SMA43 warm-up

SCALP_POINTS = {
    "4h_confirm": 3,   # 4h trend aligned with 1h direction
    "sma_align":  2,   # all 3 SMAs ordered correctly on 1h
    "pullback":   2,   # price bouncing from SMA 9 or SMA 26
    "volume":     2,   # volume above 20-bar average
    "rsi":        1,   # RSI in healthy zone (not extreme)
}
SCALP_SCORE_MAX = sum(SCALP_POINTS.values())   # 10
SCALP_GRADE_CUTOFFS = [("A+", 8), ("A", 6), ("B", 4), ("C", 2)]

SCALP_CHIP_ORDER = ["4h_confirm", "sma_align", "pullback", "volume", "rsi"]
SCALP_CHIP_BASE = {
    "4h_confirm": "4H TREND CONFIRMED",
    "sma_align":  "SMA STACK ALIGNED",
    "pullback":   "PULLBACK TO SMA",
    "volume":     "VOLUME EXPANSION",
    "rsi":        "RSI MOMENTUM",
}


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("4h").agg({
        "Open": "first", "High": "max", "Low": "min",
        "Close": "last", "Volume": "sum",
    }).dropna()


def evaluate(df: pd.DataFrame, direction: str = "long") -> dict | None:
    if df is None or len(df) < SCALP_MIN_BARS:
        return None

    # Strip timezone so resampling and indicators work cleanly
    if getattr(df.index, "tz", None) is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)

    close = df["Close"]
    sma9  = _sma(close, 9)
    sma26 = _sma(close, 26)
    sma43 = _sma(close, 43)

    last   = float(close.iloc[-1])
    prev   = float(close.iloc[-2])
    s9     = float(sma9.iloc[-1])
    s26    = float(sma26.iloc[-1])
    s43    = float(sma43.iloc[-1])

    if not all(np.isfinite(v) and v > 0 for v in [last, prev, s9, s26, s43]):
        return None

    # ── Direction gate ────────────────────────────────────────────────────────
    if direction == "long"  and last < s43:
        return None
    if direction == "short" and last > s43:
        return None

    # ── 4h confirmation ───────────────────────────────────────────────────────
    s4h_ok = False
    try:
        df4h = _resample_4h(df)
        if len(df4h) >= 12:
            s4h9  = float(_sma(df4h["Close"], 9).iloc[-1])
            s4h26 = float(_sma(df4h["Close"], 26).iloc[-1])
            c4h   = float(df4h["Close"].iloc[-1])
            if direction == "long":
                s4h_ok = c4h > s4h26 and s4h9 > s4h26
            else:
                s4h_ok = c4h < s4h26 and s4h9 < s4h26
    except Exception:
        pass

    # ── SMA alignment on 1h ──────────────────────────────────────────────────
    sma_align = (s9 > s26 > s43) if direction == "long" else (s9 < s26 < s43)

    # ── Pullback / bounce from SMA 9 or SMA 26 ───────────────────────────────
    # Price must be within 1.5% of the SMA and show the start of a reversal
    # (for longs: prev close at/below SMA, current close above → bounce)
    tol = 0.015
    if direction == "long":
        near9  = abs(last - s9)  / last <= tol and last >= s9 * (1 - tol)
        near26 = abs(last - s26) / last <= tol and last >= s26 * (1 - tol)
        bounce = last > prev  # momentum turning up
    else:
        near9  = abs(last - s9)  / last <= tol and last <= s9  * (1 + tol)
        near26 = abs(last - s26) / last <= tol and last <= s26 * (1 + tol)
        bounce = last < prev  # momentum turning down

    pullback     = (near9 or near26) and bounce
    pullback_sma = 9 if near9 else (26 if near26 else None)

    # ── Volume expansion ──────────────────────────────────────────────────────
    vol     = float(df["Volume"].iloc[-1])
    avg_vol = float(df["Volume"].iloc[-21:-1].mean())
    volume  = avg_vol > 0 and vol >= 1.3 * avg_vol

    # ── RSI healthy zone ──────────────────────────────────────────────────────
    rsi_val = float(calc_rsi(close, 14).iloc[-1])
    rsi_ok  = (40 <= rsi_val <= 65) if direction == "long" else (35 <= rsi_val <= 60)

    return {
        "direction":   direction,
        "close":       round(last, 8),
        "sma9":        round(s9, 8),
        "sma26":       round(s26, 8),
        "sma43":       round(s43, 8),
        "4h_confirm":  s4h_ok,
        "sma_align":   sma_align,
        "pullback":    pullback,
        "pullback_sma": pullback_sma,
        "volume":      volume,
        "rsi":         rsi_ok,
        "rsi_val":     round(rsi_val, 1),
        "vol":         vol,
        "avg_vol":     avg_vol,
    }


def compute_levels(df: pd.DataFrame, sig: dict) -> dict:
    """ATR-based stop and 2:1 target."""
    entry     = sig["close"]
    direction = sig["direction"]

    if getattr(df.index, "tz", None) is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)

    atr_val = float(atr(df, SCALP_ATR_PERIOD).iloc[-1])
    risk    = SCALP_ATR_STOP_MULT * atr_val

    if direction == "long":
        stop   = entry - risk
        target = entry + SCALP_ATR_TARGET_MULT * atr_val
    else:
        stop   = entry + risk
        target = entry - SCALP_ATR_TARGET_MULT * atr_val

    rr = round(abs(target - entry) / risk, 2) if risk > 0 else 0.0
    return {
        "entry":  round(entry, 8),
        "stop":   round(stop,  8),
        "target": round(target, 8),
        "rr":     rr,
        "atr":    round(atr_val, 8),
    }


def score_and_grade(sig: dict) -> tuple[int, str | None, list[str]]:
    points = 0
    fired: list[str] = []
    for key in SCALP_CHIP_ORDER:
        if sig.get(key):
            points += SCALP_POINTS[key]
            fired.append(key)
    grade = None
    for name, cutoff in SCALP_GRADE_CUTOFFS:
        if points >= cutoff:
            grade = name
            break
    return points, grade, fired


def build_chips(fired: list[str], sig: dict) -> list[str]:
    chips = []
    for key in fired:
        if key == "pullback" and sig.get("pullback_sma"):
            chips.append(f"PULLBACK TO SMA {sig['pullback_sma']}")
        else:
            chips.append(SCALP_CHIP_BASE[key])
    return chips


def narrative(symbol: str, sig: dict, lv: dict, asset_type: str, cur: str) -> str:
    direction = sig["direction"]
    sma_name  = f"SMA {sig['pullback_sma']}" if sig.get("pullback_sma") else "key SMA"
    h4        = "4h confirmed" if sig.get("4h_confirm") else "4h mixed"
    risk_pct  = abs(lv["entry"] - lv["stop"]) / lv["entry"] * 100 if lv["entry"] else 0
    return (
        f"{symbol} ({asset_type.upper()}) {direction} scalp setup on 1h. "
        f"Price bounced from {sma_name} ({h4}). "
        f"ATR stop at {cur}{lv['stop']:.4f} ({risk_pct:.1f}% risk), "
        f"target {cur}{lv['target']:.4f} ({lv['rr']:.1f}:1 R:R)."
    )
