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
  * EXCLUSIONS ARE COUNTED, never silent (REFINE200 #140, 2026-10-14):
    clean() leaves out of every statistic (a) a Saturday/Sunday-dated stock
    row that duplicates another row of the same name and side on the same
    session's base bar (the weekend heal-scan and nightly-alert copies), and
    (b) a legacy crypto row priced from Yahoo's same-ticker STRANGER (no
    price_source; base_close more than EDGE_CRYPTO_WRONG_TOKEN_FACTOR away
    from the coin's current scan price - JUP at $0.0003). The rows stay in
    the ledgers; only the summary statistics skip them, and say how many.
  * EXCESS (REFINE200 #28): rows stamped since 2026-10-14 carry `bench`, the
    market benchmark over the same bars; excess = signed(fwd - bench). It is
    printed with its own n, which starts small and only grows.
  * Sectors are folded to the 11 GICS sectors for analysis only
    (config.EDGE_SECTOR_ALIASES, REFINE200 #40); the bot's labels are untouched.
"""
import argparse
import collections
import csv
import datetime as dt
import glob
import json
import math
import os
import statistics as st
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scanner import config                                          # noqa: E402

LEDGER = os.path.join(ROOT, "data", "alert_forward_returns.json")
CRYPTO_PRICES = os.path.join(ROOT, "public", "data", "crypto_prices.json")
MIN_N = 10
HORIZONS = ("5", "10", "20")
MARKETS = ("asx", "nasdaq", "crypto")
SECTOR_ALIASES = dict(config.EDGE_SECTOR_ALIASES)
WRONG_TOKEN_FACTOR = float(config.EDGE_CRYPTO_WRONG_TOKEN_FACTOR)
# The High-conviction rule a legacy roster row (no `hc_rule` stamp) was
# judged under, by base_day. The rule changed 2026-09-20; the run that filed
# a day landed hours after it, so the two weekend days either side of the
# change cannot be attributed and read as "unknown" (their hiconv rate already
# matches the new rule's). Rows filed since 2026-10-14 carry the stamp.
HC_RULE_RETIRED = "retired 2026-09-20: 1W reclaim, A/A+ or >=2 structural TPs"
HC_RULE_FOUR_CELL = "cells=1W:reclaim/break;3D:reclaim;1D:break grades=A+/A"
HC_RULE_UNKNOWN = "unknown (filed across the 2026-09-20 change)"


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


def _session_market(market):
    return config.VIVEK_JOURNAL_SESSION.get(market) is not None


def _rolled(day, market):
    """A stock market's Sat/Sun day rolled forward to Monday - the session
    whose bar was that row's base all along."""
    if not _session_market(market):
        return day
    try:
        d = dt.date.fromisoformat(str(day)[:10])
    except ValueError:
        return day
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d.isoformat()


def crypto_prices():
    """{coin: current price} from the crypto scan's slim prices (read only)."""
    try:
        with open(CRYPTO_PRICES, encoding="utf-8") as fh:
            p = json.load(fh).get("prices") or {}
        return p if isinstance(p, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def wrong_token(e, prices):
    """A legacy crypto row (no price_source: stamped from Yahoo <SYM>-USD)
    whose base is a different instrument from the coin the scan prices."""
    if e.get("market") != "crypto" or e.get("price_source"):
        return False
    base, now = e.get("base_close"), prices.get(e.get("ticker"))
    if not (isinstance(base, (int, float)) and base > 0 and isinstance(now, (int, float)) and now > 0):
        return False
    r = base / now
    return r > WRONG_TOKEN_FACTOR or r < 1.0 / WRONG_TOKEN_FACTOR


def clean(rows, prices=None):
    """(kept rows, {reason: count}) - the rows every statistic reads.

    weekend_duplicates: a Saturday/Sunday-dated row on a stock market whose
    (market, ticker, side) also has a row on the same session (its Sat/Sun
    rolled to Monday) - a weekday row wins; among weekend-only copies the
    earliest day's rows stay. They shared one base bar, so nothing measured
    is lost. crypto_wrong_token: see wrong_token()."""
    prices = crypto_prices() if prices is None else prices
    groups = collections.defaultdict(list)
    for e in rows:
        groups[(e.get("market"), e.get("ticker"), e.get("side"),
                _rolled(e.get("base_day"), e.get("market")))].append(e)
    drop = set()
    for (_m, _t, _s, session), g in groups.items():
        days = {e.get("base_day") for e in g}
        if len(days) < 2:
            continue
        keep_day = session if session in days else min(days)
        drop.update(id(e) for e in g if e.get("base_day") != keep_day)
    counts = {"weekend_duplicates": len(drop), "crypto_wrong_token": 0}
    kept = []
    for e in rows:
        if id(e) in drop:
            continue
        if wrong_token(e, prices):
            counts["crypto_wrong_token"] += 1
            continue
        kept.append(e)
    return kept, counts


def excess(e, h):
    """Signed excess return at horizon h (the move beyond the market's, in
    the called direction), or None when the row carries no benchmark."""
    f, b = (e.get("fwd") or {}).get(h), (e.get("bench") or {}).get(h)
    if f is None or b is None:
        return None
    return signed(f - b, e.get("side"))


def norm_sector(label):
    """A sector label folded to its GICS sector (analysis only)."""
    s = (label or "").strip()
    return SECTOR_ALIASES.get(s, s) or "(no sector)"


def sector_of(e, sectors):
    """The row's own frozen sector, else today's lookup - folded."""
    return norm_sector(e.get("sector") or sectors.get((e.get("market"), e.get("ticker")), ""))


def hc_rule_of(e):
    """The High-conviction rule a roster row's `hiconv` was judged under."""
    if e.get("hc_rule"):
        return e["hc_rule"]
    day = str(e.get("base_day") or "")
    if day <= "2026-09-18":
        return HC_RULE_RETIRED
    if day <= "2026-09-20":
        return HC_RULE_UNKNOWN
    return HC_RULE_FOUR_CELL


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
        ex = [excess(e, h) for e in first]
        print(fmt(cohort_stats(ex), "    dedup EXCESS vs index  "))
        by_sec = collections.defaultdict(list)
        for e in first:
            by_sec[sector_of(e, sectors)].append(signed(e["fwd"][h], e["side"]))
        named = [(k, v) for k, v in by_sec.items() if len(v) >= MIN_N]
        if named:
            print("    by sector (dedup, buckets >= %d only):" % MIN_N)
            for k, v in sorted(named, key=lambda kv: -len(kv[1])):
                print(fmt(cohort_stats(v), f"      {k[:22]:22}"))
        # batch-100 item 11: the enrichment stamps, once present, buy two more
        # honest cuts — operating companies vs products, and the breadth
        # regime the alert fired into (stretched vs ordinary tape).
        prod = [signed(e["fwd"][h], e["side"]) for e in first if e.get("is_product") is True]
        real = [signed(e["fwd"][h], e["side"]) for e in first if e.get("is_product") is False]
        if len(prod) + len(real) >= MIN_N:
            print(fmt(cohort_stats(real), "    dedup operating cos    "))
            print(fmt(cohort_stats(prod), "    dedup products         "))
        with_b = [(e.get("breadth200"), signed(e["fwd"][h], e["side"]))
                  for e in first if isinstance(e.get("breadth200"), (int, float))]
        if len(with_b) >= MIN_N * 2:
            bs = sorted(b for b, _ in with_b)
            cut = bs[len(bs) // 2]                      # median split, sample-defined
            print(f"    by breadth on base_day (median split at {cut:.3f}):")
            print(fmt(cohort_stats([v for b, v in with_b if b < cut]), "      calmer half         "))
            print(fmt(cohort_stats([v for b, v in with_b if b >= cut]), "      stretched half      "))
        # batch-100 item 12: day-clustered SEs — one observation per base day,
        # the honest control for the serial correlation re-fires create.
        byday = collections.defaultdict(list)
        for e in rows:
            byday[e.get("base_day")].append(signed(e["fwd"][h], e["side"]))
        daymeans = [st.mean(v) for v in byday.values() if len(v) >= 3]
        print(fmt(cohort_stats(daymeans), "    day-clustered means    "))


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


ROSTERS = os.path.join(ROOT, "data", "edge_rosters.json")


def load_rosters(path=None):
    """Every roster row, READ ONLY: the monthly shards under
    data/edge_rosters/ (REFINE200 #62) plus any rows the pre-shard single
    file still holds. An unreadable shard is skipped and named."""
    path = path or ROSTERS
    rows, keys = [], set()
    for sp in sorted(glob.glob(os.path.join(os.path.splitext(path)[0], "*.json"))):
        try:
            with open(sp, encoding="utf-8") as fh:
                got = json.load(fh)["entries"]
        except (OSError, ValueError, KeyError, TypeError):
            print(f"(roster shard unreadable, skipped: {os.path.basename(sp)})")
            continue
        for r in got if isinstance(got, list) else []:
            rows.append(r)
            keys.add(r.get("key"))
    try:
        with open(path, encoding="utf-8") as fh:
            legacy = json.load(fh).get("entries") or []
    except (OSError, ValueError, AttributeError):
        legacy = []
    rows.extend(r for r in legacy if r.get("key") not in keys)
    return rows


def roster_report(entries, rosters):
    """Aligned vs plain-A+ on the SAME Yahoo plumbing (batch-100 WS-B item
    20) — the comparison that used to need git archaeology, now read straight
    off the two ledgers. Roster rows that were themselves aligned that day are
    excluded from the baseline so the cohorts stay disjoint. Per market, and
    the High-conviction tag split BY THE RULE that judged it (two definitions
    are pooled across 2026-09-20 otherwise)."""
    print("\n" + "=" * 72)
    print("ROSTER BASELINE (both cohorts on Yahoo closes, from the two ledgers)")
    print("=" * 72)
    aligned_days = {(e["market"], e["base_day"], e["ticker"]) for e in entries}
    for h in HORIZONS:
        al = dedup_first([e for e in entries if e["fwd"].get(h) is not None])
        ap = dedup_first([e for e in rosters
                          if e["fwd"].get(h) is not None
                          and (e["market"], e["base_day"], e["ticker"]) not in aligned_days])
        if not al and not ap:
            continue
        print(f"\n-- {h}-session --")
        print(fmt(cohort_stats([signed(e["fwd"][h], e["side"]) for e in al]), "  aligned dedup          "))
        print(fmt(cohort_stats([signed(e["fwd"][h], e["side"]) for e in ap]), "  roster A+ dedup        "))
        for s in ("long", "short"):
            print(fmt(cohort_stats([signed(e["fwd"][h], e["side"]) for e in al if e["side"] == s]),
                      f"    aligned {s:5}         "))
            print(fmt(cohort_stats([signed(e["fwd"][h], e["side"]) for e in ap if e["side"] == s]),
                      f"    roster  {s:5}         "))
        for m in MARKETS:
            print(fmt(cohort_stats([signed(e["fwd"][h], e["side"]) for e in ap if e["market"] == m]),
                      f"    roster  {m:7}       "))
        print(fmt(cohort_stats([excess(e, h) for e in al]), "  aligned EXCESS vs index"))
        print(fmt(cohort_stats([excess(e, h) for e in ap]), "  roster  EXCESS vs index"))
        for rule in sorted({hc_rule_of(e) for e in ap if e["side"] == "long"}):
            longs = [e for e in ap if e["side"] == "long" and hc_rule_of(e) == rule]
            print(f"    hiconv longs, rule: {rule}")
            print(fmt(cohort_stats([signed(e["fwd"][h], "long") for e in longs if e.get("hiconv")]),
                      "      hiconv               "))
            print(fmt(cohort_stats([signed(e["fwd"][h], "long") for e in longs if not e.get("hiconv")]),
                      "      not hiconv           "))


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
    prices = crypto_prices()
    entries, ex_a = clean(entries, prices)
    rosters, ex_r = clean(load_rosters(), prices)
    print(f"excluded from every statistic (rows kept in the ledgers): aligned {ex_a}; rosters {ex_r}")
    ledger_report(entries)
    if rosters:
        roster_report(entries, rosters)
    else:
        print("\n(no roster ledger yet - the Yahoo-plumbing A+ baseline starts"
              " accruing with the next daily run; --baseline uses git snapshots)")
    if args.baseline:
        baseline_report(entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
