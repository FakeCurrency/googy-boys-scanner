"""The paths a crypto price can take to the paper book (2026-09-28 review).

An independent pre-merge review of the exchange-data switch found that the
identity check guarded ONE path -- the scan's universe-wide fetch -- while
four others could still hand the book a different token's price:

  1. the frame cache back-filled a coin the identity check had just REFUSED
     (and the pre-switch cache held Yahoo's wrong-token M / MNT frames);
  2. the kill switch and the book's off-universe fetch passed no reference,
     so they took whichever venue lists the ticker first (Binance's AI and
     LIT were different tokens on the first real run);
  3. a delisted pair's frozen klines, still served by Binance's mirror, beat
     a live venue whenever the frozen close sat near today's price;
  4. a cached universe's OLD CoinGecko price refused a real coin that moved
     while CoinGecko was down.

Every test drives the SHIPPED functions with the venues and Yahoo stubbed.
"""
import datetime as dt
import json
import urllib.error
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scanner import config, data, exchange_data as X, universe
from scanner.broker import kill_switch as ks
from scanner.broker import vivek_run as vr

DAY = 86_400_000


def _today():
    return pd.Timestamp.now(tz="UTC").normalize()


def _klines(px, n=5):
    """Binance-shaped daily klines ending TODAY (the age gate refuses old ones)."""
    t0 = int((_today() - pd.Timedelta(days=n - 1)).timestamp() * 1000)
    return [[t0 + i * DAY, str(px), str(px), str(px), str(px), "1", t0 + i * DAY + 1, "9e6"]
            for i in range(n)]


def _yframe(px, end=None):
    idx = pd.date_range(end=end or _today().tz_localize(None), periods=5, freq="D")
    return pd.DataFrame({"Open": px, "High": px, "Low": px, "Close": px, "Volume": 1e6}, index=idx)


def _http(code):
    return urllib.error.HTTPError("u", code, "x", None, None)


@pytest.fixture
def venues(monkeypatch):
    """Binance's mirror + Coinbase answer (the runner's reality); the call
    log says which venue was asked for which pair."""
    monkeypatch.setattr(config, "EXCHANGE_KLINE_SOURCES", ("binance_vision", "coinbase"))
    monkeypatch.setattr(X.time, "sleep", lambda s: None)
    log = []

    def install(binance=None, yahoo=None):
        binance = binance or {}

        def router(url, timeout):
            log.append(url)
            if "binance.vision" in url:
                for pair, px in binance.items():
                    if f"symbol={pair}USDT" in url:
                        return _klines(px)
                raise _http(400)
            raise _http(404)                          # Coinbase lists nothing here

        monkeypatch.setattr(X, "_get_json", router)
        asked = []
        monkeypatch.setattr(data, "download", lambda t, period=None, **k: (
            asked.append(list(t)) or {x: _yframe(yahoo[x]) for x in t if x in (yahoo or {})}))
        return log, asked
    return install


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "_CACHE_DIR", tmp_path)
    return tmp_path


# ── 1. the frame cache never refills a refused coin ─────────────────────────────

def test_a_REFUSED_coin_is_not_back_filled_from_the_cache_and_leaves_it(venues, cache_dir):
    """The reviewers' reproduction, end to end: the cache holds Yahoo's
    wrong-token M (MemeCore trades ~$2; Yahoo's M-USD printed 0.0003), no
    exchange lists M, Yahoo still serves the stranger. fetch refuses it --
    and merge_with_cache must not hand it straight back."""
    venues(binance={"BTC": 100.0}, yahoo={"M-USD": 0.0003})
    data.save_frame_cache("crypto", {"M-USD": _yframe(0.0003)})
    fresh, rep = data.fetch("crypto", ["BTC-USD", "M-USD"], period="5y",
                            ref_prices={"BTC-USD": 100.0, "M-USD": 2.0})
    assert "M-USD" not in fresh and rep["refused"] == ["M-USD"]
    merged, stats = data.merge_with_cache("crypto", fresh, ["BTC-USD", "M-USD"],
                                          refused=rep["refused"])
    assert "M-USD" not in merged and stats["reused"] == 0 and stats["refused"] == 1
    assert "M-USD" not in data.load_frame_cache("crypto"), "the stranger must leave the cache too"


