"""Stage 2 fill-price slippage analysis — Phase 6 Live Deployment Protocol.

Reads entry_slip_pct values recorded by bybit_reconcile and aggregates them
into weekly and all-time summaries written to public/data/fill_analysis.json.

Metrics:
  entry_slip_pct  — (fill_price − intended_entry) / intended_entry × 100
                    positive = filled worse than scan price (paid more for long / received
                    less for short); negative = filled better.
  slip_in_r       — entry_slip_pct / (risk_distance_pct); expresses slippage as a
                    fraction of the trade's risk, so 0.10 R means the fill cost 10%
                    of one unit of risk.
  rejection_rate  — orders that were skipped vs total signals evaluated (logged, not
                    directly available in the journal; this module estimates from
                    skip reason fields if present).

Called from bybit_run.run() after every execution cycle.
"""

import datetime as dt
import json
import logging
import pathlib
import statistics

from scanner.scalp_journal import _atomic_write
from scanner import config as _cfg

log      = logging.getLogger(__name__)
ROOT     = pathlib.Path(__file__).resolve().parents[2]
OUT_FILE = ROOT / "public" / "data" / "fill_analysis.json"


def _iso_week(day: str) -> str:
    """Return 'YYYY-WNN' ISO week key from a YYYY-MM-DD session_day."""
    try:
        d   = dt.date.fromisoformat(day[:10])
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except Exception:
        return "unknown"


def _slip_in_r(slip_pct: float, entry: float, stop: float) -> float | None:
    """Express slip_pct as a fraction of the trade's risk distance."""
    if not entry or not stop or entry <= 0 or stop <= 0:
        return None
    risk_dist_pct = abs(entry - stop) / entry * 100
    if risk_dist_pct <= 0:
        return None
    return round(slip_pct / risk_dist_pct, 3)


def compute_trade_metrics(pos: dict) -> dict | None:
    """Return slip metrics for one closed position, or None if no fill data."""
    slip_pct = pos.get("entry_slip_pct")
    if slip_pct is None:
        return None

    entry = float(pos.get("entry") or 0)
    stop  = float(pos.get("stop")  or 0)

    return {
        "symbol":        pos.get("symbol"),
        "direction":     pos.get("direction"),
        "session_day":   pos.get("session_day", ""),
        "entry":         round(entry, 6),
        "fill_price":    pos.get("fill_price"),
        "entry_slip_pct": round(float(slip_pct), 4),
        "slip_in_r":     _slip_in_r(float(slip_pct), entry, stop),
        "pnl":           pos.get("pnl"),
        "r":             pos.get("r"),
    }


def weekly_fill_report(closed: list[dict]) -> list[dict]:
    """Aggregate per-trade slip metrics into weekly summaries.

    Returns a list of week dicts sorted most-recent first, e.g.:
      [{"week": "2026-W25", "trades": 8, "avg_slip_pct": 0.042, "avg_slip_r": 0.11}, ...]
    """
    min_trades = int(getattr(_cfg, "FILL_ANALYSIS_MIN_TRADES", 5))
    weeks: dict[str, list[float]] = {}
    weeks_r:  dict[str, list[float]] = {}

    for pos in closed:
        if pos.get("skip_daily_count"):
            continue
        m = compute_trade_metrics(pos)
        if m is None:
            continue
        w = _iso_week(m["session_day"])
        weeks.setdefault(w, []).append(m["entry_slip_pct"])
        if m["slip_in_r"] is not None:
            weeks_r.setdefault(w, []).append(m["slip_in_r"])

    rows = []
    for week in sorted(weeks.keys(), reverse=True):
        slips = weeks[week]
        rs    = weeks_r.get(week, [])
        rows.append({
            "week":          week,
            "trades":        len(slips),
            "avg_slip_pct":  round(statistics.mean(slips), 4) if len(slips) >= min_trades else None,
            "avg_slip_r":    round(statistics.mean(rs),    3) if len(rs)    >= min_trades else None,
            "max_slip_pct":  round(max(slips), 4),
            "min_slip_pct":  round(min(slips), 4),
            "note":          "insufficient_trades" if len(slips) < min_trades else "",
        })
    return rows


def all_time_summary(closed: list[dict]) -> dict:
    """Overall slippage summary across all filled trades."""
    slips, rs = [], []
    filled = 0

    for pos in closed:
        if pos.get("skip_daily_count"):
            continue
        m = compute_trade_metrics(pos)
        if m is None:
            continue
        filled += 1
        slips.append(m["entry_slip_pct"])
        if m["slip_in_r"] is not None:
            rs.append(m["slip_in_r"])

    if not slips:
        return {"filled_trades": 0, "avg_slip_pct": None, "avg_slip_r": None}

    return {
        "filled_trades": filled,
        "avg_slip_pct":  round(statistics.mean(slips), 4),
        "avg_slip_r":    round(statistics.mean(rs), 3) if rs else None,
        "max_slip_pct":  round(max(slips), 4),
        "p50_slip_pct":  round(statistics.median(slips), 4),
        "stdev_slip_pct": round(statistics.stdev(slips), 4) if len(slips) > 1 else None,
    }


def write_fill_analysis(journal: dict) -> dict:
    """Build and persist fill analysis report. Returns the report dict."""
    closed  = journal.get("closed", [])
    weekly  = weekly_fill_report(closed)
    summary = all_time_summary(closed)

    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "all_time":     summary,
        "by_week":      weekly,
    }

    if summary["filled_trades"] > 0:
        log.info(
            "fill analysis  filled=%d  avg_slip=%.3f%%  avg_slip_r=%s",
            summary["filled_trades"],
            summary["avg_slip_pct"] or 0,
            f"{summary['avg_slip_r']:.3f}" if summary.get("avg_slip_r") is not None else "n/a",
        )

        # Warn if average slippage is materially worse than expected
        warn_pct = float(getattr(_cfg, "SLIPPAGE_WARN_PCT", 0.003)) * 100
        avg      = summary.get("avg_slip_pct") or 0
        if avg > warn_pct:
            log.warning(
                "fill analysis: avg entry slippage %.3f%% > warn threshold %.3f%% "
                "— consider reducing position size or adding slippage tolerance",
                avg, warn_pct,
            )

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(OUT_FILE, json.dumps(report, indent=2))
    return report
