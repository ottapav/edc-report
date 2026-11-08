# Článek: Spravedlivá cena sdílené kilowatthodiny

Vysvětlující článek pro širokou veřejnost (psaný pro TZB-info, UCEEB ČVUT), který volně navazuje
na [Sdílení elektřiny do poslední kilowatthodiny](../do_posledni_kwh/README.md). Vysvětluje
vyúčtování podle přínosu (Shapleyho hodnota) ze záložky *Vyúčtování* aplikace: co se dělí, jak
se počítá, proč je to spravedlivé, proč na klíčích nezávisí a co znamená záporná platba.
Zatím jen česky, na adrese **`/clanky/spravedliva-cena/`**; aplikace na něj odkazuje z karty
*Vyúčtování sdílené elektřiny podle přínosu* nad tlačítkem výpočtu (v angličtině a němčině
s poznámkou, že je česky).

**Stav: připraveno k odeslání.** Zbývá jediné žlutě zvýrazněné místo
(`<mark class="todo">`): odkaz na minulý článek po jeho vydání (zdroj [1]).

Skutečná skupina je stejná jako v minulém článku, ze stejného reportu
([`../data/skupina.csv`](../data/README.md), 365 dní od 11. 9. 2025 do 10. 9. 2026).
Vyúčtování se počítá se stejnými cenami jako příklady: 4 Kč/kWh od prodejce pro všechny
členy, výkupní cena 1 Kč/kWh, pro srovnání pevná cena 2,50 Kč/kWh.

Čísla příkladů (Dana, Emil, Filip; tabulky 1 a 2; záporná platba) spočítá funkce aplikace
`billing.compute_shapley` a `billing.settle`; příklad se zápornou platbou hlídá test
`test_a_member_kept_short_by_the_keys_is_paid_the_difference` v `tests/test_billing.py`.

## Jak článek upravit

| Co | Kde |
| --- | --- |
| Text, tabulky, zdroje | `clanek.html` |
| Vzhled (společný pro všechny články) | [`../styl.css`](../styl.css) |
| Schéma cenového žebříčku (obr. 1) | `schemata.py`, funkce `zebricek` → značka `{{ZEBRICEK}}` |
| Obrázky skutečné skupiny (obr. 2 a 3) | `img/kolac_uspora.png`, `img/vyrobce_mesice.png`: `python -m clanky.spravedliva_cena.obrazky` (potřebuje kaleido), vypíše i čísla, která text cituje |

Lokální náhled: `python app.py` a otevřít <http://127.0.0.1:8050/clanky/spravedliva-cena/>.
Samostatná verze pro redakci: `python -m clanky spravedliva_cena export/`.
