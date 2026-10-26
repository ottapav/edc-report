"""Obrázky článku z reálných dat skupiny: ``python -m clanek.obrazky REPORT.csv``.

Kreslí je stejné funkce jako aplikace (``figures``) a zapíše je do ``clanek/img/``
(česky), ``clanek/img/en/`` a ``clanek/img/de/``: kolac.png (kam šla výroba) a
den_priblizna.png / den_presna.png (den, kdy přesná metoda přidá nejvíc). Členy pojmenuje
anonymně „Odběr 1 (10 %)“ atd. Jazyk volí ``--lang cs|en|de|all`` (výchozí je all).

Potřebuje kaleido a Chrome/Chromium (cestu lze dát v proměnné BROWSER_PATH);
aplikace sama je nepotřebuje. Klíče skupiny zadejte jako --keys 0.1,0.5,… v pořadí
odběrných míst v reportu (výchozí jsou klíče skupiny z článku).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import figures as F
from i18n import fmt_num
from edc_data import (
    aggregate_grid_flows, compute_wasted_split, filter_dests, load_report, shared_cols,
)
from recompute import recompute

from . import LANGS, img_dir

KEYS = [0.1, 0.5, 0.1, 0.1, 0.1]      # skupina z článku (součet 90 %)
T = {
    "cs": dict(
        months=["leden", "únor", "březen", "duben", "květen", "červen", "červenec", "srpen",
                "září", "říjen", "listopad", "prosinec"],
        pie_labels=["sdíleno", "mohlo být sdíleno", "přetok do sítě"],
        pie_title="Kam šla výroba ({a} – {b})",
        pie_note="Celkem výroba {total} kWh · „mohlo být sdíleno“ = co navíc rozdělí přesná statická metoda",
        source="Výroba A", dest="Odběr {i} ({k} %)",
        approx="Přibližná statická metoda (dnes)", exact="Přesná statická metoda",
        day="{d}. {m}. {y}", grid_unmet="SÍŤ (nepokryto)", grid_unshared="SÍŤ (nesdíleno)",
        from_grid="ze sítě (nepokryto)", to_grid="do sítě (nesdíleno)", sep=" "),
    "en": dict(
        months=["January", "February", "March", "April", "May", "June", "July", "August",
                "September", "October", "November", "December"],
        pie_labels=["shared", "could have been shared", "surplus to the grid"],
        pie_title="Where the production went ({a} – {b})",
        pie_note="Total production {total} kWh · “could have been shared” = what the exact static method adds",
        source="Plant A", dest="Consumption {i} ({k} %)",
        approx="Approximate static method (today)", exact="Exact static method",
        day="{d} {mon} {y}", grid_unmet="GRID (unmet)", grid_unshared="GRID (unshared)",
        from_grid="from grid (unmet)", to_grid="to grid (unshared)", sep=","),
    "de": dict(
        months=["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
                "September", "Oktober", "November", "Dezember"],
        pie_labels=["geteilt", "hätte geteilt werden können", "Überschuss ins Netz"],
        pie_title="Wohin die Erzeugung ging ({a} – {b})",
        pie_note="Gesamt Erzeugung {total} kWh · „hätte geteilt werden können“ = was die exakte statische Methode hinzufügt",
        source="Anlage A", dest="Verbrauch {i} ({k} %)",
        approx="Näherungsweise statische Methode (heute)", exact="Exakte statische Methode",
        day="{d}. {m}. {y}", grid_unmet="NETZ (ungedeckt)", grid_unshared="NETZ (nicht geteilt)",
        from_grid="aus dem Netz (ungedeckt)", to_grid="ins Netz (nicht geteilt)", sep="."),
}


def _save(fig, path: Path, w: int, h: int) -> None:
    fig.update_layout(font=dict(family="DejaVu Sans, Arial"))
    fig.write_image(path, width=w, height=h, scale=2)
    print(path)


def make(lang: str, d, exact, keys: list[float], out: Path) -> None:
    t = T[lang]
    out.mkdir(parents=True, exist_ok=True)
    members = set(d.dest_eans)
    names = {d.source_eans[0]: t["source"]}
    names |= {e: t["dest"].format(i=i, k=round(k * 100))
              for i, (e, k) in enumerate(zip(d.dest_eans, keys), 1)}
    th = F.theme("light")

    # kam šla výroba; „mohlo být sdíleno“ = co přidá přesná metoda
    sa, sb = filter_dests(d, members), filter_dests(exact, members)
    total = float(d.production.sum()) if hasattr(d.production, "sum") else float(d.production)
    fig = F.fig_wasted_pie(compute_wasted_split(sa), lang, th, exact_based=True)
    fig.data[0].labels = t["pie_labels"]
    start, end = sa.index.min(), sa.index.max()
    total_txt = fmt_num(total, lang)
    fig.update_layout(
        title_text=t["pie_title"].format(a=f"{t['months'][start.month - 1]} {start.year}",
                                         b=f"{t['months'][end.month - 1]} {end.year}"),
        annotations=[dict(
            text=t["pie_note"].format(total=total_txt),
            x=0.5, y=0, yshift=-58, xref="paper", yref="paper", yanchor="top",
            showarrow=False, font=dict(size=12, color=th["muted"]))])
    _save(fig, out / "kolac.png", 760, 560)

    # den, kdy přesná metoda přidá nejvíc: přibližná vs přesná na společné ose
    gain = (sb[shared_cols(sb)].sum(axis=1) - sa[shared_cols(sa)].sum(axis=1))
    day = gain.groupby(sa.index.normalize()).sum().idxmax()
    iso = str(day.date())
    y_max = max(F.intraday_ymax(sa, iso), F.intraday_ymax(sb, iso))
    day_txt = t["day"].format(d=day.day, m=day.month, y=day.year, mon=t["months"][day.month - 1][:3])
    for tag, df, data, title in (("priblizna", sa, d, t["approx"]), ("presna", sb, exact, t["exact"])):
        fig = F.fig_intraday(df, data, names, iso, y_max=y_max, lang=lang, th=th)
        fig.update_layout(title_text=f"{title} – {day_txt}")
        for tr in fig.data:
            tr.name = (tr.name.replace(t["grid_unmet"], t["from_grid"])
                              .replace(t["grid_unshared"], t["to_grid"]))
        _save(fig, out / f"den_{tag}.png", 900, 440)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", help="úplný report sdílení z portálu EDC")
    ap.add_argument("--keys", default=",".join(map(str, KEYS)),
                    help="klíče odběrných míst jako podíly, oddělené čárkou")
    ap.add_argument("--lang", default="all", choices=("all", *LANGS))
    ap.add_argument("--out", help="výstupní složka (výchozí clanek/img, img/en, img/de)")
    a = ap.parse_args()

    d = load_report(Path(a.csv).read_bytes())
    keys = [float(k) for k in a.keys.split(",")]
    exact = recompute(d, keys).data
    for lang in LANGS if a.lang == "all" else (a.lang,):
        make(lang, d, exact, keys, Path(a.out) if a.out else img_dir(lang))


if __name__ == "__main__":
    main()
