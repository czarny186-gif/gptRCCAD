"""Generator obudów - etap 7: elementy mocujące komponenty z punktów montażowych (etap 6).

Każdy zatwierdzony punkt montażowy (środek wejścia otworu albo punkt na ścianie elementu, kierunek mocowania - od
elementu do ścianki obudowy) dostaje mocowanie: słupek cylindryczny, prostokątny, stożkowy albo z żebrami, kołek
zatrzaskowy, prowadnicę wsuwaną albo podporę bez otworu. Słupek stoi na wewnętrznej powierzchni właściwej ścianki
(dno, pokrywa, ściana boczna - pierwsze trafienie promienia od punktu w kierunku mocowania), sięga do powierzchni
montażowej elementu (wysokość liczona automatycznie, można ją nadpisać) i wchodzi w ściankę na część jej grubości, więc
po BRepAlgoAPI_Fuse tworzy z częścią obudowy jedną bryłę bez szczeliny. Otwory: pod wkręt (średnica wstępna), przelotowy
z gniazdem nakrętki (sześciokąt od zewnątrz obudowy), gniazdo insertu termicznego, otwór pod gwint (średnica wiertła +
opcjonalny gwint kosmetyczny RCCAD - bez geometrii zwojów). Geometria: BRepPrimAPI_MakeCylinder / MakeBox / MakeCone /
MakeWedge, BRepAlgoAPI_Fuse / Cut. Kolizje z elementami sprawdzane operacją Common (styk powierzchni dozwolony)."""
from __future__ import annotations

import math

import numpy as np

from . import kernel

POST_TYPES = ('cylinder', 'rect', 'cone', 'ribbed', 'snap', 'guide', 'support')
POST_LABELS = {'cylinder': 'Słupek cylindryczny', 'rect': 'Słupek prostokątny', 'cone': 'Słupek stożkowy', 'ribbed': 'Słupek z żebrami',
               'snap': 'Kołek zatrzaskowy', 'guide': 'Prowadnica wsuwana', 'support': 'Podpora bez otworu'}
FASTENINGS = ('pilot', 'clearance', 'nut', 'insert', 'tapped')
FASTEN_LABELS = {'pilot': 'Otwór pod wkręt', 'clearance': 'Otwór przelotowy pod śrubę', 'nut': 'Gniazdo na nakrętkę',
                 'insert': 'Gniazdo insertu termicznego', 'tapped': 'Otwór pod gwint (gwint kosmetyczny)'}
# rozmiar: średnica nominalna, otwór przelotowy, otwór pod wkręt do tworzywa, otwór insertu, długość insertu,
# rozwartość nakrętki (S), wysokość nakrętki, skok gwintu
SCREWS = {'M2': (2.0, 2.4, 1.6, 3.2, 3.0, 4.0, 1.6, .4), 'M2.5': (2.5, 2.9, 2.0, 3.6, 4.0, 5.0, 2.0, .45),
          'M3': (3.0, 3.4, 2.5, 4.0, 4.0, 5.5, 2.4, .5), 'M4': (4.0, 4.5, 3.3, 5.6, 6.0, 7.0, 3.2, .7),
          'M5': (5.0, 5.5, 4.2, 6.4, 7.0, 8.0, 4.0, .8)}
DEFAULTS = dict(enabled=True, type='cylinder', fastening='pilot', screw='M3', diameter=7.0, width=7.0, top_diameter=5.5,
                height=0.0, hole_depth=0.0, rib=1.2, ribs=4, gap=0.2, thread=False, groove=1.6, length=12.0, embed=.6)


def screw(size):
    d, clear, pilot, ins, ins_len, nut_af, nut_h, pitch = SCREWS.get(size, SCREWS['M3'])
    return dict(d=d, clear=clear, pilot=pilot, insert=ins, insert_len=ins_len, nut_af=nut_af, nut_h=nut_h, pitch=pitch)


