"""Market clock helpers for the stdlib-only gate scripts (REFINE200 #128).

STDLIB ONLY, and pinned: scan_gate.py imports this on the runner's own python3
BEFORE any `pip install` (its sparse checkout carries this file), so the
standard library is all it may use. Callers pass the tables in from
scanner.config; nothing here reads config itself.

"The most recent weekday close" was written five times across the gate scripts
(scan_gate, morning_plays, ignition_due, momentum_due, the check-in skill), each
with its own loop, and the copies had already drifted to different ASX closes.
These are the one implementation; the remaining copies can move onto them.

Every instant is computed in the market's OWN calendar (an IANA zone), so a
DST change on either side of the world cannot move it. Python's aware
arithmetic is wall-clock arithmetic, so stepping back a day keeps 16:40 at
16:40 local across a DST change, with the right UTC offset for that date.
Exchange holidays are not modelled: a holiday weekday reads as a session.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

WEEKDAYS = frozenset(range(5))          # Mon..Fri


def at_local(now: dt.datetime, tz_name: str, hour: int, minute: int = 0) -> dt.datetime:
    """`hour:minute` on `now`'s own date in `tz_name` (aware, in that zone)."""
    local = now.astimezone(ZoneInfo(tz_name))
    return local.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)


def latest_weekday_at(now: dt.datetime, tz_name: str, hour: int,
                      minute: int = 0) -> dt.datetime:
    """The most recent Mon-Fri `hour:minute` in `tz_name` at or before `now`
    (aware, in that zone). Sunday walks back to Friday; a Monday before the
    time walks back to Friday too."""
    t = at_local(now, tz_name, hour, minute)
    if t > now:
        t -= dt.timedelta(days=1)
    while t.weekday() not in WEEKDAYS:
        t -= dt.timedelta(days=1)
    return t


def latest_session(now: dt.datetime, tz_name: str,
                   session: tuple) -> tuple[dt.datetime, dt.datetime]:
    """(open, close) of the most recent weekday session that has CLOSED at or
    before `now`, in `tz_name`. `session` is (open_h, open_m, close_h,
    close_m), the shape of config.VIVEK_JOURNAL_SESSION."""
    close = latest_weekday_at(now, tz_name, session[2], session[3])
    return close.replace(hour=int(session[0]), minute=int(session[1])), close
