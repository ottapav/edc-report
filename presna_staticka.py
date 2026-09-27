"""
Přesná statická metoda sdílení elektřiny – referenční implementace v čistém Pythonu.

Metoda
------
Každý člen skupiny dostane

    s_i = min(D_i, k_i · H)

kde D_i je jeho odběr, k_i jeho alokační klíč a H společná hladina. Hladina se volí
tak, aby se rozdělilo vše, co lze spotřebovat, tj. Σ s_i = min(P, Σ D_i):

    H = max přes členy j [ (P − Σ odběrů členů před j) / (Σ klíčů členů od j dál) ]

přičemž členové jsou seřazeni podle D_i / k_i vzestupně (kdo se naplní dřív, je dřív).
Výsledek je totožný s dnešní statickou metodou EDC po nekonečně mnoha kolech.

Jednotky
--------
Všechny energie jsou celá čísla v setinách kWh (1 = 0,01 kWh = 10 Wh), tedy v rozlišení
dat EDC. Celočíselné vstupy i výstupy zaručují, že součet sdílení sedí přesně na setinu.

Výkon
-----
Každá čtvrthodina se počítá samostatně, bez jakékoli informace z předchozích intervalů,
takže výpočet může běžet bezstavově na serveru. Bez externích balíčků a bez paralelizace.
Rychlost stojí na těchto krocích:
  * rychlé výjimky: v noci (P = 0) a když výroba stačí všem (Σ D ≤ P), se nic neřadí,
  * vestavěné řazení sorted() (Timsort v C) s klíčem list.__getitem__, bez lambdy,
  * výpočet hladiny končí u prvního člena, který se nenaplní,
  * naplnění členové se jen zkopírují; počítají a zaokrouhlují se jen ostatní.
Teoreticky lepší O(n) algoritmus (výběr mediánu) je v čistém Pythonu pomalejší, protože
běží v interpretu, kdežto řazení běží v C.
"""
from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Jádro: jedna čtvrthodina, jedna výrobna (nebo bazén)
# ---------------------------------------------------------------------------
def rozdel(P: int, D: list[int], k: list[float], rezerva: float = 0.0) -> list[int]:
    """
    Rozdělí výrobu P mezi členy s odběry D podle klíčů k.

    Parametry
      P  výroba ve čtvrthodině, setiny kWh (celé číslo ≥ 0)
      D  odběry členů ve stejné čtvrthodině, setiny kWh (celá čísla ≥ 0)
      k  alokační klíče jako podíly (např. 0.25 = 25 %), součet ≤ 1;
         členové s klíčem 0 nedostanou nic
      rezerva  volitelný podíl výroby určený k prodeji (např. 0.1 = 10 %), výchozí 0

    Klíče jako poměry: výsledek závisí jen na vzájemném poměru klíčů, ne na jejich
    součtu. Je-li součet klíčů pod 100 %, nerozdělený podíl se přerozdělí stejně jako
    v dnešní metodě po nekonečně mnoha kolech – nic nepropadne. Kdo chce část výroby
    záměrně prodávat, nastaví ji výslovně parametrem rezerva (pevná rezerva): ta se
    odečte z výroby předem a zbytek se rozdělí přesnou statickou metodou.

    Vrací seznam nasdílených množství v setinách kWh. Platí:
      * nikdo nedostane víc, než odebral: s_i ≤ D_i,
      * rozdělí se vše, co lze spotřebovat: Σ s_i = min(P − rezerva, Σ D_i přes členy s klíčem > 0),
      * nenaplnění členové dostanou v poměru svých klíčů (až na zaokrouhlení na setiny).

    Složitost (n členů, u z nich se nenaplní):
      krok 1  rychlé výjimky ...................... O(n)
      krok 2  seřazení podle D_i / k_i ............ O(n log n)   ← nejdražší krok
      krok 3  hladina H ........................... O(n)         (končí dřív u prvního nenaplněného)
      krok 4  sdílení ............................. O(n)         (kopie odběrů + nenaplnění členové)
      krok 5  rozdělení useknutých setin .......... O(u log u)
      celkem ...................................... O(n log n) čas, O(n) paměť

    Přesnost: součet vždy sedí přesně na min(P, Σ D). Poměr klíčů je přesný na setinu pro
    běžná data (odběry do 10^9 setin kWh a klíče nad 10^-6); mimo tento rozsah může
    plovoucí čárka odchýlit rozdělení mezi nenaplněnými členy o několik setin.

    Vyvolá ValueError při nesouhlasu délek, záporných odběrech či klíčích a rezervě mimo 0–1.
    """
    n = len(D)
    if len(k) != n:
        raise ValueError('D a k musí mít stejnou délku')
    if n and (min(D) < 0 or min(k) < 0):
        raise ValueError('odběry i klíče musí být nezáporné')
    if not 0.0 <= rezerva <= 1.0:
        raise ValueError('rezerva musí být v rozsahu 0–1')

    # --- Krok 0: pevná rezerva k prodeji (volitelná) ------------------------------------
    if rezerva > 0:
        P -= round(P * rezerva)                           # zaokrouhleno na celé setiny

    # --- Krok 1: rychlé výjimky (bez řazení) --------------------------------------------
    if P <= 0:                                            # noc: není co rozdělit
        return [0] * n
    if sum(d for d, x in zip(D, k) if x > 0) <= P:        # výroba stačí všem členům s klíčem
        return [d if x > 0 else 0 for d, x in zip(D, k)]

    # --- Krok 2: seřazení podle toho, kdo se naplní dřív -------------------------------
    # t_i = D_i / k_i je hladina, při které se člen i právě naplní. Člen bez klíče
    # se nenaplní nikdy (t = ∞), skončí na konci pořadí a dostane k_i · H = 0.
    t = [d / x if x > 0 else math.inf for d, x in zip(D, k)]
    poradi = sorted(range(n), key=t.__getitem__)

    # --- Krok 3: hladina H --------------------------------------------------------------
    # Kandidát pro člena j = (výroba − odběry naplněných členů) / (klíče ostatních).
    # Kandidáti rostou, dokud se další člen v pořadí naplní; jakmile se nenaplní,
    # je aktuální kandidát hledanou hladinou (vrchol). Smyčka vždy skončí dřív, než
    # dojde na členy bez klíče, protože výroba nestačí všem (viz krok 1).
    H = 0.0
    zbyva_vyroba = P                                     # výroba po odečtení naplněných členů
    zbyva_klicu = sum(k)                                 # součet klíčů nenaplněných členů
    naplnenych = 0                                       # počet plných členů na začátku pořadí
    for i in poradi:
        kandidat = zbyva_vyroba / zbyva_klicu
        if kandidat > H:
            H = kandidat
        if t[i] >= H:                                    # člen i se při hladině H nenaplní → konec
            break
        zbyva_vyroba -= D[i]                             # člen i je plný: dostane celý odběr
        zbyva_klicu -= k[i]
        naplnenych += 1

    # --- Krok 4: sdílení ----------------------------------------------------------------
    # Naplnění členové dostanou celý odběr (proto výchozí kopie D), ostatní klíč × H
    # zaokrouhlené dolů na setiny.
    s = D[:]
    nenaplneni = poradi[naplnenych:]
    presne = [k[i] * H for i in nenaplneni]              # přesné podíly (desetinná čísla)
    cele = [int(x) for x in presne]                      # zaokrouhleno dolů na setiny
    for i, x in zip(nenaplneni, cele):
        s[i] = x

    # --- Krok 5: rozdělení useknutých setin ---------------------------------------------
    # Zaokrouhlením dolů se ztratí méně setin, než je nenaplněných členů. Dostanou je
    # členové s největším useknutým zbytkem (metoda největších zbytků), takže součet
    # sedí přesně na min(P, Σ D). Nikdo tím nepřekročí svůj odběr, protože k_i · H < D_i,
    # a člen bez klíče nic nedostane, protože jeho zbytek je 0.
    chybi = P - sum(s)
    if chybi > 0:
        zbytky = [x - c for x, c in zip(presne, cele)]
        nejvetsi = sorted(range(len(nenaplneni)), key=zbytky.__getitem__, reverse=True)
        for j in nejvetsi[:chybi]:
            s[nenaplneni[j]] += 1
        # Pojistka mimo běžný rozsah dat (obří odběry, mikroskopické klíče): pokud plovoucí
        # čárka ubrala víc setin, než je nenaplněných členů, doplní se do volné kapacity,
        # aby platilo Σ s = min(P, Σ D). V běžném rozsahu se tato smyčka nikdy neprovede.
        chybi = P - sum(s)
        for i in nenaplneni:
            if chybi <= 0:
                break
            q = min(chybi, D[i] - s[i]) if k[i] > 0 else 0
            s[i] += q
            chybi -= q
    elif chybi < 0:
        # Pojistka mimo běžný rozsah dat: plovoucí čárka přidělila víc, než je výroba.
        # Přebytek se ubere nejdřív nenaplněným členům (od nejmenšího zbytku), případně
        # i naplněným od konce pořadí, aby součet nikdy nepřekročil P.
        zbytky = [x - c for x, c in zip(presne, cele)]
        poradi_ubirani = [nenaplneni[j] for j in sorted(range(len(nenaplneni)), key=zbytky.__getitem__)]
        poradi_ubirani += poradi[:naplnenych][::-1]
        for i in poradi_ubirani:
            if chybi >= 0:
                break
            q = min(-chybi, s[i])
            s[i] -= q
            chybi += q
    return s


