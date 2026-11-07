import re

import pytest

import clanky

FIG = {"cs": r"Obr\.", "en": r"Fig\.", "de": r"Abb\."}
TAB = {"cs": r"Tabulka", "en": r"Table", "de": r"Tabelle"}
CITE = {"cs": ("obr", "tabul\\w*"), "en": ("fig", "table"), "de": ("abb", "tabelle")}
#: per article: (figures, tables, at least so many drawn SVG schemata), the title per language
SHAPE = {"do_posledni_kwh": (7, 4, 4), "spravedliva_cena": (0, 3, 0)}
TITLE = {
    "do_posledni_kwh": {"cs": "Sdílení elektřiny", "en": "Electricity sharing", "de": "Stromteilung"},
    "spravedliva_cena": {"cs": "Spravedlivá cena sdílené kilowatthodiny"},
}
NB = "\u00a0"                                       # no-break space
VERSIONS = [(a, lg) for a in clanky.ARTICLES for lg in a.langs]


@pytest.fixture(params=VERSIONS, ids=[f"{a.folder}-{lg}" for a, lg in VERSIONS])
def version(request):
    return request.param


def test_every_article_has_its_folder_and_is_listed():
    folders = sorted(p.name for p in clanky.DIR.iterdir()
                     if p.is_dir() and (p / "clanek.html").is_file())
    assert folders == sorted(a.folder for a in clanky.ARTICLES) == sorted(SHAPE)
    assert len({a.slug for a in clanky.ARTICLES}) == len(clanky.ARTICLES)
    for a in clanky.ARTICLES:
        assert (a.dir / "README.md").is_file() and (a.dir / "__init__.py").is_file()
    assert clanky.DO_POSLEDNI_KWH.langs == ("cs", "en", "de")
    assert clanky.SPRAVEDLIVA_CENA.langs == ("cs",)


def test_article_renders_every_figure(version):
    article, lang = version
    html = article.render(lang)
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert f'<html lang="{lang}">' in html
    assert "{{" not in html                            # every mark has its figure
    assert html.count("<svg") >= SHAPE[article.folder][2]
    multi = len(article.langs) > 1
    assert ('class="langnav"' in html) == multi        # a switch only with translations
    assert 'class="langnav"' not in article.render(lang, links=False)


def test_article_images_exist(version):
    article, lang = version
    for name in article.images(lang):
        assert (article.img_dir(lang) / name).is_file(), name


def test_article_versions_have_the_same_structure():
    """Translations keep the figures, tables, headings and sources of the Czech original."""
    def shape(article, lang):
        h = article.source(lang).read_text(encoding="utf-8")
        return [len(re.findall(r"<h2", h)), len(re.findall(r"<h3", h)), len(re.findall(r"<table", h)),
                len(re.findall(r"<figure", h)), len(re.findall(r"<li>", h)),
                re.findall(r"\{\{[A-Z]+\}\}", h), re.findall(r"\[\d+(?:, \d+)*\]", h)]
    for article in clanky.ARTICLES:
        for lang in article.langs[1:]:
            assert shape(article, lang) == shape(article, "cs"), (article.folder, lang)


def test_article_figures_tables_and_sources_are_cited(version):
    article, lang = version
    html = article.render(lang)
    text = re.sub(r"<figcaption[\s\S]*?</figcaption>|<p class=\"tcap\">[\s\S]*?</p>", "", html)
    fig, tab = CITE[lang]
    figs = re.findall(rf'fig-no">{FIG[lang]}\s(\d+)', html)
    tabs = re.findall(rf"{TAB[lang]}\s(\d+):", html)
    assert (len(figs), len(tabs)) == SHAPE[article.folder][:2]
    for n in figs:
        assert re.search(rf"{fig}\.\s{n}\b", text, re.I), f"figure {n} is not cited"
    for n in tabs:
        assert re.search(rf"{tab}\s{n}\b", text, re.I), f"table {n} is not cited"
    body, sources = text.split('<section class="sources">')
    n_sources = len(re.findall(r"<li>", sources))
    cited = {int(n) for c in re.findall(r"\[(\d+(?:, \d+)*)\]", body) for n in c.split(", ")}
    assert cited == set(range(1, n_sources + 1)), "every source cited, no citation without one"


