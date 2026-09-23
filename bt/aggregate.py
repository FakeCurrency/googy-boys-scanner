"""Merge bt/out/*.json (v2 shards) into bt/RESULTS.md + bt/results.json."""

from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
LENSES = ("vivek", "phasemap", "momentum", "specs")
TITLE = {"vivek": "VIVEK 5.0 — long A+/A armed plans",
         "phasemap": "PhaseMap — bullish A+/A",
         "momentum": "Momentum — long signals (Rule A + Rule B)",
         "specs": "Specs — long (A+/A/B)"}


def stats(ts):
    rs = [t["r"] for t in ts]
    usd = [t["usd"] for t in ts]
    w = [r for r in rs if r > 0]
    l = [r for r in rs if r <= 0]
    n = len(rs)
    return {"trades": n, "wins": len(w), "losses": len(l),
            "win_pct": round(100 * len(w) / n, 1) if n else None,
            "r_won": round(sum(w), 1), "r_lost": round(sum(l), 1), "net_r": round(sum(rs), 1),
            "expectancy_r": round(sum(rs) / n, 3) if n else None,
            "pf": round(sum(w) / -sum(l), 2) if sum(l) < 0 else None,
            "usd_won": round(sum(u for u in usd if u > 0)), "usd_lost": round(sum(u for u in usd if u <= 0)),
            "net_usd": round(sum(usd)),
            "first": min((t["entry_date"] for t in ts), default=None),
            "last": max((t["entry_date"] for t in ts), default=None)}


def main() -> int:
    shards = [json.loads(p.read_text()) for p in sorted((ROOT / "out").glob("*.json"))]
    shards = [s for s in shards if s.get("version") == 2]
    trades = [t for s in shards for t in s["trades"]]
    cov = {}
    for s in shards:
        c = cov.setdefault(s["market"], {"universe": set(), "shards": 0, "of": s["of"], "symbols": 0,
                                         "downloaded": 0, "errors": collections.Counter()})
        c["universe"].add(s["universe"]); c["shards"] += 1
        c["symbols"] += s["shard_symbols"]; c["downloaded"] += s["downloaded"]
        c["errors"].update(s.get("errors") or {})
    coverage = {m: {"universe": sorted(c["universe"]), "shards": f"{c['shards']}/{c['of']}",
                    "downloaded": c["downloaded"], "symbols": c["symbols"], "errors": dict(c["errors"])}
                for m, c in sorted(cov.items())}
    longs = [t for t in trades if t["direction"] == "long"]
    res = {"coverage": coverage, "headline": {}, "detail": {}, "shorts": {}}
    for lens in LENSES:
        lt = [t for t in longs if t["lens"] == lens]
        res["headline"][lens] = stats(lt)
        d = {"by_market": {m: stats([t for t in lt if t["market"] == m]) for m in sorted({t["market"] for t in lt})},
             "by_cohort": {c: stats([t for t in lt if t["cohort"] == c]) for c in sorted({t["cohort"] for t in lt})},
             "by_exit": {e: stats([t for t in lt if t["exit_reason"] == e]) for e in sorted({t["exit_reason"] for t in lt})}}
        if lens == "vivek":
            d["by_timeframe"] = {tf: stats([t for t in lt if t["timeframe"] == tf]) for tf in ("1D", "3D", "1W")}
            d["high_conviction"] = stats([t for t in lt if t.get("hc_cell")])
        if lens == "phasemap":
            d["liquid_only"] = stats([t for t in lt if not t.get("illiquid")])
        res["detail"][lens] = d
        st = [t for t in trades if t["lens"] == lens and t["direction"] == "short"]
        if st:
            res["shorts"][lens] = stats(st)
    res["headline"]["all four, long"] = stats(longs)
    (ROOT / "results.json").write_text(json.dumps(res, indent=1) + "\n")

    def row(label, s):
        if not s["trades"]:
            return f"| {label} | 0 | | | | | | | | |"
        return (f"| {label} | {s['trades']:,} | {s['win_pct']}% | +{s['r_won']:,.1f}R | {s['r_lost']:,.1f}R | "
                f"**{s['net_r']:+,.1f}R** | {s['expectancy_r']:+.3f}R | {s['pf']} | "
                f"${s['usd_won']:,} / ${s['usd_lost']:,} | **${s['net_usd']:+,}** |")
    head = ("| | Trades | Win % | R won | R lost | Net R | Per trade | PF | $ won / $ lost | Net $ |\n"
            "|---|---|---|---|---|---|---|---|---|---|")
    md = ["# Four-lens backtest (v2, permanent R models) — results", "",
          "Flat $1,000 per position. 5y daily bars, today's universe (survivorship bias).", "",
          "## Headline — longs", "", head]
    for lens in LENSES:
        md.append(row(TITLE[lens], res["headline"][lens]))
    md.append(row("**All four, long**", res["headline"]["all four, long"]))
    for lens in LENSES:
        d = res["detail"][lens]
        md += ["", f"## {TITLE[lens]}", "", head]
        for k in ("by_market", "by_cohort", "by_timeframe", "by_exit"):
            for name, s in (d.get(k) or {}).items():
                md.append(row(f"{k[3:]}: {name}", s))
        for k in ("high_conviction", "liquid_only"):
            if k in d:
                md.append(row(k.replace("_", " "), d[k]))
    if res["shorts"]:
        md += ["", "## Shorts (not in the headline)", "", head]
        for lens, s in res["shorts"].items():
            md.append(row(lens, s))
    md += ["", "## Coverage", "", "```", json.dumps(coverage, indent=1), "```", ""]
    (ROOT / "RESULTS.md").write_text("\n".join(md))
    print("\n".join(md[:14]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
