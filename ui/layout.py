"""The page: top bar, upload, the side panel and the report.

The report has three tabs next to the panel. **Sharing**: the report's facts and the
card of the exact static method; **Billing**: the card of the billing by contribution
(:func:`job_card` both). The two tabs share two columns: the EDC report on the left, the
tab's computation on the right (the exact method, or the billing). Paired cards of the
two columns share CSS grid rows (see ``.compare.dual`` in ``assets/style.css``). **Spot
market**: the surplus sold on the OTE day-ahead market instead of shared (a card that
fetches the prices, tiles, figures, a table).
"""

from __future__ import annotations

import dash_ag_grid as dag
from dash import dcc, html

from i18n import LANG_LABELS, t

from . import members

GRAPH_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "toImageButtonOptions": {"format": "png", "scale": 2},
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}

#: the computations with a card, a progress bar and a result revision counter
JOB_KINDS = ("exact", "bill", "spot")
#: the tabs of the report
TABS = ("sharing", "bill", "spot")
#: the figures of the spot tab
SPOT_FIGURES = ("parties", "mix", "members", "daily", "hourly", "monthly")
#: figures that appear in both columns, in row order; "fig-<name>" left, "fig-<name>-b" right
PAIRED_FIGURES = ("overview", "pie", "daily", "hourly", "heat")


# explanatory article on the exact static method and the pool mode (cs/en/de), see clanky/
ARTICLE_URL = "/clanky/do-posledni-kwh/"


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


