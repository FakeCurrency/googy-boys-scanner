"""Daily Evidence Brief (owner-ruled fast-track, 2026-08-01) — the pins.

The brief is a READ-ONLY reporter over committed artifacts. These tests keep
the three properties that make it safe to run anywhere, any time: it writes
nothing, it imports nothing from the scanner or the bot, and it stays inside
its 15-line budget against the real checkout.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = (ROOT / "scripts" / "evidence_brief.py").read_text(encoding="utf-8")


def _run():
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "evidence_brief.py")],
                          capture_output=True, text=True, cwd=ROOT, timeout=120)


def test_it_runs_against_the_real_checkout_and_stays_in_budget():
    p = _run()
    out = p.stdout.strip().splitlines()
    assert out and out[0].startswith("# Evidence brief"), p.stderr[:300]
    assert len(out) <= 15, f"brief overflowed: {len(out)} lines"
    # every ruled section is present, every run
    text = p.stdout
    for token in ("funnel asx", "funnel nasdaq", "funnel crypto",
                  "arriving:", "graduation:", "book:", "human eyes today:"):
        assert token in text, f"brief lost its '{token}' section"


def test_the_exit_code_is_the_issue_flag_not_a_crash_signal():
    # rc 0 = quiet, rc 1 = something named in 'human eyes'. Either is a
    # VALID run; a traceback is neither.
    p = _run()
    assert p.returncode in (0, 1), p.stderr[:400]
    assert "Traceback" not in p.stderr


def test_it_writes_nothing_source_level():
    # No write-mode opens, no json.dump, no Path.write_*, no os.remove/replace.
    assert not re.search(r"open\([^)]*,\s*['\"][wax]", SRC), "write-mode open found"
    for banned in ("json.dump(", ".write_text(", ".write_bytes(",
                   "os.remove", "os.replace", "os.rename", "shutil"):
        assert banned not in SRC, f"{banned} in a read-only reporter"


def test_it_writes_nothing_behaviourally():
    before = subprocess.run(["git", "status", "--porcelain"],
                            capture_output=True, text=True, cwd=ROOT).stdout
    _run()
    after = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True, cwd=ROOT).stdout
    assert before == after, "running the brief changed the working tree"


def test_it_never_touches_scanner_or_broker_code():
    # Report-only means no engine imports at all — not even read-only ones.
    # The brief reads ARTIFACTS, so a scanner import here is scope creep.
    assert not re.search(r"^\s*(from|import)\s+scanner", SRC, re.M), \
        "the brief must read artifacts, never engine modules"
    assert not re.search(r"^\s*(from|import)\s+\S*broker", SRC, re.M), \
        "the brief must never import broker code (prose may name it)"


def test_the_line_budget_is_enforced_in_the_script_itself():
    # The budget is a contract, not a habit — the script must hard-fail on
    # overflow rather than quietly growing past the owner's 15 lines.
    assert re.search(r"assert len\(lines\) <= 15", SRC)
