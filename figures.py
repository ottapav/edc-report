"""Plotly versions of the figures of ``plot_energy_sharing.py``.

* Figure 1, subplot 1 - total energy by flow      (:func:`fig_total_by_flow`)
* Figure 1, subplot 2 - daily energy               (:func:`fig_daily`)
* Figure 1, subplot 3 - heatmap hour × month       (:func:`fig_heatmap`)
* Figure 1, subplot 4 - sharing on one day         (:func:`fig_intraday`)
* Figure 2            - shared / wasted pie        (:func:`fig_wasted_pie`)

Colours follow the script: tab10 per destination (fixed by destination order, so
unticking one never repaints the others), greys for grid flows, a blue-grey for
what unticked destinations received, green for the source, black for summary
rows, red for "could have been shared". Every figure
takes a theme (:data:`THEMES`); the dark theme uses its own greys, summary colour
and heatmap scale rather than an inverted light one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from i18n import fmt_num, month_label, plotly_separators, t
from edc_data import (
    KEY_OTHERS, SharingData, WastedSplit, aggregate_grid_flows, filter_dests, key_dest,
    key_kind, key_source, key_unmet, memoized, shared_cols,
)

TAB10 = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
         "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
FONT_FAMILY = "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"

THEMES: dict[str, dict] = {
    "light": dict(
        paper="#ffffff", ink="#1f2328", muted="#57606a", grid="#ececec",
        unshared="#8c8c8c", unmet="#c7c7c7", total="rgba(0,0,0,0.9)", others="#a9b8cc",
        source="#339933", wasted="#cc3326", marker="#000000",
        label_bg="rgba(255,255,255,0.85)", hover_bg="#ffffff", hover_border="#d0d7de",
        heat="YlOrRd", area_alpha=0.75,
    ),
    "dark": dict(
        paper="#161b22", ink="#e6edf3", muted="#9da7b3", grid="#2a313c",
        unshared="#7d8590", unmet="#3d444d", total="#e6edf3", others="#5d6b82",
        source="#3da63d", wasted="#e5534b", marker="#e6edf3",
        label_bg="rgba(22,27,34,0.85)", hover_bg="#1c2128", hover_border="#3d444d",
        # dark surface: low values stay near the surface, high values glow
        heat=[[0.0, "#1c2128"], [0.2, "#4a1d1a"], [0.45, "#a52a22"],
              [0.7, "#e8742a"], [1.0, "#ffe08a"]],
        area_alpha=0.85,
    ),
}


MAX_SERIES = 10            # tab10 has 10 hues; more destinations fold into "Others"
OTHER = "__other__"        # pseudo destination EAN of the folded rest
OTHER_COLOUR = TAB10[9]


def theme(name: str | None) -> dict:
    return THEMES.get(name or "light", THEMES["light"])


def top_dests(df: pd.DataFrame, data: SharingData) -> tuple[str, ...] | None:
    """Destinations shown individually when there are more than MAX_SERIES.

    The 9 with the most shared energy in ``df`` (pass today's report, so the
    recomputed column folds the same members and keeps the same colours); the
    rest is drawn as one "Others" series. ``None`` = no folding needed.
    """
    if len(data.dest_eans) <= MAX_SERIES:
        return None
    totals: dict[str, float] = {}
    for c in shared_cols(df):
        totals[key_dest(c)] = totals.get(key_dest(c), 0.0) + float(df[c].sum())
    ranked = sorted(totals, key=lambda e: -totals[e])
    return tuple(ranked[:MAX_SERIES - 1])


def colour_map(data: SharingData, top: tuple[str, ...] | None = None) -> dict[str, str]:
    """Destination EAN -> tab10 colour: by file order for up to 10 destinations;
    for larger groups by rank among the shown ones, the rest share OTHER_COLOUR
    (hues are never cycled)."""
    if top is None:
        return {e: TAB10[i % 10] for i, e in enumerate(data.dest_eans)}
    cmap = {e: OTHER_COLOUR for e in data.dest_eans}
    cmap.update({e: TAB10[i] for i, e in enumerate(top)})
    cmap[OTHER] = OTHER_COLOUR
    return cmap


@memoized
def _fold(df: pd.DataFrame, top: tuple[str, ...]) -> tuple[pd.DataFrame, int]:
    """Sum shared / unmet of the destinations outside ``top`` into OTHER columns."""
    keep, other_shared, other_unmet, rest = [], [], [], set()
    src = None
    for c in df.columns:
        d = key_dest(c)
        if d is None or d in top:
            keep.append(c)
        elif key_kind(c) == "shared":
            other_shared.append(c)
            src = src or key_source(c)
            rest.add(d)
        else:
            other_unmet.append(c)
            rest.add(d)
    out = df[keep].copy()
    if other_shared:
        out[f"shared|{src}|{OTHER}"] = df[other_shared].sum(axis=1)
    if other_unmet:
        out[f"unmet|{OTHER}"] = df[other_unmet].sum(axis=1)
    return out, len(rest)


def _folded(df: pd.DataFrame, data: SharingData, names: dict[str, str], lang: str,
            top: tuple[str, ...] | None):
    """(frame, names, colours) for plotting, with the rest folded when needed."""
    if top is None:
        return df, names, colour_map(data)
    out, n_rest = _fold(df, top)
    names = dict(names)
    names[OTHER] = t("others", lang).format(n=n_rest)
    return out, names, colour_map(data, top)


def _rgba(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


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


def _hatch(th: dict) -> dict:
    """Diagonal stripes: marks "went to unselected members", which is neither one of
    the selected members' colours nor one of the greys of the grid flows."""
    return dict(shape="/", size=7, solidity=0.45, fgcolor=th["others"],
                bgcolor=_rgba(th["others"], 0.25))


