"""Output snapshot: schema validation, determinism (byte-identical re-runs),
file writing with latest.json copy."""

import pytest

from phasemap.engine.scanner import scan_ticker, sort_records
from phasemap.narrate.renderer import render
from phasemap.output.writer import (build_snapshot, serialise,
                                    validate_snapshot, write_snapshot)
from phasemap.tests import synth


def snapshot_for(dfs: dict) -> dict:
    results = []
    for ticker, df in sorted(dfs.items()):
        for rec, _eng in scan_ticker(ticker, df):
            rec["narration"] = render(rec)
            results.append(rec)
    return build_snapshot("2026-07-02", universe_size=len(dfs),
                          results=sort_records(results))


def test_snapshot_validates():
    snap = snapshot_for({"AAA": synth.fixture1(), "BBB": synth.fixture2(),
                         "CCC": synth.fixture5()})
    validate_snapshot(snap)   # must not raise
    assert snap["universe_size"] == 3
    assert len(snap["results"]) >= 3


def test_deterministic_byte_identical_reruns():
    a = serialise(snapshot_for({"AAA": synth.fixture1(), "BBB": synth.fixture8()}))
    b = serialise(snapshot_for({"AAA": synth.fixture1(), "BBB": synth.fixture8()}))
    assert a == b


def test_results_sorted_by_tier_then_ticker():
    snap = snapshot_for({"ZZZ": synth.fixture1(), "AAA": synth.fixture1()})
    tiers = [r["tier"] for r in snap["results"]]
    order = {"A+": 0, "A": 1, "Watch": 2, None: 3}
    assert tiers == sorted(tiers, key=lambda t: order[t])
    same_tier = [r["ticker"] for r in snap["results"] if r["tier"] == tiers[0]
                 and r["direction"] == "bullish"]
    assert same_tier == sorted(same_tier)


def test_write_snapshot_and_latest_copy(tmp_path):
    snap = snapshot_for({"AAA": synth.fixture1()})
    dated = write_snapshot(snap, str(tmp_path))
    latest = tmp_path / "latest.json"
    assert latest.exists()
    assert (tmp_path / "2026-07-02.json").read_bytes() == latest.read_bytes()


def test_validator_rejects_bad_band():
    snap = snapshot_for({"AAA": synth.fixture1()})
    snap["results"][0]["zones"][0]["low"] = 99.0   # low > high
    with pytest.raises(ValueError):
        validate_snapshot(snap)


def test_validator_requires_disclaimer():
    snap = snapshot_for({"AAA": synth.fixture1()})
    snap["results"][0]["narration"] = "Buy now!"
    with pytest.raises(ValueError):
        validate_snapshot(snap)
