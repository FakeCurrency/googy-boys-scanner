"""Strict both-sides pivots on a 1-D series, plus the Pine control-flow
primitives the divergence rule is expressed in.

WHY NEW HELPERS AND NOT `scanner/indicators.py`'s. Its `pivot_highs(df, window)`
and `pivot_lows(df, window)` hardcode `df["High"]` / `df["Low"]`, so they cannot
take an RSI series at all -- and THE PIVOTS HERE ARE ON THE RSI, not on price
(the price leg then reads the low/high at the same bar index). They are also
CENTRE-STAMPED: they return the pivot bar's own index, so the value lands on a
bar whose confirmation is only knowable `window` bars later. Using them would be
a look-ahead bug, not merely a shape mismatch.

TWO THINGS ABOUT "STRICT" WORTH KNOWING BEFORE EDITING:

1. It is what stops a FLAT series producing pivots. The naive
   `series == series.rolling(w, center=True).min()` makes every bar of a
   constant window both a maximum and a minimum, so you get a pivot on every
   bar and a cascade of nonsense divergences behind it -- which is exactly what
   halted small caps, delisted-but-quoted names and stablecoins produce. Here
   the centre is compared against the window WITH THE CENTRE REMOVED.

2. Whether Pine's `ta.pivotlow` really requires strictly-lower or merely `<=`
   is NOT documented by TradingView; it was searched for and is genuinely
   absent. The disagreement was MEASURED rather than assumed: over ~3,380
   divergences from 300 tick-rounded random walks the two conventions differ on
   27 (0.8%) -- and NOT in one direction (10 fire only under strict, 17 only
   under non-strict), because an extra intervening pivot re-bases "the previous
   pivot" and can push an otherwise valid divergence outside the 6..61 bar
   window. So relaxing a flag can REMOVE a divergence as well as add one.
   Default strict, because it is the only convention that cannot fire on a flat
   series. Settling it is a five-minute check against a real chart and is the
   owner's call.

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

from typing import Any, Optional

import numpy as np
import pandas as pd

from . import config
from .ema import _bool_out, _nan_safe, _out, _vals

__all__ = [
    "crossover", "crossunder", "cross",
    "pivot_low_confirmed", "pivot_high_confirmed",
    "valuewhen", "barssince", "shift_bool",
]


# ---------------------------------------------------------------------------
# crossings -- NaN-safe by construction, which matters during warm-up
# ---------------------------------------------------------------------------

def crossover(a: Any, b: Any) -> pd.Series:
    """Pine `ta.crossover(a, b)`: a[1] <= b[1] and a > b.

    A NaN on either side of either comparison makes the result False, which is
    what Pine does with na in a boolean context. That is load-bearing for the
    200 MA on a short history: no cross is reported while it is still na.
    """
    av, bv = _vals(a), _vals(b)
    n = av.size
    out = np.zeros(n, dtype=bool)
    if n < 2:
        return _bool_out(out, a, "crossover")
    now = _nan_safe(av[1:] > bv[1:])
    was = _nan_safe(av[:-1] <= bv[:-1])
    out[1:] = now & was
    return _bool_out(out, a, "crossover")


def crossunder(a: Any, b: Any) -> pd.Series:
    """Pine `ta.crossunder(a, b)`: a[1] >= b[1] and a < b."""
    av, bv = _vals(a), _vals(b)
    n = av.size
    out = np.zeros(n, dtype=bool)
    if n < 2:
        return _bool_out(out, a, "crossunder")
    now = _nan_safe(av[1:] < bv[1:])
    was = _nan_safe(av[:-1] >= bv[:-1])
    out[1:] = now & was
    return _bool_out(out, a, "crossunder")


def cross(a: Any, b: Any) -> pd.Series:
    """Pine `ta.cross(a, b)` = crossover or crossunder."""
    return (crossover(a, b) | crossunder(a, b)).rename("cross")


# ---------------------------------------------------------------------------
# pivots
# ---------------------------------------------------------------------------

def _pivot(series: Any, left: int, right: int, low: bool,
           strict_left: bool, strict_right: bool) -> pd.Series:
    v = _vals(series)
    n = v.size
    out = np.full(n, np.nan, dtype="float64")
    left, right = int(left), int(right)
    width = left + right + 1
    if left < 1 or right < 1 or n < width:
        return _out(out, series, "pivot")
    win = np.lib.stride_tricks.sliding_window_view(v, width)  # (n - width + 1, width)
    centre = win[:, left]
    lw = win[:, :left]
    rw = win[:, left + 1:]
    with np.errstate(invalid="ignore"):
        if low:
            ok_l = np.all(centre[:, None] < lw if strict_left else centre[:, None] <= lw, axis=1)
            ok_r = np.all(centre[:, None] < rw if strict_right else centre[:, None] <= rw, axis=1)
        else:
            ok_l = np.all(centre[:, None] > lw if strict_left else centre[:, None] >= lw, axis=1)
            ok_r = np.all(centre[:, None] > rw if strict_right else centre[:, None] >= rw, axis=1)
    ok = ok_l & ok_r & ~np.isnan(centre)
    centres = np.arange(left, n - right)
    confirm = centres + right
    out[confirm[ok]] = centre[ok]
    return _out(out, series, "pivotlow" if low else "pivothigh")


def pivot_low_confirmed(series: Any, left: int = 5, right: int = 5,
                        strict_left: bool = True, strict_right: bool = True) -> pd.Series:
    """Pine `ta.pivotlow(source, leftbars, rightbars)`.

    On bar i the result is the value of `source[i - right]` when that bar was
    a pivot low, and NaN otherwise. The timing is the whole point: the pivot
    is only KNOWN `right` bars after it happened, which is why the RSI+ pane
    draws its divergence marks with `offset = -lbR`, and why this screen fires
    on the confirmation bar rather than the pivot bar.

    A NaN anywhere in the left+right+1 window rejects the pivot (the numpy
    comparisons resolve to False), matching Pine's na handling.

    Ties: with `strict_*` True the centre must be a UNIQUE extreme of the
    window, so a flat stretch produces no pivots at all. See KNOWN LIMITS --
    this is the one place where TradingView's exact tie convention could not
    be verified without a chart, and relaxing either flag can only ever ADD
    pivots (i.e. add candidates), never remove one.
    """
    return _pivot(series, left, right, True, strict_left, strict_right)


def pivot_high_confirmed(series: Any, left: int = 5, right: int = 5,
                         strict_left: bool = True, strict_right: bool = True) -> pd.Series:
    """Pine `ta.pivothigh(source, leftbars, rightbars)`. Mirror of the above."""
    return _pivot(series, left, right, False, strict_left, strict_right)


# ---------------------------------------------------------------------------
# the rest of the Pine control flow the divergence rule is written in
# ---------------------------------------------------------------------------

def valuewhen(condition: Any, source: Any, occurrence: int = 0) -> pd.Series:
    """Pine `ta.valuewhen(condition, source, occurrence)`.

    On bar i: the value of `source` on the bar of the (occurrence+1)-th most
    recent bar at or before i where `condition` was true. occurrence = 0 is
    the most recent, 1 the one before that. NaN when there have not been
    enough occurrences yet -- Pine returns na, and every comparison against it
    is then false, which is how the first pivot of a symbol's history is
    prevented from claiming a divergence against nothing.
    """
    c = np.asarray(condition, dtype=bool)
    s = _vals(source)
    n = c.size
    out = np.full(n, np.nan, dtype="float64")
    occ = np.flatnonzero(c)
    if occ.size == 0:
        return _out(out, source, "valuewhen")
    bars = np.arange(n)
    seen = np.searchsorted(occ, bars, side="right")  # occurrences at bars <= i
    j = seen - 1 - int(occurrence)
    ok = j >= 0
    out[ok] = s[occ[j[ok]]]
    return _out(out, source, "valuewhen")


def barssince(condition: Any) -> pd.Series:
    """Pine `ta.barssince(condition)`.

    Number of bars since `condition` was last true, 0 on a bar where it is
    true, NaN until it has ever been true (Pine returns na, and `na <= 60` is
    false, so an in-range test correctly refuses to fire on the first pivot).
    """
    c = np.asarray(condition, dtype=bool)
    n = c.size
    bars = np.arange(n)
    last = np.where(c, bars, -1)
    last = np.maximum.accumulate(last) if n else last
    out = np.where(last >= 0, (bars - last).astype("float64"), np.nan)
    return _out(out, condition, "barssince")


def shift_bool(condition: Any, by: int = 1) -> np.ndarray:
    """Pine `condition[by]`: the bool series moved `by` bars forward, with the
    leading bars false (Pine's na in a boolean context)."""
    c = np.asarray(condition, dtype=bool)
    out = np.zeros(c.size, dtype=bool)
    if by < c.size:
        out[by:] = c[:c.size - by]
    return out
