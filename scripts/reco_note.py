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
  reported as exactly that instead of being summarised.
- Atomic write (temp + os.replace); ASCII-only output (CLAUDE.md rules 7+9).
"""
import datetime as dt
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "data", "reco_note.json")
MARKETS = [("asx", "ASX"), ("nasdaq", "NASDAQ"), ("crypto", "Crypto")]


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def hours_old(iso):
    try:
        t = dt.datetime.fromisoformat(str(iso))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600.0
    except Exception:
        return None


def market_line(label, prices, positions):
    """One sentence per market, mirroring the page's own breadth maths
    (recs.js: all qualifying rows by dir; 62/38 lean thresholds; thin < 8)."""
    if not prices or not isinstance(prices.get("rows"), dict):
        return "%s: no scan data available today." % label
    age = hours_old(prices.get("generated_at"))
    if age is not None and age > 48:
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
        lines.append(market_line(label, prices, pos))
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
