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


# A real date, not a placeholder: since REFINE200 #17 an unparseable day is an
# UNKNOWN week, which fails closed whenever the weekly limit is armed.
D = "2024-01-02"


def test_check_breaches_at_the_equity_limit(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)
    # equity 10,000 → limit $300. A -$400 realised loss breaches it.
    over = {"open": [], "closed": [{"market": "asx", "exit_date": D, "realized_r": -1.0, "risk_usd": 400.0}]}
    g = vg.check(over, "asx", D, 10_000, lambda s: None)
    assert g["breached"] is True and g["limit_usd"] == pytest.approx(300.0)

    under = {"open": [], "closed": [{"market": "asx", "exit_date": D, "realized_r": -1.0, "risk_usd": 200.0}]}
    assert vg.check(under, "asx", D, 10_000, lambda s: None)["breached"] is False


def test_zero_limit_never_breaches(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 0.0)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_WEEKLY_LOSS_PCT", 0.0)
    book = {"open": [], "closed": [{"market": "asx", "exit_date": D, "realized_r": -10.0, "risk_usd": 999.0}]}
    assert vg.check(book, "asx", D, 10_000, lambda s: None)["breached"] is False


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


# ── REFINE200 #19: NaN never reaches a guard sum ──────────────────────────────
# `risk <= 0` is False for NaN, so a NaN risk sailed through `_unreal_r` and a
# NaN session total compares False against every limit: one bad field
# disarmed the guard for the whole market.

@pytest.mark.parametrize("field,value", [
    ("risk", float("nan")), ("risk", float("inf")), ("risk", None), ("risk", "junk"),
    ("entry", float("nan")), ("entry", None), ("entry", 0.0),
])
def test_unreal_r_is_zero_not_nan_on_a_bad_risk_or_entry(field, value):
    p = _pos()
    p[field] = value
    assert vg._unreal_r(p, 96.0) == 0.0


def test_unreal_r_is_zero_on_a_nan_or_infinite_price():
    assert vg._unreal_r(_pos(), float("nan")) == 0.0
    assert vg._unreal_r(_pos(), float("inf")) == 0.0
    assert vg._unreal_r(_pos(), 96.0) == pytest.approx(-1.0)     # control


def test_a_missing_entry_no_longer_raises():
    """`pos["entry"]` used to KeyError, which crashed whatever was summing."""
    p = _pos()
    del p["entry"]
    assert vg._unreal_r(p, 96.0) == 0.0


def test_a_nan_booked_pct_counts_the_full_size_not_none_of_it():
    p = _pos()
    p["booked_pct"] = float("nan")
    assert vg._unreal_r(p, 96.0) == pytest.approx(-1.0)


def test_a_nan_price_is_unpriced_and_fails_closed(monkeypatch):
    """A NaN from price_of is treated exactly like None: reported unpriced and
    valued at its stop, so the guard halts instead of reading NaN as 'fine'."""
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)   # $300
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_WEEKLY_LOSS_PCT", 0.0)
    p = _dated(entry_date="2026-07-01", risk_usd=400.0,
               day_marks={"2026-07-28": 100.0})
    p["stop"] = 96.0
    g = vg.check({"open": [p], "closed": []}, "asx", "2026-07-28", 10_000,
                 lambda s: float("nan"))
    assert g["session_usd"] == pytest.approx(0.0)        # finite, not NaN
    assert g["open_total_usd"] == pytest.approx(0.0)
    assert g["unpriced"] == ["X"]
    assert g["breached"] is True and g["breach_kind"] == "unmeasured"


def test_an_infinite_risk_usd_cannot_poison_the_total():
    p = _dated(entry_date="2026-07-01", risk_usd=float("inf"),
               day_marks={"2026-07-28": 100.0})
    pnl = vg.session_pnl({"open": [p], "closed": []}, "asx", "2026-07-28",
                         lambda s: 96.0)
    assert pnl["session_usd"] == pytest.approx(0.0)      # junk size -> $0, not inf/NaN


# ── REFINE200 #17: an unknown week fails closed ───────────────────────────────

def test_an_unparseable_day_halts_rather_than_reading_the_week_as_zero(monkeypatch):
    """`week.get("session_usd", 0.0)` turned an unknown week into a $0 week."""
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_WEEKLY_LOSS_PCT", 6.0)
    g = vg.check({"open": [], "closed": []}, "asx", "not-a-date", 10_000,
                 lambda s: 100.0)
    assert g["week_measured"] is False
    assert g["breached"] is True and g["breach_kind"] == "unmeasured"
    assert g["week_usd"] == 0.0                     # still a number for its readers


def test_an_unknown_week_with_the_weekly_guard_off_does_not_halt(monkeypatch):
    """Nothing to rule out when there is no weekly limit to breach."""
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_WEEKLY_LOSS_PCT", 0.0)
    g = vg.check({"open": [], "closed": []}, "asx", "not-a-date", 10_000,
                 lambda s: 100.0)
    assert g["breached"] is False and g["week_measured"] is False