def test_article_typography_uses_nonbreaking_spaces():
    a = clanky.DO_POSLEDNI_KWH
    html = a.render("cs")
    assert f"30{NB}000" in html and f"50{NB}%" in html and f"obr.{NB}1" in html
    text = re.sub(r"<(pre|style|svg)\b[\s\S]*?</\1>|<[^>]+>", "", html)
    assert not re.search(r"(?<!\w)[ksvzouaiKSVZOUAI] \S", text)    # no one-letter word at a line end
    assert clanky.typography("v domě") == f"v{NB}domě"
    assert clanky.typography("<pre>v domě</pre>") == "<pre>v domě</pre>"
    assert f"Fig.{NB}1" in a.render("en") and f"50{NB}%" in a.render("en")
    assert f"Abb.{NB}1" in a.render("de") and f"50{NB}%" in a.render("de")
    assert clanky.typography("v domě", "en") == "v domě"            # the Czech rule is Czech only
    text = re.sub(r"<(pre|style|svg)\b[\s\S]*?</\1>|<[^>]+>", "",
                  clanky.SPRAVEDLIVA_CENA.render("cs"))
    assert not re.search(r"(?<!\w)[ksvzouaiKSVZOUAI] \S", text)


def test_article_urls():
    a = clanky.DO_POSLEDNI_KWH
    assert [a.url(lg) for lg in clanky.LANGS] == [
        "/clanky/do-posledni-kwh/", "/clanky/do-posledni-kwh/en/", "/clanky/do-posledni-kwh/de/"]
    # no translation yet: the Czech one
    assert clanky.SPRAVEDLIVA_CENA.url("en") == "/clanky/spravedliva-cena/"
    with pytest.raises(ValueError):
        a.source("fr")
    with pytest.raises(ValueError):
        clanky.SPRAVEDLIVA_CENA.source("en")
    assert clanky.by_slug("spravedliva-cena") is clanky.SPRAVEDLIVA_CENA
    assert clanky.by_slug("nic") is None


@pytest.fixture
def client():
    import app
    return app.server.test_client()


def test_article_is_served(client, version):
    article, lang = version
    url = article.url(lang)
    page = client.get(url)
    assert page.status_code == 200 and TITLE[article.folder][lang] in page.get_data(as_text=True)
    assert client.get(url.rstrip("/")).status_code in (301, 308)       # adds the slash
    for name in article.images(lang)[:1]:
        assert client.get(f"{url}img/{name}").status_code == 200
    assert client.get(f"{url}img/../clanek.html").status_code == 404


def test_old_addresses_redirect_to_the_first_article(client):
    for old, new in (("/clanek/", "/clanky/do-posledni-kwh/"),
                     ("/clanek/en/", "/clanky/do-posledni-kwh/en/"),
                     ("/clanek/img/kolac.png", "/clanky/do-posledni-kwh/img/kolac.png"),
                     ("/clanek/de/img/kolac.png", "/clanky/do-posledni-kwh/de/img/kolac.png")):
        page = client.get(old)
        assert page.status_code == 301 and page.headers["Location"].endswith(new), old
        assert client.get(new).status_code == 200


def test_unknown_article_or_language_is_404(client):
    assert client.get("/clanky/nic/").status_code == 404
    assert client.get("/clanky/spravedliva-cena/en/").status_code == 404
    page = client.get("/clanky/do-posledni-kwh/fr/")      # not a language: not an article
    assert b'class="langnav"' not in page.data and b"fig-no" not in page.data


def test_app_links_the_first_article_in_the_ui_language():
    from ui import panel
    for lang in clanky.LANGS:
        out = (panel._report_labels.__wrapped__(lang, None, None)
               if hasattr(panel._report_labels, "__wrapped__")
               else panel._report_labels(lang, None, None))
        assert out["article_href"] == clanky.DO_POSLEDNI_KWH.url(lang)
