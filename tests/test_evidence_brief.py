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

import pytest

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
                  "arriving:", "graduation:", "book:", "cycle w3-1:",
                  "human eyes today:"):
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


def test_the_cycle_clock_carries_the_frozen_protocol_numbers():
    # The w3-1 read is pre-registered (owner-signed 2026-08-02): 30 closes,
    # judged against the w3 cohort's own sim band. The reporter carries those
    # numbers as FROZEN constants — it may not import scanner.config, and
    # changing any of them mid-cycle is the retuning the protocol forbids,
    # so this pin makes a quiet edit fail a push instead.
    assert 'CYCLE = "w3-1"' in SRC
    assert "CYCLE_TARGET = 30" in SRC
    assert "+0.056" in SRC and "+0.10" in SRC, "the sim band is part of the protocol"
    # ... and so are the n=30 verdict lines (pass >= 0, kill <= -0.05).
    assert "CYCLE_PASS_RT = 0.0" in SRC and "CYCLE_KILL_RT = -0.05" in SRC
    # Counted on the entry-time stamp, never inferred from dates — the one
    # rule that keeps pre-gate history out of the cycle read.
    assert 't.get("cycle") == CYCLE' in SRC


def test_the_book_line_reads_the_published_cap_not_a_literal():
    # The book line said "/30 open" as a typed literal and would have kept
    # saying it after the owner's 2026-09-27 resize to 60 slots. The brief may
    # not import scanner.config, so it reads the cap the scan PUBLISHES from
    # config (public/data/bot_rules.json max_open_total).
    import json
    assert not re.search(r"\}/\d+ open", SRC), "a hard-coded book cap is back"
    assert '"bot_rules.json"' in SRC and '"max_open_total"' in SRC
    cap = json.loads((ROOT / "public" / "data" / "bot_rules.json")
                     .read_text(encoding="utf-8"))["max_open_total"]
    book = next(ln for ln in _run().stdout.splitlines() if ln.startswith("book:"))
    assert f"/{cap} open" in book, book


# ── REFINE200 (2026-10-14): the verdict, the live cycle, the engine's stalls ──

def _mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location("evidence_brief", ROOT / "scripts" / "evidence_brief.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _closes(rs, day="2026-09-0{}", hold=10):
    return [{"cycle": "w3-1", "realized_r": r, "hold_days": hold,
             "exit_date": day.format(i % 9 + 1)} for i, r in enumerate(rs)]


def test_the_verdict_waits_for_n_30_and_reads_only_the_first_30():
    eb = _mod()
    assert eb.cycle_verdict(_closes([1.0] * 29)) is None, "no verdict before n=30"
    # 30 losers first, then 30 big winners: the verdict is frozen at the 30th.
    rows = _closes([-0.2] * 30, day="2026-09-0{}") + _closes([5.0] * 30, day="2026-09-2{}")
    verdict, rt, rsm, nth = eb.cycle_verdict(rows)
    assert verdict == "KILL" and abs(rt + 0.2) < 1e-9 and nth.startswith("2026-09-0")


@pytest.mark.parametrize("rs,expect", [
    ([-0.05] * 30, "KILL"),                       # the kill line is inclusive
    ([-0.049] * 30, "INCONCLUSIVE"),
    ([0.0] * 30, "PASS"),                         # >= 0 R/t and >= 0 R/sm
    ([0.3] * 30, "PASS"),
])
def test_the_verdict_uses_the_frozen_protocol_lines(rs, expect):
    assert _mod().cycle_verdict(_closes(rs))[0] == expect


def test_a_pass_needs_the_slot_month_leg_too():
    eb = _mod()
    rows = [dict(r, hold_days=0) for r in _closes([0.1] * 30)]
    assert eb.cycle_verdict(rows)[0] == "INCONCLUSIVE", "no hold_days -> no R/sm -> not a PASS"


def test_new_stalls_are_the_engines_stamps_not_a_private_rule():
    """The brief recomputed 'age >= 14 and no TP1' (45 names) while the engine
    stamps stale_pinged (35, incl. TP1-takers like EVT/INTR/ZS)."""
    eb = _mod()
    assert "_stall_syms" not in SRC and "tp1_hit" not in SRC, "the private stall rule is back"
    book = {"open": [{"symbol": "EVT", "tp1_hit": True, "stale_pinged": "2026-10-10"},
                     {"symbol": "NIC", "tp1_hit": False},
                     {"symbol": "ZS", "stale_pinged": "2026-10-01"}]}
    prev = {"open": [{"symbol": "ZS", "stale_pinged": "2026-10-01"}]}
    assert eb._stalled(book) - eb._stalled(prev) == {"EVT"}


def test_the_live_cycle_gets_its_own_line_and_the_ended_kill_is_not_an_issue():
    p = _run()
    import json
    tag = json.loads((ROOT / "public" / "data" / "bot_rules.json").read_text(encoding="utf-8")).get("cycle_tag")
    if tag and tag != "w3-1":
        assert f"cycle {tag} (live):" in p.stdout, p.stdout
        eyes = next(l for l in p.stdout.splitlines() if l.startswith("human eyes today:"))
        assert "w3-1" not in eyes, "an ENDED cycle's verdict is history, not a daily alarm"
