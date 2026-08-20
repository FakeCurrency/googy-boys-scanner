#!/usr/bin/env python3
"""Confluence edge report (2026-08-20, edge-research batch Task 1).

Answers, on demand and with growing precision as data/alert_forward_returns.json
matures: DO MULTI-LENS ALIGNED ALERTS PREDICT FORWARD RETURNS — and how do they
compare against plain single-lens A+ setups?

Two modes:
  python scripts/alert_edge_report.py                # ledger-only cohort stats
  python scripts/alert_edge_report.py --baseline     # + the A+ comparison, built
                                                     # from git history's committed
                                                     # <m>_prices.json snapshots

READ-ONLY RESEARCH. Writes nothing, changes nothing about how alerts are
generated, graded or displayed. Not imported by the engine.

METHOD NOTES (the parts that keep the numbers honest):
  * Returns are SIGNED by the alert's side: long -> +r, short -> -r, so "edge"
    always means "return in the called direction". Raw moves are in the ledger.
  * The ledger's returns are Yahoo closes (alert_returns.py). The --baseline
    comparison instead prices BOTH cohorts from the same committed scan
    snapshots (last <m>_prices.json commit of each session day), because a
    cohort comparison across two different price sources measures the sources.
  * DEDUP: the same name re-aligns day after day while the setup lasts.
    Counting every re-fire pseudo-replicates one bet; the dedup view keeps
    only the FIRST occurrence per (market, ticker, side). Both views print.
  * Right-censoring: a base day within H sessions of the newest snapshot has
    no forward price yet and is skipped (counted, not hidden).
  * SE printed beside every mean; buckets under MIN_N are labelled too-thin
    rather than reported as findings.
"""
import argparse
import collections
import csv
import json
import math
import os
import statistics as st
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "data", "alert_forward_returns.json")
MIN_N = 10
HORIZONS = ("5", "10", "20")
MARKETS = ("asx", "nasdaq", "crypto")


def signed(ret, side):
    """Edge return: positive means the move went the alert's way."""
    if ret is None:
        return None
    return ret if side == "long" else -ret


def cohort_stats(values):
    """(n, mean, se, median, win_rate) for a list of signed returns."""
    vals = [v for v in values if v is not None]
    n = len(vals)
    if n == 0:
        return {"n": 0}
    mean = st.mean(vals)
    se = (st.pstdev(vals) / math.sqrt(n)) if n > 1 else float("nan")
    return {"n": n, "mean": mean, "se": se, "median": st.median(vals),
            "win": sum(1 for v in vals if v > 0) / n}


def fmt(s, label):
    if s["n"] == 0:
        return f"{label}: n=0"
    line = (f"{label}: n={s['n']:4d}  mean={s['mean']*100:+.2f}%"
            f" (SE {s['se']*100:.2f}pp)  median={s['median']*100:+.2f}%"
            f"  win={s['win']*100:.0f}%")
    if s["n"] < MIN_N:
        line += "   [TOO THIN - not a finding]"
    return line


