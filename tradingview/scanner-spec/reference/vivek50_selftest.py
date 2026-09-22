"""Self-test / demo for vivek50_screen.

Run it:   python3 vivek50_selftest.py
Or:       python3 -m pytest -q vivek50_selftest.py

Every frame is synthetic and deterministic -- no network, no yfinance, no
random seed. Each builder is shaped to force one specific behaviour, and the
expected bar indices are hardcoded so a silent off-by-one fails the run
instead of quietly moving.

Cases, in the order the task set them:
  (a) textbook bullish RSI divergence, fires exactly 5 bars after the pivot
  (b) the bearish mirror
  (c) a 20/50 cross with MACD hist > 0 and close above the 200 -> score 3
  (d) a 20/50 cross with MACD hist < 0 and close below the 200 -> score 1
  (e) a flat / halted series -> no pivots, no divergence, no crash
  (f) no look-ahead: truncate at bar i, the verdict at bar i is unchanged
  (g) a frame shorter than 200 bars -> no crash, sensible output
plus the Pine primitives (rma / rsi / ema / macd / atr warm-ups, the
crossover NaN rule, the pivot confirmation delay, and the barssince
off-by-one that sets the real 6..61 bar window between pivots).
"""

from __future__ import annotations

import math
import sys
from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

import vivek50_screen as V

# =============================================================================
# deterministic synthetic frame builders
# =============================================================================

WOBBLE_AMP = 0.4    # absolute price units of sine wobble
WOBBLE_PERIOD = 7   # bars per wobble cycle
SPREAD = 0.004      # intrabar range as a fraction, so high/low are not close


def frame_from_close(close: Sequence[float], spread: float = SPREAD) -> pd.DataFrame:
    """OHLCV from a close path: open = previous close, high/low straddle both."""
    c = np.asarray(close, dtype=float)
    n = c.size
    prev = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame(
        {
            "open": prev,
            "high": np.maximum(c, prev) * (1.0 + spread),
            "low": np.minimum(c, prev) * (1.0 - spread),
            "close": c,
            "volume": np.full(n, 1_000_000.0),
        },
        index=pd.bdate_range("2024-01-01", periods=n, name="date"),
    )


def seg(a: float, b: float, n: int) -> List[float]:
    """n bars walking linearly from a (exclusive) to b (inclusive)."""
    return list(np.linspace(a, b, n + 1)[1:])


def wobble(path: Sequence[float]) -> np.ndarray:
    c = np.asarray(path, dtype=float)
    return c + WOBBLE_AMP * np.sin(2.0 * np.pi * np.arange(c.size) / WOBBLE_PERIOD)


def bull_div_frame() -> pd.DataFrame:
    """Price makes a LOWER low while RSI makes a HIGHER low.

    60 bars of drift, a 15-bar crash to 80 (RSI floor), a 20-bar bounce to 95,
    then a 30-bar GRIND to 78 -- lower in price, but slow enough that RSI
    holds well above its crash reading -- then a 16-bar recovery so the second
    pivot can confirm. 141 bars; the divergence confirms on bar 129.
    """
    c = [100.0]
    c += seg(100, 101, 59)    # bars 1..59   warm-up drift
    c += seg(101, 80, 15)     # bars 60..74  crash  -> RSI trough 1 (deep)
    c += seg(80, 95, 20)      # bars 75..94  bounce
    c += seg(95, 78, 30)      # bars 95..124 grind  -> RSI trough 2 (shallow)
    c += seg(78, 88, 16)      # bars 125..140 recovery, confirms the pivot
    return frame_from_close(wobble(c))


def bear_div_frame() -> pd.DataFrame:
    """The mirror: price makes a HIGHER high while RSI makes a LOWER high.
    141 bars; the divergence confirms on bar 129."""
    c = [99.0]
    c += seg(99, 100, 59)
    c += seg(100, 125, 15)    # melt-up -> RSI peak 1 (extreme)
    c += seg(125, 109, 20)    # pullback
    c += seg(109, 128, 30)    # slow grind to a HIGHER high -> RSI peak 2 (lower)
    c += seg(128, 116, 16)
    return frame_from_close(wobble(c))


def score3_frame() -> pd.DataFrame:
    """A 20/50 bull cross inside a mature uptrend: MACD hist > 0 and close is
    far above the 200 EMA. 311 bars; the only bull cross is on bar 292."""
    c = [50.0]
    c += seg(50, 150, 260)    # 261 bars of uptrend, seeds the 200 EMA low
    c += seg(150, 132, 20)    # a dip deep enough to cross the 20 under the 50
    c += seg(132, 165, 30)    # the recovery that crosses it back over
    return frame_from_close(c)


def score1_frame() -> pd.DataFrame:
    """A 20/50 bull cross inside a downtrend: price is below the 200 EMA and
    the MACD histogram has ALREADY rolled back under zero by the time the
    slower 20/50 cross completes. 294 bars; the bull cross is the LAST bar."""
    c = [200.0]
    c += seg(200, 80, 260)            # 261 bars of downtrend
    base = c[-1]
    c += seg(base, base * 1.14, 15)   # a 14 % dead-cat bounce
    top = c[-1]
    c += seg(top, top * 0.99, 18)     # then a stall: hist rolls over, 20 keeps rising
    return frame_from_close(c)


def flat_frame(n: int = 300, price: float = 42.0) -> pd.DataFrame:
    """A halted name: every OHLC value identical on every bar."""
    return pd.DataFrame(
        {"open": np.full(n, price), "high": np.full(n, price),
         "low": np.full(n, price), "close": np.full(n, price),
         "volume": np.zeros(n)},
        index=pd.bdate_range("2024-01-01", periods=n, name="date"),
    )


