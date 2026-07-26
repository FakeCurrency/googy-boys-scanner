"""Persistent per-ticker SECTOR cache (Fix-10 #10, 2026-07-26).

The ASX directory ships GICS sectors with the universe, but NASDAQ's symbol
file carries none — so the dashboard's SECTOR view had nothing to group US
names by. Same design as the market-cap cache (scanner/marketcaps.py):

  1. ``data/sector_map.json`` holds ``"<market>:<SYMBOL>" -> {"sector", "ts"}``,
     mirrored to ``public/data/sector_map.json`` for the dashboard to merge in
     (client-side, display only — nothing in any signal path reads this).
  2. Refreshed BEFORE the scan (the fresh-IP window marketcaps already uses),
     reading the PREVIOUS scan's results for symbols still missing a sector.
     Sectors are static, so cached entries are never re-fetched.
  3. Best-effort by design: every failure path leaves the cache as-is and
     exits 0 — this step must never fail a scan run.

    python -m scanner.sectorcache            # fetch up to --cap missing sectors
    python -m scanner.sectorcache --cap 10   # smaller batch
"""

import argparse
import datetime as dt
import json
import os
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE_FILE = ROOT / "data" / "sector_map.json"
PUBLIC_FILE = ROOT / "public" / "data" / "sector_map.json"

# Scan outputs we pull sector-less symbols from. Crypto is skipped on purpose
# (coins have no sector; the dashboard groups them under OTHER).
_SCAN_FILES = [
    ("asx", "public/data/asx_vivek.json"),
    ("nasdaq", "public/data/nasdaq_vivek.json"),
]
_GRADE_RANK = {"A+": 0, "A": 1, "B+": 2, "B": 2, "WATCH": 3}
_DEFAULT_CAP = 40          # per-run fetch budget — full NASDAQ fills in ~a day
_PACE_S = 1.2              # gentle pacing between profile fetches


def _key(market: str, symbol: str) -> str:
    return f"{market}:{symbol}"


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def save_cache(cache: dict) -> None:
    payload = json.dumps(cache, indent=0, sort_keys=True)
    for path in (CACHE_FILE, PUBLIC_FILE):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, path)
        except Exception:
            pass


def _scan_symbols() -> list[tuple[int, str, str]]:
    """(grade_rank, market, symbol) for every scan row still missing a sector."""
    out: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for market, rel in _SCAN_FILES:
        path = ROOT / rel
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        for sig in data.get("results", []):
            sym = str(sig.get("symbol") or "").upper()
            if not sym or (sig.get("sector") or "").strip():
                continue
            k = _key(market, sym)
            if k in seen:
                continue
            seen.add(k)
            out.append((_GRADE_RANK.get(sig.get("grade"), 4), market, sym))
    return out


def _targets(symbols: list[tuple[int, str, str]], cache: dict, cap: int) -> list[tuple[str, str]]:
    """Best-grade-first fetch list of (market, symbol), missing-only, capped."""
    todo = [(rank, m, s) for rank, m, s in symbols
            if not (cache.get(_key(m, s)) or {}).get("sector")]
    todo.sort()
    return [(m, s) for _, m, s in todo[:max(0, cap)]]


def _yf_symbol(market: str, symbol: str) -> str:
    return symbol + ".AX" if market == "asx" else symbol


def _fetch_sector(yf_symbol: str) -> str:
    """One symbol's sector from the Yahoo asset profile ('' on any failure)."""
    try:
        import yfinance as yf
        info = yf.Ticker(yf_symbol).get_info() or {}
        return str(info.get("sector") or "").strip()
    except Exception:
        return ""


def refresh(cap: int = _DEFAULT_CAP) -> dict:
    cache = load_cache()
    targets = _targets(_scan_symbols(), cache, cap)
    if not targets:
        print("  sectors: nothing to fetch - every scan symbol already mapped")
        return cache
    print(f"  sectors: fetching up to {len(targets)} missing sector(s) ...")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    got = 0
    for market, sym in targets:
        sector = _fetch_sector(_yf_symbol(market, sym))
        if sector:
            cache[_key(market, sym)] = {"sector": sector, "ts": now}
            got += 1
        time.sleep(_PACE_S)
    if got:
        save_cache(cache)
    print(f"  sectors: got {got}/{len(targets)}; cache now holds {len(cache)} symbols")
    return cache


def main() -> None:
    ap = argparse.ArgumentParser(description="Refresh the per-ticker sector cache")
    ap.add_argument("--cap", type=int, default=_DEFAULT_CAP,
                    help=f"max profile fetches this run (default {_DEFAULT_CAP})")
    args = ap.parse_args()
    try:
        refresh(cap=args.cap)
    except Exception as exc:  # noqa: BLE001 - best-effort step, never fail a scan
        print(f"  sectors: WARNING refresh failed ({exc}) - cache left as-is")


if __name__ == "__main__":
    main()
