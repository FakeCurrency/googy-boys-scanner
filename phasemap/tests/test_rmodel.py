"""PhaseMap's R model (backtest/rmodel.py): the harness's signals scored in R.

Driven through the real harness over the synthetic fixtures whose outcomes the
spec pins (fixture1 consumes T1, fixture5 stalls, fixture6 dies, fixture7 is
fixture1's exact bearish mirror). The model may only READ the engine: every
level is a zone the engine built and every exit is an event the recorder saw.
"""

import json

from phasemap.backtest import rmodel
from phasemap.backtest.harness import run_ticker
from phasemap.backtest.report import write_public_stats, write_report
from phasemap.tests import synth


def one(df, direction="bullish"):
    sigs = [s for s in run_ticker("TST", df, "asx") if s["direction"] == direction]
    assert len(sigs) == 1
    return sigs[0]


def test_a_t1_hit_is_a_winner_exited_on_the_engines_own_bar():
    s = one(synth.fixture1())
    assert s["r_tradeable"] and s["r_exit_reason"] == "t1"
    assert s["r_exit_bar"] == s["t1_consumed_bar"], "the exit IS the engine event"
    assert s["r_stop"] == s["inv_low"], "risk runs to the hard floor the engine built"
    assert s["realized_r"] > 0 and s["r_gross"] > s["realized_r"], "costs are charged"


def test_a_death_under_the_three_fills():
    """House: the floor is a resting stop, filled AT the floor (-1R before
    costs). Worst print: the bar's low, so no better than house. Engine-native:
    DEAD is a CLOSE beyond the floor, so at least -1R. House and worst exit on
    the same bar."""
    s = one(synth.fixture6())
    assert s["r_exit_reason"] == s["r_exit_reason_worst"] == s["r_exit_reason_close"] == "stop"
    assert s["r_gross"] == -1.0
    assert s["r_gross_worst"] <= s["r_gross"]
    assert s["r_gross_close"] <= -1.0 and s["r_exit_bar_close"] == s["dead_bar"]
    assert s["r_exit_bar"] == s["r_exit_bar_worst"] <= s["dead_bar"]


def test_a_wick_through_the_floor_stops_the_house_rule_but_not_the_engine():
    """The one place the house rule is stricter than the spec ("wicks through
    are a test only"): a bar that trades below the floor and closes back above
    it. House and worst are stopped on that bar; the engine-native reading
    rides on -- which is why it is published beside them as a reference."""
    ind = type("I", (), {})()
    ind.open = [10.0, 9.6, 9.8, 10.4]
    ind.high = [10.1, 9.9, 10.5, 10.6]
    ind.low = [9.9, 8.8, 9.7, 10.2]
    ind.close = [10.0, 9.5, 10.3, 10.5]
    import datetime
    ind.dates = [datetime.date(2026, 1, d) for d in (5, 6, 7, 8)]
    sig = {"signal_index": 0, "direction": "bullish", "inv_low": 9.0, "inv_high": 9.0,
           "dead_bar": None, "t1_consumed_bar": None, "end_index": None}
    out = rmodel.score(sig, ind, "asx")
    assert out["r_exit_reason"] == "stop" and out["r_exit_bar"] == 1 and out["r_gross"] == -1.0
    assert out["r_gross_worst"] == -1.2                    # the 8.8 wick
    assert out["r_exit_reason_close"] == "eod" and out["r_gross_close"] == 0.5


def test_a_gap_through_the_floor_fills_at_the_open():
    ind = type("I", (), {})()
    ind.open, ind.high, ind.low, ind.close = [10.0, 8.5], [10.1, 8.9], [9.9, 8.2], [10.0, 8.6]
    import datetime
    ind.dates = [datetime.date(2026, 1, 5), datetime.date(2026, 1, 6)]
    sig = {"signal_index": 0, "direction": "bullish", "inv_low": 9.0,
           "dead_bar": 1, "t1_consumed_bar": None, "end_index": None}
    out = rmodel.score(sig, ind, "asx")
    assert out["r_gross"] == -1.5 and out["r_gross_worst"] == -1.8 and out["r_gross_close"] == -1.4


def test_a_stall_that_never_resolves_is_marked_at_the_end():
    s = one(synth.fixture5())
    assert s["r_exit_reason"] in ("eod", "engine_end")
    assert s["stalled_bar"] is not None


def test_the_bearish_mirror_scores_the_same_trade_the_other_way():
    bull, bear = one(synth.fixture1()), one(synth.fixture7(), "bearish")
    assert bear["r_exit_reason"] == bull["r_exit_reason"] == "t1"
    assert abs(bear["r_gross"] - bull["r_gross"]) < 1e-3
    assert bear["r_stop"] == bear["inv_high"]


def test_a_floor_inside_the_house_minimum_stop_is_not_a_trade():
    s = dict(one(synth.fixture1()))
    s["inv_low"] = s["r_entry"] * (1 - 0.001)          # 0.1% below the entry
    ind_close = [s["r_entry"]] * (s["signal_index"] + 2)
    ind = type("I", (), {"close": ind_close, "dates": [None] * len(ind_close)})()
    out = rmodel.score(s, ind, "asx")
    assert out == {"r_tradeable": False, "r_skip": "stop_too_tight"}


def test_the_summary_headline_is_long_graded_and_adds_up():
    sigs = []
    for fx in (synth.fixture1, synth.fixture5, synth.fixture6, synth.fixture7):
        sigs += run_ticker("TST", fx(), "asx")
    r = rmodel.summary(sigs, 1000.0)
    lg = r["long_graded"]
    assert lg["trades"] == 3 and lg["wins"] == 1
    assert abs(lg["net_r"] - (lg["r_won"] + lg["r_lost"])) < 0.02
    assert r["all"]["trades"] == sum(v["trades"] for v in r["by_tier"].values())
    assert lg["notional"] == 1000.0 and "net_usd" in lg


def test_the_report_and_public_stats_carry_it(tmp_path):
    sigs = run_ticker("TST", synth.fixture1(), "asx")
    md = open(write_report("asx", sigs, {"n": 0}, {"n": 0}, 1, "5y", out_dir=str(tmp_path))).read()
    assert "## R model" in md and "long A+/A (headline)" in md
    assert "stop at the worst print" in md and "engine-native close exits" in md
    path = write_public_stats("asx", sigs, {"n": 0}, {"n": 0}, 1, "5y", out_dir=str(tmp_path))
    doc = json.load(open(path))
    assert doc["r_model"]["long_graded"]["trades"] == 1
    assert doc["r_model"]["fill"] == "house"
    assert doc["r_model"]["worst_print"]["long_graded"]["trades"] == 1
    assert doc["r_model"]["engine_close"]["long_graded"]["trades"] == 1
    assert {"all", "cohorts", "stall", "baselines"} <= set(doc), "additive: nothing moved"
