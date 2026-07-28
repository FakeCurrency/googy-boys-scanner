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
    # would fail identically three times and bury the real error. TOP100 #47
    # added ONE exemption and did it without touching this rule: the close
    # names its own contention failure via an output (see the test below), so
    # `failure` itself is still never a trigger.
    assert "failure" not in cond


def test_the_only_resurrectable_failure_is_the_one_the_close_vouches_for():
    """TOP100 #47 — a lost push race is not a rejected close.

    Since TOP100 #45 the close retries its push five times and then exits 1.
    From out here that failure is indistinguishable from the eviction this job
    already resurrects — the edit was right, only the publish lost — and it is
    the one failure worth retrying. But it must be the CLOSE that says so, not
    this job guessing from the result, because every other failure (bad symbol,
    tripped integrity gate) still has to stop dead.
    """
    wf = _load(CLOSE)
    close = wf["jobs"]["close"]
    cond = wf["jobs"]["redispatch"]["if"]

    assert "needs.close.outputs.push_exhausted" in cond, (
        "the redispatch no longer consults the close's own verdict — it is "
        "either back to guessing, or the exemption has silently widened"
    )
    # The output has to be declared on the job, or the expression above is
    # permanently '' and the whole exemption is dead code that reads as live.
    assert close.get("outputs", {}).get("push_exhausted"), (
        "job `close` must declare a `push_exhausted` output; without it "
        "needs.close.outputs.push_exhausted is always empty"
    )
    produced = close["outputs"]["push_exhausted"]
    step_id = re.search(r"steps\.(\w+)\.outputs\.push_exhausted", produced)
    assert step_id, f"unexpected output expression: {produced}"
    step = next(
        (s for s in close["steps"] if s.get("id") == step_id.group(1)), None
    )
    assert step is not None, (
        f"the output points at step id '{step_id.group(1)}', which no longer exists"
    )
    assert 'push_exhausted=true" >> "$GITHUB_OUTPUT"' in step["run"], (
        "the commit step never writes push_exhausted, so the exemption can "
        "never fire and a lost push race is dropped exactly as before #45"
    )

    # And the eviction-signature check must SKIP it: an exhausted push executed
    # every step, so the zero-executed-steps test would veto the very case the
    # output exists to admit.
    script = _redispatch_script()
    assert '"${PUSH_EXHAUSTED:-}" = "true"' in script, (
        "the step-count eviction check no longer exempts the exhausted-push "
        "case — a close that ran and could not publish will be vetoed by it"
    )


def test_the_close_push_is_retried_rather_than_attempted_once():
    """TOP100 #45 — the close was the only writer here with no retry.

    Every other workflow that pushes to main loops five times and exits 1. This
    one did a single `git push` after a single rebase, in the workflow whose
    input is a deliberate human act on the one and only track record — and a
    manual close is the hardest thing in the repo to notice going missing,
    because there is no cron behind it and no freshness badge for "a position
    you closed by hand still shows as open".
    """
    close = _load(CLOSE)["jobs"]["close"]
    script = "\n".join(s.get("run", "") for s in close["steps"])
    assert "for i in 1 2 3 4 5; do" in script, "the push retry loop is gone"
    assert "git rebase --abort" in script, (
        "a failed rebase must be aborted before the next attempt, or attempt 2 "
        "starts from a tree mid-conflict"
    )
    # The combined book is DERIVED (_write_combined output). Replaying this
    # run's copy onto a main that moved publishes a view derived from neither
    # tree — which is exactly what `--verify` fails the NEXT run for.
    assert "--rebuild-combined" in script, (
        "the derived combined book is no longer regenerated after the rebase"
    )
    assert '"$JOURNAL_TYPE" = "bot"' in script, (
        "--rebuild-combined must stay gated on the bot journal: it stamps "
        "updated_at, so a legacy swing/scalp close would touch the bot book"
    )


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


