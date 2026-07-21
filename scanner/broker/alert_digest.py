"""Daily and weekly performance digest alerts — Phase 8 Monitoring.

Builds a consolidated summary of the day's / week's trading and fires it as
a single alert instead of scattering individual event pings.

The daily digest fires at most once per ALERT_RATE_LIMITS["daily_report"]
seconds (default 23 h) so it naturally lands once per trading day.

The optional weekly digest is a richer report that runs when called from the
weekly summary workflow.

Called from bybit_run.run() at the end of every execution cycle via
maybe_send_digest().
"""

import datetime as dt
import logging

from scanner import config as _cfg
from scanner.scalp_journal import _session_day

log = logging.getLogger(__name__)


# ── builders ─────────────────────────────────────────────────────────────────

def build_daily_digest(
    report: dict,
    health: dict | None = None,
) -> str:
    """Build a human-readable daily digest string from the performance report."""
    today  = report.get("today", {})
    week   = report.get("week", {})
    exp    = report.get("expectancy", {})
    sday   = report.get("session_day", "")

    lines = [
        f"Daily Digest — {sday}",
        "",
        f"Today : {today.get('trades', 0)} trade(s)  "
        f"P&L ${today.get('pnl', 0):+.2f}  "
        f"Win {today.get('win_rate', 0):.0f}%  "
        f"Avg R {today.get('avg_r', 0):.2f}",
        f"Week  : {week.get('trades', 0)} trade(s)  "
        f"P&L ${week.get('pnl', 0):+.2f}  "
        f"Win {week.get('win_rate', 0):.0f}%  "
        f"Avg R {week.get('avg_r', 0):.2f}",
        f"Open  : {report.get('open_positions', 0)} position(s)  "
        f"Unrealised ${report.get('open_unrealised', 0):+.2f}",
    ]

    # Expectancy
    exp_r = exp.get("expectancy_r")
    if exp_r is not None:
        note = f"  [{exp['note']}]" if exp.get("note") else ""
        lines.append(
            f"Edge  : E={exp_r:.4f}R  "
            f"WR {exp.get('win_rate', 0):.0f}%  "
            f"AvgW {exp.get('avg_win_r', 0):.2f}R  "
            f"AvgL {exp.get('avg_loss_r', 0):.2f}R{note}"
        )

    # Streak commentary
    win_s  = report.get("current_win_streak", 0)
    loss_s = report.get("current_loss_streak", 0)
    if win_s >= 3:
        lines.append(f"Streak: {win_s} consecutive wins")
    elif loss_s >= 3:
        lines.append(f"Streak: {loss_s} consecutive losses — consider reviewing conditions")

    # Regime breakdown (week)
    regime = report.get("regime_breakdown", {})
    if regime:
        lines.append("")
        lines.append("Regime (week):")
        for name, s in regime.items():
            lines.append(
                f"  {name}: {s['trades']}t  "
                f"WR {s['win_rate']}%  P&L ${s['total_pnl']:+.2f}"
            )

    # System health summary (if provided)
    if health:
        overall = health.get("status", "OK")
        if overall != "OK":
            issues = "; ".join(
                v["message"]
                for v in health.get("checks", {}).values()
                if v.get("code", 0) >= 1
            )
            lines += ["", f"Health: {overall} — {issues}"]

    return "\n".join(lines)


def build_weekly_digest(journal: dict) -> str:
    """Build a weekly summary string (all trades from the past 7 calendar days)."""
    from scanner.broker.expectancy import calc_expectancy, by_regime

    now      = dt.datetime.now(dt.timezone.utc)
    week_ago = (now - dt.timedelta(days=7)).date().isoformat()
    countable = [t for t in journal.get("closed", []) if not t.get("skip_daily_count")]
    week_t    = [t for t in countable if t.get("session_day", "") >= week_ago]

    if not week_t:
        return "Weekly Digest: no countable trades in the past 7 days."

    exp       = calc_expectancy(week_t)
    regime    = by_regime(week_t)
    total_pnl = round(sum(t.get("pnl", 0) for t in week_t), 2)
    win_n     = sum(1 for t in week_t if t.get("pnl", 0) > 0)
    win_rate  = round(win_n / len(week_t) * 100, 1) if week_t else 0.0

    lines = [
        f"Weekly Digest — {(now - dt.timedelta(days=7)).date()} → {now.date()}",
        "",
        f"Trades : {len(week_t)}  "
        f"P&L ${total_pnl:+.2f}  "
        f"Win rate {win_rate}%",
        f"Edge   : E={exp['expectancy_r']:.4f}R  "
        f"AvgW {exp['avg_win_r']:.2f}R  "
        f"AvgL {exp['avg_loss_r']:.2f}R",
    ]

    if regime:
        lines += ["", "By regime:"]
        for name, s in regime.items():
            lines.append(
                f"  {name}: {s['trades']}t  "
                f"WR {s['win_rate']:.0f}%  "
                f"E={s['expectancy_r']:.4f}R"
            )

    return "\n".join(lines)


# ── dispatch helpers ──────────────────────────────────────────────────────────

def maybe_send_digest(report: dict, health: dict | None = None) -> bool:
    """Send the daily digest if there are trades today and the rate limit allows.

    Returns True if the digest was dispatched.
    """
    from .alert_router import smart_send

    if report.get("today", {}).get("trades", 0) == 0:
        return False

    text = build_daily_digest(report, health)
    smart_send("daily_report", "Daily Trading Digest", text)
    log.info("daily digest dispatched")
    return True


def maybe_send_weekly_digest(journal: dict) -> bool:
    """Send the weekly digest (designed to be called from a weekly workflow).

    Returns True if the digest was dispatched.
    """
    from .alert_router import smart_send

    countable = [t for t in journal.get("closed", []) if not t.get("skip_daily_count")]
    now       = dt.datetime.now(dt.timezone.utc)
    week_ago  = (now - dt.timedelta(days=7)).date().isoformat()
    week_t    = [t for t in countable if t.get("session_day", "") >= week_ago]

    if not week_t:
        return False

    text = build_weekly_digest(journal)
    # Use a separate event_type so the weekly digest gets its own rate-limit bucket
    smart_send("weekly_report", "Weekly Performance Summary", text)
    log.info("weekly digest dispatched  trades=%d", len(week_t))
    return True
