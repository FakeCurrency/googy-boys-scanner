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


# ── live quotes (2026-07-20 Phase 4) ───────────────────────────────────────────

def _pos(symbol="BHP", market="asx", **kw):
    p = {"symbol": symbol, "market": market, "direction": "long", "status": "open",
         "entry": 100.0, "risk": 5.0, "risk_usd": 100.0, "booked_pct": 0.0,
         "unreal_usd": -50.0, "realized_r": 0.0}
    p.update(kw)
    return p


def test_adapter_live_quote_repriceses_with_runner_maths():
    """A live quote replaces the stamped mark using the SAME _unreal_r the
    runner stamps with: long, entry 100, risk 5, quote 90 -> -2R on $100."""
    j = ks._book_market_journal(_book(open_=[_pos()]), "asx", "2024-01-02",
                                quotes={("BHP", "asx"): 90.0})
    assert j["open"][0]["unreal_pnl"] == pytest.approx(-200.0)
    assert j["live_marks"] == 1


def test_adapter_no_quote_falls_back_to_stamped_mark():
    j = ks._book_market_journal(_book(open_=[_pos()]), "asx", "2024-01-02",
                                quotes={})
    assert j["open"][0]["unreal_pnl"] == pytest.approx(-50.0)
    assert j["live_marks"] == 0


def test_adapter_malformed_row_keeps_stamp_not_crash():
    bad = _pos()
    del bad["entry"]                      # _unreal_r would KeyError
    j = ks._book_market_journal(_book(open_=[bad]), "asx", "2024-01-02",
                                quotes={("BHP", "asx"): 90.0})
    assert j["open"][0]["unreal_pnl"] == pytest.approx(-50.0)


def test_run_standalone_fires_on_live_move_stale_mark_says_fine(
        tmp_path, monkeypatch, stub_alerts):
    """THE reason for Phase 4: mark stamped at last scan says -$50 (fine), the
    market has since moved to -$800 — the live quote must trip the switch."""
    import scanner.broker.vivek_run as vr
    book = _book(open_=[_pos(risk_usd=400.0)])          # live -2R * $400 = -$800
    p = tmp_path / "vivek_bot_book.json"
    p.write_text(json.dumps(book), encoding="utf-8")
    monkeypatch.setattr(vr, "BOOK_FILE", p)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)   # $300 on 10k
    monkeypatch.setattr(ks, "_live_marks", lambda b: {("BHP", "asx"): 90.0})
    out = ks.run_standalone(dry_run=True)
    assert "asx" in out["triggered"]
    # sanity: with quotes suppressed the stale -$50 mark would NOT have fired
    monkeypatch.setattr(ks, "_live_marks", lambda b: {})
    assert ks.run_standalone(dry_run=True)["triggered"] == []


def test_live_marks_suffix_mapping_and_batching(monkeypatch):
    import pandas as pd

    import scanner.data as sdata

    def _frame(px):
        idx = pd.date_range(end="2024-01-02", periods=3, freq="D")
        return pd.DataFrame({"Close": [px] * 3}, index=idx)

    asked = {}

    def fake_download(tickers, period=None, retries=None, **kw):
        asked["tickers"] = list(tickers)
        return {"BHP.AX": _frame(42.0), "BTC-USD": _frame(50000.0)}

    monkeypatch.setattr(sdata, "download", fake_download)
    book = _book(open_=[_pos("BHP", "asx"), _pos("BTC", "crypto"),
                        _pos("GHOST", "not_a_market")])
    q = ks._live_marks(book)
    assert q == {("BHP", "asx"): 42.0, ("BTC", "crypto"): 50000.0}
    assert asked["tickers"] == ["BHP.AX", "BTC-USD"]    # one batch, suffix-mapped


def test_live_marks_fetch_failure_returns_empty(monkeypatch):
    import scanner.data as sdata

    def boom(*a, **k):
        raise RuntimeError("yfinance down")

    monkeypatch.setattr(sdata, "download", boom)
    q = ks._live_marks(_book(open_=[_pos()]))
    assert q == {}                        # safety net falls back, never raises


# ── mark-sanity quote filter (2026-07-21, Phase 6 P1) ──────────────────────────

def test_live_marks_drops_split_price_quote(monkeypatch):
    """A 10:1-split quote must NOT reach the loss check — the position falls
    back to its stamped mark instead of showing a fake -90% collapse."""
    import pandas as pd

    import scanner.data as sdata

    def _frame(px):
        idx = pd.date_range(end="2024-01-02", periods=3, freq="D")
        return pd.DataFrame({"Close": [px] * 3}, index=idx)

    def fake_download(tickers, period=None, retries=None, **kw):
        return {"BHP.AX": _frame(10.1), "BTC-USD": _frame(50000.0)}

    monkeypatch.setattr(sdata, "download", fake_download)
    book = _book(open_=[_pos("BHP", "asx", last_mark=101.0),
                        _pos("BTC", "crypto", entry=48000.0, risk=2000.0,
                             last_mark=48000.0)])
    q = ks._live_marks(book)
    assert ("BHP", "asx") not in q                  # split quote dropped
    assert q[("BTC", "crypto")] == 50000.0          # +4.2% quote passes


def test_live_marks_no_reference_passes_through(monkeypatch):
    """Legacy position without last_mark: quotes keep flowing (no filter)."""
    import pandas as pd

    import scanner.data as sdata

    def _frame(px):
        idx = pd.date_range(end="2024-01-02", periods=3, freq="D")
        return pd.DataFrame({"Close": [px] * 3}, index=idx)

    monkeypatch.setattr(sdata, "download",
                        lambda t, period=None, retries=None, **kw: {"BHP.AX": _frame(10.1)})
    book = _book(open_=[_pos("BHP", "asx")])        # _pos has no last_mark
    q = ks._live_marks(book)
    assert q[("BHP", "asx")] == 10.1
