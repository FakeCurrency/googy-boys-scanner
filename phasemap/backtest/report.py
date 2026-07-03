"""Backtest report + {stats} artefact writers.

Outputs, per market:
  phasemap/backtest/reports/<market>.md     — the human proof-of-edge record
  phasemap/backtest/stats/<market>.json     — feeds the narration {stats} slot
                                              (guardrail: only real M4 numbers
                                              ever reach a narration)
"""

import datetime
import json
import os

from phasemap.config import CONFIG, RULESET_VERSION

SURVIVORSHIP_BANNER = (
    "> **LIMITATION — SURVIVORSHIP BIAS:** this run used the yfinance "
    "prototype feed, which has NO delisted-stock history. Every statistic "
    "below is computed on survivors only and is therefore optimistic. "
    "Do not publish these numbers; re-run on a provider with delisted data "
    "(Norgate/EODHD) first.")


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def _pct(part, whole):
    return round(100 * part / whole, 1) if whole else None


def summarise(signals: list) -> dict:
    n = len(signals)
    out = {"n": n}
    for h in CONFIG.fwd_return_bars:
        out[f"fwd_{h}"] = _mean([s.get(f"fwd_{h}") for s in signals])
    out["mae"] = _mean([s.get("mae") for s in signals])
    hits = sum(1 for s in signals if s.get("t1_hit"))
    out["t1_hit_pct"] = _pct(hits, n)
    tt = [s["time_to_t1"] for s in signals if s.get("time_to_t1") is not None]
    out["avg_bars_to_t1"] = round(sum(tt) / len(tt), 1) if tt else None
    out["stalled_pct"] = _pct(sum(1 for s in signals if s.get("stalled_bar") is not None), n)
    out["dead_pct"] = _pct(sum(1 for s in signals if s.get("dead_bar") is not None), n)
    return out


def cohorts(signals: list) -> dict:
    """The spec's split axes: tier, direction, liquidity band, price band,
    plus in-sample vs out-of-sample by signal date."""
    split = {}

    def add(name, pred):
        subset = [s for s in signals if pred(s)]
        if subset:
            split[name] = summarise(subset)

    add("tier A+", lambda s: s["tier"] == "A+")
    add("tier A", lambda s: s["tier"] == "A")
    add("long", lambda s: s["direction"] == "bullish")
    add("short", lambda s: s["direction"] == "bearish")
    add("liquid", lambda s: not s["illiquid"])
    add("illiquid", lambda s: s["illiquid"])
    add("price >= $1", lambda s: not s["cents"])
    add("cents (<$1)", lambda s: s["cents"])
    add("in-sample", lambda s: s["signal_date"] < CONFIG.oos_split_date)
    add("out-of-sample", lambda s: s["signal_date"] >= CONFIG.oos_split_date)
    return split


def stall_summary(signals: list) -> dict:
    stalled = [s for s in signals if s.get("stall_class")]
    return {
        "stalled": len(stalled),
        "saved_capital": sum(1 for s in stalled if s["stall_class"] == "saved_capital"),
        "cut_winner": sum(1 for s in stalled if s["stall_class"] == "cut_winner"),
        "neither": sum(1 for s in stalled if s["stall_class"] == "neither"),
    }


def _fmt_row(name, s):
    f = lambda v, suf="": ("—" if v is None else f"{v * 100:+.1f}%" if suf == "r"
                           else f"{v}{suf}")
    return (f"| {name} | {s['n']} | {f(s.get('fwd_5'), 'r')} | {f(s.get('fwd_10'), 'r')} "
            f"| {f(s.get('fwd_20'), 'r')} | {f(s.get('t1_hit_pct'), '%')} "
            f"| {f(s.get('avg_bars_to_t1'))} | {f(s.get('mae'), 'r')} |")


