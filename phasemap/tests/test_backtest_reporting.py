"""REFINE200 #200 — the replay's REPORTING tells the truth about itself.

Evidence only: no detection, zone or state rule moves. Three findings:
  * the A+ label: the harness labelled a signal A+ off anchor context the
    live card only evaluates from the bar AFTER displacement, so the
    displacement-day card (A/Watch) and the cohort (A+) disagreed; both are
    now recorded, the day-of one by the scanner's own _tier;
  * fill look-ahead (pinned in test_fill_realism.py);
  * the pooled signal return (longs + signed shorts) was compared with a
    LONG-only random drift.
"""

import json
import os

import pytest

from phasemap.backtest.harness import random_baseline, run_ticker
from phasemap.backtest.report import tier_note, write_report, write_stats
from phasemap.engine.scanner import scan_ticker
from phasemap.tests import synth

def anchor_reclaimed():
    """Fixture 1 with the sweep's quarter opening at 0.96: the sweep runs the
    0.96 lows (low 0.945) and closes 0.972, back above the quarterly open —
    anchor context, reclaimed on the sweep bar itself."""
    df = synth.fixture1()
    df.loc[201, "Low"] = 0.95
    df.loc[201, "Open"] = 0.96          # bar 201 = 2025-07-01, the quarter's first
    return df


FIXTURES = [synth.fixture1, synth.fixture5, synth.fixture6, synth.fixture7,
            synth.fixture8, synth.fixture_complete, anchor_reclaimed]


def test_the_a_plus_label_is_the_running_cards_not_the_displacement_days():
    """The live mismatch, reproduced: the cohort says A+, the card on the
    displacement day said A, and the card from the next session says A+."""
    df = anchor_reclaimed()
    (sig,) = [s for s in run_ticker("TST", df, "asx") if s["direction"] == "bullish"]
    assert (sig["tier"], sig["card_tier"]) == ("A+", "A")
    running = [r for r, _ in scan_ticker("TST", df) if r["direction"] == "bullish"][0]
    assert (running["state"], running["tier"]) == ("RUNNING", "A+")
    assert "0 of 1 A+ signals showed A+" in tier_note([sig])


@pytest.mark.parametrize("fx", FIXTURES)
def test_card_tier_is_exactly_what_the_scanner_published_that_day(fx):
    df = fx()
    sigs = run_ticker("TST", df, "asx")
    assert sigs
    for s in sigs:
        day = df.iloc[:s["signal_index"] + 1].reset_index(drop=True)
        recs = [r for r, _ in scan_ticker("TST", day) if r["direction"] == s["direction"]]
        assert recs and recs[0]["state"] == "DISPLACED"
        assert s["card_tier"] == recs[0]["tier"]


def test_the_matched_baseline_signs_the_same_draws_to_the_signals_mix():
    frames = {"AAA": synth.bars_df(synth.trend(400, 1.0, 0.002, 0.02, synth.VOL)),
              "BBB": synth.bars_df(synth.trend(400, 5.0, -0.003, 0.05, synth.VOL))}
    long_only = random_baseline(frames, 10, "asx")
    assert long_only["n"] == 10
    all_short = random_baseline(frames, 10, "asx", n_short=10)
    half = random_baseline(frames, 10, "asx", n_short=5)
    for h in (5, 10, 20):
        k = f"fwd_{h}"
        # the long-only numbers never move with the mix (Insights reads them)
        assert long_only[k] == all_short[k] == half[k]
        assert long_only["matched"][k] == long_only[k]
        assert all_short["matched"][k] == pytest.approx(-long_only[k], abs=1e-4)
    assert half["matched"]["n_long"] == 5 and half["matched"]["n_short"] == 5


def test_the_report_names_both_baselines_and_the_tier_caveat(tmp_path):
    frames = {"AAA": synth.fixture1(), "BBB": synth.fixture7()}
    sigs = run_ticker("AAA", frames["AAA"], "asx") + run_ticker("BBB", frames["BBB"], "asx")
    rnd = random_baseline(frames, len(sigs), "asx",
                          n_short=sum(s["direction"] == "bearish" for s in sigs))
    path = write_report("asx", sigs, rnd, {"n": 2, "total_return": 0.1},
                        universe_size=2, period="5y", out_dir=str(tmp_path))
    text = open(path, encoding="utf-8").read()
    assert "Random entry, LONG only" in text and "signed to the signals' own mix" in text
    assert "measured from the FILL" in text
    assert "entry-zone midpoint; " not in text          # the stale pre-1.3.1 sentence
    assert tier_note(sigs) in text


def test_write_stats_is_atomic(tmp_path):
    sigs = run_ticker("TST", synth.fixture1(), "asx")
    path = write_stats("asx", sigs, out_dir=str(tmp_path))
    assert os.listdir(tmp_path) == ["asx.json"]
    assert json.load(open(path))["sample"] == len([s for s in sigs if s["tier"] in ("A+", "A")])