def test_a_coin_that_is_merely_MISSING_is_still_back_filled(venues, cache_dir):
    """The cache's job is untouched: a transient miss (no rejection) reuses
    the last-good frame exactly as before."""
    venues(binance={"BTC": 100.0})
    data.save_frame_cache("crypto", {"QNT-USD": _yframe(90.0)})
    fresh, rep = data.fetch("crypto", ["BTC-USD", "QNT-USD"], period="5y",
                            ref_prices={"BTC-USD": 100.0, "QNT-USD": 92.0})
    assert rep["refused"] == []
    merged, stats = data.merge_with_cache("crypto", fresh, ["BTC-USD", "QNT-USD"],
                                          refused=rep["refused"])
    assert "QNT-USD" in merged and stats["reused"] == 1


def test_exchange_mode_never_reads_the_yahoo_era_cache(cache_dir, monkeypatch):
    """The pre-switch cache (restored by actions/cache) holds Yahoo frames,
    wrong tokens included. Exchange mode reads and writes its own file."""
    assert data._cache_path("crypto").name == "crypto.exchange.pkl.gz"
    assert data._cache_path("ignition-crypto").name == "ignition-crypto.exchange.pkl.gz"
    assert data._cache_path("asx").name == "asx.pkl.gz"
    monkeypatch.setattr(config, "CRYPTO_DATA_SOURCE", "yahoo")
    old = data._cache_path("crypto")
    data.save_frame_cache("crypto", {"M-USD": _yframe(0.0003)})
    monkeypatch.setattr(config, "CRYPTO_DATA_SOURCE", "exchange")
    assert data._cache_path("crypto") != old
    assert data.load_frame_cache("crypto") == {}


# ── 2. held coins are priced on the venue they were marked on ──────────────────

def test_held_price_kwargs_pins_a_stamped_position_and_checks_a_legacy_one():
    kw = data.held_price_kwargs([
        {"symbol": "AI", "market": "crypto", "data_source": "yahoo", "last_mark": 0.05},
        {"symbol": "BNB", "market": "crypto", "last_mark": 776.0},          # pre-stamp row
        {"symbol": "OLD", "market": "crypto", "data_source": "cache", "last_mark": 3.0},
        {"symbol": "BHP", "market": "asx", "data_source": "yahoo", "last_mark": 45.0},
    ])
    assert kw["pin"] == {"AI-USD": "yahoo"}
    assert kw["ref_prices"] == {"BNB-USD": 776.0, "OLD-USD": 3.0}
    assert kw["ref_tol"] == config.CRYPTO_IDENTITY_TOL_STALE


def test_a_PINNED_coin_is_priced_on_its_venue_only_and_never_falls_through(venues):
    """Binance lists a DIFFERENT 'AI' (0.03); the scan marked the held AI on
    Yahoo (0.05). Pinned to yahoo, Binance is never asked for AI. Pinned to
    a venue that fails, there is no quote at all -- unpriced, not wrong."""
    log, asked = venues(binance={"AI": 0.03}, yahoo={"AI-USD": 0.05})
    fr, rep = data.fetch("crypto", ["AI-USD"], period="5d", pin={"AI-USD": "yahoo"})
    assert float(fr["AI-USD"]["Close"].iloc[-1]) == 0.05 and rep["source_of"] == {"AI-USD": "yahoo"}
    assert not any("AIUSDT" in u for u in log), "a yahoo-pinned coin must not touch Binance"
    log.clear(); asked.clear()
    fr, _ = data.fetch("crypto", ["LIT-USD"], period="5d", pin={"LIT-USD": "coinbase"})
    assert fr == {} and asked == [], "a failed pinned venue falls back to NOTHING"
    assert not any("binance" in u for u in log)


def test_the_kill_switch_prices_a_held_coin_on_its_own_venue(venues):
    venues(binance={"AI": 0.03}, yahoo={"AI-USD": 0.05})
    book = {"open": [{"symbol": "AI", "market": "crypto", "status": "open",
                      "data_source": "yahoo", "last_mark": 0.05}]}
    assert ks._live_marks(book) == {("AI", "crypto"): 0.05}


