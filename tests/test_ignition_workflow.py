"""ignition.yml -- its own invariants, the omissions that are DECISIONS, and
the shell that is EXECUTED rather than read.

The repo-wide workflow invariants already apply automatically, because
`tests/test_workflow_hardening.py` globs `.github/workflows/*.yml`: valid
shell in every `run:`, one pathspec per `git add`, a swallowed `git add`
paired with a must-change gate, a declared `permissions:` block, and the
first-party `actions/*` tripwire.

What is pinned HERE is what is specific to this lens, in the house style of
tests/test_momentum_workflow.py, with one difference in method: wherever a
step's behaviour can be RUN, it is run. Four run blocks are executed against
real git repositories in tmp_path (a bare "origin" plus a clone, exactly the
shape actions/checkout leaves behind):

  * the BACKSTOP GATE, under a frozen `date` -- today's stamp stops the run,
    yesterday's / a missing / a corrupt file lets it through, and every
    trigger that is not the backstop cron is due without touching git;
  * the SCREEN and BACKTEST steps, with a stub `python` returning each exit
    code -- 0 publishes, 3 is a reported no-op, anything else is red (and
    the backtest's `| tee` is only honest because of `pipefail`, which the
    stub proves);
  * the COMMIT step -- a kick on a feature branch writes that branch and
    leaves main byte-identical, only the files the run reported publishing
    are staged, a sibling's newer copy of an unpublished file survives, and
    a publish that staged nothing is RED.

A regex over the YAML can say a line is present; only running it says the
line does what the comment beside it claims.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess

import pytest
import yaml

from scanner import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
WFDIR = ROOT / ".github" / "workflows"
WF = WFDIR / "ignition.yml"
SRC = WF.read_text(encoding="utf-8")
DOC = yaml.safe_load(SRC)
JOB = DOC["jobs"]["ignition"]
STEPS = JOB["steps"]
# PyYAML parses a bare `on:` key as the boolean True.
ON = DOC.get("on") or DOC[True]

CANON = ("public/data/ignition/crypto.json",
         "public/data/ignition/crypto_backtest.json")
KICK = ".github/ignition-kick"
PRIMARY_CRON = "14 0 * * *"
BACKSTOP_CRON = "14 1,2 * * *"   # the scheduler-drop backstop the gate recognises
GATE_OK = "steps.due.outputs.run == 'true'"

BASH = shutil.which("bash")
GIT = shutil.which("git")
REAL_DATE = shutil.which("date")


def _gnu_date() -> bool:
    if not REAL_DATE:
        return False
    p = subprocess.run([REAL_DATE, "-u", "-d", "@0", "+%Y"], capture_output=True, text=True)
    return p.returncode == 0 and p.stdout.strip() == "1970"


needs_shell = pytest.mark.skipif(
    not (BASH and GIT), reason="bash and git are needed to execute the run blocks")
needs_gnu_date = pytest.mark.skipif(
    not _gnu_date(), reason="the frozen-clock shim needs GNU date (-d @epoch)")


def _step(**match) -> dict:
    key, value = next(iter(match.items()))
    found = [s for s in STEPS if s.get(key) == value]
    assert len(found) == 1, f"expected exactly one step with {key}={value!r}"
    return found[0]


def _index(step: dict) -> int:
    return next(i for i, s in enumerate(STEPS) if s is step)


GATE = _step(id="due")
SCAN = _step(id="scan")
BT = _step(id="bt")
COMMIT = _step(name="Commit and push")


def _code(body: str) -> list[str]:
    """Non-comment, non-blank lines of a run block, stripped. The reasoning
    for each decision is written into the YAML beside it, so a substring
    search over the whole text reads the justification as the offence."""
    return [ln.strip() for ln in body.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


# ---------------------------------------------------------------------------
# `if:` expressions, split the way GitHub evaluates them
# ---------------------------------------------------------------------------

def _strip_outer_parens(e: str) -> str:
    e = e.strip()
    while e.startswith("(") and e.endswith(")"):
        depth = 0
        for i, ch in enumerate(e):
            depth += ch == "("
            depth -= ch == ")"
            if depth == 0 and i != len(e) - 1:
                return e          # the first "(" closes before the end
        e = e[1:-1].strip()
    return e


def _split_top(expr: str, op: str) -> list[str]:
    """Split at top-level `&&` / `||`, respecting parentheses and quotes."""
    expr = _strip_outer_parens(expr)
    out, depth, quote, cur, i = [], 0, None, "", 0
    while i < len(expr):
        ch = expr[i]
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and expr.startswith(op, i):
            out.append(_strip_outer_parens(cur))
            cur, i = "", i + len(op)
            continue
        cur += ch
        i += 1
    out.append(_strip_outer_parens(cur))
    return [" ".join(x.split()) for x in out]


def _conjuncts_of(expr: str) -> list[str]:
    """The top-level `&&` conjuncts of a GitHub expression, PRECEDENCE-CORRECT.

    In GitHub's expression language `&&` binds tighter than `||` (the JS
    order), so `a || b && c` is `a || (b && c)`: an OR at the top level, with
    NO top-level conjuncts to speak of -- it is returned whole, as one term.
    Splitting on `&&` first would read it as `(a || b) && c`, which is exactly
    the mistake a mutation pass caught in the first draft of this file (the
    commit condition lost its parentheses and every test stayed green)."""
    if len(_split_top(expr, "||")) > 1:
        return [" ".join(_strip_outer_parens(expr).split())]
    return _split_top(expr, "&&")


def _conjuncts(step: dict) -> list[str]:
    cond = step.get("if")
    return _conjuncts_of(str(cond)) if cond else []


def test_the_expression_splitter_splits_the_way_github_evaluates():
    """Guards the condition tests below, which are only as good as it."""
    assert _conjuncts_of("a == 'x' && (b || c) && d") == ["a == 'x'", "b || c", "d"]
    assert _conjuncts_of("(a || b) && c") == ["a || b", "c"]
    assert _conjuncts_of("a || b && c") == ["a || b && c"], "&& binds tighter than ||"
    assert _conjuncts_of("x == 'a && b'") == ["x == 'a && b'"]
    assert _conjuncts_of("((a && b))") == ["a", "b"]
    assert _conjuncts_of("(a) || (b)") == ["(a) || (b)"]
    assert _split_top("a || b", "||") == ["a", "b"]
    assert _split_top("a || b && c", "||") == ["a", "b && c"]


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------

def test_it_has_its_own_concurrency_group_and_is_not_in_the_scan_mutex():
    """`group: scan` is the paper-book mutex. This lens writes no book, so it
    has no business in that queue: GitHub keeps only ONE pending run per
    group and cancels the previously-pending one, so joining it would start
    evicting the freshness backstops and the manual close -- and
    test_workflow_mutex.py would then demand it in close_position.yml's
    wait-loop watch list."""
    assert JOB.get("concurrency") is None, "the group belongs at workflow level here"
    group = str(DOC["concurrency"]["group"])
    assert group.startswith("ignition"), group
    assert "scan" not in group, group
    assert DOC["concurrency"]["cancel-in-progress"] is False, (
        "cancelling in progress would kill a run mid-push")
    for path in sorted(WFDIR.glob("*.yml")):
        if path.name == WF.name:
            continue
        other = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        groups = [str((other.get("concurrency") or {}).get("group", ""))]
        groups += [str((j.get("concurrency") or {}).get("group", ""))
                   for j in (other.get("jobs") or {}).values() if isinstance(j, dict)]
        assert not any(g.startswith("ignition") for g in groups), path.name


def test_it_declares_least_privilege_and_a_timeout():
    """contents: write and NOTHING else -- no actions:, no id-token:, no
    pull-requests:. It commits its own data files; it dispatches nothing."""
    assert DOC["permissions"] == {"contents": "write"}
    assert JOB.get("permissions") in (None, {"contents": "write"}), JOB.get("permissions")
    t = JOB.get("timeout-minutes")
    assert isinstance(t, int) and 0 < t < 360, (
        "an unbounded (360m default) job holds the group for six hours and "
        "stalls every later refresh with it")


def test_the_triggers_are_the_crons_a_kick_file_and_a_manual_dispatch():
    """The push trigger fires on the kick file and NOTHING else -- any wider
    path filter would run a write workflow on ordinary code pushes. No
    `branches:` filter, deliberately: a kick on a feature branch is how a
    cloud session evaluates the lens before it reaches main (and the commit
    step writes back to THAT branch, pinned below). No pull_request trigger
    of either kind: a write-permission workflow must never run on PR code."""
    assert set(ON) == {"schedule", "push", "workflow_dispatch"}, sorted(ON)
    assert ON["push"] == {"paths": [KICK]}, ON["push"]
    inputs = ON["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"backtest", "dry_run"}, sorted(inputs)
    for name in ("backtest", "dry_run"):
        assert inputs[name]["type"] == "boolean", name
        assert inputs[name]["default"] is False, name
    crons = [c["cron"] for c in ON["schedule"]]
    assert crons.count(PRIMARY_CRON) == 1, (
        "the first run after the 00:00 UTC crypto close is the one that matters")
    for cron in crons:
        assert cron.split()[0] not in ("0", "00"), (
            f"{cron!r}: minute 0 is where GitHub's scheduler queues deepest")


def test_every_run_block_is_valid_shell():
    """`bash -n` on every step body, executed -- repeated here so a broken
    ignition block is reported against THIS file, not only the repo sweep."""
    blocks = [s for s in STEPS if s.get("run")]
    assert len(blocks) >= 4, "fewer run blocks than the gate/scan/backtest/commit"
    if not BASH:
        pytest.skip("bash not available")
    broken = []
    for s in blocks:
        p = subprocess.run([BASH, "-n"], input=str(s["run"]), text=True, capture_output=True)
        if p.returncode != 0:
            broken.append(f"{s.get('name') or s.get('id')}: {p.stderr.strip()}")
    assert broken == [], broken


def test_it_uses_its_own_frame_cache_namespace():
    """Sharing `vivek-frames-` (or `momentum-frames-`) would mix a 5y screen
    window with another lens's under the same keys; a separate namespace is
    also one more thing that disappears cleanly with the lens. Checked on the
    key VALUES, not the file text -- the comment above the step names the
    other namespaces on purpose."""
    caches = [s for s in STEPS if str(s.get("uses", "")).startswith("actions/cache")]
    assert len(caches) == 1, caches
    with_ = caches[0]["with"]
    keys = [with_["key"], *str(with_.get("restore-keys", "")).split()]
    assert keys and all(k.startswith("ignition-frames-") for k in keys if k), keys
    assert with_["path"] == ".cache/frames"


# ---------------------------------------------------------------------------
# the backstop gate -- position and conditions
# ---------------------------------------------------------------------------

def _directly_gated(step: dict) -> bool:
    return GATE_OK in _conjuncts(step)


def test_the_gate_runs_before_anything_is_installed():
    """A no-op backstop wake-up must stop before setup-python, the pip
    install and the cache restore -- that is what makes the two extra crons
    free on a healthy day. Only the checkout may precede the gate (it reads
    git), and the gate itself uses the runner's own python3 for one stdlib
    json parse and nothing from the repo."""
    gi = _index(GATE)
    assert gi == 1 and str(STEPS[0].get("uses", "")).startswith("actions/checkout"), (
        [s.get("id") or s.get("name") or s.get("uses") for s in STEPS])
    installers = [i for i, s in enumerate(STEPS)
                  if str(s.get("uses", "")).startswith(("actions/setup-python", "actions/cache"))
                  or "pip install" in str(s.get("run", ""))]
    assert installers and min(installers) > gi, installers
    body = GATE["run"]
    code = "\n".join(_code(body))
    assert "pip" not in code and "scanner" not in code and "python -m" not in code
    snippets = re.findall(r'python3 -c "([^"]*)"', body)
    assert snippets, "the stamp parse moved - re-point this test"
    for s in snippets:
        assert set(re.findall(r"import ([\w, ]+)", s)[0].replace(" ", "").split(",")) \
            <= {"json", "sys"}, s


def test_every_step_after_the_gate_is_skipped_when_the_gate_says_no():
    """Each later step either carries `steps.due.outputs.run == 'true'` as a
    top-level `&&` conjunct, or has a conjunct that is ONLY an OR of `== 'true'`
    checks on outputs of steps that do -- which is false when those steps were
    skipped, so it is gated transitively. Split the way GitHub evaluates the
    expression, so `a || b && gate` cannot pass for `(a || b) && gate`."""
    gated = set()
    ungated = []
    for step in STEPS[_index(GATE) + 1:]:
        label = step.get("id") or step.get("name") or step.get("uses")
        if _directly_gated(step):
            if step.get("id"):
                gated.add(step["id"])
            continue
        ok = False
        for conj in _conjuncts(step):
            terms = _split_top(conj, "||")
            ids = [re.fullmatch(r"steps\.(\w+)\.outputs\.\w+ == 'true'", t) for t in terms]
            if all(ids) and {m.group(1) for m in ids} <= gated:
                ok = True
        if not ok:
            ungated.append(f"{label}: if: {step.get('if')!r}")
    assert ungated == [], "\n  ".join(ungated)
    assert {"scan", "bt"} <= gated


def test_the_backtest_runs_only_on_a_kick_or_when_a_human_asks():
    """The replay answers a question; it is not a feed. So no cron can run it
    -- only a push (which can only be the kick file, pinned above) or a
    manual dispatch with `backtest: true`."""
    conj = _conjuncts(BT)
    assert GATE_OK in conj
    rest = [c for c in conj if c != GATE_OK]
    assert len(rest) == 1, conj
    assert set(_split_top(rest[0], "||")) == {"github.event_name == 'push'",
                                              "inputs.backtest == true"}, rest
    assert "--backtest" in BT["run"] and "--backtest" not in "\n".join(_code(SCAN["run"]))


def test_the_commit_step_runs_only_on_a_real_publish_and_never_on_a_dry_run():
    """Exit 3 -- "the download came back empty, the previous file stands" --
    is a reported DECISION, not a fault. Letting it reach the commit step
    would fire `assert_staged` on a gate that is correctly unmet, and a
    must-change gate that cries wolf is one that gets deleted."""
    conj = _conjuncts(COMMIT)
    assert "inputs.dry_run != true" in conj, conj
    published = [c for c in conj if c != "inputs.dry_run != true"]
    assert len(published) == 1
    assert set(_split_top(published[0], "||")) == {
        "steps.scan.outputs.published == 'true'",
        "steps.bt.outputs.published == 'true'"}, published


# ---------------------------------------------------------------------------
# executing run blocks -- the harness
# ---------------------------------------------------------------------------

# A frozen instant DIFFERENT from any plausible real date, so a test that
# passes because the shim is ignored and the real clock happens to agree
# cannot exist.
FAKE_NOW = dt.datetime(2031, 3, 4, 1, 14, 5, tzinfo=dt.timezone.utc)   # a 01:14 backstop
FAKE_EPOCH = int(FAKE_NOW.timestamp())      # derived, never hand-typed
FAKE_TODAY = FAKE_NOW.strftime("%Y-%m-%d")
STAMP_TODAY = "2031-03-04T00:14:31+00:00"
STAMP_YESTERDAY = "2031-03-03T21:44:10+00:00"


def _write_exe(path: pathlib.Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def sh(tmp_path):
    """An isolated environment for running workflow shell.

    `HOME`, `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_NOSYSTEM` keep the developer's
    own git config (signing, hooks, aliases) out of it -- a runner has none.
    `bin/` is prepended to PATH for the stubs: `date` answers from
    FAKE_EPOCH, and `git` logs every invocation before exec'ing the real one.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text("", encoding="utf-8")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    git_log = tmp_path / "git-calls.log"
    git_log.write_text("", encoding="utf-8")
    if REAL_DATE:
        _write_exe(bin_ / "date",
                   f'#!/usr/bin/env bash\nexec "{REAL_DATE}" -d "@{FAKE_EPOCH}" "$@"\n')
    if GIT:
        _write_exe(bin_ / "git",
                   f'#!/usr/bin/env bash\necho "$*" >> "{git_log}"\nexec "{GIT}" "$@"\n')
    env = {
        "PATH": f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "seed", "GIT_AUTHOR_EMAIL": "seed@example.invalid",
        "GIT_COMMITTER_NAME": "seed", "GIT_COMMITTER_EMAIL": "seed@example.invalid",
        "LC_ALL": "C",
    }
    return {"tmp": tmp_path, "env": env, "bin": bin_, "git_log": git_log}


