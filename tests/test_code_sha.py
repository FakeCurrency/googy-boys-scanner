"""scan._code_sha -- the "built from <sha>" stamp names the code that RAN.

The scan.yml / crypto_bot.yml writer jobs check out ``ref: github.ref`` (the
branch tip when the job STARTS), while GITHUB_SHA is the commit the run was
TRIGGERED on. A run that queued behind the ``scan`` mutex while main moved
therefore executes newer code than GITHUB_SHA names, so the checked-out HEAD is
asked first and GITHUB_SHA is only the fallback (2026-09-28, review FE-3).

Display-only: app.js's freshness-box tooltip is the sole reader. What these
tests pin is the ORDER, the fallbacks, the 7-char shape, and that a hung or
missing git can never stall or crash a scan.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

from scanner import scan

REPO_ROOT = pathlib.Path(scan.__file__).resolve().parents[1]
HEAD_SHA = "abcdef0123456789abcdef0123456789abcdef01"
TRIGGER_SHA = "0123456fedcba9876543210fedcba9876543210f"


def _fake_git(stdout="", returncode=0, raises=None, calls=None):
    def run(args, **kw):
        if calls is not None:
            calls.append((list(args), kw))
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")
    return run


def test_the_checked_out_head_beats_the_trigger_sha(monkeypatch):
    """The whole point of the fix: with BOTH available, HEAD wins."""
    monkeypatch.setenv("GITHUB_SHA", TRIGGER_SHA)
    monkeypatch.setattr(scan.subprocess, "run", _fake_git(HEAD_SHA + "\n"))
    assert scan._code_sha() == HEAD_SHA[:7]


def test_the_stamp_is_exactly_seven_chars_from_either_source(monkeypatch):
    """Same shape the stamp has always had (GITHUB_SHA[:7]). A 64-hex SHA-256
    object name, or a longer --short answer, must not widen it."""
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setattr(scan.subprocess, "run", _fake_git("f" * 64 + "\n"))
    assert scan._code_sha() == "f" * 7
    monkeypatch.setenv("GITHUB_SHA", TRIGGER_SHA)
    monkeypatch.setattr(scan.subprocess, "run", _fake_git(returncode=128))
    assert scan._code_sha() == TRIGGER_SHA[:7]


def test_git_is_asked_in_the_repo_root_with_a_short_timeout(monkeypatch):
    """A hung git must not stall a scan: the call carries a timeout, and it runs
    in the repo root rather than whatever cwd the runner happens to have."""
    calls = []
    monkeypatch.setattr(scan.subprocess, "run", _fake_git(HEAD_SHA, calls=calls))
    scan._code_sha()
    assert len(calls) == 1
    args, kw = calls[0]
    assert args[:2] == ["git", "rev-parse"] and args[-1] == "HEAD"
    assert 0 < kw.get("timeout", 0) <= 5
    assert pathlib.Path(kw.get("cwd")).resolve() == REPO_ROOT
    assert kw.get("capture_output") is True


@pytest.mark.parametrize("fake", [
    _fake_git(raises=subprocess.TimeoutExpired(["git"], 3)),   # hung git
    _fake_git(raises=FileNotFoundError("git")),                # no git on PATH
    _fake_git(raises=OSError("boom")),
    _fake_git(HEAD_SHA, returncode=128),                       # not a checkout
    _fake_git(""),                                             # rc 0, nothing said
    _fake_git("HEAD\n"),                                       # rc 0, not a sha
    _fake_git("fatal: dubious ownership\n"),
], ids=["timeout", "no-git", "oserror", "nonzero", "empty", "not-a-sha", "junk"])
def test_any_git_failure_falls_back_to_github_sha(monkeypatch, fake):
    monkeypatch.setenv("GITHUB_SHA", TRIGGER_SHA)
    monkeypatch.setattr(scan.subprocess, "run", fake)
    assert scan._code_sha() == TRIGGER_SHA[:7]


@pytest.mark.parametrize("env", [None, ""], ids=["unset", "empty"])
def test_empty_when_neither_source_answers(monkeypatch, env):
    if env is None:
        monkeypatch.delenv("GITHUB_SHA", raising=False)
    else:
        monkeypatch.setenv("GITHUB_SHA", env)
    monkeypatch.setattr(scan.subprocess, "run",
                        _fake_git(raises=FileNotFoundError("git")))
    assert scan._code_sha() == ""


def test_in_this_checkout_the_stamp_is_the_real_head(monkeypatch):
    """End to end against the real git (the scan runs inside the repo checkout
    on Actions too): a stale trigger SHA in the environment is ignored."""
    if shutil.which("git") is None:
        pytest.skip("git not on PATH")
    real = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                          text=True, timeout=10, cwd=REPO_ROOT)
    if real.returncode != 0 or not real.stdout.strip():
        pytest.skip("not a git checkout")
    monkeypatch.setenv("GITHUB_SHA", "0" * 40)
    assert scan._code_sha() == real.stdout.strip()[:7]
