"""The members grid (tick, name, key, price) and reading what the user typed in it.

One AG Grid holds every destination: a group of 150 members would otherwise put 600
pattern-matching inputs on the page, and the Dash renderer needs tens of seconds per
update.
"""

from __future__ import annotations

from string import ascii_uppercase

from dash import ctx

from edc_data import POOL, SharingData
from figures import colour_map, top_dests
from i18n import t


def default_names(data: SharingData, lang: str) -> dict[str, str]:
    """Generic labels: ``Výroba A`` / ``Spotřeba 1`` … in file order (and the pool of
    several producers)."""
    names = {e: f"{t('source_a', lang)} {ascii_uppercase[i % 26]}"
             for i, e in enumerate(data.source_eans)}
    names[POOL] = t("pool_name", lang)
    names.update({e: f"{t('destination', lang)} {i}"
                  for i, e in enumerate(data.dest_eans, 1)})
    return names


def names(data: SharingData, lang: str, src_ids: list[dict], src_values: list,
          rows: list[dict] | None) -> dict[str, str]:
    """Display names: typed names (sources: inputs, destinations: grid) or defaults."""
    out = default_names(data, lang)
    typed = [(i["ean"], v) for i, v in zip(src_ids or [], src_values or [])]
    typed += [(r.get("ean"), r.get("name")) for r in rows or []]
    for ean, value in typed:
        if value and str(value).strip() and ean in out:
            out[ean] = str(value).strip()
    return out


def enabled(data: SharingData, selected: list[dict] | None) -> set[str]:
    """Ticked destinations; None (grid not ready yet) means all."""
    if selected is None:
        return set(data.dest_eans)
    return {r["ean"] for r in selected if r and "ean" in r}


def number(v) -> float | None:
    """A number typed in a cell or input (decimal comma allowed); None when empty."""
    try:
        return None if v in (None, "") else float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def keys(data: SharingData, rows: list[dict] | None) -> list[float | None]:
    """Key column (percent) -> fractions in destination order; None = not set."""
    by_ean = {r.get("ean"): number(r.get("key")) for r in rows or []}
    return [None if by_ean.get(e) is None else max(0.0, by_ean[e]) / 100
            for e in data.dest_eans]


def prices(data: SharingData, rows: list[dict] | None, default) -> list[float | None]:
    """Price column (Kč/kWh) in destination order; empty cells take ``default``."""
    by_ean = {r.get("ean"): number(r.get("price")) for r in rows or []}
    fallback = number(default)
    out = []
    for e in data.dest_eans:
        v = by_ean.get(e)
        v = fallback if v is None else v
        out.append(None if v is None else max(0.0, v))
    return out


def feed_ins(data: SharingData, ids: list[dict], values: list,
             default) -> list[float | None]:
    """Feed-in price (Kč/kWh) per producer in report order; empty inputs take
    ``default``."""
    typed = {i["ean"]: number(v) for i, v in zip(ids or [], values or [])}
    fallback = number(default)
    out = []
    for e in data.source_eans:
        v = typed.get(e)
        v = fallback if v is None else v
        out.append(None if v is None else max(0.0, v))
    return out


def reserve(value) -> float:
    """Reserve for sale, percent input -> fraction 0..1."""
    return min(max(number(value) or 0.0, 0.0), 100.0) / 100


def pct_key(x: float) -> float:
    """A key fraction as shown in the grid: percent with two decimals."""
    return round(x * 100, 2)


def key_only_edit() -> bool:
    """True when the callback fired only because a key or price cell was edited (names
    and selection unchanged): the figures need not be redrawn."""
    if set(ctx.triggered_prop_ids or {}) != {"members.cellValueChanged"}:
        return False
    changes = ctx.triggered[0].get("value") if ctx.triggered else None
    changes = changes if isinstance(changes, list) else [changes or {}]
    return all((c or {}).get("colId") != "name" for c in changes)


# ---------------------------------------------------------------------------
# Grid definition
# ---------------------------------------------------------------------------


def _number_column(field: str, header: str, editable: bool, width: int, precision: int,
                   lang: str, **extra) -> dict:
    dec = "," if lang == "cs" else "."
    return {"field": field, "headerName": header, "editable": editable, "width": width,
            "type": "rightAligned", "cellEditor": "agNumberCellEditor",
            "cellEditorParams": {"min": 0, "max": 100, "precision": precision},
            # values are rounded already; no globals (String/Math) in grid functions
            "valueFormatter": {"function":
                               f"params.value == null ? '' : (params.value + '').replace('.', '{dec}')"},
            **extra}


def columns(lang: str, editable: bool) -> list[dict]:
    """Grid columns; formatters depend on the language (decimal comma, default names).
    Keys and prices are editable only for an all report."""
    return [
        {"field": "name", "headerName": t("col_name", lang), "editable": True, "flex": 1,
         "minWidth": 84, "tooltipField": "ean",
         "valueFormatter": {"function": f"params.value || params.data.default_{lang}"},
         "cellClassRules": {"muted-name": "!params.value"},
         "cellStyle": {"function": "({borderLeft: '6px solid ' + params.data.colour})"}},
        {"field": "tail", "headerName": "EAN", "width": 64, "cellClass": "mono-cell",
         "tooltipField": "ean"},
        _number_column("key", t("keys", lang), editable, 70, 2, lang, tooltipField="range",
                       cellClassRules={"key-warn": "params.data.warn"}),
        _number_column("price", t("price_col", lang), editable, 62, 4, lang,
                       headerTooltip=t("price_col_tip", lang)),
    ]


def rows(data: SharingData) -> list[dict]:
    cmap = colour_map(data, top_dests(data.frame, data))
    default = {lg: default_names(data, lg) for lg in ("cs", "en")}
    return [{"ean": e, "tail": f"…{e[-6:]}", "name": "",
             "default_cs": default["cs"][e], "default_en": default["en"][e],
             "colour": cmap[e], "key": None, "range": "", "warn": False, "price": None}
            for e in data.dest_eans]


def options(many: bool) -> dict:
    return {
        "rowSelection": {"mode": "multiRow", "enableClickSelection": False},
        "singleClickEdit": True, "stopEditingWhenCellsLoseFocus": True,
        "tooltipShowDelay": 250, "rowHeight": 32, "headerHeight": 30,
        "domLayout": "normal" if many else "autoHeight",
    }
