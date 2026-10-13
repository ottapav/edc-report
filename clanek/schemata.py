"""Schémata článku jako inline SVG (barvy přes CSS třídy napojené na tokeny stránky).

Každá funkce vrací jedno <svg>; clanek.render() jím nahradí značku {{JMÉNO}} v clanek.html."""


def nadoby():
    base, sc = 270, 7.0                       # základna a px na 1 kWh hladiny
    H = 16
    members = [  # jméno, klíč, odběr, x
        ('Dana', 0.5, 4, 90), ('Emil', 0.3, 5, 340), ('Filip', 0.2, 6, 520)]
    fmt = lambda v: f"{v:g}".replace(".", ",")
    out = ['<svg viewBox="0 112 640 228" role="img" aria-label="Tři nádoby se společnou hladinou H = 16 kWh na 100 % klíče">']
    yH = base - H * sc
    # svislá osa hladiny
    out.append(f'<line x1="62" y1="{base}" x2="62" y2="125" class="edge"/>')
    for v in (0, 8, 16):
        yy = base - v * sc
        out.append(f'<line x1="56" y1="{yy}" x2="62" y2="{yy}" class="edge"/>')
        out.append(f'<text x="52" y="{yy + 5}" class="lbl mut" text-anchor="end">{v}</text>')
    out.append(f'<text transform="translate(18 {base - 8 * sc}) rotate(-90)" class="lbl mut" text-anchor="middle">hladina (kWh na 100 % klíče)</text>')
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
        out.append(f'<text x="{cx}" y="{base + 40}" class="lbl mut" text-anchor="middle">klíč {round(k*100)} %</text>')
        out.append(f'<text x="{cx}" y="{base + 58}" class="lbl mut" text-anchor="middle">spotřeba {D} kWh</text>')
        if D / k <= H:
            out.append(f'<text x="{cx}" y="{top - 8:.1f}" class="lbl mut" text-anchor="middle">plná</text>')
        elif name == 'Emil':
            out.append(f'<text x="{cx}" y="{yH - 22:.1f}" class="lbl mut" text-anchor="middle">plná až při {fmt(round(D / k, 1))}</text>')
    out.append(f'<line x1="62" y1="{yH}" x2="625" y2="{yH}" class="dash"/>')
    out.append(f'<text x="72" y="{yH - 8}" class="lbl acc">hladina H = 16 kWh</text>')
    out.append('</svg>')
    return '\n'.join(out)


def hladina():
    vals = [16 - 4 * 0.5 ** (r - 1) for r in range(1, 11)]
    x = lambda r: 80 + (r - 1) * 56
    y = lambda v: 230 - (v - 11) / 5.6 * 200
    out = ['<svg viewBox="0 0 660 290" role="img" aria-label="Hladina po kolech se blíží k H = 16">']
    for v in (12, 13, 14, 15, 16):
        out.append(f'<line x1="70" y1="{y(v):.1f}" x2="600" y2="{y(v):.1f}" class="grid"/>')
        out.append(f'<text x="60" y="{y(v) + 4:.1f}" class="lbl mut" text-anchor="end">{v}</text>')
    out.append(f'<line x1="70" y1="{y(16):.1f}" x2="640" y2="{y(16):.1f}" class="dash"/>')
    out.append(f'<text x="640" y="{y(16) - 8:.1f}" class="lbl acc" text-anchor="end">H = 16 kWh (přesná statická)</text>')
    for r in (1, 5):
        out.append(f'<line x1="{x(r)}" y1="{y(11.2):.1f}" x2="{x(r)}" y2="{y(vals[r-1]) + 8:.1f}" class="mark"/>')
    pts = ' '.join(f'{x(r):.1f},{y(v):.1f}' for r, v in enumerate(vals, 1))
    out.append(f'<polyline points="{pts}" class="line"/>')
    for r, v in enumerate(vals, 1):
        cls = 'dot hi' if r in (1, 5) else 'dot'
        out.append(f'<circle cx="{x(r):.1f}" cy="{y(v):.1f}" r="{5 if r in (1, 5) else 3.5}" class="{cls}"/>')
        out.append(f'<text x="{x(r):.1f}" y="256" class="lbl mut" text-anchor="middle">{r}</text>')
    out.append(f'<text x="{x(1) + 10}" y="{y(12) + 22:.1f}" class="lbl">12 kWh · nad 100 EAN končí po 1. kole</text>')
    out.append(f'<text x="{x(5) + 10}" y="{y(15.75) + 26:.1f}" class="lbl">15,75 kWh · do 100 EAN končí po 5. kole</text>')
    out.append('<text x="340" y="282" class="lbl mut" text-anchor="middle">kolo výpočtu</text><text x="14" y="18" class="lbl mut">hladina (kWh na 100 % klíče)</text>')
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


def sit():
    out = ['<svg viewBox="0 0 600 230" role="img" aria-label="Dvě výrobny a dvě odběrná místa s vazbami po dvojicích">', DEFS]
    out.append(_node(40, 30, 150, 54, 'Výrobna B', '10 kWh'))
    out.append(_node(40, 146, 150, 54, 'Výrobna A', '10 kWh'))
    out.append(_node(410, 30, 150, 54, 'Odběr O1', 'potřebuje 10 kWh'))
    out.append(_node(410, 146, 150, 54, 'Odběr O2', 'potřebuje 10 kWh'))
    out.append(_arrow(190, 57, 406, 57, 'klíč 100 %', 300, 46))
    out.append(_arrow(190, 173, 406, 173, 'klíč 50 %', 300, 162))
    out.append(_arrow(190, 152, 406, 80))
    out.append('<text x="215" y="112" class="lbl acc">klíč 50 %</text>')
    out.append('</svg>')
    return '\n'.join(out)


def bazen():
    out = ['<svg viewBox="0 0 680 250" role="img" aria-label="Režim bazén: výroba se sečte, rozdělí a vrátí na výrobny">', DEFS]
    out.append(_node(20, 30, 140, 54, 'Výrobna A', '10 kWh'))
    out.append(_node(20, 150, 140, 54, 'Výrobna B', '6 kWh'))
    out.append(_node(260, 82, 160, 70, 'Bazén 16 kWh', 'H = 28 kWh', 'pool'))
    out.append(_node(520, 30, 140, 54, 'Odběr O1', 'dostane 2 kWh'))
    out.append(_node(520, 150, 140, 54, 'Odběr O2', 'dostane 14 kWh'))
    out.append(_arrow(160, 57, 256, 105))
    out.append(_arrow(160, 177, 256, 130))
    out.append(_arrow(420, 105, 516, 60, 'klíč 50 %', 452, 74))
    out.append(_arrow(420, 130, 516, 175, 'klíč 50 %', 452, 172))
    out.append('<text x="340" y="236" class="lbl mut" text-anchor="middle">Zpět na výrobny v poměru jejich výroby: A 62,5 %, B 37,5 % z každého odběru</text>')
    out.append('</svg>')
    return '\n'.join(out)