def _git(sh, cwd, *args) -> str:
    p = subprocess.run([GIT, *args], cwd=cwd, env=sh["env"], capture_output=True, text=True)
    assert p.returncode == 0, f"git {' '.join(args)}: {p.stderr}"
    return p.stdout.strip()


def _commit_files(sh, repo: pathlib.Path, files: dict, msg: str) -> None:
    for rel, text in files.items():
        f = repo / rel
        if text is None:
            if f.exists():
                f.unlink()
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    _git(sh, repo, "add", "-A")
    _git(sh, repo, "commit", "-q", "--allow-empty", "-m", msg)


def _origin(sh, branches: dict) -> tuple[str, pathlib.Path]:
    """A bare origin with the given {branch: {path: text}} (each branch built
    on top of main's files). Returns (url, seed repo). A file:// URL, not a
    plain path, so a `--depth=1` fetch takes the same transport it does on a
    runner."""
    tmp = sh["tmp"]
    bare = tmp / "origin.git"
    _git(sh, tmp, "init", "-q", "--bare", "-b", "main", str(bare))
    url = bare.resolve().as_uri()
    if not branches:
        return url, bare
    seed = tmp / "seed"
    _git(sh, tmp, "init", "-q", "-b", "main", str(seed))
    _commit_files(sh, seed, branches.get("main", {}), "seed main")
    _git(sh, seed, "push", "-q", url, "main")
    for name, files in branches.items():
        if name == "main":
            continue
        _git(sh, seed, "checkout", "-q", "-b", name, "main")
        _commit_files(sh, seed, files, f"seed {name}")
        _git(sh, seed, "push", "-q", url, name)
        _git(sh, seed, "checkout", "-q", "main")
    return url, seed


