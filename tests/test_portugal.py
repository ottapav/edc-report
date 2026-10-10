import io
import json
import os
import random
import zipfile

import pandas as pd
import pytest

from portugal import cli, eredes, exemplo, partilha


def test_fixed_mode_leaves_the_unused_share_as_surplus():
    # E = 1 kWh, coefficients 50/30/20 %, consumption 0.1 / 0.5 / 0.8 kWh
    J, C, k = [1000, 0, 0, 0], [0, 100, 500, 800], [0.0, 0.5, 0.3, 0.2]
    assert partilha.fixed_erse(J, C, k) == [0, 100, 300, 200]          # 0.6 kWh shared
    s, m = partilha.exact(J, C, k)
    assert s == [0, 100, 500, 400] and m[0] == s                         # all 1 kWh shared
    assert partilha.proportional_erse(J, C) == [0, 71, 357, 572]


def test_installation_injecting_now_cannot_receive_and_its_share_moves_on():
    # installation 1 is a prosumer injecting in this interval (art. 28(4), 29(3))
    J, C, k = [600, 400, 0, 0], [0, 0, 900, 900], [0.0, 0.5, 0.25, 0.25]
    f = partilha.fixed_erse(J, C, k)
    assert f == [0, 0, 500, 500]          # 0.5 split over the others in ratio 1:1
    s, m = partilha.exact(J, C, k)
    assert s == [0, 0, 500, 500]
    # each producer gives the same share of its injection
    assert m[0][2] == 300 and m[1][2] == 200


def test_unallocated_part_is_kept_unless_asked():
    J, C, k = [1000, 0, 0], [0, 900, 900], [0.0, 0.4, 0.4]               # 20 % unallocated
    assert sum(partilha.exact(J, C, k)[0]) == 800
    assert sum(partilha.exact(J, C, k, keep_unallocated=False)[0]) == 1000
    assert sum(partilha.fixed_erse(J, C, k)) == 800


def test_random_intervals_exact_is_maximal_and_never_below_fixed():
    rng = random.Random(7)
    for _ in range(3000):
        n = rng.randint(2, 12)
        J = [rng.choice([0, 0, rng.randint(1, 20000)]) for _ in range(n)]
        C = [0 if J[i] else rng.randint(0, 3000) for i in range(n)]
        w = [rng.random() if rng.random() < 0.9 else 0.0 for _ in range(n)]
        tot = sum(w) or 1
        k = [x / tot for x in w]
        f = partilha.fixed_erse(J, C, k)
        s, m = partilha.exact(J, C, k)
        E = sum(J)
        usable = sum(C[i] for i in range(n) if k[i] > 0)
        assert sum(s) == min(E, usable)
        assert all(0 <= s[i] <= C[i] for i in range(n))
        assert all(f[i] <= C[i] for i in range(n)) and sum(f) <= sum(s)
        assert [sum(col) for col in zip(*m)] == s
        assert all(sum(m[p]) <= J[p] for p in range(n))


@pytest.fixture(scope="module")
def period_and_matrices(tmp_path_factory):
    d = tmp_path_factory.mktemp("pt")
    data, coefs = exemplo.synthetic("2026-06-01", "2026-06-07", seed=1)
    data.to_csv(d / "dados.csv", sep=";", index=False)
    coefs.to_csv(d / "coeficientes.csv", sep=";", index=False)
    period = eredes.read_period(d / "dados.csv", d / "coeficientes.csv")
    cmp_, mats = partilha.compare(period.cpes, period.injections, period.consumption,
                                  period.coef)
    return d, period, cmp_, mats


def test_reading_keeps_the_coefficient_order_and_converts_to_wh(period_and_matrices):
    _, period, cmp_, _ = period_and_matrices
    assert len(period.starts) == 7 * 96 and period.warnings == []
    assert abs(sum(period.coef) - 1) < 1e-9 and period.coef[-1] == 0.0  # IPr listed last
    assert period.producers == [0, len(period.cpes) - 1]     # prosumer flat and the IPr
    assert cmp_.exact == cmp_.maximum and cmp_.fixed < cmp_.exact
    assert cmp_.proportional == cmp_.maximum