def short_frame(n: int = 120) -> pd.DataFrame:
    """A young listing: real movement, but fewer bars than the 200 MA needs."""
    c = [10.0] + seg(10, 14, n - 1)
    return frame_from_close(wobble(c))


def gappy_frame() -> pd.DataFrame:
    """Holes in the data: NaN rows and a calendar gap. Must not raise."""
    f = bull_div_frame().copy()
    f.iloc[20:23, :] = np.nan            # three bars with no price at all
    f.iloc[45, f.columns.get_loc("close")] = np.nan
    return f.drop(f.index[60:64])        # a four-session hole in the calendar


# =============================================================================
# helpers
# =============================================================================

def true_bars(series: pd.Series) -> List[int]:
    return [int(i) for i in np.flatnonzero(np.asarray(series, dtype=bool))]


def banner(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


# =============================================================================
# primitives
# =============================================================================

def test_warmup_lengths_match_pine() -> None:
    """Pine emits na until a ta.* function has enough source bars. The first
    non-na bar index is a fingerprint of the seeding rule, so it is pinned."""
    f = frame_from_close([100.0] + seg(100, 130, 299))
    ev = V.evaluate(f)
    assert ev["rsi"].first_valid_index() == f.index[14], "ta.rsi(14) first value is bar 14"
    assert ev["slow"].first_valid_index() == f.index[199], "ta.ema(200) first value is bar 199"
    assert ev["macd_hist"].first_valid_index() == f.index[33], (
        "ta.macd hist: ema26 seeds at bar 25, ema9 of it needs 9 values -> bar 33")
    assert ev["atr"].first_valid_index() == f.index[13], "ta.atr(14) first value is bar 13"
    assert ev["fast"].first_valid_index() == f.index[19]
    assert ev["mid"].first_valid_index() == f.index[49]
    print("warm-ups: rsi14=14  ema20=19  ema50=49  ema200=199  macdhist=33  atr14=13")


def test_rma_is_wilder_not_an_ema() -> None:
    v = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    r = V.wilder_rma(v, 4)
    assert np.isnan(r.iloc[2])
    assert abs(r.iloc[3] - 2.5) < 1e-12, "seed is the SMA of the first 4 values"
    expect = 2.5 + (5.0 - 2.5) / 4.0
    assert abs(r.iloc[4] - expect) < 1e-12, "alpha = 1/length, not 2/(length+1)"
    e = V.ema_pine(v, 4)
    assert abs(e.iloc[3] - 2.5) < 1e-12
    assert abs(e.iloc[4] - (2.5 + 0.4 * (5.0 - 2.5))) < 1e-12, "ema alpha = 2/(n+1) = 0.4"
    print("rma alpha=1/4 seeded on SMA; ema alpha=0.4 seeded on SMA -- both confirmed")


def test_rsi_degenerate_cases() -> None:
    up = V.rsi_wilder(pd.Series(np.arange(1.0, 40.0)), 14)
    assert abs(up.iloc[-1] - 100.0) < 1e-9, "only gains -> rma(down)==0 -> 100"
    dn = V.rsi_wilder(pd.Series(np.arange(40.0, 1.0, -1.0)), 14)
    assert abs(dn.iloc[-1] - 0.0) < 1e-9, "only losses -> rma(up)==0 -> 0"
    fl = V.rsi_wilder(pd.Series(np.full(40, 7.0)), 14)
    assert math.isnan(fl.iloc[-1]), (
        "both averages zero -> rs = 0/0 -> NaN. This used to assert 100 on the "
        "invented premise that Pine 'tests the zero denominator first'; ta.rsi "
        "is a single division and has no such branch")
    # a ramp that then halts is NOT the same case: rma(down) is exactly zero
    # but rma(up) is not, so rs = +inf and 100 is correct and stays correct.
    ramp = list(np.linspace(10.0, 20.0, 50)) + [20.0] * 30
    assert abs(V.rsi_wilder(pd.Series(ramp), 14).iloc[-1] - 100.0) < 1e-9, (
        "only-gains-then-halted is a genuine 100, not the 0/0 case")
    print("rsi degenerate cases: all-up=100  all-down=0  flat=NaN (0/0)  "
          "ramp-then-halt=100")


def test_crossover_is_nan_safe_and_uses_the_previous_bar() -> None:
    a = pd.Series([np.nan, np.nan, 1.0, 3.0, 3.0, 1.0])
    b = pd.Series([np.nan, 2.0, 2.0, 2.0, 2.0, 2.0])
    up = V.crossover(a, b)
    dn = V.crossunder(a, b)
    assert true_bars(up) == [3], "a[1] <= b[1] and a > b"
    assert true_bars(dn) == [5], "a[1] >= b[1] and a < b"
    assert not up.iloc[1] and not up.iloc[2], "a NaN operand can never make a cross true"
    print("crossover/crossunder: NaN-safe, previous-bar rule confirmed")


def test_pivot_is_confirmed_right_bars_late() -> None:
    v = pd.Series([5, 4, 3, 2, 1, 2, 3, 4, 5, 6, 7], dtype=float)
    pl = V.pivot_low_confirmed(v, 2, 2)
    hit = [i for i in range(len(v)) if not np.isnan(pl.iloc[i])]
    assert hit == [6], "the pivot low sits on bar 4 and is only known on bar 4+2"
    assert pl.iloc[6] == 1.0, "the value reported is the pivot's own value"
    flat = V.pivot_low_confirmed(pd.Series(np.full(30, 3.0)), 5, 5)
    assert flat.notna().sum() == 0, "a tie disqualifies: a flat series has no pivots"
    print("pivot: confirmed exactly `right` bars late, value = the pivot's own")


def test_the_barssince_off_by_one_sets_a_6_to_61_bar_window() -> None:
    """f_inRange is called with plFound[1], not plFound.

    ta.barssince(plFound[1]) on a bar where plFound is true equals
    (gap between the two confirmation bars) - 1, so `5 <= bars <= 60` really
    admits gaps of 6..61 bars. This is inherited from TradingView's own
    built-in Divergence Indicator and is the single easiest thing to get
    wrong when porting it.
    """
    cond = np.zeros(80, dtype=bool)
    cond[10] = True
    cond[10 + 6] = True   # the tightest gap the filter accepts
    bars = V.barssince(V.shift_bool(cond)).to_numpy()
    assert bars[16] == 5.0, "a 6-bar gap reads as barssince == 5 (the lower bound)"
    cond2 = np.zeros(200, dtype=bool)
    cond2[10] = True
    cond2[10 + 61] = True  # the widest gap the filter accepts
    bars2 = V.barssince(V.shift_bool(cond2)).to_numpy()
    assert bars2[71] == 60.0, "a 61-bar gap reads as barssince == 60 (the upper bound)"
    cond3 = np.zeros(80, dtype=bool)
    cond3[10] = True
    cond3[15] = True       # a 5-bar gap -> barssince 4 -> rejected
    bars3 = V.barssince(V.shift_bool(cond3)).to_numpy()
    assert bars3[15] == 4.0
    assert np.isnan(V.barssince(V.shift_bool(np.zeros(10, dtype=bool))).to_numpy()).all(), (
        "never true -> na, and na <= 60 is false, so the FIRST pivot cannot fire")
    print("in-range window: rangeLower..rangeUpper 5..60 means a 6..61 bar pivot gap")


def test_valuewhen_needs_two_occurrences() -> None:
    cond = np.array([False, True, False, False, True, False, True])
    src = pd.Series([0.0, 1, 2, 3, 4, 5, 6])
    vw = V.valuewhen(cond, src, 1)
    assert np.isnan(vw.iloc[1]), "one occurrence so far: no previous one exists"
    assert vw.iloc[4] == 1.0, "at the 2nd occurrence, occurrence=1 is the 1st"
    assert vw.iloc[6] == 4.0, "at the 3rd, occurrence=1 is the 2nd"
    print("valuewhen(cond, src, 1): NaN until two occurrences, then the previous one")


# =============================================================================
# (a) bullish divergence
# =============================================================================

def test_a_bullish_divergence_fires_five_bars_after_the_pivot() -> None:
    f = bull_div_frame()
    ev = V.evaluate(f)
    bulls = true_bars(ev["bull_div"])
    bears = true_bars(ev["bear_div"])
    assert bulls == [129], "expected exactly one bullish divergence, on bar 129, got %r" % bulls
    assert bears == [], "the bull construction must not also print a bear, got %r" % bears

    piv = 129 - V.DEFAULT_CONFIG.piv_right
    assert piv == 124
    assert bool(ev["pl_found"].iloc[129]), "bar 129 is the confirmation of the bar-124 pivot"
    row = ev.iloc[129]
    assert row["low_at_pivot"] < row["prev_low_at_pivot"], "price made a LOWER low"
    assert row["rsi_at_pivot"] > row["prev_rsi_at_low_pivot"], "RSI made a HIGHER low"
    gap = row["bars_since_prev_low_pivot"]
    assert 5 <= gap <= 60, "the in-range filter as Pine writes it"

    n_piv = int(ev["pl_found"].sum())
    print("bull: %d RSI pivot lows in the frame, exactly ONE divergence, on bar 129"
          % n_piv)
    print("      pivot bar 124   price low %.4f -> %.4f (lower)   RSI %.2f -> %.2f (higher)"
          % (row["prev_low_at_pivot"], row["low_at_pivot"],
             row["prev_rsi_at_low_pivot"], row["rsi_at_pivot"]))
    print("      barssince(plFound[1]) = %.0f  (a %.0f-bar gap between pivots)"
          % (gap, gap + 1))

    # and the screen sees it when it is the last bar
    v = V.screen_symbol(f.iloc[:130], symbol="BULLDIV")
    assert v["passes"] and v["rule_a"] and v["rule_a_direction"] == "bull"
    assert v["rule_a_bars_ago"] == 0
    assert v["rule_a_label_bars_ago"] == 5, (
        "the boolean fires today; the Bull LABEL is drawn 5 bars back (offset=-lbR)")


# =============================================================================
# (b) bearish divergence
# =============================================================================

def test_b_bearish_divergence_fires_five_bars_after_the_pivot() -> None:
    f = bear_div_frame()
    ev = V.evaluate(f)
    bears = true_bars(ev["bear_div"])
    bulls = true_bars(ev["bull_div"])
    assert bears == [129], "expected exactly one bearish divergence, on bar 129, got %r" % bears
    assert bulls == [], "the bear construction must not also print a bull, got %r" % bulls
    row = ev.iloc[129]
    assert bool(ev["ph_found"].iloc[129])
    assert row["high_at_pivot"] > row["prev_high_at_pivot"], "price made a HIGHER high"
    assert row["rsi_at_pivot"] < row["prev_rsi_at_high_pivot"], "RSI made a LOWER high"
    print("bear: exactly ONE divergence, on bar 129 (pivot bar 124)")
    print("      price high %.4f -> %.4f (higher)   RSI %.2f -> %.2f (lower)"
          % (row["prev_high_at_pivot"], row["high_at_pivot"],
             row["prev_rsi_at_high_pivot"], row["rsi_at_pivot"]))
    v = V.screen_symbol(f.iloc[:130], symbol="BEARDIV")
    assert v["passes"] and v["rule_a"] and v["rule_a_direction"] == "bear"
    assert v["rule_a_bars_ago"] == 0


# =============================================================================
# (c) and (d) the scored cross
# =============================================================================

def test_c_cross_with_macd_up_and_price_above_the_200_scores_three() -> None:
    f = score3_frame()
    ev = V.evaluate(f)
    xs = true_bars(ev["bull_cross"])
    assert xs == [292], "expected one bull cross, on bar 292, got %r" % xs
    row = ev.iloc[292]
    assert row["macd_hist"] > 0, "MACD histogram agrees"
    assert row["close"] > row["slow"], "price is on the right side of the 200 EMA"
    assert int(row["bull_score"]) == 3, "1 for the cross + 1 MACD + 1 Slow = 3"
    assert int(row["bull_score"]) == V.DEFAULT_CONFIG.max_score, (
        "3 is the MAXIMUM with the shipped defaults -- useRsi is OFF")
    print("score 3: bar 292  hist %+0.4f  close %.2f  ema200 %.2f  -> label 'Bullish +3'"
          % (row["macd_hist"], row["close"], row["slow"]))
    v = V.screen_symbol(f.iloc[:293], symbol="SCORE3")
    assert v["passes"] and v["rule_b"] and v["rule_b_score"] == 3
    assert v["rule_b_label"] == "Bullish +3"
    assert v["rule_b_bars_ago"] == 0


def test_d_cross_with_macd_down_and_price_below_the_200_scores_one() -> None:
    f = score1_frame()
    ev = V.evaluate(f)
    xs = true_bars(ev["bull_cross"])
    assert xs == [293], "expected one bull cross, on the final bar 293, got %r" % xs
    row = ev.iloc[293]
    assert row["macd_hist"] < 0, "MACD histogram disagrees"
    assert row["close"] < row["slow"], "price is on the wrong side of the 200 EMA"
    assert int(row["bull_score"]) == 1, "the cross alone"
    print("score 1: bar 293  hist %+0.4f  close %.2f  ema200 %.2f  -> label 'Bullish +1'"
          % (row["macd_hist"], row["close"], row["slow"]))
    v = V.screen_symbol(f, symbol="SCORE1")
    assert v["rule_b"] is False, "min_signal_score = 2 rejects a bare cross"
    assert v["passes"] is False, "and with no divergence either, the symbol is dropped"
    loose = V.screen_symbol(f, V.DEFAULT_CONFIG.replace(min_signal_score=1), symbol="SCORE1")
    assert loose["rule_b"] and loose["rule_b_score"] == 1, (
        "it is only the THRESHOLD that rejected it, not the detection")
    print("        rejected by min_signal_score=2, detected again at min_signal_score=1")


def test_the_score_is_arithmetic_not_a_lookup() -> None:
    """Every switch combination, on the score-3 frame's cross bar."""
    f = score3_frame()
    base = V.DEFAULT_CONFIG
    combos = {
        (True, True, False): 3,    # shipped default
        (True, False, False): 2,
        (False, True, False): 2,
        (False, False, False): 1,
        (True, True, True): 4,     # only reachable with useRsi switched on
    }
    for (um, us, ur), want in combos.items():
        cfg = base.replace(use_macd=um, use_slow=us, use_rsi=ur)
        ev = V.evaluate(f, cfg)
        got = int(ev["bull_score"].iloc[292])
        assert got == want, "useMacd=%s useSlow=%s useRsi=%s -> %d, wanted %d" % (
            um, us, ur, got, want)
        assert cfg.max_score >= got
    print("score arithmetic verified across all five switch combinations (1,2,2,3,4)")


# =============================================================================
# (e) flat / halted
# =============================================================================

def test_e_a_flat_series_produces_nothing_and_does_not_crash() -> None:
    f = flat_frame()
    ev = V.evaluate(f)
    assert int(ev["pl_found"].sum()) == 0 and int(ev["ph_found"].sum()) == 0, "no pivots"
    assert not ev["bull_div"].any() and not ev["bear_div"].any(), "no divergence"
    assert not ev["bull_cross"].any() and not ev["bear_cross"].any(), (
        "fast == mid on every bar, and a cross is strict")
    assert (ev["atr"].dropna() == 0).all(), "a halted bar has zero true range"
    assert math.isnan(ev["rsi"].iloc[-1]), (
        "a series that never moved has an UNDEFINED RSI, not a maximal one")
    assert V.screen_symbol(f, symbol="FLAT")["rsi_zone"] == "", (
        "and therefore no zone label -- publishing 'extreme-overbought' for a "
        "stock that has not traded is the false positive this fix removes")
    v = V.screen_symbol(f, symbol="FLAT")
    assert v["ok"] and not v["passes"] and v["rules"] == ""
    print("flat 300-bar frame: 0 pivots, 0 divergences, 0 crosses, ATR 0, no exception")


def test_gaps_and_nans_do_not_raise() -> None:
    f = gappy_frame()
    v = V.screen_symbol(f, symbol="GAPPY")
    assert v["ok"], v["reason"]
    ev = V.evaluate(f)
    assert len(ev) == len(V.prepare_frame(f)), "NaN bars are dropped, not filled"
    assert len(ev) < len(f), "and something really was dropped"
    empty = V.screen_symbol(pd.DataFrame(), symbol="EMPTY")
    assert not empty["ok"] and "missing column" in empty["reason"]
    junk = V.screen_symbol(pd.DataFrame({"close": ["a", "b", "c"]}), symbol="JUNK")
    assert not junk["ok"], "unparseable prices are a reason, never a traceback"
    print("gaps / NaN rows / empty frame / junk frame: all handled, none raised")


# =============================================================================
# (f) the causality proof
# =============================================================================

def test_f_no_look_ahead_anywhere() -> None:
    """Truncate the frame at bar i; every value on bar i must be unchanged.

    Run over the two frames that actually carry signals, across every bar in
    the interesting stretch -- not a sample.
    """
    checked = 0
    f = bull_div_frame()
    checked += V.assert_no_lookahead(f, bars=range(60, len(f)))
    g = bear_div_frame()
    checked += V.assert_no_lookahead(g, bars=range(60, len(g)))
    h = score3_frame()
    checked += V.assert_no_lookahead(h, bars=range(250, len(h)))
    print("no look-ahead: %d cut points x %d columns, all identical"
          % (checked, len(V.CAUSAL_COLUMNS)))

    # the same property at the level the owner actually reads: the verdict
    ev = V.evaluate(f)
    mismatches = 0
    for i in range(100, len(f)):
        v = V.screen_symbol(f.iloc[: i + 1])
        live = bool(ev["bull_div"].iloc[i] or ev["bear_div"].iloc[i])
        if bool(v["rule_a"]) != live:
            mismatches += 1
    assert mismatches == 0, "the screen's RULE A verdict must not move when bars arrive"
    print("                screen verdict re-run on %d truncations: 0 mismatches"
          % (len(f) - 100))


# =============================================================================
# (g) short history
# =============================================================================

def test_g_a_frame_shorter_than_the_slow_ma_is_sensible_not_fatal() -> None:
    f = short_frame(120)
    v = V.screen_symbol(f, symbol="YOUNG")
    assert v["ok"], v["reason"]
    assert v["n_bars"] == 120
    assert v["slow_ready"] is False, "no 200 EMA on 120 bars"
    assert v["trend"] == "unknown", "and therefore no regime claim"
    assert v["above_slow"] is None, "not False -- unknown is not a direction"
    assert "only 120 bars" in v["history_warning"]
    ev = V.evaluate(f)
    assert ev["slow"].isna().all()
    if ev["bull_cross"].any():
        i = true_bars(ev["bull_cross"])[-1]
        assert int(ev["bull_score"].iloc[i]) <= 2, (
            "close > na is false in Pine, so the Slow point is simply not awarded")
    tiny = V.screen_symbol(f.iloc[:30], symbol="TINY")
    assert not tiny["ok"] and "too short" in tiny["reason"]
    print("120-bar frame: screened, slow_ready=False, trend='unknown', max score 2")
    print("30-bar frame: refused with a reason, not an exception")


# =============================================================================
# mode 1 vs mode 2
# =============================================================================

def test_mode_1_is_divergence_only() -> None:
    f = score3_frame().iloc[:293]
    m2 = V.screen_symbol(f, V.DEFAULT_CONFIG.replace(mode=2), symbol="SCORE3")
    m1 = V.screen_symbol(f, V.DEFAULT_CONFIG.replace(mode=1), symbol="SCORE3")
    assert m2["passes"] and m2["rules"] == "B"
    assert not m1["passes"] and m1["rules"] == "", "mode 1 ignores RULE B entirely"
    assert m1["rule_b"] is True, "but still REPORTS it, so a reviewer can see why"
    print("mode 1 drops a score-3 cross; mode 2 keeps it. Both report both rules.")


def test_freshness_windows_are_in_bars() -> None:
    f = bull_div_frame()          # divergence on bar 129, frame is 141 bars
    late = f.iloc[:135]           # the divergence is now 5 bars old
    assert not V.screen_symbol(late)["passes"], "div_fresh_bars=1 means today only"
    wide = V.DEFAULT_CONFIG.replace(div_fresh_bars=6)
    v = V.screen_symbol(late, wide)
    assert v["passes"] and v["rule_a_bars_ago"] == 5
    assert not V.screen_symbol(late, V.DEFAULT_CONFIG.replace(div_fresh_bars=5))["passes"], (
        "5 bars ago is outside a 5-bar window: bars_ago 0..4")
    print("freshness: div_fresh_bars=N admits bars_ago 0..N-1, inclusive of today")


# =============================================================================
# the demo basket
# =============================================================================

def demo_basket() -> pd.DataFrame:
    frames: Dict[str, pd.DataFrame] = {
        "BULLDIV.AX": bull_div_frame().iloc[:130],    # bull divergence today
        "BEARDIV.AX": bear_div_frame().iloc[:130],    # bear divergence today
        "SCORE3.NDQ": score3_frame().iloc[:293],      # Bullish +3 today
        "SCORE1.NDQ": score1_frame(),                 # Bullish +1 today (rejected)
        "STALE.AX": bull_div_frame(),                 # same divergence, 12 bars old
        "FLAT.AX": flat_frame(),                      # halted
        "YOUNG-USD": short_frame(120),                # young listing
        "TINY-USD": short_frame(30),                  # unscreenable
    }
    cfg = V.DEFAULT_CONFIG

    def show(frame: pd.DataFrame, cols: List[str]) -> None:
        view = frame.reindex(columns=cols).copy()
        for c, fmt in (("close", "%.2f"), ("rsi", "%.1f"), ("atr_pct", "%.2f"),
                       ("macd_hist", "%+.4f")):
            if c in view.columns:
                view[c] = view[c].map(lambda x, f=fmt: "" if pd.isna(x) else f % x)
        for c in ("score", "best_bars_ago", "rule_a_label_bars_ago", "n_bars"):
            if c in view.columns:
                view[c] = view[c].map(lambda x: "" if pd.isna(x) else "%d" % int(x))
        print(view.astype("object").fillna("").to_string(index=False))

    full = V.screen_frames(frames, cfg, market="demo", include_failures=True)
    banner("SCREEN OUTPUT -- mode 2 (RULE A or RULE B), every symbol shown")
    show(full, ["symbol", "passes", "rules", "direction", "score", "best_bars_ago",
                "rule_a_direction", "rule_b_label", "close", "rsi", "trend",
                "n_bars", "reason"])
    passing = V.screen_frames(frames, cfg, market="demo")
    banner("SCREEN OUTPUT -- mode 2, only the rows a reviewer opens (ranked)")
    show(passing, ["symbol", "rules", "direction", "score", "best_bars_ago",
                   "rule_a_label_bars_ago", "close", "rsi", "rsi_zone", "trend",
                   "regime", "atr_pct", "macd_hist"])
    mode1 = V.screen_frames(frames, cfg.replace(mode=1), market="demo")
    banner("SCREEN OUTPUT -- mode 1 (RULE A only)")
    show(mode1, ["symbol", "rules", "direction", "best_bars_ago",
                 "rule_a_label_bars_ago", "close", "rsi", "rsi_zone", "trend"])
    assert list(passing["symbol"]) == ["BEARDIV.AX", "BULLDIV.AX", "SCORE3.NDQ"], \
        list(passing["symbol"])
    assert list(mode1["symbol"]) == ["BEARDIV.AX", "BULLDIV.AX"], list(mode1["symbol"])
    banner("ONE FULL ROW -- every field screen_symbol() publishes for BULLDIV.AX")
    row = V.screen_symbol(frames["BULLDIV.AX"], cfg, symbol="BULLDIV.AX", market="asx")
    for k in sorted(row):
        print("  %-26s %r" % (k, row[k]))
    return full


def show_config() -> None:
    banner("ScreenConfig -- every field and its default")
    cfg = V.ScreenConfig()
    for k, v in cfg.to_dict().items():
        print("  %-22s %r" % (k, v))
    print("  %-22s %r  (derived: 1 + useMacd + useSlow + useRsi)" % ("max_score", cfg.max_score))


# =============================================================================
# runner
# =============================================================================


# =============================================================================
# (h) ADVERSARIAL -- added by the verification pass, 2026-09-22
#
# Every test below is a frame someone tried to break the module with. They are
# kept because each one either found a defect or proved an invariant that the
# original 18 only assumed.
# =============================================================================

def _walk(seed: int, n: int = 600, decimals: int | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    if decimals is not None:
        c = np.round(c, decimals)
    c = np.maximum(c, 1.0)
    h = c + np.abs(rng.normal(0, 0.1, n))
    l = c - np.abs(rng.normal(0, 0.1, n))
    return pd.DataFrame({"open": c, "high": h, "low": l, "close": c,
                         "volume": np.full(n, 1e5)},
                        index=pd.bdate_range("2022-01-03", periods=n))


def test_h_equal_consecutive_lows_make_no_pivot_under_the_strict_rule() -> None:
    """A flat trough is the tie case the pivot convention turns on."""
    v = pd.Series([10, 9, 8, 7, 6, 5, 5, 6, 7, 8, 9, 10, 11], dtype=float)
    assert V.pivot_low_confirmed(v, 2, 2).notna().sum() == 0, (
        "strict on both sides: a shared minimum is not a unique extreme")
    loose_r = V.pivot_low_confirmed(v, 2, 2, strict_right=False)
    assert true_bars(loose_r.notna()) == [7], "the FIRST of the two lows, confirmed at 5+2"
    loose_l = V.pivot_low_confirmed(v, 2, 2, strict_left=False)
    assert true_bars(loose_l.notna()) == [8], "the SECOND of the two lows"
    both = V.pivot_low_confirmed(v, 2, 2, strict_left=False, strict_right=False)
    assert true_bars(both.notna()) == [7, 8], "non-strict admits both"
    print("equal consecutive lows: strict=0 pivots, loose-right=1, loose-left=1, loose-both=2")


def test_h_a_single_bar_spike_does_not_leak_or_crash() -> None:
    n = 300
    c = np.full(n, 50.0)
    c[150] = 500.0
    f = pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                      "volume": np.full(n, 1.0)},
                     index=pd.bdate_range("2023-01-02", periods=n))
    v = V.screen_symbol(f, symbol="SPIKE")
    assert v["ok"], v["reason"]
    ev = V.evaluate(f)
    assert not ev["bull_div"].any() and not ev["bear_div"].any(), (
        "one bar cannot be both sides of a pivot window")
    assert V.assert_no_lookahead(f, bars=range(200, n)) > 0
    print("single-bar 10x spike: screened, no divergence, no look-ahead")


