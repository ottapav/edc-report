"""Callbacks of the two computation cards (exact static method, billing): start a job,
draw its progress bar, show the results and whether the inputs changed since.

Only the poll callback writes the progress bar, its text and the button state while a
job runs: with a second writer a large response applied late could overwrite the poll's
"done" and leave the bar stuck at 0 %.
"""

from __future__ import annotations

import time

import dash
from dash import ALL, Input, Output, State, callback, no_update

import jobs
import store
from edc_data import SharingData
from figures import top_dests
from i18n import fmt_duration, fmt_num, fmt_pct, t

from . import members, views
from .layout import JOB_KINDS, job_ids

_EXACT, _BILL = job_ids("exact"), job_ids("bill")
_PHASES = {"fit": "phase_fit", "compute": "phase_compute", "bill": "phase_bill"}


def _start_outputs(kind: str) -> dict:
    ids = job_ids(kind)
    return dict(job=Output(ids["job"], "data"), poll_off=Output(ids["poll"], "disabled"),
                busy=Output(ids["btn"], "disabled"), cls=Output(ids["progress"], "className"),
                bar=Output(ids["bar"], "style"), text=Output(ids["text"], "children"))


def _refused(reason: str, lang: str) -> dict:
    return dict(job=no_update, poll_off=True, busy=False, cls="progress error",
                bar={"width": "0%"}, text=t(reason, lang))


def _started(job_id: str) -> dict:
    return dict(job=job_id, poll_off=False, busy=True, cls=no_update, bar=no_update,
                text=no_update)                       # the poll draws the bar


def _usable(entry, lang: str, part_reason: str) -> dict | None:
    """Why a computation cannot start, as the card's outputs; None if it can."""
    if entry is None:                    # server restarted / went to sleep since the upload
        return _refused("session_lost", lang)
    if entry.data.fmt != "all":
        return _refused(part_reason, lang)
    return None


def bill_inputs(data: SharingData, rows, feed_in, default):
    """(prices, feed-in price) for the billing, or (None, i18n key of what is missing)."""
    f = members.number(feed_in)
    if f is None or f < 0:
        return None, "bill_need_feed_in"
    prices = members.prices(data, rows, default)
    if any(p is None for p in prices):
        return None, "bill_need_prices"
    return (prices, f), None


@callback(
    output=_start_outputs("exact"),
    inputs=dict(n=Input(_EXACT["btn"], "n_clicks")),
    state=dict(key=State("data-key", "data"), rows=State("members", "rowData"),
               reserve=State("reserve", "value"), lang=State("lang", "value")),
    prevent_initial_call=True,
)
def start_exact(n, key, rows, reserve, lang):
    if not n:
        raise dash.exceptions.PreventUpdate
    entry = store.get(key)
    refused = _usable(entry, lang, "part_no_recompute")
    if refused:
        return refused
    return _started(jobs.start_exact(key, members.keys(entry.data, rows),
                                     members.reserve(reserve)))


@callback(
    output=_start_outputs("bill"),
    inputs=dict(n=Input(_BILL["btn"], "n_clicks")),
    state=dict(key=State("data-key", "data"), rows=State("members", "rowData"),
               feed_in=State("feed-in", "value"), default=State("price-default", "value"),
               lang=State("lang", "value")),
    prevent_initial_call=True,
)
def start_bill(n, key, rows, feed_in, default, lang):
    if not n:
        raise dash.exceptions.PreventUpdate
    entry = store.get(key)
    refused = _usable(entry, lang, "part_no_bill")
    if refused:
        return refused
    inputs, missing = bill_inputs(entry.data, rows, feed_in, default)
    if missing:
        return _refused(missing, lang)
    return _started(jobs.start_bill(key, *inputs))


# ---------------------------------------------------------------------------
# Progress (one poll callback per card)
# ---------------------------------------------------------------------------


def poll_state(job_id: str | None, rev: int | None, lang: str) -> tuple:
    """(poll disabled, button disabled, bar class, bar style, text, new revision)."""
    nu = no_update
    job = jobs.get(job_id)
    if job is None:
        # The job is not in this process: the server restarted / went to sleep, or
        # (misconfigured) another worker answered. Never leave the button dead.
        if not job_id:
            return True, False, nu, nu, nu, nu
        return True, False, "progress error", {"width": "0%"}, t("job_lost", lang), nu
    job.seen = time.perf_counter()                       # the page is alive
    if job.final is not None:
        # Idempotent: the interval may fire again before the first "done" response
        # arrives, and Dash then drops that first response as outdated - so every
        # later poll repeats the complete final state instead of no_update.
        return job.final
    elapsed = time.perf_counter() - job.t0
    if not job.done:
        if job.phase == "queued":
            return False, True, "progress running", {"width": "0%"}, f"{t('queued', lang)}…", nu
        frac = job.fraction
        count = ""
        entry = store.get(job.data_key)
        if job.phase == "compute" and entry is not None:
            n = entry.data.n_rows
            count = f" · {fmt_num(job.frac * n, lang)} / {fmt_num(n, lang)}"
        text = (f"{t(_PHASES.get(job.phase, 'phase_compute'), lang)}… "
                f"{fmt_pct(100 * frac, lang, 0)}{count} · {fmt_duration(elapsed, lang)}")
        return False, True, "progress running", {"width": f"{100 * frac:.1f}%"}, text, nu
    job.reported = True
    if job.error_key or job.error:
        msg = (t(job.error_key, lang) if job.error_key
               else f"{t('phase_error', lang)}: {job.error}")
        job.final = (True, False, "progress error", {"width": "100%"}, msg, nu)
    else:
        job.final = (True, False, "progress done", {"width": "100%"},
                     f"✓ {fmt_duration(elapsed, lang)}", (rev or 0) + 1)
    return job.final


