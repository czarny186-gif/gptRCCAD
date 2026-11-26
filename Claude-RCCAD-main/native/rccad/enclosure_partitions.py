"""Generator obudów - etap 18: przegrody wewnętrzne.

Przegroda w jednej części obudowy. Położenie: płaszczyzna prostopadła do osi obudowy (X / Y / Z) w odległości od ścianki
wnętrza, płaszczyzna równoległa do wskazanej ściany (z odsunięciem), linia przez dwa punkty (przegroda pionowa / ukośna),
łuk (przegroda zakrzywiona: promień), szkic (krzywe szkicu wyciągnięte), odległość od krawędzi. Rodzaje: pełna,
częściowa (wysokość, odstęp od dna i od pokrywy), perforowana (otwory z generatora wentylacji), wyjmowana i wsuwana
(osobna bryła + prowadnice z rowkami i ogranicznikiem, opcjonalny zatrzask), pozioma, pionowa, ukośna (kąt), zakrzywiona,
półka wewnętrzna (płyta na listwach), kanał kablowy (ścianki + dno w kształcie U), kanał przepływu powietrza (dwie
równoległe ścianki), według szkicu.

Geometria: płyta grubości t w płaszczyźnie przegrody (BRepPrimAPI_MakePrism), ograniczona do wnętrza części
(BRepAlgoAPI_Common z wnętrzem obudowy z danych generatora - przegroda dopasowuje się do kształtu wnętrza; integralna -
wnętrze powiększone o wpuszczenie w ściankę), odstępy od dna / pokrywy i wysokość - część wspólna z warstwą, przepusty
(BRepAlgoAPI_Cut): otwory okrągłe, prostokątne, szczeliny, przepusty kablowe (otwarte od góry), wentylacja, wycięcia
dopasowane do komponentów (ramka + odstęp). Integralna - BRepAlgoAPI_Fuse z częścią (jedna bryła). Wyjmowana - osobna bryła
pomniejszona o luz, prowadnice połączone z częścią; sprawdzane wkładanie i wyjmowanie na całej drodze ruchu.
Kontrole: kolizje z komponentami (z odstępem), mocowaniami, żebrami i pokrywą. Przegroda nie jest certyfikowaną izolacją
elektryczną, termiczną ani przeciwpożarową."""
from __future__ import annotations

import math

import numpy as np

from . import kernel

KINDS = ('full', 'partial', 'perforated', 'removable', 'sliding', 'horizontal', 'vertical', 'inclined', 'curved', 'shelf', 'cable', 'air', 'sketch')
KIND_LABELS = {'full': 'Przegroda pełna', 'partial': 'Przegroda częściowa', 'perforated': 'Przegroda perforowana', 'removable': 'Przegroda wyjmowana',
               'sliding': 'Przegroda wsuwana', 'horizontal': 'Przegroda pozioma', 'vertical': 'Przegroda pionowa', 'inclined': 'Przegroda ukośna',
               'curved': 'Przegroda zakrzywiona', 'shelf': 'Półka wewnętrzna', 'cable': 'Kanał kablowy', 'air': 'Kanał przepływu powietrza',
               'sketch': 'Według szkicu'}
PLACES = ('axis', 'face', 'points', 'sketch')
PLACE_LABELS = {'axis': 'Płaszczyzna osi obudowy (odległość od ścianki)', 'face': 'Równolegle do wskazanej ściany', 'points': 'Przez dwa punkty',
                'sketch': 'Według szkicu'}
PASSES = ('none', 'round', 'rect', 'slot', 'cable', 'vent', 'fit')
PASS_LABELS = {'none': 'Bez przepustów', 'round': 'Otwór okrągły', 'rect': 'Otwór prostokątny', 'slot': 'Szczelina', 'cable': 'Przepust kablowy (od góry)',
               'vent': 'Otwory wentylacyjne', 'fit': 'Wycięcia dopasowane do komponentów'}
