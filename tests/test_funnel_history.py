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

def test_the_row_is_the_five_owner_named_counts_plus_the_trigger():
    row = fh.row_from(_vk())
    assert row == {"t": "2026-07-30T12:40:24+10:00", "scanned": 2212,
                   "with_data": 2120, "published": 328, "floor_killed": 299,
                   "arriving": 9, "trigger": ""}


def test_missing_and_non_numeric_fields_read_zero_not_crash():
    row = fh.row_from({"scanned": None, "funnel": {"setups": "x"}})
    assert (row["scanned"], row["published"], row["arriving"]) == (0, 0, 0)
    assert fh.row_from({})["with_data"] == 0


# ── the trigger stamp (2026-08-20) ───────────────────────────────────────────

def test_the_trigger_is_recorded_and_junk_is_an_honest_blank():
    assert fh.row_from(_vk(), "cron")["trigger"] == "cron"
    assert fh.row_from(_vk(), "manual")["trigger"] == "manual"
    assert fh.row_from(_vk(), "heartbeat")["trigger"] == "heartbeat"
    assert fh.row_from(_vk(), " CRON ")["trigger"] == "cron"       # workflow-side whitespace/case
    assert fh.row_from(_vk(), "push")["trigger"] == ""              # never a guess
    assert fh.row_from(_vk(), None)["trigger"] == ""


def test_trigger_from_env_reads_and_validates_SCAN_TRIGGER(monkeypatch):
    for val, want in (("cron", "cron"), ("manual", "manual"),
                      ("heartbeat", "heartbeat"), ("Heartbeat", "heartbeat"),
                      ("bogus", ""), ("", "")):
        monkeypatch.setenv("SCAN_TRIGGER", val)
        assert fh.trigger_from_env() == want, val
    monkeypatch.delenv("SCAN_TRIGGER")
    assert fh.trigger_from_env() == ""      # a local run records unknown, not a guess


def test_the_trigger_round_trips_through_append_for_cron_and_manual(tmp_path):
    fh.append("asx", _vk(ts="2026-08-20T01:00:00+00:00"), tmp_path, trigger="cron")
    fh.append("asx", _vk(ts="2026-08-20T02:00:00+00:00"), tmp_path, trigger="manual")
    fh.append("asx", _vk(ts="2026-08-20T03:00:00+00:00"), tmp_path, trigger="heartbeat")
    d = json.loads((tmp_path / "funnel_history.json").read_text())
    assert d["markets"]["asx"]["trigger"] == ["cron", "manual", "heartbeat"]


def test_a_pre_trigger_file_is_PADDED_not_wiped(tmp_path):
    # THE MIGRATION CASE, and the reason it is tested first against the shipped
    # append(): a legacy file has full-length numeric columns and NO trigger
    # array. The truncate-to-shortest corruption guard would read the new
    # 1-long trigger column as "the shortest" and silently WIPE hundreds of
    # rows of history on the first post-upgrade scan.
    for ts in ("T01", "T02", "T03"):
        fh.append("asx", _vk(ts=f"2026-08-19{ts}:00:00+00:00"), tmp_path, trigger="cron")
    p = tmp_path / "funnel_history.json"
    d = json.loads(p.read_text())
    del d["markets"]["asx"]["trigger"]                 # simulate the pre-2026-08-20 file
    p.write_text(json.dumps(d), encoding="utf-8")

    fh.append("asx", _vk(ts="2026-08-20T01:00:00+00:00"), tmp_path, trigger="manual")
    d = json.loads(p.read_text())
    a = d["markets"]["asx"]
    assert len(a["t"]) == 4, "history must survive the schema migration intact"
    assert a["trigger"] == ["", "", "", "manual"], "old rows read unknown, never a guess"


def test_run_py_passes_the_env_derived_trigger():
    src = (ROOT / "scanner" / "run.py").read_text(encoding="utf-8")
    assert "trigger=funnelhistory.trigger_from_env()" in src


def test_the_workflows_set_SCAN_TRIGGER_and_scan_yml_declares_reason():
    scan = (ROOT / ".github" / "workflows" / "scan.yml").read_text(encoding="utf-8")
    crypto = (ROOT / ".github" / "workflows" / "crypto_bot.yml").read_text(encoding="utf-8")
    hb = (ROOT / "functions" / "api" / "heartbeat.js").read_text(encoding="utf-8")
    # scan.yml: cron for schedule fires, heartbeat when the healer said so,
    # manual otherwise — and the `reason` input must be DECLARED or GitHub
    # rejects the healer's dispatch outright (422), breaking the heal path.
    assert "SCAN_TRIGGER:" in scan and "'cron'" in scan and "'heartbeat'" in scan
    assert "reason:" in scan
    assert "SCAN_TRIGGER:" in crypto
    assert 'reason: "heartbeat"' in hb


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
    call = src.index("funnelhistory.append(market_key, vk, args.out,")
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


# The reader list WIDENED 2026-08-19 (STATUS control, Session 1) from one file
# to an explicit two, and the property being gated changed with it. The rule was
# never "one reader" for its own sake — it is that this 33 KB artefact must not
# ride every page load, and that two surfaces must not draw the same trend and
# disagree. status.js reads a different COLUMN for a different question (`t` as
# the ledger of successful scan publishes, for per-market age and the uptime
# figure) and draws no trend at all, so the second concern does not arise; the
# first is preserved by the laziness assertion below, which is now the load-
# bearing half. A THIRD reader still fails this test: add one only with the same
# argument written down, not by extending the list.
#
# Both tests below discover the readers ON DISK rather than asserting a fixed
# set exists. That is deliberate and not laziness: the allowlist is what gates a
# NEW reader, and the laziness rule should apply to whatever readers are
# actually shipped. It also means neither test has an opinion about the ORDER
# two commits land in — a directory-at-a-time landing route cannot co-commit a
# public/js file with a tests/ file, and a pin that goes red in between is a
# failure email about a state nobody chose.
_FUNNEL_READERS = {"app.js", "status.js"}


def _shipped_readers():
    """Every public/js file that fetches the history, by filename."""
    return sorted(p.name for p in ROOT.glob("public/js/*.js")
                  if '"data/funnel_history.json"' in p.read_text(encoding="utf-8"))


def test_only_the_named_surfaces_read_the_history():
    others = [n for n in _shipped_readers() if n not in _FUNNEL_READERS]
    assert others == [], f"a new reader of the funnel history appeared: {others}"


def test_the_deck_is_still_one_of_them():
    """Guards the guard: a regex that matched nothing would make both tests vacuous."""
    assert "app.js" in _shipped_readers(), "the deck no longer fetches the history"


def test_every_reader_fetches_it_lazily_never_at_page_load():
    """The 33 KB must be paid for by a tap, not by opening a page.

    Both readers gate the fetch behind a user action - the deck's funnel
    disclosure opening, and the status sheet opening - so a phone loading the
    dashboard downloads none of it. A reader that fetched at module scope
    would put a third of a megabyte on every navigation across 14 pages.
    """
    for name in _shipped_readers():
        src = (ROOT / "public" / "js" / name).read_text(encoding="utf-8")
        # The QUOTED path - the fetch argument. Both files also NAME the file in
        # prose (status.js cites it in its header as the uptime evidence), and
        # locating the first bare mention would measure the comment, not the
        # code: the Tier 3 "ask about code, read code" trap in miniature.
        at = src.index('"data/funnel_history.json"')
        head = src[:at]
        assert head.count("function ") + head.count("=> {") > 0, (
            f"{name} appears to fetch the history at module scope")
