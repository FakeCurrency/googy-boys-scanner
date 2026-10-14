"""Specs scanner — speculative volume-spike breakouts from a base.

The setup Vivek circled on JGH / EOS / PGO / BET: a beaten-down or sideways
small-cap that suddenly trades on a big VOLUME SPIKE and breaks out of its base
while the short SMAs (9/26/43) turn up, aimed at catching the move *as it
ignites* rather than after.

Volume spike + base + breakout are mandatory; the grade reflects how strong the
spike/breakout are. Uses the user's own indicators (SMA 9/26/43/200, RSI 14,
Vol 20). The trade-level and detail builders were inherited from the retired
Reversals scanner; they moved in here when that module was deleted as dead code
(2026-10-14, REFINE200 #119), byte-for-byte in behaviour.
"""

import numpy as np
import pandas as pd

from . import config
from .grading import grade_from_points
from .indicators import pivot_highs, pivot_lows, rsi, sma, supertrend

CHIP_ORDER = ["volume", "breakout", "reclaim", "base", "rsi"]


def evaluate(df: pd.DataFrame, max_price: float | None = None) -> dict | None:
    if df is None or len(df) < config.SPEC_MIN_HISTORY:
        return None
    close, high, vol = df["Close"], df["High"], df["Volume"]
    c = float(close.iloc[-1])
    if not np.isfinite(c) or c <= 0:
        return None
    # specs only: cheap, speculative names (skip the big/expensive stocks)
    if max_price is not None and c > max_price:
        return None

    s9, s26, s43, s200 = (sma(close, n) for n in (9, 26, 43, 200))
    s9l, s26l, s43l, s200l = (float(s.iloc[-1]) for s in (s9, s26, s43, s200))
    if not all(np.isfinite(v) and v > 0 for v in (s9l, s26l, s43l, s200l)):
        return None

    # ---- volume spike (the defining feature) -----------------------------
    vol_l = float(vol.iloc[-1])
    vol20 = float(vol.iloc[-config.SPEC_VOL_LOOKBACK - 1:-1].mean())
    vol5 = float(vol.iloc[-5:].mean())
    vol_recent_max = float(vol.iloc[-config.SPEC_VOL_RECENT:].max())
    if vol20 <= 0:
        return None
    spike_ratio = vol_recent_max / vol20
    if spike_ratio < config.SPEC_VOL_SPIKE:          # MANDATORY
        return None

    # ---- base / beaten-down context (room to run) ------------------------
    hi_win = float(high.iloc[-config.SPEC_BASE_HIGH_LOOKBACK:].max())
    off_high = (hi_win - c) / hi_win if hi_win > 0 else 0.0
    below200 = bool((close.iloc[-config.SPEC_BELOW200_LOOKBACK:]
                     < s200.iloc[-config.SPEC_BELOW200_LOOKBACK:]).any())
    if not (off_high >= config.SPEC_OFF_HIGH or below200):   # MANDATORY
        return None

    # ---- price action: breakout out of the base -------------------------
    a, b = config.SPEC_BREAKOUT_BASE
    base_high = float(high.iloc[-a:-b].max())
    breakout = bool(c >= base_high * config.SPEC_BREAKOUT_TOL)
    if not breakout:                                  # MANDATORY
        return None
    # momentum must be turning up, and price has reclaimed the mid SMA
    s9_rising = s9l > float(s9.iloc[-config.SPEC_SLOPE_BARS - 1])
    if not (c > s26l and s9_rising):                  # MANDATORY
        return None
    # not already chased far above the 9-SMA
    if c > s9l * (1 + config.SPEC_MAX_EXT):           # MANDATORY (skip the latecomers)
        return None

    new_high_long = bool(c >= float(high.iloc[-config.SPEC_NEWHIGH_LONG:-b].max()) * config.SPEC_BREAKOUT_TOL)

    # ---- fresh 9-over-26 reclaim (bonus) ---------------------------------
    above = (s9 > s26).to_numpy()
    recent_cross = False
    if above[-1]:
        win = above[-config.SPEC_CROSS_LOOKBACK - 1:]
        recent_cross = any(win[k] and not win[k - 1] for k in range(1, len(win)))
    reclaim = bool(above[-1] and (recent_cross or s9l > s26l))

    # ---- RSI turning up, not exhausted ----------------------------------
    rsi_ = rsi(close, config.SPEC_RSI_PERIOD)
    rsi_ma = sma(rsi_, config.SPEC_RSI_MA)
    rsil, rsimal = float(rsi_.iloc[-1]), float(rsi_ma.iloc[-1])
    lo, hi = config.SPEC_RSI_BAND
    rsi_up = rsil > float(rsi_.iloc[-3])
    rsi_sig = bool(rsil > rsimal and rsi_up and lo <= rsil <= hi)

    return {
        "close": c, "ok": True,
        "sma": {9: s9l, 26: s26l, 43: s43l, 200: s200l},
        "rsi": rsil, "rsi_ma": rsimal, "rsi_up": rsi_up,
        "vol": vol_l, "vol20": vol20, "vol5": vol5,
        "spike_ratio": spike_ratio,
        "off_high": off_high, "base_high": base_high, "below200": below200,
        "new_high_long": new_high_long,
        # keys the shared detail/chip helpers read:
        "reclaim": reclaim, "base": True, "volume": True,
        "breakout": breakout, "rsi_sig": rsi_sig,
        "cross_up": s9l > s26l,
    }


