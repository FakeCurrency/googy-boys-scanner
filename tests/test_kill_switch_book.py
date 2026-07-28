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
    # Equity is PINNED here, not inherited: the config figure moved 10k -> 150k
    # on 2026-07-28 with fixed-notional sizing, and this test is about the
    # guard arithmetic (equity x pct), not about what the book happens to be.
    monkeypatch.setattr(config, "VIVEK_BOT_ACCOUNT_EQUITY", 10_000)
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
    # Equity is PINNED here, not inherited: the config figure moved 10k -> 150k
    # on 2026-07-28 with fixed-notional sizing, and this test is about the
    # guard arithmetic (equity x pct), not about what the book happens to be.
    monkeypatch.setattr(config, "VIVEK_BOT_ACCOUNT_EQUITY", 10_000)
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


# ── WHICH account a breach is allowed to flatten (2026-07-28, TOP100 #17) ──────
#
# The check is per market; the flatten is per ACCOUNT. close_all_positions()
# takes no market — it reduce-only closes every position Bybit holds. So an ASX
# paper-book breach used to liquidate the live crypto book, which held none of
# the positions that lost the money and was inside its own limit.

@pytest.fixture
def spy_flatten(monkeypatch):
    """Record which brokers got flattened, without touching a broker client.

    Patches the module-level `_flatten_<name>` functions rather than the
    dispatch table, which is why `_flatten` resolves through globals() at call
    time instead of binding the function objects in a dict at import.
    """
    hit: list[str] = []
    monkeypatch.setattr(ks, "_flatten_bybit",  lambda: hit.append("bybit"))
    monkeypatch.setattr(ks, "_flatten_alpaca", lambda: hit.append("alpaca"))
    return hit


@pytest.fixture
def both_keyed(monkeypatch):
    """Both accounts reachable — the state that makes the routing bug visible."""
    monkeypatch.setenv("BYBIT_API_KEY",  "test-key")
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")


def _breach():
    """A journal that is unambiguously past any limit these tests pass."""
    return {"open": [{"unreal_pnl": -5_000.0}], "closed": []}


def test_a_paper_market_breach_flattens_nothing_but_still_fires(
        spy_flatten, both_keyed, stub_alerts):
    """THE BUG: ASX is paper-only, and its breach was closing the crypto book.

    Losing money on a market no broker holds is not a reason to sell positions
    on a market that is inside its own limit. It must still return True (the
    caller aborts new orders) and still alert — not flattening is not the same
    as not firing.
    """
    assert ks.check_and_kill(_breach(), limit_usd=100.0, brokers=()) is True
    assert spy_flatten == []


def test_a_crypto_breach_reaches_bybit_and_only_bybit(
        spy_flatten, both_keyed, stub_alerts):
    ks.check_and_kill(_breach(), limit_usd=100.0, brokers=("bybit",))
    assert spy_flatten == ["bybit"]


def test_a_nasdaq_breach_reaches_alpaca_even_though_bybit_is_keyed(
        spy_flatten, both_keyed, stub_alerts):
    """The second defect in the old block: `if BYBIT: ... elif ALPACA: ...`.

    With both key sets present a NASDAQ loss flattened BYBIT and never touched
    the account that actually held the losing positions — wrong account
    liquidated AND the right one left running, from one breach.
    """
    ks.check_and_kill(_breach(), limit_usd=100.0, brokers=("alpaca",))
    assert spy_flatten == ["alpaca"]


def test_brokers_none_reproduces_the_legacy_first_keyed_wins_behaviour(
        spy_flatten, both_keyed, stub_alerts):
    """bybit_run.py and the pre-existing tests pass no `brokers` at all.

    They must be byte-identical to before: try Bybit, else Alpaca, never both.
    """
    ks.check_and_kill(_breach(), limit_usd=100.0)
    assert spy_flatten == ["bybit"]


def test_brokers_none_falls_through_to_alpaca_when_bybit_is_unkeyed(
        spy_flatten, monkeypatch, stub_alerts):
    monkeypatch.delenv("BYBIT_API_KEY", raising=False)
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    ks.check_and_kill(_breach(), limit_usd=100.0)
    assert spy_flatten == ["alpaca"]


