"""Billing of shared electricity by the Shapley value, for one or more producers.

The group's benefit from sharing in a 15-min interval is what the consumers save on their
supplier's price minus the feed-in revenue the producers give up. The *benchmark* game
values a coalition S by the best it could do with its producers' surplus, shared as a
pool (any producer can supply any consumer): the cheapest production goes first to the
consumers with the highest supplier price. With the distinct prices of everybody (feed-in
and supplier) sorted, λ_0 < λ_1 < …, that is

    v(S) = Σ_k Δλ_k · min(G_k(S), D_k(S)),      Δλ_k = λ_{k+1} − λ_k,

where layer k holds the producers with feed-in price f ≤ λ_k (surplus G_k) and the
consumers with supplier price p ≥ λ_{k+1} (demand D_k). Shapley values add up, so every
interval and every layer is a game ``min(G(S), D(S))``, and the results are summed.

Exact algorithm for one interval (hundredths of kWh, like EDC data):

* Closed forms: a layer with one producer whose surplus covers the layer's demand gives
  every consumer d / 2 and the producer the rest (D / 2); a layer with one consumer whose
  demand takes all the layer's surplus gives every producer g / 2.
* Otherwise, write min(G, D) = D − (D − G)^+ and let Z = D(S) − G(S) (the balance:
  consumers +d, producers −g). With Owen's multilinear extension (every other player
  joins with probability u) and H(a) = Σ_{s≤a} P(Z ≤ s),

      consumer j:  φ_j = ∫_0^1 H_{-j}(−1) − H_{-j}(−1 − d_j) du,
      producer i:  φ_i = g_i − ∫_0^1 H_{-i}(g_i − 1) − H_{-i}(−1) du.

  The integrand is a Bernstein polynomial of degree < m (players) with coefficients in
  [0, d_j] (or [0, g_i]), so Gauss–Legendre needs far fewer than m/2 nodes:
  :func:`nodes_needed` takes the smallest even count whose rigorous error bound
  (Bernstein ellipse) is below 1e-13 of the player's weight.
* One DP per node gives the distribution of Z: the consumers sorted by price (every layer
  takes a prefix of them, snapshots), then each layer's producers. The node 1 − u is the
  mirror image of u (Z ↦ D − G − Z), so only half the nodes need a DP.
* Leaving player i out needs no deconvolution of arrays: Z_{-i} = Z − B_i z_i turns
  H_{-i} into a finite geometric series of H shifted by multiples of z_i, each term a
  lookup. A consumer's layers are the first ones and a producer's the last ones, so
  running sums of Δλ_k · H_k over the layers give all layers with the same lookups.

Settlement: the benchmark's Shapley values are scaled to the benefit the group really got
from the report's sharing (``realized / maximum``). Each consumer pays the pool
``price · shared − its share``; each producer gets ``feed-in price · its shared energy +
its share`` from the pool.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from functools import cached_property
from typing import Callable

import numpy as np
import pandas as pd

ProgressFn = Callable[[str, float], None]

#: prefix of the producers' columns in :attr:`BillResult.per_interval`
PRODUCER = "__producer__|"

#: float elements per block of layer snapshots (layers × nodes × grid)
_BLOCK = 1_000_000
#: relative accuracy of the quadrature (rigorous bound, relative to the weight · Δλ)
REL_TOL = 1e-13


def producer_col(ean: str) -> str:
    """Column of a producer in :attr:`BillResult.per_interval`."""
    return f"{PRODUCER}{ean}"


def is_producer_col(col: str) -> bool:
    return isinstance(col, str) and col.startswith(PRODUCER)


def _noop(_phase: str, _frac: float) -> None:
    pass


# ---------------------------------------------------------------------------
# Price layers and quadrature
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Layers:
    """The price layers where sharing pays: consumer j is in layers ``k < top[j]``,
    producer i in layers ``k >= first[i]``; ``dl[k]`` is the layer's Δλ (Kč/kWh)."""

    dl: np.ndarray
    top: np.ndarray
    first: np.ndarray

    @classmethod
    def build(cls, prices, feed_ins) -> "Layers":
        p = np.asarray(prices, dtype=float)
        f = np.asarray(feed_ins, dtype=float)
        levels = np.unique(np.concatenate([p, f]))
        cidx = np.searchsorted(levels, p)          # p_j = levels[cidx]
        fidx = np.searchsorted(levels, f)
        lo = int(fidx.min()) if len(f) else 0
        hi = int(cidx.max()) if len(p) else 0
        L = max(hi - lo, 0)
        return cls(dl=np.diff(levels)[lo:lo + L], top=np.clip(cidx - lo, 0, L),
                   first=np.clip(fidx - lo, 0, L))

    @cached_property
    def consumer_in(self) -> np.ndarray:
        """Membership (n, L) of the consumers in the layers."""
        return np.arange(len(self.dl))[None, :] < self.top[:, None]

    @cached_property
    def producer_in(self) -> np.ndarray:
        """Membership (np, L) of the producers in the layers."""
        return np.arange(len(self.dl))[None, :] >= self.first[:, None]


