"""vivek50_screen -- a pure pandas/numpy reference implementation of the
"Vivek 5.0" TradingView chart template's maths, plus the daily screen built on
top of it.

WHAT THIS MIRRORS
-----------------
Three Pine Script v6 files in tradingview/ of the googy-boys-scanner repo:

  Final_Top_Script.pine   indicator("Vivek 5.0 Top",  overlay = true)
  Final_Bottom_MACD.pine  indicator("Vivek 5.0 MACD", overlay = false)
  Final_RSI_Plus.pine     indicator("Vivek 5.0 RSI+", overlay = false)

Every function below names the Pine line(s) it reproduces in its docstring.
Nothing here talks to TradingView, to a broker, or to the network.

THE SCREEN
----------
Run daily, on the latest CLOSED daily bar, over ASX / NASDAQ / crypto:

  RULE A  the RSI+ pane printed a regular divergence ("Bull" / "Bear" label)
  RULE B  the Top overlay printed a scored Fast x Mid cross whose score is
          at least `min_signal_score` (2 by default)

  mode 1 = RULE A only
  mode 2 = RULE A or RULE B

The output feeds a manual eyeball review, so a false positive costs a glance
and a miss costs a trade. Every threshold is in ScreenConfig; nothing is
hardcoded at a call site.

CAUSALITY
---------
Every series returned by this module is causal: the value on bar i depends
only on bars 0..i. `assert_no_lookahead()` proves it by truncation, and the
self-test runs it. Nothing here uses request.security(), so the one genuinely
non-causal thing in the Pine (the yearly-open lookahead) has no counterpart.

ASCII only, by house rule 9.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "ScreenConfig",
    "wilder_rma",
    "rsi_wilder",
    "ema_pine",
    "sma_pine",
    "ma_pine",
    "macd_pine",
    "atr_wilder",
    "true_range",
    "crossover",
    "crossunder",
    "cross",
    "pivot_low_confirmed",
    "pivot_high_confirmed",
    "valuewhen",
    "barssince",
    "rsi_divergence",
    "cross_signal",
    "evaluate",
    "screen_symbol",
    "screen_frames",
    "assert_no_lookahead",
    "prepare_frame",
    "OHLC_COLUMNS",
]

OHLC_COLUMNS: Tuple[str, ...] = ("open", "high", "low", "close")


# =============================================================================
# configuration
# =============================================================================


@dataclass
class ScreenConfig:
    """Every tunable, with the default taken from the Pine source it mirrors.

    Fields are grouped by the Pine file they come from. Fields marked
    DRAWING-ONLY exist so this dataclass is a complete transcription of the
    template's inputs; the screen never reads them.
    """

    # ---- Final_RSI_Plus.pine ------------------------------------------------
    rsi_len: int = 14  # rsiLen      = input.int(14, "RSI Length")
    rsi_source: str = "close"  # rsiSrc = input.source(close, "Source")
    rsi_ma_len: int = 14  # maLen      = input.int(14, "MA Length")
    rsi_ma_type: str = "SMA"  # maType    = input.string("SMA", options SMA/EMA)
    rsi_long_avg_len: int = 50  # longLen = input.int(50, "Long-run average length")
    rsi_ob1: float = 70.0  # ob1        = input.float(70, "Overbought")
    rsi_ob2: float = 75.0  # ob2        = input.float(75, "extreme")
    rsi_os1: float = 30.0  # os1        = input.float(30, "Oversold")
    rsi_os2: float = 25.0  # os2        = input.float(25, "extreme")
    rsi_midline: float = 50.0  # midL   = input.float(50, "Midline")
    show_div: bool = True  # showDiv    = input.bool(true, "Regular divergences")
    piv_left: int = 5  # lbL          = input.int(5, "Pivot lookback left")
    piv_right: int = 5  # lbR         = input.int(5, "Pivot lookback right")
    range_upper: int = 60  # rangeUpper= input.int(60, "Max bars between pivots")
    range_lower: int = 5  # rangeLower = input.int(5,  "Min bars between pivots")

    # ---- Final_Bottom_MACD.pine (and the Top script's Signals group) --------
    macd_fast: int = 12  # fastLen / macdFast = input.int(12)
    macd_slow: int = 26  # slowLen / macdSlow = input.int(26)
    macd_signal: int = 9  # sigLen / macdSig  = input.int(9)
    macd_source: str = "close"  # src   = input.source(close, "Source")

    # ---- Final_Top_Script.pine, "Moving averages" ---------------------------
    fast_len: int = 20  # fastLen = input.int(20,  "Fast Length")
    mid_len: int = 50  # midLen   = input.int(50,  "Mid Length")
    slow_len: int = 200  # slowLen= input.int(200, "Slow Length")
    ma_type: str = "EMA"  # maType = input.string("EMA", options EMA/SMA)
    ma_source: str = "close"  # maSrc = input.source(close, "Source")

    # ---- Final_Top_Script.pine, "Background" --------------------------------
    top_rsi_len: int = 14  # rsiLen = input.int(14, "RSI length")
    top_rsi_ob: float = 75.0  # rsiOB= input.float(75, "RSI overbought")
    top_rsi_os: float = 25.0  # rsiOS= input.float(25, "RSI oversold")

    # ---- Final_Top_Script.pine, "Signals (Fast x Mid cross, scored)" --------
    use_macd: bool = True  # useMacd  = input.bool(true,  "+1 MACD agrees")
    use_slow: bool = True  # useSlow  = input.bool(true,  "+1 price beyond Slow")
    use_rsi: bool = False  # useRsi   = input.bool(false, "+1 RSI agrees")
    min_score: int = 1  # minScore   = input.int(1, "Minimum score to show")

    # ---- Final_Top_Script.pine, misc computation ----------------------------
    atr_len: int = 14  # atrV = ta.atr(14)
    sr_pivot_len: int = 10  # pivLen = input.int(10, "Pivot strength")
    sr_max_per_side: int = 3  # maxSR = input.int(3, "Levels per side")
    range_len: int = 100  # rangeLen = input.int(100, "Range lookback (bars)")

    # ---- Final_Top_Script.pine, DRAWING-ONLY (unused by the screen) ---------
    swing_len: int = 5  # swingLen   = input.int(5,   "Swing lookback")
    atr_mult: float = 1.5  # atrMult  = input.float(1.5, "ATR multiple")
    atr_pad: float = 0.25  # atrPad   = input.float(0.25,"ATR pad beyond swing")
    max_stop_pct: float = 15.0  # maxStopPct = input.float(15, "max stop %")
    r1: float = 1.0  # r1 = input.float(1.0, "TP1 (R)")
    r2: float = 2.0  # r2 = input.float(2.0, "TP2 (R)")
    r3: float = 3.0  # r3 = input.float(3.0, "TP3 (R)")
    auto_max_age: int = 60  # autoMaxAge = input.int(60, "signal within bars")
    rev_look: int = 30  # revLook    = input.int(30, "Structure lookback")
    rev_pad: float = 1.0  # revPad    = input.float(1.0,"ATR pad for rev stop")
    rev_max_age: int = 60  # revMaxAge = input.int(60, "Keep the box for bars")
    max_dist_pct: float = 100.0  # maxDist = input.float(100, "Hide a level")
    yo_count: int = 2  # yoCount    = input.int(2, "Yearly opens to show")

    # ---- the screen (no Pine counterpart; these are the owner's rules) ------
    mode: int = 2  # 1 = RULE A only, 2 = RULE A or RULE B
    div_fresh_bars: int = 1  # RULE A: fired within this many bars (1 = last)
    signal_fresh_bars: int = 1  # RULE B: fired within this many bars
    min_signal_score: int = 2  # RULE B: |score| >= this
    div_directions: Tuple[str, ...] = ("bull", "bear")
    signal_directions: Tuple[str, ...] = ("bull", "bear")
    min_bars: int = 60  # refuse to screen a frame shorter than this
    warn_bars: int = 260  # below this the 200 MA is a proxy or absent

    # ---- numerical conventions (see KNOWN LIMITS in the write-up) ----------
    ema_seed: str = "sma"  # "sma" = Pine's seeding, "first" = ewm(adjust=False)
    rma_seed: str = "sma"  # Wilder's own seeding; Pine uses SMA
    pivot_strict_left: bool = True  # a tie on the left disqualifies the pivot
    pivot_strict_right: bool = True  # a tie on the right disqualifies it

    def validate(self) -> "ScreenConfig":
        """Fail loudly on a configuration that cannot mean anything."""
        if self.mode not in (1, 2):
            raise ValueError("mode must be 1 or 2, got %r" % (self.mode,))
        for name in ("rsi_len", "piv_left", "piv_right", "fast_len", "mid_len",
                     "slow_len", "macd_fast", "macd_slow", "macd_signal",
                     "atr_len", "rsi_ma_len"):
            if int(getattr(self, name)) < 1:
                raise ValueError("%s must be >= 1" % name)
        if self.range_lower > self.range_upper:
            raise ValueError("range_lower must be <= range_upper")
        for name in ("rsi_source", "ma_source", "macd_source"):
            val = getattr(self, name)
            if val not in OHLC_COLUMNS:
                # The call sites fall back to `close` for an unknown name, so
                # a typo ("hlc3", "Close", "adj_close") used to compute a
                # different indicator than the config claimed, silently.
                raise ValueError(
                    "%s must be one of %s, got %r"
                    % (name, ", ".join(OHLC_COLUMNS), val))
        if self.ma_type not in ("EMA", "SMA"):
            raise ValueError("ma_type must be EMA or SMA")
        if self.rsi_ma_type not in ("EMA", "SMA"):
            raise ValueError("rsi_ma_type must be EMA or SMA")
        if self.ema_seed not in ("sma", "first"):
            raise ValueError("ema_seed must be 'sma' or 'first'")
        if self.rma_seed not in ("sma", "first"):
            raise ValueError("rma_seed must be 'sma' or 'first'")
        if self.div_fresh_bars < 1 or self.signal_fresh_bars < 1:
            raise ValueError("freshness windows are counted in bars and are >= 1")
        return self

    @property
    def max_score(self) -> int:
        """maxScore = 1 + (useMacd ? 1 : 0) + (useSlow ? 1 : 0) + (useRsi ? 1 : 0)

        Final_Top_Script.pine, the `maxScore` line above the key table.
        With the shipped defaults this is 3, NOT 4.
        """
        return 1 + int(self.use_macd) + int(self.use_slow) + int(self.use_rsi)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def replace(self, **kw: Any) -> "ScreenConfig":
        return replace(self, **kw).validate()


DEFAULT_CONFIG = ScreenConfig().validate()


# =============================================================================
# small helpers
# =============================================================================


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


# =============================================================================
# indicators
# =============================================================================


def wilder_rma(series: Any, period: int, seed: Optional[str] = None) -> pd.Series:
    """Pine `ta.rma(source, length)`.

    Wilder's smoothing: alpha = 1 / length, seeded with the SMA of the first
    `length` values of the source (Pine's documented behaviour), na before.
    Used by ta.rsi and ta.atr, which is why it has to be exact rather than
    "an EMA with a different alpha".
    """
    seed = seed or DEFAULT_CONFIG.rma_seed
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
    seed = seed or DEFAULT_CONFIG.ema_seed
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
    ru = _recursive_ma(up, period, 1.0 / period, seed or DEFAULT_CONFIG.rma_seed)
    rd = _recursive_ma(dn, period, 1.0 / period, seed or DEFAULT_CONFIG.rma_seed)
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


def macd_pine(close: Any, fast: int = 12, slow: int = 26, signal: int = 9,
              seed: Optional[str] = None) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Pine `[macdLine, signalLine, histLine] = ta.macd(src, fast, slow, sig)`.

    Returned in Pine's order: (macd, signal, hist). hist = macd - signal.
    Both panes of the template use 12 / 26 / 9 on close, and the Top script's
    score reads `macdHist` from exactly this call.
    """
    macd = ema_pine(close, fast, seed) - ema_pine(close, slow, seed)
    macd = macd.rename("macd")
    sig = ema_pine(macd, signal, seed).rename("macd_signal")
    hist = (macd - sig).rename("macd_hist")
    return macd, sig, hist


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


# =============================================================================
# Pine control-flow primitives
# =============================================================================


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


# =============================================================================
# frame hygiene
# =============================================================================


def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise an OHLCV frame: lower-case columns, float dtypes, drop bars
    with no price.

    Dropping is deliberate and is the only place a bar disappears. An interior
    NaN close would poison every recursive average after it (Pine has no such
    bar at all -- a halted session simply is not a bar), so a NaN row is
    removed rather than filled. Removing a row does not create look-ahead:
    the remaining bars keep their order and each still only sees its own past.

    Raises ValueError only for a frame that cannot be interpreted at all.
    """
    if not isinstance(df, pd.DataFrame):
        raise ValueError("expected a DataFrame of OHLC bars")
    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    missing = [c for c in OHLC_COLUMNS if c not in out.columns]
    if "open" in missing and "close" in out.columns:
        out["open"] = out["close"]
        missing = [c for c in missing if c != "open"]
    if missing:
        raise ValueError("frame is missing column(s): %s" % ", ".join(missing))
    # A frame handed in NEWEST-FIRST is the one bad input that produces a
    # complete, plausible, entirely meaningless row: every recursive average
    # runs backwards, `last_bar` reports the OLDEST date, and nothing in the
    # output says so. Some providers and most hand-saved CSVs are descending.
    # Cheap to detect, so it is refused rather than screened. An index that is
    # both increasing and decreasing is constant (all bars share a timestamp),
    # which is a duplicate-index frame and is fine.
    if len(out.index) > 1:
        try:
            backwards = bool(out.index.is_monotonic_decreasing) and not bool(
                out.index.is_monotonic_increasing)
        except (TypeError, ValueError):
            backwards = False
        if backwards:
            raise ValueError(
                "bars are in DESCENDING order (index runs newest-first); "
                "this module reads a frame oldest-first -- sort it ascending")
    keep = list(OHLC_COLUMNS) + (["volume"] if "volume" in out.columns else [])
    out = out.loc[:, keep]
    for c in keep:
        out[c] = pd.to_numeric(out[c], errors="coerce").astype("float64")
    out = out[~out[list(OHLC_COLUMNS)].isna().any(axis=1)]
    return out


# =============================================================================
# RULE A -- regular RSI divergence (Final_RSI_Plus.pine)
# =============================================================================


def rsi_divergence(df: pd.DataFrame, cfg: Optional[ScreenConfig] = None) -> pd.DataFrame:
    """Final_RSI_Plus.pine, the divergence block, line for line.

        plFound = not na(ta.pivotlow(rsi, lbL, lbR))
        phFound = not na(ta.pivothigh(rsi, lbL, lbR))
        f_inRange(cond) =>
            bars = ta.barssince(cond == true)
            rangeLower <= bars and bars <= rangeUpper
        inRangeL = f_inRange(plFound[1])
        inRangeH = f_inRange(phFound[1])
        rsiHL   = rsi[lbR] > ta.valuewhen(plFound, rsi[lbR], 1)
        priceLL = low[lbR]  < ta.valuewhen(plFound, low[lbR], 1)
        bullDiv = showDiv and plFound and priceLL and rsiHL and inRangeL
        rsiLH   = rsi[lbR] < ta.valuewhen(phFound, rsi[lbR], 1)
        priceHH = high[lbR] > ta.valuewhen(phFound, high[lbR], 1)
        bearDiv = showDiv and phFound and priceHH and rsiLH and inRangeH

    Two facts that are easy to get wrong and that the tests pin:

    1. THE PIVOTS ARE ON THE RSI, NOT ON PRICE. The price leg compares the
       low (high) of the bar on which the RSI pivoted against the low (high)
       of the bar on which the RSI previously pivoted. It is not a price
       pivot and there is no price-pivot confirmation involved.

    2. `f_inRange` is called with `plFound[1]`, not `plFound`. On a bar i
       where plFound is true, ta.barssince(plFound[1]) is
       (i - previous_plFound_bar - 1). So `5 <= bars <= 60` admits a gap of
       6 to 61 bars inclusive between the two CONFIRMATION bars, which is
       also the gap between the two pivot bars. The naive reading (5..60)
       is off by one at both ends. This is inherited verbatim from
       TradingView's own built-in Divergence Indicator.

    Returns a DataFrame indexed like `df` with the boolean verdicts on the
    CONFIRMATION bar plus every intermediate value a reviewer would want.
    """
    cfg = (cfg or DEFAULT_CONFIG)
    d = df
    n = len(d)
    idx = d.index
    src = d[cfg.rsi_source] if cfg.rsi_source in d.columns else d["close"]
    rsi = rsi_wilder(src, cfg.rsi_len)
    pl = pivot_low_confirmed(rsi, cfg.piv_left, cfg.piv_right,
                             cfg.pivot_strict_left, cfg.pivot_strict_right)
    ph = pivot_high_confirmed(rsi, cfg.piv_left, cfg.piv_right,
                              cfg.pivot_strict_left, cfg.pivot_strict_right)
    pl_found = pl.notna().to_numpy()
    ph_found = ph.notna().to_numpy()

    r = cfg.piv_right
    rsi_at = rsi.shift(r)          # rsi[lbR]
    low_at = d["low"].shift(r)     # low[lbR]
    high_at = d["high"].shift(r)   # high[lbR]

    prev_rsi_l = valuewhen(pl_found, rsi_at, 1)
    prev_low = valuewhen(pl_found, low_at, 1)
    prev_rsi_h = valuewhen(ph_found, rsi_at, 1)
    prev_high = valuewhen(ph_found, high_at, 1)

    rsi_hl = _nan_safe(rsi_at.to_numpy() > prev_rsi_l.to_numpy())
    price_ll = _nan_safe(low_at.to_numpy() < prev_low.to_numpy())
    rsi_lh = _nan_safe(rsi_at.to_numpy() < prev_rsi_h.to_numpy())
    price_hh = _nan_safe(high_at.to_numpy() > prev_high.to_numpy())

    bars_l = barssince(shift_bool(pl_found)).to_numpy()
    bars_h = barssince(shift_bool(ph_found)).to_numpy()
    in_range_l = _nan_safe((bars_l >= cfg.range_lower) & (bars_l <= cfg.range_upper))
    in_range_h = _nan_safe((bars_h >= cfg.range_lower) & (bars_h <= cfg.range_upper))

    on = bool(cfg.show_div)
    bull = pl_found & price_ll & rsi_hl & in_range_l & on
    bear = ph_found & price_hh & rsi_lh & in_range_h & on

    return pd.DataFrame(
        {
            "rsi": rsi.to_numpy(),
            "rsi_ma": ma_pine(rsi, cfg.rsi_ma_len, cfg.rsi_ma_type).to_numpy(),
            "rsi_long_avg": sma_pine(rsi, cfg.rsi_long_avg_len).to_numpy(),
            "pl_found": pl_found,
            "ph_found": ph_found,
            "rsi_at_pivot": rsi_at.to_numpy(),
            "low_at_pivot": low_at.to_numpy(),
            "high_at_pivot": high_at.to_numpy(),
            "prev_rsi_at_low_pivot": prev_rsi_l.to_numpy(),
            "prev_low_at_pivot": prev_low.to_numpy(),
            "prev_rsi_at_high_pivot": prev_rsi_h.to_numpy(),
            "prev_high_at_pivot": prev_high.to_numpy(),
            "bars_since_prev_low_pivot": bars_l,
            "bars_since_prev_high_pivot": bars_h,
            "rsi_hl": rsi_hl,
            "price_ll": price_ll,
            "rsi_lh": rsi_lh,
            "price_hh": price_hh,
            "in_range_low": in_range_l,
            "in_range_high": in_range_h,
            "bull_div": bull,
            "bear_div": bear,
        },
        index=idx,
    )


# =============================================================================
# RULE B -- the scored Fast x Mid cross (Final_Top_Script.pine)
# =============================================================================


def cross_signal(df: pd.DataFrame, cfg: Optional[ScreenConfig] = None) -> pd.DataFrame:
    """Final_Top_Script.pine, the signal block:

        maFast = f_ma(maSrc, fastLen)          // EMA 20 by default
        maMid  = f_ma(maSrc, midLen)           // EMA 50
        maSlow = f_ma(maSrc, slowLen)          // EMA 200
        regime = maMid > maSlow
        bullX  = ta.crossover(maFast, maMid)
        bearX  = ta.crossunder(maFast, maMid)
        bullScore = 1 + (useMacd and macdHist > 0 ? 1 : 0)
                      + (useSlow and close > maSlow ? 1 : 0)
                      + (useRsi  and rsiV > 50 ? 1 : 0)
        bearScore = 1 + (useMacd and macdHist < 0 ? 1 : 0)
                      + (useSlow and close < maSlow ? 1 : 0)
                      + (useRsi  and rsiV < 50 ? 1 : 0)
        bullSig = showSig and bullX and bullScore >= minScore
        bearSig = showSig and bearX and bearScore >= minScore

    The score is computed on EVERY bar in the Pine too; only the cross bars
    ever read it. With the shipped defaults (useRsi off) the maximum is 3.

    On a history shorter than `slowLen` the 200 MA is na, so `close > maSlow`
    is false and the +1 is simply not awarded -- a young crypto listing can
    therefore never score above 2. That is Pine's behaviour, reproduced
    rather than patched, and the screen reports `slow_ready` so a reviewer
    can see it.
    """
    cfg = (cfg or DEFAULT_CONFIG)
    d = df
    src = d[cfg.ma_source] if cfg.ma_source in d.columns else d["close"]
    close = d["close"]

    fast = ma_pine(src, cfg.fast_len, cfg.ma_type)
    mid = ma_pine(src, cfg.mid_len, cfg.ma_type)
    slow = ma_pine(src, cfg.slow_len, cfg.ma_type)
    _macd, _sig, hist = macd_pine(
        d[cfg.macd_source] if cfg.macd_source in d.columns else close,
        cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    rsi = rsi_wilder(close, cfg.top_rsi_len)

    bull_x = crossover(fast, mid).to_numpy()
    bear_x = crossunder(fast, mid).to_numpy()

    h = hist.to_numpy()
    c = close.to_numpy()
    s = slow.to_numpy()
    rv = rsi.to_numpy()

    macd_up = _nan_safe(h > 0.0) if cfg.use_macd else np.zeros(len(d), dtype=bool)
    macd_dn = _nan_safe(h < 0.0) if cfg.use_macd else np.zeros(len(d), dtype=bool)
    slow_up = _nan_safe(c > s) if cfg.use_slow else np.zeros(len(d), dtype=bool)
    slow_dn = _nan_safe(c < s) if cfg.use_slow else np.zeros(len(d), dtype=bool)
    rsi_up = _nan_safe(rv > cfg.rsi_midline) if cfg.use_rsi else np.zeros(len(d), dtype=bool)
    rsi_dn = _nan_safe(rv < cfg.rsi_midline) if cfg.use_rsi else np.zeros(len(d), dtype=bool)

    bull_score = 1 + macd_up.astype(int) + slow_up.astype(int) + rsi_up.astype(int)
    bear_score = 1 + macd_dn.astype(int) + slow_dn.astype(int) + rsi_dn.astype(int)

    bull_sig = bull_x & (bull_score >= cfg.min_score)
    bear_sig = bear_x & (bear_score >= cfg.min_score)

    return pd.DataFrame(
        {
            "fast": fast.to_numpy(),
            "mid": mid.to_numpy(),
            "slow": slow.to_numpy(),
            "macd_hist": h,
            "top_rsi": rv,
            "regime_up": _nan_safe(mid.to_numpy() > s),
            "slow_ready": ~np.isnan(s),
            "bull_cross": bull_x,
            "bear_cross": bear_x,
            "bull_score": bull_score,
            "bear_score": bear_score,
            "bull_signal": bull_sig,
            "bear_signal": bear_sig,
            "macd_agrees_bull": macd_up,
            "macd_agrees_bear": macd_dn,
            "above_slow": slow_up,
            "below_slow": slow_dn,
        },
        index=d.index,
    )


# =============================================================================
# per-bar evaluation (the thing the look-ahead test compares)
# =============================================================================


def evaluate(df: pd.DataFrame, cfg: Optional[ScreenConfig] = None) -> pd.DataFrame:
    """Everything both rules need, one row per bar, causal by construction.

    This is the single source of truth: screen_symbol() only ever reads the
    tail of this frame, and assert_no_lookahead() compares it against itself
    computed on truncated inputs.
    """
    cfg = (cfg or DEFAULT_CONFIG)
    d = prepare_frame(df)
    if len(d) == 0:
        return pd.DataFrame(index=d.index)
    div = rsi_divergence(d, cfg)
    sig = cross_signal(d, cfg)
    atr = atr_wilder(d, cfg.atr_len)
    out = pd.concat([d, div, sig], axis=1)
    out["atr"] = atr.to_numpy()
    return out


# =============================================================================
# the screen
# =============================================================================


def _last_true(mask: np.ndarray, within: int) -> Optional[int]:
    """Index of the most recent True within the last `within` bars, else None.
    `within = 1` means the final bar only."""
    n = mask.size
    if n == 0 or within < 1:
        return None
    lo = max(0, n - int(within))
    tail = np.flatnonzero(mask[lo:])
    if tail.size == 0:
        return None
    return int(lo + tail[-1])


def _f(x: Any) -> Optional[float]:
    """Plain float or None -- keeps NaN out of the output dicts, because a
    NaN silently makes every downstream comparison False."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def screen_symbol(df: pd.DataFrame, cfg: Optional[ScreenConfig] = None,
                  symbol: str = "", market: str = "") -> Dict[str, Any]:
    """Screen one symbol as of its LAST bar. Never raises on bad data.

    The caller is responsible for handing in CLOSED bars only: on the ASX and
    NASDAQ that means dropping today's partial bar, and on crypto it means
    dropping the in-progress UTC day. A partial last bar is not an error this
    function can detect, and it is the single easiest way to manufacture a
    signal that evaporates overnight.

    Returns a flat dict. `ok=False` with a `reason` for anything unscreenable
    (too short, empty, unreadable), never an exception.
    """
    cfg = (cfg or DEFAULT_CONFIG)
    base: Dict[str, Any] = {
        "symbol": symbol, "market": market, "ok": False, "reason": "",
        "passes": False, "rules": "", "direction": "",
        "n_bars": 0, "last_bar": None,
        "rule_a": False, "rule_a_direction": "", "rule_a_bars_ago": None,
        "rule_a_label_bars_ago": None, "rule_a_pivot_bars_ago": None,
        "rule_b": False, "rule_b_direction": "", "rule_b_score": None,
        "rule_b_bars_ago": None,
        "score": None, "best_bars_ago": None,
        "close": None, "rsi": None, "rsi_ma": None, "atr": None, "atr_pct": None,
        "trend": "", "regime": "", "above_slow": None, "slow_ready": False,
        "macd_hist": None, "fast": None, "mid": None, "slow": None,
        "rsi_zone": "", "history_warning": "",
    }
    try:
        cfg = cfg.validate()
    except ValueError as exc:
        # A bad config is a programming error, but this function is called in
        # a 3,600-symbol loop; reporting it on the row beats a traceback that
        # kills the scan, and screen_frames() still validates once up front.
        base["reason"] = "invalid config: %s" % exc
        return base
    try:
        d = prepare_frame(df)
    except Exception as exc:  # noqa: BLE001 - a bad frame must not kill a scan
        base["reason"] = "unreadable frame: %s" % exc
        return base

    n = len(d)
    base["n_bars"] = int(n)
    if n == 0:
        base["reason"] = "no bars"
        return base
    base["last_bar"] = str(d.index[-1])
    if n < max(int(cfg.min_bars), cfg.piv_left + cfg.piv_right + 2):
        base["reason"] = "history too short (%d bars, need %d)" % (n, cfg.min_bars)
        return base

    try:
        ev = evaluate(d, cfg)
    except Exception as exc:  # noqa: BLE001
        base["reason"] = "evaluation failed: %s" % exc
        return base

    base["ok"] = True
    last = ev.iloc[-1]

    # ---- context a human reviewer wants on the row -------------------------
    base["close"] = _f(last["close"])
    base["rsi"] = _f(last["rsi"])
    base["rsi_ma"] = _f(last["rsi_ma"])
    base["atr"] = _f(last["atr"])
    if base["atr"] is not None and base["close"]:
        base["atr_pct"] = round(100.0 * base["atr"] / base["close"], 2)
    base["fast"] = _f(last["fast"])
    base["mid"] = _f(last["mid"])
    base["slow"] = _f(last["slow"])
    base["macd_hist"] = _f(last["macd_hist"])
    base["slow_ready"] = bool(last["slow_ready"])
    base["above_slow"] = bool(last["above_slow"]) if base["slow_ready"] else None
    base["trend"] = ("up" if bool(last["regime_up"]) else "down") if base["slow_ready"] else "unknown"
    f_, m_, s_ = base["fast"], base["mid"], base["slow"]
    if None not in (f_, m_, s_):
        if f_ > m_ > s_:
            base["regime"] = "fast>mid>slow"
        elif f_ < m_ < s_:
            base["regime"] = "fast<mid<slow"
        else:
            base["regime"] = "mixed"
    elif None not in (f_, m_):
        base["regime"] = "fast>mid" if f_ > m_ else "fast<mid"
    r = base["rsi"]
    if r is not None:
        if r >= cfg.rsi_ob2:
            base["rsi_zone"] = "extreme-overbought"
        elif r >= cfg.rsi_ob1:
            base["rsi_zone"] = "overbought"
        elif r <= cfg.rsi_os2:
            base["rsi_zone"] = "extreme-oversold"
        elif r <= cfg.rsi_os1:
            base["rsi_zone"] = "oversold"
        else:
            base["rsi_zone"] = "neutral"
    if n < cfg.warn_bars:
        base["history_warning"] = (
            "only %d bars: the %d MA is %s"
            % (n, cfg.slow_len, "absent" if not base["slow_ready"] else "barely seeded")
        )

    # ---- RULE A ------------------------------------------------------------
    bull_div = ev["bull_div"].to_numpy()
    bear_div = ev["bear_div"].to_numpy()
    if "bull" not in cfg.div_directions:
        bull_div = np.zeros(n, dtype=bool)
    if "bear" not in cfg.div_directions:
        bear_div = np.zeros(n, dtype=bool)
    i_bull = _last_true(bull_div, cfg.div_fresh_bars)
    i_bear = _last_true(bear_div, cfg.div_fresh_bars)
    i_a = max([x for x in (i_bull, i_bear) if x is not None], default=None)
    if i_a is not None:
        both = i_bull is not None and i_bear is not None and i_bull == i_bear
        d_a = "both" if both else ("bull" if i_a == i_bull else "bear")
        row = ev.iloc[i_a]
        base["rule_a"] = True
        base["rule_a_direction"] = d_a
        base["rule_a_bars_ago"] = int(n - 1 - i_a)
        base["rule_a_label_bars_ago"] = int(n - 1 - i_a + cfg.piv_right)
        base["rule_a_pivot_bars_ago"] = int(n - 1 - i_a + cfg.piv_right)
        base["rule_a_pivot_bar"] = str(ev.index[max(0, i_a - cfg.piv_right)])
        base["rule_a_rsi_at_pivot"] = _f(row["rsi_at_pivot"])
        if d_a in ("bull", "both"):
            base["rule_a_prev_rsi"] = _f(row["prev_rsi_at_low_pivot"])
            base["rule_a_price_at_pivot"] = _f(row["low_at_pivot"])
            base["rule_a_prev_price"] = _f(row["prev_low_at_pivot"])
            base["rule_a_bars_between_pivots"] = _f(row["bars_since_prev_low_pivot"])
        else:
            base["rule_a_prev_rsi"] = _f(row["prev_rsi_at_high_pivot"])
            base["rule_a_price_at_pivot"] = _f(row["high_at_pivot"])
            base["rule_a_prev_price"] = _f(row["prev_high_at_pivot"])
            base["rule_a_bars_between_pivots"] = _f(row["bars_since_prev_high_pivot"])

    # ---- RULE B ------------------------------------------------------------
    bull_sig = ev["bull_signal"].to_numpy() & (ev["bull_score"].to_numpy() >= cfg.min_signal_score)
    bear_sig = ev["bear_signal"].to_numpy() & (ev["bear_score"].to_numpy() >= cfg.min_signal_score)
    if "bull" not in cfg.signal_directions:
        bull_sig = np.zeros(n, dtype=bool)
    if "bear" not in cfg.signal_directions:
        bear_sig = np.zeros(n, dtype=bool)
    j_bull = _last_true(bull_sig, cfg.signal_fresh_bars)
    j_bear = _last_true(bear_sig, cfg.signal_fresh_bars)
    j_b = max([x for x in (j_bull, j_bear) if x is not None], default=None)
    if j_b is not None:
        d_b = "bull" if j_b == j_bull else "bear"
        row = ev.iloc[j_b]
        score = int(row["bull_score"] if d_b == "bull" else row["bear_score"])
        base["rule_b"] = True
        base["rule_b_direction"] = d_b
        base["rule_b_score"] = score
        base["rule_b_signed_score"] = score if d_b == "bull" else -score
        base["rule_b_label"] = ("Bullish +%d" % score) if d_b == "bull" else ("-%d Bearish" % score)
        base["rule_b_bars_ago"] = int(n - 1 - j_b)
        base["rule_b_bar"] = str(ev.index[j_b])
        base["rule_b_close"] = _f(row["close"])
        base["rule_b_macd_hist"] = _f(row["macd_hist"])
        base["rule_b_above_slow"] = bool(row["above_slow"])
        base["rule_b_below_slow"] = bool(row["below_slow"])
        base["rule_b_max_score"] = cfg.max_score
        base["score"] = score

    # ---- verdict -----------------------------------------------------------
    rules: List[str] = []
    if base["rule_a"]:
        rules.append("A")
    if base["rule_b"]:
        rules.append("B")
    base["rules"] = "+".join(rules)
    base["passes"] = bool(base["rule_a"]) if cfg.mode == 1 else bool(base["rule_a"] or base["rule_b"])
    if cfg.mode == 1:
        base["rules"] = "A" if base["rule_a"] else ""
        base["rule_b"] = base["rule_b"]  # reported, not used
    # `direction` has to honour `mode` exactly as `rules`, `passes` and
    # `best_bars_ago` above it already do. In mode 1 RULE B is REPORTED and
    # not used, so it must not be able to turn a clean bull divergence into
    # `conflict`, nor give a non-passing row a direction at all.
    dirs = {base["rule_a_direction"]}
    if cfg.mode == 2:
        dirs.add(base["rule_b_direction"])
    dirs -= {""}
    if "both" in dirs or dirs == {"bull", "bear"}:
        base["direction"] = "conflict"
    elif dirs:
        base["direction"] = dirs.pop()
    ages = [a for a in (base["rule_a_bars_ago"],
                        base["rule_b_bars_ago"] if cfg.mode == 2 else None) if a is not None]
    base["best_bars_ago"] = min(ages) if ages else None
    return base


