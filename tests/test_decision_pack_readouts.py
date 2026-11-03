"""The decision pack's report-only readouts from the owner's "20 more" (2 Nov).

#4 how far past the stop each stop-out filled, split (where the archive has
   the day's bar) into the gap at the open and the scan's lag
#5 what cutting every rules close at -0.5R adverse would have booked
#6 R per slot-month, the decision replay's pass metric, on the live book
"""
from __future__ import annotations

import io
import json

import pytest

from tests.test_decision_pack import _book, _row, dp


def _archive(root, sym, bars):
    d = root / "data" / "history" / "asx"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sym}.json").write_text(json.dumps({"symbol": sym, "bars": bars}), encoding="utf-8")


def _stop(sym, exit_price, *, market="asx", day="2026-10-20", carried=None, **kw):
    """Entry 10, stop 9 (1R = 1), filled at `exit_price`."""
    return _row(sym, -(10 - exit_price), "stop", market=market, exit_date=day,
                entry=10.0, risk=1.0, stop=9.0, exit_price=exit_price,
                day_marks={day: carried} if carried else {}, **kw)


# -- #4 stop fills ---------------------------------------------------------------

def test_a_stop_that_gapped_splits_into_the_gap_and_the_scans_lag(tmp_path):
    """Opened at 8.80 (through the 9.00 stop: 0.20R of gap nobody could
    avoid), filled at 8.60 by the next scan: 0.20R more was the lag."""
    _archive(tmp_path, "GAP", [["2026-10-19", 9.5, 9.6, 9.4, 9.5, 1], ["2026-10-20", 8.8, 8.9, 8.5, 8.6, 1]])
    a = dp.stop_audit(str(tmp_path), [_stop("GAP", 8.6)])["asx"]
    assert a["n"] == 1 and a["with_bar"] == 1
    assert a["slip_total"] == pytest.approx(0.4)
    assert a["gap_total"] == pytest.approx(0.2) and a["lag_total"] == pytest.approx(0.2)


def test_a_stop_crossed_inside_the_session_is_all_lag(tmp_path):
    _archive(tmp_path, "DAY", [["2026-10-19", 9.5, 9.6, 9.4, 9.5, 1], ["2026-10-20", 9.4, 9.5, 8.6, 8.7, 1]])
    a = dp.stop_audit(str(tmp_path), [_stop("DAY", 8.7)])["asx"]
    assert a["gap_total"] == pytest.approx(0.0) and a["lag_total"] == pytest.approx(0.3)


def test_the_adjusted_archive_is_rescaled_to_the_traded_prices(tmp_path):
    """The archive is dividend-adjusted (prior close 9.025 where the book
    carried 9.50 into the session): its 8.55 open is 9.00 as traded -- right
    at the stop, so no gap."""
    _archive(tmp_path, "ADJ", [["2026-10-19", 9.0, 9.1, 9.0, 9.025, 1], ["2026-10-20", 8.55, 8.6, 8.2, 8.3, 1]])
    a = dp.stop_audit(str(tmp_path), [_stop("ADJ", 8.7, carried=9.5)])["asx"]
    assert a["gap_total"] == pytest.approx(0.0, abs=1e-9)
    assert a["lag_total"] == pytest.approx(0.3)


def test_a_split_sized_scale_or_a_missing_bar_is_not_guessed(tmp_path):
    _archive(tmp_path, "SPL", [["2026-10-19", 4.7, 4.8, 4.6, 4.75, 1], ["2026-10-20", 4.4, 4.5, 4.3, 4.35, 1]])
    a = dp.stop_audit(str(tmp_path), [_stop("SPL", 8.7, carried=9.5),          # 2x: a split
                                      _stop("NOPE", 8.8),                        # no file
                                      _stop("NAS", 8.9, market="nasdaq")])
    assert a["asx"]["n"] == 2 and a["asx"]["with_bar"] == 0
    assert a["nasdaq"] == {"n": 1, "avg_exit_r": pytest.approx(-1.1), "slip_total": pytest.approx(0.1),
                           "slip_avg": pytest.approx(0.1), "with_bar": 0, "gap_total": 0.0,
                           "lag_total": 0.0}


# -- #5 the -0.5R cut ---------------------------------------------------------

def test_the_cut_books_minus_half_r_less_costs_and_counts_the_winners_it_kills():
    rows = [_row("A", -1.10, "stop", mae_r=-1.05, cost_r=0.02),            # saved 0.58R
            _row("B", +1.50, "trail", mae_r=-0.70, cost_r=0.02),           # a winner, cut
            _row("C", -0.30, "time", mae_r=-0.40),                         # never reached it
            _row("D", -1.00, "manual", mae_r=-1.0)]                        # a hand close: out
    m = dp.mae_cut_whatif(rows)
    assert (m["n"], m["hit"], m["winners_cut"]) == (3, 2, 1)
    assert m["rules_total"] == pytest.approx(0.10)
    assert m["cut_total"] == pytest.approx(-0.52 - 0.52 - 0.30)
    assert dp.mae_cut_whatif(rows, tag="hc4-2")["n"] == 0


# -- #6 R per slot-month ----------------------------------------------------------

def test_r_per_slot_month_counts_each_slots_days_and_open_rows_to_today():
    closed = [_row("A", 1.0, "time", entry_date="2026-09-01", exit_date="2026-10-01")]   # 30 days
    opn = [dict(_row("B", 0.0, "open", entry_date="2026-10-01"), status="open", unreal_r=0.5)]
    assert dp.r_per_slot_month(closed)["slot_months"] == pytest.approx(30 / 30.4375, abs=0.01)
    both = dp.r_per_slot_month(closed + opn, today="2026-10-31")
    assert both["r_per_slot_month"] == pytest.approx(1.5 / (60 / 30.4375), abs=1e-3)
    assert dp.r_per_slot_month(opn)["r_per_slot_month"] is None          # open needs a today


def test_the_pack_prints_all_three_and_reads_today_from_the_book(tmp_path):
    root = _book(tmp_path, [_stop("X", 8.8, day="2026-10-21")],
                 [dict(_row("Y", 0.0, "open", market="nasdaq"), status="open", unreal_r=0.2,
                       last_mark_day="2026-10-30")])
    buf = io.StringIO()
    assert dp.main([], root=str(root), out=buf) == 0
    text = buf.getvalue()
    for want in ("## Stops: how far past the stop they filled", "## What-if: cut at -0.5R",
                 "## R per slot-month", "book day 2026-10-30"):
        assert want in text, want
    assert text.isascii()