def _checkout(sh, url: str, branch: str) -> pathlib.Path:
    """Roughly what actions/checkout@v4 leaves: a clone on the run's branch
    with `origin` configured and remote-tracking refs present."""
    work = sh["tmp"] / "work"
    _git(sh, sh["tmp"], "clone", "-q", "--branch", branch, url, str(work))
    return work


def _run_block(sh, body: str, cwd: pathlib.Path, extra_env: dict) -> tuple[int, dict, str]:
    """Run a step body the way Actions does (`bash -e {0}`) and return
    (exit code, $GITHUB_OUTPUT as a dict, stdout+stderr)."""
    assert "${{" not in body, "render expressions before executing a block"
    out = sh["tmp"] / "gh_output"
    out.write_text("", encoding="utf-8")
    summary = sh["tmp"] / "step_summary"
    summary.write_text("", encoding="utf-8")
    script = sh["tmp"] / "step.sh"
    script.write_text(body, encoding="utf-8")
    env = dict(sh["env"], GITHUB_OUTPUT=str(out), GITHUB_STEP_SUMMARY=str(summary),
               **extra_env)
    p = subprocess.run([BASH, "-e", str(script)], cwd=cwd, env=env,
                       capture_output=True, text=True, timeout=120)
    outputs = {}
    for line in out.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            outputs[k] = v
    return p.returncode, outputs, p.stdout + p.stderr


