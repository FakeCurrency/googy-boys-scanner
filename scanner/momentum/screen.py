"""The screen: Rule A (RSI divergence), Rule B (scored 20/50 cross), and the
per-symbol verdict.

    RULE A  an RSI regular divergence off STRICT pivots, confirmed within
            `div_fresh_bars` closed bars.
    RULE B  a 20/50 cross whose score (1 + MACD agrees + price beyond the 200)
            is at least `min_signal_score`, printed within `signal_fresh_bars`.

THE TWO RULES DO NOT MEAN THE SAME THING, and the output says so rather than
papering over it. Rule B has ZERO detection lag: a cross on bar i is knowable at
the close of bar i. Rule A has a FIVE-BAR lag, because you cannot know bar k was
a local low until you have seen the five bars after it -- so a divergence
confirmed on bar i describes a pivot at i-5, and that is where TradingView draws
the label. If both rules report `bars_ago = 1`, the underlying market events are
SIX BARS APART in age. Every row therefore carries both `rule_a_bars_ago` (when
the scanner could know) and `rule_a_pivot_bars_ago` (the event it describes,
always exactly `piv_right` more). Any implementation reporting a divergence
sooner than that has a look-ahead bug, which `assert_no_lookahead` exists to
catch.

MODES (spec 5.4). A = Rule A only. B = Rule A OR Rule B -- a UNION, not "B
alone"; there is no B-only screen. C = both fired AND their directions agree,
and C is deliberately NOT a third code path: it is mode B plus a post-filter,
because "both rules agreeing" is a VIEW of the same computation rather than a
different screen. So the engine treats C exactly as B and the selection step
filters. v1 defaults to A.

A CONFLICT IS FLAGGED, NEVER DROPPED. A bullish divergence beside a bearish
cross is genuinely interesting -- momentum turning up while trend structure
turns down -- so `direction` resolves to "conflict" and a human sees it, rather
than a priority rule silently picking a side.

# PORTED VERBATIM from tradingview/scanner-spec/reference/vivek50_screen.py.
# The function bodies below were EXTRACTED, not retyped -- a hand-transcription
# of trading maths drifts silently, and `tests/test_momentum_screen.py` proves
# bit-identity against the reference rather than trusting this comment. The
# only edits are namespace ones:
#   ScreenConfig    -> MomentumConfig
#   DEFAULT_CONFIG  -> config.DEFAULTS
#   cfg.mode == 1   -> cfg.mode == "A"
#   cfg.mode == 2   -> cfg.mode != "A"
"""

from __future__ import annotations

import math

from typing import Any, Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

from . import config
from .config import OHLC_COLUMNS, MomentumConfig
from .ema import atr_wilder, ma_pine, rsi_wilder, sma_pine, _nan_safe
from .macd import macd_pine
from .pivots import (barssince, crossover, crossunder, pivot_high_confirmed,
                     pivot_low_confirmed, shift_bool, valuewhen)

__all__ = [
    "prepare_frame", "rsi_divergence", "cross_signal", "evaluate",
    "screen_symbol", "screen_frames", "assert_no_lookahead",
]


# ---------------------------------------------------------------------------
# frame hygiene -- the front door, and the four defects it was hardened against
# ---------------------------------------------------------------------------
# An adversarial pass over the reference found four real bugs here. The worst:
# a REVERSE-CHRONOLOGICAL frame was screened silently and returned a complete,
# plausible, WRONG answer. It is now REFUSED rather than auto-sorted -- sorting
# it would launder the caller's mistake and hand the next caller with a
# genuinely corrupt frame silence instead of an error.
# This is also where TITLE-case columns become lowercase, so the repo's
# yfinance frames feed straight in without the loader knowing anything.

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


# ---------------------------------------------------------------------------
# RULE A -- RSI regular divergence
# ---------------------------------------------------------------------------

def rsi_divergence(df: pd.DataFrame, cfg: Optional[MomentumConfig] = None) -> pd.DataFrame:
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
    cfg = (cfg or config.DEFAULTS)
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


# ---------------------------------------------------------------------------
# RULE B -- the scored Fast x Mid cross
# ---------------------------------------------------------------------------

def cross_signal(df: pd.DataFrame, cfg: Optional[MomentumConfig] = None) -> pd.DataFrame:
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
    cfg = (cfg or config.DEFAULTS)
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


# ---------------------------------------------------------------------------
# the combined evidence frame
# ---------------------------------------------------------------------------

def evaluate(df: pd.DataFrame, cfg: Optional[MomentumConfig] = None) -> pd.DataFrame:
    """Everything both rules need, one row per bar, causal by construction.

    This is the single source of truth: screen_symbol() only ever reads the
    tail of this frame, and assert_no_lookahead() compares it against itself
    computed on truncated inputs.
    """
    cfg = (cfg or config.DEFAULTS)
    d = prepare_frame(df)
    if len(d) == 0:
        return pd.DataFrame(index=d.index)
    div = rsi_divergence(d, cfg)
    sig = cross_signal(d, cfg)
    atr = atr_wilder(d, cfg.atr_len)
    out = pd.concat([d, div, sig], axis=1)
    out["atr"] = atr.to_numpy()
    return out


# ---------------------------------------------------------------------------
# the screen
# ---------------------------------------------------------------------------

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


def screen_symbol(df: pd.DataFrame, cfg: Optional[MomentumConfig] = None,
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
    cfg = (cfg or config.DEFAULTS)
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
    base["passes"] = bool(base["rule_a"]) if cfg.mode == "A" else bool(base["rule_a"] or base["rule_b"])
    if cfg.mode == "A":
        base["rules"] = "A" if base["rule_a"] else ""
        base["rule_b"] = base["rule_b"]  # reported, not used
    # `direction` has to honour `mode` exactly as `rules`, `passes` and
    # `best_bars_ago` above it already do. In mode 1 RULE B is REPORTED and
    # not used, so it must not be able to turn a clean bull divergence into
    # `conflict`, nor give a non-passing row a direction at all.
    dirs = {base["rule_a_direction"]}
    if cfg.mode != "A":
        dirs.add(base["rule_b_direction"])
    dirs -= {""}
    if "both" in dirs or dirs == {"bull", "bear"}:
        base["direction"] = "conflict"
    elif dirs:
        base["direction"] = dirs.pop()
    ages = [a for a in (base["rule_a_bars_ago"],
                        base["rule_b_bars_ago"] if cfg.mode != "A" else None) if a is not None]
    base["best_bars_ago"] = min(ages) if ages else None
    return base


def screen_frames(frames: Mapping[str, pd.DataFrame], cfg: Optional[MomentumConfig] = None,
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
    cfg = (cfg or config.DEFAULTS).validate()
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


# ---------------------------------------------------------------------------
# the causality proof
# ---------------------------------------------------------------------------

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

# Truncate the frame at each bar, re-derive the verdict, and require it to match
# what the full frame said about that bar. A screener that fails this is reading
# the future, and the failure is invisible in any single-frame test.

def assert_no_lookahead(df: pd.DataFrame, cfg: Optional[MomentumConfig] = None,
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
    cfg = (cfg or config.DEFAULTS)
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
