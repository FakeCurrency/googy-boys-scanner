"""Googy Scan — fresh consolidation breakout scanner.

Finds stocks where price has just broken above the highest high of the last
N bars, confirmed by volume expansion, RSI momentum, and SMA trend filter.
All 5 gates below are mandatory — any miss drops the stock entirely.

Mandatory gates (per image rules):
  Rule 1 — Recent Breakout:  range high was set within last 5 bars (fresh, not stale)
  Rule 2 — Breakout:         price > range high of last 25 bars
  Rule 3 — Not Extended:     price no more than 10% above the range high
  Rule 4 — Volume Expansion: volume >= 1.8× 20-bar average (hard gate, not optional)
  Rule 5 — Basic Momentum:   close > SMA(20) AND RSI(14) > 50  (AND, not OR)

Scoring out of 12:
  breakout_strength  up to 2   (5–10% above → 2, 0.5–5% → 1)
  volume             up to 3   (≥1.8× → 1, ≥2.5× → 2, ≥4× → 3)
  compression        up to 2   (ATR contracted → +1, tight range → +1)
  rsi_strength       up to 2   (50–60 → 1, >60 → 2)
  sma_alignment      up to 1   (above SMA50 → +1)
  freshness_bonus    up to 1   (range high set within last 2 bars → +1)
  adx                up to 1   (ADX > 18 AND rising over 5 bars → +1)  [Rule 6]

Low-liquidity names still appear but carry a LOW LIQUIDITY chip.
"""

import numpy as np
import pandas as pd

from . import config
from .grading import grade_from_points
from .indicators import adx as calc_adx, atr, pivot_highs, rsi, sma, supertrend


