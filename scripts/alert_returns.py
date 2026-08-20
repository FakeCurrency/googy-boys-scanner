#!/usr/bin/env python3
"""Forward returns for confluence alerts (alert_returns.yml, 2026-08-20).

The multi-lens confluence alignment is the scanner's HEADLINE feature and it
has never had its predictive value measured. This job stamps 5/10/20-session
forward returns on every alignment the ALERTS log records, so "does 2+/3-lens
agreement predict anything" becomes a question with data behind it.

RESEARCH INFRASTRUCTURE, not a signal path: nothing here changes how alerts
are generated or dispatched, and nothing in scanner/ or broker/ reads the
ledger back (tests pin both directions).

WHY A SIDE LEDGER AND NOT IN-PLACE STAMPING - two facts found by measuring,
not assumed (both contradict the naive "stamp the history file" design):
  1. public/data/phasemap/alert_history.json is a rolling HISTORY_CAP=800
     window that on current alert volume ALREADY evicts entries at ~14 days
     (measured 2026-08-20: 800 entries span Aug 6 -> Aug 20). A 20-day
     forward return can NEVER mature inside that window - the entry is gone
     before the answer exists.
  2. That file is written by confluence_alert.append_history INSIDE the scan
     mutex. A second daily writer outside the mutex would race it and lose
     one side's update.
So this script READS the history and never writes it. Entries are copied ONCE
into the durable ledger data/alert_forward_returns.json - keyed by the same
session-day|market|ticker|side|count identity confluence itself dedupes on -
and stamped there as each horizon matures.

IDEMPOTENT both ways: a second run ingests nothing new and never re-stamps a
filled horizon (the return is frozen at first measurement; later data
revisions do not rewrite history).

RETURNS ARE RAW, UNSIGNED moves: close[base + N sessions] / close[base] - 1,
where base is the alert session's own close in the market's calendar. Sign at
analysis time - a SHORT alert's edge is a NEGATIVE forward return. A ticker
Yahoo does not return today is left unstamped and retried next run: never 0,
never a guess.

Prints ALERT_RETURNS_UNCHANGED when the run changed nothing, so the workflow
skips its commit - the reco_note pattern; a quiet day is a legitimate no-op,
which is exactly where a must-change gate would be the wrong tool.

CONTEXT ENRICHMENT (2026-08-20, batch-100): entries additionally carry, when
derivable, `sector` (day-independent; backfilled), `breadth200` (the market's
above-200-day share ON base_day, exact from the committed regime series), and
- same-day scans only, because a later day's grade stamped backwards would be
look-ahead - the VIVEK leg's `grade_raw`, `score`, `is_product`. All stamps
are BLANK-ONLY and frozen once written, exactly like the returns.

ASCII-only prints; atomic write via scanner.output.write_json.
"""
import csv
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scanner import config, output                                  # noqa: E402

HISTORY = os.path.join(ROOT, "public", "data", "phasemap", "alert_history.json")
LEDGER = os.path.join(ROOT, "data", "alert_forward_returns.json")

HORIZONS = tuple(getattr(config, "ALERT_RETURNS_HORIZONS", (1, 5, 10, 20)))
CAP = int(getattr(config, "ALERT_RETURNS_CAP", 20000))
# An entry whose horizons still have holes this long after base_day is almost
# certainly a delisting/suspension — count it out loud (survivorship is a bias
# only when it is silent), keep retrying anyway (retries are cheap).
STALE_UNMATURED_DAYS = 40


def _market_day(iso: str, market: str) -> str:
    """The market-local session day of an alert stamp - the SAME identity
    confluence_alert's dedupe uses, so one alignment is one ledger row."""
    try:
        t = dt.datetime.fromisoformat(str(iso))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        tz = config.MARKETS[market].timezone if market in config.MARKETS else "UTC"
        return t.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")
    except (ValueError, KeyError):
        return str(iso)[:10]


def entry_key(e: dict) -> str:
    return "|".join([_market_day(e.get("date", ""), e.get("market", "")),
                     str(e.get("market", "")), str(e.get("ticker", "")),
                     str(e.get("side", "")), str(e.get("count", ""))])


def _fresh() -> dict:
    return {"schema_version": 1, "updated_at": "", "entries": []}


def load_ledger(path: str = LEDGER) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except FileNotFoundError:
        return _fresh()
    except (OSError, ValueError):
        print("WARNING ledger unreadable - starting fresh")
        return _fresh()
    if not isinstance(d, dict) or not isinstance(d.get("entries"), list):
        print("WARNING ledger malformed - starting fresh")
        return _fresh()
    return d


