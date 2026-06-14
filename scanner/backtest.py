"""Quick-sanity backtest of the scanner's setups.

It replays the *exact same* signal/level logic over history (reusing
``signals.evaluate`` and ``levels.compute_levels``), simulates each A+/A trade
forward — stop / target / SuperTrend trail, first touch wins — and reports the
result in **R multiples** (profit/loss measured in units of initial risk).

    python -m scanner.backtest                 # curated liquid names, both markets
    python -m scanner.backtest --market asx     # one market
    python -m scanner.backtest --limit 15       # fewer tickers (faster)

IMPORTANT — survivorship bias: the universe is *today's* listed names, so
delisted losers are excluded and these numbers are optimistic. Use them to
compare grades / tune config, not as an absolute expectation. The paper-trade
journal (scanner.journal) is the bias-free, forward-looking version.
"""

import argparse

import numpy as np

from . import config, levels, signals
from .data import download
from .indicators import supertrend
from .universe import load_universe

MAX_HOLD = 60          # bars to hold before timing a trade out
DEFAULT_LIMIT = 20     # "quick sanity" keeps the ticker count small


def _simulate(df, entry_idx, lv, grade, st_arr) -> dict | None:
    close = df["Close"].to_numpy()
    high = df["High"].to_numpy()
    low = df["Low"].to_numpy()
    n = len(df)

    entry = float(close[entry_idx])
    stop = lv["stop"]
    target = lv["target"]
    risk = entry - stop
    if risk <= 0:
        return None

    current_stop = stop
    exit_price, reason, exit_idx = None, None, None
    for j in range(entry_idx + 1, min(entry_idx + 1 + MAX_HOLD, n)):
        st = st_arr[j]
        if np.isfinite(st) and close[j] > st > current_stop:
            current_stop = st            # ratchet the trailing stop upward
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
        "grade": grade,
        "r": (exit_price - entry) / risk,
        "reason": reason,
        "bars": exit_idx - entry_idx,
    }


def backtest_ticker(df) -> list[dict]:
    if df is None or len(df) < config.MIN_HISTORY + 5:
        return []
    st_arr = supertrend(df, config.ATR_PERIOD, config.SUPERTREND_MULT).to_numpy()
    trades: list[dict] = []
    n = len(df)
    i = config.MIN_HISTORY
    while i < n - 1:
        view = df.iloc[: i + 1]
        sig = signals.evaluate(view)
        if sig and sig["uptrend"]:
            _, grade, _ = signals.score_and_grade(sig)
            if grade in config.TRADEABLE_GRADES:
                lv = levels.compute_levels(view, sig)
                if lv["rr"] > 0:
                    trade = _simulate(df, i, lv, grade, st_arr)
                    if trade:
                        trades.append(trade)
                        i = i + max(1, trade["bars"]) + 1   # no overlapping trades
                        continue
        i += 1
    return trades


def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    rs = np.array([t["r"] for t in trades], dtype=float)
    wins = rs[rs > 0]
    losses = rs[rs <= 0]
    cum = np.cumsum(rs)
    peak = np.maximum.accumulate(cum)
    max_dd = float((peak - cum).max()) if len(cum) else 0.0
    gross_win = float(wins.sum())
    gross_loss = float(-losses.sum())
    return {
        "n": len(trades),
        "win_rate": len(wins) / len(rs) * 100,
        "avg_r": float(rs.mean()),
        "expectancy": float(rs.mean()),
        "total_r": float(rs.sum()),
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "max_dd_r": max_dd,
        "best": float(rs.max()),
        "worst": float(rs.min()),
        "avg_bars": float(np.mean([t["bars"] for t in trades])),
    }


def _print_block(title: str, s: dict) -> None:
    if not s.get("n"):
        print(f"  {title:<10} no trades")
        return
    pf = "inf" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}"
    print(f"  {title:<10} trades {s['n']:>4} | win {s['win_rate']:5.1f}% | "
          f"avg {s['avg_r']:+.2f}R | total {s['total_r']:+.1f}R | PF {pf:>4} | "
          f"maxDD {s['max_dd_r']:.1f}R | hold {s['avg_bars']:.0f}d")


def run(market_key: str, limit: int) -> list[dict]:
    market = config.MARKETS[market_key]
    universe = load_universe(market_key, full=False)[:limit]
    tickers = [u["yf"] for u in universe]
    print(f"\n=== {market.label}: backtesting {len(tickers)} liquid names ===", flush=True)
    frames = download(tickers)

    all_trades: list[dict] = []
    for df in frames.values():
        all_trades.extend(backtest_ticker(df))

    by_grade = {g: [t for t in all_trades if t["grade"] == g] for g in ("A+", "A")}
    _print_block("OVERALL", _stats(all_trades))
    _print_block("A+", _stats(by_grade["A+"]))
    _print_block("A", _stats(by_grade["A"]))
    exits = {}
    for t in all_trades:
        exits[t["reason"]] = exits.get(t["reason"], 0) + 1
    if all_trades:
        print(f"  exits: " + ", ".join(f"{k} {v}" for k, v in sorted(exits.items())))
    return all_trades


def main() -> None:
    ap = argparse.ArgumentParser(description="Quick-sanity backtest of the scanner")
    ap.add_argument("--market", action="append", choices=list(config.MARKETS))
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help=f"tickers per market (default {DEFAULT_LIMIT})")
    args = ap.parse_args()

    for mk in (args.market or list(config.MARKETS)):
        run(mk, args.limit)

    print("\nNote: universe = today's listed names, so results are optimistic "
          "(survivorship bias). Use to compare grades / tune, not as a return forecast.\n")


if __name__ == "__main__":
    main()
