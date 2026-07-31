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
import os
import sys
import zoneinfo

from . import config, data, output, reversal, scanerrors, spec, universe

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
    # TOP100 #62: this was already atomic (temp + os.replace) so #64 left it
    # alone, but it kept json's default allow_nan=True — one NaN bar would emit
    # a bare `NaN` token, which JSON.parse rejects, blanking the WHOLE chart
    # page rather than one candle. Same formatting arguments, so the published
    # bytes are unchanged.
    output.write_json(os.path.join(out_dir, f"{sym}.json"),
                      {"ticker": sym, "candles": candles},
                      indent=None, separators=(",", ":"),
                      ensure_ascii=False, newline=True)


def scan_market(market_key: str, limit: int | None = None) -> dict:
    mk = config.MARKETS[market_key]
    cur = getattr(mk, "currency_symbol", "A$" if market_key == "asx" else "$")
    items = universe.load_universe(market_key, full=True)
    if limit:
        items = items[:limit]
    yf_map = {it["yf"]: it for it in items}
    frames = data.download(list(yf_map), period="2y", interval="1d")

    results = []
    # TOP100 #66 — TWO logs, because these are two different failures and
    # merging them would destroy the distinction that makes them worth counting.
    # A `build_row` throw means the name is ABSENT from the page (indistinguish-
    # able from "never set up", which is the whole defect). A `write_chart_json`
    # throw is worse in a quieter way: the row IS published, so the site lists
    # the name and its chart page then has no candles.
    errors = scanerrors.ErrorLog(f"specs [{market_key}]")
    chart_errors = scanerrors.ErrorLog(f"spec charts [{market_key}]")
    for yf_sym, df in frames.items():
        info = yf_map.get(yf_sym)
        if info is None or df is None or df.empty:
            continue
        df = _with_date_column(df)
        try:
            row = build_row(info.get("symbol", yf_sym), info, df, cur)
        except Exception as e:
            # one bad frame never kills the scan — but it is no longer silent
            errors.record(info.get("symbol", yf_sym), e)
            continue
        if row:
            results.append(row)
            try:
                write_chart_json(market_key, row["symbol"], df)
            except Exception as e:
                chart_errors.record(row["symbol"], e)
    results.sort(key=lambda r: (GRADE_RANK.get(r["grade"], 9), -r["score"], -r["rr"]))
    # Both printed unconditionally: a standing pair of zeros is what makes a
    # jump legible. `scanned` differs per log on purpose — build_row is offered
    # every downloaded frame, write_chart_json only the names that produced a
    # row, so sharing one denominator would understate the chart failure rate.
    errors.report(len(frames))
    chart_errors.report(len(results))

    tz = zoneinfo.ZoneInfo("Australia/Melbourne")
    payload = {
        "generated_at": datetime.datetime.now(tz).isoformat(timespec="seconds"),
        "market": market_key,
        "setup_type": "spec",
        "currency_symbol": cur,
        "universe_size": len(items),
        "results": results,
        # TOP100 #66. `errors`/`error_sample` carry the SAME meaning as in the
        # vivek payload — a name that failed to produce a row — so a reader does
        # not have to learn two vocabularies. `chart_*` is the second failure
        # mode above, kept separate rather than summed.
        **errors.payload(),
        **chart_errors.payload("chart_"),
    }
    path = os.path.join(OUT_DIR, f"{market_key}_spec.json")
    # TOP100 #62 — see write_chart_json above; already atomic, still allow_nan.
    output.write_json(path, payload, indent=1, ensure_ascii=False, newline=True)
    # repo hygiene: drop chart candles for names no longer in the results
    chart_dir = os.path.join(OUT_DIR, "spec_charts", market_key)
    keep = {r["symbol"] for r in results}
    removed = 0
    try:
        for name in os.listdir(chart_dir):
            if name.endswith(".json") and name[:-5] not in keep:
                os.remove(os.path.join(chart_dir, name))
                removed += 1
    except FileNotFoundError:
        pass
    print(f"[{market_key}] specs: {len(results)} setups from {len(items)} names -> {path}"
          + (f" (pruned {removed})" if removed else ""))
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
        payload = scan_market(m, limit=args.limit)
        # Specs -> VIVEK graduation watch (owner-ruled, 2026-07-31): fold the
        # published results into the report-only registry, AFTER the specs
        # publish so it records what actually shipped. Same posture as
        # run.py's funnel-history hook — a report artefact must never kill
        # the scan, so the failure is named and the loop walks on.
        try:
            from . import specgrad
            specgrad.update(m, OUT_DIR, payload)
        except (OSError, ValueError, TypeError, KeyError) as e:  # report-only
            print(f"[{m}] WARNING spec graduation update failed: "
                  f"{e.__class__.__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
