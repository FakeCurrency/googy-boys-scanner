"""Daily Discord digest of HIGH-CONVICTION VIVEK 5.0 plays (2026-09-08).

Two market-specific send slots, each ~30 min after its market's close (owner,
2026-09-09): ASX at 16:30 Melbourne, NASDAQ + Crypto at 06:30 Melbourne. A run
sends only the slot whose Melbourne HOUR is live, so ASX lands in the afternoon
and the US markets the next morning. The slots live in
config.MORNING_PLAYS_SCHEDULE; morning_plays.yml fires four DST-superset crons.

Collect the qualifying LONG setups for the live slot and post them to a Discord
channel as a CLEAN text list. READ-ONLY to the repo: it reads the COMMITTED
scan JSON (public/data/<market>_vivek.json) and posts -- it never scans, never
touches Yahoo, never commits. Its only state is a small actions/cache file (the
sent-list, below), the same cross-run pattern as the watchdog state. The shape
is reco_note.py / evidence_brief.py.

WHAT QUALIFIES (owner spec): LONG only, never a SHORT; never a fund/REIT/LIC/
preferred (`is_product`); and either
  * HIGH CONVICTION  -- app.js isHighConviction: a WEEKLY (1W) reclaim that is
    armed and is A/A+ grade or has strong structure (>= 2 structural TPs); or
  * (opt-in) a plain A+ long, when MORNING_PLAYS_INCLUDE_ALL_APLUS is True.

DE-DUP (owner ask, 2026-09-09): a ticker already SENT within the last
MORNING_PLAYS_DEDUP_DAYS days is skipped, so the reader (who charts each name)
is never handed the same ticker twice inside the window. Only tickers that were
ACTUALLY DELIVERED are recorded -- a failed post, a dry run or a missing webhook
records nothing, so no name is ever silently buried. The record is counted from
when a name was SENT, not from when it went high-conviction, so a still-valid
setup reappears once the window passes.

Each play renders as `SYMBOL -> label`, where the label is "A+ High conviction",
"High conviction", or "A+".

THE CHANNEL. Discord as an ALERT channel was removed 2026-08-27; this is the
"something new" the owner foreshadowed, on its OWN secret
(config.MORNING_PLAYS_WEBHOOK_ENV = DISCORD_MORNING_WEBHOOK_URL). The webhook
runs through config.clean_secret (the BOM lesson) and posts with a named UA.

Exit codes: 0 on a clean send / a "not my hour" skip / a missing webhook
(setup gap, warned loudly); 1 on a genuine delivery failure, so the run reddens.

    python scripts/morning_plays.py                 # gated to a slot's Melbourne hour
    python scripts/morning_plays.py --force         # send all markets now (manual test)
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


# ── de-dup memory: don't re-send a ticker within the window ──────────────────

def _seen_key(market: str, symbol) -> str:
    return f"{market}:{str(symbol or '').upper()}"


def _days_since(iso: str | None, today: dt.date) -> int | None:
    try:
        return (today - dt.date.fromisoformat(iso)).days
    except Exception:
        return None


def load_seen(path: pathlib.Path) -> dict[str, str]:
    """{market:SYMBOL -> ISO date it was last sent}, or {} if absent/corrupt."""
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        sent = data.get("sent")
        return dict(sent) if isinstance(sent, dict) else {}
    except Exception:
        return {}


def save_seen(path: pathlib.Path, sent: dict[str, str]) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"sent": sent,
               "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def filter_unseen(picks_by_market: dict[str, list[dict]], sent: dict[str, str],
                  today: dt.date, window: int) -> dict[str, list[dict]]:
    """Drop rows whose ticker was sent within the last `window` days."""
    if window <= 0:
        return {m: list(v) for m, v in picks_by_market.items()}
    out: dict[str, list[dict]] = {}
    for market, rows in picks_by_market.items():
        kept = []
        for r in rows:
            d = _days_since(sent.get(_seen_key(market, r.get("symbol"))), today)
            if d is not None and 0 <= d < window:
                continue
            kept.append(r)
        out[market] = kept
    return out


def record_sent(sent: dict[str, str], delivered_by_market: dict[str, list[dict]],
                today: dt.date, window: int) -> dict[str, str]:
    """Stamp today onto every DELIVERED ticker, then forget anything now past
    the window (it can no longer suppress, so the file stays tiny)."""
    iso = today.isoformat()
    for market, rows in delivered_by_market.items():
        for r in rows:
            sent[_seen_key(market, r.get("symbol"))] = iso
    if window > 0:
        for k in list(sent):
            d = _days_since(sent[k], today)
            if d is None or d >= window:
                del sent[k]
    return sent


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
                   when_label: str, had_qualifying: bool = False) -> list[str]:
    """One or more Discord `content` strings (chunked to CONTENT_LIMIT).

    `had_qualifying` distinguishes an empty list because there were no plays at
    all from one because every current play was already sent inside the window.
    """
    header = f"\U0001f3af **VIVEK 5.0 plays — {when_label}**"
    markets_label = " + ".join(m.upper() for m in picks_by_market) or "the market"
    if not sum(len(v) for v in picks_by_market.values()):
        if had_qualifying:
            days = int(getattr(config, "MORNING_PLAYS_DEDUP_DAYS", 0) or 0)
            return [header + f"\nNo new plays this morning — every current "
                    f"high-conviction name was already shared in the last "
                    f"{days} days."]
        return [header + f"\nNo high-conviction plays across {markets_label} "
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

def slot_markets(now_local: dt.datetime, force: bool):
    """The markets to send on this run, or None for a no-op.

    A scheduled run sends the slot whose Melbourne HOUR is live (or no-ops --
    the expected fate of every DST superset off-cron). A manual --force run
    always sends the whole schedule's union, so a test button shows everything.
    """
    if force:
        return config.MORNING_PLAYS_MARKETS
    slot = config.MORNING_PLAYS_SCHEDULE.get(now_local.hour)
    return tuple(slot) if slot else None


def gather(markets, data_dir: pathlib.Path, now_utc: dt.datetime) -> tuple[dict, dict]:
    picks_by_market: dict[str, list[dict]] = {}
    ages: dict[str, float | None] = {}
    for market in markets:
        payload = load_market(market, data_dir)
        picks_by_market[market] = select(payload.get("results", []))
        ages[market] = _scan_age_hours(payload.get("generated_at"), now_utc)
    return picks_by_market, ages


def main(argv=None, now=None) -> int:
    ap = argparse.ArgumentParser(prog="morning_plays")
    ap.add_argument("--force", action="store_true",
                    help="send all markets now regardless of the hour (manual test)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the messages, post nothing, record nothing")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--seen-file",
                    default=str(ROOT / config.MORNING_PLAYS_SEEN_FILE),
                    help="the de-dup sent-list (actions/cache file)")
    args = ap.parse_args(argv)

    tz = ZoneInfo(config.MORNING_PLAYS_TZ)
    now_utc = now or dt.datetime.now(dt.timezone.utc)
    now_local = now_utc.astimezone(tz)
    today = now_local.date()

    markets = slot_markets(now_local, args.force)
    if markets is None:
        print(f"morning_plays: {now_local:%H:%M} {config.MORNING_PLAYS_TZ} matches "
              "no send slot - this cron is a no-op today.")
        return 0

    when_label = f"{now_local:%a %-d %b}, {now_local:%H:%M} Melbourne"
    picks_by_market, ages = gather(markets, pathlib.Path(args.data_dir), now_utc)

    # De-dup on scheduled runs only: a manual --force test must never consume the
    # real sent-window nor risk re-sending a name already shared today.
    window = int(getattr(config, "MORNING_PLAYS_DEDUP_DAYS", 0) or 0)
    use_dedup = window > 0 and not args.force
    seen_path = pathlib.Path(args.seen_file)
    sent = load_seen(seen_path) if use_dedup else {}
    new_by_market = filter_unseen(picks_by_market, sent, today, window if use_dedup else 0)

    total_qual = sum(len(v) for v in picks_by_market.values())
    total_new = sum(len(v) for v in new_by_market.values())
    messages = build_messages(new_by_market, ages, when_label,
                              had_qualifying=bool(total_qual))
    per = ", ".join(f"{m} {len(v)}" for m, v in new_by_market.items())
    print(f"morning_plays: {'+'.join(markets)} slot: {total_new} new of "
          f"{total_qual} qualifying long plays ({per}); {len(messages)} message(s)")

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
            return 1                                         # NOT recorded -> retried next run
        if not (200 <= status < 300):
            print(f"::error::morning_plays: Discord returned HTTP {status} on "
                  f"message {i}/{len(messages)} - not delivered.")
            return 1

    # Delivered cleanly: record ONLY the tickers we actually sent, then persist.
    if use_dedup:
        record_sent(sent, new_by_market, today, window)
        save_seen(seen_path, sent)
    print(f"morning_plays: delivered {len(messages)} message(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
