"""Callbacks of the page frame: labels in the chosen language, theme, upload, and the
grids (producers, members; restore the estimated keys)."""

from __future__ import annotations

import base64

import dash
from dash import Input, Output, State, callback, clientside_callback, html, no_update

import config
import jobs
import store
from edc_data import load_report
from figures import heat_metrics
from i18n import t, tn

from . import members
from .layout import job_ids, upload_content

#: (component id, property, i18n key): labels that depend on the language only
LABELS = [
    ("info-title", "children", "info_title"),
    ("table-title", "children", "table_title"),
    ("head-a", "children", "col_edc"),
    ("cmp-title", "children", "cmp_title"),
    ("settle-title", "children", "bill_table_title"),
    ("lbl-right-view", "children", "right_view"),
    ("theme-btn", "title", "theme_toggle"),
    # panel
    ("lbl-source-hint", "children", "panel_source_hint"),
    ("lbl-dest", "children", "panel_dest"),
    ("lbl-dest-hint", "children", "panel_dest_hint"),
    ("lbl-keys-hint", "children", "keys_hint"),
    ("btn-clear-keys", "children", "clear_keys"),
    ("lbl-day", "children", "sel_day"),
    ("lbl-day-hint", "children", "sel_day_hint"),
    ("btn-prev-day", "title", "prev_day"),
    ("btn-next-day", "title", "next_day"),
    ("lbl-display", "children", "panel_display"),
    ("lbl-heat-metric", "children", "heat_metric"),
    ("lbl-group", "children", "panel_group"),
    ("group", "placeholder", "panel_group_ph"),
    # computation cards
    ("exact-title", "children", "recompute_title"),
    ("exact-desc", "children", "recompute_desc"),
    ("exact-article", "children", "recompute_article"),
    ("exact-btn", "children", "recompute_btn"),
    ("lbl-reserve", "children", "reserve"),
    ("bill-title", "children", "bill_title"),
    ("bill-desc", "children", "bill_desc"),
    ("bill-btn", "children", "bill_btn"),
    ("lbl-feed-in", "children", "feed_in"),
    ("lbl-price-default", "children", "price_default"),
]


@callback([Output(i, p) for i, p, _ in LABELS], Input("lang", "value"))
def _labels(lang):
    return [t(key, lang) for _, _, key in LABELS]


@callback(
    output=dict(
        upload=Output("upload", "children"),
        day_format=Output("day-picker", "display_format"),
        heat_options=Output("heat-metric", "options"),
        heat_value=Output("heat-metric", "value"),
        heat_box=Output("heat-box", "style"),
        columns=Output("members", "columnDefs"),
        source_title=Output("lbl-source", "children"),
        producer_columns=Output("producers", "columnDefs"),
        exact_title=Output("exact-btn", "title"),
        bill_title=Output("bill-btn", "title"),
    ),
    inputs=dict(lang=Input("lang", "value"), key=Input("data-key", "data")),
    state=dict(heat=State("heat-metric", "value")),
)
def _report_labels(lang, key, heat):
    """Labels that also depend on the uploaded report."""
    entry = store.get(key)
    data = entry.data if entry else None
    metrics = heat_metrics(data) if data else ("production", "consumption")
    part = data is not None and data.fmt != "all"
    multi = data is not None and len(data.source_eans) > 1
    return dict(
        upload=upload_content(lang, entry is not None),
        day_format="DD.MM.YYYY" if lang == "cs" else "YYYY-MM-DD",
        heat_options=[{"label": t(f"heat_{m}", lang), "value": m} for m in metrics],
        heat_value=heat if heat in metrics else metrics[0],
        heat_box={"display": "none"} if len(metrics) < 2 else {},   # part report: no choice
        columns=members.columns(lang, editable=not part),
        source_title=tn("panel_source", lang, len(data.source_eans) if data else 1),
        producer_columns=members.producer_columns(lang),
        exact_title=(t("part_no_recompute", lang) if part
                     else t("multi_no_recompute", lang) if multi else ""),
        bill_title=t("part_no_bill", lang) if part else "",
    )


