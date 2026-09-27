"""The JOBS table -- dataclasses over ``workflows.json`` (DESIGN section 3.2).

One entry per GitHub workflow that runs on the VPS, keyed by the workflow FILE
NAME (that key is also the ledger key, so config.WATCHDOG_RUNS maps 1:1).
Steps, env allow-lists, staging lists, must-change sets, commit messages and
the manual-vs-scheduled branches are TRANSCRIBED from the workflows into the
JSON; this module only gives them a shape and validates operator input. The
runner must not invent a step that is not in the table, and every Actions-only
step the transcription dropped is recorded under ``Job.dropped`` with a reason
so a reader can audit the mapping (tests/test_vps_jobs.py walks it).

Step kinds the runner understands (``Step.kind``):
  cmd              one argv (``python``/``python3`` = the venv interpreter),
                   optional stdin script, ok_exit_codes, continue_on_error,
                   capture (keep the output for a sentinel grep), sets_flag
  markets          one argv template per market: single market or the
                   workflow's ``order_all`` (optionally two in parallel),
                   pass iff every ``require_ok`` market exited 0
  group            fixed argv list with tags; same require_ok / ignore_rc rule
  publish          run the job's publish here (``leg`` for streamed commits)
  close            close_position's three-way branch (batch / bot / legacy)
  momentum_screen  scanner.momentum.run with the 0 / 3 / other exit contract
  brief            evidence_brief's rc 0|1 = green rule, stdout to a file
  morning_plays    the --slot / --redeliver / --force argv mapping
  offbox_copy      backup_book's optional VIVEK_BACKUP_TARGET copy
  spool_momentum   the workflow_run piggyback: spool one momentum dispatch

Argument shapes: ``key=value`` pairs; ``operator_only`` keys (extra / args /
force / dry_run / mode / window / backtest) are dropped by the spool drainer.
``default_by_slot`` derives ``reason`` from the slot: a scheduled slot means
``cron`` (the workflow's GITHUB_EVENT_NAME=schedule branch), anything else
``manual``.
"""
from __future__ import annotations

import json
import pathlib
import re
import shlex
from dataclasses import dataclass, field, replace as _dc_replace

from scanner import config

TABLE_FILE = pathlib.Path(__file__).with_name("workflows.json")

FAMILY_LOCK_WAIT = config.VPS_LOCK_WAIT_S


class ArgError(ValueError):
    """Operator/spool input the job's arg spec refuses."""


@dataclass(frozen=True)
class Step:
    name: str
    kind: str = "cmd"
    argv: tuple = ()
    stdin: str | None = None
    env_pass: tuple = ()
    env_set: dict = field(default_factory=dict)
    env_ctx: dict = field(default_factory=dict)
    continue_on_error: bool = False
    ok_exit_codes: tuple = (0,)
    capture: str | None = None
    warn_on_fail: str | None = None
    sets_flag: str | None = None
    sets_scanned: bool = False
    gated: bool = False
    always: bool = False
    when: str | None = None
    to_summary: bool = False
    # markets / group
    order_all: tuple = ()
    parallel: tuple = ()
    require_ok: tuple = ()
    ignore_rc: bool = False
    market_arg: str = "market"
    cmds: tuple = ()
    # publish
    leg: str | None = None
    # free-form extras the specialised kinds read (messages etc.)
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Publish:
    paths: tuple
    must_change: dict
    message: str
    rebuild_combined: object = False          # True | False | "bot_only"
    paths_per_market: tuple = ()
    required_paths: tuple = ()
    nothing_msg: str = "Nothing to commit."


@dataclass(frozen=True)
class Job:
    name: str
    display: str
    family: str | None
    slots: tuple
    scheduled_slots: tuple
    args: dict
    steps: tuple
    publish: Publish | None
    dropped: tuple
    timeout_s: int
    gate: str | None = None
    gate_mode: str = "job"
    recheck: tuple = ()
    book_writer: bool = False
    scan_family: bool = False

    @property
    def lock_wait_s(self) -> int:
        return int(FAMILY_LOCK_WAIT.get(self.family or "", FAMILY_LOCK_WAIT["default"]))

    @property
    def locks(self) -> tuple:
        """Lock names in acquisition order after the shared ``repo`` lock."""
        own = self.name[:-4] if self.name.endswith(".yml") else self.name
        names = [self.family] if self.family else []
        if own not in names:          # scan.yml's own name IS its family: one flock, not two
            names.append(own)
        return tuple(names)

    @property
    def operator_only_args(self) -> tuple:
        return tuple(k for k, spec in self.args.items() if spec.get("operator_only"))


def _step(raw: dict) -> Step:
    known = {f for f in Step.__dataclass_fields__}
    kw = {}
    extra = {}
    for k, v in raw.items():
        if k in known and k != "extra":
            kw[k] = v
        else:
            extra[k] = v
    for tup in ("argv", "env_pass", "ok_exit_codes", "order_all", "parallel", "require_ok"):
        if tup in kw:
            kw[tup] = tuple(kw[tup])
    if "cmds" in kw:
        kw["cmds"] = tuple({**c, "argv": tuple(c["argv"])} for c in kw["cmds"])
    kw["extra"] = extra
    return Step(**kw)


def _publish(raw: dict | None) -> Publish | None:
    if not raw:
        return None
    return Publish(paths=tuple(raw["paths"]), must_change=dict(raw["must_change"]),
                   message=raw["message"], rebuild_combined=raw.get("rebuild_combined", False),
                   paths_per_market=tuple(raw.get("paths_per_market", ())),
                   required_paths=tuple(raw.get("required_paths", ())),
                   nothing_msg=raw.get("nothing_msg", "Nothing to commit."))


