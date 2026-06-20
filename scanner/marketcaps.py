"""Persistent market-cap cache.

Yahoo throttles its market-cap / crumb endpoint from cloud IPs (GitHub Actions)
right after a heavy scan — by alert time every request returns nothing. So we
do NOT fetch caps inline at alert time. Instead:

  1. This module keeps a persistent cache in data/market_caps.json, keyed by
     "<market>:<symbol>" -> {"mcap": float, "ts": iso8601}.
  2. It is refreshed from a FRESH IP (before the scan's ~2,000-ticker download
     barrage) via Yahoo's bulk quote endpoint, with retries and pacing.
  3. notify.py reads caps from this cache — no live fetch when alerting.

Market cap is a slow-moving fundamental, so a cache that's a few days old is
fine for a "<750M" bucket. Partial failures never wipe prior values.

    python -m scanner.marketcaps          # refresh stale/missing caps for A+/A signals
    python -m scanner.marketcaps --all     # refresh every A+/A signal regardless of age
"""

import argparse
import datetime as dt
import json
import pathlib
import time

ROOT       = pathlib.Path(__file__).resolve().parents[1]
CACHE_FILE = ROOT / "data" / "market_caps.json"

# Scan outputs we pull signal symbols from: (market_key, relative_path)
_SCAN_FILES = [
    ("asx",    "public/data/asx.json"),
    ("asx",    "public/data/asx_reversal.json"),
    ("asx",    "public/data/asx_spec.json"),
    ("nasdaq", "public/data/nasdaq.json"),
    ("nasdaq", "public/data/nasdaq_reversal.json"),
    ("nasdaq", "public/data/nasdaq_spec.json"),
]

# Only cache caps for tradeable grades — that's all the alerts ever show.
_CACHE_GRADES = {"A+", "A"}
_MAX_AGE_DAYS = 4          # refresh entries older than this
_CHUNK        = 100        # symbols per bulk quote request
_RETRIES      = 3


def _yf_sym(market: str, symbol: str) -> str:
    return symbol + ".AX" if market == "asx" else symbol


def _key(market: str, symbol: str) -> str:
    return f"{market}:{symbol}"


# ── Cache I/O ─────────────────────────────────────────────────────────────────

def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))


def mcap_for(cache: dict, market: str, symbol: str) -> float:
    """Look up a cached market cap (raw float), or 0.0 if absent."""
    ent = cache.get(_key(market, symbol))
    if ent and ent.get("mcap"):
        try:
            return float(ent["mcap"])
        except Exception:
            return 0.0
    return 0.0


# ── Signal universe ───────────────────────────────────────────────────────────

def _signal_symbols() -> dict[str, set]:
    """Return {market: {symbol, ...}} of A+/A symbols across the latest scans."""
    out: dict[str, set] = {"asx": set(), "nasdaq": set()}
    for market, rel in _SCAN_FILES:
        path = ROOT / rel
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        for sig in data.get("results", []):
            if sig.get("grade") in _CACHE_GRADES and sig.get("symbol"):
                out[market].add(sig["symbol"])
    return out


# ── Yahoo bulk fetch ──────────────────────────────────────────────────────────

def _fetch_bulk_once(yf_syms: list[str]) -> dict[str, float]:
    """One bulk quote request per _CHUNK symbols. Returns {yf_sym: market_cap}."""
    from yfinance.data import YfData
    from yfinance.const import _QUERY1_URL_
    yfd = YfData()
    out: dict[str, float] = {}
    for i in range(0, len(yf_syms), _CHUNK):
        chunk = yf_syms[i:i + _CHUNK]
        params = {"symbols": ",".join(chunk), "formatted": "false",
                  "lang": "en-US", "region": "US"}
        try:
            res = yfd.get_raw_json(f"{_QUERY1_URL_}/v7/finance/quote?", params=params)
        except Exception:
            res = None
        for item in (res or {}).get("quoteResponse", {}).get("result", []):
            mc = item.get("marketCap")
            if mc:
                out[item.get("symbol", "")] = float(mc)
        time.sleep(1.0)   # gentle pacing between chunks
    return out


def _fetch_with_retries(yf_syms: list[str]) -> dict[str, float]:
    """Fetch caps, retrying the symbols still missing with back-off."""
    remaining = list(yf_syms)
    got: dict[str, float] = {}
    for attempt in range(_RETRIES):
        if not remaining:
            break
        got.update(_fetch_bulk_once(remaining))
        remaining = [s for s in yf_syms if s not in got]
        if remaining and attempt < _RETRIES - 1:
            time.sleep(5 * (attempt + 1))   # 5s, 10s back-off on throttle
    return got


# ── Refresh ───────────────────────────────────────────────────────────────────

def _stale(entry: dict, now: dt.datetime) -> bool:
    ts = entry.get("ts")
    if not ts:
        return True
    try:
        age = now - dt.datetime.fromisoformat(ts)
        return age > dt.timedelta(days=_MAX_AGE_DAYS)
    except Exception:
        return True


def refresh(only_stale: bool = True) -> dict:
    now      = dt.datetime.now(dt.timezone.utc)
    cache    = load_cache()
    universe = _signal_symbols()
    total_new = 0

    for market, symbols in universe.items():
        # Which symbols need a fetch?
        targets = [
            s for s in symbols
            if not only_stale or _stale(cache.get(_key(market, s), {}), now)
        ]
        if not targets:
            print(f"  marketcaps: {market.upper()} — {len(symbols)} signals, all cached & fresh")
            continue

        yf_map = {_yf_sym(market, s): s for s in targets}
        print(f"  marketcaps: {market.upper()} — fetching {len(yf_map)} caps "
              f"({len(symbols)} signals total) ...")
        got = _fetch_with_retries(list(yf_map))
        for ysym, mc in got.items():
            plain = yf_map.get(ysym)
            if plain:
                cache[_key(market, plain)] = {"mcap": mc, "ts": now.isoformat(timespec="seconds")}
        total_new += len(got)
        miss = len(yf_map) - len(got)
        print(f"  marketcaps: {market.upper()} — got {len(got)}, missed {miss}")

    save_cache(cache)
    print(f"  marketcaps: cache now holds {len(cache)} symbols ({total_new} refreshed)")
    return cache


def main() -> None:
    ap = argparse.ArgumentParser(description="Refresh the market-cap cache")
    ap.add_argument("--all", action="store_true",
                    help="refresh every A+/A signal regardless of cache age")
    args = ap.parse_args()
    refresh(only_stale=not args.all)


if __name__ == "__main__":
    main()
