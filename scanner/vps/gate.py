"""Fire-time gates (DESIGN section 3.3) -- import config, never re-type numbers.

Each gate answers "should this fire run?" at the moment the timer elapses and
returns a ``GateResult`` (``due`` + a printed reason). The runner evaluates it
BEFORE taking any lock, and re-evaluates the close/backstop scan slots after
the lock so a post-close scan that landed while waiting is not repeated.

The windows/thresholds come from ``scanner.config`` (``MARKET_SCAN_WINDOWS``,
``MORNING_PLAYS_SLOT_GATE`` via ``scripts.morning_plays.scan_is_post_close``,
``VPS_CRYPTO_BACKSTOP_FRESH_S``) exactly as the workflows' inlined tables did.
Every gate takes an injectable ``now`` (UTC-aware) for the tests. The runner's
post-lock re-check calls the gate again with the SAME fire-time ``now`` and
fresh data ("did something land while I waited?"), never a later clock.

Side effects: none, except ``momentum_gate``, which runs ``git fetch origin
main`` in the working checkout (momentum_due reads main's published stamps by
design) -- never with ``--depth``, bounded, under the repo lock, and skipped
with a warning when the network or the lock is unavailable.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from scanner import config

from . import emit, home as _home, iso, python_bin, state_dir as _state_dir, utcnow
from . import ledger as _ledger
from .locks import Lock, LockTimeout, lock_path

_CLOSE_MINUTE = 16 * 60          # the workflow's "960 = 16:00 market-local"


@dataclass
class GateResult:
    due: bool
    why: str
    market: str | None = None     # a market override (scan probe fail-open -> "all")
    warning: str | None = None

    def __bool__(self) -> bool:
        return self.due


class GateError(RuntimeError):
    """The gate itself crashed (not a skip): the run is a FAILURE."""


def _local_now(tz_name: str, now: dt.datetime):
    from zoneinfo import ZoneInfo
    return now.astimezone(ZoneInfo(tz_name))


def _read_stamp(path: pathlib.Path, key: str = "generated_at") -> str | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    val = doc.get(key) if isinstance(doc, dict) else None
    return str(val) if val else None


def _slot_for_market(market: str) -> str | None:
    """The MORNING_PLAYS_SLOT_GATE slot whose gate market is ``market``."""
    for slot, gate in config.MORNING_PLAYS_SLOT_GATE.items():
        if gate.get("market") == market:
            return slot
    return None


def post_close_scan_landed(market: str, now: dt.datetime, home: pathlib.Path) -> tuple[bool, str]:
    """(landed, why): is ``public/data/<market>_prices.json`` stamped at/after
    the market's most recent weekday close? Reuses morning_plays' helper so the
    close time is typed once (config.MORNING_PLAYS_SLOT_GATE)."""
    from scripts import morning_plays as mp
    slot = _slot_for_market(market)
    if slot is None:
        return False, f"no post-close gate is defined for {market}"
    stamp = _read_stamp(home / "public" / "data" / f"{market}_prices.json")
    ok, why = mp.scan_is_post_close(slot, stamp, now)
    return ok, why


# -- scan.yml ------------------------------------------------------------------

def scan_gate(market: str, slot: str, *, now: dt.datetime | None = None,
              home: pathlib.Path | None = None) -> GateResult:
    """The scan.yml gate job, per slot.

    manual      no window (parity with workflow_dispatch); ``all`` only here
    hourly      weekday in the market's zone AND minute-of-day inside
                config.MARKET_SCAN_WINDOWS[market] (inclusive)
    close       weekday AND 16:00 <= local time <= the window's end: DUE,
                unconditionally -- scan.yml's closing cron (`30 5,6`) runs
                whatever landed before it. The 16:07 hourly ASX scan stamps
                generated_at AFTER its download (often 16:1x-16:2x), so the
                post-close rule would suppress the owner-mandated 16:30 scan
                most days (2026-09-27 parity review). Past the window's end
                (a reboot-late Persistent= fire) it falls through to:
    backstop    weekday, local time >= 16:00, AND no post-close scan yet;
                no upper bound (a reboot-late close scan is still wanted)
    Probe failure (tz database unusable) fails OPEN to ``all`` with a warning.
    """
    now = now or utcnow()
    home = pathlib.Path(home) if home else _home()
    if slot == "manual":
        return GateResult(True, f"Manual dispatch - running whatever was asked for ({market}).", market)
    if market not in config.MARKET_SCAN_WINDOWS:
        return GateResult(False, f"{slot} slot fired for market={market!r}, which has no session window "
                                 "(all/crypto are reachable only by a manual run).", market)
    tz_name, lo, hi = config.MARKET_SCAN_WINDOWS[market]
    try:
        local = _local_now(tz_name, now)
        minute = local.hour * 60 + local.minute
        weekday = local.weekday() < 5
    except Exception as e:                                   # noqa: BLE001 - fail OPEN, as the YAML
        warn = "::warning::scan gate - session probe failed; scanning all markets (fail open)"
        return GateResult(True, f"{warn} ({type(e).__name__})", "all", warn)
    stamp = f"{local:%a %H:%M} {tz_name}"
    if slot == "hourly":
        if weekday and lo <= minute <= hi:
            return GateResult(True, f"In session: {market} ({stamp})", market)
        return GateResult(False, "Outside every market session (weekend, overnight, or pre-open) "
                                 f"- nothing to scan. ({market} {stamp})", market)
    if slot in ("close", "backstop"):
        if not weekday:
            return GateResult(False, f"{slot} slot fired on a weekend ({stamp}) - nothing to scan.", market)
        if minute < _CLOSE_MINUTE:
            return GateResult(False, f"Closing slot [{slot}] fired at {local:%H:%M} {market}-local "
                                     "- before the close. Skipping.", market)
        if slot == "close" and minute <= hi:
            return GateResult(True, f"close slot at {local:%H:%M} {market}-local, inside the closing window "
                                    f"(16:00-{hi // 60:02d}:{hi % 60:02d}) - the closing scan runs "
                                    "unconditionally (scan.yml parity).", market)
        landed, why = post_close_scan_landed(market, now, home)
        if landed:
            return GateResult(False, f"{slot} slot - a post-close {market} scan already landed "
                                     f"({why}). Skipping.", market)
        return GateResult(True, f"{slot} slot - no post-close {market} scan yet ({why}). "
                                "Running the closing scan.", market)
    return GateResult(False, f"unknown scan slot {slot!r}", market)


# -- crypto_bot.yml ------------------------------------------------------------

def crypto_gate(slot: str, *, now: dt.datetime | None = None,
                home: pathlib.Path | None = None) -> GateResult:
    """``hourly`` always runs; ``backstop`` skips when the LOCAL
    public/data/crypto_vivek.json is fresher than the workflow's 3900 s,
    fail-open on stale/unreadable; ``manual`` is never gated."""
    if slot != "backstop":
        return GateResult(True, f"{slot} - run=true")
    now = now or utcnow()
    home = pathlib.Path(home) if home else _home()
    stamp = _read_stamp(home / "public" / "data" / "crypto_vivek.json")
    age = "unknown"
    if stamp:
        try:
            t = dt.datetime.fromisoformat(stamp)
            if t.tzinfo is None:
                t = t.replace(tzinfo=dt.timezone.utc)
            secs = (now - t).total_seconds()
            age = "fresh" if secs < config.VPS_CRYPTO_BACKSTOP_FRESH_S else "stale"
        except ValueError:
            age = "unknown"
    if age == "fresh":
        return GateResult(False, "Backstop :52 - crypto scanned within "
                                 f"{config.VPS_CRYPTO_BACKSTOP_FRESH_S // 60} min. Skipping.")
    return GateResult(True, f"Backstop :52 - stale or unreadable ({age}). Running the missed cycle.")


# -- backup_book.yml -----------------------------------------------------------

def backup_gate(slot: str, *, now: dt.datetime | None = None,
                home: pathlib.Path | None = None) -> GateResult:
    """``backstop`` skips iff a ``backups/<UTC date>T...`` entry exists."""
    if slot != "backstop":
        return GateResult(True, f"{slot} - run=true")
    now = now or utcnow()
    home = pathlib.Path(home) if home else _home()
    prefix = now.astimezone(dt.timezone.utc).strftime("%Y-%m-%d") + "T"
    try:
        names = [p.name for p in (home / "backups").iterdir()]
    except OSError:
        names = []
    if any(n.startswith(prefix) for n in names):
        return GateResult(False, "Backstop 23:35 - today's snapshot already exists. Skipping.")
    return GateResult(True, "Backstop 23:35 - no snapshot for today yet. Running.")


# -- daily writers with a "did the scheduled run succeed today" backstop ------

def ledger_today_gate(job_name: str, slot: str, scheduled_slots, *,
                      now: dt.datetime | None = None,
                      ledger_file: pathlib.Path | None = None) -> GateResult:
    """``backstop`` skips iff the ledger shows a SCHEDULED success for the job
    today (UTC). A failed primary, or a manual run, does not suppress it; an
    unreadable ledger reads as 'no run today' (fail-open)."""
    if slot != "backstop":
        return GateResult(True, f"{slot} - run=true")
    row = _ledger.success_today(job_name, now, ledger_file)
    if row and (row.get("last_success_args") or {}).get("slot") in tuple(scheduled_slots):
        return GateResult(False, f"backstop - a scheduled {job_name} run already succeeded today "
                                 f"({row.get('last_success_at')}). Skipping.")
    return GateResult(True, f"backstop - no scheduled {job_name} success today. Running.")


# -- momentum.yml --------------------------------------------------------------

def momentum_gate(market: str | None, *, home: pathlib.Path | None = None,
                  state_dir: pathlib.Path | None = None, run=None,
                  python: str | None = None) -> GateResult:
    """``scripts/momentum_due.py`` decides which market is due.

    A named ``market`` (manual dispatch) means NO due check. Otherwise the
    stamps are read from origin/main as the workflow does (``git fetch`` then
    ``git show origin/main:...``) into a temp dir, and the script's
    ``market=`` output picks the market; empty -> not due.

    The fetch is a plain ``git fetch --quiet origin main`` -- NEVER
    ``--depth``: the workflow's ``--depth=1`` ran inside an already-shallow
    Actions checkout, but on the box it converted the FULL working clone to a
    shallow one on every fire, which hid foreign data commits from update.sh's
    second-writer scan and truncated every ``git log`` reader (2026-09-27
    reviews). It runs under the ``repo`` lock SHARED (so it never races
    update.sh / gc.sh), bounded by config.VPS_MOMENTUM_FETCH_TIMEOUT_S; a busy
    lock, a timeout, an OSError or a non-zero exit only WARN and the last
    fetched origin/main is read (offline-tolerant). A crashing momentum_due is
    a GateError, i.e. a FAILED run, never a skip.
    """
    if market:
        return GateResult(True, f"manual dispatch: {market} (no due check)", market)
    home = pathlib.Path(home) if home else _home()
    state = pathlib.Path(state_dir) if state_dir else _state_dir()
    run = run or subprocess.run
    py = python or python_bin()
    (state / "tmp").mkdir(parents=True, exist_ok=True)
    stamps = pathlib.Path(tempfile.mkdtemp(prefix="momentum-on-main-", dir=state / "tmp"))
    out_file = stamps / "github_output"
    warning = None
    try:
        warning = _fetch_origin_main(home, state, run)
        for m in ("asx", "nasdaq", "crypto"):
            show = run(["git", "show", f"origin/main:public/data/momentum/{m}.json"],
                       cwd=str(home), capture_output=True, text=True)
            if getattr(show, "returncode", 1) == 0:
                (stamps / f"{m}.json").write_text(show.stdout, encoding="utf-8")
        due = run([py, "scripts/momentum_due.py", "--dir", str(stamps)],
                  cwd=str(home), capture_output=True, text=True,
                  env={**os.environ, "GITHUB_OUTPUT": str(out_file)})
        text = (due.stdout or "") + (due.stderr or "")
        for line in text.splitlines():
            emit(line)
        if due.returncode != 0:
            raise GateError(f"momentum_due.py exited {due.returncode}")
        picked = ""
        try:
            for line in out_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("market="):
                    picked = line.split("=", 1)[1].strip()
        except OSError:
            for line in text.splitlines():
                if line.startswith("picked: ") and "nothing due" not in line:
                    picked = line.split(":", 1)[1].strip()
        if picked:
            return GateResult(True, f"picked: {picked}", picked, warning)
        return GateResult(False, "picked: nothing due", None, warning)
    finally:
        shutil.rmtree(stamps, ignore_errors=True)


FETCH_ARGV = ("git", "fetch", "--quiet", "origin", "main")      # never --depth (see momentum_gate)


def _fetch_origin_main(home: pathlib.Path, state: pathlib.Path, run) -> str | None:
    """Refresh origin/main in the working checkout; return a warning or None.

    Held under ``repo`` SHARED so update.sh / gc.sh (EXCLUSIVE) never run git
    in the same checkout at the same time. Every failure mode degrades to "use
    the last fetched ref" with a ``::warning::`` -- the network being down is
    not a reason to fail the momentum run."""
    lk = Lock(lock_path(state, "repo"), shared=True)
    try:
        lk.acquire(float(config.VPS_MOMENTUM_FETCH_LOCK_WAIT_S))
    except LockTimeout:
        return ("::warning::momentum gate - the repo lock is busy (update.sh / gc.sh); "
                "skipping git fetch and reading the last fetched origin/main")
    try:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        try:
            res = run(list(FETCH_ARGV), cwd=str(home), capture_output=True, text=True,
                      timeout=config.VPS_MOMENTUM_FETCH_TIMEOUT_S, env=env)
        except subprocess.TimeoutExpired:
            return (f"::warning::momentum gate - git fetch origin main timed out after "
                    f"{config.VPS_MOMENTUM_FETCH_TIMEOUT_S}s (network?); reading the last fetched origin/main")
        except OSError as e:
            return (f"::warning::momentum gate - git fetch could not start ({type(e).__name__}); "
                    "reading the last fetched origin/main")
        if getattr(res, "returncode", 1) != 0:
            return ("::warning::momentum gate - git fetch origin main failed (offline?); "
                    "reading the last fetched origin/main")
        return None
    finally:
        lk.release()


# -- dispatcher ----------------------------------------------------------------

def evaluate(job, args: dict, *, now: dt.datetime | None = None, home=None,
             state_dir=None, ledger_file=None, run=None, python=None) -> GateResult:
    """Route to the job's gate by the table's ``gate`` name."""
    kind = job.gate
    if not kind:
        return GateResult(True, "no gate")
    if kind == "scan":
        return scan_gate(args.get("market", "all"), args.get("slot", "manual"), now=now, home=home)
    if kind == "crypto":
        return crypto_gate(args.get("slot", "manual"), now=now, home=home)
    if kind == "backup":
        return backup_gate(args.get("slot", "manual"), now=now, home=home)
    if kind == "ledger_today":
        return ledger_today_gate(job.name, args.get("slot", "manual"), job.scheduled_slots,
                                 now=now, ledger_file=ledger_file)
    if kind == "momentum":
        return momentum_gate(args.get("market") or None, home=home, state_dir=state_dir,
                             run=run, python=python)
    raise GateError(f"unknown gate {kind!r} for {job.name}")


def describe(result: GateResult, now: dt.datetime | None = None) -> str:
    return f"gate {'DUE' if result.due else 'not due'} at {iso(now or utcnow())}: {result.why}"
