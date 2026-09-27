"""Freshness watchdog (2026-07-20, Phase 5).

Pins the three things that make the watchdog trustworthy: the probe maths
(content + run-history), the noise discipline (first alert / 6h reminder /
recovery, never per-check spam), and the failure-suppression rule (a RED run
is GitHub's to email about — the watchdog only speaks for silent problems).
No network anywhere: the run-history fetcher and the endpoint probe's status
getter are both injected, and the two tests that exercise the real
"""

import datetime as dt
import json
import subprocess
import urllib.error

import pytest

from scanner import config
from scanner import watchdog as wd

pytestmark = pytest.mark.risk

NOW = dt.datetime(2026, 7, 20, 12, 0, tzinfo=dt.timezone.utc)


def _iso(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat(timespec="seconds")


# ── content probes ─────────────────────────────────────────────────────────────

def _stamp_universe(root, stamps: dict) -> None:
    """stamps: market key -> saved_at ISO string, written as a roster cache."""
    d = root / "data" / "universe_cache"
    d.mkdir(parents=True, exist_ok=True)
    for m, ts in stamps.items():
        (d / f"{m}.json").write_text(
            json.dumps({"saved_at": ts, "items": []}), encoding="utf-8")


def _tree(tmp_path, book_age_h=1.0, crypto_age_h=1.0, pm_lag_days=0,
          backup_age_h=1.0, with_book=True, universe_age_h=1.0,
          combined_age_h=None, canonical=True):
    """combined_age_h defaults to book_age_h: the honest case, where the derived
    view is written by the same run that wrote the canonical files.
    canonical=False writes ONLY the derived combined book — the shape that used
    to pass every freshness check by itself (2026-07-28)."""
    (tmp_path / "journal").mkdir(parents=True)
    (tmp_path / "public" / "data").mkdir(parents=True)
    if with_book:
        (tmp_path / "journal" / "vivek_bot_book.json").write_text(
            json.dumps({"open": [], "closed": [],
                        "updated_at": _iso(book_age_h if combined_age_h is None
                                           else combined_age_h)}),
            encoding="utf-8")
        if canonical:
            # The CANONICAL per-market files are what a run actually writes;
            # the combined book is derived from them. probe_content reads these.
            for m in config.MARKETS:
                (tmp_path / "journal" / f"vivek_bot_book.{m}.json").write_text(
                    json.dumps({"version": 2, "market": m, "open": [], "closed": [],
                                "updated_at": _iso(book_age_h)}),
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
    if universe_age_h is not None:
        _stamp_universe(tmp_path, {m: _iso(universe_age_h) for m in config.MARKETS})
    return tmp_path


def test_content_all_fresh_is_silent(tmp_path):
    assert wd.probe_content(_tree(tmp_path), NOW) == []


# ── ticker-roster freshness (2026-07-27: asx.com.au died silently for 3 days) ──

def test_weekday_age_skips_the_weekend():
    fri = dt.datetime(2026, 7, 17, 12, 0, tzinfo=dt.timezone.utc)
    mon = dt.datetime(2026, 7, 20, 12, 0, tzinfo=dt.timezone.utc)
    assert (mon - fri).total_seconds() / 3600 == 72.0        # wall clock
    # Fri 12:00->Sat 00:00 = 12h, Sat+Sun = 0, Mon 00:00->12:00 = 12h
    assert wd._weekday_age_h(fri, mon) == pytest.approx(24.0)
    assert wd._weekday_age_h(mon, mon) == 0.0
    assert wd._weekday_age_h(mon + dt.timedelta(hours=1), mon) == 0.0
    # A garbage/epoch stamp must short-circuit, not walk a thousand days.
    ancient = mon - dt.timedelta(days=400)
    assert wd._weekday_age_h(ancient, mon) == pytest.approx(400 * 24)


def test_content_no_universe_cache_is_silent(tmp_path):
    # A fresh clone, or a market never scanned here, has no roster cache. That
    # is not a fault - same rule the backups probe uses for an absent dir.
    assert wd.probe_content(_tree(tmp_path, universe_age_h=None), NOW) == []


def test_content_stale_asx_roster_is_warning(tmp_path):
    t = _tree(tmp_path)
    _stamp_universe(t, {"asx": "2026-07-16T12:00:00+00:00"})   # Thu -> 48 weekday-h
    probs = wd.probe_content(t, NOW)
    assert [p["key"] for p in probs] == ["universe_stale_asx"]
    assert probs[0]["severity"] == "WARNING"
    assert "frozen" in probs[0]["msg"]


def test_content_weekend_gap_does_not_flag_a_weekday_market(tmp_path):
    # THE false-alarm case this probe had to survive: ASX scans Mon-Fri, so a
    # roster stamped at Friday's close is ~77h old by Monday lunch through
    # nobody's fault. Charged in weekday hours it is 29h - inside the limit.
    t = _tree(tmp_path)
    _stamp_universe(t, {"asx": "2026-07-17T06:37:00+00:00"})   # Fri ASX close
    assert wd.probe_content(t, NOW) == []


def test_content_crypto_roster_is_judged_on_wall_clock(tmp_path):
    # Crypto scans hourly 24/7, so for it a weekend is real downtime, not an
    # off-hours gap: same 20h stamp is stale for crypto and fine for ASX.
    t = _tree(tmp_path, universe_age_h=None)
    _stamp_universe(t, {"crypto": _iso(20.0), "asx": _iso(20.0)})
    probs = wd.probe_content(t, NOW)
    assert [p["key"] for p in probs] == ["universe_stale_crypto"]
    assert probs[0]["severity"] == "WARNING"


def test_content_unreadable_universe_cache_is_warning(tmp_path):
    t = _tree(tmp_path, universe_age_h=None)
    d = t / "data" / "universe_cache"
    d.mkdir(parents=True)
    (d / "asx.json").write_text("{not json", encoding="utf-8")
    probs = wd.probe_content(t, NOW)
    assert [p["key"] for p in probs] == ["universe_unreadable_asx"]


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


def test_runs_old_success_fires_with_config_severity(monkeypatch):
    by = {wf: [_run(0.5)] for wf in config.WATCHDOG_RUNS}
    by["kill_switch.yml"] = [_run(3.0)]          # limit 2h, CRITICAL
    by["scan.yml"] = [_run(30.0)]                # limit 12h IN-SESSION, WARNING
    # scan.yml is session_aware since 2026-09-21: wall-clock age no longer
    # decides it (that is the whole point -- a weekend is 52 wall hours and
    # zero session hours). Stub the session clock so this test keeps asking its
    # own question, which is whether the SEVERITY comes from config.
    monkeypatch.setattr(wd, "session_hours_between", lambda a, b: 30.0)
    probs = wd.probe_runs(_runs_fetch(by), NOW, repo="x/y")
    got = {p["key"]: p["severity"] for p in probs}
    assert got == {"run_kill_switch.yml": "CRITICAL", "run_scan.yml": "WARNING"}


def test_a_weekend_never_alarms_the_scan_workflow_but_a_lost_session_does():
    """The reason session_hours_between exists (owner, 2026-09-21: scans stop
    outside market hours). Friday's last scan to Sunday night is ~50 wall hours
    and ZERO session hours, so the watchdog must stay silent; the same wall
    gap across a weekday IS a missed session and must fire."""
    import datetime as dt
    U = dt.timezone.utc
    fri_last = dt.datetime(2026, 9, 18, 21, 10, tzinfo=U)   # after the NASDAQ post-close scan
    sun_night = dt.datetime(2026, 9, 20, 22, 0, tzinfo=U)
    assert (sun_night - fri_last).total_seconds() / 3600 > 48, "fixture is not a weekend gap"
    assert wd.session_hours_between(fri_last, sun_night) == 0.0

    tue = dt.datetime(2026, 9, 15, 0, 0, tzinfo=U)
    wed = dt.datetime(2026, 9, 16, 0, 0, tzinfo=U)
    assert wd.session_hours_between(tue, wed) > config.WATCHDOG_RUNS["scan.yml"]["max_age_h"], \
        "a whole weekday with no scan must still breach the limit"


def test_session_hours_fails_QUIET_on_unusable_input():
    """A tz error inventing an outage is worse than missing one."""
    import datetime as dt
    U = dt.timezone.utc
    n = dt.datetime(2026, 9, 15, 0, 0, tzinfo=U)
    assert wd.session_hours_between(None, n) == 0.0
    assert wd.session_hours_between(n, None) == 0.0
    assert wd.session_hours_between(n, n) == 0.0
    assert wd.session_hours_between(n, n - dt.timedelta(hours=5)) == 0.0


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


# (The /api/tick endpoint probes lived here. The cloud stop/target watcher and
#  the manual journal it served were removed 2026-09-21, and probe_endpoints
#  with them — a service that no longer exists needs no liveness test.)

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


# ── ledger mode (the VPS; deploy/DESIGN.md 3.6, 2026-09-27) ───────────────────
#
# When VIVEK_RUNS_LEDGER is set the run-history probe reads the job runner's
# state/runs.json instead of api.github.com. The contract is the FILE: these
# tests write rows in the documented shape and never import scanner.vps, so C1
# (the writer) and C4 (this reader) can only meet at the format.

import collections
import pathlib
import urllib.request


def _ledger(tmp_path, rows: dict) -> pathlib.Path:
    p = tmp_path / "runs.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return p


def _lrow(success_h=None, failure_h=None, skip_h=None, **extra) -> dict:
    """One ledger row from ages-in-hours; None leaves the stamp absent."""
    row = {"host": "vps", "last_status": "ok", "last_exit": 0}
    if success_h is not None:
        row["last_success_at"] = _iso(success_h)
    if failure_h is not None:
        row["last_failure_at"] = _iso(failure_h)
        row["last_status"] = "failed"
        row["last_exit"] = 1
    if skip_h is not None:
        row["last_skip_at"] = _iso(skip_h)
    row.update(extra)
    return row


def _all_fresh_ledger() -> dict:
    return {wf: _lrow(success_h=0.5) for wf in config.WATCHDOG_RUNS}


def test_ledger_parity_same_facts_give_the_same_findings_as_github_mode(tmp_path):
    """ONE fixture drives BOTH modes (book-safety review's ask). Where the two
    overlap -- no failure newer than the last success -- the ledger probe must
    produce the SAME findings, byte for byte: same keys, severities, wording
    and session arithmetic. A gate-skipped Actions run concludes `success`,
    so a skip stamp refreshes the ledger clock exactly as that run would."""
    facts = {wf: {"success": 0.5} for wf in config.WATCHDOG_RUNS}
    facts["kill_switch.yml"] = {"success": 3.0}                 # stale, CRITICAL
    facts["phasemap.yml"] = {"success": 30.0}                   # stale, WARNING
    facts["backup_book.yml"] = {"success": 30.0, "skip": 0.1}   # old success, fresh skip
    facts["reco_note.yml"] = {"skip": 0.2}                      # only ever skipped
    facts["confluence.yml"] = {}                                # never ran

    github, ledger = {}, {}
    for wf, f in facts.items():
        runs = []
        if "skip" in f:
            runs.append(_run(f["skip"]))          # a gate skip = a success run
        if "success" in f:
            runs.append(_run(f["success"]))
        github[wf] = sorted(runs, key=lambda r: r["run_started_at"], reverse=True)
        if f:
            ledger[wf] = _lrow(success_h=f.get("success"), skip_h=f.get("skip"))

    notes_gh, notes_ld = [], []
    from_github = wd.probe_runs(_runs_fetch(github), NOW, repo="x/y", notes=notes_gh)
    from_ledger = wd.probe_ledger(_ledger(tmp_path, ledger), NOW, notes=notes_ld)

    assert from_ledger == from_github
    assert {p["key"] for p in from_ledger} == {"run_kill_switch.yml", "run_phasemap.yml"}
    assert notes_ld == notes_gh == ["confluence.yml: no recorded runs yet"]


def test_ledger_session_aware_scan_uses_the_same_clock_as_github(tmp_path, monkeypatch):
    """scan.yml is judged in market hours in BOTH modes, off the same stamp."""
    seen = []

    def clock(a, b):
        seen.append((a, b))
        return 30.0
    monkeypatch.setattr(wd, "session_hours_between", clock)
    led = _all_fresh_ledger()
    led["scan.yml"] = _lrow(success_h=30.0)
    probs = wd.probe_ledger(_ledger(tmp_path, led), NOW)
    assert [p["key"] for p in probs] == ["run_scan.yml"]
    assert "in market hours" in probs[0]["msg"] and probs[0]["severity"] == "WARNING"
    assert seen and seen[0][0] == wd._parse_ts(led["scan.yml"]["last_success_at"])


def test_ledger_failed_run_is_a_finding_not_a_silence(tmp_path):
    """THE deliberate divergence from GitHub mode. There a failed latest run is
    GitHub's to email about; the VPS has no red-run email, so the watchdog IS
    the alarm. Table severity, except the four in VPS_WATCHDOG_FAILED_CRITICAL
    which are CRITICAL regardless (scan.yml and crypto_bot.yml are WARNING in
    the table and must come out CRITICAL here)."""
    led = _all_fresh_ledger()
    for wf in ("phasemap.yml", "confluence.yml", "scan.yml", "crypto_bot.yml",
               "kill_switch.yml", "backup_book.yml"):
        led[wf] = _lrow(success_h=5.0, failure_h=1.0, consecutive_failures=2,
                        last_line="assert_staged FAILED: scan output")
    probs = wd.probe_ledger(_ledger(tmp_path, led), NOW)
    got = {p["key"]: p["severity"] for p in probs}
    assert got == {
        "run_phasemap.yml_failed": "WARNING",
        "run_confluence.yml_failed": "WARNING",
        "run_scan.yml_failed": "CRITICAL",
        "run_crypto_bot.yml_failed": "CRITICAL",
        "run_kill_switch.yml_failed": "CRITICAL",
        "run_backup_book.yml_failed": "CRITICAL",
    }
    msg = next(p["msg"] for p in probs if p["key"] == "run_scan.yml_failed")
    assert "FAILED 1.0h ago" in msg and "last success 5.0h ago" in msg
    assert "2 consecutive" in msg and "assert_staged FAILED" in msg
    assert msg.isascii()
    # A failed run is ONE finding per workflow: the staleness verdict is
    # folded into its message rather than raised beside it.
    assert not any(p["key"] == "run_scan.yml" for p in probs)

    # ...and the SAME facts in GitHub mode stay silent (the rule there).
    by = {wf: [_run(0.5)] for wf in config.WATCHDOG_RUNS}
    by["scan.yml"] = [_run(1.0, "failure"), _run(5.0)]
    notes = []
    assert wd.probe_runs(_runs_fetch(by), NOW, repo="x/y", notes=notes) == []
    assert any("scan.yml" in n and "FAILED" in n for n in notes)


def test_ledger_failed_finding_is_raised_once_and_recovered_by_the_state_machine(tmp_path):
    """Same dedupe / remind / recover discipline as every other finding: the
    first failed run alerts, the next probe with the failure still standing
    does NOT re-alert, and a real success afterwards recovers the key."""
    led = _all_fresh_ledger()
    led["kill_switch.yml"] = _lrow(success_h=3.5, failure_h=0.5)
    path = _ledger(tmp_path, led)
    f1 = wd.probe_ledger(path, NOW)
    state, alerts, rec = wd.reconcile({}, f1, NOW)
    assert [a["key"] for a in alerts] == ["run_kill_switch.yml_failed"] and rec == []

    t2 = NOW + dt.timedelta(minutes=30)
    state, alerts, rec = wd.reconcile(state, wd.probe_ledger(path, t2), t2)
    assert alerts == [] and rec == []                     # still failed, no spam

    # the 01:00 timer succeeded: last_success_at is now newer than the failure
    led["kill_switch.yml"] = _lrow(success_h=-1.0, failure_h=0.5)
    path = _ledger(tmp_path, led)
    t3 = NOW + dt.timedelta(hours=1.1)
    f3 = wd.probe_ledger(path, t3)
    assert f3 == []
    state, alerts, rec = wd.reconcile(state, f3, t3)
    assert rec == ["run_kill_switch.yml_failed"] and state == {}


def test_ledger_a_gate_skip_counts_as_a_concluded_success(tmp_path):
    """crypto_bot's :52 backstop skips ~24 times a day. On Actions each skip
    is a green run, so the 3h WARNING never fires while the scanner is merely
    declining to double-scan. The ledger must reproduce that or the alarm
    rings every half hour on a healthy box."""
    led = _all_fresh_ledger()
    led["crypto_bot.yml"] = _lrow(success_h=5.0, skip_h=0.3)    # limit 3h
    assert wd.probe_ledger(_ledger(tmp_path, led), NOW) == []
    led["crypto_bot.yml"] = _lrow(success_h=5.0)
    probs = wd.probe_ledger(_ledger(tmp_path, led), NOW)
    assert [(p["key"], p["severity"]) for p in probs] == [("run_crypto_bot.yml", "WARNING")]


def test_ledger_a_skip_does_not_bury_a_failure(tmp_path):
    """The one place a skip is NOT a success: after a failed run, a gate skip
    refreshes nothing -- the job that failed has still not done its work.
    (On GitHub the newest-concluded rule would look at the skip and go quiet;
    that is the silence the ledger mode exists to end.)"""
    led = _all_fresh_ledger()
    led["scan.yml"] = _lrow(success_h=5.0, failure_h=1.0, skip_h=0.1)
    probs = wd.probe_ledger(_ledger(tmp_path, led), NOW)
    assert [p["key"] for p in probs] == ["run_scan.yml_failed"]


def test_ledger_a_failure_is_only_a_failure_when_strictly_newer_than_the_success(tmp_path):
    """DESIGN 3.6: `last_failure_at` NEWER than `last_success_at`. Equal
    stamps (the ledger keeps whole seconds) are not newer, and the row's own
    last_status already says which one landed last -- the finding is for a
    failure the success has not yet answered, not for a tie."""
    led = _all_fresh_ledger()
    led["phasemap.yml"] = _lrow(success_h=1.0, failure_h=1.0)
    assert wd.probe_ledger(_ledger(tmp_path, led), NOW) == []
    led["phasemap.yml"] = _lrow(success_h=1.0, failure_h=1.0 - 1 / 3600)   # one second newer
    assert [p["key"] for p in wd.probe_ledger(_ledger(tmp_path, led), NOW)] == ["run_phasemap.yml_failed"]


def test_ledger_a_failure_with_no_success_ever_is_a_failure(tmp_path):
    led = _all_fresh_ledger()
    led["backup_book.yml"] = _lrow(failure_h=2.0)
    probs = wd.probe_ledger(_ledger(tmp_path, led), NOW)
    assert [(p["key"], p["severity"]) for p in probs] == [("run_backup_book.yml_failed", "CRITICAL")]
    assert "last success never" in probs[0]["msg"]


def test_ledger_a_halted_row_says_so(tmp_path):
    """HALT (a non-VPS data commit upstream) is recorded as a failure with
    last_status=halted; the alert must name it, because the operator action
    (accept-upstream / clear-halt) is different from a crash's."""
    led = _all_fresh_ledger()
    led["scan.yml"] = _lrow(success_h=3.0, failure_h=0.2, last_status="halted", last_exit=4)
    probs = wd.probe_ledger(_ledger(tmp_path, led), NOW)
    assert probs[0]["key"] == "run_scan.yml_failed" and "HALTED" in probs[0]["msg"]
    assert "state/HALT" in probs[0]["msg"]


def test_ledger_absent_key_is_the_same_never_ran_note_github_gives_an_empty_list(tmp_path):
    led = _all_fresh_ledger()
    del led["confluence.yml"]
    led["reco_note.yml"] = {"host": "vps"}          # a row with no stamps at all
    notes_ld = []
    probs = wd.probe_ledger(_ledger(tmp_path, led), NOW, notes=notes_ld)
    assert probs == []
    by = {wf: [_run(0.5)] for wf in config.WATCHDOG_RUNS}
    by["confluence.yml"] = []
    by["reco_note.yml"] = []
    notes_gh = []
    wd.probe_runs(_runs_fetch(by), NOW, repo="x/y", notes=notes_gh)
    assert notes_ld == notes_gh
    assert notes_ld == ["confluence.yml: no recorded runs yet",
                        "reco_note.yml: no recorded runs yet"]


def test_ledger_missing_file_is_a_fresh_box_not_a_fault(tmp_path):
    notes = []
    assert wd.probe_ledger(tmp_path / "nope.json", NOW, notes=notes) == []
    assert len(notes) == len(config.WATCHDOG_RUNS)
    assert all(n.endswith("no recorded runs yet") for n in notes)


def test_ledger_unreadable_file_is_a_warning_because_nothing_else_would_say_so(tmp_path):
    p = tmp_path / "runs.json"
    p.write_text("{not json", encoding="utf-8")
    probs = wd.probe_ledger(p, NOW)
    assert [(q["key"], q["severity"]) for q in probs] == [("runs_ledger_unreadable", "WARNING")]
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert [q["key"] for q in wd.probe_ledger(p, NOW)] == ["runs_ledger_unreadable"]


def test_ledger_messages_stay_ascii_whatever_the_last_line_carried(tmp_path):
    led = _all_fresh_ledger()
    led["phasemap.yml"] = _lrow(success_h=5.0, failure_h=1.0,
                                last_line="→ Yahoo — throttled ⚠ " + "x" * 300)
    probs = wd.probe_ledger(_ledger(tmp_path, led), NOW)
    assert probs[0]["msg"].isascii() and len(probs[0]["msg"]) < 400


def test_ledger_mode_imports_nothing_from_the_runner_package():
    """The two components meet ONLY at the file (deploy/DESIGN.md section 2):
    the watchdog parses the documented fields itself."""
    import re
    src = pathlib.Path(wd.__file__).read_text(encoding="utf-8")
    # Match the IMPORT, not the word: the docstring legitimately says why the
    # package is not imported, and prose is not a coupling. An import is.
    assert not re.search(r"^\s*(from\s+(scanner\.vps|\.vps|\.\s*import\s+vps)|import\s+scanner\.vps)",
                         src, re.M), "watchdog.py imports the runner package"
    for field in ("last_success_at", "last_failure_at", "last_skip_at"):
        assert field in src


def test_the_failed_critical_set_covers_the_book_writers_and_the_table_criticals():
    crit = set(config.VPS_WATCHDOG_FAILED_CRITICAL)
    assert crit <= set(config.WATCHDOG_RUNS), "every override must name a probed workflow"
    table_crit = {wf for wf, s in config.WATCHDOG_RUNS.items() if s["severity"] == "CRITICAL"}
    assert table_crit <= crit, "a table-CRITICAL workflow cannot fail at a lower severity"
    writers = set(config.VPS_BOOK_WRITER_JOBS) & set(config.WATCHDOG_RUNS)
    assert writers <= crit, "a failed BOOK WRITER is always CRITICAL"


# ── disk_low ───────────────────────────────────────────────────────────────────

_Usage = collections.namedtuple("usage", "total used free")
_GIB = 1 << 30


def test_disk_low_is_critical_below_the_config_floor(monkeypatch, tmp_path):
    monkeypatch.setattr(wd.shutil, "disk_usage",
                        lambda p: _Usage(100 * _GIB, 99 * _GIB, (config.VPS_DISK_MIN_GB - 0.5) * _GIB))
    probs = wd.probe_disk(tmp_path)
    assert [(p["key"], p["severity"]) for p in probs] == [("disk_low", "CRITICAL")]
    assert f"limit {config.VPS_DISK_MIN_GB:g} GiB" in probs[0]["msg"]
    monkeypatch.setattr(wd.shutil, "disk_usage",
                        lambda p: _Usage(100 * _GIB, 1 * _GIB, (config.VPS_DISK_MIN_GB + 0.5) * _GIB))
    assert wd.probe_disk(tmp_path) == []


def test_disk_probe_failure_is_a_note_and_zero_switches_it_off(monkeypatch, tmp_path):
    def boom(p):
        raise OSError("statvfs failed")
    monkeypatch.setattr(wd.shutil, "disk_usage", boom)
    notes = []
    assert wd.probe_disk(tmp_path, notes=notes) == []
    assert notes and "disk probe failed" in notes[0]
    assert wd.probe_disk(tmp_path, min_gb=0) == []


# ── the mode switch inside run() ───────────────────────────────────────────────

def _no_github(monkeypatch):
    """A RECORDING stub, deliberately not a raising one: probe_runs catches
    every per-workflow exception into a note, so a stub that raised would be
    swallowed and the test would pass against a watchdog that still asked
    GitHub (found by mutation, 2026-09-27). Callers assert the list is empty."""
    asked = []

    def record(url, *a, **k):
        asked.append(str(url))
        return {"workflow_runs": []}
    monkeypatch.setattr(urllib.request, "urlopen", record)
    monkeypatch.setattr(wd, "_default_fetch", record)
    return asked


def test_ledger_mode_never_calls_the_github_api(monkeypatch, tmp_path):
    """With VIVEK_RUNS_LEDGER set, run() must not touch GitHub even when
    GITHUB_REPOSITORY and a token are present -- after cutover that history
    is stale for every key and would page about all eight workflows."""
    asked = _no_github(monkeypatch)
    monkeypatch.setattr(wd.shutil, "disk_usage", lambda p: _Usage(100 * _GIB, _GIB, 90 * _GIB))
    monkeypatch.setenv("GITHUB_REPOSITORY", "x/y")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_notused")
    monkeypatch.setenv("WATCHDOG_STATE", str(tmp_path / "state.json"))
    led = _all_fresh_ledger()
    led["kill_switch.yml"] = _lrow(success_h=3.0, failure_h=0.5)
    monkeypatch.setenv("VIVEK_RUNS_LEDGER", str(_ledger(tmp_path, led)))
    assert not hasattr(wd, "requests"), "the watchdog must stay on urllib alone"

    res = wd.run(dry_run=True, now=NOW, root=_tree(tmp_path / "tree"))
    assert asked == [], f"ledger mode contacted GitHub: {asked}"
    assert not any("fetch failed" in n or "no GITHUB_REPOSITORY" in n for n in res["notes"]), \
        "the GitHub probe ran (and merely failed) in ledger mode"
    keys = {f["key"] for f in res["findings"]}
    assert keys == {"run_kill_switch.yml_failed"}
    assert any("runs ledger" in n for n in res["notes"])
    assert not (tmp_path / "state.json").exists()          # dry run writes nothing


def test_github_mode_is_untouched_when_the_ledger_env_is_absent(monkeypatch, tmp_path):
    """The switch is the env var and nothing else: unset, run() still asks the
    Actions API (proving the test above measured the switch, not a broken
    fetch) and the disk probe stays off (it is a VPS concern)."""
    monkeypatch.delenv("VIVEK_RUNS_LEDGER", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "x/y")
    monkeypatch.setenv("WATCHDOG_STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(wd.shutil, "disk_usage", lambda p: _Usage(100 * _GIB, 100 * _GIB, 0))
    asked = []
    by = {wf: [_run(0.5)] for wf in config.WATCHDOG_RUNS}
    fetch = _runs_fetch(by)

    def recorder(url):
        asked.append(url)
        return fetch(url)
    monkeypatch.setattr(wd, "_default_fetch", recorder)
    res = wd.run(dry_run=True, now=NOW, root=_tree(tmp_path / "tree"))
    assert len(asked) == len(config.WATCHDOG_RUNS)
    assert not any(f["key"] == "disk_low" for f in res["findings"])
    assert not any("runs ledger" in n for n in res["notes"])


def test_ledger_mode_runs_the_disk_probe(monkeypatch, tmp_path):
    asked = _no_github(monkeypatch)
    monkeypatch.setattr(wd.shutil, "disk_usage", lambda p: _Usage(100 * _GIB, 100 * _GIB, 0))
    monkeypatch.setenv("WATCHDOG_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("VIVEK_RUNS_LEDGER", str(_ledger(tmp_path, _all_fresh_ledger())))
    res = wd.run(dry_run=True, now=NOW, root=_tree(tmp_path / "tree"))
    assert [f["key"] for f in res["findings"]] == ["disk_low"] and asked == []


def test_ledger_mode_findings_persist_through_the_real_state_file(monkeypatch, tmp_path):
    """Not a dry run: the failed-run finding is written to WATCHDOG_STATE
    through the same reconcile path as every GitHub-mode finding, and a
    second live run neither re-alerts nor loses the breach start."""
    asked = _no_github(monkeypatch)
    monkeypatch.setattr(wd.shutil, "disk_usage", lambda p: _Usage(100 * _GIB, _GIB, 90 * _GIB))
    monkeypatch.setattr(wd, "_dispatch", lambda sev, text: [])      # channels are unconfigured
    state = tmp_path / "state.json"
    monkeypatch.setenv("WATCHDOG_STATE", str(state))
    led = _all_fresh_ledger()
    led["crypto_bot.yml"] = _lrow(success_h=2.0, failure_h=0.4)
    monkeypatch.setenv("VIVEK_RUNS_LEDGER", str(_ledger(tmp_path, led)))
    tree = _tree(tmp_path / "tree")
    r1 = wd.run(dry_run=False, now=NOW, root=tree)
    assert [a["key"] for a in r1["alerted"]] == ["run_crypto_bot.yml_failed"]
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert set(saved) == {"run_crypto_bot.yml_failed"}
    r2 = wd.run(dry_run=False, now=NOW + dt.timedelta(minutes=20), root=tree)
    assert r2["alerted"] == [] and r2["recovered"] == []
    assert json.loads(state.read_text(encoding="utf-8"))["run_crypto_bot.yml_failed"]["first"] == saved["run_crypto_bot.yml_failed"]["first"]
    assert asked == []
