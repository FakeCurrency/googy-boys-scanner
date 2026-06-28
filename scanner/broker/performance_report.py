"""Automated performance reporting — daily/weekly summary of the scalp journal.

Writes public/data/performance.json consumed by the frontend dashboard.
Optionally sends a formatted email when SMTP is configured.

Called from bybit_run.run() after each execution cycle.
"""

import datetime as dt
import json
import logging
import pathlib
import statistics

from scanner.scalp_journal import _session_day
from scanner.journal_common import atomic_write as _atomic_write

log = logging.getLogger(__name__)

ROOT             = pathlib.Path(__file__).resolve().parents[2]
PERF_FILE        = ROOT / "public" / "data" / "performance.json"
HEALTH_SNAP_FILE = ROOT / "public" / "data" / "health_runtime.json"


def _win_rate(trades: list[dict]) -> float:
    if not trades:
        return 0.0
    return round(sum(1 for t in trades if t.get("pnl", 0) > 0) / len(trades) * 100, 1)


def _avg_r(trades: list[dict]) -> float:
    rs = [t["r"] for t in trades if t.get("r") is not None]
    return round(statistics.mean(rs), 2) if rs else 0.0


def _avg_pnl(trades: list[dict]) -> float:
    if not trades:
        return 0.0
    return round(sum(t.get("pnl", 0) for t in trades) / len(trades), 2)


def _streak(trades: list[dict]) -> tuple[int, int]:
    """(current_win_streak, current_loss_streak) from most-recent closed trades."""
    wins = losses = 0
    for t in reversed(trades):
        if t.get("pnl", 0) > 0:
            if losses:
                break
            wins += 1
        else:
            if wins:
                break
            losses += 1
    return wins, losses


def _regime_breakdown(trades: list[dict]) -> dict:
    groups: dict[str, list] = {}
    for t in trades:
        groups.setdefault(t.get("market_regime", "unknown"), []).append(t)
    return {
        regime: {
            "trades":    len(ts),
            "win_rate":  _win_rate(ts),
            "total_pnl": round(sum(t.get("pnl", 0) for t in ts), 2),
            "avg_r":     _avg_r(ts),
        }
        for regime, ts in groups.items()
    }


def _direction_breakdown(trades: list[dict]) -> dict:
    out = {}
    for direction in ("long", "short"):
        ts = [t for t in trades if t.get("direction") == direction]
        if ts:
            out[direction] = {
                "trades":    len(ts),
                "win_rate":  _win_rate(ts),
                "total_pnl": round(sum(t.get("pnl", 0) for t in ts), 2),
            }
    return out


def build_report(j: dict) -> dict:
    """Build a performance summary dict from the full journal."""
    from .expectancy import calc_expectancy

    now        = dt.datetime.now(dt.timezone.utc)
    today_key  = _session_day(now.isoformat())
    countable  = [t for t in j.get("closed", []) if not t.get("skip_daily_count")]

    seven_ago  = (now - dt.timedelta(days=7)).date().isoformat()
    thirty_ago = (now - dt.timedelta(days=30)).date().isoformat()

    today_t = [t for t in countable if t.get("session_day") == today_key]
    week_t  = [t for t in countable if t.get("session_day", "") >= seven_ago]
    month_t = [t for t in countable if t.get("session_day", "") >= thirty_ago]

    open_unreal = round(sum(p.get("unreal_pnl") or 0 for p in j.get("open", [])), 2)
    win_s, loss_s = _streak(countable)

    return {
        "generated_at":        now.isoformat(timespec="seconds"),
        "session_day":         today_key,
        "open_positions":      len(j.get("open", [])),
        "open_unrealised":     open_unreal,
        "current_win_streak":  win_s,
        "current_loss_streak": loss_s,

        "today": {
            "trades":   len(today_t),
            "pnl":      round(sum(t.get("pnl", 0) for t in today_t), 2),
            "win_rate": _win_rate(today_t),
            "avg_r":    _avg_r(today_t),
        },
        "week": {
            "trades":   len(week_t),
            "pnl":      round(sum(t.get("pnl", 0) for t in week_t), 2),
            "win_rate": _win_rate(week_t),
            "avg_r":    _avg_r(week_t),
            "avg_pnl":  _avg_pnl(week_t),
        },
        "month": {
            "trades":   len(month_t),
            "pnl":      round(sum(t.get("pnl", 0) for t in month_t), 2),
            "win_rate": _win_rate(month_t),
            "avg_r":    _avg_r(month_t),
            "avg_pnl":  _avg_pnl(month_t),
        },
        "all_time": {
            "trades":   len(countable),
            "pnl":      round(sum(t.get("pnl", 0) for t in countable), 2),
            "win_rate": _win_rate(countable),
            "avg_r":    _avg_r(countable),
        },

        "expectancy":          calc_expectancy(countable),
        "regime_breakdown":    _regime_breakdown(week_t),
        "direction_breakdown": _direction_breakdown(week_t),
    }