def _area(fig: go.Figure, x, y, col: str, cmap: dict, th: dict, names: dict, lang: str) -> None:
    """One stacked area of the daily / hourly plot."""
    colour = series_colour(col, cmap, th)
    fill = (dict(fillpattern=_hatch(th)) if col == KEY_OTHERS
            else dict(fillcolor=_rgba(colour, th["area_alpha"])))
    fig.add_scatter(x=x, y=y, mode="lines", stackgroup="one",
                    name=series_label(col, names, lang), hovertemplate="%{y:,.2f} kWh",
                    line=dict(color=colour, width=0.6 if col != KEY_OTHERS else 1.0), **fill)


def _figure(title: str, lang: str, height: int, th: dict) -> go.Figure:
    """Empty figure with the common layout, set in one validated call."""
    return go.Figure(layout=dict(
        title=dict(text=title, x=0.01, xanchor="left", font=dict(size=15)),
        height=height,
        margin=dict(l=10, r=20, t=50, b=10),
        font=dict(family=FONT_FAMILY, size=12, color=th["ink"]),
        paper_bgcolor=th["paper"],
        plot_bgcolor=th["paper"],
        separators=plotly_separators(lang),
        hoverlabel=dict(font=dict(family=FONT_FAMILY, size=12, color=th["ink"]),
                        bgcolor=th["hover_bg"], bordercolor=th["hover_border"]),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(gridcolor=th["grid"], linecolor=th["grid"], zerolinecolor=th["grid"]),
        yaxis=dict(gridcolor=th["grid"], linecolor=th["grid"], zerolinecolor=th["grid"]),
        meta=dict(marker=th["marker"]),   # read by the clientside day-marker callback
    ))


def _no_data(fig: go.Figure, lang: str, th: dict) -> go.Figure:
    fig.add_annotation(text=t("no_data", lang), x=0.5, y=0.5, xref="paper",
                       yref="paper", showarrow=False, font=dict(size=14, color=th["muted"]))
    fig.update_layout(xaxis_visible=False, yaxis_visible=False)
    return fig


@memoized
def daily_totals(df: pd.DataFrame) -> pd.DataFrame:
    """kWh per day: shared pairs, shared to unselected members, unshared, unmet."""
    return aggregate_grid_flows(df).resample("D").sum().fillna(0)


# ---------------------------------------------------------------------------
# Subplot 1: total energy by flow
# ---------------------------------------------------------------------------


