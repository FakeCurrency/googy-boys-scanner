"""Audit #25 (2026-10-08): the day-of DISPLACED record is tiered like the
backtest harness tiers the same signal.

anchor_context used to be computed only inside module 4 (RUNNING/STALLED
bars), which never runs on the displacement bar, so the freshest record of an
A+ setup published tier A with no ANCHOR_CONTEXT tag and turned A+ only the
next session -- while harness._capture, reading swept_below_anchor directly,
labelled the same signal A+ ("the harness can never disagree with the
product's rules"). Across 21 archived snapshots: 112 DISPLACED records, 0 A+.
"""

from phasemap.backtest.harness import run_ticker
from phasemap.engine.scanner import scan_ticker
from phasemap.tests import synth

VOL = synth.VOL
# fixture 1's sweep, but its close reclaims the 0.985 quarterly open
RECLAIMING_SWEEP = (0.98, 0.99, 0.945, 0.988, VOL)


def _frames():
    yield "fixture1", synth.fixture1()
    yield "reclaiming_sweep", synth.bars_df(
        synth.base_to_box() + [RECLAIMING_SWEEP, synth.DISPLACEMENT_BAR] + synth.RUN_BARS)
    yield "fixture7", synth.fixture7()
    yield "fixture8", synth.fixture8()
    yield "fixture5", synth.fixture5()


def _day_of(df, k, direction):
    for rec, _eng in scan_ticker("TST", df.iloc[:k + 1].reset_index(drop=True)):
        if rec["direction"] == direction:
            return rec
    return None


def test_the_day_of_record_carries_the_harness_tier_and_tag():
    checked = 0
    for name, df in _frames():
        for sig in run_ticker("TST", df, "asx"):
            rec = _day_of(df, sig["signal_index"], sig["direction"])
            assert rec is not None and rec["state"] == "DISPLACED", name
            assert rec["tier"] == sig["tier"], (name, sig["direction"])
            assert ("ANCHOR_CONTEXT" in rec["tags"]) == sig["anchor_context"], name
            checked += 1
    assert checked >= 5


def test_an_anchor_reclaimed_at_the_sweep_is_a_plus_on_the_displacement_day():
    df = dict(_frames())["reclaiming_sweep"]
    rec = _day_of(df, 261, "bullish")            # bar 261 = the displacement candle
    assert rec["state"] == "DISPLACED"
    assert rec["tier"] == "A+"
    assert "ANCHOR_CONTEXT" in rec["tags"]


def test_the_tier_does_not_change_overnight_without_new_evidence():
    # fixture 1: the displacement close reclaims the quarterly open, so the
    # record is A+ on the day it prints, not only from the next session
    df = synth.fixture1()
    day_of = _day_of(df, 261, "bullish")
    next_day = _day_of(df, 262, "bullish")
    assert day_of["state"] == "DISPLACED" and next_day["state"] == "RUNNING"
    assert day_of["tier"] == next_day["tier"] == "A+"