def ingest(ledger: dict, history_entries: list[dict]) -> int:
    """Copy alignments the ledger has not seen. Returns how many were new."""
    have = {e.get("key") for e in ledger["entries"]}
    added = 0
    for e in history_entries or []:
        if not (e.get("ticker") and e.get("market")):
            continue
        k = entry_key(e)
        if k in have:
            continue
        have.add(k)
        ledger["entries"].append({
            "key": k,
            "date": e.get("date"),
            "market": e.get("market"),
            "ticker": e.get("ticker"),
            "side": e.get("side"),
            "count": e.get("count"),
            "lenses": e.get("lenses"),
            "base_day": _market_day(e.get("date", ""), e.get("market", "")),
            "base_close": None,
            "fwd": {str(h): None for h in HORIZONS},
        })
        added += 1
    return added


def _load_sectors() -> dict:
    """(market, sym) -> sector, from the ASX universe (full GICS coverage) and
    the NASDAQ sector cache. Day-independent, so safe to backfill any entry."""
    sec = {}
    try:
        with open(os.path.join(ROOT, "data_universe", "asx_tickers.csv"), encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("symbol") and (r.get("sector") or "").strip():
                    sec[("asx", r["symbol"])] = r["sector"].strip()
    except OSError:
        pass
    try:
        with open(os.path.join(ROOT, "data", "sector_map.json"), encoding="utf-8") as fh:
            for k, v in json.load(fh).items():
                mkt, sym = k.split(":", 1)
                s = (v.get("sector") or "").strip()
                if s:
                    sec.setdefault((mkt, sym), s)
    except (OSError, ValueError):
        pass
    return sec


def _scan_day_rows() -> dict:
    """{(market, session_day): {sym: scan row}} for the CURRENT committed scans.
    The grade/score join is only honest when the scan's own session day matches
    the entry's base_day — a Tuesday grade stamped onto a Monday alert would be
    look-ahead — so the day travels with the rows and enrich() checks it."""
    out = {}
    for m in ("asx", "nasdaq", "crypto"):
        try:
            with open(os.path.join(ROOT, "public", "data", f"{m}_vivek.json"), encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        day = _market_day(d.get("generated_at", ""), m)
        out[(m, day)] = {r.get("symbol"): r for r in d.get("results", []) if r.get("symbol")}
    return out


def _breadth_series() -> dict:
    """{market: {day: above200 share}} from the committed regime series —
    day-indexed, so breadth CAN be backfilled exactly for any base_day."""
    out = {}
    try:
        with open(os.path.join(ROOT, "public", "data", "regime.json"), encoding="utf-8") as fh:
            mkts = json.load(fh).get("markets") or {}
        for m, blk in mkts.items():
            days, a200 = blk.get("days") or [], blk.get("above200") or []
            out[m] = dict(zip(days, a200))
    except (OSError, ValueError):
        pass
    return out


def enrich(ledger: dict) -> int:
    """Research-context stamps (2026-08-20, batch-100 WS-A): sector, the
    market's breadth on base_day, and — same-day scans only — the VIVEK leg's
    grade_raw / score / is_product. BLANK-ONLY: a stamp is written once and
    never overwritten, the same freeze rule the returns follow. Returns the
    number of fields written."""
    sectors = _load_sectors()
    scans = _scan_day_rows()
    breadth = _breadth_series()
    n = 0
    for e in ledger["entries"]:
        m, sym, day = e.get("market"), e.get("ticker"), e.get("base_day")
        if e.get("sector") is None:
            s = sectors.get((m, sym))
            if s:
                e["sector"] = s
                n += 1
        if e.get("breadth200") is None:
            b = breadth.get(m, {}).get(day)
            if b is not None:
                e["breadth200"] = round(float(b), 4)
                n += 1
        row = (scans.get((m, day)) or {}).get(sym)
        if row:
            for k in ("grade_raw", "score", "is_product"):
                if e.get(k) is None and row.get(k) is not None:
                    e[k] = row[k]
                    n += 1
    return n


def _yahoo(ticker: str, market: str) -> str:
    sfx = config.MARKETS[market].suffix if market in config.MARKETS else ""
    return f"{ticker}{sfx}"


def wanting_prices(ledger: dict, today: dt.date) -> dict:
    """{yahoo_symbol: [entry, ...]} for entries with a horizon that could
    plausibly have matured (N sessions needs at least N calendar days)."""
    want: dict = {}
    for e in ledger["entries"]:
        try:
            base = dt.date.fromisoformat(str(e.get("base_day", ""))[:10])
        except ValueError:
            continue
        age = (today - base).days
        if any(e["fwd"].get(str(h)) is None and age >= h for h in HORIZONS):
            want.setdefault(_yahoo(e["ticker"], e["market"]), []).append(e)
    return want


def stamp(ledger: dict, frames: dict, want: dict) -> int:
    """Fill matured horizons from downloaded daily bars. Returns stamps made.

    base = the first bar ON or AFTER base_day (an alert fires during its own
    session, so this is normally that session's close); horizon N = the close
    N bars later. A missing frame or a not-yet-existing bar leaves the horizon
    None for the next run."""
    stamped = 0
    for sym, entries in want.items():
        df = frames.get(sym)
        if df is None or getattr(df, "empty", True):
            continue
        closes = df["Close"]
        days = [d.date() if hasattr(d, "date") else d for d in df.index]
        for e in entries:
            try:
                base_day = dt.date.fromisoformat(e["base_day"])
            except (KeyError, ValueError):
                continue
            bi = next((i for i, d in enumerate(days) if d >= base_day), None)
            if bi is None:
                continue
            base_close = float(closes.iloc[bi])
            if not (base_close > 0):
                continue
            if e.get("base_close") is None:
                e["base_close"] = round(base_close, 8)
                stamped += 1        # recording the baseline is itself a change
            for h in HORIZONS:
                key = str(h)
                if e["fwd"].get(key) is not None:
                    continue                       # frozen at first measurement
                if bi + h < len(days):
                    e["fwd"][key] = round(float(closes.iloc[bi + h]) / base_close - 1.0, 6)
                    stamped += 1
    return stamped


def trim(ledger: dict, cap: int | None = None) -> int:
    """Drop the OLDEST fully-stamped entries past the cap - never an entry
    still waiting on a horizon (dropping those silently un-measures the
    feature). `cap` defaults to the ledger's own; edge_rosters.py reuses this
    with its roster cap."""
    cap = CAP if cap is None else cap
    entries = ledger["entries"]
    if len(entries) <= cap:
        return 0
    done = [e for e in entries if all(e["fwd"].get(str(h)) is not None for h in HORIZONS)]
    excess = len(entries) - cap
    drop = {id(e) for e in sorted(done, key=lambda e: e.get("base_day", ""))[:excess]}
    ledger["entries"] = [e for e in entries if id(e) not in drop]
    return len(drop)


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    dry = "--dry-run" in argv

    try:
        with open(HISTORY, encoding="utf-8") as fh:
            hist = json.load(fh).get("entries") or []
    except (OSError, ValueError) as e:
        print(f"ERROR alert history unreadable: {e.__class__.__name__}: {e}")
        return 2

    ledger = load_ledger()
    added = ingest(ledger, hist)
    enriched = enrich(ledger)

    today = dt.datetime.now(dt.timezone.utc).date()
    want = wanting_prices(ledger, today)
    stamped = 0
    if want:
        from scanner.data import download
        frames = download(sorted(want), period="3mo")
        stamped = stamp(ledger, frames, want)
    dropped = trim(ledger)

    entries = ledger["entries"]
    n = len(entries)
    matured = sum(1 for e in entries
                  if all(e["fwd"].get(str(h)) is not None for h in HORIZONS))
    print(f"alert returns: +{added} ingested, +{enriched} context stamps, "
          f"+{stamped} return stamps, -{dropped} trimmed; {n} tracked, {matured} fully matured")

    # Maturity curve + survivorship visibility (batch-100 items 9/93/96/97):
    # per-horizon counts, entries stuck unmatured long past any trading-halt
    # excuse (delistings — a bias only when silent), and the triple-lens cohort
    # everyone is waiting on.
    per_h = " · ".join(f"{h}s {sum(1 for e in entries if e['fwd'].get(str(h)) is not None)}/{n}"
                       for h in HORIZONS)
    def _age(e):
        try:
            return (today - dt.date.fromisoformat(str(e.get("base_day", ""))[:10])).days
        except ValueError:
            return 0
    stale = sum(1 for e in entries
                if any(e["fwd"].get(str(h)) is None for h in HORIZONS)
                and _age(e) >= STALE_UNMATURED_DAYS)
    triples = [e for e in entries if (e.get("count") or 0) >= 3]
    trip_m = sum(1 for e in triples if e["fwd"].get("5") is not None)
    print(f"maturity: {per_h}")
    print(f"stale-unmatured (>{STALE_UNMATURED_DAYS}d, likely delisted - retried anyway): {stale}")
    print(f"triple-lens cohort: {len(triples)} tracked, {trip_m} matured at 5s")

    if not (added or enriched or stamped or dropped):
        print("ALERT_RETURNS_UNCHANGED")
        return 0
    if dry:
        print("dry run - not writing")
        return 0
    ledger["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    output.write_json(LEDGER, ledger, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
