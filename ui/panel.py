"""Callbacks of the page frame: labels in the chosen language, theme, upload, and the
grids (producers, members; restore the estimated keys)."""

from __future__ import annotations

import base64

import dash
from dash import Input, Output, State, callback, clientside_callback, html, no_update

import config
import jobs
import store
from figures import heat_metrics
import clanky
from i18n import date_picker_format, t, tn

from . import members
from .layout import job_ids, upload_content

#: (component id, property, i18n key): labels that depend on the language only
LABELS = [
    ("info-title", "children", "info_title"),
    ("table-title", "children", "table_title"),
    ("cmp-title", "children", "cmp_title"),
    ("settle-title", "children", "bill_table_title"),
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
    ("lbl-export", "children", "x_title"),
    ("btn-export", "children", "x_btn"),
    ("btn-print", "children", "x_print"),
    ("lbl-export-hint", "children", "x_hint"),
    # computation cards
    ("exact-title", "children", "recompute_title"),
    ("exact-desc", "children", "recompute_desc"),
    ("exact-article", "children", "recompute_article"),
    ("exact-btn", "children", "recompute_btn"),
    ("lbl-reserve", "children", "reserve"),
    ("bill-title", "children", "bill_title"),
    ("bill-desc", "children", "bill_desc"),
    ("bill-article", "children", "bill_article"),
    ("bill-btn", "children", "bill_btn"),
    ("lbl-feed-in", "children", "feed_in"),
    ("lbl-price-default", "children", "price_default"),
    ("pair-title", "children", "pair_title"),
    ("pair-hint", "children", "pair_hint"),
    # tabs, spot tab
    ("tab-sharing", "label", "tab_sharing"),
    ("tab-bill", "label", "tab_bill"),
    ("tab-spot", "label", "tab_spot"),
    ("spot-title", "children", "spot_title"),
    ("spot-desc", "children", "spot_desc"),
    ("lbl-spot-fee", "children", "spot_fee"),
    ("lbl-spot-feed-in", "children", "spot_feed_in_lbl"),
    ("lbl-spot-price-default", "children", "price_default"),
    ("spot-table-title", "children", "spot_table_title"),
    ("spot-bill-btn", "children", "spot_bill_btn"),
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
        exact_pool=Output("exact-pool", "children"),
        article_href=Output("exact-article", "href"),
        bill_article_href=Output("bill-article", "href"),
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
        day_format=date_picker_format(lang),
        article_href=clanky.DO_POSLEDNI_KWH.url(lang),
        bill_article_href=clanky.SPRAVEDLIVA_CENA.url(lang),     # Czech only so far
        heat_options=[{"label": t(f"heat_{m}", lang), "value": m} for m in metrics],
        heat_value=heat if heat in metrics else metrics[0],
        heat_box={"display": "none"} if len(metrics) < 2 else {},   # part report: no choice
        columns=members.columns(lang, editable=not part, pool=multi and not part),
        source_title=tn("panel_source", lang, len(data.source_eans) if data else 1),
        producer_columns=members.producer_columns(lang),
        exact_title=t("part_no_recompute", lang) if part else "",
        # several producers: say up front that the key estimate and the recompute pool them
        exact_pool=(html.P(t("pool_note", lang).format(n=len(data.source_eans)),
                           className="hint pool-note") if multi and not part else []),
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

_EXACT, _BILL, _SPOT = job_ids("exact"), job_ids("bill"), job_ids("spot")


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
    pair_rows=Output("pair-keys", "rowData"),
    selected=Output("members", "selectedRows", allow_duplicate=True),
    grid=Output("members", "dashGridOptions"),
    grid_style=Output("members", "style"),
    # the key estimate runs in the recompute card's job; the billing card resets
    fit_job=Output(_EXACT["job"], "data", allow_duplicate=True),
    fit_poll_off=Output(_EXACT["poll"], "disabled", allow_duplicate=True),
    bill_job=Output(_BILL["job"], "data", allow_duplicate=True),
    bill_poll_off=Output(_BILL["poll"], "disabled", allow_duplicate=True),
    bill_progress=Output(_BILL["progress"], "className", allow_duplicate=True),
    # the spot prices belong to the old report's period (the open spot tab fetches anew)
    spot_job=Output(_SPOT["job"], "data", allow_duplicate=True),
    spot_poll_off=Output(_SPOT["poll"], "disabled", allow_duplicate=True),
    spot_progress=Output(_SPOT["progress"], "className", allow_duplicate=True),
    spot_busy=Output(_SPOT["btn"], "disabled", allow_duplicate=True),
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
    out.update(fit_poll_off=True, bill_job=None, bill_poll_off=True, bill_progress="progress idle",
               spot_job=None, spot_poll_off=True, spot_progress="progress idle", spot_busy=False)
    try:
        _header, b64 = contents.split(",", 1)
        if len(b64) * 3 / 4 > config.MAX_UPLOAD_MB * 2**20:
            raise ValueError(f"file is larger than {config.MAX_UPLOAD_MB:g} MB")
        # parsed in a child process with a memory budget, one upload at a time
        data = jobs.parse_report(base64.b64decode(b64))
    except Exception as exc:  # show any parse error to the user
        reason = (t("upload_too_big", lang) if isinstance(exc, jobs.TooBig)
                  else t("upload_busy", lang) if isinstance(exc, jobs.Busy) else exc)
        return {**out, "key": None, "sources": [], "report": "report hidden",
                "box": "upload upload-big",
                "status": html.Div([html.B(f"{t('error', lang)}: "), f"{filename} — {reason}"],
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
        pair_rows=(members.pair_rows(data, members.default_names(data, lang))
                   if len(data.source_eans) > 1 else []),
        grid=members.options(many), grid_style={"height": "440px" if many else None},
    )
    if data.fmt == "all":
        # estimate the keys right away, to check them before a recompute (several
        # producers: for their pool, see recompute.to_hundredths)
        try:
            out.update(fit_job=jobs.start_fit(key), fit_poll_off=False)
        except jobs.Busy:            # the recompute estimates the keys itself when started
            out.update(fit_job=None)
    return out


@callback(
    Output("members", "rowTransaction"),
    Output("pair-keys", "rowTransaction"),
    Input("btn-clear-keys", "n_clicks"),
    State("members", "rowData"),
    State("pair-keys", "rowData"),
    State("data-key", "data"),
    prevent_initial_call=True,
)
def _reset_keys(n, rows, pair_rows, key):
    """Put the estimated keys back (after manual edits), the pair keys too."""
    entry = store.get(key)
    if not n or entry is None or entry.fit is None:
        raise dash.exceptions.PreventUpdate
    by_ean = dict(zip(entry.data.dest_eans, entry.fit.keys))
    keys = {"update": [dict(r, key=members.pct_key(by_ean[r["ean"]])) for r in rows or []
                       if r.get("ean") in by_ean]}
    return keys, pair_update(entry.data, entry.fit, pair_rows, overwrite=True)


def pair_update(data, fit, pair_rows, overwrite: bool = False):
    """Row updates of the pair-keys grid with the estimated pair keys: into the empty
    cells, or into all of them (``overwrite``, the Odhad button)."""
    est = getattr(fit, "pair_keys", None)
    if not est or not pair_rows:
        return no_update
    col = {e: j for j, e in enumerate(data.dest_eans)}
    update = []
    for r in pair_rows:
        j = col.get(r.get("ean"))
        if j is None:
            continue
        new = dict(r)
        for i in range(len(data.source_eans)):
            f = members.pair_field(i)
            if overwrite or members.number(r.get(f)) is None:
                new[f] = members.pct_key(est[i][j])
        update.append(new)
    return {"update": update}


@callback(
    Output("pair-keys", "columnDefs"),
    Output("pair-box", "style"),
    Output("pair-keys", "rowTransaction", allow_duplicate=True),
    Input("lang", "value"),
    Input("data-key", "data"),
    Input("producers", "cellValueChanged"),
    Input("members", "cellValueChanged"),
    State("producers", "rowData"),
    State("members", "rowData"),
    State("pair-keys", "rowData"),
    prevent_initial_call="initial_duplicate",
)
def _pair_grid(lang, key, _src_changed, _changed, src_rows, rows, pair_rows):
    """The pair-keys grid of a report with several producers: a column per producer
    named like in the producers' grid, the members named like in theirs."""
    entry = store.get(key)
    data = entry.data if entry else None
    if data is None or data.fmt != "all" or len(data.source_eans) < 2:
        return [], {"display": "none"}, no_update
    names = members.names(data, lang, src_rows, rows)
    rename = [dict(r, name=names.get(r.get("ean"), r.get("name"))) for r in pair_rows or []
              if r.get("name") != names.get(r.get("ean"), r.get("name"))]
    return (members.pair_columns(data, lang, names), {},
            {"update": rename} if rename else no_update)