# ---------------------------------------------------------------------------
# executing the backstop gate
# ---------------------------------------------------------------------------

def _backstop_cron() -> str:
    """The backstop cron, as PINNED here. Deliberately not re-read out of the
    gate at collection time: a rewritten gate must fail the test that checks
    it, not turn the whole module into a collection error."""
    return BACKSTOP_CRON


def test_the_gate_compares_against_a_cron_that_really_exists():
    """The gate recognises the backstop by its cron STRING. If the schedule
    were edited without the gate, the backstop would silently become an
    always-run (a pointless commit and deploy every night) -- or, edited the
    other way, the primary would be skipped. So the literal must be one of
    the schedule's crons, must not be the primary, and the env must carry
    the real `github.event.schedule`."""
    backstop = _backstop_cron()
    crons = [c["cron"] for c in ON["schedule"]]
    assert crons.count(backstop) == 1, (backstop, crons)
    assert backstop != PRIMARY_CRON
    m = re.search(r'"\$\{SCHEDULE:-\}" != "([^"]+)"', GATE["run"])
    assert m and m.group(1) == backstop, (
        "the gate no longer recognises the backstop cron by the string the "
        "schedule fires with - " + (m.group(1) if m else "comparison not found"))
    assert GATE.get("env") == {"SCHEDULE": "${{ github.event.schedule }}"}, GATE.get("env")
    assert "${{" not in GATE["run"], "the gate reads env, so it can be executed verbatim"


def _gate_env(event: str, schedule: str = "", ref: str = "main") -> dict:
    return {"GITHUB_EVENT_NAME": event, "SCHEDULE": schedule, "GITHUB_REF_NAME": ref}


def _crypto(stamp: str) -> str:
    return json.dumps({"lens": "ignition", "generated_at": stamp, "results": []})


def _gate_repo(sh, crypto_text):
    files = {"README": "x\n"}
    if crypto_text is not None:
        files[CANON[0]] = crypto_text
    url, _ = _origin(sh, {"main": files})
    work = sh["tmp"] / "work"
    # actions/checkout@v4 = init + remote add + a fetch of the run's SHA; the
    # gate's own fetch is what must bring in origin/main.
    _git(sh, sh["tmp"], "init", "-q", str(work))
    _git(sh, work, "remote", "add", "origin", url)
    return url, work


