"""Exchange daily candles for crypto -- public, KEYLESS market-data endpoints.

WHY THIS EXISTS (2026-09-28). Every bar in the scanner came from Yahoo, crypto
included, and Yahoo's crypto series is an AGGREGATED feed, not an exchange's
candles. The first real IGNITION run showed what that costs: at 02:00 UTC on
28 Sep Yahoo still had no usable 27 Sep bar (the lens screened a day late,
on a setup where the first day is everything), its QNT print sat ~20% under
Binance's at the same hour, and 64 of 201 coins had no data at all. An
exchange's daily kline closes at exactly 00:00 UTC and is served the moment
it does.

WHAT IT IS NOT. It holds no credentials and places nothing -- these are the
public market-data endpoints. It does not replace scanner/data.py for anyone
who has not asked: the IGNITION lens opts in (config IGNITION_DATA_SOURCE);
the VIVEK scan and the paper bot still read Yahoo, because switching THEIR
source moves the prices the bot marks and stops against -- a trade change,
and the owner's call.

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


def _frame(rows: List[Tuple[int, float, float, float, float, float]], source: str) -> pd.DataFrame:
    """[(open_ms, o, h, l, c, quote_vol)] -> an ascending daily frame indexed
    by the UTC DATE (tz-naive midnight), de-duplicated, non-positive closes
    dropped. `attrs['source']` names where it came from."""
    if not rows:
        return pd.DataFrame(columns=_COLS)
    df = pd.DataFrame(rows, columns=["t", *_COLS])
    df.index = pd.to_datetime(df.pop("t"), unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
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

def _binance(host: str, sym: str, days: Optional[int], timeout: float, source: str) -> Optional[pd.DataFrame]:
    """Binance /api/v3/klines, paged FORWARD from startTime, 1000 per call.
    Row: [openTime, open, high, low, close, baseVol, closeTime, QUOTEVOL, ...].
    An unknown pair answers HTTP 400 -> None (not listed here)."""
    pair = f"{sym}USDT"
    start = _since_ms(days)
    out: list = []
    for _ in range(int(config.EXCHANGE_MAX_PAGES)):
        q = urllib.parse.urlencode({"symbol": pair, "interval": "1d", "limit": 1000,
                                    "startTime": start})
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
    return _frame(out, source) if out else None


def _bybit(sym: str, days: Optional[int], timeout: float) -> Optional[pd.DataFrame]:
    """Bybit v5 /market/kline (spot), paged BACKWARD from `end`, 1000 per call,
    newest first. Row: [start, open, high, low, close, volume, TURNOVER]."""
    host = HOSTS["bybit"]
    stop = _since_ms(days)
    end = None
    out: list = []
    for _ in range(int(config.EXCHANGE_MAX_PAGES)):
        params = {"category": "spot", "symbol": f"{sym}USDT", "interval": "D", "limit": 1000}
        if end is not None:
            params["end"] = end
        data = _get_json(f"{host}/v5/market/kline?{urllib.parse.urlencode(params)}", timeout)
        if not isinstance(data, dict) or data.get("retCode") not in (0, None):
            return None if not out else _frame(out, "bybit")
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
    return _frame(out, "bybit") if out else None


def _coinbase(sym: str, days: Optional[int], timeout: float) -> Optional[pd.DataFrame]:
    """Coinbase Exchange /products/<SYM>-USD/candles, 300 per call, paged
    BACKWARD. Row: [time_s, low, high, open, close, BASE volume] -- quote
    volume is approximated as close x base volume (Coinbase publishes no
    quote volume). An unknown product answers 404 -> None."""
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


def _fetch_one(source: str, sym: str, days: Optional[int], timeout: float) -> Optional[pd.DataFrame]:
    if source in ("binance_vision", "binance"):
        return _binance(HOSTS[source], sym, days, timeout, source)
    if source == "bybit":
        return _bybit(sym, days, timeout)
    if source == "coinbase":
        return _coinbase(sym, days, timeout)
    raise ValueError(f"unknown kline source {source!r}")


def download_klines(symbols: List[str], *, days: Optional[int] = None,
                    sources: Optional[Tuple[str, ...]] = None) -> Tuple[Dict[str, pd.DataFrame], dict]:
    """{symbol: daily frame} from the first source that lists each coin, plus
    a report: which sources answered, which were dead (and why), how many
    coins each supplied, and which coins no exchange had (the caller's
    fallback list). `days=None` = full history."""
    sources = tuple(sources or config.EXCHANGE_KLINE_SOURCES)
    timeout = float(config.EXCHANGE_HTTP_TIMEOUT)
    dead: Dict[str, str] = {}
    errors: Dict[str, int] = {}
    frames: Dict[str, pd.DataFrame] = {}

    def one(sym: str, probe: bool = False) -> Tuple[str, Optional[pd.DataFrame]]:
        for src in sources:
            if src in dead:
                continue
            try:
                df = _fetch_one(src, sym, days, timeout)
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
    }
    return frames, report
