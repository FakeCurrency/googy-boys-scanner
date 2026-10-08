"""Is a stock market's Ignition backstop run due? STDLIB ONLY -- it runs
before `pip install`, on the runner's system python3.

ignition_asx.yml and ignition_nasdaq.yml each back their post-close cron up
twice, because GitHub drops and delays crons. A backstop is only due when the
file on the branch was NOT generated at/after that market's latest daily bar
went final: otherwise it would re-screen the same completed bar, re-stamp
generated_at and commit a pointless Cloudflare deploy.

"Final" is config.IGNITION_BAR_FINAL[market] = (timezone, hour, minute), read
in the market's own calendar so both DST regimes are right by construction:
  * asx     16:40 Sydney (the digest's own close gate: the auction prints
            ~16:10-16:12 but Yahoo's ASX feed shows it ~20 min later). Under
            AEST the 06:24 UTC primary is 16:24 Sydney, before it, so the
            07:24 UTC backstop re-screens on final bars.
  * nasdaq  16:30 New York (the closing cross + the delayed feed). The 21:34
            UTC primary is past it in both EDT and EST.

    python3 scripts/ignition_due.py <market> <generated_at or ""> [--now ISO]

Prints `run=true` or `run=false` (for $GITHUB_OUTPUT) and a reason line.
Anything unreadable -- the stamp, the market -- FAILS OPEN (run=true): a spare
run costs a commit, a missed one costs a day's screen.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from scanner import config  # noqa: E402  (stdlib-only module)


def last_close(market: str, now_utc: dt.datetime) -> dt.datetime:
    """The most recent weekday bar-final instant at or before `now_utc`, as
    UTC. KeyError for a market with no entry."""
    tz_name, hour, minute = config.IGNITION_BAR_FINAL[market]
    tz = ZoneInfo(tz_name)
    local = now_utc.astimezone(tz)
    day = local.date()
    while True:
        close = dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
        if day.weekday() < 5 and close <= local:
            return close.astimezone(dt.timezone.utc)
        day -= dt.timedelta(days=1)


def due(market: str, stamp: str, now_utc: dt.datetime) -> tuple[bool, str]:
    if market not in config.IGNITION_BAR_FINAL:
        return True, "no bar-final time for market %r - running" % market
    try:
        gen = dt.datetime.fromisoformat(stamp)
        if gen.tzinfo is None:
            raise ValueError("naive timestamp")
    except (TypeError, ValueError):
        return True, "no readable generated_at (%r) - running" % stamp
    close = last_close(market, now_utc)
    if gen >= close:
        return False, "already screened after the %s %s close (%s) - nothing to do" % (
            market, close.isoformat(timespec="minutes"), stamp)
    return True, "last screen %s predates the %s %s close - running" % (
        stamp, market, close.isoformat(timespec="minutes"))


def main(argv: list[str]) -> int:
    market = argv[1] if len(argv) > 1 else ""
    stamp = argv[2] if len(argv) > 2 else ""
    now = dt.datetime.now(dt.timezone.utc)
    if "--now" in argv:
        now = dt.datetime.fromisoformat(argv[argv.index("--now") + 1])
    run, why = due(market, stamp, now)
    print("run=%s" % ("true" if run else "false"))
    print("backstop: " + why, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
