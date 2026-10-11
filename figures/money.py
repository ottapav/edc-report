"""The billing figures (Kč): the five shapes of the energy report again, so the right
column of the page lines up with the left one.

* value of the shared electricity per member  (:func:`fig_bill_split`)
* where the benefit went                      (:func:`fig_bill_pie`)
* daily share of the benefit                  (:func:`fig_bill_daily`)
* the benefit on one day, per 15 min          (:func:`fig_bill_intraday`)
* mean benefit, hour × month                  (:func:`fig_bill_heatmap`)

The per-interval values come from :attr:`billing.BillResult.per_interval`, the
settlement from :class:`billing.Billing`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from billing import PRODUCER, Billing, is_producer_col, producer_col
from edc_data import POOL, SharingData
from i18n import fmt_num, t, tn

from .base import (
    OTHER, OTHER_COLOUR, THEMES, area, colour_map, daily_layout, date_text, day_slice,
    figure, hatch, hbars, heatmap, hour_month_pivot, intraday_layout, intraday_legend,
    member_groups, no_data, order_rows, pie, producer_greens, producer_hatch,
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


def fig_bill_split(bill: Billing, data: SharingData, names: dict[str, str], enabled: set[str],
                   *, lang: str = "cs", th: dict | None = None,
                   top: tuple[str, ...] | None = None,
                   order: list[str] | None = None) -> go.Figure:
    """Value of the shared electricity per member: share of the benefit (member's
    colour) + payment to the producers (grey) = value at the supplier price; each
    producer: its share (hatched green) + feed-in value (grey) = what it receives.
    Members sit on the rows of the paired flow chart (``order``)."""
    th = th or THEMES["light"]
    cur = t("currency", lang)
    fig = figure(t("bill_split_title", lang), lang, 420, th)
    idx = {e: j for j, e in enumerate(data.dest_eans)}
    sel = [e for e in data.dest_eans if e in enabled]
    if not sel and bill.producer_income.sum() <= 0:
        return no_data(fig, lang, th)
    cmap = colour_map(data, top)
    share_lab, pays_lab = t("bill_col_share_short", lang), t("bill_pays", lang)

    def row(key, label, share, pay, c_share, c_pay, pay_lab, summary=False):
        return dict(key=key, label=label, summary=summary,
                    text=f"{fmt_num(share, lang, 0)} + {fmt_num(pay, lang, 0)} ({pay_lab}) {cur}",
                    segs=[(share, c_share, share_lab), (pay, c_pay, pay_lab)])

    groups = member_groups(data, enabled, top)
    n_rest = len(groups[-1][1]) if groups and groups[-1][0] == OTHER else 0
    rows: list[dict | None] = [
        row(key, _label(key, names, data, lang, n_rest),
            float(sum(bill.share[idx[e]] for e in members)),
            float(sum(bill.payment[idx[e]] for e in members)),
            cmap.get(key, OTHER_COLOUR), th["unmet"], pays_lab)
        for key, members in groups]
    rows = order_rows(rows, order, key=lambda r: r["segs"][0][0] + r["segs"][1][0])
    many = len(rows) > 1
    # the producers in one row, like the pool's row of the paired flow chart (several
    # producers: the settlement table has each of them)
    src = data.source_eans[0] if len(data.source_eans) == 1 else POOL
    rows.append(row(producer_col(src), _label(producer_col(src), names, data, lang),
                    float(bill.producer_share.sum()), float(bill.feed_in_value.sum()),
                    th["source"], th["unshared"], t("bill_feed_in_value", lang)))
    if many:
        rows += [None, row(None, t("bill_total_members", lang),
                           float(sum(bill.share[idx[e]] for e in sel)),
                           float(sum(bill.payment[idx[e]] for e in sel)),
                           th["total"], th["unmet"], pays_lab, summary=True)]
    shapes = ["x" if is_producer_col(r["key"]) else "" for r in rows if r is not None]
    slots = [dict(name=share_lab, pattern=dict(shape=shapes, size=6, solidity=0.3,
                                               fgcolor=th["source_ink"])),
             dict(name=pays_lab)]
    return hbars(fig, rows, slots, th=th, unit=cur, hover_decimals=2,
                 xtitle=t("bill_split_xlabel", lang), xpad=1.5, inside_above=0.75)


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


def fig_bill_heatmap(total: pd.Series, *, lang: str = "cs", th: dict | None = None) -> go.Figure:
    """Mean benefit of the whole group (Kč per 15 min), hour of day × month."""
    th = th or THEMES["light"]
    fig = figure(t("bill_heat_title", lang), lang, 440, th)
    return heatmap(fig, hour_month_pivot(total), cbar=t("bill_heat_cbar", lang),
                   unit=t("currency", lang), z_max=None, lang=lang, th=th)
