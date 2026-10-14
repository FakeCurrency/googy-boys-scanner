"""decision_replay.yml -- the pins (REFINE200 #5, 2026-10-14).

A READ-ONLY evidence run: it replays the live hc4-1 rules and the decision
variants and delivers the tables to the step summary plus the JSON report as
an artifact. What is pinned is that it stays read-only (no write permission,
no git writes, nothing under public/data), that it runs the parity replay the
decision pack comes from, and that its triggers are the ones a cloud session
can actually pull (a dispatch, or a push of the kick file). The workflow-wide
rules (valid shell, declared permissions, first-party actions) are
tests/test_workflow_hardening.py's.
"""

from __future__ import annotations

import pathlib
import re

import yaml

from scanner import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF_PATH = ROOT / ".github" / "workflows" / "decision_replay.yml"
WF = WF_PATH.read_text(encoding="utf-8")
DOC = yaml.safe_load(WF)
ON = DOC.get("on") or DOC[True]                 # PyYAML reads a bare `on:` as True
JOB = DOC["jobs"]["replay"]
KICK = ".github/replay-kick"
CODE = "\n".join(line for line in WF.splitlines() if not line.lstrip().startswith("#"))


def _runs() -> list[str]:
    return [s["run"] for s in JOB["steps"] if "run" in s]


def _step(uses_prefix: str) -> dict:
    return next(s for s in JOB["steps"] if str(s.get("uses", "")).startswith(uses_prefix))


def test_it_is_read_only():
    assert DOC["permissions"] == {"contents": "read"}
    assert "permissions" not in JOB or JOB["permissions"] == {"contents": "read"}
    assert "write" not in CODE.split("jobs:")[0], "no write scope anywhere"
    for banned in ("git add", "git commit", "git push", "assert_staged"):
        assert banned not in CODE, f"a read-only replay must not contain '{banned}'"
    assert "decision_replay.yml" not in str(getattr(config, "WATCHDOG_RUNS", {})), (
        "it commits nothing, so it has no freshness to watch")


def test_the_triggers_are_a_dispatch_or_the_kick_file_on_any_branch():
    assert ON["push"]["paths"] == [KICK]
    assert "branches" not in ON["push"], "the kick must work from a work branch too"
    assert "schedule" not in ON
    inputs = ON["workflow_dispatch"]["inputs"]
    assert {k: str(v["default"]) for k, v in inputs.items()} == {
        "limit": "300", "period": "5y", "markets": "all"}
    kick = ROOT / KICK
    assert kick.is_file(), "the kick file the push trigger watches must exist"
    ds = yaml.safe_load((ROOT / ".github/workflows/dispatch_scan.yml").read_text(encoding="utf-8"))
    assert KICK not in str(ds.get("on") or ds[True]), "a replay kick must never fire a scan"


def test_it_runs_the_parity_replay_into_runner_temp():
    run = "\n".join(_runs())
    joined = re.sub(r"\\\n\s*", " ", run)                 # fold the line continuations
    cmd = re.search(r"python -m scanner\.vivek_backtest --parity [^\n]*", joined)
    assert cmd, "the parity replay command is gone"
    cmd = cmd.group(0)
    for want in ('--market "$MKT"', '--limit "$LIM"', '--period "$PER"', "--workers 0",
                 '--summary-md "$GITHUB_STEP_SUMMARY"', '--out "$OUT/decision_replay.json"'):
        assert want in cmd, want
    assert 'OUT="$RUNNER_TEMP/decision-replay"' in run
    assert "public/data" not in cmd, "the report must never be written into the site"
    assert 'LIM="${IN_LIMIT:-300}"' in run and 'PER="${IN_PERIOD:-5y}"' in run
    # free-text inputs reach the shell through env, never by interpolation
    assert not any("${{" in r for r in _runs())
    assert "set -o pipefail" in run and "| tee" in run, "a tee'd failure must stay a failure"


def test_the_inputs_are_validated_before_they_reach_python():
    run = "\n".join(_runs())
    assert re.search(r'case "\$LIM" in .*exit 2', run)
    assert re.search(r'case "\$PER" in .*exit 2', run)
    assert re.search(r'case "\$MKT" in all\|asx\|nasdaq\|crypto\)', run)


def test_the_report_is_uploaded_even_when_the_run_fails():
    up = _step("actions/upload-artifact@v4")
    assert up.get("if") == "always()"
    assert up["with"]["retention-days"] == 30
    assert up["with"]["path"].startswith("${{ runner.temp }}/decision-replay")


def test_a_write_under_public_data_turns_the_run_red():
    guard = next(s for s in JOB["steps"] if "git status --porcelain -- public/data" in s.get("run", ""))
    assert guard.get("if") == "always()"
    assert "exit 1" in guard["run"]


def test_its_own_group_and_a_bounded_runtime():
    group = str(DOC["concurrency"]["group"])
    assert group.startswith("decision-replay-") and "github.ref_name" in group
    assert "scan" not in group, "the scan mutex is for book writers"
    assert DOC["concurrency"]["cancel-in-progress"] is False
    assert JOB["timeout-minutes"] == 330, "inside GitHub's 360-minute job ceiling"
