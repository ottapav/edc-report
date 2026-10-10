"""
Portugal in the web app: Portuguese data as a :class:`edc_data.SharingData` report.

The app's report model has one source per report. Here all producers (IPr and installations
that inject) are **pooled** into that one source: in the fixed mode and in the exact method
what a member receives does not depend on which producer it comes from (the per-producer
split only matters for the dynamic-mode files, built separately by :func:`export_zip`).

Columns of the report:
* **A** – E-REDES fixed coefficients (RAC art. 28–29), computed here from the meter data
  and the coefficients, because the data has no allocation of its own;
* **B** – the exact method on the same coefficients (``presna_staticka.rozdel`` on the pooled
  production), run in a child process like the Czech recompute.

Energies are integers in Wh inside; the report frame is in kWh like the Czech one.
"""
from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from edc_data import SharingData, key_shared, key_unmet, key_unshared
from portugal import eredes, gecad, partilha

POOL = "PV-POOL"                     # id of the pooled source


# ---------------------------------------------------------------------------
# Detection and loading
# ---------------------------------------------------------------------------
def _head(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            return content[:4096].decode(enc).lower()
        except UnicodeDecodeError:
            continue
    return ""


def kind(name: str, content: bytes) -> str:
    """``edc`` (Czech report), ``pt-data``, ``pt-coef``, ``pt-gecad`` or ``unknown``."""
    if content[:2] == b"PK" or (name or "").lower().endswith((".xlsx", ".xlsm")):
        return "pt-gecad" if gecad.is_gecad(io.BytesIO(content)) else "unknown"
    first = _head(content).splitlines()[0] if content else ""
    cols = {c.strip().strip('"') for c in first.replace(",", ";").split(";")}
    if {"datum", "cas od"} <= cols:
        return "edc"
    if {"timestamp", "cpe", "consumption_kwh", "injection_kwh"} <= cols:
        return "pt-data"
    if {"cpe", "coefficient"} <= cols:
        return "pt-coef"
    return "unknown"


def country_of(files: list[tuple[str, bytes]]) -> str:
    """``CZ`` or ``PT`` for an upload of one or more files; ValueError if unclear."""
    kinds = [kind(n, c) for n, c in files]
    if "edc" in kinds:
        if len(files) > 1:
            raise ValueError("upload one EDC report at a time")
        return "CZ"
    if any(k in ("pt-data", "pt-gecad") for k in kinds):
        return "PT"
    if kinds == ["pt-coef"]:
        raise ValueError("this is a coefficients file; select it together with the data file")
    raise ValueError("unrecognised file: expected an EDC report (edc-cr.cz), Portuguese "
                     "15-min data (timestamp;cpe;consumption_kwh;injection_kwh) or the "
                     "GECAD workbook")


@dataclass
class PTInput:
    """Everything the app needs to rebuild the Portuguese report for new coefficients."""
    period: eredes.Period
    members: list[int]               # period indices shown as members (destinations)
    producers: list[int]             # period indices that inject (pooled)
    base_coef: list[float]           # coefficients per member as loaded
    P: np.ndarray                    # [T] pooled injection, Wh
    D: np.ndarray                    # [T, m] members' consumption, Wh
    J: np.ndarray                    # [T, m] members' injection, Wh (prosumers)
    index: pd.DatetimeIndex          # naive Lisbon wall-clock starts (for the figures)
    source: str                      # "csv" or "gecad"


def load(files: list[tuple[str, bytes]]) -> tuple[SharingData, PTInput]:
    """Parse a Portuguese upload: one data file (CSV or GECAD workbook) and optionally a
    coefficients CSV."""
    kinds = [kind(n, c) for n, c in files]
    data = [f for f, k in zip(files, kinds) if k in ("pt-data", "pt-gecad")]
    coef = [f for f, k in zip(files, kinds) if k == "pt-coef"]
    if len(data) != 1:
        raise ValueError("select exactly one data file (and optionally a coefficients file)")
    if len(coef) > 1:
        raise ValueError("select at most one coefficients file")
    name, content = data[0]
    coef_bytes = coef[0][1] if coef else None
    if kind(name, content) == "pt-gecad":
        coefs = eredes.read_coefficients(coef_bytes) if coef_bytes else None
        period = gecad.to_period(io.BytesIO(content), coefs)
        source = "gecad"
    else:
        period = eredes.read_period(content, coef_bytes)
        source = "csv"
    return build_input(period, source)


def build_input(period: eredes.Period, source: str = "csv") -> tuple[SharingData, PTInput]:
    C = np.asarray(period.consumption, dtype=np.int64)
    Jall = np.asarray(period.injections, dtype=np.int64)
    if C.size == 0:
        raise ValueError("the data file has no intervals")
    injects = Jall.sum(axis=0) > 0
    consumes = C.sum(axis=0) > 0
    coef = np.asarray(period.coef, dtype=float)
    # members: anyone with a coefficient, and anyone who consumes without ever injecting
    members = [i for i in range(len(period.cpes))
               if coef[i] > 0 or (consumes[i] and not injects[i])]
    producers = [i for i in range(len(period.cpes)) if injects[i]]
    if not members:
        raise ValueError("no members (installations with a coefficient or consumption)")
    if not producers:
        raise ValueError("no installation injects energy, so there is nothing to share")
    index = pd.DatetimeIndex(period.starts).tz_convert(eredes.TZ).tz_localize(None)
    pt = PTInput(period=period, members=members, producers=producers,
                 base_coef=[float(coef[i]) for i in members],
                 P=Jall.sum(axis=1), D=C[:, members], J=Jall[:, members],
                 index=index, source=source)
    return sharing_data(pt, pt.base_coef), pt


# ---------------------------------------------------------------------------
# Column A: fixed coefficients (vectorised RAC art. 28-29)
# ---------------------------------------------------------------------------
def fixed_shares(pt: PTInput, coef: list[float]) -> np.ndarray:
    """[T, m] Wh each member self-consumes under the fixed mode (same rule as
    :func:`portugal.partilha.fixed_erse`, for all intervals at once)."""
    c = np.asarray(coef, dtype=float)
    total = c.sum()
    eligible = (pt.J <= 0) & (c[None, :] > 0)                # injecting members skipped
    s_el = (eligible * c[None, :]).sum(axis=1)
    scale = np.divide(total, s_el, out=np.zeros_like(s_el), where=s_el > 1e-12)
    imputed = np.floor(eligible * c[None, :] * (scale * pt.P)[:, None] + 1e-9)
    return np.minimum(pt.D, imputed.astype(np.int64))


def _frame(pt: PTInput, S: np.ndarray) -> pd.DataFrame:
    """Report frame (kWh) from the members' shares S [T, m] in Wh."""
    idx = pt.index
    cpes = [pt.period.cpes[i] for i in pt.members]
    cols: dict[str, np.ndarray] = {}
    for j, e in enumerate(cpes):
        cols[key_shared(POOL, e)] = S[:, j] / 1000
        cols[key_unmet(e)] = (pt.D[:, j] - S[:, j]) / 1000
    cols[key_unshared(POOL)] = (pt.P - S.sum(axis=1)) / 1000
    return pd.DataFrame(cols, index=idx)


def sharing_data(pt: PTInput, coef: list[float], S: np.ndarray | None = None) -> SharingData:
    """The report for ``coef``: the fixed mode unless the shares ``S`` are given."""
    S = fixed_shares(pt, coef) if S is None else S
    cpes = [pt.period.cpes[i] for i in pt.members]
    idx = pt.index
    first = {}
    for j, e in enumerate(cpes):
        nz = np.flatnonzero(pt.D[:, j] > 0)
        first[e] = pd.Timestamp(idx[nz[0]]) if nz.size else None
    return SharingData(
        frame=_frame(pt, S), fmt="all", source_eans=[POOL], dest_eans=cpes,
        production=pd.Series(pt.P / 1000, index=idx),
        demand={e: pd.Series(pt.D[:, j] / 1000, index=idx) for j, e in enumerate(cpes)},
        coverage={e: 1.0 for e in cpes}, first_data=first,
        notes=list(pt.period.warnings), n_rows=len(idx), country="PT",
        producer_ids=[pt.period.cpes[i] for i in pt.producers],
    )


# ---------------------------------------------------------------------------
# Column B: exact method, in a child process with timing
# ---------------------------------------------------------------------------
def unallocated(coef: list[float]) -> float:
    """Part of the energy the coefficients leave unallocated (kept so in both columns)."""
    return max(0.0, 1.0 - float(sum(coef)))


def recompute(pt: PTInput, coef: list[float],
              progress: Callable[[str, float], None] = lambda *_: None,
              cancelled: Callable[[], bool] | None = None):
    """(fixed-mode report, Recomputed exact report) for ``coef`` (fractions per member)."""
    from recompute import Recomputed, Timing, _run_isolated
    t_job = time.perf_counter()
    coef = [max(0.0, float(x)) for x in coef]
    if not any(k > 0 for k in coef):
        raise ValueError("At least one coefficient must be > 0.")
    if sum(coef) > 1 + 1e-6:
        raise ValueError(f"Coefficients add up to {100 * sum(coef):.2f} %, more than 100 %.")
    tm = Timing(intervals=len(pt.P), members=len(coef))
    t0 = time.perf_counter()
    base = sharing_data(pt, coef)
    reserve = unallocated(coef)
    # a member injecting in an interval cannot receive in it (art. 28(4))
    Pl, Dl = pt.P.tolist(), np.where(pt.J > 0, 0, pt.D).tolist()
    tm.t_prepare = time.perf_counter() - t0
    out, tt = _run_isolated(Pl, Dl, coef, reserve, 96, progress, cancelled)
    for name, value in tt.items():
        setattr(tm, name, value)
    tm.t_total = tm.t_night + tm.t_enough + tm.t_full
    t0 = time.perf_counter()
    exact = sharing_data(pt, coef, np.asarray(out, dtype=np.int64))
    exact.notes = []
    tm.t_prepare += time.perf_counter() - t0
    tm.t_wall = time.perf_counter() - t_job
    progress("done", 1.0)
    keys_from_file = np.allclose(coef, pt.base_coef, atol=1e-9)
    rec = Recomputed(data=exact, keys=coef, keys_estimated=keys_from_file, reserve=reserve,
                     timing=tm, edc_match=1.0, rounds=0)
    return base, rec


# ---------------------------------------------------------------------------
# Dynamic-mode coefficient files
# ---------------------------------------------------------------------------
def export_zip(pt: PTInput, coef: list[float], decimals: int = 3,
               generated: str | None = None) -> tuple[bytes, dict]:
    """ZIP of the per-pair coefficient files for ``coef`` and a small summary."""
    period = pt.period
    full = [0.0] * len(period.cpes)
    for i, c in zip(pt.members, coef):
        full[i] = float(c)
    cmp_, mats = partilha.compare(period.cpes, period.injections, period.consumption, full)
    p2 = eredes.Period(cpes=period.cpes, coef=full, starts=period.starts,
                       consumption=period.consumption, injections=period.injections,
                       warnings=[], equal_shares=period.equal_shares)
    co = eredes.to_coefficients(p2, mats, decimals)
    generated = generated or pd.Timestamp.now(tz=eredes.TZ).strftime("%Y%m%d")
    files = eredes.coefficient_files(p2, co, generated)
    months = eredes.months_of(files)
    summary = {"pairs": len(co.values), "files": len(files), "months": months,
               "decimals": decimals,
               "exact_kwh": co.exact_total / 1000, "delivered_kwh": co.applied_total / 1000,
               "rounding_loss_kwh": co.rounding_loss / 1000,
               "fixed_kwh": cmp_.fixed / 1000}
    readme = (
        "Dynamic-mode coefficients (partilha dinâmica, ERSE RAC art. 32)\n"
        f"Generated {generated}; {len(co.values)} consumer-producer pairs × {len(months)} "
        f"month(s) {'–'.join(dict.fromkeys([months[0], months[-1]])) if months else '-'} = {len(files)} files, {decimals} decimals.\n"
        f"Exact method shares {co.exact_total / 1000:.3f} kWh; the rounded coefficients "
        f"deliver {co.applied_total / 1000:.3f} kWh.\n"
        "Columns: date;quarter-hour;consumption CPE;production CPE;coefficient.\n"
        "Confirm separator, decimals, header and quarter-hour labels with E-REDES before "
        "submitting.\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("LEIA-ME_README.txt", readme)
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue(), summary
