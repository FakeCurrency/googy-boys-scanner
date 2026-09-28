"""Per-market ticker universes.

Source of truth is a bundled CSV (``data_universe/<market>_tickers.csv`` with
``symbol,name`` columns). Edit those files to grow or trim a universe — the
liquidity filter prunes anything too thin at scan time, so a generous list is
fine. If a CSV is missing, NASDAQ can fall back to the official symbol file.
"""

import csv
import datetime as dt
import io
import json
import os
import pathlib
import re
import time
import urllib.request

from . import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
UNIVERSE_DIR = ROOT / "data_universe"
# Last-good universe cache (2026-07-26): one flaky directory fetch dropped a
# Saturday ASX scan from ~2,000 names to the 94-name bundled CSV — silently.
# Every successful full fetch is now snapshotted here (committed by scan.yml
# alongside market_caps.json), and a failed fetch falls back to this snapshot
# BEFORE the tiny bundled list. Sector metadata rides along, so a degraded
# run keeps sectors too.
UNIVERSE_CACHE_DIR = ROOT / "data" / "universe_cache"
# A snapshot smaller than this is itself a degraded list — never cache it.
_CACHE_MIN = {"asx": 400, "nasdaq": 400, "crypto": 40}

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
ASX_LISTED_URL = "https://www.asx.com.au/asx/research/ASXListedCompanies.csv"
# CoinGecko's /coins/markets serves at most 250 rows per page. Asking for more
# is NOT an error: it silently answers with its DEFAULT page of 100. That is
# exactly what happened when CRYPTO_UNIVERSE_SIZE went 100 -> 200 (owner,
# 2026-09-21): per_page became 260, the universe SHRANK from 101 names to 86
# on the first run after the change, and the "top 200" the owner asked for
# was a top ~100 from then until 2026-09-28 (found chasing the QNT move --
# most ignitions of that shape happen in ranks 100-250, the band that was
# being dropped). So pages are fetched at the cap and walked until the target
# count of TRADEABLE coins is reached: stablecoins and wrapped tokens are
# filtered OUT of each response, so N rows never yield N tradeable coins.
COINGECKO_PER_PAGE_MAX = 250
COINGECKO_MAX_PAGES = 4          # 1,000 rows: a hard stop, never a loop


def coingecko_url(page: int, per_page: int = COINGECKO_PER_PAGE_MAX) -> str:
    """One page of the market-cap-ordered coin list. per_page is CLAMPED to
    CoinGecko's cap -- a larger value is the silent 100-row fallback above."""
    per_page = max(1, min(int(per_page), COINGECKO_PER_PAGE_MAX))
    return ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
            f"&order=market_cap_desc&per_page={per_page}"
            f"&page={int(page)}&sparkline=false")


# Page 1, kept under its old name: _fetch_failed and the logs name the host
# through it, and it is the one URL every fetch starts from.
COINGECKO_URL = coingecko_url(1)

