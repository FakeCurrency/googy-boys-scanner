"""Alerts from the runner: the watchdog's channel path + ``state/alerts.log``.

``scanner.watchdog._dispatch(severity, text)`` is the one place the repo
already turns a severity into deliveries (``config.ALERT_CHANNELS`` ->
``alert_dispatch._telegram`` / ``_email``), bypassing the router's per-event
rate limits -- right for a HALT or a failed unit, which must never be
suppressed. It is IMPORTED, not copied, so a channel added there is a channel
added here. Every alert is also appended to ``<state>/alerts.log`` so a box
with no channel configured still keeps a record (the 'NOBODY WAS TOLD' case).

``notify_failure(unit)`` is the ``OnFailure=vivek5-failed@%n.service`` hook:
it attaches the unit's last 30 journal lines when journalctl is available,
alerts at WARNING (CRITICAL for the book writers / kill switch / backup), and
writes a ledger ``failed`` row for the mapped job when the runner itself did
not get to write one (an ImportError or an OOM kill leaves no row).
"""
from __future__ import annotations

import datetime as dt
import pathlib
import shutil
import subprocess

from scanner import config

from . import emit, host_label, iso, ledger_path, state_dir as _state_dir, utcnow
from . import ledger as _ledger

_MARK = {"CRITICAL": "[CRITICAL]", "WARNING": "[WARNING]", "NOTICE": "[NOTICE]", "INFO": "[INFO]"}
_CRITICAL_KEYS = ("scan.yml", "crypto_bot.yml", "kill_switch.yml", "backup_book.yml",
                  "close_position.yml", "api", "spool")


def _dispatch_default(severity: str, text: str) -> list[str]:
    from scanner import watchdog
    return watchdog._dispatch(severity, text)


def alert_text(severity: str, title: str, details: str = "") -> str:
    lines = [f"{_MARK.get(severity, '[' + severity + ']')} [Vivek 5.0] VPS {title}"]
    if details:
        lines += [ln for ln in str(details).splitlines()]
    lines.append(f"(host: {host_label()}; unit alerts are not rate-limited; see deploy/README.md)")
    return "\n".join(lines)


def alert(severity: str, title: str, details: str = "", *, state_dir: pathlib.Path | None = None,
          dispatch=None, now: dt.datetime | None = None) -> list[str]:
    """Send through the watchdog's path; log to alerts.log whatever happens."""
    state = pathlib.Path(state_dir) if state_dir else _state_dir()
    text = alert_text(severity, title, _ledger.redact(details))
    sent: list[str] = []
    try:
        sent = list((dispatch or _dispatch_default)(severity, text) or [])
    except Exception as e:                                       # noqa: BLE001 - never let an alert crash a job
        emit(f"notify: dispatch raised {type(e).__name__}: {e}")
    line = f"{iso(now or utcnow())} {severity} {title} | sent={','.join(sent) or 'NONE'}"
    try:
        state.mkdir(parents=True, exist_ok=True)
        with open(state / "alerts.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            for ln in text.splitlines()[1:-1]:
                fh.write("    " + ln + "\n")
    except OSError as e:
        emit(f"notify: could not append alerts.log ({type(e).__name__})")
    emit(f"notify: {line}")
    if not sent:
        emit("notify: NOBODY WAS TOLD - no alert channel accepted the message "
             "(TELEGRAM_* / GBS_SMTP_* unset?); the line is in state/alerts.log")
    return sent


def unit_to_key(unit: str) -> str:
    """``vivek5-scan-close@asx.service`` -> ``scan.yml``; host units keep their name."""
    from .jobs import JOBS
    base = unit.strip()
    if base.endswith(".service"):
        base = base[:-len(".service")]
    if "@" in base:
        base = base.split("@", 1)[0]
    if base.startswith("vivek5-"):
        base = base[len("vivek5-"):]
    for suffix in ("-close", "-backstop"):
        if base.endswith(suffix):
            base = base[:-len(suffix)]
    cand = base.replace("-", "_") + ".yml"
    return cand if cand in JOBS else base


def journal_tail(unit: str, n: int = 30, run=subprocess.run) -> str:
    if not shutil.which("journalctl"):
        return "(journalctl not available)"
    try:
        res = run(["journalctl", "-u", unit, "-n", str(n), "--no-pager"],
                  capture_output=True, text=True, timeout=20)
        return (res.stdout or res.stderr or "").strip() or "(no journal lines)"
    except Exception as e:                                       # noqa: BLE001
        return f"(journalctl failed: {type(e).__name__})"


def notify_failure(unit: str, *, state_dir: pathlib.Path | None = None,
                   ledger_file: pathlib.Path | None = None, dispatch=None,
                   run=subprocess.run, now: dt.datetime | None = None,
                   recent_s: int = 180) -> int:
    """The OnFailure hook. Returns 0 (it must never itself fail the box)."""
    now = now or utcnow()
    state = pathlib.Path(state_dir) if state_dir else _state_dir()
    ledger_file = pathlib.Path(ledger_file) if ledger_file else ledger_path()
    key = unit_to_key(unit)
    tail = _ledger.redact(journal_tail(unit, run=run))
    severity = "CRITICAL" if key in _CRITICAL_KEYS else "WARNING"
    row = _ledger.rows_for(key, ledger_file)
    wrote_row = False
    try:
        last_end = dt.datetime.strptime(row.get("last_end", ""), "%Y-%m-%dT%H:%M:%SZ") \
            .replace(tzinfo=dt.timezone.utc) if row.get("last_end") else None
    except ValueError:
        last_end = None
    if last_end is None or (now - last_end).total_seconds() > recent_s:
        _ledger.record(key, status="failed", exit_code=-1, args={"unit": unit},
                       started=now, ended=now, last_line=f"unit {unit} failed (no runner row)",
                       host=host_label(), path=ledger_file, extra={"last_unit_failure_at": iso(now)})
        wrote_row = True
    else:
        _ledger.annotate(key, {"last_unit_failure_at": iso(now)}, path=ledger_file)
    details = (f"unit: {unit}\nledger key: {key}\n"
               f"last status: {row.get('last_status', '-')} exit {row.get('last_exit', '-')} "
               f"at {row.get('last_end', '-')}\n"
               f"{'(ledger row written by this hook)' if wrote_row else '(runner already recorded the row)'}\n"
               f"--- journalctl -u {unit} -n 30 ---\n{tail}")
    alert(severity, f"unit failed: {unit}", details, state_dir=state, dispatch=dispatch, now=now)
    return 0


__all__ = ["alert", "alert_text", "notify_failure", "unit_to_key", "journal_tail"]

# Severity routing lives in config.ALERT_CHANNELS; this module never widens it.
assert set(_MARK) >= set(config.ALERT_CHANNELS)
