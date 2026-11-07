"""Schémata článku jako inline SVG (barvy přes CSS třídy napojené na tokeny stránky).

Každá funkce vrací jedno <svg>; clanky.Article.render() jím nahradí značku {{JMÉNO}}
v clanek.html. Článek je zatím jen česky."""

T = {
    "cs": dict(
        aria="Cenový žebříček: úspora 3 Kč/kWh mezi výkupní cenou 1 Kč a cenou od prodejce "
             "4 Kč se dělí mezi výrobce a člena; při dostatku výroby napůl (2,50 Kč/kWh), "
             "při nedostatku dostane víc výrobce (2,75 Kč/kWh)",
        axis="Kč/kWh", supplier="cena od prodejce 4 Kč", feed_in="výkupní cena 1 Kč",
        saving="úspora 3 Kč/kWh", producer="výrobce", member="člen", price="cena",
        enough="Dost výroby pro všechny", scarce="Málo výroby (tabulka 1)"),
}


def _kc(v: float) -> str:
    return f"{v:.2f}".replace(".", ",") + " Kč"


def zebricek(lang: str = "cs") -> str:
    """Kam padne cena sdílené kWh: úspora mezi výkupní cenou a cenou od prodejce, rozdělená
    mezi výrobce (dole) a člena (nahoře); dvě situace z článku vedle sebe."""
    tx = T[lang]
    feed, supplier = 1.0, 4.0
    y = lambda p: 268 - p * 54                       # 0 Kč dole, 4,5 Kč nahoře
    cols = [(110, 2.50, tx["enough"]), (380, 2.75, tx["scarce"])]   # x, cena, popisek
    w = 130
    out = [f'<svg viewBox="0 0 660 318" role="img" aria-label="{tx["aria"]}">']
    # osa cen
    out.append(f'<line x1="70" y1="{y(0)}" x2="70" y2="{y(4.5)}" class="edge"/>')
    for p in range(5):
        out.append(f'<line x1="64" y1="{y(p)}" x2="70" y2="{y(p)}" class="edge"/>')
        out.append(f'<text x="58" y="{y(p) + 4}" class="lbl mut" text-anchor="end">{p}</text>')
    out.append(f'<text x="70" y="{y(4.5) - 8}" class="lbl mut" text-anchor="middle">{tx["axis"]}</text>')
    for x, price, title in cols:
        cx = x + w / 2
        # výrobce: od výkupní ceny k ceně sdílené kWh; člen: od ní k ceně od prodejce
        out.append(f'<rect x="{x}" y="{y(price)}" width="{w}" height="{y(feed) - y(price)}" class="part-prod"/>')
        out.append(f'<rect x="{x}" y="{y(supplier)}" width="{w}" height="{y(price) - y(supplier)}" class="water"/>')
        out.append(f'<text x="{cx}" y="{(y(price) + y(feed)) / 2 + 5}" class="lbl" text-anchor="middle">'
                   f'{tx["producer"]} {_kc(price - feed)}</text>')
        out.append(f'<text x="{cx}" y="{(y(supplier) + y(price)) / 2 + 5}" class="lbl" text-anchor="middle">'
                   f'{tx["member"]} {_kc(supplier - price)}</text>')
        out.append(f'<line x1="{x - 6}" y1="{y(price)}" x2="{x + w + 6}" y2="{y(price)}" class="line"/>')
        out.append(f'<text x="{x + w + 12}" y="{y(price) + 5}" class="lbl b">{tx["price"]} {_kc(price)}</text>')
        out.append(f'<text x="{cx}" y="{y(0) + 22}" class="lbl b" text-anchor="middle">{title}</text>')
    # společné hranice a úspora mezi nimi
    for p, label in ((supplier, tx["supplier"]), (feed, tx["feed_in"])):
        out.append(f'<line x1="70" y1="{y(p)}" x2="620" y2="{y(p)}" class="dash"/>')
        dy = -8 if p == supplier else 18
        out.append(f'<text x="80" y="{y(p) + dy}" class="lbl acc">{label}</text>')
    out.append(f'<line x1="632" y1="{y(supplier)}" x2="632" y2="{y(feed)}" class="edge"/>')
    for p in (supplier, feed):
        out.append(f'<line x1="626" y1="{y(p)}" x2="638" y2="{y(p)}" class="edge"/>')
    mid = (y(supplier) + y(feed)) / 2
    out.append(f'<text transform="translate(651 {mid}) rotate(-90)" class="lbl mut" '
               f'text-anchor="middle">{tx["saving"]}</text>')
    out.append('</svg>')
    return '\n'.join(out)
