"""kill_switch.check_and_kill -- the journal-shaped daily-loss gate.

Extracted from test_order_path.py on 2026-09-17 when the bracket/reconcile half
of that file went with the AI BOT page + Bybit execution bot. The kill switch
itself stays: kill_switch.yml is the live loss guard on the paper book.
"""
import pytest

from scanner import config
from scanner.broker import kill_switch as ks
from scanner.journal_common import session_day

pytestmark = pytest.mark.pretrade


def test_kill_switch_quiet_inside_limit():
    j = {"open": [{"unreal_pnl": -10.0}],
         "closed": [{"session_day": session_day(), "pnl": -50.0}]}
    assert ks.check_and_kill(j, dry_run=True) is False


def test_kill_switch_fires_past_limit_and_flattens(monkeypatch):
    from scanner.broker import bybit_client as bc
    cancelled, closed = [], []
    monkeypatch.setenv("BYBIT_API_KEY", "test-key")
    monkeypatch.setattr(bc, "cancel_all_orders", lambda: cancelled.append(1))
    monkeypatch.setattr(bc, "close_all_positions", lambda: closed.append(1))
    over = -(ks._vivek_daily_limit() + 1)
    j = {"open": [{"unreal_pnl": over}], "closed": []}
    assert ks.check_and_kill(j, dry_run=False) is True
    assert cancelled and closed                               # actually flattened


def test_kill_switch_dry_run_does_not_flatten(monkeypatch):
    from scanner.broker import bybit_client as bc
    monkeypatch.setenv("BYBIT_API_KEY", "test-key")
    monkeypatch.setattr(bc, "cancel_all_orders",
                        lambda: (_ for _ in ()).throw(AssertionError("flattened in dry run")))
    over = -(ks._vivek_daily_limit() + 1)
    j = {"open": [{"unreal_pnl": over}], "closed": []}
    assert ks.check_and_kill(j, dry_run=True) is True


# -- REFINE200 #91: the default limit is the VIVEK one, not the scalp journal's --

def test_the_default_limit_is_the_vivek_daily_limit_not_the_scalp_one(
        monkeypatch, stub_alerts):
    """A bare check_and_kill used to measure the retired scalp journal's $500.

    Production always passed the VIVEK figure (run_standalone), so the switch
    itself never ran on $500 -- but a default nobody is sized against is a
    trap for the next caller. Pinned on numbers where the two limits disagree.
    """
    monkeypatch.setattr(config, "VIVEK_BOT_ACCOUNT_EQUITY", 150_000)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)   # $4,500
    assert ks._vivek_daily_limit() == pytest.approx(4_500.0)
    j = {"open": [{"unreal_pnl": -(config.SCALP_MAX_DAILY_LOSS + 1)}], "closed": []}
    assert ks.check_and_kill(j, dry_run=True) is False      # -$501 is not -$4,500
    j = {"open": [{"unreal_pnl": -4_501.0}], "closed": []}
    assert ks.check_and_kill(j, dry_run=True) is True


def test_the_kill_switch_no_longer_imports_the_scalp_journal():
    """The day key moved to journal_common; scalp_journal re-exports it."""
    import ast
    import pathlib

    from scanner import journal_common, scalp_journal
    tree = ast.parse(pathlib.Path(ks.__file__).read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    named = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not any("scalp_journal" in (m or "") for m in imported)
    assert "SCALP_MAX_DAILY_LOSS" not in named
    assert scalp_journal._session_day is journal_common.session_day
    assert journal_common.session_day("2025-07-01T14:00:00") == "2025-07-02"
