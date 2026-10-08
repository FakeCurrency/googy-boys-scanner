"""Audit 2026-10-08 #18: the cross-market sector warning must count every market.

The per-sector cap is enforced per market (REFINEMENTS #113, owner decision) and
`sectorcache.global_sector_load` is the promised compensating visibility: a
per-scan WARNING naming any sector over the cap "once all markets are counted".
run_market handed it `book["open"]` -- since book layout v2 one market's
canonical file, which decide() already holds at or under the cap -- so it could
never fire (live: 4 ASX + 4 NASDAQ "Financial Services", 8 > 6, silent). It now
reads the sibling books through the same reader as the global position cap,
leniently: an unreadable sibling is named, never a reason to fail the run.
"""

import datetime as dt
import json
import logging
from zoneinfo import ZoneInfo

import pytest

from scanner import config, data
from scanner.broker import vivek_run as vr

pytestmark = pytest.mark.risk

NOW = dt.datetime(2024, 1, 2, 12, 0, tzinfo=ZoneInfo("America/New_York"))


def _pos(symbol, market, sector="Financial Services"):
    return {"id": f"{symbol}-1", "symbol": symbol, "name": symbol, "sector": sector,
            "market": market, "direction": "long", "grade": "A+",
            "entry_type": "break", "timeframe": "1D", "entry": 100.0, "stop": 96.0,
            "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
            "scale": list(config.VIVEK_TP_SCALE_LONG), "risk": 4.0, "rr": 3.0,
            "entry_date": "2024-01-01", "status": "open", "booked_pct": 0.0,
            "realized_r": 0.0, "exits": [], "mae": 100.0, "mfe": 100.0,
            "units": 25.0, "notional": 2500.0, "risk_usd": 100.0, "last_mark": 100.0}


def _book(tmp_path, market, rows):
    (tmp_path / f"vivek_bot_book.{market}.json").write_text(json.dumps(
        {"version": 2, "mode": "paper", "market": market, "open": rows,
         "closed": []}), encoding="utf-8")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "BOOK_DIR", tmp_path)
    monkeypatch.setattr(vr, "BOOK_FILE", tmp_path / "vivek_bot_book.json")
    monkeypatch.setattr(vr, "UNASSIGNED_FILE", tmp_path / "vivek_bot_book.unassigned.json")
    monkeypatch.setattr(vr, "PUBLIC_FILE", tmp_path / "public_book.json")
    monkeypatch.setattr(config, "VIVEK_BOT_ENABLED", True)
    monkeypatch.setattr(config, "VIVEK_BOT_DRY_RUN", False)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_PER_SECTOR", 6)
    monkeypatch.setattr(data, "fetch", lambda *a, **k: ({}, {}))
    return tmp_path


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING and "REFINEMENTS #113" in r.getMessage()]


def test_a_sector_over_the_cap_across_two_markets_is_reported(env, caplog):
    _book(env, "asx", [_pos(f"A{i}", "asx") for i in range(4)])
    _book(env, "nasdaq", [_pos(f"N{i}", "nasdaq") for i in range(4)])
    caplog.set_level(logging.WARNING)
    vr.run_market("nasdaq", [], {}, [], now=NOW)
    msgs = _warnings(caplog)
    assert any("Financial Services=8(asx+nasdaq)" in m for m in msgs), msgs


def test_each_market_inside_the_cap_on_its_own_and_together_is_silent(env, caplog):
    _book(env, "asx", [_pos(f"A{i}", "asx") for i in range(3)])
    _book(env, "nasdaq", [_pos(f"N{i}", "nasdaq") for i in range(3)])
    caplog.set_level(logging.WARNING)
    vr.run_market("nasdaq", [], {}, [], now=NOW)
    assert _warnings(caplog) == []


def test_an_unreadable_sibling_is_named_and_the_run_still_saves(env, caplog):
    _book(env, "nasdaq", [_pos("N0", "nasdaq")])
    (env / "vivek_bot_book.asx.json").write_text("{ truncated", encoding="utf-8")
    caplog.set_level(logging.WARNING)
    # The run's own book is saved before the combined view is rebuilt; the
    # combined rebuild is what aborts on a corrupt sibling (C2 rule), and that
    # is pre-existing and deliberate. What this pins is that the SECTOR step
    # does not abort first: it names the file and carries on to the save.
    with pytest.raises(SystemExit):
        vr.run_market("nasdaq", [], {}, [], now=NOW)
    assert any("vivek_bot_book.asx.json (unreadable)" in m for m in _warnings(caplog))
    saved = json.loads((env / "vivek_bot_book.nasdaq.json").read_text(encoding="utf-8"))
    assert saved.get("summary", {}).get("updated_day") == "2024-01-02"


def test_the_cap_reader_still_fails_closed_on_the_same_sibling(env):
    (env / "vivek_bot_book.asx.json").write_text("{ truncated", encoding="utf-8")
    _book(env, "crypto", [_pos("BTC", "crypto", sector="crypto-major")])
    assert vr._book_elsewhere("nasdaq") is None
    rows, bad = vr._sibling_open_rows("nasdaq")
    assert [r["symbol"] for r in rows] == ["BTC"]
    assert [n for n, _e in bad] == ["vivek_bot_book.asx.json"]
