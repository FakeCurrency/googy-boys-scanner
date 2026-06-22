"""Performance attribution by engine, regime, time of day, and slippage.

Supplements expectancy.py (which covers overall stats, by_regime, by_hour)
with attribution angles that aren't available there:
  - by_engine          — which scanner/strategy type produced the trades
  - slippage_by_symbol — per-symbol average fill quality
  - slippage_by_hour   — time-of-day fill quality (UTC hour)

Writes public/data/attribution.json after every bybit_run cycle.

The "by_regime" and "by_session_hour" breakdowns in attribution.json reuse
the expectancy module to avoid duplicating the calculation logic.
"""

import datetime as dt
import json
import logging
import pathlib
import statistics

from scanner.scalp_journal import _atomic_write

log      = logging.getLogger(__name__)
ROOT     = pathlib.Path(__file__).resolve().parents[2]
OUT_FILE = ROOT / "public" / "data" / "attribution.json"


# ── helpers ───────────────────────────────────────────────────────────────────

def _slip_stats(positions: list[dict]) -> dict:
    """Aggregate slippage statistics for a group of positions."""
    slips = [
        float(p["entry_slip_pct"])
        for p in positions
        if p.get("entry_slip_pct") is not None
    ]
    if not slips:
        return {"count": 0, "avg_slip_pct": None, "max_slip_pct": None, "p50_slip_pct": None}
    return {
        "count":        len(slips),
        "avg_slip_pct": round(statistics.mean(slips),   4),
        "max_slip_pct": round(max(slips),               4),
        "p50_slip_pct": round(statistics.median(slips), 4),
    }


def _perf_stats(trades: list[dict]) -> dict:
    """Compact performance stats (trades, win_rate, total_pnl, avg_r)."""
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "total_pnl": 0.0, "avg_r": 0.0}
    wins = [t for t in trades if t.get("pnl", 0) > 0]
    rs   = [float(t["r"]) for t in trades if t.get("r") is not None]
    return {
        "trades":    len(trades),
        "win_rate":  round(len(wins) / len(trades) * 100, 1),
        "total_pnl": round(sum(t.get("pnl", 0) for t in trades), 2),
        "avg_r":     round(statistics.mean(rs), 3) if rs else 0.0,
    }


# ── attribution functions ─────────────────────────────────────────────────────

def by_engine(closed: list[dict]) -> dict[str, dict]:
    """Performance breakdown by scanner engine / strategy type.

    Uses the "engine" field if present on a trade, otherwise falls back to
    "scan_type", then defaults to "scalp" (since bybit_run only processes
    scalp signals).  The field is populated when bybit_run builds the pos dict.
    """
    from scanner.broker.expectancy import calc_expectancy

    groups: dict[str, list] = {}
    for t in closed:
        engine = t.get("engine") or t.get("scan_type") or "scalp"
        groups.setdefault(engine, []).append(t)

    return {
        engine: {
            **calc_expectancy(trades),
            "total_pnl": round(sum(t.get("pnl", 0) for t in trades), 2),
        }
        for engine, trades in sorted(groups.items())
    }


def by_direction(closed: list[dict]) -> dict[str, dict]:
    """Performance breakdown by trade direction (long / short)."""
    groups: dict[str, list] = {}
    for t in closed:
        direction = t.get("direction", "unknown")
        groups.setdefault(direction, []).append(t)
    return {d: _perf_stats(ts) for d, ts in sorted(groups.items())}


def slippage_by_symbol(closed: list[dict]) -> dict[str, dict]:
    """Per-symbol average fill-quality metrics (live/testnet trades only)."""
    groups: dict[str, list] = {}
    for t in closed:
        if t.get("entry_slip_pct") is None:
            continue
        sym = t.get("symbol", "UNKNOWN")
        groups.setdefault(sym, []).append(t)
    return {sym: _slip_stats(trades) for sym, trades in sorted(groups.items())}


def slippage_by_hour(closed: list[dict]) -> dict[int, dict]:
    """Fill-quality breakdown by UTC hour the trade was opened."""
    groups: dict[int, list] = {}
    for t in closed:
        if t.get("entry_slip_pct") is None:
            continue
        ts_str = t.get("opened_ts", "")
        try:
            hour = dt.datetime.fromisoformat(ts_str).hour
        except Exception:
            continue
        groups.setdefault(hour, []).append(t)
    return {hour: _slip_stats(trades) for hour, trades in sorted(groups.items())}


def grade_breakdown(closed: list[dict]) -> dict[str, dict]:
    """Performance breakdown by signal grade (A+, A, B, etc.)."""
    groups: dict[str, list] = {}
    for t in closed:
        grade = t.get("grade", "unknown")
        groups.setdefault(grade, []).append(t)
    return {g: _perf_stats(ts) for g, ts in sorted(groups.items())}


# ── report builder ────────────────────────────────────────────────────────────

def build_attribution_report(journal: dict) -> dict:
    """Build the full attribution report dict."""
    from scanner.broker.expectancy import by_regime, by_session_hour

    countable = [t for t in journal.get("closed", []) if not t.get("skip_daily_count")]

    return {
        "generated_at":       dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "total_trades":       len(countable),
        "by_engine":          by_engine(countable),
        "by_direction":       by_direction(countable),
        "by_grade":           grade_breakdown(countable),
        "by_regime":          by_regime(countable),
        "by_session_hour":    {
            str(h): v for h, v in by_session_hour(countable).items()
        },
        "slippage_by_symbol": slippage_by_symbol(countable),
        "slippage_by_hour":   {
            str(h): v for h, v in slippage_by_hour(countable).items()
        },
    }


def write_attribution(journal: dict) -> dict:
    """Build and persist the attribution report. Returns the report dict."""
    report = build_attribution_report(journal)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(OUT_FILE, json.dumps(report, indent=2))
    log.info(
        "attribution report written  trades=%d  engines=%s  regimes=%s",
        report["total_trades"],
        ",".join(report["by_engine"].keys()) or "none",
        ",".join(report["by_regime"].keys()) or "none",
    )
    return report
