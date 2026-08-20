"""Sanity tests for scripts/alert_edge_report.py (edge-research batch, 2026-08-20).

A research script whose math is wrong produces confident nonsense, so every
number-producing function is verified against a small fixture computed by
hand. The report's prose is not tested; the arithmetic is.
"""
from __future__ import annotations

import importlib.util
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "alert_edge_report", ROOT / "scripts" / "alert_edge_report.py")
aer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aer)


def test_signed_returns_flip_for_shorts_only():
    # A short alert followed by a -3% move WENT THE ALERT'S WAY: +3% edge.
    assert aer.signed(0.03, "long") == 0.03
    assert aer.signed(-0.03, "short") == 0.03
    assert aer.signed(0.03, "short") == -0.03
    assert aer.signed(None, "long") is None


def test_cohort_stats_by_hand():
    s = aer.cohort_stats([0.10, -0.05, 0.05, None])
    assert s["n"] == 3, "None never counts as an observation"
    assert abs(s["mean"] - (0.10 - 0.05 + 0.05) / 3) < 1e-12
    assert abs(s["median"] - 0.05) < 1e-12
    assert abs(s["win"] - 2 / 3) < 1e-12
    # population sd of [.1,-.05,.05] = sqrt(mean((x-mean)^2)); SE = sd/sqrt(3)
    m = s["mean"]
    sd = math.sqrt(sum((x - m) ** 2 for x in (0.10, -0.05, 0.05)) / 3)
    assert abs(s["se"] - sd / math.sqrt(3)) < 1e-12
    assert aer.cohort_stats([])["n"] == 0


def test_dedup_keeps_the_FIRST_alignment_only():
    rows = [
        {"market": "asx", "ticker": "BHP", "side": "long", "base_day": "2026-08-10", "v": 2},
        {"market": "asx", "ticker": "BHP", "side": "long", "base_day": "2026-08-08", "v": 1},
        {"market": "asx", "ticker": "BHP", "side": "short", "base_day": "2026-08-09", "v": 3},
        {"market": "nasdaq", "ticker": "BHP", "side": "long", "base_day": "2026-08-11", "v": 4},
    ]
    out = aer.dedup_first(rows)
    assert [x["v"] for x in out] == [1, 3, 4], \
        "earliest base_day wins per (market,ticker,side); other identities survive"


def test_forward_return_is_h_sessions_not_h_days():
    days = ["d1", "d2", "d3", "d4", "d5", "d6", "d7"]
    snaps = {d: {"prices": {"XYZ": 100.0 + i}} for i, d in enumerate(days)}
    r = aer.forward_return(days, snaps, "d1", "XYZ", 5)
    assert abs(r - (105.0 / 100.0 - 1)) < 1e-12, "5 sessions forward = index +5"
    assert aer.forward_return(days, snaps, "d3", "XYZ", 5) is None, \
        "right-censored: no session d3+5 yet"
    assert aer.forward_return(days, snaps, "d1", "MISSING", 5) is None
    snaps["d1"]["prices"]["ZERO"] = 0.0
    assert aer.forward_return(days, snaps, "d1", "ZERO", 5) is None, "a zero base is not a return"


def test_too_thin_buckets_are_labelled_not_reported_as_findings():
    line = aer.fmt(aer.cohort_stats([0.01] * (aer.MIN_N - 1)), "x")
    assert "TOO THIN" in line
    line = aer.fmt(aer.cohort_stats([0.01] * aer.MIN_N), "x")
    assert "TOO THIN" not in line


def test_roster_baseline_keeps_the_cohorts_disjoint(capsys):
    # A name that aligned on a day must not also count as that day's plain-A+
    # baseline — double-counting one bet on both sides of the comparison.
    entries = [{"market": "asx", "base_day": "2026-08-01", "ticker": "BHP",
                "side": "long", "fwd": {"5": 0.05}}]
    rosters = [{"market": "asx", "base_day": "2026-08-01", "ticker": "BHP",
                "side": "long", "fwd": {"5": 0.99}},
               {"market": "asx", "base_day": "2026-08-01", "ticker": "CBA",
                "side": "long", "fwd": {"5": 0.02}}]
    aer.roster_report(entries, rosters)
    out = capsys.readouterr().out
    roster_line = next(l for l in out.splitlines() if "roster A+ dedup" in l)
    assert "n=   1" in roster_line, f"BHP must be excluded from the baseline: {roster_line}"
    assert "+2.00%" in roster_line, "only CBA's return may enter"


def test_day_clustered_view_prints_in_the_ledger_report(capsys, monkeypatch):
    entries = []
    for day in ("2026-08-01", "2026-08-02"):
        for i in range(3):
            entries.append({"market": "asx", "base_day": day, "ticker": f"T{day}{i}",
                            "side": "long", "count": 2, "lenses": ["PHASEMAP", "VIVEK"],
                            "fwd": {"5": 0.01 * (i + 1), "10": None, "20": None, "1": None}})
    monkeypatch.setattr(aer, "load_sectors", lambda: {})
    aer.ledger_report(entries)
    out = capsys.readouterr().out
    assert "day-clustered means" in out
    line = next(l for l in out.splitlines() if "day-clustered means" in l and "n=" in l)
    assert "n=   2" in line, f"two base days -> two clustered observations: {line}"


def test_the_script_is_read_only_research():
    src = (ROOT / "scripts" / "alert_edge_report.py").read_text(encoding="utf-8")
    for verb in ("write_json", "os.replace", 'open(', ):
        pass  # open() is used read-only; assert no write modes instead
    assert '"w"' not in src and "'w'" not in src, "the report must never write a file"
    for p in (ROOT / "scanner").rglob("*.py"):
        assert "alert_edge_report" not in p.read_text(encoding="utf-8"), \
            f"the engine must not import the research script: {p}"
