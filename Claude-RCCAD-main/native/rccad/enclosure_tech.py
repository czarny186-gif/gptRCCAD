"""Generator obudów - etap 14: technologia produkcji obudowy (podetapy 14A-14D, każdy z własnymi parametrami i regułami).

14A Druk 3D - geometria z generatora (etapy 2-13) + analiza dla orientacji druku: nawisy (ściany skierowane w dół
    bardziej niż kąt graniczny, poza stołem), cienkie ścianki (poniżej minimum i 2 × średnica dyszy), przestrzeń robocza
    drukarki; zbyt duża część może zostać podzielona na kawałki z otworami na kołki ustalające i osobnymi kołkami.
14B Blacha - obudowa z dwóch kształtek giętych (moduł blach RCCAD: płyta + kołnierze 90°, rozwinięcia z naddatkiem
    gięcia BA = kąt · (R + K·t), linie gięcia): podstawa „U” (dno, przód, tył) i pokrywa „U” (góra, boki) ze szczeliną
    narożną; bryły mają stan blachy - działają na nich narzędzia blach (rozłóż / zegnij, eksport DXF).
14C Frezowanie CNC - podstawa i pokrywa z litego bloku: kieszeń z promieniem wewnętrznym co najmniej promienia narzędzia
    albo z podcięciami „dogbone”; analiza dostępności z kierunku obróbki (podcięcia, zbyt małe promienie wewnętrzne).
14D Cięcie laserowe - sześć płaskich płyt o stałej grubości z połączeniami na noski i wpusty (luz montażowy), otworami
    montażowymi z punktów montażowych, kompensacją szczeliny cięcia w rozkroju; krawędzie prostopadłe do płyty (bez
    skosów); widok złożony i płyty rozłożone na płaszczyźnie."""
from __future__ import annotations

import math

import numpy as np

from . import kernel

TECHS = ('none', 'print', 'sheet', 'cnc', 'laser')
TECH_LABELS = {'none': 'Bez technologii (ogólna bryła)', 'print': '14A · Druk 3D', 'sheet': '14B · Blacha', 'cnc': '14C · Frezowanie CNC',
               'laser': '14D · Cięcie laserowe'}
DEFAULTS = {
    'print': dict(min_wall=1.2, nozzle=.4, fit=.2, overhang=45.0, bed_x=220.0, bed_y=220.0, bed_z=250.0, orient='auto', split=True, pin=4.0, pin_len=8.0),
    'sheet': dict(t=1.0, r=1.0, k=.44, gap=.2, relief='none', relief_size=2.0),
    'cnc': dict(tool=6.0, min_radius=3.0, depth=0.0, dogbone=False, floor=2.0),
    'laser': dict(t=3.0, kerf=.15, fit=.1, finger=10.0, holes=True, hole=3.2, flat=True),
}
EPS = 1e-6


def tech_of(spec):
    pr = spec.process or {}
    tech = pr.get('tech', 'none')
    return tech if tech in TECHS else 'none'


def params(spec):
    tech = tech_of(spec)
    p = dict(DEFAULTS.get(tech, {}))
    p.update((spec.process or {}).get(tech) or {})
    return p


def _box(lo, hi):
    from .enclosure import _make_box
    return _make_box(lo, hi)


def _to_world(env, shape):
    import cadquery as cq
    return kernel.transformed(cq.Shape.cast(shape), np.asarray(env.axes, float).T, np.asarray(env.center, float))


def _inner(env, spec):
    """Wnętrze (przestrzeń elementów + odstępy) w układzie przestrzeni - wspólna podstawa technologii 14B-14D."""
    from .enclosure import box_layout
    lay = box_layout(env, spec)
    return [np.asarray(x, float) for x in lay['inner']], lay


