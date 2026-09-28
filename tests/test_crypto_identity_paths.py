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
     while CoinGecko was down -- and the first fix for that (a wider band)
     let a same-ticker stranger price a HELD coin, so it is answered by
     pinning each coin to its last confirmed venue instead.

Every test drives the SHIPPED functions with the venues and Yahoo stubbed.
"""
import datetime as dt
import json
import urllib.error
import urllib.parse
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


# ── 2. a held coin must reproduce its OWN recorded history ─────────────────────
#
# Venue pins stood here for an hour; a second review showed a pinned venue
# could re-list a DIFFERENT token under the symbol with no check at all, and
# that an outage at the pinned venue froze the mark. The position's own
# day_marks are the evidence now, on whatever venue answers.

def _cb_router(log, days_px, today_px, binance=None):
    """Coinbase serving the REAL coin (close `days_px` on past days, `today_px`
    today); Binance's mirror serving `binance` {pair: px} or failing."""
    def router(url, timeout):
        log.append(url)
        if "binance.vision" in url:
            for pair, px in (binance or {}).items():
                if f"symbol={pair}USDT" in url:
                    if px == "timeout":
                        raise TimeoutError("venue down")
                    return _klines(px)
            raise _http(400)
        if "/products/" in url:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if dt.datetime.fromisoformat(q["start"][0]) < dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=301):
                return []
            t = int(_today().timestamp())
            return [[t, today_px, today_px, today_px, today_px, 5e6]] + [
                [t - 86_400 * k, days_px, days_px, days_px, days_px, 5e6] for k in range(1, 6)]
        raise _http(404)
    return router


def _yday(n=1):
    return (_today() - pd.Timedelta(days=n)).strftime("%Y-%m-%d")


def test_held_price_kwargs_anchors_on_the_positions_own_day_marks():
    today = _today().strftime("%Y-%m-%d")
    kw = data.held_price_kwargs([
        {"symbol": "MET", "market": "crypto", "opened_at": "2026-09-20T01:00:00+00:00",
         "last_mark": 0.98, "day_marks": {_yday(2): 1.02, _yday(1): 1.00}},
        {"symbol": "NEW", "market": "crypto", "opened_at": today + "T03:00:00+00:00",
         "last_mark": 5.1, "day_marks": {today: 5.0}},                     # opened today
        {"symbol": "BNB", "market": "crypto", "last_mark": 776.0},          # no marks yet
        {"symbol": "BHP", "market": "asx", "last_mark": 45.0, "day_marks": {today: 45.0}},
    ])
    assert kw["anchors"] == {"MET-USD": (_yday(2), 1.00)}
    assert kw["ref_prices"] == {"NEW-USD": 5.1, "BNB-USD": 776.0}
    assert kw["ref_tol"] == config.CRYPTO_IDENTITY_TOL and "pin" not in kw


def test_a_venue_that_relisted_a_STRANGER_under_the_symbol_is_refused(venues, monkeypatch):
    """The second review's case: the venue that marked MET now serves a
    DIFFERENT MET at 0.57. Its close on the anchor date is 0.57, not the
    1.00 the book recorded, so it is refused and the real coin (Coinbase)
    prices the position -- whichever venue answers."""
    log, _ = venues()
    monkeypatch.setattr(X, "_get_json", _cb_router(log, 1.00, 1.00, binance={"MET": 0.57}))
    kw = data.held_price_kwargs([{"symbol": "MET", "market": "crypto",
                                  "opened_at": "2026-09-01", "last_mark": 1.0,
                                  "day_marks": {_yday(0): 1.00}}])
    fr, rep = data.fetch("crypto", ["MET-USD"], period="5d", **kw)
    assert rep["identity_rejected"] == {"MET": ["binance_vision"]}
    assert rep["source_of"] == {"MET-USD": "coinbase"} and float(fr["MET-USD"]["Close"].iloc[-1]) == 1.0
    assert fr["MET-USD"].attrs["identity"] == "anchor"


