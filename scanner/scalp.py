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


def build_detail(df: pd.DataFrame, sig: dict, lv: dict) -> dict:
    """Build the detail dropdown payload for the scalp card."""
    from . import config as cfg

    if getattr(df.index, "tz", None) is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)

    close = df["Close"]
    last  = sig["close"]

    def pct_from(price: float) -> float:
        return round((price - last) / last * 100, 2) if last else 0.0

    # BB and KC band values
    sigs     = _squeeze_signals(df)
    bb_mid   = float(sigs["bb_mid"].iloc[-1])
    bb_std   = float(close.rolling(SQ_PERIOD).std(ddof=0).iloc[-1])
    bb_upper = bb_mid + SQ_BB_MULT * bb_std
    bb_lower = bb_mid - SQ_BB_MULT * bb_std
    kc_range = float((atr(df, SQ_PERIOD) * SQ_KC_MULT).iloc[-1])
    kc_upper = bb_mid + kc_range
    kc_lower = bb_mid - kc_range

    # Volume
    vol       = float(df["Volume"].iloc[-1])
    avg_vol   = float(df["Volume"].iloc[-21:-1].mean())
    vol_ratio = round(vol / avg_vol, 2) if avg_vol > 0 else 0.0

    # Swing high/low over the pivot window
    swing_high = float(df["High"].iloc[-PIVOT_LOOKBACK:].max())
    swing_low  = float(df["Low"].iloc[-PIVOT_LOOKBACK:].min())

    if sig.get("squeeze_fired"):
        sq_state = "FIRED"
    elif sig.get("sq_on"):
        sq_state = "BUILDING"
    else:
        sq_state = "RELEASED"

    sup = sig.get("nearest_support")
    res = sig.get("nearest_resistance")

    # ── Position sizing ──────────────────────────────────────────────────────
    entry_price  = lv["entry"]
    stop_price   = lv["stop"]
    target_price = lv["target"]
    notional     = cfg.SCALP_POSITION_SIZE * cfg.SCALP_LEVERAGE   # $5,000
    units        = int(notional / entry_price) if entry_price > 0 else 0
    stop_dist    = abs(entry_price - stop_price)
    target_dist  = abs(target_price - entry_price)
    risk_dollars   = round(stop_dist   * units, 2)
    reward_dollars = round(target_dist * units, 2)
    brokerage_rt   = cfg.SCALP_BROKERAGE_EACH_WAY * 2
    net_loss       = round(risk_dollars   + brokerage_rt, 2)
    net_profit     = round(reward_dollars - brokerage_rt, 2)
    eff_rr         = round(net_profit / net_loss, 2) if net_loss > 0 else 0.0
    stop_pct_val   = round(stop_dist   / entry_price * 100, 2) if entry_price else 0.0
    target_pct_val = round(target_dist / entry_price * 100, 2) if entry_price else 0.0

    return {
        "setup_type":         "scalp",
        # Trade levels
        "entry":              round(entry_price,  6),
        "stop":               round(stop_price,   6),
        "target":             round(target_price, 6),
        "stop_pct":           stop_pct_val,
        "target_pct":         target_pct_val,
        # Position sizing
        "notional":           notional,
        "units":              units,
        "risk_dollars":       risk_dollars,
        "reward_dollars":     reward_dollars,
        "brokerage_rt":       brokerage_rt,
        "net_loss":           net_loss,
        "net_profit":         net_profit,
        "eff_rr":             eff_rr,
        # Squeeze
        "sq_state":           sq_state,
        "mom_val":            sig.get("mom_val", 0.0),
        # Pivot levels
        "nearest_support":    sup,
        "support_pct":        pct_from(sup) if sup is not None else None,
        "nearest_resistance": res,
        "resistance_pct":     pct_from(res) if res is not None else None,
        # BB / KC bands
        "bb_upper":           round(bb_upper, 6),
        "bb_mid":             round(bb_mid,   6),
        "bb_lower":           round(bb_lower, 6),
        "kc_upper":           round(kc_upper, 6),
        "kc_lower":           round(kc_lower, 6),
        "atr":                lv.get("atr", 0.0),
        # Swing levels
        "swing_high":         round(swing_high, 6),
        "swing_high_pct":     pct_from(swing_high),
        "swing_low":          round(swing_low,  6),
        "swing_low_pct":      pct_from(swing_low),
        # Volume
        "volume_ratio":       vol_ratio,
        "volume_expanding":   sig.get("volume", False),
        "volume_today":       int(vol),
        "volume_avg":         int(avg_vol),
    }


_SCALP_TV_SYMBOLS = {
    "GOLD": "TVC:GOLD", "SILVER": "TVC:SILVER", "OIL": "TVC:USOIL",
    "BRENT": "TVC:UKOIL", "NATGAS": "TVC:NATURALGAS",
    "WHEAT": "TVC:WHEAT", "COFFEE": "TVC:COFFEE", "COPPER": "TVC:COPPER",
}


