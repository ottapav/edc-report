"""The page: top bar, upload, the side panel and the report.

The report has two cards that start a computation (the exact static method and the
billing; :func:`job_card`), and two columns: the EDC report on the left, the exact
method or the billing on the right. Paired cards of the two columns share CSS grid rows
(see ``.compare.dual`` in ``assets/style.css``).
"""

from __future__ import annotations

import dash_ag_grid as dag
from dash import dcc, html

from i18n import t

from . import members

GRAPH_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "toImageButtonOptions": {"format": "png", "scale": 2},
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}

#: the computations with a card, a progress bar and a result revision counter
JOB_KINDS = ("exact", "bill")
#: figures that appear in both columns, in row order; "fig-<name>" left, "fig-<name>-b" right
PAIRED_FIGURES = ("overview", "pie", "daily", "hourly", "heat")


def job_ids(kind: str) -> dict[str, str]:
    """Component ids of a computation card."""
    return {part: f"{kind}-{part}" for part in
            ("btn", "job", "poll", "rev", "progress", "bar", "text", "title", "desc")}


def fig_id(name: str, side: str) -> str:
    return f"fig-{name}" if side == "a" else f"fig-{name}-b"


def _graph(id_: str, cls: str, card_id: str | None = None) -> html.Section:
    kw = {"id": card_id} if card_id else {}
    return html.Section(className=f"card {cls}", children=dcc.Graph(id=id_, config=GRAPH_CONFIG),
                        **kw)


def upload_content(lang: str, loaded: bool) -> html.Div:
    """Text inside the upload box: big prompt before a report is loaded, one line after."""
    if loaded:
        return html.Div([html.Span("⤒ "), t("upload_other", lang)],
                        className="upload-small-text")
    return html.Div([
        html.Div("⤒", className="upload-icon"),
        html.Div(t("upload_prompt", lang), className="upload-main"),
        html.Div(t("upload_hint", lang), className="upload-hint"),
    ])


def _number_input(id_: str, label_id: str, value=None) -> html.Label:
    """A number typed like the grid cells: decimal comma or point, applied on Enter or
    when the field loses focus."""
    return html.Label(className="reserve", children=[
        html.Span(id=label_id),
        dcc.Input(id=id_, type="text", inputMode="decimal", debounce=True, value=value,
                  autoComplete="off", className="num-in"),
    ])


def job_card(kind: str, inputs: list, results: list) -> html.Section:
    """A card that starts a computation: title, description, the button and its inputs,
    a progress bar, then the results."""
    ids = job_ids(kind)
    return html.Section(id=f"{kind}-card", className="card job-card", children=[
        dcc.Store(id=ids["job"]),
        dcc.Store(id=ids["rev"], data=0),
        dcc.Interval(id=ids["poll"], interval=200, disabled=True),
        html.H2(id=ids["title"]),
        html.P(id=ids["desc"], className="hint"),
        html.Div(className="rc-row", children=[
            html.Button(id=ids["btn"], n_clicks=0, className="btn-primary"), *inputs]),
        html.Div(id=ids["progress"], className="progress idle", children=[
            html.Div(className="progress-track", children=html.Div(
                id=ids["bar"], className="progress-bar", style={"width": "0%"})),
            html.Div(id=ids["text"], className="progress-text"),
        ]),
        *results,
    ])


def _grid(id_: str, columns: list, options: dict, **kw) -> dag.AgGrid:
    return dag.AgGrid(
        id=id_, rowData=[], columnDefs=columns, getRowId="params.data.ean",
        defaultColDef={"sortable": False, "resizable": False, "suppressMovable": True},
        dashGridOptions=options, className="members-grid", style={"height": None}, **kw)


def _panel() -> html.Aside:
    return html.Aside(className="panel", children=[
        html.Section(className="panel-section", children=[
            html.H3(id="lbl-source"),
            _grid("producers", members.producer_columns("cs"), members.producer_options()),
            html.P(id="lbl-source-hint", className="hint"),
        ]),
        html.Section(className="panel-section", children=[
            html.H3(id="lbl-dest"),
            html.P(className="hint", id="lbl-dest-hint"),
            _grid("members", members.columns("cs", True), members.options(False), selectedRows=[]),
            html.Div(className="keys-foot", children=[
                html.P(className="hint", id="lbl-keys-hint"),
                html.Button(id="btn-clear-keys", n_clicks=0, className="mini"),
            ]),
        ]),
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
    ])