def load_table(path: pathlib.Path = TABLE_FILE) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    jobs = {}
    for name, raw in doc["jobs"].items():
        jobs[name] = Job(
            name=name, display=raw.get("display", name), family=raw.get("family"),
            slots=tuple(raw.get("slots", ())), scheduled_slots=tuple(raw.get("scheduled_slots", ())),
            args=dict(raw.get("args", {})), steps=tuple(_step(s) for s in raw["steps"]),
            publish=_publish(raw.get("publish")), dropped=tuple(tuple(d) for d in raw.get("dropped", ())),
            timeout_s=int(raw["timeout_s"]), gate=raw.get("gate"), gate_mode=raw.get("gate_mode", "job"),
            recheck=tuple(raw.get("recheck", ())), book_writer=bool(raw.get("book_writer")),
            scan_family=bool(raw.get("scan_family")),
        )
    return jobs


JOBS: dict[str, Job] = load_table()


def resolve_name(name: str) -> str:
    """Accept ``scan`` or ``scan.yml``; raise KeyError for anything else."""
    cand = name if name.endswith(".yml") else name + ".yml"
    if cand not in JOBS:
        raise KeyError(f"unknown job {name!r}; run `python -m scanner.vps list`")
    return cand


def get(name: str) -> Job:
    return JOBS[resolve_name(name)]


def book_writers() -> tuple:
    return tuple(n for n, j in JOBS.items() if j.book_writer)


def data_roots() -> tuple:
    """Union of every job's publish paths -- the second-writer check's scope."""
    roots: set[str] = set()
    for job in JOBS.values():
        if not job.publish:
            continue
        for p in job.publish.paths:
            roots.add(p.replace("{file}", ""))
        for tpl in job.publish.paths_per_market:
            for m in config.MARKETS:
                roots.add(tpl.replace("{m}", m))
    # a template that lost its {file} tail is a directory prefix; strip a trailing slash
    return tuple(sorted(r.rstrip("/") for r in roots if r))


# -- arguments -----------------------------------------------------------------

def parse_kv(pairs) -> dict:
    out = {}
    for item in pairs or ():
        if "=" not in item:
            raise ArgError(f"expected key=value, got {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v
    return out


def parse_args(job: Job, given: dict, *, operator: bool = True) -> dict:
    """Validate ``given`` against the job's arg spec and fill defaults.

    ``operator=False`` (the spool drainer) DROPS operator-only keys silently,
    which is the DESIGN 3.1 rule: an API caller can never reach ``extra``,
    ``force`` or ``dry_run``. Unknown keys are refused either way.
    """
    spec = job.args
    unknown = sorted(set(given) - set(spec))
    if unknown:
        raise ArgError(f"{job.name}: unknown arg(s) {unknown}; accepts {sorted(spec)}")
    out = {}
    for key, rule in spec.items():
        if key in given and (operator or not rule.get("operator_only")):
            val = str(given[key])
        elif rule.get("required"):
            raise ArgError(f"{job.name}: {key} is required")
        else:
            val = None
        if val is None:
            if rule.get("default_by_slot"):
                continue                        # filled below, needs the slot
            val = str(rule.get("default", ""))
        if rule.get("upper"):
            val = val.strip().upper()
        if "choices" in rule and val not in rule["choices"]:
            raise ArgError(f"{job.name}: {key}={val!r} not in {rule['choices']}")
        if rule.get("pattern") and not re.match(rule["pattern"], val):
            raise ArgError(f"{job.name}: {key}={val!r} does not match {rule['pattern']}")
        if rule.get("positive_number"):
            try:
                num = float(val)
            except ValueError:
                raise ArgError(f"{job.name}: {key}={val!r} is not a number") from None
            if not (num > 0) or num != num or num in (float("inf"),):
                raise ArgError(f"{job.name}: {key} must be a finite positive number")
        out[key] = val
    for key, rule in spec.items():
        if rule.get("default_by_slot") and key not in out:
            slot = out.get("slot", "manual")
            out[key] = "cron" if slot in job.scheduled_slots else "manual"
    return out


def is_scheduled(job: Job, args: dict) -> bool:
    """The workflow's ``GITHUB_EVENT_NAME == schedule`` branch."""
    if "reason" in args:
        return args["reason"] == "cron"
    slot = args.get("slot")
    if slot is not None:
        return slot in job.scheduled_slots
    # no reason/slot arg at all: a timer-only job (reco_note) is scheduled, a
    # dispatch-only one (close_position, scheduled_slots empty) never is
    return bool(job.scheduled_slots)


def split_extra(value: str | None) -> list[str]:
    """The workflow's unquoted ``$ARGS`` word-split, done with shlex."""
    return shlex.split(value) if value else []


def with_publish(job: Job, **changes) -> Job:
    """A copy of ``job`` with publish fields replaced (tests build scenarios with it)."""
    pub = job.publish
    assert pub is not None
    return _dc_replace(job, publish=_dc_replace(pub, **changes))


def table_rows() -> list[dict]:
    rows = []
    for name, job in JOBS.items():
        rows.append({
            "job": name, "family": job.family or "-", "gate": job.gate or "-",
            "slots": ",".join(job.slots), "timeout_s": job.timeout_s,
            "lock_wait_s": job.lock_wait_s, "book_writer": job.book_writer,
            "publish_paths": len(job.publish.paths) + len(job.publish.paths_per_market) if job.publish else 0,
            "must_change": job.publish.must_change.get("policy") if job.publish else "-",
            "steps": len(job.steps), "dropped": len(job.dropped),
            "operator_only": ",".join(job.operator_only_args) or "-",
        })
    return rows
