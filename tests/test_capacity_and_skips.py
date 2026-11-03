"""bot_rules.json `capacity` + `skips` (the owner's "20 more", 2 Nov): when
slots free up, each market's GICS sector load, and why each A/A+ cell row was
not taken at the last in-session run. DISPLAY ONLY -- nothing decides on any
of it; the deck and the journal render it, the digest reads the same day."""
from __future__ import annotations

import datetime as dt
import json

from scanner import run
from scanner.broker import vivek_bot as vb
from scanner.broker import vivek_run
from scanner.time_stop import time_stop_due
from tests.test_vivek_bot_global_cap import _rows


# -- the one Python definition of the time stop's day ----------------------------

def test_the_time_stop_falls_due_on_day_29_and_a_stock_weekend_rolls_to_monday():
    assert time_stop_due({"entry_date": "2026-10-13", "market": "asx"}, 28) == dt.date(2026, 11, 11)
    # Fri 9 Oct + 29 = Sat 7 Nov: Monday on a stock market, Saturday on crypto
    assert time_stop_due({"entry_date": "2026-10-09", "market": "nasdaq"}, 28) == dt.date(2026, 11, 9)
    assert time_stop_due({"entry_date": "2026-10-09", "market": "crypto"}, 28) == dt.date(2026, 11, 7)
    assert time_stop_due({"entry_date": "2026-10-09", "tp1_hit": True}, 28) is None
    assert time_stop_due({"entry_date": "2026-10-09"}, 0) is None
    assert time_stop_due({"entry_date": ""}, 28) is None


# -- capacity ---------------------------------------------------------------------

def _books(tmp_path, monkeypatch, by_market):
    for m, rows in by_market.items():
        (tmp_path / f"{m}.json").write_text(json.dumps({"open": rows, "closed": []}))
    monkeypatch.setattr(vivek_run, "_market_book_file", lambda m: tmp_path / f"{m}.json")


def test_capacity_counts_the_days_slots_free_and_the_gics_sector_load(tmp_path, monkeypatch):
    _books(tmp_path, monkeypatch, {
        "asx": [{"symbol": "NAB", "sector": "Banks", "entry_date": "2026-10-13"},
                {"symbol": "ASX", "sector": "Financial Services", "entry_date": "2026-10-13"},
                {"symbol": "BHP", "sector": "Materials", "entry_date": "2026-09-01"},   # due: past
                {"symbol": "WOW", "sector": "Consumer Staples Distribution & Retail",
                 "entry_date": "2026-10-13", "tp1_hit": True}],                          # runner
        "crypto": [{"symbol": "BTC", "entry_date": "2026-10-09"}]})
    cap = run._capacity(today=dt.date(2026, 11, 3))
    assert cap["time_stops_due"] == [["2026-11-07", 1], ["2026-11-11", 2]]
    assert cap["sector_load"]["asx"] == {"financials": 2, "consumer staples": 1, "materials": 1}
    assert cap["sector_load"]["crypto"] == {"crypto-major": 1}


def test_an_unreadable_book_gives_null_never_a_guess(tmp_path, monkeypatch):
    (tmp_path / "asx.json").write_text("{nope")
    monkeypatch.setattr(vivek_run, "_market_book_file", lambda m: tmp_path / f"{m}.json")
    assert run._capacity() is None


# -- skips --------------------------------------------------------------------------

def test_a_full_book_records_why_each_row_was_not_taken():
    d = vb.decide(_rows(3), equity=10_000, market="asx", open_book=[],
                  max_open_total=30, open_elsewhere=30)
    vivek_run._record_skips("asx", d, {}, False, dt.datetime(2026, 11, 3, 1, 10, tzinfo=dt.timezone.utc))
    rec = vivek_run.LAST_SKIPS.pop("asx")
    assert rec == {"at": "2026-11-03T01:10:00Z",
                   "reasons": {"S00": "global_cap", "S01": "global_cap", "S02": "global_cap"}}


def test_a_breached_guard_and_a_refused_fill_name_their_own_reason():
    d = vb.decide(_rows(2), equity=10_000, market="nasdaq", open_book=[],
                  max_open_total=30, open_elsewhere=0)
    assert len(d["plans"]) == 2
    now = dt.datetime(2026, 11, 3, 15, 40, tzinfo=dt.timezone.utc)
    vivek_run._record_skips("nasdaq", d, {}, True, now)
    assert set(vivek_run.LAST_SKIPS.pop("nasdaq")["reasons"].values()) == {"loss_guard"}
    vivek_run._record_skips("nasdaq", d, {"S01": "earnings"}, False, now)
    assert vivek_run.LAST_SKIPS.pop("nasdaq")["reasons"] == {"S01": "earnings"}


def test_the_published_skips_keep_a_market_that_did_not_run(tmp_path, monkeypatch):
    prev = tmp_path / "bot_rules.json"
    prev.write_text(json.dumps({"skips": {"asx": {"at": "old", "reasons": {"NAB": "book_full"}},
                                          "nasdaq": {"at": "old", "reasons": {"AAPL": "sector_cap"}}}}))
    monkeypatch.setattr(vivek_run, "LAST_SKIPS", {"nasdaq": {"at": "new", "reasons": {}}})
    out = run._skips(prev)
    assert out == {"asx": {"at": "old", "reasons": {"NAB": "book_full"}},
                   "nasdaq": {"at": "new", "reasons": {}}}
    assert run._skips(tmp_path / "missing.json") == {"nasdaq": {"at": "new", "reasons": {}}}


def test_bot_rules_publishes_both_and_never_the_ignition_word():
    p = run.bot_rules_payload()
    assert "capacity" in p and "skips" in p
    assert "ignit" not in json.dumps(p).lower()
