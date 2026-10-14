#!/usr/bin/env python3
"""Daily A+ roster ledger — the single-lens BASELINE cohort (batch-100 WS-B).

The confluence ledger answers "how do ALIGNED alerts do"; this file answers
the half every comparison needs: how do plain grade_raw A+ setups do, on the
SAME price plumbing and the same 1/5/10/20-session horizons. The
2026-08-20 edge batch had to reconstruct this baseline from git history of
scan snapshots; from today it simply accrues.

Each run copies each finished session's A+ rows (grade_raw, both directions)
into the ledger with the context the edge questions need frozen at entry:
score, STRONG STRUCTURE chip, the High-conviction condition (IMPORTED from
scanner/conviction.py) and the rule it was judged under (`hc_rule`), sector,
is_product, and the market's breadth on that day. Forward returns are
stamped by the exact machinery the alert ledger uses (imported from
alert_returns.py, never re-typed): frozen at first measurement, right-
censored until mature.

WHICH SCAN IS A SESSION'S ROSTER (REFINE200, 2026-10-14). It used to be
whatever <m>_vivek.json was on disk when the late cron landed - on 2026-10-14
the ASX cohort was a 12:15 mid-session list, and crypto's day flipped inside
the landing window (five missing days). Now each session's roster is the scan
in force at its CLOSE, read from git history (alert_returns.yml fetches the
window): stocks take the newest scan stamped at/after the digest's post-close
line (config.MORNING_PLAYS_SLOT_GATE), crypto the last scan of a finished UTC
day. A session whose close scan has not landed waits for the next run; one the
market has moved past without one takes its last scan. A session already in
the ledger is never re-read, and a stock scan is filed under the session whose
DATA it holds - never a Saturday/Sunday (#140). Without history (a local run)
the file on disk is used only when it qualifies by the same rule.

NO CAP, SHARDED BY MONTH (REFINE200 #62). The 20k cap would have started
DELETING measured rows in ~December. Rows live in data/edge_rosters/
<YYYY-MM>.json by base_day month (a month stops changing once its rows mature)
and data/edge_rosters.json is the manifest: updated_at (the workflow's
backstop gate reads it), the layout and per-month counts. The first run
splits the old single file into shards, rows copied unchanged. Nothing is ever
trimmed; an unreadable shard stops the run rather than rewriting its month.

RESEARCH ONLY: reads committed artefacts, writes ONLY its own ledger; nothing
in scanner/ or broker/ reads it back (test-pinned). Prints
EDGE_ROSTERS_UNCHANGED when a run changed nothing so the workflow can skip
its commit. ASCII-only prints; atomic writes via scanner.output.write_json.
"""
import datetime as dt
import glob
import importlib.util
import json
import os
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scanner import config, conviction, output                      # noqa: E402

# The stamping machinery is IMPORTED from the alert ledger (mirror-drift rule:
# two forward-return implementations would diverge exactly when it matters).
_spec = importlib.util.spec_from_file_location(
    "alert_returns", os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_returns.py"))
ar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ar)

LEDGER = os.path.join(ROOT, "data", "edge_rosters.json")      # the manifest (v1 held every row)
HORIZONS = ar.HORIZONS
MARKETS = ("asx", "nasdaq", "crypto")
LOOKBACK_DAYS = int(config.ALERT_ROSTER_LOOKBACK_DAYS)
SCAN_PATH = "public/data/{}_vivek.json"
# The digest's own "this scan is post-close" line, per market.
POST_CLOSE = {g["market"]: (int(g["hour"]), int(g["minute"]))
              for g in config.MORNING_PLAYS_SLOT_GATE.values()}


# ── storage: monthly shards + a manifest ─────────────────────────────────────

def _shard_dir(path: str) -> str:
    return os.path.splitext(path)[0]


def _fresh() -> dict:
    return {"schema_version": 2, "updated_at": "", "entries": []}