def write_report(j: dict) -> dict:
    """Build and persist the performance report. Returns the report dict."""
    report  = build_report(j)
    payload = json.dumps(report, indent=2)
    PERF_FILE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(PERF_FILE, payload)

    exp = report.get("expectancy", {})
    log.info(
        "performance report written  trades_all=%d  total_pnl=%.2f  "
        "week_wr=%.1f%%  week_avg_r=%.2f  expectancy=%.4fR",
        report["all_time"]["trades"], report["all_time"]["pnl"],
        report["week"]["win_rate"], report["week"]["avg_r"],
        exp.get("expectancy_r", 0),
    )

    # Write detailed expectancy breakdown separately
    try:
        from .expectancy import write_expectancy
        write_expectancy(j)
    except Exception as e:
        log.warning("expectancy report failed: %s", e)

    return report


def write_health_runtime(j: dict) -> None:
    """Write public/data/health_runtime.json with live system-state indicators.

    Provides the health dashboard with data that is only available during a
    bybit_run execution: open risk, circuit-breaker state, recent warnings.

    This is a complement to health.json (written by the scanner) and the
    health_check.py script (which reads both files).
    """
    from .risk_manager import portfolio_heat, current_drawdown
    from .circuit_breaker import check_all as _cb_check

    open_positions = j.get("open", [])
    heat = round(portfolio_heat(open_positions) * 100, 2)
    dd   = round(current_drawdown(j) * 100, 2)

    cb = {"ok": True, "failed": [], "reason": ""}
    try:
        result = _cb_check(j)
        cb = {"ok": result["ok"], "failed": result["failed"], "reason": result["reason"]}
    except Exception as e:
        cb = {"ok": False, "failed": ["check_error"], "reason": str(e)}

    snapshot = {
        "generated_at":        dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "open_positions":      len(open_positions),
        "open_risk_pct":       heat,
        "current_drawdown_pct": dd,
        "circuit_breakers":    cb,
        "open_symbols":        [p.get("symbol") for p in open_positions],
    }

    HEALTH_SNAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(HEALTH_SNAP_FILE, json.dumps(snapshot, indent=2))
    log.info(
        "health runtime snapshot  open=%d  heat=%.1f%%  dd=%.1f%%  cb_ok=%s",
        len(open_positions), heat, dd, cb["ok"],
    )


def maybe_send_daily_report(report: dict) -> None:
    """Email the daily performance summary if SMTP is configured and there are trades."""
    from .alert_dispatch import _email

    today = report["today"]
    if today["trades"] == 0:
        return

    week = report["week"]
    lines = [
        f"Daily Summary — {report['session_day']}",
        "",
        f"Today : {today['trades']} trade(s)  P&L ${today['pnl']:+.2f}  "
        f"Win rate {today['win_rate']}%  Avg R {today['avg_r']:.2f}",
        f"Week  : {week['trades']} trade(s)  P&L ${week['pnl']:+.2f}  "
        f"Win rate {week['win_rate']}%  Avg R {week['avg_r']:.2f}",
        f"Open  : {report['open_positions']} position(s)  "
        f"Unrealised ${report['open_unrealised']:+.2f}",
        "",
        "Regime breakdown (week):",
    ]
    for regime, stats in report.get("regime_breakdown", {}).items():
        lines.append(f"  {regime}: {stats['trades']} trades  "
                     f"win {stats['win_rate']}%  P&L ${stats['total_pnl']:+.2f}")

    if report["current_loss_streak"] >= 3:
        lines.append(f"\n⚠️  {report['current_loss_streak']} consecutive losses — "
                     "consider reviewing conditions.")

    subject = (f"Vivek 5.0 — Daily Report {report['session_day']}  "
               f"P&L ${today['pnl']:+.2f}")
    if _email(subject, "\n".join(lines)):
        log.info("daily report email sent")
