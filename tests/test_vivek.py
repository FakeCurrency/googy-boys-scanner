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


def test_vivek_reuses_caller_frames_no_second_download(monkeypatch):
    """When the runner passes deep frames, VIVEK must NOT download again."""
    from scanner import scan
    monkeypatch.setattr(scan, "download",
                        lambda *a, **k: pytest.fail("VIVEK downloaded despite being given frames"))
    uni = [{"yf": "BHP.AX", "symbol": "BHP", "name": "BHP Group", "sector": "Materials"}]
    frames = {"BHP.AX": _frame("long_bounce")}
    out = scan.scan_vivek_market("asx", universe=uni, frames=frames,
                                 pulse_data=[], progress=False)
    assert out["scanned"] == 1                      # used the provided frame
    assert out["setup_type"] == "vivek"


def test_vivek_payload_carries_freshness_and_schema_stamp():
    """Output must stamp schema_version, code_sha, coverage and pulse so the UI
    can show data age / coverage and detect an old-build dataset."""
    from scanner import scan
    uni = [{"yf": "BHP.AX", "symbol": "BHP", "name": "BHP Group", "sector": "Materials"},
           {"yf": "CBA.AX", "symbol": "CBA", "name": "Commonwealth Bank", "sector": "Financials"}]
    frames = {"BHP.AX": _frame("long_bounce")}        # only 1 of 2 names "downloaded"
    out = scan.scan_vivek_market("asx", universe=uni, frames=frames,
                                 pulse_data=[], progress=False)
    assert out["schema_version"] == config.VIVEK_SCHEMA_VERSION
    assert "code_sha" in out                          # may be "" off a git checkout
    assert out["downloaded"] == 1 and out["universe_size"] == 2
    assert out["coverage_pct"] == 50
    assert "pulse" in out


def test_grade_ladder_reaches_each_tier():
    from scanner.grading import grade_from_points
    assert grade_from_points(9, config.VIVEK_GRADE_CUTOFFS) == "A+"
    assert grade_from_points(6, config.VIVEK_GRADE_CUTOFFS) == "A"
    assert grade_from_points(4, config.VIVEK_GRADE_CUTOFFS) == "B+"
    assert grade_from_points(3, config.VIVEK_GRADE_CUTOFFS) == "WATCH"
    assert grade_from_points(1, config.VIVEK_GRADE_CUTOFFS) is None


# ── #1 structural take-profits (real R:R, not a constant) ───────────────────────

def _spiked_frame(highs):
    """60 daily bars flat at 100, with isolated High spikes at given (idx, value)."""
    n = 60
    o = np.full(n, 100.0); hi = np.full(n, 100.0); lo = np.full(n, 99.9); cl = np.full(n, 100.0)
    for idx, val in highs:
        hi[idx] = val
    return pd.DataFrame({"Open": o, "High": hi, "Low": lo, "Close": cl, "Volume": 1e6},
                        index=pd.date_range("2021-01-01", periods=n, freq="D"))


def test_structural_targets_land_on_prior_resistance():
    df = _spiked_frame([(20, 103.0), (40, 107.0)])     # two clean resistances above entry
    tgts = vivek._structural_targets(df, "long", entry=100.0, risk=1.0)
    assert tgts == [103.0, 107.0]                      # ordered away from entry, real pivots


def test_compute_levels_uses_structure_and_rr_varies():
    df = _spiked_frame([(20, 103.0), (40, 107.0)])
    sig = {"direction": "long", "close": 100.0, "atr": 0.1,
           "swing_low": 99.1, "swing_high": 100.0, "level": 99.2}
    lv = vivek.compute_levels(df, sig)
    assert lv["stop"] == pytest.approx(99.0)           # min(swing_low, level) − ATR buffer
    assert lv["tp1"] == pytest.approx(103.0)           # TP1/TP2 sit on the real pivots
    assert lv["tp2"] == pytest.approx(107.0)
    assert lv["tp3"] > lv["tp2"]                       # fallback placed beyond the last
    assert lv["rr"] == pytest.approx(7.0)              # (107−100)/1 — NOT the old constant 3.0
    assert lv["structural_tps"] == 2


