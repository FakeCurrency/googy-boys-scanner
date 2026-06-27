"""VIVEK-native paper-trade journal: trigger-price entries, manage_position-based
resolution, stop-out + MAE/MFE + realized R, and expectancy breakdowns."""

import numpy as np
import pandas as pd
import pytest

from scanner import vivek_journal as vj

pytestmark = pytest.mark.risk


def _trade(**kw):
    t = {"id": "X:long:1D:2024-01-01", "symbol": "X", "name": "X", "sector": "",
         "market": "asx", "direction": "long", "grade": "A+", "entry_type": "reclaim",
         "timeframe": "1D", "entry": 100.0, "stop": 96.0,
         "tp1": 106.0, "tp2": 112.0, "tp3": 120.0, "scale": [0.25, 0.50, 0.15],
         "risk": 4.0, "rr": 3.0, "entry_date": "2024-01-01", "status": "open",
         "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
         "booked_pct": 0.0, "realized_r": 0.0, "exits": [], "mae": 100.0,
         "mfe": 100.0, "_last_bar": None}
    t.update(kw)
    return t


def _bar(date, hi, lo, close=None):
    return {"date": date, "high": hi, "low": lo, "close": close if close is not None else (hi + lo) / 2}


def test_winning_long_scales_out_and_trails():
    t = _trade()
    bars = [
        _bar("2024-01-02", 107, 101),   # TP1 → book 25%, SL→BE(100)
        _bar("2024-01-03", 113, 101),   # TP2 → book 50%, SL→TP1(106)
        _bar("2024-01-04", 121, 107),   # TP3 → book 15%
        _bar("2024-01-05", 110, 105),   # low 105 ≤ trailed SL 106 → runner out at 106
    ]
    vj._resolve(t, bars)
    assert t["status"] == "closed"
    assert t["tp1_hit"] and t["tp2_hit"] and t["tp3_hit"]
    assert t["exit_reason"] == "target"
    assert t["booked_pct"] == pytest.approx(1.0)
    # 0.25*1.5 + 0.5*3.0 + 0.15*5.0 + 0.10*1.5 (runner at the trailed 106 = +1.5R)
    assert t["realized_r"] == pytest.approx(2.775, abs=1e-3)
    assert t["mfe_r"] == pytest.approx((121 - 100) / 4, abs=1e-3)
    assert t["hold_days"] == 4


def test_losing_long_stops_out_at_minus_one_r():
    t = _trade()
    vj._resolve(t, [_bar("2024-01-02", 101, 95)])   # low 95 ≤ 96 stop, before any TP
    assert t["status"] == "closed" and t["exit_reason"] == "stop"
    assert t["realized_r"] == pytest.approx(-1.0, abs=1e-9)
    assert t["mae_r"] == pytest.approx((95 - 100) / 4, abs=1e-3)


def test_pessimistic_bar_resolves_as_stop_when_spanning_both():
    # A bar that tags both TP1 and the stop must resolve as the stop (pessimistic).
    t = _trade()
    vj._resolve(t, [_bar("2024-01-02", 107, 95)])
    assert t["exit_reason"] == "stop" and t["realized_r"] == pytest.approx(-1.0)


def test_short_mirror_wins():
    t = _trade(direction="short", entry=100, stop=104, tp1=94, tp2=88, tp3=80,
               scale=[0.50, 0.25, 0.15], id="X:short:1D:2024-01-01")
    bars = [_bar("2024-01-02", 99, 93), _bar("2024-01-03", 95, 87),
            _bar("2024-01-04", 90, 79), _bar("2024-01-05", 96, 92)]
    vj._resolve(t, bars)
    assert t["status"] == "closed" and t["realized_r"] > 0 and t["tp3_hit"]


def test_open_trade_stays_open_without_resolving_bars():
    t = _trade()
    vj._resolve(t, [])                  # no new bars (trigger fired on the last bar)
    assert t["status"] == "open" and t["realized_r"] == 0.0


def test_resolution_is_incremental_across_runs():
    t = _trade()
    vj._resolve(t, [_bar("2024-01-02", 107, 101)])     # TP1 only
    assert t["tp1_hit"] and not t["tp2_hit"] and t["status"] == "open"
    # next run: only newer bars are processed (idempotent on the seen bar)
    vj._resolve(t, [_bar("2024-01-02", 107, 101), _bar("2024-01-03", 113, 101)])
    assert t["tp2_hit"] and t["booked_pct"] == pytest.approx(0.75)


