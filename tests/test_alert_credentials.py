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


def test_discord_send_survives_a_bom_in_the_stored_secret(monkeypatch):
    sent = _Sent()
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", DIRTY)
    monkeypatch.setattr(ad.urllib.request, "urlopen", sent.urlopen)
    assert ad._discord("test message") is True
    assert sent.url == CLEAN, f"request went to {sent.url!r}"


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
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    assert ad._discord("x") is False


# ── the other two read sites route through the cleaner (source pins) ─────────

def _src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_confluence_alert_cleans_its_webhook_read():
    assert re.search(r"clean_secret\(os\.environ\.get\(\"DISCORD_WEBHOOK_URL\"",
                     _src("scanner/confluence_alert.py")), \
        "confluence_alert.py no longer routes its webhook through clean_secret"


def test_discord_digest_cleans_its_webhook_read():
    assert re.search(r"clean_secret\(os\.getenv\(\"DISCORD_WEBHOOK_URL\"",
                     _src("scanner/discord.py")), \
        "discord.py no longer routes its webhook through clean_secret"


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


def test_the_evidence_brief_workflow_trims_the_same_characters():
    wf = _src(".github/workflows/evidence_brief.yml")
    assert "\\ufeff" in wf, "the workflow's inline trim lost the BOM"
    assert "\\u200b" in wf


# ── the workflows' own failure pings (found live 2026-08-27) ─────────────────
#
# The 2026-08-01 fix routed every PYTHON sender through clean_secret and left
# five workflows curling the secret raw in their `Alert on failure` steps.
# curl parses "<BOM>https" as a HOSTNAME and the path after the next colon as
# a port, dies with "Port number was not a decimal number between 0 and
# 65535", and `|| true` swallowed it — so the red-run Discord ping for
# scan/crypto_bot/phasemap/backup_book/turtle had NEVER delivered. Proven in
# the live log of turtle run #29 (2026-08-24), where the scan failure itself
# was Yahoo throttling but the alert about it silently died. These pins are
# the two halves of the repair.

_WORKFLOWS = ROOT / ".github" / "workflows"

# The workflows whose failure ping posts via curl (rather than a Python
# sender that already routes through clean_secret / the inline trim).
_CURL_PING_WORKFLOWS = (
    "scan.yml", "crypto_bot.yml", "phasemap.yml", "backup_book.yml",
    "turtle.yml",
)


def test_no_workflow_hands_the_raw_webhook_to_curl():
    # The shape being banned is the URL-as-final-argument line:
    #     "$DISCORD_WEBHOOK_URL" || true
    # The emptiness guard `[ -z "$DISCORD_WEBHOOK_URL" ]` and env: blocks are
    # legitimate raw reads and do not match. Any curl must target the trimmed
    # $URL instead.
    offenders = []
    for wf in sorted(_WORKFLOWS.glob("*.yml")):
        for i, line in enumerate(
                wf.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r'\s*"\$DISCORD_WEBHOOK_URL"', line):
                offenders.append(f"{wf.name}:{i}")
    assert not offenders, (
        "these lines hand the pasted secret straight to a command; the "
        "stored value carries a leading U+FEFF, so the send dies inside "
        f"|| true and nobody hears the red run: {offenders}")


def test_the_failure_ping_workflows_trim_the_same_characters():
    # Each curl-pinging workflow must inline clean_secret's exact ends-only
    # character set before the send — the same rule the evidence brief pin
    # above enforces for its Python post.
    for name in _CURL_PING_WORKFLOWS:
        wf = _src(f".github/workflows/{name}")
        assert "\\ufeff" in wf, f"{name}: the inline trim lost the BOM"
        assert "\\u200b" in wf, f"{name}: the inline trim lost the zero-widths"


def test_a_dead_failure_ping_is_no_longer_silent():
    # The counterpart of removing `|| true` from the send: a curl that cannot
    # deliver must say so on the run page. Every curl-pinging workflow carries
    # the ::warning:: fallback, so the next credential problem is visible on
    # the very first red run instead of after weeks of silence.
    for name in _CURL_PING_WORKFLOWS:
        wf = _src(f".github/workflows/{name}")
        assert "::warning::Discord failure ping did not deliver" in wf, (
            f"{name}: the failed-send warning is gone — a dead ping is "
            "silent again")
