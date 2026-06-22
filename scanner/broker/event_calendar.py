"""High-impact economic event filter.

Prevents new positions from being opened on days with major scheduled releases
that historically cause outsized volatility: FOMC, CPI, NFP, RBA, etc.

Event data lives in public/data/events.json — a list of records:
  {"date": "YYYY-MM-DD", "event": "FOMC", "impact": "high"}

Update the file monthly. Impact levels: "high", "medium", "low".
Only "high" events block trading by default (configurable via config.py).

Usage:
    from scanner.broker.event_calendar import is_blackout_day, next_events
    if is_blackout_day():
        log.warning("blackout day — skipping new orders")
        return
"""

import datetime as dt
import json
import logging
import pathlib

log = logging.getLogger(__name__)

ROOT        = pathlib.Path(__file__).resolve().parents[2]
EVENTS_FILE = ROOT / "public" / "data" / "events.json"


def _load_events() -> list[dict]:
    if not EVENTS_FILE.exists():
        return []
    try:
        return json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("could not load events.json: %s", e)
        return []


def is_blackout_day(date: str | None = None) -> bool:
    """Return True if date falls on a high-impact scheduled event.

    date: ISO date string "YYYY-MM-DD", or None for today (UTC).
    """
    from scanner import config as cfg
    if not getattr(cfg, "EVENT_BLACKOUT_ENABLED", True):
        return False

    if date is None:
        date = dt.datetime.now(dt.timezone.utc).date().isoformat()

    for e in _load_events():
        if e.get("date") == date and e.get("impact", "").lower() == "high":
            log.info("blackout day: %s — %s", date, e.get("event", "?"))
            return True
    return False


def today_events() -> list[dict]:
    """Return all events scheduled for today (UTC)."""
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    return [e for e in _load_events() if e.get("date") == today]


def next_events(n: int = 5) -> list[dict]:
    """Return the next n upcoming events (today or later), sorted by date."""
    today    = dt.datetime.now(dt.timezone.utc).date().isoformat()
    upcoming = sorted(
        [e for e in _load_events() if e.get("date", "") >= today],
        key=lambda e: e["date"],
    )
    return upcoming[:n]