@needs_shell
@needs_gnu_date
def test_the_frozen_clock_shim_is_load_bearing(sh):
    p = subprocess.run(["date", "-u", "+%Y-%m-%d"], env=sh["env"], capture_output=True, text=True)
    assert p.stdout.strip() == FAKE_TODAY


@needs_shell
@needs_gnu_date
def test_backstop_with_todays_file_already_published_stops_here(sh):
    _, work = _gate_repo(sh, _crypto(STAMP_TODAY))
    rc, out, log = _run_block(sh, GATE["run"], work, _gate_env("schedule", _backstop_cron()))
    assert rc == 0, log
    assert out == {"run": "false"}, (out, log)
    assert "already published" in log


@needs_shell
@needs_gnu_date
@pytest.mark.parametrize("crypto_text,why", [
    (_crypto(STAMP_YESTERDAY), "yesterday's file: the 00:14 run never landed"),
    (None, "no file at all yet"),
    ("{not json", "a corrupt file must never SILENCE the backstop"),
    (json.dumps({"lens": "ignition"}), "no generated_at"),
    (_crypto(""), "empty generated_at"),
])
def test_backstop_without_todays_file_runs(sh, crypto_text, why):
    _, work = _gate_repo(sh, crypto_text)
    rc, out, log = _run_block(sh, GATE["run"], work, _gate_env("schedule", _backstop_cron()))
    assert rc == 0, (why, log)
    assert out == {"run": "true"}, (why, out, log)


@needs_shell
@needs_gnu_date
def test_backstop_with_an_unreachable_or_empty_origin_fails_OPEN(sh):
    """The fetch is `|| true` on purpose: a backstop that could not look must
    run, not skip -- skipping is how a dropped 00:14 becomes a missing day."""
    url, _ = _origin(sh, {})                      # bare repo, no branches at all
    work = sh["tmp"] / "work"
    _git(sh, sh["tmp"], "init", "-q", str(work))
    _git(sh, work, "remote", "add", "origin", url)
    rc, out, log = _run_block(sh, GATE["run"], work, _gate_env("schedule", _backstop_cron()))
    assert rc == 0, log
    assert out == {"run": "true"}, (out, log)


@needs_shell
@needs_gnu_date
def test_the_gate_reads_the_branch_as_it_is_NOW_not_the_checkout(sh):
    """A run that sat pending was created at an older SHA. Its checkout holds
    yesterday's file; origin already holds today's (the 00:14 run landed
    meanwhile). The gate must believe origin -- and must not be fooled the
    other way by a stale working-tree file either."""
    url, seed = _origin(sh, {"main": {CANON[0]: _crypto(STAMP_YESTERDAY)}})
    work = _checkout(sh, url, "main")
    _commit_files(sh, seed, {CANON[0]: _crypto(STAMP_TODAY)}, "the 00:14 run landed")
    _git(sh, seed, "push", "-q", url, "main")
    assert json.loads((work / CANON[0]).read_text())["generated_at"] == STAMP_YESTERDAY
    rc, out, log = _run_block(sh, GATE["run"], work, _gate_env("schedule", _backstop_cron()))
    assert (rc, out) == (0, {"run": "false"}), log

    # and the converse: a working-tree file claiming today, origin yesterday
    _commit_files(sh, seed, {CANON[0]: _crypto(STAMP_YESTERDAY)}, "rewind")
    _git(sh, seed, "push", "-q", "--force", url, "main")
    (work / CANON[0]).write_text(_crypto(STAMP_TODAY), encoding="utf-8")
    rc, out, log = _run_block(sh, GATE["run"], work, _gate_env("schedule", _backstop_cron()))
    assert (rc, out) == (0, {"run": "true"}), log


def _non_backstop_triggers():
    cases = [("schedule", c["cron"]) for c in ON["schedule"] if c["cron"] != BACKSTOP_CRON]
    cases += [("push", ""), ("workflow_dispatch", "")]
    return cases


@needs_shell
@needs_gnu_date
@pytest.mark.parametrize("event,schedule", _non_backstop_triggers())
def test_every_trigger_but_the_backstop_is_due_without_touching_git(sh, event, schedule):
    """COMPUTED from the schedule, so a new cron is covered automatically.
    Origin holds TODAY's file, so a gate that consulted it for these triggers
    would answer false; the git stub proves it never even looked. The
    primary 00:14 run and every intraday refresh must always run -- they are
    what the backstop backs up -- and so must a kick and a manual dispatch."""
    _, work = _gate_repo(sh, _crypto(STAMP_TODAY))
    sh["git_log"].write_text("", encoding="utf-8")
    rc, out, log = _run_block(sh, GATE["run"], work, _gate_env(event, schedule))
    assert (rc, out) == (0, {"run": "true"}), log
    assert sh["git_log"].read_text(encoding="utf-8") == "", "a non-backstop trigger ran git"


# ---------------------------------------------------------------------------
# executing the screen and backtest steps
# ---------------------------------------------------------------------------

def _render(body: str, *, dry_run: bool) -> str:
    return body.replace("${{ inputs.dry_run }}", "true" if dry_run else "")


def _stub_python(sh) -> pathlib.Path:
    args = sh["tmp"] / "python-args.log"
    _write_exe(sh["bin"] / "python",
               '#!/usr/bin/env bash\n'
               f'echo "$*" >> "{args}"\n'
               'echo "ignition: stub output"\n'
               'exit "${STUB_RC:-0}"\n')
    return args


