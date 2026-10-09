"""
Input and output in E-REDES terms.

Input
-----
E-REDES delivers the EGAC one ``sgl_v2`` file per installation. That format is not parsed
here yet (no sample file to test against); instead the prototype reads one tidy CSV:

    timestamp;cpe;consumption_kwh;injection_kwh
    2026-06-01T00:00:00+01:00;PT0002000000000000001AA;0,123;0
    ...

``timestamp`` is the start of the 15-min interval, local time (Europe/Lisbon); naive times are
read as Lisbon time. Separator ``;`` or ``,`` and decimal comma or point are detected. The
coefficients file has ``cpe;coefficient`` (fractions, or percentages if they add up to ~100).

Output: dynamic-mode coefficient files (partilha dinâmica, RAC art. 32)
-----------------------------------------------------------------------
Per the E-REDES data model: one file per consumer–producer pair, every quarter-hour of the
billing period present (0 included), columns in the order date, quarter-hour, consumption
CPE, production CPE, coefficient; name like
``Coeficiente_Partilha_<consumer>_<producer>_<YYYYMM>_<generated YYYYMMDD>_<seq>.csv``.
A coefficient here is the share of the producer's injection in that quarter-hour that goes
to the consumer.

**To confirm with E-REDES before submitting:** separator, decimal mark and number of
decimals (the data model only shows "0.000"), whether a header row is expected, and the
quarter-hour labels. This module labels each interval by its local end time HHMM
(0015 … 2400); on the autumn day with 100 intervals it counts 0015 … 2500 as the data model
describes, and on the spring day the missing hour is simply absent.
"""
from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass

import pandas as pd

TZ = "Europe/Lisbon"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
@dataclass
class Period:
    cpes: list[str]                  # installation order (coefficients file first)
    coef: list[float]                # fixed coefficient per installation (0 if not listed)
    starts: pd.DatetimeIndex         # interval starts, tz-aware Lisbon time
    consumption: list[list[int]]     # [t][i], Wh
    injections: list[list[int]]      # [t][i], Wh
    warnings: list[str]

    @property
    def producers(self) -> list[int]:
        return [i for i in range(len(self.cpes)) if any(row[i] > 0 for row in self.injections)]


def _read_csv(src) -> pd.DataFrame:
    raw = src.read() if hasattr(src, "read") else open(src, "rb").read()
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    first = text.splitlines()[0] if text else ""
    sep = ";" if first.count(";") >= first.count(",") else ","
    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str)
    df.columns = [c.strip().lower() for c in df.columns]
    return df


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.fillna("0").str.strip().str.replace(",", ".", regex=False))


def read_coefficients(src) -> dict[str, float]:
    df = _read_csv(src)
    if not {"cpe", "coefficient"} <= set(df.columns):
        raise ValueError("coefficients file needs the columns cpe;coefficient")
    vals = _num(df["coefficient"])
    if (vals < 0).any():
        raise ValueError("coefficients must not be negative")
    total = vals.sum()
    if 1.5 < total <= 100.5:              # given in %
        vals = vals / 100
    elif total > 1.0 + 1e-6:
        raise ValueError(f"coefficients add up to {total:g}, more than 1 (100 %)")
    return dict(zip(df["cpe"].str.strip(), vals.astype(float)))


def _localize(ts: pd.Series) -> pd.DatetimeIndex:
    """Parse timestamps; naive ones are Lisbon time (the repeated autumn hour is inferred)."""
    raw = ts.str.strip()
    has_offset = raw.str.contains(r"(?:[+-]\d{2}:?\d{2}|Z)$", regex=True)
    if has_offset.all():
        return pd.DatetimeIndex(pd.to_datetime(raw, utc=True)).tz_convert(TZ)
    if has_offset.any():
        raise ValueError("mixed timestamps: give the UTC offset on all rows or on none")
    naive = pd.DatetimeIndex(pd.to_datetime(raw))
    return naive.tz_localize(TZ, ambiguous="infer", nonexistent="raise")


