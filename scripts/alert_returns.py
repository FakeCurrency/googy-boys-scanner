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
never a guess. COMPLETED BARS ONLY (2026-10-05): Yahoo's daily series carries
the session's still-forming bar, and a stamp is frozen, so a bar that may still
be forming (final_bar_cutoff) is never read as a base or a horizon.

THE BASE BAR IS PINNED (2026-10-08, audit #69). The first stamp records the
base bar's date as `base_bar`; every later horizon is measured from THAT bar,
found by date. An entry stamped before base_bar existed falls back to "the
first bar on/after base_day", but only in a frame that reaches back to
base_day and only within ALERT_RETURNS_BASE_MAX_GAP_DAYS of it: a fixed 3-month
download used to slide past an old base_day (a suspension, a long-unmatured
row) and silently re-anchor the base on a bar weeks later. Each ticker is now
downloaded over a period that reaches its oldest wanted base_day.

CRYPTO IS PRICED AS ITS OWN COIN (2026-10-08, audit #30). Since 2026-09-28 the
crypto VIVEK leg is scanned on exchange klines with an identity check, because
Yahoo serves a DIFFERENT token under several tickers (JUP, AERO, ARB...). These
ledgers priced crypto on Yahoo's `download` regardless, and the 2026-09-29 JUP
row froze another coin's returns (base 0.000327 against the scanned $0.37).
Crypto now goes through scanner.data.fetch -- the one entry point -- with the
identity check armed: a row's own pinned base (base_bar, base_close) is its
history anchor when an identity-CHECKED frame set it (`base_identity` ref /
anchor -- an unchecked base never vouches), else the committed scan's price
for the coin is the reference, and a coin nothing vouches for is left unstamped (named, retried),
never priced as a stranger. A crypto row whose STORED base is not the
instrument now priced (the pre-fix JUP row) is never extended either: its
frozen values stay exactly as they are, an owner decision.

Prints ALERT_RETURNS_UNCHANGED when the run changed nothing, so the workflow
skips its commit - the reco_note pattern; a quiet day is a legitimate no-op,
which is exactly where a must-change gate would be the wrong tool.

CONTEXT ENRICHMENT (2026-08-20, batch-100): entries additionally carry, when
derivable, `sector` (day-independent; backfilled), `breadth200` (the market's
above-200-day share ON base_day — blank since the 2026-09-20 REGIME removal), and
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
# The committed crypto scan's slim prices ({"prices": {SYM: price}}): the
# identity-checked price of each coin as the scan itself priced it -- the
# reference a crypto frame must match (audit #30).
SCAN_PRICES = os.path.join(ROOT, "public", "data", "crypto_prices.json")

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


def load_ledger(path: str | None = None) -> dict:
    # Resolved at CALL time: a default bound at import would read the repo's
    # real ledger even after a test (or a caller) repoints LEDGER.
    path = path or LEDGER
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
    """{market: {day: above200 share}}. The source (public/data/regime.json,
    the REGIME surface) was REMOVED on 2026-09-20 with the whole surface, so
    this now returns nothing and `breadth200` stays BLANK on new entries —
    rows stamped while it existed keep their frozen value (blank-only rule).
    Kept as a seam so a future breadth series plugs in here without touching
    enrich()."""
    return {}


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


def final_bar_cutoff(market: str, now: dt.datetime) -> dt.date:
    """The first bar date that may still be FORMING for `market` at `now`
    (an aware datetime); stamp() reads only bars dated before it.

    Judged in the market's own zone: today's bar is final once the local clock
    reaches config.ALERT_RETURNS_BAR_FINAL (closing print + delayed feed), so
    the cutoff moves to tomorrow; before that it is today. A market with no
    entry trades 24/7 (crypto, UTC daily bars), so its today's bar is never
    final. An unknown market reads as UTC and 24/7: the strict answer."""
    tz = config.MARKETS[market].timezone if market in config.MARKETS else "UTC"
    local = now.astimezone(ZoneInfo(tz))
    final = config.ALERT_RETURNS_BAR_FINAL.get(market)
    if final is not None and (local.hour, local.minute) >= tuple(final):
        return local.date() + dt.timedelta(days=1)
    return local.date()


# Why a wanted entry was left unstamped this run, for the WARNING stamp()
# prints (an unstamped row is retried next run; it is never re-anchored).
_UNSTAMPED_WHY = {
    "uncovered": "the frame starts after base_day, so the base bar is not in it",
    "gap": "no bar within ALERT_RETURNS_BASE_MAX_GAP_DAYS of base_day (a suspension)",
    "base_bar_missing": "the recorded base_bar is not in the frame",
    "other_instrument": ("crypto: the frame's base close is not the stored base_close "
                         "- the row was priced on another instrument, never extended"),
}


def _base_index(e: dict, days: list, done: int, base_day: dt.date) -> tuple:
    """(index of the entry's base bar in days[:done], or None; why not, or
    None when the base simply has not completed yet).

    An entry that recorded `base_bar` is measured from exactly that bar. One
    without it takes the first completed bar on/after base_day -- but only in
    a frame that reaches back to base_day (else the base bar may have slid
    out of the window) and only within ALERT_RETURNS_BASE_MAX_GAP_DAYS (else
    it is a suspension's resumption bar, not the alert session's close)."""
    if e.get("base_bar"):
        try:
            pinned = dt.date.fromisoformat(str(e["base_bar"])[:10])
        except ValueError:
            pinned = None
        if pinned is not None:
            i = next((i for i, d in enumerate(days[:done]) if d == pinned), None)
            return (i, None) if i is not None else (None, "base_bar_missing")
    if not days or days[0] > base_day:
        return None, "uncovered"
    bi = next((i for i, d in enumerate(days[:done]) if d >= base_day), None)
    if bi is None:
        return None, None
    gap = int(getattr(config, "ALERT_RETURNS_BASE_MAX_GAP_DAYS", 7))
    if (days[bi] - base_day).days > gap:
        return None, "gap"
    return bi, None


def _same_instrument(df, day: dt.date, stored) -> bool:
    """Does this frame reproduce the base close the row already stored, on
    its base day? exchange_data.anchor_ok -- the history-anchor test the book
    and the kill switch use -- but at the IDENTITY band (CRYPTO_IDENTITY_TOL),
    not the tighter anchor band: a row stamped before 2026-10-05 may hold a
    still-FORMING bar's price as its base (an intraday print, not the close),
    and a coin that moved past 15% after that print is still the coin. The
    strangers this exists to catch are orders of magnitude off (JUP: x1,100)."""
    from scanner import exchange_data
    try:
        return exchange_data.anchor_ok(df, (day.isoformat(), float(stored)),
                                       tol=float(config.CRYPTO_IDENTITY_TOL))
    except (TypeError, ValueError):
        return False


def stamp(ledger: dict, frames: dict, want: dict, now: dt.datetime | None = None) -> int:
    """Fill matured horizons from downloaded daily bars. Returns stamps made.

    base = the first bar ON or AFTER base_day (an alert fires during its own
    session, so this is normally that session's close), pinned by date as
    `base_bar` at the first stamp (see _base_index); horizon N = the close N
    bars later. Only COMPLETED bars count: a bar dated on/after
    final_bar_cutoff(market, now) may still be forming, and a base or horizon
    read from it would freeze an intraday price for good. A missing frame, a
    not-yet-existing bar or a still-forming one leaves the horizon None for
    the next run; so does a base bar that cannot be found honestly (counted
    in a WARNING)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    stamped = 0
    unstamped: dict[str, list] = {}
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
            cutoff = final_bar_cutoff(e.get("market", ""), now)
            done = sum(1 for d in days if d < cutoff)    # bars are date-ascending
            bi, why = _base_index(e, days, done, base_day)
            if bi is None:
                if why:
                    unstamped.setdefault(why, []).append(str(e.get("key") or sym))
                continue
            base_close = float(closes.iloc[bi])
            if not (base_close > 0):
                continue
            if e.get("base_close") is None:
                e["base_close"] = round(base_close, 8)
                e["base_bar"] = days[bi].isoformat()
                if e.get("market") == "crypto":
                    # How the frame that set the base proved it is the coin
                    # (data.fetch's attrs["identity"]: ref / anchor / none).
                    # Only a CHECKED base may later vouch for the coin as a
                    # history anchor (crypto_identity_kwargs) -- the rule
                    # data.anchor_of keeps: an unchecked frame (a Yahoo-mode
                    # run, CRYPTO_DATA_SOURCE="yahoo") must never become the
                    # evidence the next check trusts.
                    e["base_identity"] = str((getattr(df, "attrs", None) or {}).get("identity")
                                             or "none")
                stamped += 1        # recording the baseline is itself a change
            elif e.get("market") == "crypto" and not _same_instrument(df, days[bi], e["base_close"]):
                # Crypto bars are never split-adjusted, so a stored base this
                # far off is another coin's close (Yahoo's JUP): its frozen
                # horizons stay as they are and nothing is added to them.
                unstamped.setdefault("other_instrument", []).append(str(e.get("key") or sym))
                continue
            for h in HORIZONS:
                key = str(h)
                if e["fwd"].get(key) is not None:
                    continue                       # frozen at first measurement
                if bi + h < done:
                    e["fwd"][key] = round(float(closes.iloc[bi + h]) / base_close - 1.0, 6)
                    stamped += 1
    for why, keys in sorted(unstamped.items()):
        print(f"WARNING stamp: {len(keys)} entr{'y' if len(keys) == 1 else 'ies'} left "
              f"unstamped - {_UNSTAMPED_WHY.get(why, why)}: {', '.join(keys[:8])}"
              f"{' ...' if len(keys) > 8 else ''}")
    return stamped


# yfinance periods and the calendar days each is SAFELY known to reach back
# (the same table data.held_fetch_period uses). "3mo" -- the old fixed
# window -- stays the floor, so a young entry asks for exactly what it did.
_PERIODS = ((88, "3mo"), (180, "6mo"), (360, "1y"), (725, "2y"), (1820, "5y"))


def period_for(entries: list, today: dt.date) -> str:
    """The shortest download period whose frame reaches back past the oldest
    base_day among `entries`, plus a week (so a weekend/holiday base_day still
    has a bar before it and _base_index can see the frame covers it)."""
    days = []
    for e in entries:
        try:
            days.append((today - dt.date.fromisoformat(str(e.get("base_day", ""))[:10])).days)
        except ValueError:
            continue
    need = max(days, default=0) + 7
    return next((name for cap, name in _PERIODS if need <= cap), "max")


def _scan_prices(path: str | None = None) -> dict:
    """{SYMBOL: price} from the committed crypto scan's prices file; {} when it
    is unreadable (then only a row's own pinned base can vouch for a coin)."""
    try:
        with open(path or SCAN_PRICES, encoding="utf-8") as fh:
            prices = json.load(fh).get("prices")
    except (OSError, ValueError, AttributeError):
        return {}
    return {str(k).upper(): float(v) for k, v in (prices or {}).items()
            if isinstance(v, (int, float)) and v > 0} if isinstance(prices, dict) else {}


def crypto_identity_kwargs(want: dict) -> dict:
    """data.fetch() kwargs that make every crypto frame prove it is the coin
    the ledger row is about (audit #30).

    ANCHOR first: a row whose base was set by an IDENTITY-CHECKED frame
    (`base_identity` "ref"/"anchor") holds a real completed close of the coin
    -- (base_bar, base_close) -- and a venue's frame must reproduce it
    (exchange_data.anchor_ok); a real move since cannot fail it. A base set
    by an unchecked frame (`base_identity` "none", or a row stamped before
    the field existed) is never an anchor: it may be a same-ticker stranger,
    and anchoring on it would let the stranger vouch for itself. Else the
    REFERENCE: the committed crypto scan's price for the coin (the instrument
    the VIVEK leg scanned), against the frame's latest close at
    CRYPTO_IDENTITY_TOL. `require_identity`: a coin with neither is refused
    -- left unstamped, never priced unchecked."""
    suffix = config.MARKETS["crypto"].suffix
    prices = _scan_prices()
    refs, anchors = {}, {}
    for key, entries in want.items():
        pinned = sorted((str(e["base_bar"])[:10], float(e["base_close"])) for e in entries
                        if e.get("base_bar") and e.get("base_identity") in ("ref", "anchor")
                        and isinstance(e.get("base_close"), (int, float))
                        and e["base_close"] > 0)
        if pinned:
            anchors[key] = pinned[-1]
        sym = key[:-len(suffix)] if suffix and key.endswith(suffix) else key
        if prices.get(sym.upper()):
            refs[key] = prices[sym.upper()]
    return {"ref_prices": refs, "ref_tol": float(config.CRYPTO_IDENTITY_TOL),
            "anchors": anchors, "require_identity": True}


def fetch_frames(want: dict, today: dt.date) -> dict:
    """{want key: daily frame} for every ticker `want` asks about, each
    downloaded over a period that reaches its oldest wanted base_day (audit
    #69: a fixed '3mo' slid past it). Stocks: Yahoo `download`, the plumbing
    their scans use. Crypto: scanner.data.fetch -- the one entry point for
    crypto bars -- with the identity check armed (crypto_identity_kwargs,
    audit #30); a refused coin gets no frame and so no stamp. Shared by the
    roster ledger (edge_rosters.py), so both ledgers price the same way."""
    from scanner import data
    groups: dict[tuple, list] = {}
    for key in sorted(want):
        is_crypto = any(e.get("market") == "crypto" for e in want[key])
        groups.setdefault((is_crypto, period_for(want[key], today)), []).append(key)
    frames: dict = {}
    for (is_crypto, period), keys in sorted(groups.items()):
        if not is_crypto:
            frames.update(data.download(keys, period=period))
            continue
        kw = crypto_identity_kwargs({k: want[k] for k in keys})
        got, report = data.fetch("crypto", keys, period=period, **kw)
        got = {k: f for k, f in got.items() if k in want}
        frames.update(got)
        refused = set(report.get("refused") or ())
        print(f"crypto ({period}): {len(got)}/{len(keys)} priced via data.fetch "
              f"{report.get('by_source') or {}}, identity armed "
              f"({len(kw['anchors'])} anchored, {len(kw['ref_prices'])} referenced)")
        for label, miss in (("no source proved it is the coin the row is about",
                             sorted(k for k in keys if k not in got and k in refused)),
                            ("no source returned bars",
                             sorted(k for k in keys if k not in got and k not in refused))):
            if miss:
                print(f"WARNING crypto: {len(miss)} coin(s) left unpriced - {label}: "
                      f"{', '.join(miss[:12])}{' ...' if len(miss) > 12 else ''}")
    return frames


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

    # Taken BEFORE the download: a bar is judged final against the clock
    # when the prices were asked for, never a later one.
    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()
    want = wanting_prices(ledger, today)
    stamped = 0
    if want:
        frames = fetch_frames(want, today)
        stamped = stamp(ledger, frames, want, now)
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
