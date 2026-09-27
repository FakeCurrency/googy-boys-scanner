"""``python -m scanner.vps`` -- the CLI verbs and the runner order (DESIGN 3.1).

    run <job> [key=value ...]   preflight -> gate -> locks -> steps -> publish -> ledger
    gate <job> [key=value ...]  exit 0 due / 3 not due (prints why); no side effects
    drain-spool                 execute queued dispatches (oldest first)
    notify-failure <unit>       OnFailure= hook: alert + state/alerts.log + ledger
    ledger [--json]             print runs.json
    list [--json]               print the JOBS table
    accept-upstream             clear HALT: sync data roots FROM origin/main into the checkout
    clear-halt                  clear HALT without syncing (operator fixed it by hand)
    data-roots                  print the data roots (deploy/bin/update.sh reads them)

``run`` exit codes: 0 ok, 3 skipped-by-gate, 4 halted, 1 failure. The ledger
row is written on EVERY path out of ``run``, including a crash in the runner.

Runner order inside ``run``: (1) refuse if state/HALT exists and the job is a
book writer; (2) evaluate the gate AT FIRE TIME; (3) locks -- ``repo`` shared,
family, own -- with the lock wait budgeted separately from the step timeout;
(4) re-check the gate for slots that define it (a post-close scan may have
landed while waiting); (5) delete ``.scan-skipped`` for scan-family jobs;
(6) steps, fail-fast unless continue_on_error, output streamed to the journal
unchanged; (7) publish where the workflow committed; (8) the ledger row.

Steps run with cwd = the working checkout, ``GITHUB_STEP_SUMMARY`` pointing at
``state/summaries/<job>-<utc>.md``, a per-step ``GITHUB_OUTPUT`` temp file,
``GITHUB_SHA`` = the checkout's HEAD and ``GITHUB_EVENT_NAME`` = schedule /
workflow_dispatch from the job's reason. Secrets reach a step only through
its transcribed ``env_pass`` allow-list (kill_switch alone sees broker keys).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

from scanner import config

from . import (emit, ensure_state_dirs, home as _home, host_label, iso, ledger_path as _ledger_path,
               publish_dir as _publish_dir, python_bin, state_dir as _state_dir, utcnow)
from . import gate as G
from . import jobs as J
from . import ledger as LG
from . import locks as L
from . import notify as N
from . import publish as P
from . import spool as S

SECRET_PREFIXES = ("BYBIT_", "ALPACA_", "TELEGRAM_", "GBS_", "DISCORD_", "GH_", "DISPATCH_",
                   "CRONJOB_", "CLOUDFLARE_", "MORNING_PLAYS_TRIGGER")
EXIT_OK, EXIT_FAIL, EXIT_SKIPPED, EXIT_HALTED = 0, 1, 3, 4


class StepFailed(RuntimeError):
    def __init__(self, name: str, rc: int, last_line: str = ""):
        super().__init__(f"step '{name}' failed (exit {rc})")
        self.step = name
        self.rc = rc
        self.last_line = last_line


@dataclass
class Exec:
    rc: int
    out: str = ""
    err: str = ""


def _coerce(res) -> Exec:
    if isinstance(res, Exec):
        return res
    if isinstance(res, tuple):
        return Exec(*res) if len(res) == 3 else Exec(res[0], res[1] if len(res) > 1 else "")
    return Exec(int(res))


def default_exec(argv, *, cwd, env, stdin=None, timeout=None, stream=True) -> Exec:
    """Run one step. ``stream=True`` merges stderr into stdout and echoes every
    line to our stdout as it arrives (journald sees the step live)."""
    if not stream:
        try:
            res = subprocess.run(list(argv), cwd=cwd, env=env, input=stdin, capture_output=True,
                                 text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            return Exec(124, (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
                        "timed out")
        return Exec(res.returncode, res.stdout or "", res.stderr or "")
    proc = subprocess.Popen(list(argv), cwd=cwd, env=env, text=True,
                            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
    timer = None
    if timeout:
        timer = threading.Timer(timeout, proc.kill)
        timer.daemon = True
        timer.start()
    lines: list[str] = []
    try:
        if stdin is not None:
            try:
                proc.stdin.write(stdin)
            finally:
                proc.stdin.close()
        for line in proc.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            emit(line)
        rc = proc.wait()
    finally:
        if timer:
            timer.cancel()
    if timer is not None and rc in (-9, 137) and timeout:
        lines.append(f"(step killed after {timeout:.0f}s timeout)")
        rc = 124
    return Exec(rc, "\n".join(lines), "")


@dataclass
class Runtime:
    """Everything the runner touches that a test wants to fake."""
    home: pathlib.Path
    publish: pathlib.Path
    state: pathlib.Path
    python: str
    ledger_file: pathlib.Path
    exec_fn: Callable = default_exec
    run: Callable = subprocess.run            # git / gate subprocesses
    now: Callable = utcnow
    sleep: Callable = time.sleep
    clock: Callable = time.monotonic
    notify: Callable | None = None            # (severity, title, details) -> sent
    host: str = field(default_factory=host_label)

    @classmethod
    def from_env(cls) -> "Runtime":
        return cls(home=_home(), publish=_publish_dir(), state=_state_dir(), python=python_bin(),
                   ledger_file=_ledger_path())

    def alert(self, severity: str, title: str, details: str = "") -> list[str]:
        if self.notify:
            return list(self.notify(severity, title, details) or [])
        return N.alert(severity, title, details, state_dir=self.state)


# -- env / argv plumbing -------------------------------------------------------

def step_env(rt: Runtime, job: J.Job, step: J.Step, args: dict, ctx: dict, output_file: pathlib.Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(SECRET_PREFIXES)}
    for name in step.env_pass:
        if name in os.environ:
            env[name] = os.environ[name]
    env.update({k: str(v) for k, v in step.env_set.items()})
    for env_name, key in step.env_ctx.items():
        val = ctx.get(key, args.get(key))
        if val is not None:
            env[env_name] = str(val)
    env.update({
        "GITHUB_STEP_SUMMARY": str(ctx["summary"]), "GITHUB_OUTPUT": str(output_file),
        "GITHUB_EVENT_NAME": ctx["event_name"], "RUNNER_TEMP": str(rt.state / "tmp"),
        "VIVEK_HOME": str(rt.home), "VIVEK_STATE_DIR": str(rt.state), "PYTHONUNBUFFERED": "1",
    })
    if ctx.get("sha"):
        env["GITHUB_SHA"] = ctx["sha"]
    return env


def expand_argv(argv, rt: Runtime, args: dict, ctx: dict, **more) -> list[str]:
    fields = {**args, **{k: v for k, v in ctx.items() if isinstance(v, str)}, **more}
    out: list[str] = []
    for tok in argv:
        if tok in ("python", "python3") and not out:
            out.append(rt.python)
        elif tok in ("{extra}", "{args}"):
            out += J.split_extra(args.get(tok[1:-1]))
        elif tok == "{dry_run_flag}":
            if args.get("dry_run") == "true":
                out.append("--dry-run")
        else:
            out.append(tok.format_map(fields))
    return out


def _read_outputs(path: pathlib.Path, ctx: dict) -> None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                ctx["outputs"][k.strip()] = v.strip()
    except OSError:
        pass


def _append_summary(ctx: dict, title: str, body: str) -> None:
    try:
        with open(ctx["summary"], "a", encoding="utf-8") as fh:
            fh.write(f"### {title}\n```\n{body}\n```\n")
    except OSError:
        pass


# -- steps ---------------------------------------------------------------------

class _Runner:
    def __init__(self, rt: Runtime, job: J.Job, args: dict, ctx: dict, deadline: float):
        self.rt, self.job, self.args, self.ctx, self.deadline = rt, job, args, ctx, deadline
        self.last_output = ""

    def _remaining(self) -> float:
        left = self.deadline - self.rt.clock()
        if left <= 0:
            raise StepFailed("job timeout", 124, f"{self.job.name}: timeout_s={self.job.timeout_s} exhausted")
        return left

    def exec(self, step: J.Step, argv: list[str], *, env_extra: dict | None = None, stdin=None,
             stream: bool = True) -> Exec:
        out_file = pathlib.Path(tempfile.mkstemp(prefix="gh-output-", dir=self.rt.state / "tmp")[1])
        env = step_env(self.rt, self.job, step, self.args, self.ctx, out_file)
        env.update(env_extra or {})
        emit(f"--- {step.name}: {' '.join(argv)}")
        try:
            res = _coerce(self.rt.exec_fn(argv, cwd=str(self.rt.home), env=env, stdin=stdin,
                                          timeout=self._remaining(), stream=stream))
        finally:
            _read_outputs(out_file, self.ctx)
            try:
                out_file.unlink()
            except OSError:
                pass
        self.last_output = (res.out or "") + ("\n" + res.err if res.err else "")
        if self.rt.clock() > self.deadline:      # the step outran the job's timeout budget
            raise StepFailed("job timeout", 124,
                             f"{self.job.name}: timeout_s={self.job.timeout_s} exhausted during '{step.name}'")
        return res

    # -- kinds -----------------------------------------------------------------

    def cmd(self, step: J.Step) -> None:
        argv = expand_argv(step.argv, self.rt, self.args, self.ctx)
        res = self.exec(step, argv, stdin=step.stdin)
        ok = res.rc in step.ok_exit_codes
        if step.capture:
            self.ctx["captures"][step.capture] = self.last_output
        if step.sets_flag:
            self.ctx[step.sets_flag] = (res.rc == 0)
        if step.to_summary:
            _append_summary(self.ctx, step.name, self.last_output)
        if not ok:
            if step.continue_on_error:
                emit(step.warn_on_fail or f"::warning::{step.name} exited {res.rc} (tolerated)")
                return
            raise StepFailed(step.name, res.rc, LG.last_line_of(self.last_output))

    def markets(self, step: J.Step) -> None:
        market = self.ctx.get("market") or self.args.get(step.market_arg) or "all"
        if step.sets_scanned:
            self.ctx["scanned_market"] = market
        if market != "all":
            emit(f"Single-market run: {market}")
            res = self.exec(step, expand_argv(step.argv, self.rt, self.args, self.ctx, market=market))
            if res.rc != 0:
                raise StepFailed(step.name, res.rc, LG.last_line_of(self.last_output))
            return
        rcs = self._run_tagged(step, [(m, expand_argv(step.argv, self.rt, self.args, self.ctx, market=m))
                                      for m in step.order_all], step.parallel)
        emit("rc: " + " ".join(f"{m}={rcs[m]}" for m in step.order_all))
        bad = [m for m in step.require_ok if rcs.get(m, 1) != 0]
        if bad:
            raise StepFailed(step.name, 1, f"{step.name}: required market(s) failed: {bad}")

    def group(self, step: J.Step) -> None:
        cmds = [(c["tag"], expand_argv(c["argv"], self.rt, self.args, self.ctx)) for c in step.cmds]
        rcs = self._run_tagged(step, cmds, step.parallel)
        emit("rc: " + " ".join(f"{t}={rcs[t]}" for t, _ in cmds))
        if step.ignore_rc:
            return
        bad = [t for t in step.require_ok if rcs.get(t, 1) != 0]
        if bad:
            if step.continue_on_error:
                emit(step.warn_on_fail or f"::warning::{step.name}: {bad} failed (tolerated)")
                return
            raise StepFailed(step.name, 1, f"{step.name}: required leg(s) failed: {bad}")

    def _run_tagged(self, step: J.Step, cmds, parallel) -> dict:
        rcs: dict[str, int] = {}
        par = [(t, a) for t, a in cmds if t in parallel]
        seq = [(t, a) for t, a in cmds if t not in parallel]
        if par:
            threads = []
            outputs: dict[str, str] = {}

            def _one(tag, argv):
                res = self.exec(step, argv)
                rcs[tag] = res.rc
                outputs[tag] = self.last_output
            for tag, argv in par:
                th = threading.Thread(target=_one, args=(tag, argv), daemon=True)
                th.start()
                threads.append(th)
            for th in threads:
                th.join()
            emit("small markets done - " + " ".join(f"{t}={rcs.get(t)}" for t, _ in par) + "; now the rest")
        for tag, argv in seq:
            rcs[tag] = self.exec(step, argv).rc
        return rcs

    def close(self, step: J.Step) -> None:
        a = self.args
        py = self.rt.python
        env_extra = {}
        if a.get("batch") and a.get("journal_type") == "bot":
            argv = [py, "-m", "scanner.broker.vivek_run", "--close-batch"]
            env_extra["VIVEK_CLOSE_BATCH"] = a["batch"]
        elif a.get("journal_type") == "bot":
            argv = [py, "-m", "scanner.broker.vivek_run", "--close", a["symbol"], "--market", a["market"],
                    "--price", a["price"]]
            if a.get("direction"):
                argv += ["--direction", a["direction"]]
            if a.get("exit_date"):
                argv += ["--day", a["exit_date"]]
        else:
            argv = [py, "-m", "scanner.journal", "--close-manual", "--symbol", a["symbol"],
                    "--direction", a["direction"], "--market", a["market"], "--price", a["price"],
                    "--date", a.get("exit_date", ""), "--journal-type", a["journal_type"]]
        res = self.exec(step, argv, env_extra=env_extra)
        if res.rc != 0:
            raise StepFailed(step.name, res.rc, LG.last_line_of(self.last_output))

    def momentum_screen(self, step: J.Step) -> None:
        a = self.args
        market = self.ctx.get("market") or a.get("market")
        if not market:
            raise StepFailed(step.name, 1, "momentum: no market picked")
        argv = expand_argv(step.argv, self.rt, self.args, self.ctx, market=market)
        if a.get("mode"):
            argv += ["--mode", a["mode"]]
        if a.get("window"):
            argv += ["--window", a["window"]]
        if a.get("dry_run") == "true":
            argv.append("--dry-run")
            self.ctx["dry_run"] = True
        backtest = a.get("backtest") == "true"
        if backtest:
            argv.append("--backtest")
        self.ctx["market"] = market
        self.ctx["file"] = f"{market}_backtest.json" if backtest else f"{market}.json"
        res = self.exec(step, argv)
        emit(f"rc={res.rc}")
        if res.rc == 0:
            self.ctx["published"] = True
        elif res.rc == 3:
            self.ctx["published"] = False
            emit(step.extra.get("nodata_warn", "::warning::momentum {market} published nothing").format(market=market))
        else:
            emit(step.extra.get("fail_error", "::error::momentum {market} failed with exit {rc}")
                 .format(market=market, rc=res.rc))
            raise StepFailed(step.name, res.rc, LG.last_line_of(self.last_output))

    def brief(self, step: J.Step) -> None:
        argv = expand_argv(step.argv, self.rt, self.args, self.ctx)
        res = self.exec(step, argv, stream=False)
        stamp = self.ctx["summary"].name.rsplit(".", 1)[0]
        (self.rt.state / "summaries").mkdir(parents=True, exist_ok=True)
        brief_txt = self.rt.state / "summaries" / f"{stamp}-brief.txt"
        with open(brief_txt, "w", encoding="utf-8") as fh:
            fh.write(res.out or "")
        for line in (res.out or "").splitlines():
            emit(line)
        if res.err:
            for line in res.err.splitlines():
                emit("stderr: " + line)
        if res.rc not in step.ok_exit_codes:
            emit(step.extra.get("crash_error", "::error::crashed (rc={rc})").format(rc=res.rc))
            raise StepFailed(step.name, res.rc, LG.last_line_of(res.err or res.out))
        _append_summary(self.ctx, step.name, res.out or "")

    def morning_plays(self, step: J.Step) -> None:
        a = self.args
        argv = expand_argv(step.argv, self.rt, self.args, self.ctx)
        if a.get("slot"):
            argv += ["--slot", a["slot"]]
            if a.get("redeliver") == "true":
                argv.append("--redeliver")
        elif a.get("force", "true") != "false":
            argv.append("--force")
        else:
            emit(step.extra.get("noop_msg", "nothing to do"))
            return
        if a.get("dry_run") == "true":
            argv.append("--dry-run")
        res = self.exec(step, argv)
        if res.rc != 0:
            raise StepFailed(step.name, res.rc, LG.last_line_of(self.last_output))

    def offbox_copy(self, step: J.Step) -> None:
        target = os.environ.get("VIVEK_BACKUP_TARGET", "").strip()
        if not target:
            emit("off-box backup copy: VIVEK_BACKUP_TARGET unset - skipped (the in-tree commit is the copy)")
            return
        argv = ["rsync", "-a", "--delete", str(self.rt.home / "backups") + "/", target]
        res = self.exec(step, argv)
        if res.rc != 0:
            raise StepFailed(step.name, res.rc, f"off-box copy to {target} failed (rc {res.rc})")

    def spool_momentum(self, step: J.Step) -> None:
        path = S.write_spool("momentum.yml", {}, f"chain/{self.job.name}", state_dir=self.rt.state,
                             now=self.rt.now())
        emit(f"chained momentum dispatch -> {path.name}")

    def publish(self, step: J.Step) -> P.PublishResult:
        if step.leg:
            self.ctx["leg"] = step.leg
        res = P.publish(self.job, self.args, self.ctx, home=self.rt.home, clone=self.rt.publish,
                        state_dir=self.rt.state, python=self.rt.python, run=self.rt.run,
                        exec_fn=lambda argv, **kw: _pub_exec(self.rt, argv, **kw),
                        sleep=self.rt.sleep, now=self.rt.now(), notify=self.rt.alert)
        self.ctx.setdefault("publishes", []).append(res)
        if res.sha:
            self.ctx["pushed"] = res.sha
        if res.status == "halted":
            raise P.Halted(res.message)
        if res.status == "failed":
            raise StepFailed(step.name, 1, res.message)
        if res.exit_code:
            self.ctx["gate_failed"] = 1
        return res

    def run(self, step: J.Step) -> None:
        handler = getattr(self, step.kind, None)
        if handler is None:
            raise StepFailed(step.name, 1, f"unknown step kind {step.kind!r}")
        handler(step)


def _pub_exec(rt: Runtime, argv, *, cwd, env):
    res = _coerce(rt.exec_fn(argv, cwd=cwd, env=env, stdin=None, timeout=1800, stream=True))
    return res.rc, (res.out or "") + (("\n" + res.err) if res.err else "")


# -- the job -------------------------------------------------------------------

def _ledger_args(args: dict) -> dict:
    out = dict(args)
    if out.get("batch"):
        try:
            out["batch"] = f"<{len(json.loads(out['batch']))} entries>"
        except (ValueError, TypeError):
            out["batch"] = "<unparseable>"
    return out


def run_job(name: str, kv, rt: Runtime | None = None, *, operator: bool = True,
            source: str = "cli") -> int:
    rt = rt or Runtime.from_env()
    job = J.get(name)
    args = J.parse_args(job, kv if isinstance(kv, dict) else J.parse_kv(kv), operator=operator)
    started = rt.now()
    ensure_state_dirs(rt.state)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    summary = rt.state / "summaries" / f"{job.name[:-4]}-{stamp}.md"
    summary.touch()
    ctx: dict = {"captures": {}, "outputs": {}, "summary": summary,
                 "event_name": "schedule" if J.is_scheduled(job, args) else "workflow_dispatch",
                 "scan_trigger": args.get("reason", "manual") if job.scan_family else None}
    try:
        sha = rt.run(["git", "rev-parse", "HEAD"], cwd=str(rt.home), capture_output=True, text=True)
        if getattr(sha, "returncode", 1) == 0:
            ctx["sha"] = (sha.stdout or "").strip()
    except Exception:                                            # noqa: BLE001 - the build stamp is optional
        pass
    status, exit_code, last_line, waited = "failed", EXIT_FAIL, "", 0.0
    lockset: L.LockSet | None = None
    emit(f"=== {job.name} {source} args={_ledger_args(args)} at {iso(started)} host={rt.host}")
    try:
        # (1) HALT refusal for book writers
        if job.book_writer and (rt.state / "HALT").exists():
            last_line = "HALT present - a non-VPS data commit landed upstream; refusing to write the book"
            emit(f"::error::{job.name}: {last_line} (accept-upstream / clear-halt)")
            status, exit_code = "halted", EXIT_HALTED
            return exit_code
        # (2) gate at fire time
        gres = G.evaluate(job, args, now=rt.now(), home=rt.home, state_dir=rt.state,
                          ledger_file=rt.ledger_file, run=rt.run, python=rt.python)
        emit(G.describe(gres, rt.now()))
        if gres.warning:
            emit(gres.warning)
        if gres.market:
            ctx["market"] = gres.market
        gate_skipped = not gres.due
        if gate_skipped and job.gate_mode == "job":
            status, exit_code, last_line = "skipped", EXIT_SKIPPED, gres.why
            return exit_code
        # (3) locks: repo shared -> family -> own
        lockset = L.LockSet(rt.state, job.locks)
        waited = lockset.acquire(job.lock_wait_s, sleep=rt.sleep, clock=rt.clock)
        emit(f"locks {lockset.names} acquired after {waited:.0f}s")
        # (4) re-check for slots that define it
        if args.get("slot") in job.recheck:
            again = G.evaluate(job, args, now=rt.now(), home=rt.home, state_dir=rt.state,
                               ledger_file=rt.ledger_file, run=rt.run, python=rt.python)
            if not again.due:
                emit("re-check after the lock: " + again.why)
                status, exit_code, last_line = "skipped", EXIT_SKIPPED, again.why
                return exit_code
        # (5) per-run marker
        if job.scan_family:
            try:
                (rt.home / config.SCAN_SKIP_MARKER).unlink()
                emit(f"removed stale {config.SCAN_SKIP_MARKER} (per-run marker)")
            except FileNotFoundError:
                pass
        # (6)+(7) steps and publish
        runner = _Runner(rt, job, args, ctx, rt.clock() + job.timeout_s)
        pending_error: BaseException | None = None
        for step in job.steps:
            if pending_error is not None and not step.always:
                continue
            if gate_skipped and (step.gated or step.kind == "publish"):
                emit(f"--- {step.name}: skipped (gate)")
                continue
            if step.kind == "publish" and step.when == "momentum_published" and \
                    (not ctx.get("published") or ctx.get("dry_run")):
                emit(f"--- {step.name}: skipped (nothing published this run)")
                continue
            try:
                runner.run(step)
            except (StepFailed, P.Halted, L.LockTimeout, G.GateError) as e:
                pending_error = e
        if pending_error is not None:
            raise pending_error
        if ctx.get("gate_failed"):
            status, exit_code = "failed", EXIT_FAIL
            last_line = "a must-change gate tripped - data pushed for the healthy markets, run is red"
        else:
            status, exit_code = ("skipped", EXIT_SKIPPED) if gate_skipped else ("ok", EXIT_OK)
            last_line = gres.why if gate_skipped else (
                ctx["publishes"][-1].message if ctx.get("publishes") else "ok")
        return exit_code
    except P.Halted as e:
        status, exit_code, last_line = "halted", EXIT_HALTED, str(e)
        return exit_code
    except StepFailed as e:
        status, exit_code, last_line = "failed", EXIT_FAIL, e.last_line or str(e)
        emit(f"::error::{job.name}: {e}" + (f" - {e.last_line}" if e.last_line else ""))
        return exit_code
    except L.LockTimeout as e:
        status, exit_code, last_line = "failed", EXIT_FAIL, str(e)
        emit(f"::error::{job.name}: {e}")
        return exit_code
    except G.GateError as e:
        status, exit_code, last_line = "failed", EXIT_FAIL, f"gate crashed: {e}"
        emit(f"::error::{job.name}: {last_line}")
        return exit_code
    except J.ArgError:
        raise
    except Exception as e:                                       # noqa: BLE001 - the ledger row must still land
        status, exit_code = "failed", EXIT_FAIL
        last_line = f"runner crashed: {type(e).__name__}: {e}"
        emit("::error::" + last_line)
        traceback.print_exc()
        return exit_code
    finally:
        if lockset is not None:
            lockset.release()
        ended = rt.now()
        try:
            LG.record(job.name, status=status, exit_code=exit_code, args=_ledger_args(args),
                      started=started, ended=ended, waited_s=waited, pushed=ctx.get("pushed"),
                      last_line=last_line, host=rt.host, path=rt.ledger_file)
        except Exception as e:                                   # noqa: BLE001
            emit(f"::error::ledger write failed: {type(e).__name__}: {e}")
        if status in ("failed", "halted") and source != "cli":
            rt.alert("CRITICAL" if job.book_writer else "WARNING",
                     f"{job.name} {status} ({source})", last_line)
        emit(f"=== {job.name} {status} exit={exit_code} in "
             f"{(ended - started).total_seconds():.0f}s (waited {waited:.0f}s for locks)")


# -- verbs ---------------------------------------------------------------------

def cmd_gate(name: str, kv, rt: Runtime) -> int:
    job = J.get(name)
    args = J.parse_args(job, J.parse_kv(kv))
    res = G.evaluate(job, args, now=rt.now(), home=rt.home, state_dir=rt.state,
                     ledger_file=rt.ledger_file, run=rt.run, python=rt.python)
    emit(G.describe(res, rt.now()))
    if res.warning:
        emit(res.warning)
    return EXIT_OK if res.due else EXIT_SKIPPED


def cmd_list(as_json: bool = False) -> int:
    rows = J.table_rows()
    if as_json:
        emit(json.dumps(rows, indent=1))
        return 0
    cols = ["job", "family", "gate", "slots", "timeout_s", "lock_wait_s", "book_writer",
            "publish_paths", "must_change", "steps", "dropped", "operator_only"]
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    emit("  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        emit("  ".join(str(r[c]).ljust(widths[c]) for c in cols))
    emit(f"{len(rows)} jobs; data roots: {len(J.data_roots())}")
    return 0


def cmd_ledger(rt: Runtime, as_json: bool = False) -> int:
    doc = LG.load(rt.ledger_file)
    if as_json:
        emit(json.dumps(doc, indent=1, sort_keys=True))
        return 0
    if not doc:
        emit(f"(no ledger yet at {rt.ledger_file})")
        return 0
    for key in sorted(doc):
        row = doc[key]
        emit(f"{key:22} {row.get('last_status', '-'):8} exit={row.get('last_exit', '-')!s:3} "
             f"end={row.get('last_end', '-')} ok={row.get('last_success_at', '-')} "
             f"fail={row.get('last_failure_at', '-')} x{row.get('consecutive_failures', 0)} "
             f"| {row.get('last_line', '')[:80]}")
    return 0


def cmd_drain(rt: Runtime) -> int:
    report = S.drain(lambda name, args, source: run_job(name, args, rt, operator=False, source=source),
                     state_dir=rt.state)
    emit(f"drain-spool: ran {len(report.ran)}, done {len(report.done)}, failed {len(report.failed)}, "
         f"stuck {len(report.stuck)}, left {len(report.skipped)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scanner.vps", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="verb", required=True)
    for verb in ("run", "gate"):
        p = sub.add_parser(verb)
        p.add_argument("job")
        p.add_argument("kv", nargs="*", help="key=value job arguments")
    sub.add_parser("drain-spool")
    p = sub.add_parser("notify-failure")
    p.add_argument("unit")
    p = sub.add_parser("ledger")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("list")
    p.add_argument("--json", action="store_true")
    sub.add_parser("accept-upstream")
    sub.add_parser("clear-halt")
    sub.add_parser("data-roots", help="print the union of every job's publish paths, one per line "
                                      "(update.sh's second-writer scope)")
    ns = ap.parse_args(argv)
    if ns.verb == "list":
        return cmd_list(ns.json)
    if ns.verb == "data-roots":
        for root in J.data_roots():
            emit(root)
        return 0
    rt = Runtime.from_env()
    try:
        if ns.verb == "run":
            return run_job(ns.job, ns.kv, rt)
        if ns.verb == "gate":
            return cmd_gate(ns.job, ns.kv, rt)
        if ns.verb == "drain-spool":
            return cmd_drain(rt)
        if ns.verb == "notify-failure":
            return N.notify_failure(ns.unit, state_dir=rt.state, ledger_file=rt.ledger_file)
        if ns.verb == "ledger":
            return cmd_ledger(rt, ns.json)
        if ns.verb == "accept-upstream":
            synced = P.accept_upstream(state_dir=rt.state, clone=rt.publish, home=rt.home, run=rt.run)
            emit(f"accept-upstream: synced {len(synced)} data root(s) from origin/main; HALT cleared")
            return 0
        if ns.verb == "clear-halt":
            sha = P.clear_halt(state_dir=rt.state, clone=rt.publish, run=rt.run)
            emit(f"clear-halt: HALT removed; publish_head = {sha[:9]}")
            return 0
    except (J.ArgError, KeyError) as e:
        emit(f"error: {e}")
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
