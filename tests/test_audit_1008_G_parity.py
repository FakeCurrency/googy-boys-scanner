"""Audit 2026-10-08, cluster G -- the parity replay (scanner/vivek_parity.py).

  #34  the "live" baseline admitted every level; the bot only sees weekly/3d
  #37  a signal the portfolio skipped kept occupying its symbol in the chain,
       so the next signal live would act on was never generated

The replay's engine calls are replaced by a scripted signal on chosen bars so
each test controls exactly which signals exist; everything downstream (fill
gates, management, the portfolio pass) is the shipped code.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner import config
from scanner import vivek_parity as parity


def _flat(n: int = 300) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    px = np.full(n, 100.0)
    return pd.DataFrame({"Open": px, "High": px + 0.5, "Low": px - 0.5,
                         "Close": px, "Volume": 1e6}, index=idx)


def _script(monkeypatch, bars: set[int], level: str = "weekly") -> None:
    """A 1W reclaim (in a cell, armed, 10% stop, far targets) on `bars` only."""
    plan = {"armed": True, "entry_trigger": "reclaim", "entry": 100.0, "stop": 90.0,
            "tp1": 130.0, "tp2": 150.0, "tp3": 180.0, "rr": 3.0, "scale": [0.25, 0.5, 0.15]}
    monkeypatch.setattr(parity, "_candidate_mask",
                        lambda df: np.array([i in bars for i in range(len(df))]))
    monkeypatch.setattr(parity.vivek, "evaluate", lambda df, *a, **k: {"level_tf": level})

    def build_row(sig, df_slice, symbol, name, sector):
        row = {"symbol": symbol, "name": name, "sector": sector, "dir": "LONG",
               "grade": "A+", "entry_types": ["reclaim"], "level_tf": sig["level_tf"]}
        return row, {"1W": dict(plan)}, "A+"

    monkeypatch.setattr(parity, "_build_row", build_row)


# ------------------------------------------------------------ #34 the level gate

def test_the_baseline_enforces_the_live_level_gate():
    rules = parity.baseline_rules()
    assert rules.resolved_level_tfs() == tuple(config.VIVEK_BOT_LEVEL_TF_ALLOW)
    assert parity._entry_passes_rules("weekly", "reclaim", rules)
    assert parity._entry_passes_rules("3d", "reclaim", rules)
    assert not parity._entry_passes_rules("h4", "reclaim", rules)
    assert not parity._entry_passes_rules(None, "reclaim", rules), "fail-closed, as live"
    assert not parity._entry_passes_rules("", "reclaim", rules)
    off = parity.ParityRules(name="all", level_tfs=())
    assert parity._entry_passes_rules("h4", "reclaim", off)
    v3 = parity.ParityRules(name="V3", level_tfs=("weekly",))
    assert not parity._entry_passes_rules("3d", "reclaim", v3)


def test_an_h4_signal_never_enters_the_baseline_replay(monkeypatch):
    _script(monkeypatch, {230}, level="h4")
    assert parity.replay_symbol_parity(_flat(), "nasdaq", "X", "X", "Tech") == []
    _script(monkeypatch, {230}, level="weekly")
    assert len(parity.replay_symbol_parity(_flat(), "nasdaq", "X", "X", "Tech")) == 1


def test_the_report_says_the_level_gate_is_simulated():
    rep = parity.build_parity_report([], {}, {}, {})
    assert rep["baseline"]["rules"]["level_tfs"] == list(config.VIVEK_BOT_LEVEL_TF_ALLOW)
    t = {"symbol": "A", "market": "asx", "grade": "A+", "entry_type": "reclaim",
         "direction": "long", "timeframe": "1W", "level_tf": "weekly",
         "entry_date": "2024-01-02", "exit_date": "2024-02-01", "realized_r": 0.1,
         "entry": 100.0, "stop": 95.0, "risk": 5.0}
    params = parity.portfolio_sim_parity([t])["params"]
    assert "level_gate" in params["simulated"]
    assert params["level_tfs"] == list(config.VIVEK_BOT_LEVEL_TF_ALLOW)


# ------------------------------------------------------------ #37 phantoms

def test_a_signal_while_a_trade_is_open_is_still_replayed(monkeypatch):
    """Two armed signals five bars apart; the first trade is still open when the
    second fires. The old chain never looked at the second one."""
    _script(monkeypatch, {230, 235})
    trades = parity.replay_symbol_parity(_flat(), "nasdaq", "X", "X", "Tech")
    entries = sorted(t["entry_date"] for t in trades)
    df = _flat()
    assert entries == [df.index[231].date().isoformat(), df.index[236].date().isoformat()]
    first, second = sorted(trades, key=lambda t: t["entry_date"])
    assert first["exit_date"] > second["entry_date"], "the two really overlap"
    # ...and the one-at-a-time chain is exactly what the old replay produced.
    assert parity._symbol_chain(trades) == [first]


def test_a_signal_the_book_skips_leaves_the_symbol_flat_for_its_next_signal(monkeypatch):
    """The scenario from the audit: the book is full when X's first signal
    fills, a slot frees, and X's still-armed signal a few days later is taken.
    Under the old chain the phantom X position blocked it, so X traded nothing."""
    _script(monkeypatch, {230, 235})
    df = _flat()
    x = parity.replay_symbol_parity(df, "nasdaq", "X", "X", "Tech")
    d231, d233 = df.index[231].date().isoformat(), df.index[233].date().isoformat()
    other = {"symbol": "A", "market": "nasdaq", "grade": "A+", "entry_type": "reclaim",
             "direction": "long", "timeframe": "1W", "level_tf": "weekly", "sector": "s-A",
             "entry_date": d231, "exit_date": d233, "exit_reason": "target",
             "realized_r": 1.0, "entry": 100.0, "stop": 95.0, "risk": 5.0}
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_OPEN_TOTAL", 1)
    taken = parity._taken_list([other] + x)
    assert [(t["symbol"], t["entry_date"]) for t in taken] == [
        ("A", d231), ("X", df.index[236].date().isoformat())]
    port = parity.portfolio_sim_parity([other] + x)
    assert port["taken"] == 2 and port["skipped"].get("book_full") == 1
    # `eligible` stays the one-at-a-time chain: A plus X's first signal.
    assert port["eligible"]["n"] == 2


def test_the_published_trades_are_the_chain_plus_what_the_book_took(monkeypatch):
    _script(monkeypatch, {230, 232, 235})
    x = parity.replay_symbol_parity(_flat(), "nasdaq", "X", "X", "Tech")
    assert len(x) == 3
    rep = parity.build_parity_report(x, {"nasdaq": {"symbols": 1}}, {}, {})
    assert rep["baseline"]["signals_emitted"] == 3
    pub = rep["trades"]
    assert len(pub) == 1 and pub[0]["chain"] and pub[0]["taken"]
    assert rep["baseline"]["all_signals"]["overall"]["n"] == 1
    assert rep["baseline"]["portfolio"]["skipped"].get("dup_symbol") == 2


@pytest.mark.parametrize("seq,expect", [
    # (entry, exit) per trade, one symbol: an exit ON the next entry's day still
    # holds it (the portfolio frees a slot only for exits strictly before).
    ([("01", "05"), ("05", "09"), ("06", "07"), ("10", "12")], ["01", "06", "10"]),
    ([("01", "03"), ("02", "04"), ("04", "05")], ["01", "04"]),
])
def test_the_chain_is_one_at_a_time_per_symbol(seq, expect):
    trades = [{"market": "asx", "symbol": "S", "entry_date": f"2024-01-{a}",
               "exit_date": f"2024-01-{b}"} for a, b in seq]
    trades.append({"market": "asx", "symbol": "T", "entry_date": "2024-01-02",
                   "exit_date": "2024-01-30"})
    chain = parity._symbol_chain(trades)
    assert [t["entry_date"][-2:] for t in chain if t["symbol"] == "S"] == expect
    assert sum(t["symbol"] == "T" for t in chain) == 1
