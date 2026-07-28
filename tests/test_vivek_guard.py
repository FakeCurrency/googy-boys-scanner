"""VIVEK daily-loss guardrail — session P&L + breach detection (pure helper)."""

import pytest

from scanner import config
from scanner.broker import vivek_guard as vg

pytestmark = pytest.mark.risk


def _pos(symbol="X", direction="long", entry=100.0, risk=4.0, risk_usd=40.0, market="asx"):
    return {"symbol": symbol, "direction": direction, "entry": entry,
            "risk": risk, "risk_usd": risk_usd, "market": market, "status": "open"}


def test_session_pnl_sums_today_realised_and_open_unrealised():
    book = {
        "open": [_pos(symbol="A", entry=100.0, risk=4.0, risk_usd=40.0)],
        "closed": [
            {"market": "asx", "exit_date": "2024-01-02", "realized_r": -1.0, "risk_usd": 40.0},
            {"market": "asx", "exit_date": "2024-01-01", "realized_r": 5.0, "risk_usd": 40.0},  # other day
            {"market": "nasdaq", "exit_date": "2024-01-02", "realized_r": -3.0, "risk_usd": 40.0},  # other market
        ],
    }
    # open A long, price 96 → unreal_r = (96-100)/4 = -1 → -40
    pnl = vg.session_pnl(book, "asx", "2024-01-02", lambda s: 96.0)
    assert pnl["realised_usd"] == pytest.approx(-40.0)      # only today's asx close
    assert pnl["unrealised_usd"] == pytest.approx(-40.0)
    assert pnl["session_usd"] == pytest.approx(-80.0)
    assert pnl["open"] == 1


def test_check_breaches_at_the_equity_limit(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)
    # equity 10,000 → limit $300. A -$400 realised loss breaches it.
    over = {"open": [], "closed": [{"market": "asx", "exit_date": "d", "realized_r": -1.0, "risk_usd": 400.0}]}
    g = vg.check(over, "asx", "d", 10_000, lambda s: None)
    assert g["breached"] is True and g["limit_usd"] == pytest.approx(300.0)

    under = {"open": [], "closed": [{"market": "asx", "exit_date": "d", "realized_r": -1.0, "risk_usd": 200.0}]}
    assert vg.check(under, "asx", "d", 10_000, lambda s: None)["breached"] is False


def test_zero_limit_never_breaches(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 0.0)
    book = {"open": [], "closed": [{"market": "asx", "exit_date": "d", "realized_r": -10.0, "risk_usd": 999.0}]}
    assert vg.check(book, "asx", "d", 10_000, lambda s: None)["breached"] is False


# ── partially-scaled runners (2026-07-20, review C6) ────────────────────────────
# A position that has booked TP1/TP2 has only (1 - booked_pct) still exposed,
# and its banked R (pos["realized_r"], net of costs) is locked in. The old
# maths valued the FULL original size at the current price and ignored the
# bank — wrong unrealised for the UI and phantom numbers for the loss guard.

def _runner(booked_pct, realized_r, **kw):
    p = _pos(**kw)
    p["booked_pct"] = booked_pct
    p["realized_r"] = realized_r
    return p


def test_scaled_runner_unrealised_uses_remaining_fraction_only():
    # long 100 / risk 4, booked 50% at TP1; price back at 98 → -0.5R per unit,
    # but only HALF the position is still on → -0.25R × $40 = -$10, not -$20.
    book = {"open": [_runner(0.50, 0.75)], "closed": []}
    pnl = vg.session_pnl(book, "asx", "d", lambda s: 98.0)
    assert pnl["unrealised_usd"] == pytest.approx(-10.0)


def test_scaled_runner_banked_r_counts_in_session_totals():
    # The +0.75R already banked at TP1 was previously invisible until the
    # position fully closed — it must count in the session total NOW.
    book = {"open": [_runner(0.50, 0.75)], "closed": []}
    pnl = vg.session_pnl(book, "asx", "d", lambda s: 98.0)
    assert pnl["open_realised_usd"] == pytest.approx(30.0)      # 0.75R × $40
    assert pnl["session_usd"] == pytest.approx(30.0 - 10.0)     # banked + remaining


