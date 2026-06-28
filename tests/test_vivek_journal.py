"""VIVEK paper journal — intraday entry/exit pricing + market-hours gating.

Trades open at the delayed intraday price during the session and mark-to-market
against the observed price each scan (no intrabar look-ahead)."""

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scanner import config, vivek_journal as vj

pytestmark = pytest.mark.risk


def _trade(**kw):
    t = {"id": "X:long:1D:2024-01-02", "symbol": "X", "name": "X", "sector": "",
         "market": "asx", "direction": "long", "grade": "A+", "entry_type": "reclaim",
         "timeframe": "1D", "entry": 100.0, "stop": 96.0,
         "tp1": 106.0, "tp2": 112.0, "tp3": 120.0, "scale": [0.25, 0.50, 0.15],
         "risk": 4.0, "rr": 3.0, "entry_date": "2024-01-02", "status": "open",
         "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
         "booked_pct": 0.0, "realized_r": 0.0, "exits": [], "mae": 100.0,
         "mfe": 100.0, "mae_r": 0.0, "mfe_r": 0.0}
    t.update(kw)
    return t


# ── mark-to-market on observed intraday prices ──────────────────────────────────

def test_winning_long_scales_out_over_observed_prices():
    t = _trade()
    vj._mark(t, 107, "2024-01-03")   # TP1 → book 25% @106, SL→BE
    vj._mark(t, 113, "2024-01-04")   # TP2 → book 50% @112, SL→TP1(106)
    vj._mark(t, 121, "2024-01-05")   # TP3 → book 15% @120
    assert t["status"] == "open" and t["tp3_hit"] and t["booked_pct"] == pytest.approx(0.90)
    vj._mark(t, 105, "2024-01-08")   # ≤ trailed SL(106) → runner out @105 observed
    assert t["status"] == "closed" and t["exit_reason"] == "target"
    # 0.25*1.5 + 0.5*3.0 + 0.15*5.0 + 0.10*(105-100)/4
    assert t["realized_r"] == pytest.approx(2.75, abs=1e-3)
    assert t["mfe_r"] == pytest.approx((121 - 100) / 4, abs=1e-3)
    assert t["hold_days"] == 6


def test_losing_long_stops_at_minus_one_r():
    t = _trade()
    vj._mark(t, 96, "2024-01-03")    # exactly the stop
    assert t["status"] == "closed" and t["exit_reason"] == "stop"
    assert t["realized_r"] == pytest.approx(-1.0, abs=1e-9)


def test_overnight_gap_fills_at_the_observed_price():
    t = _trade()
    vj._mark(t, 92, "2024-01-03")    # gapped below the 96 stop → fills at 92
    assert t["status"] == "closed"
    assert t["realized_r"] == pytest.approx((92 - 100) / 4, abs=1e-3)   # -2R, worse than -1


def test_short_mirror():
    t = _trade(direction="short", entry=100, stop=104, tp1=94, tp2=88, tp3=80,
               scale=[0.50, 0.25, 0.15], id="X:short:1D:2024-01-02")
    vj._mark(t, 93, "2024-01-03")
    vj._mark(t, 87, "2024-01-04")
    vj._mark(t, 79, "2024-01-05")
    vj._mark(t, 95, "2024-01-08")    # ≥ trailed stop → runner out
    assert t["status"] == "closed" and t["realized_r"] > 0 and t["tp3_hit"]


# ── execution-cost model (fees + slippage) ──────────────────────────────────────

def test_costs_for_respects_enabled_flag_and_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(config, "VIVEK_COSTS_ENABLED", False)
    assert vj.costs_for("asx") is None
    monkeypatch.setattr(config, "VIVEK_COSTS_ENABLED", True)
    slip, comm = vj.costs_for("crypto")
    assert slip == pytest.approx(config.VIVEK_SLIPPAGE_BPS["crypto"] / 10_000)
    assert comm == pytest.approx(config.VIVEK_COMMISSION_BPS["crypto"] / 10_000)
    s2, _ = vj.costs_for("unlisted_market")             # unknown key → default backstop
    assert s2 == pytest.approx(config.VIVEK_SLIPPAGE_BPS["default"] / 10_000)


def test_cost_r_charges_slippage_only_on_market_exits():
    slip, comm = 0.001, 0.0005
    base = _trade(entry=100.0, risk=4.0)
    via_tp = {**base, "exits": [{"reason": "tp1", "price": 106.0, "pct": 1.0}]}
    via_stop = {**base, "exits": [{"reason": "stop", "price": 106.0, "pct": 1.0}]}
    c_tp = vj._cost_r(via_tp, slip, comm)
    c_stop = vj._cost_r(via_stop, slip, comm)
    # entry always pays slip+comm on full size; a TP limit pays commission only.
    assert c_tp == pytest.approx((100 * (slip + comm) + 106 * comm) / 4, abs=1e-9)
    assert c_stop > c_tp                               # the stop also pays slippage


def test_costs_make_realized_r_net_of_gross():
    costs = (0.001, 0.0005)
    t = _trade()
    vj._mark(t, 107, "2024-01-03", costs)   # TP1
    vj._mark(t, 113, "2024-01-04", costs)   # TP2
    vj._mark(t, 121, "2024-01-05", costs)   # TP3
    vj._mark(t, 105, "2024-01-08", costs)   # trail out
    assert t["status"] == "closed"
    assert t["gross_r"] == pytest.approx(2.75, abs=1e-3)        # same gross as the cost-free case
    assert t["cost_r"] > 0
    assert t["realized_r"] == pytest.approx(t["gross_r"] - t["cost_r"], abs=1e-9)
    assert t["realized_r"] < t["gross_r"]


