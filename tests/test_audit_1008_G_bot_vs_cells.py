"""Audit 2026-10-08 #65 -- scripts/bot_vs_cells.py and the grade it trusts.

`classify` marked every position entered since 2026-09-21 grade-unknown unless
a git-history scan trace was found, on the premise that plan_trade stamps every
ticket "A+". That stopped being true with the BOT HONESTY fix (2026-09-24):
plan_trade records the grade_raw it took. In a shallow clone -- what a cloud
session has -- the trace misses, and 51 of 60 open positions read "unknown",
so the note's "Open positions in-cell" headline was wrong.

Synthetic rows only: journal/ is live data and never a test fixture.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bot_vs_cells", ROOT / "scripts" / "bot_vs_cells.py")
bvc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bvc)


def _pos(**kw):
    base = {"id": "X:long:1W:2026-09-28", "symbol": "X", "name": "Operating Co",
            "sector": "Industrials", "direction": "long", "grade": "A", "timeframe": "1W",
            "entry_type": "reclaim", "level_tf": "weekly", "entry": 100.0, "risk": 20.0,
            "signal_entry": 100.0, "entry_date": "2026-09-28", "_market": "nasdaq",
            "_side": "open"}
    base.update(kw)
    return base


def test_the_boundary_sits_after_the_fix_and_inside_the_window_it_closes():
    assert bvc.A_TAKEABLE_SINCE < bvc.GRADE_TRUE_SINCE
    assert bvc.GRADE_TRUE_SINCE > "2026-09-24", "a row entered on the fix's own day is ambiguous"


@pytest.mark.parametrize("grade", ["A", "A+"])
def test_a_row_entered_after_the_fix_is_graded_off_the_book(grade):
    c = bvc.classify(_pos(grade=grade))
    assert c["cls"] == "in" and c["grade"] == grade
    assert c["grade_src"] == "book (grade_raw as taken)"


def test_a_post_fix_grade_outside_the_bot_grades_is_named_out():
    c = bvc.classify(_pos(grade="B+"))
    assert c["cls"] == "out" and "grade B+" in c["why"]


def test_a_post_fix_row_with_no_grade_stays_unknown_never_guessed():
    c = bvc.classify(_pos(grade=None))
    assert c["cls"] == "unknown" and c["unknown"] == ["grade"]


def test_the_stamped_window_is_still_unknown_without_a_trace():
    c = bvc.classify(_pos(entry_date="2026-09-22", grade="A+"))
    assert c["cls"] == "unknown" and c["unknown"] == ["grade"]
    assert bvc.classify(_pos(entry_date="2026-09-22"), {"grade_raw": "A"})["cls"] == "in"


def test_a_scan_trace_still_wins_after_the_fix():
    c = bvc.classify(_pos(grade="A+"), {"grade_raw": "A"})
    assert c["grade"] == "A" and c["grade_src"] == "scan grade_raw"
