"""What the page shows besides the figures: facts, tiles, tables and result summaries.

Pure functions of the data: they build Dash components and know nothing of callbacks.
"""

from __future__ import annotations

import numpy as np
from dash import html

from billing import BillResult, Billing
from edc_data import (
    SharingData, Summary, exact_gain, per_destination, summarize, with_overlap,
)
from figures import colour_map
from i18n import fmt_date, fmt_duration, fmt_num, fmt_pct, fmt_signed, t
from keyfit import KeyFit
from recompute import Recomputed, grid_loss

from . import members
from .widgets import (
    BLUE, GREEN, GREY, LIGHT_GREY, NBSP, RED, cell, hint, kv, muted, name_cell, num, table,
    tile, tiles, two_lines,
)


def _kwh(x, lang: str) -> str:
    return f"{fmt_num(x, lang)} kWh"


def _share(x, base, lang: str) -> str:
    return fmt_pct(100 * x / base, lang) if base else "—"


# ---------------------------------------------------------------------------
# General information
# ---------------------------------------------------------------------------


def facts(filename: str, data: SharingData, enabled: set[str], names: dict, lang: str):
    s = summarize(data, enabled)
    items = [
        kv(t("file", lang), filename),
        kv(t("report_type", lang), t("type_all" if data.fmt == "all" else "type_part", lang)),
        kv(t("period", lang),
           f"{fmt_date(s.date_from, lang)} – {fmt_date(s.date_to, lang)} "
           f"({s.n_days} {t('days', lang)}, {fmt_num(s.n_rows, lang)} {t('intervals', lang)})"),
        kv(t("producer", lang), ", ".join(f"{names[e]} ({e})" for e in data.source_eans)),
        kv(t("n_dest", lang), t("selected_of", lang).format(sel=s.n_selected, n=s.n_dests)),
    ]
    if s.peak_production_kw is not None:
        items.append(kv(t("peak", lang), f"{fmt_num(s.peak_production_kw, lang, 2)} kW"))
    if s.best_day is not None:
        items.append(kv(t("best_day", lang), f"{fmt_date(s.best_day, lang)} "
                                             f"({fmt_num(s.best_day_shared, lang, 1)} kWh)"))
    items.append(kv(t("days_sharing", lang), f"{s.days_with_sharing} / {s.n_days}"))
    return html.Dl(className="facts", children=items)


def data_notes(data: SharingData, lang: str):
    if not data.notes:
        return []
    return html.Details(className="notes", children=[
        html.Summary(f"{t('notes', lang)} ({len(data.notes)})"),
        html.Ul([html.Li(n) for n in data.notes]),
    ])


# ---------------------------------------------------------------------------
# Tiles
# ---------------------------------------------------------------------------


def _summary(data: SharingData, enabled: set[str], exact: SharingData | None) -> Summary:
    """``summarize`` where, once the exact recompute exists, "could have been shared"
    of the EDC report is what the exact method really adds to the selection."""
    s = summarize(data, enabled)
    if exact is None or data is exact or s.overlap is None:
        return s
    return with_overlap(s, exact_gain(data, exact, enabled))


