"""Which Momentum market is DUE -- the gate at the top of momentum.yml.

WHY THIS EXISTS (2026-09-23). momentum.yml used to map three fixed crons to
three markets. On 2026-09-23 GitHub's scheduler created almost no scheduled
runs repo-wide between ~06:46 and ~09:53 UTC (crypto_bot, a :22/:52 cron,
fired 4 times in ~11 hours), so the 06:30 UTC ASX event was simply never
delivered: no run, no failure, nothing to retry. A cron that is dropped leaves
no trace, so the fix cannot be "a better cron". It is to make EVERY wake-up
ask the same question -- "is a market's published file older than the close it
owes?" -- and to add wake-ups that do not come from GitHub's scheduler at all
(morning_plays.yml runs, which cron-job.org dispatches every 30 minutes after
each close). Whichever wake-up arrives first does the work; the rest find
nothing due and stop in seconds. The morning_plays delay-proof gate
(`slot_due` + `scan_is_post_close`) is the precedent.

THE WINDOW, per equity market: from (local close + PUBLISH_AFTER_CLOSE_MIN) on
a weekday until the NEXT session opens. Never inside a session -- spec 5.11:
the screen does not drop a forming bar, so a run during trading would screen a
bar that is still moving. If a whole window is missed the market waits for the
next close; the page's own "generated" stamp says how old the file is.
Crypto is due from 00:30 UTC daily and has no session to avoid.

ONE market per run, the one whose due instant is NEWEST. Newest-first means a
market that keeps failing (it stays due, because a failure leaves its
`generated_at` untouched) cannot starve a market that has just become due: the
fresh one is screened on the next wake-up and the stuck one retries in the
gaps.

STDLIB ONLY, and pinned: it runs on the runner's system python3 BEFORE
`pip install`, so a no-op wake-up costs a checkout and a second, not a
dependency install. It imports two pure-constants modules and nothing else.

Deleted with the lens: `git rm scripts/momentum_due.py
tests/test_momentum_due.py` alongside `scanner/momentum`.

    python3 scripts/momentum_due.py --dir DIR [--now 2026-09-23T07:00:00Z]

DIR holds <market>.json as committed on main. Prints one ASCII line per market
and writes `market=<name or empty>` to $GITHUB_OUTPUT when that is set.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner import config as scfg  # noqa: E402
from scanner.momentum import config as mcfg  # noqa: E402

WEEKDAYS = frozenset(range(5))   # Mon..Fri; exchange holidays are not modelled
UTC = dt.timezone.utc


def _tz(market: str):
    return ZoneInfo(scfg.MARKETS[market].timezone)


def _session(market: str) -> Optional[Tuple[int, int, int, int]]:
    """(open_h, open_m, close_h, close_m) local, or None for a 24/7 market."""
    return scfg.VIVEK_JOURNAL_SESSION.get(market)


def due_point(market: str, now: dt.datetime) -> dt.datetime:
    """The latest instant <= now after which `market` owes a fresh file."""
    session = _session(market)
    if session is None:
        h, m = mcfg.CRYPTO_DUE_UTC
        p = dt.datetime.combine(now.astimezone(UTC).date(), dt.time(h, m), tzinfo=UTC)
        return p if p <= now else p - dt.timedelta(days=1)
    tz = _tz(market)
    close_h, close_m = session[2], session[3]
    today = now.astimezone(tz).date()
    for back in range(8):
        day = today - dt.timedelta(days=back)
        if day.weekday() not in WEEKDAYS:
            continue
        p = (dt.datetime.combine(day, dt.time(close_h, close_m), tzinfo=tz)
             + dt.timedelta(minutes=mcfg.PUBLISH_AFTER_CLOSE_MIN))
        if p <= now:
            return p
    raise AssertionError("no weekday in the last eight days")  # unreachable


def next_open(market: str, after: dt.datetime) -> Optional[dt.datetime]:
    """The first session open strictly after `after`, or None for crypto."""
    session = _session(market)
    if session is None:
        return None
    tz = _tz(market)
    open_h, open_m = session[0], session[1]
    start = after.astimezone(tz).date()
    for fwd in range(8):
        day = start + dt.timedelta(days=fwd)
        if day.weekday() not in WEEKDAYS:
            continue
        o = dt.datetime.combine(day, dt.time(open_h, open_m), tzinfo=tz)
        if o > after:
            return o
    raise AssertionError("no weekday in the next eight days")  # unreachable


def parse_stamp(value) -> Optional[dt.datetime]:
    """A published `generated_at`, or None when absent or unreadable.

    None counts as DUE: a missing or corrupt file is exactly the one that most
    needs rewriting. A naive stamp is read as UTC, which is what run.py writes.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def status(market: str, generated_at: Optional[dt.datetime],
           now: dt.datetime) -> Tuple[bool, dt.datetime, str]:
    """(due, due_point, one-line reason)."""
    point = due_point(market, now)
    if generated_at is not None and generated_at >= point:
        return False, point, "fresh"
    opens = next_open(market, point)
    if opens is not None and now >= opens:
        return False, point, "session open - a forming bar would be screened; waits for the next close"
    if generated_at is None:
        return True, point, "no readable file on main"
    return True, point, "file predates the close it owes"


def pick(stamps: Dict[str, Optional[dt.datetime]],
         now: dt.datetime) -> Tuple[Optional[str], List[str]]:
    """The market to screen now (newest due instant first), plus a report."""
    lines, due = [], []
    for order, market in enumerate(mcfg.MARKETS):
        stamp = stamps.get(market)
        is_due, point, why = status(market, stamp, now)
        seen = stamp.astimezone(UTC).strftime("%Y-%m-%d %H:%MZ") if stamp else "none"
        lines.append(f"{market:<7} {'DUE ' if is_due else 'skip'} "
                     f"owes {point.astimezone(UTC):%Y-%m-%d %H:%MZ} "
                     f"file {seen} - {why}")
        if is_due:
            due.append((point, -order, market))
    chosen = max(due)[2] if due else None
    lines.append(f"picked: {chosen or 'nothing due'}")
    return chosen, lines


def read_stamps(directory: pathlib.Path) -> Dict[str, Optional[dt.datetime]]:
    stamps: Dict[str, Optional[dt.datetime]] = {}
    for market in mcfg.MARKETS:
        try:
            doc = json.loads((directory / f"{market}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        stamps[market] = parse_stamp(doc.get("generated_at") if isinstance(doc, dict) else None)
    return stamps


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", required=True, type=pathlib.Path,
                    help="directory holding <market>.json as committed on main")
    ap.add_argument("--now", default=None, help="ISO instant (tests); default: the clock")
    args = ap.parse_args(argv)

    now = parse_stamp(args.now) if args.now else dt.datetime.now(UTC)
    if now is None:
        ap.error(f"unreadable --now {args.now!r}")
    chosen, lines = pick(read_stamps(args.dir), now)
    print("\n".join(lines))

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"market={chosen or ''}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