# ── intraday entry (don't-chase) ────────────────────────────────────────────────

def _plan(**kw):
    p = {"armed": True, "entry_trigger": "reclaim", "trigger_bar": "2024-01-01",
         "stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
         "scale": [0.25, 0.50, 0.15]}
    p.update(kw)
    return p


def _row(**kw):
    r = {"symbol": "X", "name": "X", "sector": "", "dir": "LONG", "grade": "A+",
         "entry_types": ["reclaim"]}
    r.update(kw)
    return r


def test_entry_uses_the_current_price_not_the_plan():
    snap = vj._snapshot(_row(), "1D", _plan(), "asx", entry_price=101.0, day="2024-01-02")
    assert snap is not None
    assert snap["entry"] == 101.0                    # the live intraday price, not a trigger close
    assert snap["risk"] == pytest.approx(5.0)        # 101 − 96
    assert snap["entry_date"] == "2024-01-02"
    assert snap["trigger_bar"] == "2024-01-01"       # kept for reference only


def test_dont_chase_a_move_already_past_tp1():
    assert vj._snapshot(_row(), "1D", _plan(), "asx", entry_price=107.0, day="d") is None  # ≥ TP1
    assert vj._snapshot(_row(), "1D", _plan(), "asx", entry_price=95.0, day="d") is None   # ≤ stop


# ── market-hours gate ───────────────────────────────────────────────────────────

def _aest(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("Australia/Sydney"))


def test_market_open_window_is_delay_adjusted():
    # ASX 10:00–16:00 + 15m delay → 10:15–16:15, weekdays only.
    assert vj.market_open("asx", _aest(2024, 1, 2, 11, 0)) is True       # Tue mid-session
    assert vj.market_open("asx", _aest(2024, 1, 2, 10, 5)) is False      # before 10:15
    assert vj.market_open("asx", _aest(2024, 1, 2, 16, 10)) is True      # still inside (≤16:15)
    assert vj.market_open("asx", _aest(2024, 1, 6, 11, 0)) is False      # Saturday
    assert vj.market_open("crypto", _aest(2024, 1, 6, 3, 0)) is True     # 24/7


# ── update(): gating, entry, idempotency, resolution ────────────────────────────

def _frame(last_close):
    idx = pd.date_range(end="2024-01-02", periods=5, freq="D")
    return pd.DataFrame({"Open": last_close, "High": last_close, "Low": last_close,
                         "Close": last_close, "Volume": 1e6}, index=idx)


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(vj, "JOURNAL_FILE", tmp_path / "vivek_journal.json")
    monkeypatch.setattr(vj, "PUBLIC_FILE", tmp_path / "public_vivek_journal.json")


def test_update_does_not_open_outside_market_hours(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    rows = [_row(plans={"1D": _plan()})]
    uni = [{"symbol": "X", "yf": "X.AX"}]
    j = vj.update("asx", rows, {"X.AX": _frame(101.0)}, uni, now=_aest(2024, 1, 2, 9, 0))
    assert len(j["open"]) == 0                        # 09:00 < 10:15 → nothing opens


def test_update_opens_at_intraday_price_in_session_and_is_idempotent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    rows = [_row(plans={"1D": _plan()})]
    uni = [{"symbol": "X", "yf": "X.AX"}]
    when = _aest(2024, 1, 2, 11, 0)
    j = vj.update("asx", rows, {"X.AX": _frame(101.0)}, uni, now=when)
    assert len(j["open"]) == 1 and j["open"][0]["entry"] == 101.0
    j = vj.update("asx", rows, {"X.AX": _frame(101.0)}, uni, now=when)   # same day re-scan
    assert len(j["open"]) == 1                        # no duplicate


def test_update_marks_open_trade_to_observed_price(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    rows = [_row(plans={"1D": _plan()})]
    uni = [{"symbol": "X", "yf": "X.AX"}]
    vj.update("asx", rows, {"X.AX": _frame(101.0)}, uni, now=_aest(2024, 1, 2, 11, 0))
    # next session, price has fallen through the stop → trade closes at the observed price
    j = vj.update("asx", [], {"X.AX": _frame(95.0)}, uni, now=_aest(2024, 1, 3, 11, 0))
    assert len(j["open"]) == 0 and len(j["closed"]) == 1
    assert j["closed"][0]["status"] == "closed" and j["closed"][0]["realized_r"] < 0
    assert j["expectancy"]["overall"]["n"] == 1


def test_expectancy_splits_by_grade_entry_type_timeframe():
    closed = [
        _trade(grade="A+", entry_type="reclaim", timeframe="1D", realized_r=2.0, hold_days=5, mae_r=-0.3, mfe_r=3.0),
        _trade(grade="A", entry_type="break", timeframe="1W", realized_r=-1.0, hold_days=3, mae_r=-1.2, mfe_r=0.4),
    ]
    e = vj.expectancy(closed)
    assert e["overall"]["n"] == 2 and e["overall"]["expectancy_r"] == pytest.approx(0.5)
    assert e["by_grade"]["A+"]["expectancy_r"] == pytest.approx(2.0)
    assert e["by_entry_type"]["reclaim"]["n"] == 1
    assert e["by_timeframe"]["1D"]["n"] == 1 and e["by_timeframe"]["4H"]["n"] == 0
