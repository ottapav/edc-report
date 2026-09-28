import numpy as np

import keyfit
import recompute
import sharel_core as core
from conftest import all_report_csv


def test_load_all_report_roundtrip(small_group):
    P, D, S, _ = small_group
    data = core.load_report(all_report_csv(P, D, S))
    assert data.fmt == "all" and len(data.dest_eans) == 5
    P2, D2, S2 = recompute.to_hundredths(data)
    assert (P2 == P).all() and (D2 == D).all() and (S2 == S).all()


def test_wasted_overlap_is_what_the_exact_method_adds(small_group):
    P, D, S, k = small_group
    data = core.load_report(all_report_csv(P, D, S))
    split = core.compute_wasted_split(data.frame)
    res = recompute.recompute(data, list(k), rounds=5)
    gain = core.compute_wasted_split(res.data.frame).shared_total - split.shared_total
    # single producer: the exact method shares exactly the "could have been shared" part
    assert abs(gain - split.overlap) < 0.05
    assert core.compute_wasted_split(res.data.frame).overlap < 0.05


def test_recompute_timing_counts_every_interval(small_group):
    P, D, S, k = small_group
    data = core.load_report(all_report_csv(P, D, S))
    tm = recompute.recompute(data, list(k)).timing
    assert tm.intervals == len(P) == tm.n_night + tm.n_enough + tm.n_full
    assert tm.t_total > 0 and tm.per_interval > 0


def test_memoised_filter_is_reused(small_group):
    P, D, S, _ = small_group
    data = core.load_report(all_report_csv(P, D, S))
    a = core.filter_dests(data, set(data.dest_eans[:3]))
    b = core.filter_dests(data, set(data.dest_eans[:3]))
    assert a is b