DEFAULTS = dict(kind='full', place='axis', axis='x', offset=30.0, percent=0.0, thickness=2.0, height=0.0, length=0.0, angle=0.0, radius=60.0,
                gap_bottom=0.0, gap_top=.5, clearance=.3, corner=0.0, embed=.3, comp_gap=1.0, pass_kind='none', pass_w=10.0, pass_h=6.0,
                pass_u=0.0, pass_v=0.0, guide_w=2.0, guide_d=1.2, guide_h=0.0, snap=False, width=12.0, wall_h=8.0, chambers=0, sizes=[],
                p1=None, p2=None, face=None, sketch=None, auto=True, vent=dict(pattern='hex', size=3.0, web=1.2))
NO_CERT = 'Przegroda nie jest certyfikowaną izolacją elektryczną, termiczną ani przeciwpożarową.'


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _world(env):
    c = np.asarray(env.center, float)
    ax = np.asarray(env.axes, float)
    return lambda p: c + ax.T @ np.asarray(p, float), ax, c


def plane_of(p, env, lay, bodies=None, target=None):
    """Płaszczyzna przegrody (świat): (punkt, normalna, oś „w górę” w płaszczyźnie)."""
    W, ax, c = _world(env)
    lo, hi = (np.asarray(x, float) for x in lay['inner'])
    place = p['place']
    up = ax[2]
    if place == 'axis':
        i = 'xyz'.index(p['axis'])
        span = hi[i] - lo[i]
        pos = lo[i] + (span * float(p['percent']) / 100.0 if float(p['percent']) > 0 else float(p['offset']))
        if not (lo[i] < pos < hi[i]):
            raise kernel.CadError('Przegroda leży poza wnętrzem obudowy - zmień odległość od ścianki.')
        pt = np.zeros(3)
        pt[i] = pos
        n = ax[i]
        if i == 2:
            up = ax[1]
        if float(p['angle']):                                   # przegroda ukośna: obrót wokół osi „w górę”
            a = math.radians(float(p['angle']))
            k = up
            K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
            R = np.eye(3) + math.sin(a) * K + (1 - math.cos(a)) * K @ K
            n = R @ n
        return W(pt), _unit(n), up
    if place == 'face':
        f = p.get('face') or {}
        if not f:
            raise kernel.CadError('Wskaż ścianę, do której przegroda ma być równoległa.')
        n = _unit(f['normal'])
        pt = np.asarray(f['point'], float) - n * float(p['offset'])       # w głąb od ściany
        up = ax[2] if abs(float(ax[2] @ n)) < .9 else ax[1]
        return pt, n, up
    if place == 'points':
        a, b = p.get('p1'), p.get('p2')
        if a is None or b is None:
            raise kernel.CadError('Wskaż dwa punkty, przez które ma przechodzić przegroda.')
        a, b = np.asarray(a, float), np.asarray(b, float)
        d = b - a
        d = d - float(d @ up) * up
        if np.linalg.norm(d) < 1e-6:
            raise kernel.CadError('Punkty przegrody pokrywają się w rzucie - wskaż dwa różne punkty.')
        n = _unit(np.cross(d, up))
        return (a + b) / 2, n, up
    raise kernel.CadError('Nieznany sposób położenia przegrody.')


def _slab(pt, n, up, t, size, z0=None, z1=None):
    """Płyta grubości t symetrycznie wokół płaszczyzny (duża w bok); z0 / z1 - zakres wzdłuż „w górę” od punktu."""
    import cadquery as cq
    from .enclosure import _make_box
    side = _unit(np.cross(up, n))
    lo = (-size, -size if z0 is None else z0, -t / 2)
    hi = (size, size if z1 is None else z1, t / 2)
    return kernel.transformed(cq.Shape.cast(_make_box(lo, hi)), np.column_stack([side, up, n]), np.asarray(pt, float)).wrapped


