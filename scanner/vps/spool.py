"""The dispatch spool (DESIGN section 3.5): written by the API adapter, drained here.

File: ``<state>/spool/<YYYYMMDDTHHMMSSZ>-<8hex>.json`` written to
``spool/.tmp/`` and ``rename()``d into place. Body::

    {"id": "...", "received_at": "...", "workflow": "scan.yml",
     "inputs": {"market": "asx", "reason": "manual"}, "source": "api/scan"}

``drain()`` walks the directory oldest-first and, per file: only names matching
the regex; ``lstat`` and skip symlinks / non-files; size cap
``config.VPS_SPOOL_MAX_BYTES``; a parse error records the exception TYPE only;
the workflow and its inputs are RE-VALIDATED with the Functions' own shapes
(defence in depth -- the adapter already refused anything else); operator-only
keys are dropped; the job runs; the file moves to ``done/`` after exit 0/3 and
to ``failed/`` after 1/4; if that move fails it is renamed in place to
``.stuck`` so the ``.path`` unit stops re-firing on it.

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

from . import emit, ensure_state_dirs, iso, state_dir as _state_dir, utcnow

NAME_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}\.json$")
SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,15}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MARKETS = ("asx", "nasdaq", "crypto")


class SpoolRefused(ValueError):
    """The dispatch does not match any allowed workflow/input shape."""


@dataclass
class DrainReport:
    ran: list = field(default_factory=list)      # (name, job, exit)
    done: list = field(default_factory=list)
    failed: list = field(default_factory=list)   # (name, reason)
    skipped: list = field(default_factory=list)  # (name, reason) -- left in place
    stuck: list = field(default_factory=list)


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


def _move(path: pathlib.Path, dest_dir: pathlib.Path, report: DrainReport, bucket: list, note) -> None:
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        os.replace(path, dest_dir / path.name)
        bucket.append((path.name, note) if note is not None else path.name)
    except OSError as e:
        try:
            os.replace(path, path.with_name(path.name + ".stuck"))
        except OSError:
            pass
        report.stuck.append((path.name, f"{type(e).__name__}"))


def drain(runner, *, state_dir: pathlib.Path | None = None,
          max_bytes: int = config.VPS_SPOOL_MAX_BYTES) -> DrainReport:
    """Execute queued dispatches oldest first via ``runner(job_name, args, source)``.

    ``runner`` returns the job's exit code (0 ok, 3 skipped, 4 halted, 1 failed).
    """
    state = ensure_state_dirs(pathlib.Path(state_dir) if state_dir else _state_dir())
    report = DrainReport()
    done_dir, failed_dir = state / "spool" / "done", state / "spool" / "failed"
    for path in pending(state):
        try:
            st = os.lstat(path)
        except OSError:
            continue
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            report.skipped.append((path.name, "not a regular file"))
            emit(f"spool: skipping {path.name} (not a regular file)")
            continue
        if st.st_size > max_bytes:
            emit(f"spool: {path.name} is {st.st_size} bytes (> {max_bytes}) - refused unread")
            _move(path, failed_dir, report, report.failed, "oversize")
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                body = json.load(fh)
            workflow = body["workflow"]
            inputs = body.get("inputs", {})
            source = str(body.get("source", "?"))
        except Exception as e:                                   # noqa: BLE001 - TYPE only, by design
            emit(f"spool: {path.name} unreadable ({type(e).__name__})")
            _move(path, failed_dir, report, report.failed, type(e).__name__)
            continue
        try:
            job_name, args = validate_dispatch(str(workflow), inputs)
        except SpoolRefused as e:
            emit(f"spool: {path.name} refused - {e}")
            _move(path, failed_dir, report, report.failed, str(e))
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
        else:
            _move(path, failed_dir, report, report.failed, f"exit {code}")
    return report
