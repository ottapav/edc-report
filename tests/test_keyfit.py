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


def _group_with_silent_members(seed=5):
    """5-round group where member 2 never receives anything (key 0), member 3 has no
    demand at all and member 4 only has demand while there is no production."""
    n, T = 8, 96 * 120
    P, D, S, k = synthetic_group(n, T, 5, seed=seed)
    k = k.copy()
    k[2] = 0.0
    D[:, 3] = 0
    hour = (np.arange(T) % 96) / 4
    D[:, 4] = np.where((hour < 6) | (hour > 20), 30, 0)
    return P, D, keyfit.replay_edc(P, D, k, 5), k


def test_member_that_receives_nothing_gets_key_zero():
    P, D, S, k = _group_with_silent_members()
    fit = keyfit.estimate_keys(P, D, S)
    assert fit.status[2] == "zero" and fit.keys[2] == 0.0
    assert fit.status[3] == "no_data" and fit.keys[3] == 0.0     # no phantom median key
    assert fit.keys[4] == 0.0                                    # demand only without production
    lo, hi = fit.ranges[2]
    assert lo == 0.0 and 0 < hi < 0.01                           # "anything below hi gives nothing"
    for i in (0, 1, 5, 6, 7):
        assert fit.keys[i] > 0
    assert fit.match >= 0.99


def test_no_zero_key_for_a_member_that_receives_something():
    P, D, S, _ = synthetic_group(12, 96 * 40, 5, seed=8)
    fit = keyfit.estimate_keys(P, D, S)
    for i, key in enumerate(fit.keys):
        live = (P > 0) & (D[:, i] > 0)
        if S[live, i].sum() > 0:
            assert key > 0, i


def test_keys_never_sum_above_100_percent():
    for seed in range(4):
        P, D, S, _ = synthetic_group(25, 96 * 30, 5, seed=seed)
        assert sum(keyfit.estimate_keys(P, D, S).keys) <= 1.0 + 1e-9


def test_time_budget_returns_sane_rough_keys():
    P, D, S, _ = _group_with_silent_members()
    fit = keyfit.estimate_keys(P, D, S, budget=1e-6)             # out of time at once
    assert fit.rough and len(fit.keys) == 8
    assert fit.keys[2] == fit.keys[3] == fit.keys[4] == 0.0      # the rules hold regardless
    assert 0 <= sum(fit.keys) <= 1.0 + 1e-9
    assert fit.match > 0.5


def test_sample_keeps_rows_of_rarely_short_members():
    P, D, S, _ = synthetic_group(30, 96 * 120, 5, seed=4)
    status = keyfit._member_status(P, D, S)
    idx = keyfit._sample_rows(P, D, S, status, max_rows=500)
    assert 0 < len(idx) <= 500 + 30 * keyfit.MIN_MEMBER_ROWS and (np.diff(idx) > 0).all()
    short = (S < D) & (D > 0)
    for i, st in enumerate(status):
        if st == "ok":
            mine = int(((P > 0) & short[:, i]).sum())
            kept = int(short[idx, i].sum())
            assert kept >= min(mine, keyfit.MIN_MEMBER_ROWS) - 1


def test_month_of_60_members_is_roughly_right_and_fast():
    P, D, S, k = synthetic_group(60, 96 * 60, 5, seed=11)
    fit = keyfit.estimate_keys(P, D, S)
    truth = keyfit.replay_match(P, D, S, k, 5)
    assert fit.match >= truth - 0.03
    assert fit.seconds < 30
