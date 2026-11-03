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
import subprocess

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


def test_the_replay_job_is_read_only():
    """The REPLAY job: read token, no git writes. The commit-summary job
    (NEXT100 #14) is the one writer and is pinned apart below."""
    assert DOC["permissions"] == {"contents": "read"}
    assert "permissions" not in JOB or JOB["permissions"] == {"contents": "read"}
    assert "write" not in CODE.split("jobs:")[0], "no write scope at the workflow level"
    replay_code = "\n".join(l for l in "\n".join(_runs()).splitlines()
                            if not l.lstrip().startswith("#"))
    for banned in ("git add", "git commit", "git push", "assert_staged"):
        assert banned not in replay_code, f"a read-only replay must not contain '{banned}'"
    assert "decision_replay.yml" not in str(getattr(config, "WATCHDOG_RUNS", {})), (
        "it commits nothing on a clock, so it has no freshness to watch")


# -- NEXT100 #14: the slim summary is committed by a SECOND job ---------------

SUMMARY_JOB = DOC["jobs"]["commit-summary"]
SUMMARY_PATHS = ("data/research/decision_replay/summary.json",
                 "data/research/decision_replay/inputs.json")


def _summary_runs() -> list[str]:
    return [s["run"] for s in SUMMARY_JOB["steps"] if "run" in s]


def test_the_replay_writes_the_slim_summary_and_uploads_it_on_its_own():
    joined = re.sub(r"\\\n\s*", " ", "\n".join(_runs()))
    cmd = re.search(r"python -m scanner\.vivek_backtest --parity [^\n]*", joined).group(0)
    assert '--summary-dir "$OUT/summary"' in cmd, "the summary must be asked for explicitly"
    up = next(s for s in JOB["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact")
              and "summary" in str(s["with"]["name"]))
    assert up["with"]["name"] == "decision-replay-summary-${{ github.run_id }}"
    assert up["with"]["path"] == "${{ runner.temp }}/decision-replay/summary/"
    assert up["with"]["if-no-files-found"] == "error", "a replay that wrote no summary is lost output"
    assert "if" not in up, "only a successful replay uploads a verdict worth committing"
    assert config.VIVEK_PARITY_SUMMARY_DIR == "data/research/decision_replay"


def test_the_commit_job_follows_a_successful_replay_with_the_only_write_token():
    assert SUMMARY_JOB["needs"] == "replay"
    assert SUMMARY_JOB["if"] == "success()"
    assert SUMMARY_JOB["permissions"] == {"contents": "write"}
    assert isinstance(SUMMARY_JOB["timeout-minutes"], int) and SUMMARY_JOB["timeout-minutes"] <= 30
    writers = [name for name, job in DOC["jobs"].items()
               if (job.get("permissions") or {}).get("contents") == "write"]
    assert writers == ["commit-summary"]
    group = str(SUMMARY_JOB["concurrency"]["group"])
    assert group.startswith("decision-replay-summary-") and "github.ref_name" in group
    assert group != str(DOC["concurrency"]["group"])
    assert "scan" not in group, "not a book writer: it never joins the scan mutex"
    assert SUMMARY_JOB["concurrency"]["cancel-in-progress"] is False


def test_the_commit_job_checks_out_the_branch_tip_and_downloads_the_same_artifact():
    co = next(s for s in SUMMARY_JOB["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert co["with"]["ref"] == "${{ github.ref }}", "a queued commit must land on the tip, not the start SHA"
    dl = next(s for s in SUMMARY_JOB["steps"] if str(s.get("uses", "")).startswith("actions/download-artifact"))
    up = next(s for s in JOB["steps"] if "summary" in str((s.get("with") or {}).get("name", "")))
    assert dl["with"]["name"] == up["with"]["name"], "it must download what the replay uploaded"
    assert dl["with"]["path"] == "${{ runner.temp }}/decision-replay-summary"


def test_the_commit_job_stages_one_path_at_a_time_gates_on_both_and_pushes_with_retry():
    run = "\n".join(_summary_runs())
    code = "\n".join(l for l in run.splitlines() if not l.lstrip().startswith("#"))
    assert 'git add -- "$p"' in code and "git add -A" in code
    assert not re.search(r'git add -- "\$p" "\$', code), "one pathspec per git add"
    gate = next(l for l in code.splitlines() if "assert_staged.sh" in l)
    for p in SUMMARY_PATHS:
        assert f'"{p.replace("data/research/decision_replay", "$DEST")}"' in gate, (p, gate)
    assert 'DEST="data/research/decision_replay"' in code
    assert "journal/" not in code and "public/data" not in code, "never a book writer"
    assert 'git push origin "HEAD:$BRANCH"' in code and 'BRANCH="${GITHUB_REF_NAME}"' in code
    assert "for i in 1 2 3 4 5; do" in code and 'git reset --hard "origin/$BRANCH"' in code
    assert "set -o pipefail" in code and "set -u" in code
    assert 'git config user.name "github-actions[bot]"' in code
    assert "'\"schema\": 1,'" in code, \
        "it refuses to commit a file the pack cannot read; exact (a bare 1 also matches 10)"
    assert "data: decision replay summary" in code
    assert not any("${{" in r for r in _summary_runs()), "no expression interpolation in run:"
    for r in _summary_runs():
        subprocess.run(["bash", "-n"], input=r, text=True, check=True)


def test_the_commit_job_is_deliberately_absent_from_the_watchdog():
    """Like momentum.yml / ignition.yml: a committing job with no
    WATCHDOG_RUNS entry, because it only follows a replay -- which runs on a
    kick or a dispatch, never on a clock -- so there is no freshness to
    alarm on. Reversible in one line in config if that ever changes."""
    cfg = (ROOT / "scanner" / "config.py").read_text(encoding="utf-8")
    assert '"decision_replay.yml"' not in cfg


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
    up = _step("actions/upload-artifact@v5")
    assert up.get("if") == "always()"
    assert up["with"]["retention-days"] == 90
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
