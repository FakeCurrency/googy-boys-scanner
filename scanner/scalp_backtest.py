"""Out-of-sample backtest for the Scalp engine.

Replays the scalp signal engine over historical 1H bars and trades every A+/A
setup using the EXACT same pessimistic fill model as the live paper journal:

  • Entry  = OPEN of the next 1H bar after the signal + slippage (never the
    signal-bar close).
  • Stop / target fill at the level intrabar; a bar that OPENS beyond a level
    fills at the bar open (gap-through), so gaps cost you on stops and gift you
    on targets — just like the live journal.
  • $40 round-trip brokerage + 0.03% slippage each way on a $5,000 notional.

It then reports the metrics that actually matter before risking capital:
win rate, profit factor, max drawdown, expectancy (R and $), and a per-grade
breakdown — so the backtest and the live forward test can be compared directly.

    python -m scanner.scalp_backtest                 # full universe, default window
    python -m scanner.scalp_backtest --months 12     # 12 months of 1H history
    python -m scanner.scalp_backtest --symbol GOLD   # one instrument

Writes public/data/scalp_backtest.json for the site and prints a console report.
Note: yfinance caps 1H history at ~730 days; --months is clamped accordingly.
"""

import argparse
import datetime as dt
import json
import pathlib

import numpy as np
import pandas as pd

from . import config, scalp
from .data import download
from .universe import load_scalp_universe

ROOT          = pathlib.Path(__file__).resolve().parents[1]
PUBLIC_OUT    = ROOT / "public" / "data" / "scalp_backtest.json"

NOTIONAL = config.SCALP_POSITION_SIZE * config.SCALP_LEVERAGE   # $5,000
BROK_RT  = config.SCALP_BROKERAGE_EACH_WAY * 2                  # $40
SLIP     = config.SCALP_FILL_SLIPPAGE_PCT                       # 0.03% one-way

# Don't let a single trade run forever — abandon (close at market) after this many
# 1H bars without hitting stop or target. Keeps the test honest about dead trades.
MAX_HOLD_BARS = 48   # ~ two trading days of 1H bars


def _simulate_one(df: pd.DataFrame, direction: str) -> list[dict]:
    """Walk one instrument's 1H history; return a list of closed paper-trades.

    Re-evaluates the scalp engine at each bar using only data up to and including
    that bar (no look-ahead). Opens at most one position at a time per direction.
    """
    if df is None or len(df) < scalp.SCALP_MIN_BARS + 5:
        return []

    if getattr(df.index, "tz", None) is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)

    opens = df["Open"].to_numpy(dtype=float)
    highs = df["High"].to_numpy(dtype=float)
    lows  = df["Low"].to_numpy(dtype=float)
    ts    = [t.isoformat() for t in df.index]
    n     = len(df)

    trades: list[dict] = []
    i = scalp.SCALP_MIN_BARS
    while i < n - 1:
        window = df.iloc[: i + 1]                     # data through bar i (the signal bar)
        sig = scalp.evaluate(window, direction=direction)
        if sig is None:
            i += 1
            continue
        points, grade, _ = scalp.score_and_grade(sig)
        if grade not in ("A+", "A"):
            i += 1
            continue
        lv = scalp.compute_levels(window, sig)
        if lv["rr"] <= 0:
            i += 1
            continue

        stop, target = lv["stop"], lv["target"]

        # ── Pessimistic entry: open of the NEXT bar + slippage ───────────────
        fill_bar = i + 1
        raw_open = opens[fill_bar]
        entry = raw_open * (1 + SLIP) if direction == "long" else raw_open * (1 - SLIP)
        risk  = (entry - stop) if direction == "long" else (stop - entry)
        if risk <= 0:
            i += 1
            continue
        units = int(NOTIONAL / entry) if entry > 0 else 0
        if units == 0:
            i += 1
            continue

        # Gapped straight through the stop on the fill bar → immediate stop-out
        gapped = (direction == "long" and entry <= stop) or (direction == "short" and entry >= stop)
        if gapped:
            trades.append(_record(direction, grade, entry, raw_open, stop, units,
                                   ts[fill_bar], "stop-gap", 0, risk))
            i = fill_bar + 1
            continue

        # ── Walk forward from the bar after entry ────────────────────────────
        exit_px = exit_ts = reason = None
        bars = 0
        for k in range(fill_bar + 1, min(n, fill_bar + 1 + MAX_HOLD_BARS)):
            bars = k - fill_bar
            if direction == "long":
                if opens[k] <= stop:
                    exit_px, reason = opens[k], "stop-gap"; exit_ts = ts[k]; break
                if opens[k] >= target:
                    exit_px, reason = opens[k], "target-gap"; exit_ts = ts[k]; break
                if lows[k] <= stop:
                    exit_px, reason = stop, "stop"; exit_ts = ts[k]; break
                if highs[k] >= target:
                    exit_px, reason = target, "target"; exit_ts = ts[k]; break
            else:
                if opens[k] >= stop:
                    exit_px, reason = opens[k], "stop-gap"; exit_ts = ts[k]; break
                if opens[k] <= target:
                    exit_px, reason = opens[k], "target-gap"; exit_ts = ts[k]; break
                if highs[k] >= stop:
                    exit_px, reason = stop, "stop"; exit_ts = ts[k]; break
                if lows[k] <= target:
                    exit_px, reason = target, "target"; exit_ts = ts[k]; break

        if exit_px is None:
            # Timed out — close at the last bar's close (market exit)
            last = min(n - 1, fill_bar + MAX_HOLD_BARS)
            exit_px, reason, exit_ts = df["Close"].iloc[last], "timeout", ts[last]
            bars = last - fill_bar

        trades.append(_record(direction, grade, entry, exit_px, stop, units,
                               exit_ts, reason, bars, risk))
        # No overlapping positions per direction: resume after the exit bar
        i = fill_bar + bars + 1

    return trades