for _kind in JOB_KINDS:
    _ids = job_ids(_kind)
    callback(
        Output(_ids["poll"], "disabled", allow_duplicate=True),
        Output(_ids["btn"], "disabled", allow_duplicate=True),
        Output(_ids["progress"], "className", allow_duplicate=True),
        Output(_ids["bar"], "style", allow_duplicate=True),
        Output(_ids["text"], "children", allow_duplicate=True),
        Output(_ids["rev"], "data"),
        Input(_ids["poll"], "n_intervals"),
        State(_ids["job"], "data"),
        State(_ids["rev"], "data"),
        State("lang", "value"),
        prevent_initial_call=True,
    )(lambda _n, job_id, rev, lang: poll_state(job_id, rev, lang))


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

_NAMES = dict(name_values=Input({"type": "name", "ean": ALL}, "value"))
_NAME_STATE = dict(name_ids=State({"type": "name", "ean": ALL}, "id"),
                   rows=State("members", "rowData"))


@callback(
    Output("fit-info", "children"),
    Output("members", "rowTransaction", allow_duplicate=True),
    Input(_EXACT["rev"], "data"),
    Input("lang", "value"),
    Input("data-key", "data"),
    State("members", "rowData"),
    prevent_initial_call="initial_duplicate",
)
def fit_info(_rev, lang, key, rows):
    """Summary of the key estimate; per member the estimate, its range and a warning."""
    entry = store.get(key)
    if entry is None or entry.fit is None or not rows:
        return [], no_update
    notes, update = views.fit_summary(entry.fit, entry.data, rows, lang)
    return notes, {"update": update}


@callback(
    Output("exact-stale", "children"),
    Input("members", "cellValueChanged"),
    Input("members", "rowData"),
    Input("reserve", "value"),
    Input(_EXACT["rev"], "data"),
    Input("lang", "value"),
    State("data-key", "data"),
)
def exact_stale(_changed, rows, reserve, _rev, lang, key):
    """"Keys changed since the last recompute" - a tiny callback, so typing a key does
    not re-render any figure."""
    entry = store.get(key)
    if entry is None or entry.exact is None:
        return []
    exact = entry.exact
    current = members.keys(entry.data, rows)
    changed = (any(k is not None and abs(k - u) > 1e-6 for k, u in zip(current, exact.keys))
               or abs(members.reserve(reserve) - exact.reserve) > 1e-9)
    return views.hint(t("stale", lang), "stale") if changed else []


@callback(
    output=Output("exact-result", "children"),
    inputs=dict(rev=Input(_EXACT["rev"], "data"), key=Input("data-key", "data"),
                lang=Input("lang", "value"), selected=Input("members", "selectedRows"),
                changed=Input("members", "cellValueChanged"), **_NAMES),
    state=_NAME_STATE,
)
def exact_result(rev, key, lang, selected, changed, name_values, name_ids, rows):
    """Sharing error of the EDC report (for the ticked members), timing, keys used."""
    if members.key_only_edit():
        raise dash.exceptions.PreventUpdate
    entry = store.get(key)
    if entry is None or entry.exact is None:
        return []
    data = entry.data
    return views.exact_result(entry.exact, data, members.enabled(data, selected),
                              members.names(data, lang, name_ids, name_values, rows), lang)


@callback(
    output=dict(result=Output("bill-result", "children"), stale=Output("bill-stale", "children"),
                table=Output("settle-table", "children")),
    inputs=dict(rev=Input(_BILL["rev"], "data"), key=Input("data-key", "data"),
                lang=Input("lang", "value"), changed=Input("members", "cellValueChanged"),
                selected=Input("members", "selectedRows"), feed_in=Input("feed-in", "value"),
                default=Input("price-default", "value"), **_NAMES),
    state=_NAME_STATE,
)
def bill_result(rev, key, lang, changed, selected, feed_in, default, name_values, name_ids,
                rows):
    """Summary of the last billing in its card, the settlement table below the columns,
    and a note when the prices have changed since."""
    entry = store.get(key)
    if entry is None or entry.bill is None:
        return dict(result=[], stale=[], table=[])
    data, result = entry.data, entry.bill
    names = members.names(data, lang, name_ids, name_values, rows)
    table = views.bill_table(result.settlement, data, names, lang, top_dests(data.frame, data),
                             members.enabled(data, selected))
    inputs, _missing = bill_inputs(data, rows, feed_in, default)
    totals = result.totals
    changed = (inputs is None or abs(inputs[1] - totals.feed_in) > 1e-9
               or any(abs(a - b) > 1e-9 for a, b in zip(inputs[0], totals.prices)))
    return dict(result=views.bill_result(result, lang), table=[table],
                stale=views.hint(t("bill_stale", lang), "stale") if changed else [])
