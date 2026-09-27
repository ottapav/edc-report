"""Plotly versions of Figure 1 (subplots 1 & 2) and Figure 2 (pie).

Colours follow ``plot_energy_sharing.py``: tab10 per destination (fixed by
destination order, so unticking one never repaints the others), greys for
grid flows, green for the source, black for summary rows, red for "could
have been shared".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from i18n import fmt_num, month_label, plotly_separators, t
from sharel_core import (
    SharingData, WastedSplit, aggregate_grid_flows, key_dest, key_kind,
    key_source, key_unmet, shared_cols,
)

TAB10 = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
         "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
GREY_UNSHARED = "#8c8c8c"   # (0.55, 0.55, 0.55)
GREY_UNMET = "#c7c7c7"      # (0.78, 0.78, 0.78)
RED_WASTED = "#cc3326"      # (0.80, 0.20, 0.15)
SOURCE_GREEN = "#339933"    # (0.20, 0.60, 0.20)
TOTAL_BLACK = "rgba(0,0,0,0.9)"

FONT = dict(family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif", size=12,
            color="#1f2328")


def colour_map(data: SharingData) -> dict[str, str]:
    """Destination EAN -> tab10 colour, fixed by file order."""
    return {e: TAB10[i % 10] for i, e in enumerate(data.dest_eans)}


def _rgba(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def series_label(key: str, names: dict[str, str], lang: str) -> str:
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


def series_colour(key: str, cmap: dict[str, str]) -> str:
    if key == "GRID_UNSHARED" or key_kind(key) == "unshared":
        return GREY_UNSHARED
    if key == "GRID_UNMET" or key_kind(key) == "unmet":
        return GREY_UNMET
    return cmap.get(key_dest(key), TAB10[0])


def _base_layout(fig: go.Figure, title: str, lang: str, height: int) -> None:
    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left", font=dict(size=15)),
        height=height,
        margin=dict(l=10, r=20, t=50, b=10),
        font=FONT,
        paper_bgcolor="white",
        plot_bgcolor="white",
        separators=plotly_separators(lang),
        hoverlabel=dict(font=dict(family=FONT["family"], size=12)),
    )


def _no_data(fig: go.Figure, lang: str) -> go.Figure:
    fig.add_annotation(text=t("no_data", lang), x=0.5, y=0.5, xref="paper",
                       yref="paper", showarrow=False, font=dict(size=14, color="#666"))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


# ---------------------------------------------------------------------------
# Subplot 1: total energy by flow
# ---------------------------------------------------------------------------


def fig_total_by_flow(
    df: pd.DataFrame,
    data: SharingData,
    names: dict[str, str],
    *,
    show_unshared: bool = True,
    show_unmet: bool = True,
    lang: str = "cs",
) -> go.Figure:
    """Stacked horizontal bars, bottom-to-top: destinations (shared | unmet,
    ascending by shared), source (shared | unshared), gap, summary rows."""
    fig = go.Figure()
    _base_layout(fig, t("total_by_flow_title", lang), lang, 420)
    totals = df.sum()
    cmap = colour_map(data)
    sc = shared_cols(df)
    if not sc:
        return _no_data(fig, lang)

    unshared_cols = [c for c in df.columns if key_kind(c) == "unshared"]
    unmet_cols = [c for c in df.columns if key_kind(c) == "unmet"]
    n_sources = len({key_source(c) for c in sc})
    n_dests = len({key_dest(c) for c in sc})
    show_total_source = show_unshared and n_sources > 1
    show_total_dest = show_unmet and n_dests > 1

    rows: list[dict] = []  # label, shared, second, c1, c2, second_label, summary
    for col in totals[sc].sort_values(ascending=True).index:
        dst = key_dest(col)
        label = names[dst] if n_sources == 1 else series_label(col, names, lang)
        u = float(totals.get(key_unmet(dst), 0.0)) if show_unmet else 0.0
        rows.append(dict(label=label, s=float(totals[col]), u=u,
                         c1=cmap.get(dst, TAB10[0]), c2=GREY_UNMET,
                         u_lab=t("unmet", lang), summary=False))

    total_shared = float(totals[sc].sum())
    total_unshared = float(totals[unshared_cols].sum()) if show_unshared and unshared_cols else 0.0
    src_label = names[key_source(sc[0])] if n_sources == 1 else t("source", lang)
    rows.append(dict(label=src_label, s=total_shared, u=total_unshared,
                     c1=SOURCE_GREEN, c2=GREY_UNSHARED,
                     u_lab=t("unshared", lang), summary=False))

    total_unmet = float(totals[unmet_cols].sum()) if show_unmet and unmet_cols else 0.0
    if show_total_source or show_total_dest:
        rows.append(None)  # visual gap
    if show_total_source:
        rows.append(dict(label=t("total_source", lang), s=total_shared, u=total_unshared,
                         c1=TOTAL_BLACK, c2=GREY_UNSHARED,
                         u_lab=t("unshared", lang), summary=True))
    if show_total_dest:
        rows.append(dict(label=t("total_destination", lang), s=total_shared, u=total_unmet,
                         c1=TOTAL_BLACK, c2=GREY_UNMET,
                         u_lab=t("unmet", lang), summary=True))

    y = list(range(len(rows)))
    real = [(i, r) for i, r in enumerate(rows) if r is not None]
    max_val = max((r["s"] + r["u"] for _, r in real), default=0.0) or 1.0

    fig.add_bar(
        y=[i for i, _ in real], x=[r["s"] for _, r in real], orientation="h",
        marker=dict(color=[r["c1"] for _, r in real], line=dict(color="white", width=1)),
        name=t("shared", lang),
        customdata=[r["label"] for _, r in real],
        hovertemplate="%{customdata}<br>" + t("shared", lang) + ": %{x:,.1f} kWh<extra></extra>",
    )
    fig.add_bar(
        y=[i for i, _ in real], x=[r["u"] for _, r in real], orientation="h",
        base=[r["s"] for _, r in real],
        marker=dict(color=[r["c2"] for _, r in real], line=dict(color="white", width=1)),
        name=f"{t('unmet', lang)} / {t('unshared', lang)}",
        customdata=[[r["label"], r["u_lab"]] for _, r in real],
        hovertemplate="%{customdata[0]}<br>%{customdata[1]}: %{x:,.1f} kWh<extra></extra>",
    )
    for i, r in real:
        width = r["s"] + r["u"]
        if r["u"] > 0:
            txt = (f"{fmt_num(r['s'], lang, 1)} + {fmt_num(r['u'], lang, 1)} "
                   f"({r['u_lab']}) kWh")
        else:
            txt = f"{fmt_num(width, lang, 2)} kWh"
        if r["summary"]:
            txt = f"<b>{txt}</b>"
        # long bars: label inside the (light grey) second segment, else after the bar
        inside = width > 0.55 * max_val
        fig.add_annotation(
            x=width - max_val * 0.01 if inside else width + max_val * 0.01, y=i,
            text=txt, showarrow=False, xanchor="right" if inside else "left",
            font=dict(size=11, color="#1f2328"),
            bgcolor="rgba(255,255,255,0.8)" if inside else None, borderpad=2,
        )

    fig.update_layout(barmode="overlay", showlegend=False, bargap=0.25)
    fig.update_xaxes(title=t("total_energy_xlabel", lang), range=[0, max_val * 1.35],
                     showgrid=True, gridcolor="#e8e8e8", zeroline=False,
                     tickformat=",.0f")
    fig.update_yaxes(
        tickvals=y,
        ticktext=[("" if r is None else (f"<b>{r['label']}</b>" if r["summary"] else r["label"]))
                  for r in rows],
        range=[-0.6, len(rows) - 0.4], showgrid=False, ticklabelstandoff=8,
    )
    fig.update_layout(height=max(320, 90 + 38 * len(rows)))
    return fig


# ---------------------------------------------------------------------------
# Subplot 2: daily totals
# ---------------------------------------------------------------------------


def _month_ticks(index: pd.DatetimeIndex, lang: str) -> tuple[list, list]:
    start = index.min().to_period("M").to_timestamp()
    months = pd.date_range(start, index.max(), freq="MS")
    months = [m for m in months if m >= index.min()] or [index.min()]
    return list(months), [month_label(m, lang) for m in months]


def fig_daily(
    df: pd.DataFrame,
    data: SharingData,
    names: dict[str, str],
    *,
    yscale: str = "linear",
    show_unshared: bool = True,
    show_unmet: bool = True,
    lang: str = "cs",
    sel_day: str | None = None,
) -> go.Figure:
    """Stacked areas of daily kWh (linear) or unstacked lines (log).
    ``sel_day`` draws the dashed selected-day marker; click a day to select it."""
    agg = aggregate_grid_flows(df)
    if not show_unshared:
        agg = agg.drop(columns="GRID_UNSHARED", errors="ignore")
    if not show_unmet:
        agg = agg.drop(columns="GRID_UNMET", errors="ignore")
    log = yscale == "log"
    fig = go.Figure()
    _base_layout(fig, t("daily_title_lines" if log else "daily_title", lang), lang, 420)
    if agg.empty or len(agg.columns) == 0:
        return _no_data(fig, lang)

    daily = agg.resample("D").sum().fillna(0)
    cmap = colour_map(data)
    date_txt = daily.index.strftime("%d.%m.%Y" if lang == "cs" else "%Y-%m-%d")
    for col in daily.columns:
        colour = series_colour(col, cmap)
        vals = daily[col].to_numpy()
        common = dict(
            x=daily.index, name=series_label(col, names, lang),
            hovertemplate="%{y:,.2f} kWh",
            customdata=date_txt,
        )
        if log:
            fig.add_scatter(y=np.where(vals > 0, vals, np.nan), mode="lines",
                            line=dict(color=colour, width=1.2), opacity=0.9,
                            connectgaps=False, **common)
        else:
            fig.add_scatter(y=vals, mode="lines", stackgroup="one",
                            line=dict(color=colour, width=0.6),
                            fillcolor=_rgba(colour, 0.75), **common)

    tickvals, ticktext = _month_ticks(daily.index, lang)
    fig.update_xaxes(tickvals=tickvals, ticktext=ticktext, tickangle=-30,
                     showgrid=True, gridcolor="#ececec",
                     hoverformat="%d.%m.%Y" if lang == "cs" else "%Y-%m-%d")
    fig.update_yaxes(title=t("daily_ylabel", lang), showgrid=True, gridcolor="#ececec",
                     type="log" if log else "linear", zeroline=False)
    if log:
        ymax = float(np.nanmax(daily.to_numpy())) if daily.size else 1.0
        fig.update_yaxes(range=[-2, np.log10(max(ymax, 0.1)) + 0.1], dtick=1,
                         tickformat=",.2~f")
    fig.update_layout(
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="left", x=0,
                    font=dict(size=11)),
        margin=dict(l=10, r=20, t=50, b=10),
        height=460,
        shapes=day_marker(sel_day),
        clickmode="event",
    )
    return fig


# ---------------------------------------------------------------------------
# Figure 2: pie of source disposition
# ---------------------------------------------------------------------------


def fig_wasted_pie(split: WastedSplit, lang: str = "cs") -> go.Figure:
    fig = go.Figure()
    _base_layout(fig, t("pie_title", lang), lang, 440)
    total = split.shared_total + split.unshared_only + split.overlap
    if total <= 0:
        return _no_data(fig, lang)
    slices = [
        (t("pie_shared", lang), split.shared_total, SOURCE_GREEN),
        (t("pie_wasted", lang), split.overlap, RED_WASTED),
        (t("pie_unshared_only", lang), split.unshared_only, GREY_UNSHARED),
    ]
    slices = [s for s in slices if s[1] > 0]
    wasted = t("pie_wasted", lang)
    fig.add_pie(
        labels=[s[0] for s in slices],
        values=[s[1] for s in slices],
        marker=dict(colors=[s[2] for s in slices], line=dict(color="white", width=2)),
        pull=[0.06 if s[0] == wasted else 0 for s in slices],
        sort=False, direction="clockwise", rotation=0,
        texttemplate="%{label}<br>%{value:,.0f} kWh<br>%{percent:.1%}",
        textposition="outside",
        hovertemplate="%{label}: %{value:,.1f} kWh (%{percent:.1%})<extra></extra>",
        showlegend=False,
    )
    note = [t("pie_union", lang).format(total=fmt_num(total, lang)), t("pie_subtitle", lang)]
    if split.overlap <= 0:
        note.append(t("pie_no_overlap", lang))
    fig.add_annotation(text="<br>".join(note), x=0.5, y=0, yshift=-58, xref="paper",
                       yref="paper", yanchor="top", showarrow=False,
                       font=dict(size=11, color="#555"))
    fig.update_layout(margin=dict(l=40, r=40, t=60, b=100 + 14 * (len(note) - 2)),
                      height=500)
    return fig


# ---------------------------------------------------------------------------
# Selected-day marker (subplot 2), subplot 4: single day, subplot 3: heatmap
# ---------------------------------------------------------------------------

INTRADAY_XSTART_HOUR = 6
INTRADAY_XEND_HOUR = 21


def day_marker(day: str | None) -> list[dict]:
    """Dashed vertical line on the daily plot at the selected day (script: axvline)."""
    if not day:
        return []
    return [dict(type="line", xref="x", yref="paper", x0=day, x1=day, y0=0, y1=1,
                 line=dict(color="black", width=1.5, dash="dash"), layer="above")]


def _grid_filtered(df: pd.DataFrame, show_unshared: bool, show_unmet: bool) -> pd.DataFrame:
    agg = aggregate_grid_flows(df)
    if not show_unshared:
        agg = agg.drop(columns="GRID_UNSHARED", errors="ignore")
    if not show_unmet:
        agg = agg.drop(columns="GRID_UNMET", errors="ignore")
    return agg


def intraday_ymax(df: pd.DataFrame, show_unshared: bool, show_unmet: bool,
                  stacked: bool = True) -> float:
    """Peak kWh per 15 min over the whole dataset (same scale for every day)."""
    agg = _grid_filtered(df, show_unshared, show_unmet).fillna(0)
    if agg.empty or len(agg.columns) == 0:
        return 1.0
    peak = float(agg.sum(axis=1).max()) if stacked else float(agg.to_numpy().max())
    return peak if np.isfinite(peak) and peak > 0 else 1.0


def fig_intraday(
    df: pd.DataFrame,
    data: SharingData,
    names: dict[str, str],
    day: str | None,
    *,
    y_max: float | None = None,
    yscale: str = "linear",
    show_unshared: bool = True,
    show_unmet: bool = True,
    lang: str = "cs",
) -> go.Figure:
    """Stacked areas per 15 min for one calendar day (lines on a log axis)."""
    log = yscale == "log"
    agg = _grid_filtered(df, show_unshared, show_unmet)
    day_ts = pd.Timestamp(day).normalize() if day else agg.index.normalize().max()
    date_txt = day_ts.strftime("%d.%m.%Y" if lang == "cs" else "%Y-%m-%d")
    title = t("sharing_on", lang).format(date=date_txt) + (t("lines_suffix", lang) if log else "")
    fig = go.Figure()
    _base_layout(fig, title, lang, 440)
    if y_max is None:
        y_max = intraday_ymax(df, show_unshared, show_unmet, stacked=not log)
    day_df = agg.loc[agg.index.normalize() == day_ts].fillna(0)
    x0 = day_ts + pd.Timedelta(hours=INTRADAY_XSTART_HOUR)
    x1 = day_ts + pd.Timedelta(hours=INTRADAY_XEND_HOUR)
    fig.update_xaxes(range=[x0, x1], dtick=3 * 3600 * 1000, tickformat="%H:%M",
                     hoverformat="%H:%M", showgrid=True, gridcolor="#ececec")
    fig.update_yaxes(title=t("intraday_ylabel", lang), showgrid=True, gridcolor="#ececec",
                     zeroline=False, type="log" if log else "linear",
                     range=([-3, np.log10(y_max) + 0.05] if log else [0, y_max * 1.02]))
    if day_df.empty or len(agg.columns) == 0:
        fig.add_annotation(text=t("no_data", lang), x=0.5, y=0.5, xref="paper",
                           yref="paper", showarrow=False, font=dict(size=14, color="#666"))
        return fig
    cmap = colour_map(data)
    for col in day_df.columns:
        colour = series_colour(col, cmap)
        vals = day_df[col].to_numpy()
        common = dict(x=day_df.index, name=series_label(col, names, lang),
                      hovertemplate="%{y:,.2f} kWh")
        if log:
            fig.add_scatter(y=np.where(vals > 0, vals, np.nan), mode="lines",
                            line=dict(color=colour, width=1.2), **common)
        else:
            fig.add_scatter(y=vals, mode="lines", stackgroup="one",
                            line=dict(color=colour, width=0.6),
                            fillcolor=_rgba(colour, 0.75), **common)
    fig.update_layout(
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0,
                    font=dict(size=11)),
    )
    return fig


HEAT_METRICS = ("production", "shared", "unmet")


def heat_pivot(df: pd.DataFrame, metric: str = "production") -> pd.DataFrame:
    """Mean kWh per 15-min interval, hour-of-day x month.

    ``production`` = everything leaving the source (shared + unshared), as in the
    script; ``shared`` = shared only; ``unmet`` = demand covered from the grid.
    """
    if metric == "shared":
        cols = [c for c in df.columns if key_kind(c) == "shared"]
    elif metric == "unmet":
        cols = [c for c in df.columns if key_kind(c) == "unmet"]
    else:
        cols = [c for c in df.columns if key_kind(c) != "unmet"]
    if not cols:
        return pd.DataFrame()
    total = df[cols].sum(axis=1).to_frame("total")
    total["hour"] = total.index.hour
    total["month"] = total.index.to_period("M")
    return total.pivot_table(values="total", index="hour", columns="month", aggfunc="mean")


def fig_heatmap(pivot: pd.DataFrame, metric: str = "production", *,
                z_max: float | None = None, lang: str = "cs") -> go.Figure:
    fig = go.Figure()
    _base_layout(fig, t(f"heatmap_title_{metric}", lang), lang, 440)
    if pivot.empty:
        return _no_data(fig, lang)
    months = [month_label(p.to_timestamp(), lang) for p in pivot.columns]
    fig.add_heatmap(
        z=pivot.to_numpy(), x=months, y=list(pivot.index), colorscale="YlOrRd",
        zmin=0, zmax=z_max if z_max else float(np.nanmax(pivot.to_numpy()) or 1.0),
        colorbar=dict(title=dict(text=t("heatmap_cbar", lang), side="right"),
                      thickness=12, tickformat=",.2f"),
        hovertemplate="%{x}, %{y}:00<br>%{z:,.3f} kWh<extra></extra>",
        xgap=1, ygap=1,
    )
    fig.update_yaxes(title=t("hour_of_day", lang), dtick=2, range=[-0.5, 23.5])
    fig.update_xaxes(tickangle=-30, type="category")
    return fig
