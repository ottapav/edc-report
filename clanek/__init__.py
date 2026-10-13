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


def render() -> str:
    """The article as one HTML page, with every ``{{JMÉNO}}`` replaced by its SVG."""
    text = SOURCE.read_text(encoding="utf-8")
    module = _schemata()

    def svg(m: re.Match) -> str:
        fn = getattr(module, m.group(1).lower(), None)
        if fn is None:
            raise KeyError(f"clanek.html: no figure for {m.group(0)} in schemata.py")
        return fn()

    return _MARK.sub(svg, text)


def images() -> list[str]:
    """Image files the article refers to (``img/…``), in order of appearance."""
    return re.findall(r'src="img/([^"]+)"', SOURCE.read_text(encoding="utf-8"))