def fig_total_by_flow(
    df: pd.DataFrame,
    data: SharingData,
    names: dict[str, str],
    *,
    lang: str = "cs",
    th: dict | None = None,
    top: tuple[str, ...] | None = None,
) -> go.Figure:
    """Stacked horizontal bars, bottom-to-top: destinations (shared | unmet),
    ascending by shared), source (shared | shared to unselected | unshared), gap,
    summary rows."""
    th = th or THEMES["light"]
    fig = _figure(t("total_by_flow_title", lang), lang, 420, th)
    df, names, cmap = _folded(df, data, names, lang, top)
    totals = df.sum()
    sc = shared_cols(df)
    if not sc:
        return _no_data(fig, lang, th)

    unshared_cols = [c for c in df.columns if key_kind(c) == "unshared"]
    unmet_cols = [c for c in df.columns if key_kind(c) == "unmet"]
    n_sources = len({key_source(c) for c in sc})
    n_dests = len({key_dest(c) for c in sc})
    show_total_source = n_sources > 1
    show_total_dest = n_dests > 1

    # every row: s = shared | o = shared to unselected members | u = unmet / unshared
    rows: list[dict | None] = []
    for col in totals[sc].sort_values(ascending=True).index:
        dst = key_dest(col)
        label = names[dst] if n_sources == 1 else series_label(col, names, lang)
        rows.append(dict(label=label, s=float(totals[col]), o=0.0,
                         u=float(totals.get(key_unmet(dst), 0.0)),
                         c1=cmap.get(dst, TAB10[0]), c2=th["unmet"],
                         u_lab=t("unmet", lang), summary=False))

    total_shared = float(totals[sc].sum())
    total_others = float(totals.get(KEY_OTHERS, 0.0))
    total_unshared = float(totals[unshared_cols].sum()) if unshared_cols else 0.0
    src_label = names[key_source(sc[0])] if n_sources == 1 else t("source", lang)
    rows.append(dict(label=src_label, s=total_shared, o=total_others, u=total_unshared,
                     c1=th["source"], c2=th["unshared"],
                     u_lab=t("unshared", lang), summary=False))

    total_unmet = float(totals[unmet_cols].sum()) if unmet_cols else 0.0
    if show_total_source or show_total_dest:
        rows.append(None)  # visual gap
    if show_total_source:
        rows.append(dict(label=t("total_source", lang), s=total_shared, o=total_others,
                         u=total_unshared, c1=th["total"], c2=th["unshared"],
                         u_lab=t("unshared", lang), summary=True))
    if show_total_dest:
        rows.append(dict(label=t("total_destination", lang), s=total_shared, o=0.0,
                         u=total_unmet, c1=th["total"], c2=th["unmet"],
                         u_lab=t("unmet", lang), summary=True))

    y = list(range(len(rows)))
    real = [(i, r) for i, r in enumerate(rows) if r is not None]
    max_val = max((r["s"] + r["o"] + r["u"] for _, r in real), default=0.0) or 1.0
    ys = [i for i, _ in real]
    others_lab = t("others_shared", lang)

    fig.add_bar(
        y=ys, x=[r["s"] for _, r in real], orientation="h",
        marker=dict(color=[r["c1"] for _, r in real], line=dict(color=th["paper"], width=1)),
        name=t("shared", lang),
        customdata=[r["label"] for _, r in real],
        hovertemplate="%{customdata}<br>" + t("shared", lang) + ": %{x:,.1f} kWh<extra></extra>",
    )
    if total_others > 0:
        fig.add_bar(
            y=ys, x=[r["o"] for _, r in real], orientation="h",
            base=[r["s"] for _, r in real],
            marker=dict(color=th["others"], line=dict(color=th["paper"], width=1),
                        pattern=_hatch(th)),
            name=others_lab, customdata=[r["label"] for _, r in real],
            hovertemplate="%{customdata}<br>" + others_lab + ": %{x:,.1f} kWh<extra></extra>",
        )
    fig.add_bar(
        y=ys, x=[r["u"] for _, r in real], orientation="h",
        base=[r["s"] + r["o"] for _, r in real],
        marker=dict(color=[r["c2"] for _, r in real], line=dict(color=th["paper"], width=1)),
        name=f"{t('unmet', lang)} / {t('unshared', lang)}",
        customdata=[[r["label"], r["u_lab"]] for _, r in real],
        hovertemplate="%{customdata[0]}<br>%{customdata[1]}: %{x:,.1f} kWh<extra></extra>",
    )
    annotations = []
    for i, r in real:
        width = r["s"] + r["o"] + r["u"]
        if r["o"] > 0:
            # production row of a partial selection: numbers, then what each part is
            nums = [fmt_num(r[k], lang, 1) for k in ("s", "o") + (("u",) if r["u"] > 0 else ())]
            labs = [t("shared", lang), t("others_short", lang)] + ([r["u_lab"]] if r["u"] > 0 else [])
            txt = " + ".join(nums) + " kWh<br>(" + " + ".join(labs) + ")"
        elif r["u"] > 0:
            txt = f"{fmt_num(r['s'], lang, 1)} + {fmt_num(r['u'], lang, 1)} ({r['u_lab']}) kWh"
        else:
            txt = f"{fmt_num(width, lang, 2)} kWh"
        if r["summary"]:
            txt = f"<b>{txt}</b>"
        # long bars: label inside the (grey) last segment, else after the bar
        inside = width > 0.55 * max_val
        annotations.append(dict(
            x=width - max_val * 0.01 if inside else width + max_val * 0.01, y=i,
            text=txt, showarrow=False, xanchor="right" if inside else "left",
            font=dict(size=11, color=th["ink"]),
            bgcolor=th["label_bg"] if inside else None, borderpad=2,
        ))
    fig.update_layout(
        annotations=annotations, barmode="overlay", showlegend=False, bargap=0.25,
        height=max(320, 90 + 38 * len(rows) + (14 if total_others > 0 else 0)),
        xaxis=dict(title=t("total_energy_xlabel", lang), range=[0, max_val * (1.3 if total_others > 0 else 1.35)],
                   showgrid=True, zeroline=False, tickformat=",.0f"),
        yaxis=dict(
            tickvals=y,
            ticktext=[("" if r is None else (f"<b>{r['label']}</b>" if r["summary"] else r["label"]))
                      for r in rows],
            range=[-0.6, len(rows) - 0.4], showgrid=False, ticklabelstandoff=8,
        ),
    )
    return fig


