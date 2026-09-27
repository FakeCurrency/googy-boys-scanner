"""The `vars.VPS_ACTIVE` job guards (deploy/DESIGN.md D5, 2026-09-27).

One writer, enforced three ways: cutover disables the workflows, the VPS's
publish step halts on a foreign data commit, and -- this file -- a job-level
`if:` on every GitHub workflow that can reach the paper book makes a
RE-ENABLED workflow a no-op while the repository variable VPS_ACTIVE is '1'.
The third leg exists because the first is one `gh workflow enable` (or a
rollback rehearsal, or the "schedule re-registration" habit) away from being
undone, and the 30-position cap is global: two writers is the one failure
that cannot be undone.

The guard is YAML with no Python behind it, so this is a source pin. It reads
the shipped workflows; it never re-types them.
"""

import pathlib
import re

import pytest

from scanner import config

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"

# Exactly this expression. GitHub compares `!=` loosely, and `vars.X` is the
# EMPTY string on a repo where the variable was never created -- the quoted
# '1' keeps both readings honest: unset -> run (Actions is the writer today),
# '1' -> skip, anything else -> run.
GUARD = "${{ vars.VPS_ACTIVE != '1' }}"

# workflow -> the job that carries the guard. scan/crypto guard the GATE:
# the writer job sits behind `needs: gate` + `if: needs.gate.outputs.run ==
# 'true'`, and a skipped gate yields no outputs, so the writer skips with it.
GUARDED = {
    "scan.yml": "gate",
    "crypto_bot.yml": "gate",
    "close_position.yml": "close",
    "dispatch_scan.yml": "kick",
}


def _load(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("fname,job", sorted(GUARDED.items()))
def test_the_guard_is_on_the_job_verbatim(fname, job):
    doc = _load(fname)
    assert doc["jobs"][job].get("if") == GUARD, (
        f"{fname} job '{job}' lost the VPS_ACTIVE guard (deploy/DESIGN.md D5): a "
        f"re-enabled workflow would write the book beside the VPS")


@pytest.mark.parametrize("fname,job", sorted(GUARDED.items()))
def test_the_guard_carries_the_design_reference(fname, job):
    """A one-line comment naming D5 sits inside the job block, so the next
    reader who finds an `if:` on a gate job knows it is not a stray edit."""
    src = (WF / fname).read_text(encoding="utf-8")
    block = src[src.index(f"\n  {job}:\n"):]
    block = block[:block.index("runs-on:")]
    assert "deploy/DESIGN.md D5" in block, f"{fname}: the guard's D5 comment is gone"
    assert "VPS_ACTIVE" in block


def test_a_skipped_gate_skips_the_writer_behind_it():
    for fname in ("scan.yml", "crypto_bot.yml"):
        doc = _load(fname)
        writer = next(j for j, spec in doc["jobs"].items()
                      if (spec.get("concurrency") or {}).get("group") == "scan")
        spec = doc["jobs"][writer]
        assert spec["needs"] == "gate", f"{fname}: the writer no longer waits on the gate"
        assert "needs.gate.outputs.run == 'true'" in spec["if"], (
            f"{fname}: the writer must key on the gate's output; a skipped gate "
            f"has none, which is what makes guarding the gate guard the book")


def test_the_redispatch_cannot_fire_on_a_guard_skipped_close():
    """The re-dispatch resurrects a close whose job was CANCELLED (mutex
    eviction) or that vouched `push_exhausted`. A job skipped by its own `if:`
    reports `skipped` and yields no outputs, so neither branch is true. Pinned
    so a future `always() && needs.close.result != 'success'` cannot turn the
    guard into a re-dispatch loop against a disabled workflow."""
    doc = _load("close_position.yml")
    cond = doc["jobs"]["redispatch"]["if"]
    assert "cancelled" in cond and "push_exhausted == 'true'" in cond
    assert "skipped" not in cond and "!= 'success'" not in cond
    # nothing else in the condition can be true for a skipped job
    branches = re.findall(r"needs\.close\.[a-z_.]+\s*==\s*'[^']+'", cond)
    assert sorted(branches) == ["needs.close.outputs.push_exhausted == 'true'",
                                "needs.close.result == 'cancelled'"], cond


def test_every_book_writer_workflow_is_guarded_and_disabled_at_cutover():
    """The guard set is not an arbitrary four: every workflow the runner
    knows as a BOOK WRITER carries one, plus the push-kick that dispatches a
    writer -- and cutover.sh disables all four (VPS_WORKFLOWS_TO_DISABLE)."""
    assert set(config.VPS_BOOK_WRITER_JOBS) <= set(GUARDED)
    assert set(GUARDED) <= set(config.VPS_WORKFLOWS_TO_DISABLE)


def test_no_other_workflow_grew_a_guard_by_accident():
    """The guard means 'this workflow writes the book (or dispatches one that
    does)'. A read-only workflow wearing it would stop for no reason after
    cutover -- e.g. commit_sentinel, which must keep watching main."""
    wearing = set()
    for path in sorted(WF.glob("*.yml")):
        doc = _load(path.name)
        for spec in (doc.get("jobs") or {}).values():
            if "VPS_ACTIVE" in str(spec.get("if", "")):
                wearing.add(path.name)
    assert wearing == set(GUARDED), sorted(wearing ^ set(GUARDED))


def test_the_cutover_scripts_set_the_variable_the_guard_reads():
    """The guard and the scripts name the same variable, or the guard is
    dead code that reads as live."""
    cut = (ROOT / "deploy" / "bin" / "cutover.sh").read_text(encoding="utf-8")
    back = (ROOT / "deploy" / "bin" / "rollback.sh").read_text(encoding="utf-8")
    assert re.search(r"set_variable VPS_ACTIVE 1\b", cut), "cutover.sh no longer sets VPS_ACTIVE=1"
    assert re.search(r"set_variable VPS_ACTIVE 0\b", back), "rollback.sh no longer clears VPS_ACTIVE"
