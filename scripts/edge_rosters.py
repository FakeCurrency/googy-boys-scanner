#!/usr/bin/env python3
"""Daily A+ roster ledger — the single-lens BASELINE cohort (batch-100 WS-B).

The confluence ledger answers "how do ALIGNED alerts do"; this file answers
the half every comparison needs: how do plain grade_raw A+ setups do, on the
SAME Yahoo-close plumbing and the same 1/5/10/20-session horizons. The
2026-08-20 edge batch had to reconstruct this baseline from git history of
scan snapshots; from today it simply accrues.

Each daily run copies TODAY's committed scans' A+ rows (grade_raw, both
directions) into data/edge_rosters.json with the context the edge questions
need frozen at entry: score, STRONG STRUCTURE chip, the High-conviction
condition (the same weekly-reclaim test app.js's isHighConviction applies),
sector, is_product, and the market's breadth on that day. Forward returns are
stamped by the exact machinery the alert ledger uses (imported from
alert_returns.py, never re-typed): frozen at first measurement, right-censored
until mature, trim never drops an unmatured row.

RESEARCH ONLY: reads committed artefacts, writes ONLY its own ledger; nothing
in scanner/ or broker/ reads it back (test-pinned). Prints
EDGE_ROSTERS_UNCHANGED when a run changed nothing so the workflow can skip
its commit. ASCII-only prints; atomic write via scanner.output.write_json.
"""
import datetime as dt
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scanner import config, output                                  # noqa: E402

# The stamping machinery is IMPORTED from the alert ledger (mirror-drift rule:
# two forward-return implementations would diverge exactly when it matters).
_spec = importlib.util.spec_from_file_location(
    "alert_returns", os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_returns.py"))
ar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ar)

LEDGER = os.path.join(ROOT, "data", "edge_rosters.json")
CAP = int(getattr(config, "ALERT_ROSTER_CAP", 20000))
HORIZONS = ar.HORIZONS


def _fresh() -> dict:
    return {"schema_version": 1, "updated_at": "", "entries": []}


def load_ledger(path: str = LEDGER) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except FileNotFoundError:
        return _fresh()
    except (OSError, ValueError):
        print("WARNING roster ledger unreadable - starting fresh")
        return _fresh()
    if not isinstance(d, dict) or not isinstance(d.get("entries"), list):
        print("WARNING roster ledger malformed - starting fresh")
        return _fresh()
    return d


def high_conviction(row: dict) -> bool:
    """The SAME condition app.js's isHighConviction applies (weekly reclaim
    that is A/A+ or has >=2 structural TPs) — mirrored here so the tag's
    forward returns are measured against the tag as displayed."""
    p = (row.get("plans") or {}).get("1W") or {}
    if not (p.get("armed") and p.get("entry_trigger") == "reclaim"):
        return False
    return (row.get("grade") in ("A+", "A")) or ((p.get("structural_tps") or 0) >= 2)


def roster_rows(scan: dict, market: str) -> list[dict]:
    """Today's A+ cohort from one committed scan payload."""
    day = ar._market_day(scan.get("generated_at", ""), market)
    out = []
    for r in scan.get("results") or []:
        if r.get("grade_raw") != "A+" or not r.get("symbol"):
            continue
        side = "short" if str(r.get("dir", "LONG")).upper() == "SHORT" else "long"
        out.append({
            "key": f"{day}|{market}|{r['symbol']}|{side}",
            "market": market,
            "ticker": r["symbol"],
            "side": side,
            "base_day": day,
            "grade_raw": r.get("grade_raw"),
            "score": r.get("score"),
            "strong": "STRONG STRUCTURE" in (r.get("chips") or []),
            "hiconv": high_conviction(r),
            "sector": (r.get("sector") or "").strip() or None,
            "is_product": r.get("is_product"),
            "base_close": None,
            "fwd": {str(h): None for h in HORIZONS},
        })
    return out


def ingest_today(ledger: dict) -> int:
    """Copy each committed scan's A+ rows in, once per (day, name, side)."""
    have = {e.get("key") for e in ledger["entries"]}
    breadth = ar._breadth_series()
    added = 0
    for m in ("asx", "nasdaq", "crypto"):
        try:
            with open(os.path.join(ROOT, "public", "data", f"{m}_vivek.json"), encoding="utf-8") as fh:
                scan = json.load(fh)
        except (OSError, ValueError):
            print(f"WARNING {m} scan unreadable - roster skipped for this market")
            continue
        for row in roster_rows(scan, m):
            if row["key"] in have:
                continue
            have.add(row["key"])
            b = breadth.get(m, {}).get(row["base_day"])
            if b is not None:
                row["breadth200"] = round(float(b), 4)
            ledger["entries"].append(row)
            added += 1
    return added


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    dry = "--dry-run" in argv

    ledger = load_ledger()
    added = ingest_today(ledger)

    today = dt.datetime.now(dt.timezone.utc).date()
    want = ar.wanting_prices(ledger, today)
    stamped = 0
    if want:
        from scanner.data import download
        frames = download(sorted(want), period="3mo")
        stamped = ar.stamp(ledger, frames, want)
    dropped = ar.trim(ledger, cap=CAP)

    entries = ledger["entries"]
    per_h = " · ".join(f"{h}s {sum(1 for e in entries if e['fwd'].get(str(h)) is not None)}/{len(entries)}"
                       for h in HORIZONS)
    print(f"edge rosters: +{added} ingested, +{stamped} stamps, -{dropped} trimmed; "
          f"{len(entries)} tracked")
    print(f"roster maturity: {per_h}")

    if not (added or stamped or dropped):
        print("EDGE_ROSTERS_UNCHANGED")
        return 0
    if dry:
        print("dry run - not writing")
        return 0
    ledger["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    output.write_json(LEDGER, ledger, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
