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
from scanner.journal_common import atomic_write as _atomic_write

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
    "sector_run":      "NOTICE",
    "trade_review":    "NOTICE",
    # KEEP THESE TWO TABLES IN STEP WITH scanner/config.py (2026-07-28).
    # `get_severity` falls back to "WARNING" for anything it does not know, so a
    # missing key here is not an error — it is a silent DOWNGRADE. Both of the
    # events below are CRITICAL in config, and CRITICAL is the only tier that
    # reaches email; landing on the WARNING default would drop them to
    # telegram+discord without a word in any log. That is the whole failure
    # mode: these tables are only consulted when config is unavailable, which is
    # exactly the moment nobody is watching closely.
    "vivek_guard":     "CRITICAL",
    "orphan_position": "CRITICAL",
}

_CHAN_MAP = {
    "CRITICAL": ["telegram", "discord", "email"],
    "WARNING":  ["telegram", "discord"],
    "INFO":     [],
    "NOTICE":   ["discord"],
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
    "sector_run":      0,
    "trade_review":    0,
    # Both own their dedupe elsewhere (vivek_run's per-market book stamp; the
    # orphan symbol set on the journal), so a limit here could only ever drop a
    # message that the real dedupe had already decided was worth sending.
    "vivek_guard":     0,
    "orphan_position": 0,
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


def update_state(mutate) -> dict:
    """Re-read the state file, apply `mutate(state)`, write it back atomically.

    THE ONLY SUPPORTED WAY TO WRITE journal/alert_state.json (2026-07-28).
    Two modules own disjoint subtrees of this one file — this one writes
    `last_sent` and `acknowledged`, `circuit_breaker` writes `cb_state` — and
    both used to load the whole document, mutate their own corner and write the
    whole document back. Sequentially that is fine; interleaved, the second
    writer's copy predates the first writer's change and silently reverts it.

    Re-reading *inside* this function shrinks the window to the mutate-plus-
    write, and because every caller now touches only its own key, an
    interleaving costs at most one repeated alert rather than a lost
    acknowledgment or a reset breaker. `mutate` must be cheap and must not
    perform IO.

    Returns the written state so callers can log what landed.
    """
    state = _load_state()
    mutate(state)
    _save_state(state)
    return state


# ── public helpers ────────────────────────────────────────────────────────────

def get_severity(event_type: str) -> str:
    """Return severity level string for an event_type."""
    sev_map = _cfg.ALERT_SEVERITY
    return sev_map.get(event_type, "WARNING")


def get_channels(event_type: str, severity: str = "") -> list[str]:
    """Return which channels should receive an alert for event_type."""
    if not severity:
        severity = get_severity(event_type)
    chan_map = _cfg.ALERT_CHANNELS
    return list(chan_map.get(severity, _CHAN_MAP.get("WARNING", [])))


def should_send(event_type: str, commit: bool = True) -> bool:
    """Check the rate limit.  Returns True if the alert should go out.

    With `commit=True` (the default, and the historical behaviour) it also
    stamps journal/alert_state.json with the current time, so the next call
    measures elapsed time correctly.

    `commit=False` is a DRY CHECK — it answers the question without spending
    the window.  `smart_send` uses it, then calls `mark_sent` only once a
    channel has actually accepted the message (2026-07-28).  Stamping first
    meant a send that reached nobody — because a webhook 500'd, or because the
    workflow forgot to export the secret — still burned the window and
    suppressed the NEXT alert, which is the real one, for the full interval.
    The failure mode that costs you a message is the only one worth designing
    around; a duplicate costs nothing.
    """
    rate_limits = _cfg.ALERT_RATE_LIMITS
    limit_s     = rate_limits.get(event_type, rate_limits.get("DEFAULT", 300))

    state = _load_state()
    now   = dt.datetime.now(dt.timezone.utc)

    # Check acknowledgment — user has seen and dismissed this alert class
    if _is_acknowledged(event_type, state):
        log.debug("alert acknowledged (suppressed)  event=%s", event_type)
        return False

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

    if commit:
        mark_sent(event_type, now)
    return True


def mark_sent(event_type: str, when: dt.datetime | None = None) -> None:
    """Start the rate-limit window for `event_type` now (or at `when`).

    Split out of `should_send` so delivery can decide when the window opens.
    Re-reads state rather than reusing the caller's copy: the send it follows
    can take seconds, and `circuit_breaker` writes the same file.
    """
    when = when or dt.datetime.now(dt.timezone.utc)
    update_state(
        lambda st: st.setdefault("last_sent", {}).__setitem__(
            event_type, when.isoformat(timespec="seconds")
        )
    )


def reset_rate_limit(event_type: str) -> None:
    """Clear the rate-limit timestamp for an event type (e.g. in tests)."""
    update_state(lambda st: st.get("last_sent", {}).pop(event_type, None))


# ── acknowledgment ────────────────────────────────────────────────────────────

def acknowledge(event_type: str, duration_h: float = 24.0) -> None:
    """Suppress an alert type for duration_h hours (user acknowledgment).

    Example: acknowledge("circuit_breaker", 4.0) stops circuit-breaker
    alerts for 4 hours after the user has reviewed the issue.

    The acknowledgment is stored in journal/alert_state.json under the
    "acknowledged" key so it persists across GitHub Actions runs.
    """
    ack_until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=duration_h)
    update_state(
        lambda st: st.setdefault("acknowledged", {}).__setitem__(
            event_type, ack_until.isoformat(timespec="seconds")
        )
    )
    log.info(
        "alert acknowledged  event=%s  until=%s",
        event_type, ack_until.isoformat(timespec="seconds"),
    )


