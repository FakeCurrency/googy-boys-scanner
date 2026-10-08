"""Loss-guard window maths, audit 2026-10-08 (#1: the CLOSED leg).

#1  The CLOSED leg of `vivek_guard._window_pnl` charged a trade's whole-life
    `realized_r` (measured from ENTRY) to its exit day, while the OPEN leg had
    measured every earlier day from that day's `day_marks` reference since
    TOP100 #13. So the windows stopped telescoping at every close: a trailed
    runner giving back a big move to its stop read as roughly flat on a crash
    day (the guard stayed quiet and new entries carried on), and an old loser
    stopping out on a quiet day re-charged its whole loss (a false halt).
"""

import pytest

from scanner import config
from scanner.broker import vivek_guard as vg

pytestmark = pytest.mark.risk


def _row(**kw):
    p = {"symbol": "X", "market": "asx", "direction": "long", "status": "open",
         "entry": 100.0, "risk": 4.0, "risk_usd": 40.0, "entry_date": "2026-07-27"}
    p.update(kw)
    return p


def _closed(**kw):
    kw.setdefault("status", "closed")
    kw.setdefault("booked_pct", 1.0)
    return _row(**kw)


@pytest.fixture
def guard_limits(monkeypatch):
    """$4,500 a day on $150,000, the live figures; the weekly guard isolated."""
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_WEEKLY_LOSS_PCT", 0.0)
    return 150_000.0


# -- #1: the daily windows telescope ACROSS the close ---------------------------

MARKS = {"2026-07-27": 100.0, "2026-07-28": 104.0, "2026-07-29": 96.0,
         "2026-07-30": 110.0}
TP1 = {"reason": "tp1", "price": 108.0, "pct": 0.25, "date": "2026-07-29"}
STOP = {"reason": "stop", "price": 99.0, "pct": 0.75, "date": "2026-07-30"}


def _day(book, day, px):
    return vg.session_pnl(book, "asx", day, lambda s: px)["session_usd"]


def test_daily_windows_telescope_through_the_day_the_position_closes():
    """Open 27th at 100, marks 104 then 96, TP1 25% at 108 on the 29th (closes
    the day at 110), the trailed rest stops at 99 on the 30th. Whole life:
    0.25 x 2R + 0.75 x -0.25R = +0.3125R x $40 = +$12.50, however it is sliced.
    The pre-fix closed leg charged the 30th +0.3125R - 0.5R(prior TP1) = -$7.50
    instead of the -$82.50 the stop really cost from the 110 carried in, so the
    four days summed to +$87.50."""
    total = _day({"open": [_row(day_marks=MARKS)], "closed": []}, "2026-07-27", 104.0)
    total += _day({"open": [_row(day_marks=MARKS)], "closed": []}, "2026-07-28", 96.0)
    total += _day({"open": [_row(day_marks=MARKS, exits=[TP1], booked_pct=0.25)],
                   "closed": []}, "2026-07-29", 110.0)
    closed = _closed(day_marks=MARKS, exits=[TP1, STOP], exit_date="2026-07-30",
                     realized_r=0.3125)
    last = _day({"open": [], "closed": [closed]}, "2026-07-30", 99.0)
    assert last == pytest.approx(-82.5)          # 0.75 x (99 - 110)/4 x $40
    assert total + last == pytest.approx(12.5)


def test_the_week_that_holds_the_whole_life_charges_exactly_the_whole_life():
    closed = _closed(day_marks=MARKS, exits=[TP1, STOP], exit_date="2026-07-30",
                     realized_r=0.3125)
    wk = vg.week_pnl({"open": [], "closed": [closed]}, "asx", "2026-07-30",
                     lambda s: None)
    assert wk["realised_usd"] == pytest.approx(12.5)


def test_a_trade_that_lived_inside_one_window_still_pays_its_full_net_cost():
    """Control: entry and exit in one window -> the whole cost_r lands there, so
    the window equals the row's own net realized_r exactly."""
    closed = _closed(entry_date="2026-07-30", exit_date="2026-07-30",
                     exits=[{"reason": "stop", "price": 96.0, "pct": 1.0,
                             "date": "2026-07-30"}],
                     gross_r=-1.0, cost_r=0.02, realized_r=-1.02)
    pnl = vg.session_pnl({"open": [], "closed": [closed]}, "asx", "2026-07-30",
                         lambda s: None)
    assert pnl["realised_usd"] == pytest.approx(-1.02 * 40.0)


# -- #1: the two directions the audit reproduced --------------------------------

def _loser(i, day):
    """Open since September, carried into `day` at 100, marked 1R down today."""
    return _row(symbol=f"L{i}", market="nasdaq", risk=10.0, risk_usd=450.0,
                entry_date="2026-09-01", day_marks={day: 100.0})


