"""Several producers: EDC's method with a key for every pair producer -> member, the
estimate of those pair keys, the exact static method on the producers' pool with keys
made of the pair keys interval by interval, and the page and the export saying so."""
import io
import time

import numpy as np
import pytest
from openpyxl import load_workbook

import edc_data as core
import export
import jobs
import keyfit
import recompute
import store
from conftest import all_report_csv, synthetic_group
from i18n import method_title, t
from presna_staticka import rozdel
from ui import compute, members, panel, report, views


def _pair_group(n=6, n_p=3, days=20, seed=0, shifts=(-2.0, 0.0, 2.0)):
    """Producers facing east, south and west; members' demand at random; shares by
    EDC's method for several producers with random pair keys (each producer ≤ 95 %)."""
    rng = np.random.default_rng(seed)
    T = 96 * days
    hour = (np.arange(T) % 96) / 4
    P2 = np.stack([(30 * n * np.clip(np.sin(np.pi * (hour - 6 - sh) / 12), 0, None)
                    * (6 + sh < hour) * (hour < 18 + sh) * rng.uniform(0.3, 1.0, T))
                   .astype(np.int64) for sh in shifts[:n_p]], axis=1)
    base = rng.lognormal(-1.5, 0.8, n)
    D = np.maximum(0, 100 * base[None, :] * rng.uniform(0.2, 1.8, (T, n))).astype(np.int64)
    K = rng.uniform(0, 1, (n_p, n))
    K = np.round(K / K.sum(axis=1, keepdims=True) * 0.95, 4)
    S, Q = keyfit.replay_edc_multi(P2, D, K, 5)
    return all_report_csv(P2, D, S, supplied=Q), P2, D, S, Q, K


@pytest.fixture(scope="module")
def pair_group():
    return _pair_group()


@pytest.fixture
def pool_entry(pair_group):
    csv, *rest = pair_group
    key = store.put("pool.csv", core.load_report(csv))
    yield (key, *rest)
    store.drop(key)


def _wait(job_id, seconds=180):
    job, t0 = jobs.get(job_id), time.perf_counter()
    while not job.done and time.perf_counter() - t0 < seconds:
        time.sleep(0.05)
    assert job.done and job.error is None and job.error_key is None


def _shares(data, d):
    return np.stack([np.round(d.frame[core.key_shared(core.POOL, e)].to_numpy() * 100)
                     for e in data.dest_eans], axis=1).astype(np.int64)


# ---------------------------------------------------------------------------
# EDC's method for several producers
# ---------------------------------------------------------------------------


def test_replay_follows_the_worked_example_of_the_edc_methodology():
    """EDC methodology, example 4: FVE Obecní úřad 2.20 kWh, Solární park 132.45 kWh;
    Obecní úřad 3.37 kWh (30 % from its FVE first, then 10 % from the park), Knihovna
    1.20 kWh, Školka 36.87 kWh (10 % from the park); three members, three rounds."""
    P2 = np.array([[220, 13245]])
    D = np.array([[337, 120, 3687]])
    K = np.array([[0.30, 0.0, 0.0], [0.10, 0.05, 0.10]])
    s, q, sp = keyfit.replay_edc_multi(P2, D, K, rounds=3, want_sp=True)
    assert sp[0, 1].tolist() == [13245, 11530, 10377]         # the park after each round
    assert s[0].tolist() == [337, 120, 1324 + 1153 + 1037]     # Školka: 13.24 + 11.53 + 10.37
    assert q[0].tolist() == [66, 271 + 120 + 1324 + 1153 + 1037]


def test_replay_with_one_producer_is_todays_method():
    rng = np.random.default_rng(1)
    P = rng.integers(0, 900, 500)
    D = rng.integers(0, 300, (500, 4))
    k = [0.3, 0.2, 0.1, 0.25]
    s, q = keyfit.replay_edc_multi(P[:, None], D, np.array([k]), 5)
    assert (s == keyfit.replay_edc(P, D, k, 5)).all() and (q[:, 0] == s.sum(axis=1)).all()