def test_booked_runner_reversal_does_not_false_breach(monkeypatch):
    """The exact review-C6 scenario: books TP1+TP2, then moves hard against
    the remaining runner. Old maths: -2R on the FULL size ($-400) with the
    +$300 bank invisible → phantom -$400 ≤ -$300 limit → guard halts entries.
    True position P&L is +$200."""
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)   # $300 on 10k
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_WEEKLY_LOSS_PCT", 0.0)  # isolate daily
    # long 100 / risk 4 / risk_usd $200: booked 75% for +1.5R net ($300 banked);
    # price 92 → -2R per unit on the remaining 25% = -$100. Net +$200.
    book = {"open": [_runner(0.75, 1.5, risk_usd=200.0)], "closed": []}
    g = vg.check(book, "asx", "d", 10_000, lambda s: 92.0)
    assert g["session_usd"] == pytest.approx(200.0)
    assert g["breached"] is False


def test_fully_booked_open_position_has_no_unrealised_left():
    book = {"open": [_runner(1.0, 2.0)], "closed": []}
    pnl = vg.session_pnl(book, "asx", "d", lambda s: 130.0)
    assert pnl["unrealised_usd"] == pytest.approx(0.0)          # nothing still on
    assert pnl["open_realised_usd"] == pytest.approx(80.0)      # 2R × $40 banked


def test_weekly_window_includes_open_banked_r(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 0.0)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_WEEKLY_LOSS_PCT", 6.0)  # $600 on 10k
    # a -$500 stop-out five days ago + an open runner with +$300 banked, price
    # flat at entry → week = -500 + 300 + 0 = -$200, inside the -$600 limit.
    book = {"open": [_runner(0.75, 1.5, risk_usd=200.0)],
            "closed": [{"market": "asx", "exit_date": "2024-01-03",
                        "realized_r": -2.5, "risk_usd": 200.0}]}
    g = vg.check(book, "asx", "2024-01-08", 10_000, lambda s: 100.0)
    assert g["week_usd"] == pytest.approx(-200.0)
    assert g["breached"] is False


def test_unscaled_position_behaviour_unchanged():
    # No booked_pct / realized_r on a fresh position → exactly the old numbers.
    book = {"open": [_pos()], "closed": []}
    pnl = vg.session_pnl(book, "asx", "d", lambda s: 96.0)
    assert pnl["unrealised_usd"] == pytest.approx(-40.0)        # full size
    assert pnl["open_realised_usd"] == pytest.approx(0.0)
    assert pnl["session_usd"] == pytest.approx(-40.0)


# ══ WINDOW ARITHMETIC (2026-07-28, TOP100 #13/#14/#15) ════════════════════════
# The guard used to charge a position's WHOLE LIFE to today, every day, until
# it closed — the open leg had no date filter at all. These tests pin the
# replacement: P&L measured from a per-window REFERENCE PRICE, so a day's
# number is a day's number.


def _dated(day_marks=None, entry_date="", exits=None, **kw):
    p = _pos(**kw)
    p["entry_date"] = entry_date
    if day_marks is not None:
        p["day_marks"] = day_marks
    if exits is not None:
        p["exits"] = exits
        p["booked_pct"] = sum(e["pct"] for e in exits)
    return p


# ── the reference price itself ────────────────────────────────────────────────

def test_ref_price_uses_entry_when_the_position_opened_inside_the_window():
    p = _dated(entry_date="2026-07-28", day_marks={"2026-07-28": 130.0})
    # Opened today: its whole life IS the window, so the reference is its entry
    # and its first day counts in full — the day_marks stamp must not win here.
    assert vg.ref_price(p, "2026-07-28") == pytest.approx(100.0)


def test_ref_price_uses_the_mark_carried_into_the_window():
    p = _dated(entry_date="2026-07-01",
               day_marks={"2026-07-26": 110.0, "2026-07-27": 120.0,
                          "2026-07-28": 130.0})
    assert vg.ref_price(p, "2026-07-28") == pytest.approx(130.0)   # today's stamp
    assert vg.ref_price(p, "2026-07-21") == pytest.approx(110.0)   # week: oldest in window


