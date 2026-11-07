# Článek: Spravedlivá cena sdílené kilowatthodiny

Vysvětlující článek pro širokou veřejnost (psaný pro TZB-info, UCEEB ČVUT), který volně navazuje
na [Sdílení elektřiny do poslední kilowatthodiny](../do_posledni_kwh/README.md). Vysvětluje
vyúčtování podle přínosu (Shapleyho hodnota) ze záložky *Vyúčtování* aplikace: co se dělí, jak
se počítá, proč je to spravedlivé, proč na klíčích nezávisí a co znamená záporná platba.
Zatím jen česky, na adrese **`/clanky/spravedliva-cena/`**; aplikace na něj odkazuje z karty
*Vyúčtování sdílené elektřiny podle přínosu* nad tlačítkem výpočtu (v angličtině a němčině
s poznámkou, že je česky).

**Stav: rozpracováno.** Žlutě zvýrazněná místa (`<mark class="todo">`) je třeba před vydáním
doplnit a značku odstranit:

* ceny, se kterými se počítá vyúčtování skutečné skupiny z minulého článku, a výsledky ze
  záložky *Vyúčtování* (úspora, podíl výrobce, ceny členů, srovnání s pevnou cenou);
* dva obrázky do `img/` (kam šla úspora; podíl výrobce nebo cena po měsících), v textu jako
  `<figure>` stejně jako v minulém článku (budou to obr. 2 a 3);
* odkaz na minulý článek po jeho vydání (zdroj [1]).

Otevřené otázky z editorské revize: kontaktní e-mail v rámečku o UCEEB (`@cvut.cz`, nebo
`@uceeb.cz`?) a období skutečné skupiny („od září 2025 do září 2026“: 12, nebo 13 měsíců?
sjednotit s prvním článkem).

Čísla příkladů (Dana, Emil, Filip; tabulky 1 a 2; záporná platba) spočítá funkce aplikace
`billing.compute_shapley` a `billing.settle`; příklad se zápornou platbou hlídá test
`test_a_member_kept_short_by_the_keys_is_paid_the_difference` v `tests/test_billing.py`.

## Jak článek upravit

| Co | Kde |
| --- | --- |
| Text, tabulky, zdroje | `clanek.html` |
| Vzhled (společný pro všechny články) | [`../styl.css`](../styl.css) |
| Schéma cenového žebříčku (obr. 1) | `schemata.py`, funkce `zebricek` → značka `{{ZEBRICEK}}` |
| Obrázky z aplikace | `img/` (zatím žádné) |

Lokální náhled: `python app.py` a otevřít <http://127.0.0.1:8050/clanky/spravedliva-cena/>.
Samostatná verze pro redakci: `python -m clanky spravedliva_cena export/`.
