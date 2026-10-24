"""Billing by the Shapley value: exactness against brute force, settlement, job, callbacks."""
import time
from itertools import combinations
from math import factorial

import numpy as np
import pytest

import billing as B
import figures
import jobs
import store
from ui import compute, members, report, views
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


def _v_pool(S, g, d, p, f):
    """Benchmark with several producers (players 0..np-1): the cheapest surplus goes to
    the dearest demand while the price is above the feed-in price."""
    k = len(g)
    prod = sorted([[f[i], g[i]] for i in S if i < k])
    cons = sorted([[-p[j - k], d[j - k]] for j in S if j >= k])
    val, i, j = 0.0, 0, 0
    while i < len(prod) and j < len(cons) and -cons[j][0] > prod[i][0]:
        q = min(prod[i][1], cons[j][1])
        val += q * (-cons[j][0] - prod[i][0])
        prod[i][1] -= q
        cons[j][1] -= q
        i += prod[i][1] == 0
        j += cons[j][1] == 0
    return val


def _brute_pool(g, d, p, f):
    n = len(g) + len(d)
    phi = np.zeros(n)
    for i in range(n):
        others = [x for x in range(n) if x != i]
        for k in range(n):
            w = factorial(k) * factorial(n - 1 - k) / factorial(n)
            for S in combinations(others, k):
                phi[i] += w * (_v_pool(S + (i,), g, d, p, f) - _v_pool(S, g, d, p, f))
    return phi


def test_several_producers_equal_brute_force():
    """A pool of producers with their own feed-in prices, exact for every player."""
    rng = np.random.default_rng(11)
    for _ in range(30):
        npr, m = int(rng.integers(2, 4)), int(rng.integers(1, 6))
        P = rng.integers(0, 400, (3, npr))
        D = rng.integers(0, 250, (3, m))
        D[rng.random((3, m)) < 0.15] = 0
        p = list(rng.choice([2.5, 3.9, 4.4, 5.1, 6.0], m))
        f = list(rng.choice([1.0, 1.0, 2.5, 3.0, 4.4], npr))
        r = B.compute_shapley(P, D, p, f)
        ref = sum(_brute_pool(list(P[t] / 100), list(D[t] / 100), p, f) for t in range(3))
        assert np.abs(r.producers - ref[:npr]).max() < 1e-9
        assert np.abs(r.consumers - ref[npr:]).max() < 1e-9
        assert r.maximum == pytest.approx(r.producers.sum() + r.consumers.sum())


def test_one_producer_split_in_two():
    """Two equal halves of a producer: the same best benefit, equal shares (symmetry),
    and each half less indispensable than the whole, so the halves get less together."""
    P, D, _S, _k = synthetic_group(8, 96 * 3, 5, seed=5)
    prices = [3.9, 4.2, 4.2, 5.1, 3.0, 4.6, 4.4, 4.0]
    one = B.compute_shapley(2 * P, D, prices, 1.5)
    two = B.compute_shapley(np.stack([P, P], axis=1), D, prices, [1.5, 1.5])
    assert two.maximum == pytest.approx(one.maximum, rel=1e-12)
    assert two.producers[0] == pytest.approx(two.producers[1], rel=1e-12)
    assert two.producers.sum() < one.producer


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
    assert bill.share.sum() + bill.producer_share.sum() == pytest.approx(bill.realized,
                                                                        abs=0.01 * 6)
    assert bill.producer_income.sum() == pytest.approx(bill.payment.sum())
    assert np.all(np.round(bill.payment * 100) == bill.payment * 100)   # whole haléř
    # nobody pays more than the supplier price, and the producer earns at least feed-in
    assert np.all(bill.payment <= bill.saving + 1e-9)
    assert np.all(bill.producer_income >= bill.feed_in_value - 1e-9)