def test_an_explicit_list_flattens_every_keyed_broker_not_just_the_first(
        spy_flatten, both_keyed, stub_alerts):
    """Explicit is not the legacy sentinel: the caller said BOTH hold the book."""
    ks.check_and_kill(_breach(), limit_usd=100.0, brokers=("bybit", "alpaca"))
    assert spy_flatten == ["bybit", "alpaca"]


def test_a_mapped_broker_with_no_keys_here_flattens_nothing(
        spy_flatten, monkeypatch, stub_alerts):
    monkeypatch.delenv("BYBIT_API_KEY", raising=False)
    assert ks.check_and_kill(_breach(), limit_usd=100.0, brokers=("bybit",)) is True
    assert spy_flatten == []


def test_dry_run_never_reaches_a_broker_however_it_is_routed(
        spy_flatten, both_keyed, stub_alerts):
    ks.check_and_kill(_breach(), limit_usd=100.0, brokers=("bybit", "alpaca"),
                      dry_run=True)
    assert spy_flatten == []


def test_the_alert_does_not_promise_a_flatten_that_will_not_happen(
        spy_flatten, monkeypatch):
    """The one message that has to be trustworthy described a fiction.

    The old wording was a hard-coded "Flattening all positions now", sent on a
    paper market with no broker and no keys. An operator reading that has been
    told their positions were closed when nothing was.
    """
    import scanner.broker.alert_dispatch as ad
    sent: list = []
    monkeypatch.setattr(ad, "send", lambda *a, **k: sent.append(a), raising=False)

    ks.check_and_kill(_breach(), limit_usd=100.0, brokers=())
    body = sent[-1][2]
    assert "paper book" in body and "Flattening" not in body

    monkeypatch.setenv("BYBIT_API_KEY", "test-key")
    ks.check_and_kill(_breach(), limit_usd=100.0, brokers=("bybit",))
    assert "Flattening bybit now" in sent[-1][2]


# ── run_standalone routing: the map, the de-dupe, the unmapped fallback ────────

def _breached_book(markets):
    """One open position per named market, each far past any sane limit."""
    return _book(open_=[_pos(f"SYM{i}", m, risk_usd=100_000.0, unreal_usd=-99_000.0)
                        for i, m in enumerate(markets)])


@pytest.fixture
def book_on_disk(tmp_path, monkeypatch):
    import scanner.broker.vivek_run as vr

    def _write(book):
        p = tmp_path / "vivek_bot_book.json"
        p.write_text(json.dumps(book), encoding="utf-8")
        monkeypatch.setattr(vr, "BOOK_FILE", p)
        monkeypatch.setattr(ks, "_live_marks", lambda b: {})   # no network
        return p
    # Equity PINNED, as everywhere else in this file: the guard arithmetic is
    # what is under test, not whatever the live config happens to be.
    monkeypatch.setattr(config, "VIVEK_BOT_ACCOUNT_EQUITY", 10_000)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)   # $300
    return _write


def test_run_standalone_routes_each_market_to_its_own_broker(
        book_on_disk, spy_flatten, both_keyed, stub_alerts, monkeypatch):
    """An ASX-only breach must leave the crypto account alone. That is #17."""
    book_on_disk(_breached_book(["asx"]))
    monkeypatch.setattr(config, "VIVEK_KILL_SWITCH_BROKERS",
                        {"asx": (), "nasdaq": ("alpaca",), "crypto": ("bybit",)},
                        raising=False)
    out = ks.run_standalone()
    assert out["triggered"] == ["asx"]
    assert spy_flatten == []                 # <- the whole point
    assert out["flattened"] == []


def test_run_standalone_flattens_the_account_that_holds_the_loss(
        book_on_disk, spy_flatten, both_keyed, stub_alerts, monkeypatch):
    book_on_disk(_breached_book(["crypto"]))
    monkeypatch.setattr(config, "VIVEK_KILL_SWITCH_BROKERS",
                        {"asx": (), "nasdaq": ("alpaca",), "crypto": ("bybit",)},
                        raising=False)
    out = ks.run_standalone()
    assert out["triggered"] == ["crypto"]
    assert spy_flatten == ["bybit"] and out["flattened"] == ["bybit"]


