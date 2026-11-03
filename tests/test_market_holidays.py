"""config.MARKET_HOLIDAYS -- the full-day exchange closures (NEXT100 #4).

REPORT ONLY today: scripts/decision_pack.py flags a projected time stop that
lands on one (the engine does not model holidays, so it would book at a stale
close on a shut market) and audits the day_marks stamped on one. A later,
trade-affecting item will make the engine read the same table, so its shape
and its certain dates are pinned now:

  * a dated table per stock market, every key an ISO date inside the window
    (2026-09-01 .. 2027-12-31), a weekday, with a short comment;
  * no crypto entry (crypto never closes) and no early-close day;
  * the dates nobody can dispute are in it (Labor Day 7 Sep, Thanksgiving
    26 Nov, Christmas on both markets, the ASX's Boxing Day substitute).
"""
from __future__ import annotations

import datetime as dt

from scanner import config

WINDOW = ("2026-09-01", "2027-12-31")


def test_the_table_is_a_dated_closure_list_per_stock_market():
    assert set(config.MARKET_HOLIDAYS) == {"asx", "nasdaq"}, "crypto never closes; no other market is traded"
    for market, days in config.MARKET_HOLIDAYS.items():
        assert days, market
        for day, why in days.items():
            d = dt.date.fromisoformat(day)                       # a real ISO date
            assert d.isoformat() == day
            assert WINDOW[0] <= day <= WINDOW[1], (market, day)
            assert d.weekday() < 5, (market, day, "a weekend is never a closure to list")
            assert isinstance(why, str) and why.strip() and why.isascii(), (market, day)
        assert list(days) == sorted(days), f"{market}: keep the table in date order"


def test_the_certain_dates_are_listed():
    nasdaq, asx = config.MARKET_HOLIDAYS["nasdaq"], config.MARKET_HOLIDAYS["asx"]
    assert nasdaq["2026-09-07"].startswith("Labor Day")
    assert nasdaq["2026-11-26"].startswith("Thanksgiving")
    assert "2026-12-25" in nasdaq and "2026-12-25" in asx
    assert asx["2026-12-28"].startswith("Boxing Day")             # 26 Dec 2026 is a Saturday
    assert nasdaq["2027-12-24"].startswith("Christmas")          # 25 Dec 2027 is a Saturday


def test_early_closes_and_open_days_are_not_closures():
    nasdaq, asx = config.MARKET_HOLIDAYS["nasdaq"], config.MARKET_HOLIDAYS["asx"]
    for day in ("2026-11-27", "2026-12-24", "2027-11-26"):       # US 1 pm closes
        assert day not in nasdaq, day
    for day in ("2026-12-24", "2026-12-31", "2027-12-24", "2027-12-31",   # ASX early closes
                "2026-09-07", "2026-11-26",                             # US holidays, ASX open
                "2027-04-26"):                                          # listed as a trading day
        assert day not in asx, day