def test_settlement_of_a_pool_adds_up():
    P, D, S, _ = synthetic_group(6, 96 * 10, 5, seed=4)
    P3 = np.stack([P // 2, P // 3, P - P // 2 - P // 3], axis=1)
    prices = [3.9, 4.2, 4.2, 5.1, 3.0, 4.6]
    res = B.compute_shapley(P3, D, prices, [1.0, 1.5, 2.2])
    shared = S.sum(axis=0) / 100
    bill = B.settle(res, shared, [shared.sum() * 0.5, shared.sum() * 0.3, shared.sum() * 0.21])
    assert bill.supplied.sum() == pytest.approx(shared.sum())          # scaled to balance
    assert bill.producer_income.sum() == pytest.approx(bill.payment.sum(), abs=1e-9)
    assert np.all(np.round(bill.producer_income * 100) == bill.producer_income * 100)
    assert np.all(bill.producer_share > -0.01)
    assert bill.realized == pytest.approx((bill.prices * shared).sum()
                                          - (bill.feed_ins * bill.supplied).sum())


# --- web app ---------------------------------------------------------------------------


@pytest.fixture
def entry_key():
    P, D, S, _ = synthetic_group(5, 96 * 30, 5, seed=3)
    key = store.put("t.csv", core.load_report(all_report_csv(P, D, S)))
    yield key
    store.drop(key)


def _wait(job_id, seconds=60):
    job = jobs.get(job_id)
    t0 = time.perf_counter()
    while not job.done and time.perf_counter() - t0 < seconds:
        time.sleep(0.05)
    assert job.done and job.error is None and job.error_key is None


def _billed(key, lang="cs", default=None):
    """Run the billing of the stored report with prices 4.0, 4.3, … Kč/kWh."""
    entry = store.get(key)
    rows = [{"ean": e, "price": None if default else 4.0 + 0.3 * j}
            for j, e in enumerate(entry.data.dest_eans)]
    job_id = compute.start_bill(1, key, rows, [], 1.2, default, lang)["job"]
    _wait(job_id)
    return entry, rows, job_id


def test_prices_from_the_grid_with_default():
    P, D, S, _ = synthetic_group(3, 96, 5, seed=1)
    d = core.load_report(all_report_csv(P, D, S))
    rows = [{"ean": d.dest_eans[0], "price": 4.5}, {"ean": d.dest_eans[1], "price": "3,9"},
            {"ean": d.dest_eans[2], "price": None}]
    assert members.prices(d, rows, None) == [4.5, 3.9, None]
    assert members.prices(d, rows, 4.1) == [4.5, 3.9, 4.1]
    assert compute.bill_inputs(d, rows, [], None, 4.1) == (None, "bill_need_feed_in")
    assert compute.bill_inputs(d, rows, [], 1.2, None) == (None, "bill_need_prices")
    assert compute.bill_inputs(d, rows, [], "1,2", 4.1) == (([4.5, 3.9, 4.1], [1.2]), None)
    # a producer's own price (producers grid) wins over the default
    src = [{"ean": d.source_eans[0], "price": "0,9"}]
    assert compute.bill_inputs(d, rows, src, 1.2, 4.1)[0][1] == [0.9]


def test_bill_job_and_result(entry_key):
    entry, rows, job_id = _billed(entry_key, default=4.3)
    state = compute.poll_state(job_id, 0, "cs")
    assert state[2] == "progress done" and state[5] == 1
    assert len(entry.bill.totals.consumers) == 5
    out = compute.bill_result(1, entry_key, "cs", None, 1.2, 4.3, None, None, rows, [])
    assert out["result"] and out["table"] and out["stale"] == []
    # a changed price marks the billing as stale until the button is pressed again
    assert compute.bill_result(1, entry_key, "cs", None, 1.2, 4.4, None, None, rows, [])["stale"]
    src = [{"ean": entry.data.source_eans[0], "price": 1.3}]
    assert compute.bill_result(1, entry_key, "cs", None, 1.2, 4.3, None, None, rows, src)["stale"]


def test_bill_needs_prices(entry_key):
    entry = store.get(entry_key)
    rows = [{"ean": e, "price": None} for e in entry.data.dest_eans]
    out = compute.start_bill(1, entry_key, rows, [], 1.2, None, "en")
    assert out["cls"] == "progress error" and "price" in out["text"]


def test_billing_in_the_right_column(entry_key):
    """The billing draws the same five figures as the exact method, in Kč; its
    per-interval values add up to the settlement."""
    entry, _rows, _job = _billed(entry_key, "en")
    data, bill = entry.data, entry.bill.settlement
    assert report.right_mode(entry, "bill") == "bill"
    assert report.right_mode(entry, "exact") == "bill"          # no recompute yet
    enabled = set(data.dest_eans[:3])                           # two members unticked
    cols, n_rest = figures.bill_columns(entry.bill.per_interval, data, enabled, None)
    assert n_rest == 0
    prod = B.producer_col(data.source_eans[0])
    assert list(cols.columns) == list(data.dest_eans[:3]) + [figures.UNSELECTED, prod]
    assert cols.drop(columns=prod).to_numpy().sum() == pytest.approx(bill.share.sum(),
                                                                     rel=1e-5)
    assert cols[prod].sum() == pytest.approx(bill.producer_share.sum(), abs=0.05)
    names = members.default_names(data, "en")
    th = figures.theme("dark")
    split = figures.fig_bill_split(bill, data, names, enabled, lang="en", th=th)
    assert len(split.data) == 2 and split.layout.height >= 320
    pie = figures.fig_bill_pie(bill, data, enabled, "en", th)
    assert sum(pie.data[0].values) == pytest.approx(bill.maximum, abs=0.01 * len(data.dest_eans))
    day = str(data.frame.index[len(data.frame) // 2].date())
    assert figures.fig_bill_daily(cols, data, names, lang="en", sel_day=day, th=th).data
    assert figures.fig_bill_intraday(cols, data, names, day, lang="en", th=th).data
    assert figures.fig_bill_heatmap(entry.bill.per_interval.sum(axis=1), lang="en", th=th).data
    assert views.bill_tiles(bill, data, enabled, "cs")


def test_german_interface(entry_key):
    """The German strings drive the same figures, tiles and member grid as the others."""
    entry, _rows, _job = _billed(entry_key, "de")
    data, bill = entry.data, entry.bill.settlement
    enabled = set(data.dest_eans[:3])
    names = members.default_names(data, "de")
    assert names[data.dest_eans[0]].startswith("Verbrauch")
    th = figures.theme("light")
    assert figures.fig_bill_split(bill, data, names, enabled, lang="de", th=th).data
    assert figures.fig_bill_pie(bill, data, enabled, "de", th).data
    assert views.bill_tiles(bill, data, enabled, "de")
    assert views.bill_table(bill, data, names, "de")
    rows = members.rows(data)
    assert all(r["default_de"] and r["default_cs"] and r["default_en"] for r in rows)
    assert [c["field"] for c in members.columns("de", True)] == ["name", "tail", "key", "price"]


def test_paired_figures_line_up(entry_key):
    """Right-column figures take the left one's member order, height and legend rows."""
    entry, _rows, _job = _billed(entry_key)
    data, bill = entry.data, entry.bill.settlement
    enabled = set(data.dest_eans)
    names = members.default_names(data, "cs")
    df = core.filter_dests(data, enabled)
    order = figures.flow_order(df, data)
    left = figures.fig_total_by_flow(df, data, names, lang="cs")
    right = figures.fig_bill_split(bill, data, names, enabled, lang="cs", order=order)
    member_rows = lambda f: list(f.layout.yaxis.ticktext[:len(order)])  # noqa: E731
    assert member_rows(left) == member_rows(right) == [names[e] for e in order]
    cols, _ = figures.bill_columns(entry.bill.per_interval, data, enabled, None)
    fa = figures.fig_daily(df, data, names, lang="cs")
    fb = figures.fig_bill_daily(cols, data, names, lang="cs")
    figures.pair_figures(fa, fb)
    assert fa.layout.height == fb.layout.height
    assert figures.legend_entries(fa) == figures.legend_entries(fb)
    assert figures.legend_entries(fa) % 2 == 0


# --- several producers -----------------------------------------------------------------


@pytest.fixture
def pool_key():
    P, D, S, _ = synthetic_group(5, 96 * 20, 5, seed=6)
    P3 = np.stack([P // 2, P // 3, P - P // 2 - P // 3], axis=1)
    key = store.put("pool.csv", core.load_report(all_report_csv(P3, D, S)))
    yield key
    store.drop(key)


def test_report_with_several_producers_loads_as_a_pool(pool_key):
    data = store.get(pool_key).data
    assert len(data.source_eans) == 3 and set(data.productions) == set(data.source_eans)
    assert {core.key_source(c) for c in core.shared_cols(data.frame)} == {core.POOL}
    assert members.default_names(data, "cs")[core.POOL] == "Výrobny (bazén)"
    supplied = core.supplied_per_source(data)
    assert supplied.sum() == pytest.approx(core.per_destination(data)["shared"].sum(), abs=0.05)
    P, D = core.producer_arrays(data)
    assert P.shape == (data.n_rows, 3) and D.shape == (data.n_rows, 5)


def test_billing_of_several_producers(pool_key):
    entry = store.get(pool_key)
    data = entry.data
    rows = [{"ean": e, "price": 4.0 + 0.3 * j} for j, e in enumerate(data.dest_eans)]
    src = [{"ean": e, "price": p} for e, p in zip(data.source_eans, [1.0, None, 2.0])]
    job_id = compute.start_bill(1, pool_key, rows, src, 1.5, None, "cs")["job"]
    _wait(job_id)
    res = entry.bill.totals
    assert res.feed_ins == [1.0, 1.5, 2.0] and len(res.producers) == 3
    bill = entry.bill.settlement
    assert bill.producer_income.sum() == pytest.approx(bill.payment.sum(), abs=1e-9)
    enabled = set(data.dest_eans)
    names = members.default_names(data, "cs")
    cols, _ = figures.bill_columns(entry.bill.per_interval, data, enabled, None)
    assert [c for c in cols.columns if B.is_producer_col(c)] == entry.bill.producer_cols
    th = figures.theme("light")
    # the flow chart pairs one pool row with one producers' row, so the members line up
    df = core.filter_dests(data, enabled)
    order = figures.flow_order(df, data)
    left = figures.fig_total_by_flow(df, data, names, lang="cs")
    split = figures.fig_bill_split(bill, data, names, enabled, lang="cs", th=th, order=order)
    assert list(left.layout.yaxis.ticktext)[:-1] == list(split.layout.yaxis.ticktext)[:-1]
    assert figures.fig_bill_daily(cols, data, names, lang="cs", th=th).data
    table = views.bill_table(bill, data, names, "cs")
    assert table is not None
    assert "Výrobny (bazén)" in split.layout.yaxis.ticktext
    # the exact static method is refused, with a reason
    out = compute.start_exact(1, pool_key, rows, 0, "cs")
    assert out["cls"] == "progress error" and "jednou výrobnou" in out["text"]


def test_panel_grids_and_ean_tails(pool_key):
    """Producers have their own grid (name, EAN, feed-in price); EANs show three digits."""
    data = store.get(pool_key).data
    prow = members.producer_rows(data)
    assert [r["ean"] for r in prow] == data.source_eans
    assert all(r["tail"] == "…" + r["ean"][-3:] for r in prow + members.rows(data))
    assert [c["field"] for c in members.producer_columns("cs")] == ["name", "tail", "price"]
    prow[0]["name"] = "Střecha"
    names = members.names(data, "cs", prow, [{"ean": data.dest_eans[0], "name": "Škola"}])
    assert names[data.source_eans[0]] == "Střecha" and names[data.dest_eans[0]] == "Škola"
    facts = str(views.facts("x.csv", data, set(data.dest_eans), names, "cs"))
    assert data.source_eans[0] not in facts and "…" + data.source_eans[0][-3:] in facts
