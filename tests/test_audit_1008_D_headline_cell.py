"""Audit #14 (2026-10-08, owner-approved): the row headline and the R:R gate
read the first ARMED timeframe, but the bot trades the first CELL plan.

Since the 2026-09-21 cell ruling `vivek_bot._pick_plan` skips an armed plan
whose trigger is not in VIVEK_BOT_ENTRY_CELLS (a retest always; a 1D reclaim;
a 3D break). scan.py still headlined -- and fed gate_grade the R:R of -- the
first armed plan 1W > 3D > 1D whatever its trigger, so:
  * display: JBH headlined a 1W retest (entry 68.23, stop 59.40, 1.75R) under
    the chip "the one the bot trades" while the bot took the 1D break
    (68.32 / 64.03, 2.37R);
  * gate: a 1W retest at 1.2R demoted to B+ a row whose armed 3D reclaim at
    3.0R the bot would have taken -- grade_excluded, a real cell trade lost.
Now both scan.py and vivek_backtest._build_row call vivek.headline_plan: the
bot's cell walk first, then the first armed plan, then (watching) the Daily.
"""
import itertools

import pandas as pd
import pytest

import scanner.vivek as vivek
from scanner import config, scan, vivek_backtest
from scanner.broker import vivek_bot


def _plan(entry, armed=True, trigger="reclaim", rr=2.0, risk=4.0):
    return {"armed": armed, "entry": entry, "stop": entry - risk,
            "tp1": entry + 0.9 * risk, "tp2": entry + rr * risk,
            "tp3": entry + (rr + 2.0) * risk,
            "scale": [0.25, 0.50, 0.15], "risk": risk, "rr": rr,
            "entry_trigger": trigger if armed else None,
            "trigger_bar": "2024-01-02" if armed else None}


_SIG = {"direction": "long", "close": 100.0, "level_tf": "weekly", "level": 99.0,
        "at_level": True, "reaction": "bounce", "structure": 0.8, "confluence": False}


def _frame():
    idx = pd.date_range(end="2024-01-02", periods=30, freq="D")
    return pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                         "Close": 100.0, "Volume": 1_000_000.0}, index=idx)


def _row_for(monkeypatch, plans, raw=("A+", 9)):
    monkeypatch.setattr(config, "VIVEK_H4_PLANS", False)     # no intraday download
    monkeypatch.setattr(vivek, "evaluate", lambda df: dict(_SIG))
    monkeypatch.setattr(vivek, "score_and_grade", lambda sig: (raw[1], raw[0], ["CHIP"]))
    monkeypatch.setattr(vivek, "build_plans", lambda df, sig: dict(plans))
    monkeypatch.setattr(vivek, "build_markers", lambda plans: {})
    monkeypatch.setattr(vivek, "build_detail", lambda df, sig, lv: {})
    monkeypatch.setattr(vivek, "narrative", lambda *a, **k: "n/a")
    monkeypatch.setattr(vivek, "entry_types", lambda sig: ["reclaim"])
    uni = [{"yf": "JBH.AX", "symbol": "JBH", "name": "JB Hi-Fi", "sector": "Retail"}]
    (row,) = scan.scan_vivek_market("asx", universe=uni, frames={"JBH.AX": _frame()},
                                    pulse_data=[], progress=False)["results"]
    return row


def test_a_low_rr_weekly_retest_no_longer_demotes_an_armed_3d_reclaim(monkeypatch):
    plans = {"1D": _plan(100.0, armed=False),
             "3D": _plan(101.0, trigger="reclaim", rr=3.0),
             "1W": _plan(98.0, trigger="retest", rr=1.2)}
    row = _row_for(monkeypatch, plans)
    assert row["grade_raw"] == "A+" and row["grade"] == "A+", "a non-cell R:R demoted the row"
    assert not any("LOW R:R" in c for c in row["chips"])
    assert row["headline_tf"] == "3D" and row["armed_tf"] == "3D"
    assert row["entry_trigger"] == "reclaim" and row["rr"] == 3.0
    out = _bot(row)
    assert out["take"] is True and out["timeframe"] == "3D"
    assert out["_plan"]["entry"] == row["entry"] and out["_plan"]["stop"] == row["stop"]


def test_the_headline_is_the_plan_the_bot_trades_the_jbh_case(monkeypatch):
    plans = {"1D": _plan(68.32, trigger="break", rr=2.37, risk=4.29),
             "1W": _plan(68.23, trigger="retest", rr=1.75, risk=8.83)}
    row = _row_for(monkeypatch, plans)
    out = _bot(row)
    assert out["take"] is True
    assert row["headline_tf"] == out["timeframe"] == "1D"
    assert (row["entry"], row["stop"], row["rr"]) == (68.32, out["_plan"]["stop"], 2.37)
    assert row["entry_types"] == ["break"]


