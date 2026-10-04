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
import queue
import signal
import time
from typing import Callable

ProgressFn = Callable[[str, float], None]


class JobCancelled(Exception):
    """The job was stopped on request (``cancelled()`` returned True)."""


class JobTimeout(Exception):
    """The job ran longer than its time limit and was killed."""


def _child(fn, args, kwargs, q) -> None:  # runs in the child process
    # The child inherits the web server's signal handlers; gunicorn's SIGTERM handler
    # only flags "shutting down", so terminate() would not stop the child. Restore the
    # defaults first.
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT):
        signal.signal(sig, signal.SIG_DFL)
    # Freezing the inherited heap keeps the garbage collector from walking (and
    # copy-on-write faulting) all of it, which would also be billed to any timing.
    gc.freeze()
    last = {"phase": None, "frac": -1.0}

    def progress(phase: str, frac: float) -> None:
        if phase != last["phase"] or frac - last["frac"] >= 0.01 or frac >= 1.0:
            last["phase"], last["frac"] = phase, frac       # at most ~100 messages per phase
            q.put(("p", phase, frac))

    try:
        q.put(("r", fn(*args, progress=progress, **kwargs)))
    except BaseException as exc:  # reported to the parent
        q.put(("e", repr(exc)))


def run_in_child(
    fn: Callable,
    args: tuple = (),
    kwargs: dict | None = None,
    *,
    progress: ProgressFn,
    cancelled: Callable[[], bool] | None = None,
    timeout: float | None = None,
):
    """Call ``fn(*args, progress=..., **kwargs)`` in a child process and return its result.

    ``progress(phase, fraction)`` is called here, in the caller's thread, for every
    message the child sends. ``cancelled()`` is polled about four times a second; when
    it returns True the child is killed and :class:`JobCancelled` raised. After
    ``timeout`` seconds the child is killed and :class:`JobTimeout` raised. A failing
    or crashing child raises :class:`RuntimeError`.
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
                    raise RuntimeError(f"worker process exited ({proc.exitcode})") from None
            if msg[0] == "p":
                progress(msg[1], msg[2])
            elif msg[0] == "r":
                done = True
                return msg[1]
            else:
                raise RuntimeError(f"worker failed: {msg[1]}")
    finally:
        if not done and proc.is_alive():
            proc.terminate()
        proc.join(timeout=5)
        if proc.is_alive():                           # ignored SIGTERM: do not leave it running
            proc.kill()
            proc.join(timeout=5)
