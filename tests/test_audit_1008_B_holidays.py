"""Audit 2026-10-08 #15: an exchange holiday or early close is a CLOSED session.

`market_open()` knew only weekday + clock, and cron-job.org's weekday jobs and
the stale-price heartbeat keep dispatching scans on a holiday. So on
2026-12-25 (Christmas, ASX shut) run_market saw an open session and a freshly
downloaded frame ending 2026-12-24 and booked `FILLED entry 10.0 entry_date
2026-12-25` -- a fill at the previous session's close, dated a day nobody
traded -- and tested held stops on the same stale close. After a NASDAQ 13:00
early close the session stayed "open" until 16:15.

Two layers now: the DATA PROXY (`vivek_journal.no_session_today` -- not one
frame carries a bar dated the market-local today) catches any holiday, listed
or not; `config.VIVEK_JOURNAL_SPECIAL_DAYS` lists holidays (belt and braces)
and the EARLY closes no bar can reveal.
"""

import datetime as dt
import json
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scanner import config, data
from scanner import vivek_journal as vj
from scanner.broker import vivek_run as vr

pytestmark = pytest.mark.risk

SYD = ZoneInfo("Australia/Sydney")
NY = ZoneInfo("America/New_York")


def _frame(close, end):
    idx = pd.date_range(end=end, periods=5, freq="D")
    return pd.DataFrame({"Open": close, "High": close, "Low": close,
                         "Close": close, "Volume": 1e6}, index=idx)


def _row(symbol="HOL"):
    plan = {"armed": True, "entry_trigger": "break", "trigger_bar": "2026-12-23",
            "entry": 10.0, "stop": 9.6, "tp1": 10.6, "tp2": 11.2, "tp3": 12.0,
            "rr": 3.0, "scale": config.VIVEK_TP_SCALE_LONG}
    return {"symbol": symbol, "name": symbol, "sector": "", "grade": "A+",
            "grade_raw": "A+", "dir": "LONG", "entry_types": ["break"],
            "level_tf": "weekly", "plans": {"1W": plan}, "price": 10.0}


def _held(symbol="OLD"):
    return {"id": f"{symbol}-1", "symbol": symbol, "name": symbol, "sector": "",
            "market": "asx", "direction": "long", "grade": "A+",
            "entry_type": "break", "timeframe": "1D", "entry": 10.0, "stop": 9.6,
            "tp1": 10.6, "tp2": 11.2, "tp3": 12.0,
            "scale": list(config.VIVEK_TP_SCALE_LONG), "risk": 0.4, "rr": 3.0,
            "entry_date": "2026-12-01", "status": "open", "booked_pct": 0.0,
            "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
            "realized_r": 0.0, "gross_r": 0.0, "cost_r": 0.0, "exits": [],
            "mae": 10.0, "mfe": 10.0, "mae_r": 0.0, "mfe_r": 0.0,
            "units": 250.0, "notional": 2500.0, "risk_usd": 100.0, "last_mark": 10.0}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "BOOK_DIR", tmp_path)
    monkeypatch.setattr(vr, "BOOK_FILE", tmp_path / "vivek_bot_book.json")
    monkeypatch.setattr(vr, "UNASSIGNED_FILE", tmp_path / "vivek_bot_book.unassigned.json")
    monkeypatch.setattr(vr, "PUBLIC_FILE", tmp_path / "public_book.json")
    monkeypatch.setattr(config, "VIVEK_BOT_ENABLED", True)
    monkeypatch.setattr(config, "VIVEK_BOT_DRY_RUN", False)
    monkeypatch.setattr(vr, "_earnings_within", lambda *a, **k: False)
    monkeypatch.setattr(data, "fetch", lambda *a, **k: ({}, {}))
    return tmp_path


def _book(env, open_=()):
    (env / "vivek_bot_book.asx.json").write_text(json.dumps(
        {"version": 2, "mode": "paper", "market": "asx", "open": list(open_),
         "closed": []}), encoding="utf-8")


UNI = [{"symbol": "HOL", "yf": "HOL.AX"}, {"symbol": "OLD", "yf": "OLD.AX"}]


# ── the data proxy ─────────────────────────────────────────────────────────────

