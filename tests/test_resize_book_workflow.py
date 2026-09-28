"""resize_book.yml - the one-shot open-book restatement (2026-09-27).

Owner, 2026-09-27: $2,500 a position on 60 slots, and restate the 30 open
$5,000 rows now (the 2026-07-28 RESIZE precedent) rather than as they close.
The branch cannot carry resized journal/*.json - main rewrites them every ~30
min - so a merge carries the INTENT (.github/resize-kick) and this workflow
computes the restatement on main, inside the `scan` mutex.

Two of these tests EXECUTE the shipped shell rather than pattern-matching it,
per the house rule that a discriminator is verified in a scratch shell, not
inferred: the preview's Plan step (under `bash -e`, with a stub `python` that
exits with a chosen code), and the resize job's whole commit loop (against a
real bare origin, with a stub `python` whose `--check` reads the files on disk
and whose `--apply` writes them). Everything else is read off the YAML.

The mutex half - resize is a JOB_SCOPED member, the sibling writers check out
their branch tip, close_position's wait loop watches it - lives in
tests/test_workflow_mutex.py beside the pins it extends.

The same commit republishes public/data/bot_rules.json (2026-09-28, review
F1/WF-1/FE-1/C1): without it the site read the old notional beside the
restated book until the next scanner.run, and journal.js told the owner every
restated $2,500 row was held off-scale against "$5,000". The executed loop
runs the shipped regeneration one-liner through the REAL interpreter against
the real scanner.run.bot_rules_payload(), so the file it commits is the file
the workflow would commit.
"""

import ast
import json
import os
import pathlib
import re
import shlex
import shutil
import stat
import subprocess
import sys

import pytest

from scanner import config

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF_PATH = ROOT / ".github" / "workflows" / "resize_book.yml"
KICK = ROOT / ".github" / "resize-kick"
CANON = [f"journal/vivek_bot_book.{m}.json" for m in ("asx", "nasdaq", "crypto")]
DERIVED_BOOKS = ["journal/vivek_bot_book.json", "public/data/vivek_bot_book.json"]
RULES = "public/data/bot_rules.json"
DERIVED = DERIVED_BOOKS + [RULES]


def _doc():
    return yaml.safe_load(WF_PATH.read_text(encoding="utf-8"))


def _code(text):
    """Non-comment lines, stripped. Ask about code, read code: the reasoning
    for each decision is written into the YAML beside it."""
    return [l.strip() for l in text.splitlines()
            if l.strip() and not l.strip().startswith("#")]


def _step(job, fragment):
    for s in _doc()["jobs"][job]["steps"]:
        if fragment.lower() in str(s.get("name", "")).lower():
            return s
    raise AssertionError(f"no step matching {fragment!r} in {job}")


def _loop():
    return _step("resize", "Resize, verify, commit")["run"]


# -- triggers --------------------------------------------------------------

def test_it_fires_only_on_the_kick_and_by_hand():
    on = _doc()[True]
    assert set(on) == {"push", "workflow_dispatch"}, (
        "a one-shot has no business on a cron, and nothing else may start it")
    assert on["push"]["branches"] == ["main"]
    assert on["push"]["paths"] == [".github/resize-kick"], (
        "the workflow file must NOT be in its own path filter: editing it "
        "would restate the live book")


def test_a_manual_dispatch_defaults_to_a_dry_run():
    apply = _doc()[True]["workflow_dispatch"]["inputs"]["apply"]
    assert apply["type"] == "boolean"
    assert apply["default"] is False


def test_apply_from_a_non_main_ref_is_refused():
    run = _step("preview", "Plan")["run"]
    assert '[ "$GITHUB_REF" != "refs/heads/main" ]' in run


# -- the mutex -------------------------------------------------------------

def test_only_the_writer_job_takes_the_scan_mutex():
    doc = _doc()
    top = doc.get("concurrency") or {}
    assert top.get("group") == "resize-book", (
        "workflow-level group must be resize-book, never scan (REFINEMENTS #108)")
    assert doc["jobs"]["resize"]["concurrency"] == {
        "group": "scan", "cancel-in-progress": False}
    for job in ("preview", "evicted"):
        assert "concurrency" not in doc["jobs"][job], (
            f"{job} must stay OUT of `scan`: a dry run must never take (or "
            "evict) the slot, and the eviction reporter must outlive the "
            "eviction it reports")


