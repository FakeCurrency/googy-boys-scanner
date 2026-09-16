"""kill_switch.check_and_kill -- the legacy scalp-journal daily-loss gate.

Extracted from test_order_path.py on 2026-09-17 when the bracket/reconcile half
of that file went with the AI BOT page + Bybit execution bot. The kill switch
itself stays: kill_switch.yml is the live loss guard on the paper book.
"""
import pytest

from scanner import config
from scanner.broker import kill_switch as ks
from scanner.scalp_journal import _session_day

pytestmark = pytest.mark.pretrade


def test_kill_switch_quiet_inside_limit():
    j = {"open": [{"unreal_pnl": -10.0}],
         "closed": [{"session_day": _session_day(), "pnl": -50.0}]}
    assert ks.check_and_kill(j, dry_run=True) is False


def test_kill_switch_fires_past_limit_and_flattens(monkeypatch):
    from scanner.broker import bybit_client as bc
    cancelled, closed = [], []
    monkeypatch.setenv("BYBIT_API_KEY", "test-key")
    monkeypatch.setattr(bc, "cancel_all_orders", lambda: cancelled.append(1))
    monkeypatch.setattr(bc, "close_all_positions", lambda: closed.append(1))
    over = -(config.SCALP_MAX_DAILY_LOSS + 1)
    j = {"open": [{"unreal_pnl": over}], "closed": []}
    assert ks.check_and_kill(j, dry_run=False) is True
    assert cancelled and closed                               # actually flattened


def test_kill_switch_dry_run_does_not_flatten(monkeypatch):
    from scanner.broker import bybit_client as bc
    monkeypatch.setenv("BYBIT_API_KEY", "test-key")
    monkeypatch.setattr(bc, "cancel_all_orders",
                        lambda: (_ for _ in ()).throw(AssertionError("flattened in dry run")))
    over = -(config.SCALP_MAX_DAILY_LOSS + 1)
    j = {"open": [{"unreal_pnl": over}], "closed": []}
    assert ks.check_and_kill(j, dry_run=True) is True