def test_an_unlisted_holiday_takes_no_fill_off_the_previous_close(env, monkeypatch):
    # The audit's reproduction, with the table switched OFF so the proxy alone
    # must catch it: Christmas Day 12:00 Sydney, the frame ends 24 Dec.
    monkeypatch.setattr(config, "VIVEK_JOURNAL_SPECIAL_DAYS", {})
    _book(env)
    now = dt.datetime(2026, 12, 25, 12, 0, tzinfo=SYD)
    frames = {"HOL.AX": _frame(10.0, "2026-12-24"), "OLD.AX": _frame(9.0, "2026-12-24")}
    assert vj.market_open("asx", now) is True                  # the clock is fooled
    assert vj.no_session_today("asx", frames, now) is True     # the bars are not
    bk = vr.run_market("asx", [_row()], frames, UNI, now=now)
    assert bk["open"] == []                                    # pre-fix: FILLED HOL


def test_a_holiday_tests_no_stop_on_the_previous_close(env, monkeypatch):
    monkeypatch.setattr(config, "VIVEK_JOURNAL_SPECIAL_DAYS", {})
    _book(env, [_held()])
    now = dt.datetime(2026, 12, 25, 12, 0, tzinfo=SYD)
    frames = {"OLD.AX": _frame(9.0, "2026-12-24")}             # under the 9.6 stop
    bk = vr.run_market("asx", [], frames, UNI, now=now)
    assert bk["closed"] == [] and bk["open"][0]["status"] == "open"


def test_the_next_trading_day_fills_and_stops_as_normal(env, monkeypatch):
    monkeypatch.setattr(config, "VIVEK_JOURNAL_SPECIAL_DAYS", {})
    _book(env, [_held()])
    now = dt.datetime(2026, 12, 29, 12, 0, tzinfo=SYD)
    frames = {"HOL.AX": _frame(10.0, "2026-12-29"), "OLD.AX": _frame(9.0, "2026-12-29")}
    assert vj.no_session_today("asx", frames, now) is False
    bk = vr.run_market("asx", [_row()], frames, UNI, now=now)
    assert [p["symbol"] for p in bk["open"]] == ["HOL"]
    assert [p["symbol"] for p in bk["closed"]] == ["OLD"]


def test_one_name_trading_today_is_enough_to_call_the_session_live():
    now = dt.datetime(2026, 12, 29, 12, 0, tzinfo=SYD)
    frames = {f"S{i}.AX": _frame(1.0, "2026-12-24") for i in range(50)}
    frames["LIVE.AX"] = _frame(1.0, "2026-12-29")
    assert vj.no_session_today("asx", frames, now) is False


def test_no_dated_frame_is_no_evidence_and_crypto_never_has_a_holiday():
    now = dt.datetime(2026, 12, 25, 12, 0, tzinfo=SYD)
    assert vj.no_session_today("asx", {}, now) is False
    assert vj.no_session_today("asx", {"X.AX": pd.DataFrame()}, now) is False
    utc = dt.datetime(2026, 12, 25, 12, 0, tzinfo=dt.timezone.utc)
    assert vj.no_session_today("crypto", {"BTC-USD": _frame(1.0, "2026-12-20")}, utc) is False


def test_an_aware_index_is_read_in_the_markets_own_calendar():
    # 2026-12-29 00:00 Sydney is 2026-12-28 13:00 UTC: a UTC-stamped index must
    # be converted, not truncated, or a live session reads as a holiday.
    idx = pd.DatetimeIndex([pd.Timestamp("2026-12-28 13:00", tz="UTC")])
    df = pd.DataFrame({"Close": [1.0]}, index=idx)
    now = dt.datetime(2026, 12, 29, 12, 0, tzinfo=SYD)
    assert vj.no_session_today("asx", {"X.AX": df}, now) is False


