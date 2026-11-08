"""Callbacks of the spot tab: switch the tabs, fetch the OTE prices (when the tab opens
and they are not there yet: a failed download is tried again the next time), and draw
the comparison. The comparison takes a few milliseconds, so it follows every price, fee
or selection typed, with no button. The card's only button starts the billing by
contribution; it is enabled only when who gets what needs it."""

from __future__ import annotations

import dash
import numpy as np
from dash import Input, Output, State, callback, clientside_callback, ctx, no_update

import jobs
import store
from figures import (
    fig_spot_daily, fig_spot_intraday, fig_spot_members, fig_spot_mix, fig_spot_monthly,
    fig_spot_parties, theme, top_dests,
)
from i18n import t
from spot import compare, mix, replays, split

from . import members, views
from .compute import refused, start_job, start_outputs
from .layout import SPOT_FIGURES, job_ids, spot_fig_id

_SPOT = job_ids("spot")
_EXACT = job_ids("exact")
_BILL = job_ids("bill")
HIDDEN = {"display": "none"}


# Tabs: only the panes' visibility changes, in the browser; nothing is unmounted, so
# the callbacks of the hidden tab keep their components. The columns (EDC report vs the
# exact method) and the heat map's choice in the panel belong to the sharing tab.
clientside_callback(
    """
    function(tab) {
        const show = {}, hide = {display: 'none'};
        const on = name => tab === name ? show : hide;
        return [on('sharing'), on('bill'), on('sharing'), on('spot'), on('sharing')];
    }
    """,
    Output("pane-sharing", "style"),
    Output("pane-bill", "style"),
    Output("pane-columns", "style"),
    Output("pane-spot", "style"),
    Output("panel-display", "style"),
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
    output=start_outputs("spot"),
    inputs=dict(tab=Input("tabs", "value"), key=Input("data-key", "data")),
    state=dict(job_id=State(_SPOT["job"], "data"), lang=State("lang", "value")),
    prevent_initial_call=True,
)
def start_spot(tab, key, job_id, lang):
    """Opening the tab fetches the prices if they are not there (again after a failure)."""
    if tab != "spot":
        raise dash.exceptions.PreventUpdate
    entry = store.get(key)
    if entry is None:
        raise dash.exceptions.PreventUpdate
    if entry.data.fmt != "all":
        return refused("part_no_spot", lang)
    if _running(job_id, key) or entry.spot is not None:
        raise dash.exceptions.PreventUpdate
    return start_job(jobs.start_spot, lang, key)


#: what the comparison depends on (the prices and the fee typed, the selection, …)
_INPUTS = dict(
    key=Input("data-key", "data"), rev=Input(_SPOT["rev"], "data"), tab=Input("tabs", "value"),
    selected=Input("members", "selectedRows"), changed=Input("members", "cellValueChanged"),
    src_changed=Input("producers", "cellValueChanged"), feed_in=Input("feed-in", "value"),
    default=Input("price-default", "value"), fee=Input("spot-fee", "value"),
    curtail=Input("spot-curtail", "value"), lang=Input("lang", "value"),
    theme_name=Input("theme", "data"),
)
#: and what the part on spot and who gets what depend on besides: the keys (estimated,
#: typed) and the billing by contribution
_KEY_INPUTS = dict(fit_rev=Input(_EXACT["rev"], "data"),
                   pair_changed=Input("pair-keys", "cellValueChanged"),
                   bill_rev=Input(_BILL["rev"], "data"))
_STATE = dict(rows=State("members", "rowData"), src_rows=State("producers", "rowData"))


def comparison(entry, rows, src_rows, feed_in, default, fee, curtail):
    """The comparison for what is typed in the panel and the two cards."""
    data = entry.data
    return compare(data, entry.spot, members.prices(data, rows, default),
                   members.feed_ins(data, src_rows, feed_in), members.number(fee) or 0.0,
                   "on" in (curtail or []))


def part_on_spot(entry, cmp, rows, pair_rows, lang):
    """(the levels valued, None) or (None, why there is no curve): the part offered is
    shared by today's EDC method with the keys of the panel (empty cells: the estimate)."""
    data, fit = entry.data, entry.fit
    if not cmp.priced:
        return None, None
    if len(data.source_eans) > 1:
        typed = members.pair_keys(data, pair_rows)
        problem = members.pair_problem(typed, fit)
        merged = members.merged_pair_keys(typed, fit)
        args = (None, tuple(tuple(r) for r in merged))
        missing = any(k is None for r in merged for k in r)
    else:
        typed = members.keys(data, rows)
        problem = members.key_problem(typed, fit)
        merged = members.merged_keys(typed, fit)
        args = (tuple(merged), None)
        missing = any(k is None for k in merged)
    if problem:
        return None, t(problem, lang)
    if missing:
        return None, t("spot_mix_wait", lang)
    rep = replays(data, entry.spot, args[0], fit.rounds if fit else 5, args[1])
    return mix(cmp, rep), None


