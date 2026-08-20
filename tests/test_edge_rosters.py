"""The daily A+ roster ledger (scripts/edge_rosters.py, batch-100 WS-B).

The baseline cohort's whole value is comparability with the alert ledger, so
the pins here are about SAMENESS (imported machinery, same horizons, same
freeze/trim discipline) and about the ingest being honest (grade_raw only,
one row per day+name+side, tag conditions mirroring the deck's own).
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("edge_rosters", ROOT / "scripts" / "edge_rosters.py")
er = importlib.util.module_from_spec(spec)
spec.loader.exec_module(er)

WF = (ROOT / ".github" / "workflows" / "alert_returns.yml").read_text(encoding="utf-8")
SRC = (ROOT / "scripts" / "edge_rosters.py").read_text(encoding="utf-8")


def _scan(rows, generated="2026-08-20T17:34:59+10:00"):
    return {"generated_at": generated, "results": rows}


def _row(sym="BHP", grade_raw="A+", dir="LONG", score=9, chips=(), plans=None, **kw):
    return {"symbol": sym, "grade_raw": grade_raw, "grade": grade_raw, "dir": dir,
            "score": score, "chips": list(chips), "plans": plans or {}, **kw}


def test_only_grade_raw_aplus_rows_enter_the_roster():
    rows = er.roster_rows(_scan([_row(), _row(sym="XYZ", grade_raw="A"),
                                 _row(sym="W", grade_raw="WATCH")]), "asx")
    assert [r["ticker"] for r in rows] == ["BHP"]
    assert rows[0]["side"] == "long"
    assert rows[0]["fwd"] == {str(h): None for h in er.HORIZONS}


def test_the_key_is_day_name_side_in_the_markets_own_calendar():
    # 17:34 AEST on Aug 20 IS session day Aug 20 in Melbourne.
    rows = er.roster_rows(_scan([_row(dir="SHORT")]), "asx")
    assert rows[0]["key"] == "2026-08-20|asx|BHP|short"
    assert rows[0]["base_day"] == "2026-08-20"


def test_high_conviction_mirrors_the_deck_condition():
    armed_reclaim = {"1W": {"armed": True, "entry_trigger": "reclaim", "structural_tps": 0}}
    assert er.high_conviction(_row(plans=armed_reclaim)) is True          # A+ grade path
    weak = _row(grade_raw="A+", plans=armed_reclaim); weak["grade"] = "B+"
    assert er.high_conviction(weak) is False, "neither good grade nor structure"
    weak2 = _row(plans={"1W": {"armed": True, "entry_trigger": "reclaim", "structural_tps": 2}})
    weak2["grade"] = "B+"
    assert er.high_conviction(weak2) is True, "structure path"
    assert er.high_conviction(_row(plans={"1W": {"armed": True, "entry_trigger": "retest"}})) is False
    assert er.high_conviction(_row(plans={})) is False


def test_strong_structure_reads_the_chip():
    rows = er.roster_rows(_scan([_row(chips=["STRONG STRUCTURE"]),
                                 _row(sym="X", chips=["OTHER"])]), "asx")
    assert rows[0]["strong"] is True and rows[1]["strong"] is False


def test_ingest_is_idempotent_per_day(tmp_path, monkeypatch):
    led = er._fresh()
    monkeypatch.setattr(er, "ROOT", str(tmp_path))
    d = tmp_path / "public" / "data"; d.mkdir(parents=True)
    for m in ("asx", "nasdaq", "crypto"):
        (d / f"{m}_vivek.json").write_text(json.dumps(_scan([_row()])), encoding="utf-8")
    monkeypatch.setattr(er.ar, "_breadth_series", lambda: {"asx": {"2026-08-20": 0.475}})
    n1 = er.ingest_today(led)
    n2 = er.ingest_today(led)
    assert n1 == 3 and n2 == 0, "a re-run ingests nothing"
    asx = next(e for e in led["entries"] if e["market"] == "asx")
    assert asx["breadth200"] == 0.475


def test_stamping_and_trim_are_the_ALERT_ledger_machinery_not_a_copy():
    # Mirror-drift fence: the forward-return maths must have ONE home.
    assert "def stamp(" not in SRC and "def wanting_prices(" not in SRC and "def trim(" not in SRC
    assert "ar.stamp(" in SRC and "ar.wanting_prices(" in SRC and "ar.trim(" in SRC
    assert er.HORIZONS == er.ar.HORIZONS


def test_roster_returns_stamp_and_freeze_via_the_shared_machinery():
    led = er._fresh()
    led["entries"].append({"market": "asx", "ticker": "BHP", "side": "long",
                           "base_day": "2026-08-01", "base_close": None,
                           "fwd": {str(h): None for h in er.HORIZONS}})
    import datetime as dt
    want = er.ar.wanting_prices(led, dt.date(2026, 12, 1))
    idx = pd.date_range("2026-08-01", periods=30, freq="D")
    frames = {"BHP.AX": pd.DataFrame({"Close": [100.0 + i for i in range(30)]}, index=idx)}
    er.ar.stamp(led, frames, want)
    assert abs(led["entries"][0]["fwd"]["5"] - 0.05) < 1e-9


def test_trim_uses_the_roster_cap_and_never_drops_unmatured(monkeypatch):
    led = er._fresh()
    for i in range(4):
        led["entries"].append({"market": "asx", "ticker": f"T{i}", "side": "long",
                               "base_day": f"2026-07-0{i+1}",
                               "fwd": {str(h): None for h in er.HORIZONS}})
    assert er.ar.trim(led, cap=2) == 0, "all waiting -> nothing trimmed even over cap"
    led["entries"][0]["fwd"] = {str(h): 0.1 for h in er.HORIZONS}
    assert er.ar.trim(led, cap=2) == 1


def test_fences_read_only_research():
    assert '"w"' not in SRC and "'w'" not in SRC.replace("'w3", "xx"), \
        "the roster script must write only via output.write_json"
    for p in (ROOT / "scanner").rglob("*.py"):
        if p.name == "config.py":
            continue
        assert "edge_rosters" not in p.read_text(encoding="utf-8"), \
            f"the engine must not know the roster ledger exists: {p}"
    assert "alert_history" not in SRC, "the roster script has no business near the alert log"


def test_the_workflow_runs_it_and_the_report_lands_in_the_summary():
    assert "python scripts/edge_rosters.py" in WF
    assert "python scripts/alert_edge_report.py" in WF
    assert "GITHUB_STEP_SUMMARY" in WF
