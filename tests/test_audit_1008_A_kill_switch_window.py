"""Kill switch measures TODAY's window, not the whole life (audit #3, 2026-10-08).

`kill_switch._book_market_journal` hand-rolled each open position's WHOLE-LIFE
unrealised P&L (`_unreal_r`, from entry) plus every partial it had ever banked,
plus each of today's closes at its whole-life R, and `check_and_kill` compared
that with the DAILY limit — the TOP100 #13 defect, fixed only in the runner's
guard. A market holding old losers that were flat today fired every half hour
(an ::error:: annotation and, with keys set, a broker flatten), and one holding
old winners could take a day past the limit in silence. The switch now reads
`vivek_guard.session_pnl` with live quotes, falling back to each position's
`last_mark`.
"""

import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest

from scanner import config
from scanner.broker import kill_switch as ks
from scanner.broker import vivek_guard as vg

pytestmark = pytest.mark.risk


def _today(market):
    return dt.datetime.now(ZoneInfo(config.MARKETS[market].timezone)).strftime("%Y-%m-%d")


def _old(i, market, carried, last=None, **kw):
    """Open since September (risk 10/unit, $300), carried into today at `carried`."""
    p = {"symbol": f"S{i}", "market": market, "direction": "long", "status": "open",
         "entry": 100.0, "risk": 10.0, "risk_usd": 300.0, "booked_pct": 0.0,
         "realized_r": 0.0, "entry_date": "2026-09-01",
         "day_marks": {_today(market): carried},
         "last_mark": carried if last is None else last}
    p["unreal_usd"] = round((p["last_mark"] - 100.0) / 10.0 * 300.0, 2)
    p.update(kw)
    return p


@pytest.fixture
def on_disk(tmp_path, monkeypatch, stub_alerts):
    """Write a book where run_standalone reads it; quotes are injected."""
    import scanner.broker.vivek_run as vr
    monkeypatch.setattr(config, "VIVEK_BOT_ACCOUNT_EQUITY", 150_000)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)      # $4,500

    def _write(book, quotes):
        p = tmp_path / "vivek_bot_book.json"
        p.write_text(json.dumps(book), encoding="utf-8")
        monkeypatch.setattr(vr, "BOOK_FILE", p)
        monkeypatch.setattr(ks, "_live_marks", lambda b: dict(quotes))
    return _write


def test_old_losers_flat_today_do_not_fire_the_switch(on_disk):
    """20 NASDAQ names each 0.8R under water since September and flat today.
    Whole-life: 20 x -$240 = -$4,800, past -$4,500, so the old adapter fired
    (and with ALPACA keys set, flattened Alpaca) every half hour. Today: $0."""
    book = {"open": [_old(i, "nasdaq", 92.0) for i in range(20)], "closed": []}
    on_disk(book, {(f"S{i}", "nasdaq"): 92.0 for i in range(20)})
    assert ks.run_standalone(dry_run=True)["triggered"] == []


def test_old_winners_crashing_today_do_fire_the_switch(on_disk):
    """10 NASDAQ names up +2R since September each lose 1.6R today: today is
    -$4,800 (past -$4,500) while the whole-life figure still reads +$1,200,
    so the old adapter stayed silent through the crash."""
    book = {"open": [_old(i, "nasdaq", 120.0) for i in range(10)], "closed": []}
    on_disk(book, {(f"S{i}", "nasdaq"): 104.0 for i in range(10)})
    assert ks.run_standalone(dry_run=True)["triggered"] == ["nasdaq"]


def test_the_switch_and_the_runner_guard_read_one_number():
    """Same book, same prices -> the same session figure, open AND closed legs
    (including a close today measured from its day mark, audit #1)."""
    day = "2026-10-08"
    opens = [_old(0, "asx", 50.0, last=48.0), _old(1, "asx", 130.0)]
    for p in opens:
        p["day_marks"] = {day: p["day_marks"][_today("asx")]}
    closed = {"symbol": "C", "market": "asx", "direction": "long", "status": "closed",
              "entry": 100.0, "risk": 10.0, "risk_usd": 300.0, "booked_pct": 1.0,
              "entry_date": "2026-09-01", "exit_date": day,
              "day_marks": {day: 140.0},
              "exits": [{"reason": "stop", "price": 130.0, "pct": 1.0, "date": day}],
              "realized_r": 3.0}
    book = {"open": opens, "closed": [closed]}
    quotes = {("S1", "asx"): 125.0}                   # S0 falls back to last_mark 48
    j = ks._book_market_journal(book, "asx", day, quotes=quotes)
    switch = sum(c["pnl"] for c in j["closed"]) + sum(p["unreal_pnl"] for p in j["open"])
    prices = {"S0": 48.0, "S1": 125.0}
    guard = vg.session_pnl(book, "asx", day, prices.get)["session_usd"]
    assert switch == pytest.approx(guard)
    # (48-50)/10*300 + (125-130)/10*300 + (130-140)/10*300 = -60 - 150 - 300
    assert switch == pytest.approx(-510.0)
    assert j["live_marks"] == 1


def test_before_the_days_first_scan_a_flat_quote_reads_flat():
    """At 02:00 Sydney nothing is stamped for today yet. The window opens from
    what each position carried in (its last_mark, audit #57), so a quote at
    that mark is a flat day — not ~8 days of drift from the oldest mark."""
    p = _old(0, "asx", 0.0)
    p["day_marks"] = {"2026-09-30": 81.0, "2026-10-07": 77.5, "2026-10-08": 78.0}
    p["last_mark"] = 76.5
    j = ks._book_market_journal({"open": [p], "closed": []}, "asx", "2026-10-09",
                                quotes={("S0", "asx"): 76.5})
    assert j["session"]["session_usd"] == pytest.approx(0.0)


def test_a_non_finite_quote_falls_back_to_the_last_mark():
    """NaN compares False against every limit, and check_and_kill's early
    return is `>=`: a NaN session would FIRE. A bad quote is not a price."""
    p = _old(0, "asx", 100.0, last=98.0)
    p["day_marks"] = {"2026-10-08": 100.0}
    j = ks._book_market_journal({"open": [p], "closed": []}, "asx", "2026-10-08",
                                quotes={("S0", "asx"): float("nan")})
    assert j["session"]["session_usd"] == pytest.approx(-60.0)     # (98-100)/10 x $300
    assert j["live_marks"] == 0