# Stablecoins / wrapped-pegged tokens to skip (they don't trend, so the 200-SMA
# reaction system is meaningless on them — e.g. a "long" on a $1 peg is noise).
CRYPTO_SKIP = {
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "USDD", "FDUSD", "PYUSD", "USDE", "USDS",
    "GUSD", "LUSD", "USDP", "EURT", "EURC", "USD0", "USDL", "USDX", "CRVUSD",
    "RLUSD", "GHO", "USDG", "USD1", "SUSDE", "SUSDS", "BUIDL", "USDY", "EURS",
    "WBTC", "WETH", "WEETH", "WSTETH", "STETH", "RETH", "CBETH", "WBETH", "BSC-USD",
    # newer wrapped/staked BTC-ETH derivatives — duplicates of the underlying
    "CBBTC", "TBTC", "SOLVBTC", "LBTC", "EZETH", "RSETH", "METH", "CMETH",
    "LSETH", "SWETH", "OSETH", "JITOSOL", "MSOL", "BNSOL", "JUPSOL",
    # FRAX left this list 2026-09-28: CoinGecko's FRAX is now the floating
    # Frax governance token ("Frax (prev. FXS)"); the old stablecoin is
    # "Legacy Frax Dollar" (caught by name) and frxUSD (the USD suffix rule).
    # 2026-09-28: the pagination fix put ranks ~100-250 back in the universe,
    # and that band carries pegs the <X>USD rule cannot see -- non-dollar
    # fiat stablecoins (EURCV graded A+ on the first exchange-data dry run,
    # i.e. a long on EUR/USD dressed as a crypto setup) and tokenised
    # money-market / T-bill / CLO funds whose price is a NAV that only
    # accrues. Same reason as every line above: no trend to react to.
    "A7A5", "XSGD", "ZCHF", "VCHF", "VEUR", "AEUR", "GYEN", "BRZ", "BRLA",
    "TRYB", "IDRT", "BIDR", "MXNB", "CADC", "QCAD", "XIDR", "EUTBL", "USTBL",
    "JAAA", "JTRSY", "OUSG", "USTB", "USYC", "BENJI", "TBILL", "STBT", "USCC",
    "USR",
    # Found by the dry run's behaviour check (1y high/low x1.00-x1.01) or its
    # identity check, not by any name rule: Figure's YLDS, Tether's USAT, the
    # yen stablecoin JPYC.
    "YLDS", "USAT", "JPYC",
}

# Name words that mark a peg or a tokenised cash/bond fund whatever its
# ticker (CoinGecko's `name`, whole words, case-insensitive): "Resolv USR",
# "Global Dollar", "United Stables" (U -- graded A on the first exchange-data
# dry run), "Spiko Amundi Overnight Swap Fund (EUR)", "Circle USYC".
# Deliberately narrow -- "Fund", "Gold" or a singular "Stable" (the STABLE
# chain token, which floats) would catch coins that do trend -- so only
# words that cannot describe a free-floating coin are here.
_PEG_NAME = re.compile(
    r"\b(stablecoins?|stables|usd|dollar|eur|euro|treasury|treasuries|"
    r"t-?bills?|money market|government (securities|bonds?)|CLO)\b",
    re.IGNORECASE)


def _is_stable(sym: str, name: str = "") -> bool:
    """True for pegged stablecoins (and the explicit wrapped-token list).

    Beyond the explicit set, any ``<X>USD`` ticker is treated as a USD peg
    (RLUSD, FDUSD, crvUSD, …) so a newly-listed dollar stablecoin is skipped
    automatically rather than waiting to be hand-added after it's traded once.
    ``USD<X>`` (USDF, USDM, ...) and ``EUR<X>`` (EURCV, EURR, EURQ, ...)
    tickers are pegs by the same reasoning (2026-09-28), and when the coin's
    NAME is known a stablecoin / T-bill / treasury / CLO phrase marks one too.
    Gold and silver tokens (PAXG, XAUT, KAU, KAG) are NOT pegs here: the metal
    trends, and they have been scanned on purpose since the start.
    """
    s = (sym or "").upper()
    if s in CRYPTO_SKIP or s.endswith("USD") or s.startswith(("USD", "EUR")):
        return True
    return bool(name) and bool(_PEG_NAME.search(name))

_BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FibScanner/1.0)"}

# asx.com.au stopped serving the directory CSV to the honest
# "(compatible; FibScanner/1.0)" agent around 2026-07-25 - the endpoint is
# alive and returns the file to an ordinary browser, so a WAF refusing a
# bot-shaped user-agent is the likeliest cause. This is the full profile a
# real browser sends. NASDAQ (no headers at all) and CoinGecko (the honest
# agent above) both still work, so neither is touched.
_ASX_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "text/csv,application/csv,text/plain,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
    "Referer": "https://www.asx.com.au/",
}


