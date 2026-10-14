"""The parity decision replay (scanner/vivek_parity.py), REFINE200 WP4b.

#149 the baseline applies the bot's weekly/3d LEVEL gate (fail-closed)
#150 ONE chronological book: a refused signal leaves its symbol flat, so a
     later signal is still taken (no phantom trades), and the stop cooldown
     applies inside the replay
#151 a variant's time halves are split at the BASELINE's median entry date
#32  the decision variants (A+ only, no 3D reclaim, no ASX, ASX without 3D
     reclaim) and the time stop are re-run as whole books, by market and cell
"""

from __future__ import annotations

import datetime as dt
import json
import math

import numpy as np
import pandas as pd
import pytest

from scanner import config, output
from scanner import vivek_parity as vp

pytestmark = pytest.mark.risk

SCALE = list(config.VIVEK_TP_SCALE_LONG)
D0 = dt.date(2024, 1, 1)


def _plan(trigger: str) -> dict:
    return {"stop": 95.0, "tp1": 110.0, "tp2": 120.0, "tp3": 130.0, "scale": SCALE,
            "entry": 100.0, "rr": 4.0, "entry_trigger": trigger, "trigger_bar": None,
            "structural_tps": 0}


def _series(sym: str, market: str = "nasdaq", n: int = 120, signals=(), lows=None,
            sector: str | None = None) -> vp.SymbolSeries:
    """Flat bars at 100 (never TP1, never the 95 stop) unless `lows` dips a
    bar; `signals` = [(bar, {tf: trigger}, grade, level_tf)]."""
    o = np.full(n, 100.0)
    h, l, c = o + 1.0, o - 1.0, o.copy()
    for k, v in (lows or {}).items():
        l[k] = v
    days = np.array([(D0 - vp._EPOCH).days + k for k in range(n)], dtype=np.int64)
    s = vp.SymbolSeries(market=market, symbol=sym, name=sym, sector=sector or f"sec-{sym}",
                        days=days, o=o, h=h, l=l, c=c, adv=np.full(n, 1e8))
    for j, plans, grade, level in signals:
        s.signals.append((j, {"grade": grade, "dir": "LONG", "level_tf": level,
                              "entry_types": list(plans.values()),
                              "plans": {tf: _plan(trig) for tf, trig in plans.items()}}))
    return s


def _day(k: int) -> str:
    return (D0 + dt.timedelta(days=k)).isoformat()


W1R = {"1W": "reclaim"}


# ----------------------------------------------------------- #149 level gate

def test_the_baseline_book_applies_the_live_level_gate_fail_closed():
    ss = [_series("W", signals=[(0, W1R, "A+", "weekly")]),
          _series("T", signals=[(0, W1R, "A+", "3d")]),
          _series("H", signals=[(0, W1R, "A+", "h4")]),
          _series("N", signals=[(0, W1R, "A+", None)])]
    taken = vp.run_book(ss)["taken"]
    assert sorted(t["symbol"] for t in taken) == ["T", "W"]
    assert vp.baseline_rules().level_allow() == tuple(config.VIVEK_BOT_LEVEL_TF_ALLOW)
    # () turns the gate off, exactly as an empty config allowlist does
    off = vp.run_book(ss, vp.ParityRules(name="all", level_tfs=()))["taken"]
    assert len(off) == 4


# ------------------------------------------------ #150 one chronological book

def test_a_refused_signal_leaves_its_symbol_free_for_the_next_one():
    """B fills the only slot until its 28-day time stop. A's signals while the
    book is full are refused -- and A is NOT held by a phantom trade, so its
    signal after B leaves is taken. The old per-symbol replay held A from its
    first signal for a whole trade life and never generated the later one."""
    b = _series("B", signals=[(0, W1R, "A+", "weekly")])
    a = _series("A", signals=[(5, W1R, "A+", "weekly"), (20, W1R, "A+", "weekly"),
                              (31, W1R, "A+", "weekly")])
    book = vp.run_book([a, b], max_total=1)
    got = [(t["symbol"], t["entry_date"], t["exit_reason"]) for t in book["taken"]]
    assert got[0] == ("B", _day(1), "time")
    assert book["taken"][0]["exit_date"] == _day(30)           # held 29 days > 28
    assert got[1][:2] == ("A", _day(32))
    assert book["skipped"] == {"book_full": 2}
    assert book["peak_open"] == 1


