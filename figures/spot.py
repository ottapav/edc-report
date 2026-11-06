"""The spot-market figures (Kč): what the surplus is worth with sharing and on spot.

* from spot to sharing, step by step             (:func:`fig_spot_waterfall`)
* with sharing vs on spot, per member            (:func:`fig_spot_members`)
* gain of sharing per day                        (:func:`fig_spot_daily`)
* spot price and the surplus on one day          (:func:`fig_spot_intraday`)
* prices per month                               (:func:`fig_spot_monthly`)

The numbers come from :class:`spot.Comparison`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from edc_data import POOL, SharingData
from i18n import fmt_num, fmt_signed, month_label, t
from spot import Comparison, monthly

from .base import (
    OTHER, OTHER_COLOUR, THEMES, colour_map, daily_layout, date_text, figure, member_groups,
    no_data, rgba,
)


def _cur(lang: str) -> str:
    return t("currency", lang)


def _kc(x: float, lang: str, signed: bool = False) -> str:
    if signed:
        return f"{fmt_signed(x, lang, 0)} {_cur(lang)}"
    return f"{fmt_num(x, lang)} {_cur(lang)}"


def _gain_colour(x: float, th: dict) -> str:
    return th["source"] if x >= 0 else th["wasted"]


def _need_prices(fig: go.Figure, lang: str, th: dict) -> go.Figure:
    """No comparison without the supplier and feed-in prices: say so in the plot."""
    fig.add_annotation(text=t("spot_need_prices_short", lang), x=0.5, y=0.5, xref="paper",
                       yref="paper", showarrow=False, font=dict(size=13, color=th["muted"]))
    fig.update_layout(xaxis_visible=False, yaxis_visible=False)
    return fig


# ---------------------------------------------------------------------------
# From spot to sharing
# ---------------------------------------------------------------------------


def fig_spot_waterfall(cmp: Comparison, lang: str = "cs", th: dict | None = None) -> go.Figure:
    """The surplus on spot, what the shared energy and the unshared surplus add (or
    lose) with sharing, and the value with sharing."""
    th = th or THEMES["light"]
    fig = figure(t("spot_wf_title", lang), lang, 440, th)
    if not cmp.valid.any():
        return no_data(fig, lang, th)
    R = cmp.spot_revenue
    steps = [(t("spot_wf_spot", lang), 0.0, R, th["unshared"], _kc(R, lang))]
    if cmp.priced:
        gs, gu = cmp.gain_shared, cmp.gain_unshared
        steps += [
            (t("spot_wf_shared", lang), R, gs, _gain_colour(gs, th), _kc(gs, lang, True)),
            (t("spot_wf_unshared", lang), R + gs, gu, _gain_colour(gu, th), _kc(gu, lang, True)),
            (t("spot_wf_sharing", lang), 0.0, cmp.sharing_value, th["total"],
             _kc(cmp.sharing_value, lang)),
        ]
    x = [s[0] for s in steps]
    fig.add_bar(x=x, y=[s[2] for s in steps], base=[s[1] for s in steps],
                marker=dict(color=[s[3] for s in steps], line=dict(color=th["paper"], width=1)),
                text=[s[4] for s in steps], textposition="outside", cliponaxis=False,
                textfont=dict(size=12, color=th["ink"]),
                customdata=[s[4] for s in steps], hovertemplate="%{x}: %{customdata}<extra></extra>",
                showlegend=False)
    # dotted connectors from the top of one step to the next
    tops = [s[1] + s[2] for s in steps]
    shapes = [dict(type="line", xref="x", yref="y", x0=i + 0.4, x1=i + 0.6, y0=tops[i],
                   y1=tops[i], line=dict(color=th["muted"], width=1, dash="dot"))
              for i in range(len(steps) - 1)]
    lo = min(0.0, *[min(s[1], s[1] + s[2]) for s in steps])
    hi = max(0.0, *[max(s[1], s[1] + s[2]) for s in steps])
    pad = 0.12 * (hi - lo or 1.0)
    fig.update_layout(
        shapes=shapes, bargap=0.35,
        xaxis=dict(type="category", showgrid=False, tickangle=0, tickfont=dict(size=11)),
        yaxis=dict(title=t("spot_kc", lang), range=[lo - (pad if lo < 0 else 0), hi + pad],
                   tickformat=",.0f", zeroline=True, zerolinecolor=th["grid"]),
    )
    if not cmp.priced:
        fig.add_annotation(text=t("spot_need_prices_short", lang), x=0.98, y=0.5, xref="paper",
                           yref="paper", xanchor="right", showarrow=False,
                           font=dict(size=12, color=th["muted"]))
    return fig


# ---------------------------------------------------------------------------
# Per member
# ---------------------------------------------------------------------------


def fig_spot_members(cmp: Comparison, data: SharingData, names: dict[str, str],
                     enabled: set[str], *, lang: str = "cs", th: dict | None = None,
                     top: tuple[str, ...] | None = None) -> go.Figure:
    """Per ticked member: its shared energy at its supplier price and on spot; the
    producers' unshared surplus at the feed-in price and on spot. The label is the gain."""
    th = th or THEMES["light"]
    fig = figure(t("spot_members_title", lang), lang, 420, th)
    if not cmp.valid.any():
        return no_data(fig, lang, th)
    idx = {e: j for j, e in enumerate(data.dest_eans)}
    cmap = colour_map(data, top)
    rows = []          # label, with sharing, on spot, colour
    for key, group in member_groups(data, enabled, top):
        j = [idx[e] for e in group]
        label = (t("others", lang).format(n=len(group)) if key == OTHER else names.get(key, key))
        rows.append((label, float(cmp.at_supplier[j].sum()), float(cmp.shared_at_spot[j].sum()),
                     cmap.get(key, OTHER_COLOUR)))
    src = data.source_eans[0] if len(data.source_eans) == 1 else POOL
    rows.append((t("spot_row_unshared", lang).format(name=names[src]),
                 float(cmp.at_feed_in.sum()), float(cmp.unshared_at_spot.sum()), th["source"]))
    rows = rows[::-1]                               # first member on top
    y = [r[0] for r in rows]
    cur = _cur(lang)
    hover = "%{y}<br>%{fullData.name}: %{x:,.0f} " + cur + "<extra></extra>"
    fig.add_bar(y=y, x=[r[2] for r in rows], orientation="h", name=t("spot_on_spot", lang),
                marker=dict(color=th["unshared"]), hovertemplate=hover)
    fig.add_bar(y=y, x=[r[1] for r in rows], orientation="h", name=t("spot_with_sharing", lang),
                marker=dict(color=[r[3] for r in rows]), hovertemplate=hover)
    xs = [v for r in rows for v in r[1:3] if np.isfinite(v)]
    hi, lo = max([0.0, *xs]), min([0.0, *xs])
    notes = []
    for r in rows:
        if not (np.isfinite(r[1]) and np.isfinite(r[2])):
            continue
        g = r[1] - r[2]
        notes.append(dict(x=max(r[1], r[2], 0.0) + 0.01 * (hi - lo or 1.0), y=r[0],
                          text=f"<b>{_kc(g, lang, True)}</b>", showarrow=False, xanchor="left",
                          font=dict(size=11, color=_gain_colour(g, th))))
    fig.update_layout(
        barmode="group", bargap=0.3, bargroupgap=0.05, annotations=notes,
        height=max(320, 110 + 44 * len(rows)),
        xaxis=dict(title=t("spot_kc", lang), range=[lo * 1.05, hi * 1.3 if hi else 1.0],
                   tickformat=",.0f", showgrid=True, zeroline=True, zerolinecolor=th["grid"]),
        yaxis=dict(showgrid=False, ticklabelstandoff=8, type="category"),
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0,
                    traceorder="reversed", font=dict(size=11)),
    )
    return fig


