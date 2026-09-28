#!/usr/bin/env python3
"""Restate the OPEN book to the current fixed position notional.

WHY THIS EXISTS
---------------
First use, 2026-07-28. Sizing switched from risk-% off a $10,000 nominal equity
to a flat `VIVEK_BOT_POSITION_NOTIONAL` on a $150,000 book at 03:34 UTC that
day. Positions opened before that moment kept their old numbers: 24 open rows
averaging $256 of notional, $6,136 in total against a $150,000 ceiling. Each
still occupied one of the 30 slots, so filling every free slot at the new size
only reached ~$36k and the remaining ~$114k stayed hostage to the legacy rows
closing one by one, on their own schedule, over weeks. The owner's instruction
was to close that gap now by restating the legacy rows at the new size rather
than waiting them out.

Second use, 2026-09-27 (owner-approved). The notional halved to $2,500 and the
slot count doubled to 60, on the same $150,000 ceiling. The 30 open rows were
each $5,000 -- exactly the ceiling -- so until they are restated decide() drops
every new entry as `notional_cap` while 30 of the 60 slots read free. The owner
chose the July precedent again: restate the open book now. It is authorised by
a kick file (`--kick`, see USAGE) so the size a merge restates to can never
disagree with the size config.py trades new entries at.

WHAT THIS DOES AND DOES NOT CHANGE -- read this before trusting a number
-----------------------------------------------------------------------
This is a RESTATEMENT, not a trade. Nothing is bought, sold or re-marked. Every
row keeps the price it was actually filled at and the stop it was actually
given; only the size attached to those prices changes.

RESTATED (dollar quantities, all scaled by the same factor per position):
  units, notional, risk_usd, unreal_usd, risk_pct, leverage, and the dollar
  half of every `review` flag (risk_usd, share_pct, note -- see REVIEW FLAGS).
  Through risk_usd, also the dollar value of any partial exit already banked
  on an OPEN row (see BANKED PARTIALS below).

UNTOUCHED, and the reason the track record survives this:
  entry, stop, risk, signal_entry, fill_slip_bps, tp1/tp2/tp3, scale,
  last_mark, mae, mfe, exits, booked_pct, tp*_hit, and EVERY R field --
  unreal_r, realized_r, gross_r, cost_r, mae_r, mfe_r.

R is invariant under a resize, and that is the whole point. R is measured in
units of the position's own initial risk: `(price - entry) / risk`. Scaling the
size scales the numerator and the denominator of the dollar P&L together and
cancels out of the ratio entirely. So the R series -- the thing the strategy is
actually judged on -- is exactly as true after this run as before it.

The DOLLAR series is not. `unreal_usd` on a restated row now says what the
target size would have made, not what the size actually on the book made.
Anyone reading dollar P&L across a resize boundary is comparing two different
position sizes wearing the same label. The owner was told this in those words
and chose it anyway; the honest thing left to do is label it, which is why
every restated row carries `notional_before`, `units_before`, `risk_usd_before`
and `resized_at`. CLOSED positions are never touched -- they are the real track
record of what was really held, and rewriting them would destroy the only
clean dollar history the book has.

BANKED PARTIALS ON OPEN ROWS RESTATE TOO (2026-09-28). A partial exit already
taken on a row that is still OPEN is stored only as R -- `realized_r` plus the
`exits` ladder, both frozen -- and every reader (the daily/weekly guards, the
kill switch, the journal) values it in dollars as `realized_r x risk_usd`. So
halving `risk_usd` halves those banked dollars as well, lifetime and inside
the weekly-guard window; R does not move. Live case: GLBE banked its tp1 (25%)
at the $5,000 size on 2026-09-22 = $63.68, which reads $31.84 once restated.
When such a row later closes, its closed record carries the WHOLE trade at the
restated size, the pre-resize partial included; `notional_before` and
`resized_at` on the row are what say so. The report prints a line for every
restated row carrying a banked partial, naming the share and both dollar
figures, so this is seen before --apply rather than discovered after it.

WHICH STOP THE SIZING USES
--------------------------
Not the row's current `stop` -- that one trails. A position that has taken tp1
has had its stop moved to breakeven, so sizing off it would divide by a zero
stop distance and blow up. The row stores `risk`, the per-unit risk measured at
fill, and `entry - risk` reproduces the ORIGINAL stop exactly (verified against
every un-trailed row in the live book). That original distance is what
`risk_usd` has always meant, so it is what the resize sizes against.

WHICH PRICE THE SIZING USES (2026-09-27)
----------------------------------------
`signal_entry` when the row carries a usable one, else `entry`. decide() sizes
every ticket at the PLAN entry (the signal close) and the runner fills later at
a live quote; `_ticket_to_position` copies the plan's units / notional /
risk_usd onto the row and records the plan entry as `signal_entry`. So a bot
row holds `units = notional / signal_entry` and `risk_usd = units x
(signal_entry - original stop)` -- checked to the cent on all 30 open rows of
2026-09-27. Re-sizing at the FILL would re-base 22 of them onto a different
convention from every other row in the book, and their risk_usd would move by
0.34x-0.62x instead of the notional's 0.5x. Sized at the signal, every row
restates by exactly the target ratio, i.e. it reads as if the bot had opened it
at the new size. Rows written before `signal_entry` existed (the July legacy
rows) fall back to `entry`, as does a signal that is non-finite, not positive,
or on the wrong side of the stop -- never true of a real plan, but
size_position uses abs() and would otherwise size it as if it were valid.

The numbers come from `vivek_bot.size_position` itself, not from a scale factor
computed here, so a restated row is sized by the same code that sizes a new one
and cannot drift from it.

REVIEW FLAGS (2026-09-27)
-------------------------
A `review` flag (vivek_bot.review_flags, `heavy_risk`) records what was known at
ENTRY: that the plan's 1R loss was a large share of the daily loss guard. Its
risk_usd, share_pct and note are dollars of the size the row was taken at, so
a resize restates them by the same factor as the row's own risk_usd and
rebuilds the note in review_flags' exact wording (pinned byte-for-byte by the
tests). code, stop_pct and limit_usd are kept. A flag is NEVER added or dropped
-- whether the row was flagged is an entry-time fact a resize does not change.
The as-taken list is kept in `review_before` (written once, never overwritten
by a later resize). A row with no `review` key stays without one: absent
(written before flags existed) and `[]` (checked, clean) are different facts.

THE GUARD BLOCK (2026-09-27)
----------------------------
An applied market's `summary` AND `guard` are rewritten through
`vivek_run._restamp`, the engine's one writer for both (TOP100 #21), for the
SAME session day the stored guard already describes. Priced off each row's own
`last_mark` and carrying `notified` forward, so on an unchanged book it is the
identity (checked on all three live books, 2026-09-27) and after a resize it is
the same window restated at the new size -- instead of $5,000-era guard dollars
sitting in the file until that market's next run (days, over a weekend).
_restamp never lets the guard be the reason a book fails to save: if
vivek_guard.check raises it logs a warning, rewrites `summary` anyway and
leaves the stored guard block as it was. `restamp` below detects that (the
per-market guard dict is still the SAME object afterwards) and the "wrote" line
then says "guard NOT restamped" instead of claiming it was. Display-only either
way: run_market recomputes the guard itself before decide() is ever called.

USAGE
-----
    python -m scripts.resize_book_notional              # dry run, prints report
    python -m scripts.resize_book_notional --check      # read-only: exit 0 = all
                                                         # at target, 3 = pending,
                                                         # 4 = stuck (see below)
    python -m scripts.resize_book_notional --apply      # writes the books
    python -m scripts.resize_book_notional --apply --kick .github/resize-kick

DRY BY DEFAULT. It mutates the live track record, so it does nothing at all
until `--apply` is passed. It is also IDEMPOTENT: a row already at the target
notional is left alone, so a second `--apply` is a no-op rather than a
compounding rescale -- and when no row needs restating it writes no file at all.

EXIT CODES. `--check` never writes and cannot be combined with `--apply`.
  0  no open row is off the target -- INCLUDING rows this script cannot size:
     a row it cannot restate only counts as "at target" if it already is one.
  3  (--check) at least one open row would be resized. NOT 1: a traceback
     exits 1, and a crash must never read as "pending" or as "nothing to do".
  4  STUCK: an open row is off the target but cannot be restated (no usable
     entry/risk basis, or the sizer returned nothing). --check returns it
     whenever such a row exists, pending rows or not (4 wins over 3: --apply is
     certain to refuse, so the workflow must not queue a writer into the
     one-slot scan mutex for it -- review RR-5, 2026-09-28); --apply returns
     it BEFORE writing anything, pending rows or not -- every
     doubt resolves to "write nothing", never to a book left half at the old
     size under a green "at target". The symbols are printed either way.
  2  a refused invocation (bad target/equity, --check with --apply, a kick
     that is malformed or disagrees with the target); argparse usage errors
     exit 2 as well.
  1  a crash (an uncaught exception), or --apply whose verify_books() found a
     problem.
A dry run (neither flag) prints the report, names any stuck rows, and exits 0.
`--kick PATH` refuses (exit 2) unless the file holds exactly one non-comment
line `target=<positive dollars>` equal to the effective `--target` to the
cent; it applies to dry, `--check` and `--apply` runs alike.
"""

