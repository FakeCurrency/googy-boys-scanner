"""Precomputed per-ticker indicator arrays. Zero lookahead: every value at
index i uses data at indices <= i only. Swing points are fractal (k bars
either side) and therefore only *confirmed* k bars after they print — the
engine must not act on a swing before its confirm index.

ATR here is the simple mean of True Range (NOT Wilder-smoothed) — a
deliberate, documented choice for simplicity and determinism.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from phasemap.config import CONFIG


@dataclass
class Swing:
    index: int        # bar where the swing printed
    confirm: int      # first bar the engine may know about it (index + k)
    price: float


@dataclass
class IndicatorSet:
    dates: list                 # datetime.date per bar
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    tr: np.ndarray
    atr20: np.ndarray           # nan until warm
    box_high: np.ndarray        # max High over prior box_lookback bars, EXCLUDING current
    box_low: np.ndarray         # min Low over prior box_lookback bars, EXCLUDING current
    key_low: np.ndarray         # min Low over prior sweep_lookback bars, EXCLUDING current
    key_high: np.ndarray
    compressed: np.ndarray      # bool: Module 1 condition true at bar
    swing_lows: list            # list[Swing]
    swing_highs: list           # list[Swing]
    turnover20: np.ndarray      # mean(Close*Volume, 20)
    yearly_open: np.ndarray
    quarterly_open: np.ndarray
    monthly_open: np.ndarray
    prior_yearly_close: np.ndarray   # nan when no prior year in data


def true_range(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    tr = h - l
    if len(c) > 1:
        pc = c[:-1]
        tr = np.concatenate(
            [tr[:1],
             np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - pc), np.abs(l[1:] - pc)])]
        )
    return tr


def _trailing_mean(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def _prior_extreme(x: np.ndarray, n: int, kind: str) -> np.ndarray:
    """Rolling max/min over the n bars strictly BEFORE each bar."""
    s = pd.Series(x)
    roll = s.rolling(n, min_periods=n)
    ext = roll.max() if kind == "max" else roll.min()
    return ext.shift(1).to_numpy()


def _compression_flags(high, low, close, tr) -> np.ndarray:
    """Module 1: relative compression.

    Main path (needs ~2y of rolling ranges): current 40-bar range-pct
    (excluding current bar) <= own 40th percentile of that series.
    Fallback (<2y): ATR14/Close <= own 30th percentile over available history.
    """
    n = len(close)
    lb = CONFIG.box_lookback
    s_high, s_low = pd.Series(high), pd.Series(low)
    box_hi = s_high.rolling(lb, min_periods=lb).max().shift(1)
    box_lo = s_low.rolling(lb, min_periods=lb).min().shift(1)
    range_pct = (box_hi - box_lo) / box_lo

    hist = CONFIG.compression_history_bars
    main_thresh = range_pct.rolling(hist, min_periods=hist).quantile(
        CONFIG.compression_percentile)
    main_fire = (range_pct <= main_thresh)

    atr14 = pd.Series(tr).rolling(CONFIG.fallback_atr_period,
                                  min_periods=CONFIG.fallback_atr_period).mean()
    a14c = atr14 / pd.Series(close)
    fb_thresh = a14c.expanding(min_periods=CONFIG.compression_min_bars).quantile(
        CONFIG.fallback_percentile)
    fb_fire = (a14c <= fb_thresh)

    main_available = main_thresh.notna().to_numpy()
    fire = np.where(main_available, main_fire.fillna(False).to_numpy(),
                    fb_fire.fillna(False).to_numpy())
    return np.asarray(fire, dtype=bool)


def _swings(vals: np.ndarray, k: int, kind: str) -> list:
    """Fractal swings: strictly beyond the k bars either side. Confirmed k bars later."""
    out = []
    n = len(vals)
    for j in range(k, n - k):
        window_prev = vals[j - k:j]
        window_next = vals[j + 1:j + 1 + k]
        if kind == "low":
            if vals[j] < window_prev.min() and vals[j] < window_next.min():
                out.append(Swing(index=j, confirm=j + k, price=float(vals[j])))
        else:
            if vals[j] > window_prev.max() and vals[j] > window_next.max():
                out.append(Swing(index=j, confirm=j + k, price=float(vals[j])))
    return out


def _anchor_arrays(dates, opens, closes):
    """First traded Open of each calendar year/quarter/month + prior yearly close.
    Walks forward only — no lookahead."""
    n = len(dates)
    y_open = np.full(n, np.nan)
    q_open = np.full(n, np.nan)
    m_open = np.full(n, np.nan)
    py_close = np.full(n, np.nan)
    cur_y = cur_q = cur_m = None
    cur_yo = cur_qo = cur_mo = np.nan
    prior_yc = np.nan
    last_close = np.nan
    for i, d in enumerate(dates):
        y, q, m = d.year, (d.month - 1) // 3, d.month
        if y != cur_y:
            if cur_y is not None:
                prior_yc = last_close      # last close of the year just ended
            cur_y, cur_yo = y, opens[i]
        if (y, q) != cur_q:
            cur_q, cur_qo = (y, q), opens[i]
        if (y, m) != cur_m:
            cur_m, cur_mo = (y, m), opens[i]
        y_open[i], q_open[i], m_open[i], py_close[i] = cur_yo, cur_qo, cur_mo, prior_yc
        last_close = closes[i]
    return y_open, q_open, m_open, py_close


def compute_indicators(df: pd.DataFrame, volume_is_usd: bool = False) -> IndicatorSet:
    """df columns: Date (datetime-like), Open, High, Low, Close, Volume — ascending.
    volume_is_usd: crypto feeds already quote Volume in dollars — don't
    multiply by Close again."""
    o = df["Open"].to_numpy(dtype=float)
    h = df["High"].to_numpy(dtype=float)
    l = df["Low"].to_numpy(dtype=float)
    c = df["Close"].to_numpy(dtype=float)
    v = df["Volume"].to_numpy(dtype=float)
    dates = [pd.Timestamp(d).date() for d in df["Date"]]

    tr = true_range(h, l, c)
    atr20 = _trailing_mean(tr, CONFIG.atr_period)
    turnover20 = _trailing_mean(v if volume_is_usd else c * v, CONFIG.turnover_window)

    yo, qo, mo, pyc = _anchor_arrays(dates, o, c)

    return IndicatorSet(
        dates=dates, open=o, high=h, low=l, close=c, volume=v,
        tr=tr, atr20=atr20,
        box_high=_prior_extreme(h, CONFIG.box_lookback, "max"),
        box_low=_prior_extreme(l, CONFIG.box_lookback, "min"),
        key_low=_prior_extreme(l, CONFIG.sweep_lookback, "min"),
        key_high=_prior_extreme(h, CONFIG.sweep_lookback, "max"),
        compressed=_compression_flags(h, l, c, tr),
        swing_lows=_swings(l, CONFIG.swing_fractal_k, "low"),
        swing_highs=_swings(h, CONFIG.swing_fractal_k, "high"),
        turnover20=turnover20,
        yearly_open=yo, quarterly_open=qo, monthly_open=mo, prior_yearly_close=pyc,
    )
