"""REFINE200 evidence fixes in scanner/vivek_backtest.py (WP4b).

#31  every replayed trade publishes mfe_r (mfe_zero_rate read 1.0 everywhere)
#138 the published `exit` is the exit PRICE and `stop` the INITIAL stop
#146 the worst-print stop fill is disclosed, and a house-fill column sits beside it
#147 the candidate mask reads the engine's own causal levels (weekly proxy, no 3D peek)
#149 portfolio_sim applies the bot's level gate; the cell evidence is split by it
#154 the replay prices crypto through data.fetch (exchange klines + identity check)
#156 the 7-day stop cooldown applies inside the replay the headline comes from
"""

from __future__ import annotations

import ast
import pathlib
import random

import numpy as np
import pandas as pd
import pytest

from scanner import config, conviction, rmodel, vivek
from scanner import vivek_backtest as bt
from scanner.indicators import sma
from scanner.vivek_journal import _snapshot, costs_for

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCALE = list(config.VIVEK_TP_SCALE_LONG)


@pytest.fixture(autouse=True)
def _fx_memo(tmp_path):
    bt.set_fx_path(tmp_path / "out.json")
    yield
    bt.set_fx_path(bt.OUT_FILE)


# ------------------------------------------------------------- #146 house fill

def _path(rng: random.Random, n: int, start: float):
    out, px = [], start
    for i in range(n):
        o = px * (1 + rng.gauss(0, 0.015))               # gaps through stops happen
        c = o * (1 + rng.gauss(0, 0.025))
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.012)))
        l = min(o, c) * (1 - abs(rng.gauss(0, 0.012)))
        out.append(((pd.Timestamp("2026-01-01") + pd.Timedelta(days=i)).date().isoformat(),
                    o, h, l, c))
        px = c
    return out


def _plan(rng: random.Random, entry: float):
    risk = entry * rng.uniform(0.02, 0.12)
    tps = [entry + risk * r for r in (rng.uniform(0.8, 1.5), rng.uniform(1.6, 2.6),
                                       rng.uniform(2.7, 4.0))]
    return {"stop": round(entry - risk, 8), "tp1": round(tps[0], 8), "tp2": round(tps[1], 8),
            "tp3": round(tps[2], 8), "scale": SCALE}


def _engine(bars, plan, market):
    row = {"symbol": "TST", "dir": "LONG", "grade": "A"}
    tr = _snapshot(row, "1D", plan, market, float(bars[0][1]), bars[0][0])
    if tr is None:
        return None
    costs = costs_for(market)
    for k, (d, o, h, l, c) in enumerate(bars):
        bt._manage_bar(tr, h, l, c, d, costs, is_last=(k == len(bars) - 1), open_=o)
        if tr["status"] == "closed":
            break
    return tr


def test_the_house_column_is_rmodels_resting_stop_exactly():
    """The engine's house twin == rmodel.simulate_both's HOUSE leg, and its
    worst leg is untouched -- one set of exits, two fill prices."""
    rng = random.Random("wp4b-house")
    compared = differ = 0
    for _ in range(300):
        bars = _path(rng, rng.randint(3, 40), rng.uniform(1, 100))
        plan = _plan(rng, bars[0][4])
        got = _engine(bars, plan, "nasdaq")
        house, worst = rmodel.simulate_both(lambda: iter(bars), "long", float(bars[0][1]),
                                            plan["stop"], [plan["tp1"], plan["tp2"], plan["tp3"]],
                                            plan["scale"], bars[0][0], costs=costs_for("nasdaq"))
        assert (got is None) == (house is None)
        if got is None:
            continue
        compared += 1
        assert got["realized_r"] == worst["realized_r"]
        assert got["realized_r_house"] == house["realized_r"]
        assert got["realized_r_house"] >= got["realized_r"] - 1e-12
        differ += got["realized_r_house"] != got["realized_r"]
    assert compared > 150 and differ > 20


def _long_trade(stop=95.0):
    row = {"symbol": "X", "name": "X", "sector": "", "dir": "LONG",
           "grade": "A+", "entry_types": ["reclaim"]}
    plan = {"armed": True, "entry_trigger": "reclaim", "stop": stop,
            "tp1": 110.0, "tp2": 120.0, "tp3": 130.0, "scale": SCALE}
    return _snapshot(row, "1D", plan, "asx", 100.0, "2024-01-02")


