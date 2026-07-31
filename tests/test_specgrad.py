"""Specs -> VIVEK graduation watch (owner-ruled, 2026-07-31).

Three families, same shape as the funnel-history suite one file over:

  1. Registry mechanics — who enters the watch, what graduates, and every
     way a report file can be broken degrading to "do less", never to an
     exception inside the nightly specs scan.
  2. The dates: every stamp comes from a payload's own ``generated_at``,
     graduation requires first_seen STRICTLY before the vivek payload's
     date, and a same-night re-run is idempotent.
  3. THE FENCE, both directions: imported by spec_run.py alone, read back by
     nothing in scanner/broker, displayed by specs.js alone. "Feeds nothing —
     no influence on grades, bot, or what is taken" is the owner's ruling
     verbatim; these tests are what keeps it true after everyone forgets.
"""
from __future__ import annotations

import json
import pathlib
import re

from scanner import config, output, specgrad

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _spec(results, ts="2026-07-30T20:44:21+10:00"):
    return {"generated_at": ts, "market": "asx", "setup_type": "spec",
            "results": results}


def _row(sym, price=0.058, name=None):
    return {"symbol": sym, "name": name or f"{sym} Ltd", "price": price,
            "grade": "A", "spike_ratio": 4.2}


def _write_vivek(tmp_path, syms, ts="2026-07-31T12:40:24+10:00", market="asx"):
    output.write_json(tmp_path / f"{market}_vivek.json", {
        "schema_version": 5, "market": market, "generated_at": ts,
        "results": [{"symbol": s, "price": 0.61, "grade": "B+",
                     "grade_raw": "B+"} for s in syms]})


def _reg(tmp_path):
    return json.loads((tmp_path / "spec_graduation.json").read_text(encoding="utf-8"))


# ── registry mechanics ───────────────────────────────────────────────────────

def test_a_new_spec_name_enters_the_watch_with_the_payload_date(tmp_path):
    specgrad.update("asx", tmp_path, _spec([_row("RHT")]))
    mk = _reg(tmp_path)["markets"]["asx"]
    assert mk["seen"]["RHT"]["first_seen"] == "2026-07-30"
    assert mk["seen"]["RHT"]["price"] == 0.058
    assert mk["seen"]["RHT"]["name"] == "RHT Ltd"
    assert mk["graduates"] == [] and mk["graduated_total"] == 0
    # the stamp is the payload's, never the wall clock
    assert _reg(tmp_path)["updated_at"] == "2026-07-30T20:44:21+10:00"


def test_a_name_vivek_already_publishes_is_never_watched(tmp_path):
    # Nothing to graduate INTO — Specs did not surface it first.
    _write_vivek(tmp_path, ["DUAL"], ts="2026-07-30T12:00:00+10:00")
    specgrad.update("asx", tmp_path, _spec([_row("DUAL"), _row("RHT")]))
    seen = _reg(tmp_path)["markets"]["asx"]["seen"]
    assert "DUAL" not in seen and "RHT" in seen


def test_resurfacing_keeps_first_seen_and_advances_last_seen(tmp_path):
    specgrad.update("asx", tmp_path, _spec([_row("RHT", price=0.058)],
                                           ts="2026-07-28T20:00:00+10:00"))
    specgrad.update("asx", tmp_path, _spec([_row("RHT", price=0.072)],
                                           ts="2026-07-30T20:00:00+10:00"))
    e = _reg(tmp_path)["markets"]["asx"]["seen"]["RHT"]
    assert e["first_seen"] == "2026-07-28"      # that date IS the record
    assert e["price"] == 0.058                  # price when first surfaced
    assert e["last_seen"] == "2026-07-30"


def test_graduation_records_the_crossing_and_unwatches_the_name(tmp_path):
    specgrad.update("asx", tmp_path, _spec([_row("RHT")],
                                           ts="2026-07-19T20:00:00+10:00"))
    _write_vivek(tmp_path, ["RHT"], ts="2026-07-31T12:40:24+10:00")
    specgrad.update("asx", tmp_path, _spec([], ts="2026-07-31T20:00:00+10:00"))
    mk = _reg(tmp_path)["markets"]["asx"]
    assert "RHT" not in mk["seen"]
    assert mk["graduated_total"] == 1
    (g,) = mk["graduates"]
    assert g == {"symbol": "RHT", "name": "RHT Ltd", "first_seen": "2026-07-19",
                 "spec_price": 0.058, "graduated": "2026-07-31",
                 "vivek_price": 0.61, "grade": "B+", "days": 12}


def test_a_same_day_joint_appearance_is_not_a_graduation(tmp_path):
    # STRICTLY before: "previously surfaced" must be true before "later
    # crossed" can be. A first_seen equal to the vivek date proves neither.
    specgrad.update("asx", tmp_path, _spec([_row("RHT")],
                                           ts="2026-07-31T20:00:00+10:00"))
    _write_vivek(tmp_path, ["RHT"], ts="2026-07-31T12:40:24+10:00")
    specgrad.update("asx", tmp_path, _spec([], ts="2026-07-31T20:05:00+10:00"))
    mk = _reg(tmp_path)["markets"]["asx"]
    assert mk["graduates"] == [] and "RHT" in mk["seen"]


