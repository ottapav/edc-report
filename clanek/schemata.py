"""Schémata článku jako inline SVG (barvy přes CSS třídy napojené na tokeny stránky).

Každá funkce vrací jedno <svg> v daném jazyce (cs / en / de); clanek.render() jím nahradí
značku {{JMÉNO}} v clanek.html (clanek.en.html, clanek.de.html). Texty schémat jsou
v tabulce ``T``, čísla se píšou s desetinnou čárkou (cs, de) nebo tečkou (en)."""

T = {
    "cs": dict(
        vessels="Tři nádoby se společnou hladinou H = 16 kWh na 100 % klíče",
        level_axis="hladina (kWh na 100 % klíče)", key="klíč", use="spotřeba", full="plná",
        full_at="plná až při", level_h="hladina H = 16 kWh",
        rounds_aria="Hladina po kolech se blíží k H = 16", exact="H = 16 kWh (přesná statická)",
        r1="12 kWh · nad 100 EAN končí po 1. kole", r5="15,75 kWh · do 100 EAN končí po 5. kole",
        round="kolo výpočtu",
        net="Dvě výrobny a dvě odběrná místa s vazbami po dvojicích",
        plant="Výrobna", point="Odběr", needs="potřebuje",
        pool_aria="Režim bazén: výroba se sečte, rozdělí a vrátí na výrobny", pool="Bazén",
        gets="dostane", back="Zpět na výrobny v poměru jejich výroby: A 62,5 %, B 37,5 % z každého odběru"),
    "en": dict(
        vessels="Three vessels with a common level H = 16 kWh per 100 % key",
        level_axis="level (kWh per 100 % key)", key="key", use="consumption", full="full",
        full_at="full only at", level_h="level H = 16 kWh",
        rounds_aria="The level after each round approaches H = 16", exact="H = 16 kWh (exact method)",
        r1="12 kWh · above 100 EANs it ends after round 1",
        r5="15.75 kWh · up to 100 EANs it ends after round 5", round="round of the calculation",
        net="Two plants and two metering points with a key for each pair",
        plant="Plant", point="Metering point", needs="needs",
        pool_aria="Pool mode: the production is added up, divided and returned to the plants",
        pool="Pool", gets="gets",
        back="Back to the plants in proportion to their output: A 62.5 %, B 37.5 % of each consumption"),
    "de": dict(
        vessels="Drei Gefäße mit gemeinsamem Pegel H = 16 kWh je 100 % Schlüssel",
        level_axis="Pegel (kWh je 100 % Schlüssel)", key="Schlüssel", use="Verbrauch", full="voll",
        full_at="voll erst bei", level_h="Pegel H = 16 kWh",
        rounds_aria="Der Pegel nähert sich nach jeder Runde H = 16", exact="H = 16 kWh (exakte Methode)",
        r1="12 kWh · über 100 EAN endet nach Runde 1",
        r5="15,75 kWh · bis 100 EAN endet nach Runde 5", round="Berechnungsrunde",
        net="Zwei Anlagen und zwei Verbrauchsstellen mit Schlüsseln je Paar",
        plant="Anlage", point="Verbrauchsstelle", needs="braucht",
        pool_aria="Pool-Modus: Die Erzeugung wird addiert, verteilt und auf die Anlagen zurückgeführt",
        pool="Pool", gets="erhält",
        back="Zurück auf die Anlagen im Verhältnis ihrer Erzeugung: A 62,5 %, B 37,5 % von jedem Verbrauch"),
}


def _num(v, lang):
    s = f"{v:g}"
    return s if lang == "en" else s.replace(".", ",")


