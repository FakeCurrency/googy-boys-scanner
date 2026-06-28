"""VIVEK 5.0 walk-forward backtester.

Replays the REAL engine over history rather than reimplementing the strategy:
for each symbol it walks the daily series bar-by-bar and, on every bar where
price is near a 200 SMA, runs the exact same ``vivek.evaluate`` /
``build_plans`` / grading the live scanner uses on a slice of history *up to and
including that bar* (so there is no look-ahead). When that produces an ARMED
A+/A setup it opens a paper trade at the NEXT bar's open and manages it forward
with the same 5.0 rules (scale at TP1/2/3, SL → break-even at TP1 → locked
structure at TP2) and the same fees + slippage R-drag the live bot/journal use.

Fills are pessimistic intrabar: within a bar the adverse extreme (the stop
side) is checked BEFORE the favourable extreme, so when a bar's range spans
both a stop and a target the stop is assumed to fill first.

Backtestable timeframes: Daily (1D) and Weekly (1W). 4H is not backtestable
server-side (no deep intraday history). Honest caveats: today's universe →
survivorship bias; yfinance data quality; A+ setups are rare so N is modest.

CLI:  python -m scanner.vivek_backtest --market all --limit 60 --period 10y
"""

import argparse
import datetime as dt
import json
import logging
import pathlib

import numpy as np
import pandas as pd

from . import config, vivek
from .broker.vivek_bot import size_position, _is_fund_or_reit
from .vivek_journal import _snapshot, _mark, _apply_costs, _r_of, costs_for

log = logging.getLogger("vivek_backtest")

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_FILE = ROOT / "public" / "data" / "vivek_backtest.json"

EQUITY = config.VIVEK_BOT_ACCOUNT_EQUITY
TIMEFRAMES = ("1D", "1W")


# ── per-symbol replay ─────────────────────────────────────────────────────────

def _candidate_mask(df: pd.DataFrame) -> np.ndarray:
    """Bars where price is near a 200 SMA (daily or weekly) — the only place a
    reaction can exist. A superset of the engine's in-play test (the engine
    re-checks precisely), so it only saves work, never invents trades."""
    close = df["Close"]
    tol = config.VIVEK_NEAR_TOL * 1.3                      # widen so we never miss one
    dsma = close.rolling(config.VIVEK_SMA).mean()
    wk = close.resample("W-FRI").last()
    wsma = wk.rolling(config.VIVEK_SMA).mean().reindex(df.index, method="ffill")
    near_d = (close - dsma).abs() / close <= tol
    near_w = (close - wsma).abs() / close <= tol
    return (near_d.fillna(False) | near_w.fillna(False)).to_numpy()


def _build_row(sig: dict, df_slice: pd.DataFrame, symbol: str, name: str, sector: str):
    """Replicate scan.py's row build (grade + gate + plans), minus hysteresis."""
    points, grade, _ = vivek.score_and_grade(sig)
    if grade is None:
        return None, None, None
    plans = vivek.build_plans(df_slice, sig)
    lv = plans.get("1D")
    if not lv or lv.get("rr", 0) <= 0:
        return None, None, None
    armed = bool(lv.get("armed"))
    grade, _notes = vivek.gate_grade(grade, sig, lv["rr"], armed)
    if grade is None:
        return None, None, None
    entry_types = ([lv["entry_trigger"]] if armed and lv.get("entry_trigger")
                   else vivek.entry_types(sig))
    row = {"symbol": symbol, "name": name, "sector": sector,
           "dir": "LONG" if sig["direction"] == "long" else "SHORT",
           "grade": grade, "entry_types": entry_types}
    return row, plans, grade


def _force_close(tr: dict, price: float, day: str, costs) -> None:
    """Close any still-open remainder at `price` (end of data)."""
    is_long = tr["direction"] == "long"
    remaining = round(1.0 - tr.get("booked_pct", 0.0), 6)
    if remaining > 1e-9:
        tr["exits"].append({"reason": "eod", "price": round(price, 8), "pct": remaining, "date": day})
        tr["gross_r"] = round(tr.get("gross_r", 0.0) + remaining * _r_of(price, tr["entry"], tr["risk"], is_long), 4)
        tr["booked_pct"] = 1.0
    tr["status"] = "closed"
    tr["exit"] = round(price, 8)
    tr["exit_date"] = day
    tr["exit_reason"] = "target" if tr.get("tp3_hit") else ("trail" if tr.get("tp1_hit") else "eod")
    _apply_costs(tr, costs)


def _manage_bar(tr: dict, high: float, low: float, close: float, day: str, costs, is_last: bool) -> None:
    is_long = tr["direction"] == "long"
    adverse, favourable = (low, high) if is_long else (high, low)
    _mark(tr, adverse, day, costs)                         # stop side first (pessimistic)
    if tr["status"] == "open":
        _mark(tr, favourable, day, costs)                 # then any targets
    if tr["status"] == "open" and is_last:
        _force_close(tr, close, day, costs)


