"""Audit #2 (2026-10-08): the VIVEK scan's forming-bar drop ended at the raw
16:00 bell.

`scan._bar_is_forming` called today's daily bar complete the moment the local
clock passed VIVEK_JOURNAL_SESSION's close (16:00). The bot's entry window
(vivek_journal.market_open) adds the 15-minute feed delay and stays open to
16:15, so a scan between 16:00 and 16:15 graded, armed and could OPEN a paper
position on today's unfinished bar; an ASX scan up to 16:39 also graded off the
pre-auction bar. The fix routes the question to the one shared answer,
config.daily_bar_forming (DAILY_BAR_FINAL: ASX 16:40 Sydney, NASDAQ 16:05 New
York -- the MORNING_PLAYS_SLOT_GATE ruling).
"""
import datetime as dt
import types
from zoneinfo import ZoneInfo

import pandas as pd

from scanner import config, scan, vivek, vivek_journal

SYD = ZoneInfo("Australia/Sydney")
NY = ZoneInfo("America/New_York")


def test_asx_bar_is_still_forming_inside_the_bots_entry_window():
    day = dt.date(2026, 10, 8)                       # a Thursday, AEDT
    for hh, mm in ((16, 1), (16, 7), (16, 15), (16, 30), (16, 39)):
        now = dt.datetime(2026, 10, 8, hh, mm, tzinfo=SYD)
        assert scan._bar_is_forming("asx", day, now) is True, f"{hh}:{mm:02d}"
    assert scan._bar_is_forming("asx", day, dt.datetime(2026, 10, 8, 16, 40, tzinfo=SYD)) is False


def test_nasdaq_bar_is_forming_until_its_final_instant():
    day = dt.date(2026, 10, 7)
    assert scan._bar_is_forming("nasdaq", day, dt.datetime(2026, 10, 7, 16, 1, tzinfo=NY)) is True
    assert scan._bar_is_forming("nasdaq", day, dt.datetime(2026, 10, 7, 16, 4, tzinfo=NY)) is True
    assert scan._bar_is_forming("nasdaq", day, dt.datetime(2026, 10, 7, 16, 5, tzinfo=NY)) is False


def test_the_scan_agrees_with_the_shared_definition_minute_by_minute():
    """No second idea of the close: across the whole afternoon, for both stock
    markets, the scan's answer is config.daily_bar_forming's."""
    for mkt, tz, day in (("asx", SYD, dt.date(2026, 10, 8)),
                         ("nasdaq", NY, dt.date(2026, 10, 7))):
        for minute in range(15 * 60, 17 * 60 + 1):
            now = dt.datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=tz)
            assert scan._bar_is_forming(mkt, day, now) == config.daily_bar_forming(mkt, day, now)


def test_no_entry_minute_sees_a_bar_the_shared_definition_calls_forming_as_final():
    """The failure in one line: market_open() True AND the scan keeping a bar
    that is not final. Walk every minute the bot may open on."""
    for mkt, tz, day in (("asx", SYD, dt.date(2026, 10, 8)),
                         ("nasdaq", NY, dt.date(2026, 10, 7))):
        for minute in range(9 * 60, 17 * 60):
            now = dt.datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=tz)
            if not vivek_journal.market_open(mkt, now):
                continue
            if config.daily_bar_forming(mkt, day, now):
                assert scan._bar_is_forming(mkt, day, now) is True, (mkt, now.time())


def _daily_frame(last_day: str, n: int = 40):
    idx = pd.date_range(end=last_day, periods=n, freq="D")
    return pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                         "Close": 100.0, "Volume": 1_000_000.0}, index=idx)


def _scan_at(monkeypatch, now_local: dt.datetime, frame):
    seen = []

    def _evaluate(df):
        seen.append(df.index[-1].date())
        return None                                   # no setup: only the frame matters

    class _Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return now_local.astimezone(tz) if tz else now_local

    monkeypatch.setattr(scan, "dt", types.SimpleNamespace(
        datetime=_Clock, date=dt.date, timedelta=dt.timedelta, timezone=dt.timezone))
    monkeypatch.setattr(vivek, "evaluate", _evaluate)
    uni = [{"yf": "BHP.AX", "symbol": "BHP", "name": "BHP", "sector": "Materials"}]
    scan.scan_vivek_market("asx", universe=uni, frames={"BHP.AX": frame},
                           pulse_data=[], progress=False)
    return seen


def test_a_1610_scan_grades_off_yesterdays_completed_bar(monkeypatch):
    frame = _daily_frame("2026-10-08")
    seen = _scan_at(monkeypatch, dt.datetime(2026, 10, 8, 16, 10, tzinfo=SYD), frame)
    assert seen == [dt.date(2026, 10, 7)], "today's unfinished bar reached evaluate()"


def test_a_scan_after_the_final_instant_keeps_todays_bar(monkeypatch):
    frame = _daily_frame("2026-10-08")
    seen = _scan_at(monkeypatch, dt.datetime(2026, 10, 8, 16, 45, tzinfo=SYD), frame)
    assert seen == [dt.date(2026, 10, 8)]