# ---------------------------------------------------------------------------
# By day
# ---------------------------------------------------------------------------


def fig_spot_daily(cmp: Comparison, *, lang: str = "cs", sel_day: str | None = None,
                   th: dict | None = None) -> go.Figure:
    """The gain of sharing over spot per day: on the shared energy, on the unshared
    surplus (often negative: the feed-in price below spot), and the net. Click a day to
    select it."""
    th = th or THEMES["light"]
    fig = figure(t("spot_daily_title", lang), lang, 440, th)
    pi = cmp.per_interval
    if pi.empty or not cmp.valid.any():
        return no_data(fig, lang, th)
    if not cmp.priced:
        return _need_prices(fig, lang, th)
    daily = pi[["gain_shared", "gain_unshared"]].resample("D").sum()
    cur = _cur(lang)
    hover = "%{y:,.0f} " + cur
    fig.add_bar(x=daily.index, y=daily["gain_shared"], name=t("spot_daily_shared", lang),
                marker=dict(color=th["source"], line=dict(width=0)), hovertemplate=hover)
    fig.add_bar(x=daily.index, y=daily["gain_unshared"], name=t("spot_daily_unshared", lang),
                marker=dict(color=th["unshared"], line=dict(width=0)), hovertemplate=hover)
    fig.add_scatter(x=daily.index, y=daily.sum(axis=1), name=t("spot_daily_net", lang),
                    mode="lines", line=dict(color=th["total"], width=1.2), hovertemplate=hover)
    daily_layout(fig, daily.index, t("spot_daily_ylabel", lang), sel_day, lang, th)
    fig.update_layout(barmode="relative", bargap=0.05)
    fig.update_yaxes(zeroline=True, zerolinecolor=th["muted"], tickformat=",.0f")
    return fig