def test_the_writer_queues_only_when_apply_and_rows_are_pending():
    doc = _doc()
    assert doc["jobs"]["resize"]["needs"] == "preview"
    assert doc["jobs"]["resize"]["if"] == "needs.preview.outputs.go == 'true'"
    assert doc["jobs"]["preview"]["outputs"]["go"] == "${{ steps.plan.outputs.go }}"
    assert _step("preview", "Plan").get("id") == "plan"


def test_every_checkout_reads_the_tip_of_main():
    """Never the trigger SHA (tests/test_workflow_mutex.py has the why). A
    literal `main` here, not github.ref: apply is main-only, and a by-hand dry
    run from a branch should still report on MAIN's book."""
    seen = 0
    for job, spec in _doc()["jobs"].items():
        for s in spec.get("steps") or []:
            if str(s.get("uses", "")).startswith("actions/checkout"):
                seen += 1
                assert (s.get("with") or {}).get("ref") == "main", job
    assert seen == 2, "preview and resize each check out main; evicted needs no tree"


def test_every_job_is_bounded_and_least_privileged():
    doc = _doc()
    assert doc["permissions"] == {"contents": "read"}
    for job, spec in doc["jobs"].items():
        assert isinstance(spec.get("timeout-minutes"), int), job
    assert doc["jobs"]["resize"]["permissions"] == {"contents": "write"}
    assert doc["jobs"]["evicted"]["permissions"] == {}
    assert "permissions" not in doc["jobs"]["preview"], (
        "preview inherits the workflow's contents: read - it writes nothing")


def test_it_uses_only_the_reviewed_first_party_actions():
    uses = {s["uses"] for spec in _doc()["jobs"].values()
            for s in spec.get("steps") or [] if "uses" in s}
    assert uses == {"actions/checkout@v4", "actions/setup-python@v5"}, uses


# -- the loop: regenerate, never replay -------------------------------------

def test_every_attempt_restarts_from_a_fresh_main_and_reruns_the_resize():
    code = _code(_loop())
    assert "for i in 1 2 3 4 5; do" in code
    fetch = code.index("git fetch origin main")
    reset = code.index("git reset --hard origin/main")
    apply = next(i for i, l in enumerate(code) if "--apply" in l)
    assert fetch < reset < apply, "the resize must run on the tree it just reset to"
    body = "\n".join(code)
    for banned in ('git checkout "$SHA"', "git checkout $SHA", "git pull --rebase",
                   "git add -A", "git add -u", "--rebuild-combined"):
        assert banned not in body, (
            f"{banned!r} replays or sweeps files from an older tree - a resize "
            "computed from an older main carries that main's marks")
    assert code[-1] == "exit 1", "five lost push races must end red"


def test_every_script_call_carries_the_kick():
    """The kick is the authorisation. A `--check` or `--apply` without it would
    restate to whatever config says, whether or not a human asked for it."""
    calls = [l for l in _code(_loop()) if "resize_book_notional.py" in l]
    assert len(calls) == 3, calls            # pre-check, apply, postcondition
    for line in calls:
        assert "--kick .github/resize-kick" in line, line


def test_the_must_change_gate_sits_behind_the_pending_discriminator():
    code = _code(_loop())
    pre = next(i for i, l in enumerate(code) if "--check" in l)
    noop = code.index('if [ "$rc" = "0" ]; then')
    apply = next(i for i, l in enumerate(code) if "--apply" in l)
    gate = next(i for i, l in enumerate(code) if "assert_staged.sh" in l)
    assert pre < noop < apply < gate, (
        "an idempotent re-run must exit green BEFORE the must-change gate, "
        "and a pending run must reach it")
    assert 'if [ "$rc" != "3" ]; then' in code, "rc other than 0/3 must stop the run"


def test_the_gate_names_the_canonical_books_only():
    line = next(l for l in _code(_loop()) if "assert_staged.sh" in l)
    assert line == 'bash scripts/assert_staged.sh "open-book resize" $CANON'
    canon = re.search(r'CANON="([^"]+)"', _loop()).group(1).split()
    assert canon == CANON
    for d in DERIVED:
        assert d not in line, "any-of semantics: a derived view would satisfy it alone"