def test_pair_keys_are_estimated(pair_group):
    _csv, P2, D, S, Q, K = pair_group
    fit = keyfit.estimate_pair_keys(P2, D, S, Q)
    assert fit.rounds == 5 and fit.match > 0.85
    assert fit.pool_match < fit.match                       # one key set cannot do this
    Kf = np.array(fit.pair_keys)
    assert np.abs(Kf - K).max() < 0.01
    assert np.allclose(fit.keys, keyfit.pooled_keys(Kf, P2.sum(axis=0)))
    assert (Kf.sum(axis=1) <= 1 + 1e-9).all()


def test_pool_keys_treat_each_producers_keys_as_ratios():
    """EDC with endlessly many rounds gives away all of a producer's production, so its
    keys act as ratios: a producer's weight in the pool is its production alone."""
    K = np.array([[0.30, 0.10, 0.10], [0.45, 0.45, 0.0]])     # sums 50 % and 90 %
    assert np.allclose(keyfit.ratio_keys(K), [[0.6, 0.2, 0.2], [0.5, 0.5, 0.0]])
    # producers produce alike: the pool's key is the mean of the ratios
    assert np.allclose(keyfit.pooled_keys(K, [100, 100]), [0.55, 0.35, 0.1])
    assert keyfit.pooled_keys(K, [100, 100]).sum() == pytest.approx(1.0)
    assert (keyfit.ratio_keys([[0.0, 0.0], [0.2, 0.2]])[0] == 0).all()


def test_pool_equals_edc_with_endless_rounds_when_nobody_is_filled_up():
    """Different keys and different key sums per producer: as long as no member is
    filled up, the exact method on the pool gives every member what EDC's method for
    several producers gives after endlessly many rounds (up to rounding)."""
    rng = np.random.default_rng(5)
    for _ in range(50):
        P2 = rng.integers(2000, 9000, (1, 3)) * 100
        D = np.full((1, 5), 10**9)
        K = rng.uniform(0.05, 1, (3, 5))
        K = K / K.sum(axis=1, keepdims=True) * rng.uniform(0.5, 1.0, (3, 1))
        edc, _q = keyfit.replay_edc_multi(P2, D, K, rounds=400)
        k = recompute.interval_keys(P2, K)[0]
        pool = np.array(rozdel(int(P2.sum()), D[0].tolist(), k.tolist()))
        assert np.abs(pool - edc[0]).max() <= 400 * 3            # floor() per round and producer
        assert pool.sum() == P2.sum()


def test_split_surplus_is_proportional_whole_and_exact():
    P2 = np.array([[300, 200, 100], [0, 0, 0], [1, 1, 1], [7, 0, 3]])
    surplus = np.array([60, 0, 2, 10])
    out = recompute.split_surplus(P2, surplus)
    assert (out.sum(axis=1) == surplus).all() and (out <= P2).all() and (out >= 0).all()
    assert out[0].tolist() == [30, 20, 10] and out[3].tolist() == [7, 0, 3]


# ---------------------------------------------------------------------------
# The exact method on the pool
# ---------------------------------------------------------------------------


def test_exact_method_shares_the_pool_with_keys_of_the_interval(pool_entry):
    key, P2, D, S, Q, K = pool_entry
    entry = store.get(key)
    data = entry.data
    pair_rows = members.pair_rows(data, members.default_names(data, "cs"))
    out = compute.start_exact(1, key, [], 0, "cs", pair_rows)   # empty cells: the estimate
    assert out["busy"] is True
    _wait(out["job"])
    exact, fit = entry.exact, entry.fit
    assert exact.pool == 3 and fit.pair_keys and exact.keys_estimated
    assert exact.pair_keys == fit.pair_keys and exact.approx is None
    # in every interval the pool's keys are the pair keys weighted by the production then
    P = P2.sum(axis=1)
    kt = recompute.interval_keys(P2, exact.pair_keys)
    got = _shares(data, exact.data)
    for t_ in range(0, len(P), 37):
        assert got[t_].tolist() == list(rozdel(int(P[t_]), D[t_].tolist(), kt[t_].tolist()))
    assert np.allclose(exact.keys, keyfit.pooled_keys(np.array(exact.pair_keys), P2.sum(axis=0)))
    # the producers get the pool's surplus by their production, never more
    U = np.stack([np.round(exact.data.frame[core.key_unshared(p)].to_numpy() * 100)
                  for p in data.source_eans], axis=1).astype(np.int64)
    assert (U.sum(axis=1) + got.sum(axis=1) == P).all() and (U <= P2).all() and (U >= 0).all()
    assert exact.edc_match == pytest.approx(fit.match)
    loss = recompute.grid_loss(data, exact.data)
    assert loss.shared_exact >= loss.shared_edc - 0.01
    entry.exact = None


