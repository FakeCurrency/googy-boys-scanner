"""The shared-equity portfolio replay (scanner/turtle_portfolio.py).

The per-name replay cannot answer "would $5,000 have made money" -- every
name walks with its own private equity, so nothing competes for slots, cash,
margin or unit ceilings. These tests pin the properties that make the
portfolio walk a different (and honest) instrument: one equity everyone
shares, deterministic same-day ordering, the vehicle constraint binding
exactly as the forward book enforces it, and a payload that says what it is
NOT (walk-forward, a forward record, the Turtle return).
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import pandas as pd
import pytest

from scanner import config, turtle_portfolio as tp

ROOT = pathlib.Path(__file__).resolve().parents[1]


def frame(mids, opens=None):
    """The engine-test band: True Range exactly 2 while mids step by <= 1,
    so N is exactly 2.0 and every stop and unit below is hand-checkable."""
    mids = np.asarray(mids, dtype="float64")
    ops = mids if opens is None else np.asarray(opens, dtype="float64")
    return pd.DataFrame(
        {"Open": ops, "High": mids + 1.0, "Low": mids - 1.0, "Close": mids,
         "Volume": np.full(len(mids), 5e7)},
        index=pd.bdate_range("2015-01-01", periods=len(mids)),
    )


FLAT = [100.0] * 260


# ---------------------------------------------------------------------------
# the property the per-name replay cannot have: ONE equity
# ---------------------------------------------------------------------------

def test_a_loss_anywhere_shrinks_the_next_unit_everywhere():
    """Symbol A breaks out, gaps through its stop and realises a loss; symbol
    B breaks out LATER and must be sized off the post-loss equity. In the
    per-name replay B would never know A existed -- that ignorance is exactly
    what this module exists to remove."""
    a = frame(FLAT + [103.0, 95.0] + [95.0] * 12)
    b = frame(FLAT + [100.0] * 6 + [103.0, 95.0] + [95.0] * 6)
    r = tp.replay_sleeve({"A": a, "B": b}, market="crypto",
                         equity_start=5000.0, keep_trades=True)
    assert r["trades"] == 2
    trades = sorted(r["trade_rows"], key=lambda t: t["exit_date"])
    # units back out of the record exactly: r = pnl / (2N * units)
    ua = trades[0]["pnl"] / (trades[0]["r"] * 2.0 * 2.0)
    ub = trades[1]["pnl"] / (trades[1]["r"] * 2.0 * 2.0)
    assert ua == pytest.approx(0.01 * 5000.0 / 2.0, rel=1e-3), \
        "A sized off the fresh account: 25 units"
    eq_after_a = trades[0]["equity_after"]
    assert eq_after_a < 5000.0
    assert ub == pytest.approx(0.01 * eq_after_a / 2.0, rel=1e-3), \
        "B sized off what A LEFT, not off a private $5,000"


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------

def test_two_identical_runs_produce_identical_results():
    a = frame(FLAT + [103.0] + [104.0] * 10)
    b = frame(FLAT + [103.0] + [104.0] * 10)
    r1 = tp.replay_sleeve({"A": a, "B": b}, market="crypto",
                          equity_start=5000.0)
    r2 = tp.replay_sleeve({"A": frame(FLAT + [103.0] + [104.0] * 10),
                           "B": frame(FLAT + [103.0] + [104.0] * 10)},
                          market="crypto", equity_start=5000.0)
    assert r1 == r2


def test_the_declared_ordering_decides_the_last_slot():
    """Two identical breakouts, cash for one: the higher-dollar-volume name
    takes the slot, by declaration -- not by dict order."""
    hi = frame(FLAT + [103.0] + [103.0] * 5)
    lo_ = frame(FLAT + [103.0] + [103.0] * 5)
    lo_["Volume"] = 1e7          # a fifth of hi's volume
    r = tp.replay_sleeve({"AAA": lo_, "ZZZ": hi}, market="crypto",
                         equity_start=5000.0)
    assert r["open_at_end"]["positions"] == 1
    assert r["open_at_end"]["symbols"] == ["ZZZ"], \
        "the higher-volume name takes the slot, alphabet be damned"
    assert r["refused_units"].get("cash", 0) >= 1
    assert "dollar volume desc" in r["ordering"]
    # swap the volumes: the OTHER symbol must win, proving volume decides
    hi2 = frame(FLAT + [103.0] + [103.0] * 5)
    lo2 = frame(FLAT + [103.0] + [103.0] * 5)
    lo2["Volume"] = 1e7
    r2 = tp.replay_sleeve({"AAA": hi2, "ZZZ": lo2}, market="crypto",
                          equity_start=5000.0)
    assert r2["open_at_end"]["symbols"] == ["AAA"]


# ---------------------------------------------------------------------------
# the vehicle constraint, per sleeve
# ---------------------------------------------------------------------------

def test_margin_admits_what_cash_refuses_on_the_same_tape():
    """The B-lane thesis as arithmetic: two ~$2,500 units on a $5,000 book.
    Cash takes one and refuses the second; 5x posts ~$500 each and takes
    both. Same tape, same rules, different vehicle."""
    a = frame(FLAT + [103.0] + [103.5] * 5)
    b = frame(FLAT + [103.0] + [103.5] * 5)
    cash = tp.replay_sleeve({"A": a, "B": b}, market="crypto",
                            equity_start=5000.0)
    lev = tp.replay_sleeve({"A": frame(FLAT + [103.0] + [103.5] * 5),
                            "B": frame(FLAT + [103.0] + [103.5] * 5)},
                           market="crypto", equity_start=5000.0,
                           leverage=5.0)
    assert cash["open_at_end"]["positions"] == 1
    assert cash["refused_units"].get("cash", 0) >= 1
    assert lev["open_at_end"]["positions"] == 2
    assert lev["refused_units"].get("cash", 0) == 0
    assert lev["refused_units"].get("no_margin", 0) == 0
    assert lev["leverage"] == 5.0


def test_seven_same_day_breakouts_stop_at_the_six_unit_bucket():
    frames = {f"C{i}": frame(FLAT + [103.0] + [103.5] * 5) for i in range(7)}
    r = tp.replay_sleeve(frames, market="crypto", equity_start=5000.0,
                         leverage=5.0)
    assert r["open_at_end"]["units"] == config.TURTLE_MAX_UNITS_CLOSE_CORR
    assert r["refused_units"].get("close_corr_cap", 0) >= 1


def test_futures_without_a_margin_file_trade_NOTHING_and_say_why():
    frames = {"FUT": frame(FLAT + [103.0] + [103.5] * 5)}
    contracts = {"FUT": {"dpp": 1000, "micro": "MFT", "micro_dpp": 5,
                         "group": "energy"}}
    r = tp.replay_sleeve(frames, market="futures", equity_start=5000.0,
                         contracts=contracts, margins=None)
    assert r["trades"] == 0 and r["open_at_end"]["positions"] == 0
    assert r["refused_units"].get("no_margin_file", 0) >= 1, \
        "the empty sleeve must wear its reason"


def test_futures_with_a_real_margin_file_take_whole_contracts():
    frames = {"FUT": frame(FLAT + [103.0] + [103.5] * 5)}
    contracts = {"FUT": {"dpp": 1000, "micro": "MFT", "micro_dpp": 5,
                         "group": "energy"}}
    margins = {"contracts": {"FUT": {"initial": 500.0}}}
    r = tp.replay_sleeve(frames, market="futures", equity_start=5000.0,
                         contracts=contracts, margins=margins)
    assert r["open_at_end"]["positions"] == 1, \
        "unit = int(50 / (2*5)) = 5 micro contracts -- fits and opens"
    assert r["refused_units"].get("unit_lt_one", 0) == 0


def test_a_roll_suspect_in_the_N_window_blocks_the_futures_entry():
    mids = FLAT + [103.0] + [103.5] * 5
    opens = list(mids)
    opens[258] = 250.0            # a 150-point gap on a 2-point range bar
    frames = {"FUT": frame(mids, opens=opens)}
    contracts = {"FUT": {"dpp": 1000, "micro": "MFT", "micro_dpp": 5,
                         "group": "energy"}}
    margins = {"contracts": {"FUT": {"initial": 500.0}}}
    r = tp.replay_sleeve(frames, market="futures", equity_start=5000.0,
                         contracts=contracts, margins=margins)
    assert r["refused_units"].get("roll_window", 0) >= 1, \
        "a contaminated N refuses the open instead of mispricing it"


# ---------------------------------------------------------------------------
# engine law carried over
# ---------------------------------------------------------------------------

def test_the_entry_bar_checks_its_own_stop():
    """A bar that breaks out and then trades 2N against it books the loss on
    the entry bar -- the engine's 2026-08-21 rule, inherited whole."""
    mids = FLAT + [100.0]
    df = frame(mids)
    # hand-build the breakout bar: opens at 100, breaks 101, craters to 94
    df.loc[df.index[-1], "High"] = 103.0
    df.loc[df.index[-1], "Low"] = 94.0
    df.loc[df.index[-1], "Close"] = 95.0
    r = tp.replay_sleeve({"A": df}, market="crypto", equity_start=5000.0)
    assert r["trades"] == 1 and r["open_at_end"]["positions"] == 0
    assert r["total_r"] < 0, "the entry-bar stop books a real loss"


