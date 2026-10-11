"""Background computations: key estimation, recompute with the exact method, billing.

Each job runs in a thread that waits for a free slot (at most ``config.MAX_JOBS`` run at
once; small instances have < 1 CPU) and runs the heavy part in a forked child process
(:mod:`procjob`), so the web server's request threads stay free for progress polls and
the job can be cancelled. A job stops itself when its result is no longer wanted: the
upload was replaced or evicted, or the page stopped polling for ``config.JOB_IDLE_S``.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import config
import store
from billing import BillResult, compute_shapley
from edc_data import per_destination, producer_arrays, supplied_per_source
from keyfit import estimate_keys
from procjob import JobCancelled, JobTimeout, run_in_child
from recompute import recompute, to_hundredths


@dataclass
class Job:
    kind: str                       # "fit", "exact" or "bill"
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
        return (self.cancel.is_set() or not store.contains(self.data_key)
                or time.perf_counter() - self.seen > config.JOB_IDLE_S)

    @property
    def fraction(self) -> float:
        """Progress of the whole job; a recompute that estimates the keys first spends
        about 60 % of its time on that."""
        if not self.with_fit:
            return self.frac
        return 0.6 * self.frac if self.phase == "fit" else 0.6 + 0.4 * self.frac


JOBS: dict[str, Job] = {}
_SLOTS = threading.BoundedSemaphore(config.MAX_JOBS)

Work = Callable[[store.Entry, Job], None]


def get(job_id: str | None) -> Job | None:
    return JOBS.get(job_id or "")


def stats() -> dict:
    running = [j for j in list(JOBS.values()) if not j.done]
    return {"jobs_running": sum(j.phase != "queued" for j in running),
            "jobs_queued": sum(j.phase == "queued" for j in running),
            "max_jobs": config.MAX_JOBS}


def start(kind: str, data_key: str, work: Work) -> str:
    """Run ``work(entry, job)`` in the background; return the job id."""
    now = time.perf_counter()
    for old in [i for i, j in list(JOBS.items())
                if (j.reported and now - j.t0 > 60) or now - j.t0 > 3600]:
        JOBS.pop(old, None)
    job_id = uuid.uuid4().hex
    JOBS[job_id] = job = Job(kind, data_key)
    threading.Thread(target=_run, args=(job, work), daemon=True).start()
    return job_id


def _run(job: Job, work: Work) -> None:
    try:
        while not _SLOTS.acquire(timeout=0.5):          # a cancelled job leaves the queue
            if job.cancelled():
                raise JobCancelled()
        try:
            job.t0 = time.perf_counter()                 # time the work, not the queue
            entry = store.get(job.data_key)
            if entry is None:
                raise JobCancelled()
            work(entry, job)
        finally:
            _SLOTS.release()
    except JobCancelled:
        job.error_key = "job_cancelled"
    except JobTimeout:
        job.error_key = "job_timeout"
    except Exception as exc:  # reported in the UI
        traceback.print_exc()
        job.error = str(exc)
    finally:
        job.done = True


# ---------------------------------------------------------------------------
# The three computations
# ---------------------------------------------------------------------------


def _estimate(entry: store.Entry, job: Job) -> None:
    job.progress("fit", 0.0)
    entry.fit = run_in_child(estimate_keys, to_hundredths(entry.data), progress=job.progress,
                             cancelled=job.cancelled, timeout=config.FIT_TIMEOUT_S)


def start_fit(data_key: str) -> str:
    """Estimate the allocation keys from the report (right after the upload)."""
    return start("fit", data_key, _estimate)


def start_exact(data_key: str, keys: list[float | None], reserve: float) -> str:
    """Recompute with the exact static method; empty keys (None) take the estimate."""
    def work(entry: store.Entry, job: Job) -> None:
        if entry.fit is None and any(k is None for k in keys):
            job.with_fit = True
            _estimate(entry, job)
        fit = entry.fit
        merged = [k if k is not None else (fit.keys[i] if fit else None)
                  for i, k in enumerate(keys)]
        if any(k is None for k in merged):
            raise RuntimeError("missing allocation keys")
        job.progress("compute", 0.0)
        entry.exact = recompute(
            entry.data, merged, reserve, progress=job.progress, cancelled=job.cancelled,
            keys_estimated=fit is not None and merged == list(fit.keys),
            rounds=fit.rounds if fit else 5)
    return start("exact", data_key, work)


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
