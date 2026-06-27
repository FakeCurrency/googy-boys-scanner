"""Risk-management & position-sizing rules — scanner/broker/risk_manager.py.

These guard the portfolio-level controls that sit between a signal and a live
order: account sizing, equity/drawdown reconstruction, portfolio heat (incl. the
break-even carve-out), drawdown circuit-breaker thresholds, dynamic sizing,
sector caps, position/capital caps, fat-finger guard and the Weekly+3D bias gate.
"""

import pytest

from scanner.broker import risk_manager as rm

pytestmark = pytest.mark.risk


# ── account size ──────────────────────────────────────────────────────────────

def test_account_size_defaults_to_starting_capital(monkeypatch):
    monkeypatch.setattr(rm._cfg, "ACCOUNT_OVERRIDE_USD", 0)
    assert rm.account_size() == float(rm._cfg.SCALP_STARTING_CAPITAL)


def test_account_size_override_wins_when_set(monkeypatch):
    monkeypatch.setattr(rm._cfg, "ACCOUNT_OVERRIDE_USD", 12_345)
    assert rm.account_size() == 12_345.0


# ── equity curve & drawdown ───────────────────────────────────────────────────

def test_equity_and_peak_reconstructed_in_order(make_journal, closed_trade):
    acct = rm.account_size()
    j = make_journal(closed=[
        closed_trade(pnl=+1_000, opened_ts="2026-06-27T01:00:00Z"),
        closed_trade(pnl=-400,  opened_ts="2026-06-27T02:00:00Z"),
    ])
    equity, peak = rm.current_equity_and_peak(j)
    assert equity == pytest.approx(acct + 600)
    assert peak == pytest.approx(acct + 1_000)  # peak captured before the -400


def test_drawdown_is_fraction_below_peak(make_journal, closed_trade):
    acct = rm.account_size()
    j = make_journal(closed=[closed_trade(pnl=-acct * 0.10)])
    assert rm.current_drawdown(j) == pytest.approx(0.10, rel=1e-6)


def test_no_drawdown_when_only_gains(make_journal, closed_trade):
    j = make_journal(closed=[closed_trade(pnl=+500), closed_trade(pnl=+250)])
    assert rm.current_drawdown(j) == 0.0


# ── portfolio heat ────────────────────────────────────────────────────────────

def test_portfolio_heat_sums_open_risk(make_pos):
    acct = rm.account_size()
    positions = [make_pos(risk_per_trade=100), make_pos(risk_per_trade=200)]
    assert rm.portfolio_heat(positions) == pytest.approx(300 / acct)


def test_breakeven_runner_contributes_zero_heat(make_pos):
    acct = rm.account_size()
    positions = [
        make_pos(risk_per_trade=100),                       # real risk
        make_pos(risk_per_trade=100, stop_at_breakeven=True),  # flagged BE
        make_pos(risk_per_trade=100, entry=50_000, stop=50_000),  # stop==entry
    ]
    # Only the first position still carries risk.
    assert rm.portfolio_heat(positions) == pytest.approx(100 / acct)


def test_check_portfolio_heat_blocks_over_limit(make_pos, monkeypatch):
    monkeypatch.setattr(rm._cfg, "PORTFOLIO_HEAT_LIMIT", 0.05)
    acct = rm.account_size()
    over = [make_pos(risk_per_trade=acct * 0.06)]   # 6% > 5% limit
    res = rm.check_portfolio_heat(over)
    assert res["ok"] is False and res["heat"] > res["limit"]


# ── drawdown circuit breaker ──────────────────────────────────────────────────

def test_drawdown_breaker_none_pause_close(make_journal, closed_trade, monkeypatch):
    monkeypatch.setattr(rm._cfg, "MAX_DRAWDOWN_PAUSE", 0.12)
    monkeypatch.setattr(rm._cfg, "MAX_DRAWDOWN_CLOSE", 0.15)
    acct = rm.account_size()

    healthy = make_journal(closed=[closed_trade(pnl=-acct * 0.05)])
    assert rm.check_drawdown(healthy)["action"] == "none"

    paused = make_journal(closed=[closed_trade(pnl=-acct * 0.13)])
    r = rm.check_drawdown(paused)
    assert r["action"] == "pause" and r["ok"] is False

    flat = make_journal(closed=[closed_trade(pnl=-acct * 0.16)])
    r = rm.check_drawdown(flat)
    assert r["action"] == "close_all" and r["ok"] is False


# ── dynamic sizing ────────────────────────────────────────────────────────────

def test_dynamic_size_full_when_healthy_and_trending(make_journal):
    assert rm.dynamic_size_multiplier(make_journal(), regime="trending") == 1.0