# Theme: default from the system, the icon toggles and remembers the choice.
clientside_callback(
    """
    function(n, pref) {
        const dc = window.dash_clientside;
        const trig = (dc.callback_context.triggered || [])[0];
        const clicked = !!trig && trig.prop_id === 'theme-btn.n_clicks' && n > 0;
        const sys = (window.matchMedia &&
                     window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
        let cur = document.documentElement.dataset.theme || pref || sys;
        if (clicked) { cur = (cur === 'dark') ? 'light' : 'dark'; }
        document.documentElement.dataset.theme = cur;
        document.documentElement.setAttribute('data-ag-theme-mode', cur);   // AG Grid
        return [cur, clicked ? cur : dc.no_update, cur === 'dark' ? '☀' : '☾'];
    }
    """,
    Output("theme", "data"),
    Output("theme-pref", "data"),
    Output("theme-btn", "children"),
    Input("theme-btn", "n_clicks"),
    State("theme-pref", "data"),
)


# ---------------------------------------------------------------------------
# Upload -> parse -> fill the panel, estimate the keys
# ---------------------------------------------------------------------------

_EXACT, _BILL = job_ids("exact"), job_ids("bill")


UPLOAD_OUTPUTS = dict(
    key=Output("data-key", "data"),
    status=Output("upload-status", "children"),
    sources=Output("producers", "rowData"),
    report=Output("report", "className"),
    box=Output("upload", "className"),
    first=Output("day-picker", "min_date_allowed"),
    last=Output("day-picker", "max_date_allowed"),
    day=Output("day-picker", "date"),
    month=Output("day-picker", "initial_visible_month"),
    rows=Output("members", "rowData"),
    selected=Output("members", "selectedRows", allow_duplicate=True),
    grid=Output("members", "dashGridOptions"),
    grid_style=Output("members", "style"),
    # the key estimate runs in the recompute card's job; the billing card resets
    fit_job=Output(_EXACT["job"], "data", allow_duplicate=True),
    fit_poll_off=Output(_EXACT["poll"], "disabled", allow_duplicate=True),
    bill_job=Output(_BILL["job"], "data", allow_duplicate=True),
    bill_poll_off=Output(_BILL["poll"], "disabled", allow_duplicate=True),
    bill_progress=Output(_BILL["progress"], "className", allow_duplicate=True),
)


@callback(
    output=UPLOAD_OUTPUTS,
    inputs=dict(contents=Input("upload", "contents")),
    state=dict(filename=State("upload", "filename"), lang=State("lang", "value"),
               old_key=State("data-key", "data")),
    prevent_initial_call=True,
)
def _on_upload(contents, filename, lang, old_key):
    if not contents:
        raise dash.exceptions.PreventUpdate
    store.drop(old_key)            # this browser replaces its report: free it, stop its jobs
    out = dict.fromkeys(UPLOAD_OUTPUTS, no_update)
    out.update(fit_poll_off=True, bill_job=None, bill_poll_off=True, bill_progress="progress idle")
    try:
        _header, b64 = contents.split(",", 1)
        if len(b64) * 3 / 4 > config.MAX_UPLOAD_MB * 2**20:
            raise ValueError(f"file is larger than {config.MAX_UPLOAD_MB:g} MB")
        data = load_report(base64.b64decode(b64))
    except Exception as exc:  # show any parse error to the user
        return {**out, "key": None, "sources": [], "report": "report hidden",
                "box": "upload upload-big",
                "status": html.Div([html.B(f"{t('error', lang)}: "), f"{filename} — {exc}"],
                                   className="status-error")}
    key = store.put(filename or "report.csv", data)
    days = data.frame.index.normalize()
    first, last = days.min().date().isoformat(), days.max().date().isoformat()
    many = len(data.dest_eans) > 12
    out.update(
        key=key, sources=members.producer_rows(data),
        report="report", box="upload upload-small",
        first=first, last=last, day=last, month=last,
        rows=members.rows(data), selected={"ids": list(data.dest_eans)},
        grid=members.options(many), grid_style={"height": "440px" if many else None},
    )
    if data.fmt == "all" and len(data.source_eans) == 1:
        # estimate the keys right away, to check them before a recompute
        out.update(fit_job=jobs.start_fit(key), fit_poll_off=False)
    return out


@callback(
    Output("members", "rowTransaction"),
    Input("btn-clear-keys", "n_clicks"),
    State("members", "rowData"),
    State("data-key", "data"),
    prevent_initial_call=True,
)
def _reset_keys(n, rows, key):
    """Put the estimated keys back (after manual edits)."""
    entry = store.get(key)
    if not n or entry is None or entry.fit is None:
        raise dash.exceptions.PreventUpdate
    by_ean = dict(zip(entry.data.dest_eans, entry.fit.keys))
    return {"update": [dict(r, key=members.pct_key(by_ean[r["ean"]])) for r in rows or []
                       if r.get("ean") in by_ean]}
