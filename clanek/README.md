# Článek: Sdílení elektřiny do poslední kilowatthodiny

Vysvětlující článek pro širokou veřejnost (psaný pro TZB-info, UCEEB ČVUT): přibližná a
přesná statická metoda, režim bazén pro více výroben a výsledky jedné reálné skupiny.
Existuje česky (**`/clanek/`**), anglicky (**`/clanek/en/`**) a německy (**`/clanek/de/`**).
Aplikace odkazuje z karty *Přesná statická metoda* na verzi podle zvoleného jazyka rozhraní.

## Jak článek upravit

| Co | Kde |
| --- | --- |
| Text, tabulky, popisky obrázků, zdroje | `clanek.html` (česky), `clanek.en.html`, `clanek.de.html` – struktura musí zůstat shodná |
| Vzhled (společný pro všechny jazyky) | `styl.css` |
| Schémata (nádoby, hladina po kolech, síť, bazén) | `schemata.py` – značka `{{NADOBY}}` v textu volá `nadoby(lang)` atd.; texty schémat jsou ve slovníku `T` pro cs/en/de |
| Obrázky z reálných dat a srovnání výpočtů | `img/*.png` (česky), `img/en/`, `img/de/` |

Aplikace skládá článek při **každém otevření** ze souborů v této složce. Na nasazené
verzi se úprava objeví po commitu do `main` (Render ji nasadí automaticky), lokálně stačí
obnovit stránku. Úpravu zdrojů lze udělat i přímo ve webovém editoru GitHubu.

Lokální náhled: `python app.py` a otevřít <http://127.0.0.1:8050/clanek/>.

## Obrázky z dat

`kolac.png`, `den_priblizna.png` a `den_presna.png` kreslí stejné funkce jako aplikace:

```bash
pip install kaleido                         # jen pro export obrázků, aplikace ho nepotřebuje
python -m clanek.obrazky REPORT.csv --keys 0.1,0.5,0.1,0.1,0.1   # všechny jazyky; --lang cs|en|de
```

Report (CSV z portálu EDC) do repozitáře nepatří, obsahuje kódy odběrných míst.
`srovnani-vypoctu.png` kreslí `python -m clanek.srovnani [--lang cs|en|de|all]` z naměřených dat v `srovnani.json`.

## Samostatná verze (např. pro redakci)

```bash
python -m clanek export/ --lang en  # export/index.html + export/img/ (cs je výchozí)
```
