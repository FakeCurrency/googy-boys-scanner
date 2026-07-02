"""M1 acceptance: the 8 required synthetic fixtures (spec Section 11)."""

import pytest

from phasemap.engine.indicators import compute_indicators
from phasemap.engine.scanner import scan_ticker
from phasemap.engine.setup_engine import SetupEngine
from phasemap.tests import synth


def run(df, direction="bullish"):
    """Returns (record, engine) for the requested direction, or (None, None)."""
    for rec, eng in scan_ticker("TST", df):
        if rec["direction"] == direction:
            return rec, eng
    return None, None


def run_engine(df, bull=True):
    """Direct engine access — needed for negative fixtures where the correct
    outcome is 'no record emitted at all'."""
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).reset_index(drop=True)
    eng = SetupEngine(ind=compute_indicators(df), bull=bull)
    eng.process()
    return eng


def states(eng):
    return [s for _, s in eng.state_log]


def zone(rec, zid):
    for z in rec["zones"]:
        if z["id"] == zid:
            return z
    return None


# ---------------------------------------------------------------- fixture 1
def test_fixture1_clean_sweep_displacement_run_to_t1():
    rec, eng = run(synth.fixture1())
    assert rec is not None
    chain = states(eng)
    for expected in ("TRAP_SET", "SWEPT", "DISPLACED", "RUNNING"):
        assert expected in chain
    # displacement chain ordered correctly
    assert chain.index("DISPLACED") < chain.index("RUNNING")
    assert rec["state"] == "RUNNING"
    assert rec["tier"] in ("A", "A+")
    assert rec["regime"] == "EXPANSION"
    t1 = zone(rec, "t1")
    assert t1 is not None and t1["status"] == "CONSUMED"
    t2 = zone(rec, "t2")
    assert t2 is not None and t2["status"] != "CONSUMED"
    assert zone(rec, "inv_soft")["status"] == "UNTESTED"
    assert "ILLIQUID" not in rec["tags"]
    assert rec["metrics"]["sweep_date"] is not None
    # sweep printed on a Monday -> FAST_FLIP bonus
    assert "FAST_FLIP" in rec["tags"]


# ---------------------------------------------------------------- fixture 2
def test_fixture2_equal_lows_double_tap_cents_stock():
    rec, eng = run(synth.fixture2())
    assert rec is not None
    assert rec["state"] == "SWEPT"
    assert eng.sweep_variant == "equal_lows"
    assert eng.key_level == pytest.approx(0.0485)     # cluster max, not wick min
    assert eng.sweep_extreme == pytest.approx(0.0480)
    assert "ILLIQUID" in rec["tags"]
    assert rec["tier"] == "Watch"
    demand = zone(rec, "demand")
    assert demand["low"] == pytest.approx(0.0480)
    assert demand["high"] == pytest.approx(0.0485)


# ---------------------------------------------------------------- fixture 3
def test_fixture3_no_displacement_reverts_to_neutral():
    eng = run_engine(synth.fixture3())
    chain = states(eng)
    assert "DISPLACED" not in chain
    # the sweep printed, then expired back to NEUTRAL
    sweep_pos = len(chain) - 1 - chain[::-1].index("SWEPT")
    assert "NEUTRAL" in chain[sweep_pos:]
    assert eng.demand is None            # zones cleared on expiry
    assert eng.sweep_index == -1
    assert eng.state not in ("SWEPT", "DISPLACED", "RUNNING")


# ---------------------------------------------------------------- fixture 4
def test_fixture4_deep_sweep_rejected_as_breakdown():
    eng = run_engine(synth.fixture4())
    # the 20%-deep flush must never register as a sweep
    assert eng.sweep_index == -1
    assert eng.state in ("NEUTRAL", "TRAP_SET")
    assert eng.demand is None


# ---------------------------------------------------------------- fixture 5
def test_fixture5_momentum_touch_stalls_and_routes_to_fib():
    rec, eng = run(synth.fixture5())
    assert rec is not None
    assert rec["state"] == "STALLED"
    assert rec["route_to"] == "fib_reversal"
    assert zone(rec, "inv_soft")["status"] == "VIOLATED"
    assert rec["tier"] is None
    assert rec["regime"] == "ROTATION"
    # structure still intact — hard invalidation not violated
    assert zone(rec, "inv_hard")["status"] != "VIOLATED"


# ---------------------------------------------------------------- fixture 6
def test_fixture6_hard_zone_wick_is_test_close_is_kill():
    rec, eng = run(synth.fixture6())
    chain = dict(eng.state_log)          # index -> state
    # bar 262 wicked through the floor but closed back inside: alive
    assert eng.state_log[-1][1] == "DEAD"
    dead_index = eng.state_log[-1][0]
    alive_states = [s for i, s in eng.state_log if i < dead_index]
    assert "DEAD" not in alive_states
    assert rec["state"] == "DEAD"
    inv_hard = zone(rec, "inv_hard")
    assert inv_hard["status"] == "VIOLATED"


def test_fixture6_wick_only_stays_alive():
    """First ending bar only: wick through floor, close back above => alive."""
    import pandas as pd
    df = synth.fixture6().iloc[:-1].reset_index(drop=True)   # drop the kill bar
    rec, eng = run(df)
    assert eng.state != "DEAD"
    assert eng.inv_hard.status in ("TESTED", "RESPECTED")


# ---------------------------------------------------------------- fixture 7
def test_fixture7_full_bearish_mirror():
    rec, eng = run(synth.fixture7(), direction="bearish")
    assert rec is not None
    chain = states(eng)
    for expected in ("SWEPT", "DISPLACED", "RUNNING"):
        assert expected in chain
    assert rec["state"] == "RUNNING"
    assert rec["tier"] in ("A", "A+")
    supply = zone(rec, "supply")
    assert supply is not None and supply["type"] == "SUPPLY"
    t1 = zone(rec, "t1")
    assert t1 is not None and t1["status"] == "CONSUMED"
    # bearish invalidations sit ABOVE price
    inv_hard = zone(rec, "inv_hard")
    assert inv_hard["low"] >= supply["high"] - 1e-9


# ---------------------------------------------------------------- fixture 8
def test_fixture8_triple_confluence_target_merge():
    rec, eng = run(synth.fixture8())
    assert rec is not None
    t1 = zone(rec, "t1")
    assert t1 is not None
    assert t1["confluence"] >= 3
    for src in ("fib_ext_10", "equal_highs", "quarterly_open"):
        assert src in t1["sources"], f"missing source {src}: {t1['sources']}"


# ------------------------------------------------------------- supplementary
def test_trap_set_pre_alert_watch_tier():
    rec, eng = run(synth.fixture_trap_only())
    assert rec is not None
    assert rec["state"] == "TRAP_SET"
    assert rec["tier"] == "Watch"
    assert "cluster_low" in rec["metrics"]


def test_complete_when_all_targets_consumed():
    rec, eng = run(synth.fixture_complete())
    assert rec is not None
    assert rec["state"] == "COMPLETE"
    assert all(z["status"] == "CONSUMED"
               for z in rec["zones"] if z["type"] == "TARGET")