def test_the_postcondition_is_re_read_off_disk_before_the_commit():
    code = _code(_loop())
    apply = next(i for i, l in enumerate(code) if "--apply" in l)
    post = next(i for i, l in enumerate(code) if i > apply and "--check" in l)
    verify = code.index("python -m scanner.broker.vivek_run --verify")
    unstaged = next(i for i, l in enumerate(code) if l.startswith("if ! git diff --quiet --"))
    commit = next(i for i, l in enumerate(code) if l.startswith("git commit"))
    assert apply < post < verify < commit and unstaged < commit
    assert code[post].startswith("if ! python "), (
        "the postcondition must be an `if !` - a bare call under `bash -e` "
        "would exit with the script's 3 instead of the explained refusal")


def test_staging_is_surgical_and_never_swallowed():
    adds = [l for l in _code(WF_PATH.read_text(encoding="utf-8")) if l.startswith("git add")]
    assert adds == ['git add -- "$p"'], adds
    assert "for p in $CANON $DERIVED; do" in _code(_loop())
    assert "|| true" not in "".join(adds), (
        "all six files exist on a healthy main - a missing one must stop the run")
    derived = re.search(r'DERIVED="([^"]+)"', _loop()).group(1).split()
    assert derived == DERIVED
    assert "if ! git diff --quiet -- $CANON $DERIVED; then" in _code(_loop()), (
        "the unstaged-diff guard must cover every staged path, the rules included")


# -- the rules republish (review F1) ------------------------------------------

def _regen_line():
    lines = [l for l in _code(_loop()) if "bot_rules_payload" in l]
    assert len(lines) == 1, lines
    return lines[0]


def _write_call(tree, fragment):
    """The single output.write_json(...) call whose path mentions `fragment`."""
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "write_json"
             and n.args and fragment in ast.dump(n.args[0])]
    assert len(calls) == 1, [ast.dump(c) for c in calls]
    return calls[0]