def dedup_first(rows, key=lambda x: (x["market"], x["ticker"], x["side"])):
    """First occurrence per identity, in base-day order."""
    seen, out = set(), []
    for x in sorted(rows, key=lambda x: x.get("base_day") or x.get("day") or ""):
        k = key(x)
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def load_sectors():
    sec = {}
    try:
        with open(os.path.join(ROOT, "data_universe", "asx_tickers.csv"), encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                sec[("asx", r["symbol"])] = (r.get("sector") or "").strip()
    except OSError:
        pass
    try:
        sm = json.load(open(os.path.join(ROOT, "data", "sector_map.json"), encoding="utf-8"))
        for k, v in sm.items():
            mkt, sym = k.split(":", 1)
            sec.setdefault((mkt, sym), (v.get("sector") or "").strip())
    except (OSError, ValueError):
        pass
    return sec


# ── ledger mode ──────────────────────────────────────────────────────────────

def ledger_report(entries):
    print("=" * 72)
    print("LEDGER COHORT (Yahoo closes, alert_forward_returns.json)")
    print("=" * 72)
    sectors = load_sectors()
    for h in HORIZONS:
        rows = [e for e in entries if e["fwd"].get(h) is not None]
        print(f"\n-- {h}-session horizon: {len(rows)} matured of {len(entries)} --")
        if not rows:
            continue
        sg = lambda es: [signed(e["fwd"][h], e["side"]) for e in es]  # noqa: E731
        print(fmt(cohort_stats(sg(rows)), "  all (every re-fire)     "))
        first = dedup_first(rows)
        print(fmt(cohort_stats(sg(first)), "  dedup (first per name)  "))
        for s in ("long", "short"):
            print(fmt(cohort_stats(sg([e for e in first if e["side"] == s])), f"    dedup {s:5}           "))
        for m in MARKETS:
            print(fmt(cohort_stats(sg([e for e in first if e["market"] == m])), f"    dedup {m:7}         "))
        combos = collections.Counter("+".join(sorted(e.get("lenses") or [])) for e in first)
        for combo, _ in combos.most_common():
            sub = [e for e in first if "+".join(sorted(e.get("lenses") or [])) == combo]
            print(fmt(cohort_stats(sg(sub)), f"    dedup {combo[:20]:20}"))
        by_sec = collections.defaultdict(list)
        for e in first:
            by_sec[sectors.get((e["market"], e["ticker"]), "") or "(no sector)"].append(
                signed(e["fwd"][h], e["side"]))
        named = [(k, v) for k, v in by_sec.items() if len(v) >= MIN_N]
        if named:
            print("    by sector (dedup, buckets >= %d only):" % MIN_N)
            for k, v in sorted(named, key=lambda kv: -len(kv[1])):
                print(fmt(cohort_stats(v), f"      {k[:22]:22}"))


# ── baseline mode (git snapshots) ────────────────────────────────────────────

def snapshot_days(market):
    path = f"public/data/{market}_prices.json"
    out = subprocess.run(["git", "log", "--format=%H %ad", "--date=format:%Y-%m-%d",
                          "--", path], capture_output=True, text=True, cwd=ROOT).stdout
    last = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, day = line.split()
        last.setdefault(day, sha)          # newest-first: first hit = last commit of the day
    return dict(sorted(last.items()))


def load_snapshot(market, sha):
    path = f"public/data/{market}_prices.json"
    try:
        raw = subprocess.run(["git", "show", f"{sha}:{path}"], capture_output=True,
                             text=True, cwd=ROOT, check=True).stdout
        d = json.loads(raw)
        return {"prices": d.get("prices") or {}, "rows": d.get("rows") or {}}
    except (subprocess.CalledProcessError, ValueError):
        return None


def forward_return(days, snaps, day, sym, h):
    """h-session forward return off the committed snapshot price series."""
    if day not in days:
        return None
    i = days.index(day)
    if i + h >= len(days):
        return None                        # right-censored, not yet answerable
    p0 = snaps[day]["prices"].get(sym)
    p1 = snaps[days[i + h]]["prices"].get(sym)
    if not p0 or not p1 or p0 <= 0:
        return None
    return p1 / p0 - 1.0


def baseline_report(entries, h=5):
    print("\n" + "=" * 72)
    print(f"BASELINE COMPARISON ({h}-session, BOTH cohorts on scan-snapshot prices)")
    print("aligned = in the confluence ledger that day; A+ = grade_raw A+ rows")
    print("NOT aligned that day. Identical price plumbing on both sides.")
    print("=" * 72)
    aligned_by = collections.defaultdict(set)
    side_of = {}
    for e in entries:
        aligned_by[(e["market"], e["base_day"])].add(e["ticker"])
        side_of[(e["market"], e["base_day"], e["ticker"])] = e["side"]

    al_rows, ap_rows = [], []
    censored = 0
    for m in MARKETS:
        day_shas = snapshot_days(m)
        days = list(day_shas)
        snaps = {}
        for day, sha in day_shas.items():
            s = load_snapshot(m, sha)
            if s:
                snaps[day] = s
        days = [d for d in days if d in snaps]
        for day in days:
            al = aligned_by.get((m, day), set())
            for sym in al:
                r = forward_return(days, snaps, day, sym, h)
                if r is None:
                    censored += 1
                    continue
                side = side_of[(m, day, sym)]
                al_rows.append({"market": m, "ticker": sym, "side": side,
                                "base_day": day, "signed": signed(r, side)})
            for sym, row in snaps[day]["rows"].items():
                if row.get("grade_raw") != "A+" or sym in al:
                    continue
                r = forward_return(days, snaps, day, sym, h)
                if r is None:
                    continue
                side = "long" if row.get("dir") == "LONG" else "short"
                ap_rows.append({"market": m, "ticker": sym, "side": side,
                                "base_day": day, "signed": signed(r, side)})

    for name, rows in (("aligned", al_rows), ("A+ only", ap_rows)):
        first = dedup_first(rows)
        print(fmt(cohort_stats([x["signed"] for x in rows]), f"  {name:8} all           "))
        print(fmt(cohort_stats([x["signed"] for x in first]), f"  {name:8} dedup         "))
        for s in ("long", "short"):
            print(fmt(cohort_stats([x["signed"] for x in first if x["side"] == s]),
                      f"    {name:8} dedup {s:5} "))
    print(f"  (right-censored aligned observations skipped: {censored})")


def main(argv=None):
    p = argparse.ArgumentParser(description="Confluence alert edge report")
    p.add_argument("--baseline", action="store_true",
                   help="also build the single-lens A+ comparison from git snapshots")
    args = p.parse_args(argv)
    try:
        entries = json.load(open(LEDGER, encoding="utf-8"))["entries"]
    except (OSError, ValueError, KeyError) as e:
        print(f"ledger unreadable: {e.__class__.__name__}: {e}")
        return 2
    ledger_report(entries)
    if args.baseline:
        baseline_report(entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