def energy_tiles(data: SharingData, enabled: set[str], lang: str, *,
                 ref: SharingData | None = None, pad: bool = False,
                 exact: SharingData | None = None) -> list:
    """KPI tiles in kWh. With ``ref`` (the EDC report, for the recomputed column) the
    sub-line also shows the difference to it; ``pad`` reserves that line, so paired
    columns stay level. ``exact`` is the recompute (see :func:`_summary`)."""
    s = _summary(data, enabled, exact)
    r = _summary(ref, enabled, exact) if ref is not None else None
    subset = len(enabled & set(data.dest_eans)) < len(data.dest_eans)

    def sub(main: str, field: str, higher_is_better: bool = True):
        cur, old = getattr(s, field), getattr(r, field) if r is not None else None
        if cur is None or old is None:
            return two_lines(main) if pad else main
        d = cur - old
        cls = ("delta" if abs(d) <= 0.05
               else "delta good" if (d > 0) == higher_is_better else "delta bad")
        return two_lines(main, html.Span(f"{fmt_signed(d, lang)} kWh {t('vs_edc', lang)}",
                                         className=cls))

    if data.fmt != "all":
        return tiles([tile(t("kpi_shared", lang), _kwh(s.shared, lang), None, GREEN)])
    prod = s.production or 0.0
    of_prod = lambda x: f"{_share(x, prod, lang)} {t('of_production', lang)}"  # noqa: E731
    wasted_key = "kpi_wasted_max" if subset and exact is None else "kpi_wasted"
    items = [
        tile(t("kpi_production", lang), _kwh(s.production, lang), None, GREEN),
        tile(t("kpi_shared", lang), _kwh(s.shared, lang), sub(of_prod(s.shared), "shared"),
             GREEN),
        tile(t(wasted_key, lang), _kwh(s.overlap, lang),
             sub(of_prod(s.overlap), "overlap", higher_is_better=False), RED),
        tile(t("kpi_unshareable", lang), _kwh(s.unshared_only, lang),
             sub(of_prod(s.unshared_only), "unshared_only", higher_is_better=False), GREY),
        tile(t("kpi_consumption", lang), _kwh(s.consumption, lang), None, None),
        tile(t("kpi_from_grid", lang), _kwh(s.unmet, lang),
             sub(f"{_share(s.unmet, s.consumption, lang)} {t('of_consumption', lang)}",
                 "unmet", higher_is_better=False), LIGHT_GREY),
    ]
    note = t("kpi_note", lang) + (t("kpi_note_max", lang) if subset and exact is None else "")
    return tiles(items, note)


def bill_tiles(bill: Billing, data: SharingData, enabled: set[str], lang: str) -> list:
    """Six tiles in Kč, two sub-lines each like the paired energy tiles."""
    cur = t("currency", lang)
    kc = lambda x: f"{fmt_num(x, lang)} {cur}"  # noqa: E731
    sel = np.array([e in enabled for e in data.dest_eans])
    n_sel, n = int(sel.sum()), len(data.dest_eans)
    member_share = float(bill.share[sel].sum())
    lost = max(0.0, bill.maximum - bill.realized)
    kwh = float(bill.shared.sum())
    of_benefit = lambda x: f"{_share(x, bill.realized, lang)} {t('bt_of_benefit', lang)}"  # noqa: E731
    scope = t("bt_selected", lang).format(n=n_sel, m=n) if n_sel < n else NBSP
    unit = f"{fmt_num(bill.producer_income / kwh, lang, 2)} {cur}" if kwh else "—"
    items = [
        tile(t("bt_benefit", lang), kc(bill.realized),
             two_lines(t("bt_benefit_sub", lang).format(
                 eff=fmt_pct(100 * bill.efficiency, lang), max=kc(bill.maximum))), GREEN),
        tile(t("bt_lost", lang), kc(lost),
             two_lines(f"{_share(lost, bill.maximum, lang)} {t('bt_of_max', lang)}"), RED),
        tile(t("bt_producer", lang), kc(bill.producer_share),
             two_lines(of_benefit(bill.producer_share)), GREEN),
        tile(t("bt_members", lang), kc(member_share),
             two_lines(of_benefit(member_share), scope), BLUE),
        tile(t("bt_income", lang), kc(bill.producer_income),
             two_lines(t("bt_income_sub", lang).format(unit=unit)), None),
        tile(t("bt_feed_in", lang), kc(bill.feed_in_value),
             two_lines(t("bt_feed_in_sub", lang).format(
                 price=f"{fmt_num(bill.feed_in, lang, 2)} {cur}/kWh",
                 kwh=fmt_num(kwh, lang, 1))), GREY),
    ]
    return tiles(items, t("bt_note", lang))


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _name_head(lang: str) -> str:
    return f"{t('col_name', lang)} / {t('col_ean', lang)}"


def _sigma(n_sel: int, n: int, lang: str) -> str:
    return "Σ" if n_sel == n else f"Σ {t('cmp_selected', lang).format(n=n_sel, m=n)}"


