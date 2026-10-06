"""Which markets should this scan.yml run scan? STDLIB ONLY -- it runs in the
gate job on the runner's own python3, before any `pip install`.

THE RULE (owner, 2026-09-21: stock markets are scanned in market hours only),
read in each market's OWN calendar, so daylight saving cannot move it:

  * A STOCK market is LIVE while it is inside its session window
    (config.MARKET_SCAN_WINDOWS). It OWES ITS CLOSING SCAN when today's close
    has passed (the plays digest's own gate, config.MORNING_PLAYS_SLOT_GATE)
    and no scan has landed since: the digest will not send without one, and
    GitHub drops crons. Only today's close counts, so a shut market is never
    rescanned once a post-close scan has landed, and never on a weekend.
  * A run scans the live stock market, or, when none is live, the one owing
    its closing scan. Never both: a catch-up leg that failed would take the
    live market's scan down with it. The windows never overlap and neither do
    the catch-up spells, so this is at most ONE stock market per run.
  * Crypto trades 24/7. On a schedule it is crypto_bot.yml's job; scan.yml
    scans it only when asked.

Who started the run decides which rule applies:

  schedule   the due stock market, never crypto. Each closing cron is written
             twice (one per DST regime) and the copy that lands before the
             close is skipped, not run as an extra mid-session scan.
  heartbeat  the healer found the book stale: crypto, plus the due stock
             market if it was asked for. Never a shut market. (Until
             2026-10-05 a heal rescanned all three markets round the clock:
             65 of the 83 heal-started ASX scans from 28 Sep to 5 Oct ran
             with the ASX shut.)
  otherwise  a person or the SCAN button: exactly what was asked.

The gate runs outside the `scan` mutex and reads the stamps on the branch
when it starts, so a second trigger that arrives while a catch-up scan is
still queued or running can catch the same close up again. That repeat ends
as soon as a post-close stamp lands (and at local midnight at the latest).

    python3 scripts/scan_gate.py --event E [--schedule CRON] [--reason R]
                                 [--market M] [--data DIR] [--now ISO]

Prints `run=true|false` and `markets=<space-separated>` (for $GITHUB_OUTPUT)
and one reason line on stderr. scan.yml turns a crash into a fail-open scan.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scanner import config  # noqa: E402  (stdlib-only module)

STOCK = tuple(config.MARKET_SCAN_WINDOWS)            # ("asx", "nasdaq")
ALL = STOCK + ("crypto",)
# scan.yml's closing slots, each written once per DST regime.
CLOSING_CRONS = ("41 5,6 * * 1-5", "57 5,6 * * 1-5", "47 20,21 * * 1-5")


def _local(market: str, now: dt.datetime) -> dt.datetime:
    return now.astimezone(ZoneInfo(config.MARKET_SCAN_WINDOWS[market][0]))


def close_of(market: str, now: dt.datetime) -> dt.datetime:
    """Today's close in the market's own calendar: the digest's gate time."""
    g = next(g for g in config.MORNING_PLAYS_SLOT_GATE.values() if g["market"] == market)
    n = now.astimezone(ZoneInfo(g["tz"]))
    return n.replace(hour=g["hour"], minute=g["minute"], second=0, microsecond=0)


def in_session(market: str, now: dt.datetime) -> bool:
    _tz, first, last = config.MARKET_SCAN_WINDOWS[market]
    n = _local(market, now)
    return n.weekday() < 5 and first <= n.hour * 60 + n.minute <= last


def missed_close(market: str, now: dt.datetime, last_scan: dt.datetime | None) -> bool:
    """Has today's close passed with no scan since? (None = never scanned.)"""
    close = close_of(market, now)
    return (close.weekday() < 5 and now >= close
            and (last_scan is None or last_scan < close))


def decide(event: str, schedule: str, reason: str, market: str, now: dt.datetime,
           last_scans: dict) -> tuple[list[str], str]:
    """(markets, why): what this run scans; [] means skip."""
    asked = list(ALL) if market in ("", "all") else [market]
    if event == "schedule":
        asked = list(STOCK)
    elif reason != "heartbeat":
        return asked, f"{event}: running what was asked"
    closing = event == "schedule" and schedule in CLOSING_CRONS
    stock = [m for m in asked if m in STOCK]
    live = [m for m in stock if in_session(m, now)
            and not (closing and now < close_of(m, now))]
    owed = [m for m in stock if missed_close(m, now, last_scans.get(m))]
    markets = (live or owed) + [m for m in asked if m == "crypto"]
    why = []
    for m in stock:
        state = ("live" if m in live else
                 "closing slot before the close (the other DST regime's copy)"
                 if closing and in_session(m, now) else
                 "owes its closing scan" if m in owed else "shut")
        why.append(f"{m} {_local(m, now):%a %H:%M} {state}")
    who = "heartbeat" if reason == "heartbeat" else event
    return markets, f"{who}: {'; '.join(why)} -> {' '.join(markets) or 'skip'}"


def last_scan(data_dir: pathlib.Path, market: str) -> dt.datetime | None:
    """When `market` was last scanned (its published prices file), or None."""
    try:
        doc = json.loads((data_dir / f"{market}_prices.json").read_text(encoding="utf-8"))
        t = dt.datetime.fromisoformat(doc["generated_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return t if t.tzinfo else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--event", required=True)
    p.add_argument("--schedule", default="")
    p.add_argument("--reason", default="")
    p.add_argument("--market", default="")
    p.add_argument("--data", default=str(ROOT / "public" / "data"))
    p.add_argument("--now", default="")
    a = p.parse_args(argv)
    now = dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now(dt.timezone.utc)
    stamps = {m: last_scan(pathlib.Path(a.data), m) for m in STOCK}
    markets, why = decide(a.event, a.schedule, a.reason, a.market, now, stamps)
    print(f"run={'true' if markets else 'false'}")
    print(f"markets={' '.join(markets)}")
    print(f"scan gate: {why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
