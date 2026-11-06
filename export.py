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
* spot (after the OTE prices were fetched): sharing vs the surplus sold on spot, the
  totals, per member and per producer, and per month;
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
from i18n import method_title, t, tn
from keyfit import pooled_keys
from recompute import grid_loss
from spot import monthly

#: MIME type of the workbook
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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
    """A percentage in full precision: the cell's number format rounds it like the page,
    so Excel shows the page's figure (rounding to 2 decimals first made 8.649 → 8.65,
    which then reads 8.7 instead of the page's 8.6)."""
    return 100 * float(x) / float(base) if x is not None and base else None


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


def _method_columns(entry, lang: str) -> list[tuple[str, SharingData, SharingData | None]]:
    """(header, data, exact recompute for "could have been shared") of every column the
    page can show for this report: the EDC report; with the exact recompute also the
    exact method and, when it used other keys than the report's, today's method replayed
    with them. The page shows the report next to the billing and the replay next to the
    exact method (:func:`ui.report._left_sides`), so the export has both."""
    data, exact = entry.data, entry.exact
    n = len(data.source_eans)
    report, replay, exact_t = (method_title(k, n, lang)
                               for k in ("col_edc", "col_edc_replay", "col_exact"))
    if exact is None:
        return [(report, data, None)]
    if exact.approx is None:
        return [(report, data, exact.data), (exact_t, exact.data, exact.data)]
    return [(report, data, None), (replay, exact.approx, exact.data),
            (exact_t, exact.data, exact.data)]


def energy_table(entry, enabled: set[str], lang: str) -> Table:
    """The energy tiles of every column the page can show (:func:`_method_columns`), with
    the shares the tiles show under the values."""
    data = entry.data
    methods = _method_columns(entry, lang)
    cols = [_summary(d, enabled, ex) for _h, d, ex in methods]
    head = [t("x_item", lang), *(h for h, _d, _ex in methods), t("x_unit", lang)]
    fmts = [None] + [KWH] * len(cols) + [None]
    if data.fmt != "all":
        rows = [[t("kpi_shared", lang), *(_kwh(s.shared) for s in cols), "kWh"]]
        return Table(head, rows, fmts, title=t("x_energy", lang))
    subset = len(_selected(data, enabled)) < len(data.dest_eans)
    # "could have been shared" is an upper bound for a selection until the recompute,
    # and the tile says so ("at most"): such a column gets its own row
    bound = [subset and ex is None for _h, _d, ex in methods]

    def only(values, keep):
        return [v if k else None for v, k in zip(values, keep)]

    exact_rows = [not b for b in bound]
    rows, pct = [], {}
    prod = [s.production for s in cols]
    for key, field_ in (("kpi_production", "production"), ("kpi_shared", "shared")):
        rows.append([t(key, lang), *(_kwh(getattr(s, field_)) for s in cols), "kWh"])
    overlap = [_kwh(s.overlap) for s in cols]
    if any(bound):
        rows.append([t("kpi_wasted_max", lang), *only(overlap, bound), "kWh"])
    if any(exact_rows):
        rows.append([t("kpi_wasted", lang), *only(overlap, exact_rows), "kWh"])
    for key, field_ in (("kpi_unshareable", "unshared_only"), ("kpi_consumption", "consumption"),
                        ("kpi_from_grid", "unmet")):
        rows.append([t(key, lang), *(_kwh(getattr(s, field_)) for s in cols), "kWh"])
    # the shares under the tiles: of the production, and "from grid" of the consumption
    of_prod = lambda key: f"{t(key, lang)} / {t('kpi_production', lang)}"  # noqa: E731
    share = lambda f: [_pct(getattr(s, f), p) for s, p in zip(cols, prod)]  # noqa: E731
    pct_rows = [[of_prod("kpi_shared"), *share("shared"), "%"]]
    if any(bound):
        pct_rows.append([of_prod("kpi_wasted_max"), *only(share("overlap"), bound), "%"])
    if any(exact_rows):
        pct_rows.append([of_prod("kpi_wasted"), *only(share("overlap"), exact_rows), "%"])
    pct_rows.append([of_prod("kpi_unshareable"), *share("unshared_only"), "%"])
    pct_rows.append([f"{t('kpi_from_grid', lang)} / {t('kpi_consumption', lang)}",
                     *(_pct(s.unmet, s.consumption) for s in cols), "%"])
    for r in pct_rows:
        pct[len(rows)] = PCT
        rows.append(r)
    return Table(head, rows, fmts, title=t("x_energy", lang), row_formats=pct)


