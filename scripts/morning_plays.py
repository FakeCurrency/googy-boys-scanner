"""Morning Discord digest of HIGH-CONVICTION VIVEK 5.0 plays (2026-09-08).

Every Melbourne morning, collect the qualifying LONG setups across ASX and
NASDAQ and post them to a Discord channel as a CLEAN text list. READ-ONLY: it
reads the COMMITTED scan JSON (public/data/<market>_vivek.json) and posts -- it
never scans, never touches Yahoo, never commits, and is not in the scan
concurrency group. The pattern is reco_note.py / evidence_brief.py.

WHAT QUALIFIES (owner spec, 2026-09-08): LONG only, never a SHORT; never a
FUND / REIT / LIC / preferred (the scan's `is_product` flag); and either
  * HIGH CONVICTION  -- app.js isHighConviction: a WEEKLY (1W) reclaim that is
    armed and is A/A+ grade or has strong structure (>= 2 structural TPs); or
  * (opt-in) a plain A+ long, when MORNING_PLAYS_INCLUDE_ALL_APLUS is True.
Default is high-conviction longs only -- a tight, focused list. Turning the
A+ opt-in on adds ~90 more names a day (every plain long A+), a much longer
list; the message is chunked across several posts if it would exceed Discord's
2000-char limit.

Each play renders as `SYMBOL -> label`, where the label says why it made the
cut: "A+ High conviction", "High conviction", or "A+".

THE CHANNEL. Discord as an ALERT channel was removed 2026-08-27; this is the
"something new" the owner foreshadowed, on its OWN secret
(config.MORNING_PLAYS_WEBHOOK_ENV = DISCORD_MORNING_WEBHOOK_URL). The webhook
runs through config.clean_secret (the BOM lesson) and posts with a named UA.

Exit codes: 0 on a clean send / a "not my hour" skip / a missing webhook
(setup gap, warned loudly); 1 on a genuine delivery failure, so the run reddens
and GitHub emails.

    python scripts/morning_plays.py                 # gated to Melbourne 07:00
    python scripts/morning_plays.py --force         # send now regardless of hour
    python scripts/morning_plays.py --force --dry-run   # print, post nothing
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.request
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:                # runnable as `python scripts/morning_plays.py`
    sys.path.insert(0, str(ROOT))

from scanner import config                   # noqa: E402

DATA_DIR = ROOT / "public" / "data"
CONTENT_LIMIT = 1900                          # Discord caps `content` at 2000; leave slack


# ── the definition, identical to app.js isHighConviction ─────────────────────

def is_high_conviction(row: dict) -> bool:
    """A WEEKLY reclaim that's armed and A/A+ or has strong structure.

    Mirrors public/js/app.js isHighConviction exactly:
        p = row.plans["1W"]; p.armed && p.entry_trigger === "reclaim"
        && (grade in {A+, A} || (p.structural_tps || 0) >= 2)
    """
    p = (row.get("plans") or {}).get("1W")
    if not p or not p.get("armed") or p.get("entry_trigger") != "reclaim":
        return False
    good_grade = row.get("grade") in ("A+", "A")
    strong_structure = (p.get("structural_tps") or 0) >= 2
    return bool(good_grade or strong_structure)


def _is_long(row: dict) -> bool:
    return str(row.get("dir", "LONG")).upper() != "SHORT"


def qualifies(row: dict) -> bool:
    """LONG, not a fund/REIT, and high-conviction (or a plain A+ when the A+
    opt-in is on)."""
    if not _is_long(row):
        return False
    if row.get("is_product"):                 # fund / REIT / LIC / preferred
        return False
    if is_high_conviction(row):
        return True
    return bool(getattr(config, "MORNING_PLAYS_INCLUDE_ALL_APLUS", False)
                and row.get("grade") == "A+")


def play_label(row: dict) -> str:
    aplus = row.get("grade") == "A+"
    hc = is_high_conviction(row)
    if aplus and hc:
        return "A+ High conviction"
    if hc:
        return "High conviction"
    return "A+" if aplus else ""


# ── loading + selecting ──────────────────────────────────────────────────────

def load_market(market: str, data_dir: pathlib.Path = DATA_DIR) -> dict:
    """Read one market's committed scan JSON, or an empty stand-in if absent."""
    path = data_dir / f"{market}_vivek.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _scan_age_hours(generated_at: str | None, now_utc: dt.datetime) -> float | None:
    if not generated_at:
        return None
    try:
        t = dt.datetime.fromisoformat(generated_at)
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return (now_utc - t.astimezone(dt.timezone.utc)).total_seconds() / 3600.0
    except Exception:
        return None


def select(rows: list[dict]) -> list[dict]:
    """Qualifying LONG rows, strongest first (score desc)."""
    q = [r for r in rows if qualifies(r)]
    q.sort(key=lambda r: (-(r.get("score") or 0), str(r.get("symbol") or "")))
    return q


# ── formatting the clean text (pure) ─────────────────────────────────────────

