"""The publish step (DESIGN section 3.4): whole-file re-apply in the PUBLISH clone.

Nothing here touches the working checkout's git state. Every git call runs
with ``cwd=<publish clone>``; the working checkout is only READ (its files are
copied in). Per attempt::

  1. git fetch origin main; git reset --hard origin/main; git clean -fdq
  2. SECOND-WRITER CHECK (fail-closed): a commit in publish_head..origin/main
     that touches a data root and is not authored by the VPS identity ->
     state/HALT (json), CRITICAL alert, result "halted" (exit 4). Nothing pushed.
  3. for p in paths: exists in the working checkout -> copy in (file: copy2,
     directory: mirror with delete); else leave origin's copy. git add -- p,
     one pathspec per call; a missing path logs and continues.
  4. rebuild_combined: run vivek_run --rebuild-combined INSIDE the clone with
     PYTHONPATH unset, add the two derived files, then --verify there too.
  5. must-change asserts with the workflow's exact semantics (ANY-OF, per
     market, manual branch, .scan-skipped downgrade, sentinels, collect).
  6. commit with the VPS identity; 7. push, retry on rejection with 2**attempt
     backoff (max config.VPS_PUBLISH_MAX_ATTEMPTS); any other git error resets
     the clone and fails; 8. success -> state/publish_head = pushed sha.

Directory pathspecs are mirrored in Python (``rsync -a --delete`` semantics:
copy2 every file, delete what the source no longer has) so the runner does
not depend on rsync being installed. ``VIVEK_GIT_PUBLISH=0`` makes the whole
step a no-op that still reports "disabled" to the ledger.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import time
from dataclasses import dataclass, field

from scanner import config
from scanner.output import write_json

from . import (emit, git_identity, home as _home, iso, publish_dir as _publish_dir,
               publish_enabled, python_bin, state_dir as _state_dir, utcnow)
from . import jobs as _jobs
from . import ledger as _ledger
from . import notify as _notify
from .locks import Lock, lock_path

_REJECTED = ("rejected", "non-fast-forward", "fetch first", "failed to push some refs",
             "cannot lock ref", "stale info")
_COMBINED = ("journal/vivek_bot_book.json", "public/data/vivek_bot_book.json")
_ASSERT_FAIL = ("::error::ASSERT-STAGED FAILED ({label}): none of [{paths}] has staged changes "
                "after a successful run. Output is being LOST (see the 2026-07-20 staging "
                "incident in OPERATIONS.md). Do not ignore this.")


class PublishError(RuntimeError):
    pass


class Halted(RuntimeError):
    pass


@dataclass
class PublishResult:
    status: str                  # pushed | nothing | skipped | halted | failed | disabled
    exit_code: int = 0
    sha: str | None = None
    message: str = ""
    lines: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in ("pushed", "nothing", "skipped", "disabled") and self.exit_code == 0


@dataclass
class Check:
    label: str
    paths: list
    mode: str                    # hard | soft | collect
    warn: str = ""


# -- plumbing -----------------------------------------------------------------

def _git(clone: pathlib.Path, *args, check: bool = True, env: dict | None = None,
         run=subprocess.run) -> subprocess.CompletedProcess:
    res = run(["git", *args], cwd=str(clone), capture_output=True, text=True, env=env)
    if check and res.returncode != 0:
        raise PublishError(f"git {' '.join(args)} failed ({res.returncode}): "
                           f"{_ledger.redact((res.stderr or res.stdout or '').strip())[-400:]}")
    return res


def _git_env() -> dict:
    name, email = git_identity()
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
                "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email})
    return env


def mirror_dir(src: pathlib.Path, dst: pathlib.Path) -> None:
    """rsync -a --delete in Python: copy2 everything, remove what src lacks."""
    src, dst = pathlib.Path(src), pathlib.Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    wanted: set[pathlib.Path] = set()
    for root, dirs, files in os.walk(src):
        rel = pathlib.Path(root).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        wanted.add((dst / rel).resolve())
        for f in files:
            s, d = pathlib.Path(root) / f, dst / rel / f
            if d.is_dir():
                shutil.rmtree(d)
            shutil.copy2(s, d)
            wanted.add(d.resolve())
    for root, dirs, files in os.walk(dst, topdown=False):
        for f in files:
            p = pathlib.Path(root) / f
            if p.resolve() not in wanted:
                p.unlink()
        for d in dirs:
            p = pathlib.Path(root) / d
            if p.resolve() not in wanted and not any(p.iterdir()):
                p.rmdir()


def copy_in(home: pathlib.Path, clone: pathlib.Path, rel: str) -> bool:
    """Copy one listed path from the working checkout; False when it is absent
    there (the YAML's ``cat-file -e`` rule: origin's copy is left as it is)."""
    src, dst = home / rel, clone / rel
    if src.is_dir():
        mirror_dir(src, dst)
        return True
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_dir():
            shutil.rmtree(dst)
        shutil.copy2(src, dst)
        return True
    return False


def staged_diff(clone: pathlib.Path, rel: str, run=subprocess.run) -> bool:
    """``! git diff --cached --quiet -- rel`` (modified OR newly added)."""
    res = _git(clone, "diff", "--cached", "--quiet", "--", rel, check=False, run=run)
    return res.returncode != 0


def read_skip_marker(home: pathlib.Path) -> list[str]:
    """``.scan-skipped`` exactly as the commit step reads it (tr -d '\\r', words)."""
    try:
        text = (home / config.SCAN_SKIP_MARKER).read_text(encoding="ascii", errors="replace")
    except OSError:
        return []
    return [w for w in text.replace("\r", "").split() if w]


def commit_message(job: _jobs.Job, args: dict, ctx: dict, now: dt.datetime) -> str:
    fields = {
        "utc": now.strftime("%Y-%m-%d %H:%M"), "date": now.strftime("%Y-%m-%d"),
        "leg": ctx.get("leg", ""), "file_stem": str(ctx.get("file", "")).rsplit(".json", 1)[0],
        "roster": ctx.get("roster", ""), "market": ctx.get("market", args.get("market", "")),
    }
    return job.publish.message.format(**fields)


def close_roster(args: dict) -> str:
    """``journal: manual close <roster>`` -- the batch one-liner or ``SYM dir @ px``."""
    batch = args.get("batch") or ""
    if batch:
        try:
            syms = [str(e.get("symbol", "?")).upper() for e in json.loads(batch)]
        except (ValueError, AttributeError, TypeError):
            syms = ["?"]
        return f"x{len(syms)} - " + " ".join(syms[:10]) + (" ..." if len(syms) > 10 else "")
    return f"{args.get('symbol', '')} {args.get('direction', '')} @ {args.get('price', '')}"


# -- which paths, which checks -------------------------------------------------

def market_scope(job: _jobs.Job, args: dict, ctx: dict) -> list[str]:
    """MK: every market for ``all``, else the one scanned."""
    m = ctx.get("scanned_market") or args.get("market") or "all"
    return list(config.MARKETS) if m == "all" else [m]


def publish_paths(job: _jobs.Job, args: dict, ctx: dict) -> list[str]:
    pub = job.publish
    out = [p.format(file=ctx.get("file", "")) for p in pub.paths]
    for m in (market_scope(job, args, ctx) if pub.paths_per_market else []):
        out += [tpl.replace("{m}", m) for tpl in pub.paths_per_market]
    return out


def plan_checks(job: _jobs.Job, args: dict, ctx: dict, home: pathlib.Path,
                log) -> tuple[list[Check], str | None]:
    """(checks, skip_reason) -- the workflow's must-change branches as data.

    ``skip_reason`` set means: do not publish at all, report ok (the sentinel
    early-exits). Checks carry ``hard`` (abort, exit 1), ``soft`` (warn) or
    ``collect`` (remember, commit anyway, exit 1 at the end -- phasemap).
    """
    mc = job.publish.must_change
    policy = mc.get("policy", "none")
    scheduled = _jobs.is_scheduled(job, args)
    checks: list[Check] = []

    def _fmt(s: str, **kw) -> str:
        return s.format(**kw)

    if policy == "none":
        return checks, None

    if policy == "hard":
        market = ctx.get("market", args.get("market", ""))
        for label, paths in mc["hard"]:
            checks.append(Check(_fmt(label, market=market),
                                [p.format(file=ctx.get("file", "")) for p in paths], "hard"))
        return checks, None

    if policy == "event_branch":
        if scheduled:
            label, paths = mc["scheduled"]
            checks.append(Check(label, list(paths), "hard"))
        else:
            label, paths, warn = mc["manual"]
            checks.append(Check(label, list(paths), "soft", warn))
        return checks, None

    if policy == "scan":
        mk = market_scope(job, args, ctx)
        scope = ctx.get("scanned_market") or args.get("market") or "all"
        skipped = read_skip_marker(home)
        if skipped:
            log("::warning::source fully blocked for: " + " ".join(skipped) +
                " - previous JSON kept, must-change gate advisory for those markets only")
        if scheduled:
            for m in mk:
                if m in skipped:
                    log(_fmt(mc["skipped_warn"], m=m))
                elif m == "crypto" and scope == "all":
                    for (label, path), warn in zip(mc["per_market"], mc["crypto_soft_warn"]):
                        checks.append(Check(_fmt(label, m=m), [path.replace("{m}", m)], "soft", warn))
                else:
                    for label, path in mc["per_market"]:
                        checks.append(Check(_fmt(label, m=m), [path.replace("{m}", m)], "hard"))
            if all(m in skipped for m in mk):
                log(_fmt(mc["all_skipped_warn"], mk=" ".join(mk)))
            else:
                for label, path in mc["combined"]:
                    checks.append(Check(label, [path], "hard"))
        else:
            label, paths, warn = mc["manual"]
            checks.append(Check(label, list(paths), "soft", warn))
        return checks, None

    if policy == "collect":
        if scheduled:
            for label, paths in mc["scheduled"]:
                checks.append(Check(label, list(paths), "collect"))
            cond = mc.get("scheduled_if_flag")
            if cond:
                if ctx.get(cond["flag"]):
                    for label, paths in cond["checks"]:
                        checks.append(Check(label, list(paths), "collect"))
                else:
                    log(cond["else_warn"])
        else:
            label, paths, warn = mc["manual"]
            checks.append(Check(label, list(paths), "soft", warn))
        return checks, None

    if policy in ("sentinel_then_hard", "sentinels_all_then_anyof"):
        caps = ctx.get("captures", {})
        hits = [token in caps.get(key, "") for key, token in mc["sentinels"]]
        if all(hits):
            return checks, mc["sentinel_msg"]
        for label, paths in mc["hard"]:
            checks.append(Check(label, list(paths), "hard"))
        return checks, None

    if policy == "close":
        if args.get("journal_type") == "bot":
            label, paths = mc["bot"]
            checks.append(Check(label, list(paths), "hard"))
        return checks, None

    raise PublishError(f"{job.name}: unknown must-change policy {policy!r}")


def rebuild_wanted(job: _jobs.Job, args: dict) -> bool:
    flag = job.publish.rebuild_combined
    if flag == "bot_only":
        return args.get("journal_type") == "bot"
    return bool(flag)


# -- the second-writer check ---------------------------------------------------

def second_writers(clone: pathlib.Path, since: str, roots, identity: tuple[str, str],
                   run=subprocess.run) -> list[dict]:
    """Commits in ``since..origin/main`` touching a data root by someone else."""
    name, email = identity
    rev = _git(clone, "rev-list", f"{since}..origin/main", "--", *roots, check=False, run=run)
    if rev.returncode != 0:
        # an unknown publish_head (history rewritten / gc'd) is itself a reason to halt
        return [{"sha": since, "author": "?", "email": "?", "paths": [],
                 "note": "publish_head is not an ancestor of origin/main"}]
    out = []
    for sha in [s for s in rev.stdout.split() if s]:
        meta = _git(clone, "show", "-s", "--format=%an%x1f%ae", sha, run=run).stdout.strip()
        an, _, ae = meta.partition("\x1f")
        if an == name and ae == email:
            continue
        files = _git(clone, "diff-tree", "--no-commit-id", "--name-only", "-r", sha, "--", *roots,
                     run=run).stdout.split()
        out.append({"sha": sha, "author": an, "email": ae, "paths": files[:50]})
    return out


def write_halt(state: pathlib.Path, offenders: list[dict], job_name: str, now: dt.datetime) -> pathlib.Path:
    halt = state / "HALT"
    write_json(halt, {"detected_at": iso(now), "job": job_name, "shas": [o["sha"] for o in offenders],
                      "authors": sorted({f"{o['author']} <{o['email']}>" for o in offenders}),
                      "paths": sorted({p for o in offenders for p in o.get("paths", [])})[:200],
                      "commits": offenders[:20]}, indent=2, newline=True)
    return halt


# -- the loop ------------------------------------------------------------------

def publish(job: _jobs.Job, args: dict, ctx: dict, *, home: pathlib.Path | None = None,
            clone: pathlib.Path | None = None, state_dir: pathlib.Path | None = None,
            python: str | None = None, run=subprocess.run, exec_fn=None, sleep=time.sleep,
            now=None, notify=None, max_attempts: int | None = None) -> PublishResult:
    """Run the whole-file re-apply loop for ``job``. Never raises for a git
    failure -- the result carries it -- but a HALT is returned, not swallowed."""
    home = pathlib.Path(home) if home else _home()
    clone = pathlib.Path(clone) if clone else _publish_dir()
    state = pathlib.Path(state_dir) if state_dir else _state_dir()
    py = python or python_bin()
    notify = notify or (lambda sev, title, details="": _notify.alert(sev, title, details, state_dir=state))
    max_attempts = max_attempts or config.VPS_PUBLISH_MAX_ATTEMPTS
    lines: list[str] = []

    def log(msg: str) -> None:
        lines.append(msg)
        emit(msg)

    if not publish_enabled():
        log("publish: VIVEK_GIT_PUBLISH=0 - not committing (no-op)")
        return PublishResult("disabled", 0, None, "publish disabled", lines)
    if not (clone / ".git").exists():
        log(f"publish: clone {clone} is not a git checkout - refusing (run install.sh)")
        notify("CRITICAL", f"{job.name}: publish clone missing", f"{clone} has no .git")
        return PublishResult("failed", 1, None, "publish clone missing", lines)

    paths = publish_paths(job, args, ctx)
    checks, skip_reason = plan_checks(job, args, ctx, home, log)
    if skip_reason:
        log(skip_reason)
        return PublishResult("skipped", 0, None, skip_reason, lines)
    if job.name == "close_position.yml":
        ctx.setdefault("roster", close_roster(args))
    roots = _jobs.data_roots()
    identity = git_identity()
    head_file = state / "publish_head"
    env = _git_env()
    lock = Lock(lock_path(state, "publish"))
    lock.acquire(float(config.VPS_LOCK_WAIT_S["default"]))
    try:
        for attempt in range(1, max_attempts + 1):
            gate_failed = 0
            try:
                _git(clone, "fetch", "origin", "main", env=env, run=run)
                _git(clone, "reset", "-q", "--hard", "origin/main", run=run)
                _git(clone, "clean", "-fdq", run=run)
                origin_sha = _git(clone, "rev-parse", "origin/main", run=run).stdout.strip()

                # 2. second-writer check
                since = head_file.read_text(encoding="utf-8").strip() if head_file.exists() else ""
                if since and since != origin_sha:
                    offenders = second_writers(clone, since, roots, identity, run=run)
                    if offenders:
                        halt = write_halt(state, offenders, job.name, now or utcnow())
                        who = ", ".join(sorted({f"{o['author']} <{o['email']}>" for o in offenders}))
                        log(f"publish: SECOND WRITER on origin/main since {since[:9]}: {who} - "
                            f"HALT written to {halt}; nothing pushed")
                        notify("CRITICAL", f"{job.name}: second writer detected - HALTED",
                               f"commits by {who} touched data roots since publish_head {since[:9]}.\n"
                               f"Book writers refuse to run until `python -m scanner.vps accept-upstream` "
                               f"(sync FROM origin) or `clear-halt` (fixed by hand).")
                        return PublishResult("halted", 4, None, "second writer", lines)
                elif not since:
                    log("publish: no state/publish_head yet - second-writer check skipped this once")

                # 3. re-apply this run's copies, one pathspec per add
                rebuild = rebuild_wanted(job, args)
                for rel in paths:
                    if rel in _COMBINED and job.publish.rebuild_combined == "bot_only" and not rebuild:
                        # a legacy (swing/scalp) close never touches the bot book: origin's
                        # derived view -- rebuilt by the last bot-book publish -- stays
                        log(f"publish: {rel} left as origin has it (legacy close, no rebuild)")
                        continue
                    present = copy_in(home, clone, rel)
                    if not present and rel in job.publish.required_paths:
                        raise PublishError(f"required path {rel} is missing in the working checkout")
                    res = _git(clone, "add", "--", rel, check=False, run=run)
                    if res.returncode != 0:
                        log(f"publish: {rel} is not present - nothing to stage for it")

                # 4. derived combined book, rebuilt INSIDE the clone
                if rebuild:
                    clean_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
                    runner = exec_fn or (lambda argv, **kw: _plain_exec(argv, run=run, **kw))
                    rc, out = runner([py, "-m", "scanner.broker.vivek_run", "--rebuild-combined"],
                                     cwd=str(clone), env=clean_env)
                    for ln in (out or "").splitlines():
                        log(ln)
                    if rc != 0:
                        raise PublishError(f"--rebuild-combined exited {rc} in the publish clone")
                    for rel in _COMBINED:
                        _git(clone, "add", "--", rel, check=False, run=run)
                    rc, out = runner([py, "-m", "scanner.broker.vivek_run", "--verify"],
                                     cwd=str(clone), env=clean_env)
                    for ln in (out or "").splitlines():
                        log(ln)
                    if rc != 0:
                        raise PublishError(f"--verify exited {rc} in the publish clone (STALE/corrupt book)")

                # 5. must-change
                for chk in checks:
                    if any(staged_diff(clone, p, run=run) for p in chk.paths):
                        hit = next(p for p in chk.paths if staged_diff(clone, p, run=run))
                        log(f"assert_staged({chk.label}): OK - '{hit}' has staged changes")
                        continue
                    msg = _ASSERT_FAIL.format(label=chk.label, paths=" ".join(chk.paths))
                    if chk.mode == "hard":
                        log(msg)
                        status = _git(clone, "status", "--short", check=False, run=run).stdout
                        for ln in status.splitlines()[:20]:
                            log(ln)
                        raise PublishError(f"ASSERT-STAGED FAILED ({chk.label})")
                    if chk.mode == "collect":
                        log(msg)
                        gate_failed = 1
                    else:
                        log(msg)
                        log(chk.warn or f"::warning::{chk.label} not staged")

                if _git(clone, "diff", "--cached", "--quiet", check=False, run=run).returncode == 0:
                    log(job.publish.nothing_msg)
                    if gate_failed:
                        log(job.publish.must_change.get("tripped_error", "must-change gate tripped"))
                    return PublishResult("nothing", gate_failed, None, job.publish.nothing_msg, lines)

                # 6/7. commit + push
                msg = commit_message(job, args, ctx, now or utcnow())
                name, email = identity
                _git(clone, "-c", f"user.name={name}", "-c", f"user.email={email}",
                     "commit", "-q", "-m", msg, env=env, run=run)
                sha = _git(clone, "rev-parse", "HEAD", run=run).stdout.strip()
                pushed = _git(clone, "push", "origin", "HEAD:main", check=False, env=env, run=run)
                if pushed.returncode == 0:
                    head_file.parent.mkdir(parents=True, exist_ok=True)
                    tmp = head_file.with_suffix(".tmp")
                    with open(tmp, "w", encoding="utf-8") as fh:
                        fh.write(sha + "\n")
                    os.replace(tmp, head_file)
                    log(f"Pushed. {sha[:9]} {msg}")
                    if gate_failed:
                        log(job.publish.must_change.get("tripped_error", "must-change gate tripped"))
                    return PublishResult("pushed", gate_failed, sha, msg, lines)
                err = _ledger.redact((pushed.stderr or pushed.stdout or "").strip())
                if any(tok in err for tok in _REJECTED):
                    _git(clone, "reset", "-q", "--hard", "origin/main", check=False, run=run)
                    if attempt < max_attempts:
                        log(f"Push race - retry {attempt} ({err.splitlines()[-1][:120] if err else 'rejected'})")
                        sleep(2 ** attempt)
                        continue
                    break                       # exhausted: the loud message below
                raise PublishError(f"git push failed: {err[-400:]}")
            except PublishError as e:
                _git(clone, "reset", "-q", "--hard", "origin/main", check=False, run=run)
                _git(clone, "clean", "-fdq", check=False, run=run)
                log(f"publish FAILED: {e}")
                notify("WARNING", f"{job.name}: publish failed", str(e))
                return PublishResult("failed", 1, None, str(e), lines)
        log("Could not push after retries")
        notify("WARNING", f"{job.name}: publish failed", "Could not push after retries")
        return PublishResult("failed", 1, None, "Could not push after retries", lines)
    finally:
        lock.release()


def _plain_exec(argv, *, cwd, env, run=subprocess.run):
    res = run(list(argv), cwd=cwd, env=env, capture_output=True, text=True)
    return res.returncode, (res.stdout or "") + (res.stderr or "")


# -- operator verbs ------------------------------------------------------------

def origin_head(clone: pathlib.Path, run=subprocess.run) -> str:
    env = _git_env()
    _git(clone, "fetch", "origin", "main", env=env, run=run)
    return _git(clone, "rev-parse", "origin/main", run=run).stdout.strip()


def clear_halt(*, state_dir=None, clone=None, run=subprocess.run) -> str:
    """Remove state/HALT and move publish_head to origin/main so the same
    commits are not re-detected on the next publish."""
    state = pathlib.Path(state_dir) if state_dir else _state_dir()
    clone = pathlib.Path(clone) if clone else _publish_dir()
    sha = origin_head(clone, run=run)
    head_file = state / "publish_head"
    tmp = head_file.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(sha + "\n")
    os.replace(tmp, head_file)
    try:
        (state / "HALT").unlink()
    except FileNotFoundError:
        pass
    return sha


def accept_upstream(*, state_dir=None, clone=None, home=None, run=subprocess.run) -> list[str]:
    """Sync every data root FROM origin/main into the working checkout, then clear HALT."""
    state = pathlib.Path(state_dir) if state_dir else _state_dir()
    clone = pathlib.Path(clone) if clone else _publish_dir()
    home = pathlib.Path(home) if home else _home()
    env = _git_env()
    _git(clone, "fetch", "origin", "main", env=env, run=run)
    _git(clone, "reset", "-q", "--hard", "origin/main", run=run)
    _git(clone, "clean", "-fdq", run=run)
    synced = []
    for rel in _jobs.data_roots():
        if copy_in(clone, home, rel):
            synced.append(rel)
    clear_halt(state_dir=state, clone=clone, run=run)
    return synced
