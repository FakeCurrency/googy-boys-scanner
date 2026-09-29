"""Is an ASX Ignition backstop run due? STDLIB ONLY -- it runs before
`pip install`, on the runner's system python3.

ignition_asx.yml's post-close cron (06:24 UTC) is backed up twice (07:24,
09:24 UTC) because GitHub drops and delays crons. A backstop is only due when
the file on the branch was NOT generated after today's ASX close: otherwise it
would re-screen the same completed bar, re-stamp generated_at and commit a
pointless Cloudflare deploy.

The close is the morning digest's own gate (config.MORNING_PLAYS_SLOT_GATE
["asx"], 16:12 Sydney -- the closing auction prints ~16:10-16:12), read in the
market's own calendar so both DST regimes are right by construction.

    python3 scripts/ignition_asx_due.py <generated_at or ""> [--now ISO]

Prints `run=true` or `run=false` (for $GITHUB_OUTPUT) and a reason line.
Anything unreadable FAILS OPEN (run=true): a spare run costs a commit, a
missed one costs a day's screen.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from scanner import config  # noqa: E402  (stdlib-only module)


def last_close(now_utc: dt.datetime) -> dt.datetime:
    """The most recent weekday ASX close at or before `now_utc`, as UTC."""
    g = config.MORNING_PLAYS_SLOT_GATE["asx"]
    tz = ZoneInfo(g["tz"])
    local = now_utc.astimezone(tz)
    day = local.date()
    while True:
        close = dt.datetime(day.year, day.month, day.day, g["hour"], g["minute"], tzinfo=tz)
        if day.weekday() < 5 and close <= local:
            return close.astimezone(dt.timezone.utc)
        day -= dt.timedelta(days=1)


def due(stamp: str, now_utc: dt.datetime) -> tuple[bool, str]:
    try:
        gen = dt.datetime.fromisoformat(stamp)
        if gen.tzinfo is None:
            raise ValueError("naive timestamp")
    except (TypeError, ValueError):
        return True, "no readable generated_at (%r) - running" % stamp
    close = last_close(now_utc)
    if gen >= close:
        return False, "already screened after the %s close (%s) - nothing to do" % (
            close.isoformat(timespec="minutes"), stamp)
    return True, "last screen %s predates the %s close - running" % (
        stamp, close.isoformat(timespec="minutes"))


def main(argv: list[str]) -> int:
    stamp = argv[1] if len(argv) > 1 else ""
    now = dt.datetime.now(dt.timezone.utc)
    if "--now" in argv:
        now = dt.datetime.fromisoformat(argv[argv.index("--now") + 1])
    run, why = due(stamp, now)
    print("run=%s" % ("true" if run else "false"))
    print("backstop: " + why, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
