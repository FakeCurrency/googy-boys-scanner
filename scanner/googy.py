"""Googy Scan — consolidation breakout scanner.

Finds stocks where price has just broken above the highest high of the last
N bars, confirmed by RSI momentum and at least one SMA trend filter.

Unlike the Pullback scanner (continuation in an uptrend) or the Reversal
scanner (9-over-26 reclaim from a downtrend), Googy Scan focuses on the raw
breakout from a range/consolidation — more aggressive, more tolerant of lower
liquidity names, no beaten-down requirement, no price cap.

Mandatory gates:
  - Price > highest high of last GOOGY_BREAKOUT_LOOKBACK bars (the breakout)
  - RSI(14) > 50 (basic momentum — no weak/exhausted breakouts)
  - Price > SMA(20) OR SMA(50) (at least one trend filter)

Scoring out of 12:
  breakout_strength  up to 3   (how far above the range high?)
  volume             up to 3   (1.5x avg → +1, 2.5x → +2, 4x → +3)
  rsi_strength       up to 2   (RSI 50-60 → +1, RSI > 60 → +2)
  trend_alignment    up to 2   (above SMA50 → +1, SMA20 > SMA50 → +1)
  range_quality      up to 2   (tight range → +1, ≥10 bars consolidation → +1)

Low-liquidity names still appear but carry a LOW LIQUIDITY chip.
"""

import numpy as np
import pandas as pd

from . import config
from .grading import grade_from_points
from .indicators import pivot_highs, rsi, sma, supertrend


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
    if not (np.isfinite(s20l) and np.isfinite(s50l) and s20l > 0 and s50l > 0):
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
    range_high = float(range_slice["High"].max())
    range_low = float(range_slice["Low"].min())

    # ── Mandatory gates ───────────────────────────────────────────────────────
    # 1. Price must close above the range high (the actual breakout)
    if c <= range_high:
        return None

    # 2. RSI must be above 50 (momentum, not a fakeout)
    if rsil < config.GOOGY_RSI_MIN:
        return None

    # 3. Price must be above at least one SMA (trend filter)
    if c < s20l and c < s50l:
        return None

    # ── Breakout magnitude ────────────────────────────────────────────────────
    bo_pct = (c - range_high) / range_high if range_high > 0 else 0.0

    # ── Range quality ─────────────────────────────────────────────────────────
    range_span = (range_high - range_low) / range_high if range_high > 0 else 1.0
    tight_range = range_span < config.GOOGY_RANGE_TIGHT_PCT

    # Count consecutive bars of consolidation (bars where close was <= range_high)
    consol_bars = 0
    for i in range(2, min(lookback + 2, len(df))):
        if float(close.iloc[-(i)]) <= range_high:
            consol_bars += 1
        else:
            break

    return {
        "close": c, "ok": True,
        "sma20": s20l, "sma50": s50l,
        "rsi": rsil,
        "vol": vol_l, "vol_avg": vol_avg, "vol_ratio": vol_ratio,
        "range_high": range_high, "range_low": range_low,
        "bo_pct": bo_pct,
        "tight_range": tight_range,
        "consol_bars": consol_bars,
        "range_span_pct": round(range_span * 100, 1),
        # flags for scoring
        "above_sma50": c > s50l,
        "sma20_above_sma50": s20l > s50l,
        "volume_expanding": vol_ratio >= config.GOOGY_VOL_MULT,
        "volume_strong": vol_ratio >= config.GOOGY_VOL_STRONG,
        "volume_surge": vol_ratio >= config.GOOGY_VOL_SURGE,
        "rsi_strong": rsil >= 60,
    }