def _main_rules_call():
    from scanner import run
    tree = ast.parse(pathlib.Path(run.__file__).read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    return _write_call(main, "bot_rules.json")


def _kw(call):
    return {k.arg: ast.literal_eval(k.value) for k in call.keywords}


def test_the_rules_are_regenerated_after_verify_on_every_attempt():
    """Inside the loop, after the reset: regenerated per attempt from the tree
    it just reset to, never replayed. After --verify: nothing is republished
    beside a book that failed its audit. Before the staging: it has to be in
    the commit."""
    code = _code(_loop())
    loop = code.index("for i in 1 2 3 4 5; do")
    reset = code.index("git reset --hard origin/main")
    apply = next(i for i, l in enumerate(code) if "--apply" in l)
    verify = code.index("python -m scanner.broker.vivek_run --verify")
    regen = code.index(_regen_line())
    stage = code.index("for p in $CANON $DERIVED; do")
    commit = next(i for i, l in enumerate(code) if l.startswith("git commit"))
    end = len(code) - 1 - code[::-1].index("done")      # the attempt loop's own
    assert loop < reset < apply < verify < regen < stage < commit < end, (
        loop, reset, apply, verify, regen, stage, commit, end)
    assert RULES not in re.search(r'CANON="([^"]+)"', _loop()).group(1), (
        "generated_at moves on every run: in the any-of gate the rules file "
        "would pass it unconditionally")


def test_the_regeneration_is_the_same_publish_run_py_does():
    """ONE builder, one writer, same arguments: the workflow's `python -c`
    parses, calls run.bot_rules_payload() and output.write_json with exactly
    the keywords main() uses - so the two publishes differ only in
    generated_at (the executed loop test proves the bytes)."""
    argv = shlex.split(_regen_line())
    assert argv[:2] == ["python", "-c"] and len(argv) == 3, argv
    call = _write_call(ast.parse(argv[2]), "bot_rules.json")
    assert ast.literal_eval(call.args[0].args[0]) == RULES
    assert ast.unparse(call.args[1]) == "run.bot_rules_payload()"
    main_call = _main_rules_call()
    assert ast.unparse(main_call.args[1]) == "bot_rules_payload()", (
        "main() must publish the builder's output, not a dict of its own")
    assert _kw(call) == _kw(main_call) == {"newline": True}


def test_the_payload_is_the_checked_out_config():
    from scanner import run
    p = run.bot_rules_payload()
    assert p["position_notional"] == config.VIVEK_BOT_POSITION_NOTIONAL
    assert p["max_open_total"] == config.VIVEK_BOT_MAX_OPEN_TOTAL
    assert p["max_positions"] == config.VIVEK_BOT_MAX_POSITIONS
    assert p["max_per_sector"] == config.VIVEK_BOT_MAX_PER_SECTOR
    assert p["max_portfolio_notional"] == config.VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL


# -- eviction: loud, and deliberately not auto-redispatched ------------------

def test_an_eviction_turns_the_run_red_with_the_remedy():
    job = _doc()["jobs"]["evicted"]
    assert set(job["needs"]) == {"preview", "resize"}
    assert "always()" in job["if"] and "needs.resize.result == 'cancelled'" in job["if"]
    assert "failure" not in job["if"], (
        "a FAILED resize already turns the run red and names its own error")
    run = job["steps"][-1]["run"]
    assert _code(run)[-1] == "exit 1"
    assert "GITHUB_STEP_SUMMARY" in run and "apply = true" in run


def test_there_is_DELIBERATELY_no_auto_redispatch():
    """Decision, not omission. The resize is idempotent and an un-applied one
    is fail-safe (old-size rows keep counting at full notional against the
    portfolio ceiling), so a by-hand re-run is enough - and a second WATCHED
    list would be a second thing to drift from `scan` membership. If this is
    ever reversed, copy close_position.yml's redispatch AND its pins."""
    code = "\n".join(_code(WF_PATH.read_text(encoding="utf-8")))
    assert "gh workflow run" not in code
    assert "actions: write" not in code


def test_there_is_DELIBERATELY_no_watchdog_entry():
    """A one-shot never runs again: a run-age alarm would fire 26h after the
    resize and ring for ever. Same shape as momentum.yml's pinned absence -
    it gets the other half of the CLAUDE.md rule (an assert_staged, gated
    behind the pending discriminator) and not this one."""
    assert "resize_book.yml" not in config.WATCHDOG_RUNS


def test_the_wide_stop_trim_is_never_passed():
    """CLAUDE.md RESIZE: the owner DECLINED `--max-stop-pct` (2026-07-28) -
    rows opened under the rules of their day keep full size. A restatement
    workflow is exactly where that flag would creep in."""
    code = "\n".join(_code(WF_PATH.read_text(encoding="utf-8")))
    assert "--max-stop-pct" not in code
    assert "--target" not in code, (
        "the target comes from config and is cross-checked against the kick; "
        "a hard-coded --target would bypass that agreement")


# -- the kick ----------------------------------------------------------------

def test_the_kick_authorises_exactly_the_configured_notional():
    """A kick that disagrees with config would turn the owner's merge red (the
    script refuses). If config.VIVEK_BOT_POSITION_NOTIONAL changes later, this
    fails ON PURPOSE: update target= (and the push restates the open book) or
    delete the kick (and it does not) - the open book is a decision either way,
    never a side effect of a config edit."""
    if not KICK.exists():
        pytest.skip("no kick on this tree - nothing is authorised")
    from scripts import resize_book_notional as rz
    assert rz.kick_target(KICK) == float(config.VIVEK_BOT_POSITION_NOTIONAL)
    raw = KICK.read_bytes()
    assert raw.isascii(), "ASCII only - a stray byte-order mark is how the 2026-08-01 secret broke"
    assert raw.endswith(b"\n")


def test_a_push_touching_only_the_kick_still_runs_ci():
    """TOP100 #48's rule: every path a suite reads is in test.yml's push
    filter. The test above reads the kick, and a kick-only push is exactly
    the one that restates the book - it must not ship with the gate skipped."""
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml")
                        .read_text(encoding="utf-8"))
    assert ".github/resize-kick" in ci[True]["push"]["paths"]


# -- the plan step, EXECUTED ------------------------------------------------

