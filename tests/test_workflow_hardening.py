"""Workflow hardening — TOP100 #52/#54/#55/#56 (2026-07-28).

Four fixes with one shape in common: each removed a way for a scheduled job to
finish GREEN while doing less than it claimed. None of them has any Python to
exercise, all of them are a one-line edit away from coming back, and every
regression is invisible until the day you need the thing that stopped working.

The three mechanics being pinned, because the assertions below are unreadable
without them:

  1. `git add a b` is ALL-OR-NOTHING. With `b` missing it exits 128 with
     "pathspec did not match any files" and stages NEITHER — verified in a
     scratch repo, not inferred from the docs. Paired with `2>/dev/null ||
     true` (the form this repo used in two places) it swallows both the
     message and the status, and the next line finds an empty index.

  2. A tolerated step needs a DISCRIMINATOR, not just tolerance. "Specs was
     allowed to fail" and "Specs succeeded and wrote nothing" want opposite
     responses — a warning and a red job — and a step that only sets
     `continue-on-error` cannot tell a later step which one happened.

  3. `assert_staged` is the house answer to silent-failure, and it is the
     WRONG answer where a no-op is legitimate. Two places here prove it: a
     quiet confluence night, and an idempotent backfill re-merge. Asserting
     must-change in either would fail on the normal case, which is how a gate
     gets deleted rather than fixed.
"""

import importlib.util
import json
import pathlib
import re
import subprocess

import pytest

from scanner import config

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
ALL_WF = sorted(WF.glob("*.yml"))


