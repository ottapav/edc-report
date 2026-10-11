"""The energy figures (kWh), from ``plot_energy_sharing.py``:

* Figure 1, subplot 1 - total energy by flow      (:func:`fig_total_by_flow`)
* Figure 1, subplot 2 - daily energy               (:func:`fig_daily`)
* Figure 1, subplot 3 - heatmap hour × month       (:func:`fig_heatmap`)
* Figure 1, subplot 4 - sharing on one day         (:func:`fig_intraday`)
* Figure 2            - where the production went  (:func:`fig_wasted_pie`)

Colours follow the script: tab10 per destination (fixed by destination order, so
unticking one never repaints the others), greys for grid flows, a blue-grey hatch for
what unticked destinations received, green for the source, black for summary rows, red
for "could have been shared".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from edc_data import (
    KEY_OTHERS, SharingData, WastedSplit, aggregate_grid_flows, filter_dests, key_dest,
    key_kind, key_source, key_unmet, memoized, shared_cols,
)
from i18n import fmt_num, t

from .base import (
    TAB10, THEMES, area, daily_layout, date_text, day_slice, figure, fold, folded, hatch,
    heatmap, hbars, hour_month_pivot, intraday_layout, intraday_legend, no_data, pie,
)

UNIT = "kWh"


def series_label(key: str, names: dict[str, str], lang: str) -> str:
    if key == KEY_OTHERS:
        return t("others_shared", lang)
    if key == "GRID_UNSHARED":
        return f"{t('grid', lang)} {t('unshared_paren', lang)}"
    if key == "GRID_UNMET":
        return f"{t('grid', lang)} {t('unmet_paren', lang)}"
    kind = key_kind(key)
    if kind == "shared":
        return f"{names[key_source(key)]} → {names[key_dest(key)]}"
    if kind == "unmet":
        return f"{names[key_dest(key)]} ← {t('grid', lang)} {t('unmet_paren', lang)}"
    return f"{names[key_source(key)]} → {t('grid', lang)} {t('unshared_paren', lang)}"


def series_colour(key: str, cmap: dict[str, str], th: dict) -> str:
    if key == KEY_OTHERS:
        return th["others"]
    if key == "GRID_UNSHARED" or key_kind(key) == "unshared":
        return th["unshared"]
    if key == "GRID_UNMET" or key_kind(key) == "unmet":
        return th["unmet"]
    return cmap.get(key_dest(key), TAB10[0])


def _areas(fig: go.Figure, frame: pd.DataFrame, cmap: dict, th: dict, names: dict,
           lang: str) -> None:
    for col in frame.columns:
        others = col == KEY_OTHERS
        area(fig, frame.index, frame[col].to_numpy(), series_label(col, names, lang),
             series_colour(col, cmap, th), th, UNIT, pattern=hatch(th) if others else None,
             line_width=1.0 if others else 0.6)


@memoized
def daily_totals(df: pd.DataFrame) -> pd.DataFrame:
    """kWh per day: shared pairs, shared to unselected members, unshared, unmet."""
    return aggregate_grid_flows(df).resample("D").sum().fillna(0)


# ---------------------------------------------------------------------------
# Subplot 1: total energy by flow
# ---------------------------------------------------------------------------


def flow_order(df: pd.DataFrame, data: SharingData,
               top: tuple[str, ...] | None = None) -> list[str]:
    """Destinations (EANs, OTHER for the folded rest) bottom-to-top as
    :func:`fig_total_by_flow` draws them: ascending by shared energy. Pass it to the
    paired chart of the right column, so every member sits on the same row."""
    if top is not None:
        df = fold(df, top)[0]
    totals = df.sum()
    return [key_dest(c) for c in totals[shared_cols(df)].sort_values(ascending=True).index]


def _flow_text(s: float, o: float, u: float, u_lab: str, lang: str) -> str:
    """Bar label: the parts and, on the production row of a partial selection, what
    each part is."""
    if o > 0:
        parts = [(s, t("shared", lang)), (o, t("others_short", lang))] + (
            [(u, u_lab)] if u > 0 else [])
        return (" + ".join(fmt_num(v, lang, 1) for v, _ in parts) + f" {UNIT}<br>("
                + " + ".join(lab for _, lab in parts) + ")")
    if u > 0:
        return f"{fmt_num(s, lang, 1)} + {fmt_num(u, lang, 1)} ({u_lab}) {UNIT}"
    return f"{fmt_num(s, lang, 2)} {UNIT}"


def fig_total_by_flow(
    df: pd.DataFrame,
    data: SharingData,
    names: dict[str, str],
    *,
    lang: str = "cs",
    th: dict | None = None,
    top: tuple[str, ...] | None = None,
    order: list[str] | None = None,
) -> go.Figure:
    """Stacked horizontal bars, bottom-to-top: destinations (shared | unmet), ascending
    by shared or in ``order`` (see :func:`flow_order`); the source (shared | shared to
    unselected | unshared); a gap; summary rows."""
    th = th or THEMES["light"]
    fig = figure(t("total_by_flow_title", lang), lang, 420, th)
    df, names, cmap = folded(df, data, names, lang, top)
    totals = df.sum()
    sc = shared_cols(df)
    if not sc:
        return no_data(fig, lang, th)
    unshared_cols = [c for c in df.columns if key_kind(c) == "unshared"]
    unmet_cols = [c for c in df.columns if key_kind(c) == "unmet"]
    n_sources = len({key_source(c) for c in sc})
    n_dests = len({key_dest(c) for c in sc})
    total_shared = float(totals[sc].sum())
    total_others = float(totals.get(KEY_OTHERS, 0.0))
    total_unshared = float(totals[unshared_cols].sum()) if unshared_cols else 0.0
    total_unmet = float(totals[unmet_cols].sum()) if unmet_cols else 0.0
    unmet_lab, unshared_lab = t("unmet", lang), t("unshared", lang)

    def row(label, s, o, u, c1, c2, u_lab, summary=False):
        return dict(label=label, summary=summary, text=_flow_text(s, o, u, u_lab, lang),
                    segs=[(s, c1, t("shared", lang)), (o, th["others"],
                          t("others_shared", lang)), (u, c2, u_lab)])

    ranked = list(totals[sc].sort_values(ascending=True).index)
    if order is not None:
        rank = {d: i for i, d in enumerate(order)}
        ranked.sort(key=lambda c: rank.get(key_dest(c), len(rank)))     # stable
    rows: list[dict | None] = []
    for col in ranked:
        dst = key_dest(col)
        label = names[dst] if n_sources == 1 else series_label(col, names, lang)
        rows.append(row(label, float(totals[col]), 0.0, float(totals.get(key_unmet(dst), 0.0)),
                        cmap.get(dst, TAB10[0]), th["unmet"], unmet_lab))
    src_label = names[key_source(sc[0])] if n_sources == 1 else t("source", lang)
    rows.append(row(src_label, total_shared, total_others, total_unshared, th["source"],
                    th["unshared"], unshared_lab))
    if n_sources > 1 or n_dests > 1:
        rows.append(None)                                   # visual gap
    if n_sources > 1:
        rows.append(row(t("total_source", lang), total_shared, total_others, total_unshared,
                        th["total"], th["unshared"], unshared_lab, summary=True))
    if n_dests > 1:
        rows.append(row(t("total_destination", lang), total_shared, 0.0, total_unmet,
                        th["total"], th["unmet"], unmet_lab, summary=True))

    slots = [dict(name=t("shared", lang)),
             dict(name=t("others_shared", lang), pattern=hatch(th)),
             dict(name=f"{unmet_lab} / {unshared_lab}")]
    if total_others <= 0:                    # no unselected members: no hatched segment
        slots.pop(1)
        for r in rows:
            if r is not None:
                r["segs"].pop(1)
    return hbars(fig, rows, slots, th=th, unit=UNIT, hover_decimals=1,
                 xtitle=t("total_energy_xlabel", lang),
                 xpad=1.3 if total_others > 0 else 1.35, inside_above=0.55,
                 extra_height=14 if total_others > 0 else 0)


# ---------------------------------------------------------------------------
# Subplot 2: daily totals
# ---------------------------------------------------------------------------


def fig_daily(
    df: pd.DataFrame,
    data: SharingData,
    names: dict[str, str],
    *,
    lang: str = "cs",
    sel_day: str | None = None,
    th: dict | None = None,
    top: tuple[str, ...] | None = None,
) -> go.Figure:
    """Stacked areas of daily kWh: shared per destination, shared to unselected
    members, unshared, unmet. ``sel_day`` draws the dashed selected-day marker; click
    a day to select it."""
    th = th or THEMES["light"]
    fig = figure(t("daily_title", lang), lang, 460, th)
    df, names, cmap = folded(df, data, names, lang, top)
    daily = daily_totals(df)
    if daily.empty or len(daily.columns) == 0:
        return no_data(fig, lang, th)
    _areas(fig, daily, cmap, th, names, lang)
    return daily_layout(fig, daily.index, t("daily_ylabel", lang), sel_day, lang, th)


# ---------------------------------------------------------------------------
# Figure 2: where the production went
# ---------------------------------------------------------------------------


def fig_wasted_pie(split: WastedSplit, lang: str = "cs", th: dict | None = None,
                   exact_based: bool = False) -> go.Figure:
    """Where the production went. The slices always add up to the production:
    shared to the selected members, shared to the unselected ones, could have been
    shared (unshared while selected members bought from the grid; with ``exact_based``
    what the exact method adds to them), unshared."""
    th = th or THEMES["light"]
    fig = figure(t("pie_title", lang), lang, 500, th)
    total = split.shared_total + split.shared_others + split.unshared_only + split.overlap
    if total <= 0:
        return no_data(fig, lang, th)
    slices = [   # label, value, colour, hatched, pulled out
        (t("pie_shared", lang), split.shared_total, th["source"], False, False),
        (t("pie_others", lang), split.shared_others, th["others"], True, False),
        (t("pie_wasted", lang), split.overlap, th["wasted"], False, True),
        (t("pie_unshared_only", lang), split.unshared_only, th["unshared"], False, False),
    ]
    note = [t("pie_union", lang).format(total=fmt_num(total, lang)),
            t("pie_subtitle_exact" if exact_based else "pie_subtitle", lang)]
    if split.overlap <= 0:
        note.append(t("pie_no_overlap", lang))
    return pie(fig, slices, note, th=th, unit=UNIT, hover_decimals=1)


# ---------------------------------------------------------------------------
# Subplot 4: one day
# ---------------------------------------------------------------------------


@memoized
def intraday_ymax(df: pd.DataFrame, day: str | None = None) -> float:
    """Peak kWh per 15 min of the stacked flows. With ``day`` only that calendar
    day counts, so the plot fills the panel; without it the whole dataset does
    (one scale for every day)."""
    agg = aggregate_grid_flows(df).fillna(0)
    if day is not None and not agg.empty:
        agg = day_slice(agg, day)[1]
    if agg.empty or len(agg.columns) == 0:
        return 1.0
    peak = float(agg.sum(axis=1).max())
    return peak if np.isfinite(peak) and peak > 0 else 1.0


def fig_intraday(
    df: pd.DataFrame,
    data: SharingData,
    names: dict[str, str],
    day: str | None,
    *,
    y_max: float | None = None,
    lang: str = "cs",
    th: dict | None = None,
    top: tuple[str, ...] | None = None,
) -> go.Figure:
    """Stacked areas per 15 min for one calendar day."""
    th = th or THEMES["light"]
    df, names, cmap = folded(df, data, names, lang, top)
    agg = aggregate_grid_flows(df)
    day_ts, day_df = day_slice(agg, day)
    fig = figure(t("sharing_on", lang).format(date=date_text(day_ts, lang)), lang, 440, th)
    if y_max is None:
        y_max = intraday_ymax(df, str(day_ts.date()))
    intraday_layout(fig, day_ts, t("intraday_ylabel", lang), y_max)
    if day_df.empty or len(agg.columns) == 0:
        return no_data(fig, lang, th, hide_axes=False)
    _areas(fig, day_df.fillna(0), cmap, th, names, lang)
    intraday_legend(fig)
    return fig


# ---------------------------------------------------------------------------
# Subplot 3: heatmap hour × month
# ---------------------------------------------------------------------------


def heat_metrics(data: SharingData) -> tuple[str, ...]:
    """What the heatmap can show: for an all report the total production or the total
    consumption of the selected destinations; the part report only has the energy
    shared to them."""
    return ("production", "consumption") if data.fmt == "all" else ("shared",)


@memoized
def heat_pivot(data: SharingData, enabled: set[str], metric: str = "production") -> pd.DataFrame:
    """Mean kWh per 15-min interval, hour-of-day x month.

    ``production`` = the producer's whole production (does not depend on the ticked
    destinations, same as the tile); ``consumption`` = demand of the ticked
    destinations (shared + bought from the grid); ``shared`` = shared to them.
    """
    if metric == "production" and data.production is not None:
        series = data.production
    elif metric == "consumption" and data.demand:
        parts = [data.demand[e] for e in data.dest_eans if e in enabled and e in data.demand]
        series = (pd.concat(parts, axis=1).sum(axis=1) if parts
                  else pd.Series(0.0, index=data.frame.index))
    else:
        cols = shared_cols(filter_dests(data, enabled))
        if not cols:
            return pd.DataFrame()
        series = filter_dests(data, enabled)[cols].sum(axis=1)
    return hour_month_pivot(series)


def fig_heatmap(pivot: pd.DataFrame, metric: str = "production", *,
                z_max: float | None = None, lang: str = "cs",
                th: dict | None = None) -> go.Figure:
    th = th or THEMES["light"]
    fig = figure(t(f"heatmap_title_{metric}", lang), lang, 440, th)
    return heatmap(fig, pivot, cbar=t("heatmap_cbar", lang), unit=UNIT, z_max=z_max,
                   lang=lang, th=th)
