"""Freshness watchdog (2026-07-20, Phase 5).

Pins the three things that make the watchdog trustworthy: the probe maths
(content + run-history), the noise discipline (first alert / 6h reminder /
recovery, never per-check spam), and the failure-suppression rule (a RED run
is GitHub's to email about — the watchdog only speaks for silent problems).
No network anywhere: the run-history fetcher and the endpoint probe's status
getter are both injected, and the two tests that exercise the real
`_default_status` monkeypatch `urlopen` itself.
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


# ── live-endpoint probes (services that commit nothing) ───────────────────────

def _status(code, body=""):
    """A fetch_status stub that records the URL it was asked for."""
    seen = []

    def fetch(url):
        seen.append(url)
        return code, body
    fetch.seen = seen
    return fetch


def test_tick_401_is_the_healthy_answer():
    """Configured and refusing an anonymous caller is exactly right - silence.

    This is the one that must never be 'fixed' into a finding: the probe is
    deliberately unauthenticated, so a working deployment ALWAYS answers 401.
    """
    assert wd.probe_endpoints(_status(401), NOW) == []


def test_tick_503_is_a_warning_naming_the_missing_secret():
    probs = wd.probe_endpoints(_status(503), NOW)
    assert [p["key"] for p in probs] == ["tick_not_configured"]
    assert probs[0]["severity"] == "WARNING"
    assert "TICK_SECRET" in probs[0]["msg"]


def test_tick_200_unauthenticated_is_critical_because_it_means_wide_open():
    """200 to a request carrying no secret = anyone can walk every journal."""
    probs = wd.probe_endpoints(_status(200, '{"ok":true}'), NOW)
    assert [p["key"] for p in probs] == ["tick_endpoint_open"]
    assert probs[0]["severity"] == "CRITICAL"


def test_tick_unreachable_and_other_codes_are_warnings():
    for code in (0, 500, 502, 404):
        probs = wd.probe_endpoints(_status(code), NOW)
        assert [p["key"] for p in probs] == ["tick_unreachable"], code
        assert probs[0]["severity"] == "WARNING"
    # code 0 is the transport-failure sentinel and must read as unreachable,
    # not as "HTTP 0" - a status code that does not exist.
    assert "unreachable" in wd.probe_endpoints(_status(0), NOW)[0]["msg"]
    assert "HTTP 0" not in wd.probe_endpoints(_status(0), NOW)[0]["msg"]


def test_tick_probe_is_never_sent_a_credential():
    """The monitor must not run an extra tick. It asks anonymously, always.

    probe_endpoints has no way to pass auth by construction (fetch_status takes
    a URL and nothing else); this pins the URL it asks for so a future 'probe
    it properly' change that appends ?secret=... to the config fails here.
    """
    f = _status(401)
    wd.probe_endpoints(f, NOW)
    assert f.seen == [config.WATCHDOG_TICK_URL]
    assert "secret" not in config.WATCHDOG_TICK_URL.lower()
    assert "?" not in config.WATCHDOG_TICK_URL


def test_tick_probe_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(config, "WATCHDOG_TICK_ENABLED", False)
    f = _status(503)
    assert wd.probe_endpoints(f, NOW) == []
    assert f.seen == []          # switched off means not even asked


def test_tick_probe_blank_url_is_silent(monkeypatch):
    monkeypatch.setattr(config, "WATCHDOG_TICK_URL", "")
    assert wd.probe_endpoints(_status(503), NOW) == []


def test_tick_findings_ride_the_same_dedupe_as_every_other_finding():
    """The whole point of moving this off `exit 1`: it is said ONCE.

    stop_watcher.yml fires 288 times a day. Before this, each failure was a
    separate red run and a separate email. Here the finding is raised on every
    probe and the state machine still alerts exactly once until the renotify
    interval elapses.
    """
    probs = wd.probe_endpoints(_status(503), NOW)
    state, alerts, _ = wd.reconcile({}, probs, NOW)
    assert [a["key"] for a in alerts] == ["tick_not_configured"]
    # every subsequent probe inside the interval is silent
    for minutes in (5, 10, 60, 120):
        later = NOW + dt.timedelta(minutes=minutes)
        state, alerts, _ = wd.reconcile(state, wd.probe_endpoints(_status(503), later), later)
        assert alerts == [], minutes
    # ...and it recovers once when Cloudflare is finally configured
    healed = NOW + dt.timedelta(hours=3)
    _, alerts, rec = wd.reconcile(state, wd.probe_endpoints(_status(401), healed), healed)
    assert alerts == [] and rec == ["tick_not_configured"]


def test_default_status_unpacks_http_errors_rather_than_raising():
    """urllib raises on 4xx/5xx; the probe must read those as status codes.

    This is the exact shape the live 503 arrives in: urlopen does not return a
    response object with .getcode() == 503, it raises. A probe that only
    handled the return path would report every fail-closed endpoint as
    unreachable (code 0) and word the alert wrongly.
    """
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 503, "x", {}, None)

    import scanner.watchdog as _wd
    orig = _wd.urllib.request.urlopen
    try:
        _wd.urllib.request.urlopen = fake_urlopen
        code, _body = _wd._default_status("https://example.invalid/api/tick")
    finally:
        _wd.urllib.request.urlopen = orig
    assert code == 503


def test_default_status_reports_zero_when_the_host_is_unreachable():
    def fake_urlopen(req, timeout=None):
        raise OSError("dns")

    import scanner.watchdog as _wd
    orig = _wd.urllib.request.urlopen
    try:
        _wd.urllib.request.urlopen = fake_urlopen
        code, body = _wd._default_status("https://example.invalid/api/tick")
    finally:
        _wd.urllib.request.urlopen = orig
    assert (code, body) == (0, "")


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
