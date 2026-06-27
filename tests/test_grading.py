"""Unit tests for the generic grading logic used by the daily scanners."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scanner.grading import grade_from_points
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