def _curved(pt, n, up, t, R, size):
    """Przegroda zakrzywiona: wycinek powłoki walcowej (oś ∥ „w górę”, promień R, wypukłość w stronę +n)."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from .enclosure import _boolean
    if R <= t:
        raise kernel.CadError('Promień przegrody zakrzywionej musi być większy niż jej grubość.')
    centre = np.asarray(pt, float) - n * R - up * size
    outer = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*map(float, centre)), gp_Dir(*map(float, up))), R + t / 2, 2 * size).Shape()
    inner = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*map(float, centre)), gp_Dir(*map(float, up))), R - t / 2, 2 * size).Shape()
    shell = _boolean('cut', outer, inner, 'przegroda zakrzywiona')
    from .enclosure import _make_box
    import cadquery as cq
    side = _unit(np.cross(up, n))
    box = kernel.transformed(cq.Shape.cast(_make_box((-size, -size, 0.0), (size, size, R + t))), np.column_stack([side, up, n]),
                             np.asarray(pt, float) - n * R).wrapped
    return _boolean('common', shell, box, 'przegroda zakrzywiona')


def build_many(part, spec, env, lay, p, components=(), others=(), sketch_shape=None, comp_ids=()):
    """Przegrody dzielące wnętrze na komory (lista odległości `offsets`) albo jedna przegroda; przypisanie komponentów
    do komór (`assign`: id -> numer komory od 1) sprawdzane - komponent musi leżeć w całości w swojej komorze."""
    import cadquery as cq
    p = dict(DEFAULTS, **p)
    offsets = [float(x) for x in (p.get('offsets') or [])]
    assign = {str(k_): int(v) for k_, v in (p.get('assign') or {}).items()}
    if assign and p['place'] == 'axis':
        i = 'xyz'.index(p['axis'])
        lo = np.asarray(lay['inner'][0], float)
        cuts = sorted(offsets or [float(p['offset'])])
        ax = np.asarray(env.axes, float)
        c = np.asarray(env.center, float)
        for cid, comp in zip(comp_ids, components):
            if cid not in assign:
                continue
            bb = cq.Shape.cast(comp).BoundingBox()
            pts = np.array([[x, y, z] for x in (bb.xmin, bb.xmax) for y in (bb.ymin, bb.ymax) for z in (bb.zmin, bb.zmax)])
            d = (pts - c) @ ax[i] - lo[i]
            ch = {1 + sum(1 for q in cuts if q < v) for v in (d.min() + 1e-6, d.max() - 1e-6)}
            if ch != {assign[cid]}:
                raise kernel.CadError(f'Komponent nie leży w przypisanej komorze {assign[cid]} - przesuń przegrody '
                                      '(program nie przesuwa komponentów).')
    if not offsets:
        return build(part, spec, env, lay, p, components, others, sketch_shape)
    current, separate, report = part, [], []
    for off in offsets:
        res = build(current, spec, env, lay, dict(p, offset=off, percent=0.0), components, others, sketch_shape)
        current = res['part']
        separate += res['separate']
        report = res['report']
    return dict(part=current, separate=separate, report=report + [('ok', f'Komory: {len(offsets) + 1}')])


def build(part, spec, env, lay, p, components=(), others=(), sketch_shape=None):
    """Przegroda w części obudowy: dict(part, separate=[...], info, report)."""
    import cadquery as cq
    from .enclosure import _boolean, _single, _unified, _volume, check_solid, _solids
    from .enclosure_ribs import _multi
    from . import enclosure_shapes as shapes
    p = dict(DEFAULTS, **p)
    kind = p['kind']
    if kind not in KINDS:
        raise kernel.CadError('Nieznany rodzaj przegrody.')
    t = float(p['thickness'])
    if t <= 0:
        raise kernel.CadError('Grubość przegrody musi być większa od zera.')
    target = part.wrapped if hasattr(part, 'wrapped') else part
    W, ax, c = _world(env)
    size = 2.0 * float(np.linalg.norm(lay['outer_size'])) + 10.0
    e = float(p['embed'])
    removable = kind in ('removable', 'sliding')
    # wnętrze części (świat), powiększone o wpuszczenie (integralna) albo pomniejszone o luz (wyjmowana)
    if 'g_in' in lay:
        mk = lambda d: kernel.transformed(cq.Shape.cast(shapes.solid(shapes.grow(lay['g_in'], d), lay['P'])), ax.T, c).wrapped
    else:
        from .enclosure import _make_box
        lo, hi = (np.asarray(x, float) for x in lay['inner'])
        mk = lambda d: kernel.transformed(cq.Shape.cast(_make_box(lo - d, hi + d)), ax.T, c).wrapped
    room = mk(-float(p['clearance']) if removable else e)
    room = _boolean('common', room, _part_zone(target, size), 'wnętrze części')
    if kind == 'horizontal' or kind == 'shelf':
        p = dict(p, place='axis', axis='z', angle=0.0)
    if kind == 'vertical' and p['place'] == 'axis' and p['axis'] == 'z':
        p = dict(p, axis='x')
    pt, n, up = plane_of(p, env, lay)
    if kind == 'inclined' and not float(p['angle']):
        p = dict(p, angle=30.0)
        pt, n, up = plane_of(p, env, lay)
    # zakres pionowy: odstęp od dna i od pokrywy, wysokość (0 = do pokrywy)
    span_lo, span_hi = _span(target, up, pt, room)
    z0 = span_lo + float(p['gap_bottom'])
    z1 = span_hi - float(p['gap_top']) if not (removable) else span_hi + 1.0
    if float(p['height']) > 0:
        z1 = min(z1, z0 + float(p['height']))
    if kind == 'partial' and float(p['height']) <= 0:
        z1 = z0 + (z1 - z0) * .6
    if z1 - z0 <= 1e-3 and kind not in ('horizontal', 'shelf'):
        raise kernel.CadError('Przegroda nie ma wysokości - zmniejsz odstępy od dna i pokrywy.')
    if kind == 'curved':
        plate = _curved(pt, n, up, t, float(p['radius']), size)
    elif kind == 'sketch':
        if sketch_shape is None:
            raise kernel.CadError('Wskaż szkic z linią przegrody.')
        plate = _sketch_wall(sketch_shape, up, t, size)
    elif kind == 'cable':
        plate = _channel(pt, n, up, t, float(p['width']), float(p['wall_h']), size, z0, closed=False)
    elif kind == 'air':
        plate = _channel(pt, n, up, t, float(p['width']), 0.0, size, z0, closed=True)
    elif kind == 'shelf':
        plate = _slab(pt, n, up, t, size)
    else:
        plate = _slab(pt, n, up, t, size)
    if kind not in ('horizontal', 'shelf'):
        zone = _between(pt, up, z0, z1, size)
        plate = _boolean('common', plate, zone, 'wysokość przegrody')
    if float(p['length']) > 0 and kind not in ('horizontal', 'shelf'):
        side = _unit(np.cross(up, n))
        plate = _boolean('common', plate, _between(pt, side, -float(p['length']) / 2, float(p['length']) / 2, size), 'długość przegrody')
    plate = _boolean('common', plate, room, 'dopasowanie do wnętrza')
    if _volume(plate)[0] <= 1e-6:
        raise kernel.CadError('Przegroda nie leży we wnętrzu tej części obudowy - zmień położenie.')
    # przepusty
    tools = _passes(p, pt, n, up, t, z0, z1, size, components)
    if tools:
        plate = _multi('cut', plate, tools, 'przepusty przegrody')
    report = [('info', NO_CERT)]
    # kolizje z komponentami (z odstępem) - bez cichego przesuwania komponentów
    gap = float(p['comp_gap'])
    for comp in components:
        bb = cq.Shape.cast(comp).BoundingBox()
        from .enclosure import _make_box
        zone_c = _make_box((bb.xmin - gap, bb.ymin - gap, bb.zmin - gap), (bb.xmax + gap, bb.ymax + gap, bb.zmax + gap))
        if _volume(_boolean('common', plate, zone_c if gap > 0 else comp, 'przegroda a komponent'))[0] > 1e-4:
            raise kernel.CadError('Przegroda koliduje z komponentem (z wymaganym odstępem) - przesuń ją, zmniejsz albo dodaj wycięcia '
                                  'dopasowane do komponentów.')
    for o_ in others:
        if _volume(_boolean('common', plate, o_, 'przegroda a pokrywa'))[0] > 1e-3:
            raise kernel.CadError('Przegroda koliduje z pokrywą / inną częścią - zwiększ odstęp od pokrywy.')
    separate = []
    if removable:
        pieces = [s for s in _solids(plate) if _volume(s)[0] > 1e-6]
        if len(pieces) != 1:
            raise kernel.CadError('Przegroda wyjmowana rozpada się na części - zmień przepusty.')
        insert = check_solid(pieces[0])
        guides = _guides(insert.wrapped, pt, n, up, p, target, mk, size, z0)
        new_part = _multi('fuse', target, guides, 'prowadnice przegrody') if guides else target
        shape = check_solid(_single(_unified(new_part), 'Obudowa z prowadnicami'))
        if _volume(_boolean('common', insert.wrapped, shape.wrapped, 'przegroda a prowadnice'))[0] > 1e-3:
            raise kernel.CadError('Przegroda wyjmowana nachodzi na prowadnice - zwiększ luz.')
        from .enclosure_check import sweep
        moved = lambda u, s0=cq.Shape.cast(insert.wrapped): s0.translate(cq.Vector(*(up * u))).wrapped
        hit = sweep(shape.wrapped, moved, float(span_hi - z0) + 2.0, 1.0, lambda u: f'{u:.1f}', lambda u: (np.eye(3), up * u))
        if hit:
            raise kernel.CadError(f'Przegrody nie da się wyjąć - koliduje po {hit[0]} mm (zwiększ luz albo zmień prowadnice).')
        report.append(('ok', 'Wkładanie i wyjmowanie przegrody sprawdzone na całej drodze ruchu.'))
        separate.append(insert)
    else:
        shape = check_solid(_single(_unified(_boolean('fuse', target, plate, 'przegroda z obudową')), 'Obudowa z przegrodą'))
        added = _volume(shape.wrapped)[0] - _volume(target)[0]
        if added <= 1e-6:
            raise kernel.CadError('Przegroda nie dodała materiału (leży w ściance?) - zmień położenie.')
    return dict(part=shape, separate=separate, report=report, plane=(pt, n, up), span=(z0, z1))


class _BB:
    def __init__(self, x0, y0, z0, x1, y1, z1):
        self.xmin, self.ymin, self.zmin, self.xmax, self.ymax, self.zmax = x0, y0, z0, x1, y1, z1


def _tight(shape):
    """Dokładna ramka bryły (BRepBndLib.AddOptimal, bez powiększenia o tolerancje)."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped if hasattr(shape, 'wrapped') else shape, box, False, False)
    return _BB(*box.Get())