def test_liquidation_caps_the_loss_at_the_posted_margin():
    """Fat-N tape (2N wider than the 20% posted margin) on the levered
    sleeve: the liquidation line is hit first, the fill is AT the liq price
    (isolated margin cannot lose more than it posted -- a daily-bar gap
    through the line is a sampling artefact on a continuous market), and the
    realised loss is the posted margin plus costs, no more."""
    lev = tp.replay_sleeve(
        {"A": _fat_breakout()}, market="crypto", equity_start=5000.0,
        leverage=5.0, keep_trades=True)
    liq = [t for t in lev["trade_rows"] if t["reason"] == "liquidation"]
    assert liq, "the fat-N tape must produce a liquidation, not a stop"
    t = liq[0]
    # entry: fill 130 (gap open above the 112 channel), N=24, unit
    # 0.01*5000/24 units; posted = notional/5; liq = avg - posted/units
    # = 130 - 26 = 104. pnl = -(posted + fees), never the gap to 70.
    units = 0.01 * 5000.0 / 24.0
    posted = (130.0 * units) / 5.0
    assert t["pnl"] == pytest.approx(-(posted
                                       + 130.0 * units * 0.0015
                                       + 104.0 * units * 0.0015), rel=1e-3), \
        "the loss is posted margin plus the two cost legs -- capped"