def dest_table(data: SharingData, enabled: set[str], names: dict, lang: str, top=None):
    """Per destination (EDC report); unticked rows are dimmed, Σ is over all."""
    df = per_destination(data)
    cmap = colour_map(data, top)
    is_all = data.fmt == "all"
    head = [_name_head(lang)]
    head += ([t("col_consumption", lang), t("col_shared", lang), t("col_unmet", lang),
              t("col_coverage", lang)] if is_all else [t("col_shared", lang)])
    head += [t("col_share", lang), t("col_data", lang)]
    rows = []
    for r in df.itertuples():
        cells = name_cell(names[r.ean], r.ean, cmap[r.ean])
        if is_all:
            cells += (num(fmt_num(r.consumption, lang, 1)) + num(fmt_num(r.shared, lang, 1))
                      + num(fmt_num(r.unmet, lang, 1)) + num(fmt_pct(r.coverage_pct, lang)))
        else:
            cells += num(fmt_num(r.shared, lang, 1))
        cells += (num(fmt_pct(r.share_of_shared_pct, lang))
                  + cell(f"{fmt_date(r.first_data, lang)}{muted(fmt_pct(r.data_pct, lang, 0))}",
                         "num", t("col_data_pct", lang)))
        rows.append(("" if r.ean in enabled else "off", cells))
    foot = cell("<b>Σ</b>")
    if is_all:
        c, sh, u = df["consumption"].sum(), df["shared"].sum(), df["unmet"].sum()
        foot += (num(fmt_num(c, lang, 1), True) + num(fmt_num(sh, lang, 1), True)
                 + num(fmt_num(u, lang, 1), True)
                 + num(fmt_pct(100 * sh / c if c else None, lang), True))
    else:
        foot += num(fmt_num(df["shared"].sum(), lang, 1), True)
    foot += num(fmt_pct(100.0, lang), True) + cell("")
    return table(head, rows, foot)


def cmp_table(data: SharingData, exact: Recomputed, enabled: set[str], names: dict,
              lang: str, top=None) -> list:
    """EDC report vs exact method per destination; Σ over the ticked ones."""
    a = per_destination(data).set_index("ean")
    b = per_destination(exact.data).set_index("ean")
    keys = dict(zip(data.dest_eans, exact.keys))
    ksum = sum(exact.keys) or 1.0
    cmap = colour_map(data, top)
    head = [_name_head(lang), t("cmp_key", lang), t("col_consumption", lang),
            t("cmp_shared_edc", lang), t("cmp_shared_exact", lang), t("cmp_delta_pct", lang),
            t("cmp_cov", lang)]
    cov = lambda x, dem: fmt_pct(100 * x / dem if dem else None, lang)  # noqa: E731
    err = lambda sa, sb: fmt_pct(100 * (sb - sa) / sb, lang) if sb else "—"  # noqa: E731

    def cells(sa, sb, dem):
        return (num(fmt_num(dem, lang, 1)) + num(fmt_num(sa, lang, 1))
                + num(fmt_num(sb, lang, 1), True) + num(err(sa, sb))
                + num(f"{cov(sa, dem)} → {cov(sb, dem)}"))

    rows = []
    for e in data.dest_eans:
        key = f"{fmt_pct(100 * keys[e], lang, 1)}{muted(fmt_pct(100 * keys[e] / ksum, lang, 1))}"
        rows.append(("" if e in enabled else "off",
                     name_cell(names[e], e, cmap[e]) + num(key)
                     + cells(a.at[e, "shared"], b.at[e, "shared"], a.at[e, "consumption"])))
    sel = [e for e in data.dest_eans if e in enabled]
    sa, sb = a.loc[sel, "shared"].sum(), b.loc[sel, "shared"].sum()
    dem = a.loc[sel, "consumption"].sum()
    foot = (cell(f"<b>{_sigma(len(sel), len(data.dest_eans), lang)}</b>")
            + num(fmt_pct(100 * sum(keys[e] for e in sel), lang, 1), True)
            + num(fmt_num(dem, lang, 1), True) + num(fmt_num(sa, lang, 1), True)
            + num(fmt_num(sb, lang, 1), True)
            + num(fmt_pct(100 * (sb - sa) / sb if sb else None, lang), True)
            + num(f"{cov(sa, dem)} → {cov(sb, dem)}", True))
    return [table(head, rows, foot), hint(t("cmp_error_hint", lang))]


