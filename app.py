"""EDC sharing report - Dash web app for the CSV sharing reports generated on edc-cr.cz
(the EDC portal).

Upload a report and see its sharing (facts, tiles, energy by flow, where the production
went, daily, hourly and hour × month plots, per-member table). Allocation keys are
estimated from the report right after the upload. Two computations run in the background
and are shown next to the report, card by card: the recompute with the exact static method
(``presna_staticka.rozdel``) and the billing of the shared electricity by the Shapley value
(``billing.py``).

Modules: :mod:`ui.layout` (the page), :mod:`ui.panel`, :mod:`ui.compute` and
:mod:`ui.report` (callbacks), :mod:`store` and :mod:`jobs` (server state), :mod:`figures`.

Run:  python app.py            (http://127.0.0.1:8050)
      python app.py --host 0.0.0.0 --port 8050 --debug
"""

from __future__ import annotations

import argparse
import hmac

import dash
from flask import Response, request, send_from_directory

import clanek
import config
import jobs
import store
import ui.compute
import ui.panel
import ui.report
from ui.layout import INDEX_STRING, layout

#: importing a ui module registers its callbacks (``dash.callback``)
CALLBACK_MODULES = (ui.panel, ui.compute, ui.report)

app = dash.Dash(__name__, title="EDC sharing report", suppress_callback_exceptions=True)
server = app.server  # for gunicorn: gunicorn app:server -c gunicorn.conf.py
# base64 upload inflates the file by 4/3; leave headroom for the rest of the request
server.config["MAX_CONTENT_LENGTH"] = int((config.MAX_UPLOAD_MB * 1.4 + 2) * 2**20)
app.index_string = INDEX_STRING
app.layout = layout()


@server.route("/clanek/")
def _article():
    """The explanatory article, assembled from clanek/ on every request."""
    return Response(clanek.render(), mimetype="text/html")


@server.route("/clanek/img/<path:name>")
def _article_img(name: str):
    return send_from_directory(clanek.IMG, name)


@server.route("/healthz")
def _healthz():
    return {"status": "ok", "cached_reports": store.size(), **jobs.stats()}


@server.before_request
def _basic_auth():
    """Optional HTTP basic auth, enabled when BASIC_AUTH_USER/PASSWORD are set."""
    if not (config.AUTH_USER and config.AUTH_PASSWORD) or request.path == "/healthz":
        return None
    auth = request.authorization
    if (auth and hmac.compare_digest(auth.username or "", config.AUTH_USER)
            and hmac.compare_digest(auth.password or "", config.AUTH_PASSWORD)):
        return None
    return Response("Authentication required", 401,
                    {"WWW-Authenticate": 'Basic realm="EDC sharing report"'})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="EDC sharing report web app")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    app.run(host=a.host, port=a.port, debug=a.debug)