@needs_shell
@pytest.mark.parametrize("step", [SCAN, BT], ids=["screen", "backtest"])
@pytest.mark.parametrize("rc,published,step_rc", [
    (0, "true", 0),
    (3, "false", 0),
    (1, None, 1),
    (2, None, 2),
])
def test_the_exit_code_decides_the_outcome(sh, step, rc, published, step_rc):
    """run.py's contract, turned into outputs: 0 -> published=true; 3 ->
    published=false with a ::warning:: and a GREEN step (the previous file
    stands, and that is a reported decision); anything else -> the step
    goes red with that code and says nothing about publishing. For the
    backtest this is only true because of `set -o pipefail`: without it the
    `| tee` would hand the case statement tee's 0 and a crash would publish.
    """
    _stub_python(sh)
    body = _render(step["run"], dry_run=False)
    code, out, log = _run_block(sh, body, sh["tmp"], {"STUB_RC": str(rc)})
    assert code == step_rc, log
    assert out.get("published") == published, (out, log)
    if rc == 3:
        assert "::warning::" in log
    if rc not in (0, 3):
        assert "::error::" in log


@needs_shell
@pytest.mark.parametrize("dry_run", [False, True])
def test_the_screen_and_backtest_run_the_cli_they_claim_to(sh, dry_run):
    args_log = _stub_python(sh)
    for step in (SCAN, BT):
        rc, _, log = _run_block(sh, _render(step["run"], dry_run=dry_run), sh["tmp"], {})
        assert rc == 0, log
    screen, replay = args_log.read_text(encoding="utf-8").splitlines()
    assert screen.split()[:4] == ["-m", "scanner.ignition.run", "--market", "crypto"]
    assert "--backtest" not in screen.split()
    assert replay.split()[:4] == ["-m", "scanner.ignition.run", "--market", "crypto"]
    assert "--backtest" in replay.split()
    for line in (screen, replay):
        assert ("--dry-run" in line.split()) is dry_run, line
    assert "stub output" in (sh["tmp"] / "step_summary").read_text(encoding="utf-8"), (
        "the replay's summary lines should reach the run page")


def test_both_runner_steps_carry_all_three_case_arms():
    """The textual half of the exit-code contract, so a reader of the YAML
    sees what the execution test above proves."""
    for step in (SCAN, BT):
        body = step["run"]
        assert "RC=0" in body and "|| RC=$?" in body, (
            "the status must be captured WITHOUT appending to the output")
        for arm in (r"\n\s*0\)", r"\n\s*3\)", r"\n\s*\*\)"):
            assert re.search(arm, body), (step.get("id"), arm)
    assert "pipefail" in BT["run"]


# ---------------------------------------------------------------------------
# the commit step -- static
# ---------------------------------------------------------------------------

def test_the_commit_step_stages_one_path_per_git_add():
    """`git add a b` is ALL-OR-NOTHING (exit 128, stages neither, when one is
    missing) and the repo bans the shape. `git add -A` names no pathspec and
    cannot fail that way, so it is allowed."""
    for line in _code(COMMIT["run"]):
        m = re.match(r"^git add\b(.*)$", line)
        if not m:
            continue
        specs = [t for t in shlex.split(m.group(1).split("#")[0])
                 if t != "--" and not t.startswith("-")]
        assert len(specs) <= 1, line


def test_the_commit_step_stages_only_the_lens_paths():
    """The write-set fence at the workflow layer. tests/test_ignition_fences.py
    only reads run.py; a path added HERE would bypass it."""
    body = COMMIT["run"]
    added = re.findall(r'PATHS="\$PATHS ([^"]+)"', body)
    assert sorted(added) == sorted(CANON), added
    assert 'PATHS=""' in body
    for forbidden in ("journal/", "public/data/phasemap", "public/data/momentum",
                      "_vivek.json", "_spec.json", "bot_rules.json",
                      "alert_history.json", "funnel_history.json", "backups/",
                      "sector_map.json"):
        assert forbidden not in "\n".join(_code(SRC)), f"ignition.yml names {forbidden}"


def test_the_must_change_gate_runs_ONCE_PER_REPORTED_PATH():
    """assert_staged.sh is ANY-OF. One call naming both files would pass on
    the screen alone while a backtest the kick REPORTED publishing was lost
    (audit, 2026-09-28) -- so the gate is called once per path, inside the
    loop over PATHS, and PATHS only ever holds the two canonical files."""
    code = _code(COMMIT["run"])
    calls = [ln for ln in code if "scripts/assert_staged.sh" in ln]
    assert len(calls) == 1, calls
    argv = shlex.split(calls[0])
    assert argv[:2] == ["bash", "scripts/assert_staged.sh"], argv
    assert argv[2].startswith("ignition"), argv
    assert argv[3:] == ["$p"], argv
    at = code.index(calls[0])
    loop = [i for i, ln in enumerate(code[:at]) if ln.startswith("for p in $PATHS")]
    assert loop, "the gate is not inside a loop over PATHS"
    assert not any(ln.startswith("done") for ln in code[loop[-1] + 1:at]), \
        "the gate sits after the loop closed, not inside it"
    assigned = [ln for ln in code if "PATHS=" in ln and "PATHS=\"\"" not in ln]
    named = {tok for ln in assigned for tok in re.findall(r"public/data/ignition/[a-z_]+\.json", ln)}
    assert named == set(CANON), named
    assert any(ln.startswith("git add") for ln in code[:at]), "gate before staging"
    assert not any(ln.startswith("git commit") for ln in code[:at]), "gate after commit"


