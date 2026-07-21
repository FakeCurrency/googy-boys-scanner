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