def test_a_missing_vivek_artifact_means_no_graduations_not_a_crash(tmp_path):
    specgrad.update("asx", tmp_path, _spec([_row("RHT")]))
    mk = _reg(tmp_path)["markets"]["asx"]
    assert "RHT" in mk["seen"] and mk["graduates"] == []


def test_a_corrupt_registry_starts_fresh_instead_of_raising(tmp_path):
    (tmp_path / "spec_graduation.json").write_text("{not json", encoding="utf-8")
    specgrad.update("asx", tmp_path, _spec([_row("RHT")]))
    assert "RHT" in _reg(tmp_path)["markets"]["asx"]["seen"]


def test_a_shape_broken_market_block_degrades_to_empty_not_typeerror(tmp_path):
    output.write_json(tmp_path / "spec_graduation.json", {
        "schema_version": 1, "updated_at": "",
        "markets": {"asx": {"seen": ["not", "a", "dict"], "graduates": {},
                            "graduated_total": "three"}}})
    specgrad.update("asx", tmp_path, _spec([_row("RHT")]))
    mk = _reg(tmp_path)["markets"]["asx"]
    assert "RHT" in mk["seen"] and mk["graduates"] == [] and mk["graduated_total"] == 0


def test_a_same_night_rerun_is_idempotent(tmp_path):
    specgrad.update("asx", tmp_path, _spec([_row("RHT")],
                                           ts="2026-07-19T20:00:00+10:00"))
    _write_vivek(tmp_path, ["RHT"])
    payload = _spec([], ts="2026-07-31T20:00:00+10:00")
    specgrad.update("asx", tmp_path, payload)
    specgrad.update("asx", tmp_path, payload)   # the re-run
    mk = _reg(tmp_path)["markets"]["asx"]
    assert len(mk["graduates"]) == 1 and mk["graduated_total"] == 1


def test_a_fallen_angel_reenters_the_watch_and_can_graduate_again(tmp_path):
    specgrad.update("asx", tmp_path, _spec([_row("RHT")],
                                           ts="2026-06-01T20:00:00+10:00"))
    _write_vivek(tmp_path, ["RHT"], ts="2026-06-20T12:00:00+10:00")
    specgrad.update("asx", tmp_path, _spec([], ts="2026-06-20T20:00:00+10:00"))
    # back under 50c: Specs surfaces it again on a night vivek no longer has it
    _write_vivek(tmp_path, [], ts="2026-07-10T12:00:00+10:00")
    specgrad.update("asx", tmp_path, _spec([_row("RHT", price=0.31)],
                                           ts="2026-07-10T20:00:00+10:00"))
    _write_vivek(tmp_path, ["RHT"], ts="2026-07-31T12:00:00+10:00")
    specgrad.update("asx", tmp_path, _spec([], ts="2026-07-31T20:00:00+10:00"))
    mk = _reg(tmp_path)["markets"]["asx"]
    assert mk["graduated_total"] == 2
    assert [g["graduated"] for g in mk["graduates"]] == ["2026-06-20", "2026-07-31"]
    assert mk["graduates"][1]["first_seen"] == "2026-07-10"


def test_markets_are_independent(tmp_path):
    specgrad.update("asx", tmp_path, _spec([_row("RHT")]))
    specgrad.update("nasdaq", tmp_path, _spec([_row("SNDL", price=0.42)]))
    d = _reg(tmp_path)["markets"]
    assert set(d["asx"]["seen"]) == {"RHT"} and set(d["nasdaq"]["seen"]) == {"SNDL"}


