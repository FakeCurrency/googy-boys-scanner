"""Last-good universe cache (2026-07-26).

A flaky ASX directory fetch dropped a Saturday scan from ~2,000 names to the
94-name bundled CSV, silently. These tests pin the safety net that prevents
a repeat: successful full fetches snapshot to data/universe_cache/, degraded
lists are refused, and a failed directory fetch falls back to the snapshot
BEFORE the tiny bundled CSV.
"""

import json

import pytest

from scanner import universe


def _items(n, sector="Materials"):
    return [{"symbol": f"S{i}", "name": f"Name {i}", "sector": sector,
             "yf": f"S{i}.AX"} for i in range(n)]


@pytest.fixture()
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(universe, "UNIVERSE_CACHE_DIR", tmp_path)
    return tmp_path


def test_roundtrip_preserves_items_and_sector(cache_dir):
    universe._save_universe_cache("asx", _items(500))
    got = universe._load_universe_cache("asx")
    assert len(got) == 500
    assert got[0]["sector"] == "Materials"
    assert got[0]["yf"] == "S0.AX"


def test_degraded_list_is_never_cached(cache_dir):
    universe._save_universe_cache("asx", _items(90))     # the failure-mode size
    assert not (cache_dir / "asx.json").exists()
    assert universe._load_universe_cache("asx") == []


def test_undersized_cache_file_is_ignored_on_load(cache_dir):
    # A hand-edited/corrupt snapshot below the floor must not be trusted.
    (cache_dir / "asx.json").write_text(json.dumps({"items": _items(50)}))
    assert universe._load_universe_cache("asx") == []


def test_corrupt_cache_file_is_ignored(cache_dir):
    (cache_dir / "asx.json").write_text("{not json")
    assert universe._load_universe_cache("asx") == []


def test_crypto_floor_is_lower(cache_dir):
    universe._save_universe_cache("crypto", _items(60, sector=""))
    assert len(universe._load_universe_cache("crypto")) == 60


def test_failed_fetch_prefers_cache_over_bundled_csv(cache_dir, monkeypatch):
    universe._save_universe_cache("asx", _items(700))
    monkeypatch.setattr(universe, "_fetch_asx_listed", lambda suffix: [])
    got = universe.load_universe("asx", full=True)
    assert len(got) == 700                     # cache, not the ~94-name CSV
    assert got[0]["sector"] == "Materials"     # sector metadata rides along


def test_successful_fetch_snapshots_cache(cache_dir, monkeypatch):
    fresh = _items(800, sector="Energy")
    monkeypatch.setattr(universe, "_fetch_asx_listed", lambda suffix: fresh)
    got = universe.load_universe("asx", full=True)
    assert len(got) == 800
    cached = universe._load_universe_cache("asx")
    assert len(cached) == 800 and cached[0]["sector"] == "Energy"


def test_cache_ignored_when_fetch_succeeds(cache_dir, monkeypatch):
    universe._save_universe_cache("asx", _items(700, sector="Old"))
    fresh = _items(900, sector="New")
    monkeypatch.setattr(universe, "_fetch_asx_listed", lambda suffix: fresh)
    got = universe.load_universe("asx", full=True)
    assert len(got) == 900 and got[0]["sector"] == "New"