def _fat_breakout():
    """A frame whose N is fat (12) at the breakout: TR 24 band."""
    mids = np.asarray([100.0] * 260 + [130.0, 70.0] + [70.0] * 5)
    df = pd.DataFrame(
        {"Open": mids, "High": mids + 12.0, "Low": mids - 12.0, "Close": mids,
         "Volume": np.full(len(mids), 5e7)},
        index=pd.bdate_range("2015-01-01", periods=len(mids)))
    return df


# ---------------------------------------------------------------------------
# the payload says what it is NOT
# ---------------------------------------------------------------------------

def test_the_payload_carries_its_own_caveat_and_schema():
    r = tp.replay_sleeve({"A": frame(FLAT + [100.0] * 5)}, market="crypto",
                         equity_start=5000.0)
    for key in ("equity_start", "equity_realized", "equity_marked",
                "return_pct_marked", "max_dd_pct_marked", "trades", "wins",
                "win_pct", "total_r", "mean_r", "median_r", "top10_share",
                "refused_units", "open_at_end", "ordering", "caveat",
                "universe_size", "leverage", "fees_paid"):
        assert key in r, f"payload missing {key}"
    for word in ("not walk-forward", "not a forward record"):
        assert word in r["caveat"].lower(), \
            "the caveat must say what this is NOT"


def test_write_sleeves_merges_and_never_drops_a_sibling(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "OUT_PATH", str(tmp_path / "turtle_portfolio.json"))
    tp.write_sleeves({"asx_5k_cash": {"trades": 1}})
    tp.write_sleeves({"crypto_5x_5k": {"trades": 2}})
    d = json.loads((tmp_path / "turtle_portfolio.json").read_text("utf-8"))
    assert set(d["sleeves"]) == {"asx_5k_cash", "crypto_5x_5k"}, \
        "a crypto run must not drop the ASX sleeve it did not compute"
    assert d["caveat"] and d["ordering"]


# ---------------------------------------------------------------------------
# fences
# ---------------------------------------------------------------------------

def test_the_portfolio_module_writes_only_its_own_file():
    src = (ROOT / "scanner" / "turtle_portfolio.py").read_text("utf-8")
    assert src.count("output.write_json(") == 1
    assert "turtle_portfolio.json" in src
    for forbidden in ("vivek_bot_book", "bot_rules", "sector_map",
                      "journal/", "alert_history"):
        assert forbidden not in src, f"the portfolio replay touches {forbidden}"


def test_the_portfolio_module_never_imports_the_bot():
    src = (ROOT / "scanner" / "turtle_portfolio.py").read_text("utf-8")
    for ln in src.splitlines():
        if ln.strip().startswith(("import ", "from ")):
            assert "broker" not in ln and "vivek" not in ln.lower(), \
                f"the portfolio replay imports the bot: {ln}"
