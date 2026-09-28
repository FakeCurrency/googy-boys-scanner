"""PhaseMap's crypto identity check (2026-09-28).

A ticker is not an identity. Measured from a GitHub runner
(scripts/crypto_source_compare.py), Yahoo's `<SYM>-USD` is a DIFFERENT TOKEN
from the CoinGecko top-200 coin of the same symbol for AERO (+2,623,839% vs
Binance), JUP (+96,729%), ARB (+35,210%), PRL, SKY, XCN, EDGE and MET (-43%)
-- so PhaseMap was mapping sweeps and zones on the wrong instrument.

The data provider stays Yahoo (changing PhaseMap's provider is the owner's
call). What changed is a data-integrity reject at the provider boundary: a
series whose latest close is not CoinGecko's price for the coin is not served,
and the coin is NAMED in the crypto snapshot's `identity_rejected`. No
detection maths, zone or threshold is touched.
"""

import json
import sys
import types

import pandas as pd
import pytest

from phasemap import run as PR
from phasemap.data.provider import YFinanceProvider
from phasemap.output.writer import (build_snapshot, split_narrations,
                                    validate_published, validate_snapshot)


def _bars(px, n=30, end="2026-09-20"):
    idx = pd.date_range(end=end, periods=n, freq="D", name="Date")
    return pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99,
                         "Close": px, "Volume": 1e6}, index=idx)


def _stub_yahoo(monkeypatch, series: dict):
    """Fake yfinance: per-ticker MultiIndex frame, as group_by="ticker" serves."""
    def download(chunk, **kw):
        got = {s: series[s] for s in chunk if s in series}
        return pd.concat(got, axis=1) if got else pd.DataFrame()

    mod = types.ModuleType("yfinance")
    mod.download = download
    monkeypatch.setitem(sys.modules, "yfinance", mod)


YAHOO = {"ARB-USD": _bars(0.003), "BTC-USD": _bars(100.0), "XMR-USD": _bars(7.0)}


def test_the_provider_refuses_a_wrong_token_series_and_names_it(monkeypatch):
    _stub_yahoo(monkeypatch, YAHOO)
    p = YFinanceProvider({"ARB": "ARB-USD", "BTC": "BTC-USD", "XMR": "XMR-USD"},
                         ref_prices={"ARB": 1.0, "BTC": 101.0, "XMR": None})
    p.fetch_all()
    assert p.get_daily_bars("ARB") is None
    assert p.get_daily_bars("BTC") is not None
    assert p.get_daily_bars("XMR") is not None          # no reference: nothing to check
    assert p.identity_rejected == {"ARB": ["yahoo"]}


def test_without_references_the_provider_serves_exactly_as_before(monkeypatch):
    """Stocks carry no cg_price; the provider must be byte-for-byte the old one."""
    _stub_yahoo(monkeypatch, YAHOO)
    p = YFinanceProvider({"ARB": "ARB-USD", "BTC": "BTC-USD"})
    p.fetch_all()
    assert p.get_daily_bars("ARB") is not None and p.identity_rejected == {}


def test_the_snapshot_names_the_rejected_coins_and_stays_valid():
    snap = build_snapshot("2026-09-28", universe_size=3, results=[],
                          identity_rejected={"JUP": ["yahoo"], "ARB": ["yahoo"]})
    validate_snapshot(snap)
    assert list(snap) == ["run_date", "ruleset_version", "universe_size",
                          "identity_rejected", "results"]
    assert list(snap["identity_rejected"]) == ["ARB", "JUP"]      # sorted: determinism
    slim, narr = split_narrations(snap)
    assert slim["identity_rejected"] == {"ARB": ["yahoo"], "JUP": ["yahoo"]}
    validate_published(slim, narr)


def test_a_stock_snapshot_is_unchanged():
    snap = build_snapshot("2026-09-28", universe_size=1, results=[])
    assert list(snap) == ["run_date", "ruleset_version", "universe_size", "results"]
    slim, _ = split_narrations(snap)
    assert "identity_rejected" not in slim


def test_a_malformed_rejection_block_fails_the_schema_gate():
    snap = build_snapshot("2026-09-28", universe_size=1, results=[])
    snap["identity_rejected"] = ["ARB"]
    with pytest.raises(ValueError, match="identity_rejected"):
        validate_snapshot(snap)


def _run(monkeypatch, tmp_path, market, symbols):
    _stub_yahoo(monkeypatch, YAHOO)
    monkeypatch.setattr(PR, "load_symbols", lambda m: dict(symbols))
    args = types.SimpleNamespace(tickers=None, limit=None, period="2y")
    PR.run_market(market, args, "2026-09-28", str(tmp_path))
    return json.loads((tmp_path / market / "latest.json").read_text(encoding="utf-8"))


def test_the_nightly_crypto_run_leaves_the_stranger_out_and_says_so(monkeypatch, tmp_path, capsys):
    latest = _run(monkeypatch, tmp_path, "crypto", {
        "ARB": {"yf": "ARB-USD", "name": "Arbitrum", "sector": "", "cg_price": 1.0},
        "BTC": {"yf": "BTC-USD", "name": "Bitcoin", "sector": "", "cg_price": 100.0}})
    assert latest["identity_rejected"] == {"ARB": ["yahoo"]}
    assert all(r["ticker"] != "ARB" for r in latest["results"])
    assert not (tmp_path / "charts" / "crypto" / "ARB.json").exists()
    out = capsys.readouterr().out
    assert "identity check: 1 coin(s) left out" in out and "ARB" in out
    out.encode("ascii")                                  # rule 9: ASCII-only prints


def test_a_clean_crypto_run_still_records_that_the_check_ran(monkeypatch, tmp_path):
    latest = _run(monkeypatch, tmp_path, "crypto", {
        "BTC": {"yf": "BTC-USD", "name": "Bitcoin", "sector": "", "cg_price": 100.0}})
    assert latest["identity_rejected"] == {}


def test_the_nightly_run_and_the_backtest_both_arm_the_check():
    import inspect
    from phasemap.backtest import __main__ as BT
    for src in (inspect.getsource(PR.run_market), inspect.getsource(BT.main)):
        assert "ref_prices=ref_prices(symbols)" in src
        assert "report_identity(" in src
    assert "cg_price" in inspect.getsource(PR.load_symbols)
