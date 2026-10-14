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


# -- #72 dead payload fields are gone; the one that LOOKS dead is kept -------

def test_dead_top_level_and_row_fields_are_not_published(monkeypatch):
    _stub_engine(monkeypatch, {"1W": _plan(103.0)})
    out = scan.scan_vivek_market("asx", universe=_uni("BHP", suffix=".AX"),
                                 frames={"BHP.AX": _frame()}, pulse_data=[], progress=False)
    for k in ("sector_counts", "pulse"):
        assert k not in out, f"{k} had no reader anywhere"
    (row,) = out["results"]
    assert "armed_tf" not in row
    # grade_held_runs is NOT dead: it is the hysteresis state the NEXT scan
    # reads back out of the published file (_load_prev_grades).
    assert "grade_held_runs" in row


def test_grade_held_runs_is_read_back_by_the_next_scan(tmp_path):
    (tmp_path / "asx_vivek.json").write_text(json.dumps({"results": [
        {"symbol": "BHP", "grade": "A+", "dir": "LONG", "grade_held_runs": 2}]}))
    assert scan._load_prev_grades(str(tmp_path), "asx")["BHP"]["held"] == 2


def test_the_runner_keeps_prices_but_the_published_file_does_not(monkeypatch):
    _stub_engine(monkeypatch, {"1W": _plan(103.0)})
    vk = scan.scan_vivek_market("asx", universe=_uni("BHP", suffix=".AX"),
                                frames={"BHP.AX": _frame()}, pulse_data=[], progress=False)
    assert vk["prices"] == {"BHP": 100.0}, "run.py builds the slim prices file from this"
    pub = scan.published(vk, "asx", caps={}, sectors={})
    assert "prices" not in pub and "price_age" not in pub
    assert {k: v for k, v in vk.items() if k not in ("prices", "price_age", "results")} == \
        {k: v for k, v in pub.items() if k != "results"}


# -- #73 / #157 display mcap + mcap_asof + sector, on a COPY ------------------

_CAPS = {"asx:BHP": {"mcap": 2.2e11, "ts": "2026-10-10T05:00:00+00:00"},
         "nasdaq:AXTI": {"mcap": 3.1e8, "ts": "2026-06-24T05:00:00+00:00"}}
_SECTORS = {"nasdaq:AXTI": {"sector": "Technology", "ts": "x"},
            "nasdaq:KEEP": {"sector": "Energy", "ts": "x"}}


def _vk(market, *rows):
    return {"market": market, "generated_at": "g", "prices": {"X": 1.0}, "price_age": {},
            "results": [dict(r) for r in rows]}


def test_published_rows_carry_the_cap_and_the_date_it_was_fetched():
    vk = _vk("asx", {"symbol": "BHP", "sector": "Materials"}, {"symbol": "ZZZ", "sector": ""})
    bhp, zzz = scan.published(vk, "asx", caps=_CAPS, sectors={})["results"]
    assert bhp["mcap"] == 220_000_000_000 and bhp["mcap_asof"] == "2026-10-10"
    assert "mcap" not in zzz and "mcap_asof" not in zzz, "no cap is no key, never 0"


def test_an_old_cap_publishes_its_old_date():
    vk = _vk("nasdaq", {"symbol": "AXTI", "sector": ""})
    (row,) = scan.published(vk, "nasdaq", caps=_CAPS, sectors=_SECTORS)["results"]
    assert row["mcap_asof"] == "2026-06-24", "the reader can tell a 112-day-old cap"


def test_published_fills_only_a_blank_sector():
    vk = _vk("nasdaq", {"symbol": "AXTI", "sector": ""},
             {"symbol": "KEEP", "sector": "Industrials"})
    axti, keep = scan.published(vk, "nasdaq", caps={}, sectors=_SECTORS)["results"]
    assert axti["sector"] == "Technology"
    assert keep["sector"] == "Industrials", "a sector the row shipped with always wins"


def test_published_never_touches_the_rows_the_bot_reads():
    vk = _vk("nasdaq", {"symbol": "AXTI", "sector": ""})
    import copy
    before = copy.deepcopy(vk)
    pub = scan.published(vk, "nasdaq", caps=_CAPS, sectors=_SECTORS)
    assert vk == before, "the bot's in-memory rows must not gain a sector or a cap"
    assert pub["results"][0] is not vk["results"][0]


def test_crypto_rows_get_no_cap_from_the_stock_cache():
    vk = _vk("crypto", {"symbol": "BHP", "sector": ""})
    (row,) = scan.published(vk, "crypto", caps=_CAPS, sectors=_SECTORS)["results"]
    assert "mcap" not in row and row["sector"] == ""


def test_run_py_publishes_the_stamped_copy_and_builds_slim_prices_from_vk():
    from scanner import run as runmod
    src = (runmod.REPO_ROOT / "scanner" / "run.py").read_text(encoding="utf-8")
    assert "output.write_vivek_pair(scan.published(vk, market_key), args.out, market_key)" in src
    assert '"prices": vk["prices"]' in src
