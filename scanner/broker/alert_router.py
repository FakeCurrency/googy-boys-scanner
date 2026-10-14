"""Smart alert routing — Phase 7 Advanced Monitoring & Alerting.

Wraps alert_dispatch with:
  - Severity-based channel selection (config.ALERT_CHANNELS is the live map)
      CRITICAL → Telegram + Email
      WARNING  → Telegram
      NOTICE   → no channel (Discord removed 2026-08-27; the replacement
                 channel adds itself back to these tiers)
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

# The routing tables live in scanner/config.py ONLY (ALERT_SEVERITY,
# ALERT_CHANNELS, ALERT_RATE_LIMITS). This module used to carry hand-mirrored
# "fallback" copies for a config that failed to import, but config is imported
# unconditionally at the top of this file, so the copies were never consulted
# and only drifted (REFINE200 #90, 2026-10-14).


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
    It was written for two writers (`circuit_breaker` owned a `cb_state` key
    until the scalp risk stack was removed, 2026-09-17), each of which loaded
    the whole document, mutated its corner and wrote it all back, so an
    interleaving silently reverted the other's change. The one writer left
    keeps the discipline: this module writes `last_sent` and `acknowledged`.

    Re-reading *inside* this function shrinks the window to the mutate-plus-
    write, so an interleaving costs at most one repeated alert rather than a
    lost acknowledgment. `mutate` must be cheap and must not perform IO.

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
    # An unknown severity routes like WARNING, the same default get_severity
    # gives an unknown event.
    return list(chan_map.get(severity, chan_map.get("WARNING", [])))


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
    can take seconds, and another run may have written the file meanwhile.
    """
    when = when or dt.datetime.now(dt.timezone.utc)
    update_state(
        lambda st: st.setdefault("last_sent", {}).__setitem__(
            event_type, when.isoformat(timespec="seconds")
        )
    )


# ── acknowledgment ────────────────────────────────────────────────────────────

def acknowledge(event_type: str, duration_h: float = 24.0) -> None:
    """Suppress an alert type for duration_h hours (user acknowledgment).

    Example: acknowledge("anomaly", 4.0) stops suspect-price alerts for 4
    hours after the user has reviewed the issue.

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
    from .alert_dispatch import _telegram, _email, _EMOJI

    emoji   = _EMOJI.get(event_type, "ℹ️")
    message = f"{emoji} [Vivek 5.0] {title}"
    if details:
        message += f"\n{details}"

    fired: list[str] = []
    if "telegram" in channels and _telegram(message):
        fired.append("telegram")
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
            "TELEGRAM_* / GBS_SMTP_*; no push channel is live since the "
            "2026-08-27 Discord removal)",
            event_type, severity, ",".join(channels),
        )