from __future__ import annotations

import argparse
import copy
import datetime as _dt
import json
import math
import pathlib
import re
import sys
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner import config                                        # noqa: E402
from scanner.broker import vivek_bot, vivek_run                   # noqa: E402
from scanner.journal_common import atomic_write                   # noqa: E402

# Fields the resize is allowed to write. Anything not in here is frozen, and
# `frozen_fingerprint` below is what proves it stayed frozen. `review` is
# written (restated), so it is deliberately NOT in FROZEN.
WRITES = ("units", "notional", "risk_usd", "risk_pct", "leverage",
          "unreal_usd", "sizing_mode",
          "notional_before", "units_before", "risk_usd_before", "resized_at",
          "review", "review_before")

# The fields whose survival is the argument for doing this at all. Checked
# before and after on every row; any difference is a bug, not a rounding.
# signal_entry / fill_slip_bps joined 2026-09-27: the resize now READS
# signal_entry as its sizing price, so it must provably never write it.
FROZEN = ("id", "symbol", "market", "direction", "entry", "stop", "risk",
          "tp1", "tp2", "tp3", "scale", "last_mark", "mae", "mfe",
          "mae_r", "mfe_r", "unreal_r", "realized_r", "gross_r", "cost_r",
          "booked_pct", "tp1_hit", "tp2_hit", "tp3_hit", "exits",
          "entry_date", "opened_at", "status", "rr", "leverage_target",
          "signal_entry", "fill_slip_bps")