def _market_block(market: str, picks: list[dict], cap: int,
                  age: float | None, stale_h: float) -> list[str]:
    lines = [f"**{market.upper()} plays**"]
    if not picks:
        lines.append("(none this morning)")
        return lines
    for r in picks[:cap]:
        lines.append(f"{r.get('symbol', '?')} → {play_label(r)}")   # SYM -> label
    if len(picks) > cap:
        lines.append(f"...+{len(picks) - cap} more (see the app)")
    if age is not None and stale_h and age > stale_h:
        lines.append(f"_(scan {age:.0f}h old)_")
    return lines


def build_messages(picks_by_market: dict[str, list[dict]],
                   ages: dict[str, float | None],
                   when_label: str) -> list[str]:
    """One or more Discord `content` strings (chunked to CONTENT_LIMIT)."""
    header = f"\U0001f3af **Morning plays — {when_label}**"
    total = sum(len(v) for v in picks_by_market.values())
    if not total:
        return [header + "\nNo long high-conviction plays across ASX + NASDAQ "
                         "this morning."]

    cap = int(getattr(config, "MORNING_PLAYS_MAX_ROWS", 20) or 20)
    stale_h = float(getattr(config, "MORNING_PLAYS_STALE_H", 20.0) or 0)
    lines = [header]
    for market, picks in picks_by_market.items():
        lines.append("")
        lines.extend(_market_block(market, picks, cap, ages.get(market), stale_h))
    url = str(getattr(config, "MORNING_PLAYS_APP_URL", "") or "").strip()
    if url:
        lines += ["", url]
    return _chunk(lines)


def _chunk(lines: list[str], limit: int = CONTENT_LIMIT) -> list[str]:
    """Pack lines into <=limit-char messages, never splitting a line."""
    out, cur = [], ""
    for ln in lines:
        piece = (cur + "\n" + ln) if cur else ln
        if len(piece) > limit and cur:
            out.append(cur)
            cur = ln
        else:
            cur = piece
    if cur:
        out.append(cur)
    return out or [""]


# ── posting ──────────────────────────────────────────────────────────────────

def post(webhook: str, payload: dict, ua: str, urlopen=urllib.request.urlopen) -> int:
    """POST one payload; return the HTTP status. Raises on transport failure."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=data, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": ua})
    with urlopen(req, timeout=20) as resp:
        return int(getattr(resp, "status", None) or resp.getcode())


# ── the run ──────────────────────────────────────────────────────────────────

def should_send_now(now_local: dt.datetime, hour: int, force: bool) -> bool:
    """One of the two superset crons is the target hour in Melbourne; only it
    sends. A manual --force run always sends."""
    return bool(force or now_local.hour == hour)


def gather(data_dir: pathlib.Path, now_utc: dt.datetime) -> tuple[dict, dict]:
    picks_by_market: dict[str, list[dict]] = {}
    ages: dict[str, float | None] = {}
    for market in config.MORNING_PLAYS_MARKETS:
        payload = load_market(market, data_dir)
        picks_by_market[market] = select(payload.get("results", []))
        ages[market] = _scan_age_hours(payload.get("generated_at"), now_utc)
    return picks_by_market, ages


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="morning_plays")
    ap.add_argument("--force", action="store_true",
                    help="send regardless of the Melbourne hour (manual test)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the messages, post nothing")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args(argv)

    tz = ZoneInfo(config.MORNING_PLAYS_TZ)
    now_utc = dt.datetime.now(dt.timezone.utc)
    now_local = now_utc.astimezone(tz)
    hour = int(config.MORNING_PLAYS_HOUR)

    if not should_send_now(now_local, hour, args.force):
        print(f"morning_plays: {now_local:%H:%M} {config.MORNING_PLAYS_TZ} is not "
              f"the {hour:02d}:00 send hour - this cron is a no-op today.")
        return 0

    when_label = f"{now_local:%a %-d %b}, {hour:02d}:00 Melbourne"
    picks_by_market, ages = gather(pathlib.Path(args.data_dir), now_utc)
    messages = build_messages(picks_by_market, ages, when_label)
    total = sum(len(v) for v in picks_by_market.values())
    per = ", ".join(f"{m} {len(v)}" for m, v in picks_by_market.items())
    print(f"morning_plays: {total} qualifying long plays ({per}); "
          f"{len(messages)} message(s)")

    if args.dry_run:
        for m in messages:
            print("-" * 8)
            print(m)
        return 0

    webhook = config.clean_secret(os.environ.get(config.MORNING_PLAYS_WEBHOOK_ENV))
    if not webhook:
        print(f"::warning::{config.MORNING_PLAYS_WEBHOOK_ENV} is not set - "
              "nothing was sent. Create a Discord webhook for the channel you "
              "want and add it as that Actions secret to switch this on.")
        return 0

    for i, msg in enumerate(messages, 1):
        try:
            status = post(webhook, {"content": msg}, config.MORNING_PLAYS_UA)
        except Exception as e:                              # noqa: BLE001
            print(f"::error::morning_plays: Discord POST {i}/{len(messages)} "
                  f"failed: {e.__class__.__name__}: {e}")
            return 1
        if not (200 <= status < 300):
            print(f"::error::morning_plays: Discord returned HTTP {status} on "
                  f"message {i}/{len(messages)} - not delivered.")
            return 1
    print(f"morning_plays: delivered {len(messages)} message(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