def bill_table(bill: Billing, data: SharingData, names: dict, lang: str, top=None,
               enabled: set[str] | None = None):
    """Settlement per member; Σ row, then the producer as the other side of it."""
    enabled = set(data.dest_eans) if enabled is None else enabled
    cmap = colour_map(data, top)
    kc = lambda x: fmt_num(x, lang, 2)  # noqa: E731
    unit = lambda pay, kwh: fmt_num(pay / kwh, lang, 2) if kwh > 0 else "—"  # noqa: E731
    head = [_name_head(lang), t("bill_col_price", lang), t("bill_col_shared", lang),
            t("bill_col_saving", lang), t("bill_col_share", lang), t("bill_col_payment", lang),
            t("bill_col_unit", lang)]
    rows = [("" if e in enabled else "off",
             name_cell(names[e], e, cmap[e]) + num(fmt_num(bill.prices[j], lang, 2))
             + num(fmt_num(bill.shared[j], lang, 1)) + num(kc(bill.saving[j]))
             + num(kc(bill.share[j]), True) + num(kc(bill.payment[j]))
             + num(unit(bill.payment[j], bill.shared[j])))
            for j, e in enumerate(data.dest_eans)]
    src = data.source_eans[0]
    kwh = float(bill.shared.sum())
    total = (cell("<b>Σ</b>") + cell("") + num(fmt_num(kwh, lang, 1), True)
             + num(kc(float(bill.saving.sum())), True) + num(kc(float(bill.share.sum())), True)
             + num(kc(bill.producer_income), True) + num(unit(bill.producer_income, kwh), True))
    producer = (name_cell(t("bill_producer", lang).format(name=names[src]), src, GREEN)
                + num(fmt_num(bill.feed_in, lang, 2)) + num(fmt_num(kwh, lang, 1))
                + num(kc(bill.feed_in_value) + muted(t("bill_feed_in_value", lang)))
                + num(kc(bill.producer_share), True)
                + num(kc(bill.producer_income) + muted(t("bill_receives", lang)))
                + num(unit(bill.producer_income, kwh)))
    return table(head, rows, [total, producer])


# ---------------------------------------------------------------------------
# Results in the computation cards
# ---------------------------------------------------------------------------


def fit_summary(fit: KeyFit, data: SharingData, rows: list[dict], lang: str):
    """Summary of the key estimate, and the grid row updates: the estimated key into
    empty key cells, the consistency range as tooltip, a warning mark where the report
    cannot pin the key down."""
    rounds = lambda r: t(f"rounds_{r}", lang)  # noqa: E731
    pct2 = lambda x: fmt_num(100 * x, lang, 2)  # noqa: E731
    other = "".join(t("fit_other", lang).format(rounds=rounds(r), pct=fmt_pct(100 * m, lang))
                    for r, m in fit.tried.items() if r != fit.rounds)
    summary = t("fit_summary", lang).format(
        rounds=rounds(fit.rounds), pct=fmt_pct(100 * fit.match, lang), other=other,
        secs=fmt_duration(fit.seconds, lang))
    idx = {e: i for i, e in enumerate(data.dest_eans)}
    update, wide = [], False
    for r in rows:
        i = idx.get(r.get("ean"))
        if i is None:
            continue
        status = fit.status[i]
        lo, hi = fit.ranges[i] if i < len(fit.ranges) else (fit.keys[i], fit.keys[i])
        warn = False
        if status == "no_data":
            warn, text = True, t("key_nodata", lang)
        elif status == "zero":
            text = t("key_zero", lang).format(hi=pct2(hi))
        elif status == "always_covered" or hi >= 0.999:
            warn, text = True, t("key_lower", lang).format(lo=pct2(lo))
        else:
            warn = hi - lo > max(0.002, 0.05 * fit.keys[i])   # > 0.2 pp or 5 % of the key
            text = t("key_range", lang).format(lo=pct2(lo), hi=pct2(hi))
        wide = wide or warn
        key = r.get("key") if r.get("key") not in (None, "") else members.pct_key(fit.keys[i])
        update.append(dict(r, key=key, range=text, warn=warn))
    notes = [html.P([html.B(f"{t('fit_title', lang)}: "), summary], className="fit-line")]
    if fit.match < 0.95:
        notes.append(hint(t("fit_low", lang), "stale"))
    elif fit.rough:
        notes.append(hint(t("fit_rough", lang)))
    elif wide:
        notes.append(hint(t("fit_check", lang)))
    return notes, update