def read_period(data_src, coef_src) -> Period:
    coefs = read_coefficients(coef_src)
    df = _read_csv(data_src)
    need = {"timestamp", "cpe", "consumption_kwh", "injection_kwh"}
    if not need <= set(df.columns):
        raise ValueError("data file needs the columns " + ";".join(sorted(need)))
    df["cpe"] = df["cpe"].str.strip()
    warnings = []
    # parse per installation so the repeated autumn hour can be inferred in time order
    parts = []
    for cpe, g in df.groupby("cpe", sort=False):
        g = g.copy()
        g["start"] = _localize(g["timestamp"])
        parts.append(g)
    df = pd.concat(parts)
    df["c"] = (_num(df["consumption_kwh"]) * 1000).round().astype("int64")
    df["j"] = (_num(df["injection_kwh"]) * 1000).round().astype("int64")
    if (df["c"] < 0).any() or (df["j"] < 0).any():
        raise ValueError("consumption and injection must not be negative")
    both = (df["c"] > 0) & (df["j"] > 0)
    if both.any():
        warnings.append(f"{int(both.sum())} rows have consumption and injection at once; "
                        "the net 15-min balance is used")
        net = df["c"] - df["j"]
        df["c"], df["j"] = net.clip(lower=0), (-net).clip(lower=0)

    cpes = list(coefs) + sorted(set(df["cpe"]) - set(coefs))
    missing = sorted(set(coefs) - set(df["cpe"]))
    if missing:
        warnings.append("no data for " + ", ".join(missing) + " (taken as 0)")
    # installations without a coefficient receive nothing; worth a warning only if they
    # consume something while not injecting (a pure producer is expected to have none)
    takers = set(df.loc[(df["c"] > 0) & (df["j"] == 0), "cpe"])
    producers = set(df.loc[df["j"] > 0, "cpe"])
    extra = sorted((set(df["cpe"]) - set(coefs)) & (takers - producers))
    if extra:
        warnings.append("no coefficient for " + ", ".join(extra) + " (receives nothing)")

    starts = pd.DatetimeIndex(sorted(df["start"].unique()))
    full = pd.date_range(starts.min(), starts.max(), freq="15min")
    if len(full) != len(starts):
        warnings.append(f"{len(full) - len(starts)} quarter-hours have no data at all "
                        "(taken as 0)")
    starts = full
    dup = df.duplicated(["start", "cpe"])
    if dup.any():
        raise ValueError(f"{int(dup.sum())} duplicate rows (same cpe and interval)")
    C = df.pivot(index="start", columns="cpe", values="c").reindex(index=starts, columns=cpes)
    J = df.pivot(index="start", columns="cpe", values="j").reindex(index=starts, columns=cpes)
    gaps = int(C.isna().sum().sum())
    if gaps and not missing:
        warnings.append(f"{gaps} installation-intervals missing (taken as 0)")
    C = C.fillna(0).astype("int64")
    J = J.fillna(0).astype("int64")
    return Period(cpes=cpes, coef=[float(coefs.get(c, 0.0)) for c in cpes], starts=starts,
                  consumption=C.values.tolist(), injections=J.values.tolist(),
                  warnings=warnings)


# ---------------------------------------------------------------------------
# Quarter-hour labels
# ---------------------------------------------------------------------------
def quarter_hour_labels(starts: pd.DatetimeIndex) -> list[tuple[str, str]]:
    """(date YYYYMMDD, quarter-hour HHMM) per interval, see the module notes."""
    out = []
    days = pd.Series(range(len(starts)), index=starts).groupby(starts.date)
    for day, idx in days:
        ts = starts[idx.values]
        if len(ts) == 100:                                  # autumn: 0015 … 2500
            labels = [f"{(k + 1) * 15 // 60:02d}{(k + 1) * 15 % 60:02d}" for k in range(100)]
        else:
            labels = []
            for t in ts:
                end = t + pd.Timedelta(minutes=15)
                hh, mm = (24, 0) if end.date() != t.date() else (end.hour, end.minute)
                labels.append(f"{hh:02d}{mm:02d}")
        d = pd.Timestamp(day).strftime("%Y%m%d")
        out += [(d, lab) for lab in labels]
    return out


