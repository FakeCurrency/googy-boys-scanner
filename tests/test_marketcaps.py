"""scanner/marketcaps.py -- REFINE200 #157.

The refresh covered only the previous scan's A+/A, so the deck showed caps up
to 112 days old on B+/WATCH rows (600 of 1,605 cached entries were over 30
days). It now refreshes every published row whose cap is missing or stale,
best grades first, capped per run, both markets in ONE batched fetch.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from scanner import config, marketcaps as mc

NOW = dt.datetime(2026, 10, 14, 6, 0, tzinfo=dt.timezone.utc)


def _ts(days_ago):
    return (NOW - dt.timedelta(days=days_ago)).isoformat(timespec="seconds")


def test_targets_are_every_missing_or_stale_row_best_grade_first():
    rows = {"asx": {"FRESH": 0, "WATCHY": 3, "BPLUS": 2},
            "nasdaq": {"VRTX": 0, "NEW": 0}}
    cache = {"asx:FRESH": {"mcap": 1, "ts": _ts(1)},
             "asx:BPLUS": {"mcap": 1, "ts": _ts(10)},
             "nasdaq:VRTX": {"mcap": 1, "ts": _ts(112)}}
    got = mc.refresh_targets(rows, cache, NOW, limit=10)
    assert got == [("nasdaq", "NEW"),      # A-grade, never fetched
                   ("nasdaq", "VRTX"),     # A-grade, 112 days old
                   ("asx", "BPLUS"),       # B+, 10 days old
                   ("asx", "WATCHY")]      # WATCH, never fetched
    assert ("asx", "FRESH") not in got, "a fresh cap is not re-fetched"


def test_the_per_run_cap_keeps_the_best_and_the_cap_is_config():
    rows = {"asx": {f"S{i}": 3 for i in range(50)} | {"TOP": 0}}
    got = mc.refresh_targets(rows, {}, NOW, limit=5)
    assert len(got) == 5 and got[0] == ("asx", "TOP")
    assert config.MARKETCAP_REFRESH_MAX >= 100
    assert len(mc.refresh_targets(rows, {}, NOW)) == min(51, config.MARKETCAP_REFRESH_MAX)


def test_all_mode_refreshes_fresh_caps_too_but_stays_capped():
    rows = {"asx": {"A": 0}}
    cache = {"asx:A": {"mcap": 1, "ts": _ts(0)}}
    assert mc.refresh_targets(rows, cache, NOW) == []
    assert mc.refresh_targets(rows, cache, NOW, only_stale=False) == [("asx", "A")]


@pytest.fixture
def files(tmp_path, monkeypatch):
    (tmp_path / "public" / "data").mkdir(parents=True)
    scans = {"asx": [{"symbol": "BHP", "grade": "B+"}, {"symbol": "RIO", "grade": "A+"}],
             "nasdaq": [{"symbol": "AXTI", "grade": "WATCH"}]}
    for m, res in scans.items():
        (tmp_path / "public" / "data" / f"{m}_vivek.json").write_text(
            json.dumps({"results": res}), encoding="utf-8")
    monkeypatch.setattr(mc, "ROOT", tmp_path)
    monkeypatch.setattr(mc, "CACHE_FILE", tmp_path / "data" / "market_caps.json")
    monkeypatch.setattr(mc, "PUBLIC_FILE", tmp_path / "public" / "data" / "market_caps.json")
    return tmp_path


def test_refresh_makes_one_batched_fetch_for_both_markets(files, monkeypatch, capsys):
    calls = []

    def fake(yf_syms):
        calls.append(sorted(yf_syms))
        return {"BHP.AX": 2.2e11, "AXTI": 3.1e8}           # RIO.AX missed
    monkeypatch.setattr(mc, "fetch_caps", fake)
    cache = mc.refresh()
    assert calls == [["AXTI", "BHP.AX", "RIO.AX"]], "one fetch, every published row"
    assert cache["asx:BHP"]["mcap"] == 2.2e11 and cache["nasdaq:AXTI"]["mcap"] == 3.1e8
    assert "asx:RIO" not in cache, "a miss never writes a placeholder"
    saved = json.loads((files / "data" / "market_caps.json").read_text(encoding="utf-8"))
    assert saved == cache
    capsys.readouterr().out.encode("ascii")


def test_refresh_with_nothing_due_fetches_nothing(files, monkeypatch):
    fresh = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    (files / "data").mkdir()
    (files / "data" / "market_caps.json").write_text(json.dumps(
        {k: {"mcap": 1.0, "ts": fresh} for k in ("asx:BHP", "asx:RIO", "nasdaq:AXTI")}))
    monkeypatch.setattr(mc, "fetch_caps", lambda s: pytest.fail("nothing is due"))
    mc.refresh()