def _part_zone(target, size):
    """Obszar części: ramka bryły części (przegroda w podstawie nie wchodzi nad podział)."""
    import cadquery as cq
    from .enclosure import _make_box
    bb = _tight(target)
    return _make_box((bb.xmin, bb.ymin, bb.zmin), (bb.xmax, bb.ymax, bb.zmax))


def _span(target, up, pt, room):
    """Zakres wnętrza części wzdłuż „w górę” (od punktu płaszczyzny)."""
    import cadquery as cq
    pts = np.array([v.toTuple() for v in cq.Shape.cast(room).Vertices()])
    if not len(pts):
        bb = cq.Shape.cast(room).BoundingBox()
        pts = np.array([[bb.xmin, bb.ymin, bb.zmin], [bb.xmax, bb.ymax, bb.zmax]])
    d = (pts - pt) @ up
    return float(d.min()), float(d.max())


def _between(pt, d, a, b, size):
    """Warstwa między płaszczyznami pt + d·a i pt + d·b."""
    import cadquery as cq
    from .enclosure import _make_box
    d = _unit(d)
    x = _unit(np.cross(d, [0, 0, 1.0] if abs(d[2]) < .9 else [1.0, 0, 0]))
    y = np.cross(d, x)
    return kernel.transformed(cq.Shape.cast(_make_box((-size, -size, a), (size, size, b))), np.column_stack([x, y, d]), np.asarray(pt, float)).wrapped


