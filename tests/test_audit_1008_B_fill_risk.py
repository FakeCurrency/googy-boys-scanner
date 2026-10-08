"""Audit 2026-10-08 #12: a book row's risk_usd is the 1R of the FILL, not the signal.

decide() sizes the ticket at the plan entry (the signal close, or a break's
pivot): units = notional / signal, risk_usd = units x |signal - stop|. The row
then fills at a live quote, and `_snapshot` measures its per-unit `risk` -- the
unit of realized_r / unreal_r / cost_r -- from the FILL. Every dollar reader
(vivek_guard's day/week P&L, unreal_usd, kill_switch.trade_pnl, the journal)
computes R x risk_usd, so book dollars were off the real units x price move by
(signal - stop) / (fill - stop): a 10 -> 10.80 paid-up fill stopped at 8.95
booked -$256.95 of a real -$462.50.

The fix keeps the SIZE the sizer decided (units, notional) and restates only the
dollars attached to one R: risk_usd = units x risk at the fill, the plan figure
kept as `risk_usd_plan`, risk_pct and the review flag re-derived from it.
"""

import pytest

from scanner import config
from scanner.broker import kill_switch, vivek_bot as vb, vivek_guard, vivek_run as vr
from scanner.vivek_journal import _mark

pytestmark = pytest.mark.risk

DAY = "2026-10-08"


def _ticket(entry=10.0, stop=9.0, tf="1W"):
    plan = {"armed": True, "entry_trigger": "reclaim", "trigger_bar": "2026-10-01",
            "entry": entry, "stop": stop, "tp1": entry + 1.5 * (entry - stop),
            "tp2": entry + 3 * (entry - stop), "tp3": entry + 5 * (entry - stop),
            "rr": 3.0, "scale": config.VIVEK_TP_SCALE_LONG}
    row = {"symbol": "XYZ", "name": "XYZ", "sector": "Tech", "grade": "A+",
           "grade_raw": "A+", "dir": "LONG", "entry_types": ["reclaim"],
           "level_tf": "weekly", "plans": {tf: plan}, "price": entry}
    out = vb.plan_trade(row, config.VIVEK_BOT_ACCOUNT_EQUITY, "nasdaq")
    assert out.get("take"), out.get("reason")
    return out


@pytest.mark.parametrize("fill", [10.8, 9.3])
def test_book_dollars_equal_the_real_money_whatever_the_slip(fill):
    out = _ticket()
    pos = vr._ticket_to_position(out, fill, "nasdaq", DAY)
    assert pos["units"] == out["plan"]["units"] == 250.0        # SIZE unchanged
    assert pos["notional"] == out["plan"]["notional"] == 2500.0
    _mark(pos, 8.95, DAY, None)                                   # stopped out
    assert pos["status"] == "closed"
    real = pos["units"] * (8.95 - fill)
    # Pre-fix: -256.95 (fill 10.8) and -302.32 (fill 9.3) against -462.50 / -87.50.
    assert pos["realized_r"] * pos["risk_usd"] == pytest.approx(real, abs=0.05)
    assert kill_switch.trade_pnl(pos) == pytest.approx(real, abs=0.05)
    assert pos["risk_usd"] == pytest.approx(pos["units"] * pos["risk"], abs=0.01)
    assert pos["risk_usd_plan"] == out["plan"]["risk_usd"] == 250.0   # kept for audit


def test_risk_pct_moves_with_the_restated_dollars():
    out = _ticket()
    pos = vr._ticket_to_position(out, 10.8, "nasdaq", DAY)
    assert pos["risk_pct"] == pytest.approx(out["plan"]["risk_pct"] * 450.0 / 250.0, rel=1e-3)


def test_a_fill_at_the_signal_changes_nothing():
    out = _ticket()
    pos = vr._ticket_to_position(out, 10.0, "nasdaq", DAY)
    assert pos["risk_usd"] == out["plan"]["risk_usd"]
    assert pos["risk_pct"] == out["plan"]["risk_pct"]
    assert pos["review"] == list(out["plan"]["review"])


def test_the_loss_guard_charges_the_real_loss():
    out = _ticket()
    pos = vr._ticket_to_position(out, 10.8, "nasdaq", DAY)
    pos["market"] = "nasdaq"
    book = {"open": [pos], "closed": []}
    g = vivek_guard.check(book, "nasdaq", DAY, config.VIVEK_BOT_ACCOUNT_EQUITY,
                          lambda s: 9.5)
    # 250 units x (9.5 - 10.8) = -$325 of real money, now what the guard reads
    # (pre-fix: -0.722R x $250 = -$180.56).
    assert g["session_usd"] == pytest.approx(250 * (9.5 - 10.8), abs=0.05)


def test_the_review_flag_is_measured_on_the_fill(monkeypatch):
    # A 12.5% planned stop is $312.50 of 1R: under the 7.5% x $4,500 = $337.50
    # flag line. Paid up 4%, the real 1R is $412.50 (a 15.9% stop from the fill): flagged.
    monkeypatch.setattr(config, "VIVEK_BOT_REVIEW_DAILY_LOSS_PCT", 7.5)
    out = _ticket(entry=10.0, stop=8.75)
    assert out["plan"]["review"] == []
    pos = vr._ticket_to_position(out, 10.4, "nasdaq", DAY)
    assert [f["code"] for f in pos["review"]] == ["heavy_risk"]
    assert pos["review"][0]["risk_usd"] == pos["risk_usd"] == pytest.approx(412.5)