# ---------------------------------------------------------------------------
# Subplot 2: daily totals
# ---------------------------------------------------------------------------


def _month_ticks(index: pd.DatetimeIndex, lang: str) -> tuple[list, list]:
    start = index.min().to_period("M").to_timestamp()
    months = pd.date_range(start, index.max(), freq="MS")
    months = [m for m in months if m >= index.min()] or [index.min()]
    return list(months), [month_label(m, lang) for m in months]


def day_marker(day: str | None, th: dict | None = None) -> list[dict]:
    """Dashed vertical line on the daily plot at the selected day (script: axvline)."""
    if not day:
        return []
    colour = (th or THEMES["light"])["marker"]
    return [dict(type="line", xref="x", yref="paper", x0=day, x1=day, y0=0, y1=1,
                 line=dict(color=colour, width=1.5, dash="dash"), layer="above")]


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
    members, unshared, unmet. ``sel_day`` draws the dashed selected-day marker;
    click a day to select it."""
    th = th or THEMES["light"]
    fig = _figure(t("daily_title", lang), lang, 460, th)
    df, names, cmap = _folded(df, data, names, lang, top)
    daily = daily_totals(df)
    if daily.empty or len(daily.columns) == 0:
        return _no_data(fig, lang, th)

    for col in daily.columns:
        _area(fig, daily.index, daily[col].to_numpy(), col, cmap, th, names, lang)

    tickvals, ticktext = _month_ticks(daily.index, lang)
    fig.update_layout(
        xaxis=dict(tickvals=tickvals, ticktext=ticktext, tickangle=-30, showgrid=True,
                   hoverformat="%d.%m.%Y" if lang == "cs" else "%Y-%m-%d"),
        yaxis=dict(title=t("daily_ylabel", lang), showgrid=True, zeroline=False),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="left", x=0,
                    font=dict(size=11)),
        shapes=day_marker(sel_day, th),
        clickmode="event",
    )
    return fig


# ---------------------------------------------------------------------------
# Figure 2: pie of source disposition
# ---------------------------------------------------------------------------


def fig_wasted_pie(split: WastedSplit, lang: str = "cs", th: dict | None = None) -> go.Figure:
    """Where the production went. The slices always add up to the production:
    shared to the selected members, shared to the unselected ones, could have been
    shared (unshared while selected members bought from the grid), unshared."""
    th = th or THEMES["light"]
    fig = _figure(t("pie_title", lang), lang, 500, th)
    total = split.shared_total + split.shared_others + split.unshared_only + split.overlap
    if total <= 0:
        return _no_data(fig, lang, th)
    slices = [
        (t("pie_shared", lang), split.shared_total, th["source"]),
        (t("pie_others", lang), split.shared_others, th["others"]),
        (t("pie_wasted", lang), split.overlap, th["wasted"]),
        (t("pie_unshared_only", lang), split.unshared_only, th["unshared"]),
    ]
    slices = [s for s in slices if s[1] > 0]
    wasted, others = t("pie_wasted", lang), t("pie_others", lang)
    fig.add_pie(
        labels=[s[0] for s in slices],
        values=[s[1] for s in slices],
        marker=dict(colors=[s[2] for s in slices], line=dict(color=th["paper"], width=2),
                    pattern=dict(shape=["/" if s[0] == others else "" for s in slices],
                                 size=7, solidity=0.45, fgcolor=th["others"],
                                 bgcolor=_rgba(th["others"], 0.25))),
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
    fig.update_layout(
        annotations=[dict(text="<br>".join(note), x=0.5, y=0, yshift=-58, xref="paper",
                          yref="paper", yanchor="top", showarrow=False,
                          font=dict(size=11, color=th["muted"]))],
        margin=dict(l=40, r=40, t=60, b=100 + 14 * (len(note) - 2)),
    )
    return fig


# ---------------------------------------------------------------------------
# Subplot 4: one day; subplot 3: heatmap
# ---------------------------------------------------------------------------

INTRADAY_XSTART_HOUR = 6
INTRADAY_XEND_HOUR = 21


@memoized
def intraday_ymax(df: pd.DataFrame) -> float:
    """Peak kWh per 15 min of the stacked flows over the whole dataset (one scale
    for every day)."""
    agg = aggregate_grid_flows(df).fillna(0)
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
    df, names, cmap = _folded(df, data, names, lang, top)
    agg = aggregate_grid_flows(df)
    day_ts = pd.Timestamp(day).normalize() if day else agg.index.normalize().max()
    date_txt = day_ts.strftime("%d.%m.%Y" if lang == "cs" else "%Y-%m-%d")
    fig = _figure(t("sharing_on", lang).format(date=date_txt), lang, 440, th)
    if y_max is None:
        y_max = intraday_ymax(df)
    lo, hi = day_ts, day_ts + pd.Timedelta(days=1)
    day_df = agg.loc[(agg.index >= lo) & (agg.index < hi)].fillna(0)
    fig.update_layout(
        xaxis=dict(range=[day_ts + pd.Timedelta(hours=INTRADAY_XSTART_HOUR),
                          day_ts + pd.Timedelta(hours=INTRADAY_XEND_HOUR)],
                   dtick=3 * 3600 * 1000, tickformat="%H:%M", hoverformat="%H:%M",
                   showgrid=True),
        yaxis=dict(title=t("intraday_ylabel", lang), showgrid=True, zeroline=False,
                   range=[0, y_max * 1.02]),
    )
    if day_df.empty or len(agg.columns) == 0:
        fig.add_annotation(text=t("no_data", lang), x=0.5, y=0.5, xref="paper",
                           yref="paper", showarrow=False,
                           font=dict(size=14, color=th["muted"]))
        return fig
    for col in day_df.columns:
        _area(fig, day_df.index, day_df[col].to_numpy(), col, cmap, th, names, lang)
    fig.update_layout(
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0,
                    font=dict(size=11)),
    )
    return fig


# What the heatmap can show. A report with production and demand (all report): the
# total production or the total consumption of the selected destinations. The part
# report has neither, only the energy shared to the selected destinations.
def heat_metrics(data: SharingData) -> tuple[str, ...]:
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
        df = filter_dests(data, enabled)
        cols = shared_cols(df)
        if not cols:
            return pd.DataFrame()
        series = df[cols].sum(axis=1)
    total = series.to_frame("total")
    total["hour"] = total.index.hour
    total["month"] = total.index.to_period("M")
    return total.pivot_table(values="total", index="hour", columns="month", aggfunc="mean")


def fig_heatmap(pivot: pd.DataFrame, metric: str = "production", *,
                z_max: float | None = None, lang: str = "cs",
                th: dict | None = None) -> go.Figure:
    th = th or THEMES["light"]
    fig = _figure(t(f"heatmap_title_{metric}", lang), lang, 440, th)
    if pivot.empty:
        return _no_data(fig, lang, th)
    months = [month_label(p.to_timestamp(), lang) for p in pivot.columns]
    fig.add_heatmap(
        z=pivot.to_numpy(), x=months, y=list(pivot.index), colorscale=th["heat"],
        zmin=0, zmax=z_max if z_max else float(np.nanmax(pivot.to_numpy()) or 1.0),
        colorbar=dict(title=dict(text=t("heatmap_cbar", lang), side="right"),
                      thickness=12, tickformat=",.2f", outlinewidth=0),
        hovertemplate="%{x}, %{y}:00<br>%{z:,.3f} kWh<extra></extra>",
        xgap=1, ygap=1,
    )
    fig.update_layout(
        yaxis=dict(title=t("hour_of_day", lang), dtick=2, range=[-0.5, 23.5], showgrid=False),
        xaxis=dict(tickangle=-30, type="category", showgrid=False),
    )
    return fig
