"""The web server's own protections: response headers, values from the browser that end
up in code."""
import app
from ui import members


def test_every_response_carries_the_browser_protections():
    client = app.server.test_client()
    for path in ("/", "/clanky/do-posledni-kwh/", "/healthz", "/nic/"):
        h = client.get(path).headers
        assert "frame-ancestors 'none'" in h["Content-Security-Policy"], path
        assert "object-src 'none'" in h["Content-Security-Policy"]
        assert h["X-Frame-Options"] == "DENY" and h["X-Content-Type-Options"] == "nosniff"
        assert h["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "Strict-Transport-Security" not in h          # plain http (local run)
    behind_tls = client.get("/", headers={"X-Forwarded-Proto": "https"}).headers
    assert behind_tls["Strict-Transport-Security"].startswith("max-age=")


def test_the_articles_web_fonts_are_allowed():
    csp = app.CSP
    assert "https://fonts.googleapis.com" in csp and "https://fonts.gstatic.com" in csp


def test_an_unknown_language_never_reaches_the_grid_code():
    """The language is sent by the browser and is part of a grid function's code: only a
    known one is used (anything else would run as JavaScript in that browser)."""
    for lang in ("cs", "en", "de"):
        assert members._name_column(lang)["valueFormatter"]["function"].endswith(
            f"default_{lang}")
    col = members._name_column("cs; alert(1) //")
    assert col["valueFormatter"]["function"] == "params.value || params.data.default_cs"


def test_callbacks_are_registered_as_written():
    """Dash adds a callback's inputs to the state dict it is given: a dict shared by two
    callbacks then carries the first one's inputs into the second, which fails at run time
    (a keyword it does not take). Every callback gets its own dict; this would catch one
    that does not: a property never is both an input and a state of one callback."""
    from dash._callback import GLOBAL_CALLBACK_LIST
    for cb in GLOBAL_CALLBACK_LIST:
        inputs = [(i["id"], i["property"]) for i in cb["inputs"]]
        state = {(s["id"], s["property"]) for s in cb["state"]}
        assert len(inputs) == len(set(inputs)), cb["output"]
        assert not set(inputs) & state, cb["output"]