def params(defaults, mount):
    """Parametry mocowania: wspólne (defaults) + nadpisania danego punktu (mount['post'])."""
    p = dict(DEFAULTS)
    p.update(defaults or {})
    p.update((mount or {}).get('post') or {})
    return p


def hole_diameter(p):
    s = screw(p['screw'])
    f = p['fastening']
    if f == 'pilot':
        return s['pilot']
    if f in ('clearance', 'nut'):
        return s['clear'] + max(0.0, float(p['gap']) - .2)
    if f == 'insert':
        return s['insert']
    if f == 'tapped':
        from . import threads
        return threads.drill('M', s['d'], s['pitch'])
    return 0.0


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _frame(axis):
    """Układ słupka: z' = -kierunek mocowania (od ścianki do elementu)."""
    z = -_unit(axis)
    x = _unit(np.cross(z, (0, 0, 1.0) if abs(z[2]) < .9 else (1.0, 0, 0)))
    return x, np.cross(z, x), z


def wall_hit(shape, point, axis):
    """Pierwsze trafienie promienia od punktu montażowego w kierunku mocowania w bryłę obudowy: (punkt, odległość)."""
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    inter = IntCurvesFace_ShapeIntersector()
    inter.Load(shape, 1e-6)
    p = np.asarray(point, float)
    inter.Perform(gp_Lin(gp_Pnt(*map(float, p)), gp_Dir(*map(float, _unit(axis)))), 1e-6, 1e9)
    if not inter.IsDone() or inter.NbPnt() == 0:
        return None
    best = min(inter.WParameter(i) for i in range(1, inter.NbPnt() + 1))
    return p + _unit(axis) * best, float(best)


def _wall_thickness(shape, hit, axis):
    """Grubość ścianki w miejscu trafienia (wzdłuż osi mocowania) - na ile słupek wchodzi w ściankę."""
    out = wall_hit_exit(shape, hit, axis)
    return out if out is not None else 1.0


def wall_hit_exit(shape, hit, axis):
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    inter = IntCurvesFace_ShapeIntersector()
    inter.Load(shape, 1e-6)
    p = np.asarray(hit, float) + _unit(axis) * 1e-4
    inter.Perform(gp_Lin(gp_Pnt(*map(float, p)), gp_Dir(*map(float, _unit(axis)))), 1e-6, 1e9)
    if not inter.IsDone() or inter.NbPnt() == 0:
        return None
    return float(min(inter.WParameter(i) for i in range(1, inter.NbPnt() + 1)))


def _placed(shape, origin, frame):
    import cadquery as cq
    x, y, z = frame
    return kernel.transformed(cq.Shape.cast(shape), np.column_stack([x, y, z]), np.asarray(origin, float)).wrapped


def _cyl(r, z0, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    if r <= 1e-6 or z1 - z0 <= 1e-6:
        raise kernel.CadError('Wymiar mocowania musi być większy od zera.')
    mk = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, z0), gp_Dir(0, 0, 1)), float(r), float(z1 - z0))
    mk.Build()
    return mk.Shape()


def _box(x0, y0, z0, x1, y1, z1):
    from .enclosure import _make_box
    if min(x1 - x0, y1 - y0, z1 - z0) <= 1e-6:
        raise kernel.CadError('Wymiar mocowania musi być większy od zera.')
    return _make_box((x0, y0, z0), (x1, y1, z1))


def _cone(r0, r1, z0, z1):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCone
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    mk = BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(0, 0, z0), gp_Dir(0, 0, 1)), float(r0), float(r1), float(z1 - z0))
    mk.Build()
    return mk.Shape()