def build_chart_data(
    df: pd.DataFrame, sig: dict, lv: dict,
    info: dict, points: int, grade: str, chips: list[str],
) -> dict:
    """1h candlestick + BB/KC/EMA overlay JSON for the chart page."""
    if getattr(df.index, "tz", None) is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)

    close    = df["Close"]
    sigs     = _squeeze_signals(df)
    bb_mid   = sigs["bb_mid"]
    bb_std   = close.rolling(SQ_PERIOD).std(ddof=0)
    bb_upper = bb_mid + SQ_BB_MULT * bb_std
    bb_lower = bb_mid - SQ_BB_MULT * bb_std
    kc_range = atr(df, SQ_PERIOD) * SQ_KC_MULT
    kc_upper = bb_mid + kc_range
    kc_lower = bb_mid - kc_range
    ema9     = close.ewm(span=9,  adjust=False).mean()
    ema21    = close.ewm(span=21, adjust=False).mean()

    n = min(120, len(df))

    def _ts(idx_val) -> int:
        """UTC Unix timestamp (seconds) from tz-naive pandas Timestamp."""
        return int(pd.Timestamp(idx_val).value // 1_000_000_000)

    candles, volume = [], []
    for i in range(-n, 0):
        bar = df.iloc[i]
        ts  = _ts(df.index[i])
        o, h, l, c, v = (float(bar["Open"]), float(bar["High"]), float(bar["Low"]),
                         float(bar["Close"]), float(bar["Volume"]))
        candles.append({"time": ts, "open": round(o, 8), "high": round(h, 8),
                        "low": round(l, 8), "close": round(c, 8)})
        volume.append({"time": ts, "value": int(v),
                       "color": "rgba(47,208,127,0.5)" if c >= o else "rgba(255,91,91,0.5)"})

    def _line(series: pd.Series, color: str, name: str) -> dict:
        data = [{"time": _ts(df.index[i]), "value": round(float(series.iloc[i]), 8)}
                for i in range(-n, 0) if np.isfinite(float(series.iloc[i]))]
        return {"name": name, "color": color, "data": data}

    symbol     = info.get("symbol", "")
    asset_type = info.get("type", "")
    direction  = sig["direction"]
    cur        = "A$" if asset_type == "asx" else "$"

    if asset_type == "asx":
        tv_sym = f"ASX:{symbol}"
    elif asset_type == "nasdaq":
        tv_sym = symbol
    else:
        tv_sym = _SCALP_TV_SYMBOLS.get(symbol, symbol)

    risk_pct = round(abs(lv["entry"] - lv["stop"]) / lv["entry"] * 100, 1) if lv["entry"] else 0.0

    level_lines = [
        {"price": lv["target"], "color": "#2fd07f", "title": "TARGET"},
        {"price": lv["entry"],  "color": "#f0a500", "title": "ENTRY"},
        {"price": lv["stop"],   "color": "#ff5b5b", "title": "STOP"},
    ]
    if direction == "long" and sig.get("nearest_support") is not None:
        level_lines.append({"price": sig["nearest_support"],    "color": "#4477cc", "title": "SUPPORT"})
    elif direction == "short" and sig.get("nearest_resistance") is not None:
        level_lines.append({"price": sig["nearest_resistance"], "color": "#cc7700", "title": "RESIST"})

    return {
        "symbol":          symbol,
        "name":            info.get("name", symbol),
        "price":           lv["entry"],
        "grade":           grade,
        "score":           points,
        "score_max":       SCALP_SCORE_MAX,
        "chips":           chips,
        "sector":          info.get("sector", ""),
        "currency_symbol": cur,
        "tv_symbol":       tv_sym,
        "rr":              lv["rr"],
        "low_rr":          lv["rr"] < 1.5,
        "rr_text":         f"{lv['rr']:.1f}:1",
        "risk_pct":        risk_pct,
        "entry":           lv["entry"],
        "stop":            lv["stop"],
        "target":          lv["target"],
        "dir":             direction.upper(),
        "analysis":        narrative(symbol, sig, lv, asset_type, cur),
        "default_tf":      "1H",
        "level_lines":     level_lines,
        "timeframes": {
            "1H": {
                "candles": candles,
                "volume":  volume,
                "lines": [
                    _line(bb_upper, "#4477cc", "BB Upper"),
                    _line(bb_mid,   "#888888", "BB Mid"),
                    _line(bb_lower, "#4477cc", "BB Lower"),
                    _line(kc_upper, "#cc7700", "KC Upper"),
                    _line(kc_lower, "#cc7700", "KC Lower"),
                    _line(ema9,     "#ffd23f", "EMA 9"),
                    _line(ema21,    "#2fd07f", "EMA 21"),
                ],
            }
        },
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
