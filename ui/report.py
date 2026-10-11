"""Callbacks of the report: the two columns (EDC report on the left; the exact method
or the billing on the right), the hourly plot of the selected day, and the day
selection."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import dash
import numpy as np
from dash import ALL, Input, Output, State, callback, clientside_callback, ctx, html, no_update

import store
from edc_data import (
    SharingData, compute_wasted_split, exact_gain, filter_dests, with_overlap,
)
from figures import (
    bill_columns, fig_bill_daily, fig_bill_heatmap, fig_bill_intraday, fig_bill_pie,
    fig_bill_split, fig_daily, fig_heatmap, fig_intraday, fig_total_by_flow, fig_wasted_pie,
    flow_order, heat_metrics, heat_pivot, intraday_ymax, pair_figures, share_stack_ymax,
    share_xrange, theme, top_dests,
)
from i18n import t

from . import members, views
from .layout import fig_id, job_ids

HIDDEN = {"display": "none"}
_REVS = dict(exact_rev=Input(job_ids("exact")["rev"], "data"),
             bill_rev=Input(job_ids("bill")["rev"], "data"),
             view=Input("right-view", "value"))
_MEMBERS = dict(selected=Input("members", "selectedRows"),
                changed=Input("members", "cellValueChanged"),
                name_values=Input({"type": "name", "ean": ALL}, "value"))
_MEMBER_STATE = dict(name_ids=State({"type": "name", "ean": ALL}, "id"),
                     rows=State("members", "rowData"))


def right_mode(entry: store.Entry | None, view: str | None) -> str | None:
    """What the right column shows: "exact", "bill" or nothing."""
    if entry is None:
        return None
    if view == "bill" and entry.bill is not None:
        return "bill"
    if entry.exact is not None:
        return "exact"
    return "bill" if entry.bill is not None else None


@callback(
    Output("right-view", "options"),
    Output("right-view", "value"),
    Output("right-view-box", "style"),
    Input(job_ids("exact")["rev"], "data"),
    Input(job_ids("bill")["rev"], "data"),
    Input("data-key", "data"),
    Input("lang", "value"),
    State("right-view", "value"),
)
def right_view(_exact_rev, _bill_rev, key, lang, current):
    """The switch appears when both computations exist; one that has just finished is
    shown."""
    entry = store.get(key)
    options = [{"label": t("right_exact", lang), "value": "exact"},
               {"label": t("right_bill", lang), "value": "bill"}]
    if entry is None:
        return options, "exact", HIDDEN
    value = {job_ids("bill")["rev"]: "bill",
             job_ids("exact")["rev"]: "exact"}.get(ctx.triggered_id, current or "exact")
    value = right_mode(entry, value) or "exact"
    both = entry.exact is not None and entry.bill is not None
    return options, value, {} if both else HIDDEN


@dataclass
class Scope:
    """What one render is about: the report, the selection, names, language, theme."""

    entry: store.Entry
    enabled: set[str]
    names: dict[str, str]
    lang: str
    th: dict
    top: tuple[str, ...] | None        # members drawn individually (large groups fold)

    @property
    def data(self) -> SharingData:
        return self.entry.data

    @property
    def opts(self) -> dict:
        return dict(lang=self.lang, th=self.th, top=self.top)


def _scope(key, selected, lang, theme_name, name_ids, name_values, rows) -> Scope | None:
    entry = store.get(key)
    if entry is None:
        return None
    data = entry.data
    enabled = members.enabled(data, selected)
    return Scope(entry, enabled, members.names(data, lang, name_ids, name_values, rows), lang,
                 theme(theme_name), top_dests(filter_dests(data, enabled), data))


def _bill_frame(s: Scope, enabled: set[str] | None = None):
    """Per-interval Kč for the plots, with the ticked members as in the energy plots."""
    return bill_columns(s.entry.bill.per_interval, s.data,
                        s.enabled if enabled is None else enabled, s.top)


# ---------------------------------------------------------------------------
# The two columns
# ---------------------------------------------------------------------------


def _left(s: Scope, sel_day: str | None) -> dict:
    data, exact = s.data, s.entry.exact
    df = filter_dests(data, s.enabled)
    out = dict(tiles=None, overview=fig_total_by_flow(df, data, s.names, **s.opts),
               daily=fig_daily(df, data, s.names, sel_day=sel_day, **s.opts), pie={})
    if data.fmt == "all":
        split = compute_wasted_split(df)
        if exact is not None:     # "could have been shared" = what the exact method adds
            split = with_overlap(split, exact_gain(data, exact.data, s.enabled))
        out["pie"] = fig_wasted_pie(split, s.lang, s.th, exact_based=exact is not None)
    return out


def _right_exact(s: Scope, sel_day: str | None, order: list[str]) -> dict:
    exact = s.entry.exact
    df = filter_dests(exact.data, s.enabled)
    return dict(
        tiles=views.energy_tiles(exact.data, s.enabled, s.lang, ref=s.data, exact=exact.data),
        overview=fig_total_by_flow(df, exact.data, s.names, order=order, **s.opts),
        daily=fig_daily(df, exact.data, s.names, sel_day=sel_day, **s.opts),
        pie=fig_wasted_pie(compute_wasted_split(df), s.lang, s.th),
    )


def _right_bill(s: Scope, sel_day: str | None, order: list[str]) -> dict:
    bill = s.entry.bill.settlement
    cols, n_rest = _bill_frame(s)
    return dict(
        tiles=views.bill_tiles(bill, s.data, s.enabled, s.lang),
        overview=fig_bill_split(bill, s.data, s.names, s.enabled, order=order, **s.opts),
        daily=fig_bill_daily(cols, s.data, s.names, n_rest=n_rest, sel_day=sel_day, **s.opts),
        pie=fig_bill_pie(bill, s.data, s.enabled, s.lang, s.th),
    )


def _heatmaps(s: Scope, right: str | None, metric: str) -> tuple:
    """Left: production or consumption (part report: shared). Right: the same of the
    exact method on one colour scale, or the benefit in Kč on its own."""
    data = s.data
    metrics = heat_metrics(data)
    metric = metric if metric in metrics else metrics[0]
    pivots = [heat_pivot(data, s.enabled, metric)]
    if right == "exact":
        pivots.append(heat_pivot(s.entry.exact.data, s.enabled, metric))
    peaks = [float(np.nanmax(p.to_numpy())) for p in pivots if not p.empty]
    z_max = max(peaks) if peaks else None
    figs = [fig_heatmap(p, metric, z_max=z_max, lang=s.lang, th=s.th) for p in pivots]
    if right == "bill":
        total = s.entry.bill.per_interval.sum(axis=1)
        figs.append(fig_bill_heatmap(total, lang=s.lang, th=s.th))
    return figs[0], figs[1] if len(figs) > 1 else {}


def _height(fig) -> dict:
    return {"height": f"{fig.layout.height}px"} if fig else {}


_FIGS = ("overview", "pie", "daily", "heat")
RENDER_OUTPUTS = dict(
    title=Output("page-title", "children"),
    status=Output("upload-status", "children", allow_duplicate=True),
    info=Output("info", "children"),
    notes=Output("notes", "children"),
    compare=Output("compare", "className"),
    head_b=Output("head-b", "children"),
    pie_card=Output("pie-card", "style"),
    dest_table=Output("dest-table", "children"),
    cmp_card=Output("cmp-card", "style"),
    cmp_table=Output("cmp-table", "children"),
    settle_card=Output("settle-card", "style"),
    **{f"tiles_{side}": Output(f"tiles-{side}", "children") for side in "ab"},
    **{f"{name}_{side}": Output(fig_id(name, side), "figure") for name in _FIGS for side in "ab"},
    **{f"{name}_{side}_h": Output(fig_id(name, side), "style")
       for name in _FIGS for side in "ab"},
)


@callback(
    output=RENDER_OUTPUTS,
    inputs=dict(key=Input("data-key", "data"), **_REVS, **_MEMBERS,
                lang=Input("lang", "value"), group=Input("group", "value"),
                heat_metric=Input("heat-metric", "value"), theme_name=Input("theme", "data")),
    state=dict(**_MEMBER_STATE, sel_day=State("day-picker", "date")),
    prevent_initial_call="initial_duplicate",
)
def render(key, exact_rev, bill_rev, view, selected, changed, name_values, lang, group,
           heat_metric, theme_name, name_ids, rows, sel_day):
    if members.key_only_edit():
        raise dash.exceptions.PreventUpdate      # a key or price changed: figures unaffected
    group = (group or "").strip()
    title = t("report_title_group", lang).format(group=group) if group else t("report_title", lang)
    s = _scope(key, selected, lang, theme_name, name_ids, name_values, rows)
    if s is None:
        out = {k: {} for k in RENDER_OUTPUTS}
        out.update(title=title, info=[], notes=[], compare="compare single", head_b="",
                   dest_table=[], cmp_card=HIDDEN, cmp_table=[], settle_card=HIDDEN,
                   tiles_a=[], tiles_b=[],
                   status=html.Div(t("session_lost", lang), className="status-error")
                   if key else no_update)
        return out
    data, exact = s.data, s.entry.exact
    sel_day = _day(sel_day)
    right = right_mode(s.entry, view)
    order = flow_order(filter_dests(data, s.enabled), data, s.top)   # same member rows
    a = _left(s, sel_day)
    a["tiles"] = views.energy_tiles(data, s.enabled, lang, pad=right is not None,
                                    exact=exact.data if exact is not None else None)
    b = dict(tiles=[], overview={}, pie={}, daily={})
    if right == "exact":
        b = _right_exact(s, sel_day, order)
        share_xrange(a["overview"], b["overview"])
        share_stack_ymax(a["daily"], b["daily"])
    elif right == "bill":
        b = _right_bill(s, sel_day, order)
    if right is not None:          # paired cards line up: heights, margins, legend rows
        for name in ("overview", "daily", "pie"):
            pair_figures(a[name], b[name])
    a["heat"], b["heat"] = _heatmaps(s, right, heat_metric)

    out = dict(
        title=title,
        status=html.Div([html.Span("✓ ", className="ok"), f"{t('loaded', lang)}: ",
                         html.B(s.entry.filename)], className="status-ok"),
        info=views.facts(s.entry.filename, data, s.enabled, s.names, lang),
        notes=views.data_notes(data, lang),
        compare="compare dual" if right else "compare single",
        head_b={"exact": t("col_exact", lang), "bill": t("col_bill", lang)}.get(right, ""),
        pie_card={} if data.fmt == "all" else HIDDEN,
        dest_table=views.dest_table(data, s.enabled, s.names, lang, s.top),
        cmp_card={} if right == "exact" else HIDDEN,
        cmp_table=(views.cmp_table(data, exact, s.enabled, s.names, lang, s.top)
                   if right == "exact" else []),
        settle_card={} if right == "bill" else HIDDEN,
    )
    for side, col in (("a", a), ("b", b)):
        out[f"tiles_{side}"] = col["tiles"]
        for name in _FIGS:
            out[f"{name}_{side}"] = col[name]
            out[f"{name}_{side}_h"] = _height(col[name])
    return out


# ---------------------------------------------------------------------------
# The selected day: click the daily plot, or ◀ / date picker / ▶ in the panel
# ---------------------------------------------------------------------------


def _day(value) -> str | None:
    """Normalise a date-ish value ('2026-06-19', '2026-06-19 00:00', …) to ISO date."""
    return str(value)[:10] if value else None


@callback(
    Output("day-picker", "date", allow_duplicate=True),
    Input(fig_id("daily", "a"), "clickData"),
    Input(fig_id("daily", "b"), "clickData"),
    Input("btn-prev-day", "n_clicks"),
    Input("btn-next-day", "n_clicks"),
    State("day-picker", "date"),
    State("day-picker", "min_date_allowed"),
    State("day-picker", "max_date_allowed"),
    prevent_initial_call=True,
)
def select_day(click_a, click_b, _prev, _next, current, lo, hi):
    trig = ctx.triggered_id
    if trig in (fig_id("daily", "a"), fig_id("daily", "b")):
        click = click_a if trig == fig_id("daily", "a") else click_b
        if not click or not click.get("points"):
            raise dash.exceptions.PreventUpdate
        day = _day(click["points"][0].get("x"))
    else:
        if not current:
            raise dash.exceptions.PreventUpdate
        step = -1 if trig == "btn-prev-day" else 1
        day = (dt.date.fromisoformat(_day(current)) + dt.timedelta(days=step)).isoformat()
    day = min(max(day, _day(lo) or day), _day(hi) or day)
    if day == _day(current):
        raise dash.exceptions.PreventUpdate
    return day


# Move only the dashed marker, in the browser (no server round-trip); skipped while a
# daily figure has not been drawn yet.
clientside_callback(
    """
    function(day, figA, figB) {
        const nu = window.dash_clientside.no_update;
        function mark(fig) {
            if (!day || !fig || !fig.data || !fig.data.length) { return nu; }
            const d = String(day).slice(0, 10);
            const layout = Object.assign({}, fig.layout, {shapes: [{
                type: 'line', xref: 'x', yref: 'paper', x0: d, x1: d, y0: 0, y1: 1,
                line: {color: (fig.layout.meta && fig.layout.meta.marker) || 'black',
                       width: 1.5, dash: 'dash'}, layer: 'above'}]});
            return Object.assign({}, fig, {layout: layout});
        }
        return [mark(figA), mark(figB)];
    }
    """,
    Output(fig_id("daily", "a"), "figure", allow_duplicate=True),
    Output(fig_id("daily", "b"), "figure", allow_duplicate=True),
    Input("day-picker", "date"),
    State(fig_id("daily", "a"), "figure"),
    State(fig_id("daily", "b"), "figure"),
    prevent_initial_call=True,
)


@callback(
    output=[Output(fig_id("hourly", "a"), "figure"), Output(fig_id("hourly", "a"), "style"),
            Output(fig_id("hourly", "b"), "figure"), Output(fig_id("hourly", "b"), "style")],
    inputs=dict(day=Input("day-picker", "date"), key=Input("data-key", "data"), **_REVS,
                **_MEMBERS, lang=Input("lang", "value"), theme_name=Input("theme", "data")),
    state=_MEMBER_STATE,
)
def hourly(day, key, exact_rev, bill_rev, view, selected, changed, name_values, lang,
           theme_name, name_ids, rows):
    """The selected day in 15-min steps. The energy plots share one y axis fitted to
    the day, so both methods compare on one scale; the billing (Kč) has its own."""
    if members.key_only_edit():
        raise dash.exceptions.PreventUpdate
    s = _scope(key, selected, lang, theme_name, name_ids, name_values, rows)
    if s is None or not day:
        return {}, {}, {}, {}
    day = _day(day)
    right = right_mode(s.entry, view)
    frames = [filter_dests(s.data, s.enabled)]
    if right == "exact":
        frames.append(filter_dests(s.entry.exact.data, s.enabled))
    y_max = max(intraday_ymax(f, day) for f in frames)
    fa = fig_intraday(frames[0], s.data, s.names, day, y_max=y_max, **s.opts)
    fb = {}
    if right == "exact":
        fb = fig_intraday(frames[1], s.entry.exact.data, s.names, day, y_max=y_max, **s.opts)
    elif right == "bill":
        cols, n_rest = _bill_frame(s)
        fb = fig_bill_intraday(cols, s.data, s.names, day, n_rest=n_rest, **s.opts)
    pair_figures(fa, fb)
    return fa, _height(fa), fb, _height(fb)
