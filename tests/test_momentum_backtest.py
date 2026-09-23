"""scanner/momentum/backtest.py + run.py --backtest -- the momentum replay.

Driven over the COMMITTED daily bars in data/history/asx/, so these tests are
about real series without a network. They pin four things a backtest must not
get wrong: the plan is the owner's box (ELS to the cent), there is no
look-ahead (a truncated replay agrees with the full one), the signals are the
SCREEN's (Rule B's live score gate, the warm-up, the gates as of that day), and
the published payload adds up.
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd
import pytest

from scanner.momentum import backtest as bt
from scanner.momentum import config
from scanner.momentum import run as R
from scanner.momentum.screen import evaluate

ROOT = pathlib.Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "history" / "asx"


def _frame(symbol: str) -> pd.DataFrame:
    bars = json.loads((HIST / f"{symbol}.json").read_text(encoding="utf-8"))["bars"]
    f = pd.DataFrame(bars, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    f.index = pd.to_datetime(f.pop("Date"))
    return f


def _some(n: int = 25):
    return sorted(p.stem for p in HIST.glob("*.json"))[:n]


def test_the_box_is_the_owners_tradingview_plan_on_ELS():
    """The 2026-07-27 bear cross on ELS: TradingView draws Entry 5.88 / SL 6.76
    / TP1 5.00 / TP2 4.12 / TP3 3.23, and momentum.test.js pins chart.js to
    the same numbers. The replay must trade the SAME box."""
    ev = evaluate(_frame("ELS"))
    j = list(ev.index.strftime("%Y-%m-%d")).index("2026-07-27")
    b = bt.box(ev, j, "short")
    want = (5.88, 6.762, 4.998, 4.116, 3.234)
    got = (b["entry"], b["stop"], *b["targets"])
    assert all(abs(g - w) <= 0.01 for g, w in zip(got, want)), got
    assert b["capped"] and b["raw_stop"] > 7.6, "the 15% cap binds, as on the chart"
    trades, _ = bt.replay_symbol(_frame("ELS"), "asx", symbol="ELS", name="Elsight Limited")
    els = [t for t in trades if t["signal_date"] == "2026-07-27"]
    assert len(els) == 1 and els[0]["rule"] == "B" and els[0]["direction"] == "short"
    assert els[0]["score"] == 2


@pytest.mark.parametrize("symbol", ["ELS", "BHP", "CBA"])
def test_no_look_ahead_a_truncated_replay_agrees_with_the_full_one(symbol):
    if not (HIST / f"{symbol}.json").exists():
        pytest.skip(f"no committed history for {symbol}")
    full = _frame(symbol)
    cut = full.index[int(len(full) * 0.85)]
    a, _ = bt.replay_symbol(full, "asx", symbol=symbol)
    b, _ = bt.replay_symbol(full.loc[:cut], "asx", symbol=symbol)
    # strictly BEFORE the cut: the truncated replay force-closes whatever is
    # still open on its last bar, and that mark is not a real exit
    closed_before = lambda ts: [t for t in ts if pd.Timestamp(t["exit_date"]) < cut]
    assert closed_before(a) == closed_before(b)
    assert len(closed_before(a)) > 0, "the comparison must cover real trades"


def test_rule_b_uses_the_screens_score_gate_and_the_warm_up_is_skipped():
    for sym in _some():
        f = _frame(sym)
        trades, _ = bt.replay_symbol(f, "asx", symbol=sym)
        ev = evaluate(f)
        first_live = ev.index[config.DEFAULTS.warn_bars].strftime("%Y-%m-%d") \
            if len(ev) > config.DEFAULTS.warn_bars else "9999"
        for t in trades:
            assert t["signal_date"] >= first_live, (sym, t["signal_date"])
            if t["rule"] == "B":
                assert t["score"] >= config.DEFAULTS.min_signal_score, t


def test_the_gates_apply_as_of_the_signal_day():
    """A product is gated on every signal; a real name is not, and every
    gated signal is COUNTED by reason rather than silently dropped."""
    f = _frame("ELS")
    trades, gated = bt.replay_symbol(f, "asx", symbol="ELS", name="Elsight Limited")
    none, gated_p = bt.replay_symbol(f, "asx", symbol="ELS", name="Elsight Cash ETF")
    assert trades and none == []
    assert gated_p.get("non-operating listing", 0) > 0


def test_a_stop_inside_the_spread_is_not_a_trade():
    """AAA is a cash ETF; its box stop sits ~0.007% from entry and costs alone
    made each such trade about -20R. With no name (so no product gate) the
    house minimum stop still refuses every one of them."""
    if not (HIST / "AAA.json").exists():
        pytest.skip("no committed AAA history")
    trades, gated = bt.replay_symbol(_frame("AAA"), "asx", symbol="AAA")
    assert all(abs(t["entry"] - t["stop"]) / t["entry"] * 100 >= config.BT_MIN_STOP_PCT
               for t in trades)
    assert gated.get("stop_too_tight", 0) > 0


def test_the_published_backtest_adds_up(tmp_path, monkeypatch):
    rows, frames = [], {}
    for sym in _some(12):
        rows.append({"yf": f"{sym}.AX", "symbol": sym, "name": f"{sym} Ltd", "sector": ""})
        frames[f"{sym}.AX"] = _frame(sym)
    payload = R.backtest_market("asx", rows=rows, frames=frames)
    s = payload["summary"]
    streams = ("rule_a_long", "rule_a_short", "rule_b_long", "rule_b_short")
    assert s["all"]["trades"] == sum(s[k]["trades"] for k in streams) > 0
    assert abs(s["all"]["net_r"] - (s["all"]["r_won"] + s["all"]["r_lost"])) < 0.02
    assert s["long"]["trades"] + s["short"]["trades"] == s["all"]["trades"]
    assert s["all"]["notional"] == config.BT_NOTIONAL
    assert len(payload["recent"]) <= config.BT_RECENT_TRADES
    assert all(t["closed_by"] != "eod" for t in payload["recent"])
    # open-at-end is counted from HOW a trade closed, recounted independently
    recount = sum(1 for yf, fr in frames.items()
                  for t in bt.replay_symbol(fr, "asx", symbol=yf, name="x Ltd")[0]
                  if t["closed_by"] == "eod")
    assert s["all"]["open_at_end"] == recount > 0
    assert payload["coverage"]["replayed"] == 12 and payload["bt_version"] == config.BT_VERSION
    assert payload["model"]["stop"]["fill"] == config.BT_STOP_FILL
    monkeypatch.setattr(R, "OUT_DIR", tmp_path)
    path = R.publish_backtest("asx", payload)
    assert path.name == "asx_backtest.json"
    assert json.loads(path.read_text(encoding="utf-8"))["summary"]["all"] == s["all"]


def test_no_data_keeps_the_previous_file():
    assert R.backtest_market("asx", rows=[{"yf": "X.AX", "symbol": "X"}], frames={}) is None


def test_the_cli_exits_3_on_no_data_and_never_publishes(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "OUT_DIR", tmp_path)
    monkeypatch.setattr(R, "backtest_market", lambda *a, **k: None)
    assert R.main(["--market", "asx", "--backtest"]) == 3
    assert list(tmp_path.iterdir()) == []