_CENT = 0.005

# `--check` exit code when at least one open row would be resized. 0 = none
# off target, 2 = refused (bad target, bad flags, bad kick), STUCK_EXIT below =
# off target but not restatable. NOT 1, on purpose:
# an uncaught Python exception also exits 1, and the workflow that gates on
# this must never read a crash as "rows pending" -- or, worse, as "nothing to do".
CHECK_PENDING_EXIT = 3

# Exit code when an open row is OFF the target but this script cannot restate
# it (2026-09-28, review F2). Before this, --check counted only rows it WOULD
# resize, so a $5,000 row with no usable basis read "0 open row(s) off" and the
# workflow reported a green "already at target" with the row left behind. A
# DISTINCT code, not 2 (a refused invocation) and not 3 (pending): it is the
# one outcome a human has to look at a row to resolve. --check returns it
# whenever a stuck row exists (it wins over 3 -- --apply would refuse anyway);
# --apply returns it before writing a single file.
STUCK_EXIT = 4

# The skip reasons that mean "could not size it", as opposed to "did not need
# to" ("already at target") or "not ours to touch" ("not open").
STUCK_REASONS = ("no usable entry/risk basis", "sizer returned nothing")

_KICK_LINE = re.compile(r"target\s*=\s*(\S+)")


def kick_target(path) -> float:
    """The per-position notional a resize kick file authorises.

    The kick is how an owner-approved resize travels with a merge: the file
    names the size, and `--kick` refuses unless that size equals the target the
    run would restate to (config's VIVEK_BOT_POSITION_NOTIONAL by default). The
    format is strict because every doubt must resolve to "write nothing":
    `#` starts a comment line, blank lines are ignored, and exactly ONE other
    line must remain, reading `target=<positive number>`. Raises ValueError,
    naming the problem, on anything else -- a missing file, a second target
    (an ambiguous instruction), a stray line, a non-number, nan/inf, or <= 0.
    Read as utf-8-sig so a stray byte-order mark (the 2026-08-01 lesson) cannot
    turn the first comment into a "stray line".
    """
    p = pathlib.Path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise ValueError(f"kick file {p} cannot be read ({e.strerror or e})") from None
    body = [ln.strip() for ln in text.splitlines()]
    body = [ln for ln in body if ln and not ln.startswith("#")]
    if len(body) != 1:
        raise ValueError(f"kick file {p} must hold exactly one non-comment line "
                         f"'target=<dollars>', found {len(body)}")
    m = _KICK_LINE.fullmatch(body[0])
    if not m:
        raise ValueError(f"kick file {p}: expected 'target=<dollars>', "
                         f"got {body[0]!r}")
    try:
        value = float(m.group(1))
    except ValueError:
        raise ValueError(f"kick file {p}: target {m.group(1)!r} is not a "
                         f"number") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"kick file {p}: target must be a positive number, "
                         f"got {m.group(1)!r}")
    return value


def frozen_fingerprint(pos: dict) -> str:
    """Canonical JSON of the fields a resize must never move. Compare, not trust."""
    return json.dumps({k: pos.get(k) for k in FROZEN}, sort_keys=True,
                      separators=(",", ":"))


def basis_stop(pos: dict) -> float | None:
    """The ORIGINAL stop this position's `risk` was measured against.

    Reconstructed from `entry` and `risk` rather than read from `stop`, because
    `stop` trails: a position that has taken tp1 has had its stop moved to
    breakeven, and sizing off a zero stop distance is meaningless. Returns None
    when the row cannot be sized at all (no entry, no risk, a NaN/inf in either,
    or a risk so large it would put a long's stop at or below zero).

    The isfinite test is load-bearing, not tidiness (TOP100 #63's pattern):
    `nan <= 0` is False, so without it a NaN risk or entry sailed past the
    guard, the row was RESIZED rather than skipped, and NaN was written into
    units / risk_usd / unreal_usd -- where a NaN inside a sum disarms the loss
    guards. The frozen-field check cannot see it (NaN serialises identically).
    """
    try:
        entry = float(pos.get("entry") or 0.0)
        risk = float(pos.get("risk") or 0.0)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(entry) and math.isfinite(risk)) or entry <= 0 or risk <= 0:
        return None
    short = str(pos.get("direction") or "long").lower() == "short"
    stop = entry + risk if short else entry - risk
    if not short and stop <= 0:
        return None
    return stop


def stop_pct(pos: dict) -> float:
    """|entry - original stop| as a % of the FILL. 0.0 when unsizeable.

    Measured from the fill on purpose: it is what the report's wide-stop list
    compares against VIVEK_BOT_MAX_STOP_PCT, and the runner re-reads that cap
    at the fill (2026-09-24). The sizer's own stop width is `sizing_price`'s.
    """
    stop = basis_stop(pos)
    if stop is None:
        return 0.0
    entry = float(pos["entry"])
    return abs(entry - stop) / entry * 100.0


