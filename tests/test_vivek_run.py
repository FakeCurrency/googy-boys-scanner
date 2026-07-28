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
    # Book layout v2 (Phase 3): canonical per-market files under BOOK_DIR +
    # the derived combined view at BOOK_FILE (+ public twin).
    monkeypatch.setattr(vr, "BOOK_DIR", tmp_path)
    monkeypatch.setattr(vr, "BOOK_FILE", tmp_path / "vivek_bot_book.json")
    monkeypatch.setattr(vr, "UNASSIGNED_FILE", tmp_path / "vivek_bot_book.unassigned.json")
    monkeypatch.setattr(vr, "PUBLIC_FILE", tmp_path / "public_book.json")
    monkeypatch.setattr(config, "VIVEK_BOT_ENABLED", True)
    monkeypatch.setattr(config, "VIVEK_BOT_DRY_RUN", dry_run)
    if mode is not None:
        monkeypatch.setattr(config, "VIVEK_BOT_MODE", mode)


def _mfile(tmp_path, market):
    return tmp_path / f"vivek_bot_book.{market}.json"


def _write_market_book(tmp_path, market, open_=None, closed=None):
    import json
    (_mfile(tmp_path, market)).write_text(json.dumps(
        {"version": 2, "mode": "paper", "market": market,
         "open": list(open_ or []), "closed": list(closed or [])}), encoding="utf-8")


# ── safety gates ────────────────────────────────────────────────────────────────

def test_disabled_runner_is_a_noop(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VIVEK_BOT_ENABLED", False)
    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    bk = vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)}, uni,
                       now=_aest(2024, 1, 2, 11, 0))
    assert bk["open"] == [] and bk["closed"] == []
    assert not (tmp_path / "vivek_bot_book.json").exists()   # nothing written
    assert not _mfile(tmp_path, "asx").exists()


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
    assert _mfile(tmp_path, "asx").exists()               # canonical persisted
    assert (tmp_path / "vivek_bot_book.json").exists()    # derived combined too


def test_closed_session_opens_nothing(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    bk = vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)}, uni,
                       now=_aest(2024, 1, 2, 9, 0))       # before the 10:15 open
    assert len(bk["open"]) == 0


# ── persistent book (caps hold across runs) ─────────────────────────────────────

def test_book_caps_hold_across_runs(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    # Pin a small book so this stays about the MECHANISM (a cap survives a
    # restart because it is re-derived from the persisted book) rather than
    # about the live number — which is now a 30-position ceiling shared across
    # markets, covered in tests/test_vivek_bot_global_cap.py.
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_POSITIONS", 10)
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


def test_corrupt_market_file_aborts_loudly_too(tmp_path, monkeypatch):
    """Layout v2: a corrupt CANONICAL per-market file must abort the same way."""
    _enable(monkeypatch, tmp_path)
    bad = "{ not json"
    _mfile(tmp_path, "asx").write_text(bad)
    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    with pytest.raises(vr.BookCorruptError):
        vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)}, uni,
                      now=_aest(2024, 1, 2, 11, 0))
    assert _mfile(tmp_path, "asx").read_text() == bad              # untouched


# ── book layout v2: per-market canonical files (2026-07-20, Phase 3) ───────────

def test_market_isolation_by_construction(tmp_path, monkeypatch):
    """The structural guarantee: running ASX can not touch the other markets'
    canonical files, byte for byte — even though it rewrites the combined view."""
    import json
    _enable(monkeypatch, tmp_path)
    _write_market_book(tmp_path, "nasdaq",
                       open_=[{"symbol": "MDB", "market": "nasdaq", "direction": "long",
                               "status": "open", "entry": 1, "risk": 1}])
    _write_market_book(tmp_path, "crypto",
                       closed=[{"symbol": "BTC", "market": "crypto", "status": "closed",
                                "realized_r": 2.0}])
    before = {m: _mfile(tmp_path, m).read_bytes() for m in ("nasdaq", "crypto")}

    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    bk = vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)}, uni,
                       now=_aest(2024, 1, 2, 11, 0))

    for m in ("nasdaq", "crypto"):
        assert _mfile(tmp_path, m).read_bytes() == before[m]       # UNTOUCHED
    # …while the combined view sees all three markets
    assert {p["market"] for p in bk["open"]} == {"asx", "nasdaq"}
    assert any(t["market"] == "crypto" for t in bk["closed"])
    combined = json.loads((tmp_path / "vivek_bot_book.json").read_text())
    assert len(combined["open"]) == 2 and len(combined["closed"]) == 1


