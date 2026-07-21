"""Edge / expectancy calculator for the scalp journal — Phase 7.

Classical expectancy per dollar risked:
    E = (win_rate × avg_win_R) − ((1 − win_rate) × avg_loss_R)

A positive E means the strategy earns more per winner than it loses per loser
on a risk-adjusted basis.  E = 0.25 means $0.25 earned per $1 risked on average.

Computes:
  all_time   — overall expectancy across all countable closed trades
  by_regime  — expectancy per market_regime label
  by_hour    — expectancy per UTC hour the trade was opened (time-of-day edge)

Writes public/data/expectancy.json after every bybit_run cycle (via
performance_report.write_report).  Fires a WARNING alert if expectancy goes
negative once the sample reaches EXPECTANCY_MIN_TRADES.
"""

import datetime as dt
import json
import logging
import pathlib
import statistics

from scanner import config as _cfg
from scanner.journal_common import atomic_write as _atomic_write

log      = logging.getLogger(__name__)
ROOT     = pathlib.Path(__file__).resolve().parents[2]
OUT_FILE = ROOT / "public" / "data" / "expectancy.json"


def _r_vals(trades: list[dict]) -> list[float]:
    return [float(t["r"]) for t in trades if t.get("r") is not None]


def calc_expectancy(trades: list[dict]) -> dict:
    """Compute expectancy for a list of trades.

    Returns a dict with:
      trades, win_rate, avg_win_r, avg_loss_r, edge_ratio,
      expectancy_r, expectancy_usd, note
    """
    rs = _r_vals(trades)
    empty = {
        "trades": 0, "win_rate": 0.0,
        "avg_win_r": 0.0, "avg_loss_r": 0.0,
        "edge_ratio": None, "expectancy_r": 0.0,
        "expectancy_usd": 0.0, "note": "",
    }
    if not rs:
        return empty

    wins   = [r for r in rs if r >  0]
    losses = [r for r in rs if r <= 0]

    win_rate   = len(wins) / len(rs)
    avg_win_r  = round(statistics.mean(wins),        3) if wins   else 0.0
    avg_loss_r = round(abs(statistics.mean(losses)), 3) if losses else 0.0
    edge_ratio = round(avg_win_r / avg_loss_r, 3)        if avg_loss_r > 0 else None
    exp_r      = round(
        (win_rate * avg_win_r) - ((1.0 - win_rate) * avg_loss_r), 4,
    )
    risk_usd   = float(_cfg.SCALP_RISK_PER_TRADE)
    min_t      = int(_cfg.EXPECTANCY_MIN_TRADES)

    note = (
        f"low_sample ({len(rs)}<{min_t}) — estimate unreliable"
        if len(rs) < min_t else ""
    )

    return {
        "trades":         len(rs),
        "win_rate":       round(win_rate * 100, 1),
        "avg_win_r":      avg_win_r,
        "avg_loss_r":     avg_loss_r,
        "edge_ratio":     edge_ratio,
        "expectancy_r":   exp_r,
        "expectancy_usd": round(exp_r * risk_usd, 2),
        "note":           note,
    }


def by_regime(trades: list[dict]) -> dict[str, dict]:
    """Expectancy broken down by market_regime."""
    groups: dict[str, list] = {}
    for t in trades:
        groups.setdefault(t.get("market_regime", "unknown"), []).append(t)
    return {regime: calc_expectancy(ts) for regime, ts in sorted(groups.items())}


def by_session_hour(trades: list[dict]) -> dict[int, dict]:
    """Expectancy broken down by the UTC hour the trade was opened.

    Helps identify which times of day the strategy performs better or worse.
    """
    buckets: dict[int, list] = {}
    for t in trades:
        ts = t.get("opened_ts", "")
        try:
            hour = dt.datetime.fromisoformat(ts).hour
        except Exception:
            continue
        buckets.setdefault(hour, []).append(t)
    return {h: calc_expectancy(ts) for h, ts in sorted(buckets.items())}


def build_expectancy_report(journal: dict) -> dict:
    countable = [t for t in journal.get("closed", []) if not t.get("skip_daily_count")]
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "all_time":     calc_expectancy(countable),
        "by_regime":    by_regime(countable),
        "by_hour_utc":  by_session_hour(countable),
    }


def write_expectancy(journal: dict) -> dict:
    """Build and persist the expectancy report. Returns the report dict."""
    report = build_expectancy_report(journal)
    exp    = report["all_time"]

    if exp["trades"] > 0:
        note_str = f"  [{exp['note']}]" if exp.get("note") else ""
        log.info(
            "expectancy  trades=%d  E=%.4fR ($%.2f/trade)  "
            "wr=%.1f%%  avg_win=%.3fR  avg_loss=%.3fR  edge=%s%s",
            exp["trades"], exp["expectancy_r"], exp["expectancy_usd"],
            exp["win_rate"], exp["avg_win_r"], exp["avg_loss_r"],
            f"{exp['edge_ratio']:.3f}" if exp["edge_ratio"] else "n/a",
            note_str,
        )

        # Alert if strategy edge has degraded to negative expectancy
        min_t = int(_cfg.EXPECTANCY_MIN_TRADES)
        if exp["expectancy_r"] < 0 and exp["trades"] >= min_t:
            try:
                from .alert_router import smart_send
                smart_send(
                    "anomaly",
                    "Negative strategy expectancy detected",
                    f"E = {exp['expectancy_r']:.4f} R over {exp['trades']} trades. "
                    f"Win rate {exp['win_rate']}%, avg win {exp['avg_win_r']} R, "
                    f"avg loss {exp['avg_loss_r']} R. "
                    "Consider reviewing regime detection and recent slippage.",
                )
            except Exception:
                pass

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(OUT_FILE, json.dumps(report, indent=2))
    return report
