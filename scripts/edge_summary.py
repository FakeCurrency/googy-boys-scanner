#!/usr/bin/env python3
"""Headline edge numbers as a small committed artefact (batch-100 WS-J) ->
public/data/edge_summary.json.

alert_edge_report.py is pinned READ-ONLY (a report that can write invites a
report that overwrites), so the machine-readable summary lives here: import
the report's own stat functions - never re-type the math - and publish the
dedup headline per horizon for the aligned cohort and the roster baseline,
split by side. A future surface can render it; today it makes the edge
numbers diffable day over day in git.

REFINE200 (2026-10-14), schema 2 - every key schema 1 had is still there:
  * `by_market` (#29, #38): the aligned and baseline blocks per market beside
    the pooled ones, each stat with its n (crypto's ~50 rows read as thin);
  * `excess` + `bench_n` per horizon (#28): signed (move - market benchmark)
    over the rows that carry a benchmark (stamped since 2026-10-14), and how
    many do;
  * `exclusions`: rows clean() kept out of every statistic (weekend
    duplicates of one base bar, legacy wrong-token crypto rows), counted;
  * `sectors` (#40): the 5-session dedup cohorts by GICS sector, labels
    folded for analysis only (config.EDGE_SECTOR_ALIASES).

Prints EDGE_SUMMARY_UNCHANGED when the content (minus generated_at) matches
the committed file. ASCII prints; atomic write via scanner.output.write_json.
"""
import datetime as dt
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scanner import output                                          # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "alert_edge_report", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "alert_edge_report.py"))
aer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aer)

OUT = os.path.join(ROOT, "public", "data", "edge_summary.json")


def _clean(stats: dict) -> dict:
    """cohort_stats() output with NaN SE nulled - the payload must stay
    strictly finite (a bare NaN token kills response.json())."""
    out = {}
    for k, v in stats.items():
        out[k] = None if isinstance(v, float) and v != v else v
    return out


def cohort_block(entries, horizons) -> dict:
    block = {}
    for h in horizons:
        rows = [e for e in entries if (e.get("fwd") or {}).get(h) is not None]
        first = aer.dedup_first(rows)
        sg = [aer.signed(e["fwd"][h], e["side"]) for e in first]
        ex = {s: [aer.excess(e, h) for e in first if s in ("dedup", e["side"])]
              for s in ("dedup", "long", "short")}
        block[h] = {
            "dedup": _clean(aer.cohort_stats(sg)),
            "long": _clean(aer.cohort_stats(
                [aer.signed(e["fwd"][h], e["side"]) for e in first if e["side"] == "long"])),
            "short": _clean(aer.cohort_stats(
                [aer.signed(e["fwd"][h], e["side"]) for e in first if e["side"] == "short"])),
            "bench_n": sum(1 for v in ex["dedup"] if v is not None),
            "excess": {s: _clean(aer.cohort_stats(v)) for s, v in ex.items()},
        }
    return block


def sector_block(entries, h="5") -> dict:
    """{GICS sector: dedup stats} at one horizon (labels folded, analysis only)."""
    sectors = aer.load_sectors()
    first = aer.dedup_first([e for e in entries if (e.get("fwd") or {}).get(h) is not None])
    by: dict = {}
    for e in first:
        by.setdefault(aer.sector_of(e, sectors), []).append(aer.signed(e["fwd"][h], e["side"]))
    return {k: _clean(aer.cohort_stats(v)) for k, v in sorted(by.items())}


def build() -> dict:
    with open(aer.LEDGER, encoding="utf-8") as fh:
        aligned = json.load(fh)["entries"]
    rosters = aer.load_rosters()
    prices = aer.crypto_prices()
    aligned, ex_aligned = aer.clean(aligned, prices)
    rosters, ex_rosters = aer.clean(rosters, prices)
    aligned_days = {(e["market"], e["base_day"], e["ticker"]) for e in aligned}
    baseline = [e for e in rosters
                if (e["market"], e["base_day"], e["ticker"]) not in aligned_days]
    return {
        "schema_version": 2,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "note": ("Signed 5/10/20-session forward returns, deduped to first "
                 "alignment per name+side. aligned = multi-lens ledger; "
                 "baseline = plain grade_raw A+ rosters minus that day's "
                 "aligned names. Same plumbing both sides. excess = signed "
                 "(move - market benchmark) over the bench_n rows that carry "
                 "one (stamped since 2026-10-14). exclusions = rows kept out "
                 "of every statistic, counted."),
        "exclusions": {"aligned": ex_aligned, "baseline_aplus": ex_rosters},
        "aligned": cohort_block(aligned, aer.HORIZONS),
        "baseline_aplus": cohort_block(baseline, aer.HORIZONS),
        "by_market": {m: {"aligned": cohort_block([e for e in aligned if e["market"] == m], aer.HORIZONS),
                          "baseline_aplus": cohort_block([e for e in baseline if e["market"] == m],
                                                         aer.HORIZONS)}
                      for m in aer.MARKETS},
        "sectors": {"horizon": "5", "aligned": sector_block(aligned),
                    "baseline_aplus": sector_block(baseline)},
    }


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    payload = build()
    n5 = ((payload["aligned"].get("5") or {}).get("dedup") or {}).get("n", 0)
    b5 = ((payload["baseline_aplus"].get("5") or {}).get("dedup") or {}).get("n", 0)
    print(f"edge summary: aligned 5s dedup n={n5}, baseline n={b5}; excluded {payload['exclusions']}")
    try:
        with open(OUT, encoding="utf-8") as fh:
            prev = json.load(fh)
        strip = lambda d: {k: v for k, v in d.items() if k != "generated_at"}  # noqa: E731
        if strip(prev) == strip(payload):
            print("EDGE_SUMMARY_UNCHANGED")
            return 0
    except (OSError, ValueError):
        pass
    if "--dry-run" in argv:
        print("dry run - not writing")
        return 0
    output.write_json(OUT, payload, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