def nadoby(lang='cs'):
    base, sc = 270, 7.0                       # základna a px na 1 kWh hladiny
    H = 16
    members = [  # jméno, klíč, odběr, x
        ('Dana', 0.5, 4, 90), ('Emil', 0.3, 5, 340), ('Filip', 0.2, 6, 520)]
    tx = T[lang]
    fmt = lambda v: _num(v, lang)
    out = [f'<svg viewBox="0 112 640 228" role="img" aria-label="{tx["vessels"]}">']
    yH = base - H * sc
    # svislá osa hladiny
    out.append(f'<line x1="62" y1="{base}" x2="62" y2="125" class="edge"/>')
    for v in (0, 8, 16):
        yy = base - v * sc
        out.append(f'<line x1="56" y1="{yy}" x2="62" y2="{yy}" class="edge"/>')
        out.append(f'<text x="52" y="{yy + 5}" class="lbl mut" text-anchor="end">{v}</text>')
    out.append(f'<text transform="translate(18 {base - 8 * sc}) rotate(-90)" class="lbl mut" text-anchor="middle">{tx["level_axis"]}</text>')
    for name, k, D, x in members:
        w = k * 400
        top = base - D / k * sc
        water = min(D / k, H) * sc
        share = min(D, k * H)
        out.append(f'<rect x="{x}" y="{base - water:.1f}" width="{w}" height="{water:.1f}" class="water"/>')
        out.append(f'<path d="M{x},{top:.1f} V{base} H{x + w} V{top:.1f}" class="vessel"/>')
        cx = x + w / 2
        out.append(f'<text x="{cx}" y="{base - water / 2 + 6:.1f}" class="lbl b" text-anchor="middle">{fmt(share)} kWh</text>')
        out.append(f'<text x="{cx}" y="{base + 22}" class="lbl b" text-anchor="middle">{name}</text>')
        out.append(f'<text x="{cx}" y="{base + 40}" class="lbl mut" text-anchor="middle">{tx["key"]} {round(k*100)} %</text>')
        out.append(f'<text x="{cx}" y="{base + 58}" class="lbl mut" text-anchor="middle">{tx["use"]} {D} kWh</text>')
        if D / k <= H:
            out.append(f'<text x="{cx}" y="{top - 8:.1f}" class="lbl mut" text-anchor="middle">{tx["full"]}</text>')
        elif name == 'Emil':
            out.append(f'<text x="{cx}" y="{yH - 22:.1f}" class="lbl mut" text-anchor="middle">{tx["full_at"]} {fmt(round(D / k, 1))}</text>')
    out.append(f'<line x1="62" y1="{yH}" x2="625" y2="{yH}" class="dash"/>')
    out.append(f'<text x="72" y="{yH - 8}" class="lbl acc">{tx["level_h"]}</text>')
    out.append('</svg>')
    return '\n'.join(out)


def hladina(lang='cs'):
    tx = T[lang]
    vals = [16 - 4 * 0.5 ** (r - 1) for r in range(1, 11)]
    x = lambda r: 80 + (r - 1) * 56
    y = lambda v: 230 - (v - 11) / 5.6 * 200
    out = [f'<svg viewBox="0 0 660 290" role="img" aria-label="{tx["rounds_aria"]}">']
    for v in (12, 13, 14, 15, 16):
        out.append(f'<line x1="70" y1="{y(v):.1f}" x2="600" y2="{y(v):.1f}" class="grid"/>')
        out.append(f'<text x="60" y="{y(v) + 4:.1f}" class="lbl mut" text-anchor="end">{v}</text>')
    out.append(f'<line x1="70" y1="{y(16):.1f}" x2="640" y2="{y(16):.1f}" class="dash"/>')
    out.append(f'<text x="640" y="{y(16) - 8:.1f}" class="lbl acc" text-anchor="end">{tx["exact"]}</text>')
    for r in (1, 5):
        out.append(f'<line x1="{x(r)}" y1="{y(11.2):.1f}" x2="{x(r)}" y2="{y(vals[r-1]) + 8:.1f}" class="mark"/>')
    pts = ' '.join(f'{x(r):.1f},{y(v):.1f}' for r, v in enumerate(vals, 1))
    out.append(f'<polyline points="{pts}" class="line"/>')
    for r, v in enumerate(vals, 1):
        cls = 'dot hi' if r in (1, 5) else 'dot'
        out.append(f'<circle cx="{x(r):.1f}" cy="{y(v):.1f}" r="{5 if r in (1, 5) else 3.5}" class="{cls}"/>')
        out.append(f'<text x="{x(r):.1f}" y="256" class="lbl mut" text-anchor="middle">{r}</text>')
    out.append(f'<text x="{x(1) + 10}" y="{y(12) + 22:.1f}" class="lbl">{tx["r1"]}</text>')
    out.append(f'<text x="{x(5) + 10}" y="{y(15.75) + 26:.1f}" class="lbl">{tx["r5"]}</text>')
    out.append(f'<text x="340" y="282" class="lbl mut" text-anchor="middle">{tx["round"]}</text><text x="14" y="18" class="lbl mut">{tx["level_axis"]}</text>')
    out.append('</svg>')
    return '\n'.join(out)


