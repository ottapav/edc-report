"""The two grids of the panel and reading what the user typed in them: the producers
(name, feed-in price) and the members (tick, name, key, supplier price).

One AG Grid holds every destination: a group of 150 members would otherwise put 600
pattern-matching inputs on the page, and the Dash renderer needs tens of seconds per
update. The producers use the same kind of grid, so every value is typed the same way.
EANs are shown by their last three digits only (anonymity, room).
"""

from __future__ import annotations

from string import ascii_uppercase

from dash import ctx

from edc_data import POOL, SharingData
from figures import colour_map, top_dests
from i18n import LANGS, decimal_char, t

from .widgets import tail


#: the grids that hold names and prices
GRIDS = ("producers", "members")


def default_names(data: SharingData, lang: str) -> dict[str, str]:
    """Generic labels: ``Výroba A`` / ``Spotřeba 1`` … in file order (and the pool of
    several producers)."""
    names = {e: f"{t('source_a', lang)} {ascii_uppercase[i % 26]}"
             for i, e in enumerate(data.source_eans)}
    names[POOL] = t("pool_name", lang)
    names.update({e: f"{t('destination', lang)} {i}"
                  for i, e in enumerate(data.dest_eans, 1)})
    return names


def names(data: SharingData, lang: str, src_rows: list[dict] | None,
          rows: list[dict] | None) -> dict[str, str]:
    """Display names: typed in the two grids, or the defaults."""
    out = default_names(data, lang)
    typed = [(r.get("ean"), r.get("name")) for r in [*(src_rows or []), *(rows or [])]]
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
    """Key column (percent) -> fractions in destination order; None = not set. Negative
    values are kept, so :func:`key_problem` can report them."""
    by_ean = {r.get("ean"): number(r.get("key")) for r in rows or []}
    return [None if by_ean.get(e) is None else by_ean[e] / 100 for e in data.dest_eans]


def merged_keys(typed: list[float | None], fit) -> list[float | None]:
    """Typed keys, empty cells filled with the estimate (None while there is none)."""
    return [k if k is not None else (fit.keys[i] if fit is not None else None)
            for i, k in enumerate(typed)]


def key_problem(typed: list[float | None], fit) -> str | None:
    """i18n key of what is wrong with the keys (negative, sum over 100 %, all zero), or
    None. Empty cells count with their estimate; without one only the typed keys are
    checked."""
    keys = [k for k in merged_keys(typed, fit) if k is not None]
    if any(k < 0 for k in keys):
        return "keys_negative"
    if sum(keys) > 1 + 1e-9:
        return "keys_sum_over"
    if len(keys) == len(typed) and not any(k > 0 for k in keys):
        return "keys_all_zero"
    return None


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


def feed_ins(data: SharingData, src_rows: list[dict] | None, default) -> list[float | None]:
    """Feed-in price (Kč/kWh) per producer in report order (producers grid); empty cells
    take ``default``."""
    typed = {r.get("ean"): number(r.get("price")) for r in src_rows or []}
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
    """True when the callback fired only because a key or price cell was edited in one
    of the grids (names and selection unchanged): the figures need not be redrawn."""
    edits = {f"{g}.cellValueChanged" for g in GRIDS}
    trig = set(ctx.triggered_prop_ids or {})
    if not trig or not trig <= edits:
        return False
    for item in ctx.triggered or []:
        changes = item.get("value")
        changes = changes if isinstance(changes, list) else [changes or {}]
        if any((c or {}).get("colId") == "name" for c in changes):
            return False
    return True


# ---------------------------------------------------------------------------
# Grid definition
# ---------------------------------------------------------------------------


def _name_column(lang: str) -> dict:
    return {"field": "name", "headerName": t("col_name", lang), "editable": True, "flex": 1,
            "minWidth": 84,
            "valueFormatter": {"function": f"params.value || params.data.default_{lang}"},
            "cellClassRules": {"muted-name": "!params.value"},
            "cellStyle": {"function": "({borderLeft: '6px solid ' + params.data.colour})"}}


_TAIL_COLUMN = {"field": "tail", "headerName": "EAN", "width": 48, "cellClass": "mono-cell"}


def _number_column(field: str, header: str, editable: bool, width: int, lang: str,
                   negative: bool = False, **extra) -> dict:
    dec = decimal_char(lang)
    # typed as text, so a decimal comma works in every browser locale (the number editor
    # drops it: "1,1" became 11); anything that is not a number keeps the old value, and
    # so does a negative one unless ``negative`` (keys: kept and reported as an error).
    # Grid functions are expressions without globals (no String, Math, isNaN).
    num = "(+((params.newValue + '').trim().replace(',', '.')))"
    ok = f"{num} === {num}" if negative else f"{num} === {num} && {num} >= 0"
    return {"field": field, "headerName": header, "editable": editable, "width": width,
            "type": "rightAligned", "cellEditor": "agTextCellEditor",
            "valueParser": {"function":
                            f"(params.newValue == null || (params.newValue + '').trim() === '') ? null"
                            f" : ({ok} ? {num} : params.oldValue)"},
            "valueFormatter": {"function":
                               f"params.value == null ? '' : (params.value + '').replace('.', '{dec}')"},
            **extra}


def columns(lang: str, editable: bool) -> list[dict]:
    """Grid columns; formatters depend on the language (decimal comma, default names).
    Keys and prices are editable only for an all report."""
    return [
        _name_column(lang),
        _TAIL_COLUMN,
        _number_column("key", t("keys", lang), editable, 64, lang, negative=True,
                       tooltipField="range",
                       cellClassRules={"key-warn": "params.data.warn",
                                       "key-bad": "params.value != null && params.value < 0"}),
        _number_column("price", t("price_col", lang), editable, 58, lang,
                       headerTooltip=t("price_col_tip", lang)),
    ]


def rows(data: SharingData) -> list[dict]:
    cmap = colour_map(data, top_dests(data.frame, data))
    default = {lg: default_names(data, lg) for lg in LANGS}
    return [{"ean": e, "tail": tail(e), "name": "",
             **{f"default_{lg}": default[lg][e] for lg in LANGS},
             "colour": cmap[e], "key": None, "range": "", "warn": False, "price": None}
            for e in data.dest_eans]


def producer_columns(lang: str) -> list[dict]:
    """Producers grid: name, EAN, feed-in price (typed like the members' keys and prices)."""
    return [
        _name_column(lang),
        _TAIL_COLUMN,
        _number_column("price", t("feed_col", lang), True, 64, lang,
                       headerTooltip=t("feed_tip", lang)),
    ]


def producer_rows(data: SharingData) -> list[dict]:
    default = {lg: default_names(data, lg) for lg in LANGS}
    return [{"ean": e, "tail": tail(e), "name": "",
             **{f"default_{lg}": default[lg][e] for lg in LANGS},
             "colour": "#339933", "price": None}
            for e in data.source_eans]


def producer_options() -> dict:
    return {"singleClickEdit": True, "stopEditingWhenCellsLoseFocus": True,
            "tooltipShowDelay": 250, "rowHeight": 32, "headerHeight": 30,
            "domLayout": "autoHeight"}


def options(many: bool) -> dict:
    return {
        "rowSelection": {"mode": "multiRow", "enableClickSelection": False},
        # the tick column as narrow as its checkbox: the whole grid fits the panel
        "selectionColumnDef": {"width": 34, "minWidth": 34, "maxWidth": 34},
        "singleClickEdit": True, "stopEditingWhenCellsLoseFocus": True,
        "tooltipShowDelay": 250, "rowHeight": 32, "headerHeight": 30,
        "domLayout": "normal" if many else "autoHeight",
    }
