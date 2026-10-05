"""EDC sharing report - Dash web app that displays the CSV sharing reports
generated on edc-cr.cz (the EDC portal).

Phase 1: upload the CSV report from edc-cr.cz and see general information and statistics,
the "total by flow" overview and daily plot from Figure 1 of
``plot_energy_sharing.py``, and the shared / wasted pie from Figure 2, with a
selection panel (destinations on/off, names, display options).

Phase 2: a button recomputes sharing with the exact static method
(``presna_staticka.rozdel``) and shows the recomputed report side by side with
today's EDC report, with a progress bar and timing of the computation.

Phase 3: hourly plot of a selected day, heatmap, allocation keys estimated
right after upload (1 or 5 EDC rounds, any group size), dark mode.

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
from html import escape as esc
from collections import OrderedDict
from dataclasses import dataclass
from string import ascii_uppercase

import numpy as np
import dash
import dash_ag_grid as dag
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update
from flask import Response, request

from figures import (
    colour_map, fig_daily, fig_heatmap, fig_intraday, fig_total_by_flow,
    fig_wasted_pie, heat_metrics, heat_pivot, intraday_ymax, theme, top_dests,
)
from i18n import fmt_date, fmt_duration, fmt_num, fmt_pct, fmt_signed, t
from keyfit import KeyFit, estimate_keys
from procjob import JobCancelled, JobTimeout, run_in_child
from recompute import Recomputed, grid_loss, recompute, to_hundredths
from edc_data import (
    SharingData, compute_wasted_split, filter_dests, load_report,
    per_destination, summarize,
)

# ---------------------------------------------------------------------------
# Configuration (environment variables; see README "Deploy on Render")
# ---------------------------------------------------------------------------

#: parsed reports kept in memory (~20-25 MB each incl. a recompute; 512 MB instances -> 6)
CACHE_MAX = int(os.environ.get("EDC_CACHE_MAX", "6"))
#: largest accepted CSV in MB
MAX_UPLOAD_MB = float(os.environ.get("EDC_MAX_UPLOAD_MB", "25"))
#: optional HTTP basic auth for the whole app (both must be set)
AUTH_USER = os.environ.get("BASIC_AUTH_USER", "")
AUTH_PASSWORD = os.environ.get("BASIC_AUTH_PASSWORD", "")
#: computations (key estimation, recompute) running at the same time; others queue
MAX_JOBS = max(1, int(os.environ.get("EDC_MAX_JOBS", "2")))
#: a key estimate is killed after this many seconds (it stops itself after ~20 s)
FIT_TIMEOUT_S = float(os.environ.get("EDC_FIT_TIMEOUT", "120"))
#: a job nobody has polled for this long (page closed) is cancelled; browsers throttle
#: timers of hidden tabs to once a minute, so keep this well above that
JOB_IDLE_S = float(os.environ.get("EDC_JOB_IDLE_S", "180"))

# ---------------------------------------------------------------------------
# In-memory store of parsed uploads (keyed by a random id held in the browser)
# and of background jobs.
#
# ONE PROCESS ONLY. Everything a browser session refers to - its upload, the key
# estimate, a running recompute and its progress - lives in this process's
# memory, so every request of that session must reach this same process. Run
# gunicorn with a single worker and threads (gunicorn.conf.py pins that). With
# several workers a request lands in a process that does not know the upload or
# the job (the failure robopid-simulator hit with per-process job caches); that
# would need a shared store such as Redis, not more workers.
# ---------------------------------------------------------------------------


@dataclass
class Entry:
    filename: str
    data: SharingData
    exact: Recomputed | None = None
    fit: KeyFit | None = None


_CACHE: "OrderedDict[str, Entry]" = OrderedDict()
_CACHE_MAX = max(1, CACHE_MAX)
_LOCK = threading.Lock()


def _cache_put(filename: str, data: SharingData) -> str:
    key = uuid.uuid4().hex
    evicted: list[str] = []
    with _LOCK:
        _CACHE[key] = Entry(filename, data)
        while len(_CACHE) > _CACHE_MAX:
            evicted.append(_CACHE.popitem(last=False)[0])
    _cancel_jobs(evicted)                 # nobody can see their result any more
    return key


def _cache_drop(key: str | None) -> None:
    """Forget an upload (its browser replaced it) and stop its running jobs."""
    if not key:
        return
    with _LOCK:
        _CACHE.pop(key, None)
    _cancel_jobs([key])


def _cache_get(key: str | None) -> Entry | None:
    if not key:
        return None
    with _LOCK:
        item = _CACHE.get(key)
        if item is not None:
            _CACHE.move_to_end(key)
        return item


_JOBS: dict[str, dict] = {}
_JOB_SLOTS = threading.BoundedSemaphore(MAX_JOBS)


def _cancel_jobs(data_keys: list[str]) -> None:
    for job in list(_JOBS.values()):
        if job["data_key"] in data_keys:
            job["cancel"].set()


def _cancelled(job: dict) -> bool:
    """True when the job's result is no longer wanted: its upload was replaced or
    evicted, or the page stopped polling (closed) for JOB_IDLE_S."""
    return job["cancel"].is_set() or time.perf_counter() - job["seen"] > JOB_IDLE_S


def _run_job(job_id: str, kind: str, data_key: str, keys: list[float | None],
             reserve: float) -> None:
    """Background job: ``fit`` (estimate keys) or ``recompute`` (exact method).

    The heavy part runs in a child process (:mod:`procjob`), so request threads stay
    free for progress polls and the job can be cancelled. At most MAX_JOBS run at once
    (small instances have < 1 CPU); the rest wait in the "queued" phase and the
    progress bar says so.
    """
    job = _JOBS[job_id]
    stop = lambda: _cancelled(job)  # noqa: E731

    def progress(phase: str, frac: float) -> None:
        job["phase"], job["frac"] = phase, frac

    try:
        job["phase"] = "queued"
        while not _JOB_SLOTS.acquire(timeout=0.5):      # a cancelled job leaves the queue
            if stop():
                raise JobCancelled()
        try:
            job["t0"] = time.perf_counter()          # time the work, not the queue
            entry = _cache_get(data_key)
            if entry is None:
                raise JobCancelled()
            need_fit = kind == "fit" or (entry.fit is None and any(k is None for k in keys))
            if need_fit:
                job["had_fit"] = kind == "recompute"
                progress("fit", 0.0)
                P, D, S = to_hundredths(entry.data)
                entry.fit = run_in_child(estimate_keys, (P, D, S), progress=progress,
                                         cancelled=stop, timeout=FIT_TIMEOUT_S)
            if kind == "recompute":
                fit = entry.fit
                merged = [k if k is not None else (fit.keys[i] if fit else None)
                          for i, k in enumerate(keys)]
                if any(k is None for k in merged):
                    raise RuntimeError("missing allocation keys")
                progress("compute", 0.0)
                entry.exact = recompute(
                    entry.data, merged, reserve, progress=progress, fit=fit,
                    keys_estimated=fit is not None and merged == list(fit.keys),
                    rounds=fit.rounds if fit else 5, cancelled=stop,
                )
        finally:
            _JOB_SLOTS.release()
        job["done"] = True
    except JobCancelled:
        job["error_key"] = "job_cancelled"
        job["done"] = True
    except JobTimeout:
        job["error_key"] = "job_timeout"
        job["done"] = True
    except Exception as exc:  # reported in the UI
        traceback.print_exc()
        job["error"] = str(exc)
        job["done"] = True


def _start_background(kind: str, data_key: str, keys: list[float | None],
                      reserve: float, lang: str):
    """Start a job; return (job id, poll disabled=False).

    Only the poll callback writes the progress bar, its text and the button state.
    With a second writer (upload / start) a large response applied late could
    overwrite the poll's "done" and leave the bar stuck at 0 %.
    """
    now = time.perf_counter()
    for old in [j for j, v in list(_JOBS.items())
                if (v.get("reported") and now - v["t0"] > 60) or now - v["t0"] > 3600]:
        _JOBS.pop(old, None)
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = {"kind": kind, "phase": "queued", "frac": 0.0, "done": False,
                     "error": None, "t0": now, "data_key": data_key,
                     "cancel": threading.Event(), "seen": now}
    threading.Thread(target=_run_job, args=(job_id, kind, data_key, keys, reserve),
                     daemon=True).start()
    return job_id, False


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


def effective_names(data: SharingData, lang: str, src_ids: list[dict], src_values: list,
                    rows: list[dict] | None) -> dict[str, str]:
    """Display names: typed names (sources: inputs, destinations: grid) or defaults."""
    names = default_names(data, lang)
    for id_, val in zip(src_ids or [], src_values or []):
        if val and str(val).strip() and id_["ean"] in names:
            names[id_["ean"]] = str(val).strip()
    for r in rows or []:
        if r.get("name") and str(r["name"]).strip() and r.get("ean") in names:
            names[r["ean"]] = str(r["name"]).strip()
    return names


def _enabled(data: SharingData, selected: list[dict] | None) -> set[str]:
    """Ticked destinations; None (grid not ready yet) means all."""
    if selected is None:
        return set(data.dest_eans)
    return {r["ean"] for r in selected if r and "ean" in r}


def _keys_from_rows(data: SharingData, rows: list[dict] | None) -> list[float | None]:
    """Key column (percent) -> fractions in destination order; None = not set."""
    by_ean = {r.get("ean"): r.get("key") for r in rows or []}
    out: list[float | None] = []
    for e in data.dest_eans:
        v = by_ean.get(e)
        try:
            out.append(None if v in (None, "") else max(0.0, float(v)) / 100)
        except (TypeError, ValueError):
            out.append(None)
    return out


def _key_only_edit() -> bool:
    """True when the callback fired only because a key cell was edited (names and
    selection unchanged) - then the figures need not be redrawn."""
    props = set(ctx.triggered_prop_ids or {})
    if props != {"members.cellValueChanged"}:
        return False
    changes = ctx.triggered[0].get("value") if ctx.triggered else None
    changes = changes if isinstance(changes, list) else [changes or {}]
    return all((c or {}).get("colId") != "name" for c in changes)


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


def _member_columns(lang: str, can_key: bool) -> list[dict]:
    """Grid columns; formatters depend on the language (decimal comma, default names)."""
    dec = "," if lang == "cs" else "."
    return [
        {"field": "name", "headerName": t("col_name", lang), "editable": True, "flex": 1,
         "minWidth": 84, "tooltipField": "ean",
         "valueFormatter": {"function": f"params.value || params.data.default_{lang}"},
         "cellClassRules": {"muted-name": "!params.value"},
         "cellStyle": {"function": "({borderLeft: '6px solid ' + params.data.colour})"}},
        {"field": "tail", "headerName": "EAN", "width": 64, "cellClass": "mono-cell",
         "tooltipField": "ean"},
        {"field": "key", "headerName": t("keys", lang), "editable": can_key, "width": 70,
         "type": "rightAligned", "cellEditor": "agNumberCellEditor",
         "cellEditorParams": {"min": 0, "max": 100, "precision": 2},
         # values are rounded to 0.01 already; no globals (String/Math) in grid functions
         "valueFormatter": {"function":
             f"params.value == null ? '' : (params.value + '').replace('.', '{dec}')"},
         "tooltipField": "range",
         "cellClassRules": {"key-warn": "params.data.warn"}},
    ]


def _member_rows(data: SharingData) -> list[dict]:
    cmap = colour_map(data, top_dests(data.frame, data))
    names = {lg: default_names(data, lg) for lg in ("cs", "en")}
    return [{"ean": e, "tail": f"…{e[-6:]}", "name": "",
             "default_cs": names["cs"][e], "default_en": names["en"][e],
             "colour": cmap[e], "key": None, "range": "", "warn": False}
            for e in data.dest_eans]


def _grid_options(many: bool) -> dict:
    return {
        "rowSelection": {"mode": "multiRow", "enableClickSelection": False},
        "singleClickEdit": True, "stopEditingWhenCellsLoseFocus": True,
        "tooltipShowDelay": 250, "rowHeight": 32, "headerHeight": 30,
        "domLayout": "normal" if many else "autoHeight",
    }


def _source_rows(data: SharingData, lang: str) -> list:
    names = default_names(data, lang)
    return [
        html.Div(className="dest-row", children=[
            html.Span(className="swatch", style={"background": "#339933"}),
            html.Div(className="name-cell", children=[
                dcc.Input(id={"type": "name", "ean": e}, type="text", debounce=True,
                          placeholder=names[e], className="name-in"),
                html.Div(e, className="ean"),
            ]),
        ]) for e in data.source_eans
    ]


def _upload_content(lang: str, loaded: bool) -> html.Div:
    """Text inside the upload box: big prompt before a report is loaded, one line after."""
    if loaded:
        return html.Div([html.Span("⤒ "), t("upload_other", lang)],
                        className="upload-small-text")
    return html.Div([
        html.Div("⤒", className="upload-icon"),
        html.Div(t("upload_prompt", lang), className="upload-main"),
        html.Div(t("upload_hint", lang), className="upload-hint"),
    ])


def _static_panel() -> html.Div:
    """Source names + ONE grid for all destinations (tick, name, key).

    The grid is part of the static layout (filled on upload): one component
    instead of several inputs per destination - a group of 150 members would
    otherwise put 600 pattern-matching components on the page, and the Dash
    renderer then needs tens of seconds per update.
    """
    return html.Div(id="dest-panel", children=[
        html.Section(className="panel-section", children=[
            html.H3(id="lbl-source"),
            html.Div(id="src-panel"),
        ]),
        html.Section(className="panel-section", children=[
            html.Div(className="panel-head", children=[
                html.H3(id="lbl-dest"),
                html.Div(className="mini-btns", children=[
                    html.Button(id="btn-all", n_clicks=0, className="mini"),
                    html.Button(id="btn-none", n_clicks=0, className="mini"),
                ]),
            ]),
            html.P(className="hint", id="lbl-dest-hint"),
            dag.AgGrid(
                id="members", rowData=[], columnDefs=_member_columns("cs", True),
                getRowId="params.data.ean",
                defaultColDef={"sortable": False, "resizable": False, "suppressMovable": True},
                dashGridOptions=_grid_options(False), selectedRows=[],
                className="members-grid", style={"height": None},
            ),
            html.Div(className="keys-foot", children=[
                html.P(className="hint", id="lbl-keys-hint"),
                html.Button(id="btn-clear-keys", n_clicks=0, className="mini"),
            ]),
        ]),
    ])


app = dash.Dash(__name__, title="EDC sharing report", suppress_callback_exceptions=True)
server = app.server  # for gunicorn: gunicorn app:server --workers 1 --threads 8
# base64 upload inflates the file by 4/3; leave headroom for the rest of the request
server.config["MAX_CONTENT_LENGTH"] = int((MAX_UPLOAD_MB * 1.4 + 2) * 2**20)


# Apply the theme before the first paint (no light flash in dark mode): the saved
# choice from the "theme-pref" store, else the system preference.
app.index_string = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        <script>
        (function () {
            try {
                var raw = window.localStorage.getItem('theme-pref');
                var pref = raw ? JSON.parse(raw) : null;
                var sys = window.matchMedia &&
                          window.matchMedia('(prefers-color-scheme: dark)').matches;
                var mode = pref || (sys ? 'dark' : 'light');
                document.documentElement.dataset.theme = mode;
                document.documentElement.setAttribute('data-ag-theme-mode', mode);
            } catch (e) {}
        })();
        </script>
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""


@server.route("/healthz")
def _healthz():
    jobs = [j for j in list(_JOBS.values()) if not j["done"]]
    return {"status": "ok", "cached_reports": len(_CACHE),
            "jobs_running": sum(j["phase"] != "queued" for j in jobs),
            "jobs_queued": sum(j["phase"] == "queued" for j in jobs),
            "max_jobs": MAX_JOBS}


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
                    {"WWW-Authenticate": 'Basic realm="EDC sharing report"'})


app.layout = html.Div(className="page", children=[
    dcc.Store(id="theme-pref", storage_type="local"),   # "light" / "dark" / None = system
    dcc.Store(id="theme", data="light"),                 # resolved theme for the figures
    dcc.Store(id="data-key"),
    dcc.Store(id="job-id"),
    dcc.Store(id="result-rev", data=0),
    dcc.Interval(id="poll", interval=200, disabled=True),
    html.Header(className="topbar", children=[
        html.H1(id="page-title"),
        html.Div(className="lang", children=[
            html.Button("☾", id="theme-btn", n_clicks=0, className="icon-btn",
                        title="Tmavý režim"),
            dcc.RadioItems(
                id="lang", value="cs", inline=True, className="seg",
                options=[{"label": "CZ", "value": "cs"}, {"label": "EN", "value": "en"}],
            ),
        ]),
    ]),
    dcc.Upload(
        id="upload", multiple=False, accept=".csv,text/csv",
        className="upload upload-big",
        # static content in the layout: the box is never empty, even before the
        # label callback answers; the callback replaces Upload.children as a whole
        # (a nested child's update was sometimes lost inside dcc.Upload)
        children=_upload_content("cs", False),
    ),
    # spinner only next to the upload: wrapping the report in dcc.Loading would hide
    # (unmount) it while the upload callback runs and drop updates arriving meanwhile
    dcc.Loading(type="dot", color="#339933", target_components={"upload-status": "children"},
                children=html.Div(id="upload-status", className="status")),
    html.Div(id="report", className="report hidden", children=[
        html.Aside(className="panel", children=[
            _static_panel(),
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
                html.Div(id="heat-box", children=[
                    html.Label(id="lbl-heat-metric", className="field-label"),
                    dcc.RadioItems(id="heat-metric", value="production", className="radios"),
                ]),
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
                html.Div(id="fit-info"),
                html.Div(id="stale"),
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
    ]),
])


# ---------------------------------------------------------------------------
# Theme: default from the system, the icon toggles and remembers the choice
# ---------------------------------------------------------------------------

app.clientside_callback(
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
# Static labels (language)
# ---------------------------------------------------------------------------


@app.callback(
    Output("upload", "children"),
    Output("lbl-display", "children"),
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
    Output("lbl-heat-metric", "children"),
    Output("heat-metric", "options"),
    Output("heat-metric", "value"),
    Output("heat-box", "style"),
    Output("theme-btn", "title"),
    Input("lang", "value"),
    Input("data-key", "data"),
    State("heat-metric", "value"),
)
def _labels(lang, key, heat_value):
    entry = _cache_get(key)
    metrics = heat_metrics(entry.data) if entry else ("production", "consumption")
    return (
        _upload_content(lang, entry is not None),
        t("panel_display", lang),
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
        t("heat_metric", lang),
        [{"label": t(f"heat_{m}", lang), "value": m} for m in metrics],
        heat_value if heat_value in metrics else metrics[0],
        {"display": "none"} if len(metrics) < 2 else {},   # nothing to choose (part report)
        t("theme_toggle", lang),
    )


# ---------------------------------------------------------------------------
# Upload -> parse -> build the selection panel
# ---------------------------------------------------------------------------


@app.callback(
    Output("data-key", "data"),
    Output("upload-status", "children"),
    Output("src-panel", "children"),
    Output("report", "className"),
    Output("upload", "className"),
    Output("day-picker", "min_date_allowed"),
    Output("day-picker", "max_date_allowed"),
    Output("day-picker", "date"),
    Output("day-picker", "initial_visible_month"),
    Output("job-id", "data", allow_duplicate=True),
    Output("poll", "disabled", allow_duplicate=True),
    Output("members", "rowData"),
    Output("members", "columnDefs", allow_duplicate=True),
    Output("members", "selectedRows", allow_duplicate=True),
    Output("members", "dashGridOptions"),
    Output("members", "style"),
    Input("upload", "contents"),
    State("upload", "filename"),
    State("lang", "value"),
    State("data-key", "data"),
    prevent_initial_call=True,
)
def _on_upload(contents, filename, lang, old_key):
    nu = no_update
    idle = (nu, True)
    if not contents:
        return (nu,) * 9 + (nu,) * 2 + (nu,) * 5
    _cache_drop(old_key)       # this browser replaces its report: free it, stop its jobs
    try:
        _header, b64 = contents.split(",", 1)
        if len(b64) * 3 / 4 > MAX_UPLOAD_MB * 2**20:
            raise ValueError(f"file is larger than {MAX_UPLOAD_MB:g} MB")
        data = load_report(base64.b64decode(b64))
    except Exception as exc:  # show any parse error to the user
        msg = html.Div([html.B(f"{t('error', lang)}: "), f"{filename} — {exc}"],
                       className="status-error")
        return ((None, msg, [], "report hidden", "upload upload-big", nu, nu, nu, nu) + idle
                + (nu,) * 5)
    key = _cache_put(filename or "report.csv", data)
    days = data.frame.index.normalize()
    first, last = days.min().date().isoformat(), days.max().date().isoformat()
    # estimate the allocation keys right away, so they can be checked before the recompute
    job = (_start_background("fit", key, [None] * len(data.dest_eans), 0.0, lang)
           if data.fmt == "all" else idle)
    many = len(data.dest_eans) > 12
    grid = (_member_rows(data), _member_columns(lang, data.fmt == "all"),
            {"ids": list(data.dest_eans)}, _grid_options(many),
            {"height": "440px"} if many else {"height": None})
    return (key, nu, _source_rows(data, lang), "report", "upload upload-small",
            first, last, last, last) + job + grid


@app.callback(
    Output({"type": "name", "ean": ALL}, "placeholder"),
    Output("members", "columnDefs"),
    Output("lbl-source", "children"),
    Output("lbl-dest", "children"),
    Output("lbl-dest-hint", "children"),
    Output("btn-all", "children"),
    Output("btn-none", "children"),
    Output("lbl-keys-hint", "children"),
    Output("btn-clear-keys", "children"),
    Input("lang", "value"),
    State({"type": "name", "ean": ALL}, "id"),
    State("data-key", "data"),
    prevent_initial_call=False,
)
def _panel_lang(lang, ids, key):
    entry = _cache_get(key)
    names = default_names(entry.data, lang) if entry else {}
    can_key = entry is None or entry.data.fmt == "all"
    return ([names.get(i["ean"], "") for i in ids],
            _member_columns(lang, can_key),
            t("panel_source", lang), t("panel_dest", lang), t("panel_dest_hint", lang),
            t("all", lang), t("none", lang), t("keys_hint", lang), t("clear_keys", lang))


@app.callback(
    Output("members", "selectedRows"),
    Input("btn-all", "n_clicks"),
    Input("btn-none", "n_clicks"),
    State("data-key", "data"),
    prevent_initial_call=True,
)
def _all_none(_a, _n, key):
    entry = _cache_get(key)
    if entry is None:
        raise dash.exceptions.PreventUpdate
    if ctx.triggered_id == "btn-all":
        return {"ids": list(entry.data.dest_eans)}
    return []


@app.callback(
    Output("members", "rowTransaction"),
    Input("btn-clear-keys", "n_clicks"),
    State("members", "rowData"),
    State("data-key", "data"),
    prevent_initial_call=True,
)
def _reset_keys(n, rows, key):
    """Put the estimated keys back (after manual edits)."""
    entry = _cache_get(key)
    if not n or entry is None or entry.fit is None:
        raise dash.exceptions.PreventUpdate
    by_ean = dict(zip(entry.data.dest_eans, entry.fit.keys))
    return {"update": [dict(r, key=_pct_key(by_ean[r["ean"]])) for r in rows or []
                       if r.get("ean") in by_ean]}


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
    State("members", "rowData"),
    State("reserve", "value"),
    State("lang", "value"),
    prevent_initial_call=True,
)
def _start_job(n, key, rows, reserve, lang):
    if not n:
        raise dash.exceptions.PreventUpdate
    entry = _cache_get(key)
    if entry is None:   # server restarted / went to sleep since the upload
        return (no_update, True, False, "progress error", {"width": "0%"},
                t("session_lost", lang))
    if entry.data.fmt != "all":
        return (no_update, True, False, "progress error", {"width": "0%"},
                t("part_no_recompute", lang))
    keys = _keys_from_rows(entry.data, rows)
    reserve = min(max(float(reserve or 0), 0.0), 100.0) / 100
    job_id, poll_off = _start_background("recompute", key, keys, reserve, lang)
    nu = no_update
    return job_id, poll_off, True, nu, nu, nu        # the poll draws the bar


@app.callback(
    Output("poll", "disabled", allow_duplicate=True),
    Output("btn-recompute", "disabled", allow_duplicate=True),
    Output("progress", "className", allow_duplicate=True),
    Output("progress-bar", "style", allow_duplicate=True),
    Output("progress-text", "children", allow_duplicate=True),
    Output("result-rev", "data"),
    Input("poll", "n_intervals"),
    State("job-id", "data"),
    State("result-rev", "data"),
    State("lang", "value"),
    prevent_initial_call=True,
)
def _poll(_n, job_id, rev, lang):
    nu = no_update
    job = _JOBS.get(job_id or "")
    if job is not None:
        job["seen"] = time.perf_counter()          # the page is alive
    if job is None:
        # The job is not in this process: the server restarted / went to sleep, or
        # (misconfigured) another worker answered. Never leave the button dead.
        if not job_id:
            return True, False, nu, nu, nu, nu
        return (True, False, "progress error", {"width": "0%"}, t("job_lost", lang), nu)
    if job.get("final") is not None:
        # Idempotent: the interval may fire again before the first "done" response
        # arrives, and Dash then drops that first response as outdated - so every
        # later poll repeats the complete final state instead of no_update.
        return job["final"]
    elapsed = time.perf_counter() - job["t0"]
    if not job["done"]:
        phase = job["phase"]
        if phase == "queued":
            return (False, True, "progress running", {"width": "0%"},
                    f"{t('queued', lang)}…", nu)
        label = t("phase_fit" if phase == "fit" else "phase_compute", lang)
        frac = job["frac"]
        if job.get("had_fit"):                     # fit and compute in one recompute job
            frac = 0.6 * frac if phase == "fit" else 0.6 + 0.4 * frac
        entry = _cache_get(job["data_key"])
        extra = ""
        if phase == "compute" and entry is not None:
            n_iv = entry.data.n_rows
            extra = f" · {fmt_num(job['frac'] * n_iv, lang)} / {fmt_num(n_iv, lang)}"
        text = f"{label}… {fmt_pct(100 * frac, lang, 0)}{extra} · {fmt_duration(elapsed, lang)}"
        return (False, True, "progress running", {"width": f"{100 * frac:.1f}%"}, text, nu)
    job["reported"] = True
    if job.get("error_key") or job["error"]:
        msg = (t(job["error_key"], lang) if job.get("error_key")
               else f"{t('phase_error', lang)}: {job['error']}")
        job["final"] = (True, False, "progress error", {"width": "100%"}, msg, nu)
        return job["final"]
    text = f"✓ {fmt_duration(elapsed, lang)}"
    job["final"] = (True, False, "progress done", {"width": "100%"}, text, (rev or 0) + 1)
    return job["final"]


# ---------------------------------------------------------------------------
# Key estimate: summary in the recompute card, range per key, "keys changed"
# ---------------------------------------------------------------------------


@app.callback(
    Output("fit-info", "children"),
    Output("members", "rowTransaction", allow_duplicate=True),
    Input("result-rev", "data"),
    Input("lang", "value"),
    Input("data-key", "data"),
    State("members", "rowData"),
    prevent_initial_call="initial_duplicate",
)
def _fit_info(_rev, lang, key, rows):
    """Summary of the key estimate; per member: estimated key into empty key cells,
    consistency range as tooltip, warning mark where the report cannot pin it down."""
    entry = _cache_get(key)
    if entry is None or entry.fit is None or not rows:
        return [], no_update
    fit = entry.fit
    rounds = lambda r: t(f"rounds_{r}", lang)  # noqa: E731
    other = "".join(t("fit_other", lang).format(rounds=rounds(r), pct=fmt_pct(100 * m, lang))
                    for r, m in fit.tried.items() if r != fit.rounds)
    summary = t("fit_summary", lang).format(
        rounds=rounds(fit.rounds), pct=fmt_pct(100 * fit.match, lang), other=other,
        secs=fmt_duration(fit.seconds, lang))
    idx = {e: i for i, e in enumerate(entry.data.dest_eans)}
    update, wide = [], False
    for r in rows:
        i = idx.get(r.get("ean"))
        if i is None:
            continue
        status = fit.status[i]
        lo, hi = fit.ranges[i] if i < len(fit.ranges) else (fit.keys[i], fit.keys[i])
        warn, text = False, ""
        if status == "no_data":
            warn, text = True, t("key_nodata", lang)
        elif status == "zero":
            text = t("key_zero", lang).format(hi=fmt_num(100 * hi, lang, 2))
        elif status == "always_covered" or hi >= 0.999:
            warn, text = True, t("key_lower", lang).format(lo=fmt_num(100 * lo, lang, 2))
        elif hi - lo > max(0.002, 0.05 * fit.keys[i]):   # > 0.2 pp or 5 % of the key
            warn = True
            text = t("key_range", lang).format(lo=fmt_num(100 * lo, lang, 2),
                                               hi=fmt_num(100 * hi, lang, 2))
        else:
            text = t("key_range", lang).format(lo=fmt_num(100 * lo, lang, 2),
                                               hi=fmt_num(100 * hi, lang, 2))
        wide = wide or warn
        key_val = r.get("key") if r.get("key") not in (None, "") else _pct_key(fit.keys[i])
        update.append(dict(r, key=key_val, range=text, warn=warn))
    notes = [html.P([html.B(f"{t('fit_title', lang)}: "), summary], className="fit-line")]
    if fit.match < 0.95:
        notes.append(html.P(t("fit_low", lang), className="stale"))
    elif fit.rough:
        notes.append(html.P(t("fit_rough", lang), className="hint"))
    elif wide:
        notes.append(html.P(t("fit_check", lang), className="hint"))
    return notes, {"update": update}


@app.callback(
    Output("stale", "children"),
    Input("members", "cellValueChanged"),
    Input("members", "rowData"),
    Input("reserve", "value"),
    Input("result-rev", "data"),
    Input("lang", "value"),
    State("data-key", "data"),
)
def _stale(_changed, rows, reserve, _rev, lang, key):
    """"Keys changed since the last recompute" - a tiny callback, so typing a key
    no longer re-renders every figure."""
    entry = _cache_get(key)
    if entry is None or entry.exact is None:
        return []
    exact = entry.exact
    cur = _keys_from_rows(entry.data, rows)
    cur_res = min(max(float(reserve or 0), 0.0), 100.0) / 100
    changed = (any(k is not None and abs(k - u) > 1e-6 for k, u in zip(cur, exact.keys))
               or abs(cur_res - exact.reserve) > 1e-9)
    return html.P(t("stale", lang), className="stale") if changed else []


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


def _cell(text, cls: str = "", title: str = "") -> str:
    attrs = (f' class="{cls}"' if cls else "") + (f' title="{esc(title)}"' if title else "")
    return f"<td{attrs}>{text}</td>"


def _name_cell(name: str, ean: str, colour: str) -> str:
    return _cell(f'<div><span class="swatch" style="background:{esc(colour)}"></span>'
                 f'{esc(name)}</div><div class="mono sub-ean">{esc(ean)}</div>', "name")


def _html_table(head: list[str], rows: list[tuple[str, str]], foot: str) -> dcc.Markdown:
    """One component for the whole table. As Dash html.* elements a table of 150
    members is ~5 000 React components and takes seconds to render in the browser."""
    thead = "".join(f"<th>{esc(h)}</th>" for h in head)
    tbody = "".join(f'<tr class="{cls}">{cells}</tr>' for cls, cells in rows)
    markup = (f'<table class="tbl"><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody>'
              f"<tfoot><tr>{foot}</tr></tfoot></table>")
    return dcc.Markdown(markup, dangerously_allow_html=True, className="tbl-md")


def _dest_table(data: SharingData, enabled: set[str], names: dict, lang: str, top=None):
    df = per_destination(data)
    cmap = colour_map(data, top)
    is_all = data.fmt == "all"
    head = [f"{t('col_name', lang)} / {t('col_ean', lang)}"]
    if is_all:
        head += [t("col_consumption", lang), t("col_shared", lang), t("col_unmet", lang),
                 t("col_coverage", lang)]
    else:
        head += [t("col_shared", lang)]
    head += [t("col_share", lang), t("col_data", lang)]

    rows = []
    for r in df.itertuples():
        cells = _name_cell(names[r.ean], r.ean, cmap[r.ean])
        if is_all:
            cells += (_cell(fmt_num(r.consumption, lang, 1), "num")
                      + _cell(fmt_num(r.shared, lang, 1), "num")
                      + _cell(fmt_num(r.unmet, lang, 1), "num")
                      + _cell(fmt_pct(r.coverage_pct, lang), "num"))
        else:
            cells += _cell(fmt_num(r.shared, lang, 1), "num")
        cells += (_cell(fmt_pct(r.share_of_shared_pct, lang), "num")
                  + _cell(f'{fmt_date(r.first_data, lang)}<span class="muted"> '
                          f'({fmt_pct(r.data_pct, lang, 0)})</span>', "num",
                          t("col_data_pct", lang)))
        rows.append(("" if r.ean in enabled else "off", cells))

    b = lambda x: f"<b>{x}</b>"  # noqa: E731
    foot = _cell(b("Σ"))
    if is_all:
        c, sh, u = df["consumption"].sum(), df["shared"].sum(), df["unmet"].sum()
        foot += (_cell(b(fmt_num(c, lang, 1)), "num") + _cell(b(fmt_num(sh, lang, 1)), "num")
                 + _cell(b(fmt_num(u, lang, 1)), "num")
                 + _cell(b(fmt_pct(100 * sh / c if c else None, lang)), "num"))
    else:
        foot += _cell(b(fmt_num(df["shared"].sum(), lang, 1)), "num")
    foot += _cell(b(fmt_pct(100.0, lang)), "num") + _cell("")
    return _html_table(head, rows, foot)


def _cmp_table(data: SharingData, exact: Recomputed, enabled: set[str], names: dict, lang: str,
               top=None):
    a = per_destination(data).set_index("ean")
    bb = per_destination(exact.data).set_index("ean")
    keys = dict(zip(data.dest_eans, exact.keys))
    ksum = sum(exact.keys) or 1.0
    cmap = colour_map(data, top)
    head = [f"{t('col_name', lang)} / {t('col_ean', lang)}", t("cmp_key", lang),
            t("col_consumption", lang), t("cmp_shared_edc", lang), t("cmp_shared_exact", lang),
            t("cmp_delta", lang), t("cmp_delta_pct", lang), t("cmp_cov", lang)]
    cov = lambda x, dem: fmt_pct(100 * x / dem if dem else None, lang)  # noqa: E731
    rows = []
    for e in data.dest_eans:
        sa, sb, dem = a.at[e, "shared"], bb.at[e, "shared"], a.at[e, "consumption"]
        d = sb - sa
        rows.append(("" if e in enabled else "off",
                     _name_cell(names[e], e, cmap[e])
                     + _cell(f'{fmt_pct(100 * keys[e], lang, 1)}<span class="muted"> '
                             f'({fmt_pct(100 * keys[e] / ksum, lang, 1)})</span>', "num")
                     + _cell(fmt_num(dem, lang, 1), "num")
                     + _cell(fmt_num(sa, lang, 1), "num")
                     + _cell(f"<b>{fmt_num(sb, lang, 1)}</b>", "num")
                     + _cell(fmt_signed(d, lang), "num pos" if d > 0.05 else "num")
                     + _cell(fmt_pct(100 * d / sb, lang) if sb else "—", "num")
                     + _cell(f"{cov(sa, dem)} → {cov(sb, dem)}", "num")))
    sa, sb, dem = a["shared"].sum(), bb["shared"].sum(), a["consumption"].sum()
    b = lambda x: f"<b>{x}</b>"  # noqa: E731
    foot = (_cell(b("Σ")) + _cell(b(fmt_pct(100 * sum(exact.keys), lang, 1)), "num")
            + _cell(b(fmt_num(dem, lang, 1)), "num") + _cell(b(fmt_num(sa, lang, 1)), "num")
            + _cell(b(fmt_num(sb, lang, 1)), "num") + _cell(b(fmt_signed(sb - sa, lang)), "num pos")
            + _cell(b(fmt_pct(100 * (sb - sa) / sb if sb else None, lang)), "num")
            + _cell(b(f"{cov(sa, dem)} → {cov(sb, dem)}"), "num"))
    return [_html_table(head, rows, foot),
            html.P(t("cmp_error_hint", lang), className="hint")]


def _timing(exact: Recomputed, data: SharingData, names: dict, lang: str) -> list:
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
    loss = grid_loss(data, exact.data)
    if loss.negligible:
        loss_box = html.Div(className="loss-box ok", children=[
            html.Div(t("loss_title", lang), className="loss-title"),
            html.Div(t("loss_none", lang), className="loss-text")])
    else:
        loss_box = html.Div(className="loss-box", children=[
            html.Div([html.Span(fmt_pct(loss.pct_of_max, lang, 1), className="loss-pct"),
                      html.Span(t("loss_title", lang), className="loss-title")]),
            html.Div(t("loss_text", lang).format(
                max=fmt_num(loss.shared_exact, lang, 1), edc=fmt_num(loss.shared_edc, lang, 1),
                kwh=fmt_num(loss.lost, lang, 1)), className="loss-text")])
    out = [
        loss_box,
        html.H3(t("timing_title", lang), className="sub-title"),
        stats,
        html.P([html.B(f"{t('keys_used', lang)} ({src}): "), key_txt,
                f" ({t('keys_sum', lang)} {fmt_pct(100 * sum(exact.keys), lang, 1)}){reserve}"],
               className="keys-line"),
        html.P(t("edc_check", lang).format(rounds=t(f"rounds_{exact.rounds}", lang),
                                           pct=fmt_pct(100 * exact.edc_match, lang, 1)),
               className="hint"),
    ]
    return out


def _align_overview(fa, fb) -> None:
    hi = max(fa.layout.xaxis.range[1], fb.layout.xaxis.range[1])
    for f in (fa, fb):
        f.update_xaxes(range=[0, hi])


def _align_daily(fa, fb) -> None:
    if not fa.data or not fb.data:
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
    Input("members", "selectedRows"),
    Input("members", "cellValueChanged"),
    Input({"type": "name", "ean": ALL}, "value"),
    Input("lang", "value"),
    Input("group", "value"),
    Input("heat-metric", "value"),
    Input("theme", "data"),
    State({"type": "name", "ean": ALL}, "id"),
    State("members", "rowData"),
    State("day-picker", "date"),
    prevent_initial_call="initial_duplicate",
)
def _render(key, _rev, selected, _changed, name_values, lang, group,
            heat_metric, theme_name, name_ids, rows, sel_day):
    if _key_only_edit():
        raise dash.exceptions.PreventUpdate      # a key cell changed: figures unaffected
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

    enabled = _enabled(data, selected)
    names = effective_names(data, lang, name_ids, name_values, rows)
    th = theme(theme_name)
    opts = dict(lang=lang, th=th)
    h = lambda fig: {"height": f"{fig.layout.height}px"} if fig else {}  # noqa: E731

    df = filter_dests(data, enabled)
    opts["top"] = top_dests(df, data)      # >10 destinations: fold the rest (same in both)
    ov_a = fig_total_by_flow(df, data, names, **opts)
    sel_day = _day(sel_day)
    dy_a = fig_daily(df, data, names, sel_day=sel_day, **opts)
    has_grid = data.fmt == "all"
    pie_a = fig_wasted_pie(compute_wasted_split(df), lang, th) if has_grid else {}

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
        dy_b = fig_daily(df_b, exact.data, names, sel_day=sel_day, **opts)
        pie_b = fig_wasted_pie(compute_wasted_split(df_b), lang, th)
        _align_overview(ov_a, ov_b)
        _align_daily(dy_a, dy_b)
        b = (_tiles(exact.data, enabled, lang, ref=data), ov_b, dy_b, pie_b,
             h(ov_b), h(dy_b), h(pie_b), {}, _cmp_table(data, exact, enabled, names, lang, opts["top"]),
             _timing(exact, data, names, lang))
        mode = "compare dual"
        # keep paired graphs the same height
        for fa, fb in ((ov_a, ov_b),):
            hh = max(fa.layout.height, fb.layout.height)
            fa.update_layout(height=hh)
            fb.update_layout(height=hh)
        b = (b[0], ov_b, dy_b, pie_b, h(ov_b), h(dy_b), h(pie_b), *b[7:])

    # heatmap: total production or total consumption (part report: shared); in dual
    # mode both reports share one colour scale
    metrics = heat_metrics(data)
    metric = heat_metric if heat_metric in metrics else metrics[0]
    pv_a = heat_pivot(data, enabled, metric)
    pv_b = heat_pivot(exact.data, enabled, metric) if exact else None
    zs = [float(np.nanmax(p.to_numpy())) for p in (pv_a, pv_b)
          if p is not None and not p.empty]
    z_max = max(zs) if zs else None
    ht_a = fig_heatmap(pv_a, metric, z_max=z_max, lang=lang, th=th)
    ht_b = fig_heatmap(pv_b, metric, z_max=z_max, lang=lang, th=th) if exact else {}

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
        _dest_table(data, enabled, names, lang, opts["top"]),
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
                line: {color: (fig.layout.meta && fig.layout.meta.marker) || 'black',
                       width: 1.5, dash: 'dash'}, layer: 'above'}]});
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
    Input("members", "selectedRows"),
    Input("members", "cellValueChanged"),
    Input({"type": "name", "ean": ALL}, "value"),
    Input("lang", "value"),
    Input("theme", "data"),
    State({"type": "name", "ean": ALL}, "id"),
    State("members", "rowData"),
)
def _hourly(day, key, _rev, selected, _changed, name_values, lang,
            theme_name, name_ids, rows):
    """Subplot 4: one day in 15-min steps; y axis fixed over the whole period (and
    shared by both reports) so days and methods compare on one scale."""
    if _key_only_edit():
        raise dash.exceptions.PreventUpdate
    entry = _cache_get(key)
    if entry is None or not day:
        return {}, {}, {}, {}
    data = entry.data
    enabled = _enabled(data, selected)
    names = effective_names(data, lang, name_ids, name_values, rows)
    frames = [filter_dests(data, enabled)]
    if entry.exact is not None:
        frames.append(filter_dests(entry.exact.data, enabled))
    y_max = max(intraday_ymax(f) for f in frames)
    opts = dict(y_max=y_max, lang=lang, th=theme(theme_name),
                top=top_dests(frames[0], data))
    fa = fig_intraday(frames[0], data, names, _day(day), **opts)
    style = {"height": f"{fa.layout.height}px"}
    if entry.exact is None:
        return fa, style, {}, {}
    fb = fig_intraday(frames[1], entry.exact.data, names, _day(day), **opts)
    return fa, style, fb, style


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="EDC sharing report web app")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    app.run(host=a.host, port=a.port, debug=a.debug)
