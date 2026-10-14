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
    """IMPORTED from scanner/conviction.py (2026-09-20: 1W reclaim/break, 3D
    reclaim, 1D break; armed; A/A+; no structure branch)."""
    from scanner import conviction
    assert SRC.count("conviction.is_high_conviction(row)") == 1, "the roster re-typed the rule"
    armed_reclaim = {"1W": {"armed": True, "entry_trigger": "reclaim", "structural_tps": 0}}
    assert er.high_conviction(_row(plans=armed_reclaim)) is True          # A+ grade path
    assert er.high_conviction(_row(plans={"3D": {"armed": True, "entry_trigger": "reclaim"}})) is True
    assert er.high_conviction(_row(plans={"1D": {"armed": True, "entry_trigger": "break"}})) is True
    weak = _row(grade_raw="A+", plans=armed_reclaim); weak["grade"] = "B+"
    assert er.high_conviction(weak) is False, "grade A/A+ is required"
    weak2 = _row(plans={"1W": {"armed": True, "entry_trigger": "reclaim", "structural_tps": 2}})
    weak2["grade"] = "B+"
    assert er.high_conviction(weak2) is False, "the structure path was dropped"
    assert er.high_conviction(_row(plans={"1W": {"armed": True, "entry_trigger": "retest"}})) is False
    assert er.high_conviction(_row(plans={})) is False
    assert er.high_conviction(_row(plans=armed_reclaim)) == conviction.is_high_conviction(_row(plans=armed_reclaim))


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


def test_stamping_is_the_ALERT_ledger_machinery_not_a_copy():
    # Mirror-drift fence: the forward-return maths must have ONE home.
    assert "def stamp(" not in SRC and "def wanting_prices(" not in SRC and "def trim(" not in SRC
    assert "ar.stamp(" in SRC and "ar.wanting_prices(" in SRC and "ar.price_frames(" in SRC
    assert er.HORIZONS == er.ar.HORIZONS


def test_the_roster_never_trims_a_row():
    """REFINE200 #62: the 20k cap would have started DELETING measured rows
    in ~December. The roster is sharded by month instead and never trims."""
    assert "trim(" not in SRC and "ALERT_ROSTER_CAP" not in SRC
    from scanner import config
    assert not hasattr(config, "ALERT_ROSTER_CAP"), "the cap is retired, not merely unread"


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


def test_the_roster_never_freezes_a_forming_bar_either():
    """2026-10-05: the roster ledger stamps through the SAME ar.stamp, so the
    completed-bars guard covers it - an ASX A+ row from Friday 2026-10-02 is
    not stamped off Monday's forming bar at 12:03 Monday Sydney (AEDT)."""
    import datetime as dt
    from zoneinfo import ZoneInfo
    led = er._fresh()
    led["entries"].append({"market": "asx", "ticker": "BHP", "side": "long",
                           "base_day": "2026-10-02", "base_close": None,
                           "fwd": {str(h): None for h in er.HORIZONS}})
    idx = pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-05"])
    frames = {"BHP.AX": pd.DataFrame({"Close": [99.0, 100.0, 104.0]}, index=idx)}
    syd = ZoneInfo("Australia/Sydney")
    midday = dt.datetime(2026, 10, 5, 12, 3, tzinfo=syd).astimezone(dt.timezone.utc)
    want = er.ar.wanting_prices(led, midday.date())
    assert "BHP.AX" in want
    er.ar.stamp(led, frames, want, midday)
    assert led["entries"][0]["base_close"] == 100.0 and led["entries"][0]["fwd"]["1"] is None
    evening = dt.datetime(2026, 10, 5, 17, 0, tzinfo=syd).astimezone(dt.timezone.utc)
    er.ar.stamp(led, frames, want, evening)
    assert led["entries"][0]["fwd"]["1"] == 0.04


def test_main_hands_stamp_a_clock_taken_before_the_download(tmp_path, monkeypatch):
    import time
    import scanner.data
    ledger = tmp_path / "rosters.json"
    ledger.write_text(json.dumps({"schema_version": 1, "updated_at": "", "entries": [
        {"key": "k", "market": "asx", "ticker": "BHP", "side": "long", "base_day": "2026-08-03",
         "base_close": None, "fwd": {str(h): None for h in er.HORIZONS}}]}), encoding="utf-8")
    monkeypatch.setattr(er, "LEDGER", str(ledger))
    monkeypatch.setattr(er, "ROOT", str(tmp_path))      # no scans: nothing ingested
    seen = {}

    def download(syms, period=None):
        seen["asked"] = time.time()
        return {}

    def stamp(led, frames, want, now=None):
        seen["now"] = now
        return 0

    monkeypatch.setattr(scanner.data, "download", download)
    monkeypatch.setattr(er.ar, "stamp", stamp)
    assert er.main(["--dry-run"]) == 0
    assert seen["now"] is not None and seen["now"].tzinfo is not None, "ar.stamp got no clock"
    assert seen["now"].timestamp() <= seen["asked"]


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


