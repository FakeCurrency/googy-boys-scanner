"""Unified event-alert dispatcher: email, Telegram, Discord.

All broker events that warrant human attention — kill switch trigger, daily
loss limit, order failures, scan anomalies — flow through here.

Environment vars (all optional; unused channels are silently skipped):
  TELEGRAM_BOT_TOKEN     Bot API token from @BotFather
  TELEGRAM_CHAT_ID       Target chat/channel ID (negative for group chats)
  DISCORD_WEBHOOK_URL    Webhook URL from Server Settings → Integrations

Email uses the same GBS_SMTP_* vars as scanner/alerts.py.
"""

import json as _json
import logging
import os
import smtplib
import urllib.request
from email.mime.text import MIMEText

log = logging.getLogger(__name__)

_EMOJI = {
    "kill_switch":    "🛑",
    "daily_loss":     "📉",
    "order_placed":   "✅",
    "order_rejected": "⚠️",
    "order_failed":   "❌",
    "scan_error":     "🔴",
    "anomaly":        "⚠️",
    "info":           "ℹ️",
}


def _telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat  = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (token and chat):
        return False
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    data = _json.dumps({"chat_id": chat, "text": text}).encode()
    try:
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        log.warning("telegram alert failed: %s", e)
        return False


def _discord(text: str) -> bool:
    url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        return False
    data = _json.dumps({"content": text}).encode()
    try:
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        log.warning("discord alert failed: %s", e)
        return False


def _email(subject: str, body: str) -> bool:
    host = os.environ.get("GBS_SMTP_HOST", "")
    user = os.environ.get("GBS_SMTP_USER", "")
    pwd  = os.environ.get("GBS_SMTP_PASS", "")
    to   = os.environ.get("GBS_ALERT_TO", "")
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
    message = f"{emoji} [Vivek's Beta Scanner] {title}"
    if details:
        message += f"\n{details}"

    channels: list[str] = []
    if _telegram(message):
        channels.append("telegram")
    if _discord(message):
        channels.append("discord")
    if _email(f"Vivek's Beta Scanner — {title}", message):
        channels.append("email")

    if channels:
        log.info("alert sent via %s  event=%s", ",".join(channels), event_type)
    else:
        log.debug("alert skipped (no channels configured)  event=%s", event_type)