def test_the_stop_cooldown_runs_inside_the_book():
    a = _series("A", lows={3: 90.0},
                signals=[(j, W1R, "A+", "weekly") for j in range(0, 16)])
    book = vp.run_book([a], max_total=math.inf, max_sector=0, cooldown=7)
    first, second = book["taken"][:2]
    assert first["exit_reason"] == "stop" and first["exit_date"] == _day(3)
    assert second["entry_date"] == _day(12)          # signal on day 11 = exit + 8
    assert book["skipped"]["cooldown"] == 8          # signals on days 3..10
    again = vp.run_book([a], max_total=math.inf, max_sector=0, cooldown=0)["taken"]
    assert again[1]["entry_date"] == _day(4)         # the old replay's next-open re-entry


def test_a_stop_scores_both_fills_and_a_time_stop_one():
    a = _series("A", lows={3: 90.0}, signals=[(0, W1R, "A+", "weekly")])
    stop = vp.run_book([a])["taken"][0]
    assert stop["realized_r"] < stop["realized_r_house"]        # low 90 vs the 95 stop
    b = _series("B", signals=[(0, W1R, "A+", "weekly")])
    timed = vp.run_book([b])["taken"][0]
    assert timed["exit_reason"] == "time"
    assert timed["realized_r_house"] == timed["realized_r"]
    slim = vp._slim_parity(stop)
    assert slim["stop"] == 95.0 and slim["exit"] == pytest.approx(90.0)
    assert slim["cell"] == "1W reclaim" and slim["signal_date"] == _day(0)
    assert (slim["tp1"], slim["tp2"], slim["tp3"]) == (110.0, 120.0, 130.0) and slim["scale"]


def test_the_sector_cap_is_per_market():
    cap = int(config.VIVEK_BOT_MAX_PER_SECTOR)
    ss = [_series(f"S{i}", sector="tech", signals=[(0, W1R, "A+", "weekly")])
          for i in range(cap + 1)]
    ss.append(_series("C", market="crypto", sector="tech", signals=[(0, W1R, "A+", "weekly")]))
    book = vp.run_book(ss)
    assert len(book["taken"]) == cap + 1 and book["skipped"] == {"sector_cap": 1}


# --------------------------------------------------- #32 decision variants

def _variant(name: str) -> vp.ParityRules:
    return next(r for r in vp.variant_grid() if r.name == name)


def test_the_grid_carries_the_owners_decision_variants():
    names = [r.name for r in vp.variant_grid()]
    for want in ("V1_hold_off", "V5_aplus_only", "V6_no_3d_reclaim", "V7_no_asx",
                 "V8_asx_3d_reclaim_off"):
        assert want in names
    assert "3D" not in _variant("V6_no_3d_reclaim").cells_for("nasdaq")
    v8 = _variant("V8_asx_3d_reclaim_off")
    assert "3D" not in v8.cells_for("asx") and "3D" in v8.cells_for("nasdaq")


def test_the_variants_walk_the_cells_like_the_bot():
    """Dropping the 3D reclaim cell does not drop the row: the walk falls
    through to its armed 1D break, as vivek_bot._pick_plan would."""
    both = {"3D": "reclaim", "1D": "break"}
    asx = _series("X", market="asx", signals=[(0, both, "A+", "3d")])
    nas = _series("Y", market="nasdaq", signals=[(0, both, "A", "3d")])
    tf = lambda rules: {t["symbol"]: t["timeframe"] for t in vp.run_book([asx, nas], rules)["taken"]}  # noqa: E731
    assert tf(vp.baseline_rules()) == {"X": "3D", "Y": "3D"}
    assert tf(_variant("V6_no_3d_reclaim")) == {"X": "1D", "Y": "1D"}
    assert tf(_variant("V8_asx_3d_reclaim_off")) == {"X": "1D", "Y": "3D"}
    assert tf(_variant("V7_no_asx")) == {"Y": "3D"}
    assert tf(_variant("V5_aplus_only")) == {"X": "3D"}


def test_a_market_the_variant_drops_is_reported_not_gated():
    base = [{"market": mk, "entry_date": f"2024-{m:02d}-01", "exit_date": f"2024-{m:02d}-20",
             "realized_r": 0.1} for mk in ("asx", "nasdaq") for m in range(1, 13)]
    var = [{**t, "realized_r": 0.5} for t in base if t["market"] == "nasdaq"]
    v = vp.variant_passes(base, var, skip_markets=("asx",))
    assert v["checks"]["market:asx"]["pass"] is None
    assert v["checks"]["market:nasdaq"]["pass"] is True


# ------------------------------------------------- #151 one split date

