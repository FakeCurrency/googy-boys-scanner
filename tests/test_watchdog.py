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


# ── job-judged run history (REFINE200 #80) ─────────────────────────────────────

def _jobs_fetch(by_wf, jobs_by_id, boom_jobs=False):
    """Runs per workflow plus a jobs API: {run id: {job name: conclusion}}."""
    def fetch(url):
        if "/actions/runs/" in url and "/jobs" in url:
            if boom_jobs:
                raise RuntimeError("jobs api down")
            rid = int(url.split("/actions/runs/")[1].split("/")[0])
            return {"jobs": [{"name": n, "conclusion": c}
                             for n, c in jobs_by_id.get(rid, {}).items()]}
        for wf, runs in by_wf.items():
            if f"/workflows/{wf}/runs" in url:
                return {"workflow_runs": runs}
        return {"workflow_runs": []}
    return fetch


def _rid(rid, hours_ago, conclusion="success"):
    return {"id": rid, "conclusion": conclusion, "run_started_at": _iso(hours_ago)}


def _fresh_except(**over):
    by = {wf: [_run(0.5)] for wf in config.WATCHDOG_RUNS}
    by.update(over)
    return by


def test_a_gate_skipped_scan_run_is_not_a_successful_scan(monkeypatch):
    """THE #80 BUG: scan.yml's gate skips the `scan` job on most superset
    crons and the RUN still concludes success, so a scan that has not run for
    30 session-hours read as healthy off a skip from half an hour ago."""
    monkeypatch.setattr(wd, "session_hours_between", lambda a, b: _age_h_of(a, b))
    by = _fresh_except(**{"scan.yml": [_rid(1, 0.5), _rid(2, 1.5), _rid(3, 30.0)]})
    jobs = {1: {"gate": "success", "scan": "skipped"},
            2: {"gate": "success", "scan": "skipped"},
            3: {"gate": "success", "scan": "success"}}
    probs = wd.probe_runs(_jobs_fetch(by, jobs), NOW, repo="x/y")
    assert [p["key"] for p in probs] == ["run_scan.yml"]
    assert "30.0h ago" in probs[0]["msg"]
    # the same history with a real scan half an hour ago is silent
    jobs[1]["scan"] = "success"
    assert wd.probe_runs(_jobs_fetch(by, jobs), NOW, repo="x/y") == []


def _age_h_of(a, b):
    return (b - a).total_seconds() / 3600.0


def test_a_jobs_api_error_falls_back_to_the_runs_own_conclusion():
    """Fail-quiet, like the runs API: an outage must not invent a finding."""
    by = _fresh_except(**{"scan.yml": [_rid(1, 0.5), _rid(3, 30.0)]})
    notes = []
    probs = wd.probe_runs(_jobs_fetch(by, {}, boom_jobs=True), NOW, repo="x/y",
                          notes=notes)
    assert probs == []
    assert any("scan.yml" in n and "jobs lookup failed" in n for n in notes)


def test_a_run_that_lists_no_such_job_keeps_its_own_conclusion():
    by = _fresh_except(**{"scan.yml": [_rid(1, 0.5)]})
    assert wd.probe_runs(_jobs_fetch(by, {1: {"other": "success"}}), NOW, repo="x/y") == []


def test_a_window_with_no_real_run_alarms_only_when_its_own_age_breaches(monkeypatch):
    """No run in the window did the work, so the newest real one is OLDER than
    the window: its age is a lower bound. Breach -> finding; else a note."""
    monkeypatch.setattr(wd, "session_hours_between", lambda a, b: _age_h_of(a, b))
    skipped = {i: {"scan": "skipped"} for i in range(1, 4)}
    old = _fresh_except(**{"scan.yml": [_rid(1, 1.0), _rid(2, 5.0), _rid(3, 20.0)]})
    probs = wd.probe_runs(_jobs_fetch(old, skipped), NOW, repo="x/y")
    assert [p["key"] for p in probs] == ["run_scan.yml"]
    assert "no run of its `scan` job succeeded in the last 3 runs" in probs[0]["msg"]
    young = _fresh_except(**{"scan.yml": [_rid(1, 1.0), _rid(2, 2.0), _rid(3, 3.0)]})
    notes = []
    assert wd.probe_runs(_jobs_fetch(young, skipped), NOW, repo="x/y", notes=notes) == []
    assert any("inside the limit so far" in n for n in notes)


