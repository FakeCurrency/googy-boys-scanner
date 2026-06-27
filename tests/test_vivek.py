"""VIVEK (5.0-style) engine + autonomous-bot decision logic.

Covers the 200-SMA reaction engine (grading + level construction) and the bot's
take/skip rules, sizing (0.25–0.5% risk, ≤5× leverage) and the TP1/TP2/TP3
scale-out + SL-movement management.
"""

import numpy as np
import pandas as pd
import pytest

from scanner import config, vivek
from scanner.broker import vivek_bot

pytestmark = pytest.mark.risk


def _frame(kind="long_bounce", seed=7):
    rs = np.random.RandomState(seed)
    close = 100 + np.cumsum(rs.normal(0, 0.2, 340))
    close = close - (close.mean() - 100)                       # 200 SMA region ~100
    if kind == "long_bounce":
        close[-14:-4] = np.linspace(close[-15], 99.0, 10)       # dip to the level
        close[-4:] = np.linspace(99.0, 101.5, 4)                # bounce up
    elif kind == "short_reject":
        close[-14:-4] = np.linspace(close[-15], 101.0, 10)
        close[-4:] = np.linspace(101.0, 98.3, 4)                # reject down
    return pd.DataFrame({"Open": close * 0.999, "High": close * 1.01,
                         "Low": close * 0.99, "Close": close, "Volume": 2e6},
                        index=pd.date_range("2021-01-01", periods=340, freq="D"))


# ── engine ────────────────────────────────────────────────────────────────────

def test_long_bounce_is_graded_and_levels_ordered():
    df = _frame("long_bounce")
    sig = vivek.evaluate(df)
    assert sig is not None and sig["direction"] == "long"
    pts, grade, fired = vivek.score_and_grade(sig)
    assert grade in ("A+", "A", "B+", "WATCH")
    lv = vivek.compute_levels(df, sig)
    assert lv["stop"] < lv["entry"] < lv["tp1"] < lv["tp2"] < lv["tp3"]
    assert lv["scale"] == config.VIVEK_TP_SCALE_LONG


def test_short_reject_levels_mirror():
    sig = vivek.evaluate(_frame("short_reject"))
    assert sig is not None and sig["direction"] == "short"
    lv = vivek.compute_levels(_frame("short_reject"), sig)
    assert lv["stop"] > lv["entry"] > lv["tp1"] > lv["tp2"] > lv["tp3"]
    assert lv["scale"] == config.VIVEK_TP_SCALE_SHORT


def test_far_from_sma_is_no_setup():
    rs = np.random.RandomState(1)
    close = np.linspace(50, 200, 340) + rs.normal(0, 1, 340)   # price way above its SMA200
    df = pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                       "Close": close, "Volume": 1e6},
                      index=pd.date_range("2021-01-01", periods=340, freq="D"))
    assert vivek.evaluate(df) is None


def test_grade_ladder_reaches_each_tier():
    from scanner.grading import grade_from_points
    assert grade_from_points(9, config.VIVEK_GRADE_CUTOFFS) == "A+"
    assert grade_from_points(6, config.VIVEK_GRADE_CUTOFFS) == "A"
    assert grade_from_points(4, config.VIVEK_GRADE_CUTOFFS) == "B+"
    assert grade_from_points(3, config.VIVEK_GRADE_CUTOFFS) == "WATCH"
    assert grade_from_points(1, config.VIVEK_GRADE_CUTOFFS) is None


# ── bot: take / skip ──────────────────────────────────────────────────────────

def _row(**kw):
    r = {"symbol": "BHP", "dir": "LONG", "grade": "A", "rr": 3.0,
         "entry": 100.0, "stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
         "at_level": True, "reaction": "bounce",
         "scale": config.VIVEK_TP_SCALE_LONG}
    r.update(kw)
    return r


def test_bot_takes_clean_A_setup():
    d = vivek_bot.evaluate_setup(_row())
    assert d["take"] is True and d["direction"] == "long"