def test_migration_splits_legacy_and_preserves_unknown_markets(tmp_path, monkeypatch):
    import json
    _enable(monkeypatch, tmp_path)
    legacy = {"version": 1, "mode": "paper",
              "open": [{"symbol": "BHP", "market": "asx", "status": "open",
                        "entry": 100.0, "stop": 96.0, "tp1": 106.0, "tp2": 112.0,
                        "tp3": 120.0, "risk": 4.0, "direction": "long",
                        "scale": [0.25, 0.5, 0.15], "booked_pct": 0.0,
                        "entry_date": "2024-01-01",
                        "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
                        "realized_r": 0.0, "gross_r": 0.0, "exits": [],
                        "mae": 100.0, "mfe": 100.0},
                       {"symbol": "OLD", "market": "retired_mkt", "status": "open"}],
              "closed": [{"symbol": "CBA", "market": "asx", "status": "closed",
                          "realized_r": 1.0}],
              "guard": {"asx": {"breached": False}}}
    (tmp_path / "vivek_bot_book.json").write_text(json.dumps(legacy), encoding="utf-8")

    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    bk = vr.run_market("asx", [], {"BHP.AX": _frame(101.0)}, uni,
                       now=_aest(2024, 1, 2, 11, 0))

    m = json.loads(_mfile(tmp_path, "asx").read_text())
    assert [p["symbol"] for p in m["open"]] == ["BHP"]             # asx slice only
    assert [t["symbol"] for t in m["closed"]] == ["CBA"]
    stray = json.loads((tmp_path / "vivek_bot_book.unassigned.json").read_text())
    assert [e["symbol"] for e in stray["entries"]] == ["OLD"]      # never dropped
    assert any(p["symbol"] == "OLD" for p in bk["open"])           # still visible combined


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


## ── manual bot-book close (2026-07-20, review C4) ───────────────────────────────

def test_close_bot_position_closes_and_persists(tmp_path, monkeypatch):
    import json
    _enable(monkeypatch, tmp_path)
    book = {"version": 1, "mode": "paper",
            "open": [_open_position("MDB", "nasdaq")], "closed": []}
    (tmp_path / "vivek_bot_book.json").write_text(json.dumps(book), encoding="utf-8")
    closed = vr.close_bot_position("MDB", "nasdaq", 98.0, day="2024-01-05")
    assert closed is not None and closed["status"] == "closed"
    assert closed["exit_reason"] == "manual" and closed["exit_price"] == 98.0
    # entry 100 / stop 96 -> risk 4; close @98 -> -0.5R gross on full size
    assert closed["gross_r"] == pytest.approx(-0.5)
    saved = json.loads((tmp_path / "vivek_bot_book.json").read_text(encoding="utf-8"))
    assert saved["open"] == [] and len(saved["closed"]) == 1
    assert (tmp_path / "public_book.json").exists()        # public twin updated too


def test_close_bot_position_books_only_the_remaining_fraction(tmp_path, monkeypatch):
    import json
    _enable(monkeypatch, tmp_path)
    pos = _open_position("MDB", "nasdaq")
    pos["booked_pct"] = 0.25            # TP1 already banked 25% at 106 (+0.375R)
    pos["realized_r"] = 0.375
    pos["gross_r"] = 0.375
    book = {"version": 1, "mode": "paper", "open": [pos], "closed": []}
    (tmp_path / "vivek_bot_book.json").write_text(json.dumps(book), encoding="utf-8")
    closed = vr.close_bot_position("MDB", "nasdaq", 104.0, day="2024-01-05")
    # remaining 75% exits @104 (+1R per unit): 0.375 + 0.75 = 1.125R gross
    assert closed["gross_r"] == pytest.approx(1.125)
    assert closed["booked_pct"] == 1.0


