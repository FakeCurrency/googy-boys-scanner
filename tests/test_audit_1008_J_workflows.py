"""Audit 2026-10-08, cluster J: workflow-layer fixes pinned by EXECUTION.

#13  momentum.yml expanded the free-text `window` input as TEXT inside run:,
     so a double quote in it ran arbitrary shell beside a contents:write
     token. Every ${{ inputs.* }} in every workflow now reaches the shell via
     env:, and momentum validates each value. The harness below renders a step
     the way Actions does - expressions substituted into BOTH the env values
     and the run text - so the same test reproduces the injection against the
     old step and proves the new one refuses it.
#71  crypto_bot.yml never staged public/data/crypto_arriving.json, so each of
     its commits paired a fresh crypto funnel count with a stale arriving list.

(#5 lives beside the gate it changes, in test_workflow_hardening.py; #6 beside
the redispatch pins, in test_workflow_mutex.py.)
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="needs bash")

EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")

# Expressions a run: block may still interpolate as text: their values come
# from GitHub itself (the event's name, the cron line written in the workflow
# file), never from whoever dispatched or pushed. Everything else goes via env.
SAFE_IN_RUN = {"github.event_name", "github.event.schedule"}


def _load(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def _steps():
    for path in sorted(WF.glob("*.yml")):
        for jname, job in (_load(path.name).get("jobs") or {}).items():
            for i, step in enumerate(job.get("steps") or []):
                yield path.name, jname, step.get("name") or step.get("id") or str(i), step


# ---------------------------------------------------------------------------
# #13 - the repo-wide rule
# ---------------------------------------------------------------------------

def test_no_run_block_interpolates_a_caller_controlled_expression():
    bad = []
    for fname, jname, sname, step in _steps():
        for expr in EXPR.findall(str(step.get("run", ""))):
            if expr not in SAFE_IN_RUN:
                bad.append(f"{fname}:{jname}:{sname}: ${{{{ {expr} }}}}")
    assert not bad, (
        "move these into the step's env: and read them as \"$VAR\" (the "
        "2026-07-20 security pass; audit #13):\n  " + "\n  ".join(bad))


def test_every_dispatch_input_a_run_block_needs_is_in_some_env():
    """The other half: an input that left run: must still ARRIVE. Every
    `inputs.X` / `github.event.inputs.X` a workflow declares and reads lives in
    an env: block (or an `if:` expression, which is evaluated, not shelled)."""
    for path in sorted(WF.glob("*.yml")):
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"\$\{\{\s*(?:github\.event\.)?inputs\.(\w+)\s*\}\}", src):
            line = src[src.rfind("\n", 0, m.start()) + 1:src.find("\n", m.end())]
            stripped = line.strip()
            assert stripped.startswith("#") or re.match(r"[A-Z_][A-Z0-9_]*:\s", stripped), (
                f"{path.name}: {stripped!r} - an input outside an env: mapping")


# ---------------------------------------------------------------------------
# #13 - momentum.yml, executed
# ---------------------------------------------------------------------------

MOM = _load("momentum.yml")["jobs"]["momentum"]["steps"]
DUE = next(s for s in MOM if s.get("id") == "due")
SCREEN = next(s for s in MOM if s.get("id") == "scan")


def _render(text, ctx):
    return EXPR.sub(lambda m: ctx.get(m.group(1), ""), str(text))


def _run_like_actions(tmp_path, step, ctx):
    """Render expressions into env AND run text (what Actions does), run the
    body under `bash -e` with a python stub. Returns (rc, out, python_calls)."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    calls = tmp_path / "python.log"
    py = bindir / "python"
    py.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{calls}"\nexit 0\n', encoding="utf-8")
    py.chmod(0o755)
    out = tmp_path / "gh_output"
    out.write_text("", encoding="utf-8")
    script = tmp_path / "step.sh"
    script.write_text(_render(step["run"], ctx), encoding="utf-8")
    env = {k: _render(v, ctx) for k, v in (step.get("env") or {}).items()}
    full = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}",
                GITHUB_OUTPUT=str(out), GITHUB_STEP_SUMMARY=str(tmp_path / "summary"),
                PWN_MARKER=str(tmp_path / "PWNED"), **env)
    p = subprocess.run([BASH, "-e", str(script)], cwd=tmp_path, env=full,
                       capture_output=True, text=True, timeout=60)
    lines = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return p.returncode, p.stdout + p.stderr, lines


INJECT = '1"; touch "$PWN_MARKER"; echo "'