def test_h_a_descending_frame_is_REFUSED_not_screened() -> None:
    """The one bad input that produces a complete and entirely wrong row."""
    f = _walk(5, 300)
    rev = f.iloc[::-1]
    v = V.screen_symbol(rev, symbol="REV")
    assert not v["ok"], "a newest-first frame must not come back ok"
    assert "DESCENDING" in v["reason"], v["reason"]
    fwd = V.screen_symbol(f, symbol="FWD")
    assert fwd["ok"] and fwd["last_bar"] == str(f.index[-1])
    # the failure it prevents, stated as a number
    import vivek50_screen as _V
    raw = _V.rsi_wilder(rev["close"], 14).iloc[-1]
    assert abs(raw - fwd["rsi"]) > 1.0, (
        "backwards bars really do produce a different, plausible RSI")
    print("descending frame: refused with a reason (backwards RSI would have "
          "read %.1f against the true %.1f)" % (raw, fwd["rsi"]))


def test_h_a_duplicated_or_gapped_index_is_positional_and_harmless() -> None:
    f = _walk(6, 300)
    dup = f.copy()
    dup.index = pd.DatetimeIndex([f.index[0]] * len(f))     # every bar same stamp
    assert V.screen_symbol(dup, symbol="DUP")["ok"], "an all-equal index is not descending"
    ix = list(f.index)
    ix[100] = ix[99]                                        # one repeated stamp
    part = f.copy()
    part.index = pd.DatetimeIndex(ix)
    a = V.evaluate(part)["bull_div"].to_numpy()
    b = V.evaluate(f)["bull_div"].to_numpy()
    assert (a == b).all(), "the index is a label; every computation is positional"
    holed = f.drop(f.index[120:126])                        # a six-session hole
    assert V.screen_symbol(holed, symbol="HOLE")["ok"]
    assert V.assert_no_lookahead(holed, bars=range(250, len(holed))) > 0
    print("duplicated / repeated / gapped index: positional, identical verdicts")