def test_expectancy_splits_by_grade_entry_type_timeframe():
    closed = [
        _trade(grade="A+", entry_type="reclaim", timeframe="1D", realized_r=2.0, hold_days=5, mae_r=-0.3, mfe_r=3.0),
        _trade(grade="A", entry_type="break", timeframe="1W", realized_r=-1.0, hold_days=3, mae_r=-1.2, mfe_r=0.4),
    ]
    e = vj.expectancy(closed)
    assert e["overall"]["n"] == 2
    assert e["overall"]["expectancy_r"] == pytest.approx(0.5)
    assert e["by_grade"]["A+"]["n"] == 1 and e["by_grade"]["A+"]["expectancy_r"] == pytest.approx(2.0)
    assert e["by_entry_type"]["reclaim"]["n"] == 1
    assert e["by_entry_type"]["break"]["win_rate"] == 0.0
    assert e["by_timeframe"]["1D"]["n"] == 1 and e["by_timeframe"]["4H"]["n"] == 0


def _frame(dates, highs, lows, closes):
    idx = pd.to_datetime(dates)
    return pd.DataFrame({"Open": closes, "High": highs, "Low": lows,
                         "Close": closes, "Volume": 1e6}, index=idx)


def test_update_snapshots_armed_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(vj, "JOURNAL_FILE", tmp_path / "vivek_journal.json")
    monkeypatch.setattr(vj, "PUBLIC_FILE", tmp_path / "public_vivek_journal.json")
    plan = {"armed": True, "entry_trigger": "reclaim", "trigger_bar": "2024-01-01",
            "entry": 100.0, "stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
            "scale": [0.25, 0.50, 0.15], "risk": 4.0, "rr": 3.0}
    watching = {"armed": False, "trigger_bar": None, "entry": 100.0, "stop": 96.0,
                "tp1": 106.0, "tp2": 112.0, "tp3": 120.0, "scale": [0.25, 0.5, 0.15], "risk": 4.0}
    rows = [
        {"symbol": "WIN", "dir": "LONG", "grade": "A+", "entry_types": ["reclaim"],
         "plans": {"1D": plan}},
        {"symbol": "LOWGRADE", "dir": "LONG", "grade": "B+", "plans": {"1D": plan}},
        {"symbol": "WATCH", "dir": "LONG", "grade": "A", "plans": {"1D": watching}},
    ]
    uni = [{"symbol": "WIN", "yf": "WIN.AX"}, {"symbol": "LOWGRADE", "yf": "LG.AX"},
           {"symbol": "WATCH", "yf": "W.AX"}]
    # No bars after the trigger yet → the trade opens and stays open.
    frames = {"WIN.AX": _frame(["2024-01-01"], [100], [100], [100])}
    j = vj.update("asx", rows, frames, uni)
    assert len(j["open"]) == 1 and j["open"][0]["symbol"] == "WIN"   # only armed A/A+

    # Re-running the same scan must NOT duplicate the open trade.
    j = vj.update("asx", rows, frames, uni)
    assert len(j["open"]) == 1


def test_update_resolves_to_closed_when_bars_arrive(tmp_path, monkeypatch):
    monkeypatch.setattr(vj, "JOURNAL_FILE", tmp_path / "vivek_journal.json")
    monkeypatch.setattr(vj, "PUBLIC_FILE", tmp_path / "public_vivek_journal.json")
    plan = {"armed": True, "entry_trigger": "reclaim", "trigger_bar": "2024-01-01",
            "entry": 100.0, "stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
            "scale": [0.25, 0.50, 0.15], "risk": 4.0, "rr": 3.0}
    rows = [{"symbol": "WIN", "dir": "LONG", "grade": "A+", "entry_types": ["reclaim"],
             "plans": {"1D": plan}}]
    uni = [{"symbol": "WIN", "yf": "WIN.AX"}]
    vj.update("asx", rows, {"WIN.AX": _frame(["2024-01-01"], [100], [100], [100])}, uni)
    # Next scan: subsequent winning bars are now present → the trade closes.
    df = _frame(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
                [100, 107, 113, 121, 110], [100, 101, 101, 107, 105], [100, 106, 112, 120, 108])
    j = vj.update("asx", rows, {"WIN.AX": df}, uni)
    assert len(j["open"]) == 0 and len(j["closed"]) == 1
    assert j["closed"][0]["status"] == "closed" and j["closed"][0]["realized_r"] > 0
    assert j["expectancy"]["overall"]["n"] == 1