# ---------------------------------------------------------------------------------------------- 14A druk 3D
def print_up(env, part, orient):
    """Kierunek „w górę” druku części: auto - podstawa dnem do stołu, pokrywa górą do stołu."""
    ax = np.asarray(env.axes, float)
    if orient == 'auto':
        return -ax[2] if part == 'lid' else ax[2]
    sign = -1 if orient.endswith('-') else 1
    return ax['xyz'.index(orient[0])] * sign


def print_analysis(env, parts, p):
    """Nawisy, cienkie ścianki, przestrzeń robocza - dla każdej części w jej orientacji druku."""
    import cadquery as cq
    from . import enclosure_check as chk
    out = []
    limit = math.cos(math.radians(90.0 - float(p['overhang'])))
    wall = max(float(p['min_wall']), 2 * float(p['nozzle']))
    names = {'body': 'Obudowa', 'base': 'Podstawa', 'lid': 'Pokrywa'}
    for name, shape in parts.items():
        if name.startswith('pin'):
            continue
        sh = cq.Shape.cast(shape)
        up = print_up(env, 'lid' if name == 'lid' else 'base', p['orient'])
        pts = np.array([v.toTuple() for v in sh.Vertices()])
        bed = float((pts @ up).min()) if len(pts) else 0.0
        area, faces = 0.0, []
        for f in sh.Faces():
            try:
                n = np.asarray(f.normalAt(f.Center()).toTuple(), float)
            except Exception:
                continue
            c = np.asarray(f.Center().toTuple(), float)
            if float(n @ up) < -limit and float(c @ up) - bed > 1e-3:     # skierowana w dół, nie na stole
                area += f.Area()
                faces.append(f)
        label = names.get(name, name)
        if faces:
            region = cq.Compound.makeCompound(faces).wrapped
            out.append(('warning', f'{label}: nawisy / przewieszenia {area:.0f} mm² (ściany pochylone ponad {float(p["overhang"]):g}°) - podpory albo inna orientacja.', region))
        else:
            out.append(('ok', f'{label}: bez nawisów w orientacji druku.', None))
        for lvl, text, mark in chk.thickness(label, shape, wall):
            out.append((lvl, text + (' (druk: min. 2 × dysza)' if lvl == 'warning' else ''), mark))
        size = _extent(sh, up, env)
        bed_dims = sorted([float(p['bed_x']), float(p['bed_y'])])
        fits = size[2] <= float(p['bed_z']) + EPS and sorted(size[:2])[0] <= bed_dims[0] + EPS and sorted(size[:2])[1] <= bed_dims[1] + EPS
        out.append(('ok' if fits else 'warning', f'{label}: {size[0]:.0f} × {size[1]:.0f} × {size[2]:.0f} mm - ' +
                    ('mieści się w drukarce.' if fits else 'nie mieści się w przestrzeni roboczej drukarki.'), None))
    return out


def _extent(sh, up, env):
    ax = np.asarray(env.axes, float)
    others = [a for a in ax if abs(float(a @ up)) < .5]
    pts = np.array([v.toTuple() for v in sh.Vertices()])
    dims = [float((pts @ a).max() - (pts @ a).min()) for a in others] + [float((pts @ up).max() - (pts @ up).min())]
    return dims


