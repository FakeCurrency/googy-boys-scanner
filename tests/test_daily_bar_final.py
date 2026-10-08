"""config.daily_bar_forming -- the one answer to "is today's daily bar final?"

Pinned to MORNING_PLAYS_SLOT_GATE (the 2026-10-06 ASX-close ruling) so the
VIVEK scan, Ignition, momentum_due and PhaseMap cannot drift apart again.
"""
import datetime as dt
from zoneinfo import ZoneInfo

from scanner import config

SYD = ZoneInfo("Australia/Sydney")
NY = ZoneInfo("America/New_York")


def _at(tz, y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=tz)


def test_the_final_instants_are_the_digest_gate():
    for g in config.MORNING_PLAYS_SLOT_GATE.values():
        assert config.DAILY_BAR_FINAL[g["market"]] == (g["tz"], g["hour"], g["minute"])
    assert config.DAILY_BAR_FINAL["asx"][1:] == (16, 40)
    assert config.DAILY_BAR_FINAL["nasdaq"][1:] == (16, 5)


def test_asx_bar_forms_until_1640_sydney_in_both_dst_regimes():
    for (y, m, d) in ((2026, 7, 8), (2026, 10, 8)):          # AEST, AEDT
        day = dt.date(y, m, d)
        assert config.daily_bar_forming("asx", day, _at(SYD, y, m, d, 16, 0))
        assert config.daily_bar_forming("asx", day, _at(SYD, y, m, d, 16, 15))
        assert config.daily_bar_forming("asx", day, _at(SYD, y, m, d, 16, 39))
        assert not config.daily_bar_forming("asx", day, _at(SYD, y, m, d, 16, 40))
        # yesterday's bar is complete whatever the clock says
        assert not config.daily_bar_forming("asx", day - dt.timedelta(days=1),
                                            _at(SYD, y, m, d, 11, 0))


def test_nasdaq_bar_forms_until_1605_new_york_and_accepts_any_aware_now():
    day = dt.date(2026, 10, 7)
    assert config.daily_bar_forming("nasdaq", day, _at(NY, 2026, 10, 7, 11, 52))
    # the same instant expressed in UTC gives the same answer
    utc = _at(NY, 2026, 10, 7, 11, 52).astimezone(dt.timezone.utc)
    assert config.daily_bar_forming("nasdaq", day, utc)
    assert not config.daily_bar_forming("nasdaq", day, _at(NY, 2026, 10, 7, 16, 5))
    assert config.daily_bar_forming("nasdaq", "2026-10-07", utc)


def test_crypto_bar_forms_for_the_whole_utc_day():
    now = dt.datetime(2026, 10, 8, 1, 13, tzinfo=dt.timezone.utc)
    assert config.daily_bar_forming("crypto", dt.date(2026, 10, 8), now)
    assert not config.daily_bar_forming("crypto", dt.date(2026, 10, 7), now)
    # a naive now is read as UTC
    assert config.daily_bar_forming("crypto", "2026-10-08", now.replace(tzinfo=None))


def test_an_unreadable_date_is_not_forming():
    assert not config.daily_bar_forming("asx", "not-a-date",
                                        _at(SYD, 2026, 10, 8, 12, 0))
