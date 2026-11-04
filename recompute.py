"""Recompute sharing with the exact static method (``presna_staticka.rozdel``).

The ``rozdel()`` loop runs in a child process (:mod:`procjob`), so its timing is not
disturbed by the web server's threads and it can be cancelled. Allocation keys come from the caller;
they are estimated from the report in :mod:`keyfit` right after upload.

All energies are integers in hundredths of kWh (0.01 kWh), like EDC data.
The all report is needed (demand). Several producers are one **pool** for the exact
method: their production is shared as if it came from one big producer. EDC itself sets
a key for every pair producer -> member (:func:`keyfit.replay_edc_multi`); for the pool
the pair keys are combined interval by interval,
``k_j(t) = sum_i (K[i, j] / sum_l K[i, l]) · P_i(t) / P(t)``: every producer's keys as
ratios (EDC with endlessly many rounds gives away all of a producer's production, so its
keys act as ratios), weighted by what the producers produce then. When nobody is filled
up, every member gets what EDC with endlessly many rounds would give it. The pool's
surplus goes back to the producers in proportion to their production in the interval.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from keyfit import pooled_keys, replay_edc, replay_edc_multi, replay_match, replay_match_multi
from procjob import run_in_child
from presna_staticka import rozdel
from edc_data import (
    SharingData, key_shared, key_unmet, key_unshared, producer_arrays, shared_source,
)

ProgressFn = Callable[[str, float], None]  # (phase, fraction 0..1)


def _noop(_phase: str, _frac: float) -> None:
    pass


# ---------------------------------------------------------------------------
# Inputs in hundredths of kWh
# ---------------------------------------------------------------------------


def to_hundredths(data: SharingData) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (P[T], D[T, n], S_actual[T, n]) as int64 hundredths of kWh; P is the
    production of all producers together (the pool)."""
    if data.fmt != "all" or data.production is None:
        raise ValueError("Recompute needs an all report with the production of every producer.")
    src = shared_source(data)
    P2, D = producer_arrays(data)
    P = P2.sum(axis=1)
    S = np.stack([np.round(data.frame[key_shared(src, e)].to_numpy(dtype=float) * 100)
                  for e in data.dest_eans], axis=1).astype(np.int64)
    return P, D, S


def to_hundredths_multi(data: SharingData):
    """(P2[T, np] production per producer, D, S, Q[T, np] what each producer shared) as
    int64 hundredths of kWh: the inputs of the pair keys."""
    P, D, S = to_hundredths(data)
    P2, _D = producer_arrays(data)
    U = np.stack([np.round(data.frame[key_unshared(p)].to_numpy(dtype=float) * 100)
                  for p in data.source_eans], axis=1).astype(np.int64)
    return P2, D, S, np.clip(P2 - U, 0, None)


def interval_keys(P2: np.ndarray, pair_keys) -> np.ndarray:
    """The pool's key of every member in every interval (T×n) from the pair keys: each
    producer's keys as ratios, weighted by the producers' production then; with no
    production, by the producers' total production (:func:`keyfit.pooled_keys`)."""
    K = np.asarray(pair_keys, dtype=float)
    out = pooled_keys(K, P2)
    night = P2.sum(axis=1) == 0
    if night.any():
        out[night] = pooled_keys(K, P2.sum(axis=0))
    return out


def check_pair_keys(pair_keys) -> None:
    """Pair keys (np × n fractions): none negative, at least one positive, no producer
    gives away more than 100 % (EDC rule)."""
    K = np.asarray(pair_keys, dtype=float)
    if (K < 0).any():
        raise InvalidKeys("keys_negative")
    if (K.sum(axis=1) > 1 + 1e-9).any():
        raise InvalidKeys("pair_sum_over")
    if not (K > 0).any():
        raise InvalidKeys("keys_all_zero")


def split_surplus(P2: np.ndarray, surplus: np.ndarray) -> np.ndarray:
    """The pool's surplus (T, hundredths) per producer (T×np): in proportion to each
    producer's production in the interval, whole hundredths that add up exactly (largest
    remainder), never more than a producer produced."""
    P2 = np.asarray(P2, dtype=np.int64)
    total = P2.sum(axis=1)
    if P2.shape[1] == 1:
        return surplus[:, None].astype(np.int64)
    with np.errstate(divide="ignore", invalid="ignore"):
        exact = np.where(total[:, None] > 0, P2 * (surplus / np.where(total > 0, total, 1))[:, None], 0.0)
    out = np.floor(exact + 1e-9).astype(np.int64)
    left = surplus.astype(np.int64) - out.sum(axis=1)
    order = np.argsort(-(exact - out), axis=1, kind="stable")
    for t in np.nonzero(left > 0)[0]:
        out[t, order[t, :left[t]]] += 1
    return out


# ---------------------------------------------------------------------------
# rozdel() over all intervals, in a worker process
# ---------------------------------------------------------------------------


