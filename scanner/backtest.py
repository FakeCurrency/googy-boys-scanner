"""Backtest of the scanner's setups — signal stats + a realistic portfolio sim.

It replays the *exact same* signal/level logic over history (reusing
``signals.evaluate`` and ``levels.compute_levels``), simulates each A+/A trade
forward (stop / target / SuperTrend trail, first touch wins), then runs an
event-driven **portfolio** simulation with a real account size, fixed dollar
position size and per-transaction brokerage.

    python -m scanner.backtest                       # default account model
    python -m scanner.backtest --account 10000 --size 500 --brokerage 10 --min-rr 1.5
    python -m scanner.backtest --market asx --limit 200

IMPORTANT — survivorship bias: the universe is *today's* listed names, so
results are optimistic. Use to compare grades / tune, not as a return forecast.
"""

import argparse

import numpy as np

from . import config, levels, signals
from .data import download
from .indicators import supertrend
from .universe import load_universe

MAX_HOLD = 60
DEFAULT_LIMIT = 20


def _simulate(df, entry_idx, lv, grade, st_arr) -> dict | None:
    close = df["Close"].to_numpy()
    high = df["High"].to_numpy()
    low = df["Low"].to_numpy()
    n = len(df)

    entry = float(close[entry_idx])
    stop, target = lv["stop"], lv["target"]
    risk = entry - stop
    if risk <= 0:
        return None

    current_stop = stop
    exit_price, reason, exit_idx = None, None, None
    for j in range(entry_idx + 1, min(entry_idx + 1 + MAX_HOLD, n)):
        st = st_arr[j]
        if np.isfinite(st) and close[j] > st > current_stop:
            current_stop = st
        if low[j] <= current_stop:
            exit_price = current_stop
            reason = "trail" if current_stop > stop else "stop"
            exit_idx = j
            break
        if high[j] >= target:
            exit_price, reason, exit_idx = target, "target", j
            break
    if exit_price is None:
        exit_idx = min(entry_idx + MAX_HOLD, n - 1)
        exit_price, reason = float(close[exit_idx]), "timeout"

    return {
        "grade": grade, "reason": reason, "bars": exit_idx - entry_idx,
        "r": (exit_price - entry) / risk, "planned_rr": lv["rr"],
        "entry": entry, "exit": float(exit_price),
        "entry_date": df.index[entry_idx].date().isoformat(),
        "exit_date": df.index[exit_idx].date().isoformat(),
    }


def backtest_ticker(symbol: str, df) -> list[dict]:
    if df is None or len(df) < config.MIN_HISTORY + 5:
        return []
    st_arr = supertrend(df, config.ATR_PERIOD, config.SUPERTREND_MULT).to_numpy()
    trades, n, i = [], len(df), config.MIN_HISTORY
    while i < n - 1:
        view = df.iloc[: i + 1]
        sig = signals.evaluate(view)
        if sig and sig["uptrend"]:
            _, grade, _ = signals.score_and_grade(sig)
            if grade in config.TRADEABLE_GRADES:
                lv = levels.compute_levels(view, sig)
                if lv["rr"] > 0:
                    t = _simulate(df, i, lv, grade, st_arr)
                    if t:
                        t["symbol"] = symbol
                        trades.append(t)
                        i = i + max(1, t["bars"]) + 1
                        continue
        i += 1
    return trades


# --------------------------------------------------------------- signal stats
def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    rs = np.array([t["r"] for t in trades])
    wins = rs[rs > 0]
    cum = np.cumsum(rs)
    max_dd = float((np.maximum.accumulate(cum) - cum).max()) if len(cum) else 0.0
    gl = float(-rs[rs <= 0].sum())
    return {"n": len(rs), "win_rate": len(wins) / len(rs) * 100, "avg_r": float(rs.mean()),
            "total_r": float(rs.sum()), "pf": (float(wins.sum()) / gl) if gl else float("inf"),
            "max_dd_r": max_dd, "avg_bars": float(np.mean([t["bars"] for t in trades]))}


def _print_block(title: str, s: dict) -> None:
    if not s.get("n"):
        print(f"  {title:<10} no trades"); return
    pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    print(f"  {title:<10} trades {s['n']:>5} | win {s['win_rate']:5.1f}% | avg {s['avg_r']:+.2f}R | "
          f"total {s['total_r']:+.1f}R | PF {pf:>4} | maxDD {s['max_dd_r']:.1f}R")