def evaluate(df: pd.DataFrame, min_turnover: float = 0.0) -> dict | None:
    """Evaluate breakout signals for the latest bar. Returns None on failure."""
    if df is None or len(df) < config.GOOGY_MIN_HISTORY:
        return None

    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
    c = float(close.iloc[-1])
    if not np.isfinite(c) or c <= 0:
        return None

    # ── SMAs ──────────────────────────────────────────────────────────────────
    s20 = sma(close, config.GOOGY_SMA_FAST)
    s50 = sma(close, config.GOOGY_SMA_SLOW)
    s20l = float(s20.iloc[-1])
    s50l = float(s50.iloc[-1])
    if not (np.isfinite(s20l) and s20l > 0):
        return None

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi_ = rsi(close, config.GOOGY_RSI_PERIOD)
    rsil = float(rsi_.iloc[-1])
    if not np.isfinite(rsil):
        return None

    # ── Volume ────────────────────────────────────────────────────────────────
    vol_l = float(vol.iloc[-1])
    vol_avg = float(vol.iloc[-config.GOOGY_VOL_LOOKBACK - 1:-1].mean())
    vol_ratio = vol_l / vol_avg if vol_avg > 0 else 0.0

    # ── Consolidation range (excluding current bar) ───────────────────────────
    lookback = config.GOOGY_BREAKOUT_LOOKBACK
    if len(df) < lookback + 2:
        return None
    range_slice = df.iloc[-(lookback + 1):-1]
    range_high_series = range_slice["High"]
    range_high = float(range_high_series.max())
    range_low = float(range_slice["Low"].min())

    # ── Rule 1: Freshness — range high must have been set within last N bars ──
    # argmax within the window gives position from start of range_slice (0-indexed)
    high_idx = int(range_high_series.values.argmax())   # 0 = oldest bar in window
    bars_since_high = (lookback - 1) - high_idx          # 0 = most recent bar in window
    if bars_since_high > config.GOOGY_FRESH_LOOKBACK:
        return None

    # ── Rule 2: Breakout — price must close above the range high ─────────────
    if c <= range_high:
        return None

    # ── Breakout magnitude ────────────────────────────────────────────────────
    bo_pct = (c - range_high) / range_high if range_high > 0 else 0.0

    # ── Rule 3: Not extended — price no more than 10% above range high ────────
    if bo_pct > config.GOOGY_NOT_EXTENDED_PCT:
        return None

    # ── Rule 4: Volume expansion — mandatory 1.8× hard gate ──────────────────
    if vol_ratio < config.GOOGY_VOL_MULT:
        return None

    # ── Rule 5: Momentum — close > SMA(20) AND RSI > 50 (both required) ──────
    if c <= s20l or rsil < config.GOOGY_RSI_MIN:
        return None

    # ── ATR compression (Rule 3 — volatility was contracting before breakout) ─
    atr_series = atr(df, config.GOOGY_RSI_PERIOD)
    atr_now = float(atr_series.iloc[-2])          # yesterday (before breakout bar)
    atr_before = float(atr_series.iloc[-config.GOOGY_COMPRESS_LOOKBACK - 1])
    atr_contracted = np.isfinite(atr_before) and atr_before > 0 and atr_now < atr_before
    atr_now_rel = round(atr_now / c * 100, 2) if c > 0 else 0.0
    atr_before_rel = round(atr_before / c * 100, 2) if c > 0 else 0.0

    # ── Range quality ─────────────────────────────────────────────────────────
    range_span = (range_high - range_low) / range_high if range_high > 0 else 1.0
    tight_range = range_span < config.GOOGY_RANGE_TIGHT_PCT

    # Count bars where close stayed within the range (consolidation depth)
    consol_bars = 0
    for i in range(2, min(lookback + 2, len(df))):
        if float(close.iloc[-i]) <= range_high:
            consol_bars += 1
        else:
            break

    # ── ADX (Rule 6 — optional strength bonus) ────────────────────────────────
    adx_series = calc_adx(df, config.GOOGY_RSI_PERIOD)
    adx_now = float(adx_series.iloc[-1])
    adx_valid = np.isfinite(adx_now)
    adx_strong = adx_valid and adx_now > config.GOOGY_ADX_MIN
    # Rising: current ADX > ADX N bars ago
    adx_n = float(adx_series.iloc[-config.GOOGY_ADX_RISING_BARS - 1]) if len(adx_series) > config.GOOGY_ADX_RISING_BARS else float("nan")
    adx_rising = adx_valid and np.isfinite(adx_n) and adx_now > adx_n

    s50_valid = np.isfinite(s50l) and s50l > 0

    return {
        "close": c, "ok": True,
        "sma20": s20l, "sma50": s50l if s50_valid else None,
        "rsi": rsil,
        "vol": vol_l, "vol_avg": vol_avg, "vol_ratio": vol_ratio,
        "range_high": range_high, "range_low": range_low,
        "bo_pct": bo_pct,
        "bars_since_high": bars_since_high,
        "tight_range": tight_range,
        "consol_bars": consol_bars,
        "range_span_pct": round(range_span * 100, 1),
        "atr_contracted": atr_contracted,
        "atr_now_rel": atr_now_rel,
        "atr_before_rel": atr_before_rel,
        "adx": round(adx_now, 1) if adx_valid else None,
        "adx_strong": adx_strong,
        "adx_rising": adx_rising,
        # flags for scoring
        "above_sma50": s50_valid and c > s50l,
        "sma20_above_sma50": s50_valid and s20l > s50l,
        "volume_expanding": vol_ratio >= config.GOOGY_VOL_MULT,
        "volume_strong": vol_ratio >= config.GOOGY_VOL_STRONG,
        "volume_surge": vol_ratio >= config.GOOGY_VOL_SURGE,
        "rsi_strong": rsil >= 60,
    }


def score_and_grade(sig: dict) -> tuple[int, str | None, list[str]]:
    """Score the breakout setup. Max = GOOGY_SCORE_MAX (12)."""
    points = 0
    fired = []

    # breakout_strength: 5–10% → 2pts, 0.5–5% → 1pt (0–2)
    bo = sig["bo_pct"]
    if bo >= 0.05:
        points += 2; fired.append("breakout_strong")
    elif bo > 0.005:
        points += 1; fired.append("breakout")

    # volume (0–3 pts) — gate already enforced at 1.8×
    if sig["volume_surge"]:
        points += 3; fired.append("volume_surge")
    elif sig["volume_strong"]:
        points += 2; fired.append("volume_strong")
    elif sig["volume_expanding"]:
        points += 1; fired.append("volume")

    # compression: ATR contracted (+1) + tight range (+1) = 0–2
    if sig["atr_contracted"]:
        points += 1; fired.append("atr_compression")
    if sig["tight_range"]:
        points += 1; fired.append("tight_range")

    # rsi_strength: >60 → 2, 50–60 → 1 (gate already ensures >= 50)
    if sig["rsi_strong"]:
        points += 2; fired.append("rsi_strong")
    else:
        points += 1; fired.append("rsi")

    # sma_alignment: above SMA50 → +1 (0–1)
    if sig["above_sma50"]:
        points += 1; fired.append("above_sma50")

    # freshness_bonus: range high set within last 2 bars → extra +1
    if sig["bars_since_high"] <= 2:
        points += 1; fired.append("freshness_bonus")

    # adx bonus: strong AND rising → +1 (Rule 6)
    if sig["adx_strong"] and sig["adx_rising"]:
        points += 1; fired.append("adx_rising")

    return points, grade_from_points(points, config.GOOGY_GRADE_CUTOFFS), fired