def test_the_watch_cap_trims_the_oldest_first_seen(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SPEC_GRAD_SEEN_MAX", 3, raising=False)
    for i in range(5):
        specgrad.update("asx", tmp_path,
                        _spec([_row(f"S{i}")], ts=f"2026-07-{20 + i:02d}T20:00:00+10:00"))
    seen = _reg(tmp_path)["markets"]["asx"]["seen"]
    assert set(seen) == {"S2", "S3", "S4"}      # newest three survive


def test_the_graduates_cap_keeps_the_newest_and_the_lifetime_tally(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SPEC_GRAD_MAX", 2, raising=False)
    for i in range(4):
        specgrad.update("asx", tmp_path,
                        _spec([_row(f"S{i}")], ts=f"2026-07-{20 + i:02d}T20:00:00+10:00"))
        _write_vivek(tmp_path, [f"S{i}"], ts=f"2026-07-{24 + i:02d}T12:00:00+10:00")
        specgrad.update("asx", tmp_path, _spec([], ts=f"2026-07-{24 + i:02d}T20:00:00+10:00"))
    mk = _reg(tmp_path)["markets"]["asx"]
    assert mk["graduated_total"] == 4           # the tally survives the trim
    assert [g["symbol"] for g in mk["graduates"]] == ["S2", "S3"]


def test_update_never_mutates_the_spec_payload(tmp_path):
    # The payload is published evidence the caller keeps using.
    payload = _spec([_row("RHT")])
    frozen = json.dumps(payload, sort_keys=True)
    _write_vivek(tmp_path, ["RHT"])
    specgrad.update("asx", tmp_path, payload)
    assert json.dumps(payload, sort_keys=True) == frozen


def test_an_unusable_generated_at_never_invents_a_date(tmp_path):
    specgrad.update("asx", tmp_path, _spec([_row("RHT")], ts="not a date"))
    e = _reg(tmp_path)["markets"]["asx"]["seen"]["RHT"]
    assert e["first_seen"] == ""
    # ...and an empty first_seen can never satisfy "strictly before":
    _write_vivek(tmp_path, ["RHT"])
    specgrad.update("asx", tmp_path, _spec([], ts="2026-07-31T20:00:00+10:00"))
    assert _reg(tmp_path)["markets"]["asx"]["graduates"] == []


# ── THE FENCE — the owner's ruling, pinned in both directions ────────────────

def test_fence_1_the_module_is_imported_by_spec_run_alone():
    importers = []
    for p in sorted(ROOT.glob("scanner/**/*.py")):
        if p.name == "specgrad.py":
            continue
        if re.search(r"import\s+specgrad", p.read_text(encoding="utf-8")):
            importers.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    assert importers == ["scanner/spec_run.py"], (
        f"specgrad must be reachable from spec_run's publish path alone, found: {importers}")
    for p in sorted(ROOT.glob("scanner/broker/*.py")):
        text = p.read_text(encoding="utf-8")
        assert "specgrad" not in text and "spec_graduation" not in text, (
            f"{p.name}: the bot must not know the graduation watch exists")


def test_fence_2_nothing_in_scanner_or_broker_reads_the_file_back():
    # The writer module and the config constant are the only scanner-side
    # mentions of the artefact's name. scan.py, run.py, the bot and every
    # broker module must not know it exists.
    allowed = {"scanner/config.py", "scanner/specgrad.py"}
    hits = []
    for p in sorted(ROOT.glob("scanner/**/*.py")):
        if "spec_graduation" in p.read_text(encoding="utf-8"):
            rel = str(p.relative_to(ROOT)).replace("\\", "/")
            if rel not in allowed:
                hits.append(rel)
    assert hits == [], f"spec_graduation.json leaked toward a decision path: {hits}"


def test_fence_3_spec_run_updates_after_the_publish_under_a_narrow_try():
    src = (ROOT / "scanner" / "spec_run.py").read_text(encoding="utf-8")
    publish = src.index("payload = scan_market(m, limit=args.limit)")
    call = src.index("specgrad.update(m, OUT_DIR, payload)")
    assert call > publish, (
        "the watch must record what was PUBLISHED - update after scan_market")
    window = src[max(0, call - 400):call]
    assert "try:" in window, "the update must sit under a narrow try - report-only"
    assert "except (OSError, ValueError, TypeError, KeyError)" in src[call:call + 400], (
        "a report failure is named and swallowed, never a bare except, never fatal")


def test_the_nightly_stages_the_artefact_and_the_retry_reapplies_it():
    # One PATHS variable drives both the staging loop and the push-retry
    # re-apply, so membership there covers both. Deliberately NOT in the
    # must-change gate: specgrad failures are swallowed by design (spec_run
    # still exits 0), so a must-change assert would turn a tolerated report
    # failure into a red nightly.
    wf = (ROOT / ".github" / "workflows" / "phasemap.yml").read_text(encoding="utf-8")
    paths_line = next(l for l in wf.splitlines() if l.strip().startswith('PATHS="'))
    assert "public/data/spec_graduation.json" in paths_line, \
        "phasemap.yml must stage the graduation registry or the nightly reverts it"
    for line in re.findall(r"assert_staged\.sh[^\n]*", wf):
        assert "spec_graduation" not in line, (
            "the registry must stay OUT of the must-change gate (report-only tolerance)")


def test_the_specs_page_reads_it_and_only_the_specs_page():
    sp = (ROOT / "public" / "js" / "specs.js").read_text(encoding="utf-8")
    assert "data/spec_graduation.json" in sp
    others = [p.name for p in sorted(ROOT.glob("public/js/*.js"))
              if p.name != "specs.js" and "spec_graduation" in p.read_text(encoding="utf-8")]
    assert others == [], f"only the SPECS page renders the graduation watch: {others}"


def test_the_registry_is_published_through_the_integrity_writer():
    # Project rule 7 by construction: output.write_json is atomic and
    # NaN-nulled; a hand-rolled writer here would be the fourth exemption
    # test_publish_integrity exists to prevent.
    src = (ROOT / "scanner" / "specgrad.py").read_text(encoding="utf-8")
    assert "output.write_json(" in src
    assert "json.dump(" not in src and ".write_text(" not in src
