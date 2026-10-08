"""Audit #69 and #30 (2026-10-08): the edge ledgers' forward-return stamps.

#69 -- stamp() re-derived the base bar on every run as "the first completed bar
on/after base_day" in a fixed period='3mo' frame and never consulted what it
had stored. Once base_day slid out of that window (a long suspension, a row
that stays unmatured), the base silently became a bar weeks later and the
remaining horizons froze against it. The base bar is now pinned by date
(`base_bar`), a legacy row is only re-found in a frame that reaches base_day
and within ALERT_RETURNS_BASE_MAX_GAP_DAYS of it, and each ticker downloads a
period that covers its oldest wanted base_day.

#30 -- both ledgers priced crypto through Yahoo's `download`, with no identity
check, so a colliding ticker (JUP: Yahoo 0.000327 vs the scanned $0.37) froze
another token's returns. Crypto now goes through scanner.data.fetch with the
identity check armed, and a stored base that is not the instrument now
priced is never extended.

Forward fixes only: no frozen value is rewritten by any of this.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib

import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("alert_returns", ROOT / "scripts" / "alert_returns.py")
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)
er_spec = importlib.util.spec_from_file_location("edge_rosters", ROOT / "scripts" / "edge_rosters.py")
er = importlib.util.module_from_spec(er_spec)
er_spec.loader.exec_module(er)

UTC = dt.timezone.utc


def _row(market, ticker, base_day, base_close=None, fwd=None, **kw):
    r = {"key": f"{base_day}|{market}|{ticker}|long|2", "market": market, "ticker": ticker,
         "side": "long", "base_day": base_day, "base_close": base_close,
         "fwd": fwd or {str(h): None for h in ar.HORIZONS}}
    r.update(kw)
    return r


def _bars(sym, index, closes):
    return {sym: pd.DataFrame({"Close": list(closes)}, index=pd.DatetimeIndex(index))}


# ── #69: the base bar ────────────────────────────────────────────────────────

def test_the_audits_suspension_case_never_reanchors_on_the_resumption_bar(capsys):
    """Alert 2026-06-15, base_close 2.50 stored; suspended until 2026-09-21,
    resumes at 1.00. The next run's 3-month frame starts after the suspension:
    the old code took the resumption bar as the base and froze +5%/+25%/+50%
    where the true move was -60%."""
    led = ar._fresh()
    led["entries"].append(_row("asx", "XYZ", "2026-06-15", base_close=2.5))
    idx = pd.bdate_range("2026-09-21", periods=30)
    frames = _bars("XYZ.AX", idx, [1.0 + 0.05 * i for i in range(30)])
    now = dt.datetime(2026, 11, 20, tzinfo=UTC)
    assert ar.stamp(led, frames, ar.wanting_prices(led, now.date()), now) == 0
    e = led["entries"][0]
    assert e["fwd"] == {str(h): None for h in ar.HORIZONS}, "never measured off the resumption bar"
    assert e["base_close"] == 2.5 and "base_bar" not in e, "the stored row is untouched"
    assert "WARNING stamp: 1 entry left unstamped" in capsys.readouterr().out


def test_a_halt_from_the_alert_session_is_a_gap_not_a_base():
    """The frame DOES reach back to base_day, but the first bar after it is a
    month later (halted from the alert session): no base, retried."""
    led = ar._fresh()
    led["entries"].append(_row("asx", "HLT", "2026-08-03"))
    idx = list(pd.bdate_range("2026-07-20", "2026-07-31")) + list(pd.bdate_range("2026-09-01", periods=25))
    frames = _bars("HLT.AX", idx, [10.0] * len(idx))
    now = dt.datetime(2026, 10, 20, tzinfo=UTC)
    ar.stamp(led, frames, ar.wanting_prices(led, now.date()), now)
    assert led["entries"][0]["base_close"] is None


def test_a_frame_that_starts_after_base_day_never_finds_a_base_in_it(capsys):
    """A legacy row (stored base, no base_bar) whose download no longer
    reaches its base_day: the first bar in the frame is three days LATER --
    inside the holiday allowance, so only the coverage check stands between
    it and a base that is not the alert session's close."""
    led = ar._fresh()
    frozen = {"1": 0.01, "5": None, "10": None, "20": None}
    led["entries"].append(_row("asx", "SLD", "2026-06-15", base_close=2.5, fwd=dict(frozen)))
    idx = pd.bdate_range("2026-06-18", periods=30)
    frames = _bars("SLD.AX", idx, [1.0 + 0.05 * i for i in range(30)])
    now = dt.datetime(2026, 8, 20, tzinfo=UTC)
    assert ar.stamp(led, frames, ar.wanting_prices(led, now.date()), now) == 0
    assert led["entries"][0]["fwd"] == frozen, "never measured off a bar after the alert session"
    assert "the frame starts after base_day" in capsys.readouterr().out