def print_split(env, parts, p):
    """Części większe niż drukarka: podział płaszczyznami na kawałki (BRepAlgoAPI_Splitter) z otworami na kołki
    ustalające w ściankach na płaszczyznach podziału i osobnymi kołkami."""
    import cadquery as cq
    from .enclosure import _boolean, _single, _solids, _volume, check_solid
    out = {}
    ax = np.asarray(env.axes, float)
    bed = [float(p['bed_x']), float(p['bed_y']), float(p['bed_z'])]
    pin, plen, fit = float(p['pin']), float(p['pin_len']), float(p['fit'])
    npins = 0
    placed = []                                          # kołki już rozmieszczone (kołki z różnych płaszczyzn się nie krzyżują)
    for name, shape in parts.items():
        sh = cq.Shape.cast(shape)
        pts = np.array([v.toTuple() for v in sh.Vertices()])
        pieces = [shape]
        for i in range(3):
            proj = pts @ ax[i]
            length = float(proj.max() - proj.min())
            limit = bed[i] if i < 2 else bed[2]
            if length <= limit + EPS:
                continue
            n = int(math.ceil(length / limit))
            cuts = [float(proj.min()) + length * j / n for j in range(1, n)]
            new = []
            for piece in pieces:
                cur = [piece]
                for s in cuts:
                    nxt = []
                    for q in cur:
                        nxt += _split_plane(q, ax[i], s)
                    cur = nxt
                new += cur
            pieces = new
            for s in cuts:                                  # kołki ustalające na każdej płaszczyźnie podziału
                found, size = [], pin
                for size in (pin, pin * .75, pin * .5, 1.5):    # cienka ścianka - mniejszy kołek (najmniej 1,5 mm)
                    found = [c for c in _pin_points(shape, ax[i], s, size / 2 + .4, ax)
                             if all(np.linalg.norm(c - q) > plen / 2 + size for q in placed)]
                    if found:
                        break
                placed += found
                pin_d = size
                for c in found:
                    hole = cq.Solid.makeCylinder((pin_d + fit) / 2, plen + .6, cq.Vector(*(c - ax[i] * (plen / 2 + .3))), cq.Vector(*ax[i])).wrapped
                    pieces = [_boolean('cut', q, hole, 'otwór kołka') for q in pieces]
                    npins += 1
                    out[f'pin{npins}'] = check_solid(cq.Solid.makeCylinder(pin_d / 2, plen, cq.Vector(*(c - ax[i] * plen / 2)), cq.Vector(*ax[i])).wrapped)
        if len(pieces) == 1:
            out[name] = cq.Shape.cast(pieces[0])
            continue
        for j, q in enumerate(pieces, 1):
            out[f'{name}_{j}'] = check_solid(_single(q, f'Kawałek {j}'))
    return out


def _split_plane(shape, n, s):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.TopTools import TopTools_ListOfShape
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    from .enclosure import _solids, _volume
    face = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(*map(float, n * s)), gp_Dir(*map(float, n))), -1e4, 1e4, -1e4, 1e4).Face()
    args, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    args.Append(shape)
    tools.Append(face)
    sp = BRepAlgoAPI_Splitter()
    sp.SetArguments(args)
    sp.SetTools(tools)
    sp.Build()
    if not sp.IsDone():
        raise kernel.CadError('Podział części do druku nie powiódł się.')
    parts = [x for x in _solids(sp.Shape()) if _volume(x)[0] > 1e-6]
    return parts or [shape]


def _pin_points(shape, n, s, clearance, ax):
    """Punkty kołków na płaszczyźnie podziału: w materiale ścianek, z zapasem `clearance` wokół, najwyżej 4, rozstawione."""
    import cadquery as cq
    sh = cq.Shape.cast(shape)
    others = [a for a in ax if abs(float(a @ n)) < .5]
    pts = np.array([v.toTuple() for v in sh.Vertices()])
    lo = [float((pts @ a).min()) for a in others]
    hi = [float((pts @ a).max()) for a in others]
    cand = []
    for t in np.linspace(0, 1, 41):
        for u in np.linspace(0, 1, 41):
            c = n * s + others[0] * (lo[0] + (hi[0] - lo[0]) * t) + others[1] * (lo[1] + (hi[1] - lo[1]) * u)
            ring = [c] + [c + clearance * (math.cos(q) * others[0] + math.sin(q) * others[1]) for q in np.linspace(0, 2 * math.pi, 8, endpoint=False)]
            if all(kernel.point_state(sh, q) == 'in' for q in ring):
                cand.append(c)
    chosen = []
    for _ in range(4):                                     # najdalej od już wybranych
        if not cand:
            break
        best = max(cand, key=lambda c: min([np.linalg.norm(c - q) for q in chosen] or [np.linalg.norm(c)]) if chosen else -np.linalg.norm(c - cand[0]))
        if chosen and min(np.linalg.norm(best - q) for q in chosen) < 4 * clearance:
            break
        chosen.append(best)
    return chosen


