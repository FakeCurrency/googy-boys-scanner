"""Persistent market-cap cache.

Yahoo throttles its market-cap / crumb endpoint from cloud IPs (GitHub Actions)
right after a heavy scan — by alert time every request returns nothing. So we
do NOT fetch caps inline at alert time. Instead:

  1. This module keeps a persistent cache in data/market_caps.json, keyed by
     "<market>:<symbol>" -> {"mcap": float, "ts": iso8601}.
  2. It is refreshed from a FRESH IP (before the scan's ~2,000-ticker download
     barrage) via Yahoo's bulk quote endpoint, with retries and pacing.
  3. Readers: scan.published() stamps each published row's `mcap` + the date
     it was fetched (`mcap_asof`), the deck reads the public mirror, and the
     IGNITION lens reads load_cache(). (notify.py, once named here, was
     deleted 2026-07-20.)

Market cap is a slow-moving fundamental, so a cache that's a few days old is
fine for a "<750M" bucket. Partial failures never wipe prior values.

REFINE200 #157: the refresh used to cover only the previous scan's A+/A, so a
B+ or WATCH row on the deck could show a cap 100+ days old. It now covers
EVERY published row whose cap is missing or older than MAX_AGE_DAYS, best
grades first, then missing, then oldest -- at most MARKETCAP_REFRESH_MAX
symbols a run, both markets in ONE batched fetch.

    python -m scanner.marketcaps          # refresh missing/stale caps for published rows
    python -m scanner.marketcaps --all     # refresh published rows regardless of age (still capped)
"""

import argparse
import datetime as dt
import json
import pathlib
import time

from . import config

ROOT       = pathlib.Path(__file__).resolve().parents[1]
CACHE_FILE = ROOT / "data" / "market_caps.json"
# A web-served copy so the dashboard (public/) can show caps inline. The canonical
# cache stays in data/; this mirror is committed alongside the scan JSON.
PUBLIC_FILE = ROOT / "public" / "data" / "market_caps.json"

# Scan outputs we pull signal symbols from: (market_key, relative_path).
# Trimmed 2026-08-15: asx.json / nasdaq.json / *_reversal.json have not been
# published since the reversal lens retired — four of eight entries were dead
# stat() calls every refresh (REFINEMENTS #93 first flagged it). The two lens
# files that actually exist stay.
_SCAN_FILES = [
    ("asx",    "public/data/asx_spec.json"),
    ("asx",    "public/data/asx_vivek.json"),
    ("nasdaq", "public/data/nasdaq_spec.json"),
    ("nasdaq", "public/data/nasdaq_vivek.json"),
]

# Refresh order: tradeable grades first (the bot's and the digest's names),
# then the rest of the deck; an unknown grade last.
_GRADE_RANK   = {"A+": 0, "A": 1, "B+": 2, "B": 2, "WATCH": 3, "C": 3}
MAX_AGE_DAYS  = 4          # refresh entries older than this
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
    # TOP100 #64 — both writes were non-atomic, and neither named an encoding,
    # so a local Windows run wrote cp1252. Routed through output.write_json for
    # the temp+os.replace swap and a pinned utf-8/LF, matching sectorcache.
    from .output import write_json
    kw = dict(sort_keys=True)
    write_json(CACHE_FILE, cache, **kw)
    # Mirror to the web-served folder so the dashboard can read caps directly.
    try:
        write_json(PUBLIC_FILE, cache, **kw)
    except Exception:
        pass


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

def _published_rows() -> dict[str, dict[str, int]]:
    """{market: {symbol: best grade rank}} for EVERY row in the latest scans
    (REFINE200 #157 -- this was A+/A only, so the rest of the deck's caps
    were never refreshed)."""
    out: dict[str, dict[str, int]] = {"asx": {}, "nasdaq": {}}
    for market, rel in _SCAN_FILES:
        path = ROOT / rel
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for sig in data.get("results", []):
            sym = sig.get("symbol")
            if not sym:
                continue
            rank = _GRADE_RANK.get(sig.get("grade"), 9)
            out[market][sym] = min(rank, out[market].get(sym, 9))
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


def fetch_caps(yf_syms: list[str]) -> dict[str, float]:
    """Fetch caps, retrying the symbols still missing with back-off. Saves
    nothing: refresh() is the cache's one writer (the IGNITION lens reads)."""
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

def _age_days(entry: dict | None, now: dt.datetime) -> float:
    """Days since the entry was fetched; inf when missing or unreadable."""
    ts = (entry or {}).get("ts")
    if not ts:
        return float("inf")
    try:
        return (now - dt.datetime.fromisoformat(ts)).total_seconds() / 86400.0
    except Exception:
        return float("inf")


def _stale(entry: dict, now: dt.datetime) -> bool:
    return _age_days(entry, now) > MAX_AGE_DAYS


def refresh_targets(rows: dict[str, dict[str, int]], cache: dict, now: dt.datetime,
                    only_stale: bool = True, limit: int | None = None) -> list[tuple[str, str]]:
    """[(market, symbol)] to fetch this run, in priority order and capped:
    best grade first, then missing before stale, then oldest first. Pure."""
    cap = int(config.MARKETCAP_REFRESH_MAX if limit is None else limit)
    ranked = []
    for market, syms in rows.items():
        for sym, rank in syms.items():
            age = _age_days(cache.get(_key(market, sym)), now)
            if only_stale and age <= MAX_AGE_DAYS:
                continue
            ranked.append((rank, -age, market, sym))
    ranked.sort()
    return [(m, s) for _, _, m, s in ranked[:max(0, cap)]]


def refresh(only_stale: bool = True) -> dict:
    now      = dt.datetime.now(dt.timezone.utc)
    cache    = load_cache()
    rows     = _published_rows()
    targets  = refresh_targets(rows, cache, now, only_stale=only_stale)
    total    = sum(len(v) for v in rows.values())
    if not targets:
        print(f"  marketcaps: {total} published rows, all cached & fresh")
        return cache

    # ONE batched fetch for both markets: fetch_caps chunks it 100 symbols a
    # bulk request, so the Yahoo budget is bounded by MARKETCAP_REFRESH_MAX.
    yf_map = {_yf_sym(m, s): (m, s) for m, s in targets}
    print(f"  marketcaps: fetching {len(yf_map)} caps ({total} published rows, "
          f"cap {config.MARKETCAP_REFRESH_MAX} a run) ...")
    got = fetch_caps(list(yf_map))
    stamp = now.isoformat(timespec="seconds")
    for ysym, mc in got.items():
        hit = yf_map.get(ysym)
        if hit:
            cache[_key(*hit)] = {"mcap": mc, "ts": stamp}
    print(f"  marketcaps: got {len(got)}, missed {len(yf_map) - len(got)}")

    save_cache(cache)
    print(f"  marketcaps: cache now holds {len(cache)} symbols ({len(got)} refreshed)")
    return cache


def main() -> None:
    ap = argparse.ArgumentParser(description="Refresh the market-cap cache")
    ap.add_argument("--all", action="store_true",
                    help="refresh published rows regardless of age (still capped)")
    args = ap.parse_args()
    refresh(only_stale=not args.all)


if __name__ == "__main__":
    main()