def test_ref_price_falls_back_to_the_oldest_mark_when_all_of_them_predate():
    """A name nothing has been able to price for over a week. Charging MORE of
    its life to the window is the conservative direction; reporting zero is not."""
    p = _dated(entry_date="2026-06-01", day_marks={"2026-07-01": 110.0,
                                                   "2026-07-02": 115.0})
    assert vg.ref_price(p, "2026-07-28") == pytest.approx(110.0)


def test_ref_price_degrades_to_last_mark_then_entry_for_unstamped_rows():
    legacy = _pos()
    legacy["last_mark"] = 118.0
    assert vg.ref_price(legacy, "2026-07-28") == pytest.approx(118.0)
    assert vg.ref_price(_pos(), "2026-07-28") == pytest.approx(100.0)   # entry


def test_ref_price_ignores_junk_marks():
    p = _dated(entry_date="2026-07-01", day_marks={"2026-07-28": 0.0,
                                                   "2026-07-27": None})
    p["last_mark"] = 117.0
    assert vg.ref_price(p, "2026-07-28") == pytest.approx(117.0)


# ── the bug the module exists to kill ─────────────────────────────────────────

def test_an_old_loser_no_longer_arrives_pre_breached_every_morning(monkeypatch):
    """THE LIVE FAILURE. On 2026-07-28 the crypto guard read -$1,827 — 41% of a
    $4,500 daily limit — before the session had done anything at all, because a
    position down 5R since JUNE was charged its whole life to every session.
    Flat since yesterday's close is a flat day."""
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)
    p = _dated(entry_date="2026-06-01", risk_usd=400.0,
               day_marks={"2026-07-28": 80.0})
    book = {"open": [p], "closed": []}
    g = vg.check(book, "asx", "2026-07-28", 10_000, lambda s: 80.0)
    assert g["session_usd"] == pytest.approx(0.0)       # unchanged since the open
    assert g["breached"] is False
    # ...and the whole-life number is still published for anything that wants it
    assert g["open_total_usd"] == pytest.approx(-2000.0)   # -5R x $400


def test_a_real_days_damage_is_still_measured_in_full(monkeypatch):
    """Control for the test above: the guard must go looser on stale losses
    WITHOUT going deaf to today's."""
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)
    p = _dated(entry_date="2026-06-01", risk_usd=400.0,
               day_marks={"2026-07-28": 80.0})
    book = {"open": [p], "closed": []}
    g = vg.check(book, "asx", "2026-07-28", 10_000, lambda s: 76.0)   # -1R today
    assert g["session_usd"] == pytest.approx(-400.0)
    assert g["breached"] is True and g["breach_kind"] == "daily"


def test_daily_windows_telescope_to_the_whole_life_pnl():
    """The property the whole design rests on: sum every day's window over a
    position's life and you get its total P&L — no more, no less. If this drifts
    the guard is either double-counting or losing money down the back of a day."""
    marks = {"2026-07-27": 100.0, "2026-07-28": 104.0, "2026-07-29": 96.0}
    prices = {"2026-07-27": 104.0, "2026-07-28": 96.0, "2026-07-29": 112.0}
    total = 0.0
    for day, px in prices.items():
        p = _dated(entry_date="2026-07-27", day_marks=marks, risk_usd=40.0)
        total += vg.session_pnl({"open": [p], "closed": []}, "asx", day,
                                lambda s: px)["session_usd"]
    # entry 100 -> 112 on risk 4 = +3R x $40 = $120, however you slice the days.
    assert total == pytest.approx(120.0)


# ── #14: banked partial-exit R is dated ───────────────────────────────────────

