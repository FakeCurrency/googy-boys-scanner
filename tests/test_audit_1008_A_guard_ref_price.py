"""Loss-guard window reference, audit 2026-10-08 (#57).

#57 `ref_price` fell back to the OLDEST of up to nine stored marks whenever
    today's had not been stamped yet, so `_restamp` after a manual close
    before the day's first scan (and the kill switch, which reads this
    module since audit #3) charged ~8 days of drift to a day that had not
    traded.
"""

import pytest

from scanner.broker import vivek_guard as vg

pytestmark = pytest.mark.risk


def _row(**kw):
    p = {"symbol": "X", "market": "asx", "direction": "long", "status": "open",
         "entry": 100.0, "risk": 4.0, "risk_usd": 40.0, "entry_date": "2026-07-27"}
    p.update(kw)
    return p


# -- #57: before the day's first scan the reference is what it carried in ------

NIC_MARKS = {"2026-09-30": 0.81, "2026-10-01": 0.805, "2026-10-02": 0.755,
             "2026-10-07": 0.775, "2026-10-08": 0.78}


def test_ref_price_before_the_first_scan_is_the_last_mark_not_the_oldest():
    """The audit's live case: NIC's marks run 0.81 (30 Sep) .. 0.78 (8 Oct) and
    it closed the 8th at 0.765. On the 9th before the 11:07 scan the window's
    reference is 0.765 — what `_stamp_day_ref` will stamp — not 0.81."""
    p = _row(symbol="NIC", entry=1.0, risk=0.1, entry_date="2026-09-01",
             day_marks=NIC_MARKS, last_mark=0.765)
    assert vg.ref_price(p, "2026-10-09") == pytest.approx(0.765)
    no_last = {k: v for k, v in p.items() if k != "last_mark"}
    assert vg.ref_price(no_last, "2026-10-09") == pytest.approx(0.78)   # newest


def test_a_close_before_the_first_scan_does_not_stamp_a_week_of_drift_as_today():
    """What `_restamp` does after a manual close at ~10:30 Sydney: every
    position priced at its own last_mark, nothing stamped for today yet. A day
    that has not traded is a flat day; it read -$2,250 here (0.765 vs 0.81)."""
    p = _row(symbol="NIC", entry=1.0, risk=0.1, risk_usd=5000.0,
             entry_date="2026-09-01", day_marks=NIC_MARKS, last_mark=0.765)
    g = vg.check({"open": [p], "closed": []}, "asx", "2026-10-09", 150_000.0,
                 lambda s: 0.765)
    assert g["session_usd"] == pytest.approx(0.0)
    assert g["breached"] is False


def test_a_week_old_newest_mark_still_falls_back_to_the_oldest():
    """3b kept: a position nothing has marked for over a week charges MORE of
    its life to the window, never less. The edge is `_WEEK_DAYS` (7) calendar
    days between the newest mark and the window's first day."""
    p = _row(entry_date="2026-06-01", last_mark=117.0,
             day_marks={"2026-07-01": 110.0, "2026-07-21": 115.0})
    assert vg.ref_price(p, "2026-07-28") == pytest.approx(117.0)    # 7 days: fresh
    p["day_marks"] = {"2026-07-01": 110.0, "2026-07-20": 115.0}
    assert vg.ref_price(p, "2026-07-28") == pytest.approx(110.0)    # 8 days: stale


def test_a_manual_close_before_the_first_scan_is_charged_from_its_last_mark():
    """#1 and #57 together, the path close_position.yml takes at ~10:30 Sydney:
    the row closes TODAY at 0.70 with no mark stamped for today. The day owes
    the move from what it carried in (its last_mark 0.765) to the fill, not
    from the oldest of its nine marks (0.81)."""
    t = _row(symbol="NIC", entry=1.0, risk=0.1, risk_usd=5000.0,
             entry_date="2026-09-01", day_marks=NIC_MARKS, last_mark=0.765,
             status="closed", booked_pct=1.0, exit_date="2026-10-09",
             exit_reason="manual",
             exits=[{"reason": "manual", "price": 0.70, "pct": 1.0,
                     "date": "2026-10-09"}],
             realized_r=-3.0)
    pnl = vg.session_pnl({"open": [], "closed": [t]}, "asx", "2026-10-09",
                         lambda s: None)
    assert pnl["realised_usd"] == pytest.approx((0.70 - 0.765) / 0.1 * 5000.0)


def test_restamp_after_a_pre_scan_manual_close_reads_an_untraded_day_as_flat():
    """End to end through the writer #57 was found in: `vivek_run._restamp`,
    which close_bot_position / close_bot_batch call before saving. ASX book
    copy, ~10:30 Sydney on the 9th, nothing stamped for the 9th yet: the
    saved guard used to carry 0.81 -> 0.765 (the OLDEST of nine marks to the
    last mark) as the 9th's session. The day has not traded, so it is $0."""
    from scanner.broker import vivek_run as vr
    p = _row(symbol="NIC", entry=1.0, risk=0.1, risk_usd=5000.0,
             entry_date="2026-09-01", day_marks=dict(NIC_MARKS), last_mark=0.765)
    book = {"open": [p], "closed": [], "guard": {"asx": {"notified": ""}}}
    vr._restamp(book, "asx", "2026-10-09")
    assert book["guard"]["asx"]["session_usd"] == pytest.approx(0.0)
    assert book["guard"]["asx"]["breached"] is False