def test_a_stop_fills_at_the_stop_unless_the_bar_gapped_through_it():
    worst_only = _long_trade()
    bt._manage_bar(worst_only, 101, 90, 92, "2024-01-03", None, False, open_=99.0)
    assert worst_only["exit_reason"] == "stop"
    assert worst_only["realized_r"] == pytest.approx(-2.0)        # filled at the LOW (90)
    assert worst_only["realized_r_house"] == pytest.approx(-1.0)  # at the stop (95)
    assert worst_only["exit_price_house"] == pytest.approx(95.0)

    gapped = _long_trade()
    bt._manage_bar(gapped, 94, 90, 92, "2024-01-03", None, False, open_=93.0)
    assert gapped["realized_r_house"] == pytest.approx(-1.4)       # at the gapped open (93)


def test_a_trade_that_never_stops_has_one_fill():
    tr = _long_trade()
    bt._manage_bar(tr, 104, 99, 103, "2024-01-03", None, True, open_=100.0)  # eod close
    assert tr["exit_reason"] == "eod"
    assert tr["realized_r_house"] == tr["realized_r"]


def test_the_house_metrics_refuse_a_partial_population():
    base = {"entry": 100.0, "stop": 90.0, "risk": 10.0, "market": "nasdaq", "direction": "long"}
    a = {**base, "realized_r": -2.0, "realized_r_house": -1.0}
    b = {**base, "realized_r": 1.0, "realized_r_house": 1.0}
    m = bt._metrics([a, b])
    assert m["expectancy_r"] == -0.5 and m["expectancy_r_house"] == 0.0
    assert m["total_r_house"] == 0.0 and m["win_rate_house"] == 50.0
    legacy = {**base, "realized_r": 1.0}
    assert bt._metrics([a, legacy])["expectancy_r_house"] is None


def test_the_report_says_how_a_stop_fills():
    rep = bt.build_report([], {}, {"x": 1}, "complete")
    text = " ".join(rep["caveats"])
    assert "worst print" in text and "house" in text
    assert "adverse extreme" in bt.replay_params()["stop_fill"]


# --------------------------------------------- #31 / #138 the slim projection

def test_the_slim_record_carries_mfe_exit_price_and_the_initial_stop():
    tr = _long_trade()
    tr["initial_stop"] = tr["stop"]
    bt._manage_bar(tr, 111, 101, 110, "2024-01-03", None, False, open_=101.0)   # TP1 -> BE
    bt._manage_bar(tr, 101, 99, 99.5, "2024-01-04", None, False, open_=100.5)   # trail out
    assert tr["exit_reason"] == "trail"
    s = bt._slim(tr)
    assert s["mfe_r"] == pytest.approx(2.2)
    assert s["exit"] == pytest.approx(99.0)                 # the worst-print exit price
    assert s["stop"] == 95.0 and s["stop_final"] == pytest.approx(100.0)
    assert s["risk"] == pytest.approx(abs(s["entry"] - s["stop"]))
    assert s["realized_r_house"] is not None
    # an end-of-data close still publishes its price
    eod = _long_trade()
    bt._manage_bar(eod, 104, 99, 103, "2024-01-03", None, True, open_=100.0)
    assert bt._slim(eod)["exit"] == pytest.approx(103.0)
    assert bt._metrics([bt._slim(tr)])["mfe_zero_rate"] == 0.0


# --------------------------------------------------- #147 the candidate mask

def _walk(n, seed, freq="B", start="2020-01-01"):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq=freq)
    px = 50 * np.cumprod(1 + rng.normal(0, 0.012, n))
    return pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99, "Close": px,
                         "Volume": 1e6}, index=idx)