def _watched_names():
    """The display names the pre-dispatch wait loop filters GitHub's runs by.

    They live in one `WATCHED='"A","B",…'` shell variable (TOP100 #46) rather
    than in four inline comparisons, because two different jq passes consume
    the same list and a list written twice is a list that drifts.
    """
    m = re.search(r"WATCHED='([^']*)'", _redispatch_script())
    assert m, "the wait loop no longer builds a WATCHED list of workflow names"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def _scan_group_members():
    """Every workflow that can hold `group: scan`, at either scope.

    Enumerated from the tree rather than hand-listed: the omission TOP100 #46
    found was 'Backfill sector history', a workflow added long after the wait
    loop's list was written and never added to it.
    """
    members = {}
    for path in sorted(WF.glob("*.yml")):
        wf = _load(path.name)
        scopes = [_group(wf.get("concurrency"))]
        scopes += [
            _group(j.get("concurrency")) for j in (wf.get("jobs") or {}).values()
        ]
        if "scan" in scopes:
            members[path.name] = wf["name"]
    return members


def test_the_wait_loop_names_workflows_that_exist():
    """The pre-dispatch wait filters GitHub's run list by display name.

    Renaming a workflow's `name:` silently empties that filter, the wait
    becomes a no-op, and the re-dispatch goes straight back into a contested
    slot — the ping-pong the loop exists to prevent.
    """
    watched = _watched_names()
    real = {_load(p.name)["name"] for p in WF.glob("*.yml")}
    assert watched <= real, (
        f"names not found in .github/workflows: {sorted(watched - real)}"
    )


def test_the_wait_loop_watches_every_member_of_the_group():
    """A member missing from the filter is invisible while it holds the mutex.

    That is not a degraded wait, it is the absence of one: the loop counts 0,
    breaks on the first pass and dispatches straight into the contention it
    exists to sit out — evicting the very sibling it was queued behind.
    """
    watched = _watched_names()
    for fname, display in _scan_group_members().items():
        assert display in watched, (
            f"{fname} can hold `group: scan` as {display!r} but the wait loop "
            "does not watch it"
        )


def test_the_wait_loop_looks_at_job_state_not_just_run_state():
    """TOP100 #46 — the wait was reading the state the mutex stopped producing.

    It counted runs whose RUN-level status is queued/waiting/pending. That is
    what a contested member looked like when `group: scan` sat at WORKFLOW
    level. Since the group moved onto the JOBS (deliberately, so the cheap gate
    jobs stay out of the queue) a contested member's RUN is `in_progress` — its
    gate is running — while the mutex-holding JOB sits at `queued`. The old
    filter matched none of that, so it counted 0 every time and the wait was a
    no-op that read as a wait.

    Both passes have to survive: the run-level one still covers the members
    scoped at workflow level, the job-level one covers the three that are not.
    """
    script = _redispatch_script()

    # (a) run-level, for the workflow-scoped members.
    assert "gh run list" in script
    assert re.search(r'status.{0,4} == .{0,4}queued', script), (
        "the run-level pass no longer looks for queued runs"
    )

    # (b) job-level, for the job-scoped members — the half #46 added.
    assert 'gh run view "$id" --json jobs' in script, (
        "the wait loop no longer inspects JOB state, so a run whose gate is "
        "running while its mutex-holding job queues is counted as idle"
    )
    assert re.search(r'select\(\.status == "queued"', script), (
        "the job-level pass no longer filters on a queued job"
    )
    # Every mutex-holding job name must be inspected, or that workflow's
    # contention is invisible to the second pass.
    for fname, jobname in JOB_SCOPED.items():
        assert f'.name == "{jobname}"' in script, f"{fname}: job '{jobname}'"

    # It must skip its OWN run: this workflow is in the watched list (it has to
    # be — a second manual close contests the same slot), and its own close job
    # is `cancelled`, not queued, but counting itself would still be a bug
    # waiting on the next status GitHub invents.
    assert '[ "$id" = "$GITHUB_RUN_ID" ] && continue' in script

    # The wait stays bounded. An attempt that loses the race again is
    # recoverable; a close that never dispatches is not.
    assert re.search(r"for _ in 1 2 3 4 5 6 7 8 9 10; do", script), (
        "the wait is no longer bounded — a permanently contested mutex would "
        "hold this job until the 15-minute timeout instead of dispatching"
    )


def test_redispatch_ignores_a_close_that_had_already_started():
    # An evicted job never runs a step; a human hitting Cancel on a running
    # close leaves finished ones. Resurrecting the second case would override a
    # deliberate stop, so the step count is what separates them.
    script = _redispatch_script()
    assert 'select(.name == "close")' in script
    assert '.steps[]?' in script
    assert 'gh run view "$GITHUB_RUN_ID"' in script
