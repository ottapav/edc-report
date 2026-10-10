"""
Converter for the public GECAD dataset "Energy consumption and PV generation data of 15
prosumers (15 minute resolution)", Zenodo 10.5281/zenodo.5106455, CC BY 4.0
(S. Ramos, J. Soares, Z. Foroozandeh, I. Tavares, Z. Vale, Polytechnic of Porto).

    python -m portugal.gecad "Data_PV and consumptions.xlsx" out_dir

Writes ``dados.csv`` for ``portugal.cli`` and two coefficient files: ``coef_iguais.csv``
(equal shares) and ``coef_consumo.csv`` (shares of annual consumption, a common choice for a
fixed key).

What is in the workbook and how it is read:
* ``Total PV production`` – three producers in kW per 15 min; energy = kW / 4. Each producer
  becomes one production installation (IPr).
* ``Consumer 1`` … ``Consumer 15`` – Wh per 15 min.
* ``Common services`` – kWh per hour for 364 days; each hour is spread evenly over its four
  quarter-hours and the missing last day is copied from the day before.
* Timestamps are interval ends, ``dd/mm/yyyy HH:MM:SS``, with 96 intervals on every day, also
  on the clock-change days, so the clock has no daylight saving time. They are written with a
  fixed ``+00:00`` offset; all series share the same clock, so the sharing per interval does
  not depend on it.
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

PV_SHEET = "Total PV production "


def cpe(kind: str, i: int) -> str:
    """Placeholder CPEs: PT + 16 digits + 2 letters."""
    return f"PT0000{ {'P': 1, 'C': 2, 'S': 3}[kind] }{i:011d}{kind}X"


def load(xlsx) -> tuple[pd.DatetimeIndex, dict[str, np.ndarray], dict[str, np.ndarray]]:
    """(interval starts, consumption Wh per member, injection Wh per producer)."""
    x = pd.ExcelFile(xlsx)
    pv = x.parse(PV_SHEET)
    ends = parse_times(pv["Data"])
    starts = pd.DatetimeIndex(ends - pd.Timedelta(minutes=15)).tz_localize("UTC")
    T = len(starts)
    prod = {}
    for i, col in enumerate([c for c in pv.columns if c.startswith("Producer")], start=1):
        prod[cpe("P", i)] = np.round(pv[col].astype(float).values / 4 * 1000)
    cons, mismatches = {}, {}
    sheets = [s for s in x.sheet_names if s.replace(" ", "").startswith("Consumer")]
    for s in sorted(sheets, key=lambda s: int(s.replace("Consumer", ""))):
        df = x.parse(s)
        if len(df) != T:
            raise ValueError(f"sheet {s!r}: {len(df)} rows, the PV sheet has {T}")
        ts = parse_times(df.iloc[:, 0])
        off = int((ts.values != ends.values).sum())
        if off:
            mismatches[s] = off
        cons[cpe("C", int(s.replace("Consumer", "")))] = df.iloc[:, 1].astype(float).values
    cs = x.parse("Common services").iloc[:, 3].astype(float).values * 1000   # Wh per hour
    hours = T // 4
    if len(cs) < hours:                                # repeat the last day for the gap
        cs = np.concatenate([cs, np.resize(cs[-24:], hours - len(cs))])
    cons[cpe("S", 1)] = np.round(np.repeat(cs[:hours] / 4, 4))
    load.mismatches = mismatches
    return starts, cons, prod


def parse_times(col: pd.Series) -> pd.Series:
    """Text ``dd/mm/yyyy HH:MM:SS``; some cells are Excel serial numbers or datetimes."""
    out = pd.Series(pd.NaT, index=col.index, dtype="datetime64[ns]")
    num = pd.to_numeric(col, errors="coerce")
    is_num = num.notna()
    out[is_num] = pd.Timestamp("1899-12-30") + pd.to_timedelta(num[is_num], unit="D")
    is_dt = col.map(lambda v: isinstance(v, (pd.Timestamp,)) or hasattr(v, "year"))
    out[is_dt & ~is_num] = pd.to_datetime(col[is_dt & ~is_num])
    rest = ~is_num & ~is_dt
    out[rest] = pd.to_datetime(col[rest].astype(str), format="%d/%m/%Y %H:%M:%S")
    # serial numbers carry float noise (01:00 stored as 00:59:59.9999998)
    return pd.to_datetime(out).dt.round("s")


def tidy(starts, cons, prod) -> pd.DataFrame:
    ts = starts.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    rows = []
    for c, v in cons.items():
        rows.append(pd.DataFrame({"timestamp": ts, "cpe": c, "consumption_kwh": v / 1000,
                                  "injection_kwh": 0.0}))
    for p, v in prod.items():
        rows.append(pd.DataFrame({"timestamp": ts, "cpe": p, "consumption_kwh": 0.0,
                                  "injection_kwh": v / 1000}))
    return pd.concat(rows, ignore_index=True)


def coefficients(cons) -> dict[str, pd.DataFrame]:
    names = list(cons)
    n = len(names)
    eq = np.full(n, round(1 / n, 6))
    eq[-1] = round(1 - eq[:-1].sum(), 6)
    tot = np.array([cons[c].sum() for c in names])
    by = np.round(tot / tot.sum(), 6)
    by[-1] = round(1 - by[:-1].sum(), 6)
    return {"coef_iguais.csv": pd.DataFrame({"cpe": names, "coefficient": eq}),
            "coef_consumo.csv": pd.DataFrame({"cpe": names, "coefficient": by})}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert the GECAD 15-prosumer workbook")
    ap.add_argument("xlsx")
    ap.add_argument("out")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    starts, cons, prod = load(a.xlsx)
    tidy(starts, cons, prod).to_csv(os.path.join(a.out, "dados.csv"), sep=";", index=False)
    for name, df in coefficients(cons).items():
        df.to_csv(os.path.join(a.out, name), sep=";", index=False)
    if load.mismatches:
        print("timestamps not matching the PV sheet (rows aligned by position):",
              load.mismatches)
    kwh = lambda d: round(sum(v.sum() for v in d.values()) / 1000)  # noqa: E731
    print(f"{len(starts)} intervals, {len(cons)} consumers ({kwh(cons)} kWh), "
          f"{len(prod)} producers ({kwh(prod)} kWh) -> {a.out}")


if __name__ == "__main__":
    main()