_NODES: dict[int, tuple[np.ndarray, np.ndarray]] = {}
_NEEDED: dict[int, int] = {}


def nodes_needed(m: int, rel: float = REL_TOL) -> int:
    """Even number of Gauss–Legendre nodes that integrates a Bernstein polynomial of
    degree < m with coefficients in [0, 1] on [0, 1] to ``rel``.

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


def _leave_one_out(W: np.ndarray, slope: np.ndarray, rows: np.ndarray, a1: np.ndarray,
                   z: np.ndarray, u: float, off: int, top: int) -> np.ndarray:
    """H_{-i}(a1) − H_{-i}(a1 − |z_i|) for every player i (z > 0 consumers, z < 0
    producers), weighted by the layers of ``W[rows[i]]`` (running sums of Δλ · H over
    the grid, index a + off + 1; slope ``slope[rows[i]]`` above the grid's top ``top``).

    Z = Z_{-i} + B z with B ~ Bernoulli(u) gives H_{-i}(a) = 1/(1−u) Σ (−u/(1−u))^k
    H(a − k z) for u < 1/2 and 1/u Σ (−(1−u)/u)^k H(a + (k+1) z) for u > 1/2. Shifts
    below the grid give 0; above it every term is |z| · slope (closed-form tail).
    """
    w = np.abs(z)
    if u < 0.5:
        ratio, scale, k0, step = u / (1 - u), 1 / (1 - u), 0, -z
    else:
        ratio, scale, k0, step = (1 - u) / u, 1 / u, 1, z
    up = step > 0
    # up: terms from (k + k0) w >= top − a2 on are all w · slope; down: from
    # (k + k0) w > a1 + off on they are 0
    caps = np.where(up, -(-(top - (a1 - w)) // w) - k0, (a1 + off) // w - k0 + 1)
    K = max(0, min(int(caps.max()), int(math.log(1e-17) / math.log(ratio)) + 1))
    k = np.arange(K)
    A1 = a1[:, None] + (k + k0)[None, :] * step[:, None]
    A2 = A1 - w[:, None]
    width = W.shape[1]
    flat = W.ravel()
    base = (rows * width)[:, None]
    sl = slope[rows][:, None]

    def H(A):
        idx = A + (off + 1)
        np.clip(idx, 0, width - 1, out=idx)
        idx += base
        return flat.take(idx) + np.maximum(A - top, 0) * sl

    val = (H(A1) - H(A2)) @ (scale * (-ratio) ** k)
    return val + up * w * slope[rows] * (scale * (-ratio) ** K / (1 + ratio))


def _general(g: np.ndarray, d: np.ndarray, starts: np.ndarray, counts: np.ndarray,
             dl: np.ndarray, G: np.ndarray, D: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Weighted Shapley values over the layers without a closed form.

    ``d`` (> 0) consumer demands sorted so that ``counts`` (number of these layers each
    consumer is in: the first ``counts[j]``) descends; ``g`` (> 0) producer surpluses
    sorted so that ``starts`` (first layer of each producer) ascends; ``dl``, ``G``, ``D``
    per layer. Returns (φ consumers, φ producers) in Kč · hundredths of kWh.
    """
    L = len(dl)
    mc, mp = len(d), len(g)
    off, top = int(G.max()), int(D.max())
    Bn = off + top + 1
    K = nodes_needed(mc + mp)
    u_all, w_all = _gauss(K)
    h = K // 2
    slope_pre = np.cumsum(dl)
    slope_suf = np.cumsum(dl[::-1])[::-1]
    n_cons = [int((counts > k).sum()) for k in range(L)]       # consumer prefix per layer
    n_prod = [int((starts <= k).sum()) for k in range(L)]      # producer prefix per layer
    stops: dict[int, list[int]] = {}
    for k, n_k in enumerate(n_cons):
        stops.setdefault(n_k, []).append(k)
    phi_c, phi_p = np.zeros(mc), np.zeros(mp)
    # one lookup table per node: the consumers' rows W_k, then a row per distinct first
    # layer of the producers
    starts_u, rows_p = np.unique(starts, return_inverse=True)
    slopes = np.concatenate([slope_pre, slope_suf[starts_u]])
    rows = np.concatenate([counts - 1, L + rows_p])
    a1 = np.concatenate([-np.ones(mc, dtype=np.int64), g - 1])
    z = np.concatenate([d, -g]).astype(np.int64)
    nb = max(1, min(h, _BLOCK // max(1, L * Bn)))
    for b0 in range(0, h, nb):
        q = u_all[b0:b0 + nb, None]                 # nodes < 0.5
        bsz = len(q)
        snap = np.zeros((L, bsz, Bn))
        X = np.zeros((bsz, Bn))
        X[:, off] = 1.0
        for j in range(mc):                         # consumers: Z += B d
            dj = int(d[j])
            tmp = q * X[:, :Bn - dj]
            X *= 1 - q
            X[:, dj:] += tmp
            for k in stops.get(j + 1, ()):
                snap[k] = X
        for k in range(L):                          # each layer's producers: Z −= B g
            Xk = snap[k]
            for i in range(n_prod[k]):
                gi = int(g[i])
                tmp = q * Xk[:, gi:]
                Xk *= 1 - q
                Xk[:, :Bn - gi] += tmp
        # mirror: the node 1 − u of layer k is Z_k reflected within −G_k..D_k
        mirror = np.zeros_like(snap)
        for k in range(L):
            lo, hi = off - int(G[k]), off + int(D[k])
            mirror[k, :, lo:hi + 1] = snap[k, :, lo:hi + 1][:, ::-1]
        W = np.zeros((L, bsz, Bn + 1))                  # index a + off + 1, H(−off−1) = 0
        for part, nodes in ((snap, range(b0, b0 + bsz)),
                            (mirror, range(K - 1 - b0, K - 1 - b0 - bsz, -1))):
            # W_k = Σ_{k'<=k} Δλ_k' H_k' (a consumer's layers are the first ones); H is
            # linear in the distribution, so weight and sum the layers first, then two
            # running sums over the grid
            part *= dl[:, None, None]
            np.cumsum(part, axis=0, out=part)
            np.cumsum(part, axis=2, out=W[:, :, 1:])
            np.cumsum(W[:, :, 1:], axis=2, out=W[:, :, 1:])
            # a producer's layers are the last ones: W_{L-1} − W_{s-1}, as extra rows
            Wall = np.concatenate([W, W[-1:] - W[starts_u - 1] * (starts_u > 0)[:, None, None]])
            for i, t in enumerate(nodes):
                val = _leave_one_out(Wall[:, i, :], slopes, rows, a1, z, u_all[t], off, top)
                phi_c += w_all[t] * val[:mc]
                phi_p -= w_all[t] * val[mc:]
    phi_p += g * slope_suf[starts]
    return phi_c, phi_p


def shapley_interval(g, d, layers: Layers):
    """Weighted Shapley values of one interval.

    ``g[np]`` surpluses of the producers and ``d[n]`` demands of the consumers
    (hundredths of kWh). Returns (φ consumers, φ producers, v(N)) in Kč · hundredths of
    kWh, and whether a layer needed the quadrature.
    """
    g = np.asarray(g, dtype=np.int64)
    d = np.asarray(d, dtype=np.int64)
    phi_c, phi_p = np.zeros(len(d)), np.zeros(len(g))
    dl = layers.dl
    if len(dl) == 0 or not (g > 0).any() or not (d > 0).any():
        return phi_c, phi_p, 0.0, False
    Cm = layers.consumer_in & (d > 0)[:, None]
    Fm = layers.producer_in & (g > 0)[:, None]
    D, G = d @ Cm, g @ Fm
    vmax = float((dl * np.minimum(G, D)).sum())
    live = (G > 0) & (D > 0)
    one_p = live & (Fm.sum(axis=0) == 1) & (G >= D)            # one producer covers it
    one_c = live & ~one_p & (Cm.sum(axis=0) == 1) & (D >= G)   # one consumer takes all
    hard = live & ~one_p & ~one_c
    phi_c += d * (Cm @ (dl * one_p)) / 2 + Cm @ (dl * one_c * G) / 2
    phi_p += Fm @ (dl * one_p * D) / 2 + g * (Fm @ (dl * one_c)) / 2
    if not hard.any():
        return phi_c, phi_p, vmax, False
    H = np.flatnonzero(hard)
    counts = Cm[:, H].sum(axis=1)                               # first layers of H
    firsts = np.where(Fm[:, H].any(axis=1), np.argmax(Fm[:, H], axis=1), len(H))
    cons = np.flatnonzero(counts > 0)
    cons = cons[np.argsort(-counts[cons], kind="stable")]
    prods = np.flatnonzero(firsts < len(H))
    prods = prods[np.argsort(firsts[prods], kind="stable")]
    pc, pp = _general(g[prods], d[cons], firsts[prods], counts[cons], dl[H], G[H], D[H])
    phi_c[cons] += pc
    phi_p[prods] += pp
    return phi_c, phi_p, vmax, True


# ---------------------------------------------------------------------------
# Whole report
# ---------------------------------------------------------------------------


@dataclass
class ShapleyTotals:
    """Shapley values of the benchmark game in Kč, summed over the report."""

    prices: list[float]
    feed_ins: list[float]
    consumers: np.ndarray          # Kč per consumer
    producers: np.ndarray          # Kč per producer
    maximum: float                 # Kč: v(N) summed (best possible sharing)
    n_intervals: int = 0
    n_night: int = 0               # nothing to share
    n_covered: int = 0             # closed form only
    n_scarce: int = 0              # exact quadrature
    seconds: float = 0.0           # CPU time
    #: per 15-min interval with something to share: row indices into the report, and
    #: the Shapley values in Kč (float32, columns = consumers…, producers…) for the plots
    t_index: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    t_values: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=np.float32))

    @property
    def producer(self) -> float:
        """Kč: all producers together."""
        return float(self.producers.sum())


def compute_shapley(P: np.ndarray, D: np.ndarray, prices, feed_ins,
                    progress: ProgressFn = _noop) -> ShapleyTotals:
    """Shapley values of the benchmark for every interval (``P[T, np]`` surpluses of the
    producers, ``D[T, n]`` demands, in hundredths of kWh; ``prices[n]`` and
    ``feed_ins[np]`` in Kč/kWh). A 1-D ``P`` and a number ``feed_ins`` mean one producer."""
    c0 = time.process_time()
    P = np.asarray(P, dtype=np.int64)
    P = np.clip(P[:, None] if P.ndim == 1 else P, 0, None)
    D = np.clip(np.asarray(D, dtype=np.int64), 0, None)
    T, n = D.shape
    f = np.atleast_1d(np.asarray(feed_ins, dtype=float))
    npr = P.shape[1]
    lay = Layers.build(prices, f)
    res = ShapleyTotals(prices=list(map(float, prices)), feed_ins=list(map(float, f)),
                        consumers=np.zeros(n), producers=np.zeros(npr), maximum=0.0,
                        n_intervals=T)
    Cin, Fin = lay.consumer_in.astype(float), lay.producer_in.astype(float)
    dl = lay.dl
    # per interval and layer: demand, surplus, number of active consumers / producers
    Dl, Gl = D @ Cin, P @ Fin
    nc, nq = (D > 0) @ Cin, (P > 0) @ Fin
    live = (Gl > 0) & (Dl > 0)
    one_p = live & (nq == 1) & (Gl >= Dl)
    one_c = live & ~one_p & (nc == 1) & (Dl >= Gl)
    hard_any = (live & ~one_p & ~one_c).any(axis=1)
    day = np.flatnonzero(live.any(axis=1))
    res.n_night = T - len(day)
    pos = np.full(T, -1, dtype=np.int64)
    pos[day] = np.arange(len(day))
    vals = np.zeros((len(day), n + npr))                 # Kč · hundredths of kWh
    # closed forms for every interval without a hard layer, all at once
    easy = np.flatnonzero(live.any(axis=1) & ~hard_any)
    res.n_covered = len(easy)
    if len(easy):
        Pe, De = P[easy], D[easy]
        wp, wc = dl * one_p[easy], dl * one_c[easy]
        vc = De * (wp @ Cin.T) / 2 + ((wc * Gl[easy]) @ Cin.T) * (De > 0) / 2
        vp = ((wp * Dl[easy]) @ Fin.T) * (Pe > 0) / 2 + Pe * (wc @ Fin.T) / 2
        vals[pos[easy]] = np.hstack([vc, vp])
        res.maximum += float((dl * np.minimum(Gl[easy], Dl[easy])).sum())
    scarce = np.flatnonzero(hard_any)
    res.n_scarce = len(scarce)
    # progress by the work that costs: grid length × active players
    work = (np.minimum(Gl[scarce].max(axis=1, initial=0) + Dl[scarce].max(axis=1, initial=0),
                       10**9) + 1) * np.maximum((D[scarce] > 0).sum(axis=1)
                                                + (P[scarce] > 0).sum(axis=1), 1)
    total = float(work.sum()) or 1.0
    done = last = 0.0
    for i, t in enumerate(scarce):
        pc, pp, vmax, _ = shapley_interval(P[t], D[t], lay)
        vals[pos[t]] = np.concatenate([pc, pp])
        res.maximum += vmax
        done += work[i]
        if done - last >= 0.01 * total:
            last = done
            progress("bill", done / total)
    vals /= 100
    res.consumers = vals[:, :n].sum(axis=0)
    res.producers = vals[:, n:].sum(axis=0)
    res.maximum /= 100
    res.t_index = day
    res.t_values = vals.astype(np.float32)
    res.seconds = time.process_time() - c0
    progress("bill", 1.0)
    return res


# ---------------------------------------------------------------------------
# Settlement in crowns
# ---------------------------------------------------------------------------


def _haler(values: np.ndarray, total: float) -> np.ndarray:
    """``values`` rounded to whole haléř so that they add up to ``total`` (also in
    haléř): the largest remainders get the leftover haléř."""
    cents = np.asarray(values, dtype=float) * 100
    out = np.floor(cents)
    if len(out):
        q, r = divmod(int(round(total * 100 - out.sum())), len(out))      # r >= 0
        out[np.argsort(-(cents - out), kind="stable")[:r]] += 1
        out += q
    return out / 100


@dataclass
class Billing:
    prices: np.ndarray             # Kč/kWh per consumer (supplier price)
    feed_ins: np.ndarray           # Kč/kWh per producer (feed-in price)
    shared: np.ndarray             # kWh per consumer (report)
    supplied: np.ndarray           # kWh per producer: its surplus shared (report)
    saving: np.ndarray             # Kč: price · shared (what the consumer did not buy)
    share: np.ndarray              # Kč: consumer's fair share of the benefit (scaled Shapley)
    payment: np.ndarray            # Kč the consumer pays into the pool (whole haléř)
    producer_share: np.ndarray     # Kč per producer: its benefit = income − feed-in value
    producer_income: np.ndarray    # Kč per producer from the pool (whole haléř)
    feed_in_value: np.ndarray      # Kč per producer: its shared energy at the feed-in price
    realized: float                # Kč: benefit of the report's sharing
    maximum: float                 # Kč: benefit of the best possible sharing

    @property
    def efficiency(self) -> float:
        return self.realized / self.maximum if self.maximum > 0 else 0.0

    @property
    def unit_price(self) -> np.ndarray:
        """Kč/kWh each consumer effectively pays for shared electricity."""
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(self.shared > 0, self.payment / self.shared, np.nan)

    @property
    def producer_unit_price(self) -> np.ndarray:
        """Kč/kWh each producer effectively gets for its shared electricity."""
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(self.supplied > 0, self.producer_income / self.supplied, np.nan)


def settle(res: ShapleyTotals, shared_kwh, supplied_kwh=None) -> Billing:
    """Crowns: Shapley values scaled to the realized benefit, payments in haléř.

    ``supplied_kwh[np]`` is what each producer shared; it is scaled to add up to the
    consumers' ``shared_kwh`` (they differ by the report's rounding). With one producer
    it may be left out."""
    p = np.asarray(res.prices, dtype=float)
    f = np.asarray(res.feed_ins, dtype=float)
    shared = np.asarray(shared_kwh, dtype=float)
    total = float(shared.sum())
    supplied = (np.full(len(f), total / max(len(f), 1)) if supplied_kwh is None
                else np.clip(np.asarray(supplied_kwh, dtype=float), 0, None))
    if supplied.sum() > 0:
        supplied = supplied * (total / supplied.sum())
    realized = float((p * shared).sum() - (f * supplied).sum())
    scale = realized / res.maximum if res.maximum > 0 else 0.0
    share = res.consumers * scale
    saving = p * shared
    payment = np.round(saving - share, 2)
    fiv = f * supplied
    income = _haler(fiv + res.producers * scale, float(payment.sum()))
    return Billing(prices=p, feed_ins=f, shared=shared, supplied=supplied, saving=saving,
                   share=share, payment=payment, producer_share=income - fiv,
                   producer_income=income, feed_in_value=fiv, realized=realized,
                   maximum=res.maximum)


@dataclass
class BillResult:
    """A finished billing of one report: the Shapley values, the settlement, and the
    values per 15-min interval for the plots."""

    totals: ShapleyTotals
    settlement: Billing
    index: pd.DatetimeIndex        # the report's 15-min intervals
    members: list[str]             # consumer EANs in report order
    producers: list[str]           # producer EANs in report order

    @classmethod
    def build(cls, totals: ShapleyTotals, shared_kwh, supplied_kwh, index: pd.DatetimeIndex,
              members: list[str], producers: list[str]) -> "BillResult":
        return cls(totals, settle(totals, shared_kwh, supplied_kwh), index, list(members),
                   list(producers))

    @property
    def producer_cols(self) -> list[str]:
        return [producer_col(e) for e in self.producers]

    @cached_property
    def per_interval(self) -> pd.DataFrame:
        """Kč per 15 min, scaled like the settlement (to the realized benefit): one
        column per member and per producer (:func:`producer_col`); 0 in intervals
        without anything to share."""
        bill, res = self.settlement, self.totals
        scale = bill.realized / bill.maximum if bill.maximum > 0 else 0.0
        cols = self.members + self.producer_cols
        vals = np.zeros((len(self.index), len(cols)))
        if len(res.t_index):
            vals[res.t_index] = res.t_values.astype(float) * scale
        return pd.DataFrame(vals, index=self.index, columns=cols)