def _stub(bindir, name, body):
    p = bindir / name
    p.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def _run_plan(tmp_path, *, rc, apply, event="push", ref="refs/heads/main",
              kick=True):
    """Run the shipped Plan step under `bash -e` with a stub `python`."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub(bindir, "python", f'echo "STUB-PY $*"\nexit {rc}\n')
    (tmp_path / ".github").mkdir()
    if kick:
        (tmp_path / ".github" / "resize-kick").write_text("target=2500\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "t"], cwd=tmp_path, check=True)
    out, summ = tmp_path / "out", tmp_path / "summary"
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               APPLY="true" if apply else "false", EVENT=event, GITHUB_REF=ref,
               GITHUB_OUTPUT=str(out), GITHUB_STEP_SUMMARY=str(summ),
               RUNNER_TEMP=str(tmp_path))
    p = subprocess.run(["bash", "-e", "-c", _step("preview", "Plan")["run"]],
                       cwd=tmp_path, env=env, capture_output=True, text=True)
    go = "go=true" in (out.read_text() if out.exists() else "")
    return p.returncode, go, p.stdout + p.stderr


@pytest.mark.parametrize("rc,apply,want_rc,want_go", [
    (3, True, 0, True),     # rows pending + apply -> queue the writer
    (3, False, 0, False),   # rows pending, dry run -> report only
    (0, True, 0, False),    # already at target -> green no-op, no mutex slot
    (2, True, 2, False),    # kick/config mismatch -> red, nothing queued
    (1, True, 1, False),    # a crash is NEVER "pending"
    (4, True, 4, False),    # an off-target row the script cannot restate -> red,
    (4, False, 4, False),   #   never a green "nothing to resize" (review RR-1)
])
def test_the_plan_taxonomy(tmp_path, rc, apply, want_rc, want_go):
    got_rc, go, out = _run_plan(tmp_path, rc=rc, apply=apply)
    assert (got_rc, go) == (want_rc, want_go), out
    assert "STUB-PY scripts/resize_book_notional.py --check --kick .github/resize-kick" in out


def test_a_deleted_kick_is_a_green_no_op_on_push_and_red_by_hand(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    rc, go, out = _run_plan(a, rc=3, apply=True, kick=False)
    assert (rc, go) == (0, False), out
    assert "STUB-PY" not in out, "no kick: the script must not even be asked"
    rc, go, out = _run_plan(b, rc=3, apply=True, kick=False, event="workflow_dispatch")
    assert rc == 1 and not go, out


def test_a_dry_run_without_a_kick_still_measures_against_config(tmp_path):
    rc, go, out = _run_plan(tmp_path, rc=3, apply=False, kick=False,
                            event="workflow_dispatch")
    assert (rc, go) == (0, False), out
    call = out.split("STUB-PY", 1)[1].splitlines()[0]
    assert call.strip() == "scripts/resize_book_notional.py --check", call


def test_apply_dispatched_off_main_never_queues(tmp_path):
    rc, go, out = _run_plan(tmp_path, rc=3, apply=True, event="workflow_dispatch",
                            ref="refs/heads/claude/some-branch")
    assert rc == 1 and not go and "STUB-PY" not in out, out


# -- the resize loop, EXECUTED against a real origin -------------------------
#
# The stub `python` stands in for the resize script and the verify. Its
# `--check` reads the DERIVED public twin off disk (pending while it still says
# "old"), so the postcondition is a genuine re-read; `--apply` writes "new"
# into the files named by STUB_APPLY; the verify succeeds unless STUB_VERIFY_RC
# says otherwise. Every `-c` (the TARGET lookup and the bot_rules.json
# regeneration) is handed to the REAL interpreter with the repo on PYTHONPATH,
# so the shipped one-liners run for real; the regeneration is counted first.
# STUB_RACE makes the first `--apply` push a sibling commit to origin first -
# one that also republished bot_rules.json, as a scan landing mid-resize
# would - i.e. a real non-fast-forward race the loop must regenerate through.

_PY_STUB = r'''
S="$STUB_STATE"
if [ "$1" = "-c" ]; then
  case "$2" in
    *bot_rules_payload*)
      n=$(( $(cat "$S/rules" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$S/rules" ;;
  esac
  exec "$REAL_PY" "$@"
fi
if [ "$1" = "-m" ]; then echo "STUB-VERIFY $*"; exit "${STUB_VERIFY_RC:-0}"; fi
case " $* " in
  *" --check "*)
    n=$(( $(cat "$S/checks" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$S/checks"
    if [ "$n" = "1" ] && [ -n "${STUB_PRE_RC:-}" ]; then exit "$STUB_PRE_RC"; fi
    if grep -q old public/data/vivek_bot_book.json; then echo "CHECK: pending"; exit 3; fi
    echo "CHECK: 0 off"; exit 0 ;;
  *" --apply "*)
    n=$(( $(cat "$S/applies" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$S/applies"
    if [ -n "${STUB_APPLY_RC:-}" ]; then exit "$STUB_APPLY_RC"; fi
    if [ "$n" = "1" ] && [ -n "${STUB_RACE:-}" ]; then
      echo sibling-rules > "$STUB_SIBLING/public/data/bot_rules.json"
      git -C "$STUB_SIBLING" -c user.name=sib -c user.email=sib@x \
        commit -qam "sibling: scan landed mid-resize"
      git -C "$STUB_SIBLING" push -q origin HEAD:main
    fi
    for f in $STUB_APPLY; do echo new > "$f"; done
    exit 0 ;;
esac
echo "STUB-PY unexpected: $*" >&2; exit 97
'''


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "init.defaultBranch=main", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


def _run_loop(tmp_path, *, apply_files, start="old", pre_rc=None, race=False,
              verify_rc=None, apply_rc=None):
    origin, seed, runner, sib = (tmp_path / n for n in ("origin.git", "seed", "runner", "sib"))
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    seed.mkdir()
    _git(seed, "init", "-q")
    for rel in CANON + DERIVED:
        (seed / rel).parent.mkdir(parents=True, exist_ok=True)
        (seed / rel).write_text(start + "\n")
    (seed / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "assert_staged.sh", seed / "scripts" / "assert_staged.sh")
    (seed / ".github").mkdir()
    (seed / ".github" / "resize-kick").write_text("target=2500\n")
    _git(seed, "add", "-A")
    _git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "origin", "HEAD:main")
    _git(tmp_path, "clone", "-q", str(origin), str(runner))
    _git(tmp_path, "clone", "-q", str(origin), str(sib))

    bindir, state = tmp_path / "bin", tmp_path / "state"
    bindir.mkdir(); state.mkdir()
    _stub(bindir, "python", _PY_STUB)
    _stub(bindir, "sleep", "exit 0\n")          # the retry back-off, not under test
    summ = tmp_path / "summary"
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               GITHUB_STEP_SUMMARY=str(summ), RUNNER_TEMP=str(tmp_path),
               STUB_STATE=str(state), STUB_SIBLING=str(sib),
               STUB_APPLY=" ".join(apply_files),
               REAL_PY=sys.executable, PYTHONPATH=str(ROOT))
    if verify_rc is not None:
        env["STUB_VERIFY_RC"] = str(verify_rc)
    if pre_rc is not None:
        env["STUB_PRE_RC"] = str(pre_rc)
    if apply_rc is not None:
        env["STUB_APPLY_RC"] = str(apply_rc)
    if race:
        env["STUB_RACE"] = "1"
    before = _git(origin, "rev-parse", "main")
    p = subprocess.run(["bash", "-e", "-c", _loop()], cwd=runner, env=env,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr, origin, before


def _log(origin):
    return _git(origin, "log", "--format=%an|%s", "main").splitlines()


def _regens(tmp_path):
    f = tmp_path / "state" / "rules"
    return int(f.read_text().strip()) if f.exists() else 0


_GEN = re.compile(r'"generated_at": "[^"]*"')


def _assert_origin_rules_are_the_payload(tmp_path, origin):
    """origin's bot_rules.json is byte-for-byte what run.py's own publish
    writes today, bar generated_at - and it carries the checked-out config."""
    from scanner import output, run
    got = subprocess.run(["git", "show", f"main:{RULES}"], cwd=origin, check=True,
                         capture_output=True).stdout.decode("utf-8")   # exact bytes
    ref = output.write_json(tmp_path / "ref_rules.json", run.bot_rules_payload(),
                            newline=True).read_text(encoding="utf-8")
    assert _GEN.sub("G", got) == _GEN.sub("G", ref)
    j = json.loads(got)
    for key, want in (("position_notional", config.VIVEK_BOT_POSITION_NOTIONAL),
                      ("max_open_total", config.VIVEK_BOT_MAX_OPEN_TOTAL),
                      ("max_positions", config.VIVEK_BOT_MAX_POSITIONS),
                      ("max_per_sector", config.VIVEK_BOT_MAX_PER_SECTOR)):
        assert j[key] == want, (key, j[key], want)


def test_the_loop_commits_the_five_books_and_the_rules_and_pushes(tmp_path):
    rc, out, origin, _ = _run_loop(tmp_path, apply_files=CANON + DERIVED_BOOKS)
    assert rc == 0, out
    top = _log(origin)[0]
    target = int(config.VIVEK_BOT_POSITION_NOTIONAL)
    assert top == f"github-actions[bot]|journal: restate open book at ${target}/position (resize kick)", top
    files = _git(origin, "show", "--name-only", "--format=", "main").split()
    assert sorted(files) == sorted(CANON + DERIVED), (
        "one commit: the restated books AND the rules that describe them")
    assert _git(origin, "show", "main:journal/vivek_bot_book.asx.json") == "new"
    assert _regens(tmp_path) == 1
    _assert_origin_rules_are_the_payload(tmp_path, origin)


def test_a_resize_already_on_main_is_a_green_no_op_with_no_commit(tmp_path):
    rc, out, origin, before = _run_loop(tmp_path, apply_files=CANON + DERIVED_BOOKS,
                                        start="new")
    assert rc == 0, out
    assert _git(origin, "rev-parse", "main") == before, "a no-op must not push"
    assert "nothing to write" in out
    assert _regens(tmp_path) == 0


@pytest.mark.parametrize("pre_rc", [1, 2, 4])
def test_a_refused_or_crashed_pre_check_writes_and_pushes_nothing(tmp_path, pre_rc):
    rc, out, origin, before = _run_loop(tmp_path, apply_files=CANON + DERIVED_BOOKS,
                                        pre_rc=pre_rc)
    assert rc == pre_rc, out
    assert _git(origin, "rev-parse", "main") == before
    assert "STUB-PY unexpected" not in out
    assert _regens(tmp_path) == 0


def test_an_apply_that_refuses_a_stuck_row_pushes_nothing(tmp_path):
    # --apply exits 4 (an off-target row it cannot restate, review RR-1): the
    # loop dies under `bash -e` with that code, nothing is republished, main
    # is untouched.
    rc, out, origin, before = _run_loop(tmp_path, apply_files=CANON + DERIVED_BOOKS,
                                        apply_rc=4)
    assert rc == 4, out
    assert _git(origin, "rev-parse", "main") == before
    assert _regens(tmp_path) == 0


def test_an_apply_that_did_not_land_on_disk_is_refused_by_the_postcondition(tmp_path):
    rc, out, origin, before = _run_loop(tmp_path, apply_files=[])
    assert rc == 1, out
    assert "still finds rows off target" in out
    assert _git(origin, "rev-parse", "main") == before
    assert _regens(tmp_path) == 0


def test_a_book_that_fails_verify_republishes_nothing_and_pushes_nothing(tmp_path):
    rc, out, origin, before = _run_loop(tmp_path, apply_files=CANON + DERIVED_BOOKS,
                                        verify_rc=1)
    assert rc == 1, out
    assert _git(origin, "rev-parse", "main") == before
    assert _regens(tmp_path) == 0, "the rules must not be republished beside a book that failed its audit"


def test_a_restatement_that_only_moved_the_derived_view_fails_the_gate(tmp_path):
    """The any-of gate names the CANONICAL files: a run that regenerated the
    combined book + public twin while every per-market file failed to change
    is the staging loss the gate exists for, not a success. The rules file
    WAS regenerated and staged here (it changes on every run), and that must
    not satisfy the gate either."""
    rc, out, origin, before = _run_loop(tmp_path, apply_files=DERIVED_BOOKS)
    assert rc == 1, out
    assert "ASSERT-STAGED FAILED (open-book resize)" in out
    assert _git(origin, "rev-parse", "main") == before
    assert _regens(tmp_path) == 1


def test_a_lost_push_race_regenerates_on_the_new_main_and_keeps_the_sibling(tmp_path):
    rc, out, origin, _ = _run_loop(tmp_path, apply_files=CANON + DERIVED_BOOKS, race=True)
    assert rc == 0, out
    assert "push race - retry 1" in out and "Pushed the restated book (attempt 2)." in out
    log = _log(origin)
    assert log[0].endswith("(resize kick)") and log[1] == "sib|sibling: scan landed mid-resize", log
    assert (tmp_path / "state" / "applies").read_text().strip() == "2", (
        "attempt 2 must RE-RUN the resize on the new main, not replay attempt 1")
    assert _regens(tmp_path) == 2, (
        "attempt 2 must REGENERATE the rules on the new main, not replay attempt 1")
    _assert_origin_rules_are_the_payload(tmp_path, origin)
