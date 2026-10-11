"""Building blocks shared by every figure: themes, member colours and folding, the
common layout, and the five chart shapes the report uses (stacked horizontal bars, a
pie, stacked areas by day and within a day, an hour × month heatmap).

The energy figures (:mod:`figures.energy`, kWh) and the billing figures
(:mod:`figures.money`, Kč) differ only in what they put into these shapes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from edc_data import SharingData, key_dest, key_kind, key_source, memoized, shared_cols
from i18n import month_label, plotly_separators, t

TAB10 = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
         "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
FONT_FAMILY = "system-ui, -apple-system, Segoe UI, Roboto, sans-serif"

THEMES: dict[str, dict] = {
    "light": dict(
        paper="#ffffff", ink="#1f2328", muted="#57606a", grid="#ececec",
        unshared="#8c8c8c", unmet="#c7c7c7", total="rgba(0,0,0,0.9)", others="#a9b8cc",
        source="#339933", source_ink="#1d5c1d", wasted="#cc3326", members="#3b6fb6",
        marker="#000000", label_bg="rgba(255,255,255,0.85)", hover_bg="#ffffff",
        hover_border="#d0d7de", heat="YlOrRd", area_alpha=0.75,
    ),
    "dark": dict(
        paper="#161b22", ink="#e6edf3", muted="#9da7b3", grid="#2a313c",
        unshared="#7d8590", unmet="#3d444d", total="#e6edf3", others="#5d6b82",
        source="#3da63d", source_ink="#b9efb9", wasted="#e5534b", members="#5b8fd6",
        marker="#e6edf3", label_bg="rgba(22,27,34,0.85)", hover_bg="#1c2128",
        hover_border="#3d444d",
        # dark surface: low values stay near the surface, high values glow
        heat=[[0.0, "#1c2128"], [0.2, "#4a1d1a"], [0.45, "#a52a22"],
              [0.7, "#e8742a"], [1.0, "#ffe08a"]],
        area_alpha=0.85,
    ),
}

MAX_SERIES = 10            # tab10 has 10 hues; more destinations fold into "Others"
OTHER = "__other__"        # pseudo destination EAN of the folded rest
OTHER_COLOUR = TAB10[9]
INTRADAY_HOURS = (6, 21)   # x range of the plots of one day


def theme(name: str | None) -> dict:
    return THEMES.get(name or "light", THEMES["light"])


# ---------------------------------------------------------------------------
# Member colours; groups above 10 members fold into "Others"
# ---------------------------------------------------------------------------


def top_dests(df: pd.DataFrame, data: SharingData) -> tuple[str, ...] | None:
    """Destinations shown individually when there are more than MAX_SERIES.

    The 9 with the most shared energy in ``df`` (pass today's report, so the right
    column folds the same members and keeps the same colours); the rest is drawn as
    one "Others" series. ``None`` = no folding needed.
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


def member_groups(data: SharingData, enabled: set[str],
                  top: tuple[str, ...] | None) -> list[tuple[str, list[str]]]:
    """Ticked members as plotted: (key, members) with key = EAN, or OTHER for the
    folded rest of a large group."""
    sel = [e for e in data.dest_eans if e in enabled]
    if top is None:
        return [(e, [e]) for e in sel]
    groups = [(e, [e]) for e in top if e in enabled]
    rest = [e for e in sel if e not in top]
    return groups + ([(OTHER, rest)] if rest else [])


@memoized
def fold(df: pd.DataFrame, top: tuple[str, ...]) -> tuple[pd.DataFrame, int]:
    """Sum shared / unmet of the destinations outside ``top`` into OTHER columns;
    returns the frame and the number of folded destinations."""
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


def folded(df: pd.DataFrame, data: SharingData, names: dict[str, str], lang: str,
           top: tuple[str, ...] | None):
    """(frame, names, colours) for plotting, with the rest folded when needed."""
    if top is None:
        return df, names, colour_map(data)
    out, n_rest = fold(df, top)
    names = dict(names)
    names[OTHER] = t("others", lang).format(n=n_rest)
    return out, names, colour_map(data, top)


# ---------------------------------------------------------------------------
# Common layout
# ---------------------------------------------------------------------------


