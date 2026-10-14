"""phasemap.yml — every market's outcome travels as data (REFINE200 #198).

The scan step used to end `[ "$RC_ASX" -eq 0 ] && [ "$RC_NAS" -eq 0 ]`: one
market's crash turned the step red, so the Specs, schema-gate and commit
steps never ran and the healthy markets' fresh snapshots were discarded —
the run-#63 blast radius, one step earlier than the 2026-09-01 fix reached.
phasemap.run now names each outcome with its exit code (0 published,
3 carried, 4 refused, else failed) and the commit step turns those into the
must-change gate and the run's verdict. These tests EXECUTE the shipped
shell and Python blocks rather than grepping for them.
"""

import json
import os
import pathlib
import subprocess
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows" / "phasemap.yml"


def _steps():
    return {s.get("name"): s for s in
            yaml.safe_load(WF.read_text(encoding="utf-8"))["jobs"]["phasemap"]["steps"]}


def test_the_scan_step_never_fails_and_reports_every_market():
    step = _steps()["Run PhaseMap scans"]
    assert step.get("id") == "scan"
    run = step["run"]
    assert '-eq 0 ] &&' not in run, "a red scan step discards the healthy markets"
    for m in ("asx", "nasdaq", "crypto"):
        assert f'echo "rc_{m}=' in run
    assert 'echo "rc_${MARKET}=$RC" >> "$GITHUB_OUTPUT"' in run
    assert run.rstrip().endswith("exit 0")


@pytest.mark.parametrize("name", ["Verify PhaseMap snapshots",
                                  "Commit & push fresh data (triggers Cloudflare deploy)"])
def test_the_gates_read_every_markets_outcome(name):
    env = _steps()[name]["env"]
    for m, key in (("asx", "RC_ASX"), ("nasdaq", "RC_NASDAQ"), ("crypto", "RC_CRYPTO")):
        assert env[key] == f"${{{{ steps.scan.outputs.rc_{m} }}}}"


# ── the commit step's per-market gate, executed ────────────────────────────

def _gate_block():
    run = _steps()["Commit & push fresh data (triggers Cloudflare deploy)"]["run"]
    start = run.index("GATE_FAILED=0")
    end = run.index("\ndone\n", start) + len("\ndone")
    return run[start:end]


def _run_gate(tmp_path, event, rcs, assert_ok=True):
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "assert_staged.sh").write_text(
        'echo "ASSERT $1 $2" >> asserts.log\n'
        f'exit {0 if assert_ok else 1}\n', encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "GITHUB_EVENT_NAME": event,
           "RC_ASX": rcs[0], "RC_NASDAQ": rcs[1], "RC_CRYPTO": rcs[2]}
    p = subprocess.run(["bash", "-e", "-c", _gate_block() + '\necho "GATE=$GATE_FAILED"'],
                       cwd=tmp_path, env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    log = (tmp_path / "asserts.log")
    return p.stdout, (log.read_text().splitlines() if log.exists() else [])


def test_only_a_market_that_published_is_asserted(tmp_path):
    out, asserts = _run_gate(tmp_path, "schedule", ("0", "3", ""))
    assert "GATE=0" in out
    assert asserts == ["ASSERT phasemap asx public/data/phasemap/asx/latest.json",
                       "ASSERT phasemap asx confluence public/data/phasemap/asx/confluence.json"]
    assert "carried forward" in out and "crypto: not run" in out


@pytest.mark.parametrize("rc", ["4", "1", "137"])
def test_a_refused_or_failed_market_reddens_the_run_without_stopping_it(tmp_path, rc):
    out, asserts = _run_gate(tmp_path, "schedule", (rc, "0", "0"))
    assert "GATE=1" in out and "::error::phasemap asx" in out
    assert len(asserts) == 4, "the healthy markets are still gated"


def test_a_published_market_that_staged_nothing_trips_the_gate(tmp_path):
    out, _ = _run_gate(tmp_path, "schedule", ("0", "0", "0"), assert_ok=False)
    assert "GATE=1" in out


def test_by_hand_an_unstaged_publish_only_warns(tmp_path):
    out, _ = _run_gate(tmp_path, "workflow_dispatch", ("0", "", ""), assert_ok=False)
    assert "GATE=0" in out and "::warning::phasemap asx" in out


# ── the schema gate, executed ──────────────────────────────────────────────

def _schema_script():
    run = _steps()["Verify PhaseMap snapshots"]["run"]
    return run[run.index("<<'PY'\n") + len("<<'PY'\n"):run.rindex("\nPY")]


def _publish(tmp_path, market, ruleset=None, conf_rows=None):
    from phasemap.output.writer import build_snapshot, split_narrations
    from phasemap.narrate.templates import DISCLAIMER
    rec = {"ticker": "AAA", "direction": "bullish", "state": "SWEPT", "tier": "Watch",
           "tags": [], "regime": "ROTATION", "zones": [], "metrics": {}, "smt": None,
           "route_to": None, "narration": "x " + DISCLAIMER}
    snap = build_snapshot("2026-10-14", 1, [rec])
    if ruleset:
        snap["ruleset_version"] = ruleset
    slim, narr = split_narrations(snap)
    d = tmp_path / "public" / "data" / "phasemap" / market
    d.mkdir(parents=True)
    (d / "latest.json").write_text(json.dumps(slim), encoding="utf-8")
    (d / "narrations.json").write_text(json.dumps(narr), encoding="utf-8")
    rows = conf_rows if conf_rows is not None else \
        [{"ticker": "AAA", "direction": "bullish", "state": "SWEPT"}]
    (d / "confluence.json").write_text(json.dumps(
        {"schema_version": 1, "run_date": "2026-10-14", "generated_at": "x",
         "rows": rows}), encoding="utf-8")


def _schema(tmp_path, **rcs):
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(ROOT)}
    env.update({f"RC_{k.upper()}": v for k, v in rcs.items()})
    return subprocess.run([sys.executable, "-c", _schema_script()], cwd=tmp_path,
                          env=env, capture_output=True, text=True)


def test_the_schema_gate_passes_a_matching_pair(tmp_path):
    _publish(tmp_path, "asx")
    p = _schema(tmp_path, asx="0")
    assert p.returncode == 0, p.stdout + p.stderr


def test_the_schema_gate_rejects_a_confluence_file_that_drifted(tmp_path):
    _publish(tmp_path, "asx", conf_rows=[{"ticker": "AAA", "direction": "bullish",
                                          "state": "RUNNING"}])
    p = _schema(tmp_path, asx="0")
    assert p.returncode == 1 and "confluence.json: does not match" in p.stdout


def test_a_refused_markets_old_ruleset_does_not_block_the_commit(tmp_path):
    _publish(tmp_path, "asx", ruleset="0.0.1")
    assert _schema(tmp_path, asx="4").returncode == 0
    assert _schema(tmp_path, asx="0").returncode == 1