# ------------------------------------------------------------- portfolio sim
def portfolio_sim(trades, account=10000.0, size=500.0, brokerage=10.0, min_rr=None) -> dict:
    """Event-driven account simulation with fixed $ position size + brokerage."""
    elig = [t for t in trades if (min_rr is None or t["planned_rr"] >= min_rr)]
    cap = max(1, int(account // size))   # max concurrent positions

    # open events (type 1) processed after close events (type 0) on the same day.
    events = []
    for i, t in enumerate(elig):
        events.append((t["entry_date"], 1, i))
        events.append((t["exit_date"], 0, i))
    events.sort(key=lambda e: (e[0], e[1]))

    cash, shares_of, taken = account, {}, set()
    realized, brokerage_paid, ntaken, wins = 0.0, 0.0, 0, 0
    peak, max_dd = account, 0.0

    for date, etype, idx in events:
        t = elig[idx]
        if etype == 0:                       # close
            if idx in taken:
                sh = shares_of.pop(idx)
                cash += sh * t["exit"] - brokerage
                brokerage_paid += brokerage
                pnl = sh * (t["exit"] - t["entry"]) - 2 * brokerage
                realized += pnl
                wins += 1 if pnl > 0 else 0
                equity = account + realized
                peak = max(peak, equity)
                max_dd = max(max_dd, peak - equity)
        else:                                # open
            if len(shares_of) < cap and cash >= size + brokerage:
                sh = size / t["entry"]
                cash -= sh * t["entry"] + brokerage
                brokerage_paid += brokerage
                shares_of[idx] = sh
                taken.add(idx)
                ntaken += 1

    final = account + realized
    return {
        "eligible": len(elig), "taken": ntaken, "skipped": len(elig) - ntaken,
        "final": final, "return_pct": (final / account - 1) * 100,
        "win_rate": (wins / ntaken * 100) if ntaken else 0.0,
        "brokerage": brokerage_paid, "max_dd": max_dd, "cap": cap,
    }


def _print_pf(title: str, p: dict) -> None:
    print(f"  {title:<26} final ${p['final']:>10,.0f}  ({p['return_pct']:+6.1f}%)  | "
          f"trades {p['taken']:>4} | win {p['win_rate']:4.1f}% | "
          f"brokerage ${p['brokerage']:>8,.0f} | maxDD ${p['max_dd']:,.0f}")


def run(market_key: str, limit: int, full: bool = False) -> list[dict]:
    market = config.MARKETS[market_key]
    universe = load_universe(market_key, full=full)[:limit]
    sym_of = {u["yf"]: u["symbol"] for u in universe}
    print(f"\n=== {market.label}: backtesting {len(universe)} names ===", flush=True)
    frames = download([u["yf"] for u in universe])

    trades = []
    for yf_t, df in frames.items():
        trades.extend(backtest_ticker(sym_of.get(yf_t, yf_t), df))

    _print_block("OVERALL", _stats(trades))
    _print_block("A+", _stats([t for t in trades if t["grade"] == "A+"]))
    _print_block("A", _stats([t for t in trades if t["grade"] == "A"]))
    return trades


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest + portfolio simulation")
    ap.add_argument("--market", action="append", choices=list(config.MARKETS))
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--full", action="store_true", help="full ASX directory instead of curated")
    ap.add_argument("--account", type=float, default=10000)
    ap.add_argument("--size", type=float, default=500)
    ap.add_argument("--brokerage", type=float, default=10)
    ap.add_argument("--min-rr", type=float, default=1.5)
    args = ap.parse_args()

    all_trades = []
    for mk in (args.market or list(config.MARKETS)):
        all_trades.extend(run(mk, args.limit, full=args.full))

    a, s, b, m = args.account, args.size, args.brokerage, args.min_rr
    print(f"\n=== PORTFOLIO: ${a:,.0f} account · ${s:,.0f}/trade · ${b:,.0f}/transaction "
          f"(max {int(a//s)} positions) ===")
    _print_pf(f"tuned (R:R>={m}) + costs", portfolio_sim(all_trades, a, s, b, min_rr=m))
    _print_pf(f"tuned (R:R>={m}) NO costs", portfolio_sim(all_trades, a, s, 0, min_rr=m))
    _print_pf("all A+/A + costs", portfolio_sim(all_trades, a, s, b, min_rr=None))
    _print_pf("all A+/A NO costs", portfolio_sim(all_trades, a, s, 0, min_rr=None))
    _print_pf(f"tuned + $2,500/trade", portfolio_sim(all_trades, a, 2500, b, min_rr=m))

    print("\nNote: survivorship-biased (today's listed names) => optimistic. "
          "Brokerage is charged per side (open + close).\n")


if __name__ == "__main__":
    main()
