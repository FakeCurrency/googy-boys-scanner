#!/usr/bin/env python3
"""Deterministic daily note for the RECOMMENDATIONS page (reco_note.yml).

Reads the day's COMMITTED scan data + paper book and rewrites
public/data/reco_note.json with a plain-language consensus summary.
Commentary ONLY - nothing here is read by the bot or any signal path.

Rules:
- author "auto". A hand-written note (author "Claude") from TODAY is never
  overwritten - interactive sessions outrank the template. In that case the
  script prints RECO_NOTE_UNCHANGED and the workflow skips its commit.
- Never invents data: a market whose prices file is missing or >48h stale is
  reported as exactly that instead of being summarised. For a WEEKDAY-ONLY
  market (config.MARKET_SCAN_WINDOWS: scan_gate.py never scans ASX/NASDAQ on a
  weekend since 2026-10-05) the 48h are WEEKDAY hours in the market's own zone,
  so Friday's closing read stays the current read through the weekend instead
  of reading "2 days old" every Sunday (ASX) and Monday (NASDAQ) -- audit #70,
  2026-10-08. The rule exists to catch a STALLED pipeline (recs.js: "the
  pipeline may be stalled"), and a weekend is not a stall. Crypto keeps 48
  wall-clock hours.
- Atomic write (temp + os.replace); ASCII-only output (CLAUDE.md rules 7+9).
"""
import datetime as dt
import json
import os
import sys
import tempfile
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scanner import config  # noqa: E402  (stdlib-only module, like scan_gate.py)

OUT = os.path.join(ROOT, "public", "data", "reco_note.json")
MARKETS = [("asx", "ASX"), ("nasdaq", "NASDAQ"), ("crypto", "Crypto")]
STALE_H = 48


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _stamp(iso):
    t = dt.datetime.fromisoformat(str(iso))
    return t if t.tzinfo is not None else t.replace(tzinfo=dt.timezone.utc)


def hours_old(iso):
    try:
        return (dt.datetime.now(dt.timezone.utc) - _stamp(iso)).total_seconds() / 3600.0
    except Exception:
        return None


def weekday_hours(t0, t1, tz):
    """Hours between two aware instants that fall on a Monday-Friday in zone
    `tz` (each local day is cut at local midnight; DST-correct, because each
    piece is measured in UTC)."""
    z = ZoneInfo(tz)
    cur, end = t0.astimezone(z), t1.astimezone(z)
    total = 0.0
    while cur < end:
        nxt = dt.datetime.combine(cur.date() + dt.timedelta(days=1), dt.time(), tzinfo=z)
        piece = min(nxt, end)
        if cur.weekday() < 5:
            total += (piece.astimezone(dt.timezone.utc)
                      - cur.astimezone(dt.timezone.utc)).total_seconds() / 3600.0
        cur = piece
    return total


def stale_age_h(iso, market=None):
    """The age the 48h staleness rule reads: weekday hours in the market's
    own zone for a weekday-only market (MARKET_SCAN_WINDOWS), wall-clock hours
    otherwise. None when the stamp is unreadable."""
    try:
        t = _stamp(iso)
        now = dt.datetime.now(dt.timezone.utc)
        if market in config.MARKET_SCAN_WINDOWS:
            return weekday_hours(t, now, config.MARKETS[market].timezone)
        return (now - t).total_seconds() / 3600.0
    except Exception:
        return None


def market_line(label, prices, positions, market=None):
    """One sentence per market, mirroring the page's own breadth maths
    (recs.js: all qualifying rows by dir; 62/38 lean thresholds; thin < 8).
    `market` (the key) picks the staleness clock -- see the module docstring."""
    if not prices or not isinstance(prices.get("rows"), dict):
        return "%s: no scan data available today." % label
    stale = stale_age_h(prices.get("generated_at"), market)
    if stale is not None and stale > STALE_H:
        age = hours_old(prices.get("generated_at")) or stale
        return "%s: scan data is %d days old - no fresh read." % (label, int(age // 24))
    rows = list(prices["rows"].values())
    longs = sum(1 for r in rows if r.get("dir") == "LONG")
    shorts = sum(1 for r in rows if r.get("dir") == "SHORT")
    n = longs + shorts
    aplus = sum(1 for r in rows if r.get("grade") == "A+")
    if n == 0:
        return "%s: no qualifying setups on the board." % label
    pl = longs / float(n)
    if n < 8:
        lean = "too thin to call"
    elif pl >= 0.62:
        lean = "leaning long" + (" decisively" if pl >= 0.75 else "")
    elif pl <= 0.38:
        lean = "leaning short" + (" decisively" if pl <= 0.25 else "")
    else:
        lean = "mixed"
    line = "%s: %s (%dL/%dS across %d setups, %d A+)" % (label, lean, longs, shorts, n, aplus)
    if positions:
        r = sum(p.get("unreal_r") or 0 for p in positions)
        line += "; the bot's %d open position%s sit%s at %+.2fR." % (
            len(positions), "s" if len(positions) != 1 else "",
            "" if len(positions) != 1 else "s", r)
    else:
        line += "; the bot holds nothing here."
    return line


def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = now.date().isoformat()
    cur = load(OUT) or {}
    if cur.get("author") == "Claude" and cur.get("date") == today:
        print("RECO_NOTE_UNCHANGED - keeping today's hand-written Claude note")
        return 0

    book = load(os.path.join(ROOT, "journal", "vivek_bot_book.json")) or {}
    open_pos = book.get("open") or []
    lines = []
    for key, label in MARKETS:
        prices = load(os.path.join(ROOT, "public", "data", "%s_prices.json" % key))
        pos = [p for p in open_pos if str(p.get("market") or "").lower() == key]
        lines.append(market_line(label, prices, pos, key))
    total_r = sum(p.get("unreal_r") or 0 for p in open_pos)
    lines.append("Overall the open paper book is %s at %+.2fR across %d positions." % (
        "ahead" if total_r >= 0 else "behind", total_r, len(open_pos)))

    note = {
        "date": today,
        "updated_at": now.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "author": "auto",
        "basis": "Generated in CI from the day's committed scan data and the paper book - commentary only, never fed to the bot.",
        "note": " ".join(lines),
    }
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(note, f, ensure_ascii=True, indent=2)
            f.write("\n")
        os.replace(tmp, OUT)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print("reco_note.json written for %s" % today)
    print("note: %s" % note["note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
