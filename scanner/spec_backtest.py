"""Specs backtest — proof-of-edge replay for the third lens.

Same standards as the PhaseMap M4 harness: zero lookahead (spec.evaluate()
only ever sees bars up to the signal day), streak de-duplication, seeded
random baseline, and a survivorship banner (yfinance carries no delisted
names, so every number is optimistic).

    python -m scanner.spec_backtest --market asx --period 5y
    python -m scanner.spec_backtest --market asx --limit 300   # quick pass

Writes phasemap/backtest/reports/specs_<market>.md (kept beside the
PhaseMap reports so all proof records live in one place).
"""

from __future__ import annotations

import argparse
import datetime
import os
import random
import sys

import pandas as pd

from . import config, data, output, rmodel, spec, universe

HORIZONS = (5, 10, 20)
DEDUPE_BARS = 5          # one signal per fire-streak
TRACK_BARS = 40          # stop/target race horizon
SEED = 7
REPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "phasemap", "backtest", "reports")


def replay_ticker(sym: str, df: pd.DataFrame, market: str = "asx") -> list[dict]:
    if "Date" not in df.columns:          # data.download frames use a DatetimeIndex
        df = df.reset_index()
        if "Date" not in df.columns:
            df = df.rename(columns={df.columns[0]: "Date"})
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df = df[(df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)].reset_index(drop=True)
    n = len(df)
    if n < config.SPEC_MIN_HISTORY + 5:
        return []
    close = df["Close"].to_numpy()
    high = df["High"].to_numpy()
    low = df["Low"].to_numpy()
    opn = df["Open"].to_numpy()
    days = [str(d)[:10] for d in df["Date"]]
    vol = pd.Series(df["Volume"].to_numpy())
    # cheap vectorised pre-gates so the full evaluate() only runs on candidates
    vol20 = vol.rolling(config.SPEC_VOL_LOOKBACK).mean().shift(1).to_numpy()
    vmax = vol.rolling(config.SPEC_VOL_RECENT).max().to_numpy()

    signals = []
    last_fire = -(10 ** 9)
    for i in range(config.SPEC_MIN_HISTORY, n):
        c = float(close[i])
        if not (0 < c <= config.SPEC_MAX_PRICE):
            continue
        if not (vol20[i] and vol20[i] > 0 and vmax[i] / vol20[i] >= config.SPEC_VOL_SPIKE):
            continue
        sig = spec.evaluate(df.iloc[:i + 1], max_price=config.SPEC_MAX_PRICE)
        if not sig:
            continue
        is_new = (i - last_fire) > DEDUPE_BARS
        last_fire = i
        if not is_new:
            continue
        score, grade, fired = spec.score_and_grade(sig)
        if not grade:
            continue
        lv = spec.compute_levels(df.iloc[:i + 1], sig)
        if not lv or lv.get("rr", 0) <= 0:
            continue
        s = {"symbol": sym, "date": str(df["Date"].iloc[i])[:10], "grade": grade,
             "entry": c, "stop": lv["stop"], "target": lv["target"], "rr": lv["rr"]}
        for h in HORIZONS:
            s[f"fwd_{h}"] = round(float(close[i + h]) / c - 1, 4) if i + h < n else None
        end = min(n, i + 21)
        s["mae"] = round(float(low[i + 1:end].min()) / c - 1, 4) if end > i + 1 else None
        # stop/target race, pessimistic: a bar that tags both counts as a stop
        outcome, race_end = "open", min(n, i + TRACK_BARS + 1)
        for j in range(i + 1, race_end):
            hit_stop = low[j] <= s["stop"]
            hit_tgt = high[j] >= s["target"]
            if hit_stop:
                outcome = "stop"
                break
            if hit_tgt:
                outcome = "target"
                break
        s["outcome"] = outcome
        s.update(r_trade(s, i, days, opn, high, low, close, market))
        signals.append(s)
    return signals