def test_h_interior_nan_rows_are_dropped_and_do_not_poison_the_averages() -> None:
    f = _walk(7, 400)
    holed = f.copy()
    holed.iloc[200:205, :4] = np.nan
    v = V.screen_symbol(holed, symbol="NANROWS")
    assert v["ok"] and v["n_bars"] == len(f) - 5
    ev = V.evaluate(holed)
    assert ev["rsi"].iloc[-1] == ev["rsi"].iloc[-1], "a NaN bar must not poison the RMA"
    assert ev["slow"].notna().iloc[-1], "nor the 200 EMA"
    one = f.copy()
    one.iloc[300, 1] = np.nan                                # high only
    assert V.screen_symbol(one, symbol="NANHIGH")["n_bars"] == len(f) - 1, (
        "a NaN in ANY of open/high/low/close drops the whole bar")
    print("interior NaN rows: dropped, recursive averages stay finite")


def test_h_a_descending_then_flat_rsi_is_zero_not_undefined() -> None:
    """rma(up) == 0 with rma(down) > 0 -- the mirror of the ramp case, and the
    one that must NOT become NaN when the 0/0 case does."""
    c = np.concatenate([np.linspace(200.0, 50.0, 200), np.full(100, 50.0)])
    f = pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                      "volume": np.full(len(c), 1.0)},
                     index=pd.bdate_range("2023-01-02", periods=len(c)))
    v = V.screen_symbol(f, symbol="DESCFLAT")
    assert v["ok"] and abs(v["rsi"] - 0.0) < 1e-9, "only-losses-then-halted is a genuine 0"
    assert v["rsi_zone"] == "extreme-oversold"
    assert not v["passes"], "and it still fires nothing: a flat tail has no pivots"
    assert V.assert_no_lookahead(f, bars=range(250, len(c))) > 0
    print("descending-then-flat: RSI 0 (not NaN), extreme-oversold, no signal")


