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
    """Redirect the breaker's persisted state file into a temp dir.

    BOTH names have to move, and that they are the same file is the point
    (2026-07-28): `_save_cb_state` now writes through
    `alert_router.update_state`, so the breaker no longer does its own
    read-modify-write on journal/alert_state.json. The router owns `last_sent`
    and `acknowledged`, this module owns `cb_state`, and the single writer is
    what stops one silently reverting the other when check_all()'s
    cleared-breaker smart_send interleaves with its own state save.
    """
    from scanner.broker import alert_router as ar
    state = tmp_path / "alert_state.json"
    monkeypatch.setattr(cb, "_STATE_FILE", state)
    monkeypatch.setattr(ar, "STATE_FILE", state)
    return state


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


# ── reading a book that records R instead of dollars ──────────────────────────

def test_consec_losses_counts_a_bot_book_whose_rows_have_no_pnl_field(stub_alerts, monkeypatch):
    """The bot book stores realized_r + risk_usd and no `pnl` at all.

    Under the old `.get("pnl", 0)` every one of these read as exactly
    breakeven, so a book of nothing but losses returned "0 consecutive losses,
    all clear" -- silently, with nothing raised and nothing logged.
    """
    monkeypatch.setattr(cb._cfg, "CONSEC_LOSS_PAUSE", 3)
    book = {"closed": [
        {"symbol": "EVT",  "realized_r": -0.2726, "risk_usd": 35.0},
        {"symbol": "TSLA", "realized_r": -1.3882, "risk_usd": 35.0},
        {"symbol": "AMSF", "realized_r": -1.0299, "risk_usd": 35.0},
    ]}
    res = cb.check_consecutive_losses(book)
    assert res["ok"] is False and res["consec_losses"] == 3


def test_consec_losses_still_reads_an_explicit_pnl_exactly_as_before(
        make_journal, closed_trade, stub_alerts, monkeypatch):
    """No behaviour change for the journal this breaker actually guards."""
    monkeypatch.setattr(cb._cfg, "CONSEC_LOSS_PAUSE", 3)
    losses = make_journal(closed=[closed_trade(pnl=-50) for _ in range(3)])
    wins   = make_journal(closed=[closed_trade(pnl=50) for _ in range(3)])
    assert cb.check_consecutive_losses(losses)["ok"] is False
    assert cb.check_consecutive_losses(wins)["ok"] is True


def test_consec_losses_does_not_crash_on_an_explicit_null_pnl(
        make_journal, closed_trade, stub_alerts, monkeypatch):
    """`None < 0` is a TypeError, and it would take the pre-trade check down."""
    monkeypatch.setattr(cb._cfg, "CONSEC_LOSS_PAUSE", 3)
    j = make_journal(closed=[closed_trade(pnl=None) for _ in range(3)])
    res = cb.check_consecutive_losses(j)          # must not raise
    assert res["consec_losses"] == 0 and res["ok"] is True


# ── notify=False: asking what it WOULD say, without saying it ─────────────────

def _capture_alerts(monkeypatch) -> list:
    """Collect what this module would push, instead of silencing it.

    The shared `stub_alerts` fixture mutes alert_dispatch.send and returns True,
    which is what almost every test here wants and is useless to these two: the
    whole assertion is about how many sends happened. Patching the same seam
    with an appending stub is not a second mechanism, it is the same one asked
    for its output. `check_consecutive_losses` imports send INSIDE the function,
    so patching the module attribute is enough — there is no from-import binding
    captured at import time to miss.
    """
    import scanner.broker.alert_dispatch as ad
    sent: list = []
    monkeypatch.setattr(ad, "send", lambda *a, **k: sent.append(a), raising=False)
    return sent


def test_notify_false_computes_the_same_verdict_without_pushing_an_alert(
        make_journal, closed_trade, monkeypatch):
    """A read-only reporter must not announce a pause that never happened.

    scripts/health_check.py runs this breaker against the BOT BOOK, which it
    does not gate, purely to report what it would say. Left notifying, that
    readout pushes "circuit breaker fired -- new orders paused" to Discord
    about a book whose entries were not paused, which is worse than silence.
    """
    sent = _capture_alerts(monkeypatch)
    monkeypatch.setattr(cb._cfg, "CONSEC_LOSS_PAUSE", 3)
    j = make_journal(closed=[closed_trade(pnl=-50) for _ in range(3)])

    loud = cb.check_consecutive_losses(j)
    sent_after_loud = len(sent)
    quiet = cb.check_consecutive_losses(j, notify=False)

    assert quiet == loud                    # identical verdict
    assert quiet["ok"] is False             # and it is the FIRED verdict, not a no-op
    assert sent_after_loud > 0              # the default really does alert
    assert len(sent) == sent_after_loud     # ...and notify=False added none


def test_notify_defaults_to_true_so_every_existing_caller_is_unchanged(
        make_journal, closed_trade, monkeypatch):
    """The new kwarg must be invisible to pre_trade_check, bybit_run and check_all."""
    sent = _capture_alerts(monkeypatch)
    monkeypatch.setattr(cb._cfg, "CONSEC_LOSS_PAUSE", 3)
    j = make_journal(closed=[closed_trade(pnl=-50) for _ in range(3)])
    cb.check_consecutive_losses(j)
    assert len(sent) > 0
