"""The BOM'd-secret incident (2026-08-01) — pins for config.clean_secret.

The live DISCORD_WEBHOOK_URL was stored with a leading U+FEFF, invisible in
the GitHub secrets box. urllib rejects it as `unknown url type: \\ufeffhttps`,
and because every sender in alert_dispatch wraps its post in try/log-warning,
the whole Discord channel — stale probes, trade reviews, sector alarms,
kill-switch notices — failed SILENTLY. The evidence brief's first delivery was
just the first caller that let the same error fail a run out loud.

These tests pin the repair at both levels: the cleaner itself, and — the half
that actually matters — that each sender's request now reaches the network
with a CLEAN url even when the environment carries the dirty one.
"""
from __future__ import annotations

import pathlib
import re

import scanner.broker.alert_dispatch as ad
from scanner.config import clean_secret

ROOT = pathlib.Path(__file__).resolve().parents[1]

DIRTY = "﻿https://discord.test/api/webhooks/1/x \n"
CLEAN = "https://discord.test/api/webhooks/1/x"


# ── the cleaner ──────────────────────────────────────────────────────────────

def test_it_strips_bom_zero_width_and_whitespace_from_both_ends():
    assert clean_secret(DIRTY) == CLEAN
    assert clean_secret("​ tok-123 ‏") == "tok-123"
    assert clean_secret(None) == ""
    assert clean_secret("") == ""


def test_interior_bytes_are_never_touched():
    # A webhook token could legitimately contain almost anything; the trim is
    # ends-only so a weird-but-real credential passes through byte-identical.
    assert clean_secret("a​b") == "a​b"
    assert clean_secret(" a b ") == "a b"


# ── the senders actually use it ──────────────────────────────────────────────

class _Sent:
    def __init__(self):
        self.url = None

    def urlopen(self, req, timeout=None):
        self.url = getattr(req, "full_url", req)
        class _R:  # noqa: D401 — minimal response stub
            status = 204
        return _R()


def test_telegram_creds_are_cleaned_before_the_url_is_built(monkeypatch):
    sent = _Sent()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "﻿123:abc ")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", " -99​")
    monkeypatch.setattr(ad.urllib.request, "urlopen", sent.urlopen)
    import scanner.config as cfg
    monkeypatch.setattr(cfg, "TELEGRAM_ENABLED", True, raising=False)
    assert ad._telegram("test message") is True
    assert "bot123:abc/" in sent.url, sent.url
    assert "﻿" not in sent.url


def test_a_missing_secret_still_reads_as_not_configured(monkeypatch):
    # The cleaner must not turn "unset" into a phantom empty-string send.
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)
    import scanner.config as cfg
    monkeypatch.setattr(cfg, "TELEGRAM_ENABLED", True, raising=False)
    assert ad._telegram("x") is False


# ── the other two read sites route through the cleaner (source pins) ─────────

def _src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_no_scanner_code_reads_the_removed_discord_webhook():
    # Discord was removed 2026-08-27 (owner ruling). A webhook read creeping
    # back into scanner/ or scripts/ would be a partial, untested revival of
    # the channel — the replacement goes through alert_dispatch/_cred like
    # every other credential, not through a scattered env read.
    read_forms = re.compile(
        r"(?:os\.environ\.get|os\.getenv|environ\[|getenv\()\s*\(?\s*"
        r"[\"']DISCORD_WEBHOOK_URL")
    offenders = []
    for base in ("scanner", "scripts"):
        for py in sorted((ROOT / base).rglob("*.py")):
            if read_forms.search(py.read_text(encoding="utf-8")):
                offenders.append(str(py.relative_to(ROOT)))
    assert not offenders, f"webhook read crept back in: {offenders}"


def test_no_sender_in_alert_dispatch_reads_a_credential_raw():
    # The general form: any future channel added to alert_dispatch must read
    # its secrets through _cred, not os.environ directly. GITHUB_* and
    # WATCHDOG_* style vars are runner-provided, not pasted; the pasted ones
    # are exactly the channel credentials.
    src = _src("scanner/broker/alert_dispatch.py")
    body = src.split('def _cred', 1)[1]          # everything after the helper
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL",
                 "GBS_SMTP_HOST", "GBS_SMTP_USER", "GBS_SMTP_PASS", "GBS_ALERT_TO"):
        raw = re.search(r"os\.environ\.get\(\"%s\"" % name, body)
        assert raw is None, f"{name} is read raw, bypassing _cred"


# ── the workflows (Discord removed 2026-08-27, owner ruling) ─────────────────
#
# History, so the next reader knows why a whole family of pins vanished here:
# the 2026-08-01 fix routed every Python sender through clean_secret; on
# 2026-08-27 an audit found five workflows still curling the secret raw in
# their failure pings (curl parses "<BOM>https" as a hostname and dies inside
# `|| true` — proven in turtle run #29's live log), and the same day the
# owner ruled the whole Discord channel OUT ("get rid of the discord aspect,
# I will work on implementing something new in the future"). So instead of
# pinning trims onto Discord steps, the pin is now that the steps are GONE.


def test_no_workflow_references_the_removed_discord_webhook():
    """Any DISCORD_WEBHOOK_URL in a workflow is a partial revival of the
    removed channel: an env line feeding a sender that no longer exists, or a
    new raw curl re-importing the BOM bug. The replacement channel gets its
    own secret name, its own sender in alert_dispatch, and its own pins."""
    offenders = []
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for i, line in enumerate(
                wf.read_text(encoding="utf-8").splitlines(), 1):
            if "DISCORD_WEBHOOK_URL" in line:
                offenders.append(f"{wf.name}:{i}")
    assert not offenders, f"Discord webhook crept back in: {offenders}"