def test_a_held_refetch_with_todays_bar_is_evidence_the_session_is_live(env, monkeypatch):
    # The scan download came back as nothing but the previous session's bars
    # (throttled, back-filled from last night's cache), but the direct refetch
    # of a held name -- run_market's own fallback for exactly this -- returned
    # today's bar. The exchange traded: the stop it can now see must be tested,
    # so the proxy reads the frames AFTER that refetch, not before it.
    monkeypatch.setattr(config, "VIVEK_JOURNAL_SPECIAL_DAYS", {})
    _book(env, [_held()])
    now = dt.datetime(2026, 12, 29, 12, 0, tzinfo=SYD)
    frames = {"HOL.AX": _frame(10.0, "2026-12-24")}            # OLD missing: refetched
    monkeypatch.setattr(data, "fetch",
                        lambda *a, **k: ({"OLD.AX": _frame(9.0, "2026-12-29")}, {}))
    assert vj.no_session_today("asx", frames, now) is True     # the download alone
    bk = vr.run_market("asx", [], frames, UNI, now=now)
    assert [p["symbol"] for p in bk["closed"]] == ["OLD"]      # 9.0 under the 9.6 stop


def test_with_session_gating_switched_off_the_proxy_never_fires(monkeypatch):
    # VIVEK_JOURNAL_MARKET_HOURS = False means "no session gating at all":
    # market_open is always True, so the proxy must not invent a closed session
    # out of old bars (it would otherwise read every weekend as a holiday).
    monkeypatch.setattr(config, "VIVEK_JOURNAL_MARKET_HOURS", False)
    sat = dt.datetime(2026, 12, 26, 12, 0, tzinfo=SYD)
    assert vj.market_open("asx", sat) is True
    assert vj.no_session_today("asx", {"X.AX": _frame(1.0, "2026-12-24")}, sat) is False


def test_outside_the_session_the_proxy_defers_to_the_clock():
    sat = dt.datetime(2026, 12, 26, 12, 0, tzinfo=SYD)
    assert vj.no_session_today("asx", {"X.AX": _frame(1.0, "2026-12-24")}, sat) is False


# ── the table: listed holidays and early closes ───────────────────────────────

def test_a_listed_holiday_is_shut_even_if_the_feed_prints_a_bar_for_it(env):
    # Belt and braces: a vendor that emits a zero-volume holiday bar would fool
    # the proxy; the table still says shut.
    now = dt.datetime(2026, 12, 25, 12, 0, tzinfo=SYD)
    assert vj.market_open("asx", now) is False
    _book(env)
    frames = {"HOL.AX": _frame(10.0, "2026-12-25")}
    bk = vr.run_market("asx", [_row()], frames, UNI, now=now)
    assert bk["open"] == []


def test_a_nasdaq_early_close_ends_the_session_at_13_00_plus_the_feed_delay():
    day = (2026, 11, 27)                                       # day after Thanksgiving
    assert vj.market_open("nasdaq", dt.datetime(*day, 13, 10, tzinfo=NY)) is True
    assert vj.market_open("nasdaq", dt.datetime(*day, 13, 16, tzinfo=NY)) is False
    assert vj.market_open("nasdaq", dt.datetime(*day, 15, 0, tzinfo=NY)) is False
    # an ordinary Friday is untouched
    assert vj.market_open("nasdaq", dt.datetime(2026, 11, 20, 15, 0, tzinfo=NY)) is True


def test_an_asx_early_close_ends_the_session_at_14_15():
    assert vj.market_open("asx", dt.datetime(2026, 12, 24, 14, 10, tzinfo=SYD)) is True
    assert vj.market_open("asx", dt.datetime(2026, 12, 24, 14, 20, tzinfo=SYD)) is False
    assert vj.market_open("asx", dt.datetime(2026, 12, 31, 15, 0, tzinfo=SYD)) is False


def test_the_table_is_well_formed():
    table = config.VIVEK_JOURNAL_SPECIAL_DAYS
    assert set(table) <= set(config.VIVEK_JOURNAL_SESSION)
    for market, days in table.items():
        assert config.VIVEK_JOURNAL_SESSION[market] is not None, market
        for day, close in days.items():
            d = dt.date.fromisoformat(day)
            assert d.weekday() < 5, f"{market} {day} is a weekend: already shut"
            if close is not None:
                h, m = close
                base = config.VIVEK_JOURNAL_SESSION[market]
                assert (base[0], base[1]) < (h, m) < (base[2], base[3]), (market, day)
