"""Callbacks of the spot tab: switch the tabs, fetch the OTE prices (on the first visit
of the tab, or with the button), and draw the comparison. The comparison takes a few
milliseconds, so it follows every price, fee or selection typed, with no button."""

from __future__ import annotations

import dash
from dash import Input, Output, State, callback, clientside_callback, ctx, no_update

import jobs
import store
from figures import (
    fig_spot_daily, fig_spot_intraday, fig_spot_members, fig_spot_monthly, fig_spot_waterfall,
    theme, top_dests,
)
from i18n import t
from spot import compare

from . import members, views
from .compute import _refused, _start_outputs, _started
from .layout import SPOT_FIGURES, job_ids, spot_fig_id

_SPOT = job_ids("spot")
HIDDEN = {"display": "none"}


# Tabs: only the panes' visibility changes, in the browser; nothing is unmounted, so
# the callbacks of the hidden tab keep their components.
clientside_callback(
    """
    function(tab) {
        const spot = tab === 'spot';
        return [spot ? {display: 'none'} : {}, spot ? {} : {display: 'none'}];
    }
    """,
    Output("pane-sharing", "style"),
    Output("pane-spot", "style"),
    Input("tabs", "value"),
)


@callback(Output("spot-curtail", "options"), Input("lang", "value"))
def _curtail_label(lang):
    return [{"label": t("spot_curtail", lang), "value": "on"}]


# The default prices are typed in the billing card or in the spot card: one value.
for _a, _b in (("feed-in", "spot-feed-in"), ("price-default", "spot-price-default")):
    @callback(Output(_a, "value"), Output(_b, "value"), Input(_a, "value"), Input(_b, "value"),
              prevent_initial_call=True)
    def _sync(a, b, _a=_a):
        value = a if ctx.triggered_id == _a or ctx.triggered_id is None else b
        return (no_update if value == a else value), (no_update if value == b else value)


def _running(job_id: str | None, key: str | None) -> bool:
    job = jobs.get(job_id)
    return job is not None and not job.done and job.data_key == key


@callback(
    output=_start_outputs("spot"),
    inputs=dict(n=Input(_SPOT["btn"], "n_clicks"), tab=Input("tabs", "value"),
                key=Input("data-key", "data")),
    state=dict(job_id=State(_SPOT["job"], "data"), lang=State("lang", "value")),
    prevent_initial_call=True,
)
def start_spot(n, tab, key, job_id, lang):
    """The button fetches the prices (again); opening the tab fetches them once."""
    clicked = ctx.triggered_id == _SPOT["btn"]
    if not clicked and tab != "spot":
        raise dash.exceptions.PreventUpdate
    entry = store.get(key)
    if entry is None:
        if clicked:
            return _refused("session_lost", lang)
        raise dash.exceptions.PreventUpdate
    if entry.data.fmt != "all":
        return _refused("part_no_spot", lang)
    if _running(job_id, key) or (not clicked and entry.spot is not None):
        raise dash.exceptions.PreventUpdate
    return _started(jobs.start_spot(key))


_INPUTS = dict(
    key=Input("data-key", "data"), rev=Input(_SPOT["rev"], "data"), tab=Input("tabs", "value"),
    selected=Input("members", "selectedRows"), changed=Input("members", "cellValueChanged"),
    src_changed=Input("producers", "cellValueChanged"), feed_in=Input("feed-in", "value"),
    default=Input("price-default", "value"), fee=Input("spot-fee", "value"),
    curtail=Input("spot-curtail", "value"), lang=Input("lang", "value"),
    theme_name=Input("theme", "data"),
)
_STATE = dict(rows=State("members", "rowData"), src_rows=State("producers", "rowData"))


def comparison(entry, rows, src_rows, feed_in, default, fee, curtail):
    """The comparison for what is typed in the panel and the two cards."""
    data = entry.data
    return compare(data, entry.spot, members.prices(data, rows, default),
                   members.feed_ins(data, src_rows, feed_in), members.number(fee) or 0.0,
                   "on" in (curtail or []))


