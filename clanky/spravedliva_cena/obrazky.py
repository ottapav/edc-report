"""Obrázky článku ze skutečné skupiny: ``python -m clanky.spravedliva_cena.obrazky``.

Spočítá vyúčtování podle přínosu stejně jako aplikace (``billing``) z reportu skupiny
v ``clanky/data/skupina.csv`` s cenami z článku (4 Kč/kWh od prodejce pro všechny členy,
výkupní cena 1 Kč/kWh) a zapíše do ``img/``:

* ``kolac_uspora.png``: kam šla úspora ze sdílení (stejný koláč jako v aplikaci);
* ``vyrobce_mesice.png``: podíl výrobce na úspoře podle měsíce.

Vypíše i čísla, která článek cituje. Potřebuje kaleido a Chrome/Chromium (cestu lze dát
v proměnné BROWSER_PATH); aplikace sama je nepotřebuje.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

import figures as F
from billing import BillResult, compute_shapley
from edc_data import (SharingData, load_report, per_destination, producer_arrays, shared_cols,
                      supplied_per_source)
from figures.base import figure
from i18n import fmt_num

from clanky import DATA, SPRAVEDLIVA_CENA

PRICE, FEED_IN, FIXED = 4.0, 1.0, 2.5         # Kč/kWh: od prodejce, výkupní, pevná cena
KEYS = [0.1, 0.5, 0.1, 0.1, 0.1]              # klíče skupiny v pořadí odběrných míst
MONTHS = ["led", "úno", "bře", "dub", "kvě", "čvn", "čvc", "srp", "zář", "říj", "lis", "pro"]


@dataclass
class Skupina:
    data: SharingData
    bill: BillResult
    monthly: pd.DataFrame                      # podíl výrobce, nasdíleno, dost výroby po měsících


def spocitej(csv: Path = DATA / "skupina.csv") -> Skupina:
    """Vyúčtování skupiny s cenami z článku a jeho rozpad po měsících."""
    d = load_report(csv.read_bytes())
    P, D = producer_arrays(d)
    totals = compute_shapley(P, D, [PRICE] * len(d.dest_eans), [FEED_IN])
    bill = BillResult.build(totals, per_destination(d)["shared"].to_numpy(),
                            supplied_per_source(d), d.frame.index, d.dest_eans, d.source_eans)
    per = bill.per_interval
    Pt = P if P.ndim == 1 else P.sum(axis=1)
    live = (Pt > 0) & (D.sum(axis=1) > 0)
    m = pd.DataFrame({
        "vyrobce": per[bill.producer_cols].sum(axis=1),
        "clenove": per[bill.members].sum(axis=1),
        "nasdileno": d.frame[shared_cols(d.frame)].sum(axis=1),
        "zive": live, "dost": live & (Pt >= D.sum(axis=1)),
    }, index=d.frame.index).resample("MS").sum()
    m["podil"] = m["vyrobce"] / (m["vyrobce"] + m["clenove"])
    return Skupina(d, bill, m)


def cisla(s: Skupina) -> dict:
    """Čísla, která článek cituje (v Kč, kWh a podílech)."""
    b = s.bill.settlement
    m = s.monthly
    members = float(b.share.sum())
    fixed = FIXED * b.shared
    P, D = producer_arrays(s.data)
    Pt = P if P.ndim == 1 else P.sum(axis=1)
    enough = (Pt > 0) & (Pt >= D.sum(axis=1))
    per = s.bill.per_interval[s.bill.members].to_numpy()
    summer = m.index.month.isin([5, 6, 7, 8])
    return dict(
        nasdileno=float(b.shared.sum()), nejvyse=b.maximum, uspora=b.realized,
        uslo=b.maximum - b.realized, uslo_kwh=(b.maximum - b.realized) / (PRICE - FEED_IN),
        ucinnost=b.efficiency, vyrobce=float(b.producer_share.sum()),
        vyrobce_podil=float(b.producer_share.sum()) / b.realized,
        prijem=float(b.producer_income.sum()), vykup=float(b.feed_in_value.sum()),
        cena_vyrobce=float(b.producer_unit_price[0]),
        clenove=members, clenove_pri_dostatku=float(per[enough].sum()) / members,
        ceny_clenu=list(b.unit_price), nasdileno_clenu=list(b.shared), podily=list(b.share),
        platby=list(b.payment), pevna_prijem=float(fixed.sum()),
        pevna_rozdil=list(fixed - b.payment),
        podil_mesice=dict(zip(m.index.strftime("%Y-%m"), m["podil"])),
        leto=(float(m["podil"][summer].min()), float(m["podil"][summer].max())),
        leto_dost=(float((m["dost"] / m["zive"])[summer].min()),
                   float((m["dost"] / m["zive"])[summer].max())),
    )


def _save(fig: go.Figure, path: Path, w: int, h: int) -> None:
    fig.update_layout(font=dict(family="DejaVu Sans, Arial"))
    fig.write_image(path, width=w, height=h, scale=2)
    print(path)


def kolac(s: Skupina, out: Path) -> None:
    th = F.theme("light")
    fig = F.fig_bill_pie(s.bill.settlement, s.data, "cs", th)
    fig.data[0].labels = ["podíl výrobce", "podíl členů", "ušlo při sdílení EDC"]
    _save(fig, out / "kolac_uspora.png", 760, 560)


def mesice(s: Skupina, out: Path) -> None:
    th = F.theme("light")
    m = s.monthly
    rok = float(m["vyrobce"].sum() / (m["vyrobce"] + m["clenove"]).sum())
    first, last = s.data.frame.index.min(), s.data.frame.index.max()
    labels = []
    for i, ts in enumerate(m.index):
        mon = MONTHS[ts.month - 1] + (f" {ts.year % 100}" if i in (0, len(m) - 1) else "")
        if i == 0 and first.day > 1:
            mon += f"<br>od {first.day}."
        elif i == len(m) - 1 and last.day < ts.days_in_month:
            mon += f"<br>do {last.day}."
        labels.append(mon)
    fig = figure("Podíl výrobce na úspoře podle měsíce", "cs", 460, th)
    fig.add_bar(x=list(range(len(labels))), y=m["podil"] * 100, marker_color=th["source"],
                text=[f"{fmt_num(v * 100, 'cs', 0)} %" for v in m["podil"]],
                textposition="outside", textfont=dict(size=12, color=th["ink"]),
                cliponaxis=False, showlegend=False)
    # vodorovné čáry jako položky legendy (popisky u čar by zakryly sloupce)
    for y, text, dash in ((50, "napůl (výroby dost pro všechny)", "dash"),
                          (rok * 100, f"celý rok: {fmt_num(rok * 100, 'cs', 0)} %", "dot")):
        fig.add_scatter(x=[-0.5, len(labels) - 0.5], y=[y, y], mode="lines", name=text,
                        line=dict(color=th["muted"], width=1.6, dash=dash))
    fig.update_traces(selector=dict(type="scatter"), xaxis="x2")
    fig.update_layout(
        xaxis2=dict(overlaying="x", range=[-0.5, len(labels) - 0.5], visible=False),
        xaxis=dict(range=[-0.5, len(labels) - 0.5]),
        legend=dict(orientation="h", x=1, xanchor="right", y=1.02, yanchor="bottom",
                    font=dict(size=12, color=th["ink"])))
    fig.update_yaxes(range=[0, 100], ticksuffix=" %", title_text="podíl výrobce na úspoře")
    fig.update_xaxes(title_text="", tickmode="array", tickvals=list(range(len(labels))),
                     ticktext=labels, zeroline=False, selector=dict(overlaying=None))
    fig.update_layout(margin=dict(t=60, b=60, l=70, r=20), bargap=0.25)
    _save(fig, out / "vyrobce_mesice.png", 900, 440)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", default=str(DATA / "skupina.csv"))
    ap.add_argument("--out", default=str(SPRAVEDLIVA_CENA.img_dir("cs")))
    a = ap.parse_args()
    s = spocitej(Path(a.csv))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    kolac(s, out)
    mesice(s, out)
    for k, v in cisla(s).items():
        print(f"{k}: {np.round(v, 4) if not isinstance(v, dict) else {a: round(b, 4) for a, b in v.items()}}")


if __name__ == "__main__":
    main()
