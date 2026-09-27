"""``state/runs.json`` -- the runs ledger (DESIGN section 3.6).

One row per workflow key (all scan units write under ``scan.yml``), plus
``update`` / ``gc`` rows written by the host scripts, plus a
``unit_failures`` row family written by ``notify-failure``:

    {"scan.yml": {"last_start": "...", "last_end": "...",
      "last_status": "ok|failed|skipped|halted", "last_exit": 0,
      "last_args": {...}, "last_success_at": "...", "last_success_args": {...},
      "last_failure_at": "...", "last_skip_at": "...", "last_halt_at": "...",
      "consecutive_failures": 0, "waited_s": 12, "pushed": "<sha>",
      "last_line": "<redacted>", "host": "vps"}, ...}

The MULTI-FIELD shape is the point (book-safety review): a gate skip must not
overwrite the last success (probe_runs treats a gate-skipped Actions run as a
concluded success), and ``last_failure_at`` newer than ``last_success_at`` is
the watchdog's failed-run finding in ledger mode. Rows are written atomically
through ``scanner.output.write_json`` under a flock, so concurrent jobs cannot
lose each other's rows.

The watchdog (C4) imports ``load()`` / ``rows_for(key)``; nothing here reads
the checkout's data files.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re

from scanner.output import write_json

from . import iso, ledger_path, utcnow
from .locks import Lock, lock_path

STATUSES = ("ok", "failed", "skipped", "halted")

_REDACT = (
    (re.compile(r"(https?://)[^/\s@]+@"), r"\1***@"),
    (re.compile(r"(ssh://)[^/\s@]+@"), r"\1***@"),
    (re.compile(r"(Bearer)\s+\S+", re.I), r"\1 ***"),
    (re.compile(r"(token|secret|password|passwd|api[_-]?key)(\s*[=:]\s*)\S+", re.I), r"\1\2***"),
)


def redact(text: str) -> str:
    """Strip credentials before a line reaches the ledger or an alert."""
    out = text or ""
    for pat, rep in _REDACT:
        out = pat.sub(rep, out)
    return out


def last_line_of(text: str, limit: int = 300) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return redact(lines[-1])[:limit] if lines else ""


def load(path: pathlib.Path | None = None) -> dict:
    """The whole ledger; ``{}`` when missing or unreadable (never raises)."""
    p = pathlib.Path(path) if path else ledger_path()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def rows_for(key: str, path: pathlib.Path | None = None) -> dict:
    """The row for one key (``{}`` when absent)."""
    row = load(path).get(key)
    return dict(row) if isinstance(row, dict) else {}


def _ts(value) -> str:
    if value is None:
        return iso(utcnow())
    if isinstance(value, dt.datetime):
        return iso(value)
    return str(value)


def record(key: str, *, status: str, exit_code: int, args: dict | None = None,
           started=None, ended=None, waited_s: float = 0.0, pushed: str | None = None,
           last_line: str = "", host: str | None = None, path: pathlib.Path | None = None,
           extra: dict | None = None) -> dict:
    """Merge one run's outcome into the row for ``key`` and write atomically."""
    if status not in STATUSES:
        raise ValueError(f"status {status!r} not in {STATUSES}")
    p = pathlib.Path(path) if path else ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    ended_iso = _ts(ended)
    lock = Lock(lock_path(p.parent, "ledger"))
    lock.acquire(30.0)
    try:
        doc = load(p)
        row = dict(doc.get(key) or {})
        row.update({
            "last_start": _ts(started), "last_end": ended_iso, "last_status": status,
            "last_exit": int(exit_code), "last_args": dict(args or {}),
            "waited_s": int(round(waited_s)), "last_line": redact(last_line or "")[:300],
            "host": host or row.get("host") or "vps",
        })
        row.setdefault("consecutive_failures", 0)
        if status == "ok":
            row["last_success_at"] = ended_iso
            row["last_success_args"] = dict(args or {})
            row["consecutive_failures"] = 0
        elif status == "skipped":
            row["last_skip_at"] = ended_iso
        else:                                   # failed | halted
            row["last_failure_at"] = ended_iso
            row["consecutive_failures"] = int(row.get("consecutive_failures", 0)) + 1
            if status == "halted":
                row["last_halt_at"] = ended_iso
        if pushed:
            row["pushed"] = pushed
        if extra:
            row.update(extra)
        doc[key] = row
        write_json(p, doc, indent=2, sort_keys=True, newline=True)
    finally:
        lock.release()
    return row


def annotate(key: str, extra: dict, path: pathlib.Path | None = None) -> dict:
    """Merge ``extra`` fields into a row WITHOUT touching its status/timestamps."""
    p = pathlib.Path(path) if path else ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lock = Lock(lock_path(p.parent, "ledger"))
    lock.acquire(30.0)
    try:
        doc = load(p)
        row = dict(doc.get(key) or {})
        row.update(extra)
        doc[key] = row
        write_json(p, doc, indent=2, sort_keys=True, newline=True)
    finally:
        lock.release()
    return row


def success_today(key: str, now: dt.datetime | None = None,
                  path: pathlib.Path | None = None) -> dict | None:
    """The row if its last success fell on today's UTC date, else None."""
    row = rows_for(key, path)
    stamp = row.get("last_success_at")
    if not stamp:
        return None
    today = (now or utcnow()).astimezone(dt.timezone.utc).date().isoformat()
    return row if str(stamp)[:10] == today else None