def test_dynamic_size_halved_in_drawdown(make_journal, closed_trade, monkeypatch):
    monkeypatch.setattr(rm._cfg, "DRAWDOWN_HALVE_SIZE_AT", 0.08)
    j = make_journal(closed=[closed_trade(pnl=-rm.account_size() * 0.10)])
    assert rm.dynamic_size_multiplier(j, regime="trending") == 0.5


def test_dynamic_size_floored_at_quarter(make_journal, closed_trade, monkeypatch):
    monkeypatch.setattr(rm._cfg, "DRAWDOWN_HALVE_SIZE_AT", 0.08)
    monkeypatch.setattr(rm._cfg, "REGIME_RANGING_RISK_MULT", 0.5)
    # drawdown halves (0.5) AND ranging halves again (0.25) → floored at 0.25, not lower
    j = make_journal(closed=[closed_trade(pnl=-rm.account_size() * 0.10)])
    assert rm.dynamic_size_multiplier(j, regime="ranging") == 0.25


# ── sector exposure ───────────────────────────────────────────────────────────

def test_sector_exposure_aggregates_by_label(make_pos):
    positions = [make_pos(sector="metals", risk_per_trade=100),
                 make_pos(sector="metals", risk_per_trade=150),
                 make_pos(sector="energy", risk_per_trade=80)]
    exp = rm.sector_exposure_usd(positions)
    assert exp["metals"] == pytest.approx(250) and exp["energy"] == pytest.approx(80)


def test_sector_cap_blocks_when_breached(make_pos, monkeypatch):
    monkeypatch.setattr(rm._cfg, "SECTOR_EXPOSURE_CAP", 0.40)
    acct = rm.account_size()
    existing = [make_pos(sector="metals", risk_per_trade=acct * 0.35)]
    new = make_pos(sector="metals", risk_per_trade=acct * 0.10)  # would total 45% > 40%
    res = rm.check_sector_cap(existing, new)
    assert res["ok"] is False and res["sector"] == "metals"


# ── position / capital / fat-finger caps ──────────────────────────────────────

def test_max_positions_cap(make_journal, make_pos, monkeypatch):
    monkeypatch.setattr(rm._cfg, "MAX_OPEN_POSITIONS", 3)
    assert rm.check_max_positions(make_journal(open_=[make_pos()] * 2))["ok"] is True
    assert rm.check_max_positions(make_journal(open_=[make_pos()] * 3))["ok"] is False


def test_max_capital_cap(make_journal, make_pos, monkeypatch):
    monkeypatch.setattr(rm._cfg, "MAX_MANAGED_CAPITAL_USD", 10_000)
    # 0.2 @ 60000 = $12,000 notional > $10k cap
    pos = make_pos(units=0.2, entry=60_000)
    assert rm.check_max_capital(make_journal(open_=[pos]))["ok"] is False
    small = make_pos(units=0.001, entry=60_000)  # $60 notional
    assert rm.check_max_capital(make_journal(open_=[small]))["ok"] is True


def test_order_size_min_and_fatfinger(monkeypatch):
    monkeypatch.setattr(rm._cfg, "ORDER_SIZE_MIN_USD", 10)
    monkeypatch.setattr(rm._cfg, "ORDER_SIZE_MAX_USD", 5_000)
    assert rm.check_order_size(units=0.00001, entry=50_000)["ok"] is False  # $0.5 < min
    assert rm.check_order_size(units=1.0, entry=50_000)["ok"] is False       # $50k > max
    assert rm.check_order_size(units=0.02, entry=50_000)["ok"] is True       # $1k ok


# ── HTF bias gate ─────────────────────────────────────────────────────────────

def test_htf_bias_blocks_counter_trend():
    bias = {"BTCUSDT": {"weekly": "bull", "threeDay": "bull"}}
    assert rm.check_htf_bias("BTCUSDT", "short", bias)["ok"] is False
    assert rm.check_htf_bias("BTCUSDT", "long", bias)["ok"] is True


def test_htf_bias_unknown_symbol_allowed():
    assert rm.check_htf_bias("DOGEUSDT", "long", {})["ok"] is True


def test_htf_bias_partial_alignment_allowed():
    bias = {"BTCUSDT": {"weekly": "bull", "threeDay": "neutral"}}
    res = rm.check_htf_bias("BTCUSDT", "long", bias)
    assert res["ok"] is True and res["strength"] == "partial"


def test_htf_bias_respects_disable_flag(monkeypatch):
    monkeypatch.setattr(rm._cfg, "HTF_BIAS_REQUIRED", False)
    bias = {"BTCUSDT": {"weekly": "bull", "threeDay": "bull"}}
    # counter-trend would normally block, but the gate is disabled
    assert rm.check_htf_bias("BTCUSDT", "short", bias)["ok"] is True