def _http_get(url: str, timeout: int, headers: dict | None = None, attempts: int = 3) -> str:
    """GET with retries + backoff (5s, 10s). Directory endpoints flake, and a
    single miss must not collapse the scan universe. Raises on final failure
    so callers keep their existing except-and-fallback shape."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001 - any network error retries
            last = exc
            if i < attempts - 1:
                time.sleep(5 * (i + 1))
    raise last if last else RuntimeError("fetch failed")


# ── last-good universe cache ─────────────────────────────────────────────────

def _cache_path(market_key: str) -> pathlib.Path:
    return UNIVERSE_CACHE_DIR / f"{market_key}.json"


def _save_universe_cache(market_key: str, items: list[dict]) -> None:
    """Snapshot a SUCCESSFUL full fetch (atomic write; degraded lists refused)."""
    try:
        if len(items) < _CACHE_MIN.get(market_key, 400):
            return
        UNIVERSE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "saved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "market": market_key,
            "count": len(items),
            "items": items,
        })
        tmp = _cache_path(market_key).with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, _cache_path(market_key))
    except Exception:
        pass  # the cache is safety net, never a failure source


def _load_universe_cache(market_key: str) -> list[dict]:
    try:
        data = json.loads(_cache_path(market_key).read_text(encoding="utf-8"))
        items = data.get("items") or []
        if isinstance(items, list) and len(items) >= _CACHE_MIN.get(market_key, 400):
            return items
    except Exception:
        pass
    return []


def _from_csv(path: pathlib.Path, suffix: str) -> list[dict]:
    items: list[dict] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            name = (row.get("name") or symbol).strip()
            if suffix == "-USD" and _is_stable(symbol, name):    # crypto fallback list: drop pegs too
                continue
            sector = (row.get("sector") or "").strip()
            items.append({"symbol": symbol, "name": name, "sector": sector,
                          "yf": symbol + suffix})
    return items


def _pretty(name: str) -> str:
    """ASX names come in ALL CAPS; title-case them for display."""
    return name.strip().title()


def _fetch_failed(market_key: str, url: str, exc: Exception) -> list[dict]:
    """Log WHY a directory fetch failed, then hand back an empty list.

    The callers all swallowed the exception, so a source that dies (endpoint
    moved, WAF starts refusing the scanner's user-agent, TLS change) looked
    exactly like a source that is merely flaky: the cache fallback covered it
    and nothing anywhere said which one it was. Printing the reason costs
    nothing and turns the next failure into a diagnosis instead of a guess.
    ASCII only - Windows consoles are cp1252.
    """
    host = url.split("/")[2] if "://" in url else url
    print(f"  universe: {market_key} directory fetch FAILED from {host} - "
          f"{type(exc).__name__}: {str(exc)[:160]}", flush=True)
    return []


def _fetch_asx_listed(suffix: str) -> list[dict]:
    """Fetch the entire ASX-listed universe from the official directory CSV.

    The file has a few preamble lines, then rows of: "Company name","Code","GICS".
    """
    try:
        text = _http_get(ASX_LISTED_URL, timeout=45, headers=_ASX_HEADERS)
    except Exception:  # noqa: BLE001 - one retry on the old profile, then cache
        # The browser profile is a GUESS at why the WAF refuses us. If the guess
        # is wrong, try the header set that worked historically before dropping
        # all the way to a frozen cache - a wrong diagnosis must not cost us a
        # source that was merely having a bad minute. ASCII only (cp1252).
        print("  universe: asx fetch with browser headers failed - "
              "retrying on the legacy agent", flush=True)
        try:
            text = _http_get(ASX_LISTED_URL, timeout=45,
                             headers=_BROWSER_HEADERS, attempts=1)
        except Exception as exc:  # noqa: BLE001 - logged, then falls back to cache
            return _fetch_failed("asx", ASX_LISTED_URL, exc)

    items: list[dict] = []
    seen: set[str] = set()
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        name = row[0].strip()
        code = row[1].strip().upper()
        sector = row[2].strip() if len(row) > 2 else ""
        if not code or not code.isalnum() or len(code) > 5:
            continue
        if code in ("ASX CODE", "CODE") or "COMPANY NAME" in name.upper():
            continue
        if "ASX LISTED" in name.upper():
            continue
        if code in seen:
            continue
        seen.add(code)
        items.append({"symbol": code, "name": _pretty(name), "sector": sector,
                      "yf": code + suffix})
    return items


def _fetch_nasdaq_listed(suffix: str, tiers: str = "Q") -> list[dict]:
    """Live NASDAQ-listed symbol directory (pipe-delimited, free, no auth).

    ``tiers`` filters by Market Category: Q = Global Select (the most liquid
    ~1,500 names — the default scanning universe), G = Global Market,
    S = Capital Market. Pass "QGS" for everything (~3,400)."""
    try:
        text = _http_get(NASDAQ_LISTED_URL, timeout=30)
    except Exception as exc:  # noqa: BLE001 - logged, then falls back to cache
        return _fetch_failed("nasdaq", NASDAQ_LISTED_URL, exc)

    items: list[dict] = []
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    for row in reader:
        symbol = (row.get("Symbol") or "").strip().upper()
        name = (row.get("Security Name") or symbol).strip()
        etf = (row.get("ETF") or "").strip().upper()
        test = (row.get("Test Issue") or "").strip().upper()
        tier = (row.get("Market Category") or "").strip().upper()
        fin = (row.get("Financial Status") or "N").strip().upper()
        # Skip ETFs, test issues, deficient/delinquent/bankrupt listings,
        # off-tier names, non-common symbols, and the file-footer row.
        if (not symbol or not symbol.isalnum() or etf == "Y" or test == "Y"
                or (tiers and tier not in tiers) or fin not in ("N", "")):
            continue
        items.append({"symbol": symbol, "name": name, "sector": "", "yf": symbol + suffix})
    return items


def _fetch_crypto(suffix: str, limit: int | None = None) -> list[dict]:
    """Top coins by market cap from CoinGecko (stablecoins/wrapped tokens skipped).

    Maps each coin to a Yahoo ``<SYMBOL>-USD`` ticker; coins Yahoo doesn't carry
    under that exact ticker are dropped at scan time when no data comes back.

    Pages are walked at CoinGecko's 250-row cap until ``limit`` tradeable coins
    are collected (see COINGECKO_PER_PAGE_MAX for why one oversized page is
    not an option). Page 1 failing is a failed fetch (cache fallback, as
    before). A LATER page failing keeps what the earlier pages returned: a
    universe of the top ~215 is strictly better than falling back to a
    cached snapshot that is smaller, and the gap is logged, not hidden.
    """
    if limit is None:
        limit = int(getattr(config, "CRYPTO_UNIVERSE_SIZE", 100) or 100)

    items: list[dict] = []
    seen: set[str] = set()
    for page in range(1, COINGECKO_MAX_PAGES + 1):
        url = coingecko_url(page)
        try:
            data = json.loads(_http_get(url, timeout=30, headers=_BROWSER_HEADERS))
        except Exception as exc:  # noqa: BLE001 - logged, then falls back
            if page == 1:
                return _fetch_failed("crypto", url, exc)
            print(f"  universe: crypto page {page} FAILED - keeping {len(items)} "
                  f"coins from earlier pages ({type(exc).__name__}: "
                  f"{str(exc)[:120]})", flush=True)
            break
        if not isinstance(data, list):
            if page == 1:
                return _fetch_failed("crypto", url, ValueError(
                    f"unexpected payload type {type(data).__name__}"))
            break
        for coin in data:
            sym = (coin.get("symbol") or "").strip().upper()
            name = (coin.get("name") or sym).strip()
            if not sym or _is_stable(sym, name) or not sym.isalnum() or sym in seen:
                continue
            seen.add(sym)
            px = coin.get("current_price")
            # CoinGecko's own price for THIS coin: the identity reference that
            # stops a same-ticker collision (Yahoo's ARB-USD/JUP-USD/AERO-USD
            # were different tokens -- 2026-09-28) from being scanned as it.
            items.append({"symbol": sym, "name": name, "sector": "", "yf": sym + suffix,
                          "cg_price": float(px) if isinstance(px, (int, float)) and px > 0 else None})
            if len(items) >= limit:
                break
        # Stop when the target is met, or when CoinGecko ran out of coins (a
        # short page is the last page -- asking again would only repeat it).
        if len(items) >= limit or len(data) < COINGECKO_PER_PAGE_MAX:
            break
        time.sleep(1.5)   # free-tier rate limit is per minute; be polite
    # Pinned extras (2026-07-02): coins the owner tracks that must never fall
    # out of the universe because their market-cap rank slips below the cut. Coins Yahoo doesn't carry are dropped at scan time as usual.
    for sym in getattr(config, "CRYPTO_EXTRA_SYMBOLS", []):
        sym = str(sym).strip().upper()
        if sym and sym.isalnum() and sym not in seen:
            seen.add(sym)
            items.append({"symbol": sym, "name": sym, "sector": "", "yf": sym + suffix})
    return items


def identity_refs(items: list[dict]) -> tuple[dict, float]:
    """({yf ticker: CoinGecko price}, tolerance) for data.fetch's identity
    check. A universe served from the last-good snapshot (CoinGecko down)
    carries OLD prices, so it gets config.CRYPTO_IDENTITY_TOL_STALE -- wide
    enough that a real coin which moved while CoinGecko was down is not
    refused everywhere, tight enough for the gross same-ticker collisions."""
    refs = {i["yf"]: i.get("cg_price") for i in items if i.get("yf")}
    stale = any(i.get("cg_stale") for i in items)
    tol = config.CRYPTO_IDENTITY_TOL_STALE if stale else config.CRYPTO_IDENTITY_TOL
    return refs, float(tol)


def load_universe(market_key: str, full: bool = True) -> list[dict]:
    """Return [{symbol, name, yf}, ...] for a market.

    For the ASX, ``full=True`` (default) fetches the entire ASX-listed directory
    (~2,000 names); set ``full=False`` to use the smaller bundled CSV for a quick
    scan. NASDAQ uses the bundled curated list (falling back to the live directory).
    """
    market = config.MARKETS[market_key]
    csv_path = UNIVERSE_DIR / f"{market_key}_tickers.csv"

    # ASX: full universe straight from the official directory.
    if market_key == "asx" and full:
        items = _fetch_asx_listed(market.suffix)
        if items:
            _save_universe_cache(market_key, items)
            return items

    # NASDAQ: full Global Select directory (~1,500 liquid names), mirroring
    # the ASX pattern. Previously the bundled 99-name curated CSV took
    # precedence, so every lens was blind to all but mega-caps (owner
    # deep-dive 2026-07-09). The CSV remains the offline fallback below.
    if market_key == "nasdaq" and full:
        items = _fetch_nasdaq_listed(market.suffix)
        if items:
            _save_universe_cache(market_key, items)
            return items

    # Crypto: top CRYPTO_UNIVERSE_SIZE by market cap from CoinGecko.
    if market_key == "crypto":
        items = _fetch_crypto(market.suffix)
        if items:
            _save_universe_cache(market_key, items)
            return items
        # fall through to the cached/bundled list if the fetch failed

    # Directory fetch failed (even with retries): prefer the LAST GOOD full
    # snapshot over the tiny bundled CSV, so one flaky endpoint can no longer
    # shrink a scan from ~2,000 names to ~90 without a trace.
    if full or market_key == "crypto":
        cached = _load_universe_cache(market_key)
        if cached and market_key == "crypto":
            # A snapshot saved under an older peg rule must not bring a peg
            # back the day CoinGecko is down. Its cg_price is as old as the
            # snapshot: flag it, so the identity check reads it with the wide
            # stale band (identity_refs) instead of refusing every real coin
            # that moved while CoinGecko was down.
            cached = [dict(i, cg_stale=True) for i in cached
                      if not _is_stable(i.get("symbol", ""), i.get("name", ""))]
        if cached:
            print(f"  universe: {market_key} directory fetch FAILED - "
                  f"using last-good cache ({len(cached)} names)", flush=True)
            return cached

    if csv_path.exists():
        items = _from_csv(csv_path, market.suffix)
        if items:
            if full:
                print(f"  universe: WARNING {market_key} running on the bundled "
                      f"fallback CSV ({len(items)} names) - directory fetch and "
                      f"cache both unavailable", flush=True)
            return items

    if market_key == "asx":
        return _fetch_asx_listed(market.suffix)
    if market_key == "nasdaq":
        return _fetch_nasdaq_listed(market.suffix)
    return []