def score_and_grade(sig: dict) -> tuple[int, str | None, list[str]]:
    """Score the breakout setup. Max = GOOGY_SCORE_MAX (12)."""
    points = 0
    fired = []

    # breakout_strength: how much above the range high? (0–3 pts)
    bo = sig["bo_pct"]
    if bo >= config.GOOGY_BREAKOUT_STR_PCT:
        points += 3; fired.append("breakout_surge")
    elif bo >= config.GOOGY_BREAKOUT_MOD_PCT:
        points += 2; fired.append("breakout_strong")
    elif bo > 0.005:
        points += 1; fired.append("breakout")

    # volume (0–3 pts)
    if sig["volume_surge"]:
        points += 3; fired.append("volume_surge")
    elif sig["volume_strong"]:
        points += 2; fired.append("volume_strong")
    elif sig["volume_expanding"]:
        points += 1; fired.append("volume")

    # rsi_strength (0–2 pts)
    if sig["rsi_strong"]:
        points += 2; fired.append("rsi_strong")
    else:
        points += 1; fired.append("rsi")

    # trend_alignment (0–2 pts)
    if sig["above_sma50"]:
        points += 1; fired.append("above_sma50")
    if sig["sma20_above_sma50"]:
        points += 1; fired.append("sma_aligned")

    # range_quality (0–2 pts)
    if sig["tight_range"]:
        points += 1; fired.append("tight_range")
    if sig["consol_bars"] >= config.GOOGY_RANGE_MIN_BARS:
        points += 1; fired.append("consolidation")

    return points, grade_from_points(points, config.GOOGY_GRADE_CUTOFFS), fired


def build_chips(fired: list[str], sig: dict) -> list[str]:
    chips = []
    for key in fired:
        if key == "breakout_surge":
            chips.append(f"BREAKOUT +{sig['bo_pct'] * 100:.1f}% ABOVE RANGE")
        elif key == "breakout_strong":
            chips.append(f"CLEAN BREAKOUT +{sig['bo_pct'] * 100:.1f}%")
        elif key == "breakout":
            chips.append(f"RANGE BREAKOUT +{sig['bo_pct'] * 100:.1f}%")
        elif key == "volume_surge":
            chips.append(f"VOLUME SURGE {sig['vol_ratio']:.1f}×")
        elif key == "volume_strong":
            chips.append(f"VOLUME EXPANSION {sig['vol_ratio']:.1f}×")
        elif key == "volume":
            chips.append(f"VOLUME {sig['vol_ratio']:.1f}× AVG")
        elif key == "rsi_strong":
            chips.append(f"RSI {sig['rsi']:.0f} STRONG MOMENTUM")
        elif key == "rsi":
            chips.append(f"RSI {sig['rsi']:.0f} BULLISH")
        elif key == "above_sma50":
            chips.append("ABOVE SMA 50")
        elif key == "sma_aligned":
            chips.append("SMA 20 › 50 BULLISH")
        elif key == "tight_range":
            chips.append(f"TIGHT BASE ({sig['range_span_pct']:.0f}% RANGE)")
        elif key == "consolidation":
            chips.append(f"{sig['consol_bars']}+ BAR CONSOLIDATION")
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
        # Use whichever is closer and gives at least 1.5:1 RR
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


def _pct(level: float, close: float) -> float:
    return round((level - close) / close * 100, 1) if close else 0.0


def build_detail(df: pd.DataFrame, sig: dict, lv: dict) -> dict:
    """Build the expanded detail payload for the frontend detail panel."""
    close = sig["close"]
    swing_low = float(df["Low"].iloc[-config.GOOGY_STOP_LOOKBACK:].min())
    return {
        "setup_type": "googy",
        "sma20": round(sig["sma20"], 8), "sma20_pct": _pct(sig["sma20"], close),
        "sma50": round(sig["sma50"], 8), "sma50_pct": _pct(sig["sma50"], close),
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
        "consol_bars": sig["consol_bars"],
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
    p.append(
        f"{symbol} has broken out above its {config.GOOGY_BREAKOUT_LOOKBACK}-bar range high "
        f"({cur}{sig['range_high']:.4f}) by {sig['bo_pct'] * 100:.1f}%."
    )
    if sig["volume_surge"]:
        p.append(f"Volume surged to {sig['vol_ratio']:.1f}× its 20-day average — strong institutional participation.")
    elif sig["volume_strong"]:
        p.append(f"Volume is running at {sig['vol_ratio']:.1f}× its average — solid confirmation of the move.")
    elif sig["volume_expanding"]:
        p.append(f"Volume is expanding at {sig['vol_ratio']:.1f}× average — the breakout has some participation.")
    else:
        p.append("Volume is below average — watch for a re-test of the breakout level with better volume.")

    if sig["rsi_strong"]:
        p.append(f"RSI is at {sig['rsi']:.0f} — momentum is genuinely strong, not yet overbought.")
    else:
        p.append(f"RSI at {sig['rsi']:.0f} is above 50 — momentum is with the bulls.")

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
        f"(measured move — {lv['rr']:.2f}:1) — then trail it."
    )
    return " ".join(p)
