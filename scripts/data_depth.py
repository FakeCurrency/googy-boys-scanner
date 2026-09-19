#!/usr/bin/env python3
"""How much FREE daily history can we actually get, per market?

Read-only diagnostic. It answers one owner question (2026-09-19: "How is it
possible to get MORE data for every chart ... I feel like the ASX charts are
lacking 1-2 years of data on most charts whereas the nasdaq charts seem to have
more") with measurements instead of inference, because the two things that
decide the answer are both empirical and neither is visible from a dev box:

  1. Does Yahoo HAVE more than the 5 years the site currently asks for, and does
     it have as much for .AX as for NASDAQ?
  2. Yahoo silently DEGRADES deep range= requests to coarser candles (this repo
     measured "max/1d observed returning monthly candles" on 2026-08-15, which
     is why public/js/chart.js settled on range=5y). Does asking by explicit
     DATE WINDOW (period1/period2) dodge that, so deep history can be stitched
     from chunks at true 1d granularity?

It probes, prints a table, and changes nothing -- no git, no commit, no config.
The printed post-mortem IS the deliverable (the backfill_history.py pattern).

Runs on a GitHub runner because a cloud Claude session's egress proxy refuses
query1.finance.yahoo.com and stooq.com (HTTP 000) -- the same reason ops.yml
exists. stdlib only, so the job needs no pip install.

  python3 scripts/data_depth.py                       # default sample
  python3 scripts/data_depth.py --symbols BHP.AX,AAPL --chunk-years 5
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = "googy-boys-scanner/1.0 (data-depth probe)"
YH_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
DAY = 86400

# A deliberately MIXED sample: mega-cap, mid, and thin small-cap per market,
# because the owner's complaint is about "most charts" and an all-blue-chip
# sample would answer a different question. ASX names are real scan rows.
DEFAULT_SAMPLE = {
    "asx": ["BHP.AX", "CBA.AX", "TLS.AX", "FPH.AX", "NIC.AX", "PPT.AX", "ACF.AX", "RML.AX"],
    "nasdaq": ["AAPL", "MSFT", "MDLZ", "SWKS", "ASO", "GLBE"],
}


def _get(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return fh.read()


def yahoo_chart(symbol: str, *, interval="1d", rng=None, p1=None, p2=None) -> dict | None:
    """One Yahoo v8 chart call, either range= or period1/period2. None on failure."""
    if rng:
        q = f"interval={interval}&range={rng}"
    else:
        q = f"interval={interval}&period1={int(p1)}&period2={int(p2)}"
    last = None
    for host in YH_HOSTS:
        try:
            raw = _get(f"https://{host}/v8/finance/chart/{urllib.parse.quote(symbol)}?{q}")
            res = (json.loads(raw).get("chart") or {}).get("result") or []
            if res:
                return res[0]
        except Exception as exc:                      # noqa: BLE001 - probe: report, never raise
            last = exc
    if last:
        print(f"      ! {symbol}: {type(last).__name__} {last}", file=sys.stderr)
    return None


def series(result: dict) -> tuple[list[int], list[float | None]]:
    ts = list(result.get("timestamp") or [])
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    return ts, list(quote.get("close") or [])


def median_spacing(ts: list[int]) -> int | None:
    """Median gap between consecutive bars, in seconds. The tell for a silently
    coarsened interval: true daily data medians at 86400 even with weekends in
    it, weekly at 604800. Mirrors _prices.js barSpacing().

    SORTS first and returns None rather than raising on anything unmeasurable.
    A source that hands back newest-first (or a single repeated stamp) used to
    empty the filtered generator and take statistics.median() down with it --
    i.e. a probe whose job is to report on odd data died on odd data."""
    gaps = [b - a for a, b in zip(sorted(ts), sorted(ts)[1:]) if b > a]
    if len(gaps) < 2:
        return None
    return int(statistics.median(gaps))


def describe(result: dict | None, want_interval_sec: int = DAY) -> dict:
    """Bars, span, flat/null share and whether the interval was degraded."""
    if not result:
        return {"ok": False}
    ts, cl = series(result)
    if not ts:
        return {"ok": False}
    nulls = sum(1 for c in cl if c is None)
    vals = [c for c in cl if c is not None]
    flat = 0
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    o, h, lo = quote.get("open") or [], quote.get("high") or [], quote.get("low") or []
    for i in range(min(len(o), len(h), len(lo), len(cl))):
        if None in (o[i], h[i], lo[i], cl[i]):
            continue
        if o[i] == h[i] == lo[i] == cl[i]:
            flat += 1
    gap = median_spacing(ts)
    first = dt.datetime.fromtimestamp(ts[0], dt.timezone.utc).date()
    last = dt.datetime.fromtimestamp(ts[-1], dt.timezone.utc).date()
    return {
        "ok": True, "bars": len(ts), "first": first, "last": last,
        "years": round((last - first).days / 365.25, 2),
        "nulls": nulls, "flat": flat,
        # Both null and single-print sessions are "no usable trade" for TA.
        "dead_share": round((nulls + flat) / len(ts), 3),
        "gap_days": round(gap / DAY, 2) if gap else None,
        # 1.8x is _prices.js intervalDegraded()'s own threshold.
        "degraded": bool(gap and gap > want_interval_sec * 1.8),
        "usable": len(vals),
    }


def stitch_windows(symbol: str, chunk_years: int, back_years: int) -> dict:
    """Ask by explicit DATE WINDOW in chunks and concatenate. This is the whole
    point of the probe: if each window returns true 1d bars, deep history is
    free -- Yahoo's degradation is a function of the requested RANGE, not of how
    old the data is, so N shallow windows beat one deep one."""
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    seen: dict[int, None] = {}
    merged_ts: list[int] = []
    gaps, degraded_chunks, chunks_ok = [], 0, 0
    for k in range(0, back_years, chunk_years):
        p2 = now - k * 365 * DAY
        p1 = now - min(k + chunk_years, back_years) * 365 * DAY
        res = yahoo_chart(symbol, p1=p1, p2=p2)
        d = describe(res)
        if not d["ok"]:
            continue
        chunks_ok += 1
        if d["degraded"]:
            degraded_chunks += 1
        if d["gap_days"]:
            gaps.append(d["gap_days"])
        for t in (res.get("timestamp") or []):
            if t not in seen:
                seen[t] = None
                merged_ts.append(t)
    if not merged_ts:
        return {"ok": False}
    merged_ts.sort()
    first = dt.datetime.fromtimestamp(merged_ts[0], dt.timezone.utc).date()
    last = dt.datetime.fromtimestamp(merged_ts[-1], dt.timezone.utc).date()
    return {
        "ok": True, "bars": len(merged_ts), "first": first, "last": last,
        "years": round((last - first).days / 365.25, 2),
        "chunks_ok": chunks_ok, "degraded_chunks": degraded_chunks,
        "median_gap_days": round(statistics.median(gaps), 2) if gaps else None,
    }



def overlap_check(symbol: str, chunk_years: int = 5) -> dict:
    """THE STITCHING SAFETY TEST.

    Yahoo back-adjusts history for splits and dividends. The question that
    decides whether deep history can be stitched at all: is that adjustment
    ABSOLUTE (relative to today, so any window agrees about a given date), or
    is it RELATIVE TO THE LAST BAR OF THE RESPONSE (so an old window is scaled
    to its own final close)? If it is relative, joining windows would create a
    fake price JUMP at every seam -- catastrophic on a chart whose entire
    purpose is reading levels.

    So: fetch two deliberately OVERLAPPING windows and compare the adjusted
    close for the same dates. ratio 1.0 means absolute and safe to concatenate.
    Anything else is the scale factor a stitcher would have to correct by.
    """
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    recent = yahoo_chart(symbol, p1=now - chunk_years * 365 * DAY, p2=now)
    older = yahoo_chart(symbol, p1=now - 2 * chunk_years * 365 * DAY,
                        p2=now - (chunk_years - 1) * 365 * DAY)
    if not recent or not older:
        return {"ok": False}

    def closes(res):
        ts = res.get("timestamp") or []
        q = (res.get("indicators") or {}).get("quote") or [{}]
        adj = ((res.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
        raw = q[0].get("close") or []
        # Mirror _prices.js yahooCandles(): bars are scaled by adjclose/close.
        out = {}
        for i, t in enumerate(ts):
            c = raw[i] if i < len(raw) else None
            a = adj[i] if adj and i < len(adj) else None
            if c:
                out[t] = (a / c) * c if a else c      # == a when present
        return out

    a, b = closes(recent), closes(older)
    shared = sorted(set(a) & set(b))
    if not shared:
        return {"ok": False, "why": "no overlapping dates"}
    ratios = [a[t] / b[t] for t in shared if b[t]]
    if not ratios:
        return {"ok": False, "why": "no comparable closes"}
    med = statistics.median(ratios)
    return {"ok": True, "shared": len(shared), "median_ratio": round(med, 6),
            "min_ratio": round(min(ratios), 6), "max_ratio": round(max(ratios), 6),
            "absolute": abs(med - 1.0) < 0.001 and abs(max(ratios) - min(ratios)) < 0.002}



def live_endpoint(site: str, symbol: str, rng: str = "25y") -> dict:
    """Probe OUR OWN deployed /api/price, not Yahoo.

    Added 2026-09-19 after the deep-history change shipped and the owner still
    saw 5 years. The three explanations -- an old build still deployed, the new
    build erroring, or the browser holding a cached page -- are indistinguishable
    from a dev box, and this separates them in one call. A cloud session's proxy
    refuses pages.dev, so it runs on the runner with everything else.
    """
    url = f"{site.rstrip('/')}/api/price?symbol={urllib.parse.quote(symbol)}&range={rng}&interval=1d"
    try:
        raw = _get(url, timeout=40)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "why": f"HTTP {exc.code}"}
    except Exception as exc:                          # noqa: BLE001
        return {"ok": False, "why": type(exc).__name__}
    try:
        j = json.loads(raw)
    except Exception:                                 # noqa: BLE001
        return {"ok": False, "why": "not JSON: " + raw[:60].decode("utf-8", "replace")}
    if not j.get("ok"):
        return {"ok": False, "why": str(j.get("error"))[:60]}
    cs = j.get("candles") or []
    if not cs:
        return {"ok": False, "why": "no candles"}
    f = dt.datetime.fromtimestamp(cs[0]["time"], dt.timezone.utc).date()
    l = dt.datetime.fromtimestamp(cs[-1]["time"], dt.timezone.utc).date()
    return {"ok": True, "bars": len(cs), "first": f, "last": l,
            "years": round((l - f).days / 365.25, 2),
            "source": j.get("source"), "degraded": j.get("degraded")}


def stooq(symbol: str) -> dict:
    """Stooq's free daily CSV — no key, no quota published. A candidate SECOND
    free source for depth. ASX maps <ticker>.AX -> <ticker>.au."""
    s = symbol.lower()
    s = s[:-3] + ".au" if s.endswith(".ax") else s + ".us"
    try:
        raw = _get(f"https://stooq.com/q/d/l/?s={s}&i=d").decode("utf-8", "replace")
    except Exception as exc:                          # noqa: BLE001
        return {"ok": False, "why": f"{type(exc).__name__}"}
    rows = list(csv.DictReader(io.StringIO(raw)))
    dates = [r["Date"] for r in rows if r.get("Date") and r.get("Close")]
    if not dates:
        return {"ok": False, "why": raw.strip()[:60] or "empty"}
    f = dt.date.fromisoformat(dates[0])
    l = dt.date.fromisoformat(dates[-1])
    return {"ok": True, "sym": s, "bars": len(dates), "first": f, "last": l,
            "years": round((l - f).days / 365.25, 2)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Measure available free daily history per market")
    ap.add_argument("--symbols", help="comma list, overrides the built-in sample")
    ap.add_argument("--chunk-years", type=int, default=5, help="window size for the stitch test")
    ap.add_argument("--back-years", type=int, default=25, help="how far back to try stitching")
    ap.add_argument("--skip-stooq", action="store_true")
    ap.add_argument("--site", help="also probe THIS deployment's /api/price "
                                   "(e.g. https://googy-boys-scanner.pages.dev)")
    a = ap.parse_args(argv)

    sample = ({"custom": [s.strip() for s in a.symbols.split(",") if s.strip()]}
              if a.symbols else DEFAULT_SAMPLE)

    print("=" * 78)
    print("FREE DAILY HISTORY — what each source actually returns")
    print("=" * 78)
    print(f"chunk={a.chunk_years}y  back={a.back_years}y  probed {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC")
    print("\nwhat the site asks for today: chart.js range=5y interval=1d;"
          "\n                             scanner VIVEK_DATA_PERIOD = 5y\n")

    summary: dict[str, list[tuple[str, dict, dict, dict]]] = {}
    for market, syms in sample.items():
        print(f"\n{'─' * 78}\n{market.upper()}\n{'─' * 78}")
        print(f"{'symbol':10} {'ask 5y':>26} {'ask max':>26}")
        print(f"{'':10} {'bars  first      yrs dead':>26} {'bars  first      yrs degr':>26}")
        rows = []
        for sym in syms:
            five = describe(yahoo_chart(sym, rng="5y"))
            mx = describe(yahoo_chart(sym, rng="max"))
            f5 = (f"{five['bars']:5} {five['first']} {five['years']:5.1f} {five['dead_share']*100:3.0f}%"
                  if five["ok"] else "            (failed)")
            fm = (f"{mx['bars']:5} {mx['first']} {mx['years']:5.1f} "
                  f"{'COARSE' if mx['degraded'] else 'ok':>5}" if mx["ok"] else "            (failed)")
            print(f"{sym:10} {f5:>26} {fm:>26}")
            rows.append((sym, five, mx, {}))
        summary[market] = rows

    print(f"\n\n{'=' * 78}\nSTITCHED DATE WINDOWS — {a.chunk_years}y chunks back {a.back_years}y, at interval=1d")
    print("(the question: does asking by date dodge the coarsening that range=max hits?)")
    print("=" * 78)
    print(f"{'symbol':10} {'bars':>7} {'first':>12} {'years':>7} {'chunks':>7} {'coarse':>7} {'gap(d)':>7}")
    for market, syms in sample.items():
        for sym in syms:
            st = stitch_windows(sym, a.chunk_years, a.back_years)
            if not st["ok"]:
                print(f"{sym:10} {'(failed)':>7}")
                continue
            print(f"{sym:10} {st['bars']:>7} {str(st['first']):>12} {st['years']:>7.1f} "
                  f"{st['chunks_ok']:>7} {st['degraded_chunks']:>7} {str(st['median_gap_days']):>7}")

    if a.site:
        print(f"\n\n{'=' * 78}\nLIVE ENDPOINT — what {a.site} actually serves the chart")
        print("(old build deployed? new build erroring? or is it the browser cache?)")
        print("=" * 78)
        print(f"{'symbol':10} {'bars':>7} {'first':>12} {'years':>7} {'source':>12}  note")
        for market, syms in sample.items():
            for sym in syms:
                for rng in ("5y", "25y"):
                    r = live_endpoint(a.site, sym, rng)
                    if r["ok"]:
                        print(f"{sym + ' ' + rng:10} {r['bars']:>7} {str(r['first']):>12} "
                              f"{r['years']:>7.1f} {str(r['source']):>12}  "
                              f"{'COARSE' if r['degraded'] else ''}")
                    else:
                        print(f"{sym + ' ' + rng:10} {'(fail)':>7}  {r['why']}")

    print(f"\n\n{'=' * 78}\nSEAM TEST — do two overlapping windows agree about the same dates?")
    print("(if not, stitched history would jump at every join and every level would be wrong)")
    print("=" * 78)
    print(f"{'symbol':10} {'shared':>7} {'median':>10} {'min':>10} {'max':>10}  verdict")
    for market, syms in sample.items():
        for sym in syms:
            ov = overlap_check(sym, a.chunk_years)
            if not ov["ok"]:
                print(f"{sym:10} {'(n/a)':>7}  {ov.get('why','failed')}")
                continue
            verdict = "SAFE to concatenate" if ov["absolute"] else "NEEDS RESCALING"
            print(f"{sym:10} {ov['shared']:>7} {ov['median_ratio']:>10.6f} "
                  f"{ov['min_ratio']:>10.6f} {ov['max_ratio']:>10.6f}  {verdict}")

    if not a.skip_stooq:
        print(f"\n\n{'=' * 78}\nSTOOQ (free CSV, no key) — a candidate second source\n{'=' * 78}")
        print(f"{'symbol':10} {'mapped':12} {'bars':>7} {'first':>12} {'years':>7}")
        for market, syms in sample.items():
            for sym in syms:
                s = stooq(sym)
                if s["ok"]:
                    print(f"{sym:10} {s['sym']:12} {s['bars']:>7} {str(s['first']):>12} {s['years']:>7.1f}")
                else:
                    print(f"{sym:10} {'-':12} {'(none)':>7}  {s.get('why','')}")

    # The comparison the owner actually asked for, stated plainly.
    print(f"\n\n{'=' * 78}\nPER-MARKET MEDIANS\n{'=' * 78}")
    for market, rows in summary.items():
        ok5 = [r[1] for r in rows if r[1].get("ok")]
        okm = [r[2] for r in rows if r[2].get("ok")]
        if not ok5:
            continue
        print(f"{market:8} at range=5y : median span {statistics.median(r['years'] for r in ok5):.2f}y, "
              f"median dead sessions {statistics.median(r['dead_share'] for r in ok5)*100:.0f}%")
        if okm:
            print(f"{'':8} at range=max: median span {statistics.median(r['years'] for r in okm):.2f}y, "
                  f"{sum(1 for r in okm if r['degraded'])}/{len(okm)} came back COARSER than daily")
    return 0


if __name__ == "__main__":
    sys.exit(main())