def test_partial_exit_banked_last_week_is_not_charged_to_today():
    """TOP100 #14. `exits` has carried a per-exit date all along; nothing read
    it, so a TP1 taken a fortnight ago was re-banked into every session after."""
    p = _dated(entry_date="2026-07-01", risk_usd=40.0,
               day_marks={"2026-07-28": 100.0},
               exits=[{"reason": "tp1", "price": 108.0, "pct": 0.25,
                       "date": "2026-07-14"}])
    pnl = vg.session_pnl({"open": [p], "closed": []}, "asx", "2026-07-28",
                         lambda s: 100.0)
    assert pnl["open_realised_usd"] == pytest.approx(0.0)   # banked on the 14th
    assert pnl["session_usd"] == pytest.approx(0.0)


def test_a_partial_exit_taken_today_does_count_today():
    p = _dated(entry_date="2026-07-01", risk_usd=40.0,
               day_marks={"2026-07-28": 100.0},
               exits=[{"reason": "tp1", "price": 108.0, "pct": 0.25,
                       "date": "2026-07-28"}])
    pnl = vg.session_pnl({"open": [p], "closed": []}, "asx", "2026-07-28",
                         lambda s: 100.0)
    # 25% booked 2R above the day's reference = +0.5R x $40 = $20
    assert pnl["open_realised_usd"] == pytest.approx(20.0)


def test_closing_row_does_not_rebank_r_taken_before_the_window():
    """The close-day half of #14: a trade that took TP1 last week and stopped out
    today used to charge its ENTIRE realized_r to today, TP1 included."""
    closed = {"market": "asx", "exit_date": "2026-07-28", "risk_usd": 40.0,
              "direction": "long", "entry": 100.0, "risk": 4.0,
              "realized_r": 0.125,          # +0.5R banked at TP1, -0.375R on the rest
              "exits": [{"reason": "tp1", "price": 108.0, "pct": 0.25,
                         "date": "2026-07-14"},
                        {"reason": "stop", "price": 98.0, "pct": 0.75,
                         "date": "2026-07-28"}]}
    pnl = vg.session_pnl({"open": [], "closed": [closed]}, "asx", "2026-07-28",
                         lambda s: 98.0)
    # whole-life +0.125R x $40 = $5, LESS the +0.5R x $40 = $20 taken on the 14th
    assert pnl["realised_usd"] == pytest.approx(-15.0)


def test_a_trade_that_lived_entirely_inside_the_window_is_untouched():
    """Control: the subtraction must only ever remove R that genuinely belongs
    to an earlier day."""
    closed = {"market": "asx", "exit_date": "2026-07-28", "risk_usd": 40.0,
              "direction": "long", "entry": 100.0, "risk": 4.0,
              "realized_r": -1.0,
              "exits": [{"reason": "stop", "price": 96.0, "pct": 1.0,
                         "date": "2026-07-28"}]}
    pnl = vg.session_pnl({"open": [], "closed": [closed]}, "asx", "2026-07-28",
                         lambda s: 96.0)
    assert pnl["realised_usd"] == pytest.approx(-40.0)


# ── #15: fail CLOSED on a data outage ─────────────────────────────────────────

def test_an_unpriced_position_that_could_breach_halts_new_entries(monkeypatch):
    """TOP100 #15. The old loop did `if price is None: continue` — an outage
    silently DISARMED the daily stop, at the one moment you want it armed."""
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)   # $300
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_WEEKLY_LOSS_PCT", 0.0)
    p = _dated(entry_date="2026-07-01", risk_usd=400.0,
               day_marks={"2026-07-28": 100.0})
    p["stop"] = 96.0                                    # a full 1R = $400 > $300
    g = vg.check({"open": [p], "closed": []}, "asx", "2026-07-28", 10_000,
                 lambda s: None)
    assert g["breached"] is True and g["breach_kind"] == "unmeasured"
    assert g["unpriced"] == ["X"]
    assert g["session_usd"] == pytest.approx(0.0)       # nothing MEASURED moved
    assert g["worst_session_usd"] == pytest.approx(-400.0)


