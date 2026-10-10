"""Web app: a Portuguese upload is told apart from a Czech one and shown in English only."""
import base64
import io
import time
import zipfile

import pytest

import app
from conftest import all_report_csv, synthetic_group
from portugal import exemplo


def _b64(content: bytes) -> str:
    return "data:text/csv;base64," + base64.b64encode(content).decode()


@pytest.fixture(scope="module")
def pt_upload():
    data, coefs = exemplo.synthetic("2026-06-01", "2026-06-03", seed=4)
    files = [("dados.csv", data.to_csv(sep=";", index=False).encode()),
             ("coeficientes.csv", coefs.to_csv(sep=";", index=False).encode())]
    return [_b64(c) for _, c in files], [n for n, _ in files], coefs


@pytest.fixture(scope="module")
def cz_upload():
    P, D, S, _ = synthetic_group(4, 96 * 3, 5, seed=5)
    return _b64(all_report_csv(P, D, S)), "edc.csv"


def _wait(job_id, seconds=30):
    job = app._JOBS[job_id]
    t0 = time.perf_counter()
    while not job["done"] and time.perf_counter() - t0 < seconds:
        time.sleep(0.05)
    assert job["done"]
    return job


def test_portuguese_upload_is_english_only_and_czech_gets_cz_en_back(pt_upload, cz_upload):
    contents, names, coefs = pt_upload
    out = app._on_upload(contents, names, "cs", None, None)
    key, rows, cols = out[0], out[11], out[12]
    lang, options, keep = out[-3:]
    entry = app._cache_get(key)
    assert entry.pt is not None and entry.data.country == "PT"
    assert entry.filename == "dados.csv + coeficientes.csv"
    assert lang == "pt" and options == app.LANGS_PT and keep == "cs"
    assert out[9] is app.no_update                       # no key estimate for Portugal
    assert [r["key"] for r in rows] == [round(100 * c, 2) for c in coefs["coefficient"]]
    assert cols[1]["headerName"] == "CPE" and rows[0]["default_pt"] == "Member 1"
    # back to a Czech report: the CZ/EN switch returns with the earlier choice
    out = app._on_upload(cz_upload[0], cz_upload[1], "pt", "cs", key)
    assert app._cache_get(key) is None                   # the Portuguese upload was freed
    assert out[-3:] == ("cs", app.LANGS_CZ, app.no_update)
    assert out[12][1]["headerName"] == "EAN"
    app._cache_drop(out[0])


def test_czech_upload_in_english_stays_english(cz_upload):
    out = app._on_upload(cz_upload[0], cz_upload[1], "en", None, None)
    assert out[-3:] == (app.no_update, app.LANGS_CZ, app.no_update)
    app._cache_drop(out[0])


def test_unrecognised_upload_is_reported_and_keeps_the_language():
    out = app._on_upload(_b64(b"a;b\n1;2\n"), "x.csv", "cs", None, None)
    assert out[0] is None and "unrecognised" in str(out[1])
    assert out[-3:] == (app.no_update,) * 3


def test_portuguese_recompute_and_export(pt_upload):
    contents, names, coefs = pt_upload
    key = app._on_upload(contents, names, "cs", None, None)[0]
    try:
        entry = app._cache_get(key)
        fixed_before = entry.data
        job = _wait(app._start_background("recompute", key, [None] * len(coefs), 0.0, "pt")[0])
        assert job["error"] is None and not job.get("error_key")
        assert entry.exact is not None and entry.exact.keys_estimated
        assert entry.data is not fixed_before                # column A rebuilt for the keys
        assert app._stale(None, [], 0, 1, "pt", key) == []   # no reserve input in Portugal
        style, btn, hint, _ = app._export_box(1, key, "pt")
        assert style == {} and "ZIP" in btn
        sent, info = app._export(1, key, "pt")
        assert sent["filename"] == "coeficientes_dinamicos_202606.zip"   # one month
        z = zipfile.ZipFile(io.BytesIO(base64.b64decode(sent["content"])))
        assert len(z.namelist()) > 1 and "files" in info and "1 month" in info
        # half the coefficients: half of the energy stays unallocated in both columns
        half = [c / 2 for c in entry.pt.base_coef]
        _wait(app._start_background("recompute", key, half, 0.0, "pt")[0])
        assert entry.exact.reserve == pytest.approx(0.5) and not entry.exact.keys_estimated
    finally:
        app._cache_drop(key)


def test_export_box_is_hidden_for_czech_reports(cz_upload):
    key = app._on_upload(cz_upload[0], cz_upload[1], "cs", None, None)[0]
    try:
        assert app._export_box(0, key, "cs")[0] == {"display": "none"}
    finally:
        app._cache_drop(key)