@needs_shell
def test_a_reported_backtest_that_is_missing_fails_even_though_the_screen_staged(sh):
    """The audit's repro, run for real: both steps reported published=true,
    the screen file changed, the backtest file is GONE. The old single ANY-OF
    call went green here and pushed a commit without the backtest."""
    url, _, work = _commit_world(sh, "main")
    before = _tip(sh, url, "main")
    (work / CANON[0]).write_text(_crypto("2031-03-04T00:14:31+00:00"), encoding="utf-8")
    (work / CANON[1]).unlink()
    rc, _, log = _run_block(sh, COMMIT["run"], work,
                            _publish({"SCAN_PUBLISHED": "true", "BT_PUBLISHED": "true"}, "main"))
    assert rc != 0, log
    assert "reported published but is not present" in log
    assert _tip(sh, url, "main") == before


@needs_shell
def test_a_reported_backtest_that_staged_nothing_fails_even_though_the_screen_staged(sh):
    url, _, work = _commit_world(sh, "main")
    before = _tip(sh, url, "main")
    (work / CANON[0]).write_text(_crypto("2031-03-04T00:14:31+00:00"), encoding="utf-8")
    rc, _, log = _run_block(sh, COMMIT["run"], work,
                            _publish({"SCAN_PUBLISHED": "true", "BT_PUBLISHED": "true"}, "main"))
    assert rc != 0, log
    assert "ASSERT-STAGED FAILED" in log
    assert _tip(sh, url, "main") == before


def test_the_push_target_is_the_runs_own_branch_and_never_main():
    """A kick on a feature branch must never write main. The branch is
    `GITHUB_REF_NAME` -- main for the crons, the pushed branch for a kick --
    and the literal `HEAD:main` appears nowhere in the file (not even in a
    comment: this is the one string whose presence is the bug)."""
    assert "HEAD:main" not in SRC
    body = COMMIT["run"]
    code = _code(body)
    assert 'BRANCH="${GITHUB_REF_NAME}"' in code
    assert 'git push origin "HEAD:$BRANCH"' in "\n".join(code)
    assert 'git fetch origin "$BRANCH"' in "\n".join(code)
    assert 'git reset --hard "origin/$BRANCH"' in "\n".join(code)
    for ln in _code(SRC):
        assert not re.search(r"origin[/ ]+main\b|refs/heads/main", ln), ln
    assert COMMIT.get("env") == {
        "SCAN_PUBLISHED": "${{ steps.scan.outputs.published }}",
        "BT_PUBLISHED": "${{ steps.bt.outputs.published }}"}, COMMIT.get("env")
    assert "${{" not in body, "the commit reads env, so it can be executed verbatim"


# ---------------------------------------------------------------------------
# the commit step -- executed
# ---------------------------------------------------------------------------

ASSERT_STAGED = (ROOT / "scripts" / "assert_staged.sh").read_text(encoding="utf-8")


def _commit_world(sh, branch: str):
    """origin: main + (optionally) a feature branch, both carrying v0 of the
    two lens files, the real assert_staged.sh and an unrelated file."""
    base = {CANON[0]: _crypto("2031-03-01T00:14:00+00:00"),
            CANON[1]: '{"generated_at": "2031-02-01T00:00:00+00:00"}',
            "scripts/assert_staged.sh": ASSERT_STAGED,
            "other.txt": "v0\n"}
    branches = {"main": base}
    if branch != "main":
        branches[branch] = {"kick.txt": "kicked\n"}
    url, seed = _origin(sh, branches)
    work = _checkout(sh, url, branch)
    return url, seed, work


def _tip(sh, url: str, branch: str) -> str:
    out = _git(sh, sh["tmp"], "ls-remote", url, f"refs/heads/{branch}")
    return out.split()[0] if out else ""


def _show(sh, url: str, branch: str, path: str) -> str:
    probe = sh["tmp"] / "probe"
    if probe.exists():
        shutil.rmtree(probe)
    _git(sh, sh["tmp"], "clone", "-q", "--branch", branch, url, str(probe))
    return (probe / path).read_text(encoding="utf-8")


def _changed_in_tip(sh, url: str, branch: str) -> set:
    probe = sh["tmp"] / "probe2"
    if probe.exists():
        shutil.rmtree(probe)
    _git(sh, sh["tmp"], "clone", "-q", "--branch", branch, url, str(probe))
    return set(_git(sh, probe, "diff", "--name-only", "HEAD~1", "HEAD").splitlines())


def _publish(env_extra: dict, branch: str) -> dict:
    return dict({"GITHUB_REF_NAME": branch, "SCAN_PUBLISHED": "", "BT_PUBLISHED": ""},
                **env_extra)


@needs_shell
def test_a_kick_on_a_feature_branch_writes_that_branch_and_leaves_main_untouched(sh):
    branch = "claude/ignition-eval"
    url, _, work = _commit_world(sh, branch)
    main_before = _tip(sh, url, "main")
    new_screen = _crypto("2031-03-04T09:00:00+00:00")
    new_bt = '{"generated_at": "2031-03-04T09:05:00+00:00", "n": 7}'
    (work / CANON[0]).write_text(new_screen, encoding="utf-8")
    (work / CANON[1]).write_text(new_bt, encoding="utf-8")
    rc, _, log = _run_block(sh, COMMIT["run"], work,
                            _publish({"SCAN_PUBLISHED": "true", "BT_PUBLISHED": "true"}, branch))
    assert rc == 0, log
    assert _tip(sh, url, "main") == main_before, "a feature-branch kick moved main"
    assert _show(sh, url, branch, CANON[0]) == new_screen
    assert _show(sh, url, branch, CANON[1]) == new_bt
    assert _changed_in_tip(sh, url, branch) == set(CANON)


