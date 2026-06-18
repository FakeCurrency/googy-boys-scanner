"""Intraday scalp scanner — 1h bars.

Signal engine (OM Multi-Indicator style):
  1. TTM Squeeze — BB(20,2) compresses inside KC(20,1.5×ATR); fires when BB breaks out
  2. Squeeze momentum direction + acceleration (the histogram bars)
  3. Nearest 1h pivot support / resistance levels (auto-drawn horizontal lines)
  4. Volume expansion confirming the breakout

Stop : 1.5× ATR(14 on 1h) below entry (long) / above entry (short)
Target: 3× ATR → automatic 2:1 R:R
"""

import numpy as np
import pandas as pd

from .indicators import atr

# ── TTM Squeeze parameters ─────────────────────────────────────────────────────
SQ_PERIOD        = 20    # BB and KC lookback
SQ_BB_MULT       = 2.0   # Bollinger Band std multiplier
SQ_KC_MULT       = 1.5   # Keltner Channel ATR multiplier
SQ_MOM_PERIOD    = 12    # momentum linear-regression period
SQ_FIRE_LOOKBACK = 4     # squeeze must have been ON within this many bars to count as "just fired"

# ── Pivot S/R ──────────────────────────────────────────────────────────────────
PIVOT_WINDOW   = 3       # bars each side that define a pivot high/low
PIVOT_LOOKBACK = 60      # only search this many recent 1h bars

# ── Stop / Target ──────────────────────────────────────────────────────────────
SCALP_ATR_PERIOD      = 14
SCALP_ATR_STOP_MULT   = 1.5
SCALP_ATR_TARGET_MULT = 3.0
SCALP_MIN_BARS        = 65   # warm-up for SQ_PERIOD + SQ_MOM_PERIOD + ATR

# ── Scoring ────────────────────────────────────────────────────────────────────
SCALP_POINTS = {
    "squeeze_fired":  3,   # squeeze just fired in trade direction — the trigger
    "squeeze_on":     1,   # squeeze currently ON (market coiling, pressure building)
    "momentum_dir":   2,   # momentum positive (long) / negative (short)
    "momentum_accel": 1,   # histogram expanding (momentum strengthening)
    "pivot_ok":       2,   # price at a key pivot level (support for long, resistance for short)
    "volume":         1,   # volume expansion vs 20-bar average
}
SCALP_SCORE_MAX  = sum(SCALP_POINTS.values())  # 10
SCALP_GRADE_CUTOFFS = [("A+", 8), ("A", 6), ("B", 4), ("C", 2)]

SCALP_CHIP_ORDER = ["squeeze_fired", "squeeze_on", "momentum_dir", "momentum_accel", "pivot_ok", "volume"]
SCALP_CHIP_BASE  = {
    "squeeze_fired":  "SQUEEZE FIRED",
    "squeeze_on":     "SQUEEZE BUILDING",
    "momentum_dir":   "MOMENTUM ALIGNED",
    "momentum_accel": "MOMENTUM ACCELERATING",
    "pivot_ok":       "AT KEY LEVEL",
    "volume":         "VOLUME EXPANSION",
}


# ── Internal helpers ───────────────────────────────────────────────────────────

def _linreg(series: pd.Series, n: int) -> pd.Series:
    """Rolling linear regression value at the last bar of each window."""
    def _fit(x: np.ndarray) -> float:
        t = np.arange(len(x), dtype=float)
        c = np.polyfit(t, x, 1)
        return float(c[0] * (len(x) - 1) + c[1])
    return series.rolling(n).apply(_fit, raw=True)


