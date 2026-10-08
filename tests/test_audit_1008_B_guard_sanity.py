"""Audit 2026-10-08 #11: the runner's loss guard must read the mark-sanity verdict.

`_mark_sanity` freezes a held position whose observed price moved beyond
VIVEK_MARK_SANITY_PCT (a split, a consolidation, a vendor bad print) so that,
in its own docstring's words, "the loss guard reads no lie". But run_market
handed `vivek_guard.check` the RAW `price_of` (the frame's last close), so the
guard valued the frozen position at exactly the print the sanity guard had just
rejected: a 10:1 split on one held name read as a -$13,500 day and halted new
entries; a 1:10 consolidation read as a +$22,500 day and hid a real breach on
the rest of the book. A frozen position now reaches the guard UNPRICED, which
values it at its own stop (the TOP100 #15 fail-closed path).

These drive the shipped run_market end to end on an isolated book.
"""

import datetime as dt
import json
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scanner import config, data
from scanner.broker import vivek_run as vr

pytestmark = pytest.mark.risk

# Tuesday, mid-session in Sydney. Every frame below ends on this date.
NOW = dt.datetime(2024, 1, 2, 11, 0, tzinfo=ZoneInfo("Australia/Sydney"))
CLOSED = dt.datetime(2024, 1, 2, 18, 0, tzinfo=ZoneInfo("Australia/Sydney"))


def _frame(close, end="2024-01-02"):
    idx = pd.date_range(end=end, periods=5, freq="D")
    return pd.DataFrame({"Open": close, "High": close, "Low": close,
                         "Close": close, "Volume": 1e6}, index=idx)


def _held(symbol, entry=100.0, stop=96.0, risk_usd=600.0):
    risk = entry - stop
    return {"id": f"{symbol}-1", "symbol": symbol, "name": symbol, "sector": "",
            "market": "asx", "direction": "long", "grade": "A+",
            "entry_type": "break", "timeframe": "1D",
            "entry": entry, "stop": stop,
            "tp1": entry + 1.5 * risk, "tp2": entry + 3 * risk, "tp3": entry + 5 * risk,
            "scale": list(config.VIVEK_TP_SCALE_LONG), "risk": risk, "rr": 3.0,
            "trigger_bar": None, "entry_date": "2024-01-01",
            "opened_at": "2024-01-01T00:00:00+00:00", "status": "open",
            "tp1_hit": False, "tp2_hit": False, "tp3_hit": False, "booked_pct": 0.0,
            "realized_r": 0.0, "gross_r": 0.0, "cost_r": 0.0, "exits": [],
            "mae": entry, "mfe": entry, "mae_r": 0.0, "mfe_r": 0.0,
            "entry_type_label": "reclaim", "units": 25.0, "notional": 2500.0,
            "risk_usd": risk_usd, "last_mark": entry}


def _run(tmp_path, monkeypatch, positions, closes, now=NOW):
    monkeypatch.setattr(vr, "BOOK_DIR", tmp_path)
    monkeypatch.setattr(vr, "BOOK_FILE", tmp_path / "vivek_bot_book.json")
    monkeypatch.setattr(vr, "UNASSIGNED_FILE", tmp_path / "vivek_bot_book.unassigned.json")
    monkeypatch.setattr(vr, "PUBLIC_FILE", tmp_path / "public_book.json")
    monkeypatch.setattr(config, "VIVEK_BOT_ENABLED", True)
    monkeypatch.setattr(config, "VIVEK_BOT_DRY_RUN", False)
    monkeypatch.setattr(data, "fetch", lambda *a, **k: ({}, {}))   # no network
    (tmp_path / "vivek_bot_book.asx.json").write_text(json.dumps(
        {"version": 2, "mode": "paper", "market": "asx",
         "open": positions, "closed": []}), encoding="utf-8")
    frames = {f"{s}.AX": _frame(c) for s, c in closes.items()}
    uni = [{"symbol": s, "yf": f"{s}.AX"} for s in closes]
    bk = vr.run_market("asx", [], frames, uni, now=now)
    return bk, bk["guard"]["asx"]