# ---------------------------------------------------------------------------------------------- 14B blacha
def sheet_recipes(env, spec, p):
    """Przepisy blach (moduł blach RCCAD) w układzie przestrzeni: podstawa U (dno + przód / tył), pokrywa U (góra + boki)."""
    (ilo, ihi), _lay = _inner(env, spec)
    t, r, gap = float(p['t']), float(p['r']), float(p['gap'])
    if t <= 0 or r < 0 or gap < 0:
        raise kernel.CadError('Grubość blachy musi być dodatnia, a promień gięcia i szczelina nieujemne.')
    if not 0 <= float(p['k']) <= .5:
        raise kernel.CadError('Współczynnik K musi być w zakresie 0–0,5.')
    rules = dict(gap=gap, relief=p['relief'], relief_size=float(p['relief_size']), miter=True, auto_corners=True, kfactor=float(p['k']))
    H = float(ihi[2] - ilo[2])
    if H <= 2 * (r + t):
        raise kernel.CadError('Obudowa za niska dla tego promienia gięcia i grubości blachy.')
    # podstawa: płyta pod wnętrzem (x - między bokami pokrywy), kołnierze przód / tył do góry, wymiar zewnętrzny
    x0, x1 = ilo[0], ihi[0]
    y0, y1 = ilo[1] - t, ihi[1] + t
    z0 = ilo[2] - t
    base = dict(o=[x0, y0, z0], x=[1, 0, 0], y=[0, 1, 0], z=[0, 0, 1], lx=x1 - x0, ly=y1 - y0, lz=t)
    fl = [dict(kind='base', p0=[x1, y0, z0 + t], p1=[x0, y0, z0 + t], n=[0, 0, 1], m=[0, -1, 0], r=r, angle=90, length=H + t, measure='outer'),
          dict(kind='base', p0=[x0, y1, z0 + t], p1=[x1, y1, z0 + t], n=[0, 0, 1], m=[0, 1, 0], r=r, angle=90, length=H + t, measure='outer')]
    base_recipe = dict(base=base, t=t, flanges=fl, rules=rules)
    # pokrywa: płyta nad wnętrzem (x - na zewnątrz podstawy ze szczeliną), kołnierze boczne w dół
    X0, X1 = ilo[0] - gap - t - r, ihi[0] + gap + t + r          # wnętrze gięcia pokrywy omija górne krawędzie podstawy
    Z0 = ihi[2] + gap
    cover = dict(o=[X0, y0, Z0], x=[1, 0, 0], y=[0, 1, 0], z=[0, 0, 1], lx=X1 - X0, ly=y1 - y0, lz=t)
    cfl = [dict(kind='base', p0=[X0, y0, Z0], p1=[X0, y1, Z0], n=[0, 0, -1], m=[-1, 0, 0], r=r, angle=90, length=H + 2 * t + gap, measure='outer'),
           dict(kind='base', p0=[X1, y1, Z0], p1=[X1, y0, Z0], n=[0, 0, -1], m=[1, 0, 0], r=r, angle=90, length=H + 2 * t + gap, measure='outer')]
    cover_recipe = dict(base=cover, t=t, flanges=cfl, rules=rules)
    return base_recipe, cover_recipe


def _world_recipe(env, recipe):
    """Przepis blachy przeniesiony z układu przestrzeni do świata (punkty i kierunki)."""
    import copy
    ax = np.asarray(env.axes, float)
    c = np.asarray(env.center, float)
    P = lambda p: [float(x) for x in c + ax.T @ np.asarray(p, float)]
    D = lambda d: [float(x) for x in ax.T @ np.asarray(d, float)]
    r = copy.deepcopy(recipe)
    r['base'] = dict(r['base'], o=P(r['base']['o']), x=D(r['base']['x']), y=D(r['base']['y']), z=D(r['base']['z']))
    r['flanges'] = [dict(f, p0=P(f['p0']), p1=P(f['p1']), n=D(f['n']), m=D(f['m'])) for f in r['flanges']]
    return r


