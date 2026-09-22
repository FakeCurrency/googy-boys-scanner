"""Pine-faithful recursive averages -- the base module of the lens.

WHY THIS EXISTS INSTEAD OF `scanner/indicators.py`. That module's `rsi()` and
`atr()` would be acceptable here, but its `ema()` is `ewm(span, adjust=False)`,
which seeds on the FIRST VALUE and emits from bar 0. Pine seeds with the SMA of
the first `length` values and returns `na` before that. The seed error decays as
(1-alpha)^n, so it matters in inverse proportion to alpha: irrelevant for RSI 14
and the EMA 20/50, but the EMA 200 still carries about 0.67% of it at 500 bars
-- MEASURED at 0.247 price units adrift at bar 600 of a ramp, which is enough to
flip `close > slow`, one of Rule B's two live scoring terms. A name sitting near
its 200-EMA would then score 3 here and 2 on the owner's chart.

So the lens carries its own maths, end to end, for Pine parity and because a
self-contained package is one that can be deleted in one commit.

# PORTED VERBATIM from tradingview/scanner-spec/reference/vivek50_screen.py.
# The function bodies below were EXTRACTED, not retyped: a hand-transcription
# of trading maths drifts silently, and `tests/test_momentum_screen.py` proves
# bit-identity against the reference rather than trusting this comment. The
# only edits are namespace ones, and they are listed at each site:
#   ScreenConfig    -> MomentumConfig      (scanner/momentum/config.py)
#   DEFAULT_CONFIG  -> config.DEFAULTS
#   cfg.mode == 1   -> cfg.mode == "A"     (letters, per spec 5.4)
#   cfg.mode == 2   -> cfg.mode != "A"     (B and C both screen the union; C is
#                                           a post-filter on the same
#                                           computation, not a third screen)
"""

from __future__ import annotations

import math

from typing import Any, Optional

import numpy as np
import pandas as pd

from . import config
from .config import MomentumConfig  # noqa: F401  (re-exported for the ports)

__all__ = [
    "wilder_rma", "sma_pine", "ema_pine", "ma_pine", "rsi_wilder",
    "true_range", "atr_wilder",
]


# ---------------------------------------------------------------------------
# array plumbing shared by every indicator here
# ---------------------------------------------------------------------------

def _vals(x: Any) -> np.ndarray:
    """Float64 numpy view of a Series / array / list, never a copy-on-write trap."""
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype="float64", copy=True)
    return np.asarray(x, dtype="float64").copy()


def _index_of(x: Any, n: int) -> pd.Index:
    if isinstance(x, (pd.Series, pd.DataFrame)):
        return x.index
    return pd.RangeIndex(n)


def _out(values: np.ndarray, like: Any, name: str) -> pd.Series:
    return pd.Series(values, index=_index_of(like, values.size), name=name, dtype="float64")


def _bool_out(values: np.ndarray, like: Any, name: str) -> pd.Series:
    return pd.Series(np.asarray(values, dtype=bool),
                     index=_index_of(like, np.asarray(values).size), name=name)


def _nan_safe(op: np.ndarray) -> np.ndarray:
    """A numpy comparison result with NaN operands already resolves to False,
    which is exactly Pine's behaviour (`na > x` is falsy in a condition).
    This function only documents that fact for the reader."""
    return np.asarray(op, dtype=bool)


def _first_valid(v: np.ndarray) -> int:
    """Index of the first non-NaN element, or -1."""
    ok = np.flatnonzero(~np.isnan(v))
    return int(ok[0]) if ok.size else -1


def _recursive_ma(v: np.ndarray, period: int, alpha: float, seed: str) -> np.ndarray:
    """Shared engine for ta.ema / ta.rma.

    Pine seeds both with the SMA of the first `period` values of the source,
    counting from the source's first non-na bar, and returns na before that.
    `seed="first"` reproduces pandas' ewm(adjust=False) instead: seed on the
    first value, no warm-up NaNs. See KNOWN LIMITS.

    An interior NaN (a bar with no price) poisons everything after it, which
    is why prepare_frame() drops such bars before anything is computed.
    """
    n = v.size
    out = np.full(n, np.nan, dtype="float64")
    if period < 1 or n == 0:
        return out
    f = _first_valid(v)
    if f < 0:
        return out
    if seed == "first":
        start = f
        prev = v[f]
        out[f] = prev
    else:
        if n - f < period:
            return out
        start = f + period - 1
        window = v[f:f + period]
        if np.isnan(window).any():
            # A NaN inside the seed window: walk forward to the first clean one.
            for s in range(f, n - period + 1):
                w = v[s:s + period]
                if not np.isnan(w).any():
                    start = s + period - 1
                    window = w
                    break
            else:
                return out
        prev = float(window.mean())
        out[start] = prev
    for i in range(start + 1, n):
        x = v[i]
        if np.isnan(x):
            prev = np.nan
            out[i] = np.nan
            continue
        if np.isnan(prev):
            prev = x
            out[i] = x
            continue
        prev = alpha * x + (1.0 - alpha) * prev
        out[i] = prev
    return out


# ---------------------------------------------------------------------------
# the indicators
# ---------------------------------------------------------------------------

def wilder_rma(series: Any, period: int, seed: Optional[str] = None) -> pd.Series:
    """Pine `ta.rma(source, length)`.

    Wilder's smoothing: alpha = 1 / length, seeded with the SMA of the first
    `length` values of the source (Pine's documented behaviour), na before.
    Used by ta.rsi and ta.atr, which is why it has to be exact rather than
    "an EMA with a different alpha".
    """
    seed = seed or config.DEFAULTS.rma_seed
    v = _vals(series)
    return _out(_recursive_ma(v, int(period), 1.0 / float(period), seed), series, "rma%d" % period)