# ---------------------------------------------------------------------------
# Období: posloupnost nezávislých čtvrthodin
# ---------------------------------------------------------------------------
def rozdel_obdobi(vyroba: list[int], odbery: list[list[int]], klice: list[float],
                  rezerva: float = 0.0) -> list[list[int]]:
    """
    Rozdělí výrobu v každé čtvrthodině období (typicky měsíc = 2 976 intervalů).

      vyroba  výroba po čtvrthodinách, setiny kWh
      odbery  pro každou čtvrthodinu seznam odběrů členů, setiny kWh
      klice   alokační klíče členů pro celé období
      rezerva volitelný podíl výroby určený k prodeji (viz rozdel)

    Intervaly se počítají nezávisle, takže je lze zpracovat v libovolném pořadí.
    Složitost: O(T · n log n) pro T čtvrthodin a n členů.
    """
    return [rozdel(P, D, klice, rezerva) for P, D in zip(vyroba, odbery)]


# ---------------------------------------------------------------------------
# Režim bazén: více výroben jako jedna
# ---------------------------------------------------------------------------
def bazen(vyroby: list[int], D: list[int], klice: list[float],
          rezerva: float = 0.0) -> tuple[list[int], list[list[int]]]:
    """
    Režim bazén pro skupinu s více výrobnami v jedné čtvrthodině.

      vyroby  výroba jednotlivých výroben, setiny kWh
      D       odběry členů, setiny kWh
      klice   jeden klíč na člena pro celou skupinu
      rezerva volitelný podíl výroby určený k prodeji (viz rozdel), stejný pro všechny výrobny

    Postup:
      1. výroby se sečtou a rozdělí přesnou statickou metodou jako z jedné výrobny,
      2. sdílení každého člena se rozpadne na výrobny v poměru jejich výroby,
         takže každá výrobna sdílí stejné procento své výroby.

    Vrací (sdílení podle členů, matice[výrobna][člen]), vše v setinách kWh.
    Složitost: O(n log n) pro rozdělení + O(n · m log m) pro rozpad na m výroben.
    """
    celkem = sum(vyroby)
    s = rozdel(celkem, D, klice, rezerva)
    matice = [[0] * len(D) for _ in vyroby]
    if celkem == 0:
        return s, matice

    for i, si in enumerate(s):
        # přesný podíl každé výrobny na sdílení člena i, zaokrouhlený dolů
        presne = [si * p / celkem for p in vyroby]
        cele = [int(x) for x in presne]
        # useknuté setiny dostanou výrobny s největším zbytkem, aby součet seděl na si
        chybi = si - sum(cele)
        for d in sorted(range(len(vyroby)), key=lambda d: presne[d] - cele[d], reverse=True)[:chybi]:
            cele[d] += 1
        for d, x in enumerate(cele):
            matice[d][i] = x

    # Zaokrouhlení po členech může výrobně přidat setinu nad její výrobu (když se rozdělí
    # celá výroba). Taková setina se u stejného člena přesune na výrobnu s volnou kapacitou,
    # takže součty po členech zůstanou a žádná výrobna nedá víc, než vyrobila.
    sloupce = [sum(r) for r in matice]
    for d in range(len(vyroby)):
        while sloupce[d] > vyroby[d]:
            e = next(e for e in range(len(vyroby)) if sloupce[e] < vyroby[e])
            i = next(i for i in range(len(D)) if matice[d][i] > 0)
            matice[d][i] -= 1
            matice[e][i] += 1
            sloupce[d] -= 1
            sloupce[e] += 1
    return s, matice