# ── REFINE200 #62: monthly shards, nothing trimmed ───────────────────────────

def _row_at(day, ticker="BHP", fwd=None):
    return {"key": f"{day}|asx|{ticker}|long", "market": "asx", "ticker": ticker, "side": "long",
            "base_day": day, "base_close": None,
            "fwd": fwd if fwd is not None else {str(h): None for h in er.HORIZONS}}


def test_the_single_file_migrates_to_monthly_shards_rows_unchanged(tmp_path):
    path = tmp_path / "edge_rosters.json"
    rows = [_row_at("2026-08-20"), _row_at("2026-09-01", "CBA"), _row_at("2026-09-30", "WES")]
    path.write_text(json.dumps({"schema_version": 1, "updated_at": "x", "entries": rows}), encoding="utf-8")
    led = er.load_ledger(str(path))
    assert led["migrate"] is True and led["entries"] == rows
    assert er.write_ledger(led, str(path)) == 2
    shards = tmp_path / "edge_rosters"
    assert sorted(p.name for p in shards.iterdir()) == ["2026-08.json", "2026-09.json"]
    sep = json.loads((shards / "2026-09.json").read_text(encoding="utf-8"))["entries"]
    assert sep == rows[1:], "rows are copied byte-for-byte in content"
    head = json.loads(path.read_text(encoding="utf-8"))
    assert "entries" not in head and head["shards"] == {"2026-08": 1, "2026-09": 2}
    assert head["updated_at"], "the workflow's backstop gate reads the manifest's updated_at"
    again = er.load_ledger(str(path))
    assert again["entries"] == rows and not again["migrate"]


def test_only_a_changed_month_is_rewritten(tmp_path):
    path = tmp_path / "edge_rosters.json"
    led = er._fresh()
    led["entries"] = [_row_at("2026-08-20"), _row_at("2026-10-01", "CBA")]
    er.write_ledger(led, str(path))
    aug = (tmp_path / "edge_rosters" / "2026-08.json").read_bytes()
    led = er.load_ledger(str(path))
    led["entries"][1]["base_close"] = 9.5            # a stamp lands in October only
    assert er.write_ledger(led, str(path)) == 1
    assert (tmp_path / "edge_rosters" / "2026-08.json").read_bytes() == aug


def test_an_unreadable_shard_stops_the_run_instead_of_rewriting_its_month(tmp_path, monkeypatch):
    path = tmp_path / "edge_rosters.json"
    led = er._fresh()
    led["entries"] = [_row_at("2026-08-20"), _row_at("2026-09-02", "CBA")]
    er.write_ledger(led, str(path))
    bad = tmp_path / "edge_rosters" / "2026-09.json"
    bad.write_text("{truncated", encoding="utf-8")
    monkeypatch.setattr(er, "LEDGER", str(path))
    monkeypatch.setattr(er, "ROOT", str(tmp_path))
    assert er.main([]) == 2
    assert bad.read_text(encoding="utf-8") == "{truncated", "the damaged month is left for a human"


# ── which scan is a session's roster (git history) ───────────────────────────

import datetime as _dt                                                 # noqa: E402
import os as _os                                                       # noqa: E402
import shutil as _shutil                                               # noqa: E402
import subprocess as _sp                                               # noqa: E402

import pytest                                                          # noqa: E402

_GIT = _shutil.which("git")
needs_git = pytest.mark.skipif(not _GIT, reason="git builds the fixture history")


