# Data skutečné skupiny pro články

`skupina.csv` je úplný report sdílení z portálu EDC jedné skutečné skupiny sdílení:
fotovoltaika 11,44 kWp s baterií 11,6 kWh a pět odběrných míst s klíči 50 % a čtyřikrát
10 %. Pokrývá 365 dní od 11. 9. 2025 do 10. 9. 2026 po čtvrthodinách (export z 11. 9. 2026).
Z těchto dat vycházejí oba články:

| Článek | Co z dat cituje | Jak obrázky vzniknou |
| --- | --- | --- |
| [`do_posledni_kwh/`](../do_posledni_kwh/README.md) | výroba 4 275 kWh, spotřeba 36 854 kWh, nasdíleno 2 235 kWh, přesná metoda +367 kWh; obr. 4 a 5 | `python -m clanky.do_posledni_kwh.obrazky clanky/data/skupina.csv` |
| [`spravedliva_cena/`](../spravedliva_cena/README.md) | 12 707 a 3 727 čtvrthodin, vyúčtování podle přínosu za 4 a 1 Kč/kWh; obr. 2 a 3 | `python -m clanky.spravedliva_cena.obrazky` |

**Kódy odběrných míst jsou nahrazené smyšlenými** (výrobna `859182400000000000`, odběrná
místa `…001` až `…005` ve stejném pořadí jako ve skutečném reportu). Ostatní hodnoty jsou
beze změny, takže všechna čísla a obrázky vyjdou stejně jako ze skutečného reportu. Skutečné
kódy do repozitáře nepatří, ostatní reporty (`*.csv`) `.gitignore` dál vylučuje.

Čísla citovaná v článcích hlídá test `test_the_group_data_give_the_numbers_both_articles_quote`
v `tests/test_clanky.py`: když se data nebo výpočet změní, test ukáže, které číslo v textu
upravit.
