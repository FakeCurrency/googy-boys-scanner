"""One "the bar is final" table and one latest-weekday-close implementation
(REFINE200 #128, 2026-10-14).

config.BAR_FINAL is THE measured "today's daily bar is final in the free feed"
time per stock market. Everything that means the same thing DERIVES from it,
and the two places that deliberately differ say so beside their tables:
  * the edge ledger's ASX 16:45 -- five minutes later, never earlier;
  * the NASDAQ plays digest's 16:05 -- earlier on purpose (the only post-close
    NASDAQ scan under EST is 16:07 New York).
scripts/_marketclock.py is the one stdlib "latest weekday close" for the gate
scripts; the cases here are the ones the five old copies each re-derived.
"""

from __future__ import annotations

import datetime as dt
import re

import pytest

from scanner import config
from scripts import _marketclock as clock

SYD = "Australia/Sydney"
NY = "America/New_York"
UTC = dt.timezone.utc


def _u(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s).astimezone(UTC)


# ── the table and what derives from it ───────────────────────────────────────

def test_bar_final_covers_every_session_market_in_its_own_zone():
    sessions = {m for m, s in config.VIVEK_JOURNAL_SESSION.items() if s}
    assert set(config.BAR_FINAL) == sessions
    for m, (tz, h, mi) in config.BAR_FINAL.items():
        assert tz == config.MARKETS[m].timezone, m
        s = config.VIVEK_JOURNAL_SESSION[m]
        assert (h, mi) > (s[2], s[3]), f"{m}: 'final' before the bell"


def test_ignition_and_the_asx_digest_gate_are_derived_not_retyped():
    assert config.IGNITION_BAR_FINAL == config.BAR_FINAL
    g = config.MORNING_PLAYS_SLOT_GATE["asx"]
    assert (g["tz"], g["hour"], g["minute"]) == config.BAR_FINAL["asx"]
    src = open(config.__file__, encoding="utf-8").read()
    assert re.search(r'^IGNITION_BAR_FINAL = dict\(BAR_FINAL\)$', src, re.M)


def test_the_two_exceptions_are_on_the_safe_side_of_bar_final():
    """The ledger may only be LATER (a frozen stamp must never read a
    pre-final bar); the NASDAQ digest gate is the documented EARLIER one."""
    for m, (_tz, h, mi) in config.BAR_FINAL.items():
        assert tuple(config.ALERT_RETURNS_BAR_FINAL[m]) >= (h, mi), m
    assert config.ALERT_RETURNS_BAR_FINAL["nasdaq"] == config.BAR_FINAL["nasdaq"][1:]
    us = config.MORNING_PLAYS_SLOT_GATE["us"]
    assert us["market"] == "nasdaq" and us["tz"] == config.BAR_FINAL["nasdaq"][0]
    assert (us["hour"], us["minute"]) == (16, 5) < config.BAR_FINAL["nasdaq"][1:]


# ── the shared clock helper ──────────────────────────────────────────────────

@pytest.mark.parametrize("now,tz,hm,want", [
    # Sunday walks back to Friday's close, in both DST regimes.
    ("2026-10-11T09:00:00+00:00", SYD, (16, 40), "2026-10-09T16:40:00+11:00"),
    ("2026-07-12T09:00:00+00:00", SYD, (16, 40), "2026-07-10T16:40:00+10:00"),
    # A Monday BEFORE the time walks back to Friday; at the time it is today's.
    ("2026-10-12T05:39:00+00:00", SYD, (16, 40), "2026-10-09T16:40:00+11:00"),
    ("2026-10-12T05:40:00+00:00", SYD, (16, 40), "2026-10-12T16:40:00+11:00"),
    # Across the AEST -> AEDT change (Sun 4 Oct 2026): Friday's close keeps
    # its own +10:00 offset, read on the AEDT Monday.
    ("2026-10-05T01:00:00+00:00", SYD, (16, 40), "2026-10-02T16:40:00+10:00"),
    # New York, EDT and EST (the change is Sun 1 Nov 2026).
    ("2026-10-13T20:31:00+00:00", NY, (16, 30), "2026-10-13T16:30:00-04:00"),
    ("2026-11-02T21:00:00+00:00", NY, (16, 30), "2026-10-30T16:30:00-04:00"),
    ("2026-11-02T21:31:00+00:00", NY, (16, 30), "2026-11-02T16:30:00-05:00"),
])
def test_latest_weekday_at(now, tz, hm, want):
    got = clock.latest_weekday_at(_u(now), tz, *hm)
    assert got == dt.datetime.fromisoformat(want)
    assert got.isoformat() == want, "returned in the market's own zone"


def test_at_local_is_todays_wall_clock_in_the_zone():
    t = clock.at_local(_u("2026-10-14T03:00:00+00:00"), SYD, 16, 40)
    assert t.isoformat() == "2026-10-14T16:40:00+11:00"


def test_latest_session_is_the_closed_one():
    s = config.VIVEK_JOURNAL_SESSION["asx"]
    opened, close = clock.latest_session(_u("2026-10-14T03:00:00+00:00"), SYD, s)   # Wed 14:00
    assert (opened.isoformat(), close.isoformat()) == (
        "2026-10-13T10:00:00+11:00", "2026-10-13T16:00:00+11:00")


def test_it_matches_the_copies_it_replaced():
    """morning_plays.latest_close and scan_gate.close_of now delegate here;
    ignition_due.last_close (not yet moved) must still agree with it."""
    from scripts import ignition_due, morning_plays as mp
    t = _u("2026-10-11T09:00:00+00:00")
    for gate in config.MORNING_PLAYS_SLOT_GATE.values():
        want = clock.latest_weekday_at(t, gate["tz"], gate["hour"], gate["minute"])
        assert mp.latest_close(gate, t) == want
    for m, (tz, h, mi) in config.IGNITION_BAR_FINAL.items():
        assert ignition_due.last_close(m, t) == clock.latest_weekday_at(t, tz, h, mi)


def test_the_helper_is_stdlib_only():
    src = open(clock.__file__, encoding="utf-8").read()
    mods = set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", src, re.M))
    assert mods <= {"__future__", "datetime", "zoneinfo"}, mods
