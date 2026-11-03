"""Several producers: loaded as one pool, keys estimated for the pool, the exact static
method shares the pool, and the page and the export say so."""
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
from ui import compute, members, panel, report, views


def _pool_report(n=5, days=20, producers=3, seed=6):
    """Members share the producers' total production as one pool (today's EDC method)
    with known keys; each producer supplies the same part of its production."""
    keys = [0.3, 0.25, 0.2, 0.1, 0.05][:n]
    P, D, S, k = synthetic_group(n, 96 * days, 5, keys=keys, seed=seed)
    split = np.linspace(1.0, 0.6, producers)
    P3 = np.floor(P[:, None] * split / split.sum()).astype(np.int64)
    P3[:, 0] += P - P3.sum(axis=1)                       # adds up to P exactly
    surplus = recompute.split_surplus(P3, P - S.sum(axis=1))
    return all_report_csv(P3, D, S, supplied=P3 - surplus), P3, D, S, np.array(k)


@pytest.fixture
def pool_entry():
    csv, P3, D, S, k = _pool_report()
    key = store.put("pool.csv", core.load_report(csv))
    yield key, P3, D, S, k
    store.drop(key)


def _wait(job_id, seconds=120):
    job, t0 = jobs.get(job_id), time.perf_counter()
    while not job.done and time.perf_counter() - t0 < seconds:
        time.sleep(0.05)
    assert job.done and job.error is None and job.error_key is None


def test_split_surplus_is_proportional_whole_and_exact():
    P2 = np.array([[300, 200, 100], [0, 0, 0], [1, 1, 1], [7, 0, 3]])
    surplus = np.array([60, 0, 2, 10])
    out = recompute.split_surplus(P2, surplus)
    assert (out.sum(axis=1) == surplus).all() and (out <= P2).all() and (out >= 0).all()
    assert out[0].tolist() == [30, 20, 10] and out[3].tolist() == [7, 0, 3]


def test_pool_report_estimates_the_keys_of_the_pool(pool_entry):
    key, P3, D, S, k = pool_entry
    data = store.get(key).data
    P, D2, S2 = recompute.to_hundredths(data)
    assert (P == P3.sum(axis=1)).all() and (D2 == D).all() and (S2 == S).all()
    fit = keyfit.estimate_keys(P, D2, S2)
    assert fit.match > 0.97
    assert np.allclose(fit.keys, k, atol=0.006)


def test_exact_method_shares_the_pool(pool_entry):
    key, P3, D, S, k = pool_entry
    entry = store.get(key)
    data = entry.data
    rows = [{"ean": e, "key": None} for e in data.dest_eans]
    out = compute.start_exact(1, key, rows, 0, "cs")         # not refused any more
    assert out["busy"] is True
    _wait(out["job"])
    exact = entry.exact
    assert exact.pool == 3 and entry.fit is not None
    # the shares are rozdel() of the pool's production, interval by interval
    from presna_staticka import rozdel
    P = P3.sum(axis=1)
    got = np.stack([np.round(exact.data.frame[core.key_shared(core.POOL, e)].to_numpy() * 100)
                    for e in data.dest_eans], axis=1).astype(np.int64)
    for t_ in range(0, len(P), 97):
        assert got[t_].tolist() == list(rozdel(int(P[t_]), D[t_].tolist(), exact.keys))
    # every producer gets the surplus in proportion to its production, never more
    U = np.stack([np.round(exact.data.frame[core.key_unshared(p)].to_numpy() * 100)
                  for p in data.source_eans], axis=1).astype(np.int64)
    assert (U.sum(axis=1) + got.sum(axis=1) == P).all() and (U <= P3).all() and (U >= 0).all()
    # it shares at least what the report shared, and the summaries add up
    loss = recompute.grid_loss(data, exact.data)
    assert loss.shared_exact >= loss.shared_edc - 0.01
    s = core.summarize(exact.data, set(data.dest_eans))
    assert s.shared + s.unshared == pytest.approx(s.production, abs=0.05)
    entry.exact = None


def test_keys_read_back_from_the_grid_are_the_estimate(pool_entry):
    """The grid shows the estimated keys in percent with two decimals; pressing the
    button without changing them recomputes with the estimate (not "entered keys",
    and no replay): 1.04 % read back is 0.0104, the estimate 0.010400000000000001."""
    key, *_ = pool_entry
    entry = store.get(key)
    data = entry.data
    entry.fit = keyfit.estimate_keys(*recompute.to_hundredths(data))
    entry.fit.keys = [0.010400000000000001] + [0.1] * (len(data.dest_eans) - 1)
    rows = [{"ean": e, "key": members.pct_key(k)} for e, k in zip(data.dest_eans, entry.fit.keys)]
    typed = members.keys(data, rows)
    assert typed[0] != entry.fit.keys[0]                       # the float noise is real
    _wait(compute.start_exact(1, key, rows, 0, "cs")["job"])
    assert entry.exact.keys_estimated and entry.exact.approx is None
    assert entry.exact.keys == entry.fit.keys
    entry.fit = entry.exact = None


def test_page_and_export_say_pool(pool_entry, monkeypatch):
    key, P3, D, S, k = pool_entry
    entry = store.get(key)
    data = entry.data
    entry.fit = keyfit.estimate_keys(*recompute.to_hundredths(data))
    entry.exact = recompute.recompute(data, list(entry.fit.keys), keys_estimated=True,
                                      rounds=entry.fit.rounds)
    enabled = set(data.dest_eans)
    # the card: the note up front (panel), the key estimate, the column title
    labels = panel._report_labels("cs", key, "production")
    assert "bazén" in labels["exact_pool"].children and "3 výroben" in labels["exact_pool"].children
    assert labels["exact_title"] == ""
    rows = members.rows(data)
    notes, _ = views.fit_summary(entry.fit, data, rows, "cs")
    assert any("bazén 3 výroben" in str(getattr(n, "children", "")) for n in notes)
    title = method_title("col_exact", 3, "cs")
    assert title == "Přesná statická metoda (přepočet, bazén 3 výroben)"
    monkeypatch.setattr(members, "key_only_edit", lambda: False)   # outside a callback
    out = report.render(key, 1, 0, "exact", None, None, None, "cs", "", "production", "light",
                        rows, members.producer_rows(data), None)
    assert out["head_b"] == title
    # the export: the same column title and the pool in the summary
    names = members.default_names(data, "cs")
    wb = load_workbook(io.BytesIO(export.summary_xlsx(entry, enabled, names, "cs")))
    summary = [r for r in wb[t("x_sheet_summary", "cs")].iter_rows(values_only=True)]
    heads = [r for r in summary if r[0] == t("x_item", "cs")]
    assert title in heads[1]
    pool_rows = [r for r in summary if r[0] == t("x_pool", "cs")]
    assert pool_rows and all(r[1] == 3 for r in pool_rows)
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