def test_an_outage_at_one_venue_falls_through_instead_of_freezing_the_mark(venues, monkeypatch):
    """The second review's major: with a pin, a binance_vision timeout left the
    cached 1.00 frame in place while the real MET was at 0.80, under its 0.85
    stop. Now the next venue that reproduces MET's history prices it."""
    log, _ = venues()
    monkeypatch.setattr(X, "_get_json", _cb_router(log, 1.00, 0.80, binance={"MET": "timeout"}))
    book = {"open": [{"symbol": "MET", "market": "crypto", "status": "open", "last_mark": 1.0,
                      "opened_at": "2026-09-01", "day_marks": {_yday(0): 1.00}}]}
    assert ks._live_marks(book) == {("MET", "crypto"): 0.80}


def test_the_YAHOO_leg_is_held_to_the_same_history(venues):
    """No exchange lists M; Yahoo's M-USD is a different token (0.0003 against
    MemeCore's ~2). A held M's own day_marks refuse it on the Yahoo leg too."""
    venues(yahoo={"M-USD": 0.0003})
    kw = data.held_price_kwargs([{"symbol": "M", "market": "crypto", "last_mark": 2.0,
                                  "opened_at": "2026-09-01", "day_marks": {_yday(0): 2.0}}])
    fr, rep = data.fetch("crypto", ["M-USD"], period="5d", **kw)
    assert fr == {} and rep["identity_rejected"] == {"M": ["yahoo"]}


def test_the_kill_switch_never_quotes_a_stranger(venues, monkeypatch):
    """Binance lists a DIFFERENT 'AI' (0.03); the real AI is on Yahoo at 0.05.
    The position's own history rejects Binance's."""
    venues(binance={"AI": 0.03}, yahoo={"AI-USD": 0.05})
    book = {"open": [{"symbol": "AI", "market": "crypto", "status": "open", "last_mark": 0.05,
                      "opened_at": "2026-09-01", "day_marks": {_yday(0): 0.05}}]}
    assert ks._live_marks(book) == {("AI", "crypto"): 0.05}