def replay_symbol(df: pd.DataFrame, market: str, symbol: str, name: str, sector: str) -> list[dict]:
    """Walk one symbol's daily history and return its closed backtest trades."""
    if df is None or len(df) < config.VIVEK_MIN_HISTORY + 5:
        return []
    df = df[~df.index.duplicated(keep="last")].sort_index()
    n = len(df)
    idx = df.index
    o, h, l, c = df["Open"].to_numpy(), df["High"].to_numpy(), df["Low"].to_numpy(), df["Close"].to_numpy()
    cand = _candidate_mask(df)
    costs = costs_for(market)

    closed: list[dict] = []
    open_slots = {tf: None for tf in TIMEFRAMES}
    pending: list[tuple] = []                              # (tf, plan, row) → open at next bar's open

    for j in range(config.VIVEK_MIN_HISTORY, n):
        day = idx[j].date().isoformat()
        # 1) open queued entries at THIS bar's open
        for tf, plan, row in pending:
            if open_slots[tf] is None and np.isfinite(o[j]):
                tr = _snapshot(row, tf, plan, market, float(o[j]), day)
                if tr is not None:
                    tr["market"] = market
                    open_slots[tf] = tr
        pending = []

        # 2) manage open trades on this bar (intrabar, stop-first)
        for tf in TIMEFRAMES:
            tr = open_slots[tf]
            if tr is None:
                continue
            _manage_bar(tr, float(h[j]), float(l[j]), float(c[j]), day, costs, is_last=(j == n - 1))
            if tr["status"] == "closed":
                closed.append(tr)
                open_slots[tf] = None

        # 3) detect a new signal at this bar (uses its close), queue for next bar
        if cand[j] and (open_slots["1D"] is None or open_slots["1W"] is None):
            try:
                sig = vivek.evaluate(df.iloc[:j + 1])
            except Exception:
                sig = None
            if sig is not None:
                row, plans, grade = _build_row(sig, df.iloc[:j + 1], symbol, name, sector)
                if row and grade in ("A+", "A"):
                    for tf in TIMEFRAMES:
                        p = plans.get(tf)
                        if p and p.get("armed") and open_slots[tf] is None:
                            pending.append((tf, p, row))
    return closed


# ── aggregation ───────────────────────────────────────────────────────────────

def _dollars(tr: dict) -> float:
    sz = size_position(EQUITY, tr["entry"], tr["stop"])
    return (tr.get("realized_r") or 0.0) * sz["risk_usd"]


def _metrics(trades: list[dict]) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0, "win_rate": 0.0, "avg_r": 0.0, "expectancy_r": 0.0,
                "profit_factor": 0.0, "total_r": 0.0, "total_usd": 0.0, "max_dd_usd": 0.0}
    rs = [t.get("realized_r") or 0.0 for t in trades]
    ds = [_dollars(t) for t in trades]
    wins = [r for r in rs if r > 0]
    gross_win = sum(r for r in rs if r > 0)
    gross_loss = abs(sum(r for r in rs if r < 0))
    # max drawdown on the cumulative $ curve, ordered by exit date
    order = sorted(range(n), key=lambda i: trades[i].get("exit_date") or "")
    cum = peak = dd = 0.0
    for i in order:
        cum += ds[i]; peak = max(peak, cum); dd = min(dd, cum - peak)
    return {
        "n": n,
        "win_rate": round(100 * len(wins) / n, 1),
        "avg_r": round(sum(rs) / n, 3),
        "expectancy_r": round(sum(rs) / n, 3),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else float("inf"),
        "total_r": round(sum(rs), 2),
        "total_usd": round(sum(ds), 2),
        "max_dd_usd": round(dd, 2),
    }


def _split(trades: list[dict], key, values=None) -> dict:
    vals = values or sorted({t.get(key) for t in trades if t.get(key) is not None})
    return {str(v): _metrics([t for t in trades if t.get(key) == v]) for v in vals}


def aggregate(trades: list[dict]) -> dict:
    return {
        "overall": _metrics(trades),
        "by_entry_type": _split(trades, "entry_type", config.VIVEK_TRIGGER_PRIORITY),
        "by_timeframe": _split(trades, "timeframe", list(TIMEFRAMES)),
        "by_market": _split(trades, "market"),
        "by_grade": _split(trades, "grade", ["A+", "A"]),
        "by_direction": _split(trades, "direction", ["long", "short"]),
    }


# ── driver ────────────────────────────────────────────────────────────────────

# Slim trade record stored in the report — enough to recompute every metric and
# to MERGE markets together across separate (streamed) runs.
_SLIM_KEYS = ("symbol", "market", "timeframe", "entry_type", "grade", "direction",
              "entry", "stop", "exit", "exit_date", "exit_reason",
              "realized_r", "gross_r", "cost_r")


def _slim(tr: dict) -> dict:
    return {k: tr.get(k) for k in _SLIM_KEYS}