def rgba(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def hatch(th: dict) -> dict:
    """Diagonal stripes: marks "went to unselected members", which is neither one of
    the selected members' colours nor one of the greys of the grid flows."""
    return dict(shape="/", size=7, solidity=0.45, fgcolor=th["others"],
                bgcolor=rgba(th["others"], 0.25))


def producer_greens(th: dict, n: int) -> list[str]:
    """The producers' colours: the theme's green, then darker and lighter shades of it."""
    def mix(a: str, b: str, x: float) -> str:
        ca = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
        cb = [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
        return "#" + "".join(f"{round(p + (q - p) * x):02x}" for p, q in zip(ca, cb))
    steps = [0.0, -0.45, 0.45, -0.7, 0.65, -0.25, 0.25]
    return [mix(th["source"], "#000000" if x < 0 else "#ffffff", abs(x))
            for x in (steps[i % len(steps)] for i in range(n))]


def producer_hatch(th: dict, colour: str | None = None) -> dict:
    """The producer's green with a cross-hatch, so it never reads as the member that
    got tab10 green (the third one)."""
    return dict(shape="x", size=6, solidity=0.3, fgcolor=th["source_ink"],
                bgcolor=rgba(colour or th["source"], th["area_alpha"]))


def figure(title: str, lang: str, height: int, th: dict) -> go.Figure:
    """Empty figure with the common layout, set in one validated call."""
    return go.Figure(layout=dict(
        # fixed distance from the top of the card, so paired titles are level whatever
        # the plot below them does with its margins
        title=dict(text=title, x=0.01, xanchor="left", yref="container", y=1, yanchor="top",
                   pad=dict(t=16), font=dict(size=15)),
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


def no_data(fig: go.Figure, lang: str, th: dict, hide_axes: bool = True) -> go.Figure:
    fig.add_annotation(text=t("no_data", lang), x=0.5, y=0.5, xref="paper",
                       yref="paper", showarrow=False, font=dict(size=14, color=th["muted"]))
    if hide_axes:
        fig.update_layout(xaxis_visible=False, yaxis_visible=False)
    return fig


def _legend_below(y: float) -> dict:
    return dict(orientation="h", yanchor="top", y=y, xanchor="left", x=0, font=dict(size=11))


# ---------------------------------------------------------------------------
# Stacked horizontal bars (energy by flow, value of the shared electricity)
# ---------------------------------------------------------------------------


def hbars(fig: go.Figure, rows: list[dict | None], slots: list[dict], *, th: dict,
          unit: str, hover_decimals: int, xtitle: str, xpad: float, inside_above: float,
          extra_height: int = 0) -> go.Figure:
    """Rows of stacked bars, bottom to top; ``None`` leaves a gap.

    ``slots`` are the stacked segments (one bar trace each): ``name`` and an optional
    ``pattern``. A row is ``dict(label, summary, text, segs=[(value, colour, what)])``
    with one segment per slot; ``text`` is the label drawn next to (or, for long bars,
    inside) the bar.
    """
    real = [(i, r) for i, r in enumerate(rows) if r is not None]
    ys = [i for i, _ in real]
    width = [sum(max(v, 0) for v, _, _ in r["segs"]) for _, r in real]
    max_val = max(width, default=0.0) or 1.0
    base = [0.0] * len(real)
    hover = ("%{customdata[0]}<br>%{customdata[1]}: %{x:,." + str(hover_decimals) + "f} "
             + unit + "<extra></extra>")
    for k, slot in enumerate(slots):
        marker = dict(color=[r["segs"][k][1] for _, r in real],
                      line=dict(color=th["paper"], width=1))
        if slot.get("pattern"):
            marker["pattern"] = slot["pattern"]
        fig.add_bar(y=ys, x=[r["segs"][k][0] for _, r in real], orientation="h",
                    base=list(base) if k else None, marker=marker, name=slot["name"],
                    customdata=[[r["label"], r["segs"][k][2]] for _, r in real],
                    hovertemplate=hover)
        base = [b + max(r["segs"][k][0], 0) for b, (_, r) in zip(base, real)]
    annotations = []
    for (i, r), w in zip(real, width):
        inside = w > inside_above * max_val
        annotations.append(dict(
            x=w - max_val * 0.01 if inside else w + max_val * 0.01, y=i,
            text=f"<b>{r['text']}</b>" if r["summary"] else r["text"], showarrow=False,
            xanchor="right" if inside else "left", font=dict(size=11, color=th["ink"]),
            bgcolor=th["label_bg"] if inside else None, borderpad=2))
    fig.update_layout(
        annotations=annotations, barmode="overlay", showlegend=False, bargap=0.25,
        height=max(320, 90 + 38 * len(rows) + extra_height),
        xaxis=dict(title=xtitle, range=[0, max_val * xpad], showgrid=True, zeroline=False,
                   tickformat=",.0f"),
        yaxis=dict(tickvals=list(range(len(rows))),
                   ticktext=[("" if r is None else (f"<b>{r['label']}</b>" if r["summary"]
                                                    else r["label"])) for r in rows],
                   range=[-0.6, len(rows) - 0.4], showgrid=False, ticklabelstandoff=8),
    )
    return fig


def order_rows(rows: list[dict], order: list[str] | None, key=None) -> list[dict]:
    """Sort member rows bottom to top by ``order`` (the left chart's member order, see
    :func:`figures.energy.flow_order`), else by ``key``. Stable."""
    if order is None:
        return sorted(rows, key=key) if key else rows
    rank = {d: i for i, d in enumerate(order)}
    return sorted(rows, key=lambda r: rank.get(r["key"], len(rank)))


# ---------------------------------------------------------------------------
# Pie
# ---------------------------------------------------------------------------


def pie(fig: go.Figure, slices: list[tuple], note: list[str], *, th: dict, unit: str,
        hover_decimals: int) -> go.Figure:
    """Slices ``(label, value, colour, hatched, pulled)``, drawn clockwise with their
    labels outside; ``note`` lines go under the pie."""
    slices = [s for s in slices if s[1] > 0]
    fig.add_pie(
        labels=[s[0] for s in slices], values=[s[1] for s in slices],
        marker=dict(colors=[s[2] for s in slices], line=dict(color=th["paper"], width=2),
                    pattern=dict(shape=["/" if s[3] else "" for s in slices], size=7,
                                 solidity=0.45, fgcolor=th["others"],
                                 bgcolor=rgba(th["others"], 0.25))),
        pull=[0.06 if s[4] else 0 for s in slices],
        sort=False, direction="clockwise", rotation=0,
        texttemplate="%{label}<br>%{value:,.0f} " + unit + "<br>%{percent:.1%}",
        textposition="outside",
        hovertemplate=("%{label}: %{value:,." + str(hover_decimals) + "f} " + unit
                       + " (%{percent:.1%})<extra></extra>"),
        showlegend=False,
    )
    fig.update_layout(
        annotations=[dict(text="<br>".join(note), x=0.5, y=0, yshift=-58, xref="paper",
                          yref="paper", yanchor="top", showarrow=False,
                          font=dict(size=11, color=th["muted"]))],
        margin=dict(l=40, r=40, t=60, b=100 + 14 * (len(note) - 2)),
    )
    return fig


# ---------------------------------------------------------------------------
# Stacked areas: by day over the period, per 15 min within one day
# ---------------------------------------------------------------------------


def area(fig: go.Figure, x, y, name: str, colour: str, th: dict, unit: str,
         pattern: dict | None = None, line_width: float = 0.6) -> None:
    """One stacked area; ``pattern`` fills it with a hatch instead of the colour."""
    fill = (dict(fillpattern=pattern) if pattern
            else dict(fillcolor=rgba(colour, th["area_alpha"])))
    fig.add_scatter(x=x, y=y, mode="lines", stackgroup="one", name=name,
                    hovertemplate="%{y:,.2f} " + unit,
                    line=dict(color=colour, width=line_width), **fill)


def month_ticks(index: pd.DatetimeIndex, lang: str) -> tuple[list, list]:
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


def daily_layout(fig: go.Figure, index: pd.DatetimeIndex, ylabel: str, sel_day: str | None,
                 lang: str, th: dict) -> go.Figure:
    """Month ticks, unified hover, legend below, the selected-day marker; a click
    selects a day."""
    tickvals, ticktext = month_ticks(index, lang)
    fig.update_layout(
        xaxis=dict(tickvals=tickvals, ticktext=ticktext, tickangle=-30, showgrid=True,
                   hoverformat="%d.%m.%Y" if lang == "cs" else "%Y-%m-%d"),
        yaxis=dict(title=ylabel, showgrid=True, zeroline=False),
        hovermode="x unified", legend=_legend_below(-0.18),
        shapes=day_marker(sel_day, th), clickmode="event",
    )
    return fig


def day_slice(frame: pd.DataFrame, day: str | None) -> tuple[pd.Timestamp, pd.DataFrame]:
    """The calendar day (default: the last one) and the rows of ``frame`` in it."""
    day_ts = pd.Timestamp(day).normalize() if day else frame.index.normalize().max()
    rows = frame.loc[(frame.index >= day_ts) & (frame.index < day_ts + pd.Timedelta(days=1))]
    return day_ts, rows


def date_text(ts: pd.Timestamp, lang: str) -> str:
    return ts.strftime("%d.%m.%Y" if lang == "cs" else "%Y-%m-%d")


def intraday_layout(fig: go.Figure, day_ts: pd.Timestamp, ylabel: str, y_max: float) -> None:
    """06:00-21:00 of ``day_ts`` and a fixed y range (so both columns compare)."""
    lo, hi = INTRADAY_HOURS
    fig.update_layout(
        xaxis=dict(range=[day_ts + pd.Timedelta(hours=lo), day_ts + pd.Timedelta(hours=hi)],
                   dtick=3 * 3600 * 1000, tickformat="%H:%M", hoverformat="%H:%M",
                   showgrid=True),
        yaxis=dict(title=ylabel, showgrid=True, zeroline=False, range=[0, y_max * 1.05]),
    )


def intraday_legend(fig: go.Figure) -> None:
    fig.update_layout(hovermode="x unified", legend=_legend_below(-0.12))


# ---------------------------------------------------------------------------
# Hour of day × month
# ---------------------------------------------------------------------------


def hour_month_pivot(series: pd.Series) -> pd.DataFrame:
    """Mean per 15-min interval, hour of day × month."""
    total = series.to_frame("total")
    total["hour"] = total.index.hour
    total["month"] = total.index.to_period("M")
    return total.pivot_table(values="total", index="hour", columns="month", aggfunc="mean")


def heatmap(fig: go.Figure, pivot: pd.DataFrame, *, cbar: str, unit: str,
            z_max: float | None, lang: str, th: dict) -> go.Figure:
    if pivot.empty:
        return no_data(fig, lang, th)
    months = [month_label(p.to_timestamp(), lang) for p in pivot.columns]
    fig.add_heatmap(
        z=pivot.to_numpy(), x=months, y=list(pivot.index), colorscale=th["heat"],
        zmin=0, zmax=z_max if z_max else float(np.nanmax(pivot.to_numpy()) or 1.0),
        colorbar=dict(title=dict(text=cbar, side="right"),
                      thickness=12, tickformat=",.2f", outlinewidth=0),
        hovertemplate="%{x}, %{y}:00<br>%{z:,.3f} " + unit + "<extra></extra>",
        xgap=1, ygap=1,
    )
    fig.update_layout(
        yaxis=dict(title=t("hour_of_day", lang), dtick=2, range=[-0.5, 23.5], showgrid=False),
        xaxis=dict(tickangle=-30, type="category", showgrid=False),
    )
    return fig


# ---------------------------------------------------------------------------
# Paired figures (left: EDC report, right: exact method or billing)
# ---------------------------------------------------------------------------


def legend_entries(fig: go.Figure) -> int:
    return sum(1 for tr in fig.data if tr.showlegend is not False and tr.name)


def pair_figures(fa, fb) -> None:
    """Make two paired figures line up row by row: the same height and bottom margin,
    and, for the horizontal legends below the plot, the same number of legend rows (two
    entries per row; the shorter legend gets blank entries), so the plot areas are the
    same size and the x axes sit at the same height."""
    if not fb or not getattr(fb, "data", None) or not fa or not fa.data:
        return
    height = max(fa.layout.height or 0, fb.layout.height or 0)
    bottom = max(fa.layout.margin.b or 0, fb.layout.margin.b or 0)
    for f in (fa, fb):
        f.update_layout(height=height, margin_b=bottom)
    if fa.layout.legend.orientation != "h" or fb.layout.legend.orientation != "h":
        return
    n = max(legend_entries(fa), legend_entries(fb))
    n += n % 2
    for f in (fa, fb):
        k = n - legend_entries(f)
        # a blank entry needs a real x value: it comes first in the data, and plotly
        # guesses the axis type (date) from the first trace
        x0 = next((list(tr.x[:1]) for tr in f.data if tr.x is not None and len(tr.x)), [None])
        for _ in range(k):
            f.add_scatter(x=x0, y=[None], mode="lines", name=" ", hoverinfo="skip",
                          line=dict(width=0, color="rgba(0,0,0,0)"), showlegend=True)
        if k:   # stacked areas list the legend bottom-up: put the blanks first in data,
            f.data = f.data[-k:] + f.data[:-k]          # so they come last on screen
        f.update_layout(legend=dict(entrywidth=0.5, entrywidthmode="fraction",
                                    traceorder="reversed"))


def share_xrange(fa: go.Figure, fb: go.Figure) -> None:
    """One x range for two bar charts of the same unit."""
    hi = max(fa.layout.xaxis.range[1], fb.layout.xaxis.range[1])
    for f in (fa, fb):
        f.update_xaxes(range=[0, hi])


def share_stack_ymax(fa: go.Figure, fb: go.Figure) -> None:
    """One y range for two stacked-area charts of the same unit."""
    if not fa.data or not fb.data:
        return
    peak = max(np.sum([np.asarray(tr.y, dtype=float) for tr in f.data], axis=0).max()
               for f in (fa, fb))
    for f in (fa, fb):
        f.update_yaxes(range=[0, peak * 1.05])
