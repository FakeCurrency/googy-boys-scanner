"""Sector cache (Fix-10 #10, 2026-07-26) — target selection + cache I/O.

Network fetches are NOT tested (best-effort path); these pin the pure logic:
missing-only selection, best-grade-first ordering, the per-run cap, and the
atomic dual-file write.

SINCE 2026-07-28 THIS IS A SIGNAL PATH (owner-authorised — REFINEMENTS #38).
vivek_run merges the cache into the rows decide() sees, so the 3-per-sector
correlation cap finally binds on NASDAQ, whose universe file carries no sectors
at all. A wrong sector here now changes which trades get taken. The
sector_map_for / enrich_rows tests at the bottom cover that wiring; the rule
they enforce is that enrichment only ever WRITES INTO A BLANK FIELD.
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


def test_scan_symbols_puts_open_positions_ahead_of_everything(tmp_path, monkeypatch):
    """A HELD sector-less name is the worst one to leave uncovered.

    It occupies a slot but is exempt from the per-sector cap it should be
    filling, and before this it was invisible to the fetch list entirely — the
    list was built from scan results only, so a holding that had dropped out of
    the scan could never get a sector. Three NASDAQ positions were in exactly
    that state.
    """
    monkeypatch.setattr(sectorcache, "ROOT", tmp_path)
    monkeypatch.setattr(sectorcache, "_SCAN_FILES", [("nasdaq", "x_vivek.json")])
    (tmp_path / "x_vivek.json").write_text(json.dumps(
        {"results": [{"symbol": "NVDA", "grade": "A+"}]}))
    (tmp_path / "journal").mkdir()
    (tmp_path / "journal" / "vivek_bot_book.json").write_text(json.dumps({"open": [
        {"symbol": "MDB", "market": "nasdaq"},                      # held, no sector
        {"symbol": "AAPL", "market": "nasdaq", "sector": "Technology"},   # already has one
        {"symbol": "XLM", "market": "crypto"},                      # no scan file -> skipped
        {"symbol": "NVDA", "market": "nasdaq"},                     # also in the scan
    ]}))
    got = sectorcache._scan_symbols()
    assert got[0] == (-1, "nasdaq", "MDB")          # rank -1 beats every scan grade
    assert (-1, "nasdaq", "NVDA") in got            # book entry wins the dedupe...
    assert (0, "nasdaq", "NVDA") not in got         # ...and the scan row is not doubled
    assert all(s != "AAPL" for _, _, s in got)
    assert all(m != "crypto" for _, m, _ in got)


def test_scan_symbols_survives_a_corrupt_book(tmp_path, monkeypatch):
    monkeypatch.setattr(sectorcache, "ROOT", tmp_path)
    monkeypatch.setattr(sectorcache, "_SCAN_FILES", [("nasdaq", "x_vivek.json")])
    (tmp_path / "x_vivek.json").write_text(json.dumps(
        {"results": [{"symbol": "NVDA", "grade": "A+"}]}))
    (tmp_path / "journal").mkdir()
    (tmp_path / "journal" / "vivek_bot_book.json").write_text("{ truncated")
    assert sectorcache._scan_symbols() == [(0, "nasdaq", "NVDA")]


# ── the signal path: cache -> the rows decide() sees ─────────────────────────

CACHE = {
    "nasdaq:AAPL": {"sector": "Technology", "ts": "t"},
    "nasdaq:MDB": {"sector": "Technology", "ts": "t"},
    "nasdaq:BROKE": {"sector": "", "ts": "t"},       # failed fetch
    "asx:BHP": {"sector": "Materials", "ts": "t"},
}


def test_sector_map_for_is_per_market_and_upper_cased():
    m = sectorcache.sector_map_for("nasdaq", CACHE)
    assert m == {"AAPL": "Technology", "MDB": "Technology"}
    assert sectorcache.sector_map_for("asx", CACHE) == {"BHP": "Materials"}
    # A blank sector is dropped, not returned as "" — callers treat "present"
    # as "usable", and a key mapping to "" would read as a hit that fills
    # nothing.
    assert "BROKE" not in m


def test_sector_map_for_unknown_market_is_empty():
    assert sectorcache.sector_map_for("crypto", CACHE) == {}


def test_enrich_rows_fills_only_blank_sectors():
    rows = [{"symbol": "AAPL"},                              # blank -> filled
            {"symbol": "MDB", "sector": ""},                 # blank -> filled
            {"symbol": "NVDA"},                              # not in cache -> left
            {"symbol": "BHP", "sector": "Materials"}]        # already set -> untouched
    assert sectorcache.enrich_rows(rows, "nasdaq", CACHE) == 2
    assert rows[0]["sector"] == "Technology"
    assert rows[1]["sector"] == "Technology"
    assert "sector" not in rows[2]
    assert rows[3]["sector"] == "Materials"


def test_a_sector_shipped_with_the_universe_always_wins_over_the_cache():
    # ASX ships GICS sectors on the universe rows; the cache is best-effort
    # Yahoo data. If the two ever disagree the universe is the better source,
    # and silently overwriting it would change which trades get taken.
    rows = [{"symbol": "BHP", "sector": "Metals & Mining"}]
    assert sectorcache.enrich_rows(rows, "asx", CACHE) == 0
    assert rows[0]["sector"] == "Metals & Mining"


def test_enrich_rows_degrades_to_a_no_op_rather_than_clearing_sectors():
    # An empty/absent cache must leave everything exactly as it was — the
    # failure mode to avoid is blanking sectors that were already right, which
    # would silently switch the per-sector cap OFF for those rows.
    rows = [{"symbol": "BHP", "sector": "Materials"}, {"symbol": "AAPL"}]
    assert sectorcache.enrich_rows(rows, "nasdaq", {}) == 0
    assert sectorcache.enrich_rows(rows, "crypto", CACHE) == 0
    assert sectorcache.enrich_rows([], "nasdaq", CACHE) == 0
    assert sectorcache.enrich_rows(rows, "", CACHE) == 0
    assert rows == [{"symbol": "BHP", "sector": "Materials"}, {"symbol": "AAPL"}]


def test_enriched_rows_make_the_sector_cap_bind():
    """End to end, because this is the whole point of REFINEMENTS #38.

    Same four NASDAQ setups, all Technology. Un-enriched they are exempt from
    the correlation cap and all four get taken; enriched, three get in.
    """
    from scanner.broker import vivek_bot as vb

    def _rows():
        return [{"symbol": s, "dir": "LONG", "grade": "A+", "price": 100.0,
                 "entry_types": ["reclaim"],
                 "plans": {"1W": {"armed": True, "entry_trigger": "reclaim",
                                  "entry": 100.0, "stop": 96.0, "tp1": 106.0,
                                  "tp2": 112.0, "tp3": 120.0, "rr": 3.0,
                                  "scale": [0.25, 0.50, 0.15]}}}
                for s in ("AAPL", "MDB", "MSFT", "NVDA")]

    blind = vb.decide(_rows(), equity=150_000, market="nasdaq", open_book=[])
    assert len(blind["plans"]) == 4                       # today's bug, pinned
    assert blind["summary"]["sector_coverage"] == 0.0

    rows = _rows()
    cache = {f"nasdaq:{s}": {"sector": "Technology", "ts": "t"}
             for s in ("AAPL", "MDB", "MSFT", "NVDA")}
    assert sectorcache.enrich_rows(rows, "nasdaq", cache) == 4
    seeing = vb.decide(rows, equity=150_000, market="nasdaq", open_book=[])
    assert len(seeing["plans"]) == 3
    assert seeing["summary"]["skip_reasons"]["sector_cap"] == 1
    assert seeing["summary"]["sector_coverage"] == 1.0


# ── the other failure: a sector that is present but from the wrong taxonomy ──

def test_diverging_reports_a_taxonomy_split_it_must_not_repair():
    """The live case, pinned. Both are financials; the cap sees three buckets.

    SUN/AFG were opened carrying Yahoo-style labels; the ASX universe ships
    GICS and says 'Financials' for the same two symbols. Left alone, the cap
    permits 3 Financials + 3 Insurance + 3 Financial Services. Repairing it
    changes which trades get taken, so this function REPORTS and stops.
    """
    positions = [{"symbol": "SUN", "sector": "Insurance"},
                 {"symbol": "AFG", "sector": "Financial Services"},
                 {"symbol": "CCP", "sector": "Financials"}]
    rows = [{"symbol": s, "sector": "Financials"} for s in ("SUN", "AFG", "CCP")]
    assert sectorcache.diverging(positions, rows) == [
        "AFG=Financial Services->Financials", "SUN=Insurance->Financials"]
    # and nothing was touched
    assert positions[0]["sector"] == "Insurance"


def test_diverging_is_silent_about_blanks_and_absences():
    # A blank is enrich_rows' job — reporting it here would double-count the
    # same row as both "needs filling" and "disagrees".
    rows = [{"symbol": "CCP", "sector": "Financials"}]
    assert sectorcache.diverging([{"symbol": "CCP"}], rows) == []
    assert sectorcache.diverging([{"symbol": "CCP", "sector": ""}], rows) == []
    # A holding this scan does not list cannot be compared against anything.
    assert sectorcache.diverging([{"symbol": "XYZ", "sector": "Utilities"}], rows) == []
    # A scan row with no sector of its own is not evidence of disagreement.
    assert sectorcache.diverging([{"symbol": "CCP", "sector": "Financials"}],
                                 [{"symbol": "CCP", "sector": ""}]) == []
    assert sectorcache.diverging([], rows) == []
    assert sectorcache.diverging([{"symbol": "CCP", "sector": "X"}], []) == []


def test_diverging_matches_case_insensitively():
    assert sectorcache.diverging([{"symbol": "ccp", "sector": "Insurance"}],
                                 [{"symbol": "CCP", "sector": "Financials"}]) == [
        "CCP=Insurance->Financials"]


def test_global_sector_load_sees_what_the_per_market_cap_cannot():
    """The live shape of REFINEMENTS #113.

    Three ASX financials and three NASDAQ financials pass every per-market
    check — decide() is handed one market's slice — while the book holds six
    of one real sector against a 30-position ceiling that IS global.
    """
    book = ([{"symbol": f"A{i}", "market": "asx", "sector": "Financials"}
             for i in range(3)]
            + [{"symbol": f"N{i}", "market": "nasdaq", "sector": "Financials"}
               for i in range(3)]
            + [{"symbol": "AIA", "market": "asx", "sector": "Industrials"}])
    assert sectorcache.global_sector_load(book, 3) == ["Financials=6(asx+nasdaq)"]
    # At the cap is not over it — the report must not cry wolf on a legal book.
    assert sectorcache.global_sector_load(book[:3] + book[6:], 3) == []


def test_global_sector_load_is_off_unless_a_cap_is_given():
    # cap<=0 means "no correlation cap configured"; reporting breaches of a
    # limit that does not exist would be noise on every single scan.
    book = [{"symbol": "X", "market": "asx", "sector": "Financials"}] * 9
    assert sectorcache.global_sector_load(book, 0) == []
    assert sectorcache.global_sector_load([], 3) == []


def test_global_sector_load_skips_what_the_cap_skips():
    """Blanks are exempt from the cap, so they must not appear in its report.

    Crypto's synthetic crypto-major/crypto-alt buckets are per-market by
    construction and cannot collide with an equity sector name, so they are
    simply absent here rather than special-cased.
    """
    book = ([{"symbol": f"B{i}", "market": "nasdaq", "sector": ""} for i in range(9)]
            + [{"symbol": f"C{i}", "market": "crypto"} for i in range(9)])
    assert sectorcache.global_sector_load(book, 3) == []


def test_global_sector_load_folds_case_like_the_cap_does():
    # _sector_key lowercases before bucketing, so "Financials"/"financials" are
    # ONE bucket to the cap and must be one bucket in the report too.
    book = ([{"symbol": "A", "market": "asx", "sector": "Financials"}] * 2
            + [{"symbol": "N", "market": "nasdaq", "sector": "financials"}] * 2)
    out = sectorcache.global_sector_load(book, 3)
    assert len(out) == 1 and out[0].startswith("Financials=4(")


def test_global_sector_load_reports_worst_first():
    book = ([{"symbol": "A", "market": "asx", "sector": "Materials"}] * 7
            + [{"symbol": "N", "market": "nasdaq", "sector": "Technology"}] * 5
            + [{"symbol": "E", "market": "asx", "sector": "Energy"}] * 2)
    out = sectorcache.global_sector_load(book, 3)
    assert [s.split("=")[0] for s in out] == ["Materials", "Technology"]


def test_yf_symbol_suffix():
    assert sectorcache._yf_symbol("asx", "BHP") == "BHP.AX"
    assert sectorcache._yf_symbol("nasdaq", "NVDA") == "NVDA"