_OUTPUTS = dict(
    body=Output("spot-body", "style"), info=Output("spot-info", "children"),
    verdict=Output("spot-verdict", "children"),
    bill_need=Output("spot-bill-need", "data"), bill_title=Output("spot-bill-btn", "title"),
    tiles=Output("spot-tiles", "children"), table=Output("spot-table", "children"),
    **{name: Output(spot_fig_id(name), "figure") for name in SPOT_FIGURES if name != "hourly"},
    **{f"{name}_h": Output(spot_fig_id(name), "style")
       for name in SPOT_FIGURES if name != "hourly"},
)


@callback(output=_OUTPUTS, inputs=dict(**_INPUTS, **_KEY_INPUTS),
          state=dict(**_STATE, pair_rows=State("pair-keys", "rowData"),
                     sel_day=State("day-picker", "date")))
def render_spot(key, rev, tab, selected, changed, src_changed, feed_in, default, fee, curtail,
                lang, theme_name, fit_rev, pair_changed, bill_rev, rows, src_rows, pair_rows,
                sel_day):
    """Tiles, figures and the table of the spot tab (only while it is open)."""
    if tab != "spot":
        raise dash.exceptions.PreventUpdate
    entry = store.get(key)
    empty = {k: no_update for k in _OUTPUTS}
    if entry is None or entry.spot is None or entry.data.fmt != "all":
        return {**empty, "body": HIDDEN, "info": [], "bill_need": False, "bill_title": ""}
    data = entry.data
    cmp = comparison(entry, rows, src_rows, feed_in, default, fee, curtail)
    m, why = part_on_spot(entry, cmp, rows, pair_rows, lang)
    # who gets what: the billing by contribution for these prices
    sp = split(cmp, entry.bill)
    billed = entry.bill is not None
    need = None if sp is not None or not cmp.priced else views.need_bill(billed, lang)
    # the billing's button: on only when the billing is missing or stale and can run
    feed_ok = not np.isnan(cmp.feed_ins).any()
    bill_title = (t("spot_need_prices_short", lang) if not cmp.priced
                  else t("bill_need_feed_in", lang) if need is not None and not feed_ok
                  else need or t("spot_bill_current", lang))
    enabled = members.enabled(data, selected)
    names = members.names(data, lang, src_rows, rows)
    th = theme(theme_name)
    top = top_dests(data.frame, data)
    figs = dict(
        parties=fig_spot_parties(cmp, sp, lang, th, note=need),
        mix=fig_spot_mix(m, lang, th, note=why),
        members=fig_spot_members(cmp, sp, data, names, enabled, lang=lang, th=th, top=top,
                                 note=need),
        daily=fig_spot_daily(cmp, sp, lang=lang,
                             sel_day=str(sel_day)[:10] if sel_day else None, th=th),
        monthly=fig_spot_monthly(cmp, lang=lang, th=th),
    )
    out = dict(body={}, info=views.spot_info(entry.spot, data, lang),
               verdict=views.spot_verdict(cmp, m, sp, lang, why, billed),
               bill_need=need is not None and feed_ok, bill_title=bill_title,
               tiles=views.spot_tiles(cmp, sp, lang, billed),
               table=views.spot_table(cmp, sp, data, names, lang, top, enabled, billed), **figs)
    for name, fig in figs.items():
        out[f"{name}_h"] = {"height": f"{fig.layout.height}px"}
    return out


@callback(Output(spot_fig_id("hourly"), "figure"), Output(spot_fig_id("hourly"), "style"),
          inputs=dict(day=Input("day-picker", "date"), **_INPUTS), state=dict(_STATE))
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


# The billing's button in the spot card: enabled when who gets what needs the billing
# (missing, or computed with other prices) and it is not running. It never hides, so
# typing a price does not move the card.
clientside_callback(
    """
    function(need, busy) { return !need || !!busy; }
    """,
    Output("spot-bill-btn", "disabled"),
    Input("spot-bill-need", "data"),
    Input(_BILL["btn"], "disabled"),
)


# The billing's progress, shown in the spot card too (its button there starts it).
clientside_callback(
    """
    function(cls, style, text) { return [cls, style, text]; }
    """,
    Output("spot-bill-progress", "className"),
    Output("spot-bill-bar", "style"),
    Output("spot-bill-text", "children"),
    Input(_BILL["progress"], "className"),
    Input(_BILL["bar"], "style"),
    Input(_BILL["text"], "children"),
)


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
