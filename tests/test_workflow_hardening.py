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