def run_market_trades(mk: str, limit: int | None, period: str,
                      exclude_funds: bool = True) -> tuple[list[dict], dict]:
    """Backtest ONE market; return (slim trades, coverage entry)."""
    from .universe import load_universe
    from .data import download

    uni = load_universe(mk, full=False)
    if exclude_funds:
        uni = [u for u in uni if not _is_fund_or_reit({"name": u.get("name"), "sector": u.get("sector")})]
    if limit:
        uni = uni[:limit]
    log.info("[%s] downloading %d tickers (%s) ...", mk, len(uni), period)
    frames = download([u["yf"] for u in uni], period=period)
    meta = {u["yf"]: u for u in uni}
    trades: list[dict] = []
    for yf, df in frames.items():
        u = meta.get(yf, {})
        try:
            trades.extend(replay_symbol(df, mk, u.get("symbol", yf), u.get("name", yf), u.get("sector", "")))
        except Exception as e:
            log.warning("[%s] %s replay error: %s", mk, yf, e)
    log.info("[%s] %d trades from %d symbols", mk, len(trades), len(uni))
    return [_slim(t) for t in trades], {"symbols": len(uni), "trades": len(trades)}


def build_report(trades: list[dict], coverage: dict, params: dict, status: str) -> dict:
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,                                  # "partial" while streaming, "complete" when done
        "params": params,
        "coverage": coverage,
        "results": aggregate(trades),
        "trades": trades,
        "caveats": [
            "Survivorship bias — today's universe excludes delisted names.",
            "yfinance daily data (dividend-adjusted); occasional gaps.",
            "Intrabar fills assume the stop fills before the target within a bar.",
            "A+ setups are rare, so trade counts (N) can be small and noisy.",
            "4H is not backtested (no deep intraday history).",
        ],
    }


def run_backtest(markets: list[str], limit: int | None, period: str,
                 exclude_funds: bool = True) -> dict:
    """Backtest several markets in one process (no streaming)."""
    trades, coverage = [], {}
    for mk in markets:
        tr, cov = run_market_trades(mk, limit, period, exclude_funds)
        trades += tr
        coverage[mk] = cov
    params = {"markets": markets, "limit": limit, "period": period,
              "exclude_funds": exclude_funds, "equity": EQUITY,
              "intrabar": "pessimistic (stop-first)", "timeframes": list(TIMEFRAMES)}
    return build_report(trades, coverage, params, "complete")


def _print(report: dict) -> None:
    r = report["results"]
    def line(label, m):
        pf = "∞" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
        print(f"  {label:<14} n={m['n']:<4} win {m['win_rate']:>5}%  "
              f"avgR {m['avg_r']:+.2f}  exp {m['expectancy_r']:+.2f}R  "
              f"PF {pf:<5} totR {m['total_r']:+.1f}  ${m['total_usd']:+.0f}  maxDD ${m['max_dd_usd']:.0f}")
    print("\n=== VIVEK 5.0 BACKTEST ===")
    print("params:", report["params"])
    print("coverage:", report["coverage"])
    print("\nOVERALL"); line("overall", r["overall"])
    for grp in ("by_entry_type", "by_timeframe", "by_market", "by_grade", "by_direction"):
        print(f"\n{grp.upper()}")
        for k, m in r[grp].items():
            if m["n"]:
                line(k, m)


def main() -> None:
    ap = argparse.ArgumentParser(description="VIVEK 5.0 walk-forward backtest")
    ap.add_argument("--market", action="append", choices=[*config.MARKETS, "all"])
    ap.add_argument("--limit", type=int, default=60, help="max symbols per market (0 = all)")
    ap.add_argument("--period", default="10y", help="yfinance history period (e.g. 10y, max)")
    ap.add_argument("--include-funds", action="store_true", help="don't exclude REITs/ETFs/funds")
    ap.add_argument("--merge", action="store_true",
                    help="merge this run's market(s) into the existing results file (streaming)")
    ap.add_argument("--status", choices=["partial", "complete"],
                    help="override the report status (default: auto)")
    ap.add_argument("--out", default=str(OUT_FILE))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    markets = list(config.MARKETS) if (not args.market or "all" in args.market) else args.market
    out = pathlib.Path(args.out)

    # Carry over trades/coverage for OTHER markets from a previous (streamed) run.
    prior_trades, coverage = [], {}
    if args.merge and out.exists():
        try:
            prev = json.loads(out.read_text())
            prior_trades = [t for t in prev.get("trades", []) if t.get("market") not in markets]
            coverage = {k: v for k, v in prev.get("coverage", {}).items() if k not in markets}
        except Exception as e:
            log.warning("could not read prior results (%s) — starting fresh", e)

    new_trades = []
    for mk in markets:
        tr, cov = run_market_trades(mk, args.limit or None, args.period, not args.include_funds)
        new_trades += tr
        coverage[mk] = cov

    trades = prior_trades + new_trades
    done = set(coverage)
    status = args.status or ("complete" if done >= set(config.MARKETS) else "partial")
    params = {"markets": sorted(done), "limit": args.limit or None, "period": args.period,
              "exclude_funds": not args.include_funds, "equity": EQUITY,
              "intrabar": "pessimistic (stop-first)", "timeframes": list(TIMEFRAMES)}
    report = build_report(trades, coverage, params, status)
    _print(report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {out}  (status={status}, markets done: {sorted(done)})")


if __name__ == "__main__":
    main()