def test_both_halves_split_at_the_baselines_median():
    base = [{"market": "asx", "entry_date": f"2023-{m:02d}-01", "exit_date": f"2023-{m:02d}-15",
             "realized_r": 0.1 * m} for m in range(1, 11)]
    var = [t for t in base if t["entry_date"] >= "2023-05-01"]     # filters early entries
    v = vp.variant_passes(base, var)
    split = vp._split_date(base)
    assert v["split_entry_date"] == split == "2023-06-01"
    assert vp._split_date(var) != split                           # its own median differs
    want_first = vp._slot_month_stats([t for t in var if t["entry_date"] < split])[1]
    assert v["checks"]["half:first"]["variant"] == want_first


# --------------------------------------------- report + phase 1 plumbing

def test_the_adv_series_is_adv_usd_at_bar_for_bar():
    rng = np.random.default_rng(4)
    n = 60
    df = pd.DataFrame({"Close": 10 + rng.random(n), "Volume": rng.integers(0, 5000, n).astype(float),
                       "Open": 10.0, "High": 11.0, "Low": 9.0},
                      index=pd.date_range("2025-01-01", periods=n))
    df.loc[df.index[7], "Volume"] = np.nan
    for mk in ("asx", "crypto"):
        s = vp._adv_series(df, mk)
        for j in range(n):
            want = vp._adv_usd_at(df, j, mk)
            assert (want is None and np.isnan(s[j])) or s[j] == pytest.approx(want), (mk, j)


def _frame(n=300, seed=5):
    rng = np.random.default_rng(seed)
    px = 40 * np.cumprod(1 + rng.normal(0, 0.012, n))
    return pd.DataFrame({"Open": px, "High": px * 1.012, "Low": px * 0.988, "Close": px,
                         "Volume": 5e6}, index=pd.date_range("2019-01-01", periods=n, freq="B"))


def test_parallel_signals_equal_serial_signals():
    frames = {"AAA": _frame(seed=5), "BBB": _frame(seed=9)}
    meta = {k: {"symbol": k, "name": k, "sector": "s"} for k in frames}
    serial = vp.collect_series("nasdaq", frames, meta, workers=1)
    para = vp.collect_series("nasdaq", frames, meta, workers=2)
    assert [s.symbol for s in serial] == [s.symbol for s in para] == ["AAA", "BBB"]
    for a, b in zip(serial, para):
        assert a.evaluated == b.evaluated > 0
        assert json.dumps(a.signals, sort_keys=True, default=str) == \
            json.dumps(b.signals, sort_keys=True, default=str)


def test_the_full_pack_builds_serialises_and_summarises(monkeypatch, tmp_path):
    def fake_load(mk, limit, period, exclude_symbols=None, workers=1):
        ss = [_series(f"{mk[:1].upper()}{i}", market=mk,
                      signals=[(i, {"3D": "reclaim", "1D": "break"}, "A+" if i % 2 else "A", "3d"),
                               (40 + i, W1R, "A+", "weekly")],
                      lows={i + 4: 90.0} if i % 3 == 0 else None)
              for i in range(6)]
        return ss, {"symbols": 6, "universe": 60, "sampled_pct": 10.0, "replayed": 6,
                    "signals": 12, "data_sources": {"by_source": {"x": 6}},
                    "sampled_symbols": [s.symbol for s in ss]}

    monkeypatch.setattr(vp, "load_market_series", fake_load)
    monkeypatch.setattr(vp, "fx_rates", lambda: {"audusd": 0.66, "source": "fallback"})
    rep = vp.run_parity(["asx", "nasdaq", "crypto"], 6, "5y", workers=1)
    assert set(rep["variants"]) == {r.name for r in vp.variant_grid()}
    base = rep["baseline"]
    assert base["portfolio"]["taken"] == sum(1 for t in rep["trades"] if t["taken"]) > 0
    assert base["portfolio"]["params"]["level_tf_allow"] == list(config.VIVEK_BOT_LEVEL_TF_ALLOW)
    sl = base["portfolio_slices"]
    assert {"by_cell", "by_grade", "by_market_cell", "by_cell_quarter"} <= set(sl)
    assert "3D reclaim" in sl["by_cell"] and "expectancy_r_house" in sl["by_cell"]["3D reclaim"]
    assert rep["variants"]["V7_no_asx"]["slices"]["by_market"].get("asx") is None
    assert rep["params"]["stop_fill"].startswith("worst print")
    output.write_json(tmp_path / "r.json", rep)                    # no NaN / inf anywhere
    md = vp.summary_markdown(rep)
    for want in ("### Overall (book)", "### By market (book)", "### By cell (book)",
                 "### By grade (book)", "V8_asx_3d_reclaim_off", "V1_hold_off"):
        assert want in md
