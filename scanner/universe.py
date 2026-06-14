"""Per-market ticker universes.

Source of truth is a bundled CSV (``data_universe/<market>_tickers.csv`` with
``symbol,name`` columns). Edit those files to grow or trim a universe — the
liquidity filter prunes anything too thin at scan time, so a generous list is
fine. If a CSV is missing, NASDAQ can fall back to the official symbol file.
"""

import csv
import io
import pathlib
import urllib.request

from . import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
UNIVERSE_DIR = ROOT / "data_universe"

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
ASX_LISTED_URL = "https://www.asx.com.au/asx/research/ASXListedCompanies.csv"

_BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FibScanner/1.0)"}


def _from_csv(path: pathlib.Path, suffix: str) -> list[dict]:
    items: list[dict] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            symbol = (row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            name = (row.get("name") or symbol).strip()
            sector = (row.get("sector") or "").strip()
            items.append({"symbol": symbol, "name": name, "sector": sector,
                          "yf": symbol + suffix})
    return items


def _pretty(name: str) -> str:
    """ASX names come in ALL CAPS; title-case them for display."""
    return name.strip().title()


def _fetch_asx_listed(suffix: str) -> list[dict]:
    """Fetch the entire ASX-listed universe from the official directory CSV.

    The file has a few preamble lines, then rows of: "Company name","Code","GICS".
    """
    try:
        req = urllib.request.Request(ASX_LISTED_URL, headers=_BROWSER_HEADERS)
        with urllib.request.urlopen(req, timeout=45) as resp:
            text = resp.read().decode("utf-8", "ignore")
    except Exception:
        return []

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


def _fetch_nasdaq_listed(suffix: str) -> list[dict]:
    """Fallback: pull the live NASDAQ-listed symbol directory (pipe-delimited)."""
    try:
        with urllib.request.urlopen(NASDAQ_LISTED_URL, timeout=30) as resp:
            text = resp.read().decode("utf-8", "ignore")
    except Exception:
        return []

    items: list[dict] = []
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    for row in reader:
        symbol = (row.get("Symbol") or "").strip().upper()
        name = (row.get("Security Name") or symbol).strip()
        etf = (row.get("ETF") or "").strip().upper()
        test = (row.get("Test Issue") or "").strip().upper()
        # Skip ETFs, test issues, and non-common symbols (those with $ / .)
        if not symbol or etf == "Y" or test == "Y" or "$" in symbol or "." in symbol:
            continue
        items.append({"symbol": symbol, "name": name, "sector": "", "yf": symbol + suffix})
    return items


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
            return items
        # fall through to the bundled list if the fetch failed

    if csv_path.exists():
        items = _from_csv(csv_path, market.suffix)
        if items:
            return items

    if market_key == "asx":
        return _fetch_asx_listed(market.suffix)
    if market_key == "nasdaq":
        return _fetch_nasdaq_listed(market.suffix)
    return []
