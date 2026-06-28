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
