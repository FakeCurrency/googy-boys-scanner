"""Unit tests for grading logic and scalp score/grade functions."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from scanner.grading import grade_from_points
from scanner.scalp import score_and_grade, SCALP_POINTS, SCALP_SCORE_MAX, SCALP_GRADE_CUTOFFS
from scanner.config import GRADE_CUTOFFS as DAILY_GRADE_CUTOFFS


class TestGradeFromPoints:
    """Tests for the generic grade_from_points used by daily scanners."""

    def test_max_score_is_aplus(self):
        grade = grade_from_points(15, DAILY_GRADE_CUTOFFS)
        assert grade == "A+"

    def test_zero_is_none(self):
        assert grade_from_points(0, DAILY_GRADE_CUTOFFS) is None

    def test_higher_score_gives_better_or_equal_grade(self):
        rank = {"A+": 0, "A": 1, "B": 2, "C": 3, None: 4}
        g_high = grade_from_points(14, DAILY_GRADE_CUTOFFS)
        g_low  = grade_from_points(4,  DAILY_GRADE_CUTOFFS)
        assert rank.get(g_high, 4) <= rank.get(g_low, 4)


class TestScalpScoreAndGrade:
    def _make_sig(self, **kwargs):
        base = {
            "squeeze_fired":  False,
            "squeeze_on":     False,
            "momentum_dir":   False,
            "momentum_accel": False,
            "pivot_ok":       False,
            "volume":         False,
            "direction":      "long",
            "mom_val":        0.0,
            "close":          100.0,
        }
        base.update(kwargs)
        return base

    def test_all_false_no_grade(self):
        sig = self._make_sig()
        points, grade, fired = score_and_grade(sig)
        assert points == 0
        assert grade is None
        assert fired == []

    def test_squeeze_fired_only_not_aplus(self):
        # A+ requires squeeze_fired AND score >= 8; with only squeeze_fired (3 pts) → no A+
        sig = self._make_sig(squeeze_fired=True)
        points, grade, fired = score_and_grade(sig)
        assert points == SCALP_POINTS["squeeze_fired"]
        assert grade != "A+"

    def test_all_true_is_aplus(self):
        sig = self._make_sig(
            squeeze_fired=True, squeeze_on=True, momentum_dir=True,
            momentum_accel=True, pivot_ok=True, volume=True,
        )
        points, grade, fired = score_and_grade(sig)
        assert points == SCALP_SCORE_MAX
        assert grade == "A+"
        assert len(fired) == 6

    def test_aplus_requires_squeeze_fired(self):
        # Without squeeze_fired, even max other points can't yield A+
        sig = self._make_sig(
            squeeze_on=True, momentum_dir=True, momentum_accel=True, pivot_ok=True, volume=True,
        )
        points, grade, _ = score_and_grade(sig)
        assert grade != "A+", "A+ must require squeeze_fired"

    def test_score_max_constant(self):
        assert SCALP_SCORE_MAX == sum(SCALP_POINTS.values())
