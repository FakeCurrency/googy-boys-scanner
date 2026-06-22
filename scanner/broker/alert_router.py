"""Smart alert routing — Phase 7 Advanced Monitoring & Alerting.

Wraps alert_dispatch with:
  - Severity-based channel selection
      CRITICAL → Telegram + Discord + Email
      WARNING  → Telegram + Discord
      INFO     → log only (no push)
  - Per-event-type rate limiting to prevent alert storms
  - State persisted to journal/alert_state.json so rate limits
    survive across separate GitHub Actions runs

Entry point:
  smart_send(event_type, title, details)

All existing callers of alert_dispatch.send() continue to work unchanged.
New code should prefer smart_send() so routing rules are applied.
"""

import datetime as dt
import json
import logging
import pathlib

from scanner import config as _cfg
from scanner.scalp_journal import _atomic_write

log = logging.getLogger(__name__)

ROOT       = pathlib.Path(__file__).resolve().parents[2]
STATE_FILE = ROOT / "journal" / "alert_state.json"

# Fallback tables (overridden by scanner/config.py values when present)
_SEV_MAP = {
    "kill_switch":     "CRITICAL",
    "daily_loss":      "CRITICAL",
    "order_failed":    "CRITICAL",
    "scan_error":      "CRITICAL",
    "order_placed":    "INFO",
    "order_rejected":  "WARNING",
    "anomaly":         "WARNING",
    "circuit_breaker": "WARNING",
    "daily_report":    "INFO",
    "health":          "WARNING",
    "info":            "INFO",
}

_CHAN_MAP = {
    "CRITICAL": ["telegram", "discord", "email"],
    "WARNING":  ["telegram", "discord"],
    "INFO":     [],
}

_RATE_MAP = {
    "kill_switch":     0,
    "daily_loss":      0,
    "order_failed":    0,
    "scan_error":      0,
    "order_placed":    300,
    "order_rejected":  300,
    "anomaly":         1800,
    "circuit_breaker": 1800,
    "daily_report":    82800,
    "health":          3600,
    "DEFAULT":         300,
}


# ── state file helpers ────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_sent": {}}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        _atomic_write(STATE_FILE, json.dumps(state, indent=2))
    except Exception as e:
        log.warning("alert_router: could not save state: %s", e)


# ── public helpers ────────────────────────────────────────────────────────────

def get_severity(event_type: str) -> str:
    """Return severity level string for an event_type."""
    sev_map = getattr(_cfg, "ALERT_SEVERITY", _SEV_MAP)
    return sev_map.get(event_type, "WARNING")


def get_channels(event_type: str, severity: str = "") -> list[str]:
    """Return which channels should receive an alert for event_type."""
    if not severity:
        severity = get_severity(event_type)
    chan_map = getattr(_cfg, "ALERT_CHANNELS", _CHAN_MAP)
    return list(chan_map.get(severity, _CHAN_MAP.get("WARNING", [])))


def should_send(event_type: str) -> bool:
    """Check + update rate limit state.  Returns True if the alert should go out.

    Side effect: updates journal/alert_state.json with the current timestamp
    so the next call can measure elapsed time correctly.
    """
    rate_limits = getattr(_cfg, "ALERT_RATE_LIMITS", _RATE_MAP)
    limit_s     = rate_limits.get(event_type, rate_limits.get("DEFAULT", 300))

    state = _load_state()
    now   = dt.datetime.now(dt.timezone.utc)

    if limit_s > 0:
        last_raw = state.get("last_sent", {}).get(event_type)
        if last_raw:
            try:
                last_dt = dt.datetime.fromisoformat(last_raw)
                elapsed = (now - last_dt).total_seconds()
                if elapsed < limit_s:
                    log.debug(
                        "alert rate-limited  event=%s  elapsed=%.0fs  limit=%ds",
                        event_type, elapsed, limit_s,
                    )
                    return False
            except Exception:
                pass  # bad state value — treat as expired and allow send

    state.setdefault("last_sent", {})[event_type] = now.isoformat(timespec="seconds")
    _save_state(state)
    return True


def reset_rate_limit(event_type: str) -> None:
    """Clear the rate-limit timestamp for an event type (e.g. in tests)."""
    state = _load_state()
    state.get("last_sent", {}).pop(event_type, None)
    _save_state(state)


# ── main entry point ──────────────────────────────────────────────────────────

def smart_send(event_type: str, title: str, details: str = "") -> None:
    """Route an alert using severity + rate-limit rules.

    INFO  severity → suppressed (logged at DEBUG only)
    WARNING/CRITICAL → routed to the configured channels (if not rate-limited)

    Falls back gracefully if alert_dispatch channels are not configured.
    """
    channels = get_channels(event_type)
    if not channels:
        log.debug(
            "alert suppressed (INFO tier)  event=%s  title=%s", event_type, title
        )
        return

    if not should_send(event_type):
        return

    # Delegate actual delivery to the low-level dispatcher
    from .alert_dispatch import _telegram, _discord, _email, _EMOJI

    emoji   = _EMOJI.get(event_type, "ℹ️")
    message = f"{emoji} [Vivek's Beta Scanner] {title}"
    if details:
        message += f"\n{details}"

    fired: list[str] = []
    if "telegram" in channels and _telegram(message):
        fired.append("telegram")
    if "discord" in channels and _discord(message):
        fired.append("discord")
    if "email" in channels and _email(f"Vivek's Beta Scanner — {title}", message):
        fired.append("email")

    severity = get_severity(event_type)
    if fired:
        log.info(
            "smart_send  event=%s  severity=%s  channels=%s",
            event_type, severity, ",".join(fired),
        )
    else:
        log.debug(
            "smart_send: no channels delivered  event=%s  severity=%s",
            event_type, severity,
        )
