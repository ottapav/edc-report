"""Export of the summary: the sheets follow what was computed, the numbers match the
page's own sources, the selection and the EAN anonymity are respected."""
import io
import time

import pytest
from openpyxl import load_workbook

import edc_data as core
import export
import jobs
import keyfit
import recompute
import store
from conftest import all_report_csv, synthetic_group
from i18n import t
from ui import compute, members
from ui import export as ui_export


@pytest.fixture
def entry_key():
    P, D, S, k = synthetic_group(5, 96 * 20, 5, keys=[0.1, 0.5, 0.1, 0.1, 0.1], seed=3)
    key = store.put("t.csv", core.load_report(all_report_csv(P, D, S)))
    yield key, (P, D, S, k)
    store.drop(key)


def _book(entry, enabled=None, lang="cs", **kw):
    data = entry.data
    enabled = set(data.dest_eans) if enabled is None else enabled
    raw = export.summary_xlsx(entry, enabled, members.default_names(data, lang), lang, **kw)
    return load_workbook(io.BytesIO(raw))


def _cells(ws):
    return [c for row in ws.iter_rows(values_only=True) for c in row if c is not None]


def _row(ws, label):
    for row in ws.iter_rows(values_only=True):
        if row and row[0] == label:
            return row
    raise KeyError(label)


def _billed(key):
    entry = store.get(key)
    rows = [{"ean": e, "price": 4.0 + 0.3 * j} for j, e in enumerate(entry.data.dest_eans)]
    job_id = compute.start_bill(1, key, rows, [], 1.2, None, "cs", price_mode="each")["job"]
    job, t0 = jobs.get(job_id), time.perf_counter()
    while not job.done and time.perf_counter() - t0 < 60:
        time.sleep(0.05)
    assert job.done and job.error is None and entry.bill is not None
    return entry


def test_report_only_has_summary_destinations_and_daily(entry_key):
    key, _ = entry_key
    entry = store.get(key)
    wb = _book(entry)
    assert wb.sheetnames == [t("x_sheet_summary", "cs"), t("x_sheet_members", "cs"),
                             t("x_sheet_daily", "cs")]
    s = core.summarize(entry.data, set(entry.data.dest_eans))
    summary = wb[t("x_sheet_summary", "cs")]
    assert _row(summary, t("kpi_production", "cs"))[1] == pytest.approx(s.production, abs=0.01)
    assert _row(summary, t("kpi_shared", "cs"))[1] == pytest.approx(s.shared, abs=0.01)
    # the per-destination table adds up like the page's
    df = core.per_destination(entry.data)
    dest = wb[t("x_sheet_members", "cs")]
    assert _row(dest, "Σ")[4] == pytest.approx(df["shared"].sum(), abs=0.01)
    # daily rows add up to the totals
    daily = wb[t("x_sheet_daily", "cs")]
    assert daily.max_row == 1 + 20 + 1          # head, 20 days, Σ
    col = {h: i for i, h in enumerate(_row(daily, t("x_date", "cs")))}
    total = _row(daily, "Σ")
    assert total[col["Výroba [kWh]"]] == pytest.approx(s.production, abs=0.05)
    assert total[col[t("x_shared_sel", "cs")]] == pytest.approx(s.shared, abs=0.05)


def test_selection_and_ean_anonymity(entry_key):
    key, _ = entry_key
    entry = store.get(key)
    data = entry.data
    enabled = set(data.dest_eans[:2])
    wb = _book(entry, enabled, lang="en")
    cells = [str(c) for ws in wb for c in _cells(ws)]
    assert not any(e in c for e in data.dest_eans + data.source_eans for c in cells)
    assert f"…{data.dest_eans[0][-3:]}" in cells
    s = core.summarize(data, enabled)
    summary = wb[t("x_sheet_summary", "en")]
    assert _row(summary, t("kpi_shared", "en"))[1] == pytest.approx(s.shared, abs=0.01)
    assert _row(summary, t("kpi_wasted_max", "en"))      # at most, before the recompute
    dest = wb[t("x_sheet_members", "en")]
    flags = [r[2] for r in dest.iter_rows(min_row=2, values_only=True) if r[0] != "Σ"]
    assert flags == ["yes", "yes", "no", "no", "no"]
    full = [str(c) for ws in _book(entry, enabled, "en", full_ean=True) for c in _cells(ws)]
    assert data.dest_eans[0] in full and data.source_eans[0] in " ".join(full)