def exact_table(entry, enabled: set[str], names: dict, lang: str) -> Table:
    exact, data = entry.exact, entry.data
    loss = grid_loss(exact.left(data), exact.data, enabled)
    source = t("keys_est" if exact.keys_estimated else "keys_user", lang)
    rows = [
        [t("x_loss_pct", lang), float(loss.pct_of_max), "%"],
        [t("x_loss_kwh", lang), _kwh(loss.lost), "kWh"],
        [t("cmp_shared_edc", lang), _kwh(loss.shared_edc), "kWh"],
        [t("cmp_shared_exact", lang), _kwh(loss.shared_exact), "kWh"],
        [t("keys_used", lang), source, None],
        [t("x_keys_sum", lang), float(100 * sum(exact.keys)), "%"],
        [t("reserve", lang), float(100 * exact.reserve), "%"],
    ]
    if exact.pool:
        rows.append([t("x_pool", lang), exact.pool, None])
    return Table([t("x_item", lang), t("x_value", lang), t("x_unit", lang)], rows,
                 [None, None, None], title=t("loss_title", lang))


def bill_totals_table(entry, enabled: set[str], lang: str) -> Table:
    bill = entry.bill.settlement
    data = entry.data
    cur = t("currency", lang)
    sel = np.array([e in enabled for e in data.dest_eans])
    n_prod = len(bill.feed_ins)
    rows = [
        [t("bt_benefit", lang), float(bill.realized), cur],
        [t("x_max_benefit", lang), float(bill.maximum), cur],
        [t("x_efficiency", lang), float(100 * bill.efficiency), "%"],
        [t("bt_lost", lang), float(max(0.0, bill.maximum - bill.realized)), cur],
        [tn("bt_producer", lang, n_prod), float(bill.producer_share.sum()), cur],
        [t("bt_members", lang), float(bill.share[sel].sum()), cur],
        [tn("bt_income", lang, n_prod), float(bill.producer_income.sum()), cur],
        [t("bt_feed_in", lang), float(bill.feed_in_value.sum()), cur],
    ]
    return Table([t("x_item", lang), t("x_value", lang), t("x_unit", lang)], rows,
                 [None, None, None], title=t("col_bill", lang))


def pool_of(data: SharingData, K) -> list[float]:
    """The pool's key of every member over the period, as the members' key column in the
    panel (:func:`keyfit.pooled_keys`)."""
    energy = [float(data.productions[e].clip(lower=0).sum()) if e in data.productions else 0.0
              for e in data.source_eans]
    return [float(x) for x in pooled_keys(K, energy)]


def pair_table(entry, names: dict, lang: str, full_ean: bool, typed=None) -> Table:
    """Several producers: the key of every pair producer -> member and the pool's key
    over the period, as in the grid of the exact method's card: ``typed`` (np × n, the
    grid with its empty cells filled by the estimate), else the keys of the recompute,
    else the estimate."""
    data = entry.data
    exact = entry.exact
    fit = entry.fit
    if typed is not None and all(k is not None for row in typed for k in row):
        K = typed
    elif exact is not None and exact.pair_keys:
        K = exact.pair_keys
    else:
        K = fit.pair_keys
    pool = pool_of(data, K)
    est = getattr(fit, "pair_keys", None)
    estimated = bool(est) and all(abs(k - e) <= 1e-9 for row, erow in zip(K, est)
                                  for k, e in zip(row, erow))
    head = [t("col_name", lang), t("col_ean", lang),
            *(f"{names.get(e, e)} {ean_label(e, full_ean)} [%]" for e in data.source_eans),
            t("x_pool_key", lang)]
    rows = [[names.get(e, e), ean_label(e, full_ean),
             *(100 * float(K[i][j]) for i in range(len(data.source_eans))),
             100 * float(pool[j])] for j, e in enumerate(data.dest_eans)]
    rows.append(["Σ", None, *(100 * float(sum(K[i])) for i in range(len(data.source_eans))),
                 100 * float(sum(pool))])
    source = t("keys_est" if estimated else "keys_user", lang)
    return Table(head, rows, [None, None] + ["0.00"] * (len(data.source_eans) + 1),
                 title=f"{t('x_pair_source', lang)}: {source}", bold={len(rows) - 1})