def _channel(pt, n, up, t, width, wall_h, size, z0, closed):
    """Kanał: kablowy - dno + dwie ścianki (U) od dna wnętrza; powietrza - dwie równoległe ścianki na pełną wysokość."""
    from .enclosure import _boolean
    from .enclosure_ribs import _multi
    a = _slab(np.asarray(pt, float) - n * (width / 2 + t / 2), n, up, t, size)
    b = _slab(np.asarray(pt, float) + n * (width / 2 + t / 2), n, up, t, size)
    if closed:
        return _multi('fuse', a, [b], 'kanał powietrza')
    walls = _multi('fuse', a, [b], 'kanał kablowy')
    walls = _boolean('common', walls, _between(pt, up, z0, z0 + wall_h + t, size), 'wysokość kanału')
    floor = _boolean('common', _slab(pt, n, up, width + 2 * t, size), _between(pt, up, z0, z0 + t, size), 'dno kanału')
    return _multi('fuse', walls, [floor], 'kanał kablowy')


def _sketch_wall(sketch_shape, up, t, size):
    """Przegroda wzdłuż krzywych szkicu: każda krawędź z płytą grubości t (wyciągnięcie wzdłuż „w górę”)."""
    import cadquery as cq
    from .enclosure_ribs import _multi
    pieces = []
    for edge in cq.Shape.cast(sketch_shape).Edges():
        pts = [np.asarray(edge.positionAt(s).toTuple(), float) for s in np.linspace(0, 1, 2 if edge.geomType() == 'LINE' else 13)]
        for a, b in zip(pts[:-1], pts[1:]):
            d = b - a
            d = d - float(d @ up) * up
            if np.linalg.norm(d) < 1e-6:
                continue
            n = _unit(np.cross(d, up))
            L = float(np.linalg.norm(d))
            side = _unit(d)
            from .enclosure import _make_box
            box = kernel.transformed(cq.Shape.cast(_make_box((-.5 * t, -size, -t / 2), (L + .5 * t, size, t / 2))),
                                     np.column_stack([side, up, n]), a - float(a @ up) * up).wrapped
            pieces.append(box)
    if not pieces:
        raise kernel.CadError('Szkic nie ma linii przegrody.')
    return pieces[0] if len(pieces) == 1 else _multi('fuse', pieces[0], pieces[1:], 'przegroda ze szkicu')