def test_the_off_universe_fetch_prices_a_held_coin_on_its_own_venue(venues, tmp_path, monkeypatch):
    """The reviewers' scenario: a held AI drops out of the top 200. The book
    fetches it directly -- and must get the coin it holds (Yahoo, 0.49), not
    Binance's 'AI' at 0.05, which after 3 sanity challenges would have been
    accepted and booked a -5.6R stop on another token."""
    from scanner.vivek_journal import _snapshot
    row = {"symbol": "AI", "name": "AI", "sector": "", "grade": "A+", "dir": "LONG",
           "entry_types": ["break"]}
    plan = {"stop": 0.42, "tp1": 0.6, "tp2": 0.7, "tp3": 0.8,
            "scale": config.VIVEK_TP_SCALE_LONG, "entry_trigger": "break",
            "armed": True, "trigger_bar": None}
    pos = _snapshot(row, "1D", plan, "crypto", 0.50, "2026-09-20")
    pos.update(market="crypto", risk_usd=500.0, data_source="yahoo", last_mark=0.50)
    _book_with(tmp_path, monkeypatch, pos)
    log, asked = venues(binance={"AI": 0.05}, yahoo={"AI-USD": 0.49})
    bk = vr.run_market("crypto", [], {}, [], now=dt.datetime.now(ZoneInfo("UTC")))
    assert asked == [["AI-USD"]], "the straggler was fetched, from its pinned venue"
    assert not any("AIUSDT" in u for u in log)
    (held,) = [p for p in bk["open"] if p["symbol"] == "AI"]
    assert held["last_mark"] == pytest.approx(0.49), "marked on the coin it holds"
    assert held["status"] == "open" and held["data_source"] == "yahoo"


def _book_with(tmp_path, monkeypatch, pos):
    monkeypatch.setattr(vr, "BOOK_DIR", tmp_path)
    monkeypatch.setattr(vr, "BOOK_FILE", tmp_path / "vivek_bot_book.json")
    monkeypatch.setattr(vr, "UNASSIGNED_FILE", tmp_path / "vivek_bot_book.unassigned.json")
    monkeypatch.setattr(vr, "PUBLIC_FILE", tmp_path / "public_book.json")
    monkeypatch.setattr(config, "VIVEK_BOT_ENABLED", True)
    monkeypatch.setattr(config, "VIVEK_BOT_DRY_RUN", False)
    (tmp_path / "vivek_bot_book.crypto.json").write_text(json.dumps(
        {"version": 2, "mode": "paper", "market": "crypto", "open": [pos], "closed": []}),
        encoding="utf-8")


def test_a_held_position_is_stamped_with_the_venue_that_marked_it(tmp_path, monkeypatch):
    """BNB was opened before the stamp existed. The first scan-frame mark
    records its venue, so from then on the kill switch pins it there."""
    from scanner.vivek_journal import _snapshot
    row = {"symbol": "BNB", "name": "BNB", "sector": "", "grade": "A+", "dir": "LONG",
           "entry_types": ["reclaim"]}
    plan = {"stop": 560.0, "tp1": 900.0, "tp2": 950.0, "tp3": 1000.0,
            "scale": config.VIVEK_TP_SCALE_LONG, "entry_trigger": "reclaim",
            "armed": True, "trigger_bar": None}
    pos = _snapshot(row, "1W", plan, "crypto", 760.0, "2026-09-20")
    pos.update(market="crypto", risk_usd=500.0, last_mark=776.0)
    assert "data_source" not in pos
    _book_with(tmp_path, monkeypatch, pos)
    f = _yframe(772.0)
    f.attrs["source"] = "binance_vision"
    bk = vr.run_market("crypto", [], {"BNB-USD": f}, [{"symbol": "BNB", "yf": "BNB-USD"}],
                       now=dt.datetime.now(ZoneInfo("UTC")))
    (held,) = [p for p in bk["open"] if p["symbol"] == "BNB"]
    assert held["data_source"] == "binance_vision" and held["last_mark"] == pytest.approx(772.0)
    assert data.held_price_kwargs([held])["pin"] == {"BNB-USD": "binance_vision"}


def test_every_mark_stamps_the_venue_it_came_from():
    """The pin is only as good as the stamp: run_market writes the frame's
    venue onto each crypto position it marks and on each one it opens."""
    src = (vr.__file__ and open(vr.__file__, encoding="utf-8").read())
    assert src.count('pos["data_source"] = ') >= 2
    f = _yframe(1.0)
    f.attrs["source"] = "coinbase"
    assert data.venue_of({"X-USD": f}, "X-USD") == "coinbase"
    assert data.venue_of({"X-USD": _yframe(1.0)}, "X-USD") is None
    assert data.venue_of({}, None) is None


