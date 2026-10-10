"""Billing of shared electricity by the Shapley value (one producer).

The group's benefit from sharing in a 15-min interval is what the consumers save on their
supplier's price minus the feed-in revenue the producer gives up. The *benchmark* game
values a coalition S by the best it could do with the producer's surplus P: it goes first
to the consumers with the highest supplier price,

    v(S) = 1[producer in S] · Σ_k Δλ_k · min(P, D_k(S)),

where λ_0 = feed-in price < λ_1 < … are the distinct supplier prices above it, Δλ_k =
λ_k − λ_{k-1}, and D_k(S) is the demand of the consumers in S whose price is at least λ_k
(price layer k). Shapley values add up, so every interval and every layer is a game
``1[producer] · min(P, D(S))``, and the results are summed.

Exact algorithm for one interval (hundredths of kWh, like EDC data):

* P = 0: nothing to share. A layer with Σ d ≤ P covers everyone: φ_j = d_j / 2.
* otherwise, with Owen's multilinear extension (every other player joins with
  probability u):  φ_j = ∫_0^1 u · E[min(d_j, P − X_{-j}(u))^+] du.
  The integrand is a Bernstein polynomial of degree m with coefficients in [0, d_j], so
  Gauss–Legendre needs far fewer than m/2 nodes: :func:`nodes_needed` takes the smallest
  even count whose rigorous error bound (Bernstein ellipse) is below 1e-13 · d_j.
* One DP per node gives the distribution of X over the consumers sorted by price; every
  layer is a prefix of that order, so all layers come from the same DP. The node 1 − u is
  the mirror image of u, so only half the nodes need a DP.
* Leaving member j out needs no deconvolution of arrays: X_{-j} = X − B_j d_j turns
  E[h(X_{-j})] into a finite geometric series of E[h(X + c)], and h is piecewise linear,
  so each term is two lookups in G = running sum of the CDF of X. Summing G over the
  layers that contain j, weighted by Δλ_k, gives all layers with the same lookups.
* The producer gets the rest: φ_0 = v(N) − Σ φ_j.

Settlement: the benchmark's Shapley values are scaled to the benefit the group really got
from the report's sharing (``realized / maximum``), and each consumer pays the producer
``price · shared − its share``.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

ProgressFn = Callable[[str, float], None]

#: float elements per block of layer snapshots (layers × nodes × grid)
_BLOCK = 1_500_000
#: relative accuracy of the quadrature (rigorous bound, relative to d_j · Δλ)
REL_TOL = 1e-13


def _noop(_phase: str, _frac: float) -> None:
    pass


# ---------------------------------------------------------------------------
# Price layers and quadrature
# ---------------------------------------------------------------------------


def price_levels(prices, feed_in: float) -> np.ndarray:
    """Feed-in price followed by the distinct supplier prices above it."""
    p = np.asarray(prices, dtype=float)
    return np.concatenate([[float(feed_in)], np.unique(p[p > feed_in])])


_NODES: dict[int, tuple[np.ndarray, np.ndarray]] = {}
_NEEDED: dict[int, int] = {}


def nodes_needed(m: int, rel: float = REL_TOL) -> int:
    """Even number of Gauss–Legendre nodes that integrates u · B(u) on [0, 1] to ``rel``,
    B a Bernstein polynomial of degree m − 1 with coefficients in [0, 1].

    Error <= (32/15) · M · ρ^(-2K) / (ρ² − 1) for f analytic in the Bernstein ellipse
    E_ρ of [0, 1]; there |z| + |1 − z| = cosh s (ρ = e^s), so M <= cosh(s)^m. ``m // 2 + 1``
    nodes are exact for any polynomial of degree m, so that is the upper limit.
    """
    if m in _NEEDED:
        return _NEEDED[m]
    exact = m // 2 + 1
    exact += exact % 2
    s = np.linspace(1e-3, 6.0, 4000)
    base = math.log(32 / 15) + m * np.log(np.cosh(s)) - np.log(np.expm1(2 * s))
    target = math.log(rel)
    K = 2
    while K < exact and float(np.min(base - 2 * K * s)) > target:
        K += 2
    _NEEDED[m] = min(K, exact)
    return _NEEDED[m]


def _gauss(K: int) -> tuple[np.ndarray, np.ndarray]:
    if K not in _NODES:
        x, w = np.polynomial.legendre.leggauss(K)
        _NODES[K] = ((x + 1) / 2, w / 2)        # ascending, symmetric: u[K-1-t] = 1 - u[t]
    return _NODES[K]


# ---------------------------------------------------------------------------
# One interval
# ---------------------------------------------------------------------------


def _scarce(P: int, d: np.ndarray, lvl: np.ndarray, sizes: list[int],
            dl: np.ndarray) -> np.ndarray:
    """Weighted Shapley values Σ_k Δλ_k φ_j^k over the *scarce* layers (Σ d > P).

    ``d`` (> 0) are the demands in DP order (price descending), ``lvl[j]`` the number
    of scarce layers containing consumer j (>= 1), ``sizes[k]`` the prefix length of
    scarce layer k (k = 0 is the largest set) and ``dl[k]`` its Δλ.
    """
    m = len(d)
    L = len(sizes)
    Dk = [int(d[:n].sum()) for n in sizes]          # descending
    Dt = Dk[0]
    Bn = Dt + 1
    K = nodes_needed(m)
    u_all, w_all = _gauss(K)
    h = K // 2
    slope = np.cumsum(dl)                           # Σ Δλ of the layers up to k
    row = lvl - 1                                   # cumulative table each member uses
    dcol = d[:, None]
    dmin = int(d.min())
    phi = np.zeros(m)
    # boundaries of the scarce layers in DP order: smallest set first
    stops: dict[int, list[int]] = {}
    for k, n_k in enumerate(sizes):             # layers can share a prefix (zero demands)
        stops.setdefault(n_k, []).append(k)
    nb = max(1, min(h, _BLOCK // max(1, L * Bn)))
    for b0 in range(0, h, nb):
        q = u_all[b0:b0 + nb, None]                 # nodes < 0.5
        bsz = len(q)
        snap = np.zeros((L, bsz, Bn))
        X = np.zeros((bsz, Bn)); X[:, 0] = 1.0
        for j in range(m):
            dj = int(d[j])
            tmp = q * X[:, :Bn - dj]
            X *= 1 - q
            X[:, dj:] += tmp
            for k in stops.get(j + 1, ()):
                snap[k] = X
        # mirror: the node 1 - q of layer k is X_k reflected within 0..D_k
        mirror = np.zeros_like(snap)
        for k in range(L):
            mirror[k, :, :Dk[k] + 1] = snap[k, :, Dk[k]::-1]
        Wp = np.zeros((L, bsz, Bn + 1))                             # index t+1, G(-1) = 0
        for part, nodes in ((snap, range(b0, b0 + bsz)),
                            (mirror, range(K - 1 - b0, K - 1 - b0 - bsz, -1))):
            # W_k = Σ_{k'<=k} Δλ_k' G_k', G = running sum of the CDF; G is linear in the
            # distribution, so weight and sum the layers first, then two running sums
            part *= dl[:, None, None]
            np.cumsum(part, axis=0, out=part)
            np.cumsum(part, axis=2, out=Wp[:, :, 1:])
            np.cumsum(Wp[:, :, 1:], axis=2, out=Wp[:, :, 1:])      # linear past D_k
            for i, t in enumerate(nodes):
                ut = u_all[t]
                Wt = Wp[:, i, :]
                if ut < 0.5:     # R = 1/(1-u) Σ (-r)^k X(· - k d): lower indices only
                    ratio, scale = ut / (1 - ut), 1 / (1 - ut)
                    cap = -(-P // dmin)                             # k d >= P: term is 0
                    k = np.arange(min(cap, int(math.log(1e-17) / math.log(ratio)) + 1))
                    c = k[None, :] * dcol
                else:            # R = 1/u Σ (-s)^k X(· + (k+1) d)
                    ratio, scale = (1 - ut) / ut, 1 / ut
                    cap = max(1, -(-(Dt - P) // dmin) + 1)          # beyond: term is d·slope
                    k = np.arange(min(cap, int(math.log(1e-17) / math.log(ratio)) + 1))
                    c = -(k + 1)[None, :] * dcol
                coef = scale * (-ratio) ** k
                a1 = P - 1 - c
                a2 = a1 - dcol
                rr = row[:, None]
                g1 = Wt[rr, np.clip(a1, -1, Dt) + 1] + np.maximum(a1 - Dt, 0) * slope[rr]
                g2 = Wt[rr, np.clip(a2, -1, Dt) + 1] + np.maximum(a2 - Dt, 0) * slope[rr]
                val = (g1 - g2) @ coef
                if ut >= 0.5:    # closed-form tail of the series (every term = d · slope)
                    val += d * slope[row] * scale * (-ratio) ** len(k) / (1 + ratio)
                phi += w_all[t] * ut * val
    return phi


def shapley_interval(P: int, d: np.ndarray, level: np.ndarray, dl: np.ndarray):
    """Weighted Shapley values of one interval.

    ``d[n]`` demands (hundredths of kWh), ``level[n]`` the number of price layers that
    contain each consumer (0 = price not above the feed-in price), ``dl[L]`` the Δλ of
    the layers (Kč/kWh). Returns (φ consumers, φ producer, v(N)) in Kč · hundredths of
    kWh, and whether the exact quadrature was needed.
    """
    n = len(d)
    phi = np.zeros(n)
    if P <= 0 or len(dl) == 0:
        return phi, 0.0, 0.0, False
    d = np.asarray(d, dtype=np.int64)
    L = len(dl)
    # demand of every layer: consumers with level >= k + 1
    dem = np.array([int(d[level >= k + 1].sum()) for k in range(L)])
    vmax = float((dl * np.minimum(P, dem)).sum())
    scarce = dem > P                      # a prefix of the layers (dem decreases with k)
    # covered layers: everybody in them gets d / 2
    cov_w = np.concatenate([[0.0], np.cumsum(np.where(scarce, 0.0, dl))])
    phi += d * cov_w[level] / 2
    ks = int(scarce.sum())
    if ks:
        act = np.flatnonzero((d > 0) & (level >= 1))
        order = act[np.argsort(-level[act], kind="stable")]       # price descending
        lv = np.minimum(level[order], ks)
        sizes = [int((lv >= k + 1).sum()) for k in range(ks)]     # layer k (0 = largest)
        phi[order] += _scarce(int(P), d[order], lv, sizes, dl[:ks])
    return phi, vmax - float(phi.sum()), vmax, bool(ks)


# ---------------------------------------------------------------------------
# Whole report
# ---------------------------------------------------------------------------


@dataclass
class ShapleyTotals:
    """Shapley values of the benchmark game in Kč, summed over the report."""

    prices: list[float]
    feed_in: float
    consumers: np.ndarray          # Kč per consumer
    producer: float                # Kč
    maximum: float                 # Kč: v(N) summed (best possible sharing)
    n_intervals: int = 0
    n_night: int = 0               # P = 0
    n_covered: int = 0             # production covers every layer: closed form
    n_scarce: int = 0              # exact quadrature
    seconds: float = 0.0           # CPU time


def compute_shapley(P: np.ndarray, D: np.ndarray, prices, feed_in: float,
                    progress: ProgressFn = _noop) -> ShapleyTotals:
    """Shapley values of the benchmark for every interval (``P[T]``, ``D[T, n]`` in
    hundredths of kWh; ``prices[n]`` and ``feed_in`` in Kč/kWh)."""
    c0 = time.process_time()
    P = np.asarray(P, dtype=np.int64)
    D = np.asarray(D, dtype=np.int64)
    T, n = D.shape
    p = np.asarray(prices, dtype=float)
    levels = price_levels(p, feed_in)
    dl = np.diff(levels)
    level = np.searchsorted(levels[1:], p, side="right")   # layers containing each consumer
    res = ShapleyTotals(prices=list(map(float, p)), feed_in=float(feed_in),
                        consumers=np.zeros(n), producer=0.0, maximum=0.0, n_intervals=T)
    if len(dl) == 0:
        res.n_night = int((P <= 0).sum())
        progress("bill", 1.0)
        return res
    gain = p - feed_in                                      # Kč/kWh per consumer
    in_any = level >= 1
    dem1 = D[:, in_any].sum(axis=1)                         # demand of the largest layer
    night = P <= 0
    covered = ~night & (dem1 <= P)
    res.n_night, res.n_covered = int(night.sum()), int(covered.sum())
    # closed form for all covered intervals at once: φ_j = (p_j − f) d_j / 2
    Dc = D[covered].astype(float)
    res.consumers += (Dc * np.where(in_any, gain, 0.0)).sum(axis=0) / 2
    res.maximum += float((Dc * np.where(in_any, gain, 0.0)).sum())
    scarce = np.flatnonzero(~night & ~covered)
    res.n_scarce = len(scarce)
    # progress by the work that costs: grid length × active members
    work = (np.minimum(D[scarce][:, in_any].sum(axis=1), 10**9) + 1) * \
        np.maximum((D[scarce][:, in_any] > 0).sum(axis=1), 1)
    total = float(work.sum()) or 1.0
    done = last = 0.0
    for i, t in enumerate(scarce):
        phi, phi0, vmax, _ = shapley_interval(int(P[t]), D[t], level, dl)
        res.consumers += phi
        res.maximum += vmax
        done += work[i]
        if done - last >= 0.01 * total:
            last = done
            progress("bill", done / total)
    res.consumers /= 100
    res.maximum /= 100
    res.producer = res.maximum - float(res.consumers.sum())
    res.seconds = time.process_time() - c0
    progress("bill", 1.0)
    return res


# ---------------------------------------------------------------------------
# Settlement in crowns
# ---------------------------------------------------------------------------


@dataclass
class Billing:
    prices: np.ndarray             # Kč/kWh per consumer (supplier price)
    feed_in: float                 # Kč/kWh (producer's feed-in price)
    shared: np.ndarray             # kWh per consumer (report)
    saving: np.ndarray             # Kč: price · shared (what the consumer did not buy)
    share: np.ndarray              # Kč: fair share of the benefit (scaled Shapley value)
    payment: np.ndarray            # Kč the consumer pays the producer (whole haléř)
    producer_share: float          # Kč: producer's benefit = income − feed-in value
    producer_income: float         # Kč: Σ payments
    feed_in_value: float           # Kč: what the shared energy would have earned as feed-in
    realized: float                # Kč: benefit of the report's sharing
    maximum: float                 # Kč: benefit of the best possible sharing
    shapley: np.ndarray            # Kč: unscaled Shapley values of the benchmark

    @property
    def efficiency(self) -> float:
        return self.realized / self.maximum if self.maximum > 0 else 0.0

    @property
    def unit_price(self) -> np.ndarray:
        """Kč/kWh each consumer effectively pays for shared electricity."""
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(self.shared > 0, self.payment / self.shared, np.nan)


def settle(res: ShapleyTotals, shared_kwh) -> Billing:
    """Crowns: Shapley values scaled to the realized benefit, payments in haléř."""
    p = np.asarray(res.prices, dtype=float)
    f = res.feed_in
    shared = np.asarray(shared_kwh, dtype=float)
    realized = float(((p - f) * shared).sum())
    scale = realized / res.maximum if res.maximum > 0 else 0.0
    share = res.consumers * scale
    saving = p * shared
    payment = np.round(saving - share, 2)
    income = float(payment.sum())
    fiv = f * float(shared.sum())
    return Billing(prices=p, feed_in=f, shared=shared, saving=saving, share=share,
                   payment=payment, producer_share=income - fiv, producer_income=income,
                   feed_in_value=fiv, realized=realized, maximum=res.maximum,
                   shapley=res.consumers.copy())