@needs_shell
def test_only_the_files_the_run_reported_publishing_are_committed(sh):
    """The screen published, the backtest did not run. A backtest file lying
    modified in the working tree (a dry run, a leftover) must NOT ride along:
    the commit carries exactly the reported publish."""
    url, _, work = _commit_world(sh, "main")
    bt_before = _show(sh, url, "main", CANON[1])
    (work / CANON[0]).write_text(_crypto("2031-03-04T00:14:31+00:00"), encoding="utf-8")
    (work / CANON[1]).write_text('{"stray": true}', encoding="utf-8")
    rc, _, log = _run_block(sh, COMMIT["run"], work, _publish({"SCAN_PUBLISHED": "true"}, "main"))
    assert rc == 0, log
    assert _changed_in_tip(sh, url, "main") == {CANON[0]}
    assert _show(sh, url, "main", CANON[1]) == bt_before


@needs_shell
def test_a_siblings_newer_commit_survives_the_rebase_and_retry(sh):
    """Between this run's checkout and its push, someone else pushed: an
    unrelated file AND a newer backtest. The retry resets onto origin and
    replaces ONLY the paths this run generated, so both of the sibling's
    changes survive and ours lands on top -- nothing is reverted."""
    url, seed, work = _commit_world(sh, "main")
    _commit_files(sh, seed, {"other.txt": "sibling\n", CANON[1]: '{"sibling": 1}'},
                  "a sibling landed")
    _git(sh, seed, "push", "-q", url, "main")
    ours = _crypto("2031-03-04T00:14:31+00:00")
    (work / CANON[0]).write_text(ours, encoding="utf-8")
    rc, _, log = _run_block(sh, COMMIT["run"], work, _publish({"SCAN_PUBLISHED": "true"}, "main"))
    assert rc == 0, log
    assert _show(sh, url, "main", CANON[0]) == ours
    assert _show(sh, url, "main", "other.txt") == "sibling\n"
    assert _show(sh, url, "main", CANON[1]) == '{"sibling": 1}'


@needs_shell
def test_a_publish_that_staged_nothing_is_RED(sh):
    """The 2026-07-20 incident shape: the scanner said it published, the
    index is empty. Every real publish re-stamps generated_at, so this can
    only mean output was lost -- and the run must fail, not say "No data
    changes to commit." and go green. Origin is left untouched."""
    url, _, work = _commit_world(sh, "main")
    before = _tip(sh, url, "main")
    rc, _, log = _run_block(sh, COMMIT["run"], work,
                            _publish({"SCAN_PUBLISHED": "true", "BT_PUBLISHED": "true"}, "main"))
    assert rc != 0, log
    assert "ASSERT-STAGED FAILED" in log
    assert _tip(sh, url, "main") == before


# ---------------------------------------------------------------------------
# the omissions, pinned as DECISIONS
# ---------------------------------------------------------------------------

def test_there_is_DELIBERATELY_no_watchdog_entry():
    """CLAUDE.md asks for a `WATCHDOG_RUNS` entry when a workflow commits
    data, and this one deliberately has none -- the same decision, for the
    same reasons, as momentum.yml.

    First, the watchdog alarms when a workflow has not RUN recently, and for
    a report-only lens a quiet day costs a stale page and nothing else: there
    is no book to mis-price and no alert to miss, and the page already shows
    `generated_at`. Second, since the 2026-08-27 Discord removal no alert
    channel is configured (CLAUDE.md, ALERT DELIVERY), so an entry would buy
    a "NOBODY WAS TOLD" log line at the price of one more file
    (`scanner/config.py`) to edit when the lens is removed. Third, the backstop crons already heal the
    common failure (a dropped 00:14) inside the same morning.

    IT IS THE OWNER'S CALL, not a permanent ruling. This test exists so the
    absence reads as a decision rather than an oversight. If the owner wants
    the alarm, add `"ignition.yml": {"max_age_h": 26.0, "severity":
    "WARNING"}` beside phasemap's and DELETE THIS TEST in the same commit.
    """
    assert "ignition.yml" not in config.WATCHDOG_RUNS
    cfg = (ROOT / "scanner" / "config.py").read_text(encoding="utf-8")
    assert '"ignition.yml"' not in cfg
    wd = (ROOT / "scanner" / "watchdog.py").read_text(encoding="utf-8")
    assert "ignition" not in wd.lower()


def test_no_other_workflow_learned_about_the_lens():
    """Removability, checked at the workflow layer: exactly one workflow may
    name the lens's module, data, workflow file, kick file, cache namespace
    or config prefix, and it is this one. (A `node test/ignition.test.js`
    step in test.yml names none of those and stays allowed -- the JS suite
    has to be registered there or it never runs.)"""
    pattern = re.compile(r"scanner[./]ignition|data/ignition|ignition\.yml|"
                         r"ignition-kick|ignition-frames|IGNITION_")
    others = [p.name for p in sorted(WFDIR.glob("*.yml"))
              if p.name != WF.name and pattern.search(p.read_text(encoding="utf-8"))]
    assert others == [], others


def test_the_kick_file_is_not_a_scan_kick():
    """dispatch_scan.yml turns a push of `.github/scan-kick` into a full scan
    dispatch. The two kick files must stay distinct, or evaluating the lens
    would also fire a paper-book scan (and vice versa)."""
    assert KICK != ".github/scan-kick"
    ds = yaml.safe_load((WFDIR / "dispatch_scan.yml").read_text(encoding="utf-8"))
    ds_on = ds.get("on") or ds[True]
    assert KICK not in str(ds_on)