def _node(x, y, w, h, t1, t2, cls='node'):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" class="{cls}"/>'
            f'<text x="{x + w/2}" y="{y + h/2 - 3}" class="lbl b" text-anchor="middle">{t1}</text>'
            f'<text x="{x + w/2}" y="{y + h/2 + 15}" class="lbl mut" text-anchor="middle">{t2}</text>')


def _arrow(x1, y1, x2, y2, label=None, lx=None, ly=None):
    s = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="edge" marker-end="url(#ah)"/>'
    if label:
        s += f'<text x="{lx}" y="{ly}" class="lbl acc" text-anchor="middle">{label}</text>'
    return s


DEFS = ('<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="ahead"/></marker></defs>')


def sit(lang='cs'):
    tx = T[lang]
    out = [f'<svg viewBox="0 0 640 230" role="img" aria-label="{tx["net"]}">', DEFS]
    out.append(_node(40, 30, 150, 54, f"{tx['plant']} B", '10 kWh'))
    out.append(_node(40, 146, 150, 54, f"{tx['plant']} A", '10 kWh'))
    out.append(_node(410, 30, 200, 54, f"{tx['point']} O1", f"{tx['needs']} 10 kWh"))
    out.append(_node(410, 146, 200, 54, f"{tx['point']} O2", f"{tx['needs']} 10 kWh"))
    out.append(_arrow(190, 57, 406, 57, f"{tx['key']} 100 %", 300, 46))
    out.append(_arrow(190, 173, 406, 173, f"{tx['key']} 50 %", 300, 162))
    out.append(_arrow(190, 152, 406, 80))
    out.append(f'<text x="215" y="112" class="lbl acc">{tx["key"]} 50 %</text>')
    out.append('</svg>')
    return '\n'.join(out)


def bazen(lang='cs'):
    tx = T[lang]
    out = [f'<svg viewBox="0 0 760 250" role="img" aria-label="{tx["pool_aria"]}">', DEFS]
    out.append(_node(10, 30, 140, 54, f"{tx['plant']} A", '10 kWh'))
    out.append(_node(10, 150, 140, 54, f"{tx['plant']} B", '6 kWh'))
    out.append(_node(230, 82, 160, 70, f"{tx['pool']} 16 kWh", 'H = 28 kWh', 'pool'))
    out.append(_node(550, 30, 190, 54, f"{tx['point']} O1", f"{tx['gets']} 2 kWh"))
    out.append(_node(550, 150, 190, 54, f"{tx['point']} O2", f"{tx['gets']} 14 kWh"))
    out.append(_arrow(150, 57, 226, 105))
    out.append(_arrow(150, 177, 226, 130))
    out.append(_arrow(390, 105, 546, 60, f"{tx['key']} 50 %", 398, 62))
    out.append(_arrow(390, 130, 546, 175, f"{tx['key']} 50 %", 398, 194))
    out.append(f'<text x="380" y="238" class="lbl mut" text-anchor="middle">{tx["back"]}</text>')
    out.append('</svg>')
    return '\n'.join(out)