def _passes(p, pt, n, up, t, z0, z1, size, components):
    """Narzędzia przepustów w przegrodzie (świat)."""
    import cadquery as cq
    from . import enclosure_holes as eh
    kind = p['pass_kind']
    if kind == 'none':
        return []
    side = _unit(np.cross(up, n))
    centre = np.asarray(pt, float) + up * ((z0 + z1) / 2 + float(p['pass_v'])) + side * float(p['pass_u'])
    fr = (centre, side, up, n)
    w, h = float(p['pass_w']), float(p['pass_h'])
    through = lambda face: eh._prism(face, fr, t + 1, -t - 1)
    if kind == 'round':
        return [through(eh._circle_face(0, 0, w / 2, fr))]
    if kind == 'rect':
        return [through(eh._plane_face([(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)], fr))]
    if kind == 'slot':
        return [through(eh._fillet2d(eh._plane_face([(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)], fr), min(w, h) / 2 - 1e-3))]
    if kind == 'cable':                                     # otwarty od góry: szczelina od górnej krawędzi
        top = (z1 - (z0 + z1) / 2 - float(p['pass_v'])) + 1.0
        return [through(eh._plane_face([(-w / 2, top - h), (w / 2, top - h), (w / 2, top), (-w / 2, top)], fr))]
    if kind == 'vent':
        from . import enclosure_vents as ev
        vp = dict(ev.DEFAULTS, **(p.get('vent') or {}), cu=0.0, cv=0.0, width=w, height=h)
        holes, _a = ev.layout(vp)
        tools = [through(ev.hole_face(hh, fr)) for hh in holes if hh[4] == 'vent']
        if not tools:
            raise kernel.CadError('Otwory wentylacyjne nie mieszczą się w obszarze przepustu - powiększ obszar albo zmniejsz otwory.')
        return tools
    if kind == 'fit':                                       # wycięcia dopasowane do komponentów (ramka + odstęp)
        from .enclosure import _make_box
        g = float(p['comp_gap'])
        out = []
        for comp in components:
            bb = cq.Shape.cast(comp).BoundingBox()
            out.append(_make_box((bb.xmin - g, bb.ymin - g, bb.zmin - g), (bb.xmax + g, bb.ymax + g, bb.zmax + g)))
        return out
    raise kernel.CadError('Nieznany rodzaj przepustu.')