def sma_pine(series: Any, period: int) -> pd.Series:
    """Pine `ta.sma(source, length)`. NaN until `length` values exist."""
    s = series if isinstance(series, pd.Series) else pd.Series(_vals(series))
    return s.rolling(int(period), min_periods=int(period)).mean().rename("sma%d" % period)


def ema_pine(series: Any, span: int, seed: Optional[str] = None) -> pd.Series:
    """Pine `ta.ema(source, length)`.

    alpha = 2 / (length + 1), recursive, seeded with the SMA of the first
    `length` values (TradingView emits na for the first length-1 bars).

    `seed="first"` is pandas' `ewm(span=span, adjust=False).mean()` with no
    warm-up NaNs; it is offered because the task named it, and because after
    roughly 5x span bars the two are identical to within 1e-9. Use "sma" for
    anything that has to agree with a chart bar-for-bar near the left edge.
    """
    seed = seed or config.DEFAULTS.ema_seed
    v = _vals(series)
    span = int(span)
    return _out(_recursive_ma(v, span, 2.0 / (span + 1.0), seed), series, "ema%d" % span)


def ma_pine(series: Any, length: int, ma_type: str = "EMA",
            seed: Optional[str] = None) -> pd.Series:
    """Final_Top_Script.pine `f_ma(s, len)` -- EMA or SMA by the `maType` input.

    The Pine computes BOTH every bar and picks one, so that the ta.* history
    stays consistent when the input is switched. Here the choice is pure, so
    only the selected one is computed.
    """
    return ema_pine(series, length, seed) if ma_type == "EMA" else sma_pine(series, length)


def rsi_wilder(close: Any, period: int = 14, seed: Optional[str] = None) -> pd.Series:
    """Pine `ta.rsi(source, length)`.

    Pine's definition, verbatim:
        u   = math.max(ta.change(src), 0)
        d   = math.max(-ta.change(src), 0)
        rs  = ta.rma(u, len) / ta.rma(d, len)
        res = 100 - 100 / (1 + rs)
    Three boundary cases, and the third one is the corrected one:
        rma(d) == 0, rma(u)  > 0 -> rs = +inf -> 100   (only gains)
        rma(u) == 0, rma(d)  > 0 -> rs = 0    ->   0   (only losses)
        rma(u) == 0 AND rma(d) == 0 -> rs = 0/0 = NaN -> NaN

    THE THIRD CASE USED TO RETURN 100 AND THAT WAS WRONG. Pine's ta.rsi is
    one division, not a chain of branches -- there is no "zero-denominator
    branch tested first" to inherit an answer from. A perfectly flat series
    makes BOTH Wilder averages exactly zero, 0/0 is NaN under IEEE, and na
    is what the formula yields. Returning 100 published "maximally
    overbought" for a stock that had not moved a tick, which reached the
    reviewer as `rsi: 100.0, rsi_zone: extreme-overbought` on every halted
    or never-traded name in the universe.

    It can only ever REMOVE a claim, never add one: both averages are zero
    only while the series has been flat since its first bar, which has no
    pivots and no crosses, so no RULE A or RULE B verdict moves. If a chart
    comparison ever shows TradingView printing 100 there, this is the one
    line to flip back.
    """
    v = _vals(close)
    period = int(period)
    change = np.full(v.size, np.nan, dtype="float64")
    if v.size > 1:
        change[1:] = v[1:] - v[:-1]
    up = np.where(np.isnan(change), np.nan, np.maximum(change, 0.0))
    dn = np.where(np.isnan(change), np.nan, np.maximum(-change, 0.0))
    ru = _recursive_ma(up, period, 1.0 / period, seed or config.DEFAULTS.rma_seed)
    rd = _recursive_ma(dn, period, 1.0 / period, seed or config.DEFAULTS.rma_seed)
    out = np.full(v.size, np.nan, dtype="float64")
    live = ~np.isnan(ru) & ~np.isnan(rd)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(live & (rd != 0.0), ru / np.where(rd == 0.0, np.nan, rd), np.nan)
        generic = 100.0 - 100.0 / (1.0 + rs)
    both_zero = live & (rd == 0.0) & (ru == 0.0)   # 0 / 0 -> NaN, see above
    out = np.where(both_zero, np.nan,
                   np.where(live & (rd == 0.0), 100.0,
                            np.where(live & (ru == 0.0), 0.0,
                                     np.where(live, generic, np.nan))))
    return _out(out, close, "rsi%d" % period)


def true_range(df: pd.DataFrame) -> pd.Series:
    """Pine `ta.tr(true)`.

    max(high - low, |high - close[1]|, |low - close[1]|), and on the first bar
    (where close[1] is na) simply high - low, which is what the `true`
    argument means.
    """
    h = _vals(df["high"])
    l = _vals(df["low"])
    c = _vals(df["close"])
    prev = np.full(c.size, np.nan, dtype="float64")
    if c.size > 1:
        prev[1:] = c[:-1]
    hl = h - l
    with np.errstate(invalid="ignore"):
        a = np.abs(h - prev)
        b = np.abs(l - prev)
    tr = np.where(np.isnan(prev), hl, np.maximum(hl, np.maximum(a, b)))
    return _out(tr, df, "tr")


def atr_wilder(df: pd.DataFrame, period: int = 14, seed: Optional[str] = None) -> pd.Series:
    """Pine `ta.atr(length)` = ta.rma(ta.tr(true), length)."""
    return wilder_rma(true_range(df), period, seed).rename("atr%d" % period)