def test_the_yahoo_leg_stamps_its_frames_so_they_can_be_pinned(venues):
    venues(yahoo={"XMR-USD": 150.0})
    fr, _ = data.fetch("crypto", ["XMR-USD"], period="5y", ref_prices={"XMR-USD": 150.0})
    assert fr["XMR-USD"].attrs["source"] == "yahoo"


# ── 3. a delisted pair does not beat a live venue ─────────────────────────────

def test_a_delisted_pairs_frozen_klines_fall_through_to_a_live_source(venues, monkeypatch):
    """Binance's mirror serves XYZUSDT ending 120 days ago at 1.00; the coin
    trades live at 0.80 on Yahoo (inside the identity band of 1.00). The age
    gate refuses the frozen pair and the live price is used."""
    venues(yahoo={"XYZ-USD": 0.80})
    frozen_end = _today() - pd.Timedelta(days=120)
    t0 = int((frozen_end - pd.Timedelta(days=4)).timestamp() * 1000)
    rows = [[t0 + i * DAY, "1", "1", "1", "1", "1", t0 + i * DAY + 1, "9e6"] for i in range(5)]
    monkeypatch.setattr(X, "_get_json", lambda url, timeout: rows if "XYZUSDT" in url
                        else (_ for _ in ()).throw(_http(404)))
    fr, rep = data.fetch("crypto", ["XYZ-USD"], period="5y", ref_prices={"XYZ-USD": 0.80})
    assert rep["source_of"] == {"XYZ-USD": "yahoo"}
    assert float(fr["XYZ-USD"]["Close"].iloc[-1]) == 0.80
    assert rep["stale_rejected"] == {"XYZ": ["binance_vision"]}


# ── 4. an old reference reads with the wide band ──────────────────────────────

def test_a_cached_universe_arms_the_STALE_band_a_live_one_the_tight_band(monkeypatch, tmp_path):
    live = [{"symbol": "QNT", "yf": "QNT-USD", "cg_price": 71.0}]
    refs, tol = universe.identity_refs(live)
    assert refs == {"QNT-USD": 71.0} and tol == config.CRYPTO_IDENTITY_TOL
    monkeypatch.setattr(universe, "UNIVERSE_CACHE_DIR", tmp_path)
    items = [{"symbol": f"C{i}", "name": f"Coin {i}", "yf": f"C{i}-USD", "cg_price": 1.0}
             for i in range(45)] + [{"symbol": "QNT", "name": "Quant", "yf": "QNT-USD",
                                     "cg_price": 71.0}]
    (tmp_path / "crypto.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    monkeypatch.setattr(universe, "_fetch_crypto", lambda suffix: [])      # CoinGecko down
    cached = universe.load_universe("crypto")
    refs, tol = universe.identity_refs(cached)
    assert refs["QNT-USD"] == 71.0 and tol == config.CRYPTO_IDENTITY_TOL_STALE


def test_a_real_coin_that_ran_while_CoinGecko_was_down_is_not_refused(venues):
    """QNT's own move: 71 -> 272 on a stale 71 reference. The tight band
    would refuse the real coin on every venue; the stale band keeps it, and
    still refuses a same-ticker stranger priced orders of magnitude away."""
    venues(binance={"QNT": 271.8}, yahoo={"M-USD": 0.0003})
    fr, rep = data.fetch("crypto", ["QNT-USD", "M-USD"], period="5y",
                         ref_prices={"QNT-USD": 71.0, "M-USD": 2.0},
                         ref_tol=config.CRYPTO_IDENTITY_TOL_STALE)
    assert float(fr["QNT-USD"]["Close"].iloc[-1]) == 271.8
    assert "M-USD" not in fr and rep["refused"] == ["M-USD"]


def test_a_fetch_with_no_reference_says_the_check_is_off(venues, caplog):
    venues(binance={"BTC": 100.0})
    with caplog.at_level("WARNING"):
        _, rep = data.fetch("crypto", ["BTC-USD"], period="5y")
    assert rep["unchecked"] == 1
    assert any("identity check OFF" in r.message for r in caplog.records)
    assert data.source_summary(rep)["unchecked"] == 1