def _record(direction, grade, entry, raw_exit, stop, units, exit_ts, reason, bars, risk) -> dict:
    """Apply exit slippage + brokerage and compute R and $ P&L for one trade."""
    exit_px = raw_exit * (1 - SLIP) if direction == "long" else raw_exit * (1 + SLIP)
    if direction == "long":
        r   = (exit_px - entry) / risk if risk > 0 else 0.0
        pnl = units * (exit_px - entry) - BROK_RT
    else:
        r   = (entry - exit_px) / risk if risk > 0 else 0.0
        pnl = units * (entry - exit_px) - BROK_RT
    return {
        "direction": direction, "grade": grade,
        "entry": round(float(entry), 6), "exit": round(float(exit_px), 6),
        "units": units, "reason": reason, "bars": bars,
        "r": round(float(r), 3), "pnl": round(float(pnl), 2), "exit_ts": exit_ts,
    }


def _metrics(trades: list[dict]) -> dict:
    """Win rate, profit factor, max drawdown, expectancy — the real-money KPIs."""
    if not trades:
        return {"trades": 0}
    rs   = np.array([t["r"]   for t in trades], dtype=float)
    pnls = np.array([t["pnl"] for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    loss = pnls[pnls < 0]

    gross_win  = float(wins.sum())
    gross_loss = float(abs(loss.sum()))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else None

    # Max drawdown on the cumulative $ equity curve
    equity = np.cumsum(pnls)
    peak   = np.maximum.accumulate(equity)
    max_dd = float((peak - equity).max()) if len(equity) else 0.0

    return {
        "trades":         len(trades),
        "win_rate":       round(len(wins) / len(trades) * 100, 1),
        "wins":           int(len(wins)),
        "losses":         int(len(loss)),
        "profit_factor":  profit_factor,
        "expectancy_r":   round(float(rs.mean()), 3),
        "expectancy_pnl": round(float(pnls.mean()), 2),
        "total_pnl":      round(float(pnls.sum()), 2),
        "total_r":        round(float(rs.sum()), 2),
        "avg_win":        round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss":       round(float(loss.mean()), 2) if len(loss) else 0.0,
        "max_drawdown":   round(max_dd, 2),
        "avg_hold_bars":  round(float(np.mean([t["bars"] for t in trades])), 1),
    }


def run(months: int = 12, symbol: str | None = None, progress: bool = True) -> dict:
    universe = load_scalp_universe()
    if symbol:
        universe = [u for u in universe if u["symbol"] == symbol.upper()]
        if not universe:
            raise SystemExit(f"Unknown scalp symbol: {symbol}")

    # yfinance 1H history is capped at ~730 days
    days   = min(int(months * 30.4), 720)
    period = f"{days}d"
    tickers = [u["yf"] for u in universe]
    meta    = {u["yf"]: u for u in universe}

    if progress:
        print(f"Scalp backtest — {len(tickers)} instruments, {days}d of 1H bars "
              f"(pessimistic fills, ${NOTIONAL:,.0f} notional, ${BROK_RT} RT) ...", flush=True)
    frames = download(tickers, period=period, interval="1h", chunk=30)

    all_trades: list[dict] = []
    per_symbol: list[dict] = []
    for yf_ticker, df in frames.items():
        info = meta.get(yf_ticker, {})
        sym_trades: list[dict] = []
        for direction in ("long", "short"):
            sym_trades += _simulate_one(df, direction)
        for t in sym_trades:
            t["symbol"] = info.get("symbol", yf_ticker)
        all_trades += sym_trades
        if sym_trades:
            m = _metrics(sym_trades)
            per_symbol.append({
                "symbol": info.get("symbol", yf_ticker),
                "sector": info.get("sector", ""),
                "trades": m["trades"], "win_rate": m["win_rate"],
                "total_pnl": m["total_pnl"], "profit_factor": m["profit_factor"],
            })

    all_trades.sort(key=lambda t: t.get("exit_ts", ""))
    per_symbol.sort(key=lambda s: s["total_pnl"], reverse=True)

    by_grade = {
        g: _metrics([t for t in all_trades if t["grade"] == g])
        for g in ("A+", "A")
    }
    by_dir = {
        d: _metrics([t for t in all_trades if t["direction"] == d])
        for d in ("long", "short")
    }

    # Date span actually covered
    span = ""
    if all_trades:
        span = f"{all_trades[0]['exit_ts'][:10]} → {all_trades[-1]['exit_ts'][:10]}"

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "window_days":  days,
        "span":         span,
        "notional":     NOTIONAL,
        "brokerage_rt": BROK_RT,
        "slippage_pct": SLIP,
        "max_hold_bars": MAX_HOLD_BARS,
        "instruments":  len(frames),
        "overall":      _metrics(all_trades),
        "by_grade":     by_grade,
        "by_direction": by_dir,
        "per_symbol":   per_symbol[:60],
        "equity":       _equity_curve(all_trades),
        "recent":       all_trades[-100:],
    }


def _equity_curve(trades: list[dict]) -> list[dict]:
    """Cumulative $ equity, sampled for the UI (max ~300 points)."""
    if not trades:
        return []
    cum, pts = 0.0, []
    for t in trades:
        cum += t["pnl"]
        pts.append(round(cum, 2))
    step = max(1, len(pts) // 300)
    return pts[::step]


def _print_report(res: dict) -> None:
    o = res["overall"]
    print("\n" + "=" * 64)
    print(f"  SCALP BACKTEST  ·  {res['instruments']} instruments  ·  {res['span'] or 'no trades'}")
    print("=" * 64)
    if not o.get("trades"):
        print("  No qualifying A+/A setups in the window.")
        return
    pf = o["profit_factor"]
    print(f"  Trades            {o['trades']}")
    print(f"  Win rate          {o['win_rate']}%   ({o['wins']}W / {o['losses']}L)")
    print(f"  Profit factor     {pf if pf is not None else '∞'}")
    print(f"  Expectancy        {o['expectancy_r']:+.3f}R   (${o['expectancy_pnl']:+.2f}/trade)")
    print(f"  Total P&L         ${o['total_pnl']:+,.2f}   ({o['total_r']:+.1f}R)")
    print(f"  Avg win / loss    ${o['avg_win']:+,.2f} / ${o['avg_loss']:+,.2f}")
    print(f"  Max drawdown      ${o['max_drawdown']:,.2f}")
    print(f"  Avg hold          {o['avg_hold_bars']} bars (1H)")
    print("-" * 64)
    for g in ("A+", "A"):
        m = res["by_grade"][g]
        if m.get("trades"):
            print(f"  {g:<3} {m['trades']:>4} trades · win {m['win_rate']:>5}% · "
                  f"PF {m['profit_factor']} · exp {m['expectancy_r']:+.3f}R · ${m['total_pnl']:+,.0f}")
    for d in ("long", "short"):
        m = res["by_direction"][d]
        if m.get("trades"):
            print(f"  {d:<5} {m['trades']:>4} trades · win {m['win_rate']:>5}% · "
                  f"PF {m['profit_factor']} · exp {m['expectancy_r']:+.3f}R · ${m['total_pnl']:+,.0f}")
    print("=" * 64 + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Out-of-sample scalp backtest (pessimistic fills)")
    ap.add_argument("--months", type=int, default=12, help="months of 1H history (clamped to ~24)")
    ap.add_argument("--symbol", default=None, help="backtest a single scalp symbol")
    ap.add_argument("--no-write", action="store_true", help="don't write public/data/scalp_backtest.json")
    args = ap.parse_args()

    res = run(months=args.months, symbol=args.symbol)
    _print_report(res)
    if not args.no_write:
        PUBLIC_OUT.parent.mkdir(parents=True, exist_ok=True)
        PUBLIC_OUT.write_text(json.dumps(res, indent=2), encoding="utf-8")
        print(f"Wrote {PUBLIC_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