def _hex(af, z0, z1):
    """Sześciokątne gniazdo nakrętki (rozwartość af) - graniastosłup z profilu."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Pnt, gp_Vec
    R = af / math.sqrt(3)
    poly = BRepBuilderAPI_MakePolygon()
    for k in range(6):
        a = math.pi / 6 + k * math.pi / 3
        poly.Add(gp_Pnt(R * math.cos(a), R * math.sin(a), z0))
    poly.Close()
    face = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, z1 - z0)).Shape()


def _rib(angle, r_in, length, thick, z0, height):
    """Żebro wzmacniające: klin (BRepPrimAPI_MakeWedge) - przy słupku wysokość height, na końcu zero."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeWedge
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    c, s = math.cos(angle), math.sin(angle)
    # układ klina: X - od słupka na zewnątrz, Y - w górę (oś słupka), Z - grubość żebra (N = (s, -c, 0) daje Y = +z)
    ax = gp_Ax2(gp_Pnt(c * (r_in - .3) - s * thick / 2, s * (r_in - .3) + c * thick / 2, z0), gp_Dir(s, -c, 0), gp_Dir(c, s, 0))
    mk = BRepPrimAPI_MakeWedge(ax, float(length + .3), float(height), float(thick), 0.0)
    mk.Build()
    return mk.Shape()


