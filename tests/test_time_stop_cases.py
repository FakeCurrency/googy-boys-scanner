"""THE TIME STOP's day-29 boundary, pinned on the engine that closes the row
(NEXT100 #3, 2026-11-03).

Time stops are November's main exit and, under hc4-2, the only way a full book
frees a slot, so the journal's countdown has to name the day the engine really
closes on. Three readers answer to ONE table, tests/fixtures/time_stop_cases.json:

  * scanner/time_stop.py time_stop_due -- the Python definition (the digest's
    next time-stop day and bot_rules.json `capacity` read it);
  * scanner/broker/vivek_run.run_market -- the engine: a pre-TP1 row closes at
    the first IN-SESSION run held MORE than max_hold days (exit_reason "time");
  * public/js/journal.js timeStopOf -- the journal's countdown
    (test/time_stop_cases.test.js runs the same table on the shipped file).

Before this the only run_market time-stop test closed a row held 62 days
(tests/test_vivek_run.py), which proves the rule exists but not where its edge
is: a `>` turned `>=` (a day-28 close) or a dropped session gate (a Saturday
close) passed it. Here the table's own claims are checked first -- each run's
offset is its market's clock, `session` is market_open, `held` is the
market-date count, `closes` is "in session and on or after `due`" -- then every
case goes through time_stop_due and every run through a real run_market on a
one-row book.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scanner import config
from scanner.broker import vivek_run as vr
from scanner.time_stop import time_stop_due
from scanner.vivek_journal import market_open
from tests.test_vivek_run import _enable, _mfile, _open_position, _write_market_book

pytestmark = pytest.mark.risk

CASES_FILE = pathlib.Path(__file__).resolve().parent / "fixtures" / "time_stop_cases.json"
CASES = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
RUNS = [(c, r) for c in CASES for r in c["runs"]]
RUN_IDS = [f"{c['name']} @ {r['at']}" for c, r in RUNS]
# +1R on _open_position's 100 / 96 long: under TP1 (106), clear of the stop,
# and outside the stale-position probe's |0.5R| band, so the one rule this
# file is about is the only one that can close (or ping about) the row.
PRICE = 104.0


def _due(case) -> dt.date | None:
    return dt.date.fromisoformat(case["due"]) if case["due"] else None


def _local(case, run) -> dt.datetime:
    """The run's instant on its market's own clock (what run_market is handed)."""
    tz = ZoneInfo(config.MARKETS[case["market"]].timezone)
    return dt.datetime.fromisoformat(run["at"]).astimezone(tz)


def _day_n(case) -> dt.date:
    """The calendar day max_hold + 1 lands on, before any weekend roll."""
    return dt.date.fromisoformat(case["entry_date"]) + dt.timedelta(days=case["max_hold"] + 1)


# -- the table cannot be gutted ---------------------------------------------------

def test_the_table_covers_every_edge_of_the_rule():
    names = [c["name"] for c in CASES]
    assert len(names) == len(set(names)), "two cases share a name"
    stock = [c for c in CASES if c["market"] != "crypto" and c["due"]]
    assert any(_day_n(c).weekday() < 5 for c in stock), "no stock case due on a weekday"
    assert any(_day_n(c).weekday() == 5 for c in stock), "no stock case whose day falls on a Saturday"
    assert any(_day_n(c).weekday() == 6 for c in stock), "no stock case whose day falls on a Sunday"
    assert any(c["market"] == "crypto" and _due(c).weekday() >= 5 for c in CASES if c["due"]), \
        "no crypto case due on a weekend (crypto has none)"
    assert any(c["tp1_hit"] and c["max_hold"] > 0 and c["due"] is None for c in CASES), "no runner case"
    assert any(c["max_hold"] == 0 and c["due"] is None for c in CASES), "no rule-off case"
    assert any(c["due"] and c["max_hold"] not in (0, 28) for c in CASES), \
        "every case runs under 28: the table would not notice a 28 typed into the rule"
    holds = [r for c, r in RUNS if c["due"] and r["session"] and r["held"] == c["max_hold"]]
    assert holds and not any(r["closes"] for r in holds), "day max_hold in session must be a HOLD"
    assert any(r["closes"] and r["held"] == c["max_hold"] + 1 for c, r in RUNS), "no day-29 close"
    assert any(r["closes"] and _local(c, r).weekday() == 0 and r["held"] > c["max_hold"] + 1
               for c, r in RUNS), "no Monday close of a weekend due day"
    assert any(not r["session"] and c["due"] and _local(c, r).date() >= _due(c) for c, r in RUNS), \
        "no out-of-session run on or after the due day (it must not close)"
    assert any(c["market"] == "crypto" and r["closes"] for c, r in RUNS), "no crypto close"
    assert any(_local(c, r).date() != dt.datetime.fromisoformat(r["at"]).astimezone(dt.timezone.utc).date()
               for c, r in RUNS), "no run whose market date differs from the UTC date"


@pytest.mark.parametrize("case,run", RUNS, ids=RUN_IDS)
def test_each_run_states_its_own_markets_facts(case, run):
    """The table cannot carry a claim its market contradicts: the offset in
    `at` is the market's clock at that instant, `session` is market_open
    there, `held` is the engine's day count, and `closes` is exactly "in
    session and on or after the due day"."""
    at, local = dt.datetime.fromisoformat(run["at"]), _local(case, run)
    assert at.utcoffset() == local.utcoffset(), f"{run['at']} is not {case['market']}'s own clock"
    assert market_open(case["market"], local) is run["session"]
    assert vr._held_days({"entry_date": case["entry_date"]}, local.strftime("%Y-%m-%d")) == run["held"]
    due = _due(case)
    assert run["closes"] == (run["session"] and due is not None and local.date() >= due)


