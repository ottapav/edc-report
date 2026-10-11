"""Small HTML building blocks: facts, tiles, and tables rendered as one HTML block.

A table of 150 members as Dash ``html.*`` elements is ~5 000 React components and takes
seconds to render in the browser, so tables are one ``dcc.Markdown`` of plain HTML.
"""

from __future__ import annotations

from html import escape as esc

from dash import dcc, html

GREEN, RED, GREY, LIGHT_GREY, BLUE = "#339933", "#cc3326", "#8c8c8c", "#c7c7c7", "#3b6fb6"
NBSP = " "


def kv(label: str, value) -> html.Div:
    return html.Div(className="kv", children=[html.Dt(label), html.Dd(value)])


def tile(label: str, value: str, sub=None, accent: str | None = None) -> html.Div:
    return html.Div(className="tile", children=[
        html.Div(className="tile-label", children=[
            html.Span(className="tile-dot", style={"background": accent}) if accent else None,
            label,
        ]),
        html.Div(value, className="tile-value"),
        html.Div(sub or NBSP, className="tile-sub"),
    ])


def two_lines(first, second=NBSP) -> list:
    """Tile sub-line with a second line, so paired tiles keep the same height."""
    return [first, html.Br(), second]


def tiles(items: list, note: str | None = None) -> list:
    out = [html.Div(className="tiles", children=items)]
    return out + [html.P(note, className="hint")] if note else out


def hint(text, cls: str = "hint") -> html.P:
    return html.P(text, className=cls)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def cell(text, cls: str = "", title: str = "") -> str:
    attrs = (f' class="{cls}"' if cls else "") + (f' title="{esc(title)}"' if title else "")
    return f"<td{attrs}>{text}</td>"


def num(text, bold: bool = False) -> str:
    """A right-aligned number cell."""
    return cell(f"<b>{text}</b>" if bold else text, "num")


def muted(text) -> str:
    return f'<span class="muted"> ({text})</span>'


def name_cell(name: str, ean: str, colour: str) -> str:
    return cell(f'<div><span class="swatch" style="background:{esc(colour)}"></span>'
                f'{esc(name)}</div><div class="mono sub-ean">{esc(ean)}</div>', "name")


def table(head: list[str], rows: list[tuple[str, str]], foot: str | list[str]) -> dcc.Markdown:
    """Header labels, body rows ``(css class, cells)``, one footer row or several."""
    thead = "".join(f"<th>{esc(h)}</th>" for h in head)
    tbody = "".join(f'<tr class="{cls}">{cells}</tr>' for cls, cells in rows)
    tfoot = "".join(f"<tr>{f}</tr>" for f in ([foot] if isinstance(foot, str) else foot))
    markup = (f'<table class="tbl"><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody>'
              f"<tfoot>{tfoot}</tfoot></table>")
    return dcc.Markdown(markup, dangerously_allow_html=True, className="tbl-md")
