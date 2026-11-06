"""Callbacks of the export section in the panel: the summary as an Excel workbook
(:mod:`export`) and printing the page (to paper or PDF, in the light theme)."""

from __future__ import annotations

from urllib.parse import quote

import dash
from dash import Input, Output, State, callback, clientside_callback

import export
import store
from i18n import t

from . import members
from .spot import comparison


@callback(Output("export-full-ean", "options"), Input("lang", "value"))
def _full_ean_label(lang):
    return [{"label": t("x_full_ean", lang), "value": "full"}]


def summary_file(key, selected, rows, src_rows, lang, group, full_ean,
                 pair_rows=None, spot_inputs=None) -> str | None:
    """Prepare the workbook of the report ``key`` for this selection; return the link to
    download it (None when the report is gone). ``spot_inputs``: (default feed-in,
    default supplier price, fee, curtail) as typed, for the spot sheet."""
    entry = store.get(key)
    if entry is None:
        return None
    data = entry.data
    group = (group or "").strip()
    pairs = None
    if len(data.source_eans) > 1 and pair_rows:
        pairs = members.merged_pair_keys(members.pair_keys(data, pair_rows), entry.fit)
    spot_cmp = None
    if entry.spot is not None and data.fmt == "all":
        spot_cmp = comparison(entry, rows, src_rows, *(spot_inputs or (None, None, None, None)))
    content = export.summary_xlsx(
        entry, members.enabled(data, selected), members.names(data, lang, src_rows, rows),
        lang, group=group, full_ean="full" in (full_ean or []), pair_keys=pairs,
        spot_cmp=spot_cmp)
    name = export.file_name(data, lang, group)
    return f"/export/{store.put_file(name, content)}/{quote(name)}"


@callback(
    Output("export-url", "data"),
    Input("btn-export", "n_clicks"),
    State("data-key", "data"),
    State("members", "selectedRows"),
    State("members", "rowData"),
    State("producers", "rowData"),
    State("lang", "value"),
    State("group", "value"),
    State("export-full-ean", "value"),
    State("pair-keys", "rowData"),
    State("feed-in", "value"),
    State("price-default", "value"),
    State("spot-fee", "value"),
    State("spot-curtail", "value"),
    prevent_initial_call=True,
)
def download_summary(n, key, selected, rows, src_rows, lang, group, full_ean, pair_rows=None,
                     feed_in=None, default=None, fee=None, curtail=None):
    url = (summary_file(key, selected, rows, src_rows, lang, group, full_ean, pair_rows,
                        (feed_in, default, fee, curtail)) if n else None)
    if url is None:
        raise dash.exceptions.PreventUpdate
    return url


# The download itself is an ordinary link to the file on the server (Content-Disposition:
# attachment, the xlsx MIME type), so the browser saves it under its name with the
# extension. A blob saved from script lost the name on Safari and on phones.
clientside_callback(
    """
    function(url) {
        if (url) {
            const a = document.createElement('a');
            a.href = url;
            a.download = decodeURIComponent(url.split('/').pop());
            document.body.appendChild(a);
            a.click();
            a.remove();
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("btn-export", "title"),
    Input("export-url", "data"),
    prevent_initial_call=True,
)


# Print: the figures are drawn for the current theme, and a dark page prints badly (light
# text, no background), so a dark page switches to light, waits until the figures are
# redrawn, prints, and switches back; the saved theme choice is restored as it was.
clientside_callback(
    """
    function(n) {
        const nu = window.dash_clientside.no_update;
        if (!n) { return nu; }
        const root = document.documentElement;
        const btn = document.getElementById('theme-btn');
        if (root.dataset.theme !== 'dark' || !btn) { window.print(); return nu; }
        let saved = null;
        try { saved = window.localStorage.getItem('theme-pref'); } catch (e) {}
        window.addEventListener('afterprint', function () {
            btn.click();
            setTimeout(function () {
                try {
                    if (saved === null) { window.localStorage.removeItem('theme-pref'); }
                    else { window.localStorage.setItem('theme-pref', saved); }
                } catch (e) {}
            }, 0);
        }, {once: true});
        btn.click();
        const t0 = Date.now();
        (function wait() {
            const busy = document.querySelector('[data-dash-is-loading="true"]');
            const waited = Date.now() - t0;
            if ((!busy && waited > 600) || waited > 8000) { window.print(); }
            else { setTimeout(wait, 150); }
        })();
        return nu;
    }
    """,
    Output("btn-print", "title"),
    Input("btn-print", "n_clicks"),
    prevent_initial_call=True,
)