@pytest.mark.parametrize("freq,n", [("B", 700), ("D", 1100)])
def test_the_mask_reads_the_engines_own_levels(freq, n):
    """Weekly: the PROXY from VIVEK_MIN_WEEKLY_BARS (700 business days is
    ~140 weeks, so a 200-rolling mask was blind to all of it). 3D: the
    partial bucket ending at the bar, never a later close."""
    df = _walk(n, 7, freq)
    w = bt._htf_sma_each_bar(df["Close"], "W-FRI", config.VIVEK_SMA, config.VIVEK_MIN_WEEKLY_BARS)
    s3 = bt._htf_sma_each_bar(df["Close"], "72h", config.VIVEK_SMA, config.VIVEK_SMA, origin="epoch")
    seen_w = seen_3 = 0
    for j in range(config.VIVEK_MIN_HISTORY, n, 23):
        want_w, _ = vivek._weekly_sma200(df.iloc[:j + 1])
        d3 = vivek._resample_3day_ohlc(df.iloc[:j + 1])
        want_3 = float(sma(d3["Close"], config.VIVEK_SMA).iloc[-1]) if len(d3) >= config.VIVEK_SMA else None
        for want, got in ((want_w, w[j]), (want_3, s3[j])):
            if want is None:
                assert np.isnan(got)
            else:
                assert got == pytest.approx(want, rel=1e-9)
        seen_w += want_w is not None
        seen_3 += want_3 is not None
    assert seen_w > 5
    if freq == "D":
        assert seen_3 > 5


def test_the_mask_never_reads_a_later_bar():
    """Truncating the frame at k must not move any level (or mask bit) before
    k. The 3D leg used to label each bucket by its START and forward-fill it,
    so a bucket's first day read the close two bars ahead."""
    df = _walk(900, 3, "D")
    full = bt._candidate_mask(df)
    levels = bt._candidate_levels(df)
    assert np.isfinite(levels[2]).sum() > 100              # the 3D leg is live here
    for k in range(650, 900, 17):
        assert (bt._candidate_mask(df.iloc[:k]) == full[:k]).all(), k
        for got, want in zip(bt._candidate_levels(df.iloc[:k]), levels):
            np.testing.assert_allclose(got, want[:k], rtol=1e-12, equal_nan=True)


def test_a_bar_near_the_proxied_weekly_level_is_a_candidate():
    """Every bar where the engine's (proxied) weekly 200 is in play is handed
    to evaluate() -- the superset the docstring promises."""
    df = _walk(700, 11)
    mask = bt._candidate_mask(df)
    hits = 0
    for j in range(config.VIVEK_MIN_HISTORY, len(df)):
        lvl, _ = vivek._weekly_sma200(df.iloc[:j + 1])
        px = float(df["Close"].iloc[j])
        if lvl and abs(px - lvl) / px <= config.VIVEK_NEAR_TOL:
            hits += 1
            assert mask[j], j
    assert hits > 0


# ------------------------------------------------------ #156 stop cooldown

def _scripted(monkeypatch, n_after=40, stop_bar=10):
    """A frame + an engine stub that arms the same 1D plan on every bar;
    the trade stops out `stop_bar` bars after the first fill."""
    n = config.VIVEK_MIN_HISTORY + n_after
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    o = np.full(n, 100.0)
    h, l, c = o + 1, o - 1, o.copy()
    k = config.VIVEK_MIN_HISTORY + 1 + stop_bar
    l[k] = 90.0
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 1e6}, index=idx)
    plan = {"armed": True, "entry_trigger": "break", "stop": 95.0, "tp1": 110.0,
            "tp2": 120.0, "tp3": 130.0, "scale": SCALE}
    row = {"symbol": "S", "name": "S", "sector": "", "dir": "LONG", "grade": "A+",
           "entry_types": ["break"], "level_tf": "weekly"}
    monkeypatch.setattr(bt, "_candidate_mask", lambda d: np.ones(len(d), dtype=bool))
    monkeypatch.setattr(vivek, "evaluate", lambda d, *a, **kw: {"direction": "long"})
    monkeypatch.setattr(bt, "_build_row", lambda *a, **kw: (row, {"1D": plan}, "A+"))
    return df, idx[k].date()


def test_the_replay_waits_out_the_cooldown_after_a_stop(monkeypatch):
    df, stop_day = _scripted(monkeypatch)
    stats: dict = {}
    trades = bt.replay_symbol(df, "nasdaq", "S", "S", "", cooldown=7, stats=stats)
    first, second = trades[0], trades[1]
    assert first["exit_reason"] == "stop" and first["exit_date"] == stop_day.isoformat()
    # detection resumes on the first bar dated AFTER exit + 7, filling a bar later
    gap = (pd.Timestamp(second["entry_date"]).date() - stop_day).days
    assert gap == 9
    assert stats["cooldown_blocked"] == 8          # the stop bar + seven days, one 1D plan each


