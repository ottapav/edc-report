"""Portugal in the web app: detection, the pooled report, both columns, the ZIP export."""
import io
import zipfile

import numpy as np
import pytest

from conftest import all_report_csv, synthetic_group
from edc_data import key_shared
from portugal import exemplo, partilha
from portugal import report as ptr


def _csv(df) -> bytes:
    return df.to_csv(sep=";", index=False).encode()


@pytest.fixture(scope="module")
def files():
    data, coefs = exemplo.synthetic("2026-06-01", "2026-06-05", seed=2)
    return [("dados.csv", _csv(data)), ("coeficientes.csv", _csv(coefs))]


@pytest.fixture(scope="module")
def loaded(files):
    return ptr.load(files)


def test_country_is_detected_from_the_files(files):
    P, D, S, _ = synthetic_group(3, 96, 5, seed=1)
    edc = ("r.csv", all_report_csv(P, D, S))
    assert ptr.kind(*edc) == "edc" and ptr.country_of([edc]) == "CZ"
    assert [ptr.kind(n, c) for n, c in files] == ["pt-data", "pt-coef"]
    assert ptr.country_of(files) == "PT" and ptr.country_of(files[:1]) == "PT"
    with pytest.raises(ValueError, match="coefficients file"):
        ptr.country_of(files[1:])
    with pytest.raises(ValueError, match="one EDC report"):
        ptr.country_of([edc, edc])
    with pytest.raises(ValueError, match="unrecognised"):
        ptr.country_of([("x.csv", b"a;b\n1;2\n")])


def test_members_producers_and_report_shape(loaded):
    data, pt = loaded
    assert data.country == "PT" and data.source_eans == [ptr.POOL] and data.fmt == "all"
    # 12 members with a coefficient (prosumer flat, 10 flats, shop); the IPr is a producer
    assert len(pt.members) == 12 and len(pt.producers) == 2
    assert data.producer_ids == [pt.period.cpes[i] for i in pt.producers]
    assert abs(sum(pt.base_coef) - 1) < 1e-9
    assert len(data.frame) == 5 * 96 == len(pt.P)
    assert np.isclose(data.production.sum(), pt.P.sum() / 1000)


def test_fixed_column_equals_the_reference_per_interval(loaded):
    _, pt = loaded
    S = ptr.fixed_shares(pt, pt.base_coef)
    full = [0.0] * len(pt.period.cpes)
    for i, c in zip(pt.members, pt.base_coef):
        full[i] = c
    for t in range(len(pt.P)):
        ref = partilha.fixed_erse(pt.period.injections[t], pt.period.consumption[t], full)
        assert list(S[t]) == [ref[i] for i in pt.members], t


def test_recompute_matches_the_exact_reference_and_never_loses(loaded):
    data, pt = loaded
    base, rec = ptr.recompute(pt, pt.base_coef)
    cmp_, _ = partilha.compare(pt.period.cpes, pt.period.injections, pt.period.consumption,
                               [dict(zip(pt.members, pt.base_coef)).get(i, 0.0)
                                for i in range(len(pt.period.cpes))])
    shared = lambda d: sum(d.frame[c].sum() for c in d.frame if c.startswith("shared|"))  # noqa
    fixed_kwh, exact_kwh = shared(base), shared(rec.data)
    assert abs(fixed_kwh - cmp_.fixed / 1000) < 1e-6
    # pooled single-source rozdel vs per-producer bazen: same up to rounding per interval
    assert abs(exact_kwh - cmp_.exact / 1000) <= len(pt.P) / 1000
    assert exact_kwh > fixed_kwh
    assert rec.keys_estimated and rec.rounds == 0 and rec.reserve == pytest.approx(0, abs=1e-9)
    # nobody gets more than consumed, nobody receives while injecting
    S = np.column_stack([rec.data.frame[key_shared(ptr.POOL, pt.period.cpes[i])].to_numpy()
                         for i in pt.members]) * 1000
    assert (S <= pt.D + 1e-6).all() and (S[pt.J > 0] == 0).all()


def test_recompute_rejects_bad_coefficients_and_keeps_the_unallocated_part(loaded):
    _, pt = loaded
    with pytest.raises(ValueError, match="more than 100"):
        ptr.recompute(pt, [0.2] * len(pt.members))
    with pytest.raises(ValueError, match="> 0"):
        ptr.recompute(pt, [0.0] * len(pt.members))
    half = [c / 2 for c in pt.base_coef]
    _, rec = ptr.recompute(pt, half)
    assert rec.reserve == pytest.approx(0.5) and not rec.keys_estimated


def test_equal_shares_without_a_coefficients_file(files):
    data, pt = ptr.load(files[:1])
    assert pt.period.equal_shares
    assert len(set(round(c, 9) for c in pt.base_coef if c > 0)) == 1
    assert any("equal shares" in n for n in data.notes)


def test_export_zip_has_one_file_per_pair_and_a_readme(loaded):
    _, pt = loaded
    blob, summary = ptr.export_zip(pt, pt.base_coef, generated="20261010")
    z = zipfile.ZipFile(io.BytesIO(blob))
    names = z.namelist()
    assert names[0] == "LEIA-ME_README.txt" and len(names) == summary["files"] + 1
    assert summary["files"] == summary["pairs"] * len(summary["months"])
    assert all(n.startswith("Coeficiente_Partilha_") for n in names[1:])
    assert summary["delivered_kwh"] <= summary["exact_kwh"] and summary["fixed_kwh"] > 0
