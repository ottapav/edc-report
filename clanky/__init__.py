"""Vysvětlující články (každý ve vlastní složce), skládané při každém otevření.

Článek je složka v ``clanky/`` (balíček Pythonu, název s podtržítky): ``clanek.html``
(česky), volitelně ``clanek.en.html`` a ``clanek.de.html``; obrázky z dat v ``img/``
(česky), ``img/en/`` a ``img/de/``; volitelně ``schemata.py``, jehož funkce ``jméno(lang)``
nahradí značky ``{{JMÉNO}}`` v textu. ``{{STYL}}`` vloží společný ``styl.css`` a
``{{JAZYKY}}`` přepínač jazyků (jen u článku s překlady). Aplikace článek obslouží na
``/clanky/<adresa>/`` (``…/en/``, ``…/de/``), takže úprava v repozitáři se projeví hned.
Nový článek: nová složka a jeden řádek v :data:`ARTICLES`.
"""
from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from pathlib import Path

DIR = Path(__file__).parent
#: the (pseudonymised) report of the real group both articles use, see data/README.md
DATA = DIR / "data"
STYLE = DIR / "styl.css"
LANGS = ("cs", "en", "de")
LANG_LABELS = {"cs": "CZ", "en": "EN", "de": "DE"}
_MARK = re.compile(r"\{\{([A-Z_]+)\}\}")
_SCHEMATA: dict[str, tuple[object, float]] = {}     # folder -> (module, file mtime)


@dataclass(frozen=True)
class Article:
    """One article: its folder in ``clanky/``, its address under ``/clanky/``, its Czech
    title."""

    folder: str
    slug: str
    title: str

    @property
    def dir(self) -> Path:
        return DIR / self.folder

    @property
    def langs(self) -> tuple[str, ...]:
        """Czech and the translations that exist."""
        return tuple(lg for lg in LANGS if self._file(lg).is_file())

    def _file(self, lang: str) -> Path:
        return self.dir / ("clanek.html" if lang == "cs" else f"clanek.{lang}.html")

    def source(self, lang: str = "cs") -> Path:
        """The HTML source of the article in ``lang``."""
        self._check(lang)
        return self._file(lang)

    def img_dir(self, lang: str = "cs") -> Path:
        """Folder of the images in ``lang`` (the Czech ones are in ``img/``)."""
        if lang not in LANGS:
            raise ValueError(f"unknown language {lang!r}, expected one of {LANGS}")
        return self.dir / "img" if lang == "cs" else self.dir / "img" / lang

    def url(self, lang: str = "cs") -> str:
        """Address inside the app; a language without a translation gets the Czech one."""
        lang = lang if lang in self.langs else "cs"
        return f"/clanky/{self.slug}/" if lang == "cs" else f"/clanky/{self.slug}/{lang}/"

    def images(self, lang: str = "cs") -> list[str]:
        """Image files the article in ``lang`` refers to (``img/…``), in order."""
        return re.findall(r'src="img/([^"]+)"', self.source(lang).read_text(encoding="utf-8"))

    def render(self, lang: str = "cs", *, links: bool = True) -> str:
        """The article in ``lang`` as one HTML page, every ``{{JMÉNO}}`` replaced by its
        figure. ``links=False`` leaves out the language switch (a standalone export)."""
        text = self.source(lang).read_text(encoding="utf-8")

        def mark(m: re.Match) -> str:
            name = m.group(1)
            if name == "STYL":
                return STYLE.read_text(encoding="utf-8")
            if name == "JAZYKY":
                return _langnav(self, lang) if links else ""
            fn = getattr(self._schemata(), name.lower(), None)
            if fn is None:
                raise KeyError(f"{self.folder}/{self.source(lang).name}: no figure for "
                               f"{m.group(0)} in schemata.py")
            return fn(lang)

        return typography(_MARK.sub(mark, text), lang)

    def _schemata(self):
        """The article's figure module, reloaded when its file changed (an edit shows up
        without restarting a long-running server); None without one."""
        path = self.dir / "schemata.py"
        if not path.is_file():
            return None
        mtime = path.stat().st_mtime
        module, seen = _SCHEMATA.get(self.folder, (None, None))
        if module is None:
            module = importlib.import_module(f"{__name__}.{self.folder}.schemata")
        elif seen != mtime:
            module = importlib.reload(module)
        _SCHEMATA[self.folder] = (module, mtime)
        return module

    def _check(self, lang: str) -> None:
        if lang not in self.langs:
            raise ValueError(f"{self.folder}: no version in {lang!r}, only {self.langs}")


