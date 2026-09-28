import numpy as np

import keyfit
import presna_staticka as ps
from conftest import synthetic_group


def test_replay_equals_reference_implementation(small_group):
    P, D, S, k = small_group
    ref = np.array([ps.staticka_edc(int(p), list(map(int, d)), list(k)) for p, d in zip(P, D)])
    assert (keyfit.replay_edc(P, D, k, 5) == ref).all()
    ref1 = np.array([ps.staticka_edc(int(p), list(map(int, d)), list(k), kola=1)
                     for p, d in zip(P, D)])
    assert (keyfit.replay_edc(P, D, k, 1) == ref1).all()


def test_exact_bounds_contain_true_key():
    rng = np.random.default_rng(0)
    pr = np.sort(rng.integers(1, 2000, (300, 5)), axis=1)[:, ::-1].astype(float)
    k = rng.uniform(0.001, 0.6, 300)
    s = np.floor(pr * k[:, None] + 1e-9).sum(axis=1)
    lo, hi = keyfit.exact_bounds(s, pr)
    assert ((lo <= k + 1e-12) & (k < hi)).all()


def test_five_rounds_round_keys_recovered(small_group):
    """Keys the report pins down come back exactly; for the others the fit is as
    good as the truth and the truth lies in the reported range."""
    P, D, S, k = small_group
    fit = keyfit.estimate_keys(P, D, S)
    assert fit.rounds == 5
    assert fit.match == keyfit.replay_match(P, D, S, k, 5) == 1.0
    for est, true, (lo, hi) in zip(fit.keys, k, fit.ranges):
        assert lo - 1e-9 <= true <= hi + 1e-9
        if hi - lo < 1e-3:
            assert abs(est - true) < 1e-9


def test_one_round_large_group_is_exact_fit():
    P, D, S, k = synthetic_group(150, 96 * 31, 1, seed=1)
    fit = keyfit.estimate_keys(P, D, S)
    assert fit.rounds == 1
    assert fit.match == keyfit.replay_match(P, D, S, k, 1) == 1.0
    # every true key lies in the reported range of equally consistent keys
    lo = np.array([a for a, b in fit.ranges])
    hi = np.array([b for a, b in fit.ranges])
    assert ((lo - 1e-6 <= k) & (k <= hi + 1e-6)).all()
    assert fit.seconds < 5


def test_groups_above_100_try_one_round_only():
    P, D, S, _ = synthetic_group(101, 96 * 7, 1, seed=2)
    assert list(keyfit.estimate_keys(P, D, S).tried) == [1]