def test_bot_skips_below_min_grade(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_MIN_GRADE", "A")
    d = vivek_bot.evaluate_setup(_row(grade="B+"))
    assert d["take"] is False and d["code"] == "grade_below_min"


def test_bot_skips_low_rr():
    d = vivek_bot.evaluate_setup(_row(rr=1.0))
    assert d["take"] is False and d["code"] == "low_rr"


def test_bot_skips_bad_level_order():
    d = vivek_bot.evaluate_setup(_row(tp1=95.0))   # tp1 below entry on a long
    assert d["take"] is False and d["code"] == "bad_level_order"


def test_bot_skips_when_not_a_reaction():
    d = vivek_bot.evaluate_setup(_row(at_level=False, reaction="hold"))
    assert d["take"] is False and d["code"] == "no_clean_reaction"


# ── bot: sizing ───────────────────────────────────────────────────────────────

def test_sizing_risks_configured_pct():
    s = vivek_bot.size_position(10_000, entry=100, stop=96, risk_pct=0.25)
    # 0.25% of 10k = $25 risk over a $4 stop → 6.25 units
    assert s["risk_usd"] == pytest.approx(25.0)
    assert s["units"] == pytest.approx(6.25)


def test_sizing_caps_leverage():
    # tiny stop would imply huge notional; leverage must cap at the max.
    s = vivek_bot.size_position(10_000, entry=100, stop=99.99,
                                risk_pct=0.5, max_leverage=5)
    assert s["leverage"] <= 5.0 + 1e-9
    assert s["leverage_capped"] is True


def test_sizing_respects_max_risk_pct(monkeypatch):
    s = vivek_bot.size_position(10_000, entry=100, stop=90, risk_pct=2.0)  # asks 2%
    assert s["risk_pct"] <= config.VIVEK_RISK_PCT_MAX                       # clamped to 0.5


# ── bot: live management (scale-outs + SL movement) ──────────────────────────

def _pos():
    return {"symbol": "BHP", "direction": "long", "entry": 100.0, "stop": 96.0,
            "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
            "scale": config.VIVEK_TP_SCALE_LONG}


def test_tp1_books_and_moves_sl_to_breakeven():
    pos = _pos()
    acts = vivek_bot.manage_position(pos, price=106.5)
    assert pos["tp1_hit"] is True and pos["stop"] == 100.0     # SL → break-even
    assert any(a["action"] == "scale" and a["tp"] == "TP1" for a in acts)
    assert any(a["action"] == "sl" and a["to"] == "breakeven" for a in acts)


def test_tp2_moves_sl_below_support():
    pos = _pos()
    pos["tp1_hit"] = True
    pos["stop"] = 100.0
    acts = vivek_bot.manage_position(pos, price=112.5, support=108.0)
    assert pos["tp2_hit"] is True and pos["stop"] == 108.0     # SL → new support
    assert any(a["action"] == "scale" and a["tp"] == "TP2" for a in acts)


def test_sl_never_moves_against_the_trade():
    pos = _pos()
    pos["tp1_hit"] = True
    pos["stop"] = 105.0                                        # already trailed up past entry
    vivek_bot.manage_position(pos, price=112.5, support=103.0) # support is BELOW current SL
    assert pos["stop"] == 105.0, "SL must not move down on a long"


def test_short_management_mirrors():
    pos = {"symbol": "X", "direction": "short", "entry": 100.0, "stop": 104.0,
           "tp1": 94.0, "tp2": 88.0, "tp3": 80.0, "scale": config.VIVEK_TP_SCALE_SHORT}
    vivek_bot.manage_position(pos, price=93.0)                 # TP1 hit (price fell)
    assert pos["tp1_hit"] is True and pos["stop"] == 100.0     # SL → break-even (down)


def test_decide_splits_takeable_and_skipped():
    rows = [_row(symbol="A1"), _row(symbol="A2", rr=1.0), _row(symbol="A3", grade="WATCH")]
    out = vivek_bot.decide(rows, equity=10_000)
    assert len(out["plans"]) == 1 and out["plans"][0]["plan"]["symbol"] == "A1"
    assert len(out["skipped"]) == 2