def fit_table(entry, lang: str) -> Table:
    fit = entry.fit
    rows = [[t("x_rounds", lang), fit.rounds, None],
            [t("x_fit_match", lang), float(100 * fit.match), "%"]]
    n = len(entry.data.source_eans)
    if n > 1:
        rows.append([t("x_pool", lang), n, None])
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
                    else float(r.coverage_pct)]
        else:
            row += [_kwh(r.shared)]
        first = r.first_data.date() if r.first_data is not None and not pd.isna(r.first_data) else None
        row += [float(r.share_of_shared_pct), first, float(r.data_pct)]
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
                float(100 * (sb - sa) / sb) if sb else None, _pct(sa, dem), _pct(sb, dem)]

    rows = [[names.get(e, e), ean_label(e, full_ean), _yes(e in enabled, lang),
             float(100 * keys[e]),
             *values(a.at[e, "shared"], b.at[e, "shared"], a.at[e, "consumption"])]
            for e in data.dest_eans]
    sel = _selected(data, enabled)
    sa, sb = a.loc[sel, "shared"].sum(), b.loc[sel, "shared"].sum()
    dem = a.loc[sel, "consumption"].sum()
    rows.append([_sigma(len(sel), len(data.dest_eans), lang), None, None,
                 float(100 * sum(keys[e] for e in sel)), *values(sa, sb, dem)])
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
    unit = lambda pay, kwh: float(pay / kwh) if kwh > 0 else None  # noqa: E731
    rows = [[names.get(e, e), ean_label(e, full_ean), _yes(e in enabled, lang),
             float(bill.prices[j]), _kwh(bill.shared[j]), float(bill.saving[j]),
             float(bill.share[j]), float(bill.payment[j]),
             unit(float(bill.payment[j]), float(bill.shared[j]))]
            for j, e in enumerate(data.dest_eans)]
    kwh, paid = float(bill.shared.sum()), float(bill.payment.sum())
    rows.append(["Σ", None, None, None, _kwh(kwh), float(bill.saving.sum()),
                 float(bill.share.sum()), float(paid), unit(paid, kwh)])
    bold = {len(rows) - 1}
    for i, src in enumerate(data.source_eans):
        rows.append([t("bill_producer", lang).format(name=names.get(src, src)),
                     ean_label(src, full_ean), None, float(bill.feed_ins[i]),
                     _kwh(bill.supplied[i]), float(bill.feed_in_value[i]),
                     float(bill.producer_share[i]),
                     float(bill.producer_income[i]),
                     unit(float(bill.producer_income[i]), float(bill.supplied[i]))])
    return Table(head, rows, fmts, bold=bold)


def _daily_flows(d: SharingData, enabled: set[str], lang: str, suffix: str = "") -> dict:
    """kWh per 15 min of one method for the ticked members: shared to them, shared to the
    unticked ones, unshared, from the grid (the series of the daily plot)."""
    flows = aggregate_grid_flows(filter_dests(d, enabled))
    shared = [c for c in flows.columns if c.startswith("shared|")]
    out = {t("x_shared_sel", lang) + suffix: flows[shared].sum(axis=1)}
    if KEY_OTHERS in flows:
        out[f"{t('others_shared', lang)} [kWh]{suffix}"] = flows[KEY_OTHERS]
    if "GRID_UNSHARED" in flows:
        out[t("x_unshared", lang) + suffix] = flows["GRID_UNSHARED"]
    if "GRID_UNMET" in flows:
        out[f"{t('kpi_from_grid', lang)} [kWh]{suffix}"] = flows["GRID_UNMET"]
    return out


