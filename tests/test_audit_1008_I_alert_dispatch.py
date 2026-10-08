"""Audit #63 (2026-10-08): the email leg must survive an UNSET optional secret
and must not wait for ever on a stalled SMTP server.

Every workflow exports ``GBS_SMTP_PORT: ${{ secrets.GBS_SMTP_PORT }}`` (and
test_alerts.yml ``GBS_ALERT_FROM`` the same way). GitHub renders an unset
secret as an EMPTY STRING, so ``os.environ.get("GBS_SMTP_PORT", "587")`` got
``""`` and ``int("")`` raised ValueError - outside the sender's try, so
``watchdog._dispatch`` and ``alert_router.smart_send`` crashed (the watchdog
step died before saving its state) the day the four required SMTP secrets
were set without a port. ``smtplib.SMTP(host, port)`` also had no timeout.
These drive the SHIPPED ``alert_dispatch._email`` with a fake or a real
(local, stalling) SMTP server.
"""

import logging
import socket
import threading

import pytest

from scanner import config
from scanner import watchdog as wd
from scanner.broker import alert_dispatch as ad


class _FakeSMTP:
    calls: list = []

    def __init__(self, host, port, timeout=None):
        self.rec = {"host": host, "port": port, "timeout": timeout}
        _FakeSMTP.calls.append(self.rec)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, pwd):
        self.rec["login"] = user

    def sendmail(self, frm, to, msg):
        self.rec["from"] = frm
        self.rec["to"] = to


@pytest.fixture
def smtp_env(monkeypatch):
    """The four REQUIRED secrets set; the two optional ones as GitHub renders
    an unset secret: present and empty."""
    _FakeSMTP.calls = []
    monkeypatch.setattr(ad.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setenv("GBS_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("GBS_SMTP_USER", "bot@example.test")
    monkeypatch.setenv("GBS_SMTP_PASS", "pw")
    monkeypatch.setenv("GBS_ALERT_TO", "owner@example.test")
    monkeypatch.setenv("GBS_SMTP_PORT", "")
    monkeypatch.setenv("GBS_ALERT_FROM", "")
    return monkeypatch


def test_an_empty_port_secret_falls_back_to_the_default_and_delivers(smtp_env):
    assert ad._email("subject", "body") is True
    rec = _FakeSMTP.calls[-1]
    assert rec["port"] == config.ALERT_SMTP_PORT == 587
    # an empty From secret means the SMTP user, never an empty sender
    assert rec["from"] == "bot@example.test"


def test_the_connection_is_bounded_by_the_configured_timeout(smtp_env):
    ad._email("subject", "body")
    assert _FakeSMTP.calls[-1]["timeout"] == config.ALERT_SMTP_TIMEOUT_S
    assert 0 < config.ALERT_SMTP_TIMEOUT_S <= 60


def test_a_set_port_and_sender_are_honoured_and_cleaned(smtp_env):
    smtp_env.setenv("GBS_SMTP_PORT", "﻿2525 \n")    # a stray paste
    smtp_env.setenv("GBS_ALERT_FROM", "alerts@example.test")
    assert ad._email("subject", "body") is True
    rec = _FakeSMTP.calls[-1]
    assert rec["port"] == 2525 and rec["from"] == "alerts@example.test"


def test_a_garbage_port_fails_this_send_with_a_warning_never_a_raise(smtp_env, caplog):
    smtp_env.setenv("GBS_SMTP_PORT", "five-eight-seven")
    with caplog.at_level(logging.WARNING, logger=ad.log.name):
        assert ad._email("subject", "body") is False
    assert "email alert failed" in caplog.text
    assert _FakeSMTP.calls == []


def test_the_watchdog_dispatch_no_longer_crashes_on_the_empty_port(smtp_env):
    # The audit's scenario: CRITICAL routes to email; _dispatch used to raise.
    assert "email" in config.ALERT_CHANNELS["CRITICAL"]
    sent = wd._dispatch("CRITICAL", "WATCHDOG CRITICAL - test\n- detail")
    assert "email" in sent


def test_a_stalled_smtp_server_cannot_hang_the_caller(smtp_env):
    """A REAL socket that accepts the connection and never sends the 220
    greeting: without a timeout smtplib waits for ever (inside the scan job,
    under the `scan` mutex)."""
    smtp_env.undo()                      # the real smtplib.SMTP this time
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    held = []
    threading.Thread(target=lambda: held.append(srv.accept()), daemon=True).start()

    mp = pytest.MonkeyPatch()
    try:
        mp.setenv("GBS_SMTP_HOST", "127.0.0.1")
        mp.setenv("GBS_SMTP_USER", "u")
        mp.setenv("GBS_SMTP_PASS", "p")
        mp.setenv("GBS_ALERT_TO", "t@example.test")
        mp.setenv("GBS_SMTP_PORT", str(port))
        mp.setattr(config, "ALERT_SMTP_TIMEOUT_S", 0.5)
        result = []
        t = threading.Thread(target=lambda: result.append(ad._email("s", "b")),
                             daemon=True)
        t.start()
        t.join(10)
        assert not t.is_alive(), "the email leg blocked on a stalled server"
        assert result == [False]
    finally:
        mp.undo()
        for conn, _addr in held:
            conn.close()
        srv.close()