def _guides(insert, pt, n, up, p, target, mk, size, z0):
    """Prowadnice przegrody wyjmowanej: na każdej ściance, którą przegroda przecina - para listew po obu stronach przegrody
    (rowek = grubość + 2 × luz), od dna do góry przegrody; opcjonalny zatrzask - mały występ na listwie."""
    import cadquery as cq
    from .enclosure import _boolean, _volume
    gw, gd = float(p['guide_w']), float(p['guide_d'])
    t, g = float(p['thickness']), float(p['clearance'])
    rails = []
    for sgn in (-1, 1):
        offset = sgn * (t / 2 + g + gw / 2)
        rail = _slab(np.asarray(pt, float) + n * offset, n, up, gw, size)
        # listwa tylko przy ściankach: wnętrze powiększone o wpuszczenie minus wnętrze pomniejszone o głębokość prowadnicy
        band = _boolean('cut', mk(float(p['embed'])), mk(-gd - g), 'pas prowadnic')
        rail = _boolean('common', rail, band, 'prowadnica')
        bb = _tight(insert)
        top = max(np.asarray([bb.xmax, bb.ymax, bb.zmax]) @ up, np.asarray([bb.xmin, bb.ymin, bb.zmin]) @ up)
        rail = _boolean('common', rail, _between(np.zeros(3), up, -1e4, float(top), size), 'wysokość prowadnicy')
        if _volume(rail)[0] > 1e-6:
            rails.append(rail)
    if not rails:
        raise kernel.CadError('Nie ma ścianek na prowadnice przegrody wyjmowanej.')
    return rails


def chamber_positions(p, lo, hi, components_bbox=None):
    """Położenia przegród dzielących wnętrze na komory wzdłuż osi (odległości od ścianki wnętrza): liczba komór (równe),
    zadane wymiary komór [mm] albo udziały [%]; propozycja według komponentów - środki przerw między ich ramkami."""
    i = 'xyz'.index(p['axis'])
    span = float(hi[i] - lo[i])
    sizes = [float(x) for x in (p.get('sizes') or [])]
    if p.get('mode') == 'components' and components_bbox:
        boxes = sorted(components_bbox, key=lambda b: b[0][i])
        out = []
        for a, b in zip(boxes[:-1], boxes[1:]):
            gap0, gap1 = a[1][i], b[0][i]
            if gap1 - gap0 > float(p['thickness']) + 2 * float(p.get('comp_gap', 1.0)):
                out.append((gap0 + gap1) / 2 - lo[i])
        return out
    if sizes and p.get('mode') == 'percent':
        if abs(sum(sizes) - 100.0) > 1e-6:
            raise kernel.CadError('Udziały komór muszą sumować się do 100 %.')
        acc, out = 0.0, []
        for s in sizes[:-1]:
            acc += s
            out.append(span * acc / 100.0)
        return out
    if sizes:
        if sum(sizes) > span + 1e-6:
            raise kernel.CadError('Suma wymiarów komór przekracza wnętrze obudowy.')
        acc, out = 0.0, []
        for s in sizes:
            acc += s
            if acc < span - 1e-6:
                out.append(acc)
        return out
    n = int(p.get('chambers') or 0)
    if n < 2:
        raise kernel.CadError('Podaj liczbę komór (co najmniej 2), wymiary albo udziały.')
    return [span * k / n for k in range(1, n)]
