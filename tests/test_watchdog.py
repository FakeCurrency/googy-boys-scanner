"""Freshness watchdog (2026-07-20, Phase 5).

Pins the three things that make the watchdog trustworthy: the probe maths
(content + run-history), the noise discipline (first alert / 6h reminder /
recovery, never per-check spam), and the failure-suppression rule (a RED run
is GitHub's to email about — the watchdog only speaks for silent problems).
No network anywhere: the run-history fetcher is injected.
"""

import datetime as dt
import json
import subprocess

import pytest

from scanner import config
from scanner import watchdog as wd

pytestmark = pytest.mark.risk

NOW = dt.datetime(2026, 7, 20, 12, 0, tzinfo=dt.timezone.utc)


def _iso(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat(timespec="seconds")


# ── content probes ─────────────────────────────────────────────────────────────

def _tree(tmp_path, book_age_h=1.0, crypto_age_h=1.0, pm_lag_days=0,
          backup_age_h=1.0, with_book=True):
    (tmp_path / "journal").mkdir(parents=True)
    (tmp_path / "public" / "data").mkdir(parents=True)
    if with_book:
        (tmp_path / "journal" / "vivek_bot_book.json").write_text(
            json.dumps({"open": [], "closed": [], "updated_at": _iso(book_age_h)}),
            encoding="utf-8")
    (tmp_path / "public" / "data" / "crypto_vivek.json").write_text(
        json.dumps({"generated_at": _iso(crypto_age_h)}), encoding="utf-8")
    for m in config.MARKETS:
        d = tmp_path / "public" / "data" / "phasemap" / m
        d.mkdir(parents=True)
        (d / "latest.json").write_text(json.dumps(
            {"run_date": (NOW.date() - dt.timedelta(days=pm_lag_days)).isoformat()}),
            encoding="utf-8")
    b = tmp_path / "backups" / (NOW - dt.timedelta(hours=backup_age_h)).strftime(
        "%Y-%m-%dT%H-%M-%S")
    b.mkdir(parents=True)
    return tmp_path


def test_content_all_fresh_is_silent(tmp_path):
    assert wd.probe_content(_tree(tmp_path), NOW) == []


def test_content_stale_book_is_critical(tmp_path):
    probs = wd.probe_content(_tree(tmp_path, book_age_h=5.0), NOW)
    assert [p["key"] for p in probs] == ["book_stale"]
    assert probs[0]["severity"] == "CRITICAL"


def test_content_missing_book_is_critical(tmp_path):
    probs = wd.probe_content(_tree(tmp_path, with_book=False), NOW)
    assert any(p["key"] == "book_missing" and p["severity"] == "CRITICAL"
               for p in probs)


def test_content_thresholds_exact(tmp_path):
    # just inside every limit -> silent; just past -> fires
    ok = _tree(tmp_path / "a", book_age_h=3.9, crypto_age_h=3.9,
               pm_lag_days=1, backup_age_h=25.0)
    assert wd.probe_content(ok, NOW) == []
    bad = _tree(tmp_path / "b", book_age_h=4.1, crypto_age_h=4.1,
                pm_lag_days=2, backup_age_h=27.0)
    keys = {p["key"] for p in wd.probe_content(bad, NOW)}
    assert keys == {"book_stale", "crypto_scan_stale", "phasemap_stale",
                    "backup_stale"}


# ── run-history probes ─────────────────────────────────────────────────────────

def _runs_fetch(by_wf):
    def fetch(url):
        for wf, runs in by_wf.items():
            if f"/workflows/{wf}/runs" in url:
                return {"workflow_runs": runs}
        return {"workflow_runs": []}
    return fetch


def _run(hours_ago, conclusion="success"):
    return {"conclusion": conclusion, "run_started_at": _iso(hours_ago)}


def test_runs_fresh_success_is_silent():
    by = {wf: [_run(0.5)] for wf in config.WATCHDOG_RUNS}
    assert wd.probe_runs(_runs_fetch(by), NOW, repo="x/y") == []


def test_runs_old_success_fires_with_config_severity():
    by = {wf: [_run(0.5)] for wf in config.WATCHDOG_RUNS}
    by["kill_switch.yml"] = [_run(3.0)]          # limit 2h, CRITICAL
    by["scan.yml"] = [_run(30.0)]                # limit 24h, WARNING
    probs = wd.probe_runs(_runs_fetch(by), NOW, repo="x/y")
    got = {p["key"]: p["severity"] for p in probs}
    assert got == {"run_kill_switch.yml": "CRITICAL", "run_scan.yml": "WARNING"}


def test_runs_latest_failure_is_suppressed_but_noted():
    """A red run already emailed via GitHub — the watchdog must stay quiet."""
    by = {wf: [_run(0.5)] for wf in config.WATCHDOG_RUNS}
    by["phasemap.yml"] = [_run(1.0, "failure"), _run(40.0)]
    notes = []
    probs = wd.probe_runs(_runs_fetch(by), NOW, repo="x/y", notes=notes)
    assert not any(p["key"] == "run_phasemap.yml" for p in probs)
    assert any("phasemap.yml" in n and "FAILED" in n for n in notes)


def test_runs_in_progress_is_ignored_when_picking_latest():
    """conclusion=None (running now) must not mask an old success."""
    by = {wf: [_run(0.5)] for wf in config.WATCHDOG_RUNS}
    by["backup_book.yml"] = [{"conclusion": None, "run_started_at": _iso(0.1)},
                             _run(30.0)]
    probs = wd.probe_runs(_runs_fetch(by), NOW, repo="x/y")
    assert any(p["key"] == "run_backup_book.yml" and p["severity"] == "CRITICAL"
               for p in probs)


def test_runs_never_ran_is_note_not_breach():
    by = {wf: [_run(0.5)] for wf in config.WATCHDOG_RUNS}
    by["confluence.yml"] = []
    notes = []
    probs = wd.probe_runs(_runs_fetch(by), NOW, repo="x/y", notes=notes)
    assert not any("confluence" in p["key"] for p in probs)
    assert any("confluence.yml" in n for n in notes)


def test_runs_fetch_error_is_note_not_crash():
    def boom(url):
        raise RuntimeError("api down")
    notes = []
    assert wd.probe_runs(boom, NOW, repo="x/y", notes=notes) == []
    assert len(notes) == len(config.WATCHDOG_RUNS)


# ── alert state machine (the anti-spam core) ───────────────────────────────────

def _f(key, sev="WARNING"):
    return {"key": key, "severity": sev, "msg": key}


def test_state_first_detection_alerts_once():
    state, alerts, rec = wd.reconcile({}, [_f("a")], NOW)
    assert [a["key"] for a in alerts] == ["a"] and rec == []
    # 5 minutes later, still breached -> NO new alert
    later = NOW + dt.timedelta(minutes=5)
    state2, alerts2, _ = wd.reconcile(state, [_f("a")], later)
    assert alerts2 == []
    assert state2["a"]["first"] == state["a"]["first"]   # breach start kept


def test_state_renotifies_after_interval():
    state, _, _ = wd.reconcile({}, [_f("a")], NOW)
    later = NOW + dt.timedelta(hours=config.WATCHDOG_RENOTIFY_HOURS + 0.1)
    _, alerts, _ = wd.reconcile(state, [_f("a")], later)
    assert [a["key"] for a in alerts] == ["a"]


def test_state_recovery_reported_once_then_forgotten():
    state, _, _ = wd.reconcile({}, [_f("a")], NOW)
    state2, alerts, rec = wd.reconcile(state, [], NOW + dt.timedelta(hours=1))
    assert alerts == [] and rec == ["a"] and state2 == {}
    _, _, rec2 = wd.reconcile(state2, [], NOW + dt.timedelta(hours=2))
    assert rec2 == []                                    # no repeat


def test_state_mixed_new_ongoing_recovered():
    state, _, _ = wd.reconcile({}, [_f("old"), _f("gone")], NOW)
    later = NOW + dt.timedelta(hours=1)
    state2, alerts, rec = wd.reconcile(state, [_f("old"), _f("new")], later)
    assert [a["key"] for a in alerts] == ["new"]         # only the new one
    assert rec == ["gone"]
    assert set(state2) == {"old", "new"}


# ── assert_staged.sh (the must-change gate) ────────────────────────────────────

def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _gate(cwd, script, *args):
    return subprocess.run(["bash", str(script), *args],
                          cwd=cwd, capture_output=True, text=True)


def test_assert_staged_gate(tmp_path):
    import pathlib
    script = pathlib.Path(wd.ROOT) / "scripts" / "assert_staged.sh"
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "init")
    (repo / "book.json").write_text("{}", encoding="utf-8")

    # nothing staged -> hard fail with the loud marker
    r = _gate(repo, script, "test", "book.json")
    assert r.returncode == 1 and "ASSERT-STAGED FAILED" in r.stdout

    # staged NEW file -> pass; staged MODIFICATION -> pass
    _git(repo, "add", "book.json")
    assert _gate(repo, script, "test", "book.json").returncode == 0
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "add")
    (repo / "book.json").write_text('{"x": 1}', encoding="utf-8")
    _git(repo, "add", "book.json")
    assert _gate(repo, script, "test", "book.json").returncode == 0

    # any-of semantics: second path staged is enough
    r = _gate(repo, script, "test", "missing.json", "book.json")
    assert r.returncode == 0