def _screen_ctx(**over):
    ctx = {"steps.due.outputs.market": "asx", "inputs.mode": "A", "inputs.window": "",
           "inputs.dry_run": "true", "inputs.backtest": "false"}
    ctx.update(over)
    return ctx


@needs_bash
@pytest.mark.parametrize("window", [INJECT, "1; touch $PWN_MARKER", "$(touch $PWN_MARKER)",
                                    "`touch $PWN_MARKER`", "3 --backtest", "-1", "2.5"])
def test_a_hostile_window_input_runs_nothing_and_fails_the_step(tmp_path, window):
    rc, out, calls = _run_like_actions(tmp_path, SCREEN, _screen_ctx(**{"inputs.window": window}))
    assert not (tmp_path / "PWNED").exists(), "the window input executed shell:\n" + out
    assert rc == 2, out
    assert calls == [], f"the screen ran on a refused input: {calls}"
    assert "::error::window input must be a whole number of bars" in out


@needs_bash
@pytest.mark.parametrize("window,expect", [("", None), ("1", "1"), ("12", "12")])
def test_a_legal_window_reaches_the_cli(tmp_path, window, expect):
    rc, out, calls = _run_like_actions(tmp_path, SCREEN, _screen_ctx(**{"inputs.window": window}))
    assert rc == 0, out
    (line,) = calls
    args = line.split()
    assert args[:4] == ["-m", "scanner.momentum.run", "--market", "asx"]
    assert ("--window" in args) is (expect is not None)
    if expect:
        assert args[args.index("--window") + 1] == expect
    assert "--dry-run" in args and "--mode" in args


@needs_bash
@pytest.mark.parametrize("over", [{"inputs.mode": 'A"; touch "$PWN_MARKER"; echo "'},
                                  {"inputs.mode": "D"},
                                  {"steps.due.outputs.market": "asx; touch $PWN_MARKER"}])
def test_the_mode_and_market_are_checked_too(tmp_path, over):
    rc, out, calls = _run_like_actions(tmp_path, SCREEN, _screen_ctx(**over))
    assert not (tmp_path / "PWNED").exists(), out
    assert rc == 2 and calls == [], out


@needs_bash
def test_a_backtest_dispatch_still_names_the_backtest_file(tmp_path):
    rc, out, calls = _run_like_actions(
        tmp_path, SCREEN, _screen_ctx(**{"inputs.backtest": "true", "inputs.dry_run": ""}))
    assert rc == 0, out
    assert "--backtest" in calls[0].split() and "--dry-run" not in calls[0].split()
    outputs = (tmp_path / "gh_output").read_text(encoding="utf-8")
    assert "file=asx_backtest.json" in outputs and "market=asx" in outputs


@needs_bash
@pytest.mark.parametrize("market,rc_want", [("nasdaq", 0), ("", 0),
                                            ('asx" ; touch "$PWN_MARKER', 2), ("turtle", 2)])
def test_the_manual_dispatch_market_is_validated_before_it_becomes_an_output(
        tmp_path, market, rc_want):
    ctx = {"github.event_name": "workflow_dispatch", "inputs.market": market}
    rc, out, _ = _run_like_actions(tmp_path, DUE, ctx)
    assert not (tmp_path / "PWNED").exists(), out
    assert rc == rc_want, out
    outputs = (tmp_path / "gh_output").read_text(encoding="utf-8")
    if rc_want == 0:
        assert outputs == f"market={market or 'asx'}\n"
    else:
        assert outputs == "", "a refused market must not become the step's output"


# ---------------------------------------------------------------------------
# #71 - crypto_bot.yml stages what scanner.run --market crypto writes
# ---------------------------------------------------------------------------

def _crypto_bot_paths():
    body = next(s for s in _load("crypto_bot.yml")["jobs"]["crypto"]["steps"]
                if str(s.get("name", "")).startswith("Commit & push"))["run"]
    m = re.search(r'^\s*PATHS="([^"$]+)"', body, re.M)
    assert m, "crypto_bot.yml's PATHS assignment moved; re-point this test"
    return set(m.group(1).split())


def _scan_yml_per_market_paths(market):
    body = next(s for s in _load("scan.yml")["jobs"]["scan"]["steps"]
                if str(s.get("name", "")).startswith("Commit & push"))["run"]
    m = re.search(r'PATHS="\$PATHS ([^"]+)"', body)
    assert m, "scan.yml's per-market PATHS template moved; re-point this test"
    return {p.replace("${m}", market) for p in m.group(1).split()}


