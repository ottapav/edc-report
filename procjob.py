"""Run heavy work in a forked child process.

Why a process and not a thread: key estimation and the ``rozdel()`` loop are CPU-bound
numpy / Python work. In a thread they compete with the web server's request threads
for the GIL (progress polls and page renders slow down) and cannot be stopped. In a
child process they get their own core, and the parent can **cancel** them (the user
uploaded another file, closed the page, or the time limit was hit) by killing the
child, which frees the job slot at once.

``fork`` shares the parent's memory without copying it: the arguments (big numpy
arrays) are not pickled, only progress messages and the (small) result travel back
through a queue. Where ``fork`` does not exist the function runs in-process, without
cancellation or a time limit.
"""

from __future__ import annotations

import gc
import multiprocessing as mp
import pickle
import queue
import resource
import signal
import time
from typing import Callable

ProgressFn = Callable[[str, float], None]


class JobCancelled(Exception):
    """The job was stopped on request (``cancelled()`` returned True)."""


class JobTimeout(Exception):
    """The job ran longer than its time limit and was killed."""


class WorkerDied(RuntimeError):
    """The child process ended without a result (killed, e.g. out of memory)."""

    def __init__(self, exitcode: int | None):
        super().__init__(f"worker process exited ({exitcode})")
        self.exitcode = exitcode

    @property
    def killed(self) -> bool:
        """Killed by SIGKILL: the kernel's OOM killer (or a hard stop)."""
        return self.exitcode == -signal.SIGKILL


def limit_memory(extra_mb: float) -> tuple[int, int] | None:
    """In a child: let it take at most ``extra_mb`` MB of address space beyond what it
    inherited, so that a runaway allocation fails there (MemoryError) instead of taking
    the whole server down. Returns the previous limits (for :func:`unlimit_memory`), or
    None where /proc is missing (nothing done)."""
    try:
        with open("/proc/self/status") as f:
            size = next(int(line.split()[1]) * 1024 for line in f if line.startswith("VmSize:"))
    except (OSError, StopIteration, ValueError):
        return None
    before = resource.getrlimit(resource.RLIMIT_AS)
    soft = size + int(extra_mb * 2**20)
    if before[1] != resource.RLIM_INFINITY:
        soft = min(soft, before[1])
    resource.setrlimit(resource.RLIMIT_AS, (soft, before[1]))
    return before


def unlimit_memory(before: tuple[int, int] | None) -> None:
    """Put back the limits :func:`limit_memory` replaced (the child does this itself before
    it sends anything back: pickling the result needs room the budget did not count)."""
    if before is not None:
        resource.setrlimit(resource.RLIMIT_AS, before)


def _child(fn, args, kwargs, q) -> None:  # runs in the child process
    # The child inherits the web server's signal handlers; gunicorn's SIGTERM handler
    # only flags "shutting down", so terminate() would not stop the child. Restore the
    # defaults first.
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT):
        signal.signal(sig, signal.SIG_DFL)
    # When memory runs out, the kernel kills the process with the highest score: make it
    # this child, never the web server (which holds every user's upload).
    try:
        with open("/proc/self/oom_score_adj", "w") as f:
            f.write("1000")
    except OSError:
        pass
    # Freezing the inherited heap keeps the garbage collector from walking (and
    # copy-on-write faulting) all of it, which would also be billed to any timing.
    gc.freeze()
    # start the queue's feeder thread now, before ``fn`` may limit the memory (a thread
    # cannot start under a tight limit), and keep the limit to restore before replying
    q.put(("s", None))
    limits = resource.getrlimit(resource.RLIMIT_AS)
    last = {"phase": None, "frac": -1.0}

    def progress(phase: str, frac: float) -> None:
        if phase != last["phase"] or frac - last["frac"] >= 0.01 or frac >= 1.0:
            last["phase"], last["frac"] = phase, frac       # at most ~100 messages per phase
            q.put(("p", phase, frac))

    try:
        result = fn(*args, progress=progress, **kwargs)
        unlimit_memory(limits)
        q.put(("r", result))
    except MemoryError:
        unlimit_memory(limits)
        q.put(("m", None))
    except BaseException as exc:  # reported to the parent
        unlimit_memory(limits)
        try:
            pickle.dumps(exc)
            q.put(("e", exc))
        except Exception:
            q.put(("e", RuntimeError(repr(exc))))


def run_in_child(
    fn: Callable,
    args: tuple = (),
    kwargs: dict | None = None,
    *,
    progress: ProgressFn,
    cancelled: Callable[[], bool] | None = None,
    timeout: float | None = None,
    reraise: bool = False,
):
    """Call ``fn(*args, progress=..., **kwargs)`` in a child process and return its result.

    ``progress(phase, fraction)`` is called here, in the caller's thread, for every
    message the child sends. ``cancelled()`` is polled about four times a second; when
    it returns True the child is killed and :class:`JobCancelled` raised. After
    ``timeout`` seconds the child is killed and :class:`JobTimeout` raised. A failing
    or crashing child raises :class:`RuntimeError` (``worker failed: …``), or with
    ``reraise`` the child's own exception; a child that ran out of memory raises
    :class:`MemoryError`, one that ended without a result :class:`WorkerDied`.
    """
    kwargs = kwargs or {}
    if "fork" not in mp.get_all_start_methods():
        return fn(*args, progress=progress, **kwargs)
    ctx = mp.get_context("fork")
    q = ctx.Queue()
    proc = ctx.Process(target=_child, args=(fn, args, kwargs, q), daemon=True)
    proc.start()
    t0 = time.monotonic()
    done = False
    try:
        while True:
            if cancelled is not None and cancelled():
                raise JobCancelled()
            if timeout is not None and time.monotonic() - t0 > timeout:
                raise JobTimeout(f"no result after {timeout:g} s")
            try:
                msg = q.get(timeout=0.25)
            except queue.Empty:
                if proc.is_alive():
                    continue
                try:                                  # exited: its last message may still be in flight
                    msg = q.get(timeout=1.0)
                except queue.Empty:
                    raise WorkerDied(proc.exitcode) from None
            if msg[0] == "s":                         # the child has started
                continue
            if msg[0] == "p":
                progress(msg[1], msg[2])
            elif msg[0] == "r":
                done = True
                return msg[1]
            elif msg[0] == "m":
                raise MemoryError("the worker process ran out of memory")
            elif reraise:
                raise msg[1]
            else:
                raise RuntimeError(f"worker failed: {msg[1]!r}")
    finally:
        if not done and proc.is_alive():
            proc.terminate()
        proc.join(timeout=5)
        if proc.is_alive():                           # ignored SIGTERM: do not leave it running
            proc.kill()
            proc.join(timeout=5)