def clear_acknowledgment(event_type: str) -> None:
    """Re-enable a previously acknowledged alert type immediately."""
    update_state(lambda st: st.get("acknowledged", {}).pop(event_type, None))
    log.info("acknowledgment cleared  event=%s", event_type)


def _is_acknowledged(event_type: str, state: dict) -> bool:
    """Return True if event_type is within its acknowledgment window."""
    ack_until_raw = state.get("acknowledged", {}).get(event_type)
    if not ack_until_raw:
        return False
    try:
        ack_until = dt.datetime.fromisoformat(ack_until_raw)
        return dt.datetime.now(dt.timezone.utc) < ack_until
    except Exception:
        return False


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

    # DRY check — the window is only spent once something accepts the message.
    if not should_send(event_type, commit=False):
        return

    # Delegate actual delivery to the low-level dispatcher
    from .alert_dispatch import _telegram, _discord, _email, _EMOJI

    emoji   = _EMOJI.get(event_type, "ℹ️")
    message = f"{emoji} [Vivek 5.0] {title}"
    if details:
        message += f"\n{details}"

    fired: list[str] = []
    if "telegram" in channels and _telegram(message):
        fired.append("telegram")
    if "discord" in channels and _discord(message):
        fired.append("discord")
    if "email" in channels and _email(f"Vivek 5.0 — {title}", message):
        fired.append("email")

    severity = get_severity(event_type)
    if fired:
        mark_sent(event_type)
        log.info(
            "smart_send  event=%s  severity=%s  channels=%s",
            event_type, severity, ",".join(fired),
        )
    else:
        # WARNING, not DEBUG (2026-07-28). Reaching here means the event was
        # routable (get_channels returned something) and not rate-limited, and
        # STILL nobody was told — a missing secret in the workflow, or every
        # channel erroring. That is the one line in this module worth finding in
        # an Actions log, and it was the one line written below the default
        # level. The rate-limit window is deliberately NOT stamped, so the next
        # attempt is immediate rather than suppressed.
        log.warning(
            "smart_send: NOBODY WAS TOLD  event=%s  severity=%s  wanted=%s  "
            "(no channel accepted — check the workflow's env block for "
            "DISCORD_WEBHOOK_URL / TELEGRAM_* / GBS_SMTP_*)",
            event_type, severity, ",".join(channels),
        )
