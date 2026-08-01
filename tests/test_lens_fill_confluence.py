"""Fill-model switch + confluence classifier smoke tests."""
import pytest

from scripts.lens_fill_confluence import manage_bar_fill, pm_classify_at, FILL_MODELS
from scanner.vivek_journal import _snapshot

pytestmark = pytest.mark.risk


def _open_trade():
    row = {"symbol": "X", "name": "X", "sector": "", "dir": "LONG",
           "grade": "A+", "entry_types": ["reclaim"]}
    plan = {"stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
            "scale": [0.25, 0.5, 0.15], "entry_trigger": "reclaim", "armed": True}
    return _snapshot(row, "1D", plan, "asx", 100.0, "2024-01-02")


def test_fill_models_defined():
    assert set(FILL_MODELS) == {"pessimistic", "midpoint", "optimistic"}


def test_pessimistic_stop_beats_target_on_spanning_bar():
    tr = _open_trade()
    manage_bar_fill(tr, high=107, low=95, close=100, day="2024-01-03",
                    costs=None, is_last=False, fill_model="pessimistic")
    assert tr["status"] == "closed" and tr["exit_reason"] == "stop"


def test_optimistic_can_take_target_on_spanning_bar():
    tr = _open_trade()
    manage_bar_fill(tr, high=107, low=95, close=100, day="2024-01-03",
                    costs=None, is_last=False, fill_model="optimistic")
    # target side first → TP1 books; may later trail-close same bar on stop side
    assert tr.get("tp1_hit") is True


def test_midpoint_single_price_path_does_not_crash():
    tr = _open_trade()
    manage_bar_fill(tr, high=107, low=95, close=100, day="2024-01-03",
                    costs=None, is_last=False, fill_model="midpoint")
    assert tr["status"] in ("open", "closed")


def test_pm_classify_short_history_is_none():
    import pandas as pd
    df = pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1]},
                      index=pd.date_range("2024-01-01", periods=1, freq="B"))
    out = pm_classify_at(df, "asx", "2024-01-01", "long")
    assert out["confluence"] == "NONE"