_OUTPUTS = dict(
    body=Output("spot-body", "style"), info=Output("spot-info", "children"),
    tiles=Output("spot-tiles", "children"), table=Output("spot-table", "children"),
    **{name: Output(spot_fig_id(name), "figure") for name in SPOT_FIGURES if name != "hourly"},
    **{f"{name}_h": Output(spot_fig_id(name), "style")
       for name in SPOT_FIGURES if name != "hourly"},
)


@callback(output=_OUTPUTS, inputs=_INPUTS,
          state=dict(**_STATE, sel_day=State("day-picker", "date")))
def render_spot(key, rev, tab, selected, changed, src_changed, feed_in, default, fee, curtail,
                lang, theme_name, rows, src_rows, sel_day):
    """Tiles, figures and the table of the spot tab (only while it is open)."""
    if tab != "spot":
        raise dash.exceptions.PreventUpdate
    entry = store.get(key)
    empty = {k: no_update for k in _OUTPUTS}
    if entry is None or entry.spot is None or entry.data.fmt != "all":
        return {**empty, "body": HIDDEN, "info": []}
    data = entry.data
    cmp = comparison(entry, rows, src_rows, feed_in, default, fee, curtail)
    enabled = members.enabled(data, selected)
    names = members.names(data, lang, src_rows, rows)
    th = theme(theme_name)
    top = top_dests(data.frame, data)
    figs = dict(
        waterfall=fig_spot_waterfall(cmp, lang, th),
        members=fig_spot_members(cmp, data, names, enabled, lang=lang, th=th, top=top),
        daily=fig_spot_daily(cmp, lang=lang, sel_day=str(sel_day)[:10] if sel_day else None,
                             th=th),
        monthly=fig_spot_monthly(cmp, lang=lang, th=th),
    )
    # side by side: one height for the waterfall and the members chart
    h = max(figs["waterfall"].layout.height, figs["members"].layout.height)
    for name in ("waterfall", "members"):
        figs[name].update_layout(height=h)
    out = dict(body={}, info=views.spot_info(entry.spot, data, lang),
               tiles=views.spot_tiles(cmp, entry.bill, lang),
               table=views.spot_table(cmp, data, names, lang, top, enabled), **figs)
    for name, fig in figs.items():
        out[f"{name}_h"] = {"height": f"{fig.layout.height}px"}
    return out


@callback(Output(spot_fig_id("hourly"), "figure"), Output(spot_fig_id("hourly"), "style"),
          inputs=dict(day=Input("day-picker", "date"), **_INPUTS), state=_STATE)
def spot_hourly(day, key, rev, tab, selected, changed, src_changed, feed_in, default, fee,
                curtail, lang, theme_name, rows, src_rows):
    """The selected day: the spot price against the members' prices, and the surplus."""
    if tab != "spot":
        raise dash.exceptions.PreventUpdate
    entry = store.get(key)
    if entry is None or entry.spot is None or entry.data.fmt != "all":
        return no_update, no_update
    cmp = comparison(entry, rows, src_rows, feed_in, default, fee, curtail)
    fig = fig_spot_intraday(cmp, str(day)[:10] if day else None, lang=lang,
                            th=theme(theme_name))
    return fig, {"height": f"{fig.layout.height}px"}


# The selected day's marker on the daily plot, in the browser (like the sharing tab).
clientside_callback(
    """
    function(day, fig) {
        const nu = window.dash_clientside.no_update;
        if (!day || !fig || !fig.data || !fig.data.length) { return nu; }
        const d = String(day).slice(0, 10);
        const layout = Object.assign({}, fig.layout, {shapes: [{
            type: 'line', xref: 'x', yref: 'paper', x0: d, x1: d, y0: 0, y1: 1,
            line: {color: (fig.layout.meta && fig.layout.meta.marker) || 'black',
                   width: 1.5, dash: 'dash'}, layer: 'above'}]});
        return Object.assign({}, fig, {layout: layout});
    }
    """,
    Output(spot_fig_id("daily"), "figure", allow_duplicate=True),
    Input("day-picker", "date"),
    State(spot_fig_id("daily"), "figure"),
    prevent_initial_call=True,
)