def test_a_crash_day_that_stops_out_a_trailed_runner_is_still_a_breach(guard_limits):
    """Ten names each lose a full 1R ($450) from the mark they carried in, and a
    runner bought at 100 (TP1 banked last week, carried in at 140) has its
    trailed stop fill at 130. The real day is -$4,500 - $375 = -$4,875, past
    the -$4,500 limit. The pre-fix closed leg credited the runner +2.25R
    (+$1,125, its whole life since entry less the old TP1), the guard read
    -$3,375 and run_market kept filling new entries through the crash."""
    day = "2026-10-08"
    runner = _closed(symbol="RUN", market="nasdaq", risk=10.0, risk_usd=500.0,
                     entry_date="2026-09-01", exit_date=day,
                     exit_reason="trail", tp1_hit=True,
                     day_marks={"2026-10-07": 138.0, day: 140.0},
                     exits=[{"reason": "tp1", "price": 120.0, "pct": 0.25,
                             "date": "2026-09-20"},
                            {"reason": "stop", "price": 130.0, "pct": 0.75,
                             "date": day}],
                     realized_r=0.25 * 2.0 + 0.75 * 3.0)
    book = {"open": [_loser(i, day) for i in range(10)], "closed": [runner]}
    g = vg.check(book, "nasdaq", day, guard_limits,
                 lambda s: 90.0 if s.startswith("L") else None)
    assert g["realised_usd"] == pytest.approx(-375.0)     # 0.75 x (130-140)/10 x $500
    assert g["session_usd"] == pytest.approx(-4875.0)
    assert g["breached"] is True and g["breach_kind"] == "daily"


def test_an_old_loser_stopping_out_on_a_quiet_day_is_not_a_false_halt(guard_limits):
    """Carried in at -0.9R, stopped today at -1R: the day cost 0.1R ($500), not
    the whole -1R ($5,000) that the pre-fix leg re-charged — a halt on a day
    the book barely moved."""
    day = "2026-10-08"
    t = _closed(risk=10.0, risk_usd=5000.0, entry_date="2026-09-01",
                exit_date=day, day_marks={"2026-10-07": 93.0, day: 91.0},
                exits=[{"reason": "stop", "price": 90.0, "pct": 1.0, "date": day}],
                realized_r=-1.0)
    g = vg.check({"open": [], "closed": [t]}, "asx", day, guard_limits,
                 lambda s: None)
    assert g["session_usd"] == pytest.approx(-500.0)
    assert g["breached"] is False


# -- #1: what still takes the old whole-life charge, on purpose ------------------

def test_a_closed_row_with_no_reference_keeps_the_whole_life_charge():
    """No day_marks and opened before the window: `ref_price` would fall to the
    row's last_mark — on a scan-closed row that is its own exit print — and the
    close would read as zero. Such a row keeps the pre-fix charge (whole life,
    less partials dated before the window), which errs toward halting."""
    t = _closed(entry_date="2026-07-01", exit_date="2026-07-28", last_mark=98.0,
                exits=[{"reason": "tp1", "price": 108.0, "pct": 0.25,
                        "date": "2026-07-14"},
                       {"reason": "stop", "price": 98.0, "pct": 0.75,
                        "date": "2026-07-28"}],
                realized_r=0.125)
    pnl = vg.session_pnl({"open": [], "closed": [t]}, "asx", "2026-07-28",
                         lambda s: None)
    assert pnl["realised_usd"] == pytest.approx((0.125 - 0.5) * 40.0)


def test_an_incomplete_exit_ledger_keeps_the_whole_life_charge():
    """A ledger covering only part of the position cannot date the rest, so the
    window maths would silently drop it. The whole-life path counts it."""
    t = _closed(entry_date="2026-07-01", exit_date="2026-07-28",
                day_marks={"2026-07-28": 100.0},
                exits=[{"reason": "stop", "price": 96.0, "pct": 0.5,
                        "date": "2026-07-28"}],
                realized_r=-1.0)
    pnl = vg.session_pnl({"open": [], "closed": [t]}, "asx", "2026-07-28",
                         lambda s: None)
    assert pnl["realised_usd"] == pytest.approx(-40.0)


def test_windowable_close_needs_every_piece():
    ok = _closed(entry_date="2026-07-01", exit_date="2026-07-28",
                 day_marks={"2026-07-28": 100.0},
                 exits=[{"reason": "stop", "price": 96.0, "pct": 1.0,
                         "date": "2026-07-28"}])
    assert vg._windowable_close(ok, "2026-07-28", "2026-07-28") is True
    undated = dict(ok, exits=[{"reason": "stop", "price": 96.0, "pct": 1.0}])
    assert vg._windowable_close(undated, "2026-07-28", "2026-07-28") is False
    assert vg._windowable_close(dict(ok, risk=0.0), "2026-07-28", "2026-07-28") is False
    assert vg._windowable_close(dict(ok, exits=[]), "2026-07-28", "2026-07-28") is False
    no_ref = {k: v for k, v in ok.items() if k != "day_marks"}
    assert vg._windowable_close(no_ref, "2026-07-28", "2026-07-28") is False
    # ...unless it opened inside the window: its entry IS the reference
    assert vg._windowable_close(dict(no_ref, entry_date="2026-07-28"),
                                "2026-07-28", "2026-07-28") is True
