"""Obrázky článku z reálných dat skupiny: ``python -m clanek.obrazky REPORT.csv``.

Kreslí je stejné funkce jako aplikace (``figures``) a zapíše je do ``clanek/img/``:
kolac.png (kam šla výroba) a den_priblizna.png / den_presna.png (den, kdy přesná metoda
přidá nejvíc). Členy pojmenuje anonymně „Odběr 1 (10 %)“ atd.

Potřebuje kaleido a Chrome/Chromium (cestu lze dát v proměnné BROWSER_PATH);
aplikace sama je nepotřebuje. Klíče skupiny zadejte jako --keys 0.1,0.5,… v pořadí
odběrných míst v reportu (výchozí jsou klíče skupiny z článku).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import figures as F
from edc_data import (
    aggregate_grid_flows, compute_wasted_split, filter_dests, load_report, shared_cols,
)
from recompute import recompute

from . import IMG

KEYS = [0.1, 0.5, 0.1, 0.1, 0.1]      # skupina z článku (součet 90 %)
MONTHS = ["leden", "únor", "březen", "duben", "květen", "červen", "červenec", "srpen",
          "září", "říjen", "listopad", "prosinec"]


def _save(fig, path: Path, w: int, h: int) -> None:
    fig.update_layout(font=dict(family="DejaVu Sans, Arial"))
    fig.write_image(path, width=w, height=h, scale=2)
    print(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", help="úplný report sdílení z portálu EDC")
    ap.add_argument("--keys", default=",".join(map(str, KEYS)),
                    help="klíče odběrných míst jako podíly, oddělené čárkou")
    ap.add_argument("--out", default=str(IMG), help="výstupní složka (výchozí clanek/img)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    d = load_report(Path(a.csv).read_bytes())
    keys = [float(k) for k in a.keys.split(",")]
    exact = recompute(d, keys).data
    members = set(d.dest_eans)
    names = {d.source_eans[0]: "Výroba A"}
    names |= {e: f"Odběr {i} ({round(k * 100)} %)"
              for i, (e, k) in enumerate(zip(d.dest_eans, keys), 1)}
    th = F.theme("light")

    # kam šla výroba; „mohlo být sdíleno“ = co přidá přesná metoda
    sa, sb = filter_dests(d, members), filter_dests(exact, members)
    total = float(d.production.sum()) if hasattr(d.production, "sum") else float(d.production)
    fig = F.fig_wasted_pie(compute_wasted_split(sa), "cs", th, exact_based=True)
    fig.data[0].labels = ["sdíleno", "mohlo být sdíleno", "přetok do sítě"]
    start, end = sa.index.min(), sa.index.max()
    fig.update_layout(
        title_text=f"Kam šla výroba ({MONTHS[start.month - 1]} {start.year} – "
                   f"{MONTHS[end.month - 1]} {end.year})",
        annotations=[dict(
            text=f"Celkem výroba {total:,.0f} kWh · „mohlo být sdíleno“ = co navíc rozdělí "
                 "přesná statická metoda".replace(",", " "),
            x=0.5, y=0, yshift=-58, xref="paper", yref="paper", yanchor="top",
            showarrow=False, font=dict(size=12, color=th["muted"]))])
    _save(fig, out / "kolac.png", 760, 560)

    # den, kdy přesná metoda přidá nejvíc: přibližná vs přesná na společné ose
    gain = (sb[shared_cols(sb)].sum(axis=1) - sa[shared_cols(sa)].sum(axis=1))
    day = gain.groupby(sa.index.normalize()).sum().idxmax()
    iso = str(day.date())
    y_max = max(F.intraday_ymax(sa, iso), F.intraday_ymax(sb, iso))
    for tag, df, data, title in (("priblizna", sa, d, "Přibližná statická metoda (dnes)"),
                                 ("presna", sb, exact, "Přesná statická metoda")):
        fig = F.fig_intraday(df, data, names, iso, y_max=y_max, lang="cs", th=th)
        fig.update_layout(title_text=f"{title} – {day.day}. {day.month}. {day.year}")
        for tr in fig.data:
            tr.name = (tr.name.replace("SÍŤ (nepokryto)", "ze sítě (nepokryto)")
                              .replace("SÍŤ (nesdíleno)", "do sítě (nesdíleno)"))
        _save(fig, out / f"den_{tag}.png", 900, 440)


if __name__ == "__main__":
    main()
