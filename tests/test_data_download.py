"""Downloader resilience: a throttled batch (Yahoo 429 / empty result) must
recover via retry + back-off so coverage stays high, instead of discarding a
whole chunk of tickers at the first sign of throttling.
"""

import numpy as np
import pandas as pd

from scanner import data


def _multi_frame(tickers):
    """A yfinance-style group_by='ticker' MultiIndex OHLCV frame."""
    idx = pd.date_range("2024-01-01", periods=300, freq="D")
    cols = [(t, f) for t in tickers for f in ("Open", "High", "Low", "Close", "Volume")]
    arr = np.column_stack([np.linspace(10, 12, 300) for _ in cols])
    return pd.DataFrame(arr, index=idx, columns=pd.MultiIndex.from_tuples(cols))


def test_download_recovers_throttled_batches(monkeypatch):
    monkeypatch.setattr(data.time, "sleep", lambda *a: None)   # no real waits
    tickers = [f"T{i}.AX" for i in range(250)]                 # 3 chunks at chunk=120
    calls = {"n": 0}

    def fake_dl(batch, **kw):
        calls["n"] += 1
        if calls["n"] % 2 == 1:            # throttle the first attempt of each batch
            return pd.DataFrame()          # empty = throttled
        return _multi_frame(list(batch))   # retry succeeds

    monkeypatch.setattr(data.yf, "download", fake_dl)
    frames = data.download(tickers)
    assert len(frames) == len(tickers)     # every batch recovered on retry — full coverage


def test_recovery_sweep_reclaims_transiently_throttled(monkeypatch):
    """A batch that fails the whole main pass is re-tried on the recovery sweep —
    so transient throttling doesn't permanently cost coverage."""
    from scanner import config
    monkeypatch.setattr(data.time, "sleep", lambda *a: None)
    tickers = [f"T{i}.AX" for i in range(240)]                 # 2 chunks at 120
    calls = {"b1": 0}

    def fake_dl(batch, **kw):
        if "T0.AX" in batch:                                   # the first chunk
            calls["b1"] += 1
            if calls["b1"] <= config.DATA_RETRIES + 1:         # throttled for the entire main pass
                return pd.DataFrame()
        return _multi_frame(list(batch))

    monkeypatch.setattr(data.yf, "download", fake_dl)
    frames = data.download(tickers)
    assert len(frames) == len(tickers)                         # recovery sweep reclaimed the first chunk
    assert "T0.AX" in frames


