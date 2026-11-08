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