def sizing_price(pos: dict, stop: float) -> tuple[float, str]:
    """The price the bot SIZED this row at, and which field it came from.

    `signal_entry` (the plan entry decide() sized the ticket at) when it is
    finite, positive and on the correct side of the original stop; otherwise
    the fill, `entry`. See WHICH PRICE THE SIZING USES in the module docstring.
    """
    entry = float(pos["entry"])
    try:
        sig = float(pos.get("signal_entry") or 0.0)
    except (TypeError, ValueError):
        sig = 0.0
    short = str(pos.get("direction") or "long").lower() == "short"
    if math.isfinite(sig) and sig > 0 and ((sig < stop) if short else (sig > stop)):
        return sig, "signal_entry"
    return entry, "entry"


def review_note(risk: float, share: float, limit: float, spct: float) -> str:
    """The note vivek_bot.review_flags writes -- SAME WORDING, byte for byte.

    Re-typed rather than imported because vivek_bot.py is ringfenced and
    exposes no helper; tests/test_resize_book_notional.py pins it against the
    real review_flags output so the two cannot drift silently.
    """
    return (f"a 1R loss here is ${risk:,.0f} - {share:.0f}% of the "
            f"${limit:,.0f} daily loss guard, on a {spct:.0f}% stop")


def restate_review(flags: list, k: float, spct: float) -> list:
    """Restate each heavy_risk flag's DOLLAR figures by `k` (risk after / before).

    Keeps code, stop_pct and limit_usd; rewrites risk_usd, share_pct and the
    note. share_pct is re-derived from the restated risk_usd and the flag's own
    limit_usd (review_flags' formula) rather than multiplied, so a 1-dp rounding
    cannot compound into a figure review_flags would never write. NEVER adds or
    drops a flag, and carries any other code verbatim.
    """
    out = []
    for f in flags:
        if not isinstance(f, dict) or f.get("code") != "heavy_risk":
            out.append(copy.deepcopy(f))
            continue
        g = dict(f)
        risk = round(float(f.get("risk_usd") or 0.0) * k, 2)
        limit = float(f.get("limit_usd") or 0.0)
        share = (risk / limit * 100.0 if limit > 0
                 else float(f.get("share_pct") or 0.0) * k)
        g["risk_usd"] = risk
        g["share_pct"] = round(share, 1)
        g["note"] = review_note(risk, share, limit, spct)
        out.append(g)
    return out


