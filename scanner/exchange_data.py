"""Exchange daily candles for crypto -- public, KEYLESS market-data endpoints.

WHY THIS EXISTS (2026-09-28). Every bar in the scanner came from Yahoo, crypto
included, and Yahoo's crypto series is an AGGREGATED feed, not an exchange's
candles. The first real IGNITION run showed what that costs: at 02:00 UTC on
28 Sep Yahoo still had no usable 27 Sep bar (the lens screened a day late,
on a setup where the first day is everything), its QNT print sat ~20% under
Binance's at the same hour, and 64 of 201 coins had no data at all. An
exchange's daily kline closes at exactly 00:00 UTC and is served the moment
it does.

WHO READS IT. Everything that prices crypto, through `data.fetch()` (owner,
2026-09-28: "make the VIVEK crypto scan and paper bot go to the binance or
bybit ... so it's all in SYNC"): the VIVEK crypto scan, the paper bot's marks
and stops, the kill switch's live re-pricing and the IGNITION lens. One
switch, config.CRYPTO_DATA_SOURCE, puts them all back on Yahoo. It holds no
credentials and places nothing -- these are the public market-data
endpoints; orders stay in scanner/broker/.

SOURCES, tried in order per coin (config.EXCHANGE_KLINE_SOURCES). Binance and
Bybit geo-block United States IPs, and GitHub's hosted runners are US-based,
so the order starts with Binance's market-data mirror and ends with Coinbase
(US-hosted). Which ones answer from a runner is MEASURED on every run and
published (`report`), never assumed. A source that refuses its first request
with a geo/auth status (403/451/401) is marked dead for the rest of the run:
200 coins must not each wait out a blocked host.

VOLUME IS QUOTE VOLUME (USD / USDT), the unit `volume_is_usd` means. It is ONE
exchange's volume, smaller than Yahoo's aggregate -- so absolute turnover
floors read tighter on exchange data; ratios (RVOL, percentile ranks) do not
care. The source of every frame is recorded so a reader can tell.

Imports only the standard library, pandas and config -- so a lens fenced off
from the bot can use it without widening its reach.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

import pandas as pd

from . import config

_UA = {"User-Agent": "vivek5-scanner/1.0 (+market data, read-only)"}
_DEAD_STATUSES = (401, 403, 451)
_COLS = ["Open", "High", "Low", "Close", "Volume"]

HOSTS = {
    "binance_vision": "https://data-api.binance.vision",
    "binance": "https://api.binance.com",
    "bybit": "https://api.bybit.com",
    "coinbase": "https://api.exchange.coinbase.com",
}


def period_days(period: Optional[str]) -> Optional[int]:
    """yfinance-style period ("5y", "6mo", "5d", "max") -> days (None = all)."""
    p = str(period or "").strip().lower()
    if p in ("", "max"):
        return None
    for unit, mult in (("mo", 31), ("y", 366), ("d", 1), ("wk", 7)):
        if p.endswith(unit):
            try:
                return int(p[: -len(unit)]) * mult
            except ValueError:
                return None
    return None


class SourceDead(Exception):
    """The host refused us outright (geo/auth) -- stop asking it this run."""


def _get_json(url: str, timeout: float) -> object:
    req = urllib.request.Request(url, headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        if e.code in _DEAD_STATUSES:
            raise SourceDead(f"HTTP {e.code}") from e
        raise


# Interval spellings per venue. Daily is what the scan, the bot and the lens
# read; 4h feeds the display-only 4H plans (exchange 4h candles open at
# 00:00/04:00/... UTC -- exactly the epoch-anchored bins vivek's resampler
# cuts, so they pass through it unchanged). Coinbase has no 4h granularity.
_IV = {"binance": {"1d": "1d", "4h": "4h", "1h": "1h"},
       "bybit": {"1d": "D", "4h": "240", "1h": "60"},
       "coinbase": {"1d": 86400}}


def supports(venue: str, interval: str) -> bool:
    """Does this venue serve candles at `interval`? ("yahoo" is Yahoo's 1h leg,
    bucketed by the resampler, so it serves 4h too.) Coinbase has no 4h."""
    if venue == "yahoo":
        return True
    key = "binance" if venue in ("binance", "binance_vision") else venue
    return interval in _IV.get(key, {})


def _frame(rows: List[Tuple[int, float, float, float, float, float]], source: str,
           daily: bool = True) -> pd.DataFrame:
    """[(open_ms, o, h, l, c, quote_vol)] -> an ascending frame indexed by
    the bar's UTC open (tz-naive; a DAILY frame is normalised to the date),
    de-duplicated, non-positive closes dropped. `attrs['source']` names
    where it came from."""
    if not rows:
        return pd.DataFrame(columns=_COLS)
    df = pd.DataFrame(rows, columns=["t", *_COLS])
    ts = pd.to_datetime(df.pop("t"), unit="ms", utc=True).dt.tz_localize(None)
    df.index = ts.dt.normalize() if daily else ts
    df = df.astype(float)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[df["Close"] > 0]
    df.attrs["source"] = source
    return df


def _since_ms(days: Optional[int]) -> int:
    if not days:
        return 0
    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=int(days) + 2)
    return int(start.timestamp() * 1000)


# ── one fetcher per venue: symbol ("QNT") -> ascending rows ────────────────

def _binance(host: str, sym: str, days: Optional[int], timeout: float, source: str,
             interval: str = "1d") -> Optional[pd.DataFrame]:
    """Binance /api/v3/klines, paged FORWARD from startTime, 1000 per call.
    Row: [openTime, open, high, low, close, baseVol, closeTime, QUOTEVOL, ...].
    An unknown pair answers HTTP 400 -> None (not listed here)."""
    pair = f"{sym}USDT"
    start = _since_ms(days)
    out: list = []
    for _ in range(int(config.EXCHANGE_MAX_PAGES)):
        q = urllib.parse.urlencode({"symbol": pair, "interval": _IV["binance"][interval],
                                    "limit": 1000, "startTime": start})
        try:
            data = _get_json(f"{host}/api/v3/klines?{q}", timeout)
        except urllib.error.HTTPError as e:
            if e.code == 400:
                return None
            raise
        if not isinstance(data, list) or not data:
            break
        out.extend((int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[7]))
                   for k in data)
        if len(data) < 1000:
            break
        start = int(data[-1][0]) + 1
    return _frame(out, source, interval == "1d") if out else None


def _bybit(sym: str, days: Optional[int], timeout: float,
           interval: str = "1d") -> Optional[pd.DataFrame]:
    """Bybit v5 /market/kline (spot), paged BACKWARD from `end`, 1000 per call,
    newest first. Row: [start, open, high, low, close, volume, TURNOVER]."""
    host = HOSTS["bybit"]
    stop = _since_ms(days)
    end = None
    out: list = []
    for _ in range(int(config.EXCHANGE_MAX_PAGES)):
        params = {"category": "spot", "symbol": f"{sym}USDT",
                  "interval": _IV["bybit"][interval], "limit": 1000}
        if end is not None:
            params["end"] = end
        data = _get_json(f"{host}/v5/market/kline?{urllib.parse.urlencode(params)}", timeout)
        if not isinstance(data, dict) or data.get("retCode") not in (0, None):
            return None if not out else _frame(out, "bybit", interval == "1d")
        lst = ((data.get("result") or {}).get("list")) or []
        if not lst:
            break
        out.extend((int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[6]))
                   for k in lst)
        oldest = min(int(k[0]) for k in lst)
        if len(lst) < 1000 or oldest <= stop:
            break
        end = oldest - 1
    out = [r for r in out if r[0] >= stop] if stop else out
    return _frame(out, "bybit", interval == "1d") if out else None


def _coinbase(sym: str, days: Optional[int], timeout: float,
              interval: str = "1d") -> Optional[pd.DataFrame]:
    """Coinbase Exchange /products/<SYM>-USD/candles, 300 per call, paged
    BACKWARD. Row: [time_s, low, high, open, close, BASE volume] -- quote
    volume is approximated as close x base volume (Coinbase publishes no
    quote volume). An unknown product answers 404 -> None."""
    if interval not in _IV["coinbase"]:
        return None                  # no such granularity: the next venue / Yahoo
    host = HOSTS["coinbase"]
    now = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    horizon = int(days) + 2 if days else 365 * 12
    out: list = []
    end = now + dt.timedelta(days=1)
    pages = 0
    while pages < int(config.EXCHANGE_MAX_PAGES) * 4 and (now - end).days < horizon:
        start = end - dt.timedelta(days=300)
        q = urllib.parse.urlencode({"granularity": 86400, "start": start.isoformat(),
                                    "end": end.isoformat()})
        try:
            data = _get_json(f"{host}/products/{sym}-USD/candles?{q}", timeout)
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None if not out else _frame(out, "coinbase")
            raise
        pages += 1
        if not isinstance(data, list) or not data:
            break
        out.extend((int(k[0]) * 1000, float(k[3]), float(k[2]), float(k[1]), float(k[4]),
                    float(k[4]) * float(k[5])) for k in data)
        end = start
        time.sleep(float(config.EXCHANGE_COINBASE_PAUSE_S))
    return _frame(out, "coinbase") if out else None


def _fetch_one(source: str, sym: str, days: Optional[int], timeout: float,
               interval: str = "1d") -> Optional[pd.DataFrame]:
    if source in ("binance_vision", "binance"):
        return _binance(HOSTS[source], sym, days, timeout, source, interval)
    if source == "bybit":
        return _bybit(sym, days, timeout, interval)
    if source == "coinbase":
        return _coinbase(sym, days, timeout, interval)
    raise ValueError(f"unknown kline source {source!r}")


def same_coin(df: Optional[pd.DataFrame], ref: Optional[float],
              tol: Optional[float] = None) -> bool:
    """Is this frame the coin whose reference price is `ref`? Its latest
    close must sit within [1/(1+tol), 1+tol] x ref. No reference -> True
    (nothing to check against; the caller's other guards still apply)."""
    if df is None or not len(df):
        return False
    if ref is None or not (ref > 0):
        return True
    tol = float(config.CRYPTO_IDENTITY_TOL if tol is None else tol)
    try:
        last = float(df["Close"].iloc[-1])
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    if not (last > 0):
        return False
    ratio = last / float(ref)
    return 1.0 / (1.0 + tol) <= ratio <= 1.0 + tol


def bar_age_days(df: Optional[pd.DataFrame], now: Optional[dt.datetime] = None) -> Optional[int]:
    """Whole UTC days between the frame's newest bar and `now` (None when
    the frame is empty or its index is unreadable)."""
    if df is None or not len(df):
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        last = pd.Timestamp(df.index[-1])
        if last.tzinfo is not None:
            last = last.tz_convert("UTC").tz_localize(None)
        return max(0, (now.astimezone(dt.timezone.utc).date() - last.date()).days)
    except Exception:  # noqa: BLE001 - unreadable = unknown, never "fresh"
        return None


def _completed(df: pd.DataFrame, now: dt.datetime) -> pd.DataFrame:
    """The frame without its trailing FORMING daily bar(s) (the current UTC
    date or later: config.daily_bar_forming) -- the bars VIVEK grades once
    scan.py drops the forming one."""
    k = len(df)
    while k > 0 and config.daily_bar_forming("crypto", pd.Timestamp(df.index[k - 1]), now):
        k -= 1
    return df.iloc[:k]


def completed_bar_age_days(df: Optional[pd.DataFrame],
                           now: Optional[dt.datetime] = None) -> Optional[int]:
    """Whole UTC days between the frame's newest COMPLETED daily bar and `now`
    (bar_age_days reads the newest bar, which on a Yahoo frame is yfinance's
    live row). None when no bar is completed yet or the index is unreadable."""
    if df is None or not len(df):
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        return bar_age_days(_completed(df, now), now)
    except Exception:  # noqa: BLE001 - unreadable = unknown
        return None


def quantized(df: Optional[pd.DataFrame], now: Optional[dt.datetime] = None,
              bars: Optional[int] = None, min_distinct: Optional[int] = None) -> bool:
    """True when the last `bars` COMPLETED daily closes take fewer than
    `min_distinct` distinct values (config CRYPTO_YAHOO_QUANT_*): history
    rounded to a price grid coarser than the coin (Yahoo's 6 decimals on a
    sub-1e-5 coin) or frozen flat. False when fewer than `bars` completed
    bars exist -- too short to judge."""
    if df is None or not len(df):
        return False
    now = now or dt.datetime.now(dt.timezone.utc)
    bars = int(config.CRYPTO_YAHOO_QUANT_BARS if bars is None else bars)
    need = int(config.CRYPTO_YAHOO_QUANT_MIN_DISTINCT if min_distinct is None else min_distinct)
    if bars <= 0 or need <= 0:
        return False
    try:
        closes = pd.to_numeric(_completed(df, now)["Close"], errors="coerce").dropna()
    except Exception:  # noqa: BLE001 - unreadable = cannot judge
        return False
    if len(closes) < bars:
        return False
    return int(closes.iloc[-bars:].nunique()) < need


def anchor_ok(df: Optional[pd.DataFrame], anchor, tol: Optional[float] = None) -> bool:
    """Does this frame reproduce a price already RECORDED for the coin?
    `anchor` = (YYYY-MM-DD, price): the frame's close on that date must sit
    within [1/(1+tol), 1+tol] x price (tol default CRYPTO_ANCHOR_TOL). A frame
    without that date cannot vouch for itself and fails."""
    if df is None or not len(df) or not anchor:
        return False
    day, price = anchor
    try:
        price = float(price)
        idx = pd.DatetimeIndex(df.index)
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        hit = df.loc[idx.normalize() == pd.Timestamp(str(day)).normalize(), "Close"]
        if not len(hit) or not (price > 0):
            return False
        close = float(hit.iloc[-1])
    except Exception:  # noqa: BLE001 - unreadable = cannot vouch
        return False
    tol = float(config.CRYPTO_ANCHOR_TOL if tol is None else tol)
    return close > 0 and 1.0 / (1.0 + tol) <= close / price <= 1.0 + tol


def identity_of(df, ref, anchor, ref_tol=None, require=False) -> Optional[str]:
    """How this frame proves it is the coin: "anchor", "ref", "none" (no
    evidence, allowed), or None (refused). An anchor wins over a reference:
    it cannot be fooled by a real move since the reference was taken."""
    if anchor:
        return "anchor" if anchor_ok(df, anchor) else None
    if ref is not None and ref > 0:
        return "ref" if same_coin(df, ref, ref_tol) else None
    return None if require else "none"


def download_klines(symbols: List[str], *, days: Optional[int] = None,
                    sources: Optional[Tuple[str, ...]] = None,
                    interval: str = "1d",
                    ref_prices: Optional[Dict[str, float]] = None,
                    ref_tol: Optional[float] = None,
                    anchors: Optional[Dict[str, tuple]] = None,
                    require_identity: bool = False,
                    now: Optional[dt.datetime] = None) -> Tuple[Dict[str, pd.DataFrame], dict]:
    """{symbol: daily frame} from the first source that lists each coin, plus
    a report: which sources answered, which were dead (and why), how many
    coins each supplied, and which coins no exchange had (the caller's
    fallback list). `days=None` = full history.

    A venue's frame is refused for a coin, and the next venue asked, when
    (1) its newest bar is older than EXCHANGE_MAX_BAR_AGE_DAYS -- a delisted
    pair's frozen klines, which Binance's mirror keeps serving -- reported as
    `stale_rejected`; or (2) it is not THIS coin -- a same-ticker stranger --
    reported as `identity_rejected`. Identity is proved by a history ANCHOR
    when the caller has one (`anchors[sym]` = (date, recorded price):
    anchor_ok), else by the latest close against a current reference price
    (`ref_prices`, `ref_tol`); with neither the frame is accepted unchecked
    unless `require_identity`. Each accepted frame records how in
    attrs["identity"]: "anchor" | "ref" | "none"."""
    sources = tuple(sources or config.EXCHANGE_KLINE_SOURCES)
    timeout = float(config.EXCHANGE_HTTP_TIMEOUT)
    max_age = int(getattr(config, "EXCHANGE_MAX_BAR_AGE_DAYS", 0) or 0)
    now = now or dt.datetime.now(dt.timezone.utc)
    dead: Dict[str, str] = {}
    errors: Dict[str, int] = {}
    frames: Dict[str, pd.DataFrame] = {}
    refs = {str(k).upper(): v for k, v in (ref_prices or {}).items()}
    anch = {str(k).upper(): v for k, v in (anchors or {}).items() if v}
    rejected: Dict[str, List[str]] = {}
    stale: Dict[str, List[str]] = {}

    def one(sym: str, probe: bool = False) -> Tuple[str, Optional[pd.DataFrame]]:
        for src in sources:
            if src in dead:
                continue
            try:
                df = _fetch_one(src, sym, days, timeout, interval)
            except SourceDead as e:
                dead.setdefault(src, str(e))
                continue
            except Exception as e:  # noqa: BLE001 - one coin, one venue: try the next
                errors[src] = errors.get(src, 0) + 1
                # The PROBE coin is the universe's first (BTC: listed on every
                # venue), so a network error there is the venue, not the coin
                # -- drop it now rather than let 200 coins each wait out its
                # timeout.
                if probe or errors[src] >= int(config.EXCHANGE_DEAD_AFTER_ERRORS):
                    dead.setdefault(src, f"{type(e).__name__}: {str(e)[:80]}")
                continue
            if df is not None and len(df):
                age = bar_age_days(df, now)
                if max_age and (age is None or age > max_age):
                    # Listed here once; not trading here now (delisted/halted).
                    stale.setdefault(sym, []).append(src)
                    continue
                how = identity_of(df, refs.get(sym), anch.get(sym), ref_tol, require_identity)
                if how is None:
                    # Listed here, but not THIS coin (a same-ticker token).
                    rejected.setdefault(sym, []).append(src)
                    continue
                df.attrs["identity"] = how
                return sym, df
        return sym, None

    # Probe serially on the FIRST coin so a dead venue is known before the
    # thread pool fans out and asks it 200 times.
    todo = list(dict.fromkeys(s.upper() for s in symbols if s))
    if todo:
        s0, f0 = one(todo[0], probe=True)
        if f0 is not None:
            frames[s0] = f0
    with ThreadPoolExecutor(max_workers=int(config.EXCHANGE_THREADS)) as pool:
        for sym, df in pool.map(one, todo[1:]):
            if df is not None:
                frames[sym] = df
    by_source: Dict[str, int] = {}
    for df in frames.values():
        by_source[df.attrs.get("source", "?")] = by_source.get(df.attrs.get("source", "?"), 0) + 1
    report = {
        "sources_tried": list(sources),
        "dead": dead,
        "errors": errors,
        "by_source": by_source,
        "missing": sorted(s for s in todo if s not in frames),
        "identity_rejected": dict(sorted(rejected.items())),
        "stale_rejected": dict(sorted(stale.items())),
    }
    return frames, report