#: Sdílení elektřiny do poslední kilowatthodiny: přesná statická metoda a režim bazén
DO_POSLEDNI_KWH = Article("do_posledni_kwh", "do-posledni-kwh",
                          "Sdílení elektřiny do poslední kilowatthodiny")
#: Spravedlivá cena sdílené kilowatthodiny: vyúčtování podle přínosu (Shapleyho hodnota)
SPRAVEDLIVA_CENA = Article("spravedliva_cena", "spravedliva-cena",
                           "Spravedlivá cena sdílené kilowatthodiny")
ARTICLES = (DO_POSLEDNI_KWH, SPRAVEDLIVA_CENA)


def by_slug(slug: str) -> Article | None:
    return next((a for a in ARTICLES if a.slug == slug), None)


def by_folder(folder: str) -> Article | None:
    return next((a for a in ARTICLES if a.folder == folder), None)


NBSP = " "
# Tags and blocks left alone by the typography pass: markup, code, styles and figures.
_SKIP = re.compile(r"(<(?:pre|style|svg|script)\b[\s\S]*?</(?:pre|style|svg|script)>|<[^>]+>)")
_UNITS = (re.compile(r"(?<=\d) (?=(?:kWh|kWp|kW|Kč|min|ms|s|%)(?!\w))"), NBSP)    # 12 kWh, 50 %, 4 Kč
_MATH = (re.compile(r"(?<=\S) ([×=−]) (?=\S)"), NBSP + "\\1" + NBSP)                 # 0,5 × 16 = 8
_DATE = (re.compile(r"\b(\d{1,2}\.) (\d{1,2}\.) (\d{4})\b"),
         "\\1" + NBSP + "\\2" + NBSP + "\\3")                                        # 28. 6. 2026
_TYPO = {
    "cs": [
        (re.compile(r"(?<!\w)([ksvzouaiKSVZOUAI]) (?=\S|$)"), "\\1" + NBSP),  # no one-letter word ends a line
        #                                       (also before inline markup: "a <em>…")
        (re.compile(r"(?<=\d) (?=\d{3}\b)"), NBSP),                              # 30 000
        _UNITS,
        (re.compile(r"\b(Ing\.|č\.|obr\.|Obr\.|[Tt]abulk\w+|[Tt]abulce) (?=[\w\d])"), "\\1" + NBSP),
        (re.compile(r"(?<=\d) (?=Sb\.)"), NBSP),
        _DATE,
        _MATH,
    ],
    "en": [
        _UNITS,
        (re.compile(r"\b(Fig\.|fig\.|Table|table|Annex|No\.) (?=\d)"), "\\1" + NBSP),
        _MATH,
    ],
    "de": [
        _UNITS,
        (re.compile(r"\b(Abb\.|Tabelle|Anlage|Nr\.) (?=\d)"), "\\1" + NBSP),
        (re.compile(r"\b(z\.|d\.|Ing\.) (?=\w)"), "\\1" + NBSP),
        _DATE,
        _MATH,
    ],
}


def typography(html: str, lang: str = "cs") -> str:
    """Typography of ``lang``: non-breaking spaces (Czech also after one-letter words and in
    thousands) so that no line ends in the middle of a number and its unit, a date or a
    reference like "Fig. 3"."""
    parts = _SKIP.split(html)
    for i in range(0, len(parts), 2):                    # even items are text, odd are tags
        for pattern, repl in _TYPO[lang]:
            parts[i] = pattern.sub(repl, parts[i])
    return "".join(parts)


def _langnav(article: Article, lang: str) -> str:
    """Links to the other language versions; nothing for an article in one language."""
    if len(article.langs) < 2:
        return ""
    items = [f"<span>{LANG_LABELS[lg]}</span>" if lg == lang
             else f'<a href="{article.url(lg)}" hreflang="{lg}">{LANG_LABELS[lg]}</a>'
             for lg in article.langs]
    return '<nav class="langnav" aria-label="Language">' + "".join(items) + "</nav>"