def daily_table(entry, enabled: set[str], lang: str) -> Table:
    """kWh per day for the ticked members: the series of the daily plots, for every
    column the page can show (the report; the replay and the exact method after the
    recompute, marked in the header)."""
    data, exact = entry.data, entry.exact
    cols: dict[str, pd.Series] = {}
    if data.production is not None:
        cols[f"{t('kpi_production', lang)} [kWh]"] = data.production
    sel = _selected(data, enabled)
    if data.fmt == "all":
        demand = [data.demand[e] for e in sel if e in data.demand]
        cols[f"{t('kpi_consumption', lang)} [kWh]"] = (
            pd.concat(demand, axis=1).sum(axis=1) if demand
            else pd.Series(0.0, index=data.frame.index))
    cols.update(_daily_flows(data, enabled, lang))
    if exact is not None:
        if exact.approx is not None:
            cols.update(_daily_flows(exact.approx, enabled, lang, f" – {t('x_m_replay', lang)}"))
        cols.update(_daily_flows(exact.data, enabled, lang, f" – {t('x_m_exact', lang)}"))
    daily = pd.DataFrame(cols).resample("D").sum().fillna(0.0)
    rows = [[d.date(), *(_kwh(v) for v in r)] for d, r in zip(daily.index, daily.to_numpy())]
    rows.append(["Σ", *(_kwh(v) for v in daily.sum().to_numpy())])
    return Table([t("x_date", lang), *daily.columns], rows,
                 [date_format(lang)] + [KWH] * len(daily.columns), bold={len(rows) - 1})


def spot_tables(cmp, data: SharingData, enabled: set[str], names: dict, lang: str,
                full_ean: bool) -> list[Table]:
    """Sharing vs spot: the totals (the tiles), per member and producer (the table), and
    the prices per month."""
    cur, unit = t("currency", lang), f"{t('currency', lang)}/kWh"
    num = lambda x: None if x is None or not np.isfinite(x) else float(x)  # noqa: E731
    per = lambda x, kwh: num(x / kwh) if kwh > 0 else None  # noqa: E731
    totals = Table([t("x_item", lang), t("x_value", lang), t("x_unit", lang)], [
        [t("spot_t_revenue", lang), num(cmp.spot_revenue), cur],
        [t("spot_t_sharing", lang), num(cmp.sharing_value), cur],
        [t("spot_col_gain", lang), num(cmp.gain), cur],
        [t("spot_t_shared", lang), num(cmp.gain_shared), cur],
        [t("spot_t_unshared", lang), num(cmp.gain_unshared), cur],
        [t("x_spot_surplus", lang), num(cmp.surplus_kwh), "kWh"],
        [t("spot_mean", lang), num(cmp.mean_spot), unit],
        [t("spot_capture", lang), num(cmp.capture), unit],
        [t("spot_supplier_avg", lang), num(cmp.supplier_avg), unit],
        [t("x_spot_break_even", lang), num(cmp.break_even_avg), unit],
        [t("spot_fee", lang), 1000 * cmp.fee, f"{cur}/MWh"],
        [t("spot_curtail", lang), _yes(cmp.curtail, lang), None],
        [t("spot_t_negative", lang), num(cmp.negative_kwh), "kWh"],
        [t("x_spot_negative_cost", lang), num(cmp.negative_cost), cur],
    ], [None, "#,##0.00", None], title=t("spot_title", lang))
    head = [t("col_name", lang), t("col_ean", lang), t("x_included", lang),
            t("spot_col_price", lang), t("spot_col_kwh", lang), t("spot_col_sharing", lang),
            t("spot_col_spot", lang), t("spot_col_gain", lang), t("spot_col_unit", lang)]
    rows = [[names.get(e, e), ean_label(e, full_ean), _yes(e in enabled, lang),
             num(cmp.prices[j]), _kwh(cmp.shared[j]), num(cmp.at_supplier[j]),
             num(cmp.shared_at_spot[j]), num(cmp.member_gain[j]),
             per(cmp.shared_at_spot[j], cmp.shared[j])]
            for j, e in enumerate(data.dest_eans)]
    kwh = float(cmp.shared.sum())
    rows.append(["Σ", None, None, None, _kwh(kwh), num(cmp.at_supplier.sum()),
                 num(cmp.shared_at_spot.sum()), num(cmp.gain_shared),
                 per(cmp.shared_at_spot.sum(), kwh)])
    bold = {len(rows) - 1}
    for i, src in enumerate(data.source_eans):
        rows.append([t("spot_row_unshared", lang).format(name=names.get(src, src)),
                     ean_label(src, full_ean), None, num(cmp.feed_ins[i]),
                     _kwh(cmp.unshared[i]), num(cmp.at_feed_in[i]),
                     num(cmp.unshared_at_spot[i]), num(cmp.unshared_gain[i]),
                     per(cmp.unshared_at_spot[i], cmp.unshared[i])])
    rows.append([t("spot_total", lang), None, None, None, _kwh(cmp.surplus_kwh),
                 num(cmp.sharing_value), num(cmp.spot_revenue), num(cmp.gain),
                 per(cmp.spot_revenue, cmp.surplus_kwh)])
    bold.add(len(rows) - 1)
    per_member = Table(head, rows, [None, None, None, "0.00", KWH, KC, KC, KC, "0.00"],
                       title=t("spot_table_title", lang), bold=bold)
    producers = Table([t("col_name", lang), t("col_ean", lang), t("x_spot_surplus", lang),
                       t("spot_t_revenue", lang) + f" [{cur}]",
                       t("x_spot_break_even", lang) + f" [{unit}]"],
                      [[names.get(src, src), ean_label(src, full_ean),
                        _kwh(cmp.supplied[i] + cmp.unshared[i]), num(cmp.revenue[i]),
                        num(cmp.break_even[i])] for i, src in enumerate(data.source_eans)],
                      [None, None, KWH, KC, "0.00"])
    m = monthly(cmp)
    months = Table([t("x_month", lang), t("spot_mean", lang), t("spot_capture", lang),
                    t("spot_supplier_avg", lang), t("spot_feed_in_avg", lang),
                    t("x_spot_surplus", lang)],
                   [[str(p), num(r.mean_spot), num(r.capture), num(r.supplier), num(r.feed_in),
                     _kwh(r.surplus)] for p, r in zip(m.index, m.itertuples())],
                   [None, "0.000", "0.000", "0.000", "0.000", KWH],
                   title=t("spot_monthly_title", lang) + f" [{unit}]")
    return [totals, per_member, producers, months]