def test_a_measured_week_reports_itself_measured(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_WEEKLY_LOSS_PCT", 6.0)
    g = vg.check({"open": [], "closed": []}, "asx", "2026-07-28", 10_000,
                 lambda s: 100.0)
    assert g["week_measured"] is True and g["breached"] is False


def test_a_real_daily_breach_on_an_unknown_week_still_reads_daily(monkeypatch):
    """The unmeasured kind is for 'cannot rule out', never a mask on a breach
    that was actually measured."""
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_WEEKLY_LOSS_PCT", 6.0)
    book = {"open": [], "closed": [{"market": "asx", "exit_date": "not-a-date",
                                    "realized_r": -1.0, "risk_usd": 400.0}]}
    g = vg.check(book, "asx", "not-a-date", 10_000, lambda s: None)
    assert g["breached"] is True and g["breach_kind"] == "daily"


# ── REFINE200 #18: "trailing 7 calendar days" is seven, today included ────────

def _stopped(exit_date, r=-1.0, risk_usd=100.0):
    return {"market": "asx", "exit_date": exit_date, "realized_r": r,
            "risk_usd": risk_usd}


def test_the_weekly_window_is_seven_calendar_days_including_today():
    day = "2026-07-28"                               # a Tuesday
    inside = vg.week_pnl({"open": [], "closed": [_stopped("2026-07-22")]},
                         "asx", day, lambda s: None)   # day-6: last Wednesday
    outside = vg.week_pnl({"open": [], "closed": [_stopped("2026-07-21")]},
                          "asx", day, lambda s: None)  # day-7: same weekday last week
    assert inside["realised_usd"] == pytest.approx(-100.0)
    assert outside["realised_usd"] == pytest.approx(0.0)
    assert vg.week_pnl({"open": [], "closed": [_stopped(day)]}, "asx", day,
                       lambda s: None)["realised_usd"] == pytest.approx(-100.0)


def test_the_weekly_window_reads_its_length_from_config():
    assert config.VIVEK_BOT_WEEKLY_WINDOW_DAYS == 7
    from scanner.broker import vivek_run as vr
    # The day references the window measures from must outlive it.
    assert vr._DAY_MARK_KEEP >= config.VIVEK_BOT_WEEKLY_WINDOW_DAYS


def test_the_week_measures_open_positions_from_the_mark_carried_into_day_minus_6():
    p = _dated(entry_date="2026-07-01", risk_usd=40.0,
               day_marks={"2026-07-21": 90.0, "2026-07-22": 95.0,
                          "2026-07-28": 99.0})
    w = vg.week_pnl({"open": [p], "closed": []}, "asx", "2026-07-28",
                    lambda s: 100.0)
    # from 95 (carried into 07-22) to 100 = +5 / risk 4 = +1.25R x $40
    assert w["unrealised_usd"] == pytest.approx(50.0)


# ── REFINE200 #14: the closing day is a window like any other ─────────────────
# The closed leg charged a trade that closed in the window its whole-life R
# FROM ENTRY. The move from entry to the window's reference had already been
# charged while it was open, so the closing day charged it a second time.

def _long(**kw):
    p = {"symbol": "X", "market": "asx", "direction": "long", "entry": 100.0,
         "risk": 4.0, "risk_usd": 100.0, "entry_date": "2026-07-27"}
    p.update(kw)
    return p


def test_a_stop_at_the_price_it_already_sat_at_costs_nothing_more():
    """THE REPRO. Down -1R at the close of day N (charged on day N). On day N+1
    an OPEN position flat at that price costs $0 -- and the same position
    STOPPED at that same price, with no move at all, used to cost -$100."""
    marks = {"2026-07-28": 96.0}                 # carried into N+1 at -1R
    still_open = _long(status="open", day_marks=marks, last_mark=96.0)
    stopped = _long(status="closed", day_marks=marks, last_mark=96.0,
                    exit_date="2026-07-28", exit_price=96.0, booked_pct=1.0,
                    realized_r=-1.0,
                    exits=[{"reason": "stop", "price": 96.0, "pct": 1.0,
                            "date": "2026-07-28"}])
    day = "2026-07-28"
    o = vg.session_pnl({"open": [still_open], "closed": []}, "asx", day, lambda s: 96.0)
    c = vg.session_pnl({"open": [], "closed": [stopped]}, "asx", day, lambda s: None)
    assert o["session_usd"] == pytest.approx(0.0)
    assert c["realised_usd"] == pytest.approx(0.0)       # was -100.0
    assert c["session_usd"] == pytest.approx(o["session_usd"])


def test_a_closed_trade_telescopes_to_its_whole_life_pnl():
    """Sum every daily window over a trade's life -- open days AND the closing
    day -- and you get its whole-life P&L. Entry 100, risk 4, $40 a R:
      07-27 opens, marks 104                   -> +1.0R
      07-28 TP1 25% at 108, marks 106          -> +0.25 + 0.375 = +0.625R
      07-29 stopped at 98 on the remaining 75% -> -1.5R
    Whole life: 0.25 x 2R + 0.75 x -0.5R = +0.125R = +$5."""
    tp1 = {"reason": "tp1", "price": 108.0, "pct": 0.25, "date": "2026-07-28"}
    stop = {"reason": "stop", "price": 98.0, "pct": 0.75, "date": "2026-07-29"}
    base = dict(risk_usd=40.0)
    day1 = _long(status="open", last_mark=104.0, **base)
    day2 = _long(status="open", day_marks={"2026-07-28": 104.0}, last_mark=106.0,
                 exits=[tp1], booked_pct=0.25, realized_r=0.5, **base)
    day3 = _long(status="closed", last_mark=98.0, exit_date="2026-07-29",
                 day_marks={"2026-07-28": 104.0, "2026-07-29": 106.0},
                 exits=[tp1, stop], booked_pct=1.0, realized_r=0.125, **base)
    windows = [
        vg.session_pnl({"open": [day1], "closed": []}, "asx", "2026-07-27",
                       lambda s: 104.0)["session_usd"],
        vg.session_pnl({"open": [day2], "closed": []}, "asx", "2026-07-28",
                       lambda s: 106.0)["session_usd"],
        vg.session_pnl({"open": [], "closed": [day3]}, "asx", "2026-07-29",
                       lambda s: None)["session_usd"],
    ]
    assert windows == pytest.approx([40.0, 25.0, -60.0])
    assert sum(windows) == pytest.approx(0.125 * 40.0)   # was +$50: 100->106 twice


def test_a_hand_close_before_the_days_first_scan_measures_from_last_mark():
    """No run stamped the closing day (every run stamps before it can close
    anything), so this was closed by hand -- and a hand close never touches
    last_mark, the mark the trade carried into the day. The oldest stamp
    would re-charge days already charged while it was open."""
    t = _long(status="closed", risk_usd=40.0, last_mark=106.0,
              day_marks={"2026-07-20": 90.0, "2026-07-28": 104.0},
              exit_date="2026-07-29", booked_pct=1.0, realized_r=-0.5,
              exits=[{"reason": "manual", "price": 98.0, "pct": 1.0,
                      "date": "2026-07-29"}])
    c = vg.session_pnl({"open": [], "closed": [t]}, "asx", "2026-07-29",
                       lambda s: None)
    assert c["realised_usd"] == pytest.approx((98.0 - 106.0) / 4.0 * 40.0)   # -$80


def test_a_trade_opened_and_closed_inside_the_window_counts_its_whole_life():
    t = _long(status="closed", entry_date="2026-07-29", last_mark=96.0,
              day_marks={"2026-07-29": 100.0}, exit_date="2026-07-29",
              booked_pct=1.0, realized_r=-1.0,
              exits=[{"reason": "stop", "price": 96.0, "pct": 1.0,
                      "date": "2026-07-29"}])
    c = vg.session_pnl({"open": [], "closed": [t]}, "asx", "2026-07-29",
                       lambda s: None)
    assert c["realised_usd"] == pytest.approx(-100.0)


def test_the_week_charges_a_closed_trade_from_the_mark_carried_into_the_week():
    t = _long(status="closed", entry_date="2026-07-01", risk_usd=40.0,
              last_mark=95.0, exit_date="2026-07-27", booked_pct=1.0,
              realized_r=-1.25,
              day_marks={"2026-07-20": 90.0, "2026-07-22": 102.0,
                         "2026-07-27": 97.0},
              exits=[{"reason": "stop", "price": 95.0, "pct": 1.0,
                      "date": "2026-07-27"}])
    w = vg.week_pnl({"open": [], "closed": [t]}, "asx", "2026-07-28",
                    lambda s: None)
    # week = [07-22 .. 07-28]: from 102 (carried into 07-22) to 95 = -1.75R
    assert w["realised_usd"] == pytest.approx(-1.75 * 40.0)


def test_a_closed_row_with_no_exit_ledger_keeps_its_whole_life_r():
    """Nothing to date it against: the pre-#14 number (over-counts, which is
    the conservative side for a loss guard)."""
    t = _long(status="closed", entry_date="2026-07-01", exit_date="2026-07-28",
              day_marks={"2026-07-28": 96.0}, realized_r=-2.0)
    c = vg.session_pnl({"open": [], "closed": [t]}, "asx", "2026-07-28",
                       lambda s: None)
    assert c["realised_usd"] == pytest.approx(-200.0)


def test_closing_costs_still_land_on_the_closed_leg():
    """A trade living inside one window pays its whole round trip there."""
    t = _long(status="closed", entry_date="2026-07-28", exit_date="2026-07-28",
              booked_pct=1.0, gross_r=-1.0, cost_r=0.01, realized_r=-1.01,
              exits=[{"reason": "stop", "price": 96.0, "pct": 1.0,
                      "date": "2026-07-28"}])
    c = vg.session_pnl({"open": [], "closed": [t]}, "asx", "2026-07-28",
                       lambda s: None)
    assert c["realised_usd"] == pytest.approx(-101.0)
