"""Fill-model honesty — the pins Phase 6 didn't cover (2026-07-21, list #4).

The bot book decides iterate-vs-scale at ~30 closed trades. If paper fills are
even slightly optimistic, that decision is made on inflated expectancy — the
record stays intact but starts lying about what it MEANS. Phase 6 pinned
gap-through-stop, TP-at-limit and cost-drag; this file pins the rest of the
honesty surface:

  * the PRODUCTION cost model stays ON (a config flip to gross-of-costs must
    fail CI, not silently flatter every future trade),
  * entry slippage is measured with the right SIGN on both sides,
  * partial-TP-then-stop arithmetic can't double-book,
  * time-stops and manual closes are MARKET exits (pay slippage),
  * the runner applies costs END-TO-END (not just when _mark is called
    directly with costs passed in).

Tests only — no behaviour changes. If one of these fails, the fill model
changed and the sample-in-progress is no longer comparable with itself.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scanner import config, vivek_journal as vj
from scanner.broker import vivek_run as vr

pytestmark = pytest.mark.risk


# ── shared shapes (mirrors test_vivek_journal / test_vivek_run conventions) ────

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


def _decide_plan(**kw):
    """A vivek_bot.decide()-shaped plan, the input _ticket_to_position sees."""
    p = {"symbol": "BHP", "name": "BHP", "sector": "", "direction": "long",
         "grade": "A+", "entry_type": "reclaim", "entry_type_label": "Reclaim",
         "timeframe": "1D", "entry": 100.0, "stop": 96.0,
         "tp1": 106.0, "tp2": 112.0, "tp3": 120.0, "scale": [0.25, 0.50, 0.15],
         "trigger_bar": None, "units": 10.0, "notional": 1000.0,
         "leverage": 1.0, "leverage_target": 5, "risk_pct": 0.25, "risk_usd": 25.0}
    p.update(kw)
    return p


# ── 1. the production record is NET of costs — pinned at the config level ──────

def test_pin_production_cost_model_is_on():
    """VIVEK_COSTS_ENABLED=False (or zero bps) would make every future trade
    gross-of-costs — silently better than reality. The track record is NET;
    flipping that is a rule change and must be a loud, deliberate one."""
    assert config.VIVEK_COSTS_ENABLED is True
    for market in ("asx", "nasdaq", "crypto"):
        costs = vj.costs_for(market)
        assert costs is not None, f"cost model OFF for {market}"
        slip, comm = costs
        assert slip > 0, f"zero slippage modelled for {market}"
        assert comm > 0, f"zero commission modelled for {market}"


# ── 2. entry slippage is measured, sign-correct on both sides ──────────────────

def test_pin_fill_slip_bps_positive_means_worse_on_both_sides():
    """fill_slip_bps > 0 must ALWAYS mean 'the fill was worse than the
    signal'. A silent sign flip on the short side would make bad fills read
    as good ones in every slippage review."""
    day = "2024-01-02"
    # Long filled ABOVE the 100 signal → worse → positive.
    snap = vr._ticket_to_position({"plan": _decide_plan()}, 101.0, "asx", day)
    assert snap is not None
    assert snap["signal_entry"] == 100.0
    assert snap["fill_slip_bps"] == pytest.approx(100.0, abs=0.1)
    # Long filled BELOW the signal → better → negative.
    snap = vr._ticket_to_position({"plan": _decide_plan()}, 99.5, "asx", day)
    assert snap["fill_slip_bps"] == pytest.approx(-50.0, abs=0.1)
    # Short filled BELOW the 100 signal (sold lower) → worse → positive.
    short = _decide_plan(direction="short", stop=104.0, tp1=94.0, tp2=88.0,
                         tp3=80.0, scale=[0.50, 0.25, 0.15])
    snap = vr._ticket_to_position({"plan": short}, 99.0, "asx", day)
    assert snap is not None
    assert snap["fill_slip_bps"] == pytest.approx(100.0, abs=0.1)
    # And the fill seeds the mark-sanity reference (Phase 6 P1 contract).
    assert snap["last_mark"] == snap["entry"]


def test_pin_dont_chase_wrong_side_of_stop_both_directions():
    """An entry on the wrong side of its stop would be born dead (instant
    stop-out next mark) and book a guaranteed -R into the record."""
    row = {"symbol": "X", "name": "X", "sector": "", "dir": "LONG",
           "grade": "A+", "entry_types": ["reclaim"]}
    jplan = {"stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
             "scale": [0.25, 0.50, 0.15], "entry_trigger": "reclaim",
             "armed": True, "trigger_bar": None}
    assert vj._snapshot(row, "1D", jplan, "asx", 95.9, "2024-01-02") is None
    assert vj._snapshot(row, "1D", jplan, "asx", 96.0, "2024-01-02") is None
    srow = {**row, "dir": "SHORT"}
    sjplan = {**jplan, "stop": 104.0, "tp1": 94.0, "tp2": 88.0, "tp3": 80.0,
              "scale": [0.50, 0.25, 0.15]}
    assert vj._snapshot(srow, "1D", sjplan, "asx", 104.0, "2024-01-02") is None
    assert vj._snapshot(srow, "1D", sjplan, "asx", 104.2, "2024-01-02") is None


# ── 3. partial-TP then stop: composite arithmetic can't double-book ────────────

def test_pin_tp1_partial_then_gap_stop_composite_arithmetic():
    """Book 25% at TP1(106), stop trails to BE(100), then a gap to 88 closes
    the remaining 75% at the OBSERVED 88. Gross must be exactly
    0.25*1.5R + 0.75*(-3R) = -1.875R — booked fractions must sum to 1.0 and
    the runner leg must price at the gap, never at the trailed stop."""
    costs = (0.001, 0.0005)
    t = _trade()
    vj._mark(t, 107.0, "2024-01-03", costs)          # TP1 books 25% @106, SL→BE
    assert t["status"] == "open" and t["tp1_hit"]
    assert t["stop"] == pytest.approx(100.0)         # trailed to break-even
    vj._mark(t, 88.0, "2024-01-04", costs)           # gap through the BE stop
    assert t["status"] == "closed"
    assert t["exit_price"] == 88.0                   # observed price, not 100
    assert t["booked_pct"] == pytest.approx(1.0)
    assert t["gross_r"] == pytest.approx(
        0.25 * (106 - 100) / 4 + 0.75 * (88 - 100) / 4, abs=1e-6)   # -1.875R
    assert t["cost_r"] > 0
    assert t["realized_r"] == pytest.approx(t["gross_r"] - t["cost_r"], abs=1e-9)


# ── 4. time-stops and manual closes are MARKET exits ───────────────────────────

def test_pin_time_stop_books_observed_price_and_is_closed_shape():
    """A time-stop is a market fill at the observed price — same honesty rules
    as a stop: no booking at a kinder level, costs applied, audit trail set."""
    costs = (0.001, 0.0005)
    t = _trade()
    vr._close_time_stop(t, 97.0, "2024-01-10", costs)
    assert t["status"] == "closed" and t["exit_reason"] == "time"
    assert t["exit_price"] == 97.0
    assert t["booked_pct"] == pytest.approx(1.0)
    assert t["gross_r"] == pytest.approx((97 - 100) / 4, abs=1e-6)
    assert t["cost_r"] > 0
    assert t["realized_r"] == pytest.approx(t["gross_r"] - t["cost_r"], abs=1e-9)
    assert t["hold_days"] == 8


def test_pin_time_and_manual_exits_pay_slippage_like_stops():
    """_cost_r charges slippage on MARKET exits only. 'stop', 'time' and
    'manual' are all market fills and must cost the same; a resting TP limit
    pays commission only. If 'manual' or 'time' ever slipped out of the
    market-exit set, hand closes and time-stops would book flattered nets."""
    slip, comm = 0.001, 0.0005
    base = _trade()
    def cost(reason):
        tr = {**base, "exits": [{"reason": reason, "price": 97.0, "pct": 1.0}]}
        return vj._cost_r(tr, slip, comm)
    assert cost("manual") == pytest.approx(cost("stop"), abs=1e-12)
    assert cost("time") == pytest.approx(cost("stop"), abs=1e-12)
    assert cost("tp1") < cost("stop")                # limit pays no slippage


# ── 5. the RUNNER applies costs end-to-end (production path) ───────────────────

def _frame(last_close):
    idx = pd.date_range(end="2024-01-02", periods=5, freq="D")
    return pd.DataFrame({"Open": last_close, "High": last_close, "Low": last_close,
                         "Close": last_close, "Volume": 1e6}, index=idx)


def _aest(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("Australia/Sydney"))


def _row():
    return {"symbol": "BHP", "name": "BHP", "sector": "", "grade": "A+",
            "dir": "LONG", "entry_types": ["reclaim"],
            "plans": {"1D": {"armed": True, "entry_trigger": "reclaim",
                             "trigger_bar": "2024-01-01", "entry": 100.0,
                             "stop": 96.0, "tp1": 106.0, "tp2": 112.0,
                             "tp3": 120.0, "rr": 3.0,
                             "scale": config.VIVEK_TP_SCALE_LONG}}}


def test_pin_runner_applies_costs_and_gap_pricing_end_to_end(tmp_path, monkeypatch):
    """Through run_market itself (production config, costs untouched): a fill
    at 101 that gaps to 88 must close at 88 with cost_r > 0 and
    realized_r == gross_r - cost_r. Guards against the runner ever dropping
    the costs= argument and quietly going gross-of-costs."""
    monkeypatch.setattr(vr, "BOOK_DIR", tmp_path)
    monkeypatch.setattr(vr, "BOOK_FILE", tmp_path / "vivek_bot_book.json")
    monkeypatch.setattr(vr, "UNASSIGNED_FILE", tmp_path / "vivek_bot_book.unassigned.json")
    monkeypatch.setattr(vr, "PUBLIC_FILE", tmp_path / "public_book.json")
    monkeypatch.setattr(config, "VIVEK_BOT_ENABLED", True)
    monkeypatch.setattr(config, "VIVEK_BOT_DRY_RUN", False)
    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)}, uni,
                  now=_aest(2024, 1, 2, 11, 0))
    bk = vr.run_market("asx", [], {"BHP.AX": _frame(88.0)}, uni,
                       now=_aest(2024, 1, 3, 11, 0))
    assert len(bk["closed"]) == 1
    t = bk["closed"][0]
    assert t["exit_price"] == 88.0                          # gap price, not 96
    assert t["signal_entry"] == 100.0                       # slippage measured
    assert t["fill_slip_bps"] == pytest.approx(100.0, abs=0.1)
    assert t["gross_r"] == pytest.approx((88 - 101) / 5, abs=1e-6)   # -2.6R
    assert t["cost_r"] > 0                                  # costs applied by the RUNNER
    assert t["realized_r"] == pytest.approx(t["gross_r"] - t["cost_r"], abs=1e-9)