def sheet_parts(env, spec, p):
    """Podstawa i pokrywa z blachy (bryły + stany blachy) oraz rozwinięcia z liniami gięcia."""
    from . import sheetmetal as shm
    from . import sheetedit as she
    from .enclosure import check_solid
    import cadquery as cq
    br, cr = (_world_recipe(env, r) for r in sheet_recipes(env, spec, p))
    out, meta, flats, report = {}, {}, {}, []
    for name, rec in (('base', br), ('lid', cr)):
        shape = shm.build_sheet(rec)
        out[name] = check_solid(shape.wrapped)
        meta[name] = she.state(rec)
        try:
            pattern = shm.flat_pattern(rec)
        except kernel.CadError as exc:
            report.append(('warning', f'{"Podstawa" if name == "base" else "Pokrywa"}: rozwinięcie niedostępne - {exc}', None))
            continue
        blank = pattern['shape'] if hasattr(pattern['shape'], 'Faces') else cq.Shape.cast(pattern['shape'])
        top = max(blank.Faces(), key=lambda f: f.Center().z)
        flat = cq.Solid.extrudeLinear(top, cq.Vector(0, 0, -float(rec['t']))) if hasattr(cq.Solid, 'extrudeLinear') else blank
        shift = float(np.max(np.asarray(env.size, float))) * 2.5 + 40.0
        dx = shift * (1 if name == 'base' else 2)
        flat = flat.translate(cq.Vector(dx, 0, -top.Center().z))        # rozwinięcie obok obudowy, górą na z = 0
        P3 = lambda q: cq.Vector(float(q[0]) + dx, float(q[1]), 0.0)
        lines = [cq.Edge.makeLine(P3(b['a']), P3(b['b'])) for b in pattern['bends']]
        flats[name] = (flat, cq.Compound.makeCompound(lines) if lines else None, pattern)
        lengths = ', '.join(f'BA {b["allowance"]:.3f} mm' for b in pattern['bends'])
        report.append(('ok', f'{"Podstawa" if name == "base" else "Pokrywa"}: rozwinięcie {len(pattern["bends"])} gięć ({lengths}), K = {float(p["k"]):g}.', None))
    return out, meta, flats, report