# ---------------------------------------------------------------------------
# Dynamic-mode coefficients
# ---------------------------------------------------------------------------
@dataclass
class Coefficients:
    """coef[(consumer, producer)] = list over intervals, plus what they deliver."""
    values: dict[tuple[int, int], list[float]]
    decimals: int
    exact_total: int        # Wh the exact method shares
    applied_total: float    # Wh the rounded coefficients deliver (Σ coef × injection)

    @property
    def rounding_loss(self) -> float:
        return self.exact_total - self.applied_total


def to_coefficients(period: Period, matrices: list[list[list[int]]],
                    decimals: int = 3) -> Coefficients:
    """
    Turn the exact matrices into per-pair coefficients rounded to ``decimals``.

    Coefficients are rounded down, then the freed units go back (largest remainder first)
    only where they cannot push a consumer above its consumption, so applying the file
    never allocates more than a member used and each producer's coefficients add up to ≤ 1.
    """
    unit = 10 ** -decimals
    scale = 10 ** decimals
    prods = period.producers
    n = len(period.cpes)
    pairs = [(c, p) for p in prods for c in range(n) if c != p and period.coef[c] > 0]
    values = {pr: [0.0] * len(matrices) for pr in pairs}
    exact_total, applied_total = 0, 0.0
    for t, m in enumerate(matrices):
        J, C = period.injections[t], period.consumption[t]
        # pass 1: round every pair down; cap[c] = what consumer c can still take on top
        cap = [float(C[c]) if J[c] <= 0 else 0.0 for c in range(n)]
        floors = {}
        for p in prods:
            Jp = J[p]
            if Jp <= 0:
                continue
            exact_total += sum(m[p])
            units, rem = {}, {}
            for c in range(n):
                if m[p][c] <= 0 or (c, p) not in values:
                    continue
                x = m[p][c] / Jp * scale
                u = math.floor(x + 1e-9)
                units[c], rem[c] = u, x - u
                cap[c] -= u * unit * Jp
            floors[p] = (units, rem)
        # pass 2: give the freed units back, largest remainder first, never above cap
        for p, (units, rem) in floors.items():
            Jp = J[p]
            free = scale - sum(units.values())
            for c in sorted(rem, key=rem.get, reverse=True):
                if free <= 0:
                    break
                if rem[c] > 1e-9 and unit * Jp <= cap[c] + 1e-9:
                    units[c] += 1
                    free -= 1
                    cap[c] -= unit * Jp
            for c, u in units.items():
                applied_total += u * unit * Jp
                values[(c, p)][t] = u / scale
    return Coefficients(values, decimals, exact_total, applied_total)


def coefficient_files(period: Period, coefs: Coefficients, generated: str,
                      sep: str = ";", decimal: str = ".", header: bool = False,
                      seq: int = 1) -> dict[str, str]:
    """{file name: content} for every consumer–producer pair."""
    labels = quarter_hour_labels(period.starts)
    month = labels[-1][0][:6] if labels else ""
    files = {}
    for (c, p), vals in coefs.values.items():
        cons, prod = period.cpes[c], period.cpes[p]
        name = f"Coeficiente_Partilha_{cons}_{prod}_{month}_{generated}_{seq:02d}.csv"
        lines = []
        if header:
            lines.append(sep.join(["data", "quarto_hora", "cpe_consumo", "cpe_producao",
                                   "coeficiente"]))
        for (d, q), v in zip(labels, vals):
            num = f"{v:.{coefs.decimals}f}"
            if decimal != ".":
                num = num.replace(".", decimal)
            lines.append(sep.join([d, q, cons, prod, num]))
        files[name] = "\n".join(lines) + "\n"
    return files


def zip_files(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()
