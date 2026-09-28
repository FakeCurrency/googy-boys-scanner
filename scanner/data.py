"""Batched OHLCV download from Yahoo Finance via yfinance."""

import datetime as dt
import gzip
import logging
import pathlib
import pickle
import random
import time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

from . import config

log = logging.getLogger(__name__)

# Last-good per-ticker frame cache. Yahoo throttling drops a variable slice of the
# universe every run; rather than letting those tickers vanish from the scan, we
# keep the last successful deep frame for each and reuse it (with honest aging)
# when a fresh download fails. The cache lives outside the committed tree and is
# restored across CI runs via actions/cache.
_CACHE_DIR = pathlib.Path(__file__).resolve().parents[1] / ".cache" / "frames"


def _cache_path(market_key: str) -> pathlib.Path:
    """One cache file per market -- and per SOURCE for crypto (2026-09-28).
    The pre-switch crypto cache holds Yahoo frames, including the wrong-token
    series the identity check now refuses (M, MNT: Yahoo priced different
    tokens at ~$0.0003). Reading it after the switch would back-fill them for
    up to FRAME_CACHE_MAX_AGE_DAYS, so exchange mode reads and writes its own
    file and starts clean; a revert to "yahoo" goes back to the old one."""
    if (market_key == "crypto" or market_key.endswith("-crypto")) and \
            str(getattr(config, "CRYPTO_DATA_SOURCE", "yahoo")) == "exchange":
        return _CACHE_DIR / f"{market_key}.exchange.pkl.gz"   # also ignition-crypto
    return _CACHE_DIR / f"{market_key}.pkl.gz"


def load_frame_cache(market_key: str) -> dict[str, pd.DataFrame]:
    """Last-good {ticker: DataFrame} for a market, or {} if no cache yet."""
    p = _cache_path(market_key)
    if not p.exists():
        return {}
    try:
        with gzip.open(p, "rb") as f:
            data = pickle.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        log.warning("frame cache: failed to load %s (%s) — ignoring", p, e)
        return {}