def screen_frames(frames: Mapping[str, pd.DataFrame], cfg: Optional[ScreenConfig] = None,
                  market: str = "", include_failures: bool = False) -> pd.DataFrame:
    """Screen a whole universe. Returns one row per symbol, ranked.

    Ranking is deliberately NOT a quality model -- there is no evidence here
    that a score of 3 outperforms a 2, and sorting a scanner by its own
    backtest is how a page becomes a curve fit. The order is only "what a
    reviewer should look at first", and every tier is a stated preference
    rather than a measured one:

        1. passing rows before non-passing
        2. freshest first (bars_ago ascending)
        3. both rules before one rule
        4. RULE A before a RULE-B-only row -- the divergence is the owner's
           headline rule, the one mode 1 screens on by itself
        5. higher |score| first
        6. symbol, so the output is deterministic

    `include_failures=False` (the default) returns only the passing rows.
    """
    cfg = (cfg or DEFAULT_CONFIG).validate()
    rows: List[Dict[str, Any]] = []
    for sym in sorted(frames):
        rows.append(screen_symbol(frames[sym], cfg, symbol=str(sym), market=market))
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    if not include_failures:
        out = out[out["passes"]]
        if out.empty:
            return out.reset_index(drop=True)
    out = out.assign(
        _age=pd.to_numeric(out["best_bars_ago"], errors="coerce").fillna(10 ** 6),
        _nrules=out["rules"].astype("object").fillna("").map(
            lambda s: -len(str(s).split("+")) if s else 0),
        _nota=(~out["rule_a"].astype(bool)).astype(int),
        _score=-pd.to_numeric(out["score"], errors="coerce").fillna(0),
    ).sort_values(
        by=["passes", "_age", "_nrules", "_nota", "_score", "symbol"],
        ascending=[False, True, True, True, True, True],
        kind="mergesort",
    ).drop(columns=["_age", "_nrules", "_nota", "_score"])
    return out.reset_index(drop=True)


