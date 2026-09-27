"""The dispatch spool (DESIGN section 3.5): written by the API adapter, drained here.

File: ``<state>/spool/<YYYYMMDDTHHMMSSZ>-<8hex>.json`` written to
``spool/.tmp/`` and ``rename()``d into place. Body::

    {"id": "...", "received_at": "...", "workflow": "scan.yml",
     "inputs": {"market": "asx", "reason": "manual"}, "source": "api/scan"}

``drain()`` walks the directory oldest-first and, per file: only names matching
the regex; opened with ``O_NOFOLLOW`` and ``fstat``-ed (a symlink or a
non-regular file is renamed ``.stuck``, never followed); size cap
``config.VPS_SPOOL_MAX_BYTES``; a parse error records the exception TYPE only;
the workflow and its inputs are RE-VALIDATED with the Functions' own shapes
(defence in depth -- the adapter already refused anything else); operator-only
keys are dropped; the job runs; then, by its exit code:

    0 / 3   -> done/
    1       -> failed/
    4       -> renamed in place to ``<name>.halted``: the box refused to write
               the book (HALT). ``accept-upstream`` / ``clear-halt`` re-queue it,
               so a close accepted with 202 is executed once the box is
               writable again instead of being lost (2026-09-27 book review)
    5       -> ``<name>.retry``: the job gave up WAITING for its lock (a hung
               holder). Re-queued at the start of the next drain (any new
               dispatch, or `systemctl start vivek5-spool.service`) and by the
               two HALT verbs.

``.halted`` / ``.retry`` / ``.stuck`` never match the ``.path`` unit's
``*.json`` glob, so none of them re-fires the drainer. A move into done/ or
failed/ goes only into a REAL directory owned by the runner (a symlinked
done/ is refused); if the move fails the file is renamed ``.stuck``. After the
walk, any leftover ``*.json`` entry the drain did not consume -- a symlink, a
directory, a hand-dropped ``test.json`` -- is renamed ``.stuck`` too, so the
glob goes false and the drainer cannot restart in a loop (the unit has
``StartLimitIntervalSec=0``). Refusals, unreadable files and stuck entries are
``report.problems``: ``drain-spool`` exits non-zero on them so the OnFailure
hook alerts (a 202 that never runs must not be silent).

A close batch reaches the job as the ``VIVEK_CLOSE_BATCH`` env value (the
``batch`` arg), never argv.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import re
import secrets
import stat
from dataclasses import dataclass, field

from scanner import config

from . import (EXIT_HALTED, EXIT_LOCK_TIMEOUT, emit, ensure_state_dirs, iso,
               state_dir as _state_dir, utcnow)

NAME_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}\.json$")
SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,15}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MARKETS = ("asx", "nasdaq", "crypto")


class SpoolRefused(ValueError):
    """The dispatch does not match any allowed workflow/input shape."""


HELD_SUFFIXES = (".halted", ".retry")


@dataclass
class DrainReport:
    ran: list = field(default_factory=list)      # (name, job, exit)
    done: list = field(default_factory=list)
    failed: list = field(default_factory=list)   # (name, reason)
    skipped: list = field(default_factory=list)  # (name, reason) -- left in place (arrived mid-drain)
    stuck: list = field(default_factory=list)    # (name, reason) -- renamed <name>.stuck
    halted: list = field(default_factory=list)   # (name, job) -- renamed <name>.halted
    retry: list = field(default_factory=list)    # (name, job) -- renamed <name>.retry
    requeued: list = field(default_factory=list)
    problems: list = field(default_factory=list)  # (name, reason) an operator must see

    @property
    def needs_operator(self) -> bool:
        return bool(self.problems or self.stuck)


# -- validation (mirrors functions/api/*.js) ----------------------------------

def _close_entry(c) -> dict:
    if not isinstance(c, dict):
        raise SpoolRefused("close entry is not an object")
    sym = str(c.get("symbol", "")).strip().upper()
    mkt = str(c.get("market", "")).strip().lower()
    try:
        px = float(c.get("price"))
    except (TypeError, ValueError):
        raise SpoolRefused(f"close entry {sym or '?'}: price is not a number") from None
    if not SYMBOL_RE.match(sym) or not math.isfinite(px) or px <= 0:
        raise SpoolRefused(f"close entry {sym or '?'}: symbol and a positive price are required")
    if mkt not in MARKETS:
        raise SpoolRefused(f"close entry {sym}: market must be asx|nasdaq|crypto")
    return {"symbol": sym, "market": mkt,
            "direction": "short" if c.get("direction") == "short" else "long",
            "price": str(px)}


def validate_dispatch(workflow: str, inputs) -> tuple[str, dict]:
    """(job name, job args) for an allowed dispatch; SpoolRefused otherwise."""
    if not isinstance(inputs, dict):
        raise SpoolRefused("inputs is not an object")
    if workflow == "scan.yml":
        market = str(inputs.get("market", "")).strip().lower()
        reason = str(inputs.get("reason", "manual")).strip().lower()
        extra = set(inputs) - {"market", "reason"}
        if extra:
            raise SpoolRefused(f"scan.yml: unknown input(s) {sorted(extra)}")
        if market not in MARKETS + ("all",):
            raise SpoolRefused("scan.yml: market must be asx|nasdaq|crypto|all")
        if reason not in ("manual", "heartbeat"):
            raise SpoolRefused("scan.yml: reason must be manual|heartbeat")
        return workflow, {"market": market, "reason": reason, "slot": "manual"}
    if workflow == "close_position.yml":
        jt = str(inputs.get("journal_type", "")).strip()
        if jt not in ("bot", "swing", "scalp"):
            raise SpoolRefused("close_position.yml: journal_type must be bot|swing|scalp")
        raw_batch = inputs.get("closes")
        if raw_batch is None and inputs.get("batch"):
            try:
                raw_batch = json.loads(inputs["batch"])
            except (TypeError, ValueError) as e:
                raise SpoolRefused(f"close_position.yml: batch is not JSON ({type(e).__name__})") from None
        if raw_batch is not None:
            if jt != "bot":
                raise SpoolRefused("close_position.yml: batch close is bot-book only")
            if not isinstance(raw_batch, list) or not 1 <= len(raw_batch) <= 30:
                raise SpoolRefused("close_position.yml: batch must contain 1-30 closes")
            entries = []
            seen = set()
            for c in raw_batch:
                e = _close_entry(c)
                key = e["market"] + ":" + e["symbol"]
                if key in seen:
                    raise SpoolRefused(f"close_position.yml: batch lists {e['symbol']} twice")
                seen.add(key)
                entries.append(e)
            n = len(entries)
            return workflow, {
                "symbol": entries[0]["symbol"] + (f"+{n - 1}" if n > 1 else ""),
                "direction": "long", "market": entries[0]["market"], "price": entries[0]["price"],
                "exit_date": "", "journal_type": "bot",
                "batch": json.dumps(entries, separators=(",", ":")),
            }
        sym = str(inputs.get("symbol", "")).strip().upper()
        mkt = str(inputs.get("market", "")).strip().lower()
        try:
            px = float(inputs.get("price"))
        except (TypeError, ValueError):
            raise SpoolRefused("close_position.yml: price is not a number") from None
        if not SYMBOL_RE.match(sym) or not math.isfinite(px) or px <= 0:
            raise SpoolRefused("close_position.yml: symbol and a positive price are required")
        if mkt not in MARKETS + ("scalp", ""):
            raise SpoolRefused("close_position.yml: invalid market")
        if jt == "bot" and mkt not in MARKETS:
            raise SpoolRefused("close_position.yml: a bot close needs market asx|nasdaq|crypto")
        exit_date = str(inputs.get("exit_date", "") or "")
        if exit_date and not DATE_RE.match(exit_date):
            exit_date = ""
        return workflow, {"symbol": sym, "direction": "short" if inputs.get("direction") == "short" else "long",
                          "market": mkt, "price": str(px), "exit_date": exit_date,
                          "journal_type": jt, "batch": ""}
    if workflow == "morning_plays.yml":
        slot = str(inputs.get("slot", "")).strip()
        if set(inputs) - {"slot"}:
            raise SpoolRefused("morning_plays.yml: unknown input(s)")
        if slot not in ("asx", "us"):
            raise SpoolRefused("morning_plays.yml: slot must be asx|us")
        return workflow, {"slot": slot}
    if workflow == "momentum.yml":
        if inputs:
            raise SpoolRefused("momentum.yml: takes no inputs")
        return workflow, {}
    raise SpoolRefused(f"unknown workflow {workflow!r}")


# -- writing (the runner's own chain: morning_plays -> momentum) --------------

def new_id(now=None) -> str:
    return f"{(now or utcnow()).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"


def write_spool(workflow: str, inputs: dict, source: str, *,
                state_dir: pathlib.Path | None = None, now=None) -> pathlib.Path:
    """Write a dispatch atomically (tmp + rename) the way the adapter does."""
    state = ensure_state_dirs(pathlib.Path(state_dir) if state_dir else _state_dir())
    now = now or utcnow()
    sid = new_id(now)
    body = {"id": sid, "received_at": iso(now), "workflow": workflow,
            "inputs": dict(inputs), "source": source}
    tmp = state / "spool" / ".tmp" / f"{sid}.json"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(body, fh, separators=(",", ":"))
        fh.write("\n")
    final = state / "spool" / f"{sid}.json"
    os.replace(tmp, final)
    return final


# -- draining -----------------------------------------------------------------

def pending(state_dir: pathlib.Path | None = None) -> list[pathlib.Path]:
    state = pathlib.Path(state_dir) if state_dir else _state_dir()
    try:
        names = sorted(os.listdir(state / "spool"))
    except OSError:
        return []
    return [state / "spool" / n for n in names if NAME_RE.match(n)]


def held(state_dir: pathlib.Path | None = None, suffixes=HELD_SUFFIXES) -> list[pathlib.Path]:
    """Dispatches parked as ``<name>.halted`` / ``<name>.retry``."""
    state = pathlib.Path(state_dir) if state_dir else _state_dir()
    try:
        names = sorted(os.listdir(state / "spool"))
    except OSError:
        return []
    out = []
    for n in names:
        for suf in suffixes:
            if n.endswith(suf) and NAME_RE.match(n[: -len(suf)]):
                out.append(state / "spool" / n)
    return out


def requeue(state_dir: pathlib.Path | None = None, suffixes=HELD_SUFFIXES) -> list[str]:
    """Rename parked dispatches back to ``<name>.json`` so the next drain runs
    them (the .path unit fires on the rename). Returns the names re-queued."""
    out = []
    for p in held(state_dir, suffixes):
        base = p.name[: p.name.rindex(".")]
        try:
            os.replace(p, p.with_name(base))
            out.append(base)
            emit(f"spool: re-queued {base} (was {p.name[len(base):]})")
        except OSError as e:
            emit(f"spool: could not re-queue {p.name} ({type(e).__name__})")
    return out


def _real_dir_of_ours(d: pathlib.Path) -> bool:
    """done/ and failed/ must be real directories owned by the runner -- a
    symlinked done/ would let whoever planted it choose where the drainer
    drops an adapter-written file (security review)."""
    try:
        st = os.lstat(d)
    except FileNotFoundError:
        try:
            d.mkdir(parents=True, exist_ok=True)
            st = os.lstat(d)
        except OSError:
            return False
    except OSError:
        return False
    if not stat.S_ISDIR(st.st_mode):
        return False
    return not hasattr(os, "getuid") or st.st_uid == os.getuid()


def _stuck(path: pathlib.Path, report: DrainReport, reason: str) -> None:
    try:
        os.replace(path, path.with_name(path.name + ".stuck"))
        emit(f"spool: {path.name} renamed .stuck ({reason})")
    except OSError as e:
        emit(f"spool: {path.name} could not be renamed .stuck ({type(e).__name__}); {reason}")
        reason = f"{reason}; rename failed ({type(e).__name__})"
    report.stuck.append((path.name, reason))


def _move(path: pathlib.Path, dest_dir: pathlib.Path, report: DrainReport, bucket: list, note) -> None:
    if not _real_dir_of_ours(dest_dir):
        _stuck(path, report, f"{dest_dir.name}/ is not a real directory owned by the runner")
        return
    try:
        os.replace(path, dest_dir / path.name)
        bucket.append((path.name, note) if note is not None else path.name)
    except OSError as e:
        _stuck(path, report, f"move to {dest_dir.name}/ failed ({type(e).__name__})")


def _park(path: pathlib.Path, suffix: str, bucket: list, job: str, report: DrainReport) -> None:
    try:
        os.replace(path, path.with_name(path.name + suffix))
        bucket.append((path.name, job))
    except OSError as e:
        # left as *.json it would re-fire the .path unit at once (exit 4 is
        # instant): take it out of the glob as .stuck and tell the operator
        why = f"could not park as {suffix} ({type(e).__name__})"
        emit(f"spool: {path.name} {why}")
        _stuck(path, report, why)
        report.problems.append((path.name, why))


def _read_body(path: pathlib.Path, max_bytes: int):
    """(body, None) or (None, reason). O_NOFOLLOW + fstat: never follows a
    symlink planted over a pending name, never reads past the cap."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None, "not a regular file"
        if st.st_size > max_bytes:
            return None, "oversize"
        raw = b""
        while len(raw) <= max_bytes:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            raw += chunk
        if len(raw) > max_bytes:
            return None, "oversize"
    finally:
        os.close(fd)
    return json.loads(raw.decode("utf-8")), None


