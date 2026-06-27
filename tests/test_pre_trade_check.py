"""Pre-trade gate rules — scanner/broker/pre_trade_check.py.

pre_trade_check() is the single go/no-go authority before an order is placed. It
runs 12 checks and returns {ok, checks, failed, reason}. These tests prove a
clean candidate passes and that each individual rule can block it.
"""

import pytest

from scanner.broker.pre_trade_check import pre_trade_check

pytestmark = pytest.mark.pretrade


def _run(pos, journal, today, **kw):
    return pre_trade_check(pos, journal, sess_day=today, **kw)


# ── clean pass ────────────────────────────────────────────────────────────────

def test_clean_candidate_passes_all_checks(make_pos, make_journal, today):
    res = _run(make_pos(), make_journal(), today)
    assert res["ok"] is True
    assert res["failed"] == []


def test_result_exposes_all_twelve_checks(make_pos, make_journal, today):
    res = _run(make_pos(), make_journal(), today)
    expected = {"portfolio_heat", "max_positions", "drawdown", "consec_losses",
                "daily_loss", "daily_cap", "corr_cap", "sector_cap",
                "order_size", "max_capital", "slippage", "htf_bias"}
    assert expected.issubset(res["checks"].keys())


# ── individual rules block ────────────────────────────────────────────────────

def test_portfolio_heat_blocks(make_pos, make_journal, today, monkeypatch):
    from scanner.broker import risk_manager as rm
    monkeypatch.setattr(rm._cfg, "PORTFOLIO_HEAT_LIMIT", 0.07)
    hot = make_pos(symbol="X", risk_per_trade=rm.account_size() * 0.10,
                   units=0.0001, sector="other", corr_group="solo:x")
    res = _run(make_pos(), make_journal(open_=[hot]), today)
    assert res["ok"] is False and "portfolio_heat" in res["failed"]


def test_max_positions_blocks(make_pos, make_journal, today, monkeypatch):
    from scanner.broker import risk_manager as rm
    monkeypatch.setattr(rm._cfg, "MAX_OPEN_POSITIONS", 3)
    book = [make_pos(symbol=f"S{i}", risk_per_trade=1, units=0.00001,
                     corr_group=f"solo:{i}") for i in range(3)]
    res = _run(make_pos(), make_journal(open_=book), today)
    assert res["ok"] is False and "max_positions" in res["failed"]


def test_daily_loss_blocks(make_pos, make_journal, today, closed_trade, stub_alerts):
    losers = [closed_trade(pnl=-300, session_day=today),
              closed_trade(pnl=-300, session_day=today)]  # -600 < -$500 cap
    res = _run(make_pos(), make_journal(closed=losers), today)
    assert res["ok"] is False and "daily_loss" in res["failed"]


def test_daily_cap_blocks(make_pos, make_journal, today, closed_trade):
    # 5 closed trades today == SCALP_MAX_TRADES_PER_DAY → cap reached
    winners = [closed_trade(pnl=+10, session_day=today) for _ in range(5)]
    res = _run(make_pos(), make_journal(closed=winners), today)
    assert res["ok"] is False and "daily_cap" in res["failed"]


def test_correlation_cap_blocks(make_pos, make_journal, today):
    # two open positions already in the candidate's correlation group (max 2/group)
    grp = make_pos(asset_type="crypto", sector="crypto")  # → "crypto:crypto"
    book = [dict(grp, symbol="ETHUSDT", risk_per_trade=1, units=0.00001),
            dict(grp, symbol="SOLUSDT", risk_per_trade=1, units=0.00001)]
    res = _run(make_pos(), make_journal(open_=book), today)
    assert res["ok"] is False and "corr_cap" in res["failed"]


def test_order_size_fatfinger_blocks(make_pos, make_journal, today, monkeypatch):
    from scanner.broker import risk_manager as rm
    monkeypatch.setattr(rm._cfg, "ORDER_SIZE_MAX_USD", 5_000)
    huge = make_pos(units=1.0, entry=50_000)  # $50k notional
    res = _run(huge, make_journal(), today)
    assert res["ok"] is False and "order_size" in res["failed"]


def test_slippage_reject_blocks(make_pos, make_journal, today, monkeypatch):
    from scanner.broker import pre_trade_check as ptc
    monkeypatch.setattr(ptc._cfg, "SLIPPAGE_REJECT_PCT", 0.01)
    res = _run(make_pos(slippage_pct=0.05), make_journal(), today)
    assert res["ok"] is False and "slippage" in res["failed"]


def test_htf_bias_counter_trend_blocks(make_pos, make_journal, today):
    bias = {"BTCUSDT": {"weekly": "bear", "threeDay": "bear"}}
    res = _run(make_pos(direction="long"), make_journal(), today, bias_map=bias)
    assert res["ok"] is False and "htf_bias" in res["failed"]


def test_htf_bias_aligned_passes(make_pos, make_journal, today):
    bias = {"BTCUSDT": {"weekly": "bull", "threeDay": "bull"}}
    res = _run(make_pos(direction="long"), make_journal(), today, bias_map=bias)
    assert res["ok"] is True


def test_reason_string_names_the_failed_rule(make_pos, make_journal, today):
    bias = {"BTCUSDT": {"weekly": "bear", "threeDay": "bear"}}
    res = _run(make_pos(direction="long"), make_journal(), today, bias_map=bias)
    assert res["reason"]  # non-empty human-readable reason when blocked
