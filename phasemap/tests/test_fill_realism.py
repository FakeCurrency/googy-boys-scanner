"""Backtest fill realism (2026-07-20, review H4 / ruleset 1.3.1).

entry_mid is a retrace limit: it must only be credited when price actually
trades back through the mid after the signal bar. A gapper that runs without
retracing fills at the signal close — the price a taker could really get.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from phasemap.backtest.harness import _finalize


def _sig(i, direction="bullish", entry_mid=95.0):
    return {"signal_index": i, "direction": direction, "entry_mid": entry_mid,
            "t1_consumed_bar": None, "dead_bar": None, "stalled_bar": None}


def _ind(close, low, high):
    return SimpleNamespace(close=np.array(close, dtype=float),
                           low=np.array(low, dtype=float),
                           high=np.array(high, dtype=float))


def test_gapper_that_never_retraces_fills_at_signal_close():
    # signal at i=0, close 100, entry_mid 95; price runs straight up — the 95
    # limit NEVER fills. Old maths credited fwd from 95 (phantom +26% at h=5);
    # honest fill is the close (100).
    closes = [100, 104, 108, 112, 116, 120, 124]
    lows   = [ 98, 103, 107, 111, 115, 119, 123]
    highs  = [101, 105, 109, 113, 117, 121, 125]
    sig = _sig(0, entry_mid=95.0)
    _finalize(sig, _ind(closes, lows, highs))
    assert sig["fill"] == "close" and sig["fill_price"] == pytest.approx(100.0)
    assert sig["fwd_5"] == pytest.approx(120 / 100 - 1, abs=1e-4)   # from close


def test_retrace_into_the_band_fills_at_entry_mid():
    # price dips through 95 on bar 2 → the mid limit really fills.
    closes = [100,  99,  94, 100, 106, 112, 118]
    lows   = [ 98,  96,  93,  98, 104, 110, 116]
    highs  = [101, 100,  99, 101, 107, 113, 119]
    sig = _sig(0, entry_mid=95.0)
    _finalize(sig, _ind(closes, lows, highs))
    assert sig["fill"] == "entry_mid" and sig["fill_price"] == pytest.approx(95.0)
    assert sig["fwd_5"] == pytest.approx(112 / 95 - 1, abs=1e-4)    # from the mid


def test_bearish_mirror():
    # bearish signal, entry_mid above; price collapses without pulling up → close fill.
    closes = [100,  95,  90,  85,  80,  75,  70]
    lows   = [ 97,  93,  88,  83,  78,  73,  68]
    highs  = [101,  99,  94,  89,  84,  79,  74]
    sig = _sig(0, direction="bearish", entry_mid=104.0)
    _finalize(sig, _ind(closes, lows, highs))
    assert sig["fill"] == "close"
    assert sig["fwd_5"] == pytest.approx(-(75 / 100 - 1), abs=1e-4)

    # …and a pull-up through the mid credits the mid.
    highs2 = [101, 105,  94,  89,  84,  79,  74]
    sig = _sig(0, direction="bearish", entry_mid=104.0)
    _finalize(sig, _ind(closes, lows, highs2))
    assert sig["fill"] == "entry_mid"
    assert sig["fwd_5"] == pytest.approx(-(75 / 104 - 1), abs=1e-4)


def test_mae_measured_from_the_actual_fill():
    closes = [100, 104, 108, 112, 116, 120, 124]
    lows   = [ 98,  99, 107, 111, 115, 119, 123]
    highs  = [101, 105, 109, 113, 117, 121, 125]
    sig = _sig(0, entry_mid=95.0)                  # never fills → close fill @100
    _finalize(sig, _ind(closes, lows, highs))
    assert sig["mae"] == pytest.approx(99 / 100 - 1, abs=1e-4)      # from 100, not 95
