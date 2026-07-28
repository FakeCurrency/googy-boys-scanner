#!/usr/bin/env python3
"""Restate the OPEN book to the current fixed position notional.

WHY THIS EXISTS
---------------
Sizing switched from risk-% off a $10,000 nominal equity to a flat
`VIVEK_BOT_POSITION_NOTIONAL` on a $150,000 book at 03:34 UTC on 2026-07-28.
Positions opened before that moment kept their old numbers: 24 open rows
averaging $256 of notional, $6,136 in total against a $150,000 ceiling. Each
still occupies one of the 30 slots, so filling every free slot at the new size
only reached ~$36k and the remaining ~$114k stayed hostage to the legacy rows
closing one by one, on their own schedule, over weeks.

The owner's instruction (2026-07-28) was to close that gap now by restating the
legacy rows at the new size rather than waiting them out.

WHAT THIS DOES AND DOES NOT CHANGE -- read this before trusting a number
-----------------------------------------------------------------------
This is a RESTATEMENT, not a trade. Nothing is bought, sold or re-marked. Every
row keeps the price it was actually filled at and the stop it was actually
given; only the size attached to those prices changes.

RESTATED (dollar quantities, all scaled by the same factor per position):
  units, notional, risk_usd, unreal_usd, risk_pct, leverage

UNTOUCHED, and the reason the track record survives this:
  entry, stop, risk, tp1/tp2/tp3, scale, last_mark, mae, mfe, exits,
  booked_pct, tp*_hit, and EVERY R field -- unreal_r, realized_r, gross_r,
  cost_r, mae_r, mfe_r.

R is invariant under a resize, and that is the whole point. R is measured in
units of the position's own initial risk: `(price - entry) / risk`. Scaling the
size scales the numerator and the denominator of the dollar P&L together and
cancels out of the ratio entirely. So the R series -- the thing the strategy is
actually judged on -- is exactly as true after this run as before it.

The DOLLAR series is not. `unreal_usd` on a legacy row now says what $5,000
would have made, not what the ~$256 actually on the book made. Anyone reading
dollar P&L across the 2026-07-28 boundary is comparing two different position
sizes wearing the same label. The owner was told this in those words and chose
it anyway; the honest thing left to do is label it, which is why every restated
row carries `notional_before`, `units_before`, `risk_usd_before` and
`resized_at`. The 12 CLOSED positions are never touched -- they are the real
track record of what was really held, and rewriting them would destroy the only
clean dollar history the book has.

WHICH STOP THE SIZING USES
--------------------------
Not the row's current `stop` -- that one trails. BGA's stop has already been
moved up to breakeven, so sizing off it would divide by a zero stop distance
and blow up. The row stores `risk`, the per-unit risk measured at fill, and
`entry - risk` reproduces the ORIGINAL stop exactly (verified against every
un-trailed row in the live book). That original distance is what `risk_usd`
has always meant, so it is what the resize sizes against.

The numbers come from `vivek_bot.size_position` itself, not from a scale factor
computed here, so a restated row is sized by the same code that sizes a new one
and cannot drift from it.

USAGE
-----
    python -m scripts.resize_book_notional              # dry run, prints report
    python -m scripts.resize_book_notional --apply      # writes the books

DRY BY DEFAULT. It mutates the live track record, so it does nothing at all
until `--apply` is passed. It is also IDEMPOTENT: a row already at the target
notional is left alone, so a second `--apply` is a no-op rather than a
compounding rescale.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner import config                                        # noqa: E402
from scanner.broker import vivek_bot, vivek_run                   # noqa: E402
from scanner.journal_common import atomic_write                   # noqa: E402

# Fields the resize is allowed to write. Anything not in here is frozen, and
# `frozen_fingerprint` below is what proves it stayed frozen.
WRITES = ("units", "notional", "risk_usd", "risk_pct", "leverage",
          "unreal_usd", "sizing_mode",
          "notional_before", "units_before", "risk_usd_before", "resized_at")

# The fields whose survival is the argument for doing this at all. Checked
# before and after on every row; any difference is a bug, not a rounding.
FROZEN = ("id", "symbol", "market", "direction", "entry", "stop", "risk",
          "tp1", "tp2", "tp3", "scale", "last_mark", "mae", "mfe",
          "mae_r", "mfe_r", "unreal_r", "realized_r", "gross_r", "cost_r",
          "booked_pct", "tp1_hit", "tp2_hit", "tp3_hit", "exits",
          "entry_date", "opened_at", "status", "rr", "leverage_target")

_CENT = 0.005


def frozen_fingerprint(pos: dict) -> str:
    """Canonical JSON of the fields a resize must never move. Compare, not trust."""
    return json.dumps({k: pos.get(k) for k in FROZEN}, sort_keys=True,
                      separators=(",", ":"))


def basis_stop(pos: dict) -> float | None:
    """The ORIGINAL stop this position's `risk` was measured against.

    Reconstructed from `entry` and `risk` rather than read from `stop`, because
    `stop` trails: a position that has taken tp1 has had its stop moved to
    breakeven, and sizing off a zero stop distance is meaningless. Returns None
    when the row cannot be sized at all (no entry, no risk, or a risk so large
    it would put a long's stop at or below zero).
    """
    try:
        entry = float(pos.get("entry") or 0.0)
        risk = float(pos.get("risk") or 0.0)
    except (TypeError, ValueError):
        return None
    if entry <= 0 or risk <= 0:
        return None
    short = str(pos.get("direction") or "long").lower() == "short"
    stop = entry + risk if short else entry - risk
    if not short and stop <= 0:
        return None
    return stop


def stop_pct(pos: dict) -> float:
    """|entry - original stop| as a % of entry. 0.0 when unsizeable."""
    stop = basis_stop(pos)
    if stop is None:
        return 0.0
    entry = float(pos["entry"])
    return abs(entry - stop) / entry * 100.0


def resize_position(pos: dict, target: float, equity: float, stamp: str,
                    max_stop_pct: float = 0.0) -> dict:
    """Restate one open position at `target` notional. Mutates and returns `pos`.

    `max_stop_pct` (0 = off, the default) caps the DOLLAR RISK a restated row
    may carry at what a position with that stop width would risk at the full
    target -- i.e. notional falls to `target * max_stop_pct / stop_pct` for a
    row whose stop is wider than that. See the CLI help for why the option
    exists and why it is off by default.

    Returns a change record: {"symbol", "action", "reason", "before", "after"}.
    `action` is "resized" or "skipped"; a skip never mutates.
    """
    sym = str(pos.get("symbol") or "?")
    rec = {"symbol": sym, "market": str(pos.get("market") or ""),
           "action": "skipped", "reason": "", "capped": 0.0,
           "stop_pct": round(stop_pct(pos), 4),
           "notional_before": pos.get("notional"), "notional_after": pos.get("notional"),
           "risk_usd_before": pos.get("risk_usd"), "risk_usd_after": pos.get("risk_usd"),
           "units_before": pos.get("units"), "units_after": pos.get("units")}

    if str(pos.get("status") or "open") != "open":
        rec["reason"] = "not open"
        return rec

    stop = basis_stop(pos)
    if stop is None:
        rec["reason"] = "no usable entry/risk basis"
        return rec

    want = target
    spct = stop_pct(pos)
    if max_stop_pct > 0 and spct > max_stop_pct:
        want = round(target * max_stop_pct / spct, 2)
        rec["capped"] = round(spct, 2)

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

    sizing = vivek_bot.size_position(equity, float(pos["entry"]), stop,
                                     notional_target=want)
    if sizing["units"] <= 0 or sizing["notional"] <= 0:
        rec["reason"] = "sizer returned nothing"
        return rec

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
    # Re-stamp the dollar mark off the UNCHANGED R. vivek_run marks it as
    # `unreal_r * risk_usd` (line ~769); recomputing it the same way here keeps
    # the row self-consistent until the next scan re-marks it anyway.
    try:
        ur = float(pos.get("unreal_r") or 0.0)
    except (TypeError, ValueError):
        ur = 0.0
    pos["unreal_usd"] = round(ur * sizing["risk_usd"], 2)

    rec.update(action="resized", reason="",
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
    """Refresh the market book's summary block. SAME SHAPE the engine writes.

    `unreal_usd` genuinely changes under a resize, so leaving it stale would
    have the header disagree with the rows it is summing. Nothing else in the
    block moves, and no new key is introduced -- the next scan overwrites this
    with its own three fields and a schema surprise here would survive as a
    permanent orphan.
    """
    rows = book.get("open") or []
    return {
        "open": len(rows),
        "unreal_usd": round(sum(float(p.get("unreal_usd") or 0.0) for p in rows), 2),
        "updated_day": day,
    }


def report(results: dict, target: float, equity: float) -> list[str]:
    """Human-readable before/after. Printed in both dry and applied runs."""
    lines: list[str] = []
    tot_before = tot_after = 0.0
    risk_before = risk_after = 0.0
    n_resized = n_skipped = 0
    wide: list[tuple[float, str, float]] = []
    gate = float(getattr(config, "VIVEK_BOT_MAX_STOP_PCT", 0) or 0)
    for market in sorted(results):
        changes = results[market]["changes"]
        if not changes:
            continue
        lines.append(f"  {market.upper()}")
        for c in changes:
            nb = float(c["notional_before"] or 0.0)
            na = float(c["notional_after"] or 0.0)
            tot_before += nb
            tot_after += na
            risk_before += float(c["risk_usd_before"] or 0.0)
            risk_after += float(c["risk_usd_after"] or 0.0)
            if c["action"] == "resized":
                n_resized += 1
                flag = f"  CAPPED (stop {c['capped']:.0f}%)" if c.get("capped") else ""
                lines.append(
                    f"    {c['symbol']:<6} ${nb:>9,.2f} -> ${na:>9,.2f}   "
                    f"risk ${float(c['risk_usd_before'] or 0):>8,.2f} -> "
                    f"${float(c['risk_usd_after'] or 0):>8,.2f}   "
                    f"x{(na / nb if nb else 0):.2f}{flag}")
            else:
                n_skipped += 1
                lines.append(f"    {c['symbol']:<6} ${nb:>9,.2f}   SKIPPED "
                             f"({c['reason']})")
            if gate > 0 and c["stop_pct"] > gate:
                wide.append((c["stop_pct"], c["symbol"], float(c["risk_usd_after"] or 0)))

    cap = float(getattr(config, "VIVEK_BOT_MAX_PORTFOLIO_NOTIONAL", 0) or 0)
    daily = equity * float(getattr(config, "VIVEK_BOT_MAX_DAILY_LOSS_PCT", 0) or 0) / 100.0
    lines.append("")
    lines.append(f"  target ${target:,.0f}/position on ${equity:,.0f} equity")
    lines.append(f"  {n_resized} resized, {n_skipped} skipped")
    lines.append(f"  open notional ${tot_before:,.2f} -> ${tot_after:,.2f}"
                 + (f"  ({tot_after / cap * 100:.1f}% of the ${cap:,.0f} cap)"
                    if cap else ""))
    lines.append(f"  open RISK     ${risk_before:,.2f} -> ${risk_after:,.2f}"
                 + (f"  ({risk_after / equity * 100:.1f}% of equity if every "
                    f"stop hit at once)" if equity else ""))

    # The consequence the raw notional figure hides. A legacy row was ~$256, so
    # even a 50%-wide stop only ever risked $35; at the full target the same
    # stop risks $2,489, and the daily guard is a fixed dollar limit that does
    # not scale with it.
    if wide:
        wide.sort(reverse=True)
        lines.append("")
        lines.append(f"  WIDE STOPS: {len(wide)} position(s) sit beyond the "
                     f"{gate:.0f}% max_stop_pct gate that every NEW entry must "
                     f"pass.")
        lines.append(f"  They were opened before the gate applied to them. At "
                     f"this size each now risks:")
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
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
                    help="actually write. Without it nothing is written.")
    args = ap.parse_args(argv)

    if args.target <= 0:
        print("ERROR: --target must be > 0 (fixed-notional sizing is off?)")
        return 2
    if args.equity <= 0:
        print("ERROR: --equity must be > 0")
        return 2

    markets = args.market or list(config.MARKETS)
    stamp = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()

    print(f"RESIZE  open book -> ${args.target:,.0f}/position", flush=True)
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

    if not args.apply:
        print("")
        print("  dry run: nothing written. Re-run with --apply to commit.",
              flush=True)
        return 0

    for market, res in results.items():
        book = res["book"]
        if any(c["action"] == "resized" for c in res["changes"]):
            book["summary"] = summarise(book, stamp[:10])
            book["updated_at"] = stamp
        atomic_write(vivek_run._market_book_file(market),
                     json.dumps(book, indent=2))
        print(f"  wrote journal/vivek_bot_book.{market}.json", flush=True)

    # The combined file and its public twin are DERIVED. Regenerating them from
    # the canonical files is what keeps verify_books() happy on the next scan.
    vivek_run._write_combined()
    print("  rebuilt the derived combined book + public twin", flush=True)

    problems = vivek_run.verify_books()
    for p in problems:
        print(f"  VERIFY: {p}", flush=True)
    print(f"  verify_books: {len(problems)} problem(s)", flush=True)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
