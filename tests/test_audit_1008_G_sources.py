"""Audit 2026-10-08 #36 -- the crypto backtests read Yahoo directly.

Since 2026-09-28 the live crypto scan and the bot price crypto through
`data.fetch` (exchange klines, the identity check, single-venue volume under
the $3M floor). The VIVEK backtest, the parity replay, r_parity and the
fill-sensitivity study still called `data.download` for every market, so the
crypto evidence was replayed on Yahoo `<SYM>-USD` series -- including the
same-ticker strangers the live scan refuses -- and on Yahoo's aggregate volume.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib

import numpy as np
import pandas as pd
import pytest

from scanner import vivek_backtest as bt
from scanner import vivek_parity as parity

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATHS = ("scanner/vivek_backtest.py", "scanner/vivek_parity.py",
         "scripts/r_parity.py", "scripts/lens_fill_confluence.py")


def _calls(rel: str) -> set[str]:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            out.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", ""))
    return out


@pytest.mark.parametrize("rel", PATHS)
def test_every_replay_prices_through_fetch_with_the_identity_check(rel):
    calls = _calls(rel)
    assert "fetch" in calls and "identity_kwargs" in calls, rel
    assert "download" not in calls, f"{rel} still calls data.download for its frames"


def _uni():
    return [{"symbol": "BTC", "yf": "BTC-USD", "name": "Bitcoin", "sector": "", "cg_price": 65000.0},
            {"symbol": "PRL", "yf": "PRL-USD", "name": "Perle", "sector": "", "cg_price": 0.5}]


def _btc() -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=300, freq="D")
    px = np.linspace(60000, 65000, 300)
    return pd.DataFrame({"Open": px, "High": px, "Low": px, "Close": px, "Volume": 1e9}, index=idx)


def _fake_fetch(seen: list):
    def fetch(market, tickers, period=None, interval="1d", ref_prices=None, **kw):
        seen.append({"market": market, "tickers": list(tickers), "ref_prices": dict(ref_prices or {}),
                     "period": period, **kw})
        # The identity check refused PRL (Yahoo's PRL-USD is another token).
        frames = {"BTC-USD": _btc()}
        return frames, {"mode": "exchange", "by_source": {"binance_vision": 1},
                        "source_of": {"BTC-USD": "binance_vision"}, "refused": ["PRL-USD"],
                        "identity_rejected": {"PRL": ["binance_vision", "yahoo"]}}
    return fetch


@pytest.mark.parametrize("runner", ["backtest", "parity"])
def test_the_crypto_replay_reads_what_fetch_admits_and_says_where_from(monkeypatch, runner):
    import scanner.data
    import scanner.universe
    seen, replayed = [], []
    monkeypatch.setattr(scanner.universe, "load_universe", lambda m, full=True: _uni())
    monkeypatch.setattr(scanner.data, "fetch", _fake_fetch(seen))
    monkeypatch.setattr(scanner.data, "download", lambda *a, **k: pytest.fail("bare Yahoo download"))
    if runner == "backtest":
        monkeypatch.setattr(bt, "replay_symbol",
                            lambda df, mk, sym, *a, **k: replayed.append(sym) or [])
        _trades, cov = bt.run_market_trades("crypto", None, "1y")
    else:
        monkeypatch.setattr(parity, "replay_symbol_parity",
                            lambda df, mk, sym, *a, **k: replayed.append(sym) or [])
        _trades, cov = parity.run_market_parity("crypto", None, "1y")
    assert seen and seen[0]["market"] == "crypto"
    assert seen[0]["ref_prices"] == {"BTC-USD": 65000.0, "PRL-USD": 0.5}
    assert replayed == ["BTC"], "the refused coin is never replayed"
    assert cov["data_sources"]["refused"] == ["PRL-USD"]
    assert cov["data_sources"]["by_source"] == {"binance_vision": 1}


def test_stocks_fall_straight_through_to_the_same_yahoo_download(monkeypatch):
    """fetch's stock branch IS download(), with the call shape it always had."""
    import scanner.data
    import scanner.universe
    calls = []
    monkeypatch.setattr(scanner.universe, "load_universe",
                        lambda m, full=True: [{"symbol": "BHP", "yf": "BHP.AX", "name": "BHP"}])
    monkeypatch.setattr(scanner.data, "download",
                        lambda tickers, period=None, **k: calls.append((list(tickers), period, k)) or {})
    _t, cov = bt.run_market_trades("asx", None, "5y")
    assert calls == [(["BHP.AX"], "5y", {})]
    assert cov["data_sources"]["mode"] == "yahoo"


def test_the_fill_study_arms_the_identity_check_from_todays_universe(monkeypatch):
    import scanner.data
    import scanner.universe
    spec = importlib.util.spec_from_file_location("lens_fill_confluence",
                                                  ROOT / "scripts" / "lens_fill_confluence.py")
    lfc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lfc)
    seen = []
    monkeypatch.setattr(scanner.universe, "load_universe", lambda m, full=True: _uni())
    monkeypatch.setattr(scanner.data, "fetch", _fake_fetch(seen))
    frames = lfc.download_frames([{"market": "crypto", "symbol": "BTC"},
                                  {"market": "crypto", "symbol": "PRL"}])
    assert set(frames) == {("crypto", "BTC")}
    assert seen[0]["ref_prices"] == {"BTC-USD": 65000.0, "PRL-USD": 0.5}