def test_targets_fall_back_to_r_multiples_without_structure():
    df = _spiked_frame([])                              # nothing above entry
    sig = {"direction": "long", "close": 100.0, "atr": 0.1,
           "swing_low": 99.1, "swing_high": 100.0, "level": 99.2}
    lv = vivek.compute_levels(df, sig)
    assert lv["structural_tps"] == 0
    assert lv["stop"] < lv["entry"] < lv["tp1"] < lv["tp2"] < lv["tp3"]


def test_short_targets_never_go_negative():
    # A penny-stock short with a wide stop would push an R-multiple TP below zero.
    df = _spiked_frame([])                              # no structure → R-multiple fallback
    sig = {"direction": "short", "close": 0.12, "atr": 0.04,
           "swing_low": 0.10, "swing_high": 0.121, "level": 0.121}
    lv = vivek.compute_levels(df, sig)
    assert lv["tp1"] > 0 and lv["tp2"] > 0 and lv["tp3"] > 0          # no negative prices
    assert lv["stop"] > lv["entry"] > lv["tp1"] > lv["tp2"] > lv["tp3"]   # still ordered


# ── #2 selectivity gate ─────────────────────────────────────────────────────────

def test_gate_keeps_armed_high_rr_setup():
    grade, notes = vivek.gate_grade("A+", {}, rr=3.0, armed=True)
    assert grade == "A+" and notes == []


def test_gate_demotes_when_not_armed():
    grade, notes = vivek.gate_grade("A", {}, rr=3.0, armed=False)
    assert grade == "B+" and any("WATCHING" in n for n in notes)


def test_gate_demotes_low_rr():
    grade, notes = vivek.gate_grade("A+", {}, rr=1.0, armed=True)
    assert grade == "B+" and any("R:R" in n for n in notes)


def test_gate_leaves_lower_grades_untouched():
    assert vivek.gate_grade("B+", {}, rr=1.0, armed=False) == ("B+", [])
    assert vivek.gate_grade("WATCH", {}, rr=0.5, armed=False) == ("WATCH", [])


# ── trigger model + per-timeframe plans ─────────────────────────────────────────

def test_long_reclaim_trigger_fires_and_arms():
    """Price pierced the level then closed back above it on the last bar → reclaim."""
    df = _frame("long_bounce")
    sig = vivek.evaluate(df)
    plan = vivek.build_tf_plan(df, "long")
    assert plan is not None
    # The dip-then-bounce fixture closes back above its ~100 level → an armed reclaim.
    assert plan["armed"] is True
    assert plan["entry_trigger"] in ("reclaim", "retest", "break")
    assert plan["trigger_bar"] is not None
    assert plan["stop"] < plan["entry"] < plan["tp1"] < plan["tp2"] < plan["tp3"]


def test_break_trigger_requires_volume():
    """A close beyond the prior pivot only triggers `break` with volume support."""
    n = 60
    # Gently declining highs so there is exactly one clean prior pivot (the 103
    # spike) — a flat plateau would make every bar a pivot under the >= rule.
    hi = np.linspace(102.0, 100.2, n); hi[40] = 103.0
    lo = hi - 0.6; o = hi - 0.3; cl = hi - 0.3
    # Last bar trades well ABOVE the level (low 102) so it neither pierces nor
    # retests it — only a structure break is eligible.
    o[-1] = 102.5; lo[-1] = 102.0; cl[-1] = 104.0; hi[-1] = 104.5
    vol = np.full(n, 1e6)
    df = pd.DataFrame({"Open": o, "High": hi, "Low": lo, "Close": cl, "Volume": vol},
                      index=pd.date_range("2021-01-01", periods=n, freq="D"))
    assert vivek.detect_trigger(df, "long", level=99.0) is None    # volume == average → no break
    df.iloc[-1, df.columns.get_loc("Volume")] = 2e6                # 2x average
    trig = vivek.detect_trigger(df, "long", level=99.0)
    assert trig is not None and trig["type"] == "break" and trig["entry"] == pytest.approx(103.0)