def _load(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def _text(name):
    return (WF / name).read_text(encoding="utf-8")


def _step(doc, job, name_fragment):
    for s in doc["jobs"][job]["steps"]:
        if name_fragment.lower() in str(s.get("name", "")).lower():
            return s
    raise AssertionError(f"no step matching {name_fragment!r} in {job}")


# --------------------------------------------------------------------------
# #52 / #54 — staging is per-path, everywhere
# --------------------------------------------------------------------------

def _code(text: str):
    """(lineno, line) for lines that are not comments.

    Every test below asks whether a workflow CALLS something or RUNS something.
    A plain substring search cannot answer that in this repo, because the
    reasoning for each of these decisions is written into the YAML beside it —
    so the comment explaining why `assert_staged` is deliberately absent from a
    step contains the string "assert_staged", and a naive `not in` reads the
    justification as the offence. Ask about code, read code.
    """
    for i, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if s and not s.startswith("#"):
            yield i, s


# Tokens that end the pathspec list on a `git add` line.
_ENDS_ARGS = ("|", "&&", ";", "2>/dev/null", ">/dev/null", "#")


def _git_add_paths(line: str):
    """Pathspecs a `git add` line stages, or None if the line is not one.

    Returns [] for the pathspec-free forms (`git add -A`, `git add -u`), which
    are a different construct with none of this failure mode: they cannot fail
    on a missing pathspec because they name none.
    """
    m = re.match(r"^git add\b(.*)$", line)
    if not m:
        return None
    out = []
    for tok in m.group(1).split():
        if tok in _ENDS_ARGS or tok.startswith(("2>", ">", "|", "#")):
            break
        if tok == "--" or tok.startswith("-"):
            continue
        out.append(tok)
    return out


@pytest.mark.parametrize("wf", [f.name for f in ALL_WF])
def test_every_run_block_is_valid_shell(wf):
    """`bash -n` on every step body — the cheapest gate this repo did not have.

    A YAML parse proves the file is well-formed YAML, which says nothing about
    the shell inside the `run:` scalars, and a broken `if`/`for`/`fi` in there
    is only discovered by dispatching the workflow. For the manual ones
    (close_position, backfill, test_alerts) that means discovering it at the
    moment you need them, which for a manual close is the moment you are
    already trying to record a real trade.
    """
    doc = _load(wf)
    broken = []
    for job, spec in (doc.get("jobs") or {}).items():
        for step in (spec.get("steps") or []):
            body = step.get("run")
            if not body or "bash" not in (step.get("shell") or "bash"):
                continue
            p = subprocess.run(["bash", "-n"], input=str(body),
                               text=True, capture_output=True)
            if p.returncode != 0:
                broken.append(f"{job}:{step.get('name', '?')}: "
                              f"{p.stderr.strip()}")
    assert not broken, "\n  ".join(broken)


def test_no_git_add_stages_more_than_one_path_at_a_time():
    """The all-or-nothing bug, banned repo-wide rather than fixed file by file.

    `git add a b` is ALL-OR-NOTHING: with `b` missing it exits 128 with
    "pathspec did not match any files" and stages NEITHER (verified in a
    scratch repo, not assumed). That construct took confluence.yml and
    phasemap.yml down.

    The ban is on the SHAPE, not on the spelling. The first version of this
    test matched `git add $PATHS` and passed while close_position.yml was
    staging two literal paths in one call, in the workflow that edits the only
    track record — the same bug with the list written out instead of held in a
    variable. Count pathspecs; do not pattern-match the variable.
    """
    offenders = []
    for f in ALL_WF:
        for i, line in _code(f.read_text(encoding="utf-8")):
            paths = _git_add_paths(line)
            if paths is not None and len(paths) > 1:
                offenders.append(f"{f.name}:{i}: {line}")
    assert not offenders, (
        "git add is all-or-nothing across its pathspecs — one missing path "
        "stages NONE of them. Stage one at a time:\n  " + "\n  ".join(offenders)
    )


def test_a_swallowed_git_add_always_has_something_downstream_that_can_tell():
    """`|| true` on a `git add` is allowed — but only where it stays legible.

    It was never the `git add` that was fatal, it was the PAIRING: the status
    is discarded, so the empty index that follows reads as "nothing changed",
    and in these workflows that is also the true and common outcome. One icon,
    two questions.

    Swallowing is sometimes right. close_position.yml stages ten paths of which
    roughly six are legitimately absent on any given close (a bot close never
    touches scalp_journal), so announcing each absentee would print six lines
    of noise every run. What makes it survivable there is not the silence but
    what comes after it: an `assert_staged` that fires when the close really
    did edit the book and nothing reached the index. This test requires that
    pairing rather than banning half of it.
    """
    offenders = []
    for f in ALL_WF:
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        for job, spec in (doc.get("jobs") or {}).items():
            for step in (spec.get("steps") or []):
                body = str(step.get("run", "") or "")
                swallowed = [
                    line for _, line in _code(body)
                    if _git_add_paths(line) is not None and "|| true" in line
                ]
                if swallowed and "assert_staged.sh" not in body:
                    offenders.append(
                        f"{f.name}:{job}:{step.get('name', '?')}: "
                        + "; ".join(swallowed))
    assert not offenders, (
        "a git add whose failure is swallowed needs a must-change gate in the "
        "same step, or an empty index is indistinguishable from a clean "
        "no-op:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("wf,job", [("confluence.yml", "confluence"),
                                    ("phasemap.yml", "phasemap")])
def test_the_repaired_workflows_stage_one_path_at_a_time(wf, job):
    """Positive form: they loop, and they SAY when a path is absent."""
    body = "\n".join(
        str(s.get("run", "")) for s in _load(wf)["jobs"][job]["steps"])
    assert "for p in $PATHS; do" in body
    assert 'git add -- "$p"' in body
    assert "::warning::" in body, (
        "a path that is not there must be announced — silence is what made "
        "the original bug survive"
    )


def test_confluence_gates_on_unstaged_rather_than_on_changed():
    """The invariant had to be INVERTED here, and that is the interesting part.

    A night with no new alignment legitimately stages nothing, so the house
    `assert_staged` (must-change) would fail most runs and get deleted. The
    question that IS always answerable: after the per-path adds, anything still
    showing an unstaged diff in those paths is a staging bug by construction.
    Silent on a quiet night, loud on a real one.
    """
    body = "\n".join(
        str(s.get("run", "")) for s in _load("confluence.yml")["jobs"]["confluence"]["steps"])
    assert "if ! git diff --quiet -- $PATHS; then" in body
    assert "::error::" in body
    assert not [l for _, l in _code(body) if "assert_staged.sh" in l], (
        "a must-change gate here fails on every quiet night, which is the "
        "normal case for this workflow"
    )


def _close_commit_body() -> str:
    return _step(_load("close_position.yml"), "close", "Commit updated journal")["run"]