# -- the Python definition ---------------------------------------------------------

@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_time_stop_due_names_the_tables_day(case):
    pos = {"market": case["market"], "entry_date": case["entry_date"], "tp1_hit": case["tp1_hit"]}
    assert time_stop_due(pos, case["max_hold"]) == _due(case)


# -- the engine ----------------------------------------------------------------------

def _frame(day: dt.date, close: float) -> pd.DataFrame:
    idx = pd.date_range(end=pd.Timestamp(day), periods=5, freq="D")
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close,
                         "Volume": 1e6}, index=idx)


def _held_row(case, symbol):
    pos = _open_position(symbol, case["market"])
    pos["entry_date"] = case["entry_date"]
    if case["tp1_hit"]:
        # a runner as _mark leaves one: TP1's slice booked, the stop at break-even
        slice_ = config.VIVEK_TP_SCALE_LONG[0]
        pos.update(tp1_hit=True, stop=pos["entry"], booked_pct=slice_,
                   gross_r=round(slice_ * 1.5, 4), realized_r=round(slice_ * 1.5, 4),
                   exits=[{"reason": "tp1", "price": pos["tp1"], "pct": slice_,
                           "date": case["entry_date"]}])
    return pos


@pytest.mark.parametrize("case,run", RUNS, ids=RUN_IDS)
def test_run_market_closes_on_exactly_the_tables_run(case, run, tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_HOLD_DAYS", case["max_hold"])
    market, sym = case["market"], "TSC"
    pos = _held_row(case, sym)
    _write_market_book(tmp_path, market, open_=[pos])
    now = _local(case, run)
    day = now.strftime("%Y-%m-%d")
    yf = sym + config.MARKETS[market].suffix
    bk = vr.run_market(market, [], {yf: _frame(now.date(), PRICE)}, [{"symbol": sym, "yf": yf}],
                       now=now)

    # the journal's definition and the engine agree on this run, before the
    # table's own expectation is even read
    due = time_stop_due(pos, case["max_hold"])
    assert run["closes"] == (market_open(market, now) and due is not None and now.date() >= due)

    saved = json.loads(_mfile(tmp_path, market).read_text(encoding="utf-8"))
    open_now = [t for t in bk["open"] if t["symbol"] == sym]
    closed_now = [t for t in bk["closed"] if t["symbol"] == sym]
    if run["closes"]:
        assert open_now == [], f"held {run['held']} days in session: the time stop should have closed it"
        (row,) = closed_now
        assert row["exit_reason"] == "time" and row["exit_date"] == day
        assert row["hold_days"] == run["held"] and row["exit_price"] == PRICE
        assert saved["open"] == [] and [t["exit_reason"] for t in saved["closed"]] == ["time"]
    else:
        assert closed_now == [], (f"closed {closed_now and closed_now[0].get('exit_reason')!r} on a run "
                                  f"the table says holds (held {run['held']}, session {run['session']})")
        (row,) = open_now
        assert row["status"] == "open" and "exit_reason" not in row
        assert [t["symbol"] for t in saved["open"]] == [sym] and saved["closed"] == []