def test_an_unpriced_position_too_small_to_matter_does_not_halt(monkeypatch):
    """The bound is the position's own STOP, not infinity — deliberately. An
    unbounded worst case halts the book permanently the first time one name goes
    unpriceable (MDB did exactly that for weeks), and a guard that never lifts is
    a guard nobody leaves switched on."""
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)   # $300
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_WEEKLY_LOSS_PCT", 0.0)
    p = _dated(entry_date="2026-07-01", risk_usd=40.0,
               day_marks={"2026-07-28": 100.0})
    p["stop"] = 96.0                                    # 1R = $40, nowhere near
    g = vg.check({"open": [p], "closed": []}, "asx", "2026-07-28", 10_000,
                 lambda s: None)
    assert g["breached"] is False and g["breach_kind"] is None
    assert g["unpriced"] == ["X"]                       # reported even so
    assert g["worst_session_usd"] == pytest.approx(-40.0)


def test_a_trailed_stop_above_the_reference_cannot_book_a_worst_case_profit():
    """A runner whose stop has trailed above where the window opened can only
    make money from here. `worst` must clamp at zero, not add a phantom credit
    that offsets a real loss elsewhere in the book."""
    p = _dated(entry_date="2026-07-01", risk_usd=40.0,
               day_marks={"2026-07-28": 100.0})
    p["stop"] = 130.0
    g = vg.check({"open": [p], "closed": []}, "asx", "2026-07-28", 10_000,
                 lambda s: None)
    assert g["unpriced_worst_usd"] == pytest.approx(0.0)


def test_when_everything_prices_the_verdict_is_bit_identical(monkeypatch):
    """The halt is 'the part I cannot see is big enough to matter', NOT a
    blanket outage rule. With a full price feed the fail-closed branch must
    contribute exactly nothing."""
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)
    p = _dated(entry_date="2026-07-01", risk_usd=400.0,
               day_marks={"2026-07-28": 100.0})
    p["stop"] = 96.0
    g = vg.check({"open": [p], "closed": []}, "asx", "2026-07-28", 10_000,
                 lambda s: 100.0)
    assert g["unpriced"] == [] and g["unpriced_worst_usd"] == pytest.approx(0.0)
    assert g["worst_session_usd"] == g["session_usd"]
    assert g["breached"] is False


def test_week_pnl_returns_empty_rather_than_zero_on_an_unparseable_day():
    """An unknown window must not be reported as a quiet one."""
    assert vg.week_pnl({"open": [], "closed": []}, "asx", "not-a-date",
                       lambda s: 100.0) == {}


def test_entry_cost_on_a_never_scaled_position_is_charged_to_the_entry_day():
    """Live evidence: every open row carries ~-0.006R of entry cost (~$3.50 at a
    $5,000 notional). With no `exits` ledger to date it against, that was
    charged to EVERY session for the life of the position — 24 rows x every
    scan, forever. It is a cost, it was paid at entry, it belongs to entry day."""
    old = _dated(entry_date="2026-06-30", risk_usd=500.0,
                 day_marks={"2026-07-28": 100.0})
    old["realized_r"] = -0.0092
    flat = vg.session_pnl({"open": [old], "closed": []}, "asx", "2026-07-28",
                          lambda s: 100.0)
    assert flat["session_usd"] == pytest.approx(0.0)     # a flat day is flat

    fresh = _dated(entry_date="2026-07-28", risk_usd=500.0)
    fresh["realized_r"] = -0.0092
    day1 = vg.session_pnl({"open": [fresh], "closed": []}, "asx", "2026-07-28",
                          lambda s: 100.0)
    assert day1["open_realised_usd"] == pytest.approx(-4.6)   # charged once


def test_undated_banked_r_is_still_counted_when_something_was_actually_booked():
    """The conservative half of the split. Once `booked_pct` > 0 with no ledger
    the dates are genuinely unknown, so the guard keeps over-counting rather
    than guessing — a loss guard should err toward halting."""
    p = _dated(entry_date="2026-06-01", risk_usd=40.0,
               day_marks={"2026-07-28": 100.0})
    p["booked_pct"], p["realized_r"] = 0.5, -2.0
    pnl = vg.session_pnl({"open": [p], "closed": []}, "asx", "2026-07-28",
                         lambda s: 100.0)
    assert pnl["open_realised_usd"] == pytest.approx(-80.0)