def score_and_grade(sig: dict) -> tuple[int, str | None, list[str]]:
    """Grade reflects how *strong* the spike + breakout are (max = SPEC_SCORE_MAX).

    volume   up to 4   (3x→2, 5x→+1, 8x→+1)
    breakout up to 3   (broke the base→2, also a fresh 3-month high→+1)
    reclaim       2    (fresh 9-over-26 reclaim, momentum confirmed)
    base     up to 1   (deep base ≥60% off the high)
    rsi           1    (RSI turning up through its line)
    """
    points, fired = 0, []
    r = sig["spike_ratio"]
    vol_pts = 2 + (1 if r >= 5 else 0) + (1 if r >= 8 else 0)
    points += vol_pts
    fired.append("volume")

    bo_pts = 2 + (1 if sig["new_high_long"] else 0)
    points += bo_pts
    fired.append("breakout")

    if sig["reclaim"]:
        points += 2
        fired.append("reclaim")
    if sig["off_high"] >= 0.60:
        points += 1
        fired.append("base")
    if sig["rsi_sig"]:
        points += 1
        fired.append("rsi")

    return points, grade_from_points(points, config.SPEC_GRADE_CUTOFFS), fired


def build_chips(fired: list[str], sig: dict) -> list[str]:
    chips: list[str] = []
    for key in fired:
        if key == "volume":
            chips.append(f"VOLUME {sig['spike_ratio']:.1f}× SPIKE")
        elif key == "breakout":
            chips.append("NEW 3-MONTH HIGH" if sig["new_high_long"] else "BASE BREAKOUT")
        elif key == "reclaim":
            chips.append("9 › 26 RECLAIM")
        elif key == "base":
            chips.append(f"DEEP BASE -{sig['off_high'] * 100:.0f}% OFF HIGH")
        elif key == "rsi":
            chips.append("RSI TURNING UP")
    return chips


def compute_levels(df: pd.DataFrame, sig: dict) -> dict:
    close = sig["close"]
    entry = close                         # enter on the reclaim / breakout
    swing_low = float(df["Low"].iloc[-config.SPEC_STOP_LOOKBACK:].min())
    stop = swing_low * (1 - config.STOP_BUFFER)
    if stop >= entry:
        stop = min(sig["sma"][26], entry * config.SPEC_STOP_FALLBACK_PCT)
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


def _pct(level: float, close: float) -> float:
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
    s = sig["sma"]
    ratio = sig["vol5"] / sig["vol20"] if sig["vol20"] else 0.0
    swing_low = float(df["Low"].iloc[-config.SPEC_STOP_LOOKBACK:].min())
    return {
        "setup_type": "spec",
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
        "structure": _structure(df),
        "risk_pct": round((lv["entry"] - lv["stop"]) / lv["entry"] * 100, 1) if lv["entry"] else 0.0,
        "spike_ratio": round(sig["spike_ratio"], 1),
        "new_high_long": sig["new_high_long"],
    }


def spec_narrative(symbol: str, sig: dict, lv: dict, detail: dict, cur: str = "$") -> str:
    p = [f"{symbol} just fired a speculative volume-spike breakout — volume hit "
         f"{sig['spike_ratio']:.1f}× its 20-day average as price broke out of its base."]
    if sig["off_high"] >= config.SPEC_OFF_HIGH:
        p.append(f"It's coming off a base {sig['off_high'] * 100:.0f}% below the 1-year high, "
                 "so there's room to run.")
    if sig["new_high_long"]:
        p.append("The breakout cleared a fresh 3-month high.")
    if sig["reclaim"]:
        p.append("The 9-SMA has reclaimed the 26 — short-term momentum is up.")
    if sig["rsi_sig"]:
        p.append("RSI has turned up through its signal line.")
    p.append("These are high-risk speculative names — they move fast both ways, so "
             "size small and respect the stop.")
    p.append(f"Trade idea: entry {cur}{lv['entry']:.4f}, stop {cur}{lv['stop']:.4f}, "
             f"target {cur}{lv['target']:.4f} ({lv['rr']:.2f}:1) — then trail it.")
    return " ".join(p)