def test_close_bot_position_without_match_leaves_book_unwritten(tmp_path, monkeypatch):
    _enable(monkeypatch, tmp_path)
    assert vr.close_bot_position("XYZ", "asx", 10.0) is None
    assert not (tmp_path / "vivek_bot_book.json").exists()  # nothing created/saved


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


# ── verify_books: the Phase 4 track-record integrity gate ──────────────────────

def _vpos(symbol="BHP", market="asx", **kw):
    import copy
    p = {"symbol": symbol, "market": market, "direction": "long", "status": "open",
         "entry": 100.0, "stop": 96.0, "risk": 4.0, "risk_usd": 100.0,
         "unreal_usd": 0.0, "realized_r": 0.0}
    p.update(kw)
    return copy.deepcopy(p)


def test_verify_books_healthy(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    _write_market_book(tmp_path, "asx", open_=[_vpos()])
    _write_market_book(tmp_path, "crypto", open_=[_vpos("BTC", "crypto")])
    vr._write_combined()
    assert vr.verify_books() == []


def test_verify_books_empty_layout_is_ok(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)                 # nothing on disk at all
    assert vr.verify_books() == []


def test_verify_books_flags_cross_market_contamination(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    # post-migration layout: all three market files exist; a crypto entry has
    # somehow landed inside the ASX canonical file
    _write_market_book(tmp_path, "asx", open_=[_vpos(), _vpos("BTC", "crypto")])
    _write_market_book(tmp_path, "nasdaq")
    _write_market_book(tmp_path, "crypto")
    vr._write_combined()
    probs = vr.verify_books()
    assert len(probs) == 1 and "DIFFERENT market" in probs[0] and "BTC" in probs[0]


def test_verify_books_flags_duplicate_open_symbol(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    _write_market_book(tmp_path, "asx", open_=[_vpos(), _vpos()])
    vr._write_combined()
    probs = vr.verify_books()
    assert any("duplicate open symbols" in p and "BHP" in p for p in probs)


def test_verify_books_flags_stale_combined_and_public(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    _write_market_book(tmp_path, "asx", open_=[_vpos()])
    vr._write_combined()
    # a later canonical write that somehow skipped the combined refresh
    _write_market_book(tmp_path, "asx", open_=[_vpos(), _vpos("CBA", "asx")])
    probs = vr.verify_books()
    assert sum("STALE" in p for p in probs) == 2   # combined + public twin


def test_verify_books_flags_missing_combined(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    _write_market_book(tmp_path, "asx", open_=[_vpos()])
    probs = vr.verify_books()
    assert sum("MISSING" in p for p in probs) == 2


def test_verify_books_corrupt_market_file_reported_not_raised(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    _mfile(tmp_path, "asx").write_text("{not json", encoding="utf-8")
    probs = vr.verify_books()                      # must NOT raise/abort
    assert any("UNPARSEABLE" in p for p in probs)


# ── mark-sanity guard (2026-07-21, Phase 6 P1) ─────────────────────────────────

def _sane_pos(**kw):
    p = {"symbol": "BHP", "market": "asx", "direction": "long", "status": "open",
         "entry": 100.0, "stop": 96.0, "risk": 4.0, "risk_usd": 100.0,
         "last_mark": 100.0}
    p.update(kw)
    return p


def test_sanity_normal_move_accepted_and_tracked():
    pos = _sane_pos()
    assert vr._mark_sanity(pos, 110.0, "asx") == 110.0
    assert pos["last_mark"] == 110.0 and "suspect_price_runs" not in pos


def test_sanity_split_price_rejected_not_managed():
    """A 10:1 split reads as -90% vs the last mark: must NOT manage on it."""
    pos = _sane_pos()
    assert vr._mark_sanity(pos, 10.0, "asx") is None
    assert pos["suspect_price_runs"] == 1 and pos["suspect_price"] == 10.0
    assert pos["last_mark"] == 100.0                     # reference unchanged


def test_sanity_second_hit_alerts_third_accepts(stub_alerts):
    pos = _sane_pos()
    assert vr._mark_sanity(pos, 10.0, "asx") is None     # 1st: silent freeze
    assert vr._mark_sanity(pos, 10.1, "asx") is None     # 2nd: alert
    assert pos["suspect_price_runs"] == 2
    assert vr._mark_sanity(pos, 10.05, "asx") == 10.05   # 3rd: accepted as real
    assert pos["last_mark"] == 10.05
    assert "suspect_price_runs" not in pos and "suspect_price" not in pos


def test_sanity_recovery_clears_counter():
    pos = _sane_pos()
    assert vr._mark_sanity(pos, 10.0, "asx") is None
    assert vr._mark_sanity(pos, 101.0, "asx") == 101.0   # sane price returns
    assert "suspect_price_runs" not in pos and pos["last_mark"] == 101.0


def test_sanity_seeds_legacy_position_without_false_positive():
    """Rollout: an old runner +80% from entry has no last_mark — first guarded
    observation must be accepted and become the reference."""
    pos = _sane_pos()
    del pos["last_mark"]
    assert vr._mark_sanity(pos, 180.0, "asx") == 180.0
    assert pos["last_mark"] == 180.0


def test_sanity_crypto_headroom():
    pos = _sane_pos(symbol="BTC", market="crypto")
    assert vr._mark_sanity(pos, 155.0, "crypto") == 155.0    # +55% < 60% limit
    assert vr._mark_sanity(pos, 260.0, "crypto") is None     # +68% > limit


def test_sanity_guard_prevents_fake_stop_out_in_run_market(tmp_path, monkeypatch):
    """End to end: a split price must NOT close the position via run_market."""
    _enable(monkeypatch, tmp_path)
    uni = [{"symbol": "BHP", "yf": "BHP.AX"}]
    bk = vr.run_market("asx", [_row()], {"BHP.AX": _frame(101.0)}, uni,
                       now=_aest(2024, 1, 2, 11, 0))
    assert len(bk["open"]) == 1
    # next run the feed serves a 10:1-split price: 10.1 (would be a "stop hit")
    bk = vr.run_market("asx", [], {"BHP.AX": _frame(10.1)}, uni,
                       now=_aest(2024, 1, 3, 11, 0))
    assert len(bk["open"]) == 1 and len(bk["closed"]) == 0   # NOT closed
    assert bk["open"][0]["suspect_price_runs"] == 1


# ── sector back-fill sources on the OPEN BOOK (2026-07-28) ─────────────────────


def _held(symbol, sector="", notional=5_000.0, entry=100.0, **kw):
    """A schema-complete OPEN position, as run_market's mark-to-market expects
    to find one (``_vpos`` above is the thinner shape verify_books works on)."""
    p = {"id": f"{symbol}-1", "symbol": symbol, "name": symbol, "sector": sector,
         "market": "asx", "direction": "long", "grade": "A+",
         "entry_type": "reclaim", "timeframe": "1D",
         "entry": entry, "stop": entry - 4.0,
         "tp1": entry + 6.0, "tp2": entry + 12.0, "tp3": entry + 20.0,
         "scale": list(config.VIVEK_TP_SCALE_LONG), "risk": 4.0, "rr": 3.0,
         "trigger_bar": None, "entry_date": "2024-01-01",
         "opened_at": "2024-01-01T00:00:00+00:00", "status": "open",
         "tp1_hit": False, "tp2_hit": False, "tp3_hit": False, "booked_pct": 0.0,
         "realized_r": 0.0, "gross_r": 0.0, "cost_r": 0.0, "exits": [],
         "mae": entry, "mfe": entry, "mae_r": 0.0, "mfe_r": 0.0,
         "entry_type_label": "reclaim", "units": notional / entry,
         "notional": notional, "risk_usd": 100.0, "last_mark": entry}
    p.update(kw)
    return p


#
# The per-sector correlation cap exempts a row with no sector, so a HELD
# position that carries none occupies a slot while being invisible to the cap
# it should be filling. Back-fill originally read this scan's rows and then the
# Yahoo cache; neither can reach a holding that has dropped out of the scan and
# was never fetched — which is exactly the row that matters most. The market's
# universe file is the third source and the only one with full coverage.

def test_the_universe_backfills_sectors_the_scan_no_longer_lists(tmp_path, monkeypatch):
    from scanner import sectorcache
    monkeypatch.setattr(sectorcache, "load_cache", lambda: {})   # isolate: universe only
    _enable(monkeypatch, tmp_path)
    _write_market_book(tmp_path, "asx", open_=[
        _held("RIO"),        # in the universe
        _held("ZZZ"),        # in neither
    ])
    uni = [{"symbol": "RIO", "yf": "RIO.AX", "sector": "Materials"}]

    # An EMPTY scan: nothing to match on, so only the universe can fill this.
    bk = vr.run_market("asx", [], {"RIO.AX": _frame(101.0)}, uni,
                       now=_aest(2024, 1, 2, 11, 0))

    held = {p["symbol"]: p for p in bk["open"]}
    assert held["RIO"]["sector"] == "Materials"     # cap can now count it
    assert held["ZZZ"]["sector"] == ""              # unknown stays honestly blank
    # ...and it PERSISTS, so the next run's cap sees it too.
    import json
    on_disk = {p["symbol"]: p for p in
               json.loads(_mfile(tmp_path, "asx").read_text())["open"]}
    assert on_disk["RIO"]["sector"] == "Materials"


def test_a_sector_already_on_the_position_is_never_overwritten(tmp_path, monkeypatch):
    """Back-fill fills holes; it does not re-taxonomise. Overwriting a non-blank
    sector changes which trades get taken (REFINEMENTS #112, owner's call)."""
    from scanner import sectorcache
    monkeypatch.setattr(sectorcache, "load_cache", lambda: {})
    _enable(monkeypatch, tmp_path)
    _write_market_book(tmp_path, "asx", open_=[
        _held("RIO", sector="Metals & Mining")])
    uni = [{"symbol": "RIO", "yf": "RIO.AX", "sector": "Materials"}]
    bk = vr.run_market("asx", [], {"RIO.AX": _frame(101.0)}, uni,
                       now=_aest(2024, 1, 2, 11, 0))
    assert bk["open"][0]["sector"] == "Metals & Mining"


# ── the portfolio ceiling must count THIS market's own exposure ───────────────

def _notional_setup(tmp_path, monkeypatch, cap):
    _enable(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL", float(cap))
    monkeypatch.setattr(config, "VIVEK_BOT_POSITION_NOTIONAL", 5_000.0)
    # $5,000 already committed in THIS market, and nothing anywhere else.
    _write_market_book(tmp_path, "asx", open_=[
        _held("RIO", sector="Materials")])
    return [{"symbol": "BHP", "yf": "BHP.AX", "sector": "Materials"},
            {"symbol": "RIO", "yf": "RIO.AX", "sector": "Materials"}]


def test_this_markets_own_notional_counts_against_the_portfolio_ceiling(tmp_path, monkeypatch):
    """decide() seeds `open_notional` from the runner's `open_book` projection.
    That projection dropped the `notional` field, so the ceiling counted every
    market's exposure EXCEPT the one it was deciding for — an effective ceiling
    of the configured one PLUS whatever this market already held."""
    uni = _notional_setup(tmp_path, monkeypatch, cap=6_000)
    bk = vr.run_market("asx", [_row(sector="Materials")],
                       {"BHP.AX": _frame(101.0), "RIO.AX": _frame(101.0)},
                       uni, now=_aest(2024, 1, 2, 11, 0))
    # $5,000 held + $5,000 for BHP = $10,000 > the $6,000 ceiling -> declined.
    # Unfixed, this market's $5,000 read as $0 and $5,000 <= $6,000 let it in.
    assert [p["symbol"] for p in bk["open"]] == ["RIO"]


def test_the_ceiling_still_admits_an_entry_that_genuinely_fits(tmp_path, monkeypatch):
    """Control for the test above: the block must come from the arithmetic, not
    from the seeded book blocking entries for some unrelated reason."""
    uni = _notional_setup(tmp_path, monkeypatch, cap=11_000)
    bk = vr.run_market("asx", [_row(sector="Materials")],
                       {"BHP.AX": _frame(101.0), "RIO.AX": _frame(101.0)},
                       uni, now=_aest(2024, 1, 2, 11, 0))
    assert sorted(p["symbol"] for p in bk["open"]) == ["BHP", "RIO"]
