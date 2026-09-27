"""flock-based locks for the VPS runner (DESIGN section 3.2, "Lock families").

Every lock is a file under ``<state>/locks/<name>.lock`` held with
``fcntl.flock`` for the life of the process (the OS releases it on crash, so a
killed job can never wedge the box). Acquisition is ORDERED, always:

    family lock (scan | heavy, exclusive)  ->  own name (exclusive)  ->  repo (shared)

so two jobs can never deadlock on each other. ``repo`` is taken LAST on
purpose (2026-09-27 book review): a job QUEUED behind a 40-80 minute ASX scan
used to hold ``repo`` shared for its whole wait, which pinned the lock from
11:07 to ~17:00 and made update.sh raise a false "a job may be hung" alarm
five times a session. Now only RUNNING jobs hold ``repo``. The holders of
``repo`` EXCLUSIVE (update.sh non-blocking; accept-upstream / clear-halt
blocking) hold no family/own lock (gc.sh holds it only SHARED, plus a bounded
``publish`` for the publish clone), and ``publish`` is only ever
taken by a job that already holds ``repo`` shared or by an operator verb that
holds ``repo`` exclusive, so the order stays deadlock-free. The WAIT for a lock is a
separate budget from the step timeout (``Job.lock_wait_s`` vs ``Job.timeout_s``):
a close arriving mid-scan queues behind a 40-80 minute ASX run instead of
failing, and the ledger row records how long it waited (``waited_s``).

``update.sh`` takes ``repo`` EXCLUSIVE and non-blocking; ``gc.sh`` takes it
SHARED (so a repack never stalls a job) and ``publish`` exclusive, bounded, for
the publish clone's pass; the publish step takes ``publish`` exclusive for the
publish alone (publish.py). Every lock fd here is close-on-exec and every
step child is spawned with close_fds, so a SIGKILLed runner releases all of
its locks even while a step child outlives it (tests/test_vps_deploy.py).
"""
from __future__ import annotations

import fcntl
import os
import pathlib
import time


class LockTimeout(RuntimeError):
    def __init__(self, name: str, waited_s: float):
        super().__init__(f"could not acquire lock {name!r} within {waited_s:.0f}s")
        self.name = name
        self.waited_s = waited_s


class Lock:
    """One flock. ``shared=True`` = LOCK_SH (readers), else LOCK_EX."""

    def __init__(self, path: pathlib.Path, shared: bool = False):
        self.path = pathlib.Path(path)
        self.shared = shared
        self.fd: int | None = None

    def try_acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o664)
        flag = (fcntl.LOCK_SH if self.shared else fcntl.LOCK_EX) | fcntl.LOCK_NB
        try:
            fcntl.flock(fd, flag)
        except (BlockingIOError, OSError):
            os.close(fd)
            return False
        self.fd = fd
        return True

    def acquire(self, wait_s: float, *, poll_s: float = 0.5,
                clock=time.monotonic, sleep=time.sleep) -> float:
        """Block up to ``wait_s``; return the seconds actually waited."""
        start = clock()
        while True:
            if self.try_acquire():
                return clock() - start
            waited = clock() - start
            if waited >= wait_s:
                raise LockTimeout(self.path.stem, waited)
            sleep(min(poll_s, max(0.0, wait_s - waited)))

    def release(self) -> None:
        if self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = None

    @property
    def held(self) -> bool:
        return self.fd is not None


def lock_path(state_dir: pathlib.Path, name: str) -> pathlib.Path:
    return pathlib.Path(state_dir) / "locks" / f"{name}.lock"


class LockSet:
    """Ordered acquisition of the job's locks (exclusive), then ``repo`` (shared)."""

    def __init__(self, state_dir: pathlib.Path, names, *, repo_shared: bool = True):
        self.state_dir = pathlib.Path(state_dir)
        self.order: list[Lock] = [Lock(lock_path(self.state_dir, n)) for n in names]
        self.order.append(Lock(lock_path(self.state_dir, "repo"), shared=repo_shared))
        self.waited_s = 0.0

    def acquire(self, wait_s: float, **kw) -> float:
        """Acquire every lock in order within ONE shared wait budget.

        On a timeout every lock already taken is released, so a job that gave
        up waiting never keeps its family lock (or ``repo``) pinned.
        """
        remaining = float(wait_s)
        total = 0.0
        try:
            for lk in self.order:
                waited = lk.acquire(max(0.0, remaining), **kw)
                total += waited
                remaining -= waited
        except LockTimeout as e:
            self.release()
            raise LockTimeout(e.name, total + e.waited_s) from None
        self.waited_s = total
        return total

    def release(self) -> None:
        for lk in reversed(self.order):
            lk.release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        return False

    @property
    def names(self) -> list[str]:
        return [lk.path.stem for lk in self.order]
