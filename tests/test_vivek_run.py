"""VIVEK execution/runner layer (Phase 1–2: dry-run + paper book).

Verifies the safety gates (disabled → no-op; dry-run → no book write; "live"
mode treated as paper), the persistent book (caps/short-bias hold across runs),
intraday fills carrying the entry-type label, and mark-to-market resolution.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scanner import config
from scanner.broker import vivek_run as vr

pytestmark = pytest.mark.risk


def _plan(**kw):
    p = {"armed": True, "entry_trigger": "reclaim", "trigger_bar": "2024-01-01",
         "entry": 100.0, "stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
         "rr": 3.0, "scale": config.VIVEK_TP_SCALE_LONG}
    p.update(kw)
    return p


def _short_plan(**kw):
    p = {"armed": True, "entry_trigger": "reclaim", "trigger_bar": "2024-01-01",
         "entry": 100.0, "stop": 104.0, "tp1": 94.0, "tp2": 88.0, "tp3": 80.0,
         "rr": 3.0, "scale": config.VIVEK_TP_SCALE_SHORT}
    p.update(kw)
    return p


def _row(symbol="BHP", direction="long", **kw):
    plans = kw.pop("plans", None) or ({"1D": _plan()} if direction == "long" else {"1D": _short_plan()})
    r = {"symbol": symbol, "name": symbol, "sector": "", "grade": "A+",
         "dir": "SHORT" if direction == "short" else "LONG",
         "entry_types": ["reclaim"], "plans": plans}
    r.update(kw)
    return r


def _frame(last_close):
    idx = pd.date_range(end="2024-01-02", periods=5, freq="D")
    return pd.DataFrame({"Open": last_close, "High": last_close, "Low": last_close,
                         "Close": last_close, "Volume": 1e6}, index=idx)


def _aest(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("Australia/Sydney"))


def _enable(monkeypatch, tmp_path, dry_run=False, mode=None):
    monkeypatch.setattr(vr, "BOOK_FILE", tmp_path / "vivek_bot_book.json")
    monkeypatch.setattr(vr, "PUBLIC_FILE", tmp_path / "public_book.json")
    monkeypatch.setattr(config, "VIVEK_BOT_ENABLED", True)
    monkeypatch.setattr(config, "VIVEK_BOT_DRY_RUN", dry_run)
    if mode is not None:
        monkeypatch.setattr(config, "VIVEK_BOT_MODE", mode)


# ── safety gates ────────────────────────────────────────────────────────────────

def test_disabled_runner_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "BOOK_FILE", tmp_path / "book.json")
    monkeypatch.setattr(vr, "PUBLIC_FILE", tmp_path / "pub.json")
    monkeypatch.setattr(config, "VIVEK_BOT_ENABLED", False)
    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    bk = vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)}, uni,
                       now=_aest(2024, 1, 2, 11, 0))
    assert bk["open"] == [] and bk["closed"] == []
    assert not (tmp_path / "book.json").exists()        # nothing written


def test_dry_run_decides_but_never_writes_the_book(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path, dry_run=True)
    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    bk = vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)}, uni,
                       now=_aest(2024, 1, 2, 11, 0))
    # The returned book reflects the would-be fill in memory, but nothing persists.
    assert not (tmp_path / "vivek_bot_book.json").exists()
    assert not (tmp_path / "public_book.json").exists()


def test_live_mode_is_treated_as_paper_in_this_phase(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path, dry_run=False,
            mode={"asx": "live", "nasdaq": "paper", "crypto": "paper"})
    monkeypatch.setattr(config, "VIVEK_LIVE_CONFIRMED", False)
    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    bk = vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)}, uni,
                       now=_aest(2024, 1, 2, 11, 0))
    assert bk["mode"] == "paper"                          # never escalates to live here
    assert len(bk["open"]) == 1


# ── paper fills + entry-type label end-to-end ───────────────────────────────────

def test_fills_at_intraday_price_and_carries_entry_type_label(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    bk = vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)}, uni,
                       now=_aest(2024, 1, 2, 11, 0))
    assert len(bk["open"]) == 1
    pos = bk["open"][0]
    assert pos["entry"] == 101.0                          # the live intraday price
    assert pos["entry_type"] == "reclaim"
    from scanner.broker.vivek_bot import ENTRY_TYPE_LABEL
    assert pos["entry_type_label"] == ENTRY_TYPE_LABEL["reclaim"]
    assert pos["timeframe"] == "1D" and pos["grade"] == "A+"
    assert pos["units"] > 0 and pos["leverage_target"] == 5
    assert (tmp_path / "vivek_bot_book.json").exists()    # persisted


def test_closed_session_opens_nothing(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    bk = vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)}, uni,
                       now=_aest(2024, 1, 2, 9, 0))       # before the 10:15 open
    assert len(bk["open"]) == 0


# ── persistent book (caps hold across runs) ─────────────────────────────────────

def test_book_caps_hold_across_runs(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VIVEK_BOT_MIN_SHORTS", 4)   # exercise the 6-long reservation cap
    uni = [{"symbol": f"L{i}", "yf": f"L{i}.AX"} for i in range(8)]
    frames = {f"L{i}.AX": _frame(101.0) for i in range(8)}
    rows = [_row(symbol=f"L{i}") for i in range(6)]
    when = _aest(2024, 1, 2, 11, 0)
    bk = vr.run_market("asx", rows, frames, uni, now=when)
    assert len(bk["open"]) == 6                            # 6-long cap reached

    # A later run offering two MORE longs must not exceed the long cap.
    rows2 = [_row(symbol="L6"), _row(symbol="L7")]
    uni2 = uni + [{"symbol": "L6", "yf": "L6.AX"}, {"symbol": "L7", "yf": "L7.AX"}]
    frames2 = {**frames, "L6.AX": _frame(101.0), "L7.AX": _frame(101.0)}
    bk = vr.run_market("asx", rows2, frames2, uni2, now=_aest(2024, 1, 3, 11, 0))
    longs = [p for p in bk["open"] if p["direction"] == "long"]
    assert len(longs) == 6                                # still capped at 6 across runs


def test_open_position_marks_to_market_and_closes_on_stop(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)}, uni,
                  now=_aest(2024, 1, 2, 11, 0))
    # next session price falls through the 96 stop → position closes
    bk = vr.run_market("asx", [], {"BHP.AX": _frame(95.0)}, uni,
                       now=_aest(2024, 1, 3, 11, 0))
    assert len(bk["open"]) == 0 and len(bk["closed"]) == 1
    assert bk["closed"][0]["status"] == "closed" and bk["closed"][0]["realized_r"] < 0


# ── daily-loss guardrail + book hardening (Phase 3) ─────────────────────────────

def test_daily_loss_guard_halts_new_entries(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 0.1)   # tiny limit, easy to breach
    uni = [{"symbol": "BHP", "yf": "BHP.AX"}, {"symbol": "CBA", "yf": "CBA.AX"}]
    frames_ok = {"BHP.AX": _frame(101.0), "CBA.AX": _frame(101.0)}
    # open BHP, then stop it out the SAME day → a realised loss on the books
    vr.run_market("asx", [_row("BHP")], frames_ok, uni, now=_aest(2024, 1, 2, 11, 0))
    vr.run_market("asx", [], {"BHP.AX": _frame(95.0), "CBA.AX": _frame(101.0)}, uni,
                  now=_aest(2024, 1, 2, 14, 0))
    # later the same day a fresh A+ (CBA) is offered — the guard must refuse it
    bk = vr.run_market("asx", [_row("CBA")], {"BHP.AX": _frame(95.0), "CBA.AX": _frame(101.0)}, uni,
                       now=_aest(2024, 1, 2, 15, 0))
    assert bk["guard"]["asx"]["breached"] is True
    assert all(p["symbol"] != "CBA" for p in bk["open"])   # no new risk added


def test_corrupt_book_aborts_loudly_and_leaves_the_file_untouched(tmp_path, monkeypatch):
    """THE track record must never be silently replaced (2026-07-20, review C2):
    an unreadable book aborts the run with a non-zero exit, the file is left
    byte-for-byte as it was (no .corrupt.json parking — a rename made the NEXT
    run start empty), and nothing is written."""
    _enable(monkeypatch, tmp_path)
    bad = "{ this is not valid json"
    (tmp_path / "vivek_bot_book.json").write_text(bad)
    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    with pytest.raises(vr.BookCorruptError):
        vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)}, uni,
                      now=_aest(2024, 1, 2, 11, 0))
    assert (tmp_path / "vivek_bot_book.json").read_text() == bad   # untouched
    assert not (tmp_path / "vivek_bot_book.corrupt.json").exists() # no parking
    assert not (tmp_path / "public_book.json").exists()            # nothing written


def test_book_corrupt_error_escapes_generic_exception_handlers():
    """run.py wraps run_market in best-effort `except Exception` blocks; the
    abort only works because BookCorruptError is a SystemExit (a BaseException),
    which those wrappers cannot swallow. Pin that contract."""
    assert issubclass(vr.BookCorruptError, SystemExit)
    assert not issubclass(vr.BookCorruptError, Exception)


# ── off-universe positions must still price (the MDB freeze, 2026-07) ──────────

def _ny(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("America/New_York"))


def _open_position(symbol="MDB", market="nasdaq"):
    from scanner.vivek_journal import _snapshot
    row = {"symbol": symbol, "name": symbol, "sector": "", "grade": "A+",
           "dir": "LONG", "entry_types": ["reclaim"]}
    plan = {"stop": 96.0, "tp1": 106.0, "tp2": 112.0, "tp3": 120.0,
            "scale": config.VIVEK_TP_SCALE_LONG, "entry_trigger": "reclaim",
            "armed": True, "trigger_bar": None}
    pos = _snapshot(row, "1D", plan, market, 100.0, "2024-01-01")
    pos["market"] = market
    pos["risk_usd"] = 35.0
    return pos


def test_off_universe_position_is_fetched_and_can_stop_out(tmp_path, monkeypatch):
    """A held symbol that fell out of the universe (delist/tier change/list swap)
    must STILL be priced — otherwise its stop can never fire and it squats a
    slot forever (the frozen-MDB bug)."""
    import json
    _enable(monkeypatch, tmp_path)
    book = {"version": 1, "mode": "paper", "open": [_open_position()], "closed": []}
    (tmp_path / "vivek_bot_book.json").write_text(json.dumps(book), encoding="utf-8")

    calls = {}
    def fake_download(tickers, period="6mo"):
        calls["tickers"] = list(tickers)
        return {t: _frame(90.0) for t in tickers}      # below the 96 stop
    import scanner.data
    monkeypatch.setattr(scanner.data, "download", fake_download)

    bk = vr.run_market("nasdaq", [], {}, [], now=_ny(2024, 1, 2, 12, 0))
    assert calls["tickers"] == ["MDB"]                 # fetched directly
    assert bk["open"] == []                            # no longer frozen open
    (closed,) = [t for t in bk["closed"] if t["symbol"] == "MDB"]
    assert closed["status"] == "closed" and closed["exit_reason"] == "stop"


def test_unpriceable_position_gets_auditable_counter(tmp_path, monkeypatch):
    """If a symbol truly has no data anywhere, the freeze must be VISIBLE:
    unpriced_runs counts up on the position instead of a silent stale mark."""
    import json
    _enable(monkeypatch, tmp_path)
    book = {"version": 1, "mode": "paper", "open": [_open_position()], "closed": []}
    (tmp_path / "vivek_bot_book.json").write_text(json.dumps(book), encoding="utf-8")
    import scanner.data
    monkeypatch.setattr(scanner.data, "download", lambda tickers, period="6mo": {})

    bk = vr.run_market("nasdaq", [], {}, [], now=_ny(2024, 1, 2, 12, 0))
    (pos,) = bk["open"]
    assert pos["unpriced_runs"] == 1                   # visible, not silent

    # a second run keeps counting
    bk = vr.run_market("nasdaq", [], {}, [], now=_ny(2024, 1, 3, 12, 0))
    (pos,) = bk["open"]
    assert pos["unpriced_runs"] == 2
