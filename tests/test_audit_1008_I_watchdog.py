"""Audit #61 (2026-10-08): the watchdog must not announce a recovery it never
measured.

``reconcile`` counted every remembered key absent from this run's findings as
RECOVERED. ``probe_runs`` drops a workflow's finding WITHOUT measuring it when
the GitHub API fetch fails or the workflow's newest run failed (deliberately
silent - GitHub emails red runs). So an ongoing ``run_<wf>`` breach sent
"Watchdog recovered", lost its state, and alerted again on the next run as a
FIRST detection - alert / recovered / alert flapping that bypasses the
one-reminder-every-6h rule. These drive the SHIPPED ``run()`` end to end with
an injected fetcher, a temp state file and a captured dispatcher.
"""

import datetime as dt
import json

import pytest

from scanner import config
from scanner import watchdog as wd

pytestmark = pytest.mark.risk

NOW = dt.datetime(2026, 10, 8, 2, 15, tzinfo=dt.timezone.utc)
WF = "backup_book.yml"
KEY = f"run_{WF}"


def _run(start, hours_ago, conclusion="success"):
    t = (start - dt.timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    return {"conclusion": conclusion, "run_started_at": t}


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Returns (step, sent): step(now, mode) runs the real watchdog once.

    mode "stale"  - backup_book's newest success is 30h old (CRITICAL breach)
    mode "down"   - the API raises for backup_book (cannot be measured)
    mode "red"    - backup_book's newest concluded run FAILED (stay quiet)
    mode "fresh"  - backup_book succeeded 10 minutes ago (a real recovery)
    Every other watched workflow is fresh throughout.
    """
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(wd, "ROOT", root)       # content probes: empty tree
    monkeypatch.setenv("GITHUB_REPOSITORY", "x/y")
    monkeypatch.setenv("WATCHDOG_STATE", str(tmp_path / "state.json"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    sent = []
    monkeypatch.setattr(wd, "_dispatch",
                        lambda sev, text: sent.append((sev, text)) or [])
    monkeypatch.setattr(wd, "session_hours_between", lambda a, b: 0.0)

    def step(now, mode):
        def fetch(url):
            if f"/workflows/{WF}/runs" not in url:
                return {"workflow_runs": [_run(now, 0.1)]}
            if mode == "down":
                raise RuntimeError("HTTP Error 502: Bad Gateway")
            if mode == "red":
                return {"workflow_runs": [_run(now, 0.2, "failure"),
                                          _run(now, 30.0)]}
            if mode == "fresh":
                return {"workflow_runs": [_run(now, 0.2)]}
            return {"workflow_runs": [_run(now, 30.0)]}
        monkeypatch.setattr(wd, "_default_fetch", fetch)
        sent.clear()
        out = wd.run(now=now)
        state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        return out, state, list(sent)
    return step


def _recovery_msgs(sent):
    return [t for _s, t in sent if "recovered" in t]


@pytest.mark.parametrize("blind", ["down", "red"])
def test_an_unmeasured_breach_is_not_recovered_and_does_not_re_alert(harness, blind):
    assert config.WATCHDOG_RUNS[WF]["max_age_h"] < 30, "fixture must breach"
    out, state, _ = harness(NOW, "stale")
    assert KEY in [f["key"] for f in out["alerted"]]
    first = state[KEY]["first"]

    # the probe goes blind: API down, or the backstop run failed
    later = NOW + dt.timedelta(minutes=30)
    out, state, sent = harness(later, blind)
    assert KEY not in out["recovered"]
    assert not any(KEY in t for t in _recovery_msgs(sent))
    assert state[KEY]["first"] == first          # the breach start survives
    assert any(KEY in n and "NOT a recovery" in n for n in out["notes"])

    # measurable again, still stale: inside the 6h window -> NO first-detection
    again = NOW + dt.timedelta(hours=1)
    out, state, sent = harness(again, "stale")
    assert KEY not in [f["key"] for f in out["alerted"]]
    assert state[KEY]["first"] == first


def test_a_real_recovery_after_a_blind_run_is_still_reported(harness):
    harness(NOW, "stale")
    harness(NOW + dt.timedelta(minutes=30), "down")
    out, state, sent = harness(NOW + dt.timedelta(hours=1), "fresh")
    assert out["recovered"] == [KEY]
    assert any(KEY in t for t in _recovery_msgs(sent))
    assert KEY not in state


def test_the_renotify_clock_still_runs_across_a_blind_run(harness):
    harness(NOW, "stale")
    harness(NOW + dt.timedelta(hours=3), "down")
    late = NOW + dt.timedelta(hours=config.WATCHDOG_RENOTIFY_HOURS + 0.1)
    out, _, _ = harness(late, "stale")
    assert KEY in [f["key"] for f in out["alerted"]]   # the ONE reminder


def test_no_repo_means_every_run_probe_is_unmeasured(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    unmeasured = set()
    assert wd.probe_runs(lambda u: {}, NOW, repo="", unmeasured=unmeasured) == []
    assert unmeasured == {f"run_{wf}" for wf in config.WATCHDOG_RUNS}


def test_probe_runs_names_what_it_could_not_measure():
    def fetch(url):
        if "/workflows/scan.yml/" in url:
            raise RuntimeError("timeout")
        if "/workflows/phasemap.yml/" in url:
            return {"workflow_runs": [{"conclusion": "failure",
                                       "run_started_at": NOW.isoformat()}]}
        if "/workflows/confluence.yml/" in url:
            return {"workflow_runs": [{"conclusion": None,
                                       "run_started_at": NOW.isoformat()}]}
        return {"workflow_runs": [{"conclusion": "success",
                                   "run_started_at": NOW.isoformat()}]}
    unmeasured = set()
    wd.probe_runs(fetch, NOW, repo="x/y", unmeasured=unmeasured)
    want = {f"run_{wf}" for wf in ("scan.yml", "phasemap.yml", "confluence.yml")
            if wf in config.WATCHDOG_RUNS}
    assert unmeasured == want


def test_reconcile_keeps_unmeasured_state_verbatim_and_still_recovers_the_rest():
    f = {"key": "a", "severity": "WARNING", "msg": "a"}
    g = {"key": "b", "severity": "WARNING", "msg": "b"}
    state, _, _ = wd.reconcile({}, [f, g], NOW)
    later = NOW + dt.timedelta(hours=1)
    state2, alerts, rec = wd.reconcile(state, [], later, unmeasured={"a"})
    assert alerts == [] and rec == ["b"]
    assert state2 == {"a": state["a"]}
    # a key that IS measured and present wins over the unmeasured hint
    state3, _, rec3 = wd.reconcile(state, [f], later, unmeasured={"a"})
    assert rec3 == ["b"] and state3["a"] == state["a"]