def test_crypto_bot_stages_every_per_market_file_scan_yml_stages_for_crypto():
    """Both workflows run the same `scanner.run --market crypto`; scan.yml's
    per-market template is the list of what one market's run writes. A file
    crypto_bot.yml does not stage is discarded by its push loop's
    `git reset --hard origin/main`, so main keeps whichever older copy a
    scan.yml crypto run last committed beside crypto_bot's fresh scan."""
    missing = _scan_yml_per_market_paths("crypto") - _crypto_bot_paths()
    assert not missing, f"crypto_bot.yml does not stage: {sorted(missing)}"


def test_the_arriving_file_is_what_the_scan_writes():
    assert "public/data/crypto_arriving.json" in _crypto_bot_paths()
    src = (ROOT / "scanner" / "scan.py").read_text(encoding="utf-8")
    assert 'f"{market_key}_arriving.json"' in src, (
        "scan.py renamed the arriving file; both staging lists must follow")


# ---------------------------------------------------------------------------
# #13 hardening (review) - scan.yml's market input never reaches
# $GITHUB_OUTPUT / $GITHUB_ENV unchecked
# ---------------------------------------------------------------------------
# The same threat as #13 by a different door: scan_gate.py echoed a manual
# dispatch's market straight into `markets=` ($GITHUB_OUTPUT), the scan job
# copies that into $GITHUB_ENV, and the gate's fail-open branch did the same
# in shell. A newline in the value would forge an output or an env line (e.g.
# BASH_ENV) for every later step. GitHub's choice list should refuse such a
# value; these pins make the workflow not depend on it.

import importlib.util  # noqa: E402

_gspec = importlib.util.spec_from_file_location("scan_gate_j", ROOT / "scripts" / "scan_gate.py")
SCAN_GATE = importlib.util.module_from_spec(_gspec)
_gspec.loader.exec_module(SCAN_GATE)

FORGE = "asx\nmarkets<<E\nasx\nBASH_ENV=/tmp/pwn\nE"


@pytest.mark.parametrize("market", [FORGE, "turtle", "asx nasdaq", "ASX"])
@pytest.mark.parametrize("reason", ["manual", "heartbeat", ""])
def test_the_scan_gate_never_echoes_an_unknown_market(market, reason, capsys):
    import datetime as dt
    now = dt.datetime(2026, 10, 7, 2, 0, tzinfo=dt.timezone.utc)   # ASX live
    markets, why = SCAN_GATE.decide("workflow_dispatch", "", reason, market, now, {})
    assert markets == [], why
    assert "\n" not in why
    SCAN_GATE.main(["--event", "workflow_dispatch", "--reason", reason, "--market", market,
                    "--now", now.isoformat(), "--data", str(ROOT / "public" / "data")])
    assert capsys.readouterr().out == "run=false\nmarkets=\n"


@pytest.mark.parametrize("market", ["", "all", "asx", "nasdaq", "crypto"])
def test_every_legal_market_is_still_scanned_as_asked(market):
    import datetime as dt
    now = dt.datetime(2026, 10, 10, 1, 0, tzinfo=dt.timezone.utc)  # Saturday
    want = list(SCAN_GATE.ALL) if market in ("", "all") else [market]
    assert SCAN_GATE.decide("workflow_dispatch", "", "manual", market, now, {})[0] == want


def _gate_check_step():
    return next(s for s in _load("scan.yml")["jobs"]["gate"]["steps"] if s.get("id") == "check")


@needs_bash
@pytest.mark.parametrize("market,rc_want,out_want", [
    (FORGE, 2, ""), ("turtle", 2, ""),
    ("asx", 0, "run=true\nmarkets=asx\n"), ("", 0, "run=true\nmarkets=asx nasdaq crypto\n"),
])
def test_a_gate_crash_never_writes_an_unchecked_market_to_the_outputs(
        tmp_path, market, rc_want, out_want):
    """No scripts/scan_gate.py in the cwd = the crash branch (a failed sparse
    checkout), which builds `markets=` itself from the raw input."""
    out = tmp_path / "out"
    out.write_text("", encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin", "GITHUB_OUTPUT": str(out), "EVENT": "workflow_dispatch",
           "SCHED": "", "REASON": "", "MARKET": market}
    p = subprocess.run([BASH, "-e", "-c", _gate_check_step()["run"]], cwd=tmp_path, env=env,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == rc_want, p.stdout + p.stderr
    assert out.read_text(encoding="utf-8") == out_want
