"""Specs scanner runner — the third lens, rebuilt 2026-07-02.

The engine (spec.py: volume-spike breakouts from a base) survived the VIVEK
5.0 overhaul; its orchestration didn't. This module is that orchestration,
kept OFF the 30-minute hot path: it runs nightly (phasemap.yml) and writes
public/data/<market>_spec.json for the SPECS page and the chart page's
`mode=spec` fallback (which expects the legacy row shape).

    python -m scanner.spec_run                 # asx + nasdaq
    python -m scanner.spec_run --market asx
    python -m scanner.spec_run --limit 200     # quick test

Crypto is excluded: SPEC_MAX_PRICE is a market-currency cents filter that
has no meaning for coins (see config note).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import zoneinfo

from . import config, data, reversal, spec, universe

MARKETS = ("asx", "nasdaq")
GRADE_RANK = {"A+": 0, "A": 1, "B": 2, "C": 3}
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "public", "data")


def build_row(sym: str, info: dict, df, cur: str) -> dict | None:
    sig = spec.evaluate(df, max_price=config.SPEC_MAX_PRICE)
    if not sig:
        return None
    score, grade, fired = spec.score_and_grade(sig)
    if not grade:
        return None
    lv = spec.compute_levels(df, sig)
    if not lv or lv.get("rr", 0) <= 0:
        return None
    if config.DEMOTE_LOW_RR and grade in ("A+", "A") \
            and lv["rr"] < config.MIN_TRADEABLE_RR:
        grade = "B"
    detail = spec.build_detail(df, sig, lv)
    chips = spec.build_chips(fired, sig)
    return {
        "symbol": sym,
        "name": info.get("name", sym),
        "sector": info.get("sector", ""),
        "setup_type": "spec",
        "grade": grade,
        "score": score,
        "score_max": config.SPEC_SCORE_MAX,
        "chips": chips,
        "price": round(sig["close"], 8),
        "entry": lv["entry"],
        "stop": lv["stop"],
        "target": lv["target"],
        "rr": lv["rr"],
        "low_rr": lv["rr"] < getattr(config, "LOW_RR_THRESHOLD", 1.5),
        "spike_ratio": round(sig["spike_ratio"], 1),
        "off_high_pct": round(sig["off_high"] * 100, 1),
        "detail": detail,
        "analysis": spec.spec_narrative(sym, sig, lv, detail, cur),
    }


def _with_date_column(df):
    """data.download frames carry the date in a DatetimeIndex — normalise to a
    'Date' column so downstream code can use it uniformly."""
    if "Date" in df.columns:
        return df
    out = df.reset_index()
    if "Date" not in out.columns:
        out = out.rename(columns={out.columns[0]: "Date"})
    return out


def write_chart_json(market_key: str, sym: str, df) -> None:
    """Last ~220 daily candles for the chart page (works offline/deterministic;
    the live feed is only an enrichment on top)."""
    out_dir = os.path.join(OUT_DIR, "spec_charts", market_key)
    os.makedirs(out_dir, exist_ok=True)
    tail = df.tail(220)
    candles = [
        {"t": str(r.Date)[:10],
         "o": round(float(r.Open), 8), "h": round(float(r.High), 8),
         "l": round(float(r.Low), 8), "c": round(float(r.Close), 8),
         "v": int(r.Volume) if r.Volume == r.Volume else 0}
        for r in tail.itertuples()
    ]
    path = os.path.join(out_dir, f"{sym}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"ticker": sym, "candles": candles}, fh,
                  ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")
    os.replace(tmp, path)


def scan_market(market_key: str, limit: int | None = None) -> dict:
    mk = config.MARKETS[market_key]
    cur = getattr(mk, "currency_symbol", "A$" if market_key == "asx" else "$")
    items = universe.load_universe(market_key, full=True)
    if limit:
        items = items[:limit]
    yf_map = {it["yf"]: it for it in items}
    frames = data.download(list(yf_map), period="2y", interval="1d")

    results = []
    for yf_sym, df in frames.items():
        info = yf_map.get(yf_sym)
        if info is None or df is None or df.empty:
            continue
        df = _with_date_column(df)
        try:
            row = build_row(info.get("symbol", yf_sym), info, df, cur)
        except Exception:
            continue           # one bad frame never kills the scan
        if row:
            results.append(row)
            try:
                write_chart_json(market_key, row["symbol"], df)
            except Exception:
                pass
    results.sort(key=lambda r: (GRADE_RANK.get(r["grade"], 9), -r["score"], -r["rr"]))

    tz = zoneinfo.ZoneInfo("Australia/Melbourne")
    payload = {
        "generated_at": datetime.datetime.now(tz).isoformat(timespec="seconds"),
        "market": market_key,
        "setup_type": "spec",
        "currency_symbol": cur,
        "universe_size": len(items),
        "results": results,
    }
    path = os.path.join(OUT_DIR, f"{market_key}_spec.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(tmp, path)
    print(f"[{market_key}] specs: {len(results)} setups from {len(items)} names -> {path}")
    return payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="specs scanner")
    ap.add_argument("--market", default="all", help="asx | nasdaq | all")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv)
    markets = MARKETS if args.market == "all" else tuple(args.market.split(","))
    for m in markets:
        if m not in MARKETS:
            print(f"unknown/unsupported market: {m}")
            return 2
    for m in markets:
        scan_market(m, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
