# Článek: Sdílení elektřiny do poslední kilowatthodiny

Vysvětlující článek pro širokou veřejnost (psaný pro TZB-info, UCEEB ČVUT): přibližná a
přesná statická metoda, režim bazén pro více výroben a výsledky jedné reálné skupiny.
Aplikace ho nabízí na adrese **`/clanek/`** a odkazuje na něj z karty
*Přesná statická metoda (návrh)*.

## Jak článek upravit

| Co | Kde |
| --- | --- |
| Text, tabulky, popisky obrázků, zdroje | `clanek.html` |
| Schémata (nádoby, hladina po kolech, síť, bazén) | `schemata.py` – značka `{{NADOBY}}` v textu volá `nadoby()` atd. |
| Obrázky z reálných dat a srovnání výpočtů | `img/*.png` |

Aplikace skládá článek při **každém otevření** ze souborů v této složce. Na nasazené
verzi se úprava objeví po commitu do `main` (Render ji nasadí automaticky), lokálně stačí
obnovit stránku. Úpravu `clanek.html` lze udělat i přímo ve webovém editoru GitHubu.

Lokální náhled: `python app.py` a otevřít <http://127.0.0.1:8050/clanek/>.

## Obrázky z dat

`kolac.png`, `den_priblizna.png` a `den_presna.png` kreslí stejné funkce jako aplikace:

```bash
pip install kaleido                         # jen pro export obrázků, aplikace ho nepotřebuje
python -m clanek.obrazky REPORT.csv --keys 0.1,0.5,0.1,0.1,0.1
```

Report (CSV z portálu EDC) do repozitáře nepatří, obsahuje kódy odběrných míst.
`srovnani-vypoctu.png` je výsledek benchmarku z prezentace a mění se jen ručně.

## Samostatná verze (např. pro redakci)

```bash
python -m clanek export/            # export/index.html + export/img/
```
