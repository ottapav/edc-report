"""Background computations: key estimation, recompute with the exact method, billing,
and fetching the spot prices.

Each job runs in a thread that waits for a free slot (at most ``config.MAX_JOBS`` run at
once; small instances have < 1 CPU) and runs the heavy part in a forked child process
(:mod:`procjob`), so the web server's request threads stay free for progress polls and
the job can be cancelled. A job stops itself when its result is no longer wanted: the
upload was replaced or evicted, or the page stopped polling for ``config.JOB_IDLE_S``;
and it is stopped after ``config.JOB_TIMEOUT_S`` of work.

Limits that keep one client from taking the server (anyone can send the callbacks the
page sends, buttons or not): a report has one job of a kind at a time (a new one replaces
it), at most ``config.MAX_PENDING`` jobs are unfinished at once (more are refused,
:class:`Busy`), and an upload is parsed in a child process with a memory budget, one at a
time (:func:`parse_report`).
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from pandas.errors import ParserError

import config
import spot
import store
from billing import BillResult, compute_shapley
from edc_data import (SharingData, load_report, per_destination, producer_arrays,
                      supplied_per_source)
from keyfit import estimate_keys, estimate_pair_keys
from procjob import JobCancelled, JobTimeout, WorkerDied, limit_memory, run_in_child
from recompute import InvalidKeys, recompute, to_hundredths, to_hundredths_multi


@dataclass
class Job:
    kind: str                       # "fit", "exact", "bill" or "spot"
    data_key: str                   # the upload it works on
    phase: str = "queued"           # then the phase the work reports: fit / compute / bill
    frac: float = 0.0               # progress of the phase, 0..1
    with_fit: bool = False          # an "exact" job that first estimates the keys
    done: bool = False
    error: str | None = None        # message of an unexpected failure
    error_key: str | None = None    # i18n key of an expected stop (cancelled, timeout)
    t0: float = field(default_factory=time.perf_counter)     # start of the work
    seen: float = field(default_factory=time.perf_counter)   # last progress poll
    cancel: threading.Event = field(default_factory=threading.Event)
    final: Any = None               # the UI's final state, repeated by every later poll
    reported: bool = False          # the UI has shown the result

    def progress(self, phase: str, frac: float) -> None:
        self.phase, self.frac = phase, frac

    def cancelled(self) -> bool:
        """True when the result is no longer wanted. Raises :class:`JobTimeout` when the
        work has run longer than ``config.JOB_TIMEOUT_S`` (every long step polls this, so
        the limit holds wherever the job is)."""
        now = time.perf_counter()
        if self.phase != "queued" and now - self.t0 > config.JOB_TIMEOUT_S:
            raise JobTimeout(f"stopped after {config.JOB_TIMEOUT_S:g} s")
        return (self.cancel.is_set() or not store.contains(self.data_key)
                or now - self.seen > config.JOB_IDLE_S)

    @property
    def fraction(self) -> float:
        """Progress of the whole job; a recompute that estimates the keys first spends
        about 60 % of its time on that."""
        if not self.with_fit:
            return self.frac
        return 0.6 * self.frac if self.phase == "fit" else 0.6 + 0.4 * self.frac


JOBS: dict[str, Job] = {}
_SLOTS = threading.BoundedSemaphore(config.MAX_JOBS)
_START = threading.Lock()


class Busy(Exception):
    """Too many computations at once (``config.MAX_PENDING``), or another upload is being
    parsed: the request is refused, the user tries again in a while."""


class TooBig(Exception):
    """The report needs more memory to parse than ``config.PARSE_MB``."""

Work = Callable[[store.Entry, Job], None]


def get(job_id: str | None) -> Job | None:
    return JOBS.get(job_id or "")


def stats() -> dict:
    running = [j for j in list(JOBS.values()) if not j.done]
    return {"jobs_running": sum(j.phase != "queued" for j in running),
            "jobs_queued": sum(j.phase == "queued" for j in running),
            "max_jobs": config.MAX_JOBS}


def start(kind: str, data_key: str, work: Work, slot: bool = True) -> str:
    """Run ``work(entry, job)`` in the background; return the job id. ``slot``: wait for
    one of the ``MAX_JOBS`` slots (CPU-bound work); network waits need none. A running
    job of the same kind for the same report is cancelled (its result would be replaced);
    :class:`Busy` when ``config.MAX_PENDING`` jobs are unfinished."""
    with _START:
        now = time.perf_counter()
        for old in [i for i, j in list(JOBS.items())
                    if (j.reported and now - j.t0 > 60) or now - j.t0 > 3600]:
            JOBS.pop(old, None)
        live = [j for j in JOBS.values() if not j.done and not j.cancel.is_set()]
        for j in live:
            if j.kind == kind and j.data_key == data_key:
                j.cancel.set()
        if sum(not j.cancel.is_set() for j in live) >= config.MAX_PENDING:
            raise Busy()
        job_id = uuid.uuid4().hex
        JOBS[job_id] = job = Job(kind, data_key)
    threading.Thread(target=_run, args=(job, work, slot), daemon=True).start()
    return job_id


def _run(job: Job, work: Work, slot: bool = True) -> None:
    try:
        while slot and not _SLOTS.acquire(timeout=0.5):   # a cancelled job leaves the queue
            if job.cancelled():
                raise JobCancelled()
        try:
            job.t0 = time.perf_counter()                 # time the work, not the queue
            entry = store.get(job.data_key)
            if entry is None:
                raise JobCancelled()
            work(entry, job)
        finally:
            if slot:
                _SLOTS.release()
    except (JobCancelled, spot.Cancelled):
        job.error_key = "job_cancelled"
    except JobTimeout:
        job.error_key = "job_timeout"
    except MemoryError:
        job.error_key = "job_memory"
    except WorkerDied as exc:
        if not exc.killed:
            raise
        job.error_key = "job_memory"                 # the kernel's OOM killer, most likely
    except InvalidKeys as exc:
        job.error_key = exc.reason
    except spot.SpotError as exc:                    # OTE unreachable or answered oddly
        job.error_key, job.error = "spot_error", str(exc)
    except Exception as exc:  # reported in the UI
        traceback.print_exc()
        job.error = str(exc)
    finally:
        job.done = True


# ---------------------------------------------------------------------------
# Parsing an upload
# ---------------------------------------------------------------------------

_PARSE = threading.Lock()


def _parse_child(content: bytes, budget_mb: float, progress) -> SharingData:
    limit_memory(budget_mb)              # procjob lifts it again before sending the result
    try:
        return load_report(content)
    except ParserError as exc:           # pandas' C reader reports its own out-of-memory
        if "out of memory" in str(exc):
            raise MemoryError() from None
        raise


def parse_report(content: bytes) -> SharingData:
    """:func:`edc_data.load_report` in a child process that may take at most
    ``config.PARSE_MB`` of memory, one upload at a time: a huge or odd file then fails
    alone (:class:`TooBig`) and the server keeps every other user's data. Parse errors
    (ValueError: not an EDC report, …) come back as they are. :class:`Busy` when another
    upload is still being parsed after ``config.PARSE_WAIT_S``."""
    if not _PARSE.acquire(timeout=config.PARSE_WAIT_S):
        raise Busy()
    try:
        return run_in_child(_parse_child, (content, config.PARSE_MB), progress=_no_progress,
                            timeout=config.PARSE_TIMEOUT_S, reraise=True)
    except (MemoryError, WorkerDied, JobTimeout):
        raise TooBig() from None
    finally:
        _PARSE.release()


def _no_progress(phase: str, frac: float) -> None:
    pass


# ---------------------------------------------------------------------------
# The computations
# ---------------------------------------------------------------------------


def _estimate(entry: store.Entry, job: Job) -> None:
    """Allocation keys from the report; with several producers the key of every pair
    producer -> member (EDC's method for several producers)."""
    job.progress("fit", 0.0)
    multi = len(entry.data.source_eans) > 1
    fn, args = ((estimate_pair_keys, to_hundredths_multi(entry.data)) if multi
                else (estimate_keys, to_hundredths(entry.data)))
    entry.fit = run_in_child(fn, args, progress=job.progress, cancelled=job.cancelled,
                             timeout=config.FIT_TIMEOUT_S)


def start_fit(data_key: str) -> str:
    """Estimate the allocation keys from the report (right after the upload)."""
    return start("fit", data_key, _estimate)


def start_exact(data_key: str, keys: list[float | None] | None, reserve: float,
                pairs: list[list[float | None]] | None = None) -> str:
    """Recompute with the exact static method; empty keys (None) take the estimate. With
    other keys than the estimate (or a reserve) today's method is replayed with them too
    (see :func:`recompute.recompute`). Several producers: ``pairs`` are the pair keys
    (np × n), the pool gets keys made of them in every interval."""
    def work(entry: store.Entry, job: Job) -> None:
        if pairs is not None:
            _exact_pairs(entry, job, pairs, reserve)
            return
        if entry.fit is None and any(k is None for k in keys):
            job.with_fit = True
            _estimate(entry, job)
        fit = entry.fit
        merged = [k if k is not None else (fit.keys[i] if fit else None)
                  for i, k in enumerate(keys)]
        if any(k is None for k in merged):
            raise RuntimeError("missing allocation keys")
        # the grid shows the estimate in percent with two decimals, so a key read back
        # from it can differ from the estimate in the last bits (1.04 % is 0.0104, the
        # estimate 0.010400000000000001): within 1e-9 it is the estimate
        estimated = fit is not None and len(fit.keys) == len(merged) and all(
            abs(k - f) <= 1e-9 for k, f in zip(merged, fit.keys))
        if estimated:
            merged = [float(f) for f in fit.keys]
        job.progress("compute", 0.0)
        entry.exact = recompute(
            entry.data, merged, reserve, progress=job.progress, cancelled=job.cancelled,
            keys_estimated=estimated, rounds=fit.rounds if fit else 5)
    return start("exact", data_key, work)


def _exact_pairs(entry: store.Entry, job: Job, pairs, reserve: float) -> None:
    """The exact method for several producers, from the pair keys (empty cells: the
    estimate)."""
    if entry.fit is None and any(k is None for row in pairs for k in row):
        job.with_fit = True
        _estimate(entry, job)
    fit = entry.fit
    est = getattr(fit, "pair_keys", None)
    merged = [[k if k is not None else (est[i][j] if est else None)
               for j, k in enumerate(row)] for i, row in enumerate(pairs)]
    if any(k is None for row in merged for k in row):
        raise RuntimeError("missing allocation keys")
    # read back from the grid (percent, two decimals) a key may differ from the
    # estimate in the last bits: within 1e-9 it is the estimate
    estimated = bool(est) and all(abs(k - e) <= 1e-9 for row, erow in zip(merged, est)
                                  for k, e in zip(row, erow))
    if estimated:
        merged = [[float(e) for e in row] for row in est]
    job.progress("compute", 0.0)
    entry.exact = recompute(entry.data, None, reserve, progress=job.progress,
                            cancelled=job.cancelled, keys_estimated=estimated,
                            rounds=fit.rounds if fit else 5, pair_keys=merged)


def start_bill(data_key: str, prices: list[float], feed_ins: list[float]) -> str:
    """Billing by the Shapley value of the report's shared energy (supplier price per
    destination, feed-in price per producer)."""
    def work(entry: store.Entry, job: Job) -> None:
        job.progress("bill", 0.0)
        data = entry.data
        P, D = producer_arrays(data)
        totals = run_in_child(compute_shapley, (P, D, prices, feed_ins),
                              progress=job.progress, cancelled=job.cancelled)
        entry.bill = BillResult.build(totals, per_destination(data)["shared"].to_numpy(),
                                      supplied_per_source(data), data.frame.index,
                                      data.dest_eans, data.source_eans)
    return start("bill", data_key, work)


def start_spot(data_key: str) -> str:
    """Fetch the OTE day-ahead prices of the report's period (network, no CPU slot); the
    comparison itself is quick and follows the prices typed in the panel."""
    def work(entry: store.Entry, job: Job) -> None:
        job.progress("spot", 0.0)
        entry.spot = spot.fetch_for(entry.data, progress=job.progress,
                                    cancelled=job.cancelled)
    return start("spot", data_key, work, slot=False)