def costs_for(market: str) -> tuple:
    slip = config.VIVEK_SLIPPAGE_BPS.get(market, config.VIVEK_SLIPPAGE_BPS["default"])
    comm = config.VIVEK_COMMISSION_BPS.get(market, config.VIVEK_COMMISSION_BPS["default"])
    return slip / 10_000.0, comm / 10_000.0


def r_trade(s: dict, i: int, days, opn, high, low, close, market: str) -> dict:
    """The R model (2026-09-23): the engine's own plan, traded and scored in R.

    Entry at the signal close (as the race above), the engine's stop, and its
    ONE target booked in full as a resting limit; the stop is a resting order
    too -- the house fill rule, filled at the stop or at the open of a bar that
    gapped through it -- and a bar that spans both is a stop. `r_worst` scores
    the same trade with the stop at the bar's worst print (the 5.0 fill). Anything still open after TRACK_BARS
    -- the race's own horizon -- is closed at that bar's close ("time").
    House costs through scanner/rmodel.py; a stop closer than the house
    minimum is not a trade. The narrative's "then trail it" is NOT modelled:
    the target is where the engine names the exit, so that is where R is
    counted.
    """
    entry, stop = float(s["entry"]), float(s["stop"])
    if i + 1 >= len(close):
        return {"r": None, "r_skip": "signal on the last bar"}
    if not (entry > 0 and stop < entry):
        return {"r": None, "r_skip": "stop not below entry"}
    if (entry - stop) / entry * 100.0 < config.VIVEK_BOT_MIN_STOP_PCT:
        return {"r": None, "r_skip": "stop_too_tight"}
    def make_bars():
        return ((days[j], opn[j], high[j], low[j], close[j]) for j in range(i + 1, len(close)))
    tr, worst = rmodel.simulate_both(make_bars, "long", entry, stop, [float(s["target"])], [1.0],
                                     s["date"], costs=costs_for(market), time_stop=TRACK_BARS)
    if tr is None:
        return {"r": None, "r_skip": "target at or below entry"}
    return {"r": tr["realized_r"], "r_gross": tr["gross_r"], "r_cost": tr["cost_r"],
            "r_risk": tr["risk"], "r_exit": tr["exit_reason"], "r_closed_by": tr.get("closed_by"),
            "r_exit_date": tr.get("exit_date"), "r_bars": tr["bars"],
            # the same trade, stop filled at the bar's worst print (the 5.0 fill)
            "r_worst": worst["realized_r"], "r_gross_worst": worst["gross_r"]}


def summarise_r(sigs: list[dict], notional: float | None = None, fill: str = "house") -> dict:
    """R won / lost / net over the signals that were tradeable plans.
    `fill="worst_print"` scores the same trades with the 5.0 stop fill."""
    key = {"house": "r", "worst_print": "r_worst"}[fill]
    rows = [{"realized_r": s[key], "entry": s["entry"], "risk": s["r_risk"],
             "exit_reason": s["r_exit"], "closed_by": s.get("r_closed_by")}
            for s in sigs if s.get("r") is not None]
    out = rmodel.summarise(rows, notional)
    skipped: dict = {}
    for s in sigs:
        if s.get("r") is None and s.get("r_skip"):
            skipped[s["r_skip"]] = skipped.get(s["r_skip"], 0) + 1
    out["skipped"] = skipped
    return out


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def summarise(sigs: list[dict]) -> dict:
    n = len(sigs)
    out = {"n": n}
    for h in HORIZONS:
        out[f"fwd_{h}"] = _mean([s[f"fwd_{h}"] for s in sigs])
    out["mae"] = _mean([s["mae"] for s in sigs])
    for o in ("target", "stop", "open"):
        out[o] = round(100 * sum(1 for s in sigs if s["outcome"] == o) / n, 1) if n else None
    return out