def test_exact_billing_and_fit_add_their_sheets(entry_key):
    key, (P, D, S, k) = entry_key
    entry = store.get(key)
    entry.fit = keyfit.estimate_keys(P, D, S)
    entry.exact = recompute.recompute(entry.data, list(k), rounds=5, keys_estimated=True)
    _billed(key)
    data = entry.data
    enabled = set(data.dest_eans[1:])
    wb = _book(entry, enabled, group="0000018947")
    assert wb.sheetnames == [t(f"x_sheet_{s}", "cs") for s in
                             ("summary", "members", "compare", "bill", "daily")]
    summary = wb[t("x_sheet_summary", "cs")]
    loss = recompute.grid_loss(data, entry.exact.data, enabled)
    assert _row(summary, t("x_loss_kwh", "cs"))[1] == pytest.approx(loss.lost, abs=0.01)
    # energy: the exact column next to the report, "could have been shared" = the gain
    heads = [r for r in summary.iter_rows(values_only=True) if r[0] == t("x_item", "cs")]
    assert heads[1][1:4] == (t("col_edc", "cs"), t("col_exact", "cs"), t("x_unit", "cs"))
    wasted = _row(summary, t("kpi_wasted", "cs"))
    assert wasted[1] == pytest.approx(core.exact_gain(data, entry.exact.data, enabled), abs=0.01)
    assert wasted[2] == 0
    assert "0000018947" in _cells(summary)[0]
    cmp = wb[t("x_sheet_compare", "cs")]
    sigma = [r for r in cmp.iter_rows(values_only=True) if str(r[0]).startswith("Σ")][0]
    assert sigma[6] - sigma[5] == pytest.approx(loss.lost, abs=0.02)
    bill = entry.bill.settlement
    rows = list(wb[t("x_sheet_bill", "cs")].iter_rows(values_only=True))
    assert _row(wb[t("x_sheet_bill", "cs")], "Σ")[7] == pytest.approx(bill.payment.sum(), abs=0.01)
    assert len(rows) == 1 + len(data.dest_eans) + 1 + len(data.source_eans)
    assert _row(summary, t("x_rounds", "cs"))[1] == entry.fit.rounds
    # keys other than the report's: the energy table compares with EDC replayed with them
    entry.exact = recompute.recompute(data, list(k), rounds=5)
    summary = _book(entry, enabled)[t("x_sheet_summary", "cs")]
    heads = [r for r in summary.iter_rows(values_only=True) if r[0] == t("x_item", "cs")]
    # the page shows the report next to the billing and the replay next to the exact
    # method, so the export has all three
    assert heads[1][1:5] == (t("col_edc", "cs"), t("col_edc_replay", "cs"),
                             t("col_exact", "cs"), t("x_unit", "cs"))
    # with unticked members "could have been shared" of the report is an upper bound, in
    # a row of its own like the tile ("at most"); the other two are what the exact adds
    report = core.summarize(data, enabled)
    at_most = _row(summary, t("kpi_wasted_max", "cs"))
    assert at_most[1] == pytest.approx(report.overlap, abs=0.01) and at_most[2:4] == (None, None)
    gain = _row(summary, t("kpi_wasted", "cs"))
    assert gain[1] is None
    assert gain[2] == pytest.approx(core.exact_gain(entry.exact.approx, entry.exact.data, enabled),
                                    abs=0.01)
    assert gain[3] == 0
    # the daily sheet has the series of every daily plot
    daily = _book(entry, enabled)[t("x_sheet_daily", "cs")]
    head = _row(daily, t("x_date", "cs"))
    total = _row(daily, "Σ")
    for d, suffix in ((data, ""), (entry.exact.approx, f" – {t('x_m_replay', 'cs')}"),
                      (entry.exact.data, f" – {t('x_m_exact', 'cs')}")):
        shared = core.summarize(d, enabled).shared
        assert total[head.index(t("x_shared_sel", "cs") + suffix)] == pytest.approx(shared, abs=0.05)
    entry.fit = entry.exact = entry.bill = None


def test_download_is_a_link_with_the_name_and_extension(entry_key):
    """The workbook is served as an attachment under its name (a blob download lost the
    name and the extension on Safari and on phones)."""
    import app
    key, _ = entry_key
    data = store.get(key).data
    url = ui_export.summary_file(key, None, [], [], "de", " Gruppe 7 ", ["full"])
    name = export.file_name(data, "de", "Gruppe 7")
    assert name.startswith("edc-zusammenfassung-Gruppe-7-2026-06-01_") and name.endswith(".xlsx")
    assert url.startswith("/export/") and url.endswith("/" + name)
    client = app.server.test_client()
    for _ in range(2):                          # some browsers fetch a download twice
        r = client.get(url)
        assert r.status_code == 200 and r.mimetype == export.XLSX_MIME
        assert f'filename={name}' in r.headers["Content-Disposition"]
        assert r.headers["Content-Disposition"].startswith("attachment")
        assert load_workbook(io.BytesIO(r.data)).sheetnames[0] == t("x_sheet_summary", "de")
    assert client.get("/export/nope/x.xlsx").status_code == 404
    assert ui_export.summary_file("gone", None, [], [], "cs", "", []) is None


def test_prepared_files_expire_and_are_bounded(monkeypatch):
    tokens = [store.put_file(f"{i}.xlsx", b"x") for i in range(store.FILE_MAX + 5)]
    assert store.get_file(tokens[0]) is None and store.get_file(tokens[-1]).name.endswith(".xlsx")
    monkeypatch.setattr(store, "FILE_TTL_S", -1)
    assert store.get_file(tokens[-1]) is None
