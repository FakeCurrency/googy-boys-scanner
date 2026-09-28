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
                     ref_prices: dict | None = None) -> tuple[dict[str, pd.DataFrame], dict]:
    """Fill tickers Yahoo dropped this run from the last-good cache, then refresh
    the cache with everything we now hold (capped to the current universe).

    Returns (merged_frames, stats) where stats reports fresh vs reused counts so
    the scan can stamp honest coverage/aging.

    `ref_prices` {ticker: CoinGecko price} (crypto; the same map `fetch` takes)
    puts every CACHED frame through the identity check before it is reused
    (2026-09-28). Without it the cache undid `fetch`'s: a coin whose Yahoo
    series is a different token (PRL/SKY/XCN/EDGE/MET, none on an exchange
    here) is rejected by `fetch` -- and then re-admitted from the cache, which
    still holds the stranger from every Yahoo-era run, for the full
    FRAME_CACHE_MAX_AGE_DAYS. A cached frame that fails is neither reused nor
    re-saved, so it leaves the cache too. A None/absent reference checks
    nothing (stocks carry none), exactly as in `fetch`.
    """
    cache = load_frame_cache(market_key)
    merged = dict(fresh)
    reused = 0
    wanted = set(tickers)
    # A cached frame is only DATA for so long (TOP100 #24). Past the ceiling it
    # is a fossil, and a fossil's last close is published as a live mark and used
    # to mark held positions and test their stops. See FRAME_CACHE_MAX_AGE_DAYS.
    max_age = int(getattr(config, "FRAME_CACHE_MAX_AGE_DAYS", 0) or 0)
    mkt = config.MARKETS.get(market_key) if hasattr(config, "MARKETS") else None
    tz = getattr(mkt, "timezone", None)
    fossils: list[str] = []
    strangers: list[str] = []
    refs = {t: v for t, v in (ref_prices or {}).items() if v is not None}
    if refs:
        from .exchange_data import same_coin
    for t in sorted(wanted):
        if t in merged or t not in cache:
            continue
        if max_age and _frame_age_days(cache[t], tz) > max_age:
            fossils.append(t)
            continue
        if t in refs and not same_coin(cache[t], refs[t]):
            strangers.append(t)
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
             "identity_dropped": len(strangers)}
    if strangers:
        stats["identity_dropped_names"] = strangers[:60]
        log.warning("frame cache [%s]: %d cached frames are NOT the coin CoinGecko "
                    "prices under that ticker and were NOT reused - dropped from "
                    "the scan and the cache: %s", market_key, len(strangers),
                    ", ".join(strangers[:12]) + (" ..." if len(strangers) > 12 else ""))
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

def fetch(market_key: str, tickers: list[str], period: str | None = None,
          interval: str = "1d", ref_prices: dict | None = None,
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
    (config.CRYPTO_IDENTITY_TOL): a source -- exchange OR Yahoo -- whose latest
    close is not that coin's price is rejected for it, and a coin no source
    confirms is left out rather than scanned as a same-ticker stranger.

    The report: `source_of` {ticker: venue}, `by_source` counts, `dead`
    venues (refused the runner), `yahoo_fallback` count, `identity_rejected`.
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
        ex, rep = exchange_data.download_klines(
            list(base.values()), days=exchange_data.period_days(period or config.DATA_PERIOD),
            interval=interval, ref_prices=refs)
        rejected = {k: list(v) for k, v in (rep.get("identity_rejected") or {}).items()}
        frames: dict[str, pd.DataFrame] = {}
        source_of: dict[str, str] = {}
        for t, b in base.items():
            f = ex.get(str(b).upper())
            if f is not None and len(f):
                frames[t] = f
                source_of[t] = f.attrs.get("source", "exchange")
        missing = [t for t in tickers if t not in frames]
        fb: dict[str, pd.DataFrame] = {}
        if missing and getattr(config, "CRYPTO_YAHOO_FALLBACK", True):
            fb = download(missing, period=period, **ykw)
            for t, f in list(fb.items()):
                if not exchange_data.same_coin(f, (ref_prices or {}).get(t)):
                    rejected.setdefault(base[t], []).append("yahoo")
                    del fb[t]
                    continue
                frames[t] = f
                source_of[t] = "yahoo"
        report = {"mode": "exchange", "dead": rep.get("dead") or {},
                  "errors": rep.get("errors") or {}, "no_exchange": rep.get("missing") or [],
                  "yahoo_fallback": len(fb), "source_of": source_of,
                  "identity_rejected": dict(sorted(rejected.items()))}
    else:
        frames = download(tickers, period=period, **ykw)
        report = {"mode": "yahoo", "dead": {}, "errors": {}, "no_exchange": [],
                  "yahoo_fallback": 0, "source_of": {t: "yahoo" for t in frames},
                  "identity_rejected": {}}
    by: dict[str, int] = {}
    for v in report["source_of"].values():
        by[v] = by.get(v, 0) + 1
    report["by_source"] = dict(sorted(by.items(), key=lambda kv: -kv[1]))
    if report["mode"] == "exchange":
        log.info("fetch [%s]: %s; dead %s; yahoo fallback %d",
                 market_key, report["by_source"], report["dead"], report["yahoo_fallback"])
    return frames, report


def left_out(report: dict) -> list[str]:
    """The coins the identity check actually LEFT OUT: named in
    `identity_rejected` AND served by no source. `identity_rejected` itself
    lists every venue that refused a coin, including coins a later source
    then confirmed (measured 2026-09-28: Binance's XMR series is the stale
    pre-delisting one and is refused, Yahoo's XMR-USD is Monero and is used)
    -- so reading it as "left out" overstates the gap. Base symbols, sorted."""
    served = {str(t).upper() for t in (report.get("source_of") or {})}
    suffix = str(getattr(config.MARKETS.get("crypto"), "suffix", "") or "").upper()
    return sorted(b for b in (report.get("identity_rejected") or {})
                  if f"{str(b).upper()}{suffix}" not in served and str(b).upper() not in served)


def source_summary(report: dict) -> dict:
    """The published half of a fetch() report (the per-ticker map stays out:
    rows carry their own `data_source`)."""
    return {"mode": report.get("mode"), "by_source": report.get("by_source") or {},
            "dead": report.get("dead") or {}, "errors": report.get("errors") or {},
            "no_exchange": list(report.get("no_exchange") or [])[:60],
            "yahoo_fallback": report.get("yahoo_fallback", 0),
            "identity_rejected": report.get("identity_rejected") or {}}