# =============================================================================
# the causality proof
# =============================================================================

#: the columns whose value on bar i must not change when later bars arrive
CAUSAL_COLUMNS: Tuple[str, ...] = (
    # the verdicts
    "bull_div", "bear_div", "bull_signal", "bear_signal",
    # everything they are built from
    "rsi", "rsi_ma", "rsi_long_avg", "pl_found", "ph_found",
    "rsi_at_pivot", "low_at_pivot", "high_at_pivot",
    "prev_rsi_at_low_pivot", "prev_low_at_pivot",
    "prev_rsi_at_high_pivot", "prev_high_at_pivot",
    "bars_since_prev_low_pivot", "bars_since_prev_high_pivot",
    "rsi_hl", "price_ll", "rsi_lh", "price_hh",
    "in_range_low", "in_range_high",
    "fast", "mid", "slow", "macd_hist", "top_rsi", "regime_up", "slow_ready",
    "bull_cross", "bear_cross", "bull_score", "bear_score",
    "macd_agrees_bull", "macd_agrees_bear", "above_slow", "below_slow",
    "atr",
)


def assert_no_lookahead(df: pd.DataFrame, cfg: Optional[ScreenConfig] = None,
                        bars: Optional[Sequence[int]] = None,
                        tol: float = 1e-12) -> int:
    """Prove that no value on bar i depends on a bar after i.

    For each tested cut point i, recompute everything on df[:i+1] and compare
    the final row against row i of the full-history computation. Any
    disagreement raises AssertionError naming the column and the bar.

    This is the test that a divergence implementation most often fails: the
    tempting shortcut is to stamp the divergence on the PIVOT bar, which is
    only knowable `piv_right` bars later, and the resulting screen looks
    wonderful in a backtest and fires late in production.

    Returns the number of cut points checked.
    """
    cfg = (cfg or DEFAULT_CONFIG)
    d = prepare_frame(df)
    n = len(d)
    full = evaluate(d, cfg)
    if bars is None:
        lo = max(cfg.slow_len + 5, cfg.min_bars, 40)
        bars = [i for i in range(min(lo, n - 1), n)]
    checked = 0
    for i in bars:
        if i < 1 or i >= n:
            continue
        cut = evaluate(d.iloc[: i + 1], cfg)
        a = full.iloc[i]
        b = cut.iloc[-1]
        for col in CAUSAL_COLUMNS:
            if col not in full.columns:
                continue
            av, bv = a[col], b[col]
            if isinstance(av, (bool, np.bool_)) or isinstance(bv, (bool, np.bool_)):
                if bool(av) != bool(bv):
                    raise AssertionError(
                        "LOOK-AHEAD in %r at bar %d: full=%r truncated=%r" % (col, i, av, bv))
                continue
            af, bf = float(av), float(bv)
            if math.isnan(af) and math.isnan(bf):
                continue
            if math.isnan(af) != math.isnan(bf) or abs(af - bf) > tol:
                raise AssertionError(
                    "LOOK-AHEAD in %r at bar %d: full=%r truncated=%r" % (col, i, av, bv))
        checked += 1
    return checked