def test_two_markets_on_one_broker_flatten_it_exactly_once(
        book_on_disk, spy_flatten, both_keyed, stub_alerts, monkeypatch):
    """N breached markets used to mean N full cancel-all + close-all cycles.

    The second one races the first's reduce-only orders against an account that
    is already flat, which is noise at best and a rejected-order storm at worst.
    """
    book_on_disk(_breached_book(["nasdaq", "crypto"]))
    monkeypatch.setattr(config, "VIVEK_KILL_SWITCH_BROKERS",
                        {"asx": (), "nasdaq": ("bybit",), "crypto": ("bybit",)},
                        raising=False)
    out = ks.run_standalone()
    assert set(out["triggered"]) == {"nasdaq", "crypto"}   # both still FIRE
    assert spy_flatten == ["bybit"]                        # ...one flatten
    assert out["flattened"] == ["bybit"]


def test_an_unmapped_market_falls_back_to_the_account_wide_flatten(
        book_on_disk, spy_flatten, both_keyed, stub_alerts, monkeypatch, caplog):
    """Deliberately over-protective: a new market is NOISY, never unguarded.

    Leaving it out of the map must not quietly disarm the switch for it, so it
    keeps the legacy behaviour and logs loudly enough to get the map fixed.
    """
    book_on_disk(_breached_book(["asx"]))
    monkeypatch.setattr(config, "VIVEK_KILL_SWITCH_BROKERS",
                        {"nasdaq": ("alpaca",), "crypto": ("bybit",)},
                        raising=False)
    with caplog.at_level("WARNING"):
        out = ks.run_standalone()
    assert out["triggered"] == ["asx"]
    assert spy_flatten == ["bybit"]                        # legacy first-keyed
    assert any("VIVEK_KILL_SWITCH_BROKERS" in r.getMessage()
               for r in caplog.records if r.levelname == "WARNING")


def test_flattened_reports_only_accounts_that_were_actually_reachable(
        book_on_disk, spy_flatten, stub_alerts, monkeypatch):
    """The Actions summary must not claim a flatten that had no key to run.

    `flattened` is read by _write_step_summary, whose other branch tells the
    owner the mapped broker has no keys set here. Recording the ROUTED broker
    instead of the ARMED one puts every keyless run in the wrong branch.
    """
    monkeypatch.delenv("BYBIT_API_KEY", raising=False)
    book_on_disk(_breached_book(["crypto"]))
    monkeypatch.setattr(config, "VIVEK_KILL_SWITCH_BROKERS",
                        {"asx": (), "nasdaq": ("alpaca",), "crypto": ("bybit",)},
                        raising=False)
    out = ks.run_standalone()
    assert out["triggered"] == ["crypto"]
    assert spy_flatten == [] and out["flattened"] == []


def test_dry_run_reports_no_flatten_and_performs_none(
        book_on_disk, spy_flatten, both_keyed, stub_alerts, monkeypatch):
    book_on_disk(_breached_book(["crypto"]))
    monkeypatch.setattr(config, "VIVEK_KILL_SWITCH_BROKERS",
                        {"asx": (), "nasdaq": ("alpaca",), "crypto": ("bybit",)},
                        raising=False)
    out = ks.run_standalone(dry_run=True)
    assert out["triggered"] == ["crypto"]
    assert spy_flatten == [] and out["flattened"] == []


def test_the_shipped_config_map_covers_every_market_and_names_real_brokers():
    """A market missing here is not broken, but it IS the noisy fallback path.

    Kept as a test rather than a comment because the failure is silent in
    production: the switch still works, it just goes back to flattening
    accounts that do not hold the loss.
    """
    routing = config.VIVEK_KILL_SWITCH_BROKERS
    assert set(routing) == set(config.MARKETS)
    for market, brokers in routing.items():
        assert isinstance(brokers, tuple), market
        for b in brokers:
            assert b in ks._FLATTEN_KEYS, f"{market} -> unknown broker {b!r}"