def load_ledger(path: str | None = None) -> dict:
    """Every roster row, from the monthly shards plus any rows a v1 single
    file still holds (the pre-shard layout; the next write migrates them).
    An unreadable shard is NOT a fresh start: it is reported in
    `unreadable` and main() refuses to write, so a month is never rewritten
    from what little survived."""
    path = path or LEDGER
    led = _fresh()
    led["unreadable"] = []
    keys = set()
    for sp in sorted(glob.glob(os.path.join(_shard_dir(path), "*.json"))):
        try:
            with open(sp, encoding="utf-8") as fh:
                rows = json.load(fh)["entries"]
            if not isinstance(rows, list):
                raise ValueError("entries is not a list")
        except (OSError, ValueError, KeyError, TypeError) as e:
            print(f"WARNING roster shard unreadable: {os.path.basename(sp)}: {e.__class__.__name__}")
            led["unreadable"].append(sp)
            continue
        for r in rows:
            led["entries"].append(r)
            keys.add(r.get("key"))
    try:
        with open(path, encoding="utf-8") as fh:
            head = json.load(fh)
    except FileNotFoundError:
        head = {}
    except (OSError, ValueError):
        print("WARNING roster manifest unreadable - shards only")
        head = {}
    if isinstance(head, dict):
        led["updated_at"] = head.get("updated_at") or ""
        legacy = head.get("entries") if isinstance(head.get("entries"), list) else []
        led["migrate"] = bool(legacy)
        for r in legacy:
            if r.get("key") not in keys:
                led["entries"].append(r)
                keys.add(r.get("key"))
    return led


def _month(e: dict) -> str:
    m = str(e.get("base_day") or "")[:7]
    return m if len(m) == 7 and m[4] == "-" else "unknown"


def write_ledger(ledger: dict, path: str | None = None, now: dt.datetime | None = None) -> int:
    """Write every month whose rows changed (an unchanged month's file is left
    byte-identical) and the manifest. Returns the number of shards written."""
    path = path or LEDGER
    now = now or dt.datetime.now(dt.timezone.utc)
    stamp = now.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
    by_month: dict = {}
    for e in ledger["entries"]:
        by_month.setdefault(_month(e), []).append(e)
    written = 0
    for month, rows in sorted(by_month.items()):
        sp = os.path.join(_shard_dir(path), f"{month}.json")
        try:
            with open(sp, encoding="utf-8") as fh:
                if json.load(fh).get("entries") == rows:
                    continue
        except (OSError, ValueError, AttributeError):
            pass
        output.write_json(sp, {"schema_version": 2, "month": month, "updated_at": stamp,
                               "entries": rows}, indent=1)
        written += 1
    output.write_json(path, {
        "schema_version": 2,
        "updated_at": stamp,
        "layout": "rows live in data/edge_rosters/<YYYY-MM>.json by base_day month; "
                  "this file is the manifest (no rows, nothing trimmed)",
        "shards": {m: len(r) for m, r in sorted(by_month.items())},
        "rows": len(ledger["entries"]),
    }, indent=1)
    return written


# ── which scan is a session's roster ─────────────────────────────────────────

def _parse(iso) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _tz(market: str) -> ZoneInfo:
    return ZoneInfo(config.MARKETS[market].timezone if market in config.MARKETS else "UTC")


def session_of(stamp: dt.datetime, market: str) -> dt.date:
    """The session whose DATA a scan stamped at `stamp` holds: the market-
    local day, except that a stamp before the open, or on a weekend, belongs
    to the previous weekday's session. Crypto: the UTC day."""
    local = stamp.astimezone(_tz(market))
    sess = config.VIVEK_JOURNAL_SESSION.get(market)
    d = local.date()
    if sess is None:
        return d
    if (local.hour, local.minute) < (sess[0], sess[1]):
        d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def post_close(stamp: dt.datetime, market: str, day: dt.date) -> bool:
    """Was this scan of session `day` taken at/after its close line? (A 24/7
    market has none: its day is over only once the next one starts.)"""
    gate = POST_CLOSE.get(market)
    if gate is None:
        return False
    local = stamp.astimezone(_tz(market))
    return local.date() > day or (local.date() == day and (local.hour, local.minute) >= gate)