def test_a_weekend_or_holiday_base_still_finds_the_next_session():
    # Good Friday 2027-03-26 alert -> the Tuesday (Easter Monday shut): +4 days.
    led = ar._fresh()
    led["entries"].append(_row("asx", "BHP", "2027-03-26"))
    idx = pd.to_datetime(["2027-03-24", "2027-03-25", "2027-03-30", "2027-03-31"])
    frames = _bars("BHP.AX", idx, [40.0, 41.0, 42.0, 42.84])
    now = dt.datetime(2027, 4, 2, tzinfo=UTC)
    ar.stamp(led, frames, ar.wanting_prices(led, now.date()), now)
    e = led["entries"][0]
    assert e["base_close"] == 42.0 and e["base_bar"] == "2027-03-30"
    assert e["fwd"]["1"] == 0.02


def test_the_first_stamp_pins_the_base_bar_and_later_runs_measure_from_it():
    led = ar._fresh()
    led["entries"].append(_row("asx", "BHP", "2026-08-03"))
    idx = pd.bdate_range("2026-07-27", periods=12)            # Mon 27 Jul ..
    closes = [100.0 + i for i in range(12)]
    first = dt.datetime(2026, 8, 5, tzinfo=UTC)                # base + 1 session done
    ar.stamp(led, _bars("BHP.AX", idx[:8], closes[:8]), ar.wanting_prices(led, first.date()), first)
    e = led["entries"][0]
    assert e["base_bar"] == "2026-08-03" and e["base_close"] == 105.0
    # A later download LOST the base bar (Yahoo dropped it). The old code took
    # the next bar as the base and measured every new horizon from it.
    later = dt.datetime(2026, 8, 20, tzinfo=UTC)
    keep = [i for i in range(12) if idx[i].date() != dt.date(2026, 8, 3)]
    ar.stamp(led, _bars("BHP.AX", [idx[i] for i in keep], [closes[i] for i in keep]),
             ar.wanting_prices(led, later.date()), later)
    assert e["fwd"]["5"] is None, "never measured from a bar that is not the base"
    # With the base bar back, the horizon is the close 5 bars after IT.
    ar.stamp(led, _bars("BHP.AX", idx, closes), ar.wanting_prices(led, later.date()), later)
    assert e["fwd"]["5"] == round(110.0 / 105.0 - 1.0, 6)


@pytest.mark.parametrize("age,period", [(0, "3mo"), (81, "3mo"), (82, "6mo"),
                                        (173, "6mo"), (300, "1y"), (700, "2y"), (2000, "max")])
def test_the_period_reaches_the_oldest_wanted_base_day(age, period):
    today = dt.date(2026, 10, 8)
    old = (today - dt.timedelta(days=age)).isoformat()
    young = (today - dt.timedelta(days=2)).isoformat()
    assert ar.period_for([_row("asx", "X", young), _row("asx", "X", old)], today) == period