# ---------------------------------------------------------------------------
# One day
# ---------------------------------------------------------------------------


def _line(fig, x, y, name, colour, dash, row, unit, shape="linear", width=1.5):
    fig.add_scatter(x=x, y=y, name=name, mode="lines", line=dict(color=colour, width=width,
                    dash=dash, shape=shape), hovertemplate="%{y:,.2f} " + unit, row=row, col=1)


def fig_spot_intraday(cmp: Comparison, day: str | None, *, lang: str = "cs",
                      th: dict | None = None) -> go.Figure:
    """The selected day: the spot price against the supplier and feed-in prices (top),
    the surplus shared and unshared (bottom), per 15 min."""
    th = th or THEMES["light"]
    pi = cmp.per_interval
    day_ts = pd.Timestamp(day).normalize() if day else pi.index.normalize().max()
    rows = pi.loc[(pi.index >= day_ts) & (pi.index < day_ts + pd.Timedelta(days=1))]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.5, 0.5],
                        vertical_spacing=0.07)
    base = figure(t("spot_on", lang).format(date=date_text(day_ts, lang)), lang, 520, th)
    fig.update_layout(base.layout)
    if rows.empty:
        return no_data(fig, lang, th, hide_axes=False)
    x = rows.index
    pu = f"{_cur(lang)}/kWh"
    _line(fig, x, rows["spot"], t("spot_price", lang), th["ink"], "solid", 1, pu, shape="hv",
          width=2)
    if cmp.fee:
        _line(fig, x, rows["spot"] - cmp.fee, t("spot_price_net", lang), th["muted"], "dot", 1,
              pu, shape="hv")
    ends = [day_ts, day_ts + pd.Timedelta(days=1)]
    if np.isfinite(cmp.supplier_avg):
        _line(fig, ends, [cmp.supplier_avg] * 2, t("spot_supplier_avg", lang), th["members"],
              "dash", 1, pu)
    feed = (cmp.feed_in_avg if np.isfinite(cmp.feed_in_avg)
            else float(np.mean(cmp.feed_ins)) if not np.isnan(cmp.feed_ins).any() else None)
    if feed is not None:
        _line(fig, ends, [feed] * 2, t("spot_feed_in_avg", lang), th["source"], "dash", 1, pu)
    for col, name, colour in (("shared", t("spot_shared_kwh", lang), th["source"]),
                              ("unshared", t("spot_unshared_kwh", lang), th["unshared"])):
        fig.add_scatter(x=x, y=rows[col], name=name, mode="lines", stackgroup="energy",
                        line=dict(color=colour, width=0.6),
                        fillcolor=rgba(colour, th["area_alpha"]),
                        hovertemplate="%{y:,.2f} kWh", row=2, col=1)
    axis = dict(gridcolor=th["grid"], linecolor=th["grid"], zerolinecolor=th["grid"])
    fig.update_xaxes(range=ends, dtick=3 * 3600 * 1000, tickformat="%H:%M",
                     hoverformat="%H:%M", showgrid=True, **axis)
    fig.update_yaxes(showgrid=True, **axis)
    levels = [v for v in (*rows["spot"].dropna(), cmp.supplier_avg, feed or np.nan)
              if np.isfinite(v)]
    lo, hi = min([0.0, *levels]), max([0.0, *levels])
    pad = 0.08 * (hi - lo or 1.0)
    fig.update_yaxes(title=t("spot_price_axis", lang), zeroline=True, range=[lo - pad, hi + pad],
                     zerolinecolor=th["muted"], row=1, col=1)
    fig.update_yaxes(title=t("intraday_ylabel", lang), rangemode="tozero", row=2, col=1)
    fig.update_layout(hovermode="x unified",
                      legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="left", x=0,
                                  traceorder="normal", font=dict(size=11)))
    return fig