def test_cooldown_zero_is_the_old_replay(monkeypatch):
    df, stop_day = _scripted(monkeypatch)
    trades = bt.replay_symbol(df, "nasdaq", "S", "S", "", cooldown=0)
    gap = (pd.Timestamp(trades[1]["entry_date"]).date() - stop_day).days
    assert gap == 1                                # re-entered at the next open
    assert bt.cooldown_days() == config.VIVEK_BOT_REENTRY_COOLDOWN_DAYS


# ---------------------------------------------------------- #149 level gate

def _cell_trade(sym, level_tf, r=1.0, **kw):
    t = {"symbol": sym, "market": "asx", "grade": "A+", "entry_type": "break",
         "direction": "long", "timeframe": "1D", "sector": f"s-{sym}", "level_tf": level_tf,
         "entry": 100.0, "stop": 90.0, "risk": 10.0, "entry_date": "2026-01-05",
         "exit_date": "2026-02-01", "exit_reason": "target", "realized_r": r}
    t.update(kw)
    return t


def test_portfolio_sim_applies_the_live_level_gate_fail_closed():
    trades = [_cell_trade("W", "weekly"), _cell_trade("T", "3d"), _cell_trade("H", "h4"),
              _cell_trade("B", ""), _cell_trade("N", None), _cell_trade("U", " Weekly ")]
    r = bt.portfolio_sim(trades)
    assert r["taken"] == 3 and r["level_gated"] == 3
    assert r["params"]["level_tf_allow"] == list(config.VIVEK_BOT_LEVEL_TF_ALLOW)
    assert "level_gate" in r["params"]["simulated_gates"]


def test_the_cell_evidence_is_split_by_the_level_gate():
    rep = bt.aggregate([_cell_trade("W", "weekly", 1.0), _cell_trade("H", "h4", -1.0)])
    split = rep["by_conviction_cell_long_level"]
    assert split["bot_level"]["1D break"]["n"] == 1
    assert split["bot_level"]["1D break"]["total_r"] == 1.0
    assert split["other_level"]["1D break"]["total_r"] == -1.0
    assert rep["by_conviction_cell_long"]["1D break"]["n"] == 2       # unchanged, additive
    assert set(split["bot_level"]) == set(conviction.cell_names())


# ------------------------------------------------- #154 crypto data source

def _calls(rel: str, name: str) -> int:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    return sum(1 for node in ast.walk(tree) if isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Name) and node.func.id == name)
        or (isinstance(node.func, ast.Attribute) and node.func.attr == name)))


@pytest.mark.parametrize("rel", ["scanner/vivek_backtest.py", "scanner/vivek_parity.py"])
def test_the_replays_price_through_fetch_never_bare_download(rel):
    """The crypto-source-switch caller pin, extended to the two replays: a
    bare `download` would replay crypto on Yahoo's aggregate (and, for
    colliding tickers, a different token)."""
    assert _calls("scanner/vivek_backtest.py", "fetch") >= 1
    assert _calls(rel, "download") == 0, rel
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert "fetch_market_frames(" in src, rel


def test_the_replay_arms_the_identity_check_and_reports_its_sources(monkeypatch):
    from scanner import data, universe
    uni = [{"yf": "AAA-USD", "symbol": "AAA", "name": "Aaa", "sector": "", "cg_price": 2.0},
           {"yf": "BBB-USD", "symbol": "BBB", "name": "Bbb", "sector": "", "cg_price": 3.0}]
    seen = {}

    def fake_fetch(mk, tickers, period=None, **kw):
        seen.update(mk=mk, tickers=list(tickers), period=period, **kw)
        return {}, {"mode": "exchange", "by_source": {"binance_vision": 1}, "refused": ["BBB-USD"],
                    "identity_rejected": {"BBB": ["yahoo"]}, "stale_rejected": {},
                    "yahoo_fallback": 0, "unchecked": 0}

    monkeypatch.setattr(universe, "load_universe", lambda mk, full=True: uni)
    monkeypatch.setattr(data, "fetch", fake_fetch)
    trades, cov = bt.run_market_trades("crypto", None, "5y")
    assert seen["mk"] == "crypto" and seen["ref_prices"] == {"AAA-USD": 2.0, "BBB-USD": 3.0}
    assert cov["data_sources"]["mode"] == "exchange" and cov["data_sources"]["refused"] == 1
    assert cov["cooldown_blocked"] == 0 and trades == []
    assert "exchange daily klines" in bt.data_source_caveat()
