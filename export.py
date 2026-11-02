"""Export of the summary to an Excel workbook (.xlsx).

The workbook holds what the page shows, as numbers rather than formatted text, for the
current selection: the ticked members, the names typed in the grids, the language and
whatever has been computed (key estimate, exact recompute, billing). One sheet per
table:

* summary: facts of the report, the energy tiles (next to the exact method when it has
  been recomputed), the sharing error, the billing totals and the key estimate;
* destinations: the per-destination table of the EDC report;
* comparison (after the recompute): approximate vs exact method per destination;
* billing (after the billing): the settlement per member and per producer;
* daily: energy per day, for your own plots.

EANs are shortened to their last three digits as on the page unless ``full_ean``.
Pure functions of the data: no Dash here, :mod:`ui.export` wires it to the page.
"""

from __future__ import annotations

import datetime as dt
import io
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from edc_data import (
    KEY_OTHERS, SharingData, Summary, aggregate_grid_flows, exact_gain, filter_dests,
    per_destination, summarize, with_overlap,
)
from i18n import t, tn
from recompute import grid_loss

#: Excel number formats (Excel shows them with the reader's own separators)
KWH, PCT, KC, KW, INT = "#,##0.00", "0.0", "#,##0.00", "#,##0.00", "#,##0"
_HEAD_FILL = PatternFill("solid", fgColor="E8EEE8")
_SECTION_FONT = Font(bold=True, size=12)
_BOLD = Font(bold=True)


def ean_label(ean: str, full: bool) -> str:
    """An EAN as exported: the last three digits (as on the page) or the whole of it."""
    return ean if full else f"…{ean[-3:]}"


def date_format(lang: str) -> str:
    return "dd.mm.yyyy" if lang in ("cs", "de") else "yyyy-mm-dd"


def file_name(data: SharingData, lang: str, group: str = "") -> str:
    """``edc-souhrn-<group>-<from>_<to>.xlsx`` (in the language), safe for any file
    system."""
    idx = data.frame.index
    span = f"{idx.min():%Y-%m-%d}_{idx.max():%Y-%m-%d}"
    group = re.sub(r"[^\w-]+", "-", (group or "").strip()).strip("-")
    return f"{t('x_file', lang)}-{group + '-' if group else ''}{span}.xlsx"


# ---------------------------------------------------------------------------
# Tables as plain data: a header, rows of values, and a number format per column
# ---------------------------------------------------------------------------


@dataclass
class Table:
    head: list[str]
    rows: list[list]
    formats: list[str | None]
    title: str | None = None
    #: indices of rows written in bold (Σ rows)
    bold: set[int] = field(default_factory=set)
    #: number format of whole rows, overriding the columns' (a % row in a kWh table)
    row_formats: dict[int, str] = field(default_factory=dict)


@dataclass
class Sheet:
    name: str
    tables: list[Table]


def _kwh(x) -> float | None:
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 2)


def _pct(x, base) -> float | None:
    return round(100 * float(x) / float(base), 2) if x is not None and base else None


def _summary(data: SharingData, enabled: set[str], exact: SharingData | None) -> Summary:
    """As the tiles: once the exact recompute exists, "could have been shared" is what it
    really adds to the selection (0 for the exact method itself)."""
    s = summarize(data, enabled)
    if exact is None or s.overlap is None:
        return s
    return with_overlap(s, 0.0 if data is exact else exact_gain(data, exact, enabled))


def _selected(data: SharingData, enabled: set[str]) -> list[str]:
    return [e for e in data.dest_eans if e in enabled]


def _sigma(n_sel: int, n: int, lang: str) -> str:
    return "Σ" if n_sel == n else f"Σ {t('cmp_selected', lang).format(n=n_sel, m=n)}"


def _yes(on: bool, lang: str) -> str:
    return t("x_yes" if on else "x_no", lang)