def _squeeze_signals(df: pd.DataFrame) -> dict:
    """
    TTM Squeeze (LazyBear / John Carter style).
    squeeze ON  = BB entirely inside KC (market coiling, volatility contracting)
    squeeze OFF = BB broke out of KC (fire — expansion begins)
    momentum    = linear regression of (close − midpoint) — the histogram bars
    """
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]

    # Bollinger Bands (20, 2.0)
    bb_mid   = close.rolling(SQ_PERIOD).mean()
    bb_std   = close.rolling(SQ_PERIOD).std(ddof=0)
    bb_upper = bb_mid + SQ_BB_MULT * bb_std
    bb_lower = bb_mid - SQ_BB_MULT * bb_std

    # Keltner Channels (20-period SMA ± 1.5 × ATR)
    kc_mid   = close.rolling(SQ_PERIOD).mean()
    kc_range = atr(df, SQ_PERIOD) * SQ_KC_MULT
    kc_upper = kc_mid + kc_range
    kc_lower = kc_mid - kc_range

    # Squeeze ON = BB entirely inside KC
    sq_on = (bb_upper < kc_upper) & (bb_lower > kc_lower)

    # Momentum = linreg of (close − midpoint of [HH/LL midpoint + SMA])
    hh  = high.rolling(SQ_PERIOD).max()
    ll  = low.rolling(SQ_PERIOD).min()
    val = close - ((hh + ll) / 2 + bb_mid) / 2
    mom = _linreg(val, SQ_MOM_PERIOD)

    return {"sq_on": sq_on, "mom": mom, "bb_mid": bb_mid}


def _find_pivot_levels(df: pd.DataFrame, last: float):
    """
    Find the nearest pivot support below and pivot resistance above current price.
    Returns (nearest_support, nearest_resistance) — either may be None.
    Broken resistance acts as support and vice-versa.
    """
    hi = df["High"].iloc[-PIVOT_LOOKBACK:]
    lo = df["Low"].iloc[-PIVOT_LOOKBACK:]
    n  = len(hi)

    supports:    list[float] = []
    resistances: list[float] = []

    for i in range(PIVOT_WINDOW, n - PIVOT_WINDOW):
        h = float(hi.iloc[i])
        l = float(lo.iloc[i])

        is_pivot_high = h == float(hi.iloc[i - PIVOT_WINDOW : i + PIVOT_WINDOW + 1].max())
        is_pivot_low  = l == float(lo.iloc[i - PIVOT_WINDOW : i + PIVOT_WINDOW + 1].min())

        if is_pivot_high:
            if h > last:
                resistances.append(h)      # unbroken resistance above
            else:
                supports.append(h)         # broken resistance = flipped support

        if is_pivot_low:
            if l < last:
                supports.append(l)         # unbroken support below
            else:
                resistances.append(l)      # broken support = flipped resistance

    nearest_support    = max(supports)    if supports    else None
    nearest_resistance = min(resistances) if resistances else None
    return nearest_support, nearest_resistance


# ── Public API ─────────────────────────────────────────────────────────────────

