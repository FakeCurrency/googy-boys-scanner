"""Kill-switch on the BOT BOOK (2026-07-20, review C5).

The scheduled kill-switch used to read the retired scalp journal — always
$0.00, could never fire. It now reads journal/vivek_bot_book.json per market
with the VIVEK guard limit, and (2026-10-14, REFINE200 #16) measures the same
session WINDOW the runner's guard does. These tests pin the adapter maths and
the end-to-end trigger path (dry-run — never flattens a broker in tests).
"""

import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest

from scanner import config
from scanner.broker import kill_switch as ks
from scanner.broker import vivek_guard as vg

pytestmark = pytest.mark.risk


def _book(open_=None, closed=None):
    return {"version": 1, "mode": "paper",
            "open": list(open_ or []), "closed": list(closed or [])}


def _market_today(market):
    return dt.datetime.now(ZoneInfo(config.MARKETS[market].timezone)).strftime("%Y-%m-%d")


def test_adapter_selects_the_market_and_the_market_day():
    book = _book(
        open_=[_pos("BHP", "asx", last_mark=100.0, day_marks={"2024-01-02": 100.0}),
               _pos("MDB", "nasdaq", last_mark=50.0, risk_usd=999.0)],   # other market
        closed=[{"market": "asx", "exit_date": "2024-01-02", "realized_r": -2.0, "risk_usd": 100.0},
                {"market": "asx", "exit_date": "2024-01-01", "realized_r": -5.0, "risk_usd": 100.0},  # other day
                {"market": "nasdaq", "exit_date": "2024-01-02", "realized_r": -9.0, "risk_usd": 100.0}],
    )
    j = ks._book_market_journal(book, "asx", "2024-01-02")
    assert j["guard"]["realised_usd"] == pytest.approx(-200.0)   # today's asx close only
    assert j["positions"] == 1
    assert j["session_usd"] == pytest.approx(-200.0)             # BHP flat on its day ref


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


def test_adapter_live_quote_reprices_from_the_days_reference():
    """A live quote is measured from the mark the position carried into the
    day: carried in at 100, quote 90 -> -2R on $100."""
    pos = _pos(day_marks={"2024-01-02": 100.0}, last_mark=95.0)
    j = ks._book_market_journal(_book(open_=[pos]), "asx", "2024-01-02",
                                quotes={("BHP", "asx"): 90.0})
    assert j["session_usd"] == pytest.approx(-200.0)
    assert j["live_marks"] == 1


def test_adapter_no_quote_falls_back_to_the_last_scan_mark():
    pos = _pos(day_marks={"2024-01-02": 100.0}, last_mark=95.0)
    j = ks._book_market_journal(_book(open_=[pos]), "asx", "2024-01-02",
                                quotes={})
    assert j["session_usd"] == pytest.approx(-100.0)     # 100 -> 95 = -1R
    assert j["live_marks"] == 0 and j["guard"]["unpriced"] == []


def test_adapter_malformed_row_cannot_crash_or_poison_the_check():
    bad = _pos(last_mark=95.0)
    del bad["entry"]                      # _unreal_r used to KeyError on this
    bad["risk"] = float("nan")
    j = ks._book_market_journal(_book(open_=[bad]), "asx", "2024-01-02",
                                quotes={("BHP", "asx"): 90.0})
    assert j["session_usd"] == pytest.approx(0.0)


def test_adapter_never_writes_the_book_it_measures():
    pos = _pos(last_mark=95.0)
    book = _book(open_=[pos])
    before = json.dumps(book, sort_keys=True)
    ks._book_market_journal(book, "asx", "2024-01-02", quotes={("BHP", "asx"): 90.0})
    assert json.dumps(book, sort_keys=True) == before    # no day_marks stamped