def info_table(entry, enabled: set[str], names: dict, lang: str, group: str,
               full_ean: bool) -> Table:
    data = entry.data
    s = summarize(data, enabled)
    title = (t("report_title_group", lang).format(group=group) if group
             else t("report_title", lang))
    producers = ", ".join(f"{names.get(e, e)} ({ean_label(e, full_ean)})"
                          for e in data.source_eans)
    rows = [
        [t("file", lang), entry.filename, None],
        [t("report_type", lang),
         t("type_all" if data.fmt == "all" else "type_part", lang), None],
        [t("x_from", lang), s.date_from.date(), None],
        [t("x_to", lang), s.date_to.date(), None],
        [f"{t('period', lang)} [{t('days', lang)}]", s.n_days, None],
        [f"{t('period', lang)} [{t('intervals', lang)}]", s.n_rows, None],
        [t("producer", lang), producers, None],
        [t("n_dest", lang), t("selected_of", lang).format(sel=s.n_selected, n=s.n_dests), None],
    ]
    if s.peak_production_kw is not None:
        rows.append([t("peak", lang), round(s.peak_production_kw, 2), "kW"])
    if s.best_day is not None:
        rows.append([t("best_day", lang), s.best_day.date(), None])
        rows.append([t("x_best_day_kwh", lang), _kwh(s.best_day_shared), "kWh"])
    rows.append([t("days_sharing", lang), s.days_with_sharing, None])
    rows.append([t("x_generated", lang), dt.datetime.now().replace(microsecond=0), None])
    day = date_format(lang)
    formats = {i: (f"{day} hh:mm" if isinstance(r[1], dt.datetime) else day)
               for i, r in enumerate(rows) if isinstance(r[1], dt.date)}
    return Table([t("x_item", lang), t("x_value", lang), t("x_unit", lang)], rows,
                 [None, None, None], title=title, row_formats=formats)


def energy_table(entry, enabled: set[str], lang: str) -> Table:
    """The energy tiles; with the exact recompute, its column next to the one it is
    compared with (the report, or today's method replayed with the same keys)."""
    data, exact = entry.data, entry.exact
    left = exact.left(data) if exact is not None else data
    a = _summary(left, enabled, exact.data if exact else None)
    cols = [a]
    head = [t("x_item", lang),
            t("col_edc" if left is data else "col_edc_replay", lang)]
    if exact is not None:
        cols.append(_summary(exact.data, enabled, exact.data))
        head.append(t("col_exact", lang))
    head.append(t("x_unit", lang))
    subset = len(_selected(data, enabled)) < len(data.dest_eans)
    if data.fmt != "all":
        items = [("kpi_shared", "shared", "kWh")]
    else:
        wasted = "kpi_wasted_max" if subset and exact is None else "kpi_wasted"
        items = [("kpi_production", "production", "kWh"), ("kpi_shared", "shared", "kWh"),
                 (wasted, "overlap", "kWh"), ("kpi_unshareable", "unshared_only", "kWh"),
                 ("kpi_consumption", "consumption", "kWh"), ("kpi_from_grid", "unmet", "kWh")]
    rows = [[t(key, lang), *(_kwh(getattr(s, f)) for s in cols), unit]
            for key, f, unit in items]
    fmts = [None] + [KWH] * len(cols) + [None]
    if data.fmt == "all":
        rows.append([f"{t('kpi_shared', lang)} / {t('kpi_production', lang)}",
                     *(_pct(s.shared, s.production) for s in cols), "%"])
        rows.append([t("col_coverage", lang),
                     *(_pct(s.shared, s.consumption) for s in cols), "%"])
    pct_rows = {len(items): PCT, len(items) + 1: PCT} if data.fmt == "all" else {}
    return Table(head, rows, fmts, title=t("x_energy", lang), row_formats=pct_rows)


def exact_table(entry, enabled: set[str], names: dict, lang: str) -> Table:
    exact, data = entry.exact, entry.data
    loss = grid_loss(exact.left(data), exact.data, enabled)
    source = t("keys_est" if exact.keys_estimated else "keys_user", lang)
    rows = [
        [t("x_loss_pct", lang), round(loss.pct_of_max, 2), "%"],
        [t("x_loss_kwh", lang), _kwh(loss.lost), "kWh"],
        [t("cmp_shared_edc", lang), _kwh(loss.shared_edc), "kWh"],
        [t("cmp_shared_exact", lang), _kwh(loss.shared_exact), "kWh"],
        [t("keys_used", lang), source, None],
        [t("x_keys_sum", lang), round(100 * sum(exact.keys), 2), "%"],
        [t("reserve", lang), round(100 * exact.reserve, 2), "%"],
    ]
    return Table([t("x_item", lang), t("x_value", lang), t("x_unit", lang)], rows,
                 [None, None, None], title=t("loss_title", lang))