def test_h_mode_1_does_not_let_rule_b_colour_the_direction() -> None:
    f = score3_frame()
    ev = V.evaluate(f)
    i = int(np.flatnonzero(ev["bull_signal"].to_numpy())[-1])
    g = f.iloc[: i + 1]
    one = V.screen_symbol(g, V.DEFAULT_CONFIG.replace(mode=1), symbol="S3")
    two = V.screen_symbol(g, V.DEFAULT_CONFIG.replace(mode=2), symbol="S3")
    assert two["passes"] and two["direction"] == "bull"
    assert not one["passes"] and one["rules"] == "" and one["best_bars_ago"] is None
    assert one["direction"] == "", (
        "in mode 1 RULE B is reported and NOT used -- it must not be the only "
        "thing giving a non-passing row a direction")
    assert one["rule_b"] and one["rule_b_direction"] == "bull", "still REPORTED"
    print("mode 1: RULE B reported, and no longer able to set `direction`")


def test_h_a_mistyped_source_is_refused_instead_of_silently_meaning_close() -> None:
    try:
        V.DEFAULT_CONFIG.replace(rsi_source="hlc3")
        raise AssertionError("a source this module cannot compute must not validate")
    except ValueError as exc:
        assert "rsi_source" in str(exc)
    bad = V.ScreenConfig(ma_source="adj_close")
    row = V.screen_symbol(score3_frame(), bad, symbol="BAD")
    assert not row["ok"] and "invalid config" in row["reason"], row["reason"]
    assert V.ScreenConfig(rsi_source="high").validate().rsi_source == "high", (
        "a real OHLC column is still allowed")
    print("mistyped source: refused by validate(), reported as a row reason")


