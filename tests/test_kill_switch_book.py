"""Kill-switch on the BOT BOOK (2026-07-20, review C5).

The scheduled kill-switch used to read the retired scalp journal — always
$0.00, could never fire. It now reads journal/vivek_bot_book.json per market
with the VIVEK guard limit. These tests pin the adapter maths and the
end-to-end trigger path (dry-run — never flattens a broker in tests).
"""

import json

import pytest

from scanner import config
from scanner.broker import kill_switch as ks
from scanner.scalp_journal import _session_day

pytestmark = pytest.mark.risk


def _book(open_=None, closed=None):
    return {"version": 1, "mode": "paper",
            "open": list(open_ or []), "closed": list(closed or [])}


def test_adapter_selects_market_day_and_stamps_session_key():
    book = _book(
        open_=[{"market": "asx", "unreal_usd": -50.0, "realized_r": 0.5, "risk_usd": 40.0},
               {"market": "nasdaq", "unreal_usd": -999.0}],          # other market: excluded
        closed=[{"market": "asx", "exit_date": "2024-01-02", "realized_r": -2.0, "risk_usd": 100.0},
                {"market": "asx", "exit_date": "2024-01-01", "realized_r": -5.0, "risk_usd": 100.0}],  # other day
    )
    j = ks._book_market_journal(book, "asx", "2024-01-02")
    assert len(j["closed"]) == 1 and j["closed"][0]["pnl"] == pytest.approx(-200.0)
    assert j["closed"][0]["session_day"] == _session_day()   # comparable key for check_and_kill
    # open leg: stamped unreal on remaining size + banked partial-exit R
    assert len(j["open"]) == 1
    assert j["open"][0]["unreal_pnl"] == pytest.approx(-50.0 + 0.5 * 40.0)


def test_check_and_kill_honours_custom_limit(stub_alerts):
    j = {"open": [{"unreal_pnl": -250.0}], "closed": []}
    assert ks.check_and_kill(j, dry_run=True, limit_usd=300.0) is False   # -250 > -300
    assert ks.check_and_kill(j, dry_run=True, limit_usd=200.0) is True    # -250 <= -200


def test_run_standalone_fires_on_book_loss(tmp_path, monkeypatch, stub_alerts):
    """A big same-day realised loss in one market must trip that market's check."""
    import scanner.broker.vivek_run as vr
    import datetime as dt
    from zoneinfo import ZoneInfo

    # today's date in the ASX market tz so the adapter picks the trade up
    day = dt.datetime.now(ZoneInfo(config.MARKETS["asx"].timezone)).strftime("%Y-%m-%d")
    book = _book(closed=[{"market": "asx", "exit_date": day,
                          "realized_r": -2.0, "risk_usd": 400.0}])   # -$800
    p = tmp_path / "vivek_bot_book.json"
    p.write_text(json.dumps(book), encoding="utf-8")
    monkeypatch.setattr(ks, "BOOK_FILE", p, raising=False)
    monkeypatch.setattr(vr, "BOOK_FILE", p)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)   # $300 on 10k

    out = ks.run_standalone(dry_run=True)
    assert "asx" in out["triggered"]
    assert set(out["checked"]) == set(config.MARKETS)
    assert "nasdaq" not in out["triggered"] and "crypto" not in out["triggered"]


def test_run_standalone_all_clear_on_quiet_book(tmp_path, monkeypatch, stub_alerts):
    import scanner.broker.vivek_run as vr
    p = tmp_path / "vivek_bot_book.json"
    p.write_text(json.dumps(_book()), encoding="utf-8")
    monkeypatch.setattr(vr, "BOOK_FILE", p)
    out = ks.run_standalone(dry_run=True)
    assert out["triggered"] == []