def test_a_bot_close_that_stages_nothing_is_a_failure_not_a_no_op():
    """The highest-stakes instance of the whole family, and it read as green.

    `Nothing to commit (position not found or already closed).` + `exit 0` was
    describing, for journal_type=bot, a state that cannot occur: the close step
    above exits non-zero when no open position matches, and the default shell
    is `bash -e`, so reaching the commit step at all means the book WAS edited.
    An empty index there is a staging bug wearing the no-op's message — in the
    workflow whose input is a deliberate human act on the only track record,
    and whose loss is the hardest in the repo to notice.
    """
    body = _close_commit_body()
    assert "assert_staged.sh" in body
    lines = [l for _, l in _code(body)]
    gate = next(i for i, l in enumerate(lines) if "assert_staged.sh" in l)
    quiet = next(i for i, l in enumerate(lines) if "git diff --cached --quiet" in l)
    assert gate < quiet, (
        "the must-change gate has to run BEFORE the quiet check, or the "
        "`exit 0` it exists to prevent has already happened"
    )


def test_the_bot_close_gate_names_the_canonical_files_not_the_derived_ones():
    """The combined book is `_write_combined()` OUTPUT, so it proves nothing.

    A gate that accepted the derived pair would pass on a run that regenerated
    a view while the per-market file the close actually edited failed to stage.
    `assert_staged` is any-of semantics, so listing the derived twin alongside
    would be enough to satisfy it on its own.
    """
    body = _close_commit_body()
    gate = next(l for _, l in _code(body) if "assert_staged.sh" in l)
    tail = body[body.index(gate):body.index("if git diff --cached --quiet")]
    for market in ("asx", "nasdaq", "crypto"):
        assert f"journal/vivek_bot_book.{market}.json" in tail
    assert "public/data/vivek_bot_book.json" not in tail, (
        "the public twin is a derived view; staging it says nothing about "
        "whether the close reached the canonical book"
    )


def test_the_swing_and_scalp_paths_stay_a_green_no_op():
    """The asymmetry is deliberate and is the reason the gate is conditional.

    `journal.py --close-manual` prints "no open X found - nothing changed" and
    returns 0, so for swing/scalp an empty index really is the honest no-op the
    message describes. Blanket-applying the bot gate would turn a legitimate
    outcome red on the legacy pages; a test that only checked "there is a gate"
    would not notice.
    """
    body = _close_commit_body()
    lines = [l for _, l in _code(body)]
    gate = next(i for i, l in enumerate(lines) if "assert_staged.sh" in l)
    guard = next(i for i, l in enumerate(lines)
                 if '[ "$JOURNAL_TYPE" = "bot" ]' in l)
    assert guard < gate, "the assert must sit INSIDE the journal_type=bot branch"
    assert gate - guard <= 3, (
        "the gate drifted out of the branch it was meant to be inside"
    )
    assert 'echo "Nothing to commit' in body and "exit 0" in body


# --------------------------------------------------------------------------
# #54 — the Specs discriminator
# --------------------------------------------------------------------------

def test_the_specs_step_records_its_outcome_as_an_output():
    """Tolerated, but no longer silent — and the outcome has to be READABLE.

    Specs is a confluence LENS: confluence_alert reads {market}_spec.json with
    no freshness check, so a frozen file keeps voting and a "triple-lens
    agreement" @here ping can be two live lenses plus a week-old Specs row.
    The tolerance stays; what changed is that the result travels.
    """
    step = _step(_load("phasemap.yml"), "phasemap", "Run Specs scan")
    assert step.get("id") == "specs"
    assert "continue-on-error" not in step, (
        "continue-on-error makes the else-branch unreachable under the default "
        "`bash -e` — the failure message would never run"
    )
    run = step["run"]
    assert 'echo "ok=true" >> "$GITHUB_OUTPUT"' in run
    assert 'echo "ok=false" >> "$GITHUB_OUTPUT"' in run
    assert "::warning::" in run


