"""Persistent per-ticker SECTOR cache (Fix-10 #10, 2026-07-26).

The ASX directory ships GICS sectors with the universe, but NASDAQ's symbol
file carries none — so the dashboard's SECTOR view had nothing to group US
names by. Same design as the market-cap cache (scanner/marketcaps.py):

  1. ``data/sector_map.json`` holds ``"<market>:<SYMBOL>" -> {"sector", "ts"}``,
     mirrored to ``public/data/sector_map.json`` for the dashboard to merge in.

     THIS IS NOW A SIGNAL PATH (2026-07-28, owner-authorised — REFINEMENTS #38).
     It used to be display-only, and that was the bug: vivek_bot's 3-per-sector
     correlation cap exempts rows with no sector, so NASDAQ — whose universe
     file carries none — had *no* correlation control at all while looking like
     it did. It merely needed wiring, not sourcing: the cache already covered
     269 of 269 rows in the last NASDAQ scan. ``enrich_rows`` below is that
     wiring; ``vivek_run`` calls it before ``vivek_bot.decide``.
     Consequence to respect when editing: a wrong sector here now changes which
     trades get taken, not just how the dashboard groups them.
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


def sector_map_for(market: str, cache: dict | None = None) -> dict:
    """``{SYMBOL: sector}`` for one market, symbol keys upper-cased.

    Entries with a blank sector are dropped so callers can treat "present" as
    "usable" — a key mapping to "" would otherwise overwrite nothing but still
    read as a hit.
    """
    cache = load_cache() if cache is None else cache
    prefix = f"{market}:"
    out: dict = {}
    for key, val in (cache or {}).items():
        if not str(key).startswith(prefix):
            continue
        sector = (val or {}).get("sector") if isinstance(val, dict) else val
        sector = str(sector or "").strip()
        if sector:
            out[str(key)[len(prefix):].upper()] = sector
    return out


def enrich_rows(rows, market: str, cache: dict | None = None) -> int:
    """Fill ``sector`` on rows that lack one, from the cache. Returns how many.

    Only ever WRITES into a blank field — a sector that shipped with the
    universe (ASX does) always wins over the cache, which is best-effort Yahoo
    data. Returns 0 and touches nothing when the cache has no entry for the
    market, so an empty cache degrades to today's behaviour rather than
    clearing sectors that were already right.
    """
    if not rows or not market:
        return 0
    lookup = sector_map_for(market, cache)
    if not lookup:
        return 0
    filled = 0
    for row in rows:
        if str(row.get("sector") or "").strip():
            continue
        sector = lookup.get(str(row.get("symbol") or "").upper())
        if sector:
            row["sector"] = sector
            filled += 1
    return filled


def diverging(positions, rows) -> list[str]:
    """Held positions whose stored sector disagrees with this scan's rows.

    Reported, never repaired. `enrich_rows` fills blanks; this finds the other
    failure — a sector that is present but from a DIFFERENT taxonomy than the
    one the market's universe ships today. Two ASX holdings carry Yahoo-style
    'Insurance' / 'Financial Services' where the ASX universe says 'Financials'
    for the same symbols, so the 3-per-sector cap sees three buckets where
    there is one. Overwriting a non-blank sector changes which trades get
    taken, so that is an owner decision (REFINEMENTS #112) and this function
    exists only to stop it being invisible.

    Returns ``SYM=stored->universe`` strings, sorted, for logging.
    """
    if not positions or not rows:
        return []
    from_scan = {str(r.get("symbol") or "").upper(): str(r.get("sector") or "").strip()
                 for r in rows if str(r.get("sector") or "").strip()}
    out = set()
    for pos in positions:
        sym = str(pos.get("symbol") or "").upper()
        stored = str(pos.get("sector") or "").strip()
        # A blank is enrich_rows' job, not a disagreement.
        if not stored or sym not in from_scan or stored == from_scan[sym]:
            continue
        out.add(f"{sym}={stored}->{from_scan[sym]}")
    return sorted(out)


def global_sector_load(positions, cap: int = 0) -> list[str]:
    """Real sectors held ABOVE `cap` once every market is counted together.

    The correlation cap is enforced PER MARKET — `decide()` seeds its counter
    from `open_book`, which is one market's slice — while the 30-position and
    $150,000 ceilings are GLOBAL (`open_elsewhere` / `notional_elsewhere`). So
    three ASX financials plus three NASDAQ financials is six of one real sector
    in a 30-slot book, and every per-market check passes. That gap only started
    mattering when the position ceiling went global (2026-07-28); before it, a
    per-market sector cap matched a per-market position cap.

    Reported, never enforced: making the cap global changes which trades get
    taken, so it is an owner decision (REFINEMENTS #113). This exists so the
    concentration is a number in the log rather than a surprise in a drawdown.

    Sectors are compared case-insensitively, matching `vivek_bot._sector_key`.
    Blanks are skipped (the cap exempts them) and so are crypto's synthetic
    buckets, which are per-market by construction and cannot collide with an
    equity sector name.

    Returns ``sector=count(markets)`` strings, worst first, for logging.
    """
    if not positions or cap <= 0:
        return []
    buckets: dict = {}
    for pos in positions:
        sector = str((pos or {}).get("sector") or "").strip()
        if not sector:
            continue
        entry = buckets.setdefault(sector.lower(), {"n": 0, "markets": set(),
                                                    "label": sector})
        entry["n"] += 1
        entry["markets"].add(str(pos.get("market") or "?"))
    out = [(e["n"], e["label"], sorted(e["markets"]))
           for e in buckets.values() if e["n"] > cap]
    out.sort(key=lambda t: (-t[0], t[1]))
    return [f"{label}={n}({'+'.join(mkts)})" for n, label, mkts in out]


def _scan_symbols() -> list[tuple[int, str, str]]:
    """(grade_rank, market, symbol) for every scan row still missing a sector.

    OPEN POSITIONS ARE INCLUDED FIRST (2026-07-28). Now that the per-sector cap
    reads this cache, a holding that has dropped out of the scan is the worst
    case to leave uncovered: it occupies a slot but is exempt from the cap it
    should be filling. Three of the book's NASDAQ positions were in exactly
    that state — held, sector-less, and invisible to the fetch list because the
    list was built from scan results only.
    """
    out: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    book = ROOT / "journal" / "vivek_bot_book.json"
    if book.exists():
        try:
            for pos in json.loads(book.read_text()).get("open", []):
                market = str(pos.get("market") or "")
                sym = str(pos.get("symbol") or "").upper()
                if (not sym or not market
                        or market not in {m for m, _ in _SCAN_FILES}
                        or str(pos.get("sector") or "").strip()):
                    continue
                k = _key(market, sym)
                if k not in seen:
                    seen.add(k)
                    out.append((-1, market, sym))   # ahead of every scan grade
        except Exception:
            pass                                    # best-effort, same as below
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


def _fetch_sector(yf_symbol: str) -> tuple[str, str]:
    """(sector, outcome) for one symbol, outcome one of 'ok' / 'none' / 'failed'.

    TOP100 #65 — this used to return ``''`` for two situations that are not the
    same thing and do not have the same remedy:

      * the profile fetch RAISED (rate limit, network, delisted, a Yahoo symbol
        that does not resolve) — nothing was learned, and the name is worth
        retrying;
      * the profile came back fine and simply carries no sector — an ETF, a
        trust, a shell. Retrying will return the same nothing tomorrow and every
        day after.

    Both landed in the same `got X/N` line, so a run where Yahoo rate-limited
    every request and a run where every remaining name is genuinely an ETF
    printed the identical sentence. Since REFINEMENTS #38 made this cache a
    SIGNAL path — a blank sector is exempt from the 3-per-sector cap — "coverage
    stopped improving" is a question about the correlation limit, and it needed
    an answer better than one number.

    The outcome is REPORTED, not acted on. Caching the 'none' verdict is the
    obvious next step and is deliberately not taken here: it would be inert
    today (``_targets`` filters on a falsy ``sector``, so a cached blank is
    still "missing" and still refetched) and the version that is NOT inert —
    teaching ``_targets`` to skip them — changes which names carry a sector,
    hence which sectors the cap counts, hence which trades get taken. Owner's
    call, not a refactor.
    """
    try:
        import yfinance as yf
        info = yf.Ticker(yf_symbol).get_info() or {}
    except Exception:
        return "", "failed"
    sector = str(info.get("sector") or "").strip()
    return sector, ("ok" if sector else "none")


def refresh(cap: int = _DEFAULT_CAP) -> dict:
    cache = load_cache()
    targets = _targets(_scan_symbols(), cache, cap)
    if not targets:
        print("  sectors: nothing to fetch - every scan symbol already mapped")
        return cache
    print(f"  sectors: fetching up to {len(targets)} missing sector(s) ...")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    got = none = failed = 0
    for market, sym in targets:
        sector, outcome = _fetch_sector(_yf_symbol(market, sym))
        if outcome == "ok":
            cache[_key(market, sym)] = {"sector": sector, "ts": now}
            got += 1
        elif outcome == "none":
            none += 1
        else:
            failed += 1
        time.sleep(_PACE_S)
    if got:
        save_cache(cache)
    # TOP100 #65 — three numbers, because they mean three different things and
    # only one of them is a problem you can do anything about. Printed on every
    # run including a clean one, so a standing `failed 0` is what makes a jump
    # legible (same rule as the scan's error accounting).
    print(f"  sectors: got {got} / none {none} / failed {failed} of "
          f"{len(targets)}; cache now holds {len(cache)} symbols")
    if failed:
        print(f"  sectors: WARNING {failed} profile fetch(es) FAILED - those names "
              f"learned nothing this run and stay exempt from the per-sector cap "
              f"until a later scan succeeds")
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