def test_main_downloads_each_ticker_over_the_period_its_oldest_row_needs(tmp_path, monkeypatch):
    import scanner.data
    today = dt.datetime.now(UTC).date()
    led = {"schema_version": 1, "updated_at": "", "entries": [
        _row("asx", "OLD", (today - dt.timedelta(days=120)).isoformat()),
        _row("asx", "NEW", (today - dt.timedelta(days=10)).isoformat())]}
    (tmp_path / "ledger.json").write_text(json.dumps(led), encoding="utf-8")
    (tmp_path / "history.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    monkeypatch.setattr(ar, "LEDGER", str(tmp_path / "ledger.json"))
    monkeypatch.setattr(ar, "HISTORY", str(tmp_path / "history.json"))
    asked = []
    monkeypatch.setattr(scanner.data, "download",
                        lambda syms, period=None, **k: asked.append((sorted(syms), period)) or {})
    assert ar.main(["--dry-run"]) == 0
    assert sorted(asked) == [(["NEW.AX"], "3mo"), (["OLD.AX"], "6mo")]


# ── #30: crypto is priced as its own coin ────────────────────────────────────

DAY_MS = 86_400_000


def _today_utc():
    return pd.Timestamp.now(tz="UTC").normalize()


def _klines(px, n=10):
    """Binance-shaped daily klines ending TODAY (the venue age gate refuses old ones)."""
    t0 = int((_today_utc() - pd.Timedelta(days=n - 1)).timestamp() * 1000)
    return [[t0 + i * DAY_MS, str(px), str(px), str(px), str(px), "1", t0 + i * DAY_MS + 1, "9e6"]
            for i in range(n)]


def _yahoo_frame(px, n=10):
    idx = pd.date_range(end=_today_utc().tz_localize(None), periods=n, freq="D")
    return pd.DataFrame({"Open": px, "High": px, "Low": px, "Close": px, "Volume": 1e6}, index=idx)


@pytest.fixture
def venues(monkeypatch, tmp_path):
    """Binance's mirror lists the REAL coins; Yahoo's `download` serves the
    audit's same-ticker stranger for JUP (0.000327 against a ~$0.37 coin).
    The committed scan prices are a temp file the test writes."""
    from scanner import config, data, exchange_data as X
    monkeypatch.setattr(config, "CRYPTO_DATA_SOURCE", "exchange")
    monkeypatch.setattr(config, "EXCHANGE_KLINE_SOURCES", ("binance_vision", "coinbase"))
    monkeypatch.setattr(X.time, "sleep", lambda s: None)
    import urllib.error

    def install(binance, yahoo, scan_prices):
        def router(url, timeout):
            if "binance.vision" in url:
                for pair, px in binance.items():
                    if f"symbol={pair}USDT" in url:
                        return _klines(px)
                raise urllib.error.HTTPError("u", 400, "x", None, None)
            raise urllib.error.HTTPError("u", 404, "x", None, None)

        monkeypatch.setattr(X, "_get_json", router)
        asked = []
        monkeypatch.setattr(data, "download", lambda t, period=None, **k: (
            asked.append(sorted(t)) or {x: _yahoo_frame(yahoo[x]) for x in t if x in yahoo}))
        prices = tmp_path / "crypto_prices.json"
        prices.write_text(json.dumps({"prices": scan_prices}), encoding="utf-8")
        monkeypatch.setattr(ar, "SCAN_PRICES", str(prices))
        return asked
    return install


def _history(tmp_path, monkeypatch, entries):
    hist = tmp_path / "history.json"
    hist.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    monkeypatch.setattr(ar, "HISTORY", str(hist))
    monkeypatch.setattr(ar, "LEDGER", str(tmp_path / "ledger.json"))


def test_the_audits_JUP_alignment_is_stamped_off_the_real_coin(venues, tmp_path, monkeypatch):
    """The 2026-09-29 JUP short: Yahoo's JUP-USD is another token (0.000327);
    the VIVEK leg scanned the real one (~$0.37). The ledger must measure the
    coin the alert was about."""
    asked = venues(binance={"JUP": 0.37}, yahoo={"JUP-USD": 0.000327},
                   scan_prices={"JUP": 0.3667})
    when = (_today_utc() - pd.Timedelta(days=3)).replace(hour=1, minute=43)
    _history(tmp_path, monkeypatch, [{"date": when.isoformat(), "market": "crypto",
                                      "ticker": "JUP", "side": "short", "count": 2,
                                      "lenses": ["PHASEMAP", "VIVEK"]}])
    assert ar.main([]) == 0
    e = json.loads((tmp_path / "ledger.json").read_text())["entries"][0]
    assert e["base_close"] == 0.37, "the base is the real JUP, not Yahoo's stranger"
    assert e["base_bar"] == when.strftime("%Y-%m-%d") and e["fwd"]["1"] == 0.0
    assert e["base_identity"] == "ref", "checked against the scan's price, and it says so"
    assert ["JUP-USD"] not in asked, "Yahoo's JUP was never even the candidate"


def test_a_coin_nothing_vouches_for_is_left_unstamped_never_priced_unchecked(venues, capsys):
    """Binance lists XYZ, but the scan has no price for it and the row has no
    pinned base: the identity check has nothing to check against, so it is
    refused -- the row waits, named, instead of freezing an unchecked series."""
    venues(binance={"XYZ": 2.0}, yahoo={"XYZ-USD": 2.0}, scan_prices={"BTC": 82000.0})
    day = (_today_utc() - pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    want = {"XYZ-USD": [_row("crypto", "XYZ", day)]}
    frames = ar.fetch_frames(want, _today_utc().date())
    assert "XYZ-USD" not in frames
    assert "left unpriced - no source proved it is the coin" in capsys.readouterr().out


def test_a_pinned_base_is_the_rows_own_history_anchor(venues):
    """A row stamped since base_bar existed vouches for its coin itself: the
    venue's frame must reproduce (base_bar, base_close) -- so a coin that has
    left the scan still matures, and a stranger still cannot."""
    day = (_today_utc() - pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    row = _row("crypto", "OLD", day, base_close=1.0, base_bar=day, base_identity="ref")
    venues(binance={"OLD": 1.0}, yahoo={}, scan_prices={})
    assert "OLD-USD" in ar.fetch_frames({"OLD-USD": [row]}, _today_utc().date())
    venues(binance={"OLD": 50.0}, yahoo={"OLD-USD": 50.0}, scan_prices={})
    assert "OLD-USD" not in ar.fetch_frames({"OLD-USD": [row]}, _today_utc().date())


def test_crypto_identity_kwargs_prefers_the_rows_anchor_and_requires_identity(tmp_path, monkeypatch):
    prices = tmp_path / "p.json"
    prices.write_text(json.dumps({"prices": {"JUP": 0.3667, "BTC": 82000.0}}), encoding="utf-8")
    monkeypatch.setattr(ar, "SCAN_PRICES", str(prices))
    want = {"JUP-USD": [_row("crypto", "JUP", "2026-10-01")],
            "BTC-USD": [_row("crypto", "BTC", "2026-09-20", base_close=80000.0, base_bar="2026-09-20",
                             base_identity="anchor"),
                        _row("crypto", "BTC", "2026-09-25", base_close=81000.0, base_bar="2026-09-25",
                             base_identity="ref")]}
    kw = ar.crypto_identity_kwargs(want)
    assert kw["require_identity"] is True
    assert kw["ref_prices"] == {"JUP-USD": 0.3667, "BTC-USD": 82000.0}
    assert kw["anchors"] == {"BTC-USD": ("2026-09-25", 81000.0)}, "the newest pinned base"


def test_a_base_an_unchecked_frame_set_never_vouches_for_the_coin(tmp_path, monkeypatch):
    """A Yahoo-mode run (CRYPTO_DATA_SOURCE="yahoo") prices crypto with no
    identity check, so the base it pins may be a same-ticker stranger's close.
    Anchoring on it would let the stranger vouch for itself -- and for every
    later row on the coin -- once exchange mode is back (data.anchor_of's rule:
    an unchecked frame is never the evidence the next check trusts)."""
    prices = tmp_path / "p.json"
    prices.write_text(json.dumps({"prices": {"JUP": 0.3667}}), encoding="utf-8")
    monkeypatch.setattr(ar, "SCAN_PRICES", str(prices))
    want = {"JUP-USD": [_row("crypto", "JUP", "2026-10-01", base_close=0.000327,
                             base_bar="2026-10-01", base_identity="none"),
                        _row("crypto", "JUP", "2026-10-02", base_close=0.00033,
                             base_bar="2026-10-02"),            # stamped before the field
                        _row("crypto", "JUP", "2026-10-05")]}
    kw = ar.crypto_identity_kwargs(want)
    assert kw["anchors"] == {}, "an unchecked base is never an anchor"
    assert kw["ref_prices"] == {"JUP-USD": 0.3667}, "the scan's price is the check instead"


def test_the_first_crypto_stamp_records_how_its_frame_was_checked():
    led = ar._fresh()
    led["entries"] += [_row("crypto", "AAA", "2026-10-01"), _row("crypto", "BBB", "2026-10-01"),
                       _row("asx", "CCC", "2026-10-01")]
    idx = pd.date_range("2026-09-28", periods=6, freq="D")
    frames = {**_bars("AAA-USD", idx, [1.0] * 6), **_bars("BBB-USD", idx, [2.0] * 6),
              **_bars("CCC.AX", idx, [3.0] * 6)}
    frames["AAA-USD"].attrs["identity"] = "anchor"           # BBB-USD: no stamp at all
    now = dt.datetime(2026, 10, 4, 1, 0, tzinfo=UTC)
    ar.stamp(led, frames, ar.wanting_prices(led, now.date()), now)
    a, b, c = led["entries"]
    assert a["base_identity"] == "anchor" and b["base_identity"] == "none"
    assert "base_identity" not in c, "stocks have no identity check to record"


def test_a_row_frozen_on_another_instrument_is_never_extended(capsys):
    """The committed JUP row: base 0.000327 and 1s/5s from Yahoo's token. Now
    priced on the real coin, its 10s/20s must NOT be measured against the
    stranger's base, and its frozen values stay exactly as they are."""
    led = ar._fresh()
    frozen = {"1": -0.003058, "5": -0.009174, "10": None, "20": None}
    led["entries"].append(_row("crypto", "JUP", "2026-09-29", base_close=0.000327, fwd=dict(frozen)))
    idx = pd.date_range("2026-09-20", periods=40, freq="D")
    frames = _bars("JUP-USD", idx, [0.37] * 40)
    now = dt.datetime(2026, 10, 29, 1, 0, tzinfo=UTC)
    assert ar.stamp(led, frames, ar.wanting_prices(led, now.date()), now) == 0
    e = led["entries"][0]
    assert e["fwd"] == frozen and e["base_close"] == 0.000327 and "base_bar" not in e
    assert "another instrument" in capsys.readouterr().out


def test_a_legacy_crypto_row_on_the_same_coin_keeps_maturing():
    # Yahoo and the exchange agree on a non-colliding coin to ~0.1%.
    led = ar._fresh()
    led["entries"].append(_row("crypto", "BTC", "2026-09-29", base_close=80000.0,
                               fwd={"1": 0.01, "5": 0.02, "10": None, "20": None}))
    idx = pd.date_range("2026-09-20", periods=40, freq="D")
    closes = [80080.0] * 9 + [80080.0 * (1 + 0.001 * i) for i in range(31)]
    frames = _bars("BTC-USD", idx, closes)
    now = dt.datetime(2026, 10, 29, 1, 0, tzinfo=UTC)
    ar.stamp(led, frames, ar.wanting_prices(led, now.date()), now)
    e = led["entries"][0]
    assert e["fwd"]["1"] == 0.01 and e["fwd"]["10"] is not None and e["fwd"]["20"] is not None


def test_a_legacy_base_from_a_forming_bar_is_still_the_same_coin():
    """Before 2026-10-05 a crypto base could be a still-forming bar's intraday
    print. The final close 25% away from it is a big day for the SAME coin,
    not another instrument: the row keeps maturing (the anchor band, 15%,
    would have frozen it for good and dropped exactly the big-move days)."""
    led = ar._fresh()
    led["entries"].append(_row("crypto", "PMP", "2026-09-29", base_close=1.0,
                               fwd={"1": 0.01, "5": None, "10": None, "20": None}))
    idx = pd.date_range("2026-09-20", periods=40, freq="D")
    closes = [1.0] * 9 + [1.25] * 31                         # 09-29 closed at 1.25
    now = dt.datetime(2026, 10, 29, 1, 0, tzinfo=UTC)
    ar.stamp(led, _bars("PMP-USD", idx, closes), ar.wanting_prices(led, now.date()), now)
    assert led["entries"][0]["fwd"]["5"] == 0.0


def test_the_roster_ledger_prices_crypto_through_data_fetch_too(tmp_path, monkeypatch):
    import scanner.data
    day = (dt.datetime.now(UTC).date() - dt.timedelta(days=3)).isoformat()
    (tmp_path / "rosters.json").write_text(json.dumps({"schema_version": 1, "updated_at": "",
        "entries": [_row("crypto", "APT", day), _row("asx", "BHP", day)]}), encoding="utf-8")
    monkeypatch.setattr(er, "LEDGER", str(tmp_path / "rosters.json"))
    monkeypatch.setattr(er, "ROOT", str(tmp_path))          # no scans: nothing ingested
    calls = []
    monkeypatch.setattr(scanner.data, "download",
                        lambda t, period=None, **k: calls.append(("download", sorted(t))) or {})
    monkeypatch.setattr(scanner.data, "fetch", lambda m, t, period=None, **k: (
        calls.append(("fetch", m, sorted(t), k.get("require_identity"))) or ({}, {})))
    assert er.main(["--dry-run"]) == 0
    assert ("fetch", "crypto", ["APT-USD"], True) in calls
    assert ("download", ["BHP.AX"]) in calls
    assert not any(c[0] == "download" and any(s.endswith("-USD") for s in c[1]) for c in calls), \
        "no crypto ticker may reach Yahoo's unchecked download"
