import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import keyfit  # noqa: E402


def synthetic_group(n: int, T: int, rounds: int, keys=None, seed: int = 0):
    """PV-like production, random demands, shares by today's EDC method."""
    rng = np.random.default_rng(seed)
    if keys is None:
        w = rng.lognormal(0, 0.8, n)
        keys = np.round(w / w.sum() * 0.95 * 1e4) / 1e4
        keys[keys <= 0] = 1e-4
    keys = np.asarray(keys, dtype=float)
    hour = (np.arange(T) % 96) / 4
    sun = np.clip(np.sin(np.pi * (hour - 6) / 14), 0, None) * (6 < hour) * (hour < 20)
    P = (35 * n * sun * rng.uniform(0.3, 1.0, T)).astype(np.int64)
    base = rng.lognormal(-1.8, 0.7, n)
    prof = 0.6 + 0.5 * np.sin(np.pi * (hour - 7) / 12) ** 2
    D = np.maximum(0, 100 * base[None, :] * prof[:, None]
                   * rng.uniform(0.2, 1.8, (T, n))).astype(np.int64)
    S = keyfit.replay_edc(P, D, keys, rounds)
    return P, D, S, keys


def all_report_csv(P, D, S, eans=None, prod="859182400699900000",
                   start="2026-06-01") -> bytes:
    """Build a SharEl 'all report' CSV (decimal comma, ';') from hundredths of kWh."""
    T, n = D.shape
    eans = eans or [f"8591824006{i:08d}" for i in range(n)]
    idx = pd.date_range(start, periods=T, freq="15min")
    fmt = lambda a: [f"{x / 100:.2f}".replace(".", ",") for x in a]  # noqa: E731
    cols = {"Datum": idx.strftime("%d.%m.%Y"), "Cas od": idx.strftime("%H:%M"),
            "Cas do": (idx + pd.Timedelta(minutes=15)).strftime("%H:%M"),
            f"IN-{prod}-D": fmt(P), f"OUT-{prod}-D": fmt(P - S.sum(axis=1))}
    for j, e in enumerate(eans):
        cols[f"IN-{e}-O"] = fmt(-D[:, j])
        cols[f"OUT-{e}-O"] = fmt(S[:, j] - D[:, j])
    return pd.DataFrame(cols).to_csv(sep=";", index=False).encode("utf-8")


@pytest.fixture
def small_group():
    return synthetic_group(5, 96 * 60, 5, keys=[0.1, 0.5, 0.1, 0.1, 0.1], seed=3)
