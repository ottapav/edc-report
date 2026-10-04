"""Benchmark of the key estimate on synthetic one-year groups (35 040 intervals).

    python bench/keyfit_bench.py            # all cases
    python bench/keyfit_bench.py --quick    # one month instead of a year

Shares come from today's EDC method with known keys, 1 % of the intervals are
perturbed (reports are not perfectly clean). "truth" is the share of intervals the
true keys reproduce, so a fit "as good as the truth" has match ~ truth; "in range"
is the share of keys whose reported range of equally consistent values holds the
true key, "exact" the share of keys equal to the true key.
"""
import argparse
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]

import keyfit  # noqa: E402
from conftest import synthetic_group  # noqa: E402

CASES = [  # members, keys, EDC rounds
    (20, "random", 5), (60, "round", 5), (60, "random", 5), (100, "random", 5), (150, "random", 1),
]


def make(n, T, rounds, kind, seed=1):
    rng = np.random.default_rng(seed)
    w = rng.lognormal(0, 0.8, n)
    k = w / w.sum() * rng.uniform(0.9, 1.0)
    k = np.round(k, 2) if kind == "round" else np.round(k, 4)
    k[k <= 0] = 1e-4
    P, D, S, k = synthetic_group(n, T, rounds, keys=k, seed=seed)
    bad = rng.random(T) < 0.01
    S[bad] = np.maximum(0, S[bad] + rng.integers(-2, 3, (int(bad.sum()), n)))
    return P, D, S, k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    T = 96 * 31 if ap.parse_args().quick else 35040
    print(f"{'members':>7} {'keys':>6} {'rounds':>6} {'match':>6} {'truth':>6} {'in range':>8} "
          f"{'exact':>6} {'time':>6}")
    for n, kind, rounds in CASES:
        P, D, S, k = make(n, T, rounds, kind)
        t0 = time.perf_counter()
        f = keyfit.estimate_keys(P, D, S, budget=None)
        dt = time.perf_counter() - t0
        est = np.array(f.keys)
        lo = np.array([a for a, _ in f.ranges])
        hi = np.array([b for _, b in f.ranges])
        ok = np.array([s == "ok" for s in f.status])
        print(f"{n:>7} {kind:>6} {rounds:>6} {f.match:>6.3f} "
              f"{keyfit.replay_match(P, D, S, k, rounds):>6.3f} "
              f"{((lo - 1e-6 <= k) & (k <= hi + 1e-6))[ok].mean() * 100:>7.0f}% "
              f"{(np.abs(est - k) < 5e-7)[ok].mean() * 100:>5.0f}% {dt:>5.1f}s", flush=True)


if __name__ == "__main__":
    main()
