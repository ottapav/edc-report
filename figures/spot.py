"""The spot-market figures (Kč): what the surplus is worth with sharing and on spot.

* value by the share of the production sold on spot (:func:`fig_spot_mix`)
* who gets what: producers and members           (:func:`fig_spot_parties`)
* with sharing vs on spot, per participant       (:func:`fig_spot_members`)
* what sharing brings per day                    (:func:`fig_spot_daily`)
* spot price and the surplus on one day          (:func:`fig_spot_intraday`)
* prices per month                               (:func:`fig_spot_monthly`)

The numbers come from :class:`spot.Comparison`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from edc_data import SharingData
from i18n import fmt_num, fmt_signed, month_label, t
from spot import Comparison, Mix, Split, monthly

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


def _need_prices(fig: go.Figure, lang: str, th: dict, text: str | None = None) -> go.Figure:
    """No comparison (without the supplier and feed-in prices, or the keys): say why in
    the plot."""
    fig.add_annotation(text=text or t("spot_need_prices_short", lang), x=0.5, y=0.5,
                       xref="paper", yref="paper", showarrow=False,
                       font=dict(size=13, color=th["muted"]))
    fig.update_layout(xaxis_visible=False, yaxis_visible=False)
    return fig


# ---------------------------------------------------------------------------
# Part on spot, the rest shared
# ---------------------------------------------------------------------------


def fig_spot_mix(m: Mix | None, lang: str = "cs", th: dict | None = None,
                 note: str | None = None) -> go.Figure:
    """The group's value by the share of the production offered for sharing (0 % = all
    on spot, 100 % = the report's sharing), the rest always on spot: stacked the shared
    electricity at the supplier prices and the spot sales, the total, the best share
    marked."""
    th = th or THEMES["light"]
    fig = figure(t("spot_mix_title", lang), lang, 440, th)
    if m is None or not np.isfinite(m.total).all():
        return _need_prices(fig, lang, th, note)
    x = 100 * m.levels
    cur = _cur(lang)
    hover = "%{y:,.0f} " + cur
    for y, name, colour in ((m.spot, t("spot_mix_spot", lang), th["unshared"]),
                            (m.members, t("spot_mix_members", lang), th["members"])):
        fig.add_scatter(x=x, y=y, name=name, mode="lines", stackgroup="mix",
                        line=dict(color=colour, width=0.6),
                        fillcolor=rgba(colour, th["area_alpha"]), hovertemplate=hover)
    tot = m.total
    fig.add_scatter(x=x, y=tot, name=t("spot_mix_total", lang), mode="lines+markers",
                    line=dict(color=th["total"], width=2), marker=dict(size=6),
                    hovertemplate=hover)
    b = m.best
    fig.add_annotation(x=x[b], y=tot[b], text=f"<b>{t('spot_mix_best', lang)}</b><br>"
                       f"{_kc(tot[b], lang)}", showarrow=True, arrowhead=0, ax=60 if b < 6 else -60,
                       ay=-34, xanchor="left" if b < 6 else "right", align="left",
                       font=dict(size=11, color=th["ink"]), bgcolor=th["label_bg"])
    fig.update_layout(
        hovermode="x unified",
        xaxis=dict(title=t("spot_mix_x", lang), range=[0, 100], dtick=10, ticksuffix=" %",
                   showgrid=True, hoverformat=".0f"),
        yaxis=dict(title=t("spot_kc", lang), tickformat=",.0f", showgrid=True,
                   rangemode="tozero"),
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="left", x=0,
                    traceorder="normal", font=dict(size=11)),
    )
    return fig


# ---------------------------------------------------------------------------
# Who gets what
# ---------------------------------------------------------------------------


def fig_spot_parties(cmp: Comparison, sp: Split | None, lang: str = "cs",
                     th: dict | None = None, note: str | None = None) -> go.Figure:
    """Sharing with the unshared rest on spot (producers paid by the billing by
    contribution for the shared electricity) and all on spot: stacked what the producers
    get and what the members save. Without the billing only the group's totals, with
    ``note`` saying why."""
    th = th or THEMES["light"]
    fig = figure(t("spot_parties_title", lang), lang, 440, th)
    if not cmp.valid.any():
        return no_data(fig, lang, th)
    if not cmp.priced:
        return _need_prices(fig, lang, th)
    x = [t("spot_parties_sharing", lang), t("spot_parties_spot", lang)]
    cur = _cur(lang)
    hover = "%{x}<br>%{fullData.name}: %{y:,.0f} " + cur + "<extra></extra>"
    if sp is None:
        y = [cmp.sharing_value, cmp.spot_revenue]
        fig.add_bar(x=x, y=y, name=t("spot_parties_group", lang), marker=dict(color=th["total"]),
                    text=[_kc(v, lang) for v in y], textposition="outside", cliponaxis=False,
                    hovertemplate=hover)
        if note:
            fig.add_annotation(text=note, x=0.5, y=1.0, xref="paper", yref="paper",
                               yanchor="bottom", showarrow=False,
                               font=dict(size=11, color=th["muted"]))
    else:
        prod = [sp.producers_sharing, sp.producers_spot]
        mem = [sp.members_saving, 0.0]
        fig.add_bar(x=x, y=prod, name=t("spot_parties_producers", lang),
                    marker=dict(color=th["source"]), text=[_kc(v, lang) for v in prod],
                    textposition="inside", insidetextanchor="middle", hovertemplate=hover)
        fig.add_bar(x=x, y=mem, name=t("spot_parties_members", lang),
                    marker=dict(color=th["members"]),
                    text=[_kc(v, lang) if v else "" for v in mem], textposition="inside",
                    insidetextanchor="middle", hovertemplate=hover)
        tops = [a + b for a, b in zip(prod, mem)]
        for xi, top in zip(x, tops):
            fig.add_annotation(x=xi, y=top, text=f"<b>{_kc(top, lang)}</b>", showarrow=False,
                               yanchor="bottom", font=dict(size=12, color=th["ink"]))
    fig.update_layout(
        barmode="stack", bargap=0.4,
        xaxis=dict(type="category", showgrid=False, tickangle=0, tickfont=dict(size=11)),
        yaxis=dict(title=t("spot_kc", lang), tickformat=",.0f", rangemode="tozero"),
        legend=dict(orientation="h", yanchor="top", y=-0.16, xanchor="left", x=0,
                    traceorder="normal", font=dict(size=11)),
    )
    return fig


def fig_spot_members(cmp: Comparison, sp: Split | None, data: SharingData,
                     names: dict[str, str], enabled: set[str], *, lang: str = "cs",
                     th: dict | None = None, top: tuple[str, ...] | None = None,
                     note: str | None = None) -> go.Figure:
    """Per producer: what it gets with sharing and on spot; per ticked member: what it
    saves with sharing (on spot nothing). The label is the difference."""
    th = th or THEMES["light"]
    fig = figure(t("spot_members_title", lang), lang, 420, th)
    if not cmp.valid.any():
        return no_data(fig, lang, th)
    if sp is None:
        return _need_prices(fig, lang, th, note)
    idx = {e: j for j, e in enumerate(data.dest_eans)}
    cmap = colour_map(data, top)
    rows = [(names.get(src, src), float(sp.producer_sharing[i]), float(sp.producer_spot[i]),
             th["source"]) for i, src in enumerate(data.source_eans)]
    for key, group in member_groups(data, enabled, top):
        j = [idx[e] for e in group]
        label = (t("others", lang).format(n=len(group)) if key == OTHER else names.get(key, key))
        rows.append((label, float(sp.member_saving[j].sum()), 0.0, cmap.get(key, OTHER_COLOUR)))
    # producers on top (reversed axis): the first bar of the coloured trace is then the
    # producer's, and its colour is the one the legend shows
    y = [r[0] for r in rows]
    cur = _cur(lang)
    hover = "%{y}<br>%{fullData.name}: %{x:,.0f} " + cur + "<extra></extra>"
    fig.add_bar(y=y, x=[r[1] for r in rows], orientation="h", name=t("spot_with_sharing", lang),
                marker=dict(color=[r[3] for r in rows]), hovertemplate=hover)
    fig.add_bar(y=y, x=[r[2] for r in rows], orientation="h", name=t("spot_on_spot", lang),
                marker=dict(color=th["unshared"]), hovertemplate=hover)
    xs = [v for r in rows for v in r[1:3]]
    hi, lo = max([0.0, *xs]), min([0.0, *xs])
    notes = [dict(x=max(r[1], r[2], 0.0) + 0.01 * (hi - lo or 1.0), y=r[0],
                  text=f"<b>{_kc(r[1] - r[2], lang, True)}</b>", showarrow=False,
                  xanchor="left", font=dict(size=11, color=_gain_colour(r[1] - r[2], th)))
             for r in rows]
    fig.update_layout(
        barmode="group", bargap=0.3, bargroupgap=0.05, annotations=notes,
        height=max(320, 110 + 44 * len(rows)),
        xaxis=dict(title=t("spot_kc", lang), range=[lo * 1.05, hi * 1.3 if hi else 1.0],
                   tickformat=",.0f", showgrid=True, zeroline=True, zerolinecolor=th["grid"]),
        yaxis=dict(showgrid=False, ticklabelstandoff=8, type="category", autorange="reversed"),
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0,
                    traceorder="normal", font=dict(size=11)),
    )
    return fig


# ---------------------------------------------------------------------------
# By day
# ---------------------------------------------------------------------------


def fig_spot_daily(cmp: Comparison, sp: Split | None = None, *, lang: str = "cs",
                   sel_day: str | None = None, th: dict | None = None) -> go.Figure:
    """Per day: with the billing, what sharing brings the producers over spot and what
    the members save, the line their sum; without it, the group's gain (the shared
    electricity at the supplier prices against spot; the rest is on spot either way).
    Click a day to select it."""
    th = th or THEMES["light"]
    fig = figure(t("spot_daily_title", lang), lang, 440, th)
    pi = cmp.per_interval
    if pi.empty or not cmp.valid.any():
        return no_data(fig, lang, th)
    if not cmp.priced:
        return _need_prices(fig, lang, th)
    if sp is not None:
        daily = sp.daily[["producers", "members"]]
        parts = (("producers", t("spot_daily_producers", lang), th["source"]),
                 ("members", t("spot_daily_members", lang), th["members"]))
    else:
        daily = pi[["gain_shared"]].resample("D").sum()
        parts = (("gain_shared", t("spot_daily_shared", lang), th["source"]),)
    cur = _cur(lang)
    hover = "%{y:,.0f} " + cur
    for col, name, colour in parts:
        fig.add_bar(x=daily.index, y=daily[col], name=name,
                    marker=dict(color=colour, line=dict(width=0)), hovertemplate=hover)
    if len(parts) > 1:
        fig.add_scatter(x=daily.index, y=daily.sum(axis=1), name=t("spot_daily_net", lang),
                        mode="lines", line=dict(color=th["total"], width=1.2),
                        hovertemplate=hover)
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
    """The selected day: the spot price against the supplier price of the shared energy
    (top), the surplus shared and unshared (bottom), per 15 min."""
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
    levels = [v for v in (*rows["spot"].dropna(), cmp.supplier_avg) if np.isfinite(v)]
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
    """Per month: the average spot price, what the shared electricity would have got on
    spot (energy weighted, after the fee: what sharing must beat), the supplier price of
    the shared energy."""
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
    fig.update_layout(
        barmode="group", bargap=0.25, hovermode="x unified",
        xaxis=dict(type="category", tickangle=-30, showgrid=False),
        yaxis=dict(title=t("spot_price_axis", lang), showgrid=True, zeroline=True,
                   zerolinecolor=th["muted"], tickformat=",.1f"),
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="left", x=0,
                    font=dict(size=11)),
    )
    return fig
