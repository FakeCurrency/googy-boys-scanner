"""VIVEK walk-forward backtester — management lifecycle, metrics, replay smoke."""

import numpy as np
import pandas as pd
import pytest

from scanner import vivek_backtest as bt
from scanner.vivek_journal import _snapshot

pytestmark = pytest.mark.risk


def _t(r, d, **kw):
    base = {"realized_r": r, "exit_date": d, "entry_type": "reclaim", "timeframe": "1D",
            "market": "asx", "direction": "long", "entry": 100.0, "stop": 96.0, "grade": "A+"}
    base.update(kw)
    return base


def test_metrics_winrate_profit_factor_drawdown():
    trades = [_t(2.0, "2024-01-05"), _t(-1.0, "2024-01-06"),
              _t(1.5, "2024-01-07"), _t(-1.0, "2024-01-08")]
    m = bt._metrics(trades)
    assert m["n"] == 4
    assert m["win_rate"] == 50.0
    assert m["profit_factor"] == pytest.approx(1.75)      # (2 + 1.5) / (1 + 1)
    assert m["total_r"] == pytest.approx(1.5)


def test_manage_bar_runs_the_5_0_rules_to_a_target_close():
    row = {"symbol": "X", "name": "X", "sector": "", "dir": "LONG",
           "grade": "A+", "entry_types": ["reclaim"]}
    plan = {"armed": True, "entry_trigger": "reclaim", "trigger_bar": "d",
            "stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0, "scale": [0.25, 0.5, 0.15]}
    tr = _snapshot(row, "1D", plan, "asx", 100.0, "2024-01-02")
    assert tr["entry"] == 100.0 and tr["risk"] == pytest.approx(4.0)

    bt._manage_bar(tr, 107, 99, 106, "2024-01-03", None, False)     # TP1
    assert tr["tp1_hit"] and tr["stop"] == pytest.approx(100.0)     # SL → break-even
    bt._manage_bar(tr, 121, 110, 120, "2024-01-04", None, False)    # TP2 + TP3
    assert tr["tp2_hit"] and tr["tp3_hit"] and tr["stop"] == pytest.approx(106.0)
    bt._manage_bar(tr, 108, 105, 106, "2024-01-05", None, True)     # trailed stop hit
    assert tr["status"] == "closed"
    assert tr["realized_r"] == pytest.approx(2.75, abs=1e-3)        # 0.25·1.5 + 0.5·3 + 0.15·5 + 0.10·1.5
    assert tr["exit_reason"] == "target"


def test_manage_bar_is_pessimistic_stop_before_target():
    # a bar whose range spans BOTH the stop and TP1 must resolve as the stop
    row = {"symbol": "X", "name": "X", "sector": "", "dir": "LONG",
           "grade": "A+", "entry_types": ["reclaim"]}
    plan = {"armed": True, "entry_trigger": "reclaim", "stop": 96.0,
            "tp1": 106.0, "tp2": 112.0, "tp3": 120.0, "scale": [0.25, 0.5, 0.15]}
    tr = _snapshot(row, "1D", plan, "asx", 100.0, "2024-01-02")
    bt._manage_bar(tr, 107, 95, 100, "2024-01-03", None, False)     # high≥TP1 AND low≤stop
    assert tr["status"] == "closed" and tr["exit_reason"] == "stop"
    assert tr["realized_r"] < 0


def test_replay_symbol_smoke_does_not_crash():
    np.random.seed(1)
    n = 400
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    px = 100 * np.cumprod(1 + np.random.normal(0, 0.012, n))
    df = pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99,
                       "Close": px, "Volume": 1e6}, index=idx)
    trades = bt.replay_symbol(df, "asx", "RND", "Random", "Materials")
    assert isinstance(trades, list)
    for t in trades:                                       # any trades must be well-formed
        assert t["status"] == "closed" and t["timeframe"] in ("1D", "1W")
        assert t.get("realized_r") is not None


# ── portfolio-level simulation (bot book rules applied chronologically) ──────

def _sim_trade(sym, entry_date, exit_date, r=1.0, sector="secA", **kw):
    t = {"symbol": sym, "market": "asx", "grade": "A+", "entry_type": "reclaim",
         "direction": "long", "timeframe": "1W", "sector": sector,
         "entry": 100, "stop": 96, "entry_date": entry_date, "exit_date": exit_date,
         "exit_reason": "target", "realized_r": r}
    t.update(kw)
    return t


def test_portfolio_sim_slot_cap():
    trades = [_sim_trade(f"S{i}", "2026-01-05", "2026-02-01", sector=f"sec{i}")
              for i in range(12)]
    r = bt.portfolio_sim(trades)
    assert r["taken"] == 10 and r["skipped"]["book_full"] == 2
    assert r["peak_open"] == 10
    assert r["eligible"]["n"] == 12 and r["portfolio"]["n"] == 10


def test_portfolio_sim_slots_free_after_exit():
    trades = [_sim_trade("AAA", "2026-01-05", "2026-01-20"),
              _sim_trade("BBB", "2026-01-25", "2026-02-10", sector="secB")]
    r = bt.portfolio_sim(trades)
    assert r["taken"] == 2 and not r["skipped"]


def test_portfolio_sim_one_per_symbol_and_sector_cap():
    trades = ([_sim_trade("AAA", "2026-01-05", "2026-03-01"),
               _sim_trade("AAA", "2026-01-12", "2026-03-01")] +      # dup while open
              [_sim_trade(f"M{i}", "2026-01-05", "2026-03-01", sector="materials")
               for i in range(4)])                                    # 4th materials blocked
    r = bt.portfolio_sim(trades)
    assert r["skipped"]["dup_symbol"] == 1
    assert r["skipped"]["sector_cap"] == 1


def test_portfolio_sim_cooldown_after_stop_out():
    trades = [_sim_trade("AAA", "2026-01-05", "2026-01-10", r=-1.0, exit_reason="stop"),
              _sim_trade("AAA", "2026-01-13", "2026-02-01"),          # 3d later — blocked
              _sim_trade("AAA", "2026-02-05", "2026-03-01")]          # past cooldown — ok
    r = bt.portfolio_sim(trades)
    assert r["skipped"]["cooldown"] == 1 and r["taken"] == 2


def test_portfolio_sim_filters_non_bot_trades():
    trades = [_sim_trade("AAA", "2026-01-05", "2026-02-01", grade="A"),
              _sim_trade("BBB", "2026-01-05", "2026-02-01", entry_type="retest"),
              _sim_trade("CCC", "2026-01-05", "2026-02-01", direction="short"),
              _sim_trade("DDD", "2026-01-05", "2026-02-01")]
    r = bt.portfolio_sim(trades)
    assert r["eligible"]["n"] == 1 and r["taken"] == 1


def test_portfolio_sim_legacy_trades_without_entry_date():
    r = bt.portfolio_sim([{"symbol": "AAA", "grade": "A+",
                                       "entry_type": "reclaim", "direction": "long",
                                       "market": "asx", "exit_date": "2026-01-10"}])
    assert "note" in r