def test_download_stays_fast_until_heavy_throttling(monkeypatch):
    """Healthy batches incur no long waits; a long cooldown only kicks in after a
    run of consecutive failures (clear heavy throttling)."""
    from scanner import config
    sleeps = []
    monkeypatch.setattr(data.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(data.yf, "download", lambda *a, **k: pd.DataFrame())  # everything throttled
    tickers = [f"T{i}.AX" for i in range(config.DATA_CHUNK * 5)]              # 5 dead batches
    assert data.download(tickers) == {}
    # The big recovery cooldown only appears after DATA_HEAVY_AFTER failures in a row.
    assert any(s >= config.DATA_HEAVY_COOLDOWN * 0.7 for s in sleeps)


def test_download_skips_dead_batch_but_keeps_the_rest(monkeypatch):
    monkeypatch.setattr(data.time, "sleep", lambda *a: None)
    tickers = [f"T{i}.AX" for i in range(240)]                 # 2 chunks at chunk=120

    def fake_dl(batch, **kw):
        if "T0.AX" in batch:               # first chunk is permanently throttled
            return pd.DataFrame()
        return _multi_frame(list(batch))

    monkeypatch.setattr(data.yf, "download", fake_dl)
    frames = data.download(tickers)
    assert 0 < len(frames) < len(tickers)  # dead chunk dropped, healthy chunk kept
    assert "T120.AX" in frames and "T0.AX" not in frames


# ── last-good per-ticker frame cache ────────────────────────────────────────────

def _ohlc(last_date=None, n=60):
    """A plain daily OHLCV frame ending `last_date` (DEFAULT: today).

    The default used to be a hard-coded "2024-06-01". Harmless while nothing
    read the frame's age; since TOP100 #24 `merge_with_cache` refuses a cached
    frame older than FRAME_CACHE_MAX_AGE_DAYS, so a fixed past date would make
    every reuse test silently exercise the FOSSIL path instead of the reuse
    path it is named for. Tests that care about age pass the date explicitly.
    """
    if last_date is None:
        last_date = pd.Timestamp.now().normalize()
    idx = pd.date_range(end=last_date, periods=n, freq="D")
    return pd.DataFrame({"Open": 10.0, "High": 10.5, "Low": 9.5, "Close": 10.0,
                         "Volume": 1e6}, index=idx)


def test_merge_with_cache_reuses_dropped_tickers(tmp_path, monkeypatch):
    """Tickers Yahoo drops this run are filled from the last-good cache."""
    monkeypatch.setattr(data, "_CACHE_DIR", tmp_path / "frames")
    uni = ["A.AX", "B.AX", "C.AX"]
    # First run: all three downloaded → cache primed.
    full = {t: _ohlc() for t in uni}
    merged, stats = data.merge_with_cache("asx", full, uni)
    assert stats == {"fresh": 3, "reused": 0, "merged": 3, "universe": 3,
                     "stale_dropped": 0}
    # Second run: Yahoo only returns A; B and C must be reused from cache.
    partial = {"A.AX": _ohlc()}
    merged, stats = data.merge_with_cache("asx", partial, uni)
    assert set(merged) == {"A.AX", "B.AX", "C.AX"}
    assert stats["fresh"] == 1 and stats["reused"] == 2 and stats["merged"] == 3


def test_merge_with_cache_drops_out_of_universe(tmp_path, monkeypatch):
    """The cache shouldn't accumulate delisted names forever."""
    monkeypatch.setattr(data, "_CACHE_DIR", tmp_path / "frames")
    data.merge_with_cache("asx", {"OLD.AX": _ohlc(), "A.AX": _ohlc()}, ["OLD.AX", "A.AX"])
    # Next universe no longer contains OLD; a run that drops A reuses only A's slot.
    merged, stats = data.merge_with_cache("asx", {}, ["A.AX"])
    assert set(merged) == {"A.AX"}
    cached = data.load_frame_cache("asx")
    assert "OLD.AX" not in cached


def test_frame_age_days_counts_staleness():
    fresh = _ohlc(last_date=pd.Timestamp.now().normalize())
    assert data._frame_age_days(fresh) == 0
    old = _ohlc(last_date=pd.Timestamp.now().normalize() - pd.Timedelta(days=5))
    assert data._frame_age_days(old) == 5


# ── TOP100 #23: "today" belongs to the exchange, not to the runner ───────────
# `_frame_age_days` compared exchange-local bar dates against the RUNNER's naive
# date. Wrong by up to a day in both directions, and the ASX direction is the
# one that costs money: it understates staleness, and vivek_bot's `stale_data`
# gate is what stops the bot opening a position on a cache-reused frame
# describing a market that has since moved.

def _bar_dated(y, m, d):
    return _ohlc(last_date=pd.Timestamp(f"{y}-{m:02d}-{d:02d}"))


def test_the_asx_date_is_a_day_ahead_of_the_runner_and_the_age_follows(monkeypatch):
    """23:00 UTC Tuesday is already Wednesday in Sydney. Tuesday's bar is one
    ASX day old, and reading it as fresh is what let a stale frame through."""
    import datetime as dt_

    real = dt_.datetime

    class _Fixed(dt_.datetime):
        @classmethod
        def now(cls, tz=None):
            base = real(2026, 7, 21, 23, 0, tzinfo=dt_.timezone.utc)
            return base if tz is None else base.astimezone(tz)

    monkeypatch.setattr(data.dt, "datetime", _Fixed)
    tuesday = _bar_dated(2026, 7, 21)
    assert data._frame_age_days(tuesday) == 0                    # UTC calendar
    assert data._frame_age_days(tuesday, "Australia/Sydney") == 1  # the truth


def test_a_fresh_nasdaq_session_is_not_aged_out_by_the_utc_rollover(monkeypatch):
    """The mirror image. 01:00 UTC Thursday is 21:00 Wednesday in New York, so
    Wednesday's close is that session's own bar — refusing it as a day old would
    skip perfectly fresh setups."""
    import datetime as dt_

    real = dt_.datetime

    class _Fixed(dt_.datetime):
        @classmethod
        def now(cls, tz=None):
            base = real(2026, 7, 23, 1, 0, tzinfo=dt_.timezone.utc)
            return base if tz is None else base.astimezone(tz)

    monkeypatch.setattr(data.dt, "datetime", _Fixed)
    wednesday = _bar_dated(2026, 7, 22)
    assert data._frame_age_days(wednesday) == 1                  # UTC calendar
    assert data._frame_age_days(wednesday, "America/New_York") == 0


def test_an_unusable_timezone_falls_back_to_the_old_answer_not_to_fresh(caplog):
    """A bad zone must degrade to the RUNNER's date, never to 0.

    The tz resolution is deliberately outside the arithmetic's try/except: fold
    it in and an unknown zone returns 0, i.e. "perfectly fresh", which is the
    one answer a freshness check must never give by accident."""
    old = _ohlc(last_date=pd.Timestamp.now().normalize() - pd.Timedelta(days=5))
    with caplog.at_level("WARNING"):
        assert data._frame_age_days(old, "Mars/Olympus") == 5
    assert "timezone" in " ".join(r.getMessage() for r in caplog.records)


def test_the_scan_measures_in_the_market_s_own_zone():
    """The fix is only worth anything if the caller passes the zone. Pinned
    against the source so a later edit cannot quietly drop the argument."""
    import inspect

    from scanner import scan as scan_mod
    assert "_frame_age_days(df, market.timezone)" in inspect.getsource(
        scan_mod.scan_vivek_market)


# ── TOP100 #24: a cached frame stops being data eventually ──────────────────
# `merge_with_cache` back-fills tickers Yahoo dropped this run from the last-good
# cache. Right for the ordinary case (a name misses one batch and reappears) and
# it had NO ceiling — so a ticker Yahoo has not returned since March was handed
# to the scanner as if it were today's bars, its last close published as a live
# mark and used to mark held positions and test their stops.

def _cache_ceiling(monkeypatch, days):
    from scanner import config
    monkeypatch.setattr(config, "FRAME_CACHE_MAX_AGE_DAYS", days, raising=False)


def test_a_cached_frame_past_the_ceiling_leaves_the_scan(tmp_path, monkeypatch, caplog):
    """The whole point. A fossil is refused rather than priced off."""
    monkeypatch.setattr(data, "_CACHE_DIR", tmp_path / "frames")
    _cache_ceiling(monkeypatch, 10)
    uni = ["FRESH.AX", "FOSSIL.AX"]
    old = pd.Timestamp.now().normalize() - pd.Timedelta(days=60)
    data.merge_with_cache("asx", {"FRESH.AX": _ohlc(), "FOSSIL.AX": _ohlc(last_date=old)}, uni)
    with caplog.at_level("WARNING"):
        merged, stats = data.merge_with_cache("asx", {}, uni)
    assert set(merged) == {"FRESH.AX"}          # the fossil is gone, the rest is not
    assert stats["reused"] == 1 and stats["stale_dropped"] == 1
    # Named, not counted. "1 dropped" is not something anyone can act on.
    assert "FOSSIL.AX" in " ".join(r.getMessage() for r in caplog.records)


def test_a_refused_frame_is_forgotten_but_never_at_the_cost_of_the_whole_cache(
        tmp_path, monkeypatch):
    """A refused frame is not re-saved, so the run that stops serving it is also
    the run that drops it — UNLESS dropping it would leave nothing to save.

    Two guards meet here and the order matters. `save_frame_cache` has always
    refused to write an empty dict, so a run in which Yahoo returned nothing at
    all cannot wipe the cache; that guard wins, and the fossil survives on disk.
    It is refused at READ time on every subsequent run regardless, so nothing
    ever reaches the scanner off it — the only cost is disk. That is the right
    way round: the alternative is a total-outage run deleting a cache that would
    have been useful the moment Yahoo came back.
    """
    monkeypatch.setattr(data, "_CACHE_DIR", tmp_path / "frames")
    _cache_ceiling(monkeypatch, 10)
    old = pd.Timestamp.now().normalize() - pd.Timedelta(days=60)

    # NASDAQ: the fossil is the only thing there is, so the run has nothing to
    # save and the empty-write guard leaves the cache alone. Refused all the same.
    data.merge_with_cache("nasdaq", {"FOSSIL": _ohlc(last_date=old)}, ["FOSSIL"])
    merged, stats = data.merge_with_cache("nasdaq", {}, ["FOSSIL"])
    assert merged == {} and stats["stale_dropped"] == 1
    assert "FOSSIL" in data.load_frame_cache("nasdaq")         # kept on disk, unused

    # ASX: something survives, so the save runs and the fossil goes with it.
    uni = ["FOSSIL.AX", "LIVE.AX"]
    data.merge_with_cache("asx", {"FOSSIL.AX": _ohlc(last_date=old),
                                  "LIVE.AX": _ohlc()}, uni)
    assert "FOSSIL.AX" in data.load_frame_cache("asx")         # still there going in
    merged, _ = data.merge_with_cache("asx", {}, uni)
    assert set(merged) == {"LIVE.AX"}
    assert "FOSSIL.AX" not in data.load_frame_cache("asx")     # and gone coming out


def test_a_fresh_download_of_a_fossil_name_is_never_refused(tmp_path, monkeypatch):
    """The ceiling gates the CACHE, never the download. A name Yahoo returns today
    is today's data whatever the cache remembers about it."""
    monkeypatch.setattr(data, "_CACHE_DIR", tmp_path / "frames")
    _cache_ceiling(monkeypatch, 10)
    old = pd.Timestamp.now().normalize() - pd.Timedelta(days=60)
    data.merge_with_cache("asx", {"BACK.AX": _ohlc(last_date=old)}, ["BACK.AX"])
    merged, stats = data.merge_with_cache("asx", {"BACK.AX": _ohlc()}, ["BACK.AX"])
    assert set(merged) == {"BACK.AX"} and stats["stale_dropped"] == 0


def test_zero_restores_the_old_unbounded_reuse_exactly(tmp_path, monkeypatch):
    """The escape hatch has to actually work — an off switch nobody has tested is
    not an off switch, and this is the one knob to reach for if the ceiling ever
    turns out to be cutting into a real outage."""
    monkeypatch.setattr(data, "_CACHE_DIR", tmp_path / "frames")
    _cache_ceiling(monkeypatch, 0)
    ancient = pd.Timestamp.now().normalize() - pd.Timedelta(days=900)
    data.merge_with_cache("asx", {"OLD.AX": _ohlc(last_date=ancient)}, ["OLD.AX"])
    merged, stats = data.merge_with_cache("asx", {}, ["OLD.AX"])
    assert set(merged) == {"OLD.AX"} and stats["stale_dropped"] == 0


def test_the_ceiling_is_measured_in_the_markets_calendar_too(tmp_path, monkeypatch):
    """#23 and #24 are one mechanism: the ceiling is only as honest as the age it
    reads, so `merge_with_cache` must pass the market's zone through rather than
    fall back to the runner's date."""
    import inspect

    src = inspect.getsource(data.merge_with_cache)
    assert '_frame_age_days(cache[t], tz)' in src
    assert 'timezone' in src


def test_the_scan_publishes_how_old_each_mark_is(monkeypatch):
    """A refused frame removes a name from the scan; a REUSED one (inside the
    ceiling) is still a past close being published as a live mark, and the page
    marks every open position off that map. So the age travels with it.

    Sparse by construction: a healthy ASX run publishes ~2,200 marks and every
    one of them is 0. Absent means fresh.
    """
    import inspect

    from scanner import scan as scan_mod
    src = inspect.getsource(scan_mod.scan_vivek_market)
    assert '"price_age": price_age' in src
    assert "price_age[symbol] = age" in src
    # The age must be computed BEFORE the price snapshot, not inside the scoring
    # block below it: a name that fails `evaluate` still publishes a price, and a
    # held position that has dropped out of the setup list is precisely the row
    # that gets priced off cache for weeks.
    assert src.index("age = _frame_age_days(df, market.timezone)") < src.index(
        'prices[symbol] = round(')

    from scanner import run as run_mod
    assert '"price_age": vk.get("price_age")' in inspect.getsource(run_mod.main)
