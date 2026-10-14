"""REFINE200 #135 -- sub-millionth coins on Yahoo publish nonsense plans.

Yahoo stores crypto closes at 6 decimals. HTX (1.65e-6) and BTT (3.7e-7) fell
back to Yahoo, whose history for both is one or two repeated ticks, while the
NEWEST close -- the only one the identity check reads -- carries full
precision. The published HTX row had entry = stop = tp1 = 2e-06, risk 0.0 and
rr_text "3.0:1"; BTT a price 2.7x CoinGecko's and a stop of -2.5e-07.

Two guards, both of which only ever remove a coin: data.fetch refuses such a
frame like a stranger (and the cache may not refill it), and the scan drops a
row none of whose plans has positive risk, entry and (long) stop.
"""
from __future__ import annotations

import pandas as pd
import pytest

import scanner.vivek as vivek
from scanner import config, data, scan


def _yahoo(history, newest, n=60):
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").normalize().tz_localize(None),
                        periods=n, freq="D")
    closes = [history[i % len(history)] for i in range(n - 1)] + [newest]
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": 5e6}, index=idx)


def test_a_one_tick_history_is_quantised():
    assert data.quantised(_yahoo([1e-06], 3.7e-07))            # BTT
    assert data.quantised(_yahoo([2e-06, 1e-06], 1.65e-06))    # HTX, two ticks
    assert not data.quantised(_yahoo([1e-06, 2e-06, 3e-06], 2e-06))
    real = _yahoo([1.0], 1.0)
    real["Close"] = [1.0 + i / 100 for i in range(len(real))]
    assert not data.quantised(real)


def test_a_frame_too_short_to_tell_is_not_refused():
    assert not data.quantised(_yahoo([1e-06], 1e-06, n=config.CRYPTO_QUANTISED_BARS))
    assert data.quantised(_yahoo([1e-06], 1e-06, n=config.CRYPTO_QUANTISED_BARS + 1))


def test_the_newest_close_is_left_out_because_it_is_the_one_that_looks_right():
    f = _yahoo([1e-06], 3.7e-07)
    f.iloc[-1, f.columns.get_loc("Close")] = 3.7e-07
    assert data.quantised(f), "full precision on the newest bar must not rescue it"


@pytest.fixture
def yahoo_only(monkeypatch):
    """Every exchange refuses (conftest); Yahoo serves BTT coarse, ETH fine."""
    eth = _yahoo([1.0], 2500.0)
    eth["Close"] = [2400.0 + i for i in range(len(eth) - 1)] + [2500.0]
    frames = {"BTT-USD": _yahoo([1e-06], 3.7e-07), "ETH-USD": eth}
    monkeypatch.setattr(data, "download",
                        lambda t, period=None, **k: {x: frames[x].copy() for x in t if x in frames})
    return frames


def test_fetch_refuses_a_coarse_yahoo_series_like_a_stranger(yahoo_only):
    fr, rep = data.fetch("crypto", ["BTT-USD", "ETH-USD"], period="5y",
                         ref_prices={"BTT-USD": 3.68e-07, "ETH-USD": 2500.0})
    assert set(fr) == {"ETH-USD"}
    assert rep["precision_rejected"] == {"BTT": ["yahoo"]}
    assert rep["refused"] == ["BTT-USD"] and rep["rejected_venues"] == {"BTT-USD": ["yahoo"]}
    assert data.source_summary(rep)["precision_rejected"] == {"BTT": ["yahoo"]}


def test_the_cache_does_not_refill_a_coarse_coin(yahoo_only):
    old = yahoo_only["BTT-USD"].copy()
    old.attrs["source"] = "yahoo"
    data.save_frame_cache("crypto", {"BTT-USD": old})
    fr, rep = data.fetch("crypto", ["BTT-USD", "ETH-USD"], period="5y",
                         ref_prices={"BTT-USD": 3.68e-07, "ETH-USD": 2500.0})
    merged, stats = data.merge_with_cache("crypto", fr, ["BTT-USD", "ETH-USD"],
                                          refused=rep["refused"],
                                          rejected_venues=rep["rejected_venues"])
    assert "BTT-USD" not in merged and stats["refused"] == 1


