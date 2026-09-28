"""Recompute sharing with the exact static method (``presna_staticka.rozdel``).

The ``rozdel()`` loop runs in a forked worker process so its timing is not
disturbed by the web server's threads. Allocation keys come from the caller;
they are estimated from the report in :mod:`keyfit` right after upload.

All energies are integers in hundredths of kWh (0.01 kWh), like EDC data.
Only the all report with one producer is supported (demand is needed).
"""

from __future__ import annotations

import gc
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from keyfit import KeyFit, replay_match
from presna_staticka import rozdel
from edc_data import (
    SharingData, key_shared, key_unmet, key_unshared,
)

ProgressFn = Callable[[str, float], None]  # (phase, fraction 0..1)


def _noop(_phase: str, _frac: float) -> None:
    pass


# ---------------------------------------------------------------------------
# Inputs in hundredths of kWh
# ---------------------------------------------------------------------------


def to_hundredths(data: SharingData) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (P[T], D[T, n], S_actual[T, n]) as int64 hundredths of kWh."""
    if data.fmt != "all" or data.production is None or len(data.source_eans) != 1:
        raise ValueError("Recompute needs an all report with exactly one producer.")
    src = data.source_eans[0]
    P = np.round(data.production.to_numpy(dtype=float) * 100).astype(np.int64)
    P = np.clip(P, 0, None)
    D = np.stack([np.round(data.demand[e].to_numpy(dtype=float) * 100)
                  for e in data.dest_eans], axis=1).astype(np.int64)
    S = np.stack([np.round(data.frame[key_shared(src, e)].to_numpy(dtype=float) * 100)
                  for e in data.dest_eans], axis=1).astype(np.int64)
    return P, D, S


# ---------------------------------------------------------------------------
# rozdel() over all intervals, in a worker process
# ---------------------------------------------------------------------------


def rozdel_all(Pl: list[int], Dl: list[list[int]], keys: list[float], reserve: float,
               chunk: int = 96, report: Callable[[float], None] | None = None):
    """Evaluate every interval with ``rozdel``; return (shares, timing dict).

    Intervals are classified exactly like rozdel's fast paths (after the reserve)
    and each class runs as one timed batch, so per-class times are exact without
    timing every call. Intervals are independent, so the order does not matter.
    """
    T = len(Pl)
    active = [k > 0 for k in keys]
    night, enough, full = [], [], []
    for t in range(T):
        p = Pl[t]
        p_eff = p - round(p * reserve) if reserve > 0 else p
        if p_eff <= 0:
            night.append(t)
        elif sum(x for x, a in zip(Dl[t], active) if a) <= p_eff:
            enough.append(t)
        else:
            full.append(t)
    fine = time.get_clock_info("thread_time").resolution <= 1e-6
    clock = time.thread_time if fine else time.perf_counter
    out: list = [None] * T
    tt: dict = {"n_night": len(night), "n_enough": len(enough), "n_full": len(full),
                "clock": "thread CPU time" if fine else "wall time"}
    done = 0
    for batch, name in ((night, "t_night"), (enough, "t_enough"), (full, "t_full")):
        c0 = clock()
        for pos, t in enumerate(batch):
            out[t] = rozdel(Pl[t], Dl[t], keys, reserve)
            if report is not None and pos % chunk == 0:
                report((done + pos) / T)
        tt[name] = clock() - c0
        done += len(batch)
    return out, tt


def _worker(Pl, Dl, keys, reserve, chunk, q) -> None:  # runs in the child process
    # The forked child inherits the whole web-server heap; freezing it keeps the
    # garbage collector from walking (and copy-on-write faulting) all of it, which
    # would otherwise be billed to the rozdel() timing.
    gc.freeze()
    try:
        last = [0.0]

        def report(frac: float) -> None:
            if frac - last[0] >= 0.01:  # at most ~100 progress messages
                last[0] = frac
                q.put(("p", frac))

        out, tt = rozdel_all(Pl, Dl, keys, reserve, chunk, report)
        q.put(("r", out, tt))
    except Exception as exc:  # pragma: no cover - reported to the parent
        q.put(("e", repr(exc)))


def _run_isolated(Pl, Dl, keys, reserve, chunk, progress: ProgressFn):
    """Run :func:`rozdel_all` in a child process, relaying progress.

    Uses ``fork`` where available (cheap, no re-import of the web app); falls back
    to running in-process if a child process cannot be started.
    """
    import multiprocessing as mp
    import queue as _queue

    methods = mp.get_all_start_methods()
    if "fork" not in methods:
        return rozdel_all(Pl, Dl, keys, reserve, chunk, lambda f: progress("compute", f))
    ctx = mp.get_context("fork")
    q = ctx.Queue()
    proc = ctx.Process(target=_worker, args=(Pl, Dl, keys, reserve, chunk, q), daemon=True)
    proc.start()
    progress("compute", 0.0)
    try:
        while True:
            try:
                msg = q.get(timeout=0.5)
            except _queue.Empty:
                if not proc.is_alive():
                    raise RuntimeError(f"worker process exited ({proc.exitcode})")
                continue
            if msg[0] == "p":
                progress("compute", msg[1])
            elif msg[0] == "r":
                progress("compute", 1.0)
                return msg[1], msg[2]
            else:
                raise RuntimeError(f"worker failed: {msg[1]}")
    finally:
        proc.join(timeout=5)
        if proc.is_alive():
            proc.terminate()


# ---------------------------------------------------------------------------
# Exact static method over the whole report
# ---------------------------------------------------------------------------


@dataclass
class Timing:
    intervals: int = 0          # rozdel() calls = 15-min intervals evaluated
    members: int = 0
    n_night: int = 0            # P = 0            -> fast path
    n_enough: int = 0           # sum D <= P       -> fast path
    n_full: int = 0             # level H computed (sorting)
    t_total: float = 0.0        # s, sum of rozdel() call times
    t_night: float = 0.0
    t_enough: float = 0.0
    t_full: float = 0.0
    t_prepare: float = 0.0      # s, data conversion + building the result
    t_fit: float = 0.0          # s, key fitting (0 if keys were given)
    t_wall: float = 0.0         # s, whole job
    clock: str = ""             # which clock measured the rozdel calls

    @property
    def per_interval(self) -> float:
        return self.t_total / self.intervals if self.intervals else 0.0

    @property
    def per_full(self) -> float:
        return self.t_full / self.n_full if self.n_full else 0.0


@dataclass
class Recomputed:
    data: SharingData
    keys: list[float]
    keys_estimated: bool
    reserve: float
    timing: Timing
    edc_match: float           # replay of today's method with these keys vs report
    rounds: int = 5            # EDC rounds used for that replay
    fit: KeyFit | None = None
    notes: list[str] = field(default_factory=list)


def recompute(
    data: SharingData,
    keys: list[float],
    reserve: float = 0.0,
    progress: ProgressFn = _noop,
    chunk: int = 96,
    *,
    fit: KeyFit | None = None,
    keys_estimated: bool = False,
    rounds: int = 5,
) -> Recomputed:
    """Run ``rozdel`` for every 15-min interval and build a comparable SharingData.

    ``keys`` are fractions per destination (file order). ``rounds`` is the number
    of EDC rounds used to check how well the keys reproduce today's report.
    """
    t_job = time.perf_counter()
    tm = Timing()
    t0 = time.perf_counter()
    P, D, S = to_hundredths(data)
    tm.t_prepare += time.perf_counter() - t0

    keys = [max(0.0, float(x)) for x in keys]
    if not any(k > 0 for k in keys):
        raise ValueError("At least one allocation key must be > 0.")

    T, n = D.shape
    tm.intervals, tm.members = T, n
    Pl = P.tolist()
    Dl = D.tolist()

    # The rozdel() loop runs in a separate process: it gets a whole core and its
    # timing is not disturbed by the web server's threads (GIL, caches).
    out, tt = _run_isolated(Pl, Dl, keys, reserve, chunk, progress)
    for name, value in tt.items():
        setattr(tm, name, value)
    tm.t_total = tm.t_night + tm.t_enough + tm.t_full

    t0 = time.perf_counter()
    s_arr = np.asarray(out, dtype=np.int64)
    src = data.source_eans[0]
    idx = data.frame.index
    cols: dict[str, pd.Series] = {}
    for j, e in enumerate(data.dest_eans):
        cols[key_shared(src, e)] = pd.Series(s_arr[:, j] / 100, index=idx)
        cols[key_unmet(e)] = pd.Series((D[:, j] - s_arr[:, j]) / 100, index=idx)
    cols[key_unshared(src)] = pd.Series((P - s_arr.sum(axis=1)) / 100, index=idx)
    frame = pd.DataFrame(cols, index=idx)
    new = SharingData(
        frame=frame, fmt="all", source_eans=list(data.source_eans),
        dest_eans=list(data.dest_eans), production=data.production,
        demand=data.demand, coverage=data.coverage, first_data=data.first_data,
        notes=[], n_rows=data.n_rows,
    )
    edc_match = replay_match(P, D, S, keys, rounds)
    tm.t_prepare += time.perf_counter() - t0
    tm.t_wall = time.perf_counter() - t_job
    progress("done", 1.0)
    return Recomputed(data=new, keys=keys, keys_estimated=keys_estimated, reserve=reserve,
                      timing=tm, edc_match=edc_match, rounds=rounds, fit=fit)