def test_typed_pair_keys_replay_edc_and_keep_the_estimate_otherwise(pool_entry):
    key, P2, D, S, Q, K = pool_entry
    entry = store.get(key)
    data = entry.data
    entry.fit = keyfit.estimate_pair_keys(P2, D, S, Q)
    rows = members.pair_rows(data, members.default_names(data, "cs"))
    # the estimate typed back from the grid (two decimals of a percent) is the estimate
    est = rows_with(data, rows, entry.fit.pair_keys)
    assert members.pair_problem(members.pair_keys(data, est), entry.fit) is None
    _wait(compute.start_exact(1, key, [], 0, "cs", est)["job"])
    assert entry.exact.keys_estimated and entry.exact.approx is None
    # the contract's keys: one changed -> EDC's method for several producers replayed
    K2 = [row[:] for row in entry.fit.pair_keys]
    K2[0][0] = round(K2[0][0] + 0.02, 4)
    _wait(compute.start_exact(1, key, [], 0, "cs", rows_with(data, rows, K2))["job"])
    ex = entry.exact
    assert not ex.keys_estimated and ex.approx is not None
    assert ex.pair_keys[0][0] == pytest.approx(K2[0][0])
    s, q = keyfit.replay_edc_multi(P2, D, np.array(ex.pair_keys), ex.rounds)
    assert (_shares(data, ex.approx) == s).all()
    U = np.stack([np.round(ex.approx.frame[core.key_unshared(p)].to_numpy() * 100)
                  for p in data.source_eans], axis=1).astype(np.int64)
    assert (P2 - U == q).all()                                # what each producer shared
    # a producer over 100 % is refused, with the reason
    bad = rows_with(data, rows, [[0.6] * len(data.dest_eans)] + K2[1:])
    assert members.pair_problem(members.pair_keys(data, bad), entry.fit) == "pair_sum_over"
    out = compute.start_exact(1, key, [], 0, "cs", bad)
    assert out["cls"] == "progress error" and "100" in out["text"]
    entry.fit = entry.exact = None


def rows_with(data, rows, K):
    return [dict(r, **{members.pair_field(i): members.pct_key(K[i][j])
                       for i in range(len(data.source_eans))})
            for j, r in enumerate(rows)]


# ---------------------------------------------------------------------------
# The page and the export
# ---------------------------------------------------------------------------