# ---------------------------------------------------------------------------
# The workbook
# ---------------------------------------------------------------------------


def sheets(entry, enabled: set[str], names: dict, lang: str, *, group: str = "",
           full_ean: bool = False, pair_keys=None, spot_cmp=None) -> list[Sheet]:
    """The sheets of the export for this report and selection (what has been computed
    decides which ones there are); ``spot_cmp`` is the spot comparison as on the page."""
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
    has_pairs = ((entry.exact is not None and entry.exact.pair_keys)
                 or (entry.fit is not None and entry.fit.pair_keys))
    if has_pairs:
        out.append(Sheet(t("x_sheet_pairs", lang),
                         [pair_table(entry, names, lang, full_ean, pair_keys)]))
    if entry.bill is not None:
        out.append(Sheet(t("x_sheet_bill", lang),
                         [bill_table(entry, enabled, names, lang, full_ean)]))
    if spot_cmp is not None:
        out.append(Sheet(t("x_sheet_spot", lang),
                         spot_tables(spot_cmp, data, enabled, names, lang, full_ean)))
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
                if fmt is None and isinstance(v, float) and row[-1] == "%":
                    fmt = PCT                        # a percentage in a summary table
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
                 full_ean: bool = False, pair_keys=None, spot_cmp=None) -> bytes:
    """The export of one report as the bytes of an .xlsx file; ``pair_keys`` are the
    keys per producer as in the page's grid (several producers)."""
    wb = Workbook()
    wb.remove(wb.active)
    for sh in sheets(entry, enabled, names, lang, group=group, full_ean=full_ean,
                     pair_keys=pair_keys, spot_cmp=spot_cmp):
        _write(wb.create_sheet(_sheet_title(sh.name)), sh.tables)
    wb.properties.title = t("report_title", lang)
    wb.properties.creator = "EDC sharing report"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
