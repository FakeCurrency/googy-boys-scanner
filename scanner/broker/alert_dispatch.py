"""Unified event-alert dispatcher: email, Telegram.

All broker events that warrant human attention — kill switch trigger, daily
loss limit, order failures, scan anomalies — flow through here.

The Discord sender was REMOVED 2026-08-27 (owner ruling: "get rid of the
discord aspect, I will work on implementing something new in the future").
This module is where the replacement channel plugs in: add a `_<channel>`
sender beside `_telegram`/`_email`, wire it into `send()` below and into
`alert_router.smart_send`, and add the channel name to
config.ALERT_CHANNELS' tiers.

Environment vars (all optional; unused channels are silently skipped):
  TELEGRAM_BOT_TOKEN     Bot API token from @BotFather
  TELEGRAM_CHAT_ID       Target chat/channel ID (negative for group chats)

Email uses the same GBS_SMTP_* vars as scanner/alerts.py.
"""

import json as _json
import logging
import os
import smtplib
import urllib.request
from email.mime.text import MIMEText

log = logging.getLogger(__name__)


# Webhook edges (Discord's did, and anything behind Cloudflare may) 403 a
# default Python UA as a bot. A named agent is both politer and deliverable.
_UA = "vivek5-alerts/1.0 (+github-actions)"


def _cred(name: str) -> str:
    """Read a pasted credential tolerantly — see config.clean_secret for the
    live incident (a BOM inside the then-live DISCORD_WEBHOOK_URL silenced
    that whole channel because every sender here swallows its exceptions)."""
    try:
        from scanner.config import clean_secret
        return clean_secret(os.environ.get(name, ""))
    except Exception:                                     # noqa: BLE001
        return os.environ.get(name, "").strip()

_EMOJI = {
    "kill_switch":    "🛑",
    "daily_loss":     "📉",
    "order_placed":   "✅",
    "order_rejected": "⚠️",
    "order_failed":   "❌",
    "scan_error":     "🔴",
    "anomaly":        "⚠️",
    "info":           "ℹ️",
    # HORIZON's "look wider" — nothing is broken, something is running.
    "sector_run":     "🔭",
    # "your call" — the bot took it; do you want it, or does it?
    "trade_review":   "🖐",
    # The book's own loss guard tripped — new entries halted for the session.
    "vivek_guard":    "⛔",
    # Real exposure at the broker that the journal has never heard of.
    "orphan_position": "👻",
}


def _telegram(text: str) -> bool:
    try:
        from scanner import config as _cfg
        if not _cfg.TELEGRAM_ENABLED:
            return False
    except Exception:
        pass
    token = _cred("TELEGRAM_BOT_TOKEN")
    chat  = _cred("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    data = _json.dumps({"chat_id": chat, "text": text}).encode()
    try:
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json",
                                     "User-Agent": _UA})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        log.warning("telegram alert failed: %s", e)
        return False


def _email(subject: str, body: str) -> bool:
    host = _cred("GBS_SMTP_HOST")
    user = _cred("GBS_SMTP_USER")
    pwd  = _cred("GBS_SMTP_PASS")
    to   = _cred("GBS_ALERT_TO")
    if not (host and user and pwd and to):
        return False
    port = int(os.environ.get("GBS_SMTP_PORT", "587"))
    msg  = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"]    = os.environ.get("GBS_ALERT_FROM", user)
    msg["To"]      = to
    try:
        with smtplib.SMTP(host, port) as s:
            s.starttls()
            s.login(user, pwd)
            s.sendmail(msg["From"], [to], msg.as_string())
        return True
    except Exception as e:
        log.warning("email alert failed: %s", e)
        return False


def send(event_type: str, title: str, details: str = "") -> None:
    """Fire all configured alert channels for an event.

    event_type: one of the _EMOJI keys, or any string
    title:      short one-line description
    details:    optional extra context (multi-line OK)
    """
    emoji   = _EMOJI.get(event_type, "ℹ️")
    message = f"{emoji} [Vivek 5.0] {title}"
    if details:
        message += f"\n{details}"

    channels: list[str] = []
    if _telegram(message):
        channels.append("telegram")
    if _email(f"Vivek 5.0 — {title}", message):
        channels.append("email")

    if channels:
        log.info("alert sent via %s  event=%s", ",".join(channels), event_type)
    else:
        # WARNING, not DEBUG (2026-07-28). `send` is the LOW-level path with no
        # severity tier, so unlike the router there is no legitimate "meant to
        # be silent" case here — every caller of `send` believes it is telling
        # somebody something. Reaching this branch means no channel is
        # configured at all, which in CI means a workflow step is missing its
        # secrets. kill_switch.yml shipped that way and a fired kill switch was
        # silent; it was invisible precisely because this line was DEBUG.
        log.warning(
            "alert NOT DELIVERED (no channel configured)  event=%s  title=%s  "
            "— check this workflow step's env block",
            event_type, title,
        )