# ---------------------------------------------------------------------------------------------- 14C frezowanie CNC
def cnc_parts(env, spec, p):
    """Podstawa i pokrywa frezowane z bloku: kieszeń od góry (podstawa) i od dołu (pokrywa) - narożniki wewnętrzne z
    promieniem ≥ promień narzędzia albo ostre z podcięciami dogbone."""
    import cadquery as cq
    from .enclosure import _boolean, check_solid
    from .enclosure_shapes import _fillet_profile
    (ilo, ihi), lay = _inner(env, spec)
    olo, ohi = (np.asarray(x, float) for x in lay['outer'])
    tool, rmin, floor = float(p['tool']), float(p['min_radius']), float(p['floor'])
    if tool <= 0 or floor <= 0:
        raise kernel.CadError('Średnica narzędzia i grubość dna muszą być dodatnie.')
    if not p['dogbone'] and rmin < tool / 2 - 1e-9:
        raise kernel.CadError(f'Minimalny promień wewnętrzny {rmin:g} mm jest mniejszy niż promień narzędzia {tool / 2:g} mm - zwiększ promień albo włącz dogbone.')
    split = float((ilo[2] + ihi[2]) / 2) if float(p['depth']) <= 0 else float(min(ihi[2], ilo[2] + float(p['depth'])))
    r = 0.0 if p['dogbone'] else max(rmin, tool / 2)

    def pocket(z0, z1):
        w, h = float(ihi[0] - ilo[0]), float(ihi[1] - ilo[1])
        if r >= min(w, h) / 2:
            raise kernel.CadError('Promień wewnętrzny za duży dla kieszeni.')
        face = cq.Face.makeFromWires(cq.Wire.makePolygon([cq.Vector(ilo[0], ilo[1], z0), cq.Vector(ihi[0], ilo[1], z0), cq.Vector(ihi[0], ihi[1], z0),
                                                          cq.Vector(ilo[0], ihi[1], z0)], close=True)).wrapped
        if r > 0:
            face = _fillet_profile(face, r)
        from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
        from OCP.gp import gp_Vec
        solid = BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, z1 - z0)).Shape()
        if p['dogbone']:                                   # podcięcia w narożnikach: walce Ø narzędzia przez narożnik
            rr = tool / 2
            for sx, x in ((-1, ilo[0]), (1, ihi[0])):
                for sy, y in ((-1, ilo[1]), (1, ihi[1])):
                    cx, cy = x + sx * rr / math.sqrt(2), y + sy * rr / math.sqrt(2)     # okrąg przechodzi przez narożnik
                    solid = _boolean('fuse', solid, cq.Solid.makeCylinder(rr, z1 - z0, cq.Vector(cx, cy, z0)).wrapped, 'dogbone')
        return solid
    base = _boolean('cut', _box(olo, [ohi[0], ohi[1], split]), pocket(ilo[2], split + 1.0), 'kieszeń podstawy')
    lid = _boolean('cut', _box([olo[0], olo[1], split], ohi), pocket(split - 1.0, ihi[2]), 'kieszeń pokrywy')
    out = {'base': check_solid(_to_world(env, base).wrapped), 'lid': check_solid(_to_world(env, lid).wrapped)}
    if ilo[2] - olo[2] < floor - 1e-6:
        raise kernel.CadError(f'Dno podstawy cieńsze niż {floor:g} mm - zwiększ grubość dna (ścianka dolna).')
    return out


def cnc_analysis(env, parts, p):
    """Dostępność dla obróbki z góry (podstawa) / z dołu (pokrywa): podcięcia (ściany skierowane od narzędzia, poza
    dnem przedmiotu) i zbyt małe promienie wewnętrzne (wklęsłe walce o osi wzdłuż kierunku obróbki)."""
    import cadquery as cq
    from .enclosure_mounts import _surface_info
    out = []
    ax = np.asarray(env.axes, float)
    tool = float(p['tool'])
    for name, shape in parts.items():
        d = ax[2] if name != 'lid' else -ax[2]             # kierunek „do narzędzia” (narzędzie podchodzi z tej strony)
        sh = cq.Shape.cast(shape)
        pts = np.array([v.toTuple() for v in sh.Vertices()])
        bottom = float((pts @ d).min())
        under, small = [], []
        for f in sh.Faces():
            if f.geomType() == 'PLANE':
                n = np.asarray(f.normalAt(f.Center()).toTuple(), float)
                if float(n @ d) < -1e-3 and float(np.asarray(f.Center().toTuple()) @ d) - bottom > 1e-3:
                    under.append(f)
            elif f.geomType() == 'CYLINDER':
                info = _surface_info(f.wrapped)
                if info and info['concave'] and abs(abs(float(info['d'] @ d)) - 1) < 1e-6 and info['r0'] < tool / 2 - 1e-6:
                    small.append(f)
        label = 'Podstawa' if name == 'base' else ('Pokrywa' if name == 'lid' else name)
        if under:
            out.append(('warning', f'{label}: {len(under)} ściany niedostępne z kierunku obróbki (podcięcia) - wymagają innego zamocowania.',
                        cq.Compound.makeCompound(under).wrapped))
        else:
            out.append(('ok', f'{label}: wszystkie ściany dostępne z kierunku obróbki.', None))
        if small:
            out.append(('warning', f'{label}: {len(small)} promienie wewnętrzne mniejsze niż narzędzie Ø{tool:g} mm.', cq.Compound.makeCompound(small).wrapped))
        else:
            out.append(('ok', f'{label}: promienie wewnętrzne ≥ promień narzędzia ({tool / 2:g} mm).', None))
    return out