def bill_totals_table(entry, enabled: set[str], lang: str) -> Table:
    bill = entry.bill.settlement
    data = entry.data
    cur = t("currency", lang)
    sel = np.array([e in enabled for e in data.dest_eans])
    n_prod = len(bill.feed_ins)
    rows = [
        [t("bt_benefit", lang), round(bill.realized, 2), cur],
        [t("x_max_benefit", lang), round(bill.maximum, 2), cur],
        [t("x_efficiency", lang), round(100 * bill.efficiency, 2), "%"],
        [t("bt_lost", lang), round(max(0.0, bill.maximum - bill.realized), 2), cur],
        [tn("bt_producer", lang, n_prod), round(float(bill.producer_share.sum()), 2), cur],
        [t("bt_members", lang), round(float(bill.share[sel].sum()), 2), cur],
        [tn("bt_income", lang, n_prod), round(float(bill.producer_income.sum()), 2), cur],
        [t("bt_feed_in", lang), round(float(bill.feed_in_value.sum()), 2), cur],
    ]
    return Table([t("x_item", lang), t("x_value", lang), t("x_unit", lang)], rows,
                 [None, None, None], title=t("col_bill", lang))


def fit_table(entry, lang: str) -> Table:
    fit = entry.fit
    rows = [[t("x_rounds", lang), fit.rounds, None],
            [t("x_fit_match", lang), round(100 * fit.match, 2), "%"]]
    return Table([t("x_item", lang), t("x_value", lang), t("x_unit", lang)], rows,
                 [None, None, None], title=t("fit_title", lang))


def members_table(data: SharingData, enabled: set[str], names: dict, lang: str,
                  full_ean: bool) -> Table:
    """The per-destination table of the page; Σ over all members, as there."""
    df = per_destination(data)
    is_all = data.fmt == "all"
    head = [t("col_name", lang), t("col_ean", lang), t("x_included", lang)]
    fmts: list[str | None] = [None, None, None]
    if is_all:
        head += [t("col_consumption", lang), t("col_shared", lang), t("col_unmet", lang),
                 f"{t('col_coverage', lang)} [%]"]
        fmts += [KWH, KWH, KWH, PCT]
    else:
        head += [t("col_shared", lang)]
        fmts += [KWH]
    head += [f"{t('col_share', lang)} [%]", t("col_data", lang), f"{t('col_data_pct', lang)} [%]"]
    fmts += [PCT, date_format(lang), PCT]
    rows = []
    for r in df.itertuples():
        row = [names.get(r.ean, r.ean), ean_label(r.ean, full_ean), _yes(r.ean in enabled, lang)]
        if is_all:
            row += [_kwh(r.consumption), _kwh(r.shared), _kwh(r.unmet),
                    None if r.coverage_pct is None or pd.isna(r.coverage_pct)
                    else round(r.coverage_pct, 2)]
        else:
            row += [_kwh(r.shared)]
        first = r.first_data.date() if r.first_data is not None and not pd.isna(r.first_data) else None
        row += [round(r.share_of_shared_pct, 2), first, round(r.data_pct, 2)]
        rows.append(row)
    foot = ["Σ", None, None]
    if is_all:
        c, sh, u = df["consumption"].sum(), df["shared"].sum(), df["unmet"].sum()
        foot += [_kwh(c), _kwh(sh), _kwh(u), _pct(sh, c)]
    else:
        foot += [_kwh(df["shared"].sum())]
    foot += [100.0, None, None]
    rows.append(foot)
    return Table(head, rows, fmts, bold={len(rows) - 1})


def compare_table(entry, enabled: set[str], names: dict, lang: str, full_ean: bool) -> Table:
    """Approximate vs exact static method per destination; Σ over the ticked ones."""
    data, exact = entry.data, entry.exact
    a = per_destination(exact.left(data)).set_index("ean")
    b = per_destination(exact.data).set_index("ean")
    keys = dict(zip(data.dest_eans, exact.keys))
    head = [t("col_name", lang), t("col_ean", lang), t("x_included", lang),
            f"{t('cmp_key', lang)} [%]", t("col_consumption", lang), t("cmp_shared_edc", lang),
            t("cmp_shared_exact", lang), t("x_delta_kwh", lang), t("cmp_delta_pct", lang),
            t("x_cov_approx", lang), t("x_cov_exact", lang)]
    fmts = [None, None, None, "0.00", KWH, KWH, KWH, KWH, PCT, PCT, PCT]

    def values(sa, sb, dem):
        return [_kwh(dem), _kwh(sa), _kwh(sb), _kwh(sb - sa),
                round(100 * (sb - sa) / sb, 2) if sb else None, _pct(sa, dem), _pct(sb, dem)]

    rows = [[names.get(e, e), ean_label(e, full_ean), _yes(e in enabled, lang),
             round(100 * keys[e], 2),
             *values(a.at[e, "shared"], b.at[e, "shared"], a.at[e, "consumption"])]
            for e in data.dest_eans]
    sel = _selected(data, enabled)
    sa, sb = a.loc[sel, "shared"].sum(), b.loc[sel, "shared"].sum()
    dem = a.loc[sel, "consumption"].sum()
    rows.append([_sigma(len(sel), len(data.dest_eans), lang), None, None,
                 round(100 * sum(keys[e] for e in sel), 2), *values(sa, sb, dem)])
    return Table(head, rows, fmts, bold={len(rows) - 1})


