"""Circuit-breaker conditions — scanner/broker/circuit_breaker.py.

The safety layers that halt new orders between scans: consecutive-loss pause,
drawdown breaker, anomaly breaker, and the aggregate check_all() (which also
persists fired-state for self-healing notifications).
"""

import json

import pytest

from scanner.broker import circuit_breaker as cb

pytestmark = pytest.mark.breaker


# ── consecutive losses ────────────────────────────────────────────────────────

def test_consec_losses_fires_at_threshold(make_journal, closed_trade, stub_alerts, monkeypatch):
    monkeypatch.setattr(cb._cfg, "CONSEC_LOSS_PAUSE", 3)
    j = make_journal(closed=[closed_trade(pnl=-50) for _ in range(3)])
    res = cb.check_consecutive_losses(j)
    assert res["ok"] is False and res["consec_losses"] == 3


def test_consec_losses_a_win_in_the_window_resets(make_journal, closed_trade, monkeypatch):
    monkeypatch.setattr(cb._cfg, "CONSEC_LOSS_PAUSE", 3)
    # last three are loss, WIN, loss → not three losses in a row
    j = make_journal(closed=[
        closed_trade(pnl=-50), closed_trade(pnl=+80), closed_trade(pnl=-50)])
    assert cb.check_consecutive_losses(j)["ok"] is True


def test_consec_losses_below_threshold_is_ok(make_journal, closed_trade, monkeypatch):
    monkeypatch.setattr(cb._cfg, "CONSEC_LOSS_PAUSE", 3)
    j = make_journal(closed=[closed_trade(pnl=-50), closed_trade(pnl=-50)])
    assert cb.check_consecutive_losses(j)["ok"] is True


def test_consec_losses_ignores_stop_gap_phantoms(make_journal, closed_trade, stub_alerts, monkeypatch):
    monkeypatch.setattr(cb._cfg, "CONSEC_LOSS_PAUSE", 3)
    # a skip_daily_count phantom loss must NOT count toward the streak
    j = make_journal(closed=[
        closed_trade(pnl=-50),
        closed_trade(pnl=-999, skip_daily_count=True),
        closed_trade(pnl=-50)])
    # only two real losses remain → not fired
    assert cb.check_consecutive_losses(j)["ok"] is True


# ── drawdown breaker ──────────────────────────────────────────────────────────

def test_drawdown_breaker_passes_through_action(make_journal, closed_trade, stub_alerts, monkeypatch):
    from scanner.broker import risk_manager as rm
    monkeypatch.setattr(rm._cfg, "MAX_DRAWDOWN_PAUSE", 0.12)
    j = make_journal(closed=[closed_trade(pnl=-rm.account_size() * 0.13)])
    res = cb.check_drawdown_breaker(j)
    assert res["ok"] is False and res["action"] == "pause"


# ── anomaly breaker ───────────────────────────────────────────────────────────

def test_anomaly_breaker_blocks_when_fired(monkeypatch):
    monkeypatch.setattr(cb._cfg, "ANOMALY_PAUSE_ON_TRIGGER", True)
    assert cb.check_anomaly_breaker(last_anomaly_fired=True)["ok"] is False


def test_anomaly_breaker_ok_when_quiet(monkeypatch):
    monkeypatch.setattr(cb._cfg, "ANOMALY_PAUSE_ON_TRIGGER", True)
    assert cb.check_anomaly_breaker(last_anomaly_fired=False)["ok"] is True


def test_anomaly_breaker_respects_disable_flag(monkeypatch):
    monkeypatch.setattr(cb._cfg, "ANOMALY_PAUSE_ON_TRIGGER", False)
    assert cb.check_anomaly_breaker(last_anomaly_fired=True)["ok"] is True


# ── aggregate check_all ───────────────────────────────────────────────────────

@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Redirect the breaker's persisted state file into a temp dir."""
    monkeypatch.setattr(cb, "_STATE_FILE", tmp_path / "alert_state.json")
    return tmp_path / "alert_state.json"


def test_check_all_clean_journal_is_ok(make_journal, isolated_state, stub_alerts):
    res = cb.check_all(make_journal())
    assert res["ok"] is True and res["failed"] == []


def test_check_all_reports_consecutive_losses(make_journal, closed_trade, isolated_state, stub_alerts, monkeypatch):
    monkeypatch.setattr(cb._cfg, "CONSEC_LOSS_PAUSE", 3)
    j = make_journal(closed=[closed_trade(pnl=-50) for _ in range(3)])
    res = cb.check_all(j)
    assert res["ok"] is False and "consecutive_losses" in res["failed"]


def test_check_all_persists_fired_state(make_journal, closed_trade, isolated_state, stub_alerts, monkeypatch):
    monkeypatch.setattr(cb._cfg, "CONSEC_LOSS_PAUSE", 3)
    j = make_journal(closed=[closed_trade(pnl=-50) for _ in range(3)])
    cb.check_all(j)
    saved = json.loads(isolated_state.read_text())
    assert saved["cb_state"]["consecutive_losses"] is True
