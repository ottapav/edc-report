"""SharEl sharing report - Dash web app.

Phase 1: upload a SharEl CSV export and see general information and statistics,
the "total by flow" overview and daily plot from Figure 1 of
``plot_energy_sharing.py``, and the shared / wasted pie from Figure 2, with a
selection panel (destinations on/off, names, display options).

Phase 2: a button recomputes sharing with the exact static method
(``presna_staticka.rozdel``) and shows the recomputed report side by side with
today's EDC report, with a progress bar and timing of the computation.

Run:  python app.py            (http://127.0.0.1:8050)
      python app.py --host 0.0.0.0 --port 8050 --debug
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hmac
import os
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from string import ascii_uppercase

import numpy as np
import dash
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update
from flask import Response, request

from figures import (
    colour_map, fig_daily, fig_heatmap, fig_intraday, fig_total_by_flow,
    fig_wasted_pie, heat_pivot, intraday_ymax,
)
from i18n import fmt_date, fmt_duration, fmt_num, fmt_pct, fmt_signed, t
from recompute import Recomputed, recompute
from sharel_core import (
    SharingData, compute_wasted_split, filter_dests, load_report,
    per_destination, summarize,
)

# ---------------------------------------------------------------------------
# Configuration (environment variables; see README "Deploy on Render")
# ---------------------------------------------------------------------------

#: parsed reports kept in memory (~20-25 MB each incl. a recompute; 512 MB instances -> 6)
CACHE_MAX = int(os.environ.get("SHAREL_CACHE_MAX", "6"))
#: largest accepted CSV in MB
MAX_UPLOAD_MB = float(os.environ.get("SHAREL_MAX_UPLOAD_MB", "25"))
#: optional HTTP basic auth for the whole app (both must be set)
AUTH_USER = os.environ.get("BASIC_AUTH_USER", "")
AUTH_PASSWORD = os.environ.get("BASIC_AUTH_PASSWORD", "")

# ---------------------------------------------------------------------------
# In-memory store of parsed uploads (keyed by a random id held in the browser)
# and of recompute jobs. Single-process only: with gunicorn use one worker, or
# swap these for a shared cache (e.g. flask-caching with Redis).
# ---------------------------------------------------------------------------


@dataclass
class Entry:
    filename: str
    data: SharingData
    exact: Recomputed | None = None


_CACHE: "OrderedDict[str, Entry]" = OrderedDict()
_CACHE_MAX = max(1, CACHE_MAX)
_LOCK = threading.Lock()


def _cache_put(filename: str, data: SharingData) -> str:
    key = uuid.uuid4().hex
    with _LOCK:
        _CACHE[key] = Entry(filename, data)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return key


def _cache_get(key: str | None) -> Entry | None:
    if not key:
        return None
    with _LOCK:
        item = _CACHE.get(key)
        if item is not None:
            _CACHE.move_to_end(key)
        return item


_JOBS: dict[str, dict] = {}


def _run_job(job_id: str, data_key: str, keys: list[float | None], reserve: float) -> None:
    job = _JOBS[job_id]

    def progress(phase: str, frac: float) -> None:
        job["phase"], job["frac"] = phase, frac

    try:
        entry = _cache_get(data_key)
        if entry is None:
            raise RuntimeError("data no longer on the server")
        given = all(k is not None for k in keys)
        res = recompute(entry.data, keys if given else None, reserve, progress=progress)
        if not given:  # user-entered keys override the fitted ones
            merged = [k if k is not None else f for k, f in zip(keys, res.keys)]
            if merged != res.keys:
                fit, t_fit = res.fit, res.timing.t_fit
                res = recompute(entry.data, merged, reserve, progress=progress)
                res.fit, res.keys_estimated = fit, True
                res.timing.t_fit = t_fit
                res.timing.t_wall += t_fit
        entry.exact = res
        job["done"] = True
    except Exception as exc:  # reported in the UI
        traceback.print_exc()
        job["error"] = str(exc)
        job["done"] = True


# ---------------------------------------------------------------------------
# Names and keys
# ---------------------------------------------------------------------------


def default_names(data: SharingData, lang: str) -> dict[str, str]:
    """Generic labels: ``Výroba A`` / ``Spotřeba 1`` … in file order."""
    names: dict[str, str] = {}
    for i, e in enumerate(data.source_eans):
        names[e] = f"{t('source_a', lang)} {ascii_uppercase[i % 26]}"
    for i, e in enumerate(data.dest_eans, 1):
        names[e] = f"{t('destination', lang)} {i}"
    return names


def effective_names(data: SharingData, lang: str, ids: list[dict], values: list) -> dict[str, str]:
    names = default_names(data, lang)
    for id_, val in zip(ids or [], values or []):
        if val and str(val).strip() and id_["ean"] in names:
            names[id_["ean"]] = str(val).strip()
    return names


def _keys_from_inputs(data: SharingData, ids: list[dict], values: list) -> list[float | None]:
    """Key inputs (percent) -> fractions in destination order; None = estimate."""
    by_ean = {i["ean"]: v for i, v in zip(ids or [], values or [])}
    out: list[float | None] = []
    for e in data.dest_eans:
        v = by_ean.get(e)
        out.append(None if v in (None, "") else max(0.0, float(v)) / 100)
    return out


def _pct_key(x: float) -> float:
    return round(x * 100, 2)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

GRAPH_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "toImageButtonOptions": {"format": "png", "scale": 2},
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}


def _graph(id_: str, cls: str = "") -> html.Section:
    return html.Section(className=f"card {cls}".strip(),
                        children=dcc.Graph(id=id_, config=GRAPH_CONFIG))


app = dash.Dash(__name__, title="SharEl report", suppress_callback_exceptions=True)
server = app.server  # for gunicorn: gunicorn app:server --workers 1 --threads 8
# base64 upload inflates the file by 4/3; leave headroom for the rest of the request
server.config["MAX_CONTENT_LENGTH"] = int((MAX_UPLOAD_MB * 1.4 + 2) * 2**20)


@server.route("/healthz")
def _healthz():
    return {"status": "ok", "cached_reports": len(_CACHE)}


@server.before_request
def _basic_auth():
    """Optional HTTP basic auth, enabled when BASIC_AUTH_USER/PASSWORD are set."""
    if not (AUTH_USER and AUTH_PASSWORD) or request.path == "/healthz":
        return None
    auth = request.authorization
    if (auth and hmac.compare_digest(auth.username or "", AUTH_USER)
            and hmac.compare_digest(auth.password or "", AUTH_PASSWORD)):
        return None
    return Response("Authentication required", 401,
                    {"WWW-Authenticate": 'Basic realm="SharEl report"'})


app.layout = html.Div(className="page", children=[
    dcc.Store(id="data-key"),
    dcc.Store(id="job-id"),
    dcc.Store(id="result-rev", data=0),
    dcc.Interval(id="poll", interval=200, disabled=True),
    html.Header(className="topbar", children=[
        html.H1(id="page-title"),
        html.Div(className="lang", children=[
            dcc.RadioItems(
                id="lang", value="cs", inline=True, className="seg",
                options=[{"label": "CZ", "value": "cs"}, {"label": "EN", "value": "en"}],
            ),
        ]),
    ]),
    dcc.Upload(
        id="upload", multiple=False, accept=".csv,text/csv",
        className="upload upload-big",
        children=html.Div(id="upload-text"),
    ),
    html.Div(id="upload-status", className="status"),
    dcc.Loading(type="dot", color="#339933", target_components={"report": "className"},
                children=html.Div(id="report", className="report hidden", children=[
        html.Aside(className="panel", children=[
            html.Div(id="dest-panel"),
            html.Section(className="panel-section", children=[
                html.H3(id="lbl-day"),
                html.Div(className="day-row", children=[
                    html.Button("◀", id="btn-prev-day", n_clicks=0, className="mini day-btn"),
                    dcc.DatePickerSingle(id="day-picker", first_day_of_week=1,
                                         display_format="DD.MM.YYYY", clearable=False,
                                         className="day-picker"),
                    html.Button("▶", id="btn-next-day", n_clicks=0, className="mini day-btn"),
                ]),
                html.P(id="lbl-day-hint", className="hint"),
            ]),
            html.Section(className="panel-section", children=[
                html.H3(id="lbl-display"),
                html.Label(id="lbl-yscale", className="field-label"),
                dcc.RadioItems(id="yscale", value="linear", className="radios"),
                dcc.Checklist(id="grid-toggles", value=["unshared", "unmet"],
                              className="checks"),
                dcc.Checklist(id="show-heat", value=["on"], className="checks"),
                html.Label(id="lbl-heat-metric", className="field-label"),
                dcc.RadioItems(id="heat-metric", value="production", className="radios"),
            ]),
            html.Section(className="panel-section", children=[
                html.H3(id="lbl-group"),
                dcc.Input(id="group", type="text", debounce=True, className="text-in"),
            ]),
        ]),
        html.Main(className="main", children=[
            html.Section(className="card", children=[
                html.H2(id="info-title"),
                html.Div(id="info"),
                html.Div(id="notes"),
            ]),
            html.Section(className="card recompute-card", children=[
                html.H2(id="rc-title"),
                html.P(id="rc-desc", className="hint"),
                html.Div(className="rc-row", children=[
                    html.Button(id="btn-recompute", n_clicks=0, className="btn-primary"),
                    html.Label(className="reserve", children=[
                        html.Span(id="lbl-reserve"),
                        dcc.Input(id="reserve", type="number", min=0, max=100, step=0.1,
                                  value=0, debounce=True, className="num-in"),
                    ]),
                ]),
                html.Div(id="progress", className="progress idle", children=[
                    html.Div(className="progress-track", children=html.Div(
                        id="progress-bar", className="progress-bar", style={"width": "0%"})),
                    html.Div(id="progress-text", className="progress-text"),
                ]),
                html.Div(id="timing"),
            ]),
            html.Div(id="compare", className="compare single", children=[
                html.Div(className="col col-a", children=[
                    html.H2(id="head-a", className="col-head col-head-a"),
                    html.Section(className="card tiles-card", children=html.Div(id="tiles-a")),
                    _graph("fig-overview", "overview-card"),
                    html.Section(id="pie-card", className="card pie-card", children=dcc.Graph(
                        id="fig-pie", config=GRAPH_CONFIG)),
                    _graph("fig-daily", "daily-card"),
                    _graph("fig-hourly", "hourly-card"),
                    _graph("fig-heat", "heat-card"),
                    html.Section(className="card table-card", children=[
                        html.H2(id="table-title"),
                        html.Div(id="dest-table", className="table-wrap"),
                    ]),
                ]),
                html.Div(className="col col-b", children=[
                    html.H2(id="head-b", className="col-head col-head-b"),
                    html.Section(className="card tiles-card", children=html.Div(id="tiles-b")),
                    _graph("fig-overview-b", "overview-card"),
                    _graph("fig-pie-b", "pie-card"),
                    _graph("fig-daily-b", "daily-card"),
                    _graph("fig-hourly-b", "hourly-card"),
                    _graph("fig-heat-b", "heat-card"),
                ]),
            ]),
            html.Section(id="cmp-card", className="card cmp-card", children=[
                html.H2(id="cmp-title"),
                html.Div(id="cmp-table", className="table-wrap"),
            ]),
        ]),
    ])),
])


# ---------------------------------------------------------------------------
# Static labels (language)
# ---------------------------------------------------------------------------


@app.callback(
    Output("upload-text", "children"),
    Output("lbl-display", "children"),
    Output("lbl-yscale", "children"),
    Output("yscale", "options"),
    Output("grid-toggles", "options"),
    Output("lbl-group", "children"),
    Output("group", "placeholder"),
    Output("info-title", "children"),
    Output("table-title", "children"),
    Output("rc-title", "children"),
    Output("rc-desc", "children"),
    Output("btn-recompute", "children"),
    Output("lbl-reserve", "children"),
    Output("head-a", "children"),
    Output("head-b", "children"),
    Output("cmp-title", "children"),
    Output("lbl-day", "children"),
    Output("lbl-day-hint", "children"),
    Output("btn-prev-day", "title"),
    Output("btn-next-day", "title"),
    Output("day-picker", "display_format"),
    Output("show-heat", "options"),
    Output("lbl-heat-metric", "children"),
    Output("heat-metric", "options"),
    Input("lang", "value"),
    Input("data-key", "data"),
)
def _labels(lang, key):
    loaded = _cache_get(key) is not None
    upload_text = (
        html.Div([html.Span("⤒ "), t("upload_other", lang)], className="upload-small-text")
        if loaded else
        html.Div([
            html.Div("⤒", className="upload-icon"),
            html.Div(t("upload_prompt", lang), className="upload-main"),
            html.Div(t("upload_hint", lang), className="upload-hint"),
        ])
    )
    return (
        upload_text,
        t("panel_display", lang),
        t("yscale", lang),
        [{"label": t("linear", lang), "value": "linear"},
         {"label": t("log", lang), "value": "log"}],
        [{"label": t("show_unshared", lang), "value": "unshared"},
         {"label": t("show_unmet", lang), "value": "unmet"}],
        t("panel_group", lang),
        t("panel_group_ph", lang),
        t("info_title", lang),
        t("table_title", lang),
        t("recompute_title", lang),
        t("recompute_desc", lang),
        t("recompute_btn", lang),
        t("reserve", lang),
        t("col_edc", lang),
        t("col_exact", lang),
        t("cmp_title", lang),
        t("sel_day", lang),
        t("sel_day_hint", lang),
        t("prev_day", lang),
        t("next_day", lang),
        "DD.MM.YYYY" if lang == "cs" else "YYYY-MM-DD",
        [{"label": t("show_heatmap", lang), "value": "on"}],
        t("heat_metric", lang),
        [{"label": t(f"heat_{m}", lang), "value": m}
         for m in ("production", "shared", "unmet")],
    )


# ---------------------------------------------------------------------------
# Upload -> parse -> build the selection panel
# ---------------------------------------------------------------------------


def _dest_panel(data: SharingData, lang: str) -> html.Div:
    cmap = colour_map(data)
    names = default_names(data, lang)
    can_key = data.fmt == "all"
    src_rows = [
        html.Div(className="dest-row", children=[
            html.Span(className="swatch", style={"background": "#339933"}),
            html.Div(className="name-cell", children=[
                dcc.Input(id={"type": "name", "ean": e}, type="text", debounce=True,
                          placeholder=names[e], className="name-in"),
                html.Div(e, className="ean"),
            ]),
        ]) for e in data.source_eans
    ]
    dest_rows = [
        html.Div(className="dest-row", children=[
            dcc.Checklist(id={"type": "dest", "ean": e}, value=[e],
                          options=[{"label": "", "value": e}], className="dest-check"),
            html.Span(className="swatch", style={"background": cmap[e]}),
            html.Div(className="name-cell", children=[
                dcc.Input(id={"type": "name", "ean": e}, type="text", debounce=True,
                          placeholder=names[e], className="name-in"),
                html.Div(e, className="ean"),
            ]),
            dcc.Input(id={"type": "key", "ean": e}, type="number", min=0, max=100, step=0.01,
                      debounce=True, placeholder=t("key_ph", lang), className="key-in",
                      disabled=not can_key),
        ]) for e in data.dest_eans
    ]
    return html.Div([
        html.Section(className="panel-section", children=[
            html.H3(t("panel_source", lang), id="lbl-source"),
            *src_rows,
        ]),
        html.Section(className="panel-section", children=[
            html.Div(className="panel-head", children=[
                html.H3(t("panel_dest", lang), id="lbl-dest"),
                html.Div(className="mini-btns", children=[
                    html.Button(t("all", lang), id="btn-all", n_clicks=0, className="mini"),
                    html.Button(t("none", lang), id="btn-none", n_clicks=0, className="mini"),
                ]),
            ]),
            html.P(t("panel_dest_hint", lang), className="hint", id="lbl-dest-hint"),
            html.Div(className="dest-head", children=[
                html.Span(),
                html.Span(t("keys", lang), id="lbl-keys"),
            ]),
            *dest_rows,
            html.Div(className="keys-foot", children=[
                html.P(t("keys_hint", lang), className="hint", id="lbl-keys-hint"),
                html.Button(t("clear_keys", lang), id="btn-clear-keys", n_clicks=0,
                            className="mini"),
            ]),
        ]),
    ])


@app.callback(
    Output("data-key", "data"),
    Output("upload-status", "children"),
    Output("dest-panel", "children"),
    Output("report", "className"),
    Output("upload", "className"),
    Output("day-picker", "min_date_allowed"),
    Output("day-picker", "max_date_allowed"),
    Output("day-picker", "date"),
    Output("day-picker", "initial_visible_month"),
    Input("upload", "contents"),
    State("upload", "filename"),
    State("lang", "value"),
    prevent_initial_call=True,
)
def _on_upload(contents, filename, lang):
    nu = no_update
    if not contents:
        return nu, nu, nu, nu, nu, nu, nu, nu, nu
    try:
        _header, b64 = contents.split(",", 1)
        if len(b64) * 3 / 4 > MAX_UPLOAD_MB * 2**20:
            raise ValueError(f"file is larger than {MAX_UPLOAD_MB:g} MB")
        data = load_report(base64.b64decode(b64))
    except Exception as exc:  # show any parse error to the user
        msg = html.Div([html.B(f"{t('error', lang)}: "), f"{filename} — {exc}"],
                       className="status-error")
        return None, msg, [], "report hidden", "upload upload-big", nu, nu, nu, nu
    key = _cache_put(filename or "report.csv", data)
    days = data.frame.index.normalize()
    first, last = days.min().date().isoformat(), days.max().date().isoformat()
    return (key, nu, _dest_panel(data, lang), "report", "upload upload-small",
            first, last, last, last)


@app.callback(
    Output({"type": "name", "ean": ALL}, "placeholder"),
    Output({"type": "key", "ean": ALL}, "placeholder"),
    Output("lbl-source", "children"),
    Output("lbl-dest", "children"),
    Output("lbl-dest-hint", "children"),
    Output("btn-all", "children"),
    Output("btn-none", "children"),
    Output("lbl-keys", "children"),
    Output("lbl-keys-hint", "children"),
    Output("btn-clear-keys", "children"),
    Input("lang", "value"),
    State({"type": "name", "ean": ALL}, "id"),
    State({"type": "key", "ean": ALL}, "id"),
    State("data-key", "data"),
    prevent_initial_call=True,
)
def _panel_lang(lang, ids, key_ids, key):
    entry = _cache_get(key)
    if entry is None:
        raise dash.exceptions.PreventUpdate
    names = default_names(entry.data, lang)
    return ([names.get(i["ean"], "") for i in ids], [t("key_ph", lang)] * len(key_ids),
            t("panel_source", lang), t("panel_dest", lang), t("panel_dest_hint", lang),
            t("all", lang), t("none", lang), t("keys", lang), t("keys_hint", lang),
            t("clear_keys", lang))


@app.callback(
    Output({"type": "dest", "ean": ALL}, "value"),
    Input("btn-all", "n_clicks"),
    Input("btn-none", "n_clicks"),
    State({"type": "dest", "ean": ALL}, "id"),
    prevent_initial_call=True,
)
def _all_none(_a, _n, ids):
    if ctx.triggered_id == "btn-all":
        return [[i["ean"]] for i in ids]
    return [[] for _ in ids]


@app.callback(
    Output({"type": "key", "ean": ALL}, "value"),
    Input("btn-clear-keys", "n_clicks"),
    State({"type": "key", "ean": ALL}, "id"),
    prevent_initial_call=True,
)
def _clear_keys(n, ids):
    if not n:
        raise dash.exceptions.PreventUpdate
    return [None] * len(ids)


# ---------------------------------------------------------------------------
# Recompute job: start + poll (progress bar)
# ---------------------------------------------------------------------------


@app.callback(
    Output("job-id", "data"),
    Output("poll", "disabled"),
    Output("btn-recompute", "disabled"),
    Output("progress", "className"),
    Output("progress-bar", "style"),
    Output("progress-text", "children"),
    Input("btn-recompute", "n_clicks"),
    State("data-key", "data"),
    State({"type": "key", "ean": ALL}, "id"),
    State({"type": "key", "ean": ALL}, "value"),
    State("reserve", "value"),
    State("lang", "value"),
    prevent_initial_call=True,
)
def _start_job(n, key, key_ids, key_values, reserve, lang):
    entry = _cache_get(key)
    if not n or entry is None:
        raise dash.exceptions.PreventUpdate
    if entry.data.fmt != "all":
        return (no_update, True, False, "progress error", {"width": "0%"},
                t("part_no_recompute", lang))
    keys = _keys_from_inputs(entry.data, key_ids, key_values)
    reserve = min(max(float(reserve or 0), 0.0), 100.0) / 100
    now = time.perf_counter()
    for old in [j for j, v in _JOBS.items() if v.get("reported") or now - v["t0"] > 3600]:
        _JOBS.pop(old, None)
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = {"phase": "start", "frac": 0.0, "done": False, "error": None,
                     "t0": time.perf_counter(), "data_key": key}
    threading.Thread(target=_run_job, args=(job_id, key, keys, reserve), daemon=True).start()
    first = t("phase_fit" if any(k is None for k in keys) else "phase_compute", lang)
    return job_id, False, True, "progress running", {"width": "0%"}, f"{first}… 0 %"


@app.callback(
    Output("poll", "disabled", allow_duplicate=True),
    Output("btn-recompute", "disabled", allow_duplicate=True),
    Output("progress", "className", allow_duplicate=True),
    Output("progress-bar", "style", allow_duplicate=True),
    Output("progress-text", "children", allow_duplicate=True),
    Output("result-rev", "data"),
    Output({"type": "key", "ean": ALL}, "value", allow_duplicate=True),
    Input("poll", "n_intervals"),
    State("job-id", "data"),
    State("result-rev", "data"),
    State({"type": "key", "ean": ALL}, "id"),
    State("lang", "value"),
    prevent_initial_call=True,
)
def _poll(_n, job_id, rev, key_ids, lang):
    job = _JOBS.get(job_id or "")
    if job is None or job.get("reported"):
        # late poll after completion: just make sure polling stops, keep the bar as is
        nu = no_update
        return True, nu, nu, nu, nu, nu, [nu] * len(key_ids)
    elapsed = time.perf_counter() - job["t0"]
    if not job["done"]:
        phase = job["phase"]
        label = t("phase_fit" if phase == "fit" else "phase_compute", lang)
        # fit and compute are shown as one bar: fit 0–60 %, compute 60–100 % when fitting
        frac = job["frac"]
        if job.get("had_fit") or phase == "fit":
            job["had_fit"] = True
            frac = 0.6 * frac if phase == "fit" else 0.6 + 0.4 * frac
        entry = _cache_get(job["data_key"])
        extra = ""
        if phase == "compute" and entry is not None:
            n_iv = entry.data.n_rows
            extra = f" · {fmt_num(job['frac'] * n_iv, lang)} / {fmt_num(n_iv, lang)}"
        text = f"{label}… {fmt_pct(100 * frac, lang, 0)}{extra} · {fmt_duration(elapsed, lang)}"
        return (False, True, "progress running", {"width": f"{100 * frac:.1f}%"}, text,
                no_update, [no_update] * len(key_ids))
    job["reported"] = True
    if job["error"]:
        return (True, False, "progress error", {"width": "100%"},
                f"{t('phase_error', lang)}: {job['error']}", no_update,
                [no_update] * len(key_ids))
    entry = _cache_get(job["data_key"])
    values = [no_update] * len(key_ids)
    if entry is not None and entry.exact is not None:
        by_ean = dict(zip(entry.data.dest_eans, entry.exact.keys))
        values = [_pct_key(by_ean[i["ean"]]) for i in key_ids]
    text = f"✓ {fmt_duration(elapsed, lang)}"
    return True, False, "progress done", {"width": "100%"}, text, (rev or 0) + 1, values


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _kv(label: str, value) -> html.Div:
    return html.Div(className="kv", children=[html.Dt(label), html.Dd(value)])


def _tile(label: str, value: str, sub=None, accent: str | None = None) -> html.Div:
    return html.Div(className="tile", children=[
        html.Div(className="tile-label", children=[
            html.Span(className="tile-dot", style={"background": accent}) if accent else None,
            label,
        ]),
        html.Div(value, className="tile-value"),
        html.Div(sub or " ", className="tile-sub"),
    ])


def _facts(filename: str, data: SharingData, enabled: set[str], names: dict, lang: str):
    s = summarize(data, enabled)
    facts = [
        _kv(t("file", lang), filename),
        _kv(t("report_type", lang), t("type_all" if data.fmt == "all" else "type_part", lang)),
        _kv(t("period", lang),
            f"{fmt_date(s.date_from, lang)} – {fmt_date(s.date_to, lang)} "
            f"({s.n_days} {t('days', lang)}, {fmt_num(s.n_rows, lang)} {t('intervals', lang)})"),
        _kv(t("producer", lang),
            ", ".join(f"{names[e]} ({e})" for e in data.source_eans)),
        _kv(t("n_dest", lang),
            t("selected_of", lang).format(sel=s.n_selected, n=s.n_dests)),
    ]
    if s.peak_production_kw is not None:
        facts.append(_kv(t("peak", lang), f"{fmt_num(s.peak_production_kw, lang, 2)} kW"))
    if s.best_day is not None:
        facts.append(_kv(t("best_day", lang),
                         f"{fmt_date(s.best_day, lang)} ({fmt_num(s.best_day_shared, lang, 1)} kWh)"))
    facts.append(_kv(t("days_sharing", lang), f"{s.days_with_sharing} / {s.n_days}"))
    return html.Dl(className="facts", children=facts)


def _tiles(data: SharingData, enabled: set[str], lang: str, ref: SharingData | None = None,
           pad: bool = False):
    """KPI tiles; with ``ref`` the sub-line also shows the difference to ``ref``.
    ``pad`` reserves the same extra line so paired columns stay aligned."""
    s = summarize(data, enabled)
    r = summarize(ref, enabled) if ref is not None else None
    kwh = lambda x: f"{fmt_num(x, lang)} kWh"  # noqa: E731
    pct = lambda x, base: fmt_pct(100 * x / base, lang) if base else "—"  # noqa: E731

    def sub(main: str, cur, old, higher_is_better: bool = True):
        if r is None or cur is None or old is None:
            return [main, html.Br(), "\u00a0"] if pad else main
        d = cur - old
        if abs(d) <= 0.05:
            cls = "delta"
        else:
            cls = "delta good" if (d > 0) == higher_is_better else "delta bad"
        return [main, html.Br(),
                html.Span(f"{fmt_signed(d, lang)} kWh {t('vs_edc', lang)}", className=cls)]

    if data.fmt != "all":
        return [html.Div(className="tiles", children=[
            _tile(t("kpi_shared", lang), kwh(s.shared), None, "#339933")])]
    prod = s.production or 0.0
    g = lambda name: getattr(r, name) if r is not None else None  # noqa: E731
    tiles = [
        _tile(t("kpi_production", lang), kwh(s.production), None, "#339933"),
        _tile(t("kpi_shared", lang), kwh(s.shared),
              sub(f"{pct(s.shared, prod)} {t('of_production', lang)}", s.shared, g("shared")),
              "#339933"),
        _tile(t("kpi_wasted", lang), kwh(s.overlap),
              sub(f"{pct(s.overlap, prod)} {t('of_production', lang)}", s.overlap, g("overlap"),
                  higher_is_better=False),
              "#cc3326"),
        _tile(t("kpi_unshareable", lang), kwh(s.unshared_only),
              sub(f"{pct(s.unshared_only, prod)} {t('of_production', lang)}",
                  s.unshared_only, g("unshared_only"), higher_is_better=False), "#8c8c8c"),
        _tile(t("kpi_consumption", lang), kwh(s.consumption), None, None),
        _tile(t("kpi_from_grid", lang), kwh(s.unmet),
              sub(f"{pct(s.unmet, s.consumption)} {t('of_consumption', lang)}",
                  s.unmet, g("unmet"), higher_is_better=False), "#c7c7c7"),
    ]
    return [html.Div(className="tiles", children=tiles),
            html.P(t("kpi_note", lang), className="hint")]


def _dest_table(data: SharingData, enabled: set[str], names: dict, lang: str):
    df = per_destination(data)
    cmap = colour_map(data)
    is_all = data.fmt == "all"
    head = [f"{t('col_name', lang)} / {t('col_ean', lang)}"]
    if is_all:
        head += [t("col_consumption", lang), t("col_shared", lang), t("col_unmet", lang),
                 t("col_coverage", lang)]
    else:
        head += [t("col_shared", lang)]
    head += [t("col_share", lang), t("col_data", lang)]

    body = []
    for r in df.itertuples():
        cells = [
            html.Td(className="name", children=[
                html.Div([html.Span(className="swatch", style={"background": cmap[r.ean]}),
                          names[r.ean]]),
                html.Div(r.ean, className="mono sub-ean"),
            ]),
        ]
        if is_all:
            cells += [html.Td(fmt_num(r.consumption, lang, 1), className="num"),
                      html.Td(fmt_num(r.shared, lang, 1), className="num"),
                      html.Td(fmt_num(r.unmet, lang, 1), className="num"),
                      html.Td(fmt_pct(r.coverage_pct, lang), className="num")]
        else:
            cells += [html.Td(fmt_num(r.shared, lang, 1), className="num")]
        cells += [html.Td(fmt_pct(r.share_of_shared_pct, lang), className="num"),
                  html.Td([fmt_date(r.first_data, lang),
                           html.Span(f" ({fmt_pct(r.data_pct, lang, 0)})", className="muted")],
                          className="num", title=t("col_data_pct", lang))]
        body.append(html.Tr(cells, className="" if r.ean in enabled else "off"))

    tot = [html.Td(html.B("Σ"))]
    if is_all:
        c, sh, u = df["consumption"].sum(), df["shared"].sum(), df["unmet"].sum()
        tot += [html.Td(html.B(fmt_num(c, lang, 1)), className="num"),
                html.Td(html.B(fmt_num(sh, lang, 1)), className="num"),
                html.Td(html.B(fmt_num(u, lang, 1)), className="num"),
                html.Td(html.B(fmt_pct(100 * sh / c if c else None, lang)), className="num")]
    else:
        tot += [html.Td(html.B(fmt_num(df["shared"].sum(), lang, 1)), className="num")]
    tot += [html.Td(html.B(fmt_pct(100.0, lang)), className="num"), html.Td("")]

    return html.Table(className="tbl", children=[
        html.Thead(html.Tr([html.Th(h) for h in head])),
        html.Tbody(body),
        html.Tfoot(html.Tr(tot)),
    ])


def _cmp_table(data: SharingData, exact: Recomputed, enabled: set[str], names: dict, lang: str):
    a = per_destination(data).set_index("ean")
    b = per_destination(exact.data).set_index("ean")
    keys = dict(zip(data.dest_eans, exact.keys))
    ksum = sum(exact.keys) or 1.0
    cmap = colour_map(data)
    head = [f"{t('col_name', lang)} / {t('col_ean', lang)}", t("cmp_key", lang),
            t("col_consumption", lang), t("cmp_shared_edc", lang), t("cmp_shared_exact", lang),
            t("cmp_delta", lang), t("cmp_delta_pct", lang), t("cmp_cov", lang)]
    body = []
    for e in data.dest_eans:
        sa, sb, dem = a.at[e, "shared"], b.at[e, "shared"], a.at[e, "consumption"]
        d = sb - sa
        body.append(html.Tr(className="" if e in enabled else "off", children=[
            html.Td(className="name", children=[
                html.Div([html.Span(className="swatch", style={"background": cmap[e]}), names[e]]),
                html.Div(e, className="mono sub-ean"),
            ]),
            html.Td([fmt_pct(100 * keys[e], lang, 1),
                     html.Span(f" ({fmt_pct(100 * keys[e] / ksum, lang, 1)})", className="muted")],
                    className="num"),
            html.Td(fmt_num(dem, lang, 1), className="num"),
            html.Td(fmt_num(sa, lang, 1), className="num"),
            html.Td(html.B(fmt_num(sb, lang, 1)), className="num"),
            html.Td(fmt_signed(d, lang), className="num " + ("pos" if d > 0.05 else "")),
            html.Td(fmt_pct(100 * d / sa, lang) if sa else "—", className="num"),
            html.Td(f"{fmt_pct(100 * sa / dem if dem else None, lang)} → "
                    f"{fmt_pct(100 * sb / dem if dem else None, lang)}", className="num"),
        ]))
    sa, sb, dem = a["shared"].sum(), b["shared"].sum(), a["consumption"].sum()
    foot = html.Tr([
        html.Td(html.B("Σ")),
        html.Td(html.B(fmt_pct(100 * sum(exact.keys), lang, 1)), className="num"),
        html.Td(html.B(fmt_num(dem, lang, 1)), className="num"),
        html.Td(html.B(fmt_num(sa, lang, 1)), className="num"),
        html.Td(html.B(fmt_num(sb, lang, 1)), className="num"),
        html.Td(html.B(fmt_signed(sb - sa, lang)), className="num pos"),
        html.Td(html.B(fmt_pct(100 * (sb - sa) / sa if sa else None, lang)), className="num"),
        html.Td(html.B(f"{fmt_pct(100 * sa / dem if dem else None, lang)} → "
                       f"{fmt_pct(100 * sb / dem if dem else None, lang)}"), className="num"),
    ])
    return html.Table(className="tbl", children=[
        html.Thead(html.Tr([html.Th(h) for h in head])),
        html.Tbody(body), html.Tfoot(foot),
    ])


def _timing(exact: Recomputed, data: SharingData, names: dict, lang: str,
            stale: bool) -> list:
    tm = exact.timing
    n = lambda x: fmt_num(x, lang)  # noqa: E731
    stats = html.Div(className="timing-grid", children=[
        html.Div(className="tstat", children=[
            html.Div(t("t_intervals", lang), className="tstat-label"),
            html.Div(n(tm.intervals), className="tstat-value"),
            html.Div(t("t_breakdown", lang).format(a=n(tm.n_night), b=n(tm.n_enough),
                                                   c=n(tm.n_full)), className="tstat-sub"),
        ]),
        html.Div(className="tstat", children=[
            html.Div(t("t_total", lang), className="tstat-label"),
            html.Div(fmt_duration(tm.t_total, lang), className="tstat-value"),
            html.Div(f"{t('t_members', lang)}: {tm.members} · "
                     f"{t('t_clock_cpu' if tm.clock.startswith('thread') else 't_clock_wall', lang)}",
                     className="tstat-sub"),
        ]),
        html.Div(className="tstat", children=[
            html.Div(t("t_per", lang), className="tstat-label"),
            html.Div(fmt_duration(tm.per_interval, lang), className="tstat-value"),
            html.Div(f"{fmt_duration(tm.per_full, lang)} {t('t_per_full', lang)}",
                     className="tstat-sub"),
        ]),
        html.Div(className="tstat", children=[
            html.Div(t("t_wall", lang), className="tstat-label"),
            html.Div(fmt_duration(tm.t_wall, lang), className="tstat-value"),
            html.Div(f"{t('t_fit', lang)}: {fmt_duration(tm.t_fit, lang)}" if tm.t_fit else " ",
                     className="tstat-sub"),
        ]),
    ])
    key_txt = " · ".join(f"{names[e]} {fmt_pct(100 * k, lang, 1)}"
                         for e, k in zip(data.dest_eans, exact.keys))
    src = t("keys_est", lang) if exact.keys_estimated else t("keys_user", lang)
    reserve = (f" · {t('reserve', lang)}: {fmt_pct(100 * exact.reserve, lang, 1)}"
               if exact.reserve else "")
    out = [
        html.H3(t("timing_title", lang), className="sub-title"),
        stats,
        html.P([html.B(f"{t('keys_used', lang)} ({src}): "), key_txt,
                f" ({t('keys_sum', lang)} {fmt_pct(100 * sum(exact.keys), lang, 1)}){reserve}"],
               className="keys-line"),
        html.P(t("edc_check", lang).format(pct=fmt_pct(100 * exact.edc_match, lang, 1)),
               className="hint"),
    ]
    if stale:
        out.append(html.P(t("stale", lang), className="stale"))
    return out


def _align_overview(fa, fb) -> None:
    hi = max(fa.layout.xaxis.range[1], fb.layout.xaxis.range[1])
    for f in (fa, fb):
        f.update_xaxes(range=[0, hi])


def _align_daily(fa, fb, log: bool) -> None:
    if not fa.data or not fb.data:
        return
    if log:
        hi = max(fa.layout.yaxis.range[1], fb.layout.yaxis.range[1])
        for f in (fa, fb):
            f.update_yaxes(range=[-2, hi])
        return
    peak = max(np.sum([np.asarray(tr.y, dtype=float) for tr in f.data], axis=0).max()
               for f in (fa, fb))
    for f in (fa, fb):
        f.update_yaxes(range=[0, peak * 1.05])


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------


@app.callback(
    Output("page-title", "children"),
    Output("info", "children"),
    Output("notes", "children"),
    Output("tiles-a", "children"),
    Output("fig-overview", "figure"),
    Output("fig-daily", "figure"),
    Output("fig-pie", "figure"),
    Output("fig-overview", "style"),
    Output("fig-daily", "style"),
    Output("fig-pie", "style"),
    Output("pie-card", "style"),
    Output("dest-table", "children"),
    Output("compare", "className"),
    Output("tiles-b", "children"),
    Output("fig-overview-b", "figure"),
    Output("fig-daily-b", "figure"),
    Output("fig-pie-b", "figure"),
    Output("fig-overview-b", "style"),
    Output("fig-daily-b", "style"),
    Output("fig-pie-b", "style"),
    Output("cmp-card", "style"),
    Output("cmp-table", "children"),
    Output("timing", "children"),
    Output("btn-recompute", "title"),
    Output("upload-status", "children", allow_duplicate=True),
    Output("fig-heat", "figure"),
    Output("fig-heat", "style"),
    Output("fig-heat-b", "figure"),
    Output("fig-heat-b", "style"),
    Input("data-key", "data"),
    Input("result-rev", "data"),
    Input({"type": "dest", "ean": ALL}, "value"),
    Input({"type": "name", "ean": ALL}, "value"),
    Input({"type": "key", "ean": ALL}, "value"),
    Input("reserve", "value"),
    Input("lang", "value"),
    Input("yscale", "value"),
    Input("grid-toggles", "value"),
    Input("group", "value"),
    Input("show-heat", "value"),
    Input("heat-metric", "value"),
    State({"type": "name", "ean": ALL}, "id"),
    State({"type": "key", "ean": ALL}, "id"),
    State("day-picker", "date"),
    prevent_initial_call="initial_duplicate",
)
def _render(key, _rev, dest_values, name_values, key_values, reserve, lang, yscale,
            toggles, group, show_heat, heat_metric, name_ids, key_ids, sel_day):
    group = (group or "").strip()
    title = (t("report_title_group", lang).format(group=group) if group
             else t("report_title", lang))
    entry = _cache_get(key)
    if entry is None:
        status = (html.Div(t("session_lost", lang), className="status-error")
                  if key else no_update)
        e = {}
        return (title, [], [], [], e, e, e, e, e, e, e, [], "compare single",
                [], e, e, e, e, e, e, {"display": "none"}, [], [], "", status, e, e, e, e)
    data = entry.data

    enabled = {v[0] for v in (dest_values or []) if v}
    if not dest_values:  # panel not rendered yet -> everything on
        enabled = set(data.dest_eans)
    names = effective_names(data, lang, name_ids, name_values)
    show_unshared = "unshared" in (toggles or [])
    show_unmet = "unmet" in (toggles or [])
    yscale = yscale or "linear"
    opts = dict(show_unshared=show_unshared, show_unmet=show_unmet, lang=lang)
    h = lambda fig: {"height": f"{fig.layout.height}px"} if fig else {}  # noqa: E731

    df = filter_dests(data, enabled)
    ov_a = fig_total_by_flow(df, data, names, **opts)
    sel_day = _day(sel_day)
    dy_a = fig_daily(df, data, names, yscale=yscale, sel_day=sel_day, **opts)
    has_grid = data.fmt == "all"
    pie_a = fig_wasted_pie(compute_wasted_split(df), lang) if has_grid else {}

    notes = []
    if data.notes:
        notes = html.Details(className="notes", children=[
            html.Summary(f"{t('notes', lang)} ({len(data.notes)})"),
            html.Ul([html.Li(n) for n in data.notes]),
        ])

    exact = entry.exact
    hidden = {"display": "none"}
    if exact is None:
        b = ([], {}, {}, {}, {}, {}, {}, hidden, [], [])
        mode = "compare single"
    else:
        df_b = filter_dests(exact.data, enabled)
        ov_b = fig_total_by_flow(df_b, exact.data, names, **opts)
        dy_b = fig_daily(df_b, exact.data, names, yscale=yscale, sel_day=sel_day, **opts)
        pie_b = fig_wasted_pie(compute_wasted_split(df_b), lang)
        _align_overview(ov_a, ov_b)
        _align_daily(dy_a, dy_b, yscale == "log")
        cur_keys = _keys_from_inputs(data, key_ids, key_values)
        cur_res = min(max(float(reserve or 0), 0.0), 100.0) / 100
        stale = (any(k is not None and abs(k - u) > 1e-6 for k, u in zip(cur_keys, exact.keys))
                 or abs(cur_res - exact.reserve) > 1e-9)
        b = (_tiles(exact.data, enabled, lang, ref=data), ov_b, dy_b, pie_b,
             h(ov_b), h(dy_b), h(pie_b), {}, _cmp_table(data, exact, enabled, names, lang),
             _timing(exact, data, names, lang, stale))
        mode = "compare dual"
        # keep paired graphs the same height
        for fa, fb in ((ov_a, ov_b),):
            hh = max(fa.layout.height, fb.layout.height)
            fa.update_layout(height=hh)
            fb.update_layout(height=hh)
        b = (b[0], ov_b, dy_b, pie_b, h(ov_b), h(dy_b), h(pie_b), *b[7:])

    # heatmap (optional); in dual mode both share one colour scale
    heat_on = "on" in (show_heat or [])
    metric = heat_metric or "production"
    ht_a = ht_b = {}
    if heat_on:
        pv_a = heat_pivot(df, metric)
        pv_b = heat_pivot(filter_dests(exact.data, enabled), metric) if exact else None
        zs = [float(np.nanmax(p.to_numpy())) for p in (pv_a, pv_b)
              if p is not None and not p.empty]
        z_max = max(zs) if zs else None
        ht_a = fig_heatmap(pv_a, metric, z_max=z_max, lang=lang)
        if exact is not None:
            ht_b = fig_heatmap(pv_b, metric, z_max=z_max, lang=lang)
    if not heat_on:
        mode += " no-heat"

    btn_title = t("part_no_recompute", lang) if data.fmt != "all" else ""
    status = html.Div([html.Span("✓ ", className="ok"), f"{t('loaded', lang)}: ",
                       html.B(entry.filename)], className="status-ok")
    return (
        title,
        _facts(entry.filename, data, enabled, names, lang),
        notes,
        _tiles(data, enabled, lang, pad=exact is not None),
        ov_a, dy_a, pie_a,
        h(ov_a), h(dy_a), h(pie_a),
        {} if has_grid else hidden,
        _dest_table(data, enabled, names, lang),
        mode,
        *b,
        btn_title,
        status,
        ht_a, h(ht_a), ht_b, h(ht_b),
    )


# ---------------------------------------------------------------------------
# Selected day: click the daily plot, or ◀ / date picker / ▶ in the panel
# ---------------------------------------------------------------------------


def _day(value) -> str | None:
    """Normalise a date-ish value ('2026-06-19', '2026-06-19 00:00', …) to ISO date."""
    return str(value)[:10] if value else None


@app.callback(
    Output("day-picker", "date", allow_duplicate=True),
    Input("fig-daily", "clickData"),
    Input("fig-daily-b", "clickData"),
    Input("btn-prev-day", "n_clicks"),
    Input("btn-next-day", "n_clicks"),
    State("day-picker", "date"),
    State("day-picker", "min_date_allowed"),
    State("day-picker", "max_date_allowed"),
    prevent_initial_call=True,
)
def _select_day(click_a, click_b, _prev, _next, cur, lo, hi):
    trig = ctx.triggered_id
    if trig in ("fig-daily", "fig-daily-b"):
        click = click_a if trig == "fig-daily" else click_b
        if not click or not click.get("points"):
            raise dash.exceptions.PreventUpdate
        day = _day(click["points"][0].get("x"))
    else:
        if not cur:
            raise dash.exceptions.PreventUpdate
        step = -1 if trig == "btn-prev-day" else 1
        day = (dt.date.fromisoformat(_day(cur)) + dt.timedelta(days=step)).isoformat()
    if lo and day < _day(lo):
        day = _day(lo)
    if hi and day > _day(hi):
        day = _day(hi)
    if day == _day(cur):
        raise dash.exceptions.PreventUpdate
    return day


# Move only the dashed marker, in the browser (no server round-trip); skipped while a
# daily figure has not been drawn yet.
app.clientside_callback(
    """
    function(day, figA, figB) {
        const nu = window.dash_clientside.no_update;
        function mark(fig) {
            if (!day || !fig || !fig.data || !fig.data.length) { return nu; }
            const d = String(day).slice(0, 10);
            const layout = Object.assign({}, fig.layout, {shapes: [{
                type: 'line', xref: 'x', yref: 'paper', x0: d, x1: d, y0: 0, y1: 1,
                line: {color: 'black', width: 1.5, dash: 'dash'}, layer: 'above'}]});
            return Object.assign({}, fig, {layout: layout});
        }
        return [mark(figA), mark(figB)];
    }
    """,
    Output("fig-daily", "figure", allow_duplicate=True),
    Output("fig-daily-b", "figure", allow_duplicate=True),
    Input("day-picker", "date"),
    State("fig-daily", "figure"),
    State("fig-daily-b", "figure"),
    prevent_initial_call=True,
)


@app.callback(
    Output("fig-hourly", "figure"),
    Output("fig-hourly", "style"),
    Output("fig-hourly-b", "figure"),
    Output("fig-hourly-b", "style"),
    Input("day-picker", "date"),
    Input("data-key", "data"),
    Input("result-rev", "data"),
    Input({"type": "dest", "ean": ALL}, "value"),
    Input({"type": "name", "ean": ALL}, "value"),
    Input("lang", "value"),
    Input("yscale", "value"),
    Input("grid-toggles", "value"),
    State({"type": "name", "ean": ALL}, "id"),
)
def _hourly(day, key, _rev, dest_values, name_values, lang, yscale, toggles, name_ids):
    """Subplot 4: one day in 15-min steps; y axis fixed over the whole period (and
    shared by both reports) so days and methods compare on one scale."""
    entry = _cache_get(key)
    if entry is None or not day:
        return {}, {}, {}, {}
    data = entry.data
    enabled = {v[0] for v in (dest_values or []) if v}
    if not dest_values:
        enabled = set(data.dest_eans)
    names = effective_names(data, lang, name_ids, name_values)
    yscale = yscale or "linear"
    show_unshared = "unshared" in (toggles or [])
    show_unmet = "unmet" in (toggles or [])
    stacked = yscale != "log"
    frames = [filter_dests(data, enabled)]
    if entry.exact is not None:
        frames.append(filter_dests(entry.exact.data, enabled))
    y_max = max(intraday_ymax(f, show_unshared, show_unmet, stacked) for f in frames)
    opts = dict(y_max=y_max, yscale=yscale, show_unshared=show_unshared,
                show_unmet=show_unmet, lang=lang)
    fa = fig_intraday(frames[0], data, names, _day(day), **opts)
    style = {"height": f"{fa.layout.height}px"}
    if entry.exact is None:
        return fa, style, {}, {}
    fb = fig_intraday(frames[1], entry.exact.data, names, _day(day), **opts)
    return fa, style, fb, style


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="SharEl sharing report web app")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    app.run(host=a.host, port=a.port, debug=a.debug)