def test_the_jobs_lookups_are_capped(monkeypatch):
    monkeypatch.setattr(config, "WATCHDOG_JOB_LOOKUPS", 2)
    calls = []
    runs = [_rid(i, 0.1 * i) for i in range(1, 9)]
    base = _jobs_fetch(_fresh_except(**{"scan.yml": runs}),
                       {i: {"scan": "skipped"} for i in range(1, 9)})

    def fetch(url):
        if "/jobs" in url and "/runs/" in url:
            calls.append(url)
        return base(url)
    wd.probe_runs(fetch, NOW, repo="x/y")
    assert len([u for u in calls if "/runs/" in u]) == 2


def test_the_alarm_jobs_red_run_is_not_read_as_a_kill_switch_failure():
    """kill_switch.yml is judged by its `check` job: the watchdog-alarm job's
    red run (#77) must neither silence the kill-switch probe as 'GitHub
    emailed' nor count as a missing check."""
    by = _fresh_except(**{"kill_switch.yml": [_rid(7, 0.3, "failure")]})
    jobs = {7: {"check": "success", "Watchdog CRITICAL (the kill-switch check itself passed)": "failure"}}
    notes = []
    assert wd.probe_runs(_jobs_fetch(by, jobs), NOW, repo="x/y", notes=notes) == []
    assert not any("kill_switch.yml" in n for n in notes)
    assert config.WATCHDOG_RUNS["kill_switch.yml"]["job"] == "check"