def resize_position(pos: dict, target: float, equity: float, stamp: str,
                    max_stop_pct: float = 0.0) -> dict:
    """Restate one open position at `target` notional. Mutates and returns `pos`.

    `max_stop_pct` (0 = off, the default) caps the DOLLAR RISK a restated row
    may carry at what a position with that stop width would risk at the full
    target -- i.e. notional falls to `target * max_stop_pct / stop_pct` for a
    row whose stop is wider than that, measured at the price the row is sized
    at. See the CLI help for why the option exists and why it is off by default.

    Returns a change record: {"symbol", "action", "reason", "before", "after"}.
    `action` is "resized" or "skipped"; a skip never mutates. `want` is the
    notional this run would give the row (the target, or the capped size under
    --max-stop-pct) and stays None when no basis exists to compute it;
    `booked_pct` / `n_exits` / `realized_r` let the report name a banked
    partial whose dollars restate with the row.
    """
    sym = str(pos.get("symbol") or "?")
    rec = {"symbol": sym, "market": str(pos.get("market") or ""),
           "action": "skipped", "reason": "", "capped": 0.0,
           "stop_pct": round(stop_pct(pos), 4),
           "notional_before": pos.get("notional"), "notional_after": pos.get("notional"),
           "risk_usd_before": pos.get("risk_usd"), "risk_usd_after": pos.get("risk_usd"),
           "units_before": pos.get("units"), "units_after": pos.get("units"),
           "sized_at": "", "review_restated": 0, "want": None,
           "booked_pct": pos.get("booked_pct"),
           "n_exits": (len(pos["exits"]) if isinstance(pos.get("exits"), list)
                       else 0),
           "realized_r": pos.get("realized_r")}

    if str(pos.get("status") or "open") != "open":
        rec["reason"] = "not open"
        return rec

    stop = basis_stop(pos)
    if stop is None:
        rec["reason"] = "no usable entry/risk basis"
        return rec

    px, basis = sizing_price(pos, stop)
    spct = abs(px - stop) / px * 100.0          # the stop width the SIZER sees
    want = target
    if max_stop_pct > 0 and spct > max_stop_pct:
        want = round(target * max_stop_pct / spct, 2)
        rec["capped"] = round(spct, 2)
    rec["want"] = want

    try:
        now = float(pos.get("notional") or 0.0)
    except (TypeError, ValueError):
        now = 0.0
    if abs(now - want) < _CENT:
        # Idempotence: already at the size this run would give it. Saying so out
        # loud beats silently rescaling a row a second --apply would rescale
        # again -- and it has to compare against `want`, not `target`, or a
        # risk-capped row would be re-capped from its own capped notional.
        rec["reason"] = "already at target"
        return rec

    sizing = vivek_bot.size_position(equity, px, stop, notional_target=want)
    if sizing["units"] <= 0 or sizing["notional"] <= 0:
        rec["reason"] = "sizer returned nothing"
        return rec

    # The one factor every dollar field on the row moves by.
    try:
        rb = float(pos.get("risk_usd") or 0.0)
    except (TypeError, ValueError):
        rb = 0.0
    k = sizing["risk_usd"] / rb if (math.isfinite(rb) and rb > 0) else 0.0

    # REVIEW FLAGS (2026-09-27). `review_before` keeps the list AS TAKEN: a
    # later resize must not overwrite the entry-time record with an already
    # restated one. Absent stays absent; [] restates to [].
    if "review" in pos:
        if "review_before" not in pos:
            pos["review_before"] = copy.deepcopy(pos["review"])
        if isinstance(pos["review"], list) and pos["review"] and k > 0:
            pos["review"] = restate_review(pos["review"], k, spct)
            rec["review_restated"] = sum(
                1 for f in pos["review"]
                if isinstance(f, dict) and f.get("code") == "heavy_risk")

    pos["notional_before"] = pos.get("notional")
    pos["units_before"] = pos.get("units")
    pos["risk_usd_before"] = pos.get("risk_usd")
    pos["resized_at"] = stamp

    pos["units"] = sizing["units"]
    pos["notional"] = sizing["notional"]
    pos["risk_usd"] = sizing["risk_usd"]
    pos["risk_pct"] = sizing["risk_pct"]
    pos["leverage"] = sizing["leverage"]
    pos["sizing_mode"] = sizing["sizing_mode"]
    # The dollar mark moves by the SAME factor as risk_usd, R unchanged. The
    # engine stamps it as `unreal_r * risk_usd` off the UNROUNDED R, so scaling
    # the stored figure lands within a cent of what the next marked run writes,
    # where rebuilding it from the stored 3-dp unreal_r can miss by far more on
    # a large position. Rebuilt from R only when there is no factor to scale by.
    try:
        uu = float(pos.get("unreal_usd"))
    except (TypeError, ValueError):
        uu = float("nan")
    if k > 0 and math.isfinite(uu):
        pos["unreal_usd"] = round(uu * k, 2)
    else:
        try:
            ur = float(pos.get("unreal_r") or 0.0)
        except (TypeError, ValueError):
            ur = 0.0
        pos["unreal_usd"] = round(ur * sizing["risk_usd"], 2)

    rec.update(action="resized", reason="", sized_at=basis,
               notional_after=pos["notional"], risk_usd_after=pos["risk_usd"],
               units_after=pos["units"])
    return rec


def resize_market(market: str, target: float, equity: float, stamp: str,
                  max_stop_pct: float = 0.0) -> tuple[dict | None, list[dict]]:
    """Load one canonical market book, resize its open rows, return (book, changes).

    Nothing is written here -- the caller decides. Returns (None, []) when the
    market has no book file.
    """
    path = vivek_run._market_book_file(market)
    if not path.exists():
        return None, []
    book = json.loads(path.read_text(encoding="utf-8"))
    rows = book.get("open") or []

    before = [frozen_fingerprint(p) for p in rows]
    changes = [resize_position(p, target, equity, stamp, max_stop_pct)
               for p in rows]
    after = [frozen_fingerprint(p) for p in rows]

    drifted = [rows[i].get("symbol") for i in range(len(rows)) if before[i] != after[i]]
    if drifted:
        # Loud, not a warning. The one claim this script makes is that R and the
        # fill prices survive it; if that is false the run must not be written.
        raise AssertionError(
            f"{market}: resize moved a frozen field on {drifted} - refusing to write")

    return book, changes


def summarise(book: dict, day: str) -> dict:
    """The market book's summary block -- the engine's own writer, not a copy.

    main() no longer calls this: `restamp` below rewrites summary AND guard
    through vivek_run._restamp, which builds the summary with this same
    function. Kept so the shape stays pinned in one obvious place.
    """
    return vivek_run._summary_of(book, day)


def restamp(book: dict, market: str) -> tuple[str, bool]:
    """Rewrite `summary` + `guard` through vivek_run._restamp.

    Returns (day, guard_restamped). The day is the one the stored guard already
    describes (then the summary's `updated_day`, then the market's local today
    -- close_bot_position's rule), so the restamp restates the SAME session
    window at the new size rather than opening a new one: a guard re-dated to a
    day no run has stamped a `day_marks` reference for yet would charge the
    oldest stored mark to it and publish several sessions of P&L as one. Priced
    off `last_mark`; `notified` is carried forward by _restamp itself.

    `guard_restamped` is False when _restamp swallowed a vivek_guard.check
    failure (it logs a warning and returns without touching the guard). The
    signal is object IDENTITY: on success _restamp installs the fresh dict
    check() builds, so the per-market block is a different object afterwards;
    on the swallowed path it is the very same object (or still absent). Read
    here rather than by changing vivek_run, whose contract -- never let the
    guard be the reason a save is lost -- is right as it stands.
    """
    prev = (book.get("guard") or {}).get(market)
    day = str((prev or {}).get("day") or "")
    if not day:
        day = str((book.get("summary") or {}).get("updated_day") or "")
    if not day:
        tz = config.MARKETS[market].timezone if market in config.MARKETS else "UTC"
        day = _dt.datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")
    vivek_run._restamp(book, market, day)
    now = (book.get("guard") or {}).get(market)
    return day, (now is not None and now is not prev)