def test_the_spec_must_change_gate_is_gated_on_the_specs_outcome():
    """Asserting the spec files unconditionally would REVERSE the tolerance.

    A throttled Yahoo fetch would become a red nightly, i.e. the decision not
    to fail the PhaseMap publish over the third lens, undone by the back door.
    Gated, the assert catches the case tolerance never covered: Specs exited 0
    and still wrote nothing.
    """
    step = _step(_load("phasemap.yml"), "phasemap", "Commit & push fresh data")
    assert step.get("env", {}).get("SPECS_OK") == "${{ steps.specs.outputs.ok }}", (
        "without this wiring $SPECS_OK is the empty string and the gate below "
        "never fires — the fix would be present and inert"
    )
    run = step["run"]
    assert '[ "$SPECS_OK" = "true" ]' in run
    for label in ("specs asx", "specs nasdaq"):
        assert f'assert_staged.sh "{label}"' in run
    # The gate must sit INSIDE the schedule branch and INSIDE the SPECS_OK
    # branch. Cheapest structural proof: the SPECS_OK test appears before the
    # first spec assert, and the schedule test before that.
    assert (run.index('= "schedule"')
            < run.index('[ "$SPECS_OK" = "true" ]')
            < run.index('assert_staged.sh "specs asx"'))


def test_a_failed_specs_run_still_says_what_it_costs():
    """The skip branch must not be a bare `else: :`.

    A skipped gate that says nothing is indistinguishable from a gate that
    passed, which is the whole failure mode being repaired.
    """
    run = _step(_load("phasemap.yml"), "phasemap", "Commit & push fresh data")["run"]
    tail = run[run.index('[ "$SPECS_OK" = "true" ]'):]
    assert "::warning::" in tail
    assert "freshness" in tail.lower()


# --------------------------------------------------------------------------
# #55 — the backfill merge proves its own postcondition
# --------------------------------------------------------------------------