def bill_table(entry, enabled: set[str], names: dict, lang: str, full_ean: bool) -> Table:
    """Settlement per member, Σ, then the producers as the other side of it."""
    data, bill = entry.data, entry.bill.settlement
    n_prod = len(data.source_eans)
    head = [t("col_name", lang), t("col_ean", lang), t("x_included", lang),
            t("bill_col_price", lang), t("bill_col_shared", lang), t("bill_col_saving", lang),
            t("bill_col_share", lang), tn("bill_col_payment", lang, n_prod),
            t("bill_col_unit", lang)]
    fmts = [None, None, None, "0.00", KWH, KC, KC, KC, "0.00"]
    unit = lambda pay, kwh: round(pay / kwh, 4) if kwh > 0 else None  # noqa: E731
    rows = [[names.get(e, e), ean_label(e, full_ean), _yes(e in enabled, lang),
             float(bill.prices[j]), _kwh(bill.shared[j]), round(float(bill.saving[j]), 2),
             round(float(bill.share[j]), 2), round(float(bill.payment[j]), 2),
             unit(float(bill.payment[j]), float(bill.shared[j]))]
            for j, e in enumerate(data.dest_eans)]
    kwh, paid = float(bill.shared.sum()), float(bill.payment.sum())
    rows.append(["Σ", None, None, None, _kwh(kwh), round(float(bill.saving.sum()), 2),
                 round(float(bill.share.sum()), 2), round(paid, 2), unit(paid, kwh)])
    bold = {len(rows) - 1}
    for i, src in enumerate(data.source_eans):
        rows.append([t("bill_producer", lang).format(name=names.get(src, src)),
                     ean_label(src, full_ean), None, float(bill.feed_ins[i]),
                     _kwh(bill.supplied[i]), round(float(bill.feed_in_value[i]), 2),
                     round(float(bill.producer_share[i]), 2),
                     round(float(bill.producer_income[i]), 2),
                     unit(float(bill.producer_income[i]), float(bill.supplied[i]))])
    return Table(head, rows, fmts, bold=bold)


def daily_table(entry, enabled: set[str], lang: str) -> Table:
    """kWh per day for the ticked members (the report; with the recompute also what the
    exact method shares them)."""
    data, exact = entry.data, entry.exact
    flows = aggregate_grid_flows(filter_dests(data, enabled))
    shared = [c for c in flows.columns if c.startswith("shared|")]
    cols: dict[str, pd.Series] = {}
    if data.production is not None:
        cols[f"{t('kpi_production', lang)} [kWh]"] = data.production
    cols[t("x_shared_sel", lang)] = flows[shared].sum(axis=1)
    if KEY_OTHERS in flows:
        cols[f"{t('others_shared', lang)} [kWh]"] = flows[KEY_OTHERS]
    if "GRID_UNSHARED" in flows:
        cols[t("x_unshared", lang)] = flows["GRID_UNSHARED"]
    sel = _selected(data, enabled)
    if data.fmt == "all":
        demand = [data.demand[e] for e in sel if e in data.demand]
        cols[f"{t('kpi_consumption', lang)} [kWh]"] = (
            pd.concat(demand, axis=1).sum(axis=1) if demand
            else pd.Series(0.0, index=data.frame.index))
    if "GRID_UNMET" in flows:
        cols[f"{t('kpi_from_grid', lang)} [kWh]"] = flows["GRID_UNMET"]
    if exact is not None:
        ex = exact.data.frame
        ex_cols = [c for c in ex.columns if c.startswith("shared|") and c.split("|")[2] in enabled]
        cols[t("cmp_shared_exact", lang)] = ex[ex_cols].sum(axis=1)
    daily = pd.DataFrame(cols).resample("D").sum().fillna(0.0)
    rows = [[d.date(), *(_kwh(v) for v in r)] for d, r in zip(daily.index, daily.to_numpy())]
    rows.append(["Σ", *(_kwh(v) for v in daily.sum().to_numpy())])
    return Table([t("x_date", lang), *daily.columns], rows,
                 [date_format(lang)] + [KWH] * len(daily.columns), bold={len(rows) - 1})


