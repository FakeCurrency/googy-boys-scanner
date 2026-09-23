"""Throwaway three-lens backtest, one market shard per call (2026-09-23).

Lives only on branch backtest-2026-09-23; never merged. Reads engines, writes
only bt/out/. Every lens is replayed on the SAME downloaded bars:

  vivek     scanner.vivek_backtest.replay_symbol, long only. The real engine
            walked bar by bar (no look-ahead), ARMED A+/A plans on 1D/3D/1W,
            filled at the next open, 5.0 management (25/50/15 + runner, SL to
            break-even at TP1, to TP1 at TP2), stop-first intrabar, fees and
            slippage. Funds/REITs excluded, as the backtest and the bot do.
  phasemap  the harness's SetupEngine + SignalRecorder (no look-ahead),
            bullish tier A+/A. Entry at the signal-bar close. Exit on the
            engine's own events, whichever comes first: T1 consumed (daily
            close through its far edge), DEAD (daily close through the hard
            invalidation floor = the stop), or the engine dropping the setup
            (stall expiry / new sweep). Risk = entry - hard floor. Same fee +
            slippage model, both legs as market fills.
  momentum  screen.evaluate() -- the causal per-bar frame the live screen
            reads its tail from -- long signals only: Rule A (bull RSI
            divergence, what mode A lists) and Rule B (bull scored 20/50
            cross), each its own cohort. The screen's gates are applied to
            the frame AS OF the signal bar. Plan = the Pine template's Auto
            trade box exactly as chart.js momentumPlan ports it (5-bar swing
            low - 0.25 ATR, stop capped at 15% of entry, TP1/2/3 at 1R/2R/3R),
            then the SAME fill + management + costs as vivek, so R compares.

$ per trade at a flat 1,000 of notional: realized_r * 1000 * risk / entry.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import pathlib
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner import config  # noqa: E402
from scanner import conviction  # noqa: E402
from scanner import vivek_backtest as vbt  # noqa: E402
from scanner.broker.vivek_bot import _is_fund_or_reit  # noqa: E402
from scanner.vivek_journal import _snapshot, costs_for  # noqa: E402
from scanner.momentum import gates as mgates  # noqa: E402
from scanner.momentum import screen as mscreen  # noqa: E402
from phasemap.backtest.harness import SignalRecorder  # noqa: E402
from phasemap.engine.indicators import compute_indicators  # noqa: E402
from phasemap.engine.setup_engine import SetupEngine  # noqa: E402
from phasemap.config import CONFIG as PMCFG  # noqa: E402

log = logging.getLogger("bt")
NOTIONAL = 1000.0
# chart.js TV_PLAN, the Pine template's Auto trade box
BOX = {"swing": 5, "atr_pad": 0.25, "max_stop_pct": 15.0, "r": (1.0, 2.0, 3.0)}


def dollars(r: float, risk: float, entry: float) -> float:
    if not (entry and risk) or not math.isfinite(r):
        return 0.0
    return r * NOTIONAL * risk / entry


def drop_forming(df: pd.DataFrame, market: str) -> pd.DataFrame:
    """Never replay a bar that is still forming at run time."""
    if df is None or not len(df):
        return df
    last = df.index[-1].date()
    now = dt.datetime.now(dt.timezone.utc)
    sess = config.VIVEK_JOURNAL_SESSION.get(market)
    if sess is None:
        return df.iloc[:-1] if last >= now.date() else df
    local = now.astimezone(ZoneInfo(config.MARKETS[market].timezone))
    settled = local.replace(hour=sess[2], minute=sess[3], second=0, microsecond=0) + dt.timedelta(minutes=30)
    if last >= local.date() and local < settled:
        return df.iloc[:-1]
    return df


# ── vivek ────────────────────────────────────────────────────────────────────

def run_vivek(df, market, u):
    if _is_fund_or_reit({"name": u.get("name"), "sector": u.get("sector")}):
        return []
    out = []
    for tr in vbt.replay_symbol(df, market, u["symbol"], u.get("name", ""), u.get("sector", ""),
                                long_only=True):
        if tr.get("direction") != "long":
            continue
        r = float(tr.get("realized_r") or 0.0)
        out.append({
            "lens": "vivek", "market": market, "symbol": u["symbol"],
            "cohort": tr.get("grade"), "timeframe": tr.get("timeframe"),
            "entry_type": tr.get("entry_type"), "level_tf": tr.get("level_tf"),
            "hc_cell": conviction.trade_cell(tr),
            "entry_date": tr.get("entry_date"), "exit_date": tr.get("exit_date"),
            "exit_reason": tr.get("exit_reason"),
            "entry": tr.get("entry"), "risk": tr.get("risk"),
            "r": round(r, 4), "gross_r": tr.get("gross_r"), "cost_r": tr.get("cost_r"),
            "usd": round(dollars(r, float(tr["risk"]), float(tr["entry"])), 2),
        })
    return out


# ── momentum ─────────────────────────────────────────────────────────────────

def _box(ev, j):
    c = float(ev["close"].iat[j])
    lo = float(ev["low"].iloc[max(0, j - BOX["swing"] + 1): j + 1].min())
    a = float(ev["atr"].iat[j])
    a = a if math.isfinite(a) else 0.0
    stop = lo - a * BOX["atr_pad"]
    stop = max(stop, c - c * BOX["max_stop_pct"] / 100.0)
    risk = c - stop
    if not (math.isfinite(risk) and risk > 0):
        return None
    tps = [max(c + risk * r, c * 0.05) for r in BOX["r"]]
    return {"entry": c, "stop": stop, "tp1": tps[0], "tp2": tps[1], "tp3": tps[2],
            "scale": list(config.VIVEK_TP_SCALE_LONG)}


def run_momentum(df, market, u):
    ev = mscreen.evaluate(df)
    n = len(ev)
    if n < 2:
        return [], {}
    costs = costs_for(market)
    o, h, l, c = (ev[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    days = [d.date().isoformat() for d in ev.index]
    bar_cols = [k for k in ("open", "high", "low", "close", "volume") if k in ev.columns]
    out, gated = [], {}
    for rule, col in (("A", "bull_div"), ("B", "bull_signal")):
        sig = ev[col].to_numpy(dtype=bool)
        open_tr, pending = None, None
        for j in range(n):
            if pending is not None and open_tr is None and np.isfinite(o[j]):
                plan, row = pending
                tr = _snapshot(row, "1D", plan, market, float(o[j]), days[j])
                if tr is not None:
                    tr["signal_date"] = plan["signal_date"]
                    open_tr = tr
            pending = None
            if open_tr is not None:
                vbt._manage_bar(open_tr, float(h[j]), float(l[j]), float(c[j]), days[j], costs,
                                is_last=(j == n - 1))
                if open_tr["status"] == "closed":
                    r = float(open_tr.get("realized_r") or 0.0)
                    out.append({
                        "lens": "momentum", "market": market, "symbol": u["symbol"],
                        "cohort": f"Rule {rule}", "timeframe": "1D",
                        "signal_date": open_tr.get("signal_date"),
                        "entry_date": open_tr.get("entry_date"), "exit_date": open_tr.get("exit_date"),
                        "exit_reason": open_tr.get("exit_reason"),
                        "entry": open_tr.get("entry"), "risk": open_tr.get("risk"),
                        "r": round(r, 4), "gross_r": open_tr.get("gross_r"),
                        "cost_r": open_tr.get("cost_r"),
                        "usd": round(dollars(r, float(open_tr["risk"]), float(open_tr["entry"])), 2),
                    })
                    open_tr = None
            if open_tr is None and sig[j] and j + 1 < n:
                # gate on evaluate()'s own rows: prepare_frame drops NaN
                # bars, so a raw-frame index would point at a different day
                reason = mgates.gate_frame(ev.iloc[: j + 1][bar_cols], market,
                                           name=u.get("name"), sector=u.get("sector"))
                if reason is not None:
                    key = reason.split(" ")[0]
                    gated[key] = gated.get(key, 0) + 1
                    continue
                plan = _box(ev, j)
                if plan is None:
                    continue
                plan["signal_date"] = days[j]
                plan["entry_trigger"] = f"rule_{rule.lower()}"
                row = {"symbol": u["symbol"], "name": u.get("name", ""), "sector": u.get("sector", ""),
                       "dir": "LONG", "grade": f"Rule {rule}", "entry_types": [plan["entry_trigger"]]}
                pending = (plan, row)
    return out, gated


# ── phasemap ─────────────────────────────────────────────────────────────────

class _Rec(SignalRecorder):
    def _capture(self, i, eng):
        d = super()._capture(i, eng)
        inv = eng.inv_hard
        d["inv_low"] = float(inv.low) if inv is not None else float("nan")
        return d


def run_phasemap(df, market, u):
    pm = df.reset_index()
    pm = pm.rename(columns={pm.columns[0]: "Date"})
    pm = pm.dropna(subset=["Open", "High", "Low", "Close"])
    pm = pm[(pm[["Open", "High", "Low", "Close"]] > 0).all(axis=1)].reset_index(drop=True)
    if len(pm) < PMCFG.min_history_bars:
        return []
    ind = compute_indicators(pm, volume_is_usd=(market == "crypto"))
    rec = _Rec(u["symbol"], ind, market)
    SetupEngine(ind=ind, bull=True, market=market, recorder=rec).process()
    slip, comm = costs_for(market) or (0.0, 0.0)
    close = ind.close
    n = len(close)
    out = []
    for s in rec.signals:
        if s["tier"] not in ("A+", "A") or s["direction"] != "bullish":
            continue
        i = s["signal_index"]
        entry, stop = float(close[i]), float(s.get("inv_low", float("nan")))
        risk = entry - stop
        if not (math.isfinite(risk) and risk > 0 and entry > 0):
            continue
        events = [(b, why) for b, why in ((s.get("dead_bar"), "stop"),
                                          (s.get("t1_consumed_bar"), "t1"),
                                          (s.get("end_index"), "engine_end"))
                  if b is not None and b > i]
        if events:
            b, why = min(events)
        else:
            b, why = n - 1, "eod"
            if b <= i:
                continue
        exit_px = float(close[b])
        gross = (exit_px - entry) / risk
        cost_r = 2.0 * (slip + comm) * entry / risk
        r = gross - cost_r
        out.append({
            "lens": "phasemap", "market": market, "symbol": u["symbol"],
            "cohort": s["tier"], "timeframe": "1D", "illiquid": s.get("illiquid"),
            "entry_date": s["signal_date"], "exit_date": ind.dates[b].isoformat(),
            "exit_reason": why, "entry": round(entry, 10), "risk": round(risk, 10),
            "r": round(r, 4), "gross_r": round(gross, 4), "cost_r": round(cost_r, 4),
            "usd": round(dollars(r, risk, entry), 2),
        })
    return out


# ── driver ───────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=list(config.MARKETS))
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--of", type=int, default=1)
    ap.add_argument("--period", default="5y")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0, help="first N shard symbols (smoke)")
    ap.add_argument("--frames-dir", default=None, help="local bars instead of Yahoo (smoke)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    t0 = time.time()

    from scanner.universe import load_universe
    uni = sorted(load_universe(a.market, full=True), key=lambda u: u["yf"])
    mine = uni[a.shard::a.of]
    if a.limit:
        mine = mine[: a.limit]
    by_yf = {u["yf"]: u for u in mine}

    if a.frames_dir:
        frames = {}
        for u in mine:
            p = pathlib.Path(a.frames_dir) / f"{u['symbol']}.json"
            if not p.exists():
                continue
            bars = json.loads(p.read_text())["bars"]
            f = pd.DataFrame(bars, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
            f.index = pd.to_datetime(f.pop("Date"))
            frames[u["yf"]] = f
    else:
        from scanner.data import download
        frames = download(list(by_yf), period=a.period)

    trades, errors, gated = [], {}, {}
    for yf, df in sorted(frames.items()):
        u = by_yf.get(yf)
        if u is None or df is None or not len(df):
            continue
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = drop_forming(df, a.market)
        for lens, fn in (("vivek", run_vivek), ("phasemap", run_phasemap), ("momentum", run_momentum)):
            try:
                got = fn(df, a.market, u)
                if lens == "momentum":
                    got, g = got
                    for k, v in g.items():
                        gated[k] = gated.get(k, 0) + v
                trades.extend(got)
            except Exception as e:  # one name must not sink the shard
                errors[lens] = errors.get(lens, 0) + 1
                log.warning("%s %s %s: %s", lens, a.market, yf, e)

    doc = {
        "market": a.market, "shard": a.shard, "of": a.of, "period": a.period,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "universe": len(uni), "shard_symbols": len(mine), "downloaded": len(frames),
        "errors": errors, "momentum_gated": gated,
        "elapsed_s": round(time.time() - t0, 1), "trades": trades,
    }
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    by = {}
    for t in trades:
        by[t["lens"]] = by.get(t["lens"], 0) + 1
    print(f"bt {a.market} shard {a.shard}/{a.of}: {len(frames)}/{len(mine)} downloaded, "
          f"trades {by}, errors {errors}, {doc['elapsed_s']}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