def _num(x) -> float:
    """float(x), or NaN for anything unparseable. Never raises."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def _fin(x) -> float:
    """float(x) when finite, else 0.0 -- for the report's running totals."""
    v = _num(x)
    return v if math.isfinite(v) else 0.0


def banked_line(c: dict) -> str:
    """The report line for a RESTATED row that already banked a partial exit.

    "" when the row banked nothing (booked_pct 0/absent AND no exits). The
    dollars are realized_r x risk_usd before and after -- the valuation every
    reader applies to a banked partial on an open row -- so the owner sees the
    realised money move, not only the open exposure. R is quoted to show it
    does not. See BANKED PARTIALS ON OPEN ROWS in the module docstring.
    """
    bp = _num(c.get("booked_pct"))
    n = int(c.get("n_exits") or 0)
    has_bp = math.isfinite(bp) and bp > 0
    if not has_bp and n <= 0:
        return ""
    share = f"{bp * 100:.0f}%" if has_bp else f"{n} exit(s)"
    nb = _num(c.get("notional_before"))
    rr = _num(c.get("realized_r"))
    rb = _num(c.get("risk_usd_before"))
    ra = _num(c.get("risk_usd_after"))
    at = f" at ${nb:,.0f}" if math.isfinite(nb) else ""
    money = (f"realised ${rr * rb:,.2f} -> ${rr * ra:,.2f} "
             if all(math.isfinite(v) for v in (rr, rb, ra)) else "")
    r = f" ({rr:+.4f}R)" if math.isfinite(rr) else ""
    return (f"           {c['symbol']}: {share} already banked{at} - its "
            f"{money or 'realised $ '}is restated with the row; R unchanged{r}")


def report(results: dict, target: float, equity: float) -> list[str]:
    """Human-readable before/after. Printed in dry, --check and applied runs."""
    lines: list[str] = []
    tot_before = tot_after = 0.0
    risk_before = risk_after = 0.0
    n_resized = n_skipped = n_signal = n_review = n_banked = 0
    per_market: list[tuple[str, float]] = []
    wide: list[tuple[float, str, float]] = []
    gate = float(getattr(config, "VIVEK_BOT_MAX_STOP_PCT", 0) or 0)
    for market in sorted(results):
        changes = results[market]["changes"]
        if not changes:
            continue
        lines.append(f"  {market.upper()}")
        m_risk = 0.0
        for c in changes:
            # _fin, not float(): a hand-edited "junk" or NaN notional must not
            # crash the report (or poison every total) before the stuck-row
            # line below it can name the row.
            nb = _fin(c["notional_before"])
            na = _fin(c["notional_after"])
            rb = _fin(c["risk_usd_before"])
            ra = _fin(c["risk_usd_after"])
            tot_before += nb
            tot_after += na
            risk_before += rb
            risk_after += ra
            m_risk += ra
            if c["action"] == "resized":
                n_resized += 1
                n_signal += c.get("sized_at") == "signal_entry"
                n_review += bool(c.get("review_restated"))
                flag = f"  CAPPED (stop {c['capped']:.0f}%)" if c.get("capped") else ""
                lines.append(
                    f"    {c['symbol']:<6} ${nb:>9,.2f} -> ${na:>9,.2f}   "
                    f"risk ${rb:>8,.2f} -> ${ra:>8,.2f}   "
                    f"x{(na / nb if nb else 0):.2f}  risk x{(ra / rb if rb else 0):.3f}"
                    f"{'  [review restated]' if c.get('review_restated') else ''}"
                    f"{flag}")
                banked = banked_line(c)
                if banked:
                    n_banked += 1
                    lines.append(banked)
            else:
                n_skipped += 1
                lines.append(f"    {c['symbol']:<6} "
                             f"${_num(c['notional_before'] or 0.0):>9,.2f}   SKIPPED "
                             f"({c['reason']})")
            if gate > 0 and c["stop_pct"] > gate:
                wide.append((c["stop_pct"], c["symbol"], ra))
        per_market.append((market, m_risk))

    cap = float(getattr(config, "VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL", 0) or 0)
    daily = equity * float(getattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 0) or 0) / 100.0
    lines.append("")
    lines.append(f"  target ${target:,.0f}/position on ${equity:,.0f} equity")
    lines.append(f"  {n_resized} resized ({n_signal} sized at signal_entry, "
                 f"{n_resized - n_signal} at the fill; {n_review} with review "
                 f"flags restated), {n_skipped} skipped")
    if n_banked:
        lines.append(f"  {n_banked} restated row(s) carry a partial exit banked "
                     "at the old size: its realised $ restates with the row "
                     "(realized_r x risk_usd); R unchanged")
    lines.append(f"  open notional ${tot_before:,.2f} -> ${tot_after:,.2f}"
                 + (f"  ({tot_after / cap * 100:.1f}% of the ${cap:,.0f} cap)"
                    if cap else ""))
    lines.append(f"  open RISK     ${risk_before:,.2f} -> ${risk_after:,.2f}"
                 + (f"  ({risk_after / equity * 100:.1f}% of equity if every "
                    f"stop hit at once)" if equity else ""))
    # The daily guard is PER MARKET and a fixed dollar figure, so the number
    # that says whether it is reachable is each market's own stop-out total.
    if daily and per_market:
        lines.append(f"  whole-market stop-out at this size vs the ${daily:,.0f} "
                     f"daily loss guard:")
        for market, r in per_market:
            lines.append(f"    {market.upper():<6} ${r:>9,.2f} = "
                         f"{r / daily * 100:.1f}% of the guard")

    # The consequence the raw notional figure hides. The daily guard is a fixed
    # dollar limit that does not scale with position size, so a wide stop's
    # share of it grows with the target.
    if wide:
        wide.sort(reverse=True)
        lines.append("")
        lines.append(f"  WIDE STOPS: {len(wide)} position(s) sit beyond the "
                     f"{gate:.0f}% max_stop_pct gate, measured from the fill.")
        lines.append("  Each was booked before a gate that would refuse it now "
                     "(the cap itself, or its")
        lines.append("  re-read at the fill from 2026-09-24). At this size each "
                     "now risks:")
        for sp, sym, r in wide:
            share = (r / daily * 100.0) if daily else 0.0
            lines.append(f"    {sym:<6} stop {sp:5.1f}% of entry   risk "
                         f"${r:>8,.2f}"
                         + (f"   = {share:.0f}% of the ${daily:,.0f} daily "
                            f"loss limit" if daily else ""))
        lines.append("  --max-stop-pct trims these back; it is OFF by default "
                     "because trimming is an")
        lines.append("  exposure decision, not a migration detail.")
    return lines


