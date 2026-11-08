"""Callbacks of the report: the two columns of the sharing tab (the EDC report on the
left, the exact method on the right once computed), the billing tab's result, the
hourly plots of the selected day, and the day selection."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import dash
from dash import Input, Output, State, callback, clientside_callback, ctx, html, no_update

import store
from edc_data import (
    SharingData, compute_wasted_split, exact_gain, filter_dests, with_overlap,
)
from figures import (
    bill_columns, fig_bill_daily, fig_bill_intraday, fig_bill_monthly, fig_bill_pie,
    fig_daily, fig_heatmap, fig_intraday, fig_total_by_flow, fig_wasted_pie, flow_order,
    heat_metrics, heat_pivot, intraday_ymax, pair_figures, share_stack_ymax, share_xrange,
    theme, top_dests,
)
from i18n import method_title, t

from . import members, views
from .layout import fig_id, job_ids, spot_fig_id

HIDDEN = {"display": "none"}
_EXACT_REV = dict(exact_rev=Input(job_ids("exact")["rev"], "data"))
_BILL_REV = dict(bill_rev=Input(job_ids("bill")["rev"], "data"))
#: names typed in the grids; the billing is the whole group's, the selection changes
#: only the sharing tab (``_MEMBERS``)
_NAMES = dict(changed=Input("members", "cellValueChanged"),
              src_changed=Input("producers", "cellValueChanged"))
_MEMBERS = dict(selected=Input("members", "selectedRows"), **_NAMES)
_MEMBER_STATE = dict(rows=State("members", "rowData"), src_rows=State("producers", "rowData"))


def right_mode(entry: store.Entry | None) -> str | None:
    """What the right column shows: the exact method once computed, else nothing (the
    columns belong to the sharing tab; the billing has its own tab)."""
    return "exact" if entry is not None and entry.exact is not None else None


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


def _scope(key, selected, lang, theme_name, src_rows, rows) -> Scope | None:
    entry = store.get(key)
    if entry is None:
        return None
    data = entry.data
    enabled = members.enabled(data, selected)
    return Scope(entry, enabled, members.names(data, lang, src_rows, rows), lang,
                 theme(theme_name), top_dests(filter_dests(data, enabled), data))


def _bill_frame(s: Scope):
    """Per-interval Kč for the plots, the whole group."""
    return bill_columns(s.entry.bill.per_interval, s.data, s.top)


# ---------------------------------------------------------------------------
# The two columns
# ---------------------------------------------------------------------------


def _left_sides(s: Scope) -> tuple[SharingData, SharingData | None]:
    """(the left column's data, the exact recompute it is compared with or None).

    Next to the exact method the left column uses the same keys: the EDC report, or
    today's method replayed with the keys the user typed."""
    data, exact = s.data, s.entry.exact
    if exact is None:
        return data, None
    return exact.left(data), exact.data


def _left(s: Scope, sel_day: str | None, data: SharingData,
          exact: SharingData | None) -> dict:
    df = filter_dests(data, s.enabled)
    out = dict(tiles=None, overview=fig_total_by_flow(df, data, s.names, **s.opts),
               daily=fig_daily(df, data, s.names, sel_day=sel_day, **s.opts), pie={})
    if data.fmt == "all":
        split = compute_wasted_split(df)
        if exact is not None:     # "could have been shared" = what the exact method adds
            split = with_overlap(split, exact_gain(data, exact, s.enabled))
        out["pie"] = fig_wasted_pie(split, s.lang, s.th, exact_based=exact is not None)
    return out


def _right_exact(s: Scope, sel_day: str | None, order: list[str], left: SharingData) -> dict:
    exact = s.entry.exact
    df = filter_dests(exact.data, s.enabled)
    return dict(
        tiles=views.energy_tiles(exact.data, s.enabled, s.lang, ref=left, exact=exact.data),
        overview=fig_total_by_flow(df, exact.data, s.names, order=order, **s.opts),
        daily=fig_daily(df, exact.data, s.names, sel_day=sel_day, **s.opts),
        pie=fig_wasted_pie(with_overlap(compute_wasted_split(df), 0.0), s.lang, s.th,
                           explain=False),     # the most these keys can share: see views
    )


def _heatmap(s: Scope, metric: str):
    """Production or consumption (part report: shared); the right column has none
    (production and consumption do not depend on the sharing method)."""
    metrics = heat_metrics(s.data)
    metric = metric if metric in metrics else metrics[0]
    return fig_heatmap(heat_pivot(s.data, s.enabled, metric), metric, lang=s.lang, th=s.th)


def _height(fig) -> dict:
    return {"height": f"{fig.layout.height}px"} if fig else {}


_FIGS = ("overview", "pie", "daily", "heat")
RENDER_OUTPUTS = dict(
    title=Output("page-title", "children"),
    status=Output("upload-status", "children", allow_duplicate=True),
    info=Output("info", "children"),
    notes=Output("notes", "children"),
    compare=Output("compare", "className"),
    head_a=Output("head-a", "children"),
    head_b=Output("head-b", "children"),
    pie_card=Output("pie-card", "style"),
    dest_table=Output("dest-table", "children"),
    cmp_card=Output("cmp-card", "style"),
    cmp_table=Output("cmp-table", "children"),
    **{f"tiles_{side}": Output(f"tiles-{side}", "children") for side in "ab"},
    **{f"{name}_{side}": Output(fig_id(name, side), "figure") for name in _FIGS for side in "ab"},
    **{f"{name}_{side}_h": Output(fig_id(name, side), "style")
       for name in _FIGS for side in "ab"},
)


@callback(
    output=RENDER_OUTPUTS,
    inputs=dict(key=Input("data-key", "data"), **_EXACT_REV, **_MEMBERS,
                lang=Input("lang", "value"), group=Input("group", "value"),
                heat_metric=Input("heat-metric", "value"), theme_name=Input("theme", "data")),
    state=dict(**_MEMBER_STATE, sel_day=State("day-picker", "date")),
    prevent_initial_call="initial_duplicate",
)
def render(key, exact_rev, selected, changed, src_changed, lang, group,
           heat_metric, theme_name, rows, src_rows, sel_day):
    if members.key_only_edit():
        raise dash.exceptions.PreventUpdate      # a key or price changed: figures unaffected
    group = (group or "").strip()
    title = t("report_title_group", lang).format(group=group) if group else t("report_title", lang)
    s = _scope(key, selected, lang, theme_name, src_rows, rows)
    if s is None:
        out = {k: {} for k in RENDER_OUTPUTS}
        out.update(title=title, info=[], notes=[], compare="compare single", head_a=t("col_edc", lang), head_b="",
                   dest_table=[], cmp_card=HIDDEN, cmp_table=[],
                   tiles_a=[], tiles_b=[],
                   status=html.Div(t("session_lost", lang), className="status-error")
                   if key else no_update)
        return out
    data, exact = s.data, s.entry.exact
    sel_day = _day(sel_day)
    right = right_mode(s.entry)
    order = flow_order(filter_dests(data, s.enabled), data, s.top)   # same member rows
    left, versus = _left_sides(s)
    a = _left(s, sel_day, left, versus)
    a["tiles"] = views.energy_tiles(left, s.enabled, lang, pad=right is not None, exact=versus)
    b = dict(tiles=[], overview={}, pie={}, daily={})
    if right == "exact":
        b = _right_exact(s, sel_day, order, left)
        share_xrange(a["overview"], b["overview"])
        share_stack_ymax(a["daily"], b["daily"])
        for name in ("overview", "daily", "pie"):   # paired cards line up
            pair_figures(a[name], b[name])
    a["heat"], b["heat"] = _heatmap(s, heat_metric), {}

    out = dict(
        title=title,
        status=html.Div([html.Span("✓ ", className="ok"), f"{t('loaded', lang)}: ",
                         html.B(s.entry.filename)], className="status-ok"),
        info=views.facts(s.entry.filename, data, s.enabled, s.names, lang),
        notes=views.data_notes(data, lang),
        compare=f"compare dual right-{right}" if right else "compare single",
        head_a=method_title("col_edc" if left is data else "col_edc_replay",
                            len(data.source_eans), lang),
        head_b=method_title("col_exact", len(data.source_eans), lang) if right else "",
        pie_card={} if data.fmt == "all" else HIDDEN,
        dest_table=views.dest_table(data, s.enabled, s.names, lang, s.top),
        cmp_card={} if right == "exact" else HIDDEN,
        cmp_table=(views.cmp_table(data, exact, s.enabled, s.names, lang, s.top)
                   if right == "exact" else []),
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
    Input(spot_fig_id("daily"), "clickData"),
    Input("fig-bill-daily", "clickData"),
    Input("btn-prev-day", "n_clicks"),
    Input("btn-next-day", "n_clicks"),
    State("day-picker", "date"),
    State("day-picker", "min_date_allowed"),
    State("day-picker", "max_date_allowed"),
    prevent_initial_call=True,
)
def select_day(click_a, click_b, click_spot, click_bill, _prev, _next, current, lo, hi):
    trig = ctx.triggered_id
    clicks = {fig_id("daily", "a"): click_a, fig_id("daily", "b"): click_b,
              spot_fig_id("daily"): click_spot, "fig-bill-daily": click_bill}
    if trig in clicks:
        click = clicks[trig]
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
    function(day, figA, figB, figBill) {
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
        return [mark(figA), mark(figB), mark(figBill)];
    }
    """,
    Output(fig_id("daily", "a"), "figure", allow_duplicate=True),
    Output(fig_id("daily", "b"), "figure", allow_duplicate=True),
    Output("fig-bill-daily", "figure", allow_duplicate=True),
    Input("day-picker", "date"),
    State(fig_id("daily", "a"), "figure"),
    State(fig_id("daily", "b"), "figure"),
    State("fig-bill-daily", "figure"),
    prevent_initial_call=True,
)


@callback(
    output=[Output(fig_id("hourly", "a"), "figure"), Output(fig_id("hourly", "a"), "style"),
            Output(fig_id("hourly", "b"), "figure"), Output(fig_id("hourly", "b"), "style")],
    inputs=dict(day=Input("day-picker", "date"), key=Input("data-key", "data"), **_EXACT_REV,
                **_MEMBERS, lang=Input("lang", "value"), theme_name=Input("theme", "data")),
    state=dict(_MEMBER_STATE),      # a copy: Dash adds the inputs to the dict it gets
)
def hourly(day, key, exact_rev, selected, changed, src_changed, lang, theme_name, rows,
           src_rows):
    """The selected day in 15-min steps. The energy plots share one y axis fitted to
    the day, so both methods compare on one scale."""
    if members.key_only_edit():
        raise dash.exceptions.PreventUpdate
    s = _scope(key, selected, lang, theme_name, src_rows, rows)
    if s is None or not day:
        return {}, {}, {}, {}
    day = _day(day)
    right = right_mode(s.entry)
    frames = [filter_dests(s.data, s.enabled)]
    if right == "exact":
        frames.append(filter_dests(s.entry.exact.data, s.enabled))
    y_max = max(intraday_ymax(f, day) for f in frames)
    fa = fig_intraday(frames[0], s.data, s.names, day, y_max=y_max, **s.opts)
    fb = {}
    if right == "exact":
        fb = fig_intraday(frames[1], s.entry.exact.data, s.names, day, y_max=y_max, **s.opts)
    pair_figures(fa, fb)
    return fa, _height(fa), fb, _height(fb)


# ---------------------------------------------------------------------------
# The billing tab's result
# ---------------------------------------------------------------------------


@callback(
    output=dict(body=Output("bill-body", "style"), tiles=Output("bill-tiles", "children"),
                pie=Output("fig-bill-pie", "figure"), pie_h=Output("fig-bill-pie", "style"),
                monthly=Output("fig-bill-monthly", "figure"),
                monthly_h=Output("fig-bill-monthly", "style"),
                daily=Output("fig-bill-daily", "figure"),
                daily_h=Output("fig-bill-daily", "style")),
    inputs=dict(key=Input("data-key", "data"), **_BILL_REV, **_NAMES,
                lang=Input("lang", "value"), theme_name=Input("theme", "data")),
    state=dict(**_MEMBER_STATE, sel_day=State("day-picker", "date")),
)
def render_bill(key, bill_rev, changed, src_changed, lang, theme_name, rows, src_rows,
                sel_day):
    """The billing tab below its card, once the billing is computed: the tiles, where
    the benefit went and the producers' share by month side by side, the daily share
    (in the collapsed "over time" card). The settlement table comes with the card's
    result (:func:`ui.compute.bill_result`). Always the whole group: ticking members
    off in the panel does not change the billing."""
    if members.key_only_edit():
        raise dash.exceptions.PreventUpdate
    s = _scope(key, None, lang, theme_name, src_rows, rows)
    if s is None or s.entry.bill is None:
        return dict(body=HIDDEN, tiles=[], pie={}, pie_h={}, monthly={}, monthly_h={},
                    daily={}, daily_h={})
    bill = s.entry.bill
    cols, n_rest = _bill_frame(s)
    pie = fig_bill_pie(bill.settlement, s.data, lang, s.th)
    monthly = fig_bill_monthly(bill.per_interval, bill.producer_cols, lang=lang, th=s.th)
    pie.update_layout(height=monthly.layout.height)      # side by side, the same height
    daily = fig_bill_daily(cols, s.data, s.names, n_rest=n_rest, sel_day=_day(sel_day),
                           **s.opts)
    return dict(body={}, tiles=views.bill_tiles(bill.settlement, lang),
                pie=pie, pie_h=_height(pie), monthly=monthly, monthly_h=_height(monthly),
                daily=daily, daily_h=_height(daily))


@callback(
    output=[Output("fig-bill-hourly", "figure"), Output("fig-bill-hourly", "style")],
    inputs=dict(day=Input("day-picker", "date"), key=Input("data-key", "data"), **_BILL_REV,
                **_NAMES, lang=Input("lang", "value"), theme_name=Input("theme", "data")),
    state=dict(_MEMBER_STATE),      # a copy: Dash adds the inputs to the dict it gets
)
def bill_hourly(day, key, bill_rev, changed, src_changed, lang, theme_name, rows, src_rows):
    """The share of the benefit on the selected day, per 15 min (Kč, its own y axis)."""
    if members.key_only_edit():
        raise dash.exceptions.PreventUpdate
    s = _scope(key, None, lang, theme_name, src_rows, rows)
    if s is None or s.entry.bill is None or not day:
        return {}, {}
    cols, n_rest = _bill_frame(s)
    fig = fig_bill_intraday(cols, s.data, s.names, _day(day), n_rest=n_rest, **s.opts)
    return fig, _height(fig)