# ---------------------------------------------------------------------------
# The workbook
# ---------------------------------------------------------------------------


def sheets(entry, enabled: set[str], names: dict, lang: str, *, group: str = "",
           full_ean: bool = False) -> list[Sheet]:
    """The sheets of the export for this report and selection (what has been computed
    decides which ones there are)."""
    data = entry.data
    summary = [info_table(entry, enabled, names, lang, group, full_ean),
               energy_table(entry, enabled, lang)]
    if entry.exact is not None:
        summary.append(exact_table(entry, enabled, names, lang))
    if entry.bill is not None:
        summary.append(bill_totals_table(entry, enabled, lang))
    if entry.fit is not None:
        summary.append(fit_table(entry, lang))
    out = [Sheet(t("x_sheet_summary", lang), summary),
           Sheet(t("x_sheet_members", lang), [members_table(data, enabled, names, lang,
                                                            full_ean)])]
    if entry.exact is not None:
        out.append(Sheet(t("x_sheet_compare", lang),
                         [compare_table(entry, enabled, names, lang, full_ean)]))
    if entry.bill is not None:
        out.append(Sheet(t("x_sheet_bill", lang),
                         [bill_table(entry, enabled, names, lang, full_ean)]))
    out.append(Sheet(t("x_sheet_daily", lang), [daily_table(entry, enabled, lang)]))
    return out


def _sheet_title(name: str) -> str:
    """Excel sheet names: at most 31 characters, none of []:*?/\\."""
    return re.sub(r"[\[\]:*?/\\]", "-", name)[:31]


def _write(ws, tables: list[Table]) -> None:
    r = 1
    widths: dict[int, int] = {}
    for n, tbl in enumerate(tables):
        if n:
            r += 1                                   # blank row between tables
        if tbl.title:
            ws.cell(r, 1, tbl.title).font = _SECTION_FONT
            r += 1
        for c, h in enumerate(tbl.head, 1):
            cell = ws.cell(r, c, h)
            cell.font, cell.fill = _BOLD, _HEAD_FILL
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            widths[c] = max(widths.get(c, 0), min(len(str(h)), 28))
        if len(tables) == 1:
            ws.freeze_panes = ws.cell(r + 1, 2)
        r += 1
        for i, row in enumerate(tbl.rows):
            for c, v in enumerate(row, 1):
                cell = ws.cell(r, c, v)
                fmt = tbl.formats[c - 1] if c - 1 < len(tbl.formats) else None
                if c > 1 and i in tbl.row_formats and v is not None and not isinstance(v, str):
                    fmt = tbl.row_formats[i]
                if fmt is None and isinstance(v, dt.datetime):
                    fmt = "yyyy-mm-dd hh:mm"
                elif fmt is None and isinstance(v, dt.date):
                    fmt = "yyyy-mm-dd"
                elif fmt is None and isinstance(v, float):
                    fmt = KWH
                if fmt:
                    cell.number_format = fmt
                if i in tbl.bold:
                    cell.font = _BOLD
                widths[c] = max(widths.get(c, 0), min(len(str(v)) if v is not None else 0, 60))
            r += 1
    for c, w in widths.items():
        ws.column_dimensions[get_column_letter(c)].width = max(10, w + 2)


def summary_xlsx(entry, enabled: set[str], names: dict, lang: str, *, group: str = "",
                 full_ean: bool = False) -> bytes:
    """The export of one report as the bytes of an .xlsx file."""
    wb = Workbook()
    wb.remove(wb.active)
    for sh in sheets(entry, enabled, names, lang, group=group, full_ean=full_ean):
        _write(wb.create_sheet(_sheet_title(sh.name)), sh.tables)
    wb.properties.title = t("report_title", lang)
    wb.properties.creator = "EDC sharing report"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
