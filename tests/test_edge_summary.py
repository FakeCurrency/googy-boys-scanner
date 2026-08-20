"""Edge summary artefact (scripts/edge_summary.py, batch-100 WS-J).

The headline aligned-vs-A+ numbers as a committed JSON. The rules worth
pinning: the math is IMPORTED from alert_edge_report (a re-typed formula
drifts in step with the bug it should catch), the baseline cohort is
DISJOINT from the aligned one, the payload is strictly finite, and the
engine never reads it back.
"""
from __future__ import annotations

import importlib.util
import json
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("edge_summary", ROOT / "scripts" / "edge_summary.py")
es = importlib.util.module_from_spec(spec)
spec.loader.exec_module(es)


def _entry(market="asx", day="2026-08-01", ticker="BHP", side="long", fwd=None):
    return {"market": market, "base_day": day, "ticker": ticker, "side": side,
            "fwd": fwd if fwd is not None else {"5": 2.0, "10": 3.0, "20": None}}


# ---------------------------------------------------------------- math source

def test_the_math_is_imported_not_retyped():
    src = (ROOT / "scripts" / "edge_summary.py").read_text(encoding="utf-8")
    assert "alert_edge_report" in src
    for fn in ("aer.dedup_first", "aer.signed", "aer.cohort_stats", "aer.HORIZONS"):
        assert fn in src, f"summary must call the report's own {fn}"
    # And no local reimplementation of the mean/SE math.
    assert "statistics" not in src and "stdev" not in src


def test_horizons_mirror_the_report():
    # The summary answers per-horizon exactly where the report does; a horizon
    # added to one and not the other silently splits the story.
    payload_keys = set(es.cohort_block([_entry()], es.aer.HORIZONS).keys())
    assert payload_keys == set(es.aer.HORIZONS)


# ---------------------------------------------------------------- cohort math

def test_signed_side_split_is_faithful():
    entries = [
        _entry(ticker="AAA", side="long", fwd={"5": 2.0}),
        _entry(ticker="BBB", side="short", fwd={"5": -3.0}),   # signed -> +3.0
    ]
    blk = es.cohort_block(entries, ("5",))
    assert blk["5"]["dedup"]["n"] == 2
    assert blk["5"]["long"]["n"] == 1 and blk["5"]["short"]["n"] == 1
    assert abs(blk["5"]["long"]["mean"] - 2.0) < 1e-9
    assert abs(blk["5"]["short"]["mean"] - 3.0) < 1e-9, \
        "a short that fell 3% is a +3% signed outcome"


def test_dedup_is_applied_before_the_split():
    # Two rows for the same name+side must count once, exactly as the report
    # counts them — pseudo-replication was the R1 lesson.
    entries = [
        _entry(ticker="AAA", day="2026-08-01", fwd={"5": 2.0}),
        _entry(ticker="AAA", day="2026-08-05", fwd={"5": 9.0}),
    ]
    blk = es.cohort_block(entries, ("5",))
    assert blk["5"]["dedup"]["n"] == len(es.aer.dedup_first(entries)), \
        "the summary must count exactly what dedup_first returns"


def test_unmatured_horizon_rows_are_excluded_not_zeroed():
    blk = es.cohort_block([_entry(fwd={"5": None})], ("5",))
    assert blk["5"]["dedup"]["n"] == 0


# ---------------------------------------------------------------- disjointness

def test_baseline_excludes_that_days_aligned_names(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    rosters = tmp_path / "rosters.json"
    ledger.write_text(json.dumps({"entries": [_entry(ticker="BHP")]}), encoding="utf-8")
    rosters.write_text(json.dumps({"entries": [
        _entry(ticker="BHP"),                       # same market+day+ticker -> excluded
        _entry(ticker="CBA"),                       # plain A+ -> stays
    ]}), encoding="utf-8")
    monkeypatch.setattr(es.aer, "LEDGER", str(ledger))
    monkeypatch.setattr(es.aer, "ROSTERS", str(rosters))
    out = es.build()
    assert out["baseline_aplus"]["5"]["dedup"]["n"] == 1, \
        "an aligned name must not sit in its own control group"
    assert out["aligned"]["5"]["dedup"]["n"] == 1


def test_a_missing_roster_file_degrades_to_an_empty_baseline(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"entries": [_entry()]}), encoding="utf-8")
    monkeypatch.setattr(es.aer, "LEDGER", str(ledger))
    monkeypatch.setattr(es.aer, "ROSTERS", str(tmp_path / "absent.json"))
    out = es.build()
    assert out["baseline_aplus"]["5"]["dedup"]["n"] == 0