def test_h_the_lookahead_proof_catches_a_planted_lookahead() -> None:
    """A proof nobody has tried to break is a decoration. Plant the exact bug
    the proof exists to catch and require it to go red."""
    f = bull_div_frame()
    original = V._pivot
    try:
        V._pivot = lambda s, l, r, low, sl, sr: original(s, l, r, low, sl, sr).shift(-r)
        try:
            V.assert_no_lookahead(f, bars=range(60, len(f)))
            raise AssertionError("the pivot-on-the-pivot-bar bug was NOT caught")
        except AssertionError as exc:
            assert "LOOK-AHEAD" in str(exc), str(exc)
    finally:
        V._pivot = original
    orig_sma = V.sma_pine
    try:
        V.sma_pine = lambda s, p: orig_sma(s, p).shift(-2)
        try:
            V.assert_no_lookahead(f, bars=range(60, len(f)))
            raise AssertionError("a centred moving average was NOT caught")
        except AssertionError as exc:
            assert "LOOK-AHEAD" in str(exc), str(exc)
    finally:
        V.sma_pine = orig_sma
    assert V.assert_no_lookahead(f, bars=range(60, len(f))) > 0, "and clean again after"
    print("look-ahead proof: both planted bugs caught, module clean afterwards")


def test_h_matches_a_naive_bar_by_bar_pine_reading() -> None:
    """The vectorised code is compared against a separately written, literal
    loop over the Pine source. 24 frames x 4 tie conventions, with flat
    stretches injected so the halted/illiquid population is exercised."""
    try:
        import pinesim as P
    except ImportError:
        print("differential test skipped: pinesim.py not present")
        return
    rng = np.random.default_rng(99)
    compared = 0
    divs = 0
    for trial in range(24):
        n = 500
        c = np.round(50 + np.cumsum(rng.normal(0, 0.25, n)), 2)
        for _ in range(int(rng.integers(1, 5))):
            st = int(rng.integers(20, n - 30))
            c[st:st + int(rng.integers(3, 25))] = c[st]
        c = np.maximum(c, 0.5)
        h = np.round(c + np.abs(rng.normal(0, 0.1, n)), 2)
        l = np.round(c - np.abs(rng.normal(0, 0.1, n)), 2)
        f = pd.DataFrame({"open": c, "high": h, "low": l, "close": c,
                          "volume": np.full(n, 1e5)})
        for sl, sr in ((True, True), (False, False), (True, False), (False, True)):
            cfg = V.DEFAULT_CONFIG.replace(pivot_strict_left=sl, pivot_strict_right=sr)
            ev = V.evaluate(f, cfg)
            ref = P.divergence(list(h), list(l), list(c), strict_left=sl, strict_right=sr)
            for col, key in (("pl_found", "plFound"), ("ph_found", "phFound"),
                             ("bull_div", "bull"), ("bear_div", "bear")):
                assert list(ev[col].astype(bool)) == [bool(x) for x in ref[key]], (
                    "trial %d strict=%s: %s disagrees with the naive Pine reading"
                    % (trial, (sl, sr), col))
            compared += 1
        divs += int(ev["bull_div"].sum()) + int(ev["bear_div"].sum())
    print("differential vs a naive bar-by-bar Pine reading: %d frame/convention "
          "pairs identical" % compared)


