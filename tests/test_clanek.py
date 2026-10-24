import re

import pytest

import clanek

FIG = {"cs": r"Obr\.", "en": r"Fig\.", "de": r"Abb\."}
TAB = {"cs": r"Tabulka", "en": r"Table", "de": r"Tabelle"}
CITE = {"cs": ("obr", "tabul\\w*"), "en": ("fig", "table"), "de": ("abb", "tabelle")}
TITLE = {"cs": "Sdílení elektřiny", "en": "Electricity sharing", "de": "Stromteilung"}


@pytest.fixture(params=clanek.LANGS)
def lang(request):
    return request.param


def test_article_renders_every_figure(lang):
    html = clanek.render(lang)
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert f'<html lang="{lang}">' in html
    assert "{{" not in html                            # every mark has its figure
    assert html.count("<svg") >= 4
    assert 'class="langnav"' in html and "{{" not in clanek.render(lang, links=False)
    assert 'class="langnav"' not in clanek.render(lang, links=False)


def test_article_images_exist(lang):
    names = clanek.images(lang)
    assert names
    for name in names:
        assert (clanek.img_dir(lang) / name).is_file(), name


def test_article_versions_have_the_same_structure():
    """Translations keep the figures, tables, headings and sources of the Czech original."""
    def shape(lang):
        h = clanek.source(lang).read_text(encoding="utf-8")
        return [len(re.findall(r"<h2", h)), len(re.findall(r"<h3", h)), len(re.findall(r"<table", h)),
                len(re.findall(r"<figure", h)), len(re.findall(r"<li>", h)),
                re.findall(r"\{\{[A-Z]+\}\}", h), re.findall(r"\[\d+(?:, \d+)*\]", h)]
    for lang in ("en", "de"):
        assert shape(lang) == shape("cs"), lang


def test_article_figures_and_tables_are_cited(lang):
    html = clanek.render(lang)
    text = re.sub(r"<figcaption[\s\S]*?</figcaption>|<p class=\"tcap\">[\s\S]*?</p>", "", html)
    fig, tab = CITE[lang]
    figs = re.findall(rf'fig-no">{FIG[lang]}\s(\d+)', html)
    tabs = re.findall(rf"{TAB[lang]}\s(\d+):", html)
    assert len(figs) == 7 and len(tabs) == 4
    for n in figs:
        assert re.search(rf"{fig}\.\s{n}\b", text, re.I), f"figure {n} is not cited"
    for n in tabs:
        assert re.search(rf"{tab}\s{n}\b", text, re.I), f"table {n} is not cited"


def test_article_typography_uses_nonbreaking_spaces():
    html = clanek.render("cs")
    assert "30 000" in html and "50 %" in html and "obr. 1" in html
    text = re.sub(r"<(pre|style|svg)\b[\s\S]*?</\1>|<[^>]+>", "", html)
    assert not re.search(r"(?<!\w)[ksvzouaiKSVZOUAI] \S", text)    # no one-letter word at a line end
    assert clanek.typography("v domě") == "v domě"
    assert clanek.typography("<pre>v domě</pre>") == "<pre>v domě</pre>"
    assert "Fig. 1" in clanek.render("en") and "50 %" in clanek.render("en")
    assert "Abb. 1" in clanek.render("de") and "50 %" in clanek.render("de")
    assert clanek.typography("v domě", "en") == "v domě"            # the Czech rule is Czech only


def test_article_urls():
    assert [clanek.url(lg) for lg in clanek.LANGS] == ["/clanek/", "/clanek/en/", "/clanek/de/"]
    with pytest.raises(ValueError):
        clanek.url("fr")


@pytest.fixture
def client():
    import app
    return app.server.test_client()


def test_article_is_served(client, lang):
    page = client.get(clanek.url(lang))
    assert page.status_code == 200 and TITLE[lang] in page.get_data(as_text=True)
    assert client.get(clanek.url(lang).rstrip("/")).status_code in (301, 308)       # adds the slash
    assert client.get(f"{clanek.url(lang)}img/{clanek.images(lang)[0]}").status_code == 200
    assert client.get(f"{clanek.url(lang)}img/../clanek.html").status_code == 404


def test_unknown_article_language_is_404(client):
    page = client.get("/clanek/fr/")                  # falls through to the Dash page, not the article
    assert b'class="langnav"' not in page.data and b"fig-no" not in page.data


def test_app_links_the_article_in_the_ui_language(lang):
    from ui import panel
    out = panel._report_labels.__wrapped__(lang, None, None) if hasattr(panel._report_labels, "__wrapped__") \
        else panel._report_labels(lang, None, None)
    assert out["article_href"] == clanek.url(lang)