def test_run_standalone_fires_on_live_move_stale_mark_says_fine(
        tmp_path, monkeypatch, stub_alerts):
    """THE reason for Phase 4: the mark stamped at last scan says -$80 (fine),
    the market has since moved to -$720 — the live quote must trip the switch."""
    import scanner.broker.vivek_run as vr
    book = _book(open_=[_pos(risk_usd=400.0, last_mark=99.0)])   # 99 -> 90 = -1.8R x $400
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

    asked = []

    def fake_download(tickers, period=None, retries=None, **kw):
        asked.append(list(tickers))
        px = {"BHP.AX": _frame(42.0), "BTC-USD": _frame(50000.0)}
        return {t: px[t] for t in tickers if t in px}

    monkeypatch.setattr(sdata, "download", fake_download)
    # A crypto quote must be the coin's own price (identity check vs its last
    # mark / entry), so the BTC fixture holds a BTC-sized entry.
    book = _book(open_=[_pos("BHP", "asx"), _pos("BTC", "crypto", entry=49000.0),
                        _pos("GHOST", "not_a_market")])
    q = ks._live_marks(book)
    assert q == {("BHP", "asx"): 42.0, ("BTC", "crypto"): 50000.0}
    # Stocks: one Yahoo batch, suffix-mapped. Crypto: through data.fetch --
    # the exchange klines the scan marks with (2026-09-28); tests refuse the
    # exchanges (conftest), so it falls back to Yahoo, as it does live for a
    # coin no exchange lists.
    assert asked == [["BHP.AX"], ["BTC-USD"]]