def test_the_off_universe_fetch_prices_a_held_coin_on_its_own_coin(venues, tmp_path, monkeypatch):
    """The first review's scenario: a held AI drops out of the top 200. The
    book fetches it directly -- and must get the coin it holds (Yahoo, 0.49),
    not Binance's 'AI' at 0.05, which after 3 sanity challenges would have
    been accepted and booked a -5.6R stop on another token."""
    from scanner.vivek_journal import _snapshot
    row = {"symbol": "AI", "name": "AI", "sector": "", "grade": "A+", "dir": "LONG",
           "entry_types": ["break"]}
    plan = {"stop": 0.42, "tp1": 0.6, "tp2": 0.7, "tp3": 0.8,
            "scale": config.VIVEK_TP_SCALE_LONG, "entry_trigger": "break",
            "armed": True, "trigger_bar": None}
    pos = _snapshot(row, "1D", plan, "crypto", 0.50, "2026-09-20")
    pos.update(market="crypto", risk_usd=500.0, last_mark=0.50, opened_at="2026-09-20",
               day_marks={_yday(0): 0.50})
    _book_with(tmp_path, monkeypatch, pos)
    log, asked = venues(binance={"AI": 0.05}, yahoo={"AI-USD": 0.49})
    bk = vr.run_market("crypto", [], {}, [], now=dt.datetime.now(ZoneInfo("UTC")))
    assert asked == [["AI-USD"]], "the straggler was fetched"
    assert any("AIUSDT" in u for u in log), "Binance was asked -- and refused"
    (held,) = [p for p in bk["open"] if p["symbol"] == "AI"]
    assert held["last_mark"] == pytest.approx(0.49), "marked on the coin it holds"
    assert held["status"] == "open"


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
    records its venue (the chart draws that venue's candles)."""
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


def test_every_mark_stamps_the_venue_it_came_from():
    """run_market writes the frame's venue onto each crypto position it marks
    (once the mark is accepted) and on each one it opens."""
    src = (vr.__file__ and open(vr.__file__, encoding="utf-8").read())
    assert src.count("_stamp_identity(pos,") >= 2       # the accepted mark AND the open
    f = _yframe(1.0)
    f.attrs["source"] = "coinbase"
    assert data.venue_of({"X-USD": f}, "X-USD") == "coinbase"
    assert data.venue_of({"X-USD": _yframe(1.0)}, "X-USD") is None
    assert data.venue_of({}, None) is None


def test_the_yahoo_leg_stamps_its_frames_with_venue_and_identity(venues):
    venues(yahoo={"XMR-USD": 150.0})
    fr, _ = data.fetch("crypto", ["XMR-USD"], period="5y", ref_prices={"XMR-USD": 150.0})
    assert fr["XMR-USD"].attrs["source"] == "yahoo" and fr["XMR-USD"].attrs["identity"] == "ref"


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


# ── 4. an old reference is answered by a HISTORY ANCHOR ───────────────────────

def _cached_universe(tmp_path, monkeypatch, extra, price=1.0):
    """load_universe with CoinGecko down: the snapshot, flagged cg_stale."""
    monkeypatch.setattr(universe, "UNIVERSE_CACHE_DIR", tmp_path / "uc")
    (tmp_path / "uc").mkdir()
    items = [{"symbol": f"C{i}", "name": f"Coin {i}", "yf": f"C{i}-USD", "cg_price": price}
             for i in range(45)] + extra
    (tmp_path / "uc" / "crypto.json").write_text(json.dumps({"items": items}), encoding="utf-8")
    monkeypatch.setattr(universe, "_fetch_crypto", lambda suffix: [])
    return universe.load_universe("crypto")


def _checked(px, source="coinbase", how="ref"):
    f = _yframe(px)
    f.attrs.update(source=source, identity=how)
    return f


def test_a_live_universe_arms_the_tight_band_and_nothing_else():
    kw = data.identity_kwargs("crypto", [{"symbol": "QNT", "yf": "QNT-USD", "cg_price": 71.0}])
    assert kw == {"ref_prices": {"QNT-USD": 71.0}, "ref_tol": config.CRYPTO_IDENTITY_TOL,
                  "anchors": {}, "require_identity": False}


def test_the_reviewers_MET_case_on_a_snapshot_the_stranger_is_refused(
        venues, cache_dir, tmp_path, monkeypatch):
    """The first review's blocker, end to end: CoinGecko down, MET last
    confirmed at 1.00, Binance's mirror lists a DIFFERENT 'MET' at 0.57
    (-43%, the measured collision). The wide band admitted it and a held
    MET was stopped at -2.88R. Now MET is anchored to its last checked
    frame: Binance's MET cannot reproduce that close and is refused."""
    uni = _cached_universe(tmp_path, monkeypatch,
                           [{"symbol": "MET", "name": "Meteora", "yf": "MET-USD", "cg_price": 1.00}])
    data.save_frame_cache("crypto", {"MET-USD": _checked(1.00)})
    kw = data.identity_kwargs("crypto", uni)
    assert kw["anchors"]["MET-USD"][1] == 1.00 and "MET-USD" not in kw["ref_prices"]
    assert kw["require_identity"] is True and "pin" not in kw
    log, _ = venues()
    monkeypatch.setattr(X, "_get_json", _cb_router(log, 1.00, 1.00, binance={"MET": 0.57}))
    fr, rep = data.fetch("crypto", ["MET-USD"], period="5y", **kw)
    assert rep["identity_rejected"] == {"MET": ["binance_vision"]}
    assert rep["source_of"] == {"MET-USD": "coinbase"} and float(fr["MET-USD"]["Close"].iloc[-1]) == 1.0


def test_an_UNCHECKED_frame_never_becomes_the_evidence(venues, cache_dir, tmp_path, monkeypatch):
    """The second review's blocker: on a snapshot with no prices (the
    committed pre-switch one), a frame fetched with NO check was cached and
    then trusted as a confirmed pin -- Yahoo's wrong-token M stayed scanned
    and the 'check OFF' warning went quiet. Now an unchecked frame is never
    an anchor, and a snapshot coin nothing vouches for is refused."""
    uni = _cached_universe(tmp_path, monkeypatch,
                           [{"symbol": "M", "name": "MemeCore", "yf": "M-USD"}])   # no cg_price
    data.save_frame_cache("crypto", {"M-USD": _checked(0.0003, source="yahoo", how="none")})
    kw = data.identity_kwargs("crypto", uni)
    assert "M-USD" not in kw["anchors"] and kw["require_identity"] is True
    venues(yahoo={"M-USD": 0.0003})
    fr, rep = data.fetch("crypto", ["M-USD"], period="5y", **kw)
    assert fr == {} and rep["refused"] == ["M-USD"] and rep["unchecked"] == 0


def test_a_coin_with_no_anchor_keeps_the_TIGHT_band_on_a_snapshot(
        venues, cache_dir, tmp_path, monkeypatch):
    """No checked frame to anchor to: the old price is checked at 0.40. A real
    coin that ran past it is refused for the run -- the cost -- and a
    stranger can never get in -- the point."""
    uni = _cached_universe(tmp_path, monkeypatch,
                           [{"symbol": "QNT", "name": "Quant", "yf": "QNT-USD", "cg_price": 71.0}])
    kw = data.identity_kwargs("crypto", uni)
    assert kw["anchors"] == {} and kw["ref_prices"]["QNT-USD"] == 71.0
    venues(binance={"QNT": 271.8})
    fr, rep = data.fetch("crypto", ["QNT-USD"], period="5y", **kw)
    assert fr == {} and rep["refused"] == ["QNT-USD"]


def test_a_real_coin_that_RAN_on_a_snapshot_passes_its_anchor(venues, cache_dir, tmp_path, monkeypatch):
    """QNT's own move while CoinGecko is down: 71 -> 272. The stale price
    would refuse it; its anchor (yesterday's 71 close) does not care where it
    trades today."""
    uni = _cached_universe(tmp_path, monkeypatch,
                           [{"symbol": "QNT", "name": "Quant", "yf": "QNT-USD", "cg_price": 71.0}])
    data.save_frame_cache("crypto", {"QNT-USD": _checked(71.0, source="coinbase")})
    kw = data.identity_kwargs("crypto", uni)
    log, _ = venues()
    monkeypatch.setattr(X, "_get_json", _cb_router(log, 71.0, 271.8))
    fr, rep = data.fetch("crypto", ["QNT-USD"], period="5y", **kw)
    assert float(fr["QNT-USD"]["Close"].iloc[-1]) == 271.8 and fr["QNT-USD"].attrs["identity"] == "anchor"


def test_anchor_ok_needs_the_date_and_the_band():
    f = _yframe(1.0)
    day = _yday(1)
    assert X.anchor_ok(f, (day, 1.0)) and X.anchor_ok(f, (day, 1.0 * (1 + config.CRYPTO_ANCHOR_TOL)))
    assert not X.anchor_ok(f, (day, 1.2 * (1 + config.CRYPTO_ANCHOR_TOL)))
    assert not X.anchor_ok(f, ("2020-01-01", 1.0)), "a frame without the date cannot vouch"
    assert not X.anchor_ok(None, (day, 1.0)) and not X.anchor_ok(f, None)


def test_the_lens_anchors_from_its_OWN_cache():
    src = open(__import__("scanner.ignition.run", fromlist=["x"]).__file__, encoding="utf-8").read()
    assert 'identity_kwargs(market, rows,' in src and 'cache_key=f"ignition-{market}"' in src


# ── 5. a mark the sanity guard refuses does not relabel the source ────────────

def test_a_suspect_print_does_not_relabel_the_positions_source(tmp_path, monkeypatch):
    """The review's second MET case: a stranger at 0.30 (-70%) is SUSPENDED by
    the mark-sanity guard -- and must not become the position's recorded
    venue on the way."""
    from scanner.vivek_journal import _snapshot
    row = {"symbol": "MET", "name": "MET", "sector": "", "grade": "A+", "dir": "LONG",
           "entry_types": ["reclaim"]}
    plan = {"stop": 0.85, "tp1": 1.3, "tp2": 1.5, "tp3": 1.8,
            "scale": config.VIVEK_TP_SCALE_LONG, "entry_trigger": "reclaim",
            "armed": True, "trigger_bar": None}
    pos = _snapshot(row, "1W", plan, "crypto", 1.0, "2026-09-20")
    pos.update(market="crypto", risk_usd=500.0, last_mark=1.0, data_source="coinbase")
    _book_with(tmp_path, monkeypatch, pos)
    stranger = _yframe(0.30)
    stranger.attrs["source"] = "binance_vision"
    bk = vr.run_market("crypto", [], {"MET-USD": stranger}, [{"symbol": "MET", "yf": "MET-USD"}],
                       now=dt.datetime.now(ZoneInfo("UTC")))
    (held,) = [p for p in bk["open"] if p["symbol"] == "MET"]
    assert held.get("suspect_price_runs"), "the -70% print was challenged"
    assert held["data_source"] == "coinbase", "a refused mark must not relabel the source"
    assert held["last_mark"] == 1.0


# ── 6. a delisted pair is not refilled from the cache either ─────────────────

def test_a_coin_whose_only_listing_is_a_delisted_pair_is_refused_not_refilled(
        venues, cache_dir, monkeypatch):
    """The review's second finding: the age gate refused LIT's frozen Binance
    pair, nothing else listed it, and the frame cache handed the SAME frozen
    klines back for up to 10 days. Now it is `refused` like a stranger."""
    frozen_end = _today() - pd.Timedelta(days=6)
    t0 = int((frozen_end - pd.Timedelta(days=4)).timestamp() * 1000)
    rows = [[t0 + i * DAY, "2", "2", "2", "2", "1", t0 + i * DAY + 1, "9e6"] for i in range(5)]
    venues()
    monkeypatch.setattr(X, "_get_json", lambda url, timeout: rows if "LITUSDT" in url
                        else (_ for _ in ()).throw(_http(404)))
    old = _yframe(2.0, end=(_today() - pd.Timedelta(days=3)).tz_localize(None))
    old.attrs["source"] = "binance_vision"
    data.save_frame_cache("crypto", {"LIT-USD": old})
    fresh, rep = data.fetch("crypto", ["LIT-USD"], period="5y", ref_prices={"LIT-USD": 2.0})
    assert rep["stale_rejected"] == {"LIT": ["binance_vision"]} and rep["refused"] == ["LIT-USD"]
    assert rep["rejected_venues"] == {"LIT-USD": ["binance_vision"]}
    merged, stats = data.merge_with_cache("crypto", fresh, ["LIT-USD"], refused=rep["refused"],
                                          rejected_venues=rep["rejected_venues"])
    assert merged == {} and stats["reused"] == 0 and stats["refused"] == 1


def test_a_cached_frame_from_a_venue_that_was_NOT_rejected_is_still_reused(
        venues, cache_dir, monkeypatch):
    """Found on the real run of 9af7396f: LIT's only exchange listing is
    Binance's dead pair (skipped by the age gate) and its real series is on
    Yahoo -- which was throttled that run. Blocking LIT's cached YAHOO frame
    would turn an ordinary transient miss into a missing coin. Only a cached
    frame from a REJECTED venue (or of unknown venue) is blocked."""
    frozen_end = _today() - pd.Timedelta(days=6)
    t0 = int((frozen_end - pd.Timedelta(days=4)).timestamp() * 1000)
    rows = [[t0 + i * DAY, "2", "2", "2", "2", "1", t0 + i * DAY + 1, "9e6"] for i in range(5)]
    venues(yahoo={})                                        # Yahoo throttled: nothing back
    monkeypatch.setattr(X, "_get_json", lambda url, timeout: rows if "LITUSDT" in url
                        else (_ for _ in ()).throw(_http(404)))
    real = _yframe(2.1, end=(_today() - pd.Timedelta(days=1)).tz_localize(None))
    real.attrs["source"] = "yahoo"
    data.save_frame_cache("crypto", {"LIT-USD": real})
    fresh, rep = data.fetch("crypto", ["LIT-USD"], period="5y", ref_prices={"LIT-USD": 2.0})
    assert rep["refused"] == ["LIT-USD"] and rep["rejected_venues"] == {"LIT-USD": ["binance_vision"]}
    merged, stats = data.merge_with_cache("crypto", fresh, ["LIT-USD"], refused=rep["refused"],
                                          rejected_venues=rep["rejected_venues"])
    assert float(merged["LIT-USD"]["Close"].iloc[-1]) == 2.1 and stats["reused"] == 1
    # ...and with no venue map at all, every refused coin stays blocked
    merged, _ = data.merge_with_cache("crypto", fresh, ["LIT-USD"], refused=rep["refused"])
    assert merged == {}


def test_a_pinned_venue_that_returns_nothing_is_REPORTED(venues):
    venues()
    fr, rep = data.fetch("crypto", ["AI-USD"], period="5d", pin={"AI-USD": "coinbase"})
    assert fr == {} and rep["pinned_missing"] == ["AI-USD"]
    assert data.source_summary(rep)["pinned_missing"] == ["AI-USD"]


# ── 7. 4H: a venue with no 4h candles is not pinned ───────────────────────────

def test_a_coinbase_sourced_row_still_gets_a_4H_fetch(monkeypatch):
    """The review's third finding: Coinbase has no 4h candles, so pinning a
    Coinbase-sourced coin there left it with no 4H plan and no request made."""
    from scanner import scan
    assert X.supports("binance_vision", "4h") and X.supports("yahoo", "4h")
    assert not X.supports("coinbase", "4h") and X.supports("coinbase", "1d")
    seen = []
    monkeypatch.setattr(scan, "_bars", lambda m, t, p, iv="1d", **kw: (seen.append(kw) or {}))
    cb = _yframe(2.0)
    cb.attrs["source"] = "coinbase"
    bn = _yframe(3.0)
    bn.attrs["source"] = "binance_vision"
    scan._attach_h4_plans([{"symbol": "LIT", "dir": "LONG", "price": 2.0},
                           {"symbol": "ETH", "dir": "LONG", "price": 3.0}], "crypto",
                          {"LIT-USD": cb, "ETH-USD": bn})
    (kw,) = seen
    assert kw["pin"] == {"ETH-USD": "binance_vision"}
    assert kw["ref_prices"] == {"LIT-USD": 2.0, "ETH-USD": 3.0}


def test_a_fetch_with_no_reference_says_the_check_is_off(venues, caplog):
    venues(binance={"BTC": 100.0})
    with caplog.at_level("WARNING"):
        _, rep = data.fetch("crypto", ["BTC-USD"], period="5y")
    assert rep["unchecked"] == 1
    assert any("identity check OFF" in r.message for r in caplog.records)
    assert data.source_summary(rep)["unchecked"] == 1


# ── 8. the anchor is a REAL past close, stored at every accepted mark ─────────
#
# The fourth review: an anchor built from day_marks is a MARK, and a mark only
# moves when a price is accepted -- after an outage it lags the market, every
# venue then fails it, and the position is unpriced for ever. And Yahoo
# publishes yesterday late, so a D-1 anchor failed every Yahoo coin each
# morning. The anchor is now the checked frame's own last completed close.

def _held_row(**kw):
    from scanner.vivek_journal import _snapshot
    row = {"symbol": "XYZ", "name": "XYZ", "sector": "", "grade": "A+", "dir": "LONG",
           "entry_types": ["reclaim"]}
    plan = {"stop": 0.50, "tp1": 1.5, "tp2": 1.8, "tp3": 2.0,
            "scale": config.VIVEK_TP_SCALE_LONG, "entry_trigger": "reclaim",
            "armed": True, "trigger_bar": None}
    pos = _snapshot(row, "1W", plan, "crypto", 1.0, "2026-09-01")
    pos.update(market="crypto", risk_usd=500.0, last_mark=1.0, opened_at="2026-09-01")
    pos.update(kw)
    return pos


def test_an_accepted_mark_stores_the_frames_own_last_close_as_the_anchor(tmp_path, monkeypatch):
    pos = _held_row()
    _book_with(tmp_path, monkeypatch, pos)
    f = _yframe(0.98)
    f.attrs.update(source="binance_vision", identity="ref")
    bk = vr.run_market("crypto", [], {"XYZ-USD": f}, [{"symbol": "XYZ", "yf": "XYZ-USD"}],
                       now=dt.datetime.now(ZoneInfo("UTC")))
    (held,) = [p for p in bk["open"] if p["symbol"] == "XYZ"]
    assert held["anchor"] == [_yday(1), 0.98] and held["data_source"] == "binance_vision"
    kw = data.held_price_kwargs([dict(held, day_marks={_yday(0): 5.0})])
    assert kw["anchors"]["XYZ-USD"] == (_yday(1), 0.98), "the stored close beats day_marks"


def test_an_UNCHECKED_frame_never_writes_the_anchor(tmp_path, monkeypatch):
    pos = _held_row(anchor=["2026-09-20", 1.0])
    _book_with(tmp_path, monkeypatch, pos)
    f = _yframe(0.97)
    f.attrs.update(source="yahoo", identity="none")
    bk = vr.run_market("crypto", [], {"XYZ-USD": f}, [{"symbol": "XYZ", "yf": "XYZ-USD"}],
                       now=dt.datetime.now(ZoneInfo("UTC")))
    (held,) = [p for p in bk["open"] if p["symbol"] == "XYZ"]
    assert held["anchor"] == ["2026-09-20", 1.0]


def test_a_coin_that_drifted_while_unpriced_is_NOT_locked_out(venues, monkeypatch):
    """The review's lock-up: last priced at 1.00, then unpriced while the coin
    slid to 0.60 (under the 0.85 stop). Its day_marks say 1.00 into today, so a
    mark-based anchor refuses the real 0.60 for ever. The stored close (1.00 on
    the day it was last priced) is in the real history, so 0.60 is accepted."""
    last_priced = (_today() - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    log, _ = venues()

    def router(url, timeout):
        log.append(url)
        if "binance.vision" in url and "XYZUSDT" in url:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            start = int(q["startTime"][0])
            rows = []
            for k in range(8, -1, -1):
                t = int((_today() - pd.Timedelta(days=k)).timestamp() * 1000)
                px = 1.00 if k >= 5 else 0.60
                rows.append([t, str(px), str(px), str(px), str(px), "1", t + 1, "9e6"])
            return [r for r in rows if r[0] >= start]
        raise _http(404)
    monkeypatch.setattr(X, "_get_json", router)
    pos = _held_row(anchor=[last_priced, 1.00], day_marks={_yday(0): 1.00})
    kw = data.held_price_kwargs([pos])
    assert kw["anchors"]["XYZ-USD"] == (last_priced, 1.00)
    fr, rep = data.fetch("crypto", ["XYZ-USD"], period=data.held_fetch_period(kw), **kw)
    assert float(fr["XYZ-USD"]["Close"].iloc[-1]) == 0.60
    # ...where the day_marks anchor alone refuses the real coin:
    fr2, rep2 = data.fetch("crypto", ["XYZ-USD"], period="1mo",
                           **data.held_price_kwargs([dict(pos, anchor=None)]))
    assert fr2 == {} and rep2["identity_rejected"] == {"XYZ": ["binance_vision"]}


def test_a_yahoo_coin_missing_yesterdays_row_still_passes_its_stored_anchor(venues, monkeypatch):
    """Yahoo publishes D-1 late: its frame at 02:00 UTC ends D-2, D. The stored
    anchor is the close Yahoo DID have when it last priced the coin (D-2)."""
    idx = [_today().tz_localize(None) - pd.Timedelta(days=k) for k in (4, 3, 2, 0)]
    frame = pd.DataFrame({"Open": 0.05, "High": 0.05, "Low": 0.05, "Close": 0.05,
                          "Volume": 1e6}, index=pd.DatetimeIndex(idx))
    venues()
    monkeypatch.setattr(data, "download", lambda t, period=None, **k: {"AI-USD": frame})
    pos = {"symbol": "AI", "market": "crypto", "last_mark": 0.05, "opened_at": "2026-09-01",
           "anchor": [_yday(2), 0.05], "day_marks": {_yday(0): 0.05}}
    fr, rep = data.fetch("crypto", ["AI-USD"], period="5d", **data.held_price_kwargs([pos]))
    assert float(fr["AI-USD"]["Close"].iloc[-1]) == 0.05 and rep["source_of"] == {"AI-USD": "yahoo"}


def test_the_kill_switch_window_reaches_the_oldest_anchor(monkeypatch):
    seen = {}

    def fake_fetch(market, tickers, period=None, **kw):
        seen["period"] = period
        return {}, {}
    monkeypatch.setattr(data, "fetch", fake_fetch)
    monkeypatch.setattr(data, "download", lambda *a, **k: {})
    old = (_today() - pd.Timedelta(days=12)).strftime("%Y-%m-%d")
    ks._live_marks({"open": [{"symbol": "XYZ", "market": "crypto", "status": "open",
                              "last_mark": 1.0, "anchor": [old, 1.0]}]})
    assert seen["period"] == "1mo"
    assert data.held_fetch_period({"anchors": {}}) == "5d"
    assert data.held_fetch_period({"anchors": {"A": (_yday(2), 1.0)}}) == "5d"


def test_the_scans_own_fetch_forwards_the_identity_kwargs(monkeypatch):
    """scan._bars had no anchors/require_identity parameters, so the path
    that downloads its own frames raised TypeError on every market."""
    from scanner import scan
    seen = {}
    monkeypatch.setattr(scan, "fetch", lambda m, t, **kw: (seen.update(kw) or ({}, {})))
    scan._bars("crypto", ["BTC-USD"], "5y", **data.identity_kwargs("crypto", [
        {"symbol": "BTC", "yf": "BTC-USD", "cg_price": 100.0, "cg_stale": True}]))
    assert "anchors" in seen and seen["require_identity"] is True


def test_the_age_gate_is_ONE_day():
    """Crypto trades 24/7 and every venue opens today's candle at 00:00 UTC;
    at 3 days a pair frozen two days ago still beat a live venue."""
    assert config.EXCHANGE_MAX_BAR_AGE_DAYS == 1


def test_a_malformed_stored_anchor_falls_back_to_day_marks():
    """A hand-edited or truncated `anchor` must never become the evidence:
    a zero/negative close or a date that is not YYYY-MM-DD is ignored."""
    base = {"symbol": "XYZ", "market": "crypto", "last_mark": 1.0, "opened_at": "2026-09-01",
            "day_marks": {_yday(0): 0.9}}
    for bad in (["2026-09-20", 0], ["2026-09-20", -1.0], ["20260920", 1.0], ["2026-09-20"],
                None, "junk", [None, 1.0]):
        kw = data.held_price_kwargs([dict(base, anchor=bad)])
        assert kw["anchors"]["XYZ-USD"] == (_yday(1), 0.9), bad
