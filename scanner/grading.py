"""Shared scoring + grading helpers for every scanner.

All the scanners (pullback, short, reversal, spec, scalp) turn a set of fired
signal "chips" into a points total, then map that total to a letter grade using
a list of (grade, cutoff) thresholds. That logic was copy-pasted into each
module; it now lives here so there is exactly one place to read or change it.
"""


def score_chips(sig: dict, chip_order: list[str], points_map: dict[str, int],
                key_map: dict[str, str] | None = None) -> tuple[int, list[str]]:
    """Sum the points of every chip that fired.

    sig         the evaluated-signal dict (chip -> truthy/falsey).
    chip_order  the chips to check, in display order.
    points_map  chip -> point weight.
    key_map     optional chip -> the key to read in `sig` (when they differ).

    Returns (total_points, fired_chip_keys).
    """
    points = 0
    fired: list[str] = []
    for key in chip_order:
        sig_key = key_map[key] if key_map else key
        if sig.get(sig_key):
            points += points_map[key]
            fired.append(key)
    return points, fired


def grade_from_points(points: int, cutoffs: list[tuple[str, int]]) -> str | None:
    """Map a points total to the first grade whose cutoff it clears (high -> low)."""
    for name, cutoff in cutoffs:
        if points >= cutoff:
            return name
    return None
