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
import hashlib
import hmac
import io
from pathlib import Path

import dash
from flask import Response, abort, redirect, request, send_file, send_from_directory

import clanky
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


def code_version(root: Path = Path(__file__).parent) -> str:
    """A hash of the app's code (Python modules, assets): it changes with a deploy that
    changes the app, not with one that only changes the docs."""
    h = hashlib.sha1()
    for path in sorted([*root.glob("*.py"), *root.glob("ui/*.py"), *root.glob("figures/*.py"),
                        *root.glob("assets/*")]):
        h.update(path.relative_to(root).as_posix().encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:12]


#: The page carries the version it was served with (a meta tag) and every response the
#: server's (X-App-Version). A page loaded before a deploy then calls callbacks the new
#: server may not have (a button does nothing), so assets/version.js offers a reload.
VERSION = code_version()

app = dash.Dash(__name__, title="EDC sharing report", suppress_callback_exceptions=True)
server = app.server  # for gunicorn: gunicorn app:server -c gunicorn.conf.py
# base64 upload inflates the file by 4/3; leave headroom for the rest of the request
server.config["MAX_CONTENT_LENGTH"] = int((config.MAX_UPLOAD_MB * 1.4 + 2) * 2**20)
app.index_string = INDEX_STRING.replace("__APP_VERSION__", VERSION)
app.layout = layout()


def _article_or_404(slug: str, lang: str) -> "clanky.Article":
    article = clanky.by_slug(slug)
    if article is None or lang not in article.langs:
        abort(404)
    return article


@server.route("/clanky/<slug>/", defaults={"lang": "cs"})
@server.route("/clanky/<slug>/<any(en,de):lang>/")
def _article(slug: str, lang: str):
    """An explanatory article in ``lang``, assembled from its folder in clanky/ on every
    request."""
    return Response(_article_or_404(slug, lang).render(lang), mimetype="text/html")


@server.route("/clanky/<slug>/img/<path:name>", defaults={"lang": "cs"})
@server.route("/clanky/<slug>/<any(en,de):lang>/img/<path:name>")
def _article_img(slug: str, lang: str, name: str):
    return send_from_directory(_article_or_404(slug, lang).img_dir(lang), name)


# The first article used to be at /clanek/ (links in the wild keep working).
@server.route("/clanek/", defaults={"lang": "cs"})
@server.route("/clanek/<any(en,de):lang>/")
def _old_article(lang: str):
    return redirect(clanky.DO_POSLEDNI_KWH.url(lang), code=301)


@server.route("/clanek/img/<path:name>", defaults={"lang": "cs"})
@server.route("/clanek/<any(en,de):lang>/img/<path:name>")
def _old_article_img(lang: str, name: str):
    return redirect(clanky.DO_POSLEDNI_KWH.url(lang) + "img/" + name, code=301)


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


@server.after_request
def _version_header(response: Response) -> Response:
    response.headers["X-App-Version"] = VERSION
    return response


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