@pytest.mark.parametrize("decimals", [3, 4, 6])
def test_rounded_coefficients_never_allocate_above_consumption(period_and_matrices, decimals):
    _, period, cmp_, mats = period_and_matrices
    co = eredes.to_coefficients(period, mats, decimals)
    n = len(period.cpes)
    applied = 0.0
    for t in range(len(mats)):
        J, C = period.injections[t], period.consumption[t]
        got = [0.0] * n
        per_prod = {}
        for (c, p), v in co.values.items():
            got[c] += v[t] * J[p]
            per_prod[p] = per_prod.get(p, 0) + v[t]
        assert all(got[c] <= C[c] + 1e-6 for c in range(n))
        assert all(x <= 1 + 1e-9 for x in per_prod.values())
        applied += sum(got)
    assert abs(applied - co.applied_total) < 1e-3
    # rounding can only lose: at most one unit per pair and interval
    bound = sum(10 ** -decimals * J[p] for t, J in enumerate(period.injections)
                for (c, p) in co.values)
    assert 0 <= co.rounding_loss <= bound
    assert co.exact_total == cmp_.exact
    if decimals == 6:
        assert co.rounding_loss / co.exact_total < 1e-3


def test_quarter_hour_labels_with_clock_changes():
    def day(d):
        nxt = (pd.Timestamp(d) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        idx = pd.date_range(pd.Timestamp(d, tz=eredes.TZ), pd.Timestamp(nxt, tz=eredes.TZ),
                            freq="15min", inclusive="left")   # local midnight to midnight
        return eredes.quarter_hour_labels(idx)
    normal = day("2026-06-01")
    assert len(normal) == 96 and normal[0] == ("20260601", "0015") and normal[-1][1] == "2400"
    autumn = day("2026-10-25")
    assert len(autumn) == 100 and [q for _, q in autumn[-4:]] == ["2415", "2430", "2445", "2500"]
    spring = day("2026-03-29")
    assert len(spring) == 92 and spring[-1][1] == "2400"
    assert len({q for _, q in spring}) == 92


def test_naive_lisbon_times_on_the_autumn_day_are_inferred(tmp_path):
    idx = pd.date_range(pd.Timestamp("2026-10-25", tz=eredes.TZ), periods=100, freq="15min")
    naive = idx.tz_localize(None).strftime("%Y-%m-%d %H:%M")
    rows = pd.DataFrame({"timestamp": list(naive) * 2,
                         "cpe": ["A"] * 100 + ["B"] * 100,
                         "consumption_kwh": [0] * 100 + ["0,5"] * 100,
                         "injection_kwh": ["1,0"] * 100 + [0] * 100})
    rows.to_csv(tmp_path / "d.csv", sep=";", index=False)
    (tmp_path / "k.csv").write_text("cpe;coefficient\nB;100\n")
    p = eredes.read_period(tmp_path / "d.csv", tmp_path / "k.csv")
    assert len(p.starts) == 100 and p.coef == [1.0, 0.0]
    assert p.consumption[0] == [500, 0] and p.injections[0] == [0, 1000]


def test_bad_coefficients_are_rejected(tmp_path):
    (tmp_path / "k.csv").write_text("cpe;coefficient\nA;0,7\nB;0,6\n")
    with pytest.raises(ValueError, match="more than 1"):
        eredes.read_coefficients(tmp_path / "k.csv")


def test_cli_writes_report_members_and_one_file_per_pair(period_and_matrices, tmp_path):
    d, period, cmp_, _ = period_and_matrices
    rep = cli.run(d / "dados.csv", d / "coeficientes.csv", str(tmp_path), generated="20261010",
                  quiet=True)
    assert json.load(open(tmp_path / "report.json"))["lost_kwh"] == rep["lost_kwh"]
    assert rep["lost_kwh"] == round((cmp_.exact - cmp_.fixed) / 1000, 3) > 0
    z = zipfile.ZipFile(io.BytesIO(open(tmp_path / "coeficientes_dinamicos.zip", "rb").read()))
    names = z.namelist()
    assert len(names) == rep["coefficient_files"]
    first = z.read(names[0]).decode().splitlines()
    assert len(first) == 7 * 96
    date, qh, cons, prod, val = first[0].split(";")
    assert names[0] == f"Coeficiente_Partilha_{cons}_{prod}_202606_20261010_01.csv"
    assert date == "20260601" and qh == "0015" and len(val.split(".")[1]) == 3
    assert os.path.exists(tmp_path / "membros.csv")


def test_gecad_times_accept_text_serials_with_float_noise_and_cpes_are_20_chars():
    from portugal import gecad
    col = pd.Series(["31/03/2019 00:45:00", 43555.041666666664, 43555.0520833334])
    assert list(gecad.parse_times(col)) == [pd.Timestamp("2019-03-31 00:45"),
                                            pd.Timestamp("2019-03-31 01:00"),
                                            pd.Timestamp("2019-03-31 01:15")]
    assert {len(gecad.cpe(k, 15)) for k in "PCS"} == {20}