def write_report(market: str, signals: list, rnd: dict, bh: dict,
                 universe_size: int, period: str, out_dir: str = None) -> str:
    out_dir = out_dir or os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(out_dir, exist_ok=True)
    top = summarise(signals)
    grades = cohorts(signals)
    stall = stall_summary(signals)
    today = datetime.date.today().isoformat()

    lines = [
        f"# PhaseMap backtest — {market.upper()}",
        "",
        f"Generated {today} · ruleset v{RULESET_VERSION} · universe {universe_size} "
        f"tickers · history period {period} · zero-lookahead replay through the "
        f"production SetupEngine.",
        "",
        SURVIVORSHIP_BANNER,
        "",
        "A **signal** is a displacement confirmation (state DISPLACED). Forward "
        "returns are measured from the entry-zone midpoint; \"T1 hit\" means the "
        f"first target zone was CONSUMED within {CONFIG.stats_window_bars} sessions "
        "before any hard invalidation.",
        "",
        "| cohort | n | fwd 5 | fwd 10 | fwd 20 | T1 hit | bars→T1 | MAE |",
        "|---|---|---|---|---|---|---|---|",
        _fmt_row("ALL SIGNALS", top),
    ]
    for name, s in grades.items():
        lines.append(_fmt_row(name, s))
    lines += [
        "",
        "## Baselines (same tickers, same window)",
        f"- Random entry ({rnd['n']} samples, seeded): "
        + " · ".join(f"fwd {h}: " + ("—" if rnd.get(f'fwd_{h}') is None
                     else f"{rnd[f'fwd_{h}'] * 100:+.1f}%") for h in CONFIG.fwd_return_bars),
        f"- Buy & hold ({bh['n']} tickers): "
        + ("—" if bh.get("total_return") is None else f"{bh['total_return'] * 100:+.1f}%")
        + " mean total return over the replay window",
        "",
        "## The 50% rule, measured",
        f"- Signals that stalled (momentum zone touched): {stall['stalled']}",
        f"- Saved capital (hard floor broke first after the stall): {stall['saved_capital']}",
        f"- Cut a winner (T1 was still consumed first): {stall['cut_winner']}",
        f"- Neither within the tracking window: {stall['neither']}",
        "",
        f"In-sample = signals before {CONFIG.oos_split_date}; out-of-sample = after. "
        "If a cohort doesn't beat the baselines out-of-sample, the spec says cut "
        "it and note it here.",
        "",
        "Analysis only — not financial advice.",
        "",
    ]
    path = os.path.join(out_dir, f"{market}.md")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    return path


def write_public_stats(market: str, signals: list, rnd: dict, bh: dict,
                       universe_size: int, period: str) -> str:
    """Machine-readable cohorts for the Insights page (public/data/...), so
    the site's findings track the LATEST replay instead of rotting. Written
    on every backtest run; the weekly CI keeps it fresh."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out_dir = os.path.join(root, "public", "data", "phasemap", "stats")
    os.makedirs(out_dir, exist_ok=True)
    payload = {
        "market": market.upper(),
        "generated": datetime.date.today().isoformat(),
        "ruleset_version": RULESET_VERSION,
        "universe": universe_size,
        "period": period,
        "survivorship_bias": True,
        "all": summarise(signals),
        "cohorts": cohorts(signals),
        "stall": stall_summary(signals),
        "baselines": {"random": rnd, "buy_hold": bh},
    }
    path = os.path.join(out_dir, f"{market}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=1)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def write_stats(market: str, signals: list, out_dir: str = None) -> str:
    """The {stats} artefact. Only A+/A signals feed the narration claim, and
    run.py refuses the file when the sample is too small or the ruleset moved."""
    out_dir = out_dir or os.path.join(os.path.dirname(__file__), "stats")
    os.makedirs(out_dir, exist_ok=True)
    graded = [s for s in signals if s["tier"] in ("A+", "A")]
    hits = sum(1 for s in graded if s.get("t1_hit"))
    stats = {
        "market": market.upper(),
        "ruleset_version": RULESET_VERSION,
        "generated": datetime.date.today().isoformat(),
        "window_sessions": CONFIG.stats_window_bars,
        "sample": len(graded),
        "hit_rate_pct": round(100 * hits / len(graded)) if graded else None,
        "survivorship_bias": True,   # yfinance prototype — no delisted history
    }
    path = os.path.join(out_dir, f"{market}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(stats, fh, indent=2)
        fh.write("\n")
    return path
