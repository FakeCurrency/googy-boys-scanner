"""The `scan` mutex and the manual-close re-dispatch (2026-07-28).

Why a test that only reads YAML: this behaviour has no Python to exercise, it
cost real data twice, and every regression is a one-line edit that looks
harmless in review.

The mechanic underneath all of it: GitHub keeps exactly ONE pending run per
concurrency group, and a newly-queued member CANCELS the previously-pending
one — independently of `cancel-in-progress`. So membership of `group: scan` is
not just "wait your turn", it is "be deleted if anyone else arrives while you
wait". Two consequences are pinned below.

  1. The group belongs on the JOB, not the workflow (REFINEMENTS #108). At
     workflow level the cheap gate jobs queue too, and every `:47` ASX
     freshness backstop was evicted by the `:52` crypto arrival before it
     could even probe.
  2. A manual close that gets evicted must re-dispatch itself (owner,
     2026-07-28). That only works because the eviction now cancels one JOB and
     leaves the run alive, so a sibling job outside the group can observe it.

If a future edit moves any of these blocks back to workflow level, the failure
is silent — a run that simply never appears. Hence the assertions.
"""

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

WF = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"

# The workflows that serialise on the shared bot book / alert state.
JOB_SCOPED = {
    "scan.yml": "scan",
    "crypto_bot.yml": "crypto",
    "close_position.yml": "close",
}


def _load(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def _group(block):
    """concurrency: may be a mapping or a bare string."""
    if block is None:
        return None
    return block.get("group") if isinstance(block, dict) else block


@pytest.mark.parametrize("fname,jobname", sorted(JOB_SCOPED.items()))
def test_the_scan_mutex_sits_on_the_job_not_the_workflow(fname, jobname):
    wf = _load(fname)
    assert _group(wf.get("concurrency")) != "scan", (
        f"{fname} declares group 'scan' at WORKFLOW level. That queues its gate "
        "jobs too, and a pending run in this group is deleted outright by the "
        "next arrival — see REFINEMENTS #108."
    )
    assert _group(wf["jobs"][jobname].get("concurrency")) == "scan", (
        f"{fname} job '{jobname}' must hold the scan mutex: it writes the bot "
        "book, and two writers can each read the same open count and both open."
    )


def test_the_writer_jobs_never_cancel_each_other_mid_write():
    # cancel-in-progress: true here would kill a scan half-way through the
    # load->modify->write cycle on the only track record.
    for fname, jobname in JOB_SCOPED.items():
        block = _load(fname)["jobs"][jobname]["concurrency"]
        assert block.get("cancel-in-progress") is False, fname


# ── the re-dispatch ──────────────────────────────────────────────────────────

CLOSE = "close_position.yml"


def _redispatch_script():
    job = _load(CLOSE)["jobs"]["redispatch"]
    return "\n".join(s.get("run", "") for s in job["steps"])


def test_redispatch_is_outside_the_group_it_is_rescuing_from():
    """The one thing that makes any of this work.

    If the re-dispatch job ever joins `group: scan` it is evicted by the same
    arrival that evicted the close, and the close vanishes exactly as before —
    only now with a job that looks like it should have saved it.
    """
    job = _load(CLOSE)["jobs"]["redispatch"]
    assert _group(job.get("concurrency")) is None


def test_redispatch_fires_only_on_a_cancellation():
    job = _load(CLOSE)["jobs"]["redispatch"]
    assert job["needs"] == "close"
    cond = job["if"]
    # always(), not success()/failure(): the close job's result IS 'cancelled',
    # which every other conditional function treats as "do not run".
    assert "always()" in cond
    assert "cancelled" in cond
    # A FAILED close (bad symbol, integrity gate) must not be retried — it
    # would fail identically three times and bury the real error.
    assert "failure" not in cond


def test_redispatch_can_actually_dispatch():
    job = _load(CLOSE)["jobs"]["redispatch"]
    # Job-level permissions REPLACE the workflow's contents:write, so this
    # block is the only thing granting the dispatch scope.
    assert job["permissions"] == {"actions": "write"}
    assert "gh workflow run close_position.yml" in _redispatch_script()


def test_every_dispatch_input_is_threaded_through_the_retry():
    """A retry that drops an input is worse than no retry.

    `market` defaults to "" and `journal_type` defaults to bot — a re-dispatch
    that forgot to pass them would close the wrong book, or fail to find the
    position, and look like a legitimate outcome. This test fails the moment
    someone adds an input without threading it through.
    """
    wf = _load(CLOSE)
    inputs = set(wf[True]["workflow_dispatch"]["inputs"])
    passed = set(re.findall(r'-f (\w+)=', _redispatch_script()))
    assert inputs <= passed, f"not re-dispatched: {sorted(inputs - passed)}"


def test_the_retry_chain_is_bounded():
    wf = _load(CLOSE)
    attempt = wf[True]["workflow_dispatch"]["inputs"]["attempt"]
    # A string, not an int: workflow_dispatch inputs are strings, and a YAML
    # `default: 1` arrives as "1" anyway — declaring it as one keeps the shell
    # arithmetic honest about what it is handling.
    assert attempt["default"] == "1"
    assert attempt.get("required") is not True

    script = _redispatch_script()
    assert re.search(r'\[ "\$attempt" -ge 3 \]', script), (
        "the cap must be a hard numeric bound in the shell, not just the `if:` "
        "expression — a non-numeric attempt input would make fromJSON() error "
        "and the bound disappear"
    )
    assert "attempt + 1" in script


def test_the_wait_loop_names_workflows_that_exist():
    """The pre-dispatch wait filters GitHub's run list by display name.

    Renaming a workflow's `name:` silently empties that filter, the wait
    becomes a no-op, and the re-dispatch goes straight back into a contested
    slot — the ping-pong the loop exists to prevent.
    """
    script = _redispatch_script()
    quoted = set(re.findall(r'\.workflowName == "([^"]+)"', script))
    assert quoted, "the wait loop no longer filters by workflow name"
    real = {_load(p.name)["name"] for p in WF.glob("*.yml")}
    assert quoted <= real, f"names not found in .github/workflows: {sorted(quoted - real)}"
    # Every scan-group member must be in the filter, or the loop clears while
    # that member is still pending and we evict it.
    for fname in JOB_SCOPED:
        assert _load(fname)["name"] in quoted, fname


def test_redispatch_ignores_a_close_that_had_already_started():
    # An evicted job never runs a step; a human hitting Cancel on a running
    # close leaves finished ones. Resurrecting the second case would override a
    # deliberate stop, so the step count is what separates them.
    script = _redispatch_script()
    assert 'select(.name == "close")' in script
    assert '.steps[]?' in script
    assert 'gh run view "$GITHUB_RUN_ID"' in script
