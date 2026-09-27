"""flock-based locks for the VPS runner (DESIGN section 3.2, "Lock families").

Every lock is a file under ``<state>/locks/<name>.lock`` held with
``fcntl.flock`` for the life of the process (the OS releases it on crash, so a
killed job can never wedge the box). Acquisition is ORDERED, always:

    repo (shared)  ->  family lock (scan | heavy, exclusive)  ->  own name (exclusive)

so two jobs can never deadlock on each other. The WAIT for a lock is a
separate budget from the step timeout (``Job.lock_wait_s`` vs ``Job.timeout_s``):
a close arriving mid-scan queues behind a 40-80 minute ASX run instead of
failing, and the ledger row records how long it waited (``waited_s``).

``update.sh`` / ``gc.sh`` take ``repo`` EXCLUSIVE and non-blocking; the publish
step takes ``publish`` exclusive for the publish alone (publish.py).
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
    """Ordered acquisition of ``repo`` (shared) then the job's locks (exclusive)."""

    def __init__(self, state_dir: pathlib.Path, names, *, repo_shared: bool = True):
        self.state_dir = pathlib.Path(state_dir)
        self.order: list[Lock] = [Lock(lock_path(self.state_dir, "repo"), shared=repo_shared)]
        self.order += [Lock(lock_path(self.state_dir, n)) for n in names]
        self.waited_s = 0.0

    def acquire(self, wait_s: float, **kw) -> float:
        """Acquire every lock in order within ONE shared wait budget.

        On a timeout every lock already taken is released, so a job that gave
        up waiting for ``scan`` never keeps ``repo`` pinned for update.sh.
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