def _git(*args: str) -> str | None:
    try:
        p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def _history_ref() -> str | None:
    """origin/main when it resolves (the workflow fetches it), else HEAD -
    and None unless ROOT is the top of its own git checkout (a scratch dir
    inside some other repo must not read that repo's history)."""
    top = _git("rev-parse", "--show-toplevel")
    if not top or os.path.realpath(top.strip()) != os.path.realpath(ROOT):
        return None
    return "origin/main" if _git("rev-parse", "--verify", "-q", "origin/main") else "HEAD"


def _scan_versions(market: str, since: dt.datetime, ref: str) -> list:
    """[(sha, commit time)] of the market's scan file, newest first."""
    out = _git("log", f"--since={since.isoformat()}", "--format=%H %ct", ref, "--",
               SCAN_PATH.format(market)) or ""
    vs = []
    for line in out.splitlines():
        try:
            sha, ts = line.split()
            vs.append((sha, dt.datetime.fromtimestamp(int(ts), dt.timezone.utc)))
        except ValueError:
            continue
    return vs


def _scan_at(sha: str, market: str) -> dict | None:
    raw = _git("show", f"{sha}:{SCAN_PATH.format(market)}")
    try:
        d = json.loads(raw) if raw else None
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def _qualifies(gen: dt.datetime, market: str, day: dt.date, now: dt.datetime) -> bool:
    """A session's newest scan is its roster once it is post-close, or once
    the market has moved past the session without a post-close scan."""
    return post_close(gen, market, day) or session_of(now, market) > day


def session_snapshots(market: str, now: dt.datetime) -> list | None:
    """[(session day, scan, generated_at)] for the finished sessions inside
    the lookback, oldest first, each the newest scan of its session; None
    when no git history is readable (the caller falls back to the disk)."""
    ref = _history_ref()
    if ref is None:
        return None
    since = now - dt.timedelta(days=LOOKBACK_DAYS + 1)
    versions = _scan_versions(market, since, ref)
    if not versions:
        return None
    first = (now - dt.timedelta(days=LOOKBACK_DAYS)).astimezone(_tz(market)).date()
    best: dict = {}
    seen_commit_days = set()
    for sha, committed in versions:                 # newest first
        cday = session_of(committed, market)
        if cday in seen_commit_days and cday in best:
            continue                                # its session is already decided
        seen_commit_days.add(cday)
        scan = _scan_at(sha, market)
        gen = _parse((scan or {}).get("generated_at"))
        if gen is None:
            continue
        day = session_of(gen, market)
        if day not in best:
            best[day] = (scan, gen)
    return [(d, s, g) for d, (s, g) in sorted(best.items())
            if d >= first and _qualifies(g, market, d, now)]


def _disk_snapshot(market: str, now: dt.datetime) -> list:
    try:
        with open(os.path.join(ROOT, *SCAN_PATH.format(market).split("/")), encoding="utf-8") as fh:
            scan = json.load(fh)
    except (OSError, ValueError):
        print(f"WARNING {market} scan unreadable - roster skipped for this market")
        return []
    gen = _parse(scan.get("generated_at"))
    if gen is None:
        return []
    day = session_of(gen, market)
    return [(day, scan, gen)] if _qualifies(gen, market, day, now) else []


# ── rows ─────────────────────────────────────────────────────────────────────

def high_conviction(row: dict) -> bool:
    """The SAME condition the deck applies — IMPORTED from scanner/conviction.py
    (1W reclaim/break, 3D reclaim, 1D break; armed; grade A/A+), so the tag's
    forward returns are measured against the tag as displayed."""
    return conviction.is_high_conviction(row)


def hc_rule() -> str:
    """The High-conviction rule a row's `hiconv` was judged under, DERIVED from
    the imported table so it moves when the rule does. The rule changed on
    2026-09-20 (one 1W-reclaim cell + a structure branch -> four cells) and
    rows before that carried no stamp; readers split on this."""
    cells = ";".join(f"{tf}:{'/'.join(trigs)}" for tf, trigs in conviction.HC_CELLS.items())
    return f"cells={cells} grades={'/'.join(conviction.HC_GRADES)}"


