"""Tests for the fail-closed live-trading interlock (scanner/broker/safety.py).

Run:  python -m pytest test/test_safety.py
"""

import pytest

from scanner.broker import safety


def _good_record(n=40):
    """A proven record: ≥30 trades, >30 days span, positive P&L and R."""
    rec = [{"pnl": 12.0, "r": 0.4, "opened_ts": f"2024-02-{(i % 27) + 1:02d}T10:00:00"}
           for i in range(n)]
    rec[0]["opened_ts"]  = "2024-01-01T10:00:00"
    rec[-1]["opened_ts"] = "2024-03-05T10:00:00"
    return rec


def test_paper_mode_is_never_gated(monkeypatch):
    monkeypatch.delenv("ALPACA_LIVE", raising=False)
    safety.assert_live_allowed()                # no raise when not going live


def test_live_blocked_without_confirmation_token(monkeypatch):
    monkeypatch.setenv("ALPACA_LIVE", "true")
    monkeypatch.delenv("LIVE_TRADING_CONFIRMED", raising=False)
    monkeypatch.setattr(safety, "_closed_trades", _good_record)
    blockers = safety.live_blockers()
    assert any("LIVE_TRADING_CONFIRMED" in b for b in blockers)
    with pytest.raises(RuntimeError):
        safety.assert_live_allowed()


def test_live_blocked_with_insufficient_trades(monkeypatch):
    monkeypatch.setenv("ALPACA_LIVE", "true")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMED", safety.CONFIRM_TOKEN)
    monkeypatch.setattr(safety, "_closed_trades", lambda: _good_record(5))
    blockers = safety.live_blockers()
    assert any("closed paper trades" in b for b in blockers)
    with pytest.raises(RuntimeError):
        safety.assert_live_allowed()


def test_live_blocked_with_negative_edge(monkeypatch):
    monkeypatch.setenv("ALPACA_LIVE", "true")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMED", safety.CONFIRM_TOKEN)
    losing = [{"pnl": -5.0, "r": -0.3, "opened_ts": f"2024-0{(i % 3) + 1}-15T10:00:00"}
              for i in range(40)]
    monkeypatch.setattr(safety, "_closed_trades", lambda: losing)
    blockers = safety.live_blockers()
    assert any("not positive" in b for b in blockers)
    with pytest.raises(RuntimeError):
        safety.assert_live_allowed()


def test_live_allowed_when_fully_proven(monkeypatch):
    monkeypatch.setenv("ALPACA_LIVE", "true")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMED", safety.CONFIRM_TOKEN)
    monkeypatch.setattr(safety, "_closed_trades", _good_record)
    assert safety.live_blockers() == []
    safety.assert_live_allowed()                # must not raise