def evaluate(df: pd.DataFrame, direction: str = "long") -> dict | None:
    """Evaluate a single instrument for a scalp setup.  Returns a signal dict or None."""
    if df is None or len(df) < SCALP_MIN_BARS:
        return None

    # Strip timezone — rolling / resampling ops need tz-naive index
    if getattr(df.index, "tz", None) is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)

    close = df["Close"]
    last  = float(close.iloc[-1])
    if not np.isfinite(last) or last <= 0:
        return None

    # ── Squeeze signals ────────────────────────────────────────────────────────
    sigs  = _squeeze_signals(df)
    sq_on = sigs["sq_on"]
    mom   = sigs["mom"]

    mom_now  = float(mom.iloc[-1])
    mom_prev = float(mom.iloc[-2])
    if not (np.isfinite(mom_now) and np.isfinite(mom_prev)):
        return None

    # Direction gate: price above (long) / below (short) the BB midline (SMA 20).
    # More stable than momentum sign — allows transitioning / coiling setups.
    bb_mid_now = float(sigs["bb_mid"].iloc[-1])
    if not np.isfinite(bb_mid_now) or bb_mid_now <= 0:
        return None
    if direction == "long"  and last < bb_mid_now:
        return None
    if direction == "short" and last > bb_mid_now:
        return None

    # Squeeze fired = was compressed recently, now released
    sq_currently_on = bool(sq_on.iloc[-1])
    sq_was_on       = bool(sq_on.iloc[-(SQ_FIRE_LOOKBACK + 1):-1].any())
    sq_fired        = (not sq_currently_on) and sq_was_on

    # ── Momentum direction ─────────────────────────────────────────────────────
    mom_dir = (mom_now > 0) if direction == "long" else (mom_now < 0)

    # ── Momentum acceleration (histogram expanding in trade direction) ──────────
    mom_accel = (mom_now > mom_prev) if direction == "long" else (mom_now < mom_prev)

    # ── Volume expansion ───────────────────────────────────────────────────────
    vol     = float(df["Volume"].iloc[-1])
    avg_vol = float(df["Volume"].iloc[-21:-1].mean())
    volume  = avg_vol > 0 and vol >= 1.3 * avg_vol

    # ── Pivot S/R ──────────────────────────────────────────────────────────────
    nearest_sup, nearest_res = _find_pivot_levels(df, last)

    if direction == "long":
        # Price at or just above a support level
        pivot_ok = nearest_sup is not None and last >= nearest_sup * 0.98
    else:
        # Price at or just below a resistance level
        pivot_ok = nearest_res is not None and last <= nearest_res * 1.02

    return {
        "direction":          direction,
        "close":              round(last, 8),
        "squeeze_fired":      sq_fired,
        "squeeze_on":         sq_currently_on,
        "sq_on":              sq_currently_on,
        "momentum_dir":       mom_dir,
        "momentum_accel":     mom_accel,
        "pivot_ok":           pivot_ok,
        "volume":             volume,
        "mom_val":            round(mom_now, 6),
        "nearest_support":    round(nearest_sup, 6)  if nearest_sup  is not None else None,
        "nearest_resistance": round(nearest_res, 6)  if nearest_res  is not None else None,
    }


def compute_levels(df: pd.DataFrame, sig: dict) -> dict:
    """ATR-based stop and 2:1 target from entry."""
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
        label = SCALP_CHIP_BASE[key]
        if key == "pivot_ok":
            if sig["direction"] == "long" and sig.get("nearest_support") is not None:
                label = f"SUPPORT @ {sig['nearest_support']:.4f}"
            elif sig["direction"] == "short" and sig.get("nearest_resistance") is not None:
                label = f"RESISTANCE @ {sig['nearest_resistance']:.4f}"
        chips.append(label)
    return chips


def narrative(symbol: str, sig: dict, lv: dict, asset_type: str, cur: str) -> str:
    direction = sig["direction"]
    if sig.get("squeeze_fired"):
        sq_txt = "squeeze fired"
    elif sig.get("sq_on"):
        sq_txt = "squeeze building (coiling)"
    else:
        sq_txt = "squeeze released"

    mom_txt  = f"momentum {'▲' if direction == 'long' else '▼'} {sig['mom_val']:+.4f}"
    risk_pct = abs(lv["entry"] - lv["stop"]) / lv["entry"] * 100 if lv["entry"] else 0

    lvl_txt = ""
    if direction == "long" and sig.get("nearest_support") is not None:
        lvl_txt = f" Support {cur}{sig['nearest_support']:.4f}."
    elif direction == "short" and sig.get("nearest_resistance") is not None:
        lvl_txt = f" Resistance {cur}{sig['nearest_resistance']:.4f}."

    return (
        f"{symbol} ({asset_type.upper()}) {direction} scalp — {sq_txt}. "
        f"{mom_txt}.{lvl_txt} "
        f"Stop {cur}{lv['stop']:.4f} ({risk_pct:.1f}% risk), "
        f"target {cur}{lv['target']:.4f} ({lv['rr']:.1f}:1 R:R)."
    )
