"""Allocation keys: validation, a member with key 0, and the approximate method replayed
with the keys the user typed (so both columns compare the same keys)."""
import numpy as np
import pytest

import edc_data as core
import recompute
from keyfit import KeyFit, replay_edc
from ui import members
from conftest import all_report_csv


def _fit(keys):
    return KeyFit(keys=list(keys), rounds=5, match=1.0, seconds=0.0, status=[], support=[],
                  tried=0, ranges=[], rough=False, rows=0)


@pytest.mark.parametrize("keys,reason", [
    ([0.2, -0.1, 0.3], "keys_negative"),
    ([0.6, 0.3, 0.2], "keys_sum_over"),
    ([0.0, 0.0, 0.0], "keys_all_zero"),
])
def test_invalid_keys_are_refused(keys, reason):
    with pytest.raises(recompute.InvalidKeys) as exc:
        recompute.check_keys(keys)
    assert exc.value.reason == reason
    assert members.key_problem(keys, None) == reason


def test_key_problem_counts_empty_cells_with_their_estimate():
    fit = _fit([0.3, 0.3, 0.3])
    assert members.key_problem([None, None, None], fit) is None
    assert members.key_problem([0.5, None, None], fit) == "keys_sum_over"     # 0.5 + 0.3 + 0.3
    assert members.key_problem([0.4, None, None], fit) is None
    assert members.key_problem([0.5, None, None], None) is None               # no estimate yet
    assert members.key_problem([1.0, 0.5, None], None) == "keys_sum_over"
    assert members.key_problem([0.1, 1.0], fit) == "keys_sum_over"           # a key over 100 %
    typed = members.keys(_Data(), [{"ean": "a", "key": -5}])                  # typed -5 %
    assert typed == [-0.05] and members.key_problem(typed, None) == "keys_negative"


class _Data:
    dest_eans = ["a"]


def test_member_with_key_zero_gets_nothing_on_both_sides(small_group):
    P, D, S, k = small_group
    data = core.load_report(all_report_csv(P, D, S))
    keys = list(k)
    keys[2] = 0.0
    res = recompute.recompute(data, keys, rounds=5)
    src, e = data.source_eans[0], data.dest_eans[2]
    assert res.data.frame[core.key_shared(src, e)].sum() == 0
    assert res.approx is not None                        # typed keys: today's method replayed
    assert res.approx.frame[core.key_shared(src, e)].sum() == 0
    # the replay is today's EDC method with these keys
    Ph, Dh, _ = recompute.to_hundredths(data)
    rep = replay_edc(Ph, Dh, keys, 5)
    got = np.stack([np.round(res.approx.frame[core.key_shared(src, x)].to_numpy() * 100)
                    for x in data.dest_eans], axis=1)
    assert (got == rep).all()
    # the exact method shares all that members with a key can use, never less than EDC
    active = np.array(keys) > 0
    exact = np.stack([np.round(res.data.frame[core.key_shared(src, x)].to_numpy() * 100)
                      for x in data.dest_eans], axis=1)
    assert (exact.sum(axis=1) == np.minimum(Ph, Dh[:, active].sum(axis=1))).all()
    gain = recompute.grid_loss(res.left(data), res.data)
    assert gain.lost == pytest.approx(gain.shared_exact - gain.shared_edc)
    assert gain.shared_exact >= gain.shared_edc


def test_estimated_keys_compare_with_the_report_itself(small_group):
    P, D, S, k = small_group
    data = core.load_report(all_report_csv(P, D, S))
    res = recompute.recompute(data, list(k), rounds=5, keys_estimated=True)
    assert res.approx is None and res.left(data) is data
    with_reserve = recompute.recompute(data, list(k), 0.1, rounds=5, keys_estimated=True)
    assert with_reserve.approx is not None                # the report has no reserve


def test_tiles_of_both_columns_add_up_with_a_zero_key(small_group):
    from ui import views
    P, D, S, k = small_group
    data = core.load_report(all_report_csv(P, D, S))
    keys = list(k)
    keys[0] = 0.0
    res = recompute.recompute(data, keys, rounds=5)
    sel = set(data.dest_eans)
    left = views._summary(res.left(data), sel, res.data)
    right = views._summary(res.data, sel, res.data)
    assert right.overlap == 0                       # the exact method is the most these keys share
    assert left.overlap == pytest.approx(right.shared - left.shared)
    assert left.unshared_only == pytest.approx(right.unshared_only, abs=0.05)
