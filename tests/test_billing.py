"""Billing by the Shapley value: exactness against brute force, settlement, job, callbacks."""
import time
from itertools import combinations
from math import factorial

import numpy as np
import pytest

import app
import billing as B
import edc_data as core
from conftest import all_report_csv, synthetic_group


def _v(S, P, d, p, f):
    """Benchmark coalition value: player 0 is the producer, P goes to the highest prices."""
    if 0 not in S:
        return 0.0
    left, val = P, 0.0
    for j in sorted((i - 1 for i in S if i > 0), key=lambda j: -p[j]):
        if p[j] <= f:
            break
        q = min(left, d[j])
        val += q * (p[j] - f)
        left -= q
    return val


def _brute(P, d, p, f):
    n = len(d) + 1
    phi = np.zeros(n)
    for i in range(n):
        others = [x for x in range(n) if x != i]
        for k in range(n):
            w = factorial(k) * factorial(n - 1 - k) / factorial(n)
            for S in combinations(others, k):
                phi[i] += w * (_v(S + (i,), P, d, p, f) - _v(S, P, d, p, f))
    return phi


def test_shapley_equals_brute_force_with_mixed_prices():
    rng = np.random.default_rng(7)
    for _ in range(40):
        m = int(rng.integers(1, 8))
        P = rng.integers(0, 500, 4)
        D = rng.integers(0, 250, (4, m))
        D[rng.random((4, m)) < 0.2] = 0                      # members without demand
        p = list(rng.choice([2.5, 3.9, 4.4, 5.1, 6.0], m))
        f = float(rng.choice([1.0, 2.5, 3.0, 4.4]))          # some prices not above feed-in
        r = B.compute_shapley(P, D, p, f)
        ref = sum(_brute(int(P[t]) / 100, D[t] / 100, p, f) for t in range(4))
        assert np.abs(r.consumers - ref[1:]).max() < 1e-9
        assert abs(r.producer - ref[0]) < 1e-9
        assert r.maximum == pytest.approx(r.producer + r.consumers.sum())


def test_fewer_nodes_than_exact_still_match():
    """The error bound lets large groups use far fewer nodes than m // 2 + 1."""
    assert B.nodes_needed(150) < 150 // 2 + 1
    P, D, _S, _k = synthetic_group(60, 96 * 4, 5, seed=2)
    prices = list(np.random.default_rng(1).choice([3.8, 4.4, 5.0], 60))
    a = B.compute_shapley(P, D, prices, 1.2)
    saved = B.nodes_needed
    try:
        B.nodes_needed = lambda m, rel=0: (m // 2 + 1) + ((m // 2 + 1) % 2)
        b = B.compute_shapley(P, D, prices, 1.2)
    finally:
        B.nodes_needed = saved
    assert np.abs(a.consumers - b.consumers).max() < 1e-9


def test_one_price_splits_like_kwh_and_covered_intervals_halve():
    # production covers everyone: each consumer and the producer split (p - f) d evenly
    P = np.array([1000, 0])
    D = np.array([[100, 200, 50], [30, 30, 30]])
    r = B.compute_shapley(P, D, [4.0, 4.0, 4.0], 1.0)
    assert r.n_covered == 1 and r.n_night == 1 and r.n_scarce == 0
    assert np.allclose(r.consumers, np.array([100, 200, 50]) / 100 * 3 / 2)
    assert r.producer == pytest.approx(3.5 * 3 / 2)


def test_settlement_adds_up():
    P, D, S, _ = synthetic_group(6, 96 * 20, 5, seed=4)
    prices = [3.9, 4.2, 4.2, 5.1, 3.0, 4.6]
    res = B.compute_shapley(P, D, prices, 1.5)
    bill = B.settle(res, S.sum(axis=0) / 100)
    assert bill.realized <= bill.maximum + 1e-9
    # consumers' shares + producer's share = realized benefit (to the haléř rounding)
    assert bill.share.sum() + bill.producer_share == pytest.approx(bill.realized, abs=0.01 * 6)
    assert bill.producer_income == pytest.approx(bill.payment.sum())
    assert np.all(np.round(bill.payment * 100) == bill.payment * 100)   # whole haléř
    # nobody pays more than the supplier price, and the producer earns at least feed-in
    assert np.all(bill.payment <= bill.saving + 1e-9)
    assert bill.producer_income >= bill.feed_in_value - 1e-9


# --- web app ---------------------------------------------------------------------------


@pytest.fixture
def entry_key():
    P, D, S, _ = synthetic_group(5, 96 * 30, 5, seed=3)
    data = core.load_report(all_report_csv(P, D, S))
    key = app._cache_put("t.csv", data)
    yield key
    app._cache_drop(key)


def _wait(job, seconds=60):
    t0 = time.perf_counter()
    while not job["done"] and time.perf_counter() - t0 < seconds:
        time.sleep(0.05)
    assert job["done"]


def test_prices_from_the_grid_with_default():
    P, D, S, _ = synthetic_group(3, 96, 5, seed=1)
    d = core.load_report(all_report_csv(P, D, S))
    rows = [{"ean": d.dest_eans[0], "price": 4.5}, {"ean": d.dest_eans[1], "price": "3,9"},
            {"ean": d.dest_eans[2], "price": None}]
    assert app._prices_from_rows(d, rows, None) == [4.5, 3.9, None]
    assert app._prices_from_rows(d, rows, 4.1) == [4.5, 3.9, 4.1]
    assert app._bill_inputs(d, rows, None, 4.1) == (None, "bill_need_feed_in")
    assert app._bill_inputs(d, rows, 1.2, None) == (None, "bill_need_prices")
    assert app._bill_inputs(d, rows, "1,2", 4.1) == (([4.5, 3.9, 4.1], 1.2), None)


def test_bill_job_and_render(entry_key):
    entry = app._cache_get(entry_key)
    rows = [{"ean": e, "price": None} for e in entry.data.dest_eans]
    out = app._start_bill(1, entry_key, rows, 1.2, 4.3, "cs")
    job_id = out[0]
    _wait(app._JOBS[job_id])
    state = app._poll_state(job_id, 0, "cs")
    assert state[2] == "progress done" and state[5] == 1
    assert entry.bill is not None and len(entry.bill.consumers) == 5
    result, stale, _title = app._bill_render(1, entry_key, "cs", None, [], 1.2, 4.3, [], rows)
    assert result and stale == []
    # a changed price marks the billing as stale until the button is pressed again
    _result, stale, _title = app._bill_render(1, entry_key, "cs", None, [], 1.2, 4.4, [], rows)
    assert stale


def test_bill_needs_prices(entry_key):
    entry = app._cache_get(entry_key)
    rows = [{"ean": e, "price": None} for e in entry.data.dest_eans]
    out = app._start_bill(1, entry_key, rows, 1.2, None, "en")
    assert out[3] == "progress error" and "price" in out[5]
