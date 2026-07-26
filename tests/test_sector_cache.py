"""Sector cache (Fix-10 #10, 2026-07-26) — target selection + cache I/O.

Network fetches are NOT tested (best-effort path); these pin the pure logic:
missing-only selection, best-grade-first ordering, the per-run cap, and the
atomic dual-file write.
"""

import json

import pytest

from scanner import sectorcache


@pytest.fixture()
def cache_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(sectorcache, "CACHE_FILE", tmp_path / "sector_map.json")
    monkeypatch.setattr(sectorcache, "PUBLIC_FILE", tmp_path / "public_sector_map.json")
    return tmp_path


def test_cache_roundtrip_writes_both_files(cache_paths):
    sectorcache.save_cache({"nasdaq:AAPL": {"sector": "Technology", "ts": "t"}})
    assert sectorcache.load_cache()["nasdaq:AAPL"]["sector"] == "Technology"
    assert json.loads((cache_paths / "public_sector_map.json").read_text())["nasdaq:AAPL"]["sector"] == "Technology"


def test_corrupt_cache_loads_empty(cache_paths):
    (cache_paths / "sector_map.json").write_text("{broken")
    assert sectorcache.load_cache() == {}


def test_targets_skip_already_cached():
    symbols = [(0, "nasdaq", "AAPL"), (0, "nasdaq", "NVDA")]
    cache = {"nasdaq:AAPL": {"sector": "Technology", "ts": "t"}}
    assert sectorcache._targets(symbols, cache, 40) == [("nasdaq", "NVDA")]


def test_targets_best_grade_first_and_capped():
    symbols = [(3, "nasdaq", "WWW"), (0, "nasdaq", "AAA"), (1, "nasdaq", "BBB"), (2, "nasdaq", "CCC")]
    assert sectorcache._targets(symbols, {}, 2) == [("nasdaq", "AAA"), ("nasdaq", "BBB")]


def test_targets_empty_sector_entry_refetches():
    # an entry that failed before (empty sector) must be retried, not skipped
    cache = {"nasdaq:AAPL": {"sector": "", "ts": "t"}}
    assert sectorcache._targets([(0, "nasdaq", "AAPL")], cache, 40) == [("nasdaq", "AAPL")]


def test_scan_symbols_only_sectorless(tmp_path, monkeypatch):
    scan = {"results": [
        {"symbol": "BHP", "grade": "A+", "sector": "Materials"},   # has sector -> excluded
        {"symbol": "NVDA", "grade": "A+", "sector": ""},
        {"symbol": "AAPL", "grade": "WATCH"},                       # missing key counts as sectorless
    ]}
    p = tmp_path / "x_vivek.json"
    p.write_text(json.dumps(scan))
    monkeypatch.setattr(sectorcache, "ROOT", tmp_path)
    monkeypatch.setattr(sectorcache, "_SCAN_FILES", [("nasdaq", "x_vivek.json")])
    got = sectorcache._scan_symbols()
    assert (0, "nasdaq", "NVDA") in got
    assert (3, "nasdaq", "AAPL") in got
    assert all(s != "BHP" for _, _, s in got)


def test_yf_symbol_suffix():
    assert sectorcache._yf_symbol("asx", "BHP") == "BHP.AX"
    assert sectorcache._yf_symbol("nasdaq", "NVDA") == "NVDA"
