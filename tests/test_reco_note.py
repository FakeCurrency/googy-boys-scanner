"""scripts/reco_note.py -- the daily RECOMMENDATIONS note's staleness rule.

REFINE200 (2026-10-14): a flat 48h wall-clock limit called Friday's closing
scan stale every Sunday (ASX, ~51h at the 08:52 UTC run) and every Monday
(NASDAQ, ~60h), though in both cases that file WAS the latest close -- scans
run in market hours only. Stale now means "no scan inside or after the latest
session that has closed", in the market's own calendar; crypto (24/7) keeps
its 48h.
"""

from __future__ import annotations

import datetime as dt

import pytest

from scripts import reco_note as rn

UTC = dt.timezone.utc
PRICES = {"rows": {"A": {"dir": "LONG", "grade": "A+"}}}


def _u(s):
    return dt.datetime.fromisoformat(s).astimezone(UTC)


@pytest.mark.parametrize("key,stamp,now,stale", [
    # The two weekend false alarms the flat 48h raised (real 2026-10 stamps).
    ("asx", "2026-10-09T16:45:00+11:00", "2026-10-11T08:52:00+00:00", False),
    ("nasdaq", "2026-10-09T16:22:00-04:00", "2026-10-12T08:52:00+00:00", False),
    ("nasdaq", "2026-10-09T16:22:00-04:00", "2026-10-12T13:00:00+00:00", False),
    # A whole missed session is stale even inside 48 wall hours: Friday's
    # close read on Monday evening Sydney, after Monday's session closed.
    ("asx", "2026-10-09T16:45:00+11:00", "2026-10-12T08:52:00+00:00", True),
    # NASDAQ Tuesday 08:52 UTC: Monday's session has closed, so Friday's file
    # is stale; a Monday 16:07 post-close scan is fresh.
    ("nasdaq", "2026-10-09T16:22:00-04:00", "2026-10-13T08:52:00+00:00", True),
    ("nasdaq", "2026-10-12T16:07:00-04:00", "2026-10-13T08:52:00+00:00", False),
    # A mid-session scan of the latest closed session still reads it.
    ("asx", "2026-10-13T14:07:00+11:00", "2026-10-13T08:52:00+00:00", False),
    # Crypto trades 24/7: plain 48h.
    ("crypto", "2026-10-11T08:00:00+00:00", "2026-10-13T08:52:00+00:00", True),
    ("crypto", "2026-10-12T08:00:00+00:00", "2026-10-13T08:52:00+00:00", False),
])
def test_staleness_is_judged_against_the_latest_closed_session(key, stamp, now, stale):
    why = rn.stale_reason(key, stamp, _u(now))
    assert (why is not None) == stale, why


def test_a_stale_market_says_so_and_a_fresh_one_is_summarised():
    now = _u("2026-10-12T08:52:00+00:00")
    stale = rn.market_line("ASX", dict(PRICES, generated_at="2026-10-09T16:45:00+11:00"),
                           [], key="asx", now=now)
    assert stale == "ASX: last scan Fri 09 Oct 16:45, before the Mon 12 Oct session - no fresh read."
    fresh = rn.market_line("NASDAQ", dict(PRICES, generated_at="2026-10-09T16:22:00-04:00"),
                           [], key="nasdaq", now=now)
    assert "no fresh read" not in fresh and "1L/0S" in fresh
    assert stale.isascii() and fresh.isascii()


def test_an_unreadable_stamp_is_not_called_stale():
    assert rn.stale_reason("asx", "not a date", _u("2026-10-12T08:52:00+00:00")) is None