def roster_rows(scan: dict, market: str, day: str | None = None) -> list[dict]:
    """A session's A+ cohort from one committed scan payload. `day` is the
    session it is filed under (default: the session its stamp holds)."""
    gen = _parse(scan.get("generated_at"))
    if day is None:
        day = session_of(gen, market).isoformat() if gen else str(scan.get("generated_at", ""))[:10]
    rule = hc_rule()
    out = []
    for r in scan.get("results") or []:
        if r.get("grade_raw") != "A+" or not r.get("symbol"):
            continue
        side = "short" if str(r.get("dir", "LONG")).upper() == "SHORT" else "long"
        out.append({
            "key": f"{day}|{market}|{r['symbol']}|{side}",
            "market": market,
            "ticker": r["symbol"],
            "side": side,
            "base_day": day,
            "grade_raw": r.get("grade_raw"),
            "score": r.get("score"),
            "strong": "STRONG STRUCTURE" in (r.get("chips") or []),
            "hiconv": high_conviction(r),
            "hc_rule": rule,
            "sector": (r.get("sector") or "").strip() or None,
            "is_product": r.get("is_product"),
            "snapshot_at": scan.get("generated_at"),
            "base_close": None,
            "fwd": {str(h): None for h in HORIZONS},
        })
    return out


def ingest_today(ledger: dict, now: dt.datetime | None = None) -> int:
    """Copy each finished session's A+ rows in, once per session: a session
    that already has rows is never re-read (a second snapshot of one day
    would file a union of two lists)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    have = {e.get("key") for e in ledger["entries"]}
    filed = {(e.get("market"), e.get("base_day")) for e in ledger["entries"]}
    breadth = ar._breadth_series()
    added = 0
    for m in MARKETS:
        snaps = session_snapshots(m, now)
        if snaps is None:
            snaps = _disk_snapshot(m, now)
        for day, scan, gen in snaps:
            iso = day.isoformat()
            if (m, iso) in filed:
                continue
            filed.add((m, iso))
            for row in roster_rows(scan, m, day=iso):
                if row["key"] in have:
                    continue
                have.add(row["key"])
                b = breadth.get(m, {}).get(row["base_day"])
                if b is not None:
                    row["breadth200"] = round(float(b), 4)
                ledger["entries"].append(row)
                added += 1
    return added


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    dry = "--dry-run" in argv
    frames_in = ar.arg_value(argv, "--frames-in")

    ledger = load_ledger()
    if ledger.get("unreadable"):
        print("ERROR roster shard(s) unreadable - refusing to write over them")
        return 2
    # Taken BEFORE the download: a bar is judged final against the clock
    # when the prices were asked for, never a later one. A hand-off from
    # alert_returns.py was fetched EARLIER, so its clock wins: a frame is
    # final only as of the moment it was downloaded.
    now = dt.datetime.now(dt.timezone.utc)
    have, have_periods, fetched = ar.load_frames(frames_in, now) if frames_in else ({}, {}, None)
    added = ingest_today(ledger, now)
    if fetched is not None:
        now = min(now, fetched)
    today = now.date()
    want = ar.wanting_prices(ledger, today)
    stamped = 0
    if want:
        frames, _ = ar.price_frames(want, today, have=have, have_periods=have_periods)
        stamped = ar.stamp(ledger, frames, want, now)
    migrated = bool(ledger.get("migrate"))

    entries = ledger["entries"]
    per_h = " · ".join(f"{h}s {sum(1 for e in entries if e['fwd'].get(str(h)) is not None)}/{len(entries)}"
                       for h in HORIZONS)
    print(f"edge rosters: +{added} ingested, +{stamped} stamps; {len(entries)} tracked "
          f"(no cap - monthly shards){' - migrating the single file to shards' if migrated else ''}")
    print(f"roster maturity: {per_h}")

    if not (added or stamped or migrated):
        print("EDGE_ROSTERS_UNCHANGED")
        return 0
    if dry:
        print("dry run - not writing")
        return 0
    write_ledger(ledger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
