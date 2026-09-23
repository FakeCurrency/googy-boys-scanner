"""Throwaway four-lens backtest, v2 (2026-09-23) -- scored by the PERMANENT
R models from branch lens-rmodels-2026-09-23, one market shard per call.

Lives only on branch backtest-2026-09-23; never merged. Every lens replays the
SAME downloaded bars:
  vivek     scanner.vivek_backtest.replay_symbol, long only (unchanged: the
            5.0 evidence engine, stops filled at the bar's extreme)
  phasemap  phasemap.backtest.harness.run_ticker, now scoring each signal via
            phasemap/backtest/rmodel.py (engine-native exits, house costs,
            house minimum stop)
  momentum  scanner.momentum.backtest.replay_symbol (the screen's own
            signals incl. Rule B's live score gate, the Pine box, the 5.0
            ladder through scanner/rmodel.py, resting-stop fills)
  specs     scanner.spec_backtest.replay_ticker (asx + nasdaq), scored by its
            r_trade (engine plan, one target, 40-bar time stop)
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

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner import config  # noqa: E402
from scanner import conviction  # noqa: E402
from scanner import spec_backtest as sbt  # noqa: E402
from scanner import vivek_backtest as vbt  # noqa: E402
from scanner.broker.vivek_bot import _is_fund_or_reit  # noqa: E402
from scanner.momentum import backtest as mbt  # noqa: E402
from phasemap.backtest.harness import run_ticker  # noqa: E402

log = logging.getLogger("bt")
NOTIONAL = float(config.LENS_BACKTEST_NOTIONAL)


def dollars(r, risk, entry):
    if not (entry and risk) or r is None or not math.isfinite(r):
        return 0.0
    return round(r * NOTIONAL * risk / entry, 2)


def drop_forming(df, market):
    if df is None or not len(df):
        return df
    last = df.index[-1].date()
    now = dt.datetime.now(dt.timezone.utc)
    sess = config.VIVEK_JOURNAL_SESSION.get(market)
    if sess is None:
        return df.iloc[:-1] if last >= now.date() else df
    local = now.astimezone(ZoneInfo(config.MARKETS[market].timezone))
    settled = local.replace(hour=sess[2], minute=sess[3], second=0, microsecond=0) + dt.timedelta(minutes=30)
    return df.iloc[:-1] if (last >= local.date() and local < settled) else df


def run_vivek(df, market, u):
    if _is_fund_or_reit({"name": u.get("name"), "sector": u.get("sector")}):
        return []
    out = []
    for tr in vbt.replay_symbol(df, market, u["symbol"], u.get("name", ""), u.get("sector", ""),
                                long_only=True):
        r = float(tr.get("realized_r") or 0.0)
        out.append({"lens": "vivek", "market": market, "symbol": u["symbol"], "direction": "long",
                    "cohort": tr.get("grade"), "timeframe": tr.get("timeframe"),
                    "hc_cell": conviction.trade_cell(tr), "entry_date": tr.get("entry_date"),
                    "exit_reason": tr.get("exit_reason"), "entry": tr.get("entry"),
                    "risk": tr.get("risk"), "r": round(r, 4),
                    "usd": dollars(r, float(tr["risk"]), float(tr["entry"]))})
    return out


def run_phasemap(df, market, u):
    pm = df.reset_index()
    pm = pm.rename(columns={pm.columns[0]: "Date"})
    out = []
    for s in run_ticker(u["symbol"], pm, market, volume_is_usd=(market == "crypto")):
        if s["tier"] not in ("A+", "A") or not s.get("r_tradeable"):
            continue
        out.append({"lens": "phasemap", "market": market, "symbol": u["symbol"],
                    "direction": "long" if s["direction"] == "bullish" else "short",
                    "cohort": s["tier"], "illiquid": s.get("illiquid"),
                    "entry_date": s["signal_date"], "exit_reason": s["r_exit_reason"],
                    "entry": s["r_entry"], "risk": s["r_risk"], "r": s["realized_r"],
                    "usd": dollars(s["realized_r"], s["r_risk"], s["r_entry"])})
    return out


def run_momentum(df, market, u):
    trades, gated = mbt.replay_symbol(df, market, symbol=u["symbol"], name=u.get("name"),
                                      sector=u.get("sector"))
    out = [{"lens": "momentum", "market": market, "symbol": u["symbol"], "direction": t["direction"],
            "cohort": f"Rule {t['rule']}", "entry_date": t["signal_date"],
            "exit_reason": t["exit_reason"], "closed_by": t.get("closed_by"),
            "entry": t["entry"], "risk": t["risk"], "r": t["realized_r"],
            "usd": dollars(t["realized_r"], t["risk"], t["entry"])} for t in trades]
    return out, gated


def run_specs(df, market, u):
    if market not in ("asx", "nasdaq"):
        return []
    out = []
    for s in sbt.replay_ticker(u["symbol"], df, market):
        if s.get("r") is None:
            continue
        out.append({"lens": "specs", "market": market, "symbol": u["symbol"], "direction": "long",
                    "cohort": s["grade"], "entry_date": s["date"], "exit_reason": s["r_exit"],
                    "closed_by": s.get("r_closed_by"), "entry": s["entry"], "risk": s["r_risk"],
                    "r": s["r"], "usd": dollars(s["r"], s["r_risk"], s["entry"])})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=list(config.MARKETS))
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--of", type=int, default=1)
    ap.add_argument("--period", default="5y")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--frames-dir", default=None)
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
            if p.exists():
                f = pd.DataFrame(json.loads(p.read_text())["bars"],
                                 columns=["Date", "Open", "High", "Low", "Close", "Volume"])
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
        df = drop_forming(df[~df.index.duplicated(keep="last")].sort_index(), a.market)
        for lens, fn in (("vivek", run_vivek), ("phasemap", run_phasemap),
                         ("momentum", run_momentum), ("specs", run_specs)):
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
    doc = {"version": 2, "market": a.market, "shard": a.shard, "of": a.of, "period": a.period,
           "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "universe": len(uni), "shard_symbols": len(mine), "downloaded": len(frames),
           "errors": errors, "momentum_gated": gated, "elapsed_s": round(time.time() - t0, 1),
           "trades": trades}
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    by = {}
    for t in trades:
        by[t["lens"]] = by.get(t["lens"], 0) + 1
    print(f"bt v2 {a.market} shard {a.shard}/{a.of}: {len(frames)}/{len(mine)} downloaded, "
          f"trades {by}, errors {errors}, {doc['elapsed_s']}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