def _bf():
    spec = importlib.util.spec_from_file_location(
        "bf_hardening", ROOT / "scripts" / "backfill_sector_history.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def history(tmp_path, monkeypatch):
    from scanner import sectorbreadth
    monkeypatch.setattr(sectorbreadth, "HISTORY_FILE",
                        tmp_path / "sector_history.json")
    return tmp_path


def _rows(days, market="asx"):
    return [{"d": f"2026-07-{d:02d}", "m": market, "r": 1,
             "top": [{"s": "Consumer Discretionary", "rate": 0.11}],
             "held": None} for d in days]


def _park(tmp_path, rows, market="asx"):
    p = tmp_path / "rows.json"
    p.write_text(json.dumps({"market": market, "horizon": "", "rows": rows}),
                 encoding="utf-8")
    return str(p)


def test_merge_only_verifies_the_write_landed(history):
    bf = _bf()
    rows = _rows((10, 11, 12))
    assert bf.merge_only(_park(history, rows)) == 0


def test_a_re_run_is_idempotent_and_must_not_be_treated_as_a_failure(history):
    """THE reason this is not an assert_staged call.

    merge_rows is documented idempotent, so a second run legitimately produces
    a byte-identical file and stages nothing. A must-change gate would fail on
    exactly the property the script advertises — so the postcondition asks
    "does the file CONTAIN the reconstruction", which is true both times.
    """
    bf = _bf()
    parked = _park(history, _rows((10, 11, 12)))
    assert bf.merge_only(parked) == 0
    assert bf.merge_only(parked) == 0


def test_a_session_lost_between_the_merge_and_the_disk_is_caught(history):
    """The failure the old code reported as "nothing to commit"."""
    from scanner import sectorbreadth
    bf = _bf()
    rows = _rows((10, 11, 12))
    assert bf.merge_only(_park(history, rows)) == 0
    hist = sectorbreadth.load_history()
    hist["rows"] = [r for r in hist["rows"] if r["d"] != "2026-07-11"]
    sectorbreadth._write_json(sectorbreadth.HISTORY_FILE, hist)
    assert bf._verify_merged(rows) == 1


def test_rows_dropped_by_the_history_cap_are_excused_not_reported_lost(history):
    """Truncation is legitimate, and must not read as data loss.

    SECTOR_BREADTH_HISTORY_MAX keeps the NEWEST rows, so a long enough replay
    can legitimately lose its oldest sessions off the far end. Reporting that
    as a failed write would make a successful long backfill un-committable.
    """
    from scanner import sectorbreadth
    bf = _bf()
    rows = _rows((10, 11, 12))
    # Only the newest survives — as the cap would leave it.
    sectorbreadth._write_json(sectorbreadth.HISTORY_FILE,
                              {"version": sectorbreadth.HISTORY_VERSION,
                               "rows": _rows((12,))})
    assert bf._verify_merged(rows) == 0


def test_an_empty_parked_file_is_still_a_failure(history):
    """A replay that produced nothing must not merge quietly and exit 0."""
    bf = _bf()
    assert bf.merge_only(_park(history, [])) == 1


def test_the_backfill_commit_step_deliberately_has_no_assert_staged():
    """Pinned as a DECISION, so it reads as considered rather than forgotten.

    Every other committing workflow here has one. Adding it to this one would
    fail every idempotent re-run; the postcondition inside merge_only is the
    replacement, and this test is what stops someone "restoring consistency".
    """
    body = "\n".join(str(s.get("run", ""))
                     for s in _load("backfill_history.yml")["jobs"]["backfill"]["steps"])
    assert not [l for _, l in _code(body) if "assert_staged.sh" in l]
    assert "--merge-only" in body
    assert "set -e" in body


# --------------------------------------------------------------------------
# #56 — least privilege, and the pin rule that actually matters
# --------------------------------------------------------------------------

@pytest.mark.parametrize("wf", [f.name for f in ALL_WF])
def test_every_workflow_declares_its_permissions(wf):
    """An absent block means "whatever the repo default is", which is a setting
    nobody reads and which grants WRITE on repos created before the read-only
    default. test.yml — widest trigger surface in the repo, runs on every push
    and every PR — was the one without it."""
    assert "permissions" in _load(wf), (
        f"{wf} inherits the repository default token scope; declare it"
    )


def test_the_test_workflow_cannot_push():
    doc = _load("test.yml")
    assert doc["permissions"] == {"contents": "read"}


def test_the_scan_gate_job_does_not_inherit_write():
    """The workflow needs write for the SCAN job. The gate checks out nothing,
    curls a public health endpoint and writes only $GITHUB_OUTPUT — and it runs
    on every scheduled fire, so it is the most frequently executed job here."""
    doc = _load("scan.yml")
    assert doc["permissions"] == {"contents": "write"}, (
        "the scan job commits; this is expected to stay write"
    )
    assert doc["jobs"]["gate"]["permissions"] == {"contents": "read"}


def _uses():
    out = []
    for f in ALL_WF:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = re.search(r"uses:\s*(\S+)", line)
            if m and not m.group(1).startswith("./"):
                out.append((f.name, i, m.group(1)))
    return out


def test_third_party_actions_must_be_pinned_to_a_commit_sha():
    """The supply-chain rule, aimed at the case that has actually happened.

    A mutable tag on a THIRD-party action is the tj-actions class of incident:
    one maintainer credential repoints v4, and every job running it hands over
    the secrets in its env — here that is DISCORD_WEBHOOK_URL, BYBIT_*,
    TELEGRAM_*, GBS_SMTP_* and GH_DISPATCH_TOKEN.

    `actions/*` is deliberately exempt and it is not laziness: those tags are
    moved by GitHub itself, in the same trust domain as the runner and the
    token service, so a compromise deep enough to repoint them already owns
    the environment a SHA pin was meant to protect. The cost is not symmetric
    either — a frozen SHA on a first-party action stops receiving patch fixes
    and this repo has no Dependabot to bump it.

    So the gate is on the boundary that matters: the first non-actions/* entry
    added to this repo has to arrive SHA-pinned.
    """
    bad = [f"{f}:{i}: {u}" for f, i, u in _uses()
           if not u.startswith("actions/")
           and not re.search(r"@[0-9a-f]{40}$", u)]
    assert not bad, (
        "third-party actions must be pinned to a full commit SHA "
        "(uses: owner/repo@<40-hex>  # vX.Y.Z):\n  " + "\n  ".join(bad)
    )


def test_no_action_floats_on_a_branch():
    """`@main` / `@master` is a mutable tag with no version at all — it is not
    a pin in any sense, and it applies to first-party actions too."""
    bad = [f"{f}:{i}: {u}" for f, i, u in _uses()
           if u.rsplit("@", 1)[-1] in ("main", "master", "latest")]
    assert not bad, "\n  ".join(bad)


def test_the_first_party_actions_are_the_five_we_reviewed():
    """A tripwire, not a style rule.

    The exemption above is an argument about `actions/*` specifically. If the
    set ever grows, the new entry should be looked at rather than inherit an
    exemption reasoned about five others.
    """
    seen = {u.split("@")[0] for _, _, u in _uses() if u.startswith("actions/")}
    assert seen == {"actions/checkout", "actions/setup-python",
                    "actions/setup-node", "actions/cache",
                    "actions/upload-artifact"}, sorted(seen)


# --------------------------------------------------------------------------
# 2026-07-28 incident - the skip marker, EXERCISED rather than pattern-matched
# --------------------------------------------------------------------------
# This is principle 2 of the header ("a tolerated step needs a DISCRIMINATOR")
# applied to the case that actually shipped a failure email. `run.py` has one
# path where a market publishes nothing and exits 0 on purpose: the download
# came back fully empty AND the frame cache had nothing to fall back on, so it
# keeps yesterday's JSON rather than clobbering it. That is a reported decision,
# not a fault. `scan.yml`'s per-market `assert_staged` could not see the
# decision - "no staged diff" is byte-identical to the 2026-07-20 silent-staging
# bug - so an upstream outage failed the whole cycle.
#
# The fix is a marker file, and a marker file is exactly the kind of thing that
# rots quietly: rename it on one side, and the gate silently goes back to
# failing on outages (or, far worse, silently stops gating at all). So these
# tests EXTRACT the gate's shell out of the YAML and RUN it against a stub
# `assert_staged` - the same "verify in a scratch repo, don't infer" standard
# the rest of this file was written to.


def _scan_commit_body() -> str:
    return str(_step(_load("scan.yml"), "scan", "Commit & push fresh data")["run"])


def _gate_block() -> str:
    """The staging gate only: from the marker read to the end of its if/else.

    Sliced rather than copied, so the thing under test is the shipping YAML and
    an edit to it cannot leave these tests passing against a stale duplicate.
    """
    lines = _scan_commit_body().splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == 'SKIPPED=""')
    manual = next(i for i, l in enumerate(lines) if "scan output (manual)" in l)
    end = next(i for i in range(manual, len(lines)) if lines[i].strip() == "fi")
    return "\n".join(lines[start:end + 1])