# ---------------------------------------------------------------------------------------------- 14D cięcie laserowe
PANELS = ('bottom', 'top', 'front', 'back', 'left', 'right')
PANEL_LABELS = {'bottom': 'dno', 'top': 'góra', 'front': 'przód', 'back': 'tył', 'left': 'lewa', 'right': 'prawa'}
PRIORITY = {'bottom': 0, 'top': 0, 'front': 1, 'back': 1, 'left': 2, 'right': 2}
PANEL_AXIS = {'bottom': (2, -1), 'top': (2, 1), 'front': (1, -1), 'back': (1, 1), 'left': (0, -1), 'right': (0, 1)}


def laser_panels(env, spec, p, mounts=()):
    """Sześć płyt grubości t (układ przestrzeni): pełne płyty zewnętrznego prostopadłościanu, na wspólnych krawędziach
    naprzemienne noski / wpusty (luz montażowy w wpustach), narożniki - płyta o wyższym priorytecie (dno / góra)."""
    from .enclosure import _boolean, _single
    (ilo, ihi), _lay = _inner(env, spec)
    t, fit, finger = float(p['t']), float(p['fit']), float(p['finger'])
    if t <= 0 or finger <= t or fit < 0:
        raise kernel.CadError('Grubość płyty musi być dodatnia, nosek dłuższy niż grubość, a luz nieujemny.')
    lo, hi = ilo - t, ihi + t
    plates = {}
    for name, (i, s) in PANEL_AXIS.items():
        a, b = lo.copy(), hi.copy()
        if s < 0:
            b[i] = lo[i] + t
        else:
            a[i] = hi[i] - t
        plates[name] = _box(a, b)
    cuts = {name: [] for name in PANELS}
    names = list(PANELS)
    for x in range(len(names)):
        for y in range(x + 1, len(names)):
            A, B = names[x], names[y]
            ia, sa = PANEL_AXIS[A]
            ib, sb = PANEL_AXIS[B]
            if ia == ib:
                continue
            k = 3 - ia - ib                                       # oś wspólnej krawędzi
            if PRIORITY[A] > PRIORITY[B]:
                A, B, ia, sa, ib, sb = B, A, ib, sb, ia, sa
            e_lo, e_hi = lo.copy(), hi.copy()
            for i_, s_ in ((ia, sa), (ib, sb)):
                if s_ < 0:
                    e_hi[i_] = lo[i_] + t
                else:
                    e_lo[i_] = hi[i_] - t
            L = float(hi[k] - lo[k] - 2 * t)
            n = max(3, int(L // finger))
            n += (n + 1) % 2                                       # nieparzysta liczba odcinków: skrajne należą do A
            seg = L / n
            for j in range(n):
                s0 = lo[k] + t + j * seg
                q0, q1 = e_lo.copy(), e_hi.copy()
                q0[k], q1[k] = s0, s0 + seg
                if j % 2 == 0:                                     # odcinek należy do A - wycięty z B (z luzem)
                    q0[k] -= fit / 2
                    q1[k] += fit / 2
                    cuts[B].append(_box(q0, q1))
                else:
                    g0, g1 = q0.copy(), q1.copy()
                    g0[k] -= fit / 2
                    g1[k] += fit / 2
                    cuts[A].append(_box(g0, g1))
            corner = [e_lo.copy(), e_hi.copy()]                    # narożniki krawędzi (poza odcinkami) - do A
            for end in (0, 1):
                c0, c1 = e_lo.copy(), e_hi.copy()
                if end == 0:
                    c1[k] = lo[k] + t
                else:
                    c0[k] = hi[k] - t
                cuts[B].append(_box(c0, c1))
    out = {}
    for name in PANELS:
        shape = plates[name]
        for c in cuts[name]:
            shape = _boolean('cut', shape, c, 'noski i wpusty')
        out[name] = _single(shape, f'Płyta {PANEL_LABELS[name]}')
    if p.get('holes') and mounts:                                  # otwory montażowe (punkty montażowe od dna)
        import cadquery as cq
        ax = np.asarray(env.axes, float)
        c = np.asarray(env.center, float)
        for m in mounts:
            if m.get('side') != 'z-':
                continue
            q = ax @ (np.asarray(m['center'], float) - c)
            hole = cq.Solid.makeCylinder(float(p['hole']) / 2, t + 2, cq.Vector(q[0], q[1], lo[2] - 1), cq.Vector(0, 0, 1)).wrapped
            out['bottom'] = _boolean('cut', out['bottom'], hole, 'otwór montażowy')
    return out


def laser_parts(env, spec, p, mounts=()):
    """Płyty złożone (świat) i rozłożone na płaszczyźnie (z kompensacją szczeliny cięcia w obrysie rozkroju)."""
    import cadquery as cq
    from .enclosure import check_solid
    local = laser_panels(env, spec, p, mounts)
    out = {f'panel_{k}': check_solid(_to_world(env, v).wrapped) for k, v in local.items()}
    flats = {}
    if p.get('flat', True):
        x = float(np.max(np.asarray(env.size, float))) * 2.5 + 40.0
        kerf = float(p['kerf'])
        for name, shape in local.items():
            i, s = PANEL_AXIS[name]
            sh = cq.Shape.cast(shape)
            # płyta na płaszczyźnie XY: oś grubości -> Z, potem obok siebie
            R = np.eye(3)[[k for k in range(3) if k != i] + [i]]
            flat = kernel.transformed(sh, R, np.zeros(3))
            bb = flat.BoundingBox()
            flat = flat.translate(cq.Vector(x - bb.xmin, -bb.ymin, -bb.zmin))
            if kerf > 0:                                           # obrys do cięcia: odsunięty o połowę szczeliny (kompensacja)
                top = max(flat.Faces(), key=lambda f: f.Center().z)
                from .enclosure_contour import offset
                face = offset(top.wrapped, kerf / 2, 'kompensacja szczeliny')
                flat = cq.Solid.extrudeLinear(cq.Face(face), cq.Vector(0, 0, -float(p['t'])))
            flats[f'flat_{name}'] = check_solid(flat.wrapped)
            x += bb.xlen + 10.0
    return out, flats


def laser_analysis(parts):
    """Krawędzie płyt prostopadłe do powierzchni (płaskie ściany tylko w trzech kierunkach osi płyty) - bez skosów."""
    import cadquery as cq
    out = []
    for name, shape in parts.items():
        from .enclosure_mounts import _surface_info
        sh = cq.Shape.cast(shape)
        bb = sh.BoundingBox()
        dims = [bb.xlen, bb.ylen, bb.zlen]
        thick = np.eye(3)[int(np.argmin(dims))]                 # oś grubości płyty
        bad = []
        for f in sh.Faces():
            if f.geomType() == 'PLANE':
                n = np.abs(np.asarray(f.normalAt(f.Center()).toTuple()))
                if not (abs(float(n @ thick) - 1) < 1e-6 or abs(float(n @ thick)) < 1e-6):
                    bad.append(f)
            elif f.geomType() == 'CYLINDER':
                info = _surface_info(f.wrapped)
                if info is None or abs(abs(float(info['d'] @ thick)) - 1) > 1e-6:
                    bad.append(f)
            else:
                bad.append(f)
        ok = not bad
        label = PANEL_LABELS.get(name.replace('panel_', ''), name)
        out.append(('ok' if ok else 'error', f'Płyta {label}: ' + ('krawędzie prostopadłe do płyty (bez skosów).' if ok else 'krawędzie ukośne albo zakrzywione - niewykonalne laserem.'), None))
    return out
