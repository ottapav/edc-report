"""Vysvětlující článek o přesné statické metodě a režimu bazén (česky, anglicky, německy).

Zdrojem je ``clanek.html`` (česky), ``clanek.en.html`` a ``clanek.de.html``. Značky
``{{JMÉNO}}`` v nich nahradí schémata, která kreslí funkce ``schemata.jméno(lang)``,
``{{STYL}}`` vloží ``styl.css`` a ``{{JAZYKY}}`` přepínač jazyků. Obrázky z reálných dat
jsou v ``img/`` (česky) a ``img/en/``, ``img/de/``. Aplikace článek skládá při každém
otevření (``/clanek/``, ``/clanek/en/``, ``/clanek/de/``), takže úprava v repozitáři se
projeví hned.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

from . import schemata

DIR = Path(__file__).parent
IMG = DIR / "img"
STYLE = DIR / "styl.css"
LANGS = ("cs", "en", "de")
LANG_LABELS = {"cs": "CZ", "en": "EN", "de": "DE"}
SOURCE = DIR / "clanek.html"                      # the Czech original
_MARK = re.compile(r"\{\{([A-Z_]+)\}\}")
_SCHEMATA_MTIME = Path(schemata.__file__).stat().st_mtime


def source(lang: str = "cs") -> Path:
    """The HTML source of the article in ``lang``."""
    _check(lang)
    return SOURCE if lang == "cs" else DIR / f"clanek.{lang}.html"


def img_dir(lang: str = "cs") -> Path:
    """Folder of the images of the article in ``lang`` (the Czech ones are in ``img/``)."""
    _check(lang)
    return IMG if lang == "cs" else IMG / lang


def url(lang: str = "cs") -> str:
    """Address of the article in ``lang`` inside the app."""
    _check(lang)
    return "/clanek/" if lang == "cs" else f"/clanek/{lang}/"


def _check(lang: str) -> None:
    if lang not in LANGS:
        raise ValueError(f"unknown language {lang!r}, expected one of {LANGS}")


def _schemata():
    """The figure module, reloaded when its file changed (an edit shows up without a
    restart of a long-running server)."""
    global _SCHEMATA_MTIME
    mtime = Path(schemata.__file__).stat().st_mtime
    if mtime != _SCHEMATA_MTIME:
        importlib.reload(schemata)
        _SCHEMATA_MTIME = mtime
    return schemata


NBSP = " "
# Tags and blocks left alone by the typography pass: markup, code, styles and figures.
_SKIP = re.compile(r"(<(?:pre|style|svg|script)\b[\s\S]*?</(?:pre|style|svg|script)>|<[^>]+>)")
_UNITS = (re.compile(r"(?<=\d) (?=(?:kWh|kWp|kW|ms|s|%)(?!\w))"), NBSP)            # 12 kWh, 50 %
_MATH = (re.compile(r"(?<=\S) ([×=−]) (?=\S)"), NBSP + "\\1" + NBSP)                 # 0,5 × 16 = 8
_DATE = (re.compile(r"\b(\d{1,2}\.) (\d{1,2}\.) (\d{4})\b"),
         "\\1" + NBSP + "\\2" + NBSP + "\\3")                                        # 28. 6. 2026
_TYPO = {
    "cs": [
        (re.compile(r"(?<!\w)([ksvzouaiKSVZOUAI]) (?=\S)"), "\\1" + NBSP),     # no one-letter word ends a line
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


def _langnav(lang: str) -> str:
    items = [f"<span>{LANG_LABELS[lg]}</span>" if lg == lang
             else f'<a href="{url(lg)}" hreflang="{lg}">{LANG_LABELS[lg]}</a>' for lg in LANGS]
    return '<nav class="langnav" aria-label="Language">' + "".join(items) + "</nav>"


def render(lang: str = "cs", *, links: bool = True) -> str:
    """The article in ``lang`` as one HTML page, with every ``{{JMÉNO}}`` replaced by its
    SVG. ``links=False`` leaves out the language switch (for a standalone export)."""
    text = source(lang).read_text(encoding="utf-8")
    module = _schemata()

    def mark(m: re.Match) -> str:
        name = m.group(1)
        if name == "STYL":
            return STYLE.read_text(encoding="utf-8")
        if name == "JAZYKY":
            return _langnav(lang) if links else ""
        fn = getattr(module, name.lower(), None)
        if fn is None:
            raise KeyError(f"{source(lang).name}: no figure for {m.group(0)} in schemata.py")
        return fn(lang)

    return typography(_MARK.sub(mark, text), lang)


def images(lang: str = "cs") -> list[str]:
    """Image files the article in ``lang`` refers to (``img/…``), in order of appearance."""
    return re.findall(r'src="img/([^"]+)"', source(lang).read_text(encoding="utf-8"))
