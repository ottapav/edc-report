"""Estimate EDC allocation keys from a SharEl report (the CSV carries no keys).

Today's EDC static method (``presna_staticka.staticka_edc``): in every round each
member gets ``min(remaining demand, floor(k_i * P_r))`` where ``P_r`` is the
production left at the start of round r. Groups up to 100 EAN get 5 rounds,
larger groups a single round.

Key observation: a member that is *not* fully covered at the end of an interval
was never capped, so it received exactly ``floor(k_i * P_r)`` in every round:

    s_i = sum_r floor(k_i * P_r)   =>   s_i / SP  <=  k_i  <  (s_i + R) / SP,
    SP = sum_r P_r

so every interval bounds k_i. (With one round a fully covered member adds
``k_i >= D_i / P``.) The key is the value consistent with the most intervals on
the 0.01 % grid of EDC keys; a rounder value nearby wins unless the intervals that
separate the two clearly favour the other (see :func:`_choose_key`).

* One round is **separable** - each member depends on its own key only - so all
  keys come out in one pass, O(T·n). This covers groups above 100 EAN.
* Five rounds couple the members through P_r. The bounds are iterated to a fixed
  point, then members are settled by the replay itself (several round keys can be
  self-consistent). Only for groups up to 100 members, as in EDC.

Both round counts are tried when allowed; the one whose replay reproduces more
report intervals wins. Replays run in numpy blocks of intervals to bound memory.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

ProgressFn = Callable[[str, float], None]
CHUNK = 4096                 # intervals per numpy block (bounds memory for big groups)
EDC_MAX_5_ROUNDS = 100       # larger groups get a single round (EDC rule)
FINE = 1e-4                  # EDC keys are whole hundredths of a percent
SNAP_STEPS = (0.01, 0.005, 0.001, 0.0005)   # rounder candidates, coarse to fine


def _noop(_p: str, _f: float) -> None:
    pass


# ---------------------------------------------------------------------------
# Replay of today's EDC method
# ---------------------------------------------------------------------------


def replay_edc(P: np.ndarray, D: np.ndarray, k, rounds: int = 5, want_sp: bool = False):
    """Vectorised ``staticka_edc`` over intervals (rows).

    Returns shares ``s`` (T×n) and, with ``want_sp``, the production at the start
    of each round (T×rounds).
    """
    k = np.asarray(k, dtype=float)
    T = len(P)
    s_out = np.empty(D.shape, dtype=np.int64)
    sp_out = np.empty((T, rounds), dtype=float) if want_sp else None
    for a in range(0, T, CHUNK):
        b = min(a + CHUNK, T)
        rem = D[a:b].astype(np.int64)
        Pr = P[a:b].astype(np.int64)
        s = np.zeros_like(rem)
        sp = np.zeros((b - a, rounds), dtype=float)
        for r in range(rounds):
            sp[:, r] = Pr
            q = np.minimum(rem, np.floor(Pr[:, None] * k[None, :] + 1e-9).astype(np.int64))
            s += q
            rem -= q
            Pr = Pr - q.sum(axis=1)
        s_out[a:b] = s
        if want_sp:
            sp_out[a:b] = sp
    return (s_out, sp_out) if want_sp else s_out


def replay_match(P, D, S, k, rounds: int = 5) -> float:
    """Fraction of intervals where the replay with keys ``k`` equals the report."""
    if not len(P):
        return 0.0
    ok = 0
    for a in range(0, len(P), CHUNK):
        b = min(a + CHUNK, len(P))
        ok += int((replay_edc(P[a:b], D[a:b], k, rounds) == S[a:b]).all(axis=1).sum())
    return ok / len(P)


# ---------------------------------------------------------------------------
# Exact per-interval bounds
# ---------------------------------------------------------------------------


def exact_bounds(s: np.ndarray, pr: np.ndarray, iters: int = 40) -> tuple[np.ndarray, np.ndarray]:
    """For each interval, the k range with sum_r floor(k * P_r) == s exactly.

    ``pr`` is (m, R) production at the start of each round. The sum is a monotone
    step function of k, so both ends are found by bisection (vectorised):
    lo = min k with sum >= s, hi = min k with sum >= s + 1. About R times tighter
    than the plain bounds s/SP <= k < (s+R)/SP.
    """
    sp = pr.sum(axis=1)

    def first_k_reaching(target: np.ndarray) -> np.ndarray:
        rounds = pr.shape[1]
        a = np.maximum(target - rounds, 0) / np.maximum(sp, 1)   # sum at a <= target - R
        a = np.where(target > 0, a, 0.0)
        b = (target + rounds) / np.maximum(sp, 1) + 1e-12         # sum at b >= target
        for _ in range(iters):
            mid = (a + b) / 2
            reach = np.floor(pr * mid[:, None] + 1e-9).sum(axis=1) >= target
            b = np.where(reach, mid, b)
            a = np.where(reach, a, mid)
        return b

    s = s.astype(float)
    return first_k_reaching(s), first_k_reaching(s + 1)


# ---------------------------------------------------------------------------
# Choosing one key from interval bounds
# ---------------------------------------------------------------------------


def plateau(lo: np.ndarray, hi: np.ndarray) -> tuple[float, float]:
    """Range of keys (0.01 % grid) consistent with the most intervals: every value in
    it explains the report equally well, so the data cannot tell them apart."""
    lo_s, hi_s = np.sort(lo), np.sort(hi)
    a = max(FINE, float(lo_s[0]))
    b = min(1.0, float(np.max(np.minimum(hi, 1.0))))
    grid = np.arange(np.floor(a / FINE), np.ceil(b / FINE) + 1) * FINE
    grid = grid[(grid > 0) & (grid <= 1.0 + 1e-12)]
    if not len(grid):
        return (0.0, 1.0)
    cov = np.searchsorted(lo_s, grid, side="right") - np.searchsorted(hi_s, grid, side="right")
    idx = np.flatnonzero(cov == cov.max())
    return float(round(grid[idx[0]], 6)), float(round(grid[idx[-1]], 6))


def _best_fine(lo: np.ndarray, hi: np.ndarray) -> tuple[float, int]:
    """Value on the 0.01 % grid covered by the most intervals [lo, hi)."""
    lo_s, hi_s = np.sort(lo), np.sort(hi)
    a = max(FINE, float(lo_s[0]))
    b = min(1.0, float(np.max(np.minimum(hi, 1.0))))
    grid = np.arange(np.floor(a / FINE), np.ceil(b / FINE) + 1) * FINE
    grid = grid[(grid > 0) & (grid <= 1.0 + 1e-12)]
    if not len(grid):
        return float(np.clip(np.median(lo), FINE, 1.0)), 0
    cov = np.searchsorted(lo_s, grid, side="right") - np.searchsorted(hi_s, grid, side="right")
    top = int(cov.max())
    idx = np.flatnonzero(cov == top)
    if grid[idx[-1]] >= 1.0 - 1e-9:
        # open-ended plateau (only lower bounds, e.g. a member almost always fully
        # covered): take the smallest consistent key
        j = idx[0]
    else:
        j = idx[len(idx) // 2]                 # middle of the best plateau
    return float(round(grid[j], 6)), top


def _choose_key(lo: np.ndarray, hi: np.ndarray) -> tuple[float, int]:
    """Pick one key from per-interval bounds [lo, hi).

    x* = best-covered value on the 0.01 % grid. A rounder value v next to x*
    (whole %, then 0.5 %, 0.1 %, 0.05 %) replaces it only when the intervals that
    separate the two do not clearly favour x*: with A = intervals holding x* but
    not v and B = intervals holding v but not x*, v is taken when |B| >= |A| / 2.
    A wrong round value has almost no B; the true round value, beaten by x* only
    through a few systematic report deviations, keeps a large B.
    """
    x, top = _best_fine(lo, hi)
    in_x = (lo <= x) & (x < hi)
    for step in SNAP_STEPS:
        near = {round(np.floor(x / step) * step, 6), round(np.ceil(x / step) * step, 6)}
        for v in sorted(near, key=lambda u: abs(u - x)):
            if v <= 0 or v > 1 or abs(v - x) < 1e-12:
                continue
            in_v = (lo <= v) & (v < hi)
            a_cnt = int((in_x & ~in_v).sum())
            b_cnt = int((in_v & ~in_x).sum())
            if a_cnt == 0 or b_cnt >= 0.5 * a_cnt:
                return float(v), int(in_v.sum())
    return x, top


def _neighbours(k: float) -> list[float]:
    out = []
    for step in (0.02,) + SNAP_STEPS + (FINE,):
        out += [round(k - step, 6), round(k + step, 6)]
    return [v for v in out if 0 < v <= 1]


# ---------------------------------------------------------------------------
# Fits
# ---------------------------------------------------------------------------


def _status(D_col: np.ndarray) -> str:
    return "no_data" if not (D_col > 0).any() else "always_covered"


def _covering_key(d: np.ndarray, pr: np.ndarray) -> float:
    """Smallest key (0.01 % grid) that fully covers demand d in every interval,
    given the production at the start of each round ``pr`` (m×R)."""
    m = d > 0
    if not m.any():
        return 0.0
    need = exact_bounds(d[m].astype(float), pr[m])[0]   # min k with sum >= d
    return float(min(1.0, np.ceil(need.max() / FINE - 1e-6) * FINE))


def _fit_one_round(P, D, S, progress: ProgressFn, p0: float, p1: float):
    """One round: member i gets min(D_i, floor(k_i P)), so each key is fitted on its
    own column. Per interval with P > 0: not fully covered -> s/P <= k < (s+1)/P;
    fully covered (s = D > 0) -> k >= D/P."""
    n = D.shape[1]
    k = np.zeros(n)
    status, support = ["ok"] * n, [0] * n
    ranges: list[tuple[float, float]] = [(0.0, 1.0)] * n
    rows = P > 0
    Pr = P[rows].astype(float)
    for i in range(n):
        d, s = D[rows, i], S[rows, i]
        uns = (s < d) & (d > 0)
        sat = (s == d) & (d > 0)
        if not uns.any():
            status[i] = _status(D[:, i])
            if status[i] == "always_covered":
                k[i] = _covering_key(d, Pr[:, None])
                ranges[i] = (k[i], 1.0)
        else:
            lo = np.concatenate([s[uns] / Pr[uns], d[sat] / Pr[sat]])
            hi = np.concatenate([(s[uns] + 1) / Pr[uns], np.full(int(sat.sum()), 2.0)])
            k[i], support[i] = _choose_key(lo, hi)
            ranges[i] = plateau(lo, hi)
        if i % 8 == 0 or i == n - 1:
            progress("fit", p0 + (p1 - p0) * (i + 1) / n)
    return k, status, support, ranges


def _rank1_start(P, D, S, rounds: int, iters: int = 60) -> np.ndarray:
    """Starting keys that do not need P_r: two members short in the same interval
    both get their key's share of the same round productions, so s_it ~ k_i * SP_t
    (a rank-1 matrix with the fully covered cells missing). Alternating least
    squares gives k up to one scale; the scale is picked by the replay."""
    info = (P > 0) & ((S < D) & (D > 0)).any(axis=1)
    Pi, Di, Si = P[info], D[info], S[info]
    W = ((Si < Di) & (Di > 0)).astype(float)
    Y = Si + rounds / 2.0                      # average loss to the floors
    k = np.ones(Si.shape[1])
    for _ in range(iters):
        sp = (W * Y * k).sum(1) / np.maximum((W * k * k).sum(1), 1e-12)
        k = (W * Y * sp[:, None]).sum(0) / np.maximum((W * sp[:, None] ** 2).sum(0), 1e-12)
        k /= max(k.sum(), 1e-12)
    best, best_c = -1, 0.9
    for c in np.linspace(0.3, 1.0, 71):
        sc = int((replay_edc(Pi, Di, c * k, rounds) == Si).sum())
        if sc > best:
            best, best_c = sc, c
    return best_c * k


def _fit_rounds_multi(P, D, S, rounds: int, progress: ProgressFn, p0: float, p1: float):
    """Several starts (uniform, rank-1); keep the fit that reproduces most intervals."""
    mid = p0 + 0.5 * (p1 - p0)
    runs = [_fit_rounds(P, D, S, rounds, progress, p0, mid)]
    runs.append(_fit_rounds(P, D, S, rounds, progress, mid, p1,
                            k0=_rank1_start(P, D, S, rounds)))
    return max(runs, key=lambda r: replay_match(P, D, S, r[0], rounds))


def _fit_rounds(P, D, S, rounds: int, progress: ProgressFn, p0: float, p1: float,
                max_iter: int = 30, k0: np.ndarray | None = None):
    """Several rounds: iterate the bounds to a fixed point, then settle each member
    by the replay (a lower key leaves more for later rounds, which can "confirm"
    it, so more than one round key may be self-consistent)."""
    n = D.shape[1]
    info = (P > 0) & ((S < D) & (D > 0)).any(axis=1)
    Pi, Di, Si = P[info], D[info], S[info]
    unsat = (Si < Di) & (Di > 0)
    k = np.full(n, 0.9 / n) if k0 is None else np.asarray(k0, dtype=float).copy()
    status, support = ["ok"] * n, [0] * n
    p_mid = p0 + 0.5 * (p1 - p0)

    def bounds(i, pr):
        m = unsat[:, i] & (pr[:, 0] > 0)
        return exact_bounds(Si[m, i], pr[m])

    # Fixed point without rounding: a key stays while it is still in the best-covered
    # range (rounding here would shift P_r for everybody and make the iteration drift).
    for it in range(max_iter):
        _, sp = replay_edc(Pi, Di, k, rounds, want_sp=True)
        new = k.copy()
        for i in range(n):
            if not (unsat[:, i] & (sp[:, 0] > 0)).any():
                status[i] = _status(D[:, i])
                continue
            lo, hi = bounds(i, sp)
            a, b = plateau(lo, hi)
            if not (a - 1e-9 <= k[i] <= b + 1e-9):
                new[i], support[i] = _best_fine(lo, hi)
        progress("fit", p0 + (p_mid - p0) * (it + 1) / max_iter)
        done = np.allclose(new, k, atol=1e-9)
        k = new
        if done:
            break

    # members that are never short: smallest key that keeps them fully covered
    _, sp = replay_edc(Pi, Di, k, rounds, want_sp=True)
    for i in range(n):
        if status[i] == "always_covered":
            k[i] = _covering_key(Di[:, i], sp)

    def score(kk) -> int:
        # matching (interval, member) cells: unlike whole-row matches this still
        # rewards fixing one member while others are off
        return int((replay_edc(Pi, Di, kk, rounds) == Si).sum())

    base = score(k)

    def joint_moves(k: np.ndarray, base: int):
        """Moves of all keys together, which single-member steps cannot reach:
        the whole vector rounded (1 %, 0.5 %, 0.1 %) and rescaled (±3 %). A fixed
        point can be a scaled copy of the true keys (all slightly high, one low)."""
        best_k, best = k, base
        cands = []
        for step in (0.01, 0.005, 0.001):
            r = np.round(k / step) * step
            cands.append(np.where(r > 0, r, k))
        for f in np.linspace(0.97, 1.03, 61):
            cands.append(np.round(k * f / FINE) * FINE)
            for step in (0.01, 0.005):
                r = np.round(k * f / step) * step
                cands.append(np.where(r > 0, r, k))
        for kk in cands:
            if kk.sum() > 1.0001 or np.allclose(kk, best_k):
                continue
            sc = score(kk)
            if sc > best:
                best_k, best = kk, sc
        return best_k, best

    k, base = joint_moves(k, base)
    # prefer round keys where the data allow it (never at the cost of matches)
    _, sp = replay_edc(Pi, Di, k, rounds, want_sp=True)
    for i in range(n):
        if status[i] != "ok":
            continue
        v, support[i] = _choose_key(*bounds(i, sp))
        if abs(v - k[i]) > 1e-12:
            kk = k.copy()
            kk[i] = v
            sc = score(kk)
            if sc >= base:
                base, k = sc, kk
    for sweep in range(3):
        changed = False
        _, sp = replay_edc(Pi, Di, k, rounds, want_sp=True)
        for i in range(n):
            if status[i] != "ok":
                continue
            own = _choose_key(*bounds(i, sp))[0]
            near = [round(k[i] + d, 6) for d in (-0.01, 0.01, -0.005, 0.005, -0.001, 0.001)]
            for v in dict.fromkeys(c for c in [own] + near if 0 < c <= 1):
                if abs(v - k[i]) < 1e-12:
                    continue
                kk = k.copy()
                kk[i] = v
                sc = score(kk)
                if sc > base:
                    base, k, changed = sc, kk, True
            progress("fit", p_mid + (p1 - p_mid) * ((sweep + (i + 1) / n) / 3))
        k2, base2 = joint_moves(k, base)
        if base2 > base:
            k, base, changed = k2, base2, True
        if not changed:
            break
    _, sp = replay_edc(Pi, Di, k, rounds, want_sp=True)
    ranges = [plateau(*bounds(i, sp)) if status[i] == "ok" else (0.0, 1.0) for i in range(n)]
    return k, status, support, ranges


@dataclass
class KeyFit:
    keys: list[float]                                  # fractions (0.1 = 10 %)
    rounds: int                                        # EDC rounds that fit best
    match: float                                       # intervals reproduced exactly
    seconds: float
    status: list[str] = field(default_factory=list)    # ok / no_data / always_covered
    support: list[int] = field(default_factory=list)   # intervals consistent with the key
    tried: dict = field(default_factory=dict)          # rounds -> match
    ranges: list = field(default_factory=list)         # (lo, hi) equally consistent keys


def estimate_keys(P: np.ndarray, D: np.ndarray, S: np.ndarray,
                  rounds: int | None = None, progress: ProgressFn = _noop) -> KeyFit:
    """Fit keys for 1 and (groups up to 100) 5 EDC rounds; keep the better fit."""
    t0 = time.perf_counter()
    n = D.shape[1]
    if rounds:
        options = [rounds]
    else:
        options = [1, 5] if n <= EDC_MAX_5_ROUNDS else [1]
    # share of the progress bar: the 5-round fit costs far more than the 1-round one
    weights = {1: 1.0, 5: 4.0}
    total = sum(weights.get(r, 4.0) for r in options)
    best, tried, pos = None, {}, 0.0
    for r in options:
        w = weights.get(r, 4.0) / total
        fit = _fit_one_round if r == 1 else _fit_rounds_multi
        if r == 1:
            k, status, support, ranges = fit(P, D, S, progress, pos, pos + w)
        else:
            k, status, support, ranges = fit(P, D, S, r, progress, pos, pos + w)
        pos += w
        match = replay_match(P, D, S, k, r)
        tried[r] = match
        if best is None or match > best[3]:
            best = (k, status, support, match, r, ranges)
    k, status, support, match, r, ranges = best
    # members without any consumption data: the median key (it cannot matter here)
    known = [k[i] for i in range(n) if status[i] == "ok"]
    fill = float(np.median(known)) if known else 1.0 / max(n, 1)
    k = [fill if status[i] == "no_data" else float(k[i]) for i in range(n)]
    progress("fit", 1.0)
    return KeyFit(keys=k, rounds=r, match=match, seconds=time.perf_counter() - t0,
                  status=status, support=support, tried=tried, ranges=ranges)