def _stat(label: str, value: str, sub: str) -> html.Div:
    return html.Div(className="tstat", children=[
        html.Div(label, className="tstat-label"),
        html.Div(value, className="tstat-value"),
        html.Div(sub, className="tstat-sub"),
    ])


def exact_result(exact: Recomputed, data: SharingData, enabled: set[str], names: dict,
                 lang: str) -> list:
    """Sharing error of the EDC report, timing of the recompute, keys used."""
    tm = exact.timing
    n = lambda x: fmt_num(x, lang)  # noqa: E731
    clock = t("t_clock_cpu" if tm.clock.startswith("thread") else "t_clock_wall", lang)
    stats = html.Div(className="timing-grid", children=[
        _stat(t("t_intervals", lang), n(tm.intervals),
              t("t_breakdown", lang).format(a=n(tm.n_night), b=n(tm.n_enough), c=n(tm.n_full))),
        _stat(t("t_total", lang), fmt_duration(tm.t_total, lang),
              f"{t('t_members', lang)}: {tm.members} · {clock}"),
        _stat(t("t_per", lang), fmt_duration(tm.per_interval, lang),
              f"{fmt_duration(tm.per_full, lang)} {t('t_per_full', lang)}"),
        _stat(t("t_wall", lang), fmt_duration(tm.t_wall, lang), NBSP),
    ])
    loss = grid_loss(data, exact.data, enabled)
    n_sel = len([e for e in data.dest_eans if e in enabled])
    scope = ("" if n_sel == len(data.dest_eans)
             else f" — {t('loss_selected', lang).format(n=n_sel, m=len(data.dest_eans))}")
    if loss.negligible:
        loss_box = html.Div(className="loss-box ok", children=[
            html.Div(t("loss_title", lang) + scope, className="loss-title"),
            html.Div(t("loss_none", lang), className="loss-text")])
    else:
        loss_box = html.Div(className="loss-box", children=[
            html.Div([html.Span(fmt_pct(loss.pct_of_max, lang, 1), className="loss-pct"),
                      html.Span(t("loss_title", lang) + scope, className="loss-title")]),
            html.Div(t("loss_text", lang).format(
                max=fmt_num(loss.shared_exact, lang, 1), edc=fmt_num(loss.shared_edc, lang, 1),
                kwh=fmt_num(loss.lost, lang, 1)), className="loss-text")])
    used = " · ".join(f"{names[e]} {fmt_pct(100 * k, lang, 1)}"
                      for e, k in zip(data.dest_eans, exact.keys))
    source = t("keys_est" if exact.keys_estimated else "keys_user", lang)
    reserve = (f" · {t('reserve', lang)}: {fmt_pct(100 * exact.reserve, lang, 1)}"
               if exact.reserve else "")
    return [
        loss_box,
        html.H3(t("timing_title", lang), className="sub-title"),
        stats,
        html.P([html.B(f"{t('keys_used', lang)} ({source}): "), used,
                f" ({t('keys_sum', lang)} {fmt_pct(100 * sum(exact.keys), lang, 1)}){reserve}"],
               className="keys-line"),
        hint(t("edc_check", lang).format(rounds=t(f"rounds_{exact.rounds}", lang),
                                         pct=fmt_pct(100 * exact.edc_match, lang, 1))),
    ]


def bill_result(result: BillResult, lang: str) -> list:
    """Summary of the billing in its card (the table is below the columns)."""
    bill, res = result.settlement, result.totals
    cur = t("currency", lang)
    money = lambda x: f"{fmt_num(x, lang, 2)}{NBSP}{cur}"  # noqa: E731
    return [
        html.P(t("bill_summary", lang).format(real=money(bill.realized), max=money(bill.maximum),
                                              eff=fmt_pct(100 * bill.efficiency, lang, 1)),
               className="fit-line"),
        hint(t("bill_hint", lang)),
        hint(t("bill_timing", lang).format(
            secs=fmt_duration(res.seconds, lang), scarce=fmt_num(res.n_scarce, lang),
            covered=fmt_num(res.n_covered, lang), night=fmt_num(res.n_night, lang))),
    ]