def build_post(mount, defaults, shape, up=(0, 0, 1.0)):
    """Bryła mocowania (bez otworów) i narzędzia tnące dla jednego punktu: dict(solid, cuts, hit, height, embed, frame,
    origin, part_cut_through). shape - bryła części obudowy, w której ścianka jest trafiana."""
    from .enclosure import _boolean
    p = params(defaults, mount)
    c = np.asarray(mount['center'], float)
    axis = _unit(mount['axis'])
    hit = wall_hit(shape, c, axis)
    if hit is None:
        raise kernel.CadError(f'Punkt {mount.get("source_name", "")}: w kierunku mocowania nie ma ścianki obudowy - zmień kierunek.')
    w, dist = hit
    thick = _wall_thickness(shape, w, axis)
    embed = min(max(float(p['embed']) * thick, .2), .9 * thick)
    auto = dist
    height = float(p['height']) if float(p['height']) > 0 else auto
    if height <= 1e-3:
        raise kernel.CadError('Element leży na ściance - mocowanie nie ma wysokości.')
    frame = _frame(axis)
    if p['type'] == 'guide':                      # prowadnica: rowek w poprzek grubości elementu (kierunek „góra” obudowy)
        zz = frame[2]
        t = np.asarray(up, float) - float(np.asarray(up, float) @ zz) * zz
        if np.linalg.norm(t) < 1e-6:
            t = frame[0]
        t = _unit(t)
        frame = (t, np.cross(zz, t), zz)
    origin = w                                     # z' = 0 na wewnętrznej powierzchni ścianki, w górę do elementu
    kind = p['type']
    d = float(p['diameter'])
    hole_d = hole_diameter(p) if kind not in ('support', 'snap', 'guide') else 0.0
    if kind in ('cylinder', 'ribbed', 'cone', 'snap') and d <= hole_d + .8:
        raise kernel.CadError(f'Średnica słupka {d:g} mm jest za mała dla otworu Ø{hole_d:.2f} mm (ścianka co najmniej 0,4 mm).')
    z0, z1 = -embed, height
    cuts = []
    if kind in ('cylinder', 'ribbed', 'support', 'snap'):
        solid = _cyl(d / 2, z0, z1)
        if kind == 'ribbed':
            n = max(2, min(8, int(p['ribs'])))
            for k in range(n):
                solid = _boolean('fuse', solid, _rib(2 * math.pi * k / n + math.pi / 4, d / 2, max(1.0, .6 * d), float(p['rib']), z0,
                                                     embed + .7 * height), 'żebro')
    elif kind == 'rect':
        a = float(p['width']) / 2
        if a * 2 <= hole_d + .8:
            raise kernel.CadError('Słupek prostokątny za wąski dla otworu.')
        solid = _box(-a, -a, z0, a, a, z1)
    elif kind == 'cone':
        top = float(p['top_diameter'])
        if top <= hole_d + .8 or top > d + 1e-9:
            raise kernel.CadError('Średnica górna słupka stożkowego musi być mniejsza od dolnej i większa od otworu.')
        solid = _boolean('fuse', _cyl(d / 2, z0, 0.0 + 1e-3), _cone(d / 2, top / 2, 0.0, z1), 'słupek stożkowy')
    elif kind == 'guide':
        L, g, depth = float(p['length']), float(p['groove']) + float(p['gap']), max(float(p['hole_depth']) or 2.0, .5)
        wide = g + 2 * max(1.2, float(p['rib']))
        if L <= 0 or g <= 0:
            raise kernel.CadError('Prowadnica: długość i szerokość rowka muszą być większe od zera.')
        solid = _boolean('cut', _box(-wide / 2, -L / 2, z0, wide / 2, L / 2, z1 + depth),
                         _box(-g / 2, -L / 2 - 1, z1 - float(p['gap']), g / 2, L / 2 + 1, z1 + depth + 1), 'rowek prowadnicy')
    else:
        raise kernel.CadError('Nieznany rodzaj mocowania.')
    if kind == 'snap':                            # kołek z rozciętym trzpieniem i zaczepem (stożek najazdowy) nad elementem
        s = screw(p['screw'])
        pin = max(.6, float(mount['diameter']) - float(p['gap']))
        through = max(float(mount.get('depth') or 0.0), 1.0)
        lip = min(.45, .25 * pin)
        pin_solid = _boolean('fuse', _cyl(pin / 2, z1 - .001, z1 + through), _cone(pin / 2 + lip, pin / 2 * .55, z1 + through, z1 + through + 1.2 * pin),
                             'kołek zatrzaskowy')
        pin_solid = _boolean('cut', pin_solid, _box(-max(.35, .18 * pin), -pin, z1 + .5 * through, max(.35, .18 * pin), pin, z1 + through + 2 * pin),
                             'rozcięcie kołka')
        solid = _boolean('fuse', solid, pin_solid, 'słupek z kołkiem')
        del s
    world = _placed(solid, origin, frame)
    f = p['fastening']
    if kind in ('cylinder', 'rect', 'cone', 'ribbed') and hole_d > 0:
        s = screw(p['screw'])
        depth = float(p['hole_depth']) if float(p['hole_depth']) > 0 else (height if f in ('clearance', 'nut') else min(height, max(6.0, 2.5 * s['d'])))
        if f == 'insert':
            depth = float(p['hole_depth']) if float(p['hole_depth']) > 0 else min(height, s['insert_len'] + 1.0)
        if depth > height + 1e-6 and f not in ('clearance', 'nut'):
            raise kernel.CadError(f'Głębokość otworu {depth:g} mm większa niż wysokość słupka {height:.2f} mm.')
        if f in ('clearance', 'nut'):
            cuts.append(('part', _placed(_cyl(hole_d / 2, -thick - 1.0, height + .5), origin, frame)))   # przez słupek i ściankę
            if f == 'nut':
                nh = s['nut_h'] + float(p['gap'])
                if nh >= thick + height - .4:
                    raise kernel.CadError('Słupek z gniazdem nakrętki jest za niski.')
                cuts.append(('part', _placed(_hex(s['nut_af'] + 2 * float(p['gap']), -thick - 1.0, -thick + nh), origin, frame)))
        else:
            cuts.append(('part', _placed(_cyl(hole_d / 2, height - depth, height + .5), origin, frame)))
    return dict(solid=world, cuts=cuts, hit=w, height=height, auto_height=auto, embed=embed, thickness=thick, frame=frame,
                origin=origin, params=p, hole=hole_d, axis=axis)


