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
import io

import dash
from flask import Response, request, send_file, send_from_directory

import clanek
import config
import export
import jobs
import store
import ui.compute
import ui.export
import ui.panel
import ui.report
import ui.spot
from ui.layout import INDEX_STRING, layout

#: importing a ui module registers its callbacks (``dash.callback``)
CALLBACK_MODULES = (ui.panel, ui.compute, ui.report, ui.export, ui.spot)

app = dash.Dash(__name__, title="EDC sharing report", suppress_callback_exceptions=True)
server = app.server  # for gunicorn: gunicorn app:server -c gunicorn.conf.py
# base64 upload inflates the file by 4/3; leave headroom for the rest of the request
server.config["MAX_CONTENT_LENGTH"] = int((config.MAX_UPLOAD_MB * 1.4 + 2) * 2**20)
app.index_string = INDEX_STRING
app.layout = layout()


@server.route("/clanek/", defaults={"lang": "cs"})
@server.route("/clanek/<any(en,de):lang>/")
def _article(lang: str):
    """The explanatory article in ``lang``, assembled from clanek/ on every request."""
    return Response(clanek.render(lang), mimetype="text/html")


@server.route("/clanek/img/<path:name>", defaults={"lang": "cs"})
@server.route("/clanek/<any(en,de):lang>/img/<path:name>")
def _article_img(lang: str, name: str):
    return send_from_directory(clanek.img_dir(lang), name)


@server.route("/favicon.ico")
def _favicon():
    """The icon where browsers look by default (the article pages have no icon link)."""
    return send_from_directory(app.config.assets_folder, "favicon.ico")


@server.route("/export/<token>/<path:name>")
def _export_file(token: str, name: str):
    """A summary prepared by the export button (:func:`store.put_file`), as an attachment
    under its own name, so the browser keeps the .xlsx extension."""
    f = store.get_file(token)
    if f is None:
        return Response("Export expired, please download it again.", 404,
                        mimetype="text/plain")
    return send_file(io.BytesIO(f.content), mimetype=export.XLSX_MIME, as_attachment=True,
                     download_name=f.name, max_age=0)


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