TESTS = [
    test_warmup_lengths_match_pine,
    test_rma_is_wilder_not_an_ema,
    test_rsi_degenerate_cases,
    test_crossover_is_nan_safe_and_uses_the_previous_bar,
    test_pivot_is_confirmed_right_bars_late,
    test_the_barssince_off_by_one_sets_a_6_to_61_bar_window,
    test_valuewhen_needs_two_occurrences,
    test_a_bullish_divergence_fires_five_bars_after_the_pivot,
    test_b_bearish_divergence_fires_five_bars_after_the_pivot,
    test_c_cross_with_macd_up_and_price_above_the_200_scores_three,
    test_d_cross_with_macd_down_and_price_below_the_200_scores_one,
    test_the_score_is_arithmetic_not_a_lookup,
    test_e_a_flat_series_produces_nothing_and_does_not_crash,
    test_gaps_and_nans_do_not_raise,
    test_f_no_look_ahead_anywhere,
    test_g_a_frame_shorter_than_the_slow_ma_is_sensible_not_fatal,
    test_mode_1_is_divergence_only,
    test_freshness_windows_are_in_bars,
    test_h_equal_consecutive_lows_make_no_pivot_under_the_strict_rule,
    test_h_a_single_bar_spike_does_not_leak_or_crash,
    test_h_a_descending_frame_is_REFUSED_not_screened,
    test_h_a_duplicated_or_gapped_index_is_positional_and_harmless,
    test_h_interior_nan_rows_are_dropped_and_do_not_poison_the_averages,
    test_h_a_descending_then_flat_rsi_is_zero_not_undefined,
    test_h_mode_1_does_not_let_rule_b_colour_the_direction,
    test_h_a_mistyped_source_is_refused_instead_of_silently_meaning_close,
    test_h_the_lookahead_proof_catches_a_planted_lookahead,
    test_h_matches_a_naive_bar_by_bar_pine_reading,
]


def main() -> int:
    banner("vivek50_screen self-test -- pandas %s, numpy %s" % (pd.__version__, np.__version__))
    failures = 0
    for fn in TESTS:
        name = fn.__name__
        try:
            fn()
            print("  PASS  %s" % name)
        except AssertionError as exc:
            failures += 1
            print("  FAIL  %s\n        %s" % (name, exc))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print("  ERROR %s\n        %r" % (name, exc))
    demo_basket()
    show_config()
    banner("%d/%d tests passed" % (len(TESTS) - failures, len(TESTS)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
