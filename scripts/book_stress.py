#!/usr/bin/env python3
"""Book tide-stress report (batch-100 WS-D) -> public/data/book_stress.json.

The 2026-08-20 edge research measured that a plain reversion of breadth to
its 6-month mean (~a -3.5% uniform mark move) erases ~58% of the open book's
unrealized R without firing a single stop. That number was computed once, in
a chat; this publishes it daily so the journal can SHOW how much of the
paper profit is tide.

Method, deliberately simple and stated on the payload: apply a uniform
percentage drawdown d to every LONG position's last_mark; a position stops
out when mark*(1-d) <= stop (its R lands at the stop's R), otherwise it
re-marks at the shocked price. Shorts (none held today; allow_shorts is off)
are left untouched and counted out loud. A RUNNER (a position that has banked a
partial, `booked_pct` > 0) is shocked on its un-booked REMAINDER only - the same
basis as the engine's published `unreal_r` (vivek_guard._unreal_r), so the
base and every shocked figure measure the same exposure and a 0% shock gives
back exactly nothing (audit #31, 2026-10-08: the shocked side used to value the
full original size, so a runner read as GAINING under a drawdown). Banked R is
out of both sides, as it always was. No betas, no correlations - a
uniform beta-1 shock is the honest floor of sophistication, and what it
loses in nuance it keeps in explainability.

READ-ONLY with respect to trading: reads the committed book, writes ONE
report artefact. Nothing in scanner/ or broker/ reads it back (test-pinned).
Unpriced/malformed rows are SKIPPED AND COUNTED, never valued at zero.
ASCII-only prints; atomic write via scanner.output.write_json.
"""
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scanner import config, output                                  # noqa: E402

BOOK = os.path.join(ROOT, "journal", "vivek_bot_book.json")
OUT = os.path.join(ROOT, "public", "data", "book_stress.json")
SHOCKS = tuple(getattr(config, "BOOK_STRESS_SHOCKS", (0.03, 0.05, 0.08, 0.10)))


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and x == x and abs(x) != float("inf")


def stress(open_rows: list[dict], shocks=SHOCKS) -> dict:
    """The stress table for one open book. Pure; hand-testable."""
    rows = []
    skipped = 0
    shorts = 0
    for t in open_rows or []:
        mark, stop, entry, risk = (t.get("last_mark"), t.get("stop"),
                                   t.get("entry"), t.get("risk"))
        ur = t.get("unreal_r")
        booked = t.get("booked_pct")
        booked = 0.0 if booked is None else booked
        if str(t.get("direction", "long")).lower() != "long":
            shorts += 1
            continue
        if (not all(_finite(x) for x in (mark, stop, entry, risk, booked)) or risk <= 0
                or not _finite(ur)):
            skipped += 1
            continue
        # The un-booked remainder, clamped exactly as vivek_guard._remaining
        # does - the basis the published `unreal_r` (the base below) is on.
        rem = min(1.0, max(0.0, 1.0 - float(booked)))
        if rem <= 0.0:
            continue        # fully booked: nothing left exposed to a shock
        rows.append({"mark": float(mark), "stop": float(stop), "entry": float(entry),
                     "risk": float(risk), "ur": float(ur), "rem": rem})
    base_ur = round(sum(r["ur"] for r in rows), 3)
    table = []
    for d in shocks:
        stopped = 0
        new_total = 0.0
        for r in rows:
            shocked = r["mark"] * (1 - d)
            if shocked <= r["stop"]:
                stopped += 1
                new_total += r["rem"] * (r["stop"] - r["entry"]) / r["risk"]
            else:
                new_total += r["rem"] * (shocked - r["entry"]) / r["risk"]
        table.append({
            "shock_pct": round(d * 100, 1),
            "stopped": stopped,
            # `+ 0.0` turns a rounded -0.0 into 0.0 (a 0% shock is exact now).
            "unreal_r": round(new_total, 2) + 0.0,
            "given_back_r": round(base_ur - new_total, 2) + 0.0,
        })
    return {
        "n_long": len(rows),
        "n_short_untouched": shorts,
        "n_skipped_unpriced": skipped,
        "base_unreal_r": round(base_ur, 2),
        "shocks": table,
        "method": ("uniform beta-1 shock on every long's last_mark vs its real "
                   "stop; a stopped position realises its stop's R; a runner is "
                   "valued on its un-booked remainder, like unreal_r; no "
                   "correlations, no betas - the honest floor of sophistication"),
    }


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    dry = "--dry-run" in argv
    try:
        with open(BOOK, encoding="utf-8") as fh:
            book = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"ERROR book unreadable: {e.__class__.__name__}: {e}")
        return 2
    payload = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "book_updated_at": book.get("updated_at") or (book.get("summary") or {}).get("updated_at"),
        **stress(book.get("open") or []),
    }
    line = " · ".join(f"-{s['shock_pct']:.0f}%: {s['unreal_r']:+.1f}R ({s['stopped']} stopped)"
                      for s in payload["shocks"])
    print(f"book stress: base {payload['base_unreal_r']:+.2f}R over {payload['n_long']} longs | {line}")
    if payload["n_skipped_unpriced"]:
        print(f"WARNING {payload['n_skipped_unpriced']} unpriced/malformed rows skipped "
              f"(never valued at zero)")
    # No-op honesty (the reco_note pattern): a timestamp is not a change. If
    # the stress CONTENT matches what is already published, say so and let the
    # workflow skip the commit instead of re-dating the file daily.
    try:
        with open(OUT, encoding="utf-8") as fh:
            prev = json.load(fh)
        strip = lambda d: {k: v for k, v in d.items() if k != "generated_at"}  # noqa: E731
        if strip(prev) == strip(payload):
            print("BOOK_STRESS_UNCHANGED")
            return 0
    except (OSError, ValueError):
        pass
    if dry:
        print("dry run - not writing")
        return 0
    output.write_json(OUT, payload, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
