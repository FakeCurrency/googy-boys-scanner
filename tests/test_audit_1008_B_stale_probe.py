"""Audit 2026-10-08 #58: the stale probe must not call an UNPRICED row "still".

`_stale_probe`'s docstring promised that rows unpriced this run are skipped
("no price means no movement claim"), but it tested that by the presence of
`unreal_r` -- and run_market only ever WRITES `unreal_r` when a price exists,
never clears it. A held position with no frame this run (a Yahoo-starved batch,
a cache past VIVEK_BOT_MAX_MARK_AGE_H) or one frozen by `_mark_sanity` kept the
last priced run's R, qualified as "sitting still", was stamped `stale_pinged`
(the journal's STALLED strip) and pushed as "YOUR CALL ... sitting still" about
a name whose price -- and stop -- nobody was observing. run_market now passes
the set of symbols it actually priced and the probe skips everything else.
"""

import datetime as dt
import json
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scanner import config, data
from scanner.broker import alert_router, vivek_run as vr

pytestmark = pytest.mark.risk

NOW = dt.datetime(2024, 1, 19, 11, 0, tzinfo=ZoneInfo("Australia/Sydney"))   # a Friday
DAY = "2024-01-19"


def _frame(close, end=DAY):
    idx = pd.date_range(end=end, periods=5, freq="D")
    return pd.DataFrame({"Open": close, "High": close, "Low": close,
                         "Close": close, "Volume": 1e6}, index=idx)


def _held(symbol="PMT", unreal_r=0.1, last_mark=100.4):
    return {"id": f"{symbol}-1", "symbol": symbol, "name": symbol, "sector": "",
            "market": "asx", "direction": "long", "grade": "A+",
            "entry_type": "break", "timeframe": "1D",
            "entry": 100.0, "stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
            "scale": list(config.VIVEK_TP_SCALE_LONG), "risk": 4.0, "rr": 3.0,
            "trigger_bar": None, "entry_date": "2024-01-01",          # 18 days held
            "opened_at": "2024-01-01T00:00:00+00:00", "status": "open",
            "tp1_hit": False, "tp2_hit": False, "tp3_hit": False, "booked_pct": 0.0,
            "realized_r": 0.0, "gross_r": 0.0, "cost_r": 0.0, "exits": [],
            "mae": 100.0, "mfe": 100.4, "mae_r": 0.0, "mfe_r": 0.1,
            "units": 25.0, "notional": 2500.0, "risk_usd": 100.0,
            "unreal_r": unreal_r, "unreal_usd": unreal_r * 100.0,
            "last_mark": last_mark}


@pytest.fixture()
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "BOOK_DIR", tmp_path)
    monkeypatch.setattr(vr, "BOOK_FILE", tmp_path / "vivek_bot_book.json")
    monkeypatch.setattr(vr, "UNASSIGNED_FILE", tmp_path / "vivek_bot_book.unassigned.json")
    monkeypatch.setattr(vr, "PUBLIC_FILE", tmp_path / "public_book.json")
    monkeypatch.setattr(config, "VIVEK_BOT_ENABLED", True)
    monkeypatch.setattr(config, "VIVEK_BOT_DRY_RUN", False)
    monkeypatch.setattr(config, "VIVEK_BOT_STALE_PROBE_DAYS", 14)
    monkeypatch.setattr(config, "VIVEK_BOT_STALE_PROBE_PUSH", True)
    monkeypatch.setattr(data, "fetch", lambda *a, **k: ({}, {}))   # refetch gets nothing
    sent = []
    monkeypatch.setattr(alert_router, "smart_send",
                        lambda event, *a, **k: sent.append((event,) + a))

    def _go(pos, frames):
        (tmp_path / "vivek_bot_book.asx.json").write_text(json.dumps(
            {"version": 2, "mode": "paper", "market": "asx",
             "open": [pos], "closed": []}), encoding="utf-8")
        bk = vr.run_market("asx", [], frames, [{"symbol": "PMT", "yf": "PMT.AX"}], now=NOW)
        return bk["open"][0], [s for s in sent if s[0] == "stale_position"]

    return _go


def test_an_unpriced_row_is_not_reported_sitting_still(run):
    pos, pings = run(_held(), {})                         # no frame this run
    assert pos["unpriced_runs"] == 1
    assert pos["unreal_r"] == 0.1                         # the fossil R is still there
    assert "stale_pinged" not in pos and pings == []      # ...but makes no claim


def test_a_row_frozen_by_mark_sanity_is_not_reported_sitting_still(run):
    pos, pings = run(_held(), {"PMT.AX": _frame(10.0)})   # 10:1 split, frozen
    assert pos["suspect_price_runs"] == 1
    assert "stale_pinged" not in pos and pings == []


def test_a_priced_row_going_nowhere_still_pings(run):
    # The control: priced this run, 18 days held, +0.1R -> the probe fires.
    pos, pings = run(_held(), {"PMT.AX": _frame(100.4)})
    assert pos["stale_pinged"] == DAY
    assert len(pings) == 1 and "PMT" in pings[0][2]


def test_an_unpriced_run_neither_renews_nor_clears_an_earlier_stamp(run):
    # Skipped whole: the episode's stamp survives a blind run untouched.
    pos, pings = run(_held() | {"stale_pinged": "2024-01-10"}, {})
    assert pos["stale_pinged"] == "2024-01-10" and pings == []


def test_a_direct_caller_without_the_priced_set_keeps_the_old_reading(monkeypatch):
    monkeypatch.setattr(vr, "_save_market_book", lambda m, b: None)
    book = {"open": [_held()]}
    assert vr._stale_probe("asx", book, DAY, send=lambda *a: None) == ["PMT"]
    book = {"open": [_held()]}
    assert vr._stale_probe("asx", book, DAY, send=lambda *a: None, priced=set()) == []