def collisions(post, mount, bodies, sources):
    """Elementy, w które wchodzi mocowanie (Common o objętości > tolerancji; sam styk z powierzchnią elementu dozwolony)."""
    from .enclosure import _boolean, _volume
    import cadquery as cq
    by_id = {b.id: b for b in bodies}
    sh = cq.Shape.cast(post['solid'])
    bb = sh.BoundingBox()
    hits = []
    for src in sources:
        body = by_id.get(src.id)
        if body is None or body.kind != 'solid':
            continue
        b2 = body.shape.BoundingBox()
        if (b2.xmax < bb.xmin or b2.xmin > bb.xmax or b2.ymax < bb.ymin or b2.ymin > bb.ymax or b2.zmax < bb.zmin or b2.zmin > bb.zmax):
            continue
        vol = _volume(_boolean('common', post['solid'], body.shape.wrapped, 'kolizja mocowania'))[0]
        if vol > 1e-4:
            hits.append(body.name)
    return hits


def apply(env, spec, parts, bodies, check=True):
    """Mocowania dołączone do części obudowy (dict nazwa -> bryła cq). Słupek trafia do części, której ściankę trafia
    promień mocowania; po Fuse część musi zostać jedną poprawną bryłą. Zwraca (nowe części, gwinty kosmetyczne na część, opisy mocowań)."""
    from .enclosure import _boolean, _single, check_solid, _unified
    import cadquery as cq
    defaults = dict(DEFAULTS, **(spec.posts or {}))
    if not defaults.get('enabled', True):
        return parts, {}, []
    mounts = [m for m in spec.mounts or [] if (m.get('post') or {}).get('type', defaults['type']) != 'none']
    if not mounts:
        return parts, {}, []
    shapes = {k: v.wrapped for k, v in parts.items()}
    built, threads_out = [], {k: [] for k in parts}
    for m in mounts:
        best = None
        for name, sh in shapes.items():
            hit = wall_hit(sh, m['center'], m['axis'])
            if hit is not None and (best is None or hit[1] < best[1]):
                best = (hit[1], name)
        if best is None:
            raise kernel.CadError(f'Punkt montażowy ({m.get("source_name", "")}): w kierunku mocowania nie ma ścianki obudowy.')
        name = best[1]
        post = build_post(m, defaults, shapes[name], up=np.asarray(env.axes, float)[2])
        if check:
            hits = collisions(post, m, bodies, spec.sources)
            if hits:
                raise kernel.CadError(f'Mocowanie przy {m.get("source_name", "")} koliduje z: {", ".join(hits)}.')
        post['part'] = name
        post['mount'] = m
        built.append(post)
        shapes[name] = _boolean('fuse', shapes[name], post['solid'], 'słupek z obudową')
    for post in built:
        for _kind, tool in post['cuts']:
            shapes[post['part']] = _boolean('cut', shapes[post['part']], tool, 'otwór mocowania')
    out = {}
    for name, sh in shapes.items():
        solid = _single(_unified(sh), 'Obudowa z mocowaniami' if name == 'body' else ('Podstawa' if name == 'base' else 'Pokrywa'))
        out[name] = check_solid(solid)
    for post in built:                              # opcjonalny gwint kosmetyczny (istniejący mechanizm gwintów RCCAD)
        p = post['params']
        if p['fastening'] == 'tapped' and p.get('thread') and post['params']['type'] in ('cylinder', 'rect', 'cone', 'ribbed'):
            from . import threads
            s = screw(p['screw'])
            info = threads.find_cylinder(out[post['part']], post['origin'] + post['frame'][2] * post['height'], post['frame'][2], post['hole'] / 2, tol=1e-3)
            if info is not None:
                threads_out[post['part']].append(threads.make_thread(info, 'M', p['screw'], 'right', info['t0'], info['t1']))
            del s
    info = [dict(id=p['mount'].get('id'), part=p['part'], height=p['height'], auto_height=p['auto_height'], hole=p['hole'],
                 type=p['params']['type'], fastening=p['params']['fastening']) for p in built]
    return out, threads_out, info
