"""
Synthetic collective for trying the Portugal tools without real meter data.

    python -m portugal.exemplo out_dir [--start 2026-05-21] [--end 2026-06-20] [--seed 0]

Writes ``dados.csv`` (15-min consumption/injection, Lisbon time) and ``coeficientes.csv``.
The collective: one shared PV plant (IPr), one flat with its own PV that also injects
(IC with UPAC), and ten flats and a shop that only consume. Coefficients follow investment
shares, as many collectives set them.
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

TZ = "Europe/Lisbon"


def cpe(i: int) -> str:
    return f"PT0002{i:012d}AA"   # PT + 16 digits + 2 letters = 20 characters


def synthetic(start: str, end: str, seed: int = 0, n_flats: int = 10):
    rng = np.random.default_rng(seed)
    after = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    idx = pd.date_range(pd.Timestamp(start, tz=TZ), pd.Timestamp(after, tz=TZ),
                        freq="15min", inclusive="left")   # local days, clock changes included
    hour = idx.hour + idx.minute / 60
    sun = np.clip(np.sin(np.pi * (hour - 6.5) / 14), 0, None) * (hour > 6.5) * (hour < 20.5)
    cloud = rng.uniform(0.35, 1.0, len(idx))
    rows = []

    def add(i, cons, inj):
        rows.append(pd.DataFrame({"timestamp": idx.strftime("%Y-%m-%dT%H:%M:%S%z")
                                  .str.replace(r"(\d{2})(\d{2})$", r"\1:\2", regex=True),
                                  "cpe": cpe(i), "consumption_kwh": np.round(cons, 3),
                                  "injection_kwh": np.round(inj, 3)}))

    # IPr: 30 kWp community plant, small own consumption at night
    pv = 30 * 0.25 * sun * cloud
    add(0, np.where(pv > 0, 0, 0.01), pv)
    # IC with UPAC: 4 kWp on a flat, net 15-min balance
    own = 4 * 0.25 * sun * cloud
    load = 0.12 + 0.10 * np.sin(np.pi * (hour - 7) / 13) ** 2 * rng.uniform(0.5, 1.5, len(idx))
    net = load - own
    add(1, np.clip(net, 0, None), np.clip(-net, 0, None))
    # flats: evening peaks, some home during the day
    for k in range(n_flats):
        base = rng.lognormal(-2.4, 0.4)
        day_home = rng.uniform(0.2, 1.2)
        prof = (0.6 + day_home * ((hour > 9) & (hour < 17))
                + 1.8 * np.exp(-((hour - 20) ** 2) / 3) + 0.8 * np.exp(-((hour - 8) ** 2) / 1.5))
        add(2 + k, base * prof * rng.uniform(0.3, 1.9, len(idx)), np.zeros(len(idx)))
    # shop: open 9-19, high daytime load
    shop = np.where((hour >= 9) & (hour < 19), 1.1, 0.15) * rng.uniform(0.7, 1.3, len(idx))
    add(2 + n_flats, shop, np.zeros(len(idx)))

    data = pd.concat(rows, ignore_index=True)
    w = rng.uniform(0.5, 1.5, n_flats + 2)
    w[-1] *= 2.5                                   # the shop invested more
    coef = np.round(w / w.sum(), 4)
    coef[-1] = round(1 - coef[:-1].sum(), 4)       # exactly 100 %
    coefs = pd.DataFrame({"cpe": [cpe(i) for i in range(1, n_flats + 3)], "coefficient": coef})
    return data, coefs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("out")
    ap.add_argument("--start", default="2026-05-21")
    ap.add_argument("--end", default="2026-06-20")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    data, coefs = synthetic(a.start, a.end, a.seed)
    data.to_csv(os.path.join(a.out, "dados.csv"), sep=";", index=False)
    coefs.to_csv(os.path.join(a.out, "coeficientes.csv"), sep=";", index=False)
    print(f"{len(data)} rows, {data['cpe'].nunique()} installations -> {a.out}")


if __name__ == "__main__":
    main()
