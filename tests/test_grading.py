"""Unit tests for the generic grading logic used by the daily scanners.

Pinned on the Specs ladder (SPEC_GRADE_CUTOFFS); tests/test_vivek.py pins the
VIVEK one. The retired Reversals/pullback GRADE_CUTOFFS these used to read went
with that dead code on 2026-10-14 (REFINE200 #119)."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scanner import config
from scanner.grading import grade_from_points

CUTOFFS = config.SPEC_GRADE_CUTOFFS


class TestGradeFromPoints:
    """Tests for the generic grade_from_points used by daily scanners."""

    def test_max_score_is_aplus(self):
        assert grade_from_points(config.SPEC_SCORE_MAX, CUTOFFS) == "A+"

    def test_zero_is_none(self):
        assert grade_from_points(0, CUTOFFS) is None

    def test_higher_score_gives_better_or_equal_grade(self):
        rank = {"A+": 0, "A": 1, "B": 2, "C": 3, None: 4}
        grades = [grade_from_points(p, CUTOFFS)
                  for p in range(config.SPEC_SCORE_MAX + 1)]
        ranks = [rank[g] for g in grades]
        assert ranks == sorted(ranks, reverse=True)

    def test_each_cutoff_is_inclusive(self):
        for name, cutoff in CUTOFFS:
            assert grade_from_points(cutoff, CUTOFFS) == name
