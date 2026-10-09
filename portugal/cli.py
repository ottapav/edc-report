"""
Sharing error of the fixed mode and the exact allocation as dynamic-mode coefficient files.

    python -m portugal.cli dados.csv coeficientes.csv --out resultado/

Writes to the output folder:
  report.json                  totals, sharing error, per member
  membros.csv                  per member: consumption, fixed, exact, gain (kWh)
  coeficientes_dinamicos.zip   one file per consumer–producer pair (partilha dinâmica)
"""
from __future__ import annotations

import argparse
import json
import os
import time

import pandas as pd

from portugal import eredes, partilha


def run(data, coefs, out: str, decimals: int = 3, sep: str = ";", decimal: str = ".",
        header: bool = False, keep_unallocated: bool = True, generated: str | None = None,
        quiet: bool = False) -> dict:
    t0 = time.perf_counter()
    period = eredes.read_period(data, coefs)
    cmp_, matrices = partilha.compare(period.cpes, period.injections, period.consumption,
                                      period.coef, keep_unallocated)
    co = eredes.to_coefficients(period, matrices, decimals)
    generated = generated or pd.Timestamp.now(tz=eredes.TZ).strftime("%Y%m%d")
    files = eredes.coefficient_files(period, co, generated, sep=sep, decimal=decimal,
                                     header=header)
    os.makedirs(out, exist_ok=True)
    rep = cmp_.as_dict()
    rep.update({
        "period": {"first_interval_start": str(period.starts[0]),
                   "last_interval_start": str(period.starts[-1])},
        "coefficient_files": len(files),
        "coefficient_decimals": decimals,
        "applied_by_rounded_coefficients_kwh": round(co.applied_total / 1000, 3),
        "rounding_loss_kwh": round(co.rounding_loss / 1000, 3),
        "warnings": period.warnings,
        "seconds": round(time.perf_counter() - t0, 2),
    })
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    pd.DataFrame(rep["members"]).to_csv(os.path.join(out, "membros.csv"), sep=";", index=False)
    with open(os.path.join(out, "coeficientes_dinamicos.zip"), "wb") as f:
        f.write(eredes.zip_files(files))
    if not quiet:
        print(summary(rep))
    return rep


def summary(r: dict) -> str:
    lines = [
        f"Intervals: {r['intervals']}  ({r['period']['first_interval_start']} … "
        f"{r['period']['last_interval_start']})",
        f"Energy for sharing:      {r['energy_for_sharing_kwh']:10.3f} kWh",
        f"Maximum sharing:         {r['maximum_kwh']:10.3f} kWh",
        f"Fixed coefficients:      {r['fixed_kwh']:10.3f} kWh",
        f"Exact method:            {r['exact_kwh']:10.3f} kWh",
        f"Lost to the grid:        {r['lost_kwh']:10.3f} kWh  "
        f"= {r['sharing_error_pct_of_max']:.2f} % of the maximum, "
        f"{r['lost_pct_of_energy']:.2f} % of the energy for sharing, "
        f"in {r['intervals_with_loss']} intervals",
        f"Dynamic files: {r['coefficient_files']} pairs, {r['coefficient_decimals']} decimals, "
        f"deliver {r['applied_by_rounded_coefficients_kwh']:.3f} kWh "
        f"(rounding loss {r['rounding_loss_kwh']:.3f} kWh)",
    ]
    lines += [f"Warning: {w}" for w in r["warnings"]]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Portugal: fixed-mode sharing error and exact "
                                             "dynamic-mode coefficients")
    ap.add_argument("data", help="15-min data CSV (timestamp;cpe;consumption_kwh;injection_kwh)")
    ap.add_argument("coefficients", help="fixed coefficients CSV (cpe;coefficient)")
    ap.add_argument("--out", default="resultado")
    ap.add_argument("--decimals", type=int, default=3)
    ap.add_argument("--sep", default=";")
    ap.add_argument("--decimal", default=".")
    ap.add_argument("--header", action="store_true")
    ap.add_argument("--share-unallocated", action="store_true",
                    help="if coefficients add up to < 1, share that part too")
    a = ap.parse_args(argv)
    run(a.data, a.coefficients, a.out, a.decimals, a.sep, a.decimal, a.header,
        not a.share_unallocated)


if __name__ == "__main__":
    main()