def save_frame_cache(market_key: str, frames: dict[str, pd.DataFrame]) -> None:
    """Persist the last-good frames for a market (atomic write)."""
    if not frames:
        return
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _cache_path(market_key)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        with gzip.open(tmp, "wb") as f:
            pickle.dump(frames, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(p)
    except Exception as e:
        log.warning("frame cache: failed to save %s (%s)", p, e)


def _frame_age_days(df: pd.DataFrame, tz: str | None = None) -> int:
    """How many days old the frame's most recent bar is (0 = today).

    MEASURED IN THE MARKET'S OWN CALENDAR when `tz` is given (2026-07-28,
    TOP100 #23). "Today" is a property of the exchange, not of whatever machine
    happens to be running the scan, and the bars are dated in exchange-local
    time — so comparing them against the runner's date compares two different
    calendars and is wrong by up to a day in BOTH directions:

      * ASX (UTC+10/+11) — a scan at 23:00 UTC Tuesday is Wednesday in Sydney.
        Tuesday's bar reads 0 days old against the UTC date and 1 against the
        ASX date. This is the dangerous direction: it UNDERSTATES staleness, and
        `vivek_bot`'s `stale_data` gate (VIVEK_BOT_MAX_DATA_AGE_DAYS) is what
        stops the bot opening a position on a cache-reused frame describing a
        market that has since moved.
      * NASDAQ (UTC-4/-5) — the mirror image: a scan at 01:00 UTC reads the
        session that closed four hours ago as a day old and can refuse a
        perfectly fresh frame.

    `tz` defaults to None, which keeps the old naive comparison, because the
    fallback has to be something and a wrong timezone would be worse than none.
    Every caller in the scan path passes the market's own zone; `scan.py`
    already had `ZoneInfo(market.timezone)` in hand one line away.
    """
    # Resolve the zone SEPARATELY from the arithmetic. Folding it into the block
    # below would make an unknown zone return 0 — i.e. "perfectly fresh" — which
    # is the one answer a freshness check must never give by accident.
    today = None
    if tz:
        try:
            today = dt.datetime.now(ZoneInfo(tz)).date()
        except Exception as e:                                    # noqa: BLE001
            log.warning("frame age: unusable timezone %r (%s) - falling back to "
                        "the runner's own date, which can be a day out", tz, e)
    if today is None:
        today = dt.datetime.now().date()
    try:
        last = df.index[-1]
        last = last.to_pydatetime() if hasattr(last, "to_pydatetime") else last
        return max(0, (today - last.date()).days)
    except Exception:
        return 0


def merge_with_cache(market_key: str, fresh: dict[str, pd.DataFrame],
                     tickers: list[str],
                     refused=()) -> tuple[dict[str, pd.DataFrame], dict]:
    """Fill tickers Yahoo dropped this run from the last-good cache, then refresh
    the cache with everything we now hold (capped to the current universe).

    `refused` (fetch()'s report["refused"]): tickers the IDENTITY CHECK turned
    down this run -- every source that listed them priced a different token.
    Those are never back-filled and are dropped from the saved cache: the
    cache only knows a ticker is missing, not why, and refilling a coin the
    check just refused re-scans the stranger it refused (2026-09-28 review).

    Returns (merged_frames, stats) where stats reports fresh vs reused counts so
    the scan can stamp honest coverage/aging.
    """
    cache = load_frame_cache(market_key)
    merged = dict(fresh)
    reused = 0
    refused = set(refused or ())
    wanted = set(tickers) - refused
    # A cached frame is only DATA for so long (TOP100 #24). Past the ceiling it
    # is a fossil, and a fossil's last close is published as a live mark and used
    # to mark held positions and test their stops. See FRAME_CACHE_MAX_AGE_DAYS.
    max_age = int(getattr(config, "FRAME_CACHE_MAX_AGE_DAYS", 0) or 0)
    mkt = config.MARKETS.get(market_key) if hasattr(config, "MARKETS") else None
    tz = getattr(mkt, "timezone", None)
    fossils: list[str] = []
    for t in sorted(wanted):
        if t in merged or t not in cache:
            continue
        if max_age and _frame_age_days(cache[t], tz) > max_age:
            fossils.append(t)
            continue
        merged[t] = cache[t]
        reused += 1
    # Persist only current-universe tickers so the cache doesn't accumulate
    # delisted names forever; freshly downloaded frames overwrite stale ones.
    # A fossil is NOT re-saved: it is already excluded from `merged`, so a run
    # with anything at all to save is also the run that drops it from disk. Note
    # `save_frame_cache` refuses to write an EMPTY dict — so a run in which
    # Yahoo returned nothing leaves the fossil on disk rather than wiping a
    # cache that will be useful the moment Yahoo comes back. That guard wins on
    # purpose: the fossil is refused at read time on every later run regardless,
    # so nothing reaches the scanner off it and the only cost is disk.
    save_frame_cache(market_key, {t: df for t, df in merged.items() if t in wanted})
    stats = {"fresh": len(fresh), "reused": reused, "merged": len(merged),
             "universe": len(tickers), "stale_dropped": len(fossils),
             "refused": len(refused & set(tickers))}
    if reused:
        log.info("frame cache: reused %d cached tickers Yahoo dropped (now %d/%d)",
                 reused, len(merged), len(tickers))
    if fossils:
        # WARNING, not info: these names have silently left the scan. Named,
        # because "12 dropped" is not something anyone can act on.
        log.warning("frame cache [%s]: %d cached tickers are older than %dd and "
                    "were NOT reused - they leave this scan rather than be priced "
                    "off stale bars: %s", market_key, len(fossils), max_age,
                    ", ".join(fossils[:12]) + (" ..." if len(fossils) > 12 else ""))
    return merged, stats

# The full ASX universe has many thin/suspended names; silence yfinance's noisy
# per-ticker "possibly delisted" warnings — we skip those tickers anyway.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


class DataQualityError(Exception):
    """Raised when downloaded OHLCV data fails quality checks."""


def validate_bars(df: pd.DataFrame, symbol: str = "", interval: str = "1h",
                  min_bars: int | None = None, staleness_hours: float | None = None) -> None:
    """Check downloaded OHLCV for common quality problems.

    Raises DataQualityError with a human-readable reason.
    Callers can catch this to skip the ticker or log a warning.
    """
    min_bars = min_bars or config.SCALP_DATA_MIN_BARS
    staleness_hours = staleness_hours or config.DATA_STALENESS_HOURS

    if df is None or len(df) == 0:
        raise DataQualityError(f"{symbol}: empty dataframe")

    if len(df) < min_bars:
        raise DataQualityError(
            f"{symbol}: only {len(df)} bars (need {min_bars})"
        )

    close = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
    nan_frac = close.isna().mean()
    if nan_frac > 0.1:
        raise DataQualityError(
            f"{symbol}: {nan_frac:.0%} of Close values are NaN"
        )

    last_val = close.dropna().iloc[-1] if not close.dropna().empty else None
    if last_val is None or not np.isfinite(last_val) or last_val <= 0:
        raise DataQualityError(f"{symbol}: last close is invalid ({last_val!r})")

    # Staleness check — only meaningful for intraday data
    if interval in ("1m", "5m", "15m", "30m", "1h"):
        idx = df.index
        if hasattr(idx, "tz") and idx.tz is None:
            last_ts = pd.Timestamp(idx[-1], tz="UTC")
        else:
            last_ts = pd.Timestamp(idx[-1]).tz_convert("UTC") if idx.tz else pd.Timestamp(idx[-1], tz="UTC")
        now_utc = pd.Timestamp.now("UTC")
        age_hours = (now_utc - last_ts).total_seconds() / 3600
        if age_hours > staleness_hours:
            raise DataQualityError(
                f"{symbol}: last bar is {age_hours:.1f}h old (stale, limit={staleness_hours}h)"
            )


def _fetch_batch(batch: list[str], period: str, interval: str,
                 retries: int, backoff: list[float]) -> pd.DataFrame | None:
    """Download one batch, retrying with an escalating back-off on failure.

    Yahoo throttles bursty requests (429). A short 2–4s wait isn't enough to
    recover, so each retry waits progressively longer (config.DATA_BACKOFF, with
    jitter) before re-requesting the SAME batch — patience keeps coverage high
    rather than discarding 100+ tickers at the first sign of throttling.
    """
    for attempt in range(retries + 1):
        try:
            data = yf.download(
                batch, period=period, interval=interval,
                group_by="ticker", auto_adjust=True,
                threads=True, progress=False,
            )
            if data is not None and len(data):
                return data
            reason = "empty result (likely throttled)"
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"
        if attempt < retries:
            wait = backoff[min(attempt, len(backoff) - 1)] * (0.8 + 0.4 * random.random())
            log.warning("batch attempt %d/%d failed (%s) — backing off %.1fs",
                        attempt + 1, retries + 1, reason, wait)
            time.sleep(wait)
    return None


def _download_pass(tickers: list[str], period: str, interval: str, chunk: int,
                   retries: int, backoff: list[float], pause: float,
                   label: str) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """One pass over `tickers` in batches. Returns (frames, failed_tickers).

    Fast by default — healthy batches incur only a tiny jittered pause. A longer
    cooldown is used ONLY after several consecutive batches fail (clear heavy
    throttling), so normal runs never pay for it.
    """
    frames: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    consecutive_fail = 0
    n_batches = (len(tickers) + chunk - 1) // chunk

    for bi, start in enumerate(range(0, len(tickers), chunk)):
        if start:
            time.sleep(pause * (0.6 + 0.8 * random.random()))
        batch = tickers[start:start + chunk]
        data = _fetch_batch(batch, period, interval, retries, backoff)

        if data is None or len(data) == 0:          # whole batch unavailable this pass
            failed.extend(batch)
            consecutive_fail += 1
            log.warning("[%s] batch %d/%d (%d tickers) no data after %d attempts",
                        label, bi + 1, n_batches, len(batch), retries + 1)
            if consecutive_fail >= config.DATA_HEAVY_AFTER and bi + 1 < n_batches:
                cooldown = config.DATA_HEAVY_COOLDOWN * (0.8 + 0.4 * random.random())
                log.warning("[%s] heavy throttling (%d batches failed in a row) — cooling %.0fs",
                            label, consecutive_fail, cooldown)
                time.sleep(cooldown)
            continue
        consecutive_fail = 0

        for ticker in batch:
            try:
                df = data[ticker].copy() if isinstance(data.columns, pd.MultiIndex) else data.copy()
                df = df.dropna()
                if len(df):
                    frames[ticker] = df
                else:
                    failed.append(ticker)          # empty → retry it on the recovery sweep
            except Exception as e:
                failed.append(ticker)
                log.warning("[%s] %s: %s: %s", label, ticker, type(e).__name__, e)
    return frames, failed


def download(tickers: list[str], period: str | None = None,
             interval: str = "1d", chunk: int | None = None,
             retries: int | None = None) -> dict[str, pd.DataFrame]:
    """Download OHLCV for many tickers, returned as {ticker: DataFrame}.

    Strategy: a FAST main pass (short retry waits) gets the bulk quickly; then a
    single RECOVERY SWEEP re-tries only the tickers that failed — after a brief
    cooldown — to reclaim coverage lost to transient throttling. Healthy runs
    (no failures) skip the sweep entirely and stay fast; throttled runs recover
    most of what a slow-but-patient single pass would have, in less time.
    """
    period = period or config.DATA_PERIOD
    chunk = chunk or config.DATA_CHUNK
    retries = config.DATA_RETRIES if retries is None else retries
    backoff = config.DATA_BACKOFF
    pause = config.DATA_BATCH_PAUSE
    total = len(tickers)

    frames, failed = _download_pass(tickers, period, interval, chunk, retries, backoff, pause, "pass 1")

    # Recovery sweep: re-try the failed tickers once. Only worth it when this was
    # partial throttling (we got *some* data) rather than a total outage.
    if failed and frames and len(failed) < total:
        cooldown = config.DATA_RECOVERY_COOLDOWN * (0.8 + 0.4 * random.random())
        log.info("recovery sweep: %d/%d failed pass 1 — cooling %.0fs then retrying",
                 len(failed), total, cooldown)
        time.sleep(cooldown)
        more, still_failed = _download_pass(failed, period, interval, chunk, retries, backoff, pause, "recovery")
        frames.update(more)
        log.info("recovery sweep: reclaimed %d/%d tickers", len(more), len(failed))

    got = len(frames)
    cov = 100.0 * got / total if total else 0.0
    log.info("download: %d/%d tickers (%.0f%% coverage)", got, total, cov)
    if total and got == 0:
        log.error("download: ZERO tickers returned for %d requested — upstream data source likely down", total)

    return frames


# ── market-aware bars: the ONE entry point for anything that prices crypto ───

# A pinned venue -> the kline sources that ARE that venue (Binance's public
# API and its market-data mirror serve the same candles).
_PIN_SOURCES = {"binance_vision": ("binance_vision", "binance"),
                "binance": ("binance_vision", "binance"),
                "bybit": ("bybit",), "coinbase": ("coinbase",)}


def fetch(market_key: str, tickers: list[str], period: str | None = None,
          interval: str = "1d", ref_prices: dict | None = None,
          ref_tol: float | None = None, pin: dict | None = None,
          **kw) -> tuple[dict[str, pd.DataFrame], dict]:
    """({ticker: frame}, source report) -- what the scan, the paper bot and
    the kill switch price through, so crypto can never come from two sources
    depending on which path asked (owner, 2026-09-28: "make the VIVEK crypto
    scan and paper bot go to the binance or bybit ... so it's all in SYNC").

    crypto with config.CRYPTO_DATA_SOURCE == "exchange": public exchange daily
    klines per coin (scanner/exchange_data.py -- exact 00:00 UTC closes, quote
    volume), Yahoo only for the coins no exchange lists (and only when
    CRYPTO_YAHOO_FALLBACK). Every other market, or "yahoo": `download()`
    exactly as before. Tickers keep their Yahoo spelling ("QNT-USD") either
    way, so every caller's keys are unchanged.

    `interval` "1d" (the scan, the bot, the lens) or "4h" (the display-only
    4H plans). Yahoo has no 4h, so a Yahoo leg asks for 1h and vivek's
    resampler buckets it -- the same bins an exchange's 4h candles already
    sit in.

    `ref_prices` {ticker: CoinGecko price} arms the IDENTITY CHECK
    (`ref_tol`, default config.CRYPTO_IDENTITY_TOL; callers holding an OLD
    reference pass CRYPTO_IDENTITY_TOL_STALE): a source -- exchange OR Yahoo
    -- whose latest close is not that coin's price is rejected for it, and a
    coin no source confirms is left out rather than scanned as a same-ticker
    stranger. Such tickers are listed in report["refused"] so the frame cache
    never back-fills them (merge_with_cache).

    `pin` {ticker: venue} prices a HELD coin from the venue the scan marked it
    on and nowhere else (the kill switch and the book's off-universe fetch):
    the first venue that lists a ticker can be a different token (Binance's
    AI and LIT were, 2026-09-28), and a position must never be stop-tested
    on another instrument. A pinned venue that fails gives no frame -- the
    position shows as unpriced -- never a quote from somewhere else.

    The report: `source_of` {ticker: venue}, `by_source` counts, `dead`
    venues (refused the runner), `yahoo_fallback` count, `identity_rejected`,
    `stale_rejected` (a venue whose newest bar is too old: a delisted pair),
    `refused`, and `unchecked` (tickers priced with no reference at all).
    """
    tickers = list(tickers)
    yahoo_iv = {"4h": "1h"}.get(interval, interval)
    # A daily Yahoo leg keeps the exact call shape `download` always had.
    ykw = dict(kw) if yahoo_iv == "1d" else {**kw, "interval": yahoo_iv}
    if market_key == "crypto" and str(getattr(config, "CRYPTO_DATA_SOURCE", "yahoo")) == "exchange":
        from . import exchange_data
        suffix = config.MARKETS["crypto"].suffix
        base = {t: (t[:-len(suffix)] if suffix and t.endswith(suffix) else t) for t in tickers}
        refs = {base[t]: v for t, v in (ref_prices or {}).items() if t in base}
        days = exchange_data.period_days(period or config.DATA_PERIOD)
        # Pinned tickers go to their venue ONLY; the rest walk every venue.
        pins = {t: str((pin or {}).get(t) or "") for t in tickers}
        groups: dict[tuple, list[str]] = {}
        to_yahoo: list[str] = []
        for t in tickers:
            v = pins[t]
            if v == "yahoo":
                to_yahoo.append(t)
            else:
                groups.setdefault(_PIN_SOURCES.get(v, ()), []).append(t)
        rejected: dict[str, list] = {}
        stale: dict[str, list] = {}
        frames: dict[str, pd.DataFrame] = {}
        source_of: dict[str, str] = {}
        dead: dict = {}
        errors: dict = {}
        no_exchange: list = []
        for srcs, ts in groups.items():
            ex, rep = exchange_data.download_klines(
                [base[t] for t in ts], days=days, sources=srcs or None,
                interval=interval, ref_prices={base[t]: refs[base[t]] for t in ts if base[t] in refs},
                ref_tol=ref_tol)
            for k, v in (rep.get("identity_rejected") or {}).items():
                rejected.setdefault(k, []).extend(v)
            for k, v in (rep.get("stale_rejected") or {}).items():
                stale.setdefault(k, []).extend(v)
            for k, v in (rep.get("dead") or {}).items():
                dead.setdefault(k, v)
            for k, v in (rep.get("errors") or {}).items():
                errors[k] = errors.get(k, 0) + v
            for t in ts:
                f = ex.get(str(base[t]).upper())
                if f is not None and len(f):
                    frames[t] = f
                    source_of[t] = f.attrs.get("source", "exchange")
                elif not srcs:
                    # Unpinned and no exchange has it: the Yahoo fallback.
                    # A PINNED coin whose venue failed does not fall back.
                    no_exchange.append(base[t])
                    to_yahoo.append(t)
        fb: dict[str, pd.DataFrame] = {}
        if to_yahoo and getattr(config, "CRYPTO_YAHOO_FALLBACK", True):
            asked = set(to_yahoo)
            fb = {t: f for t, f in download(to_yahoo, period=period, **ykw).items()
                  if t in asked}
            for t, f in list(fb.items()):
                if not exchange_data.same_coin(f, (ref_prices or {}).get(t), ref_tol):
                    rejected.setdefault(base[t], []).append("yahoo")
                    del fb[t]
                    continue
                f.attrs["source"] = "yahoo"
                frames[t] = f
                source_of[t] = "yahoo"
        refused = sorted(t for t in tickers if t not in frames and base[t].upper() in
                         {str(k).upper() for k in rejected})
        report = {"mode": "exchange", "dead": dead, "errors": errors,
                  "no_exchange": sorted(no_exchange),
                  "yahoo_fallback": len(fb), "source_of": source_of,
                  "identity_rejected": dict(sorted(rejected.items())),
                  "stale_rejected": dict(sorted(stale.items())),
                  "refused": refused,
                  "unchecked": sum(1 for t in frames
                                   if (ref_prices or {}).get(t) is None and not pins[t])}
    else:
        frames = download(tickers, period=period, **ykw)
        report = {"mode": "yahoo", "dead": {}, "errors": {}, "no_exchange": [],
                  "yahoo_fallback": 0, "source_of": {t: "yahoo" for t in frames},
                  "identity_rejected": {}, "stale_rejected": {}, "refused": [],
                  "unchecked": 0}
    by: dict[str, int] = {}
    for v in report["source_of"].values():
        by[v] = by.get(v, 0) + 1
    report["by_source"] = dict(sorted(by.items(), key=lambda kv: -kv[1]))
    if report["mode"] == "exchange":
        log.info("fetch [%s]: %s; dead %s; yahoo fallback %d",
                 market_key, report["by_source"], report["dead"], report["yahoo_fallback"])
        if report["unchecked"]:
            log.warning("fetch [%s]: identity check OFF for %d coin(s) -- no reference "
                        "price (no CoinGecko price in the universe)", market_key,
                        report["unchecked"])
    return frames, report


def venue_of(frames: dict, ticker: str | None) -> str | None:
    """The venue a frame came from (fetch() stamps every crypto frame's
    attrs["source"]; the stamp survives the frame cache's pickle)."""
    df = frames.get(ticker) if ticker else None
    src = getattr(df, "attrs", {}).get("source") if df is not None else None
    return str(src) if src else None


def held_price_kwargs(positions: list) -> dict:
    """fetch() kwargs that price HELD crypto the way the scan marked it
    (2026-09-28 review). A position that records its venue (`data_source`,
    stamped by vivek_run each time it is marked) is PINNED to it; one that
    predates the stamp is checked against its own last accepted mark with
    the wide stale band -- enough to refuse a same-ticker stranger priced
    orders of magnitude away, never enough to refuse a real crash."""
    suffix = config.MARKETS["crypto"].suffix
    pin, refs = {}, {}
    for p in positions or []:
        if p.get("market") != "crypto" or not p.get("symbol"):
            continue
        yf = f"{p['symbol']}{suffix}"
        src = p.get("data_source")
        if src and src != "cache":
            pin[yf] = src
        elif (p.get("last_mark") or 0) > 0:
            refs[yf] = float(p["last_mark"])
    return {"pin": pin, "ref_prices": refs,
            "ref_tol": float(config.CRYPTO_IDENTITY_TOL_STALE)}


def source_summary(report: dict) -> dict:
    """The published half of a fetch() report (the per-ticker map stays out:
    rows carry their own `data_source`)."""
    return {"mode": report.get("mode"), "by_source": report.get("by_source") or {},
            "dead": report.get("dead") or {}, "errors": report.get("errors") or {},
            "no_exchange": list(report.get("no_exchange") or [])[:60],
            "yahoo_fallback": report.get("yahoo_fallback", 0),
            "identity_rejected": report.get("identity_rejected") or {},
            "stale_rejected": report.get("stale_rejected") or {},
            "refused": list(report.get("refused") or []),
            "unchecked": report.get("unchecked", 0)}

