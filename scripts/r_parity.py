"""Like-for-like R across the four lenses (2026-09-24). ANALYSIS ONLY.

The four lenses were each scored in R by their own replay, and the fills did
not match: the VIVEK 5.0 backtest fills a stop at the bar's worst print, the
other three at the stop. This puts all four on ONE set of rules so the
numbers can be read side by side:

  fill      the HOUSE rule -- a stop is a resting order, filled at the stop or
            at the open of a bar that gapped through it (scanner.rmodel
            .HOUSE_STOP_FILL). The SAME trades are also scored with the 5.0
            worst-print fill (rmodel.WORST_PRINT_FILL) as a second column.
            Exit timing is identical under both, so both columns describe one
            trade set.
  costs     the house table (VIVEK_SLIPPAGE_BPS / VIVEK_COMMISSION_BPS)
  notional  LENS_BACKTEST_NOTIONAL ($1,000 a trade): $ = R x 1000 x risk/entry
  min stop  VIVEK_BOT_MIN_STOP_PCT (1%): a closer stop is not a trade
  universe  today's universe, less the bot's fund/REIT exclusion, for all four

Each lens keeps its OWN signals and management (5.0: armed A+/A plans, one
slot per timeframe, the 3-target ladder; PhaseMap: A+/A signals, exit at the
floor, T1 consumed or the engine dropping the setup; momentum: Rule A + Rule
B at the live min_signal_score, the Pine box, the 5.0 ladder; Specs: the
engine plan, one target, 40-bar time stop).

5.0 is replayed by the evidence engine itself (vivek_backtest.replay_symbol,
UNCHANGED): the house column is a re-score of each of its trades from the
fill bar, and the worst-print re-score must reproduce the engine's own
realized_r to the 4th decimal -- every mismatch is counted and printed. The
1% minimum stop is applied as the bot applies it, at the fill: a plan whose
stop is closer is refused, and its timeframe slot stays free.

Nothing here writes to the book, bot_rules.json, Discord or the confluence
machinery. Two subcommands:

  python scripts/r_parity.py shard  --market asx --shard 0 --of 16 --out bt/out/asx-00.json
  python scripts/r_parity.py report --in bt/out --out reviews/2026-09-24-r-parity.md
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import logging
import pathlib
import sys
import time
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phasemap.backtest.harness import run_ticker  # noqa: E402
from scanner import config  # noqa: E402
from scanner import conviction  # noqa: E402
from scanner import rmodel  # noqa: E402
from scanner import spec_backtest as sbt  # noqa: E402
from scanner import vivek_backtest as vbt  # noqa: E402
from scanner.broker.vivek_bot import _is_fund_or_reit  # noqa: E402
from scanner.journal_common import atomic_write  # noqa: E402
from scanner.momentum import backtest as mbt  # noqa: E402
from scanner.momentum import config as mcfg  # noqa: E402
from scanner.vivek_journal import costs_for  # noqa: E402

log = logging.getLogger("r_parity")

VERSION = 2
LENSES = ("vivek", "phasemap", "momentum", "specs")
TITLE = {"vivek": "VIVEK 5.0", "phasemap": "PhaseMap", "momentum": "Momentum", "specs": "Specs"}
WHAT = {"vivek": "armed A+/A plans, 1D/3D/1W",
        "phasemap": "bullish A+/A signals",
        "momentum": "Rule A + Rule B longs",
        "specs": "every signal, A+/A/B"}
FILLS = (("house", "r"), ("worst print", "w"))
NOTIONAL = float(config.LENS_BACKTEST_NOTIONAL)
MIN_STOP = float(config.VIVEK_BOT_MIN_STOP_PCT)
SPEC_MARKETS = ("asx", "nasdaq")
SURVIVORSHIP = ("Survivorship: every market is replayed on TODAY's universe, so names "
                "that delisted, were acquired or went to zero inside the window are "
                "missing, and every number below is flattered by that -- none of it "
                "is corrected for.")


# -- the shard ---------------------------------------------------------------

def drop_forming(df: pd.DataFrame, market: str) -> pd.DataFrame:
    """Closed bars only: a still-forming last bar is dropped for every lens."""
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


def _bars(df: pd.DataFrame):
    days = [ix.date().isoformat() for ix in df.index]
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close"))
    return days, o, h, l, c


def replay_vivek(df, market, u, *, long_only: bool, gated: collections.Counter,
                 check: collections.Counter) -> list:
    """The 5.0 evidence engine's trades, re-scored under both fills.

    The engine is run UNCHANGED; its `_snapshot` is wrapped for the duration of
    the call to (a) apply the 1% minimum stop at the fill, as the bot does, and
    (b) keep the plan's original stop, which the trade's own `stop` field
    trails away from. The wrapper is always restored."""
    orig = vbt._snapshot

    def snap(row, tf, plan, mkt, entry_price, day):
        tr = orig(row, tf, plan, mkt, entry_price, day)
        if tr is None:
            return None
        if tr["risk"] / tr["entry"] * 100.0 < MIN_STOP:
            gated["stop_too_tight"] += 1
            return None
        tr["initial_stop"] = float(plan["stop"])
        return tr

    vbt._snapshot = snap
    try:
        closed = vbt.replay_symbol(df, market, u["symbol"], u.get("name", ""), u.get("sector", ""),
                                   long_only=long_only)
    finally:
        vbt._snapshot = orig
    days, o, h, l, c = _bars(df)
    at = {d: k for k, d in enumerate(days)}
    n, costs, out = len(days), costs_for(market), []
    for tr in closed:
        j = at[tr["entry_date"]]
        house, worst = rmodel.simulate_both(
            lambda j=j: ((days[k], o[k], h[k], l[k], c[k]) for k in range(j, n)),
            tr["direction"], tr["entry"], tr["initial_stop"], [tr["tp1"], tr["tp2"], tr["tp3"]],
            tr["scale"], tr["entry_date"], costs=costs,
            # the engine already decided the trade was takeable, on the RAW open;
            # re-deciding on the 8-dp entry refuses an open that sits within
            # float noise of TP1 (seen on the runners: 2.9499999... vs 2.95)
            chase_guard=False)
        if house is None or abs(worst["realized_r"] - tr["realized_r"]) > 1e-9 \
                or worst["exit_date"] != tr["exit_date"]:
            check["mismatch"] += 1
            log.warning("5.0 re-score mismatch %s %s %s: engine %s, re-score %s", market,
                        u["symbol"], tr["entry_date"], tr["realized_r"],
                        None if worst is None else worst["realized_r"])
            if house is None:
                continue
        check["compared"] += 1
        out.append({"lens": "vivek", "m": market, "s": u["symbol"], "dir": tr["direction"],
                    "cohort": tr["grade"], "tf": tr["timeframe"], "et": tr.get("entry_type"),
                    "cell": conviction.trade_cell(tr), "lvl": tr.get("level_tf"),
                    "d": tr["entry_date"], "e": tr["entry"], "k": tr["risk"],
                    "r": house["realized_r"], "w": worst["realized_r"], "cb": house["closed_by"]})
    return out


def replay_phasemap(df, market, u, skipped: collections.Counter) -> list:
    pm = df.reset_index()
    pm = pm.rename(columns={pm.columns[0]: "Date"})
    out = []
    for s in run_ticker(u["symbol"], pm, market, volume_is_usd=(market == "crypto")):
        if s["tier"] not in ("A+", "A"):
            continue
        if not s.get("r_tradeable"):
            skipped[s.get("r_skip") or "untradeable"] += 1
            continue
        out.append({"lens": "phasemap", "m": market, "s": u["symbol"],
                    "dir": "long" if s["direction"] == "bullish" else "short",
                    "cohort": s["tier"], "illiquid": bool(s.get("illiquid")),
                    "d": s["signal_date"], "e": s["r_entry"], "k": s["r_risk"],
                    "r": s["realized_r"], "w": s["realized_r_worst"], "c": s["realized_r_close"],
                    "cb": s["r_exit_reason"]})
    return out


def replay_momentum(df, market, u, gated: collections.Counter) -> list:
    trades, g = mbt.replay_symbol(df, market, symbol=u["symbol"], name=u.get("name"),
                                  sector=u.get("sector"))
    gated.update(g)
    return [{"lens": "momentum", "m": market, "s": u["symbol"], "dir": t["direction"],
             "cohort": f"Rule {t['rule']}", "d": t["signal_date"], "e": t["entry"],
             "k": t["risk"], "r": t["realized_r"], "w": t["realized_r_worst"],
             "cb": t.get("closed_by")} for t in trades]


def replay_specs(df, market, u, skipped: collections.Counter) -> list:
    if market not in SPEC_MARKETS:
        return []
    out = []
    for s in sbt.replay_ticker(u["symbol"], df, market):
        if s.get("r") is None:
            skipped[s.get("r_skip") or "untradeable"] += 1
            continue
        out.append({"lens": "specs", "m": market, "s": u["symbol"], "dir": "long",
                    "cohort": s["grade"], "d": s["date"], "e": s["entry"], "k": s["r_risk"],
                    "r": s["r"], "w": s["r_worst"], "cb": s.get("r_closed_by")})
    return out


def replay_frames(market: str, frames: dict, by_yf: dict) -> dict:
    """Every lens over one market's frames. One name that throws is counted
    against its lens and skipped, never allowed to sink the shard."""
    trades, errors = [], collections.Counter()
    excluded = replayed = 0
    gated = {k: collections.Counter() for k in LENSES}
    check = collections.Counter()
    for yf, df in sorted(frames.items()):
        u = by_yf.get(yf)
        if u is None or df is None or not len(df):
            continue
        if _is_fund_or_reit({"name": u.get("name"), "sector": u.get("sector")}):
            excluded += 1
            continue
        replayed += 1
        df = drop_forming(df[~df.index.duplicated(keep="last")].sort_index(), market)
        steps = (
            ("vivek", lambda: replay_vivek(df, market, u, long_only=True, gated=gated["vivek"],
                                           check=check)),
            ("vivek", lambda: [t for t in replay_vivek(df, market, u, long_only=False,
                                                       gated=collections.Counter(), check=check)
                               if t["dir"] == "short"]),
            ("phasemap", lambda: replay_phasemap(df, market, u, gated["phasemap"])),
            ("momentum", lambda: replay_momentum(df, market, u, gated["momentum"])),
            ("specs", lambda: replay_specs(df, market, u, gated["specs"])),
        )
        for lens, fn in steps:
            try:
                trades.extend(fn())
            except Exception as e:  # noqa: BLE001 -- counted and logged, per name
                errors[lens] += 1
                log.warning("%s %s %s: %s", lens, market, yf, e)
    return {"trades": trades, "errors": dict(errors), "product_excluded": excluded,
            "replayed": replayed, "gated": {k: dict(v) for k, v in gated.items()},
            "vivek_check": dict(check)}


def _load_frames(frames_dir: pathlib.Path, rows: list) -> dict:
    frames = {}
    for u in rows:
        p = frames_dir / f"{u['symbol']}.json"
        if p.exists():
            f = pd.DataFrame(json.loads(p.read_text(encoding="utf-8"))["bars"],
                             columns=["Date", "Open", "High", "Low", "Close", "Volume"])
            f.index = pd.to_datetime(f.pop("Date"))
            frames[u["yf"]] = f
    return frames


def cmd_shard(a) -> int:
    t0 = time.time()
    from scanner.universe import load_universe
    uni = sorted(load_universe(a.market, full=True), key=lambda u: u["yf"])
    mine = uni[a.shard::a.of]
    if a.symbols:
        want = set(a.symbols.split(","))
        mine = [u for u in mine if u["symbol"] in want]
    if a.limit:
        mine = mine[: a.limit]
    by_yf = {u["yf"]: u for u in mine}
    if a.frames_dir:
        frames = _load_frames(pathlib.Path(a.frames_dir), mine)
    else:
        from scanner.data import download
        frames = download(list(by_yf), period=a.period)
        missed = [yf for yf in by_yf if frames.get(yf) is None or not len(frames[yf])]
        if missed:                       # one more pass once a throttled source has cooled
            time.sleep(a.retry_wait)
            frames.update({k: v for k, v in download(missed, period=a.period).items()
                           if v is not None and len(v)})
    frames = {k: v for k, v in frames.items() if v is not None and len(v)}
    doc = {"version": VERSION, "market": a.market, "shard": a.shard, "of": a.of,
           "period": a.period, "universe": len(uni), "shard_symbols": len(mine),
           "downloaded": len(frames),
           "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    doc.update(replay_frames(a.market, frames, by_yf))
    doc["elapsed_s"] = round(time.time() - t0, 1)
    atomic_write(pathlib.Path(a.out), json.dumps(doc, separators=(",", ":")) + "\n", newline="\n")
    by = collections.Counter(t["lens"] for t in doc["trades"])
    print(f"r_parity {a.market} shard {a.shard}/{a.of}: {len(frames)}/{len(mine)} downloaded, "
          f"trades {dict(by)}, errors {doc['errors']}, 5.0 check {doc['vivek_check']}, "
          f"{doc['elapsed_s']}s", flush=True)
    if doc["vivek_check"].get("mismatch"):
        print(f"::warning::r_parity {a.market} shard {a.shard}: {doc['vivek_check']['mismatch']} "
              "5.0 re-score mismatches -- the report counts them", flush=True)
    return 0


# -- the report --------------------------------------------------------------

def stats(ts: list, key: str = "r") -> dict:
    rs = [float(t[key]) for t in ts]
    n = len(rs)
    usd = sum(r * NOTIONAL * float(t["k"]) / float(t["e"]) for r, t in zip(rs, ts) if t["e"])
    wins = sum(1 for r in rs if r > 0)
    return {"n": n, "net_r": round(sum(rs), 2), "r_per_trade": round(sum(rs) / n, 3) if n else None,
            "win_pct": round(100.0 * wins / n, 1) if n else None, "usd": round(usd, 2),
            "open_at_end": sum(1 for t in ts if t.get("cb") == "eod")}


def _num(v, fmt, sign=True):
    if v is None:
        return "--"
    return (("+" if sign and v > 0 else "") + format(v, fmt))


def _usd(v):
    return ("+" if v > 0 else "-" if v < 0 else "") + f"${abs(v):,.0f}"


def _row(label, fill, s):
    return (f"| {label} | {fill} | {_num(s['net_r'], ',.1f')} | {_num(s['r_per_trade'], '.3f')} | "
            f"{_num(s['win_pct'], '.1f', sign=False)}% | {s['n']:,} | {_usd(s['usd'])} |")


HEAD = ["| lens | fill rule | net R | R/trade | win% | n | $ at $1k |",
        "|---|---|---|---|---|---|---|"]


def _pair(label, ts):
    return [_row(label, f, stats(ts, k)) for f, k in FILLS]


def load_shards(indir: pathlib.Path) -> list:
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(indir.glob("*.json"))]
    return [d for d in docs if d.get("version") == VERSION]


def coverage(shards: list) -> dict:
    cov = {}
    for s in shards:
        c = cov.setdefault(s["market"], {"universe": s["universe"], "of": s["of"], "shards": set(),
                                         "symbols": 0, "downloaded": 0, "excluded": 0,
                                         "replayed": 0, "errors": collections.Counter()})
        c["universe"] = max(c["universe"], s["universe"])
        c["shards"].add(s["shard"])
        c["symbols"] += s["shard_symbols"]
        c["downloaded"] += s["downloaded"]
        c["excluded"] += s.get("product_excluded", 0)
        c["replayed"] += s.get("replayed", 0)
        c["errors"].update(s.get("errors") or {})
    for c in cov.values():
        c["missing_shards"] = sorted(set(range(c["of"])) - c["shards"])
        c["shards"] = len(c["shards"])
        c["errors"] = dict(c["errors"])
    return cov


def coverage_line(market: str, c: dict) -> str:
    pct = 100.0 * c["downloaded"] / c["universe"] if c["universe"] else 0.0
    line = (f"- **{market.upper()}**: {c['downloaded']:,} downloaded / {c['universe']:,} in "
            f"the universe ({pct:.1f}%); {c['excluded']:,} funds/REITs excluded, "
            f"{c['replayed']:,} names replayed; shards {c['shards']}/{c['of']}")
    if c["missing_shards"]:
        line += f" -- MISSING shards {c['missing_shards']}, so the missing names are not in any number below"
    if c["errors"]:
        line += f"; per-name errors {c['errors']}"
    return line + "."


def _bps() -> str:
    return "; ".join(f"{m.upper()} slippage {config.VIVEK_SLIPPAGE_BPS[m]:g} + commission "
                     f"{config.VIVEK_COMMISSION_BPS[m]:g}" for m in ("asx", "nasdaq", "crypto"))


def build_report(shards: list, verdict: str = "") -> tuple[str, dict]:
    trades = [t for s in shards for t in s["trades"]]
    cov = coverage(shards)
    markets = [m for m in ("asx", "nasdaq", "crypto") if m in cov]
    longs = [t for t in trades if t["dir"] == "long"]
    shorts = [t for t in trades if t["dir"] == "short"]
    by = lambda ts, lens: [t for t in ts if t["lens"] == lens]  # noqa: E731
    check = collections.Counter()
    gated = {k: collections.Counter() for k in LENSES}
    for s in shards:
        check.update(s.get("vivek_check") or {})
        for k in LENSES:
            gated[k].update((s.get("gated") or {}).get(k) or {})
    dates = sorted(t["d"] for t in trades)
    span = f"{dates[0]} to {dates[-1]}" if dates else "no trades"
    periods = sorted({s["period"] for s in shards})

    L = ["# Like-for-like R across the four lenses -- 2026-09-24", "",
         "One fill rule, one cost table, one notional, one minimum stop, applied to every "
         "lens's own signals over the same downloaded bars. The HEADLINE IS LONG ONLY; "
         "shorts are in the appendix and are in no win% above it.", "",
         "- **House fill** (the headline): a stop is a resting order, filled at the stop or "
         "at the open of a bar that gapped through it.",
         "- **Worst print** (second column): the SAME trades, a stop filled at the bar's worst "
         "print -- the 5.0 backtest's convention. Exit timing is identical, so both columns "
         "are one trade set; the difference is purely the fill.",
         f"- Costs: the house table, basis points per side -- {_bps()}. $ at ${NOTIONAL:,.0f} a trade = R x "
         f"{NOTIONAL:,.0f} x risk / entry. Minimum stop {MIN_STOP:g}% of entry: a closer stop "
         "is not a trade in any lens.",
         f"- Window: {', '.join(periods)} of daily bars; trades entered {span}. Universe: "
         "today's, less the bot's fund/REIT exclusion, identically for all four lenses.",
         "", "## Coverage", ""]
    L += [coverage_line(m, cov[m]) for m in markets]
    L += ["", SURVIVORSHIP, "", "## Headline -- longs only", ""] + HEAD
    for lens in LENSES:
        L += _pair(f"{TITLE[lens]}: {WHAT[lens]}", by(longs, lens))

    vl = by(longs, "vivek")
    bot_rule = [t for t in vl if t.get("cell") and t.get("lvl") in config.VIVEK_BOT_LEVEL_TF_ALLOW]
    L += ["", "## VIVEK 5.0 -- the splits that must stay visible (longs)", "", *HEAD]
    for tf in ("1D", "3D", "1W"):
        L += _pair(f"5.0 {tf}", [t for t in vl if t["tf"] == tf])
    L += _pair("5.0 all A+/A", vl)
    L += _pair("5.0 high-conviction cells (any of the four)", [t for t in vl if t.get("cell")])
    L += _pair("5.0 not a high-conviction cell", [t for t in vl if not t.get("cell")])
    for cell in conviction.cell_names():
        L += _pair(f"5.0 cell: {cell}", [t for t in vl if t.get("cell") == cell])
    L += _pair("5.0 bot rule (four cells, weekly/3d level)", bot_rule)
    for g in ("A+", "A"):
        L += _pair(f"5.0 grade {g}", [t for t in vl if t["cohort"] == g])

    ml = by(longs, "momentum")
    L += ["", f"## Momentum -- Rule A vs Rule B by market (longs; live min_signal_score "
          f"= {mcfg.DEFAULTS.min_signal_score})", "", *HEAD]
    for rule in ("Rule A", "Rule B"):
        for m in markets:
            L += _pair(f"Momentum {rule} {m.upper()}", [t for t in ml if t["cohort"] == rule and t["m"] == m])
        L += _pair(f"Momentum {rule} all markets", [t for t in ml if t["cohort"] == rule])

    L += ["", "## Every lens by market (longs)", "", *HEAD]
    for lens in LENSES:
        for m in markets:
            if lens == "specs" and m not in SPEC_MARKETS:
                continue
            L += _pair(f"{TITLE[lens]} {m.upper()}", [t for t in by(longs, lens) if t["m"] == m])

    pl = by(longs, "phasemap")
    L += ["", "## PhaseMap reference -- the engine's own close-only exits (longs)", "",
          "The house rule stops a PhaseMap trade on the first print through the "
          "INVALIDATION_HARD floor; the spec says a wick through is a test and only a CLOSE "
          "through kills the setup. This column reads the engine natively (every exit at a "
          "close) so the cost of the house rule to this lens is visible.", "", *HEAD,
          _row("PhaseMap (bullish A+/A)", "engine close", stats(pl, "c"))]

    L += ["", "## Appendix -- shorts (never in a headline number)", "", *HEAD]
    for lens in ("vivek", "phasemap", "momentum"):
        L += _pair(f"{TITLE[lens]} shorts", by(shorts, lens))
    L += ["", "Specs has no short side. 5.0 shorts come from a separate both-directions "
          "replay, because a short holds a timeframe slot a long would otherwise take; the "
          "headline 5.0 longs are the long-only replay, as the bot trades."]

    L += ["", "## Checks", "",
          f"- 5.0 re-score: {check.get('compared', 0):,} engine trades (both 5.0 replays) "
          f"re-scored from the fill bar; the worst-print column reproduced the engine's own realized_r on all but "
          f"{check.get('mismatch', 0)}.",
          f"- Refused by the 1% minimum stop: 5.0 {gated['vivek'].get('stop_too_tight', 0):,}, "
          f"PhaseMap {gated['phasemap'].get('stop_too_tight', 0):,}, momentum "
          f"{gated['momentum'].get('stop_too_tight', 0):,}, Specs "
          f"{gated['specs'].get('stop_too_tight', 0):,}.",
          f"- Momentum signals removed by its own gates: "
          f"{dict(sorted(gated['momentum'].items(), key=lambda kv: -kv[1]))}.",
          "- Still open at the end of the data (marked at the last close), longs: "
          + ", ".join(f"{TITLE[k]} {stats(by(longs, k))['open_at_end']:,}" for k in LENSES) + "."]
    if verdict.strip():
        L += ["", "## What the paper bot should keep taking, and what it should not", "",
              verdict.strip()]
    res = {"coverage": {m: {k: v for k, v in c.items()} for m, c in cov.items()},
           "headline": {lens: {f: stats(by(longs, lens), k) for f, k in FILLS} for lens in LENSES},
           "shorts": {lens: {f: stats(by(shorts, lens), k) for f, k in FILLS}
                      for lens in ("vivek", "phasemap", "momentum")},
           "vivek_check": dict(check)}
    return "\n".join(L) + "\n", res


def cmd_report(a) -> int:
    shards = load_shards(pathlib.Path(a.indir))
    if not shards:
        print("r_parity report: no shards found", flush=True)
        return 3
    verdict = pathlib.Path(a.verdict).read_text(encoding="utf-8") if a.verdict else ""
    md, res = build_report(shards, verdict)
    atomic_write(pathlib.Path(a.out), md, newline="\n")
    if a.json:
        atomic_write(pathlib.Path(a.json), json.dumps(res, indent=1, sort_keys=True) + "\n", newline="\n")
    print(f"r_parity report: {len(shards)} shards -> {a.out}", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sh = sub.add_parser("shard")
    sh.add_argument("--market", required=True, choices=list(config.MARKETS))
    sh.add_argument("--shard", type=int, default=0)
    sh.add_argument("--of", type=int, default=1)
    sh.add_argument("--period", default="5y")
    sh.add_argument("--out", required=True)
    sh.add_argument("--limit", type=int, default=0)
    sh.add_argument("--symbols", default="")
    sh.add_argument("--frames-dir", default=None)
    sh.add_argument("--retry-wait", type=float, default=60.0)
    rp = sub.add_parser("report")
    rp.add_argument("--in", dest="indir", required=True)
    rp.add_argument("--out", required=True)
    rp.add_argument("--json", default=None)
    rp.add_argument("--verdict", default=None)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    return cmd_shard(a) if a.cmd == "shard" else cmd_report(a)


if __name__ == "__main__":
    sys.exit(main())
