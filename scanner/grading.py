"""Shared grading helper for the scanners.

VIVEK (vivek.py) and Specs (spec.py) each turn their own points total into a
letter grade using a list of (grade, cutoff) thresholds; the mapping lives here
so there is exactly one place to read or change it. (`score_chips`, used only by
the retired Reversals scanner, went with it on 2026-10-14, REFINE200 #119.)
"""


def grade_from_points(points: int, cutoffs: list[tuple[str, int]]) -> str | None:
    """Map a points total to the first grade whose cutoff it clears (high -> low)."""
    for name, cutoff in cutoffs:
        if points >= cutoff:
            return name
    return None
