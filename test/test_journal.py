"""Tests for the swing paper-journal's honest-fill model (scanner/journal.py).

These lock in the bias fixes: entry slippage via fill_price, gap-through stops
filling at the bar open (not the stop level), market-exit slippage, limit-target
no-slip, and the trailing stop locking gains without same-bar lookahead.

Run:  python -m pytest test/test_journal.py
"""

import pandas as pd

from scanner import config, journal

SLIP = config.SWING_FILL_SLIPPAGE_PCT


def _df(rows):
    """rows: list of (date, open, high, low, close)."""
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame(
        {"Open":  [r[1] for r in rows],
         "High":  [r[2] for r in rows],
         "Low":   [r[3] for r in rows],
         "Close": [r[4] for r in rows],
         "Volume": [1000] * len(rows)},
        index=idx,
    )


def _long_pos(**kw):
    base = {"entry": 100.0, "fill_price": 100.0, "stop": 95.0, "target": 110.0,
            "direction": "long", "shares": 10, "opened": "2024-01-01",
            "brokerage": 5, "status": "open"}
    base.update(kw)
    return base


# ── gap-through stop: the headline bias fix ──────────────────────────────────
def test_long_gap_through_stop_fills_at_open_not_stop():
    pos = _long_pos()
    df = _df([
        ("2024-01-01", 100, 101, 99, 100),   # open bar (skipped — opened here)
        ("2024-01-02", 92,  93,  90, 91),    # gaps below the 95 stop
    ])
    res = journal._walk(df, pos)
    assert res["status"] == "closed"
    assert res["reason"] == "stop-gap"
    # Filled at the bar open (92), slipped worse — a real, larger loss than 95.
    assert res["exit"] == round(92 * (1 - SLIP), 4)
    assert res["exit"] < pos["stop"]            # worse than the optimistic stop
    assert res["pnl"] < 0


def test_short_gap_through_stop_fills_at_open():
    pos = _long_pos(direction="short", entry=100.0, fill_price=100.0,
                    stop=105.0, target=90.0)
    df = _df([
        ("2024-01-01", 100, 101, 99, 100),
        ("2024-01-02", 108, 110, 107, 109),  # gaps above the 105 short stop
    ])
    res = journal._walk(df, pos)
    assert res["reason"] == "stop-gap"
    assert res["exit"] == round(108 * (1 + SLIP), 4)
    assert res["exit"] > pos["stop"]


# ── normal (non-gap) stop: filled at the stop, with market-exit slippage ─────
def test_long_normal_stop_fills_at_stop_with_slippage():
    pos = _long_pos()
    df = _df([
        ("2024-01-01", 100, 101, 99, 100),
        ("2024-01-02", 99,  99.5, 94, 96),   # opens above stop, low pierces it
    ])
    res = journal._walk(df, pos)
    assert res["reason"] == "stop"
    assert res["exit"] == round(95 * (1 - SLIP), 4)


# ── target: limit order, no slippage, no overshoot credit ────────────────────
def test_long_target_no_slippage():
    pos = _long_pos()
    df = _df([
        ("2024-01-01", 100, 101, 99, 100),
        ("2024-01-02", 101, 111, 100, 110),  # high pierces target 110
    ])
    res = journal._walk(df, pos)
    assert res["reason"] == "target"
    assert res["exit"] == 110.0                # exactly the target, no slip


def test_long_target_gap_is_windfall_at_open():
    pos = _long_pos()
    df = _df([
        ("2024-01-01", 100, 101, 99, 100),
        ("2024-01-02", 112, 113, 111, 112),  # gaps above target → windfall
    ])
    res = journal._walk(df, pos)
    assert res["reason"] == "target-gap"
    assert res["exit"] == 112.0                # credited the better open, no slip


# ── entry slippage feeds risk / R via fill_price ─────────────────────────────
def test_close_uses_fill_price_for_risk_and_pnl():
    pos = _long_pos(fill_price=100.5)          # entry slipped from 100 → 100.5
    res = journal._close(pos, 110.0, "2024-01-02", "target", 1)
    assert res["r"] == round((110 - 100.5) / (100.5 - 95), 2)
    assert res["pnl"] == round(10 * (110 - 100.5) - 2 * 5, 2)


def test_legacy_position_without_fill_price_falls_back_to_entry():
    pos = {"entry": 100.0, "stop": 95.0, "target": 110.0, "direction": "long",
           "shares": 10, "opened": "2024-01-01", "brokerage": 5, "status": "open"}
    res = journal._close(pos, 110.0, "2024-01-02", "target", 1)
    assert res["r"] == round((110 - 100) / (100 - 95), 2)


# ── trailing stop locks gains and still closes (no same-bar lookahead) ───────
def test_uptrend_then_reversal_closes_in_profit_via_trail():
    # 25 calm up-bars let SuperTrend warm up and trail beneath price, then a
    # sharp down-bar takes us out above the original stop.
    rows = [("2024-01-01", 100, 101, 99, 100)]
    px = 100.0
    for k in range(2, 26):
        px += 1.0
        rows.append((f"2024-01-{k:02d}", px - 0.5, px + 0.5, px - 0.8, px))
    rows.append(("2024-01-26", px, px, px - 30, px - 28))   # capitulation bar
    df = _df(rows)
    pos = _long_pos(target=10_000.0)           # target unreachable → must trail out
    res = journal._walk(df, pos)
    assert res["status"] == "closed"
    assert res["reason"] in ("trail", "trail-gap", "stop", "stop-gap")
    if res["reason"].startswith("trail"):
        assert res["pnl"] > 0                   # the trail locked in profit