def test_live_marks_price_crypto_from_the_exchange_the_scan_uses(monkeypatch):
    """The kill switch must never measure a crypto position on a different
    venue's print than the one the scan marked and stopped it on."""
    import pandas as pd

    import scanner.data as sdata
    from scanner import exchange_data as ex

    monkeypatch.setattr(sdata, "download", lambda *a, **k: pytest.fail("crypto must not hit Yahoo"))
    # today's bar: an older one is a delisted pair's frozen klines (age gate)
    idx_ms = int(pd.Timestamp.now(tz="UTC").normalize().timestamp() * 1000)
    monkeypatch.setattr(ex, "_get_json", lambda url, timeout: [
        [idx_ms, "1", "2", "0.5", "51000", "1", idx_ms + 1, "9"]] if "BTCUSDT" in url else [])
    q = ks._live_marks(_book(open_=[_pos("BTC", "crypto", entry=50000.0)]))
    assert q == {("BTC", "crypto"): 51000.0}


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
    """One close TODAY (market-local) per named market, far past any sane limit."""
    return _book(closed=[{"symbol": f"SYM{i}", "market": m, "exit_date": _market_today(m),
                          "realized_r": -1.0, "risk_usd": 100_000.0}
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


# ── REFINE200 #16: the switch measures the window the runner's guard measures ──
#
# It used to hand check_and_kill each open position's WHOLE-LIFE P&L as
# "today": a position down 5R since June read as a 5R day every half hour --
# and on this switch a false breach is a flatten, not a halted entry.

def _guard_book(day):
    """A book that exercises every leg: a stamped open position, one the runner
    has not stamped yet today, a scaled runner, today's close, an old close."""
    return _book(
        open_=[
            _pos("OLD", entry_date="2026-06-01", risk_usd=400.0, last_mark=80.0,
                 day_marks={"2026-07-27": 82.0, day: 80.0}),
            _pos("FRESH", entry_date="2026-07-01", risk_usd=200.0, last_mark=104.0,
                 day_marks={"2026-07-27": 101.0}),          # no stamp for today yet
            _pos("RUN", entry_date="2026-07-01", risk_usd=100.0, last_mark=110.0,
                 day_marks={day: 108.0}, booked_pct=0.25, realized_r=0.5,
                 exits=[{"reason": "tp1", "price": 110.0, "pct": 0.25, "date": day}]),
        ],
        closed=[
            {"symbol": "GONE", "market": "asx", "direction": "long", "entry": 100.0,
             "risk": 5.0, "risk_usd": 300.0, "entry_date": "2026-07-01",
             "status": "closed", "exit_date": day, "booked_pct": 1.0,
             "realized_r": -1.2, "last_mark": 94.0, "day_marks": {day: 96.0},
             "exits": [{"reason": "stop", "price": 94.0, "pct": 1.0, "date": day}]},
            {"symbol": "LAST", "market": "asx", "exit_date": "2026-07-20",
             "realized_r": -3.0, "risk_usd": 300.0},
        ])


def test_the_kill_switch_and_the_guard_agree_on_one_book():
    """THE PIN. Same book, same prices: the switch's session figure IS the
    runner's guard figure -- after the runner's own day stamp, which the switch
    reproduces on a copy for any position the day's first run has not reached."""
    import copy

    import scanner.broker.vivek_run as vr
    day = "2026-07-28"
    quotes = {("OLD", "asx"): 76.0, ("FRESH", "asx"): 101.0}     # RUN unquoted
    book = _guard_book(day)
    j = ks._book_market_journal(book, "asx", day, quotes=quotes)

    stamped = copy.deepcopy(book)                 # what the runner sees after stamping
    for p in stamped["open"]:
        vr._stamp_day_ref(p, day, None)
    prices = {"OLD": 76.0, "FRESH": 101.0, "RUN": 110.0}         # RUN at its last mark
    guard = vg.check(stamped, "asx", day, 150_000, prices.get)
    assert j["session_usd"] == guard["session_usd"]
    assert j["guard"] == vg.session_pnl(stamped, "asx", day, prices.get)
    # and the number is a DAY's: OLD -0.8R, FRESH -0.6R, RUN +0.1 banked +0.3
    # open, GONE -0.4R -- not OLD's -4.8R life nor GONE's -1.2R
    assert j["session_usd"] == pytest.approx(-320.0 - 120.0 + 40.0 - 120.0)


def test_an_old_loser_flat_today_does_not_fire_the_switch(
        tmp_path, monkeypatch, stub_alerts):
    """The live failure the window model exists for, on the switch: down 5R
    since June ($2,000 on $400 of risk) and flat since the day began."""
    import scanner.broker.vivek_run as vr
    day = _market_today("asx")
    book = _book(open_=[_pos("OLD", entry_date="2026-06-01", risk_usd=400.0,
                             last_mark=75.0, day_marks={day: 75.0})])
    p = tmp_path / "vivek_bot_book.json"
    p.write_text(json.dumps(book), encoding="utf-8")
    monkeypatch.setattr(vr, "BOOK_FILE", p)
    monkeypatch.setattr(config, "VIVEK_BOT_ACCOUNT_EQUITY", 10_000)
    monkeypatch.setattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 3.0)   # $300
    monkeypatch.setattr(ks, "_live_marks", lambda b: {("OLD", "asx"): 75.0})
    assert ks.run_standalone(dry_run=True)["triggered"] == []
    # control: the same position losing a real 1R today does fire
    monkeypatch.setattr(ks, "_live_marks", lambda b: {("OLD", "asx"): 70.0})
    assert ks.run_standalone(dry_run=True)["triggered"] == ["asx"]


def test_before_the_days_first_run_the_switch_measures_from_the_carried_mark():
    """No stamp for today yet (the ASX's first scan is 11:00; the switch runs
    from midnight): the reference is the mark the last run left, exactly what
    that first run will stamp -- never the position's oldest stamp."""
    day = "2026-07-28"
    pos = _pos("A", entry_date="2026-07-01", risk_usd=100.0, last_mark=90.0,
               day_marks={"2026-07-20": 110.0, "2026-07-27": 95.0})
    j = ks._book_market_journal(_book(open_=[pos]), "asx", day,
                                quotes={("A", "asx"): 90.0})
    assert j["session_usd"] == pytest.approx(0.0)        # not (90-110)/5 = -4R


def test_a_nan_quote_never_reaches_the_loss_check(monkeypatch):
    """REFINE200 #19: NaN passed `px <= 0` and the sanity ratio."""
    import pandas as pd

    import scanner.data as sdata
    idx = pd.date_range(end="2024-01-02", periods=3, freq="D")
    monkeypatch.setattr(sdata, "download", lambda t, period=None, retries=None, **kw:
                        {"BHP.AX": pd.DataFrame({"Close": [1.0, 2.0, float("nan")]}, index=idx)})
    assert ks._live_marks(_book(open_=[_pos("BHP", "asx", last_mark=2.0)])) == {}


def test_a_nan_row_does_not_fire_check_and_kill(stub_alerts):
    """A NaN total compares False against `>= -limit`, which FIRED the switch."""
    j = {"open": [{"unreal_pnl": float("nan")}, {"unreal_pnl": -10.0}], "closed": []}
    assert ks.check_and_kill(j, dry_run=True, limit_usd=300.0) is False
    assert ks.check_and_kill({"session_usd": float("nan")}, dry_run=True,
                             limit_usd=300.0) is False


def test_a_zero_limit_is_off_as_it_is_in_the_guard(stub_alerts):
    j = {"session_usd": -10_000.0}
    assert ks.check_and_kill(j, dry_run=True, limit_usd=0.0) is False
    assert ks.check_and_kill(j, dry_run=True, limit_usd=300.0) is True