def job_card(kind: str, inputs: list, results: list, link: str | None = None,
             button: bool = True) -> html.Section:
    """A card that starts a computation: title, description (with an optional link to an
    explanatory text), the button and its inputs, a progress bar, then the results.
    ``button=False``: the job starts by itself (the button stays, hidden, for the job's
    callbacks)."""
    ids = job_ids(kind)
    return html.Section(id=f"{kind}-card", className="card job-card", children=[
        dcc.Store(id=ids["job"]),
        dcc.Store(id=ids["rev"], data=0),
        dcc.Interval(id=ids["poll"], interval=200, disabled=True),
        html.H2(id=ids["title"]),
        html.P(id=ids["desc"], className="hint"),
        *([html.P(className="hint article-link", children=html.A(
            id=f"{kind}-article", href=link, target="_blank", rel="noopener"))] if link else []),
        html.Div(className="rc-row", children=[
            html.Button(id=ids["btn"], n_clicks=0, className="btn-primary",
                        style=None if button else {"display": "none"}), *inputs]),
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


def _pair_box() -> html.Div:
    """Several producers: the key of every pair producer -> member, as set in EDC."""
    return html.Div(id="pair-box", className="pair-box", style={"display": "none"}, children=[
        html.H3(id="pair-title", className="sub-title"),
        html.P(id="pair-hint", className="hint"),
        _grid("pair-keys", [], members.pair_options()),
    ])


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
        html.Section(className="panel-section export-section", children=[
            html.H3(id="lbl-export"),
            html.Div(className="export-row", children=[
                html.Button(id="btn-export", n_clicks=0, className="btn-primary"),
                html.Button(id="btn-print", n_clicks=0, className="mini"),
            ]),
            dcc.Checklist(id="export-full-ean", options=[{"label": "", "value": "full"}],
                          value=[], className="checks"),
            html.P(id="lbl-export-hint", className="hint"),
            dcc.Store(id="export-url"),
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


def spot_fig_id(name: str) -> str:
    return f"fig-spot-{name}"


def _spot_bill_progress() -> html.Div:
    """The billing's progress, mirrored from the billing card on the billing tab (the
    spot card's button starts the billing too)."""
    return html.Div(id="spot-bill-progress", className="progress idle", children=[
        html.Div(className="progress-track", children=html.Div(
            id="spot-bill-bar", className="progress-bar", style={"width": "0%"})),
        html.Div(id="spot-bill-text", className="progress-text"),
    ])


def _spot_pane() -> html.Div:
    """The spot tab: the card that fetches the prices when the tab opens (no button), with
    the trader's fee, the curtailment switch and the default prices (the same as in the
    billing card), and the button of the billing by contribution, which who gets what
    needs: always there, enabled only when the billing is missing or was computed with
    other prices. Then the comparison."""
    curtail = dcc.Checklist(id="spot-curtail", options=[{"label": "", "value": "on"}],
                            value=[], className="checks")
    return html.Div(id="pane-spot", className="pane", style={"display": "none"}, children=[
        job_card("spot", [html.Button(id="spot-bill-btn", n_clicks=0, className="btn-primary",
                                      disabled=True),
                          _number_input("spot-fee", "lbl-spot-fee", value="0"),
                          _number_input("spot-feed-in", "lbl-spot-feed-in"),
                          _number_input("spot-price-default", "lbl-spot-price-default"),
                          curtail],
                 [dcc.Store(id="spot-bill-need", data=False), html.Div(id="spot-info"),
                  _spot_bill_progress()], button=False),
        html.Div(id="spot-body", className="spot-body", style={"display": "none"}, children=[
            html.Section(className="card tiles-card", children=[
                html.Div(id="spot-verdict"), html.Div(id="spot-tiles")]),
            _graph(spot_fig_id("parties"), "spot-parties-card"),
            _graph(spot_fig_id("mix"), "spot-mix-card"),
            _graph(spot_fig_id("members"), "spot-members-card"),
            _graph(spot_fig_id("daily"), "spot-daily-card daily-card"),
            _graph(spot_fig_id("hourly"), "spot-hourly-card"),
            _graph(spot_fig_id("monthly"), "spot-monthly-card"),
            html.Section(className="card table-card", children=[
                html.H2(id="spot-table-title"), html.Div(id="spot-table", className="table-wrap")]),
        ]),
    ])


def _tabs() -> dcc.Tabs:
    return dcc.Tabs(id="tabs", value="sharing", className="tabs", parent_className="tabs-parent",
                    content_className="tabs-content", children=[
                        dcc.Tab(id=f"tab-{name}", value=name, className="tab",
                                selected_className="tab--selected") for name in TABS])


def _report() -> html.Div:
    return html.Div(id="report", className="report hidden", children=[
        _panel(),
        html.Main(className="main", children=[
            _tabs(),
            html.Div(id="pane-sharing", className="pane", children=_sharing_pane()),
            html.Div(id="pane-bill", className="pane", style={"display": "none"},
                     children=_bill_pane()),
            html.Div(id="pane-columns", className="pane", children=_columns()),
            _spot_pane(),
        ]),
    ])


def _sharing_pane() -> list:
    """The sharing tab above the columns: the report's facts, the exact method's card."""
    return [
        html.Section(className="card", children=[
            html.H2(id="info-title"), html.Div(id="info"), html.Div(id="notes")]),
        job_card("exact", [_number_input("reserve", "lbl-reserve", value="0")],
                 [html.Div(id="exact-pool"), _pair_box(), html.Div(id="fit-info"),
                  html.Div(id="exact-stale"),
                  html.Div(id="exact-result")], link=ARTICLE_URL),
    ]


def _bill_pane() -> list:
    """The billing tab above the columns: the card of the billing by contribution."""
    return [
        job_card("bill", [_number_input("feed-in", "lbl-feed-in"),
                          _number_input("price-default", "lbl-price-default")],
                 [html.Div(id="bill-stale"), html.Div(id="bill-result")]),
    ]


def _columns() -> list:
    """The two columns of the sharing and billing tabs, and the full-width table of
    the tab's computation below them."""
    return [
        html.Div(id="compare", className="compare single",
                 children=[_column("a"), _column("b")]),
        _wide_card("cmp"),          # exact method: EDC vs exact per destination
        _wide_card("settle"),       # billing: settlement per member
    ]


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
                               options=[{"label": label, "value": code}
                                        for code, label in LANG_LABELS.items()]),
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
        # (unmount) it while the upload callback runs and drop updates arriving meanwhile.
        # The report's render may write the status too (session lost): delay_show keeps
        # the status line from blinking to the spinner on every quick re-render.
        dcc.Loading(type="dot", color="#339933", target_components={"upload-status": "children"},
                    delay_show=500, children=html.Div(id="upload-status", className="status")),
        _report(),
    ])


#: the page before its first paint: apply the saved or the system theme (no light flash).
#: The icon (assets/favicon.*) replaces Dash's {%favicon%}: browsers take the SVG, the
#: sizes on the ICO keep Chrome from preferring it.
#: The meta app-version is the code version the page was served with (app.VERSION).
INDEX_STRING = """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        <meta name="app-version" content="__APP_VERSION__">
        <link rel="icon" href="/assets/favicon.ico" sizes="32x32">
        <link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
        <link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
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