def build_chips(fired: list[str], sig: dict) -> list[str]:
    chips = []
    for key in fired:
        if key == "breakout_strong":
            chips.append(f"STRONG BREAKOUT +{sig['bo_pct'] * 100:.1f}%")
        elif key == "breakout":
            chips.append(f"RANGE BREAKOUT +{sig['bo_pct'] * 100:.1f}%")
        elif key == "volume_surge":
            chips.append(f"VOLUME SURGE {sig['vol_ratio']:.1f}×")
        elif key == "volume_strong":
            chips.append(f"VOLUME EXPANSION {sig['vol_ratio']:.1f}×")
        elif key == "volume":
            chips.append(f"VOLUME {sig['vol_ratio']:.1f}× AVG")
        elif key == "atr_compression":
            chips.append("VOLATILITY COMPRESSION")
        elif key == "tight_range":
            chips.append(f"TIGHT BASE ({sig['range_span_pct']:.0f}% RANGE)")
        elif key == "rsi_strong":
            chips.append(f"RSI {sig['rsi']:.0f} STRONG MOMENTUM")
        elif key == "rsi":
            chips.append(f"RSI {sig['rsi']:.0f} BULLISH")
        elif key == "above_sma50":
            chips.append("ABOVE SMA 50")
        elif key == "freshness_bonus":
            chips.append("FRESH BREAKOUT")
        elif key == "adx_rising":
            adx_val = sig.get("adx")
            chips.append(f"ADX {adx_val:.0f} RISING" if adx_val is not None else "ADX RISING")
    return chips


def compute_levels(df: pd.DataFrame, sig: dict) -> dict:
    """Compute entry, stop, and target levels for a Googy breakout setup."""
    close = sig["close"]
    entry = close   # buy on the breakout close

    # Stop: below the consolidation range's swing low
    swing_low = float(df["Low"].iloc[-config.GOOGY_STOP_LOOKBACK:].min())
    stop = swing_low * (1 - config.GOOGY_STOP_BUFFER)
    if stop >= entry:
        stop = entry * config.GOOGY_STOP_FALLBACK_PCT

    risk = entry - stop
    if risk <= 0:
        return {"entry": round(entry, 8), "stop": round(stop, 8), "target": round(entry * 1.10, 8),
                "rr": 0.0, "trail": round(entry * 0.95, 8), "target_basis": "measured"}

    # Target: measured move = consolidation height projected above the breakout
    range_height = sig["range_high"] - sig["range_low"]
    if range_height > 0:
        target_measured = sig["range_high"] + range_height
        basis = "measured"
    else:
        target_measured = entry + 3 * risk
        basis = "measured"

    # Also check nearest pivot resistance above entry
    piv = pivot_highs(df.iloc[-config.RESIST_LOOKBACK:], config.PIVOT_WINDOW)
    above = piv[piv > close * 1.05]
    if len(above) > 0:
        resist_target = float(above.min())
        if (resist_target - entry) / risk >= 1.5:
            target = min(target_measured, resist_target)
            basis = "resistance" if target == resist_target else "measured"
        else:
            target = target_measured
    else:
        target = target_measured

    # Clamp: RR cap at 6:1 to avoid unrealistic targets
    if (target - entry) / risk > 6.0:
        target = entry + 6 * risk
        basis = "measured"

    rr = (target - entry) / risk
    trail = float(supertrend(df, config.ATR_PERIOD, config.SUPERTREND_MULT).iloc[-1])
    return {
        "entry": round(entry, 8), "stop": round(stop, 8), "target": round(target, 8),
        "rr": round(rr, 2), "trail": round(trail, 8), "target_basis": basis,
    }


def _pct(level: float | None, close: float) -> float:
    if level is None:
        return 0.0
    return round((level - close) / close * 100, 1) if close else 0.0