def _run_gate(tmp_path, *, skipped=(), staged_ok=False,
              market="all", mk="asx nasdaq crypto", event="schedule"):
    """Run the real gate shell with a stubbed assert_staged. Returns (rc, out).

    `staged_ok` is what the stub reports for EVERY path, which is the only two
    states that matter here: a run where everything landed, and a run where
    nothing did. The gate's whole job is deciding whether the second one is a
    bug or a reported outage, and the marker is the only input it has.
    """
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    stub = tmp_path / "scripts" / "assert_staged.sh"
    stub.write_text(
        '#!/usr/bin/env bash\necho "ASSERT-CALLED: $1"\nexit %d\n'
        % (0 if staged_ok else 1),
        encoding="utf-8",
    )
    if skipped:
        (tmp_path / config.SCAN_SKIP_MARKER).write_text(
            "".join(f"{m}\n" for m in skipped), encoding="ascii")
    script = tmp_path / "gate.sh"
    script.write_text(
        f'GITHUB_EVENT_NAME="{event}"\nM="{market}"\nMK="{mk}"\n' + _gate_block(),
        encoding="utf-8",
    )
    # `bash -e` is what GitHub Actions runs `run:` blocks under (default shell
    # is `bash -e {0}`; pipefail is NOT set). Testing under anything else would
    # test a gate that does not exist.
    p = subprocess.run(["bash", "-e", str(script)], cwd=tmp_path,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def test_the_gate_still_fails_a_run_that_staged_nothing_and_claimed_nothing(tmp_path):
    """The 2026-07-20 bug, unchanged. If this ever goes green the fix has eaten
    the gate it was meant to narrow, which is the failure mode that matters
    more than the one being fixed."""
    rc, out = _run_gate(tmp_path, staged_ok=False)
    assert rc != 0, out
    assert "ASSERT-CALLED: scan output [asx]" in out


def test_a_market_that_deliberately_published_nothing_does_not_fail_the_cycle(tmp_path):
    """The incident itself: every market's source blocked, nothing staged,
    nothing wrong. run.py already exited 0; the gate now agrees."""
    rc, out = _run_gate(tmp_path, skipped=("asx", "nasdaq", "crypto"), staged_ok=False)
    assert rc == 0, out
    assert "ASSERT-CALLED" not in out, (
        "a market named in the marker must not be asserted at all:\n" + out)
    assert "UNCHANGED from the previous run" in out


def test_a_skip_excuses_only_the_market_that_skipped(tmp_path):
    """The narrowing that makes this a discriminator and not just tolerance.

    ASX blocked does not buy NASDAQ an excuse - and NASDAQ silently staging
    nothing is precisely the bug the gate exists for, so it must still be red
    on the same run where ASX is forgiven.
    """
    rc, out = _run_gate(tmp_path, skipped=("asx",), staged_ok=False)
    assert rc != 0, out
    assert "ASSERT-CALLED: scan output [nasdaq]" in out
    assert "ASSERT-CALLED: scan output [asx]" not in out


def test_only_an_all_skipped_cycle_relaxes_the_combined_books(tmp_path):
    """`_write_combined()` re-stamps the books whenever ANY market's bot layer
    runs, so a partial skip leaves the markets that DID scan obliged to move
    them. Only a cycle where every market skipped leaves them legitimately
    untouched. Crypto is the sharp case: its own asserts are tolerated, so if
    the all-skipped test were written as "no hard failure" it would pass here
    too and the combined-book gate would be gone on every crypto-blocked run.
    """
    rc, out = _run_gate(tmp_path, skipped=("asx", "nasdaq"), staged_ok=False)
    assert rc != 0, out
    assert "ASSERT-CALLED: combined book (journal)" in out


def test_a_normal_run_is_untouched_by_any_of_this(tmp_path):
    rc, out = _run_gate(tmp_path, staged_ok=True)
    assert rc == 0, out
    for label in ("scan output [asx]", "bot book [nasdaq]",
                  "combined book (journal)", "combined book (public twin)"):
        assert f"ASSERT-CALLED: {label}" in out


def test_the_workflow_reads_the_exact_path_the_scanner_writes():
    """Two files, one filename, no import between them - the classic way a
    marker-file contract dies silently. Renaming it in config.py without
    touching scan.yml sends the gate back to failing on outages."""
    body = _scan_commit_body()
    assert config.SCAN_SKIP_MARKER in body, (
        f"scan.yml must read {config.SCAN_SKIP_MARKER!r} "
        "(scanner/config.py SCAN_SKIP_MARKER)")
    src = (ROOT / "scanner" / "run.py").read_text(encoding="utf-8")
    assert "config.SCAN_SKIP_MARKER" in src, (
        "run.py must write the marker via config, not a second literal")


def test_the_scanner_records_the_skip_on_the_path_that_takes_it():
    """The other half of the contract. If run.py stops writing the marker the
    gate is not wrong, it is just uninformed - and the symptom is identical to
    the incident, so it would be re-diagnosed from scratch."""
    src = (ROOT / "scanner" / "run.py").read_text(encoding="utf-8").splitlines()
    guard = next(i for i, l in enumerate(src) if l.strip() == "if not deep_frames:")
    stop = next(i for i in range(guard, len(src)) if src[i].strip() == "continue")
    assert any("_record_skip(market_key)" in l for l in src[guard:stop]), (
        "the deliberate no-data skip must record itself BEFORE it continues, "
        "or scan.yml cannot tell it apart from a staging bug")


def test_the_skip_marker_is_never_committed():
    """It describes ONE run. Committed, an outage on Monday would silence
    Tuesday's gate - a marker file that survives its run is worse than none."""
    # Ask git, not the file. The first version of this read .gitignore and
    # substring-matched, which passed against a COMMENTED-OUT rule - the exact
    # mutation it was written to catch. git is the only thing whose opinion on
    # what is ignored actually counts.
    p = subprocess.run(["git", "check-ignore", "-q", config.SCAN_SKIP_MARKER],
                       cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 0, (
        f"{config.SCAN_SKIP_MARKER} is not gitignored (git check-ignore "
        f"rc={p.returncode}); one run's outage would silence the next run's gate"
    )
    staged = [l for _, l in _code(_scan_commit_body())
              if l.startswith("SHARED=") or l.startswith("PATHS=")]
    assert staged, "staging scope moved; re-point this test"
    assert not [l for l in staged if config.SCAN_SKIP_MARKER in l]


# ── stop_watcher: curl's exit code must never BE the step's exit code ─────────
# Found live, 2026-08-04, run #372: `Process completed with exit code 28`.
# 28 is curl's "operation timed out", not any exit this script writes. GitHub's
# default shell is `bash -e {0}`, so the bare `code=$(curl ...)` assignment
# aborted the step the moment curl failed - upstream of the normalisation, the
# retry loop, the 503 branch and the exit-1 branch alike. The log carries the
# proof: not one "attempt N" line was printed before the step died. The three
# tries that exist to absorb a transient were therefore unreachable by the most
# common transient there is, and one 30-second stall was reported as "stop
# watcher DOWN". Run #277 (Jul 28) is the same signature, so it is twice now.

def _tick_run_block():
    return _load("stop_watcher.yml")["jobs"]["tick"]["steps"][0]["run"]


def test_a_curl_failure_cannot_kill_the_step_before_it_retries(tmp_path):
    """BEHAVIOURAL, and it has to be: the source-level pin below cannot tell a
    guarded assignment from a decorative comment about one. Runs the SHIPPED run
    block under `bash -e` (what GitHub actually uses) against a curl that fails
    exactly as #372's did, and asserts the job reaches its own verdict instead
    of dying with curl's."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Fails like a timeout does: writes the -w value ("000"), exits 28.
    (bin_dir / "curl").write_text('#!/bin/sh\nprintf 000\nexit 28\n')
    (bin_dir / "sleep").write_text('#!/bin/sh\nexit 0\n')   # keep the retry cheap
    for f in ("curl", "sleep"):
        (bin_dir / f).chmod(0o755)

    script = tmp_path / "step.sh"
    script.write_text(_tick_run_block())
    p = subprocess.run(
        ["bash", "-e", str(script)], capture_output=True, text=True, timeout=60,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path),
             "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md")})

    assert p.returncode != 28, (
        "the step died with CURL's exit code - `bash -e` aborted the "
        "`code=$(curl ...)` assignment, so the retry loop never ran")
    assert p.returncode == 1, (
        f"a sustained outage must reach the job's own exit 1, got "
        f"{p.returncode}: {p.stdout[-300:]}{p.stderr[-300:]}")
    assert "attempt 3: HTTP 000" in p.stdout, (
        "all three attempts must actually run before the job calls it down")
    assert "stop watcher DOWN" in p.stdout


def test_the_curl_status_guard_and_its_reason_both_survive():
    """Source pin beside the behavioural one. The guard is a lone `|| true` on a
    long line and reads like debris, so what protects it is the comment naming
    the run it came from - delete the reasoning and the next cleanup deletes the
    guard. NOT interchangeable with `|| echo 000`, which appends a SECOND value
    to curl's output (the "000000" bug) instead of neutralising its status."""
    block = _tick_run_block()
    # CODE lines only, via the house helper — the reasoning for this guard is
    # written into the YAML beside it and NAMES `|| echo 000` as the thing it is
    # not, so a naive `not in` over the whole block reads the justification as
    # the offence. (Caught by this very test on first run; same trap #52 hit.)
    code = [l for _, l in _code(block)]
    curl_lines = [l for l in code if "curl -sS" in l]
    assert len(curl_lines) == 1, "one probe, one guard - re-point this test"
    assert curl_lines[0].rstrip().endswith("|| true"), (
        "an unguarded command substitution under `bash -e` aborts the step on "
        "any curl failure, which is exactly what run #372 did")
    assert not [l for l in code if "|| echo 000" in l], (
        "that is the 000000 bug, not the guard")
    assert "exit 28" in block, "the comment must keep naming what this catches"


def test_the_normalisation_still_covers_an_empty_capture():
    """`|| true` keeps whatever curl managed to write, which on a hard failure
    can be nothing at all. Under `set -u` an EMPTY code must still resolve to
    000 rather than falling through as a bare string into the comparisons."""
    assert re.search(r'case "\$code" in \[0-9\]\[0-9\]\[0-9\]\) ;; \*\) code="000"',
                     _tick_run_block()), "the 3-digit normalisation has moved"
