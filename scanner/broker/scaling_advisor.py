"""Stage 4 capital-scaling milestone advisor — Phase 6 Live Deployment Protocol.

Checks whether the live journal meets the conditions to advance to the next
scaling level and emits a recommendation string.

Levels (from the Phase 6 protocol):
  Level 0  Not yet qualifying for any capital increase
  Level 1  4+ profitable completed weeks + current drawdown < 5%
           → increase capital by ~37.5% (midpoint of 25–50% range)
  Level 2  Another 4+ profitable completed weeks + drawdown < 6%
           → increase capital by another ~37.5%
  Level 3  Consistent performance over 3+ months → move to normal risk parameters
  Level 4  Proven over 6+ months with controlled drawdowns → scale more aggressively

Levels 3 and 4 are advisory only (no automated action); they require manual review.

Called from bybit_run.run() at the end of every execution cycle so the
recommendation is always fresh in the log.
"""

import datetime as dt
import logging

from scanner import config as _cfg
from scanner.broker.risk_manager import current_drawdown

log = logging.getLogger(__name__)


def _iso_week(day: str) -> str:
    """Return 'YYYY-WNN' from a YYYY-MM-DD session_day."""
    try:
        d   = dt.date.fromisoformat(day[:10])
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except Exception:
        return ""


def _current_iso_week() -> str:
    iso = dt.date.today().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _weekly_pnl(closed: list[dict]) -> dict[str, float]:
    """Aggregate realised PnL by ISO week, excluding stop-gapped trades."""
    weeks: dict[str, float] = {}
    for t in closed:
        if t.get("skip_daily_count"):
            continue
        week = _iso_week(t.get("session_day", ""))
        if week:
            weeks[week] = weeks.get(week, 0.0) + t.get("pnl", 0)
    return weeks


def profitable_weeks_streak(journal: dict) -> int:
    """Count consecutive profitable completed calendar weeks (most recent first).

    The current (incomplete) week is excluded so an in-progress bad week
    doesn't prematurely break a good streak.
    """
    closed  = [t for t in journal.get("closed", []) if not t.get("skip_daily_count")]
    weekly  = _weekly_pnl(closed)
    current = _current_iso_week()

    # Remove the current (potentially incomplete) week
    past = {w: pnl for w, pnl in weekly.items() if w != current}
    if not past:
        return 0

    streak = 0
    for week in sorted(past.keys(), reverse=True):
        if past[week] > 0:
            streak += 1
        else:
            break
    return streak


def total_completed_weeks(journal: dict) -> int:
    """Count how many distinct completed calendar weeks have any trade data."""
    closed  = [t for t in journal.get("closed", []) if not t.get("skip_daily_count")]
    current = _current_iso_week()
    weeks   = {_iso_week(t.get("session_day", "")) for t in closed}
    weeks.discard(current)
    weeks.discard("")
    return len(weeks)


def check_stage4_milestones(journal: dict) -> dict:
    """Evaluate Stage 4 scaling milestones.

    Returns:
      {
        current_level          int      highest level whose conditions are currently met
        conditions_met         bool     True if current_level >= 1
        profitable_weeks_streak int     consecutive profitable completed weeks
        completed_weeks_total  int      total completed weeks with trade data
        current_dd_pct         float    current drawdown as a percentage
        l1_min_weeks           int
        l1_max_dd_pct          float
        l1_capital_bump_pct    float
        l2_min_weeks           int
        l2_max_dd_pct          float
        l2_capital_bump_pct    float
        recommendation         str
      }
    """
    dd     = current_drawdown(journal)
    streak = profitable_weeks_streak(journal)
    total  = total_completed_weeks(journal)

    l1_weeks = int(getattr(_cfg, "LIVE_STAGE4_L1_MIN_WEEKS", 4))
    l1_dd    = float(getattr(_cfg, "LIVE_STAGE4_L1_MAX_DD",   0.05))
    l1_bump  = float(getattr(_cfg, "LIVE_STAGE4_L1_BUMP",     0.375))
    l2_weeks = int(getattr(_cfg, "LIVE_STAGE4_L2_MIN_WEEKS", 4))
    l2_dd    = float(getattr(_cfg, "LIVE_STAGE4_L2_MAX_DD",   0.06))
    l2_bump  = float(getattr(_cfg, "LIVE_STAGE4_L2_BUMP",     0.375))

    l1_met = streak >= l1_weeks and dd < l1_dd
    l2_met = l1_met and streak >= l1_weeks + l2_weeks and dd < l2_dd
    l3_met = total >= 13   # ~3 months of weekly data
    l4_met = total >= 26   # ~6 months

    current_level = 0
    if l1_met:
        current_level = 1
    if l2_met:
        current_level = 2
    if l3_met and current_level >= 2:
        current_level = 3
    if l4_met and current_level >= 3:
        current_level = 4

    # Build recommendation
    if current_level == 0:
        need_weeks = max(0, l1_weeks - streak)
        reco = (
            f"Not yet at Level 1. Need {need_weeks} more profitable week(s) "
            f"with drawdown < {l1_dd:.0%}. "
            f"Current: {streak} profitable week streak, DD {dd:.1%}."
        )
    elif current_level == 1:
        need_weeks = max(0, l1_weeks + l2_weeks - streak)
        reco = (
            f"Level 1 met — eligible to increase capital by {l1_bump:.0%}. "
            f"Work toward Level 2: need {need_weeks} more profitable week(s) "
            f"with DD < {l2_dd:.0%}."
        )
    elif current_level == 2:
        reco = (
            f"Level 2 met — eligible for another {l2_bump:.0%} capital increase. "
            f"Maintain consistent performance for 3+ months ({13 - total} more weeks) "
            f"to reach Level 3 (normal risk parameters)."
        )
    elif current_level == 3:
        reco = (
            "Level 3 met — move to normal risk parameters. "
            f"Continue for {26 - total} more weeks of proven performance to reach Level 4."
        )
    else:
        reco = (
            "Level 4 met — proven over 6+ months with controlled drawdowns. "
            "You may scale more aggressively with discipline."
        )

    if current_level >= 1:
        log.info(
            "scaling advisor: Level %d conditions met — %s",
            current_level, reco,
        )

    return {
        "current_level":             current_level,
        "conditions_met":            current_level >= 1,
        "profitable_weeks_streak":   streak,
        "completed_weeks_total":     total,
        "current_dd_pct":            round(dd * 100, 2),
        "l1_min_weeks":              l1_weeks,
        "l1_max_dd_pct":             round(l1_dd  * 100, 1),
        "l1_capital_bump_pct":       round(l1_bump * 100, 1),
        "l2_min_weeks":              l2_weeks,
        "l2_max_dd_pct":             round(l2_dd  * 100, 1),
        "l2_capital_bump_pct":       round(l2_bump * 100, 1),
        "recommendation":            reco,
    }
