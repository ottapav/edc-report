# Články

Vysvětlující články pro širokou veřejnost (psané pro TZB-info, UCEEB ČVUT). Každý článek má
vlastní složku; aplikace ho skládá při každém otevření a obslouží ho na své adrese.

| Složka | Článek | Adresa v aplikaci | Jazyky |
| --- | --- | --- | --- |
| [`do_posledni_kwh/`](do_posledni_kwh/README.md) | Sdílení elektřiny do poslední kilowatthodiny | [`/clanky/do-posledni-kwh/`](https://edc-report.uceeb.cvut.cz/clanky/do-posledni-kwh/) | cs, en, de |
| [`spravedliva_cena/`](spravedliva_cena/README.md) | Spravedlivá cena sdílené kilowatthodiny | [`/clanky/spravedliva-cena/`](https://edc-report.uceeb.cvut.cz/clanky/spravedliva-cena/) | cs (rozpracováno) |

Starší adresy `/clanek/`, `/clanek/en/` a `/clanek/de/` přesměrují na první článek.

Oba články vycházejí z reportu stejné skutečné skupiny v [`data/`](data/README.md)
(kódy odběrných míst jsou smyšlené).

## Co je ve složce článku

| Soubor | Obsah |
| --- | --- |
| `clanek.html` | Text česky (zdroj); překlady `clanek.en.html`, `clanek.de.html` se strukturou shodnou s originálem |
| `img/` | Obrázky česky; `img/en/`, `img/de/` pro překlady |
| `schemata.py` | Volitelně: funkce `jméno(lang)`, které nahradí značky `{{JMÉNO}}` v textu vlastním SVG |
| `README.md` | Jak článek upravit a jak vznikly jeho obrázky |

Společné pro všechny články je jen to, co je přímo zde: vzhled `styl.css` (značka `{{STYL}}`),
přepínač jazyků (`{{JAZYKY}}`, jen u článků s překladem) a česká, anglická a německá typografie
(nedělitelné mezery u jednotek, čísel a jednopísmenných slov).

## Nový článek

1. Složka s názvem z písmen a podtržítek, v ní prázdný `__init__.py` a `clanek.html`
   (nejsnáz jako kopie existujícího článku).
2. Jeden řádek v `ARTICLES` v [`__init__.py`](__init__.py): složka, adresa a český název.
3. `python -m pytest tests/test_clanky.py` zkontroluje, že se článek složí, že obrázky
   existují a že jsou všechny obrázky a tabulky v textu citované.

Lokální náhled: `python app.py` a otevřít <http://127.0.0.1:8050/clanky/ADRESA/>.

## Samostatná verze (např. pro redakci)

```bash
python -m clanky do_posledni_kwh export/ --lang en   # export/index.html + export/img/ (cs je výchozí)
```