def _column(side: str) -> html.Div:
    """One column of the report; the left one also has the per-destination table (shown
    while there is no right column)."""
    b = "" if side == "a" else "-b"
    cards = [
        html.H2(id=f"head-{side}", className=f"col-head col-head-{side}"),
        html.Section(className="card tiles-card", children=html.Div(id=f"tiles-{side}")),
        _graph(fig_id("overview", side), "overview-card"),
        _graph(fig_id("pie", side), "pie-card", card_id=f"pie-card{b}"),
        _graph(fig_id("daily", side), "daily-card"),
        _graph(fig_id("hourly", side), "hourly-card"),
        _graph(fig_id("heat", side), "heat-card"),
    ]
    if side == "a":
        cards.append(html.Section(className="card table-card", children=[
            html.H2(id="table-title"), html.Div(id="dest-table", className="table-wrap")]))
    return html.Div(className=f"col col-{side}", children=cards)


def _wide_card(id_: str) -> html.Section:
    """Full-width table below the columns."""
    return html.Section(id=f"{id_}-card", className="card cmp-card", style={"display": "none"},
                        children=[html.H2(id=f"{id_}-title"),
                                  html.Div(id=f"{id_}-table", className="table-wrap")])


def _report() -> html.Div:
    return html.Div(id="report", className="report hidden", children=[
        _panel(),
        html.Main(className="main", children=[
            html.Section(className="card", children=[
                html.H2(id="info-title"), html.Div(id="info"), html.Div(id="notes")]),
            job_card("exact", [_number_input("reserve", "lbl-reserve", value="0")],
                     [html.Div(id="fit-info"), html.Div(id="exact-stale"),
                      html.Div(id="exact-result")]),
            job_card("bill", [_number_input("feed-in", "lbl-feed-in"),
                              _number_input("price-default", "lbl-price-default")],
                     [html.Div(id="bill-stale"), html.Div(id="bill-result")]),
            # what the right column shows when both computations exist
            html.Div(id="right-view-box", className="right-view", style={"display": "none"},
                     children=[html.Span(id="lbl-right-view", className="field-label"),
                               dcc.RadioItems(id="right-view", value="exact", inline=True,
                                              className="seg")]),
            html.Div(id="compare", className="compare single",
                     children=[_column("a"), _column("b")]),
            _wide_card("cmp"),          # exact method: EDC vs exact per destination
            _wide_card("settle"),       # billing: settlement per member
        ]),
    ])


def layout() -> html.Div:
    return html.Div(className="page", children=[
        dcc.Store(id="theme-pref", storage_type="local"),   # "light" / "dark" / None = system
        dcc.Store(id="theme", data="light"),                 # resolved theme for the figures
        dcc.Store(id="data-key"),
        html.Header(className="topbar", children=[
            html.H1(id="page-title"),
            html.Div(className="lang", children=[
                html.Button("☾", id="theme-btn", n_clicks=0, className="icon-btn",
                            title="Tmavý režim"),
                dcc.RadioItems(id="lang", value="cs", inline=True, className="seg",
                               options=[{"label": "CZ", "value": "cs"},
                                        {"label": "EN", "value": "en"}]),
            ]),
        ]),
        dcc.Upload(
            id="upload", multiple=False, accept=".csv,text/csv", className="upload upload-big",
            # static content: the box is never empty, even before the label callback
            # answers; the callback replaces Upload.children as a whole (a nested
            # child's update was sometimes lost inside dcc.Upload)
            children=upload_content("cs", False),
        ),
        # spinner only next to the upload: wrapping the report in dcc.Loading would hide
        # (unmount) it while the upload callback runs and drop updates arriving meanwhile
        dcc.Loading(type="dot", color="#339933", target_components={"upload-status": "children"},
                    children=html.Div(id="upload-status", className="status")),
        _report(),
    ])


#: the page before its first paint: apply the saved or the system theme (no light flash)
INDEX_STRING = """<!DOCTYPE html>
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
