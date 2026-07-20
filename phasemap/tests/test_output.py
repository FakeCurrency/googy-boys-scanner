"""Output snapshot: schema validation, determinism (byte-identical re-runs),
file writing with latest.json copy."""

import pytest

from phasemap.engine.scanner import scan_ticker, sort_records
from phasemap.narrate.renderer import render
from phasemap.output.writer import (build_snapshot, serialise, split_narrations,
                                    validate_published, validate_snapshot,
                                    write_snapshot)
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
    import json
    snap = snapshot_for({"AAA": synth.fixture1()})
    write_snapshot(snap, str(tmp_path))
    # dated snapshot keeps the FULL spec Section 7 schema (archival record)
    dated = json.loads((tmp_path / "2026-07-02.json").read_text(encoding="utf-8"))
    assert all("narration" in r for r in dated["results"])
    # published latest.json is slim: narration lives in narrations.json
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["narrations_file"] == "narrations.json"
    assert all("narration" not in r for r in latest["results"])
    assert [r["ticker"] for r in latest["results"]] == [r["ticker"] for r in dated["results"]]
    narr = json.loads((tmp_path / "narrations.json").read_text(encoding="utf-8"))
    for r in dated["results"]:
        assert narr["narrations"][f"{r['ticker']}|{r['direction']}"] == r["narration"]


def test_validate_published_accepts_slim_pair():
    """The CI schema gate validates the PUBLISHED slim latest.json against its
    narrations.json sidecar — this is what broke the nightly on 2026-07-05."""
    snap = snapshot_for({"AAA": synth.fixture1()})
    slim, narr = split_narrations(snap)
    validate_published(slim, narr)                 # must not raise


def test_validate_published_rejects_missing_sidecar_entry():
    snap = snapshot_for({"AAA": synth.fixture1()})
    slim, narr = split_narrations(snap)
    narr["narrations"] = {}                         # drop every narration
    with pytest.raises(ValueError):
        validate_published(slim, narr)


def test_validate_published_rejects_full_snapshot():
    # a full (non-slim) snapshot has no narrations_file pointer → rejected
    snap = snapshot_for({"AAA": synth.fixture1()})
    with pytest.raises(ValueError):
        validate_published(snap, {"narrations": {}})


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


def test_chart_writer_skips_windows_reserved_names(tmp_path):
    """PRN.json (Perenti) broke every Windows checkout — never write reserved
    device-name files again. NOTE: assert via listdir, not Path.exists() —
    on Windows, exists('PRN.json') answers for the printer DEVICE and lies."""
    import os
    import pandas as pd
    from phasemap.run import write_chart_json
    df = pd.DataFrame({"Date": ["2026-07-01"], "Open": [1.0], "High": [1.1],
                       "Low": [0.9], "Close": [1.05], "Volume": [1000]})
    for bad in ("PRN", "CON", "AUX", "NUL", "COM1", "LPT9"):
        write_chart_json(str(tmp_path), bad, df)
    assert os.listdir(tmp_path) == []          # nothing written for reserved names
    write_chart_json(str(tmp_path), "BHP", df)
    assert os.listdir(tmp_path) == ["BHP.json"]


# ── publish-pair discipline (2026-07-20 Phase 4, review H5) ────────────────────

def test_write_order_sidecar_before_latest(tmp_path, monkeypatch):
    """narrations.json must land BEFORE latest.json: latest is the entry point
    readers key off, so when a new latest appears its sidecar already exists."""
    import os
    from phasemap.output import writer as w
    calls, real = [], w._atomic_write

    def spy(path, payload):
        calls.append(os.path.basename(path))
        real(path, payload)

    monkeypatch.setattr(w, "_atomic_write", spy)
    w.write_snapshot(snapshot_for({"AAA": synth.fixture1()}), str(tmp_path))
    assert calls.index("narrations.json") < calls.index("latest.json")


def test_broken_pair_never_touches_disk(tmp_path, monkeypatch):
    """Regression guard: if split/validation ever diverge, write_snapshot must
    abort BEFORE any published file is replaced (validate_published up front)."""
    from phasemap.output import writer as w
    monkeypatch.setattr(w, "split_narrations",
                        lambda s: ({"run_date": "x"}, {"narrations": {}}))
    with pytest.raises(ValueError):
        w.write_snapshot(snapshot_for({"AAA": synth.fixture1()}), str(tmp_path))
    assert list(tmp_path.iterdir()) == []          # nothing written at all