def test_a_retest_only_row_still_headlines_its_armed_plan_and_the_bot_skips_it(monkeypatch):
    plans = {"1D": _plan(100.0, armed=False), "1W": _plan(103.0, trigger="retest", rr=2.0)}
    row = _row_for(monkeypatch, plans)
    assert row["armed"] is True and row["headline_tf"] == "1W"
    assert row["entry_trigger"] == "retest" and row["grade_raw"] == "A+"
    assert _bot(row)["code"] == "no_cell_plan"


def test_a_low_rr_cell_plan_still_demotes_because_the_bot_would_refuse_it(monkeypatch):
    """The walk does not shop for the best R:R: the bot takes the FIRST cell
    plan and refuses it on low_rr, so the gate reads that plan's R:R too."""
    plans = {"1W": _plan(103.0, trigger="reclaim", rr=1.2),
             "3D": _plan(101.0, trigger="reclaim", rr=3.0)}
    row = _row_for(monkeypatch, plans)
    assert row["headline_tf"] == "1W" and row["grade_raw"] == "B+"


def test_watching_rows_keep_the_daily_headline(monkeypatch):
    plans = {"1D": _plan(100.0, armed=False), "1W": _plan(103.0, armed=False)}
    row = _row_for(monkeypatch, plans)
    assert row["armed"] is False and row["headline_tf"] == "1D" and row["armed_tf"] is None


def _bot(row):
    """The bot's verdict on the row as if its frame were fresh (the fixture
    frame is dated 2024, which the stale-data gate would refuse first)."""
    return vivek_bot.evaluate_setup({**row, "data_age_days": 0})


def _all_plan_sets():
    trig = (None, "reclaim", "retest", "break")
    for combo in itertools.product(trig, repeat=3):
        plans = {}
        for i, (tf, t) in enumerate(zip(("1W", "3D", "1D"), combo)):
            plans[tf] = _plan(100.0 + i, armed=t is not None, trigger=t or "reclaim")
        yield plans


def test_headline_plan_agrees_with_the_bots_walk_on_every_trigger_combination():
    n_cell = 0
    for plans in _all_plan_sets():
        bot_tf, bot_plan = vivek_bot._pick_plan({"plans": plans})
        tf, plan = vivek.headline_plan(plans)
        if bot_plan is not None:
            n_cell += 1
            assert (tf, plan) == (bot_tf, bot_plan), plans
        else:
            first = next((t for t in ("1W", "3D", "1D") if plans[t]["armed"]), None)
            assert tf == first
    assert n_cell > 20                                   # the property was exercised


def test_the_headline_reads_the_bots_own_table():
    assert vivek.headline_plan({"3D": _plan(1.0, trigger="break")},
                               cells={"3D": ("break",)})[0] == "3D"
    p = {"1W": _plan(1.0, trigger="retest"), "3D": _plan(2.0, trigger="reclaim")}
    assert vivek.headline_plan(p)[0] == "3D"
    assert vivek.headline_plan(p, cells={})[0] == "1W"    # no cells: first armed
    assert set(config.VIVEK_BOT_ENTRY_CELLS) <= {"1W", "3D", "1D"}


@pytest.mark.parametrize("plans,want", [
    ({"3D": _plan(101.0, trigger="reclaim", rr=3.0), "1W": _plan(98.0, trigger="retest", rr=1.2)}, "A+"),
    ({"1W": _plan(98.0, trigger="retest", rr=1.2)}, "B+"),
])
def test_the_backtest_row_gates_exactly_like_the_scan(monkeypatch, plans, want):
    """Owner condition: the gate change lands in vivek_backtest._build_row in
    the same commit, so the replay measures the gate the live scan applies."""
    monkeypatch.setattr(vivek, "score_and_grade", lambda sig: (9, "A+", []))
    monkeypatch.setattr(vivek, "build_plans", lambda df, sig: dict(plans))
    row, got_plans, grade = vivek_backtest._build_row(dict(_SIG), _frame(), "JBH", "JB", "Retail")
    assert grade == want
    if want == "A+":
        assert row["entry_types"] == ["reclaim"]


def test_scan_and_backtest_share_one_gate_function():
    for mod in (scan, vivek_backtest):
        src = open(mod.__file__, encoding="utf-8").read()
        assert "vivek.headline_plan(plans)" in src, mod.__name__
        assert 'gate_tf = next((tf for tf in ("1W", "3D", "1D")' not in src, mod.__name__
