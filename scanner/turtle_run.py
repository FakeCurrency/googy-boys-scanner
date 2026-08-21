"""TURTLE lens runner — publishes public/data/<market>_turtle.json.

    python -m scanner.turtle_run                  # asx + nasdaq + crypto
    python -m scanner.turtle_run --market asx
    python -m scanner.turtle_run --limit 200      # quick local pass

Runs nightly (turtle.yml), OFF the 30-minute hot path and outside the `scan`
concurrency group: it writes only its own files and reads nothing the scan
writes. Crypto IS included here, unlike the Specs lens — Specs excludes it
because SPEC_MAX_PRICE is a cents filter with no meaning for coins, whereas
every Turtle parameter is expressed in N and is unit-free by construction.

Five years of daily bars by default. The System 1 filter needs enough history
to have seen prior breakouts resolve, and the per-name record the page ranks
on is only worth reading over a span that contains more than one regime.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import zoneinfo

from . import config, data, output, scanerrors, turtle, universe

MARKETS = ("asx", "nasdaq", "crypto")
PERIOD = "5y"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "public", "data")


def _with_date_column(df):
    """data.download frames carry the date in a DatetimeIndex — normalise to a
    'Date' column so the engine can label trades uniformly. Same helper as
    spec_run's, kept local rather than shared: the two lenses are deliberately
    independent and a shared private helper is how a coupling starts."""
    if "Date" in df.columns:
        return df
    out = df.reset_index()
    if "Date" not in out.columns:
        out = out.rename(columns={out.columns[0]: "Date"})
    return out


def params_block() -> dict:
    """Every parameter the engine ran with, published beside the results.

    Not decoration. The page states rule numbers in prose and a reader has no
    way to tell whether the prose describes the code — so the code publishes
    its own constants and the page renders THOSE, which makes a drift between
    the two impossible rather than merely unlikely.
    """
    c = config
    return {
        "n_period": c.TURTLE_N_PERIOD,
        "s1_entry": c.TURTLE_S1_ENTRY, "s1_exit": c.TURTLE_S1_EXIT,
        "s2_entry": c.TURTLE_S2_ENTRY, "s2_exit": c.TURTLE_S2_EXIT,
        "stop_n": c.TURTLE_STOP_N,
        "pyramid_step_n": c.TURTLE_PYRAMID_STEP_N,
        "max_units": c.TURTLE_MAX_UNITS,
        "risk_pct": c.TURTLE_RISK_PCT,
        "max_units_close_corr": c.TURTLE_MAX_UNITS_CLOSE_CORR,
        "max_units_loose_corr": c.TURTLE_MAX_UNITS_LOOSE_CORR,
        "max_units_direction": c.TURTLE_MAX_UNITS_DIRECTION,
        "drawdown_step_pct": c.TURTLE_DRAWDOWN_STEP_PCT,
        "drawdown_cut_pct": c.TURTLE_DRAWDOWN_CUT_PCT,
        "whipsaw_risk_pct": c.TURTLE_WHIPSAW_RISK_PCT,
        "whipsaw_stop_n": c.TURTLE_WHIPSAW_STOP_N,
        "account_equity": c.TURTLE_ACCOUNT_EQUITY,
        "allow_shorts": c.TURTLE_ALLOW_SHORTS,
        "min_bars": c.TURTLE_MIN_BARS,
        "approach_pct": c.TURTLE_APPROACH_PCT,
        "period": PERIOD,
    }


def aggregate(rows: list[dict]) -> dict:
    """What the whole market did under these rules, and the cohort counts.

    The aggregate record is the honest headline: one flattering name proves
    nothing, and the page's per-name table invites exactly that error. Summed
    across the market it is a wide, in-sample, survivor-biased number — the
    payload says so and the page repeats it.
    """
    trades = sum((r["record"]["n"] for r in rows), 0)
    total_r = sum((r["record"]["total_r"] for r in rows), 0.0)
    wins = sum((r["record"]["wins"] for r in rows), 0)
    with_trades = [r for r in rows if r["record"]["n"]]
    return {
        "names": len(rows),
        "names_with_trades": len(with_trades),
        "trades": trades,
        "wins": wins,
        "win_pct": round(100.0 * wins / trades, 1) if trades else None,
        "total_r": round(total_r, 2),
        "avg_r": round(total_r / trades, 4) if trades else None,
        "long": sum(1 for r in rows if r["state"] == "long"),
        "short": sum(1 for r in rows if r["state"] == "short"),
        "flat": sum(1 for r in rows if r["state"] == "flat"),
        "fired_today": sum(1 for r in rows if r.get("signal")),
        "added_today": sum(1 for r in rows if r.get("added_today")),
        "approaching": sum(1 for r in rows if r.get("approaching")),
        "s1_blocked": sum(1 for r in rows if r.get("s1_blocked")),
    }


def scan_market(market_key: str, limit: int | None = None,
                period: str = PERIOD, equity: float | None = None) -> dict:
    mk = config.MARKETS[market_key]
    cur = getattr(mk, "currency_symbol", "$")
    items = universe.load_universe(market_key, full=True)
    if limit:
        items = items[:limit]
    yf_map = {it["yf"]: it for it in items}
    frames = data.download(list(yf_map), period=period, interval="1d")

    rows: list[dict] = []
    errors = scanerrors.ErrorLog(f"turtle [{market_key}]")
    skipped_short = skipped_illiquid = 0
    for yf_sym, df in frames.items():
        info = yf_map.get(yf_sym)
        if info is None or df is None or df.empty:
            continue
        if len(df) < config.TURTLE_MIN_BARS:
            skipped_short += 1
            continue
        df = _with_date_column(df)
        sym = info.get("symbol", yf_sym)
        try:
            row = turtle.build_row(sym, info, df, market_key, equity=equity)
        except Exception as e:
            # One bad frame never kills the scan, and never does it silently:
            # a name that throws every night is otherwise indistinguishable
            # from a name that simply never breaks out (TOP100 #66).
            errors.record(sym, e)
            continue
        if row is None:
            skipped_illiquid += 1
            continue
        rows.append(row)

    rows.sort(key=turtle.rank_key)
    published = rows[:config.TURTLE_MAX_ROWS]
    errors.report(len(frames))

    tz = zoneinfo.ZoneInfo("Australia/Melbourne")
    payload = {
        "generated_at": datetime.datetime.now(tz).isoformat(timespec="seconds"),
        "market": market_key,
        "lens": "turtle",
        "currency_symbol": cur,
        "universe_size": len(items),
        "evaluated": len(rows),
        "skipped_short_history": skipped_short,
        "skipped_illiquid": skipped_illiquid,
        "truncated": max(0, len(rows) - len(published)),
        "params": params_block(),
        "aggregate": aggregate(rows),
        "results": published,
        **errors.payload(),
    }
    path = os.path.join(OUT_DIR, f"{market_key}_turtle.json")
    output.write_json(path, payload, indent=1, ensure_ascii=False, newline=True)
    agg = payload["aggregate"]
    print(f"[{market_key}] turtle: {len(rows)} names "
          f"({agg['long']}L/{agg['short']}S/{agg['flat']}F, "
          f"{agg['fired_today']} fired, {agg['approaching']} approaching) "
          f"from {len(items)} in universe -> {path}")
    print(f"[{market_key}] turtle record (in-sample, {period}): "
          f"{agg['trades']} trades, {agg['win_pct']}% win, "
          f"{agg['total_r']}R total, {agg['avg_r']}R average")
    return payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="turtle scanner")
    ap.add_argument("--market", default="all", help="asx | nasdaq | crypto | all")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--period", default=PERIOD)
    ap.add_argument("--equity", type=float,
                    help="account size the published unit sizes are computed "
                         "against (default config.TURTLE_ACCOUNT_EQUITY)")
    args = ap.parse_args(argv)
    markets = MARKETS if args.market == "all" else tuple(args.market.split(","))
    for m in markets:
        if m not in MARKETS:
            print(f"unknown/unsupported market: {m}")
            return 2
    failed = []
    for m in markets:
        try:
            scan_market(m, limit=args.limit, period=args.period, equity=args.equity)
        except Exception as e:                                   # noqa: BLE001
            # TOP100 #67: a market that fails ENTIRELY used to print one line
            # and exit 0, so a night with no ASX file at all looked like a
            # night with no ASX breakouts.
            failed.append(m)
            print(f"[{m}] turtle scan FAILED: {e.__class__.__name__}: {e}")
    if failed:
        print(f"turtle: {len(failed)} market(s) failed: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
