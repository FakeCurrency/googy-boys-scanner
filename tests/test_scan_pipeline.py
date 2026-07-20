"""Scan pipeline: hysteresis vs grade_raw + traded-plan headline (H1+H2, 2026-07-20).

First integration-level coverage of scan_vivek_market's grading/headline
assembly (the review flagged it as untested). The signal engine is stubbed so
these tests pin the PIPELINE contract, not detection maths:

  * row["grade"]      = hysteresis-held then gated   (display)
  * row["grade_raw"]  = raw then gated               (what the bot may buy)
  * headline entry/stop/TP/R:R = the TRADED plan (gated TF when armed,
    1D fallback when watching), labelled by headline_tf
  * a weekly-armed setup with no usable 1D plan is still published
  * vivek_bot buys off grade_raw, never the smoothed grade
"""

import pandas as pd
import pytest

import scanner.vivek as vivek
from scanner import scan
from scanner.broker import vivek_bot

pytestmark = pytest.mark.risk


def _frame():
    idx = pd.date_range(end="2024-01-02", periods=30, freq="D")
    return pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                         "Close": 100.0, "Volume": 1_000_000.0}, index=idx)


def _plan(entry, armed, trigger="reclaim"):
    risk = entry - (entry - 4.0)
    return {"armed": armed, "entry": entry, "stop": entry - 4.0,
            "tp1": entry + 6.0, "tp2": entry + 8.0, "tp3": entry + 12.0,
            "scale": [0.25, 0.50, 0.15], "risk": 4.0,
            "rr": round((entry + 8.0 - entry) / risk, 2),   # 2.0
            "entry_trigger": trigger if armed else None,
            "trigger_bar": "2024-01-02" if armed else None}


_SIG = {"direction": "long", "close": 100.0, "level_tf": "weekly", "level": 99.0,
        "at_level": True, "reaction": "bounce", "structure": 0.8, "confluence": False}


def _stub_engine(monkeypatch, plans, raw=("A+", 8), held=None):
    monkeypatch.setattr(vivek, "evaluate", lambda df: dict(_SIG))
    monkeypatch.setattr(vivek, "score_and_grade", lambda sig: (raw[1], raw[0], ["CHIP"]))
    if held is not None:  # force a hysteresis hold different from the raw grade
        monkeypatch.setattr(vivek, "apply_grade_hysteresis",
                            lambda *a, **k: (held, 1))
    monkeypatch.setattr(vivek, "build_plans", lambda df, sig: dict(plans))
    monkeypatch.setattr(vivek, "build_markers", lambda plans: {})
    monkeypatch.setattr(vivek, "build_detail", lambda df, sig, lv: {})
    monkeypatch.setattr(vivek, "narrative", lambda *a, **k: "n/a")
    monkeypatch.setattr(vivek, "entry_types", lambda sig: ["reclaim"])


def _run():
    uni = [{"yf": "BHP.AX", "symbol": "BHP", "name": "BHP", "sector": "Materials"}]
    out = scan.scan_vivek_market("asx", universe=uni,
                                 frames={"BHP.AX": _frame()},
                                 pulse_data=[], progress=False)
    return out["results"]


def test_headline_follows_the_armed_traded_plan(monkeypatch):
    plans = {"1D": _plan(100.0, armed=False), "1W": _plan(103.0, armed=True)}
    (row,) = _run() if _stub_engine(monkeypatch, plans) is None else ()
    assert row["headline_tf"] == "1W" and row["armed_tf"] == "1W"
    assert row["entry"] == 103.0 and row["stop"] == 99.0     # weekly numbers
    assert row["entry_trigger"] == "reclaim"
    assert row["grade"] == "A+" and row["grade_raw"] == "A+"


def test_watching_setup_keeps_1d_headline_and_caps_at_b_plus(monkeypatch):
    plans = {"1D": _plan(100.0, armed=False), "1W": _plan(103.0, armed=False)}
    (row,) = _run() if _stub_engine(monkeypatch, plans) is None else ()
    assert row["headline_tf"] == "1D" and row["armed_tf"] is None
    assert row["entry"] == 100.0
    assert row["grade"] == "B+" and row["grade_raw"] == "B+"   # gate demotes both


def test_weekly_armed_setup_without_1d_plan_is_still_published(monkeypatch):
    plans = {"1W": _plan(103.0, armed=True)}                   # no 1D plan at all
    (row,) = _run() if _stub_engine(monkeypatch, plans) is None else ()
    assert row["headline_tf"] == "1W" and row["entry"] == 103.0
    # the pre-H1 code `continue`d on a missing/bad 1D plan and hid this row


def test_display_hold_does_not_leak_into_grade_raw(monkeypatch):
    # raw decayed to A, hysteresis holds the DISPLAYED grade at A+:
    plans = {"1D": _plan(100.0, armed=True)}
    _stub_engine(monkeypatch, plans, raw=("A", 7), held="A+")
    (row,) = _run()
    assert row["grade"] == "A+"          # what the user sees (smoothed)
    assert row["grade_raw"] == "A"       # what the bot is allowed to buy


def test_bot_buys_off_grade_raw_not_the_smoothed_grade():
    plans = {"1W": _plan(103.0, armed=True)}
    row = {"symbol": "BHP", "name": "BHP", "sector": "Materials", "dir": "LONG",
           "grade": "A+", "grade_raw": "A", "entry_types": ["reclaim"],
           "plans": plans, "price": 103.0}
    out = vivek_bot.evaluate_setup(row)
    assert out["take"] is False and out["code"] == "not_a_plus"

    row["grade_raw"] = "A+"
    out = vivek_bot.evaluate_setup(row)
    assert out["take"] is True and out["timeframe"] == "1W"

    legacy = dict(row)                    # pre-v4 JSON: no grade_raw field
    legacy.pop("grade_raw")
    assert vivek_bot.evaluate_setup(legacy)["take"] is True   # falls back to grade