def _history(tmp_path, commits):
    """A git repo whose history holds each (market, commit UTC iso,
    generated_at, [A+ symbols]) as a version of public/data/<m>_vivek.json."""
    repo = tmp_path / "repo"
    env = {**_os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x.invalid",
           "GIT_CONFIG_GLOBAL": _os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    _sp.run([_GIT, "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    d = repo / "public" / "data"
    d.mkdir(parents=True)
    for market, committed, generated, syms in commits:
        (d / f"{market}_vivek.json").write_text(
            json.dumps(_scan([_row(sym=s) for s in syms], generated=generated)), encoding="utf-8")
        _sp.run([_GIT, "add", "-A"], cwd=repo, check=True, env=env)
        _sp.run([_GIT, "commit", "-q", "-m", f"{market} {committed}"], cwd=repo, check=True,
                env={**env, "GIT_AUTHOR_DATE": committed, "GIT_COMMITTER_DATE": committed})
    return repo


def _ingest_at(monkeypatch, repo, now):
    monkeypatch.setattr(er, "ROOT", str(repo))
    led = er._fresh()
    er.ingest_today(led, now)
    return {(e["market"], e["base_day"], e["ticker"]) for e in led["entries"]}, led


@needs_git
def test_a_late_run_files_the_post_close_scan_not_the_mid_session_one(tmp_path, monkeypatch):
    """2026-10-14: the run landed 12:17 Sydney and filed a 12:15 mid-session
    ASX list as that day's cohort. Now: yesterday's POST-CLOSE scan, and the
    session still trading waits."""
    repo = _history(tmp_path, [
        ("asx", "2026-10-13T01:20:00+00:00", "2026-10-13T12:15:00+11:00", ["MID"]),
        ("asx", "2026-10-13T05:55:00+00:00", "2026-10-13T16:46:00+11:00", ["CLOSE"]),
        ("asx", "2026-10-14T01:16:00+00:00", "2026-10-14T12:15:00+11:00", ["TODAY"]),
    ])
    got, led = _ingest_at(monkeypatch, repo, _dt.datetime(2026, 10, 14, 1, 30, tzinfo=_dt.timezone.utc))
    assert got == {("asx", "2026-10-13", "CLOSE")}
    assert led["entries"][0]["snapshot_at"] == "2026-10-13T16:46:00+11:00"


@needs_git
def test_a_session_whose_close_scan_never_came_takes_its_last_scan_once_the_market_moved_on(
        tmp_path, monkeypatch):
    repo = _history(tmp_path, [
        ("asx", "2026-10-12T03:00:00+00:00", "2026-10-12T14:00:00+11:00", ["LAST"]),
        ("asx", "2026-10-13T01:20:00+00:00", "2026-10-13T12:15:00+11:00", ["NEXT"]),
    ])
    got, _ = _ingest_at(monkeypatch, repo, _dt.datetime(2026, 10, 13, 2, 0, tzinfo=_dt.timezone.utc))
    assert got == {("asx", "2026-10-12", "LAST")}, "the 13th is still trading"


@needs_git
def test_nasdaq_waits_for_its_post_close_scan_rather_than_filing_a_1543_list(tmp_path, monkeypatch):
    repo = _history(tmp_path, [
        ("nasdaq", "2026-10-13T19:50:00+00:00", "2026-10-13T15:43:00-04:00", ["EARLY"]),
    ])
    at_2220 = _dt.datetime(2026, 10, 13, 22, 20, tzinfo=_dt.timezone.utc)   # 18:20 New York
    got, _ = _ingest_at(monkeypatch, repo, at_2220)
    assert got == set(), "the 21:07 UTC post-close scan may still be in flight"


@needs_git
def test_crypto_files_the_last_scan_of_a_finished_UTC_day(tmp_path, monkeypatch):
    repo = _history(tmp_path, [
        ("crypto", "2026-10-13T22:30:00+00:00", "2026-10-13T22:22:00+00:00", ["A"]),
        ("crypto", "2026-10-13T23:30:00+00:00", "2026-10-13T23:22:00+00:00", ["B"]),
        ("crypto", "2026-10-14T00:30:00+00:00", "2026-10-14T00:22:00+00:00", ["C"]),
    ])
    got, _ = _ingest_at(monkeypatch, repo, _dt.datetime(2026, 10, 14, 1, 18, tzinfo=_dt.timezone.utc))
    assert got == {("crypto", "2026-10-13", "B")}


@needs_git
def test_a_weekend_stock_scan_is_filed_under_the_session_whose_data_it_holds(tmp_path, monkeypatch):
    """#140: pre-2026-10-05 heals rescanned shut markets at the weekend and the
    roster filed each as a Saturday/Sunday cohort (23% of rows)."""
    repo = _history(tmp_path, [
        ("nasdaq", "2026-10-10T15:00:00+00:00", "2026-10-10T11:00:00-04:00", ["SAT"]),
    ])
    got, _ = _ingest_at(monkeypatch, repo, _dt.datetime(2026, 10, 13, 1, 0, tzinfo=_dt.timezone.utc))
    assert got == {("nasdaq", "2026-10-09", "SAT")}, "Saturday's heal holds Friday's session"


@needs_git
def test_a_session_already_filed_is_never_read_a_second_time(tmp_path, monkeypatch):
    repo = _history(tmp_path, [
        ("asx", "2026-10-13T05:55:00+00:00", "2026-10-13T16:46:00+11:00", ["CLOSE"]),
    ])
    monkeypatch.setattr(er, "ROOT", str(repo))
    led = er._fresh()
    led["entries"].append(_row_at("2026-10-13", "MIDSESSION"))
    assert er.ingest_today(led, _dt.datetime(2026, 10, 14, 1, 0, tzinfo=_dt.timezone.utc)) == 0


def test_without_history_a_mid_session_file_on_disk_is_not_a_roster(tmp_path, monkeypatch):
    monkeypatch.setattr(er, "ROOT", str(tmp_path))
    d = tmp_path / "public" / "data"
    d.mkdir(parents=True)
    (d / "asx_vivek.json").write_text(json.dumps(_scan([_row()], generated="2026-10-14T12:15:00+11:00")),
                                      encoding="utf-8")
    led = er._fresh()
    assert er.ingest_today(led, _dt.datetime(2026, 10, 14, 1, 30, tzinfo=_dt.timezone.utc)) == 0


# ── the High-conviction rule travels with the tag ────────────────────────────

def test_every_new_row_says_which_high_conviction_rule_judged_it(monkeypatch):
    rows = er.roster_rows(_scan([_row()]), "asx")
    assert rows[0]["hc_rule"] == "cells=1W:reclaim/break;3D:reclaim;1D:break grades=A+/A"
    from scanner import conviction
    monkeypatch.setattr(conviction, "HC_CELLS", {"1W": ("reclaim",)})
    assert er.roster_rows(_scan([_row()]), "asx")[0]["hc_rule"] != rows[0]["hc_rule"], \
        "the stamp is DERIVED from the table, so it moves when the rule does"


# ── one download for both ledgers ────────────────────────────────────────────

def test_the_hand_off_is_reused_and_its_earlier_clock_judges_finality(tmp_path, monkeypatch):
    import datetime as dt
    import scanner.data
    path = tmp_path / "rosters.json"
    path.write_text(json.dumps({"schema_version": 1, "updated_at": "", "entries": [
        _row_at("2026-10-01")]}), encoding="utf-8")
    monkeypatch.setattr(er, "LEDGER", str(path))
    monkeypatch.setattr(er, "ROOT", str(tmp_path))
    fetched = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=20)
    hand = tmp_path / "frames.json"
    idx = pd.bdate_range("2026-09-01", periods=40)
    er.ar.save_frames(str(hand), {"BHP.AX": pd.DataFrame({"Close": [1.0] * 40}, index=idx),
                                  "^AXJO": pd.DataFrame({"Close": [1.0] * 40}, index=idx)},
                      {"BHP.AX": "3mo", "^AXJO": "3mo"}, fetched)
    asked, seen = [], {}
    monkeypatch.setattr(scanner.data, "download", lambda syms, period=None: asked.extend(syms) or {})
    monkeypatch.setattr(er.ar, "stamp", lambda led, frames, want, now=None: seen.update(now=now) or 0)
    assert er.main(["--frames-in", str(hand), "--dry-run"]) == 0
    assert asked == [], "everything the roster wanted was already downloaded"
    assert abs((seen["now"] - fetched).total_seconds()) < 1, "finality is judged on the hand-off's clock"


# ── the workflow wiring ──────────────────────────────────────────────────────

def _steps():
    yaml = pytest.importorskip("yaml")
    return {s.get("name"): s for s in yaml.safe_load(WF)["jobs"]["returns"]["steps"]}


def test_the_workflow_fetches_the_history_window_before_the_roster_reads_it():
    steps = _steps()
    names = list(steps)
    fetch = steps["Fetch recent scan history"]["run"]
    assert names.index("Fetch recent scan history") < names.index("Build the A+ roster baseline")
    assert "config.ALERT_ROSTER_LOOKBACK_DAYS" in fetch, "the window is read from config, never retyped"
    assert "--shallow-since" in fetch and "origin main" in fetch
    assert "|| echo \"::warning::" in fetch, "a failed fetch must degrade, not fail the ledgers"


def test_one_download_is_handed_from_the_alert_step_to_the_roster_step():
    steps = _steps()
    out = steps["Ingest + stamp forward returns"]["run"]
    inn = steps["Build the A+ roster baseline"]["run"]
    assert "--frames-out /tmp/edge_frames.json" in out and "--frames-in /tmp/edge_frames.json" in inn


def test_the_monthly_shards_are_staged_gated_and_carried_through_the_retry():
    commit = _steps()["Commit & push (surgical — the edge artefacts only)"]["run"]
    assert commit.count("git add -- data/edge_rosters 2>/dev/null || true") == 2
    assert 'git checkout "$SHA" -- data/edge_rosters 2>/dev/null || true' in commit
    gate = next(l for l in commit.splitlines() if "assert_staged.sh" in l)
    assert " data/edge_rosters " in gate and "data/edge_rosters.json" in gate
