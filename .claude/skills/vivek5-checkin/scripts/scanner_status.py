#!/usr/bin/env python3
"""Vivek 5.0 check-in: everything the REPO can say about the scanner, in
Melbourne time, with a verdict list at the end. Read-only.

    python3 scanner_status.py                    # fetches origin/main first
    python3 scanner_status.py --since "2026-10-08 09:00 +1100"
    python3 scanner_status.py --rev <sha> --now 2026-10-06T16:20:00+11:00   # replay a past moment

It answers from committed files only (origin/main by default): scan stamps,
the funnel ledger, lens files, the paper book and its git history, the
confluence log and backups. It does NOT see GitHub run results, the digest's
Discord post, cron-job.org or the live site; the skill covers those.

Stdlib only. Every stamp is converted to Melbourne before it is compared:
the files mix Sydney, New York, UTC and Melbourne offsets.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from zoneinfo import ZoneInfo

MEL = ZoneInfo("Australia/Melbourne")
SYD = ZoneInfo("Australia/Sydney")
NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc

# Copied from scanner/config.py (MARKET_SCAN_WINDOWS, MORNING_PLAYS_SLOT_GATE,
# VIVEK_JOURNAL_SESSION) and scanner/momentum/config.py (PUBLISH_AFTER_CLOSE_MIN,
# CRYPTO_DUE_UTC). tests/test_vivek5_checkin.py fails if config moves and these
# do not; the script stays stdlib-only so it runs with `python3 -I` anywhere.
WINDOW = {"asx": ((11, 0), (16, 45), SYD), "nasdaq": ((10, 30), (16, 45), NY)}
CLOSE_GATE = {"asx": (16, 40), "nasdaq": (16, 5)}
GAP_FLAG_MIN = 80          # hourly pings: a gap longer than this inside a session is a miss
CRYPTO_GAP_FLAG_MIN = 120  # crypto pings hourly at :22; one ~100 min gap is normal
MOMENTUM_OWE = {"asx": ((16, 30), SYD), "nasdaq": ((16, 30), NY)}  # session close + 30 min
MOMENTUM_CRYPTO_DUE_UTC = (0, 30)  # crypto: daily, UTC

REPO = "."
REV = "origin/main"


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True, check=True).stdout


def load(path: str, rev: str | None = None):
    try:
        return json.loads(git("show", f"{rev or REV}:{path}"))
    except subprocess.CalledProcessError:
        return None


def ts(s) -> dt.datetime:
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def mel(t: dt.datetime, fmt: str = "%a %H:%M") -> str:
    return t.astimezone(MEL).strftime(fmt)


def ago(t: dt.datetime, now: dt.datetime) -> str:
    m = (now - t).total_seconds() / 60
    if m < 90:
        return f"{m:.0f} min ago"
    if m < 48 * 60:
        return f"{m / 60:.1f} h ago"
    return f"{m / 1440:.1f} days ago"


def dur(t: dt.datetime, now: dt.datetime) -> str:
    return ago(t, now).replace(" ago", "")


def at(day: dt.date, hm: tuple[int, int], tz) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(*hm), tz)


def last_weekday_at(now: dt.datetime, hm, tz) -> dt.datetime:
    """The most recent weekday moment hm (in tz) that is at or before now."""
    d = now.astimezone(tz).date()
    for _ in range(8):
        cand = at(d, hm, tz)
        if d.weekday() < 5 and cand <= now:
            return cand
        d -= dt.timedelta(days=1)
    return at(d, hm, tz)


def in_window(m: str, t: dt.datetime) -> bool:
    (h0, h1, tz) = WINDOW[m]
    lt = t.astimezone(tz)
    return lt.weekday() < 5 and h0 <= (lt.hour, lt.minute) <= h1


FLAGS: list[str] = []      # looks wrong
WAITING: list[str] = []    # not due yet / normal lag worth saying out loud


def section(title: str) -> None:
    print(f"\n== {title}")


# ---------------------------------------------------------------------------
def scans(now: dt.datetime) -> None:
    section("SCANS (Melbourne time; trigger h = cron-job.org heartbeat, c = GitHub cron, m = manual)")
    fh = load("public/data/funnel_history.json") or {"markets": {}}
    health = load("data/scan_health.json") or {}
    for m in ("asx", "nasdaq", "crypto"):
        col = fh["markets"].get(m) or {"t": [], "trigger": []}
        trig = col.get("trigger") or []
        off = len(col["t"]) - len(trig)          # align from the END if lengths differ
        rows = [(ts(x), (trig[i - off] if 0 <= i - off < len(trig) else "") or "?")
                for i, x in enumerate(col["t"])]
        prices = load(f"public/data/{m}_prices.json") or {}
        vivek_meta = {}
        last = ts(prices["generated_at"]) if prices.get("generated_at") else None
        dry = (health.get(m) or {}).get("dry", 0)
        if m == "crypto":
            recent = [(t, k) for t, k in rows if now - t <= dt.timedelta(hours=24)]
            gaps = [(b[0] - a[0]).total_seconds() / 60 for a, b in zip(recent, recent[1:])]
            big = [f"{mel(recent[i][0])}->{mel(recent[i + 1][0])} ({g:.0f} min)"
                   for i, g in enumerate(gaps) if g > CRYPTO_GAP_FLAG_MIN]
            kinds = {k: sum(1 for _, x in recent if x == k) for k in sorted({x for _, x in recent})}
            print(f"crypto: {len(recent)} scans in the last 24 h {kinds}; last {mel(last) if last else '?'}"
                  f" ({ago(last, now) if last else 'never'})")
            if last and now - last > dt.timedelta(hours=2):
                FLAGS.append(f"crypto has not scanned for {dur(last, now)} (pings run hourly at :22)")
            if big:
                FLAGS.append("crypto gaps over 2 h in the last 24 h: " + ", ".join(big))
        else:
            h0, h1, tz = WINDOW[m]
            # The session the owner means: today's if it has started, else the last weekday's.
            open_today = at(now.astimezone(tz).date(), h0, tz)
            sess_day = (now.astimezone(tz).date() if now >= open_today and now.astimezone(tz).weekday() < 5
                        else last_weekday_at(now, h0, tz).astimezone(tz).date())
            close_gate = at(sess_day, CLOSE_GATE[m], tz)
            day_rows = [(t, k) for t, k in rows if t.astimezone(tz).date() == sess_day]
            lo, hi = at(sess_day, h0, tz) - dt.timedelta(minutes=30), close_gate + dt.timedelta(minutes=75)
            sess = [(t, k) for t, k in day_rows if lo <= t <= hi]
            times = " ".join(f"{mel(t, '%H:%M')}{k[0]}" for t, k in sess)
            off_hours = len(day_rows) - len(sess)
            closed_scan = next((t for t, _ in day_rows if t >= close_gate), None)  # a late catch-up still counts
            label = "ASX" if m == "asx" else "NASDAQ"
            where = "" if m == "asx" else " New York"
            print(f"{m}: the {sess_day:%a %d %b}{where} session: {len(sess)} scans [{times}]"
                  + (f" (+{off_hours} outside trading hours)" if off_hours else ""))
            # gaps inside the window, up to now or the window end
            win_end = min(now, at(sess_day, h1, tz))
            pts = [at(sess_day, h0, tz)] + [t for t, _ in sess if in_window(m, t)] + [win_end]
            gaps = [(a, b) for a, b in zip(pts, pts[1:]) if (b - a).total_seconds() / 60 > GAP_FLAG_MIN]
            if gaps:
                spans = ", ".join(f"{mel(a, '%H:%M')}-{mel(b, '%H:%M')}" for a, b in gaps)
                FLAGS.append(f"{label}: {len(gaps)} gap(s) over {GAP_FLAG_MIN} min with no scan in the "
                             f"{sess_day:%a %d %b}{where} session, Melbourne {spans} "
                             f"(hourly pings should give a scan ~5 min past each hour)")
            if closed_scan:
                print(f"    closing scan: {mel(closed_scan)} (counts from {CLOSE_GATE[m][0]:02d}:{CLOSE_GATE[m][1]:02d} "
                      f"{'Sydney' if m == 'asx' else 'New York'})")
            elif now >= close_gate + dt.timedelta(minutes=15):
                FLAGS.append(f"{label}: no closing scan for the {sess_day:%a %d %b}{where} session (nothing stamped at/after "
                             f"{CLOSE_GATE[m][0]:02d}:{CLOSE_GATE[m][1]:02d} {'Sydney' if m == 'asx' else 'New York'})")
            else:
                WAITING.append(f"{label} closing scan not due yet (from {mel(close_gate, '%H:%M')} Melbourne)")
            if not sess and now >= open_today + dt.timedelta(minutes=30) and now.astimezone(tz).weekday() < 5:
                FLAGS.append(f"{label}: no scans at all this session - public holiday, or broken? check before saying broken")
            vivek_meta = load(f"public/data/{m}_vivek.json") or {}
            if vivek_meta:
                print(f"    last scan data: {vivek_meta.get('scanned')}/{vivek_meta.get('universe_size')} names, "
                      f"{vivek_meta.get('from_cache')} from cache, {vivek_meta.get('errors')} errors, "
                      f"{(vivek_meta.get('funnel') or {}).get('setups')} setups")
        if dry:
            FLAGS.append(f"{m}: {dry} dry scan run(s) in a row (data/scan_health.json) - it ran but got no prices")


# ---------------------------------------------------------------------------
def lenses(now: dt.datetime) -> None:
    section("AFTER-CLOSE LENSES")
    for m in ("asx", "nasdaq", "crypto"):
        d = load(f"public/data/momentum/{m}.json")
        if not d:
            FLAGS.append(f"momentum {m}: file missing")
            continue
        g = ts(d["generated_at"])
        owe = (last_weekday_at(now, *MOMENTUM_OWE[m]) if m in MOMENTUM_OWE
               else (lambda c: c if c <= now else c - dt.timedelta(days=1))(
                   dt.datetime.combine(now.astimezone(UTC).date(), dt.time(*MOMENTUM_CRYPTO_DUE_UTC), UTC)))
        state = "fresh" if g >= owe else f"OWED since {mel(owe)}"
        print(f"momentum {m}: {mel(g)} ({ago(g, now)}), bar {d.get('last_closed_bar')}, "
              f"{(d.get('summary') or {}).get('hits')} hits - {state}")
        if g < owe:
            late = (now - owe).total_seconds() / 3600
            (FLAGS if late > 3 else WAITING).append(
                f"momentum {m} owed since {mel(owe)} ({late:.1f} h)" + ("" if late > 3 else " - normally lands within ~1 h"))
    ic = load("public/data/ignition/crypto.json")
    if ic:
        g = ts(ic["generated_at"])
        want = (now.astimezone(UTC) - dt.timedelta(hours=30)).date().isoformat()
        stale = (ic.get("last_closed_bar") or "") < want or now - g > dt.timedelta(hours=26)
        print(f"ignition crypto: {mel(g)} ({ago(g, now)}), newest bar {ic.get('last_closed_bar')}"
              + (" - STALE on the page" if stale else ""))
        if stale:
            FLAGS.append("ignition crypto is STALE on the page (no completed bar from UTC-yesterday)")
    ia = load("public/data/ignition/asx.json")
    if ia:
        g = ts(ia["generated_at"])
        close = last_weekday_at(now, CLOSE_GATE["asx"], SYD)
        print(f"ignition asx: {mel(g)} ({ago(g, now)}), newest bar {ia.get('last_closed_bar')}"
              + ("" if g >= close else f" - not yet screened since the {mel(close)} close"))
        if g < close:
            hrs = (now - close).total_seconds() / 3600
            (FLAGS if hrs > 10 else WAITING).append(
                f"ignition ASX not screened since the {mel(close)} close ({hrs:.1f} h)"
                + ("" if hrs > 10 else " - its GitHub cron usually lands 17:45 to past midnight"))
    pm = git("log", "-1", "--format=%cI", REV, "--", "public/data/phasemap/asx/latest.json").strip()
    if pm:
        g = ts(pm)
        rd = (load("public/data/phasemap/asx/latest.json") or {}).get("run_date")
        print(f"phasemap: last ran {mel(g, '%a %d %b %H:%M')} ({ago(g, now)}), run_date {rd}")
        if now - g > dt.timedelta(hours=30):
            FLAGS.append(f"PhaseMap last ran {ago(g, now)} (nightly; usually lands midnight to ~4am Melbourne)")
    for path, label, limit_h in (("data/alert_forward_returns.json", "edge ledgers", 30),
                                 ("public/data/reco_note.json", "reco note", 30)):
        d = load(path) or {}
        stamp = d.get("updated_at") or d.get("generated_at")
        if stamp:
            g = ts(stamp)
            print(f"{label}: {mel(g, '%a %d %b %H:%M')} ({ago(g, now)})")
            if now - g > dt.timedelta(hours=limit_h):
                FLAGS.append(f"{label} not updated for {dur(g, now)}")
    dirs = sorted(x.split("/")[-1] for x in git("ls-tree", "--name-only", REV, "backups/").split()
                  if x.split("/")[-1][:2] == "20")
    if dirs:
        n = dirs[-1]
        g = ts(n[:10] + "T" + n[11:].replace("-", ":") + "+00:00")
        print(f"backup: {mel(g, '%a %d %b %H:%M')} ({ago(g, now)}), {len(dirs)} kept")
        if now - g > dt.timedelta(hours=26):
            FLAGS.append(f"newest bot-book backup is {ago(g, now)} (limit 26 h)")


# ---------------------------------------------------------------------------
def book(now: dt.datetime, since: dt.datetime) -> None:
    section(f"PAPER BOT (changes since {mel(since, '%a %d %b %H:%M')})")
    rules = load("public/data/bot_rules.json") or {}
    cap = rules.get("max_open_total", 60)
    hold_max = rules.get("max_hold_days", 28)
    total = 0
    stalled = 0
    for m in ("asx", "nasdaq", "crypto"):
        path = f"journal/vivek_bot_book.{m}.json"
        b = load(path)
        if not b:
            FLAGS.append(f"bot book {m}: missing or unreadable")
            continue
        g = (b.get("guard") or {}).get(m) or {}
        upd = ts(b["updated_at"])
        total += len(b["open"])
        cur = "A$" if m == "asx" else "$"
        guard = (f"BREACHED ({g.get('breach_kind')}) - new entries halted, nothing sold" if g.get("breached")
                 else "clear")
        print(f"{m}: {len(b['open'])} open, last updated {mel(upd)} ({ago(upd, now)}); loss guard {guard}: "
              f"day {cur}{g.get('session_usd', 0):+,.0f} of -{cur}{g.get('limit_usd', 0):,.0f}, "
              f"week {cur}{g.get('week_usd', 0):+,.0f} of -{cur}{g.get('week_limit_usd', 0):,.0f}")
        if g.get("breached"):
            FLAGS.append(f"{m} loss guard breached ({g.get('breach_kind')}): the guard working, new entries halted for the day")
        if m == "crypto" and now - upd > dt.timedelta(hours=2):
            FLAGS.append(f"crypto bot book not updated for {dur(upd, now)}")
        # exact opens/closes since `since`, from the book's own git history
        then_sha = git("log", REV, "-1", f"--until={since.isoformat()}", "--format=%H", "--", path).strip()
        if then_sha:
            tb = load(path, then_sha) or {"open": [], "closed": []}
            was_open = {p["id"] for p in tb["open"]}
            was_closed = {t["id"] for t in tb["closed"]}
            for p in b["open"] + b["closed"]:
                if p["id"] not in was_open and p["id"] not in was_closed:
                    flag = "; ".join(f["note"] for f in p.get("review") or [])
                    print(f"    OPENED {p['symbol']} {p.get('grade')} {p.get('timeframe')} {p.get('entry_type')} "
                          f"at {p['entry']:g}, stop {p['stop']:g}" + (f" - REVIEW: {flag}" if flag else ""))
            for t in b["closed"]:
                if t["id"] not in was_closed:
                    who = "you" if t.get("exit_reason") in (None, "", "manual") else "the rules"
                    print(f"    CLOSED {t['symbol']} {t.get('exit_date')} {t.get('exit_reason') or 'by hand'} "
                          f"({who}) {t.get('realized_r', 0):+.2f}R")
        else:
            print("    (git history too shallow to diff; run git fetch --deepen=300 origin main)")
        unpriced = sorted(((p["unpriced_runs"], p["symbol"]) for p in b["open"] if p.get("unpriced_runs")),
                          reverse=True)
        if unpriced:
            FLAGS.append(f"{m}: {len(unpriced)} held name(s) had no price on the last run, so their stops were "
                         "not tested: " + ", ".join(f"{s_} ({n} run{'s' if n > 1 else ''})" for n, s_ in unpriced))
        for p in b["open"]:
            why = []
            if p.get("unpriced_runs"):
                why.append(f"NO PRICE for {p['unpriced_runs']} run(s), its stop is not being tested")
            last, stop, risk = p.get("last_mark") or p["entry"], p["stop"], p.get("risk") or 0
            if risk and (last - stop) / risk < 0.25:
                why.append(f"{(last - stop) / risk:.2f}R above its stop")
            try:
                held = (dt.date.fromisoformat(b["summary"]["updated_day"]) - dt.date.fromisoformat(p["entry_date"])).days
            except (KeyError, TypeError, ValueError):
                held = 0
            if not p.get("tp1_hit") and held >= hold_max - 3:
                why.append(f"time stop in {hold_max + 1 - held} day(s)")
            if p.get("stale_pinged"):
                stalled += 1
            if why:
                print(f"    WATCH {p['symbol']}: " + ", ".join(why))
    print(f"total: {total}/{cap} open" + (" - book FULL, new setups are skipped by design" if total >= cap else
                                            f", {cap - total} free"))
    if stalled:
        print(f"stalled (14+ days, under 0.5R either way): {stalled} positions - shown on the journal page")


# ---------------------------------------------------------------------------
def confluence(now: dt.datetime, since: dt.datetime) -> None:
    section("CONFLUENCE")
    h = load("public/data/phasemap/alert_history.json") or {}
    new = [e for e in h.get("entries") or [] if e.get("date") and ts(e["date"]) >= since]
    by = {}
    for e in new:
        by[e.get("count")] = by.get(e.get("count"), 0) + 1
    triples = [f"{e['market']} {e['ticker']} {e['side']}" for e in new if (e.get("count") or 0) >= 3]
    print(f"new multi-lens alignments since {mel(since, '%a %H:%M')}: {len(new)} "
          + (str({f'{k}-lens': v for k, v in sorted(by.items())}) if by else ""))
    if triples:
        print("    TRIPLES (all three lenses agree): " + ", ".join(triples))


# ---------------------------------------------------------------------------
def main() -> int:
    global REPO, REV
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--rev", default="origin/main")
    ap.add_argument("--now", help="ISO time to judge at (default: now); use with --rev to replay")
    ap.add_argument("--since", help="window start for book/confluence changes (any git date; default 24 h before now)")
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()
    REPO, REV = a.repo, a.rev
    if not a.no_fetch and a.rev == "origin/main":
        subprocess.run(["git", "-C", REPO, "fetch", "-q", "origin", "main"], check=False)
    now = ts(a.now) if a.now else dt.datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=MEL)  # a bare --now means Melbourne
    if a.since:
        try:
            since = ts(a.since)
        except ValueError:
            # git's own date parser ("yesterday 9am", "3 hours ago"); unlike GNU
            # `date -d` it works on Windows too. It prints --max-age=<epoch>.
            # It is lenient: unreadable text means "now", which the PAPER BOT
            # header line then shows, so check that line.
            out = git("rev-parse", f"--since={a.since}").strip()
            since = dt.datetime.fromtimestamp(int(out.split("=", 1)[1]), UTC)
        if since.tzinfo is None:
            since = since.replace(tzinfo=MEL)  # a bare "2026-10-08 09:00" means Melbourne
    else:
        since = now - dt.timedelta(hours=24)
    head = git("log", "-1", "--format=%h %cI", REV).split()
    print(f"Vivek 5.0 status at {mel(now, '%a %d %b %H:%M %Z')} Melbourne; repo {REV} {head[0]} "
          f"(last commit {mel(ts(head[1]), '%H:%M')})")
    for fn in (lambda: scans(now), lambda: lenses(now), lambda: book(now, since), lambda: confluence(now, since)):
        try:
            fn()
        except Exception as e:  # one broken section must not hide the rest
            FLAGS.append(f"status script could not read a section: {type(e).__name__}: {e}")
    section("VERDICT FROM REPO DATA")
    print("LOOKS WRONG:" if FLAGS else "LOOKS WRONG: nothing in the repo data")
    for f in FLAGS:
        print(f"  - {f}")
    if WAITING:
        print("NOT DUE YET / NORMAL LAG:")
        for w in WAITING:
            print(f"  - {w}")
    print("NOT CHECKED HERE (use the GitHub tools): failure emails / red runs, whether the digest posted, "
          "kill switch + watchdog lines, cron-job.org pings, the live site.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