# ---------------------------------------------------------------------------
# By month
# ---------------------------------------------------------------------------


def fig_spot_monthly(cmp: Comparison, *, lang: str = "cs", th: dict | None = None) -> go.Figure:
    """Per month: the average spot price, what the surplus got on spot (energy weighted,
    after the fee), the supplier price of the shared energy, the feed-in price."""
    th = th or THEMES["light"]
    fig = figure(t("spot_monthly_title", lang), lang, 440, th)
    if not cmp.valid.any():
        return no_data(fig, lang, th)
    m = monthly(cmp)
    x = [month_label(p.to_timestamp(), lang) for p in m.index]
    pu = f"{_cur(lang)}/kWh"
    hover = "%{y:,.2f} " + pu
    fig.add_bar(x=x, y=m["mean_spot"], name=t("spot_mean", lang),
                marker=dict(color=rgba(th["unshared"], 0.55)), hovertemplate=hover)
    fig.add_bar(x=x, y=m["capture"], name=t("spot_capture", lang),
                marker=dict(color=th["unshared"]), hovertemplate=hover)
    if m["supplier"].notna().any():
        fig.add_scatter(x=x, y=m["supplier"], name=t("spot_supplier_avg", lang),
                        mode="lines+markers", line=dict(color=th["members"], width=2),
                        hovertemplate=hover)
    if m["feed_in"].notna().any():
        fig.add_scatter(x=x, y=m["feed_in"], name=t("spot_feed_in_avg", lang),
                        mode="lines+markers", line=dict(color=th["source"], width=2, dash="dash"),
                        hovertemplate=hover)
    fig.update_layout(
        barmode="group", bargap=0.25, hovermode="x unified",
        xaxis=dict(type="category", tickangle=-30, showgrid=False),
        yaxis=dict(title=t("spot_price_axis", lang), showgrid=True, zeroline=True,
                   zerolinecolor=th["muted"], tickformat=",.1f"),
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="left", x=0,
                    font=dict(size=11)),
    )
    return fig
