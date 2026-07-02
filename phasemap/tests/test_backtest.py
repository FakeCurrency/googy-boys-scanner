"""M4 harness: fixture signals must be captured and measured correctly, and
the whole pipeline must stay deterministic."""

import json

from phasemap.backtest.harness import (buy_hold_baseline, random_baseline,
                                       run_ticker)
from phasemap.backtest.report import cohorts, stall_summary, summarise
from phasemap.tests import synth


def bullish(signals):
    return [s for s in signals if s["direction"] == "bullish"]


def test_fixture1_signal_hits_t1():
    sigs = bullish(run_ticker("TST", synth.fixture1(), "asx"))
    # the clean setup fires exactly one bullish displacement signal
    assert len(sigs) == 1
    s = sigs[0]
    assert s["tier"] in ("A", "A+")
    assert s["t1_consumed_bar"] is not None
    assert s["t1_hit"] is True
    assert s["time_to_t1"] is not None and s["time_to_t1"] <= 10
    assert s["stalled_bar"] is None and s["dead_bar"] is None
    # bullish run: the 5-bar forward return from the entry mid is positive
    assert s["fwd_5"] is not None and s["fwd_5"] > 0


def test_fixture5_stall_recorded():
    sigs = bullish(run_ticker("TST", synth.fixture5(), "asx"))
    assert len(sigs) == 1
    s = sigs[0]
    assert s["stalled_bar"] is not None
    assert s["stall_class"] in ("saved_capital", "cut_winner", "neither")


def test_fixture6_death_recorded():
    sigs = bullish(run_ticker("TST", synth.fixture6(), "asx"))
    assert len(sigs) == 1
    s = sigs[0]
    assert s["dead_bar"] is not None
    assert s["t1_hit"] is False


def test_summaries_and_cohorts():
    sigs = (run_ticker("AAA", synth.fixture1(), "asx")
            + run_ticker("BBB", synth.fixture5(), "asx")
            + run_ticker("CCC", synth.fixture6(), "asx"))
    top = summarise(sigs)
    assert top["n"] == len(sigs) >= 3
    assert top["t1_hit_pct"] is not None
    split = cohorts(sigs)
    assert any(k.startswith("tier") for k in split)
    st = stall_summary(sigs)
    assert st["stalled"] >= 1
    assert st["saved_capital"] + st["cut_winner"] + st["neither"] == st["stalled"]


def test_baselines_deterministic():
    frames = {"AAA": synth.fixture1(), "BBB": synth.fixture_complete()}
    a = random_baseline(frames, 10, "asx")
    b = random_baseline(frames, 10, "asx")
    assert a == b                      # seeded — byte-identical reruns
    bh = buy_hold_baseline(frames)
    assert bh["n"] == 2


def test_signals_json_serialisable_and_deterministic():
    a = json.dumps(run_ticker("TST", synth.fixture1(), "asx"), sort_keys=True)
    b = json.dumps(run_ticker("TST", synth.fixture1(), "asx"), sort_keys=True)
    assert a == b