# ---------------------------------------------------------------- payload hygiene

def test_payload_is_strictly_finite():
    # n=1 cohorts give the report a NaN SE; the summary must null it, never
    # ship it (a bare NaN token kills response.json() for the whole file).
    blk = es.cohort_block([_entry(fwd={"5": 2.0})], ("5",))
    flat = json.dumps(blk, allow_nan=False)      # raises on any NaN/Infinity
    assert "NaN" not in flat


def test_clean_nulls_nan_and_keeps_real_values():
    out = es._clean({"mean": 1.5, "se": float("nan"), "n": 3})
    assert out == {"mean": 1.5, "se": None, "n": 3}


def test_writes_atomically_via_output_write_json():
    src = (ROOT / "scripts" / "edge_summary.py").read_text(encoding="utf-8")
    assert "output.write_json" in src
    assert "json.dump(" not in src, "raw dumps bypass the atomic+finite gate"


def test_unchanged_content_is_a_stated_noop_not_a_redate():
    src = (ROOT / "scripts" / "edge_summary.py").read_text(encoding="utf-8")
    assert "EDGE_SUMMARY_UNCHANGED" in src
    assert 'k != "generated_at"' in src, "the comparison must ignore only the timestamp"


# ---------------------------------------------------------------- fences

def test_nothing_in_the_engine_reads_the_summary():
    for p in list((ROOT / "scanner").rglob("*.py")):
        assert "edge_summary" not in p.read_text(encoding="utf-8"), \
            f"the summary is research output only: {p}"


def test_the_summary_never_writes_the_ledgers_it_reads():
    src = (ROOT / "scripts" / "edge_summary.py").read_text(encoding="utf-8")
    for token in ("alert_forward_returns", "edge_rosters"):
        for line in src.splitlines():
            if token in line:
                assert "write" not in line and 'open(' not in line.replace(
                    'open(aer.', 'READ('), f"suspicious ledger line: {line}"
    # Structural version of the same claim: the only write target is OUT.
    assert src.count("output.write_json(") == 1
    assert "output.write_json(OUT" in src


# ---------------------------------------------------------------- workflow pins

def test_the_workflow_runs_and_stages_it():
    wf = (ROOT / ".github" / "workflows" / "alert_returns.yml").read_text(encoding="utf-8")
    assert "python scripts/edge_summary.py" in wf
    assert "git add -- public/data/edge_summary.json" in wf
    assert "EDGE_SUMMARY_UNCHANGED" in wf
    assert "public/data/edge_summary.json" in wf.split("assert_staged.sh")[1].splitlines()[0]


def test_the_retry_loop_carries_the_summary_through_the_rebase():
    wf = (ROOT / ".github" / "workflows" / "alert_returns.yml").read_text(encoding="utf-8")
    assert 'git checkout "$SHA" -- public/data/edge_summary.json' in wf, \
        "a push race must not silently drop the summary from the retried commit"


def test_the_sunday_digest_is_gated_missing_webhook_safe_and_bom_trimmed():
    wf = (ROOT / ".github" / "workflows" / "alert_returns.yml").read_text(encoding="utf-8")
    assert 'date -u +%u' in wf and '"7"' in wf, "digest fires on Sundays only"
    assert "DISCORD_WEBHOOK_URL not set" in wf, "missing webhook degrades, never reds"
    assert "\\ufeff" in wf, "the webhook trim must survive the BOM paste (2026-08-01)"
    assert "vivek5-alerts/1.0" in wf, "Discord 403s the default Python UA"