def stuck_rows(results: dict, target: float) -> list[dict]:
    """Open rows OFF the target that this run could not restate (review F2).

    A skip for one of STUCK_REASONS whose notional is not within a cent of the
    size this run wanted for it -- `want` when the sizer got far enough to
    compute one, else `target`. A row that cannot be sized but already sits at
    the target is NOT stuck: nothing is left behind. An unreadable or NaN
    notional counts as off (the comparison is written `not (... < _CENT)` so a
    NaN lands on the stuck side): every doubt resolves to "write nothing".
    Each entry is the change record plus the results' market key.
    """
    out = []
    for market, res in results.items():
        for c in res["changes"]:
            if c.get("action") != "skipped" or c.get("reason") not in STUCK_REASONS:
                continue
            want = c.get("want")
            goal = float(want) if want is not None else float(target)
            if not (abs(_num(c.get("notional_before")) - goal) < _CENT):
                out.append(dict(c, market=market))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "exit codes:\n"
            "  0  every open row is at --target, rows this script cannot\n"
            "     size INCLUDED (a dry run also exits 0 after its report)\n"
            f"  {CHECK_PENDING_EXIT}  --check: at least one open row would be resized\n"
            f"  {STUCK_EXIT}  an open row is off --target but cannot be restated\n"
            "     (--check whenever one exists; --apply before writing)\n"
            "  2  refused: bad --target/--equity, --check with --apply, a bad\n"
            "     or disagreeing --kick, or a usage error\n"
            "  1  a crash (traceback), or --apply whose verify_books() failed"))
    ap.add_argument("--target", type=float,
                    default=float(getattr(config, "VIVEK_BOT_POSITION_NOTIONAL", 0) or 0),
                    help="notional per position (default: config)")
    ap.add_argument("--equity", type=float,
                    default=float(getattr(config, "VIVEK_BOT_ACCOUNT_EQUITY", 0) or 0),
                    help="equity the reported risk_pct/leverage divide by")
    ap.add_argument("--market", action="append", default=None,
                    help="limit to one market (repeatable); default all")
    ap.add_argument("--max-stop-pct", type=float, default=0.0,
                    help="OFF by default. Cap the dollar risk a restated row "
                         "may carry at what a stop this wide would risk at the "
                         "full target, sizing wide-stop rows down instead. "
                         "Exists because several legacy rows have stops beyond "
                         "the max_stop_pct gate a new entry must pass, and at "
                         "the full target they would each risk a large slice "
                         "of the daily loss limit. Trimming them is an "
                         "exposure decision, so it is not the default.")
    ap.add_argument("--apply", action="store_true",
                    help="actually write. Without it nothing is written. "
                         f"Refused (exit {STUCK_EXIT}, no file written) when "
                         "any open row is off --target but cannot be restated.")
    ap.add_argument("--check", action="store_true",
                    help="read-only: exit 0 when every open row is at "
                         "--target (unsizeable rows included), "
                         f"{CHECK_PENDING_EXIT} when at least one would be "
                         f"resized, {STUCK_EXIT} when any open row is off "
                         "target and cannot be restated (wins over "
                         f"{CHECK_PENDING_EXIT}). Writes nothing; "
                         "refused with --apply.")
    ap.add_argument("--kick", default=None, metavar="PATH",
                    help="a resize kick file. Refuses (exit 2) unless it holds "
                         "exactly one non-comment line target=<dollars> equal "
                         "to --target (default: config), so a kick can only "
                         "ever restate the book to the size config.py already "
                         "trades new entries at.")
    args = ap.parse_args(argv)

    if args.target <= 0:
        print("ERROR: --target must be > 0 (fixed-notional sizing is off?)")
        return 2
    if args.equity <= 0:
        print("ERROR: --equity must be > 0")
        return 2
    if args.check and args.apply:
        print("ERROR: --check is read-only and cannot be combined with --apply")
        return 2
    kicked = None
    if args.kick is not None:
        # Both refusals happen BEFORE any book is loaded, let alone written.
        try:
            kicked = kick_target(args.kick)
        except ValueError as e:
            print(f"ERROR: {e} - nothing is authorised")
            return 2
        if abs(kicked - args.target) >= _CENT:
            print(f"ERROR: kick file {args.kick} authorises ${kicked:,.2f}/position "
                  f"but the target is ${args.target:,.2f} (config "
                  "VIVEK_BOT_POSITION_NOTIONAL unless --target was passed) - "
                  "refusing to restate the book to a size config does not trade")
            return 2

    markets = args.market or list(config.MARKETS)
    stamp = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()

    print(f"RESIZE  open book -> ${args.target:,.0f}/position", flush=True)
    if kicked is not None:
        print(f"  kick {args.kick}: target=${kicked:,.2f} matches --target",
              flush=True)
    results: dict = {}
    for market in markets:
        book, changes = resize_market(market, args.target, args.equity, stamp,
                                      args.max_stop_pct)
        if book is None:
            print(f"  {market}: no book file - skipped", flush=True)
            continue
        results[market] = {"book": book, "changes": changes}

    for line in report(results, args.target, args.equity):
        print(line, flush=True)

    pending = sum(1 for res in results.values() for c in res["changes"]
                  if c["action"] == "resized")
    stuck = stuck_rows(results, args.target)
    syms = ", ".join(f"{c['symbol']} ({c['market']})" for c in stuck)
    if stuck:
        print("", flush=True)
        print(f"  NOT RESTATABLE: {len(stuck)} open row(s) off the "
              f"${args.target:,.0f} target that this script cannot size -- "
              "fix the row by hand (or close it), then re-run:", flush=True)
        for c in stuck:
            print(f"    {c['market'].upper():<6} {c['symbol']:<6} "
                  f"${_num(c.get('notional_before')):>9,.2f}  ({c['reason']})",
                  flush=True)
    if args.check:
        # "N open row(s) off the $X target" counts EVERY off-target row, the
        # unsizeable ones included -- the line used to count only the rows it
        # would resize and read 0 over a $5,000 row it had skipped.
        print(f"  CHECK: {pending + len(stuck)} open row(s) off the "
              f"${args.target:,.0f} target - {pending} to restate, "
              f"{len(stuck)} off target but NOT restatable"
              + (f": {syms}" if stuck else ""), flush=True)
        # STUCK wins over PENDING (review RR-5): --apply refuses before writing
        # whenever a stuck row exists, so reporting "pending" would only queue a
        # writer into the one-slot scan mutex -- where it can evict a real scan
        # -- to do nothing.
        if stuck:
            return STUCK_EXIT
        return CHECK_PENDING_EXIT if pending else 0

    if not args.apply:
        print("")
        print("  dry run: nothing written. Re-run with --apply to commit.",
              flush=True)
        return 0

    if stuck:
        # BEFORE any write, pending rows or not: restating the other rows and
        # leaving these at the old size is exactly the green half-done state
        # the stuck check exists to prevent.
        print(f"  REFUSED: {len(stuck)} open row(s) off target cannot be "
              f"restated ({syms}) - nothing written", flush=True)
        return STUCK_EXIT

    if not pending:
        # A true no-op: the canonical files AND the derived pair stay
        # byte-identical, so a re-run leaves nothing to commit.
        print("  nothing to restate: every open row is already at target - "
              "no file written", flush=True)
    else:
        for market, res in results.items():
            if not any(c["action"] == "resized" for c in res["changes"]):
                continue
            book = res["book"]
            day, guard_ok = restamp(book, market)
            book["updated_at"] = stamp
            atomic_write(vivek_run._market_book_file(market),
                         json.dumps(book, indent=2))
            what = (f"summary + guard restamped for {day}" if guard_ok else
                    f"summary restamped for {day}; guard NOT restamped - see "
                    "warning above, the stored guard still carries the old "
                    "size until this market's next run")
            print(f"  wrote journal/vivek_bot_book.{market}.json ({what})",
                  flush=True)

        # The combined file and its public twin are DERIVED. Regenerating them
        # from the canonical files is what keeps verify_books() happy on the
        # next scan.
        vivek_run._write_combined()
        print("  rebuilt the derived combined book + public twin", flush=True)

    problems = vivek_run.verify_books()
    for p in problems:
        print(f"  VERIFY: {p}", flush=True)
    print(f"  verify_books: {len(problems)} problem(s)", flush=True)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