def write_report(market: str, sigs: list[dict], rnd: dict, universe_size: int,
                 period: str) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    top = summarise(sigs)
    lines = [
        f"# Specs backtest — {market.upper()}",
        "",
        f"Generated {datetime.date.today().isoformat()} · engine scanner/spec.py "
        f"(restored 2026-07-02) · universe {universe_size} · period {period} · "
        f"zero-lookahead slice replay, one signal per fire-streak.",
        "",
        "> **LIMITATION — SURVIVORSHIP BIAS:** yfinance has no delisted history. "
        "Sub-$0.50 specs delist *constantly* — this cohort is missing its "
        "casualties and every number below is optimistic. Directional use only.",
        "",
        "A **signal** = the first day a fire-streak passes every mandatory gate "
        "(3× volume spike, beaten-down base, breakout, rising 9-SMA, not "
        "over-extended). Entry at the signal close; stop/target from the "
        "engine's own levels; a bar tagging both counts as a stop (pessimistic).",
        "",
        "| cohort | n | fwd 5 | fwd 10 | fwd 20 | target first | stopped | still open | MAE |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    def row(name, s):
        f = lambda v: "—" if v is None else f"{v * 100:+.1f}%"
        p = lambda v: "—" if v is None else f"{v}%"
        return (f"| {name} | {s['n']} | {f(s.get('fwd_5'))} | {f(s.get('fwd_10'))} "
                f"| {f(s.get('fwd_20'))} | {p(s.get('target'))} | {p(s.get('stop'))} "
                f"| {p(s.get('open'))} | {f(s.get('mae'))} |")

    lines.append(row("ALL SIGNALS", top))
    for g in ("A+", "A", "B"):
        sub = [s for s in sigs if s["grade"] == g]
        if sub:
            lines.append(row(f"grade {g}", summarise(sub)))
    r_all = summarise_r(sigs, config.LENS_BACKTEST_NOTIONAL)

    def rrow(name, r):
        if not r.get("trades"):
            return f"| {name} | 0 | — | — | — | — | — | — |"
        return (f"| {name} | {r['trades']} | {r['win_pct']}% | +{r['r_won']:.1f}R | "
                f"{r['r_lost']:.1f}R | **{r['net_r']:+.1f}R** | {r['expectancy_r']:+.3f}R | "
                f"${r.get('net_usd', 0):+,.0f} |")
    lines += [
        "",
        "## R model — what trading the signals earned",
        "",
        "Entry at the signal close, the engine's stop, its one target booked in full "
        f"(resting limit), stop gap-aware, closed at the close after {TRACK_BARS} bars "
        "if neither; house costs; a stop under the house minimum is not a trade. "
        f"Dollars at a flat ${config.LENS_BACKTEST_NOTIONAL:,.0f} per position.",
        "",
        "| cohort | trades | win | R won | R lost | net R | per trade | net $ |",
        "|---|---|---|---|---|---|---|---|",
        rrow("ALL SIGNALS", r_all),
        rrow("ALL SIGNALS, stop at the worst print",
             summarise_r(sigs, config.LENS_BACKTEST_NOTIONAL, "worst_print")),
    ]
    for g in ("A+", "A", "B"):
        sub = [s for s in sigs if s["grade"] == g]
        if sub:
            lines.append(rrow(f"grade {g}", summarise_r(sub, config.LENS_BACKTEST_NOTIONAL)))
    lines += [
        "",
        "## Baseline",
        f"- Random entry on the same sub-$0.50 universe ({rnd['n']} samples, seeded): "
        + " · ".join(f"fwd {h}: " + ("—" if rnd.get(f'fwd_{h}') is None
                     else f"{rnd[f'fwd_{h}'] * 100:+.1f}%") for h in HORIZONS),
        "",
        "Analysis only — not financial advice.",
        "",
    ]
    path = os.path.join(REPORT_DIR, f"specs_{market}.md")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    return path


def random_baseline(frames: dict, n_samples: int) -> dict:
    rng = random.Random(SEED)
    pool = []
    for df in frames.values():
        closes = df["Close"].dropna()
        closes = closes[closes > 0].to_numpy()
        hi = len(closes) - max(HORIZONS) - 1
        for i in range(config.SPEC_MIN_HISTORY, hi):
            if closes[i] <= config.SPEC_MAX_PRICE:
                pool.append((closes, i))
    rets = {h: [] for h in HORIZONS}
    if pool:
        for _ in range(min(n_samples, len(pool))):
            closes, i = pool[rng.randrange(len(pool))]
            for h in HORIZONS:
                rets[h].append(float(closes[i + h]) / float(closes[i]) - 1)
    out = {"n": len(rets[HORIZONS[0]])}
    for h in HORIZONS:
        out[f"fwd_{h}"] = _mean(rets[h])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="specs backtest")
    ap.add_argument("--market", default="asx", choices=["asx", "nasdaq"])
    ap.add_argument("--period", default="5y")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args(argv)

    items = universe.load_universe(args.market, full=True)
    if args.limit:
        items = items[:args.limit]
    yf_map = {it["yf"]: it for it in items}
    print(f"specs backtest - {args.market} ({len(items)} names, {args.period})")
    frames = data.download(list(yf_map), period=args.period, interval="1d")

    signals = []
    for yf_sym, df in frames.items():
        info = yf_map.get(yf_sym)
        if info is None or df is None or df.empty:
            continue
        try:
            signals.extend(replay_ticker(info.get("symbol", yf_sym), df, args.market))
        except Exception:
            continue
    signals.sort(key=lambda s: (s["date"], s["symbol"]))

    rnd = random_baseline(frames, max(len(signals), 200))
    path = write_report(args.market, signals, rnd, len(items), args.period)
    # machine-readable copy for the Insights page (kept fresh by weekly CI)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pub_dir = os.path.join(root, "public", "data", "phasemap", "stats")
    os.makedirs(pub_dir, exist_ok=True)
    top = summarise(signals)
    pub = {
        "market": args.market.upper(),
        "generated": datetime.date.today().isoformat(),
        "period": args.period,
        "survivorship_bias": True,
        "all": top,
        "grades": {g: summarise([s for s in signals if s["grade"] == g])
                   for g in ("A+", "A", "B") if any(s["grade"] == g for s in signals)},
        "baseline_random": rnd,
        # additive (2026-09-23): the R model, see r_trade()
        "r_model": {
            "fill": "house",
            "all": summarise_r(signals, config.LENS_BACKTEST_NOTIONAL),
            "worst_print": summarise_r(signals, config.LENS_BACKTEST_NOTIONAL, "worst_print"),
            "grades": {g: summarise_r([s for s in signals if s["grade"] == g],
                                      config.LENS_BACKTEST_NOTIONAL)
                       for g in ("A+", "A", "B") if any(s["grade"] == g for s in signals)},
        },
    }
    # TOP100 #64 — was a plain open()+write, so a crash mid-write published a
    # truncated file. write_json keeps the utf-8 and the pinned LF this call
    # already asked for, and adds the temp+os.replace swap.
    output.write_json(os.path.join(pub_dir, f"specs_{args.market}.json"), pub,
                      indent=1, newline=True)
    print(f"signals: {len(signals)}  target-first: {top.get('target')}%  "
          f"stopped: {top.get('stop')}%  report: {path}")
    r = pub["r_model"]["all"]
    print(f"R model: {r['trades']} trades  win {r['win_pct']}%  R won {r['r_won']:+.1f}  "
          f"R lost {r['r_lost']:+.1f}  net {r['net_r']:+.1f}R  ({r['expectancy_r']}R/trade)  "
          f"${r.get('net_usd', 0):+,.0f} at ${config.LENS_BACKTEST_NOTIONAL:,.0f}/position")
    return 0


if __name__ == "__main__":
    sys.exit(main())