def test_the_yahoo_mode_path_refuses_it_too(yahoo_only, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_DATA_SOURCE", "yahoo")
    fr, rep = data.fetch("crypto", ["BTT-USD", "ETH-USD"], period="5y")
    assert set(fr) == {"ETH-USD"} and rep["refused"] == ["BTT-USD"]


def test_stocks_are_never_judged_by_it(monkeypatch):
    penny = _yahoo([0.001, 0.002], 0.002)
    monkeypatch.setattr(data, "download", lambda t, period=None, **k: {"ZZZ.AX": penny})
    fr, rep = data.fetch("asx", ["ZZZ.AX"], period="5y")
    assert "ZZZ.AX" in fr and rep["refused"] == []


# -- the scan backstop: a row with no sane plan anywhere is not published ----

def _p(entry, stop, risk, armed=False):
    return {"armed": armed, "entry": entry, "stop": stop, "risk": risk,
            "tp1": entry + risk, "tp2": entry + 2 * risk, "tp3": entry + 3 * risk,
            "scale": [0.25, 0.5, 0.15], "rr": 3.0, "entry_trigger": None, "trigger_bar": None}


def _run(monkeypatch, plans, market="crypto"):
    sig = {"direction": "long", "close": 1.0, "level_tf": "h4", "level": 1.0,
           "at_level": True, "reaction": "bounce", "structure": 0.5, "confluence": False}
    monkeypatch.setattr(vivek, "evaluate", lambda df, **kw: dict(sig))
    monkeypatch.setattr(vivek, "score_and_grade", lambda s: (6, "B+", []))
    monkeypatch.setattr(vivek, "build_plans", lambda df, s, **kw: dict(plans))
    monkeypatch.setattr(vivek, "build_markers", lambda p: {})
    monkeypatch.setattr(vivek, "build_detail", lambda df, s, lv: {})
    monkeypatch.setattr(vivek, "narrative", lambda *a, **k: "n/a")
    monkeypatch.setattr(vivek, "entry_types", lambda s: [])
    monkeypatch.setattr(config, "VIVEK_H4_PLANS", False)
    f = _yahoo([1.0], 1.0, n=40)
    f["Close"] = [1.0 + (i % 7) / 10 for i in range(40)]   # not a peg, not coarse
    return scan.scan_vivek_market(market, universe=[{"yf": "X-USD", "symbol": "X",
                                                     "name": "X", "sector": ""}],
                                  frames={"X-USD": f}, pulse_data=[], progress=False)


def test_a_row_whose_every_plan_is_degenerate_is_dropped(monkeypatch):
    out = _run(monkeypatch, {"1D": _p(2e-06, 2e-06, 0.0), "3D": _p(2e-06, 2e-06, 0.0)})
    assert out["results"] == [] and out["funnel"]["no_plan"] == 1
    out = _run(monkeypatch, {"1D": _p(1e-06, -2.5e-07, 1.25e-06)})        # BTT's
    assert out["results"] == []


def test_one_sane_plan_keeps_the_row_untouched(monkeypatch):
    """AXTI (NASDAQ, A) carried a 1W long plan with a -2.72 stop beside a sane
    1D headline; only rows with NO sane plan go, so it stays as it was."""
    out = _run(monkeypatch, {"1D": _p(1.0, 0.9, 0.1), "1W": _p(1.0, -0.2, 1.2)})
    (row,) = out["results"]
    assert row["plans"]["1W"]["stop"] == -0.2 and row["entry"] == 1.0


def test_degenerate_reads_the_published_numbers():
    assert scan._degenerate(_p(2e-06, 2e-06, 0.0), "long")
    assert scan._degenerate(_p(1.0, -0.1, 1.1), "long")
    assert not scan._degenerate(_p(1.0, 1.2, 0.2), "short")
    assert scan._degenerate({"entry": None, "stop": 1, "risk": 1}, "short")