def test_watching_setup_not_armed():
    """Price sitting above the level with no pierce/retest/break → WATCHING."""
    n = 60
    cl = np.full(n, 105.0); o = cl.copy(); hi = cl * 1.001; lo = cl * 0.999
    df = pd.DataFrame({"Open": o, "High": hi, "Low": lo, "Close": cl, "Volume": np.full(n, 1e6)},
                      index=pd.date_range("2021-01-01", periods=n, freq="D"))
    assert vivek.detect_trigger(df, "long", level=99.0) is None
    plan = vivek.build_tf_plan(df, "long")
    assert plan is not None and plan["armed"] is False and plan["entry_trigger"] is None


def test_build_plans_emits_daily_and_weekly():
    df = _frame("long_bounce")
    sig = vivek.evaluate(df)
    plans = vivek.build_plans(df, sig)
    assert "1D" in plans                                   # daily always present
    assert "1W" in plans                                   # 340 daily bars → enough weeks
    for p in plans.values():
        assert p["stop"] < p["entry"] < p["tp1"] < p["tp2"] < p["tp3"]
        assert "armed" in p and "level" in p
    markers = vivek.build_markers(plans)
    assert set(markers) == set(plans)                      # one marker list per plan TF


# ── entry-type categories (filter chips) ────────────────────────────────────────

def test_entry_types_classify_each_interaction():
    assert "reclaim" in vivek.entry_types({"reaction": "bounce", "at_level": True, "structure": 0.4})
    assert "reclaim" in vivek.entry_types({"reaction": "reject", "at_level": False, "structure": 0.2})
    assert "retest" in vivek.entry_types({"reaction": "hold", "at_level": True, "structure": 0.6})
    assert "break" in vivek.entry_types({"reaction": "hold", "at_level": False, "structure": 0.9})


def test_entry_types_always_returns_at_least_one():
    assert vivek.entry_types({"reaction": "fade", "at_level": False, "structure": 0.1}) == ["retest"]
    # every code maps to a human label
    assert set(vivek.ENTRY_TYPES) <= set(vivek.ENTRY_TYPE_LABELS)


# ── bot: take / skip ──────────────────────────────────────────────────────────

def _row(**kw):
    r = {"symbol": "BHP", "dir": "LONG", "grade": "A", "rr": 3.0,
         "entry": 100.0, "stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
         "at_level": True, "reaction": "bounce", "armed": True, "entry_trigger": "reclaim",
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


def test_bot_skips_when_not_armed():
    d = vivek_bot.evaluate_setup(_row(armed=False))
    assert d["take"] is False and d["code"] == "not_armed"


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


# ── bot: portfolio discipline (few, uncorrelated positions) ─────────────────────

def test_decide_caps_total_positions():
    rows = [_row(symbol=f"S{i}", sector=f"sec{i}") for i in range(8)]   # all takeable
    out = vivek_bot.decide(rows, equity=10_000, max_positions=3)
    assert len(out["plans"]) == 3
    assert out["summary"]["skip_reasons"].get("book_full") == 5


def test_decide_caps_per_sector():
    rows = [_row(symbol=f"M{i}", sector="Materials") for i in range(4)]
    out = vivek_bot.decide(rows, equity=10_000)                         # default 2 per sector
    assert len(out["plans"]) == 2
    assert out["summary"]["skip_reasons"].get("sector_full") == 2


def test_decide_dedups_symbol():
    rows = [_row(symbol="BHP", sector="A"), _row(symbol="BHP", sector="A")]
    out = vivek_bot.decide(rows, equity=10_000)
    assert len(out["plans"]) == 1
    assert out["summary"]["skip_reasons"].get("dup_symbol") == 1


def test_bot_leverage_defaults_to_conservative_target():
    # A tight stop would imply huge leverage; the bot caps at the 3× target, not 5×.
    out = vivek_bot.plan_trade(_row(entry=100, stop=99.99, tp1=101, tp2=102, tp3=103),
                               equity=10_000)
    assert out["plan"]["leverage"] <= config.VIVEK_BOT_TARGET_LEVERAGE + 1e-9
    assert out["plan"]["leverage_capped"] is True
