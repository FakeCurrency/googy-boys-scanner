"""Shared utility functions for scanner broker modules.

Extracted here to avoid duplication across fill_analysis, scaling_advisor,
and any future modules that work with ISO week keys.
"""
import datetime as dt


def _iso_week(day: str) -> str:
    """Return 'YYYY-WNN' ISO week key from a YYYY-MM-DD session_day string.

    Returns an empty string if the input cannot be parsed.
    """
    try:
        d   = dt.date.fromisoformat(day[:10])
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except Exception:
        return ""


def _current_iso_week() -> str:
    """Return the ISO week key for today (e.g. '2026-W25')."""
    iso = dt.date.today().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"
