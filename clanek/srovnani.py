"""Obrázek „Srovnání výpočtů“ (doba výpočtu a podíl rozdělené elektřiny podle velikosti
skupiny): ``python -m clanek.srovnani [--lang cs|en|de|all]``.

Kreslí ho z ``srovnani.json`` (výsledek ``bench_scaling.py``: medián doby výpočtu jedné
čtvrthodiny a podíl nasdílené elektřiny pro 5–1000 odběrných míst). Potřebuje matplotlib.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import LANGS, img_dir

DATA = Path(__file__).with_name("srovnani.json")
METHODS = ("Statická, 1 kolo", "Statická, 5 kol", "Přesná statická")   # klíče v srovnani.json
COLOUR = dict(zip(METHODS, ("#9CA3AF", "#D97706", "#0065BD")))
MARKER = dict(zip(METHODS, ("s", "^", "o")))
T = {
    "cs": dict(
        methods=METHODS, size="Počet odběrných míst ve skupině",
        time="Doba výpočtu jedné čtvrthodiny [ms]", t_title="Výpočetní náročnost",
        month="Za měsíc (2 976 čtvrthodin) [s]", ann="1 000 míst: {ms} ms\n({s} s za měsíc)",
        limit="limit iterací:\nnad 100 EAN\njen 1 kolo", edc="EDC dnes (dle pravidel)",
        shared="Nasdíleno z toho, co lze spotřebovat [%]", s_title="Kolik se rozdělí",
        one_round="nad 100 EAN jen 1 kolo", dec=",",
        note=("Čistý Python, jedno jádro, bez stavu mezi intervaly. Denní čtvrthodiny, kdy výroba "
              "nestačí všem (30–90 % součtu odběrů); náhodné klíče a odběry, 300 intervalů na "
              "velikost, medián z 5 měření.\nSkupina = uvedený počet odběrných míst + 1 výrobna; "
              "iterační výpočet EDC je dnes možný jen do 100 EAN.")),
    "en": dict(
        methods=("Static, 1 round", "Static, 5 rounds", "Exact static"),
        size="Number of metering points in the group",
        time="Computation time of one 15-minute interval [ms]", t_title="Computational cost",
        month="Per month (2,976 intervals) [s]", ann="1,000 points: {ms} ms\n({s} s per month)",
        limit="iteration limit:\nabove 100 EANs\n1 round only", edc="EDC today (per the rules)",
        shared="Share of what can be consumed that is shared [%]", s_title="How much is shared",
        one_round="above 100 EANs 1 round only", dec=".",
        note=("Pure Python, one core, no state between intervals. Daytime intervals in which the "
              "production does not cover everyone (30–90 % of the total consumption); random keys "
              "and consumption, 300 intervals per size, median of 5 runs.\nGroup = the stated number "
              "of metering points + 1 plant; the iterative EDC calculation is currently possible "
              "only up to 100 EANs.")),
    "de": dict(
        methods=("Statisch, 1 Runde", "Statisch, 5 Runden", "Exakt statisch"),
        size="Anzahl der Verbrauchsstellen in der Gruppe",
        time="Rechenzeit einer Viertelstunde [ms]", t_title="Rechenaufwand",
        month="Pro Monat (2.976 Viertelstunden) [s]", ann="1.000 Stellen: {ms} ms\n({s} s pro Monat)",
        limit="Iterationslimit:\nüber 100 EAN\nnur 1 Runde", edc="EDC heute (nach den Regeln)",
        shared="Geteilt von dem, was verbraucht werden kann [%]", s_title="Wie viel geteilt wird",
        one_round="über 100 EAN nur 1 Runde", dec=",",
        note=("Reines Python, ein Kern, kein Zustand zwischen den Intervallen. Tagesviertelstunden, in "
              "denen die Erzeugung nicht für alle reicht (30–90 % des Gesamtverbrauchs); zufällige "
              "Schlüssel und Verbräuche, 300 Intervalle je Größe, Median aus 5 Messungen.\nGruppe = "
              "angegebene Zahl von Verbrauchsstellen + 1 Anlage; die iterative EDC-Berechnung ist "
              "heute nur bis 100 EAN möglich.")),
}


def draw(lang: str, out: Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib import font_manager as fm
    names = {f.name for f in fm.fontManager.ttflist}
    plt.rcParams["font.family"] = "Technika" if "Technika" in names else "DejaVu Sans"

    t, r = T[lang], json.loads(DATA.read_text(encoding="utf-8"))
    n = r["sizes"]
    label = dict(zip(METHODS, t["methods"]))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.2), gridspec_kw={"width_ratios": [1.25, 1]})
    for m, ms in r["time_ms"].items():
        a1.plot(n, ms, marker=MARKER[m], color=COLOUR[m], lw=2.4 if m == METHODS[2] else 1.8,
                ms=6, label=label[m])
    a1.set_xscale("log")
    a1.set_yscale("log")
    a1.set_xlabel(t["size"])
    a1.set_ylabel(t["time"])
    a1.set_title(t["t_title"], fontsize=14, fontweight="bold", loc="left")
    a1.grid(True, which="both", color="#E5E7EB", lw=0.6)
    ticks = [5, 10, 20, 50, 100, 200, 500, 1000]
    a1.set_xticks(ticks)
    a1.set_xticklabels([str(v) for v in ticks])
    sec = a1.secondary_yaxis("right", functions=(lambda ms: ms * 2976 / 1000,
                                                 lambda s: s * 1000 / 2976))
    sec.set_ylabel(t["month"])
    te = r["time_ms"][METHODS[2]][-1]
    ms_txt = f"{te:.2f}".replace(".", t["dec"])
    s_txt = f"{te * 2976 / 1000:.1f}".replace(".", t["dec"])
    a1.annotate(t["ann"].format(ms=ms_txt, s=s_txt), xy=(1000, te), xytext=(170, 0.5),
                fontsize=11, color="#0065BD", arrowprops=dict(arrowstyle="->", color="#0065BD", lw=1))
    a1.axvline(99, color="#6B7280", ls="--", lw=1)
    a1.text(104, 0.0022, t["limit"], fontsize=9, color="#6B7280")
    a1.legend(frameon=False, loc="upper left")

    x = np.arange(len(n))
    # EDC podle pravidel: 5 kol jen do 100 EAN ve skupině (členové + 1 výrobna), jinak 1 kolo
    edc = [r["shared_pct"][METHODS[1]][i] if v + 1 <= 100 else r["shared_pct"][METHODS[0]][i]
           for i, v in enumerate(n)]
    w = 0.38
    a2.bar(x - w / 2, edc, w, color=COLOUR[METHODS[1]], label=t["edc"])
    a2.bar(x + w / 2, r["shared_pct"][METHODS[2]], w, color=COLOUR[METHODS[2]], label=label[METHODS[2]])
    a2.axvline(3.5, color="#6B7280", ls="--", lw=1)
    a2.text(3.6, 104, t["one_round"], fontsize=10, color="#6B7280")
    a2.set_xticks(x)
    a2.set_xticklabels([str(v) for v in n], rotation=0, fontsize=9)
    a2.set_ylim(50, 112)
    a2.set_yticks([50, 60, 70, 80, 90, 100])
    a2.set_xlabel(t["size"])
    a2.set_ylabel(t["shared"])
    a2.set_title(t["s_title"], fontsize=14, fontweight="bold", loc="left")
    a2.grid(True, axis="y", color="#E5E7EB", lw=0.6)
    a2.legend(frameon=False, loc="upper left", ncol=2, fontsize=10, bbox_to_anchor=(0.0, 1.02))
    fig.text(0.008, -0.02, t["note"], fontsize=9.5, color="#6B7280", va="top", linespacing=1.5)
    for a in (a1, a2):
        a.spines["top"].set_visible(False)
    a2.spines["right"].set_visible(False)
    fig.tight_layout()
    out.mkdir(parents=True, exist_ok=True)
    path = out / "srovnani-vypoctu.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(path)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lang", default="all", choices=("all", *LANGS))
    a = ap.parse_args()
    for lang in LANGS if a.lang == "all" else (a.lang,):
        draw(lang, img_dir(lang))


if __name__ == "__main__":
    main()
