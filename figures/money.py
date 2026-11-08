"""The billing figures (Kč) of the billing tab.

* where the benefit went                      (:func:`fig_bill_pie`)
* the producers' share by month              (:func:`fig_bill_monthly`)
* daily share of the benefit                  (:func:`fig_bill_daily`)
* the benefit on one day, per 15 min          (:func:`fig_bill_intraday`)

The per-interval values come from :attr:`billing.BillResult.per_interval`, the
settlement from :class:`billing.Billing`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from billing import PRODUCER, Billing, is_producer_col
from edc_data import POOL, SharingData
from i18n import fmt_num, month_label, t, tn

from .base import (
    OTHER, OTHER_COLOUR, THEMES, area, colour_map, daily_layout, date_text, day_slice,
    figure, hatch, intraday_layout, intraday_legend, member_groups, no_data, pie,
    producer_greens, producer_hatch,
)

UNSELECTED = "__unselected__"  # shares of the unticked members, summed


def bill_columns(frame: pd.DataFrame, data: SharingData, enabled: set[str],
                 top: tuple[str, ...] | None) -> tuple[pd.DataFrame, int]:
    """Per-interval Kč for plotting: ticked members (the rest of a large group folded
    into OTHER), the unticked members summed (UNSELECTED), the producers; and the number
    of folded members."""
    out, n_rest = {}, 0
    for key, members in member_groups(data, enabled, top):
        out[key] = frame[members[0]] if key != OTHER else frame[members].sum(axis=1)
        n_rest = len(members) if key == OTHER else n_rest
    unsel = [e for e in data.dest_eans if e not in enabled]
    if unsel:
        out[UNSELECTED] = frame[unsel].sum(axis=1)
    for col in frame.columns:
        if is_producer_col(col):
            out[col] = frame[col]
    return pd.DataFrame(out, index=frame.index), n_rest


def _label(col: str, names: dict[str, str], data: SharingData, lang: str,
           n_rest: int = 0) -> str:
    if is_producer_col(col):
        src = col[len(PRODUCER):]
        return names[src] if src == POOL else t("bill_producer", lang).format(name=names[src])
    if col == UNSELECTED:
        return t("bill_unselected", lang)
    if col == OTHER:
        return t("others", lang).format(n=n_rest)
    return names.get(col, col)


def _areas(fig: go.Figure, frame: pd.DataFrame, data: SharingData, names: dict, lang: str,
           th: dict, top, n_rest: int) -> None:
    cmap = colour_map(data, top)
    unit = t("currency", lang)
    greens = dict(zip([c for c in frame.columns if is_producer_col(c)],
                      producer_greens(th, len(data.source_eans))))
    for col in frame.columns:
        if col in greens:
            colour, pattern = greens[col], producer_hatch(th, greens[col])
        elif col == UNSELECTED:
            colour, pattern = th["others"], hatch(th)
        else:
            colour, pattern = cmap.get(col, OTHER_COLOUR), None
        area(fig, frame.index, frame[col].to_numpy(), _label(col, names, data, lang, n_rest),
             colour, th, unit, pattern=pattern, line_width=1.0 if col == UNSELECTED else 0.6)


def fig_bill_pie(bill: Billing, data: SharingData, enabled: set[str], lang: str = "cs",
                 th: dict | None = None) -> go.Figure:
    """Where the benefit went: the producer's share, the shares of the ticked and the
    unticked members, and what the EDC sharing missed against the best possible one.
    The slices add up to the best possible benefit."""
    th = th or THEMES["light"]
    cur = t("currency", lang)
    fig = figure(t("bill_pie_title", lang), lang, 500, th)
    if bill.maximum <= 0:
        return no_data(fig, lang, th)
    sel = np.array([e in enabled for e in data.dest_eans])
    slices = [   # label, value, colour, hatched, pulled out
        (tn("bill_pie_producer", lang, len(data.source_eans)), float(bill.producer_share.sum()),
         th["source"], False, False),
        (t("bill_pie_members", lang), float(bill.share[sel].sum()), th["members"], False, False),
        (t("bill_pie_unselected", lang), float(bill.share[~sel].sum()), th["others"], True, False),
        (t("bill_pie_lost", lang), bill.maximum - bill.realized, th["wasted"], False, True),
    ]
    note = [t("bill_pie_total", lang).format(total=fmt_num(bill.maximum, lang), cur=cur),
            t("bill_pie_subtitle", lang)]
    return pie(fig, [s for s in slices if s[1] > 0.005], note, th=th, unit=cur,
               hover_decimals=2)


def fig_bill_monthly(per_interval: pd.DataFrame, producer_cols: list[str], *,
                     lang: str = "cs", th: dict | None = None) -> go.Figure:
    """The producers' share of the benefit in each calendar month: scarce production
    (winter) pays the producer more, enough for everybody pays half. Lines: half, and
    the share over the whole period. A month the report covers only partly says so in
    its hover."""
    th = th or THEMES["light"]
    n_prod = len(producer_cols)
    fig = figure(tn("bill_monthly_title", lang, n_prod), lang, 500, th)
    total = per_interval.sum(axis=1)
    prod = per_interval[producer_cols].sum(axis=1)
    m = pd.DataFrame({"prod": prod, "total": total}).resample("MS").sum()
    m = m[m["total"] > 0.005]
    if m.empty:
        return no_data(fig, lang, th)
    share = 100 * m["prod"] / m["total"]
    whole = 100 * float(m["prod"].sum() / m["total"].sum())
    first, last = per_interval.index.min(), per_interval.index.max()
    cur = t("currency", lang)
    labels, notes = [], []
    for ts in m.index:
        labels.append(month_label(ts, lang))
        part = ""
        if ts.year == first.year and ts.month == first.month and first.day > 1:
            part = t("bill_month_from", lang).format(day=first.day)
        elif ts.year == last.year and ts.month == last.month and last.day < ts.days_in_month:
            part = t("bill_month_to", lang).format(day=last.day)
        notes.append(f" ({part})" if part else "")
    pct = lambda v: f"{fmt_num(v, lang, 0)} %"  # noqa: E731
    fig.add_bar(
        x=labels, y=share, marker=dict(color=th["source"]), showlegend=False,
        text=[pct(v) for v in share], textposition="outside", cliponaxis=False,
        textfont=dict(size=11, color=th["ink"]),
        # numbers stay numbers for the hover's format (a numpy stack would make them text)
        customdata=[[float(p), float(tot), note]
                    for p, tot, note in zip(m["prod"], m["total"], notes)],
        hovertemplate="%{x}%{customdata[2]}<br>" + t("bill_monthly_hover", lang).format(
            share="%{y:,.1f} %", prod="%{customdata[0]:,.0f} " + cur,
            total="%{customdata[1]:,.0f} " + cur) + "<extra></extra>")
    for y, name, dash in ((50.0, t("bill_monthly_half", lang), "dash"),
                          (whole, t("bill_monthly_whole", lang).format(pct=pct(whole)), "dot")):
        fig.add_scatter(x=[-0.5, len(labels) - 0.5], y=[y, y], mode="lines", name=name,
                        line=dict(color=th["muted"], width=1.5, dash=dash), hoverinfo="skip",
                        xaxis="x2")
    fig.update_layout(
        bargap=0.25, hovermode="closest",
        xaxis=dict(type="category", tickangle=-30, showgrid=False),
        # the lines span the whole plot width (their own axis over the bars' categories)
        xaxis2=dict(type="linear", overlaying="x", visible=False,
                    range=[-0.5, len(labels) - 0.5]),
        yaxis=dict(title=tn("bill_monthly_axis", lang, n_prod), range=[0, 105],
                   ticksuffix=" %", showgrid=True),
        legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="left", x=0,
                    font=dict(size=11)),
    )
    return fig


def fig_bill_daily(cols: pd.DataFrame, data: SharingData, names: dict[str, str], *,
                   n_rest: int = 0, lang: str = "cs", sel_day: str | None = None,
                   th: dict | None = None, top: tuple[str, ...] | None = None) -> go.Figure:
    """Stacked areas of the daily share of the benefit per member and the producer.
    Click a day to select it, like in the daily energy plot."""
    th = th or THEMES["light"]
    fig = figure(t("bill_daily_title", lang), lang, 460, th)
    daily = cols.resample("D").sum()
    if daily.empty:
        return no_data(fig, lang, th)
    _areas(fig, daily, data, names, lang, th, top, n_rest)
    return daily_layout(fig, daily.index, t("bill_daily_ylabel", lang), sel_day, lang, th)


def fig_bill_intraday(cols: pd.DataFrame, data: SharingData, names: dict[str, str],
                      day: str | None, *, n_rest: int = 0, lang: str = "cs",
                      th: dict | None = None, top: tuple[str, ...] | None = None) -> go.Figure:
    """The share of the benefit per 15 min on one calendar day (its own y axis: Kč)."""
    th = th or THEMES["light"]
    day_ts, day_df = day_slice(cols, day)
    fig = figure(t("bill_on", lang).format(date=date_text(day_ts, lang)), lang, 440, th)
    peak = float(day_df.clip(lower=0).sum(axis=1).max()) if not day_df.empty else 0.0
    intraday_layout(fig, day_ts, t("bill_intraday_ylabel", lang), peak if peak > 0 else 1.0)
    if day_df.empty:
        return no_data(fig, lang, th, hide_axes=False)
    _areas(fig, day_df, data, names, lang, th, top, n_rest)
    intraday_legend(fig)
    return fig