# ---------------------------------------------------------------------------
# Pro srovnání: dnešní statická metoda EDC (5 kol, zaokrouhlení dolů v každém kole)
# ---------------------------------------------------------------------------
def staticka_edc(P: int, D: list[int], k: list[float], kola: int = 5) -> list[int]:
    """
    Dnešní iterační výpočet: v každém kole dostane člen min(zbývající odběr,
    klíč × výroba na začátku kola) zaokrouhleno dolů; výroba se sníží až na konci kola.
    Složitost: O(kola · n).
    """
    s = [0] * len(D)
    zbyva_odber = list(D)
    for _ in range(kola):
        na_zacatku, rozdeleno = P, 0
        for i, ki in enumerate(k):
            q = min(zbyva_odber[i], int(ki * na_zacatku + 1e-9))
            s[i] += q
            zbyva_odber[i] -= q
            rozdeleno += q
        P -= rozdeleno
        if rozdeleno == 0:
            break
    return s


# ---------------------------------------------------------------------------
# Příklady, kontrola a měření
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    import random
    import time

    def kwh(s):
        return [x / 100 for x in s]

    # Příklad z prezentace: výroba 12 kWh, klíče 50/30/20 %, odběry 4/5/6 kWh
    P, D, k = 1200, [400, 500, 600], [0.5, 0.3, 0.2]
    print('Přesná statická:', kwh(rozdel(P, D, k)))         # [4.0, 4.8, 3.2]
    print('Dnešní (5 kol): ', kwh(staticka_edc(P, D, k)))   # [4.0, 4.72, 3.15]

    # Bazén: výrobny A 10 kWh a B 6 kWh, klíče 50/50, odběry 2 a 20 kWh
    s, m = bazen([1000, 600], [200, 2000], [0.5, 0.5])
    print('Bazén:', kwh(s), '| z A:', kwh(m[0]), '| z B:', kwh(m[1]))

    # Součet klíčů pod 100 %: klíče se berou jako poměry, výsledek je stejný
    print('Klíče 45/27/18 %:', kwh(rozdel(P, D, [0.45, 0.27, 0.18])))              # [4.0, 4.8, 3.2]
    # Pevná rezerva 10 % k prodeji: 1,20 kWh se prodá, zbytek se rozdělí
    print('Rezerva 10 %:    ', kwh(rozdel(P, D, [0.5, 0.3, 0.2], rezerva=0.1)))      # [4.0, 4.08, 2.72]

    # Testy: python3 -m unittest test_presna_staticka.py

    # Měření: realistický měsíc (den/noc, profil FVE), každá čtvrthodina samostatně
    def mesic(n, T):
        rng = random.Random(0)
        w = [rng.random() for _ in range(n)]
        k = [x / sum(w) for x in w]
        zaklad = [rng.lognormvariate(-1.5, 0.6) for _ in range(n)]
        vyroba, odbery = [], []
        for t in range(T):
            hodina = (t % 96) / 4
            slunce = max(0.0, math.sin(math.pi * (hodina - 6) / 14)) if 6 < hodina < 20 else 0.0
            vyroba.append(int(35 * n * slunce * rng.uniform(0.3, 1.0)))
            odbery.append([int(100 * z * rng.uniform(0.2, 1.8)) for z in zaklad])
        return vyroba, odbery, k

    print('\nMěsíc (2 976 čtvrthodin), čistý Python, jedno jádro, bez stavu mezi intervaly:')
    for n in (100, 1_000, 10_000):
        T = 31 * 96 if n <= 1_000 else 7 * 96
        vyroba, odbery, k = mesic(n, T)
        t0 = time.perf_counter()
        rozdel_obdobi(vyroba, odbery, k)
        dt = (time.perf_counter() - t0) * 2976 / T
        print(f'  {n:>6} členů: {dt:6.2f} s za měsíc ({dt / 2976 * 1e3:.3f} ms na čtvrthodinu)')
