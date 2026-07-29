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


def test_bot_skips_stale_cache_reused_rows(monkeypatch):
    """2026-07-20 (Phase 2): a row built from a cache-reused frame carries
    data_age_days > 0 — its armed trigger describes a market that has since
    moved. The bot must never open on it; fresh rows pass untouched."""
    from scanner import config as _c
    monkeypatch.setattr(_c, "VIVEK_BOT_MAX_DATA_AGE_DAYS", 3, raising=False)
    row = {"symbol": "BHP", "name": "BHP", "sector": "Materials", "dir": "LONG",
           "grade": "A+", "grade_raw": "A+", "entry_types": ["reclaim"],
           "plans": {"1W": _plan(103.0, armed=True)}, "price": 103.0,
           "data_age_days": 5}
    out = vivek_bot.evaluate_setup(row)
    assert out["take"] is False and out["code"] == "stale_data"

    row["data_age_days"] = 0
    assert vivek_bot.evaluate_setup(row)["take"] is True
    del row["data_age_days"]                       # absent field == fresh
    assert vivek_bot.evaluate_setup(row)["take"] is True


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


# ── the pipeline funnel: drop-offs as numbers, not feelings (2026-07-29) ─────
# Published with every scan so "is a filter too restrictive?" is answerable
# from the artefact. Counted at the loop's own `continue` points — pure
# observation; these tests also pin the identity so a future drop point that
# forgets its counter shows up as a hole in the arithmetic.

def _run_full(monkeypatch, frames=None, uni=None):
    uni = uni or [{"yf": "BHP.AX", "symbol": "BHP", "name": "BHP", "sector": "Materials"}]
    return scan.scan_vivek_market("asx", universe=uni,
                                  frames=frames or {"BHP.AX": _frame()},
                                  pulse_data=[], progress=False)


def test_funnel_counts_a_clean_setup_through_to_grades(monkeypatch):
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    f = _run_full(monkeypatch)["funnel"]
    assert f["universe"] == 1 and f["with_data"] == 1
    assert f["setups"] == 1 and f["grades"].get("A+") == 1
    assert f["no_setup"] == f["illiquid_setup"] == f["below_score"] == f["no_plan"] == 0


def test_funnel_counts_no_setup(monkeypatch):
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    monkeypatch.setattr(vivek, "evaluate", lambda df: None)
    f = _run_full(monkeypatch)["funnel"]
    assert f["no_setup"] == 1 and f["setups"] == 0


def test_funnel_counts_an_illiquid_setup_separately(monkeypatch):
    # The interesting number: a name that HAD a setup and was dropped for
    # turnover — the row a too-tight liquidity floor would be killing.
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    monkeypatch.setattr(scan, "_liquidity", lambda df, m: 0.0)
    f = _run_full(monkeypatch)["funnel"]
    assert f["illiquid_setup"] == 1 and f["no_setup"] == 0 and f["setups"] == 0


def test_funnel_counts_below_score_and_no_plan(monkeypatch):
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    monkeypatch.setattr(vivek, "score_and_grade", lambda sig: (0, None, []))
    assert _run_full(monkeypatch)["funnel"]["below_score"] == 1
    _stub_engine(monkeypatch, {})          # no plans at all -> no headline plan
    f = _run_full(monkeypatch)["funnel"]
    assert f["no_plan"] == 1 and f["setups"] == 0


def test_funnel_identity_holds_with_a_thrown_name(monkeypatch):
    # Two names: one clean A+, one whose evaluate throws. The thrown one lands
    # in `errors`, and the identity must still balance exactly.
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    real_frame = _frame()
    calls = {"n": 0}

    def evaluate(df):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("synthetic failure")
        return dict(_SIG)
    monkeypatch.setattr(vivek, "evaluate", evaluate)
    uni = [{"yf": "BHP.AX", "symbol": "BHP", "name": "BHP", "sector": "Materials"},
           {"yf": "RIO.AX", "symbol": "RIO", "name": "RIO", "sector": "Materials"}]
    out = _run_full(monkeypatch, frames={"BHP.AX": real_frame, "RIO.AX": real_frame}, uni=uni)
    f = out["funnel"]
    assert f["errors"] == 1 and f["setups"] == 1
    assert (f["with_data"] == f["no_setup"] + f["illiquid_setup"] + f["below_score"]
            + f["no_plan"] + f["errors"] + f["setups"]), f"funnel does not balance: {f}"


def test_funnel_is_additive_not_a_schema_bump(monkeypatch):
    # Same contract as `errors` (TOP100 #60): consumers read named keys and the
    # schema gates read schema_version alone, so this key must ride the
    # CURRENT version rather than forcing every committed scan stale.
    from scanner import config
    _stub_engine(monkeypatch, {"1W": _plan(103.0, armed=True)})
    out = _run_full(monkeypatch)
    assert out["schema_version"] == config.VIVEK_SCHEMA_VERSION
    assert isinstance(out["funnel"], dict)
