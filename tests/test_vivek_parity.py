"""Parity backtest + variant grid + level_tf audit stamp."""

from __future__ import annotations

import json
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from scanner import config
from scanner import vivek_parity as parity
from scanner.broker import vivek_run
from scanner.vivek_journal import _snapshot

pytestmark = pytest.mark.risk


def _ohlc(n=400, seed=2, start="2019-01-01"):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="B")
    px = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
    return pd.DataFrame(
        {"Open": px, "High": px * 1.015, "Low": px * 0.985, "Close": px, "Volume": 1e6},
        index=idx,
    )


def test_baseline_rules_read_live_hold_days():
    r = parity.baseline_rules()
    assert r.resolved_hold() == int(config.VIVEK_BOT_MAX_HOLD_DAYS)


def test_variant_grid_has_v1_v2_v3_v4():
    names = [v.name for v in parity.variant_grid()]
    assert any(n.startswith("V1_") for n in names)
    assert any(n.startswith("V2_") for n in names)
    assert any(n.startswith("V3_") for n in names)
    assert any(n.startswith("V4_") for n in names)


def test_time_stop_closes_pre_tp1_after_max_hold():
    """A flat trade past MAX_HOLD must exit with reason 'time', not ride forever."""
    row = {"symbol": "X", "name": "X", "sector": "sec", "dir": "LONG",
           "grade": "A+", "entry_types": ["reclaim"], "level_tf": "weekly"}
    plan = {"armed": True, "entry_trigger": "reclaim", "stop": 90.0,
            "tp1": 130.0, "tp2": 150.0, "tp3": 180.0, "scale": [0.25, 0.5, 0.15]}
    tr = _snapshot(row, "1W", plan, "asx", 100.0, "2024-01-02")
    tr["market"] = "asx"
    tr["level_tf"] = "weekly"
    tr["mfe_r_at"] = {}
    rules = parity.ParityRules(name="t", max_hold_days=28)
    # Walk 30 flat days — never hits TP1 (130) or stop (90)
    day0 = pd.Timestamp("2024-01-02")
    for i in range(1, 35):
        day = (day0 + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        parity._manage_parity_bar(tr, 105, 95, 100, day, None, False, rules)
        if tr["status"] == "closed":
            break
    assert tr["status"] == "closed"
    assert tr["exit_reason"] == "time"
    assert (tr.get("hold_days") or 0) > 28


def test_early_cut_fires_when_mfe_below_floor():
    row = {"symbol": "X", "name": "X", "sector": "sec", "dir": "LONG",
           "grade": "A+", "entry_types": ["reclaim"], "level_tf": "weekly"}
    plan = {"armed": True, "entry_trigger": "reclaim", "stop": 90.0,
            "tp1": 130.0, "tp2": 150.0, "tp3": 180.0, "scale": [0.25, 0.5, 0.15]}
    tr = _snapshot(row, "1W", plan, "nasdaq", 100.0, "2024-01-02")
    tr["mfe_r_at"] = {}
    rules = parity.ParityRules(name="t", early_cut_day=10, early_cut_mfe=0.5,
                               max_hold_days=28)
    day0 = pd.Timestamp("2024-01-02")
    for i in range(1, 20):
        day = (day0 + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        # tiny upside — mfe stays well under 0.5R (risk=10, high=101 → 0.1R)
        parity._manage_parity_bar(tr, 101, 99, 100, day, None, False, rules)
        if tr["status"] == "closed":
            break
    assert tr["status"] == "closed"
    assert tr["exit_reason"] == "early_cut"


def test_mfe_checkpoints_stamp_at_day_boundaries():
    row = {"symbol": "X", "name": "X", "sector": "", "dir": "LONG",
           "grade": "A+", "entry_types": ["reclaim"]}
    plan = {"armed": True, "entry_trigger": "reclaim", "stop": 90.0,
            "tp1": 200.0, "tp2": 220.0, "tp3": 250.0, "scale": [0.25, 0.5, 0.15]}
    tr = _snapshot(row, "1D", plan, "asx", 100.0, "2024-01-01")
    tr["mfe_r_at"] = {}
    rules = parity.ParityRules(name="t", max_hold_days=0)  # off
    day0 = pd.Timestamp("2024-01-01")
    for i in range(1, 16):
        day = (day0 + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        # push high so mfe grows
        hi = 100 + i
        parity._manage_parity_bar(tr, hi, 99, 100, day, None, False, rules)
    assert "5" in tr["mfe_r_at"]
    assert "10" in tr["mfe_r_at"]
    assert "14" in tr["mfe_r_at"]


def test_slot_month_stats_basic():
    trades = [
        {"entry_date": "2024-01-01", "exit_date": "2024-01-31", "realized_r": 1.0},
        {"entry_date": "2024-01-01", "exit_date": "2024-01-31", "realized_r": 1.0},
    ]
    sm, rpsm = parity._slot_month_stats(trades)
    # 2 slots * 30 days ≈ 1.97 slot-months; 2R / that ≈ 1.0
    assert sm > 1.5
    assert rpsm is not None and rpsm > 0.8


def test_variant_pass_requires_both_markets_and_halves():
    # Build a baseline where ASX is weak and a "variant" that only fixes NASDAQ
    base = []
    var = []
    for i, mk in enumerate(["asx"] * 10 + ["nasdaq"] * 10):
        d0 = f"2023-{(i % 12) + 1:02d}-01"
        d1 = f"2023-{(i % 12) + 1:02d}-20"
        base.append({"market": mk, "entry_date": d0, "exit_date": d1,
                     "realized_r": -0.5 if mk == "asx" else 0.5,
                     "symbol": f"S{i}", "grade": "A+", "entry_type": "reclaim",
                     "direction": "long", "timeframe": "1W"})
        var.append({**base[-1],
                    "realized_r": -0.5 if mk == "asx" else 1.5})  # only nasdaq improves
    v = parity.variant_passes(base, var)
    assert v["pass"] is False
    assert v["checks"]["market:asx"]["pass"] is False


def test_portfolio_sim_parity_global_cap():
    trades = []
    for i in range(40):
        trades.append({
            "symbol": f"S{i}", "market": "asx" if i < 20 else "nasdaq",
            "grade": "A+", "entry_type": "reclaim", "direction": "long",
            "timeframe": "1W", "sector": f"sec{i}",
            "entry_date": "2024-01-02", "exit_date": "2024-06-01",
            "exit_reason": "time", "realized_r": 0.1,
            "entry": 100, "stop": 95, "risk": 5,
        })
    r = parity.portfolio_sim_parity(trades, max_total=30)
    assert r["taken"] == 30
    assert r["skipped"].get("book_full", 0) >= 10


def test_ticket_stamps_level_tf_audit_only():
    out = {
        "plan": {
            "symbol": "AAA", "name": "AAA", "sector": "Materials",
            "direction": "long", "timeframe": "1W", "entry_type": "reclaim",
            "entry_type_label": "Reclaim", "grade": "A+",
            "entry": 100.0, "stop": 95.0, "tp1": 110.0, "tp2": 120.0, "tp3": 130.0,
            "scale": [0.25, 0.5, 0.15], "units": 10, "notional": 1000,
            "leverage": 1.0, "leverage_target": 5, "risk_pct": 0.35, "risk_usd": 50,
            "rr": 4.0, "review": [], "sizing_mode": "fixed_notional",
        }
    }
    pos = vivek_run._ticket_to_position(out, 100.0, "asx", "2024-06-01",
                                        level_tf="weekly")
    assert pos is not None
    assert pos["level_tf"] == "weekly"
    # No level_tf arg and none on plan → field absent (not guessed)
    pos2 = vivek_run._ticket_to_position(out, 100.0, "asx", "2024-06-01")
    assert pos2 is not None
    assert "level_tf" not in pos2 or pos2.get("level_tf") in (None, "")


def test_replay_symbol_parity_smoke_does_not_crash():
    df = _ohlc()
    trades = parity.replay_symbol_parity(df, "asx", "RND", "Random", "Materials")
    assert isinstance(trades, list)
    for t in trades:
        assert t["status"] == "closed"
        assert t.get("grade") == "A+"
        assert t.get("direction") == "long"
        assert "mfe_r_at" in t


def test_frozen_fingerprint_detects_r_move():
    from scripts import backfill_level_tf as bf
    pos = {"id": "X", "symbol": "X", "market": "asx", "direction": "long",
           "entry": 1, "stop": 0.9, "risk": 0.1, "realized_r": 1.0,
           "entry_date": "2024-01-01", "status": "open"}
    a = bf.frozen_fingerprint(pos)
    pos2 = dict(pos)
    pos2["level_tf"] = "weekly"          # allowed write — fingerprint ignores it
    assert bf.frozen_fingerprint(pos2) == a
    pos3 = dict(pos)
    pos3["realized_r"] = 0.0             # frozen — must differ
    assert bf.frozen_fingerprint(pos3) != a


def test_exclude_map_and_taken_flag_schema():
    """OOS plumbing: exclusion loader + taken stamp on published trades."""
    from scanner.vivek_parity import load_exclude_map, build_parity_report, baseline_rules
    import tempfile, json, pathlib
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "ex.json"
        p.write_text(json.dumps({"by_market": {"asx": ["AAA", "bbb"]}}), encoding="utf-8")
        m = load_exclude_map(p)
        assert m["asx"] == {"AAA", "BBB"}
    trades = [
        {"symbol": "A", "market": "asx", "grade": "A+", "entry_type": "reclaim",
         "direction": "long", "timeframe": "1W", "sector": "s1",
         "entry_date": "2024-01-02", "exit_date": "2024-02-01",
         "exit_reason": "time", "realized_r": 0.1, "entry": 10, "stop": 9, "risk": 1},
        {"symbol": "B", "market": "asx", "grade": "A+", "entry_type": "reclaim",
         "direction": "long", "timeframe": "1W", "sector": "s2",
         "entry_date": "2024-01-02", "exit_date": "2024-02-01",
         "exit_reason": "time", "realized_r": -0.1, "entry": 10, "stop": 9, "risk": 1},
    ]
    rep = build_parity_report(trades, {"asx": {"symbols": 2}}, {"mode": "t"}, {})
    assert all("taken" in t for t in rep["trades"])
    assert all("close_r_at" in t for t in rep["trades"])
    assert sum(1 for t in rep["trades"] if t["taken"]) == rep["baseline"]["portfolio"]["taken"]


def test_close_r_checkpoint_stamps_with_close_price():
    from scanner.vivek_parity import _stamp_mfe_checkpoints
    tr = {"direction": "long", "entry": 100.0, "risk": 10.0, "mfe_r": 0.3,
          "mfe_r_at": {}, "close_r_at": {}}
    _stamp_mfe_checkpoints(tr, held=10, close=103.0)
    assert "10" in tr["mfe_r_at"]
    assert tr["close_r_at"]["10"] == pytest.approx(0.3)


def test_config_parity_constants_exist():
    assert config.VIVEK_PARITY_OUT_FILE.endswith("vivek_backtest_parity.json")
    assert config.VIVEK_PARITY_MFE_DAYS
    assert config.VIVEK_PARITY_PASS_MARKETS == ("asx", "nasdaq")
