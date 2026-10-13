import re

import pytest

import clanek


def test_article_renders_every_figure():
    html = clanek.render()
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert "{{" not in html                            # every mark has its figure
    assert html.count("<svg") >= 4


def test_article_images_exist():
    names = clanek.images()
    assert names
    for name in names:
        assert (clanek.IMG / name).is_file(), name


def test_article_figures_and_tables_are_cited():
    html = clanek.render()
    text = re.sub(r"<figcaption[\s\S]*?</figcaption>|<p class=\"tcap\">[\s\S]*?</p>", "", html)
    for n in re.findall(r'fig-no">Obr\. (\d+)', html):
        assert re.search(rf"obr\. {n}\b", text, re.I), f"Obr. {n} is not cited"
    for n in re.findall(r"Tabulka (\d+):", html):
        assert re.search(rf"tabul\w* {n}\b", text, re.I), f"Tabulka {n} is not cited"


@pytest.fixture
def client():
    import app
    return app.server.test_client()


def test_article_is_served(client):
    page = client.get("/clanek/")
    assert page.status_code == 200 and "Sdílení elektřiny" in page.get_data(as_text=True)
    assert client.get("/clanek").status_code in (301, 308)       # adds the slash
    assert client.get(f"/clanek/img/{clanek.images()[0]}").status_code == 200
    assert client.get("/clanek/img/../clanek.html").status_code == 404