def test_a_split_the_sanity_guard_froze_does_not_fake_a_breach(tmp_path, monkeypatch):
    # A 10:1 split: last accepted mark 100, the adjusted frame now reads 10.
    bk, guard = _run(tmp_path, monkeypatch, [_held("BHP")], {"BHP": 10.0})
    (pos,) = bk["open"]
    assert pos["suspect_price_runs"] == 1 and pos["last_mark"] == 100.0   # frozen
    # Pre-fix: session_usd -13500.0, breached=daily. The guard now sees the
    # position as unpriced and values it at its stop (-1R = -$600), no breach.
    assert guard["unpriced"] == ["BHP"]
    assert guard["session_usd"] == 0.0 and guard["week_usd"] == 0.0
    assert guard["worst_session_usd"] == pytest.approx(-600.0)
    assert guard["breached"] is False


def test_a_consolidation_the_sanity_guard_froze_cannot_hide_a_real_breach(tmp_path, monkeypatch):
    # Five names genuinely down ~0.95R each ($950 apiece): -$4,750 against the
    # $4,500 daily limit. A sixth goes through a 1:10 consolidation (1.0 -> 10.0).
    real = [_held(f"L{i}", risk_usd=1000.0) for i in range(5)]
    spl = _held("SPL", entry=1.0, stop=0.9, risk_usd=250.0)
    closes = {**{f"L{i}": 96.2 for i in range(5)}, "SPL": 10.0}
    bk, guard = _run(tmp_path, monkeypatch, real + [spl], closes)
    frozen = next(p for p in bk["open"] if p["symbol"] == "SPL")
    assert frozen["suspect_price_runs"] == 1 and frozen["last_mark"] == 1.0
    # Pre-fix the rejected 10.0 booked +90R x $250 = +$22,500 and breached=False.
    assert guard["unpriced"] == ["SPL"]
    assert guard["session_usd"] == pytest.approx(-4750.0, abs=1.0)
    assert guard["breached"] is True and guard["breach_kind"] == "daily"


def test_an_accepted_mark_is_still_priced_by_the_guard(tmp_path, monkeypatch):
    # The control: a move inside the sanity band is a real mark, and the guard
    # values it exactly as before.
    bk, guard = _run(tmp_path, monkeypatch, [_held("BHP")], {"BHP": 98.0})
    assert bk["open"][0]["last_mark"] == 98.0
    assert guard["unpriced"] == []
    assert guard["session_usd"] == pytest.approx(-300.0)      # -0.5R x $600


def test_a_closed_market_suspect_print_is_unpriced_for_the_guard_too(tmp_path, monkeypatch):
    bk, guard = _run(tmp_path, monkeypatch, [_held("BHP")], {"BHP": 10.0}, now=CLOSED)
    (pos,) = bk["open"]
    assert pos.get("suspect_closed") is True and pos["last_mark"] == 100.0
    assert guard["unpriced"] == ["BHP"] and guard["session_usd"] == 0.0


def test_a_frozen_symbol_held_twice_is_unpriced_even_if_one_row_accepts(tmp_path, monkeypatch):
    # A hand-edited book holding two rows of one symbol: one with a mark the
    # new price is sane against, one it is not. The guard can only look a price
    # up by symbol, so the pair reads unpriced (fail closed), never the print.
    a = _held("BHP", risk_usd=600.0)                 # last_mark 100 vs 10: frozen
    b = dict(_held("BHP", entry=11.0, stop=9.0, risk_usd=100.0), id="BHP-2")
    bk, guard = _run(tmp_path, monkeypatch, [a, b], {"BHP": 10.0})
    assert guard["unpriced"] == ["BHP", "BHP"]
