"""Funnel history (owner-ruled Task 2) — the append-only trend artefact.

Three families, and the fence tests are the ones that matter most:

  1. The row is DERIVED from the published payload — the history can never
     disagree with the funnel summary the deck shows for the same scan.
  2. Append mechanics: columnar shape, per-market cap, corrupt-file recovery,
     unequal-column truncation — a report file must degrade to nothing, never
     take a scan down or publish rows whose timestamp belongs to another
     scan's counts.
  3. THE FENCE, both directions: the module is imported by run.py alone, and
     nothing in scanner/broker reads the file back. "Nothing in this series
     may be read back into the scanner, bot, or any decision path" is the
     owner's ruling verbatim; these tests are what keeps it true after
     everyone forgets.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from scanner import config, funnelhistory as fh

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _vk(scanned=2212, with_data=2120, setups=328, illiquid=299, arriving=9,
        ts="2026-07-30T12:40:24+10:00"):
    return {"scanned": scanned, "generated_at": ts,
            "funnel": {"with_data": with_data, "setups": setups,
                       "illiquid_setup": illiquid, "arriving": arriving}}


# ── the row derives from the payload ─────────────────────────────────────────

def test_the_row_is_exactly_the_five_owner_named_counts():
    row = fh.row_from(_vk())
    assert row == {"t": "2026-07-30T12:40:24+10:00", "scanned": 2212,
                   "with_data": 2120, "published": 328, "floor_killed": 299,
                   "arriving": 9}


def test_missing_and_non_numeric_fields_read_zero_not_crash():
    row = fh.row_from({"scanned": None, "funnel": {"setups": "x"}})
    assert (row["scanned"], row["published"], row["arriving"]) == (0, 0, 0)
    assert fh.row_from({})["with_data"] == 0


# ── append mechanics ─────────────────────────────────────────────────────────

def test_append_creates_the_columnar_file_and_rows_accumulate(tmp_path):
    fh.append("asx", _vk(ts="2026-07-30T01:00:00+00:00"), tmp_path)
    fh.append("asx", _vk(setups=330, ts="2026-07-30T02:00:00+00:00"), tmp_path)
    fh.append("crypto", _vk(scanned=104, ts="2026-07-30T02:05:00+00:00"), tmp_path)
    d = json.loads((tmp_path / "funnel_history.json").read_text())
    a = d["markets"]["asx"]
    assert a["t"] == ["2026-07-30T01:00:00+00:00", "2026-07-30T02:00:00+00:00"]
    assert a["published"] == [328, 330]
    assert d["markets"]["crypto"]["scanned"] == [104]
    assert d["updated_at"] == "2026-07-30T02:05:00+00:00"
    for c in ("t", "scanned", "with_data", "published", "floor_killed", "arriving"):
        assert len(a[c]) == 2, c


def test_the_cap_trims_the_oldest_rows_per_market(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCAN_FUNNEL_HISTORY_MAX", 3, raising=False)
    for i in range(5):
        fh.append("asx", _vk(setups=i, ts=f"2026-07-{25 + i:02d}T01:00:00+00:00"), tmp_path)
    a = json.loads((tmp_path / "funnel_history.json").read_text())["markets"]["asx"]
    assert a["published"] == [2, 3, 4]          # newest three
    assert len(a["t"]) == 3


def test_a_corrupt_file_starts_fresh_instead_of_raising(tmp_path):
    (tmp_path / "funnel_history.json").write_text("{not json", encoding="utf-8")
    fh.append("asx", _vk(), tmp_path)           # must not raise
    d = json.loads((tmp_path / "funnel_history.json").read_text())
    assert d["markets"]["asx"]["published"] == [328]


def test_unequal_columns_are_truncated_so_the_arrays_always_zip(tmp_path):
    (tmp_path / "funnel_history.json").write_text(json.dumps({
        "schema_version": 1, "updated_at": "",
        "markets": {"asx": {"t": ["a", "b"], "scanned": [1],  # broken tail
                            "with_data": [1], "published": [1],
                            "floor_killed": [1], "arriving": [1]}}}))
    fh.append("asx", _vk(), tmp_path)
    a = json.loads((tmp_path / "funnel_history.json").read_text())["markets"]["asx"]
    lengths = {c: len(a[c]) for c in ("t", "scanned", "with_data", "published",
                                      "floor_killed", "arriving")}
    assert len(set(lengths.values())) == 1, lengths


def test_append_never_rewrites_earlier_rows(tmp_path):
    fh.append("asx", _vk(setups=100, ts="t1"), tmp_path)
    before = json.loads((tmp_path / "funnel_history.json").read_text())
    fh.append("asx", _vk(setups=200, ts="t2"), tmp_path)
    after = json.loads((tmp_path / "funnel_history.json").read_text())
    assert after["markets"]["asx"]["published"][0] == \
        before["markets"]["asx"]["published"][0] == 100


# ── THE FENCE — the owner's ruling, pinned in both directions ────────────────

def test_fence_1_the_module_is_imported_by_run_py_alone():
    # Match the IMPORT, not the word — config.py legitimately NAMES the module
    # in the constant's comment, and prose is not a leak. An import is.
    import re
    importers = []
    for p in sorted(ROOT.glob("scanner/**/*.py")):
        if p.name == "funnelhistory.py":
            continue
        if re.search(r"import\s+funnelhistory", p.read_text(encoding="utf-8")):
            importers.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    assert importers == ["scanner/run.py"], (
        f"funnelhistory must be reachable from run.py's report path alone, found: {importers}")
    for p in sorted(ROOT.glob("scanner/broker/*.py")):
        text = p.read_text(encoding="utf-8")
        assert "funnelhistory" not in text and "funnel_history" not in text, (
            f"{p.name}: the bot must not know the funnel history exists")


def test_fence_2_nothing_in_scanner_or_broker_reads_the_file_back():
    # The writer module and the config constant are the only scanner-side
    # mentions of the artefact's name. scan.py, the bot, the paper book and
    # every broker module must not know it exists.
    allowed = {"scanner/config.py", "scanner/funnelhistory.py"}
    hits = []
    for p in sorted(ROOT.glob("scanner/**/*.py")):
        if "funnel_history" in p.read_text(encoding="utf-8"):
            rel = str(p.relative_to(ROOT)).replace("\\", "/")
            if rel not in allowed:
                hits.append(rel)
    assert hits == [], f"funnel_history.json leaked toward a decision path: {hits}"


def test_fence_3_run_py_appends_after_the_publish_not_before():
    src = (ROOT / "scanner" / "run.py").read_text(encoding="utf-8")
    publish = src.index("output.write_vivek_pair(vk, args.out, market_key)")
    call = src.index("funnelhistory.append(market_key, vk, args.out)")
    assert call > publish, (
        "the history must record what was PUBLISHED - append after the publish")


def test_fence_4_the_report_call_cannot_kill_the_scan():
    src = (ROOT / "scanner" / "run.py").read_text(encoding="utf-8")
    at = src.index("funnelhistory.append")
    window = src[max(0, at - 400):at]
    assert "try:" in window, "the append must sit under a narrow try - report-only"


def test_the_staging_lists_carry_the_artefact():
    scan = (ROOT / ".github" / "workflows" / "scan.yml").read_text(encoding="utf-8")
    crypto = (ROOT / ".github" / "workflows" / "crypto_bot.yml").read_text(encoding="utf-8")
    assert "public/data/funnel_history.json" in scan.split('SHARED="', 1)[1].split('"', 1)[0], \
        "scan.yml must stage the SHARED funnel history or non-staged runs revert it"
    assert "public/data/funnel_history.json" in crypto, \
        "crypto_bot.yml writes the crypto rows and must stage the file"


def test_the_deck_reads_it_lazily_and_only_the_deck():
    app = (ROOT / "public" / "js" / "app.js").read_text(encoding="utf-8")
    assert "data/funnel_history.json" in app
    others = [p for p in sorted(ROOT.glob("public/js/*.js"))
              if p.name != "app.js" and "funnel_history" in p.read_text(encoding="utf-8")]
    assert others == [], f"only the deck's funnel disclosure renders the trend: {others}"