def rozdel_all(Pl: list[int], Dl: list[list[int]], keys: list, reserve: float,
               chunk: int = 96, report: Callable[[float], None] | None = None):
    """Evaluate every interval with ``rozdel``; return (shares, timing dict).

    ``keys`` is one list of keys, or a list of keys per interval (the pool of several
    producers). Intervals are classified exactly like rozdel's fast paths (after the
    reserve) and each class runs as one timed batch, so per-class times are exact
    without timing every call. Intervals are independent, so the order does not matter.
    """
    T = len(Pl)
    per_interval = bool(keys) and isinstance(keys[0], (list, tuple))
    key_of = (lambda t: keys[t]) if per_interval else (lambda t: keys)  # noqa: E731
    night, enough, full = [], [], []
    for t in range(T):
        p = Pl[t]
        p_eff = p - round(p * reserve) if reserve > 0 else p
        if p_eff <= 0:
            night.append(t)
        elif sum(x for x, k in zip(Dl[t], key_of(t)) if k > 0) <= p_eff:
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
            out[t] = rozdel(Pl[t], Dl[t], key_of(t), reserve)
            if report is not None and pos % chunk == 0:
                report((done + pos) / T)
        tt[name] = clock() - c0
        done += len(batch)
    return out, tt


def _rozdel_child(Pl, Dl, keys, reserve, chunk, progress: ProgressFn):
    return rozdel_all(Pl, Dl, keys, reserve, chunk, lambda f: progress("compute", f))


def _run_isolated(Pl, Dl, keys, reserve, chunk, progress: ProgressFn,
                  cancelled: Callable[[], bool] | None = None):
    """Run :func:`rozdel_all` in a child process (see :mod:`procjob`), relaying progress.

    The loop gets a core of its own, so its timing is not disturbed by the web server's
    threads, and the child can be killed when ``cancelled()`` turns True.
    """
    progress("compute", 0.0)
    return run_in_child(_rozdel_child, (Pl, Dl, keys, reserve, chunk), progress=progress,
                        cancelled=cancelled)


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
    #: the approximate static method (today's EDC rounds) replayed with the same keys and
    #: reserve, unless they are the report's own (estimated keys, no reserve: then None,
    #: the report itself is the approximate method's result)
    approx: SharingData | None = None
    #: several producers: the pair keys (np × n) the pool's keys came from; ``keys``
    #: are then the pool's keys over the period (pair keys weighted by production)
    pair_keys: list | None = None

    @property
    def pool(self) -> int:
        """Number of producers shared as one pool (0 with one producer)."""
        n = len(self.data.source_eans)
        return n if n > 1 else 0

    def left(self, report: SharingData) -> SharingData:
        """What the exact method is compared with: the replay, or the EDC report."""
        return self.approx if self.approx is not None else report