def drain(runner, *, state_dir: pathlib.Path | None = None,
          max_bytes: int = config.VPS_SPOOL_MAX_BYTES) -> DrainReport:
    """Execute queued dispatches oldest first via ``runner(job_name, args, source)``.

    ``runner`` returns the job's exit code (0 ok, 3 skipped, 4 halted, 5 lock
    wait timed out, 1 failed). See the module docstring for where each lands.
    """
    state = ensure_state_dirs(pathlib.Path(state_dir) if state_dir else _state_dir())
    report = DrainReport()
    spool_dir = state / "spool"
    done_dir, failed_dir = spool_dir / "done", spool_dir / "failed"
    report.requeued = requeue(state, (".retry",))
    consumed: set[str] = set()
    for path in pending(state):
        consumed.add(path.name)
        try:
            st = os.lstat(path)
        except OSError:
            continue
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            _stuck(path, report, "not a regular file")
            report.problems.append((path.name, "not a regular file"))
            continue
        if st.st_size > max_bytes:
            emit(f"spool: {path.name} is {st.st_size} bytes (> {max_bytes}) - refused unread")
            _move(path, failed_dir, report, report.failed, "oversize")
            report.problems.append((path.name, "oversize"))
            continue
        try:
            body, why = _read_body(path, max_bytes)
            if why is None:
                workflow = body["workflow"]
                inputs = body.get("inputs", {})
                source = str(body.get("source", "?"))
        except Exception as e:                                   # noqa: BLE001 - TYPE only, by design
            body, why = None, type(e).__name__
        if why is not None:
            emit(f"spool: {path.name} unreadable ({why})")
            if why == "not a regular file":
                _stuck(path, report, why)
            else:
                _move(path, failed_dir, report, report.failed, why)
            report.problems.append((path.name, f"unreadable: {why}"))
            continue
        try:
            job_name, args = validate_dispatch(str(workflow), inputs)
        except SpoolRefused as e:
            emit(f"spool: {path.name} refused - {e}")
            _move(path, failed_dir, report, report.failed, str(e))
            report.problems.append((path.name, f"refused: {e}"))
            continue
        emit(f"spool: {path.name} -> run {job_name} {sorted(k for k in args if k != 'batch')} (source {source})")
        try:
            code = int(runner(job_name, args, source))
        except Exception as e:                                   # noqa: BLE001 - the file must still move
            emit(f"spool: {path.name} runner raised {type(e).__name__}: {e}")
            code = 1
        report.ran.append((path.name, job_name, code))
        if code in (0, 3):
            _move(path, done_dir, report, report.done, None)
        elif code == EXIT_HALTED:
            emit(f"spool: {path.name} parked as .halted - re-queued by accept-upstream / clear-halt")
            _park(path, ".halted", report.halted, job_name, report)
        elif code == EXIT_LOCK_TIMEOUT:
            emit(f"spool: {path.name} parked as .retry - re-queued by the next drain")
            _park(path, ".retry", report.retry, job_name, report)
        else:
            _move(path, failed_dir, report, report.failed, f"exit {code}")
    # Leftover *.json entries this walk did not consume keep the .path unit's
    # glob true: rename them .stuck so the drainer cannot loop on them. A
    # VALID dispatch that arrived mid-drain is left alone (the unit re-fires).
    try:
        leftovers = sorted(os.scandir(spool_dir), key=lambda e: e.name)
    except OSError:
        leftovers = []
    for entry in leftovers:
        if not entry.name.endswith(".json") or entry.name in consumed:
            continue
        valid = NAME_RE.match(entry.name) and entry.is_file(follow_symlinks=False)
        if valid:
            report.skipped.append((entry.name, "arrived during this drain"))
            continue
        why = "symlink" if entry.is_symlink() else ("not a dispatch file name" if entry.is_file(follow_symlinks=False)
                                                   else "not a regular file")
        _stuck(pathlib.Path(entry.path), report, why)
        report.problems.append((entry.name, why))
    return report
