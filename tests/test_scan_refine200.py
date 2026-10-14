"""scanner/scan.py -- REFINE200 WP3 fixes, pinned on the shipped scan loop.

The signal engine is stubbed (as in tests/test_scan_pipeline.py) so these pin
the PIPELINE: what the scan publishes, never the detection maths.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

import scanner.vivek as vivek
from scanner import config, scan


def _frame(close=100.0, vol=1_000_000.0, n=30, end="2024-01-02"):
    idx = pd.date_range(end=end, periods=n, freq="D")
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": vol}, index=idx)


def _plan(entry, armed=True, risk=4.0):
    return {"armed": armed, "entry": entry, "stop": entry - risk,
            "tp1": entry + 1.5 * risk, "tp2": entry + 2 * risk, "tp3": entry + 3 * risk,
            "scale": [0.25, 0.50, 0.15], "risk": risk, "rr": 2.0,
            "entry_trigger": "reclaim" if armed else None,
            "trigger_bar": "2024-01-02" if armed else None}


_SIG = {"direction": "long", "close": 100.0, "level_tf": "weekly", "level": 99.0,
        "at_level": True, "reaction": "bounce", "structure": 0.8, "confluence": False}


def _stub_engine(monkeypatch, plans, raw=("A+", 8)):
    monkeypatch.setattr(vivek, "evaluate", lambda df, **kw: dict(_SIG))
    monkeypatch.setattr(vivek, "score_and_grade", lambda sig: (raw[1], raw[0], ["CHIP"]))
    monkeypatch.setattr(vivek, "build_plans", lambda df, sig, **kw: dict(plans))
    monkeypatch.setattr(vivek, "build_markers", lambda plans: {})
    monkeypatch.setattr(vivek, "build_detail", lambda df, sig, lv: {})
    monkeypatch.setattr(vivek, "narrative", lambda *a, **k: "n/a")
    monkeypatch.setattr(vivek, "entry_types", lambda sig: ["reclaim"])
    monkeypatch.setattr(config, "VIVEK_H4_PLANS", False)     # no live 4H download


def _uni(*syms, suffix=""):
    return [{"yf": s + suffix, "symbol": s, "name": s, "sector": ""} for s in syms]


# -- #22 "liquidity arriving" reads crypto Volume as the dollars it already is --

def test_crypto_arriving_turnover_is_the_usd_volume_not_price_times_it(monkeypatch, tmp_path):
    """Crypto Volume is quote (USD) volume. A 1c coin trading $5M today against
    a $1M/day history clears the $3M floor on today's turnover alone; the old
    Close x Volume read it as $50k and dropped it from the report."""
    _stub_engine(monkeypatch, {"1W": _plan(0.0103, risk=0.0004)})
    f = _frame(close=0.01, vol=1_000_000.0)
    f.loc[f.index[-1], "Volume"] = 5_000_000.0
    out = scan.scan_vivek_market("crypto", universe=_uni("THN", suffix="-USD"),
                                 frames={"THN-USD": f}, pulse_data=[], progress=False,
                                 out_root=str(tmp_path))
    arr = json.loads((tmp_path / "crypto_arriving.json").read_text(encoding="utf-8"))
    assert out["funnel"]["illiquid_setup"] == 1          # avg $1.2M < $3M floor
    assert [r["symbol"] for r in arr["results"]] == ["THN"]
    assert arr["results"][0]["turnover_today"] == 5_000_000


def test_stock_arriving_turnover_is_still_close_times_volume():
    stock = config.MARKETS["asx"]
    f = _frame(close=2.0, vol=1_000.0)
    assert scan._turnover_today(f, stock) == 2_000.0
    assert scan._turnover_today(f, config.MARKETS["crypto"]) == 1_000.0


# -- #66 sparkline closes ship at significant figures, not float noise --------

@pytest.mark.parametrize("raw,want", [
    (23.559999465942383, 23.56),          # a float32 close as Yahoo serves it
    (64.62999725341797, 64.63),
    (1234.5678, 1234.6),
    (3.6771499e-07, 3.6771e-07),          # a sub-millionth coin keeps its shape
    (0.0, 0.0),
])
def test_spark_is_rounded_to_significant_figures(raw, want):
    f = _frame(close=raw, n=3)
    assert scan._spark(f) == [want] * 3
    assert config.SPARK_SIG_FIGS == 5


def test_spark_keeps_the_last_spark_bars_in_order():
    f = _frame(n=40)
    f["Close"] = [100.0 + i / 3 for i in range(40)]
    sp = scan._spark(f)
    assert len(sp) == config.SPARK_BARS and sp == sorted(sp)
    assert sp[-1] == 113.0 and sp[0] == 103.33
