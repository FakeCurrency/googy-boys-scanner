"""The day a position's time stop falls due -- standard library only.

This is the ONE Python definition (journal.js timeStopOf is the browser's).
It lives apart from vivek_journal because scripts/morning_plays.py imports it,
and the digest job (morning_plays.yml) runs on a bare Python with no packages
installed. On 3 Nov 2026 the digest imported it through vivek_journal, whose
imports reach numpy, and the ASX slot crashed with ModuleNotFoundError before
it posted. Keep this file to the standard library:
tests/test_bare_python_jobs.py walks every bare-runner script's imports.
vivek_journal re-exports the name, so `vivek_journal.time_stop_due` still
resolves.
"""
from __future__ import annotations

import datetime as dt


def time_stop_due(pos: dict, max_hold: int) -> dt.date | None:
    """The day a position's pre-TP1 time stop falls due, as the engine applies
    it (vivek_run.run_market): the first in-session run whose market date is
    MORE than `max_hold` calendar days after entry -- day max_hold + 1 -- and
    on a stock market the Monday when that day is a weekend (holidays are not
    modelled: "on or after"). journal.js timeStopOf is the browser's copy.
    None past TP1 (a runner is exempt), with the rule off, or no entry date.
    Display only: nothing decides on it."""
    if not max_hold > 0 or pos.get("tp1_hit"):
        return None
    try:
        due = dt.date.fromisoformat(str(pos.get("entry_date") or "")[:10]) + dt.timedelta(days=max_hold + 1)
    except ValueError:
        return None
    if pos.get("market") != "crypto" and due.weekday() >= 5:
        due += dt.timedelta(days=7 - due.weekday())
    return due
