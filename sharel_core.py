"""Loading and statistics for SharEl export CSVs (no plotting, no matplotlib).

Ported from ``plot_energy_sharing.py`` with one structural change: frame
columns are keyed by EAN rather than by display name, so names can be edited
in the web UI without re-parsing the file.

Column keys
-----------
``shared|<src>|<dst>``   energy shared from producer ``src`` to consumer ``dst``
``unmet|<dst>``          consumer demand not covered by sharing (all report)
``unshared|<src>``       producer surplus exported to grid (all report)

Two export layouts are auto-detected from the header (see the original
script's docstring for the sign conventions):

* **part report** - ``<src_ean>-<dst_ean>`` columns (shared kWh per pair).
* **all report**  - ``IN/OUT-<ean>-D`` (producer) and ``IN/OUT-<ean>-O``
  (consumers).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

_RE_PAIR = re.compile(r"^(\d+)-(\d+)$")
_RE_PROD_IN = re.compile(r"^IN-(\d+)-D$")
_RE_PROD_OUT = re.compile(r"^OUT-(\d+)-D$")
_RE_CONS_IN = re.compile(r"^IN-(\d+)-O$")
_RE_CONS_OUT = re.compile(r"^OUT-(\d+)-O$")


# ---------------------------------------------------------------------------
# Column-key helpers
# ---------------------------------------------------------------------------


def key_shared(src: str, dst: str) -> str:
    return f"shared|{src}|{dst}"


def key_unmet(dst: str) -> str:
    return f"unmet|{dst}"


def key_unshared(src: str) -> str:
    return f"unshared|{src}"


def key_kind(key: str) -> str:
    """Return ``shared`` / ``unmet`` / ``unshared``."""
    return key.split("|", 1)[0]


def key_dest(key: str) -> str | None:
    """Destination EAN of a column key (``None`` for producer-side columns)."""
    parts = key.split("|")
    if parts[0] == "shared":
        return parts[2]
    if parts[0] == "unmet":
        return parts[1]
    return None


def key_source(key: str) -> str | None:
    parts = key.split("|")
    if parts[0] in ("shared", "unshared"):
        return parts[1]
    return None


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SharingData:
    """Parsed report.

    Attributes
    ----------
    frame
        Datetime-indexed kWh per 15-min interval, EAN-keyed columns.
    fmt
        ``"all"`` or ``"part"``.
    source_eans, dest_eans
        EANs in file order.
    production
        Producer ``IN-D`` series (all report only).
    demand
        Consumer demand per destination EAN (all report only), positive kWh.
    coverage
        Destination EAN -> fraction of rows with a value (``OUT-O`` for the
        all report, the pair column for the part report).
    first_data
        Destination EAN -> first timestamp with data.
    notes
        Human-readable warnings produced while loading.
    """

    frame: pd.DataFrame
    fmt: str
    source_eans: list[str]
    dest_eans: list[str]
    production: pd.Series | None = None
    demand: dict[str, pd.Series] = field(default_factory=dict)
    coverage: dict[str, float] = field(default_factory=dict)
    first_data: dict[str, pd.Timestamp | None] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    n_rows: int = 0


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _detect_format(columns: list[str]) -> str:
    if any(_RE_PROD_IN.match(c) or _RE_PROD_OUT.match(c) for c in columns):
        return "all"
    if any(_RE_PAIR.match(c) for c in columns):
        return "part"
    raise ValueError(
        "Unrecognised SharEl CSV header. Expected '<ean>-<ean>' columns "
        "(part report) or 'IN-<ean>-D' / 'OUT-<ean>-D' columns (all report)."
    )


def _attach_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    if "Datum" not in df.columns or "Cas od" not in df.columns:
        raise ValueError("CSV is missing the 'Datum' / 'Cas od' columns.")
    out = df.copy()
    out["datetime"] = pd.to_datetime(
        out["Datum"].astype(str).str.strip() + " " + out["Cas od"].astype(str).str.strip(),
        format="%d.%m.%Y %H:%M",
    )
    return out.set_index("datetime").sort_index()


def _first_valid(s: pd.Series) -> pd.Timestamp | None:
    idx = s.first_valid_index()
    return None if idx is None else pd.Timestamp(idx)


def _load_part(df: pd.DataFrame) -> SharingData:
    df = _attach_datetime_index(df)
    pairs = [(c, *_RE_PAIR.match(c).groups()) for c in df.columns if _RE_PAIR.match(c)]
    out: dict[str, pd.Series] = {}
    sources: list[str] = []
    dests: list[str] = []
    coverage: dict[str, float] = {}
    first: dict[str, pd.Timestamp | None] = {}
    for col, src, dst in pairs:
        s = pd.to_numeric(df[col], errors="coerce")
        out[key_shared(src, dst)] = s.fillna(0).clip(lower=0)
        if src not in sources:
            sources.append(src)
        if dst not in dests:
            dests.append(dst)
        coverage[dst] = max(coverage.get(dst, 0.0), float(s.notna().mean()))
        f = _first_valid(s)
        if f is not None and (first.get(dst) is None or f < first[dst]):
            first[dst] = f
    frame = pd.DataFrame(out, index=df.index)
    return SharingData(
        frame=frame, fmt="part", source_eans=sources, dest_eans=dests,
        coverage=coverage, first_data=first, n_rows=len(frame),
        notes=["Part report: production, grid export and unmet demand are not "
               "available, so only shared energy is shown."],
    )


def _load_all(df: pd.DataFrame) -> SharingData:
    df = _attach_datetime_index(df)
    cols = [str(c) for c in df.columns]
    prod_eans = {m.group(1) for c in cols if (m := _RE_PROD_IN.match(c))}
    prod_eans |= {m.group(1) for c in cols if (m := _RE_PROD_OUT.match(c))}
    if len(prod_eans) != 1:
        raise ValueError(
            f"Expected exactly one producer EAN (…-D columns), found {len(prod_eans)}: "
            f"{sorted(prod_eans)}. Multi-producer all-reports are not supported yet."
        )
    prod = next(iter(prod_eans))
    prod_in, prod_out = f"IN-{prod}-D", f"OUT-{prod}-D"

    cons_in = {m.group(1): c for c in cols if (m := _RE_CONS_IN.match(c))}
    cons_out = {m.group(1): c for c in cols if (m := _RE_CONS_OUT.match(c))}
    # keep file order
    dests = [e for e in cons_in if e in cons_out]  # dicts keep file order

    for c in (prod_in, prod_out, *cons_in.values(), *cons_out.values()):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    out: dict[str, pd.Series] = {}
    demand: dict[str, pd.Series] = {}
    coverage: dict[str, float] = {}
    first: dict[str, pd.Timestamp | None] = {}
    notes: list[str] = []
    for ean in dests:
        c_in, c_out = df[cons_in[ean]], df[cons_out[ean]]
        shared = (c_out - c_in).fillna(0).clip(lower=0)
        dem = (-c_in.fillna(0)).clip(lower=0)
        out[key_shared(prod, ean)] = shared
        out[key_unmet(ean)] = (dem - shared).clip(lower=0)
        demand[ean] = dem
        coverage[ean] = float(c_out.notna().mean())
        first[ean] = _first_valid(c_out)
        # OUT-O missing while IN-O present -> unmet under-reported
        gap = int((c_in.notna() & c_out.isna()).sum())
        if gap:
            notes.append(
                f"EAN …{ean[-6:]}: {gap} intervals have consumption (IN-O) but no "
                f"OUT-O value; unmet energy is under-reported for those intervals."
            )

    out[key_unshared(prod)] = (
        df[prod_out].fillna(0).clip(lower=0) if prod_out in df.columns
        else pd.Series(0.0, index=df.index)
    )
    frame = pd.DataFrame(out, index=df.index)

    production = df[prod_in].fillna(0) if prod_in in df.columns else None
    if production is not None:
        shared_sum = frame[[key_shared(prod, e) for e in dests]].sum(axis=1)
        residual = production - shared_sum - frame[key_unshared(prod)]
        max_abs = float(residual.abs().max())
        if max_abs > 0.01:
            notes.append(
                f"Balance check: max |IN-D − shared − unshared| = {max_abs:.3f} kWh "
                f"in one interval (total {float(residual.sum()):.2f} kWh)."
            )

    return SharingData(
        frame=frame, fmt="all", source_eans=[prod], dest_eans=dests,
        production=production, demand=demand, coverage=coverage,
        first_data=first, notes=notes, n_rows=len(frame),
    )


def load_report(content: bytes) -> SharingData:
    """Parse the raw bytes of a SharEl CSV export."""
    text = None
    for enc in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:  # pragma: no cover - latin-1 never fails
        raise ValueError("Could not decode the file.")
    raw = pd.read_csv(
        io.StringIO(text), sep=";", decimal=",", skipinitialspace=True,
        index_col=False, dtype=str,
    )
    raw.columns = [str(c).strip() for c in raw.columns]
    # numeric columns were read as str to keep 'Datum' / 'Cas od' intact
    for c in raw.columns:
        if c not in ("Datum", "Cas od", "Cas do"):
            raw[c] = pd.to_numeric(raw[c].str.replace(",", ".", regex=False), errors="coerce")
    raw = raw.dropna(subset=["Datum"]) if "Datum" in raw.columns else raw
    fmt = _detect_format(list(raw.columns))
    return _load_part(raw) if fmt == "part" else _load_all(raw)


# ---------------------------------------------------------------------------
# Filtering / aggregation
# ---------------------------------------------------------------------------


def filter_dests(data: SharingData, enabled: set[str]) -> pd.DataFrame:
    """Keep columns of checked destinations; producer-side columns always stay."""
    keep = [c for c in data.frame.columns
            if key_dest(c) is None or key_dest(c) in enabled]
    return data.frame[keep]


def shared_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if key_kind(c) == "shared"]


def aggregate_grid_flows(df: pd.DataFrame) -> pd.DataFrame:
    """Shared pair columns + one ``GRID_UNSHARED`` + one ``GRID_UNMET`` column."""
    parts: dict[str, pd.Series] = {c: df[c] for c in shared_cols(df)}
    uns = [c for c in df.columns if key_kind(c) == "unshared"]
    unm = [c for c in df.columns if key_kind(c) == "unmet"]
    if uns:
        parts["GRID_UNSHARED"] = df[uns].sum(axis=1)
    if unm:
        parts["GRID_UNMET"] = df[unm].sum(axis=1)
    return pd.DataFrame(parts, index=df.index)


@dataclass(frozen=True)
class WastedSplit:
    shared_total: float
    unshared_only: float
    overlap: float
    unshared_total: float
    unmet_total: float


def compute_wasted_split(df: pd.DataFrame) -> WastedSplit:
    """Shared / wasted overlap ``min(unshared, unmet)`` per interval / unshared-only."""
    agg = aggregate_grid_flows(df)
    sc = shared_cols(agg)
    shared_total = float(agg[sc].sum().sum()) if sc else 0.0
    zero = pd.Series(0.0, index=agg.index)
    uns = agg["GRID_UNSHARED"] if "GRID_UNSHARED" in agg else zero
    unm = agg["GRID_UNMET"] if "GRID_UNMET" in agg else zero
    overlap = float(np.minimum(uns.to_numpy(), unm.to_numpy()).sum())
    return WastedSplit(
        shared_total=shared_total,
        unshared_only=float(uns.sum()) - overlap,
        overlap=overlap,
        unshared_total=float(uns.sum()),
        unmet_total=float(unm.sum()),
    )


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


@dataclass
class Summary:
    """Headline numbers for the selected destinations."""

    date_from: pd.Timestamp
    date_to: pd.Timestamp
    n_days: int
    n_rows: int
    n_selected: int
    n_dests: int
    production: float | None
    shared: float
    unshared: float | None
    overlap: float | None
    unshared_only: float | None
    consumption: float | None
    unmet: float | None
    peak_production_kw: float | None
    best_day: pd.Timestamp | None
    best_day_shared: float
    days_with_sharing: int


def summarize(data: SharingData, enabled: set[str]) -> Summary:
    df = filter_dests(data, enabled)
    idx = data.frame.index
    split = compute_wasted_split(df)
    sc = shared_cols(df)
    daily_shared = df[sc].sum(axis=1).resample("D").sum() if sc else pd.Series(dtype=float)
    best_day = daily_shared.idxmax() if len(daily_shared) and daily_shared.max() > 0 else None
    is_all = data.fmt == "all"
    consumption = (
        float(sum(data.demand[e].sum() for e in data.dest_eans if e in enabled))
        if is_all else None
    )
    return Summary(
        date_from=idx.min(),
        date_to=idx.max(),
        n_days=int(idx.normalize().nunique()),
        n_rows=data.n_rows,
        n_selected=len([e for e in data.dest_eans if e in enabled]),
        n_dests=len(data.dest_eans),
        production=float(data.production.sum()) if data.production is not None else None,
        shared=split.shared_total,
        unshared=split.unshared_total if is_all else None,
        overlap=split.overlap if is_all else None,
        unshared_only=split.unshared_only if is_all else None,
        consumption=consumption,
        unmet=split.unmet_total if is_all else None,
        # kWh per 15 min * 4 = average kW over the interval
        peak_production_kw=(float(data.production.max()) * 4
                            if data.production is not None else None),
        best_day=best_day,
        best_day_shared=float(daily_shared.max()) if len(daily_shared) else 0.0,
        days_with_sharing=int((daily_shared > 0.005).sum()) if len(daily_shared) else 0,
    )


def per_destination(data: SharingData) -> pd.DataFrame:
    """One row per destination EAN (all destinations, ignoring selection)."""
    rows = []
    total_shared = float(data.frame[shared_cols(data.frame)].sum().sum()) or 1.0
    for ean in data.dest_eans:
        sh = float(sum(data.frame[c].sum() for c in shared_cols(data.frame)
                       if key_dest(c) == ean))
        dem = float(data.demand[ean].sum()) if ean in data.demand else None
        unm = (float(data.frame[key_unmet(ean)].sum())
               if key_unmet(ean) in data.frame else None)
        rows.append({
            "ean": ean,
            "consumption": dem,
            "shared": sh,
            "unmet": unm,
            "coverage_pct": (100 * sh / dem) if dem else None,
            "share_of_shared_pct": 100 * sh / total_shared,
            "data_pct": 100 * data.coverage.get(ean, 0.0),
            "first_data": data.first_data.get(ean),
        })
    return pd.DataFrame(rows)