def test_the_judged_jobs_exist_in_their_workflows():
    """A renamed job would read as 'no such job' and silently fall back to the
    run's conclusion -- the very bug #80 fixed."""
    import yaml
    for wf, spec in config.WATCHDOG_RUNS.items():
        if spec.get("job"):
            doc = yaml.safe_load((wd.ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8"))
            job = doc["jobs"].get(spec["job"])
            assert job is not None, f"{wf} has no job {spec['job']!r}"
            assert "name" not in job, f"{wf}:{spec['job']} has a display name; the API reports that"


def test_the_backtest_workflows_are_watched_at_their_cadence():
    """REFINE200 #79: a weekly and a monthly evidence refresh, each alarming
    about a day after a dropped run -- never inside its own cadence."""
    import yaml
    for wf, cadence_h in (("lens_backtest.yml", 7 * 24), ("vivek_backtest.yml", 31 * 24)):
        spec = config.WATCHDOG_RUNS[wf]
        assert cadence_h < spec["max_age_h"] <= cadence_h + 48, wf
        doc = yaml.safe_load((wd.ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8"))
        crons = [c["cron"] for c in doc[True]["schedule"]]
        want = "0 8 * * 0" if wf == "lens_backtest.yml" else "0 8 1 * *"
        assert crons == [want], f"{wf} cadence moved: re-check its WATCHDOG_RUNS limit"


# ── the run page carries it (REFINE200 #77) ────────────────────────────────────

def _live_run(monkeypatch, tmp_path, findings, state=None, env=None, now=NOW):
    st = tmp_path / "state.json"
    if state is not None:
        st.write_text(json.dumps(state), encoding="utf-8")
    out = tmp_path / "gh_output"
    out.write_text("", encoding="utf-8")
    monkeypatch.setenv("WATCHDOG_STATE", str(st))
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("WATCHDOG_RAISE", raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(wd, "probe_content", lambda root, n: list(findings))
    monkeypatch.setattr(wd, "probe_runs", lambda fetch, n, notes=None: [])
    monkeypatch.setattr(wd, "_dispatch", lambda sev, text: [])
    res = wd.run(now=now)
    return res, json.loads(st.read_text(encoding="utf-8")), out.read_text(encoding="utf-8")


def test_a_due_finding_is_annotated_on_the_run_page(monkeypatch, tmp_path, capsys):
    _live_run(monkeypatch, tmp_path, [_f("book_stale", "CRITICAL"), _f("pm", "WARNING")])
    out = capsys.readouterr().out
    assert "::error title=Watchdog CRITICAL::book_stale" in out
    assert "::warning title=Watchdog WARNING::pm" in out


def test_a_finding_not_due_a_reminder_is_not_re_annotated(monkeypatch, tmp_path, capsys):
    state = {"book_stale": {"first": _iso(1), "last_alert": _iso(1)}}
    _live_run(monkeypatch, tmp_path, [_f("book_stale", "CRITICAL")], state=state)
    assert "::error" not in capsys.readouterr().out


def test_the_annotation_escapes_what_github_would_read_as_commands():
    a = wd._annotation("error", "a: b, c", "50% done\nnext")
    assert a == "::error title=a%3A b%2C c::50%25 done%0Anext"


def test_an_undelivered_alert_names_the_missing_secrets(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(config, "TELEGRAM_ENABLED", True)  # secrets-path test; the real flag is the owner's mute
    res, _, _ = _live_run(monkeypatch, tmp_path, [_f("book_stale", "CRITICAL")])
    out = capsys.readouterr().out
    assert "CRITICAL alert NOT delivered: telegram (secret(s) not set: " \
           "TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)" in out
    assert "GBS_SMTP_HOST" in out


# ── the red-run alarm (REFINE200 #77) ──────────────────────────────────────────

RAISE = {"WATCHDOG_RAISE": "1"}


def test_a_critical_is_raised_once_per_episode(monkeypatch, tmp_path):
    crit = [_f("book_stale", "CRITICAL")]
    res, state, out = _live_run(monkeypatch, tmp_path, crit, env=RAISE)
    assert [a["key"] for a in res["alarm"]] == ["book_stale"]
    assert out == "alarm=book_stale\n"
    assert state["book_stale"]["raised"] == NOW.isoformat(timespec="seconds")
    # next run: same episode -> no alarm, and the stamp survives a REMINDER
    later = NOW + dt.timedelta(hours=config.WATCHDOG_RENOTIFY_HOURS + 1)
    res2, state2, out2 = _live_run(monkeypatch, tmp_path, crit, env=RAISE, now=later)
    assert res2["alarm"] == [] and out2 == "alarm=\n"
    assert state2["book_stale"]["raised"] == state["book_stale"]["raised"]
    # recovery, then a NEW episode raises again
    _live_run(monkeypatch, tmp_path, [], env=RAISE, now=later)
    res3, _, _ = _live_run(monkeypatch, tmp_path, crit, env=RAISE, now=later)
    assert [a["key"] for a in res3["alarm"]] == ["book_stale"]


def test_a_critical_first_seen_by_the_other_host_is_raised_by_this_one(monkeypatch, tmp_path):
    seen = {"book_stale": {"first": _iso(0.4), "last_alert": _iso(0.4)}}   # crypto_bot alerted
    res, _, _ = _live_run(monkeypatch, tmp_path, [_f("book_stale", "CRITICAL")],
                          state=seen, env=RAISE)
    assert [a["key"] for a in res["alarm"]] == ["book_stale"]


def test_only_the_raising_host_and_only_criticals_raise(monkeypatch, tmp_path):
    res, _, out = _live_run(monkeypatch, tmp_path, [_f("book_stale", "CRITICAL")])
    assert res["alarm"] == [] and out == "alarm=\n"          # no WATCHDOG_RAISE
    res, _, _ = _live_run(monkeypatch, tmp_path, [_f("pm", "WARNING")], env=RAISE)
    assert res["alarm"] == []


def test_a_configured_critical_channel_carries_it_instead(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TELEGRAM_ENABLED", True)  # secrets-path test; the real flag is the owner's mute
    env = dict(RAISE, TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_CHAT_ID="-9")
    res, _, _ = _live_run(monkeypatch, tmp_path, [_f("book_stale", "CRITICAL")], env=env)
    assert res["alarm"] == []


def test_a_dry_run_raises_nothing_and_writes_nothing(monkeypatch, tmp_path):
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("WATCHDOG_RAISE", "1")
    monkeypatch.setenv("WATCHDOG_STATE", str(tmp_path / "state.json"))
    monkeypatch.setattr(wd, "probe_content", lambda root, n: [_f("book_stale", "CRITICAL")])
    monkeypatch.setattr(wd, "probe_runs", lambda fetch, n, notes=None: [])
    res = wd.run(dry_run=True, now=NOW)
    assert res["alarm"] == [] and not out.exists()
    assert not (tmp_path / "state.json").exists()


def test_the_kill_switch_workflow_raises_from_a_separate_job():
    """The alarm must fail a job that is NOT the kill-switch check: a red
    `check` would read as a failed kill switch and skip actions/cache's
    post-save, so the once-per-episode state would never persist."""
    import yaml
    doc = yaml.safe_load((wd.ROOT / ".github" / "workflows" / "kill_switch.yml").read_text(encoding="utf-8"))
    check = doc["jobs"]["check"]
    step = next(s for s in check["steps"] if s.get("name") == "Freshness watchdog")
    assert step["id"] == "watchdog" and step["env"]["WATCHDOG_RAISE"] == "1"
    assert step is check["steps"][-1], "the watchdog runs after the kill-switch check"
    assert check["outputs"]["watchdog_alarm"] == "${{ steps.watchdog.outputs.alarm }}"
    alarm = doc["jobs"]["watchdog-alarm"]
    assert alarm["needs"] == "check"
    assert alarm["if"] == "needs.check.outputs.watchdog_alarm != ''"
    assert alarm["permissions"] == {} and alarm["timeout-minutes"] <= 5
    assert "exit 1" in alarm["steps"][-1]["run"]
    crypto = (wd.ROOT / ".github" / "workflows" / "crypto_bot.yml").read_text(encoding="utf-8")
    assert "WATCHDOG_RAISE" not in crypto, "one raising host, so one red run per episode"


# ── channel diagnostics (REFINE200 #127) ──────────────────────────────────────

def test_the_telegram_mute_is_named_not_hidden(monkeypatch):
    """TELEGRAM_ENABLED stays the owner's mute (kept False in REFINE200), but a
    NOT-delivered line must name it rather than blame the secrets alone."""
    monkeypatch.setattr(config, "TELEGRAM_ENABLED", False)
    env = {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "42"}
    assert wd.channel_problem("telegram", env) == "muted by config.TELEGRAM_ENABLED = False"
    assert wd.channel_problem("telegram", {}) == (
        "muted by config.TELEGRAM_ENABLED = False; "
        "secret(s) not set: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID")


def test_channel_problem_names_the_real_reason(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_ENABLED", True)
    env = {}
    assert wd.channel_problem("telegram", env) == \
        "secret(s) not set: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"
    env = {"TELEGRAM_BOT_TOKEN": "﻿123:abc", "TELEGRAM_CHAT_ID": " "}
    assert wd.channel_problem("telegram", env) == "secret(s) not set: TELEGRAM_CHAT_ID"
    env["TELEGRAM_CHAT_ID"] = "-9"
    assert wd.channel_problem("telegram", env) == ""
    monkeypatch.setattr(config, "TELEGRAM_ENABLED", False)
    assert "TELEGRAM_ENABLED" in wd.channel_problem("telegram", env)
    assert wd.channel_problem("pigeon", env) == "no sender for this channel"


def test_the_self_test_says_why_each_channel_did_not_deliver(monkeypatch, capsys):
    monkeypatch.setattr(config, "TELEGRAM_ENABLED", True)  # secrets-path test; the real flag is the owner's mute
    monkeypatch.setattr(wd, "_dispatch", lambda sev, text: [])
    wd.test_alert()
    out = capsys.readouterr().out
    assert "NOT delivered: telegram (secret(s) not set: TELEGRAM_BOT_TOKEN, " \
           "TELEGRAM_CHAT_ID)" in out
    assert "unconfigured or failing" not in out
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-9")
    wd.test_alert()
    assert "telegram (configured, but the send failed" in capsys.readouterr().out


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
