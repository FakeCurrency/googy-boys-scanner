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

Prints ALERT_RETURNS_UNCHANGED when the run changed nothing, so the workflow
skips its commit - the reco_note pattern; a quiet day is a legitimate no-op,
which is exactly where a must-change gate would be the wrong tool.

CONTEXT ENRICHMENT (2026-08-20, batch-100): entries additionally carry, when
derivable, `sector` (day-independent; backfilled), `breadth200` (the market's
above-200-day share ON base_day — blank since the 2026-09-20 REGIME removal), and
- same-day scans only, because a later day's grade stamped backwards would be
look-ahead - the VIVEK leg's `grade_raw`, `score`, `is_product`. All stamps
are BLANK-ONLY and frozen once written, exactly like the returns.

GOING FORWARD (REFINE200, 2026-10-14) - every change below applies to NEW
stamps only; no existing row is rewritten or re-stamped (that is the owner's
call, REFINE200 #30):
  * the VIVEK context is COPIED from the history entry, where
    confluence_alert stamps it at the moment the alignment is seen (#139);
    the same-day scan join above remains the fallback;
  * a Saturday/Sunday alert on a stock market is filed under the Monday
    session whose close was always its base (#140) - one row, not a weekend
    copy of Monday's;
  * every stamp records `stamped_at` (UTC, the clock finality was judged
    on), a new base records `base_bar` (the bar's date) and `price_source`;
  * every new horizon stamp also stamps `bench` - the market benchmark
    (config.ALERT_RETURNS_BENCHMARK) between the same two bar dates (#28);
  * the base bar must sit within ALERT_RETURNS_BASE_MAX_GAP_DAYS of base_day,
    and the download reaches back past each symbol's oldest wanted base_day,
    so a suspended name that resumes is never measured off the window's
    first bar;
  * crypto prices through data.fetch with the identity check against the
    crypto scan's own prices, never Yahoo's same-ticker strangers;
  * the frames this run downloaded are handed to edge_rosters.py
    (--frames-out), so one walk prices both ledgers.

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
CRYPTO_PRICES = os.path.join(ROOT, "public", "data", "crypto_prices.json")

HORIZONS = tuple(getattr(config, "ALERT_RETURNS_HORIZONS", (1, 5, 10, 20)))
CAP = int(getattr(config, "ALERT_RETURNS_CAP", 20000))
BENCH = dict(config.ALERT_RETURNS_BENCHMARK)
MAX_GAP = int(config.ALERT_RETURNS_BASE_MAX_GAP_DAYS)
FRAMES_MAX_AGE_H = float(config.ALERT_RETURNS_FRAMES_MAX_AGE_H)
CONTEXT_KEYS = ("grade_raw", "score", "is_product")
# An entry whose horizons still have holes this long after base_day is almost
# certainly a delisting/suspension — count it out loud (survivorship is a bias
# only when it is silent), keep retrying anyway (retries are cheap).
STALE_UNMATURED_DAYS = 40
# yfinance-valid periods by the calendar days they reliably cover.
_PERIODS = ((88, "3mo"), (180, "6mo"), (360, "1y"), (720, "2y"))


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


def session_market(market: str) -> bool:
    """A market with a session (config.VIVEK_JOURNAL_SESSION), i.e. one that
    is shut at the weekend. Crypto and unknown markets trade every day."""
    return config.VIVEK_JOURNAL_SESSION.get(market) is not None


def base_day_for(day: str, market: str) -> str:
    """The session whose close is an alert's base. A Saturday/Sunday alert on
    a stock market (the nightly PhaseMap -> confluence pass) rolls FORWARD to
    Monday - the bar stamp() always measured it from - so it files as the one
    row it is, not a weekend copy of Monday's (REFINE200 #140)."""
    if not session_market(market):
        return day
    try:
        d = dt.date.fromisoformat(str(day)[:10])
    except ValueError:
        return day
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d.isoformat()


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
    """Copy alignments the ledger has not seen. Returns how many were new.

    The identity check reads BOTH the raw alert-day key and the rolled
    session key, so an older weekend row (filed under its raw day before the
    roll existed) is never ingested a second time under Monday's key."""
    have = {e.get("key") for e in ledger["entries"]}
    added = 0
    for e in history_entries or []:
        if not (e.get("ticker") and e.get("market")):
            continue
        raw = entry_key(e)
        day = _market_day(e.get("date", ""), e.get("market", ""))
        base = base_day_for(day, e["market"])
        k = raw if base == day else "|".join([base] + raw.split("|")[1:])
        if raw in have or k in have:
            continue
        have.update((raw, k))
        row = {
            "key": k,
            "date": e.get("date"),
            "market": e.get("market"),
            "ticker": e.get("ticker"),
            "side": e.get("side"),
            "count": e.get("count"),
            "lenses": e.get("lenses"),
            "base_day": base,
            "base_close": None,
            "fwd": {str(h): None for h in HORIZONS},
        }
        if base != day:
            row["alert_day"] = day
        # The VIVEK context confluence stamped at the moment it saw the
        # alignment (REFINE200 #139): same session, no look-ahead.
        for c in CONTEXT_KEYS:
            if e.get(c) is not None:
                row[c] = e[c]
        ledger["entries"].append(row)
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
            for k in CONTEXT_KEYS:
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


# ── prices: one walk, every market on its own plumbing ───────────────────────

def period_for(days: int) -> str:
    """The shortest yfinance period that covers `days` calendar days."""
    for cap, name in _PERIODS:
        if days <= cap:
            return name
    return "5y"


def _period_rank(name) -> int:
    names = [n for _, n in _PERIODS] + ["5y"]
    return names.index(name) if name in names else -1


def _crypto_refs(syms) -> dict:
    """{yahoo-spelled coin: price} from the crypto scan's own slim prices
    (public/data/crypto_prices.json - identity-checked exchange closes). The
    reference that keeps a same-ticker stranger out of the ledger: the scan
    stopped trusting Yahoo's <SYM>-USD on 2026-09-28 (JUP priced ~$0.0003)."""
    try:
        with open(CRYPTO_PRICES, encoding="utf-8") as fh:
            prices = json.load(fh).get("prices") or {}
    except (OSError, ValueError, AttributeError):
        prices = {}
    sfx = config.MARKETS["crypto"].suffix
    out = {}
    for s in syms:
        p = prices.get(s[:-len(sfx)] if sfx and s.endswith(sfx) else s)
        if isinstance(p, (int, float)) and p > 0:
            out[s] = float(p)
    return out


def price_frames(want: dict, today: dt.date, have: dict | None = None,
                 have_periods: dict | None = None) -> tuple[dict, dict]:
    """({symbol: daily frame}, {symbol: period}) for every wanted symbol plus
    each wanted market's benchmark.

    Each symbol's window reaches back past its OLDEST wanted base_day (with
    room for a weekend and a holiday), bucketed into yfinance periods, so a
    long-suspended name is never measured off a window that starts after its
    base. Stocks download from Yahoo; crypto goes through data.fetch - the
    entry point every crypto price takes - with the identity check armed
    against the crypto scan's own prices and REQUIRED (a coin nothing vouches
    for stays unstamped and is retried, never priced as a stranger). `have`
    is a hand-off already downloaded in this job: a frame there is reused when
    its period covers the window."""
    from scanner import data
    have, have_periods = have or {}, have_periods or {}
    need: dict = {}                                   # sym -> (market, days)
    for sym, entries in want.items():
        days = []
        for e in entries:
            try:
                days.append((today - dt.date.fromisoformat(str(e.get("base_day", ""))[:10])).days)
            except ValueError:
                continue
        if days:
            need[sym] = (entries[0].get("market"), max(days) + 2 * MAX_GAP)
    for m in sorted({mk for mk, _ in need.values()}):
        b = BENCH.get(m)
        if b:
            span = max(d for mk, d in need.values() if mk == m)
            need[b] = (m, max(span, need.get(b, (m, 0))[1]))
    frames, periods, groups = {}, {}, {}
    for sym, (m, days) in need.items():
        period = period_for(days)
        if sym in have and _period_rank(have_periods.get(sym)) >= _period_rank(period):
            frames[sym], periods[sym] = have[sym], have_periods[sym]
            continue
        groups.setdefault(("crypto" if m == "crypto" else "stock", period), []).append(sym)
    for (kind, period), syms in sorted(groups.items()):
        syms = sorted(syms)
        if kind == "crypto":
            got, rep = data.fetch("crypto", syms, period=period,
                                  ref_prices=_crypto_refs(syms),
                                  ref_tol=float(config.CRYPTO_IDENTITY_TOL),
                                  require_identity=True)
            if rep.get("refused"):
                print(f"crypto identity refused (left unstamped): {', '.join(rep['refused'][:20])}")
        else:
            got = data.download(syms, period=period)
        for s, f in (got or {}).items():
            frames[s], periods[s] = f, period
    return frames, periods


def save_frames(frames_path: str, frames: dict, periods: dict, now: dt.datetime) -> None:
    """The hand-off edge_rosters.py reads (--frames-in): dates + closes only,
    stamped with the clock finality is judged on (taken BEFORE the download)."""
    payload = {"schema_version": 1,
               "fetched_at": now.astimezone(dt.timezone.utc).isoformat(timespec="seconds"),
               "frames": {}}
    for sym, df in frames.items():
        try:
            payload["frames"][sym] = {
                "period": periods.get(sym),
                "source": (getattr(df, "attrs", None) or {}).get("source"),
                "d": [(d.date() if hasattr(d, "date") else d).isoformat() for d in df.index],
                "c": [float(c) for c in df["Close"]],
            }
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    output.write_json(frames_path, payload, indent=None, separators=(",", ":"))


def load_frames(frames_path: str, now: dt.datetime) -> tuple[dict, dict, dt.datetime | None]:
    """(frames, periods, fetched_at) from a same-job hand-off, or ({}, {},
    None) when it is missing, unreadable, from the future or older than
    ALERT_RETURNS_FRAMES_MAX_AGE_H - a stale hand-off is a fresh download."""
    import pandas as pd
    try:
        with open(frames_path, encoding="utf-8") as fh:
            d = json.load(fh)
        at = dt.datetime.fromisoformat(d["fetched_at"])
        if at.tzinfo is None:
            at = at.replace(tzinfo=dt.timezone.utc)
    except (OSError, ValueError, KeyError, TypeError):
        return {}, {}, None
    age_h = (now - at).total_seconds() / 3600
    if not (0 <= age_h <= FRAMES_MAX_AGE_H):
        print(f"frames hand-off ignored ({age_h:.1f}h old)")
        return {}, {}, None
    frames, periods = {}, {}
    for sym, f in (d.get("frames") or {}).items():
        try:
            df = pd.DataFrame({"Close": [float(c) for c in f["c"]]},
                              index=pd.to_datetime(list(f["d"])))
        except (KeyError, TypeError, ValueError):
            continue
        if f.get("source"):
            df.attrs["source"] = f["source"]
        frames[sym], periods[sym] = df, f.get("period")
    return frames, periods, at


# ── stamping ─────────────────────────────────────────────────────────────────

def _bar_days(df) -> list:
    return [d.date() if hasattr(d, "date") else d for d in df.index]


def _base_index(e: dict, days: list, done: int, base_day: dt.date) -> int | None:
    """The row's base bar among the completed bars, or None (retry later).

    A row that recorded its `base_bar` finds THAT bar. Otherwise the base is
    the first bar on/after base_day - but only within MAX_GAP calendar days of
    it: a longer gap is a suspension, or a window that never reached back to
    base_day, and its first bar is not this row's base (REFINE200)."""
    bb = e.get("base_bar")
    if bb:
        try:
            d = dt.date.fromisoformat(str(bb)[:10])
        except ValueError:
            return None
        return next((i for i, x in enumerate(days[:done]) if x == d), None)
    bi = next((i for i, x in enumerate(days[:done]) if x >= base_day), None)
    if bi is None or (days[bi] - base_day).days > MAX_GAP:
        return None
    return bi


def _bench_closes(frames: dict, market: str, cache: dict) -> dict:
    """{bar date: close} of the market's benchmark frame (cached per call)."""
    if market not in cache:
        df = frames.get(BENCH.get(market, ""))
        out = {}
        if df is not None and not getattr(df, "empty", True):
            for d, c in zip(_bar_days(df), df["Close"]):
                try:
                    if float(c) > 0:
                        out[d] = float(c)
                except (TypeError, ValueError):
                    continue
        cache[market] = out
    return cache[market]


def _stamp_time(e: dict, key: str, iso: str) -> None:
    e.setdefault("stamped_at", {})[key] = iso


def stamp(ledger: dict, frames: dict, want: dict, now: dt.datetime | None = None) -> int:
    """Fill matured horizons from downloaded daily bars. Returns stamps made.

    base = the first bar ON or AFTER base_day (an alert fires during its own
    session, so this is normally that session's close); horizon N = the close
    N bars later. Only COMPLETED bars count: a bar dated on/after
    final_bar_cutoff(market, now) may still be forming, and a base or horizon
    read from it would freeze an intraday price for good. A missing frame, a
    not-yet-existing bar or a still-forming one leaves the horizon None for
    the next run.

    Returns are read off ONE frame - its base close and its horizon close -
    because Yahoo's closes are dividend-adjusted (auto_adjust): the ratio is
    the total return, where a stored base against a later-adjusted horizon
    would not be. The stored base_close is never rewritten.

    Every NEW stamp records `stamped_at` (REFINE200 #30); a new base records
    `base_bar` and `price_source`; every horizon stamped under this regime
    owes a `bench` - the market benchmark between the same two bar dates
    (#28), measured when the horizon is, or retried while the row is still
    being priced."""
    now = now or dt.datetime.now(dt.timezone.utc)
    iso = now.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
    bench_cache: dict = {}
    stamped = 0
    for sym, entries in want.items():
        df = frames.get(sym)
        if df is None or getattr(df, "empty", True):
            continue
        closes = df["Close"]
        days = _bar_days(df)
        for e in entries:
            try:
                base_day = dt.date.fromisoformat(e["base_day"])
            except (KeyError, ValueError):
                continue
            market = e.get("market", "")
            cutoff = final_bar_cutoff(market, now)
            done = sum(1 for d in days if d < cutoff)    # bars are date-ascending
            bi = _base_index(e, days, done, base_day)
            if bi is None:
                continue
            base_close = float(closes.iloc[bi])
            if not (base_close > 0):
                continue
            if e.get("base_close") is None:
                e["base_close"] = round(base_close, 8)
                e["base_bar"] = days[bi].isoformat()
                e["price_source"] = str((getattr(df, "attrs", None) or {}).get("source") or "yahoo")
                _stamp_time(e, "base", iso)
                stamped += 1        # recording the baseline is itself a change
            for h in HORIZONS:
                key = str(h)
                if bi + h >= done:
                    continue
                if e["fwd"].get(key) is None:
                    e["fwd"][key] = round(float(closes.iloc[bi + h]) / base_close - 1.0, 6)
                    _stamp_time(e, key, iso)
                    stamped += 1
                if key in (e.get("stamped_at") or {}) and (e.get("bench") or {}).get(key) is None:
                    b = _bench_closes(frames, market, bench_cache)
                    c0, ch = b.get(days[bi]), b.get(days[bi + h])
                    if c0 and ch:
                        e.setdefault("bench", {})[key] = round(ch / c0 - 1.0, 6)
                        stamped += 1
    return stamped


def trim(ledger: dict, cap: int | None = None) -> int:
    """Drop the OLDEST fully-stamped entries past the cap - never an entry
    still waiting on a horizon (dropping those silently un-measures the
    feature). `cap` defaults to the ledger's own. (edge_rosters.py used to
    reuse this with a roster cap; since REFINE200 #62 it never trims.)"""
    cap = CAP if cap is None else cap
    entries = ledger["entries"]
    if len(entries) <= cap:
        return 0
    done = [e for e in entries if all(e["fwd"].get(str(h)) is not None for h in HORIZONS)]
    excess = len(entries) - cap
    drop = {id(e) for e in sorted(done, key=lambda e: e.get("base_day", ""))[:excess]}
    ledger["entries"] = [e for e in entries if id(e) not in drop]
    return len(drop)


def arg_value(argv, flag):
    """The value after `flag` in argv, or None."""
    if flag in argv:
        i = argv.index(flag) + 1
        return argv[i] if i < len(argv) else None
    return None


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    dry = "--dry-run" in argv
    frames_out = arg_value(argv, "--frames-out")

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
        frames, periods = price_frames(want, today)
        stamped = stamp(ledger, frames, want, now)
        if frames_out and not dry:
            save_frames(frames_out, frames, periods, now)
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
    benched = sum(1 for e in entries if any(v is not None for v in (e.get("bench") or {}).values()))
    print(f"maturity: {per_h}")
    print(f"stale-unmatured (>{STALE_UNMATURED_DAYS}d, likely delisted - retried anyway): {stale}")
    print(f"triple-lens cohort: {len(triples)} tracked, {trip_m} matured at 5s")
    print(f"benchmarked rows (excess returns): {benched}/{n}")

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