class InvalidKeys(ValueError):
    """Allocation keys that cannot be used; ``reason`` is the i18n key of the message."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def check_keys(keys: list[float]) -> None:
    """Keys are fractions: none negative, at least one positive, sum at most 100 %."""
    if any(k < 0 for k in keys):
        raise InvalidKeys("keys_negative")
    if sum(keys) > 1 + 1e-9:
        raise InvalidKeys("keys_sum_over")
    if not any(k > 0 for k in keys):
        raise InvalidKeys("keys_all_zero")


def _as_data(data: SharingData, s: np.ndarray, P: np.ndarray, D: np.ndarray,
             unshared: np.ndarray | None = None) -> SharingData:
    """Shares ``s`` (T×n hundredths) as a report like ``data``: shared from the producer
    (or the pool), unmet per member, unshared per producer (given, or the pool's surplus
    split by :func:`split_surplus`)."""
    src = shared_source(data)
    idx = data.frame.index
    cols: dict[str, pd.Series] = {}
    for j, e in enumerate(data.dest_eans):
        cols[key_shared(src, e)] = pd.Series(s[:, j] / 100, index=idx)
        cols[key_unmet(e)] = pd.Series((D[:, j] - s[:, j]) / 100, index=idx)
    if unshared is None:
        P2, _D = producer_arrays(data)
        surplus = split_surplus(P2, P - s.sum(axis=1))
    else:
        surplus = np.asarray(unshared, dtype=np.int64)
    for i, p in enumerate(data.source_eans):
        cols[key_unshared(p)] = pd.Series(surplus[:, i] / 100, index=idx)
    return SharingData(
        frame=pd.DataFrame(cols, index=idx), fmt="all", source_eans=list(data.source_eans),
        dest_eans=list(data.dest_eans), production=data.production,
        productions=data.productions, demand=data.demand, coverage=data.coverage,
        first_data=data.first_data, notes=[], n_rows=data.n_rows,
    )


def replay_approx(data: SharingData, keys: list[float], rounds: int,
                  reserve: float = 0.0, pair_keys=None) -> SharingData:
    """Today's EDC method (``rounds`` rounds) with ``keys``, over the whole report; a
    reserve for sale is taken off the production first, as in the exact method. With
    ``pair_keys`` (several producers) it is EDC's method for several producers: what
    each producer shared comes from the replay itself."""
    P, D, _S = to_hundredths(data)
    if pair_keys is None:
        P_eff = P - np.round(P * reserve).astype(np.int64) if reserve > 0 else P
        return _as_data(data, replay_edc(P_eff, D, keys, rounds), P, D)
    P2, _D = producer_arrays(data)
    P2_eff = P2 - np.round(P2 * reserve).astype(np.int64) if reserve > 0 else P2
    s, q = replay_edc_multi(P2_eff, D, pair_keys, rounds)
    return _as_data(data, s, P, D, unshared=P2 - q)


@dataclass(frozen=True)
class GridLoss:
    """Energy the EDC report sent to the grid although members could have used it."""

    production: float       # kWh
    shared_edc: float       # kWh shared by the EDC report
    shared_exact: float     # kWh shared by the exact method
    lost: float             # kWh the exact method shares in addition (>= 0)

    @property
    def pct_of_max(self) -> float:
        """Sharing error: the part of the maximum (exact-method) sharing EDC missed."""
        return 100 * self.lost / self.shared_exact if self.shared_exact > 0 else 0.0

    @property
    def negligible(self) -> bool:
        return self.lost < 0.005


def grid_loss(edc: SharingData, exact: SharingData, enabled: set[str] | None = None) -> GridLoss:
    """Shared energy of the ``enabled`` members (default all): EDC report vs. exact recompute."""
    enabled = set(edc.dest_eans) if enabled is None else enabled

    def shared(d: SharingData) -> float:
        cols = [key_shared(shared_source(d), e) for e in d.dest_eans if e in enabled]
        return float(d.frame[cols].to_numpy(dtype=float).sum()) if cols else 0.0

    prod = float(edc.production.sum()) if edc.production is not None else 0.0
    a, b = shared(edc), shared(exact)
    return GridLoss(production=prod, shared_edc=a, shared_exact=b, lost=max(0.0, b - a))


def recompute(
    data: SharingData,
    keys: list[float],
    reserve: float = 0.0,
    progress: ProgressFn = _noop,
    chunk: int = 96,
    *,
    keys_estimated: bool = False,
    rounds: int = 5,
    cancelled: Callable[[], bool] | None = None,
    pair_keys=None,
) -> Recomputed:
    """Run ``rozdel`` for every 15-min interval and build a comparable SharingData.

    ``keys`` are fractions per destination (file order); :class:`InvalidKeys` if they
    cannot be used (:func:`check_keys`). ``rounds`` is the number of EDC rounds used to
    check how well the keys reproduce today's report. Unless the keys are the ones
    estimated from the report (and there is no reserve), today's method is replayed with
    them as well (``Recomputed.approx``), so both sides of the comparison use the same
    inputs.

    With ``pair_keys`` (several producers, np × n) the pool gets in every interval the
    keys :func:`interval_keys` makes of them, ``keys`` is ignored and becomes the pool's
    keys over the period; the replay and its check use EDC's method for several
    producers.
    """
    t_job = time.perf_counter()
    tm = Timing()
    t0 = time.perf_counter()
    P, D, S = to_hundredths(data)
    tm.t_prepare += time.perf_counter() - t0

    if pair_keys is not None:
        pair_keys = [[float(x) for x in row] for row in pair_keys]
        check_pair_keys(pair_keys)
        P2, _D, _S, Q = to_hundredths_multi(data)
        keys = [float(x) for x in pooled_keys(pair_keys, P2.sum(axis=0))]
        loop_keys = interval_keys(P2, pair_keys).tolist()
    else:
        keys = [float(x) for x in keys]
        check_keys(keys)
        loop_keys = keys

    T, n = D.shape
    tm.intervals, tm.members = T, n
    Pl = P.tolist()
    Dl = D.tolist()

    # The rozdel() loop runs in a separate process: it gets a whole core and its
    # timing is not disturbed by the web server's threads (GIL, caches).
    out, tt = _run_isolated(Pl, Dl, loop_keys, reserve, chunk, progress, cancelled)
    for name, value in tt.items():
        setattr(tm, name, value)
    tm.t_total = tm.t_night + tm.t_enough + tm.t_full

    t0 = time.perf_counter()
    new = _as_data(data, np.asarray(out, dtype=np.int64), P, D)
    same_as_report = keys_estimated and reserve == 0
    approx = None if same_as_report else replay_approx(data, keys, rounds, reserve, pair_keys)
    edc_match = (replay_match(P, D, S, keys, rounds) if pair_keys is None
                 else replay_match_multi(P2, D, S, Q, pair_keys, rounds))
    tm.t_prepare += time.perf_counter() - t0
    tm.t_wall = time.perf_counter() - t_job
    progress("done", 1.0)
    return Recomputed(data=new, keys=keys, keys_estimated=keys_estimated, reserve=reserve,
                      timing=tm, edc_match=edc_match, rounds=rounds, approx=approx,
                      pair_keys=pair_keys)