def test_page_and_export_say_pool_and_show_the_pair_keys(pool_entry, monkeypatch):
    key, P2, D, S, Q, K = pool_entry
    entry = store.get(key)
    data = entry.data
    entry.fit = keyfit.estimate_pair_keys(P2, D, S, Q)
    entry.exact = recompute.recompute(data, None, keys_estimated=True, rounds=entry.fit.rounds,
                                      pair_keys=entry.fit.pair_keys)
    enabled = set(data.dest_eans)
    # the card: the note up front, the pair-keys grid, the key estimate
    labels = panel._report_labels("cs", key, "production")
    assert "bazén" in labels["exact_pool"].children and "3 výroben" in labels["exact_pool"].children
    cols, style, _ = panel._pair_grid("cs", key, None, None, members.producer_rows(data),
                                      members.rows(data), [])
    assert style == {} and len(cols) == 2 + 3 and "Výroba B" in cols[3]["headerName"]
    pair_rows = members.pair_rows(data, members.default_names(data, "cs"))
    rows = members.rows(data)
    notes, update, pairs = compute.fit_info(1, "cs", key, rows, pair_rows)
    filled = members.pair_keys(data, pairs["update"])
    assert np.allclose(filled, entry.fit.pair_keys, atol=5e-5)       # two decimals of a %
    pool = dict(zip(data.dest_eans, entry.fit.keys))
    assert all(r["key"] == members.pct_key(pool[r["ean"]]) for r in update["update"])
    assert any("dvojici" in str(getattr(n, "children", "")) for n in notes)
    # the column title says pool
    title = method_title("col_exact", 3, "cs")
    assert title == "Přesná statická metoda (přepočet, bazén 3 výroben)"
    monkeypatch.setattr(members, "key_only_edit", lambda: False)   # outside a callback
    out = report.render(key, 1, 0, "exact", None, None, None, "cs", "", "production", "light",
                        rows, members.producer_rows(data), None)
    assert out["head_b"] == title
    result = views.exact_result(entry.exact, data, enabled, members.default_names(data, "cs"),
                                "cs")
    assert "klíče bazénu" in str(result)
    # the export: the same title, the pool, and the pair keys
    names = members.default_names(data, "cs")
    wb = load_workbook(io.BytesIO(export.summary_xlsx(entry, enabled, names, "cs")))
    summary = list(wb[t("x_sheet_summary", "cs")].iter_rows(values_only=True))
    heads = [r for r in summary if r[0] == t("x_item", "cs")]
    assert title in heads[1]
    assert [r for r in summary if r[0] == t("x_pool", "cs")]
    pairs_sheet = list(wb[t("x_sheet_pairs", "cs")].iter_rows(values_only=True))
    body = [r for r in pairs_sheet[2:] if r[0] != "Σ"]
    assert len(body) == len(data.dest_eans)
    for j, r in enumerate(body):
        assert list(r[2:5]) == pytest.approx([100 * entry.fit.pair_keys[i][j] for i in range(3)])
        assert r[5] == pytest.approx(100 * entry.fit.keys[j])
    # a key typed in the grid and not recomputed yet: the export shows the grid
    K2 = [row[:] for row in entry.fit.pair_keys]
    K2[2][1] = 0.05
    typed = members.merged_pair_keys(members.pair_keys(data, rows_with(data, pair_rows, K2)),
                                     entry.fit)
    wb = load_workbook(io.BytesIO(export.summary_xlsx(entry, enabled, names, "cs",
                                                      pair_keys=typed)))
    sheet = list(wb[t("x_sheet_pairs", "cs")].iter_rows(values_only=True))
    assert sheet[0][0].endswith(t("keys_user", "cs"))
    assert sheet[3][4] == pytest.approx(5.0)
    pool_typed = members.pool_keys(data, typed)
    assert sheet[3][5] == pytest.approx(100 * pool_typed[1])
    # one producer: no pool anywhere
    assert method_title("col_exact", 1, "cs") == t("col_exact", "cs")
    entry.fit = entry.exact = None


def test_rows_away_from_the_period_are_left_out():
    P, D, S, _ = synthetic_group(3, 96 * 3, 5, seed=2)
    good = all_report_csv(P, D, S, start="2026-03-01")
    stray = all_report_csv(P[:4], D[:4], S[:4], start="2026-01-31 23:00")
    csv = good + b"\n".join(stray.split(b"\n")[1:])
    data = core.load_report(csv)
    assert data.n_rows == 96 * 3
    assert data.frame.index.min() == np.datetime64("2026-03-01T00:00")
    assert any("31.01.2026" in n and "4 rows" in n for n in data.notes)
    # a report with a real gap of whole days keeps both parts
    two = all_report_csv(P[:96], D[:96], S[:96], start="2026-03-01") + b"\n".join(
        all_report_csv(P[:96], D[:96], S[:96], start="2026-03-05").split(b"\n")[1:])
    assert core.load_report(two).n_rows == 192