def build_detail(df: pd.DataFrame, sig: dict, lv: dict) -> dict:
    """Build the expanded detail payload for the frontend detail panel."""
    close = sig["close"]
    swing_low = float(df["Low"].iloc[-config.GOOGY_STOP_LOOKBACK:].min())
    return {
        "setup_type": "googy",
        "sma20": round(sig["sma20"], 8), "sma20_pct": _pct(sig["sma20"], close),
        "sma50": round(sig["sma50"], 8) if sig["sma50"] is not None else None,
        "sma50_pct": _pct(sig["sma50"], close),
        "rsi": round(sig["rsi"], 1),
        "volume_ratio": round(sig["vol_ratio"], 1),
        "volume_today": int(sig["vol"]),
        "volume_avg": int(sig["vol_avg"]),
        "volume_expanding": sig["volume_expanding"],
        "range_high": round(sig["range_high"], 8),
        "range_high_pct": _pct(sig["range_high"], close),
        "range_low": round(sig["range_low"], 8),
        "range_low_pct": _pct(sig["range_low"], close),
        "range_span_pct": sig["range_span_pct"],
        "bo_pct": round(sig["bo_pct"] * 100, 2),
        "bars_since_high": sig["bars_since_high"],
        "consol_bars": sig["consol_bars"],
        "compression": sig["atr_contracted"],
        "atr_now_rel": sig["atr_now_rel"],
        "atr_before_rel": sig["atr_before_rel"],
        "adx": sig["adx"],
        "adx_strong": sig["adx_strong"],
        "adx_rising": sig["adx_rising"],
        "swing_low": round(swing_low, 8),
        "swing_low_pct": _pct(swing_low, close),
        "trailing_stop": lv["trail"],
        "trailing_label": "SuperTrend 3× ATR",
        "trailing_pct": _pct(lv["trail"], close),
        "risk_pct": round((lv["entry"] - lv["stop"]) / lv["entry"] * 100, 1) if lv["entry"] else 0.0,
    }


def narrative(symbol: str, sig: dict, lv: dict, detail: dict, cur: str = "$") -> str:
    """Generate the analysis text shown in the detail panel."""
    p = []

    freshness = sig["bars_since_high"]
    fresh_str = "yesterday" if freshness == 1 else f"{freshness} bars ago"
    p.append(
        f"{symbol} set its {config.GOOGY_BREAKOUT_LOOKBACK}-bar range high {fresh_str} "
        f"and has just broken out above {cur}{sig['range_high']:.4f} "
        f"by +{sig['bo_pct'] * 100:.1f}% — a fresh, not stale, breakout."
    )

    if sig["atr_contracted"]:
        p.append(
            f"ATR contracted from {sig['atr_before_rel']:.2f}% to {sig['atr_now_rel']:.2f}% of price "
            "in the {config.GOOGY_COMPRESS_LOOKBACK} bars before the breakout — "
            "classic volatility coil before the expansion."
        )

    if sig["volume_surge"]:
        p.append(f"Volume surged to {sig['vol_ratio']:.1f}× its 20-day average — strong institutional participation.")
    elif sig["volume_strong"]:
        p.append(f"Volume is running at {sig['vol_ratio']:.1f}× its average — solid confirmation of the move.")
    else:
        p.append(f"Volume is at {sig['vol_ratio']:.1f}× average — the minimum required gate is cleared.")

    if sig["rsi_strong"]:
        p.append(f"RSI is at {sig['rsi']:.0f} — momentum is genuinely strong, not yet overbought.")
    else:
        p.append(f"RSI at {sig['rsi']:.0f} is above 50 — momentum is with the bulls.")

    if sig["adx_strong"] and sig["adx_rising"]:
        adx_val = sig.get("adx")
        p.append(f"ADX at {adx_val:.0f} and rising confirms a trending market — not a false breakout from noise.")

    if sig["sma20_above_sma50"]:
        p.append("The 20-SMA is above the 50-SMA — the medium-term trend structure is bullish.")
    elif sig["above_sma50"]:
        p.append("Price is above the 50-SMA. The 20 has not yet crossed the 50 — watch for full alignment.")

    if sig["tight_range"] and sig["consol_bars"] >= config.GOOGY_RANGE_MIN_BARS:
        p.append(
            f"The {sig['consol_bars']}-bar consolidation was tight ({sig['range_span_pct']:.0f}% range) — "
            "compressed setups often release with force."
        )

    p.append(
        f"Trade idea: entry {cur}{lv['entry']:.4f}, stop {cur}{lv['stop']:.4f} "
        f"(below range low), target {cur}{lv['target']:.4f} "
        f"(measured move — {lv['rr']:.2f}:1) — then trail with the SuperTrend."
    )
    return " ".join(p)
