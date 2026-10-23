"""Vysvětlující článek o přesné statické metodě a režimu bazén (česky).

Zdrojem je ``clanek.html``. Značky ``{{JMÉNO}}`` v něm nahradí schémata, která kreslí
funkce ``schemata.jméno()``. Obrázky z reálných dat jsou v ``img/``. Aplikace článek
skládá při každém otevření (``/clanek/``), takže úprava v repozitáři se projeví hned.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

from . import schemata

DIR = Path(__file__).parent
SOURCE = DIR / "clanek.html"
IMG = DIR / "img"
_MARK = re.compile(r"\{\{([A-Z_]+)\}\}")
_SCHEMATA_MTIME = Path(schemata.__file__).stat().st_mtime


def _schemata():
    """The figure module, reloaded when its file changed (an edit shows up without a
    restart of a long-running server)."""
    global _SCHEMATA_MTIME
    mtime = Path(schemata.__file__).stat().st_mtime
    if mtime != _SCHEMATA_MTIME:
        importlib.reload(schemata)
        _SCHEMATA_MTIME = mtime
    return schemata


NBSP = "\u00a0"
# Tags and blocks left alone by the typography pass: markup, code, styles and figures.
_SKIP = re.compile(r"(<(?:pre|style|svg|script)\b[\s\S]*?</(?:pre|style|svg|script)>|<[^>]+>)")
_TYPO = [
    (re.compile(r"(?<!\w)([ksvzouaiKSVZOUAI]) (?=\S)"), "\\1" + NBSP),         # no one-letter word ends a line
    (re.compile(r"(?<=\d) (?=\d{3}\b)"), NBSP),                                # 30 000
    (re.compile(r"(?<=\d) (?=(?:kWh|kWp|kW|ms|s|%)(?!\w))"), NBSP),             # 12 kWh, 50 %
    (re.compile(r"\b(Ing\.|č\.|obr\.|Obr\.|[Tt]abulk\w+|[Tt]abulce) (?=[\w\d])"), "\\1" + NBSP),
    (re.compile(r"(?<=\d) (?=Sb\.)"), NBSP),
    (re.compile(r"\b(\d{1,2}\.) (\d{1,2}\.) (\d{4})\b"), "\\1" + NBSP + "\\2" + NBSP + "\\3"),
    (re.compile(r"(?<=\S) ([×=−]) (?=\S)"), NBSP + "\\1" + NBSP),               # 0,5 × 16 = 8
]


def typography(html: str) -> str:
    """Czech typography: non-breaking spaces after one-letter words, inside numbers and
    between a number and its unit, so that no line ends in the middle of such a pair."""
    parts = _SKIP.split(html)
    for i in range(0, len(parts), 2):                    # even items are text, odd are tags
        for pattern, repl in _TYPO:
            parts[i] = pattern.sub(repl, parts[i])
    return "".join(parts)


def render() -> str:
    """The article as one HTML page, with every ``{{JMÉNO}}`` replaced by its SVG."""
    text = SOURCE.read_text(encoding="utf-8")
    module = _schemata()

    def svg(m: re.Match) -> str:
        fn = getattr(module, m.group(1).lower(), None)
        if fn is None:
            raise KeyError(f"clanek.html: no figure for {m.group(0)} in schemata.py")
        return fn()

    return typography(_MARK.sub(svg, text))


def images() -> list[str]:
    """Image files the article refers to (``img/…``), in order of appearance."""
    return re.findall(r'src="img/([^"]+)"', SOURCE.read_text(encoding="utf-8"))
