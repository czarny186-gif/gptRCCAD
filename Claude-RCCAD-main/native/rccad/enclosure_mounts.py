"""Generator obudów - etap 6: wykrywanie otworów montażowych w elementach i punkty montażowe.

Analiza topologii B-Rep (TopExp_Explorer po ścianach, BRepAdaptor_Surface): powierzchnie cylindryczne (i stożkowe -
pogłębienia stożkowe) grupowane po wspólnej osi (współosiowość sąsiednich powierzchni). Grupa jest otworem tylko wtedy,
gdy jej ściany są wklęsłe (normalna do osi), obejmują pełny obwód, a co najmniej jeden koniec jest otwarty (powietrze na
osi za końcem). Rodzaje: zwykły (jedna średnica, przelotowy), ślepy (jeden koniec zamknięty), pogłębiony (większa
średnica albo stożek przy wejściu), stopniowany (kilka średnic). Każdy otwór dostaje: średnicę, środek wejścia, kierunek
osi (od elementu na zewnątrz - kierunek mocowania), głębokość, przelotowość, stopnie, stronę obudowy i dostępność od strony
obudowy (oś za wejściem nie trafia w inne elementy). Słupki montażowe - kolejny etap."""
from __future__ import annotations

import math
import uuid

import numpy as np

from . import kernel

KINDS = ('plain', 'blind', 'counterbore', 'stepped', 'point')
KIND_LABELS = {'plain': 'zwykły', 'blind': 'ślepy', 'counterbore': 'pogłębiony', 'stepped': 'stopniowany', 'point': 'punkt ręczny'}
SIDE_WORDS = {'z-': 'od dna', 'z+': 'od pokrywy', 'x-': 'od ściany X−', 'x+': 'od ściany X+', 'y-': 'od ściany Y−', 'y+': 'od ściany Y+'}
DEFAULT_FILTER = dict(dmin=1.0, dmax=12.0, axis='all', kinds=('plain', 'blind', 'counterbore', 'stepped'))
ANG_TOL = 1e-3            # równoległość osi (|sin kąta|)
POS_TOL = 1e-3            # współosiowość (mm)


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _faces(shape):
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        yield TopoDS.Face_s(ex.Current())
        ex.Next()


def _surface_info(face):
    """Ściana cylindryczna / stożkowa: oś, promień (dla stożka - promienie na końcach), zakres osiowy, kąt obwodu, wklęsłość."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder
    from OCP.TopAbs import TopAbs_REVERSED
    s = BRepAdaptor_Surface(face, True)
    kind = s.GetType()
    if kind not in (GeomAbs_Cylinder, GeomAbs_Cone):
        return None
    u0, u1, v0, v1 = s.FirstUParameter(), s.LastUParameter(), s.FirstVParameter(), s.LastVParameter()
    if kind == GeomAbs_Cylinder:
        g = s.Cylinder()
        ax = g.Axis()
        o = np.array(ax.Location().Coord())
        d = _unit(ax.Direction().Coord())
        r0 = r1 = g.Radius()
        t0, t1 = v0, v1                          # v - położenie wzdłuż osi
    else:
        g = s.Cone()
        ax = g.Axis()
        o = np.array(ax.Location().Coord())
        d = _unit(ax.Direction().Coord())
        ang = g.SemiAngle()
        r0, r1 = g.RefRadius() + v0 * math.sin(ang), g.RefRadius() + v1 * math.sin(ang)
        t0, t1 = v0 * math.cos(ang), v1 * math.cos(ang)
    # normalna w środku ściany (z orientacją ściany) a kierunek od osi: wklęsła = otwór
    from OCP.gp import gp_Pnt, gp_Vec
    um, vm = (u0 + u1) / 2, (v0 + v1) / 2
    p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
    s.D1(um, vm, p, du, dv)
    n = np.cross(np.array(du.Coord()), np.array(dv.Coord()))
    if face.Orientation() == TopAbs_REVERSED:
        n = -n
    pt = np.array(p.Coord())
    radial = pt - o - ((pt - o) @ d) * d
    concave = float(n @ radial) < 0
    return dict(kind='cyl' if kind == GeomAbs_Cylinder else 'cone', o=o, d=d, r0=float(abs(r0)), r1=float(abs(r1)),
                t0=float(min(t0, t1)), t1=float(max(t0, t1)), span=float(abs(u1 - u0)), concave=concave, face=face)


def _coaxial(a, b):
    if float(np.linalg.norm(np.cross(a['d'], b['d']))) > ANG_TOL:
        return False
    w = b['o'] - a['o']
    return float(np.linalg.norm(w - (w @ a['d']) * a['d'])) < POS_TOL


def _groups(shape):
    infos = [i for i in (_surface_info(f) for f in _faces(shape)) if i is not None and i['concave']]   # wypukłe (wałki) - nie otwory
    groups = []
    for info in infos:
        for g in groups:
            if _coaxial(g[0], info):
                g.append(info)
                break
        else:
            groups.append([info])
    return groups


def analyse_group(shape, group, name=''):
    """Otwór z grupy współosiowych ścian: odcinki (średnica, zakres osiowy), końce otwarte / zamknięte, rodzaj. None - to
    nie jest otwór (wypukła, niepełny obwód, oba końce zamknięte)."""
    base = group[0]
    o, d = base['o'], base['d']
    segs = []
    for f in group:
        shift = float((f['o'] - o) @ d) * (1 if float(f['d'] @ d) > 0 else 1)
        sign = 1.0 if float(f['d'] @ d) > 0 else -1.0
        a, b = sorted((shift + sign * f['t0'], shift + sign * f['t1']))
        segs.append(dict(f, a=a, b=b))
    if not all(s['concave'] for s in segs):
        return None
    cyl = [s for s in segs if s['kind'] == 'cyl']
    if not cyl:
        return None
    # pełny obwód w każdym paśmie osiowym (ściany rozcięte szwem sumują się do 2π)
    bands = {}
    for s in cyl:
        key = (round(s['a'], 4), round(s['b'], 4), round(s['r0'], 4))
        bands[key] = bands.get(key, 0.0) + s['span']
    if any(span < 2 * math.pi - 1e-3 for span in bands.values()):
        return None
    lo = min(s['a'] for s in segs)
    hi = max(s['b'] for s in segs)
    if hi - lo < 1e-4:
        return None
    radius_at = lambda t: max((s['r0'] if s['kind'] == 'cyl' else s['r0'] + (s['r1'] - s['r0']) * (t - s['a']) / max(s['b'] - s['a'], 1e-9))
                              for s in segs if s['a'] - 1e-6 <= t <= s['b'] + 1e-6) if any(s['a'] - 1e-6 <= t <= s['b'] + 1e-6 for s in segs) else 0.0
    eps = 1e-2
    import cadquery as cq
    sh = cq.Shape.cast(shape)
    open_lo = kernel.point_state(sh, o + d * (lo - eps)) == 'out'
    open_hi = kernel.point_state(sh, o + d * (hi + eps)) == 'out'
    if not (open_lo or open_hi):
        return None
    rmin = min(s['r0'] for s in cyl)
    steps = sorted({round(2 * s['r0'], 4) for s in cyl})
    cone = any(s['kind'] == 'cone' for s in segs)
    through = open_lo and open_hi
    # wejście: otwarty koniec; przy przelotowym - koniec z większą średnicą (pogłębienie), inaczej dolny
    if through:
        r_lo, r_hi = radius_at(lo + 1e-4), radius_at(hi - 1e-4)
        entry_hi = r_hi > r_lo + 1e-6
    else:
        entry_hi = open_hi
    axis = d if entry_hi else -d
    center = o + d * (hi if entry_hi else lo)
    entry_r = radius_at(hi - 1e-4) if entry_hi else radius_at(lo + 1e-4)
    if len(steps) == 1 and not cone:
        kind = 'plain' if through else 'blind'
    elif (entry_r > rmin + 1e-6) and (cone or len(steps) == 2):
        kind = 'counterbore'
    else:
        kind = 'stepped'
    # powierzchnia oparcia przy wejściu: materiał obok wejścia, powietrze tuż nad nim
    side = _unit(np.cross(axis, (0, 0, 1.0) if abs(axis[2]) < .9 else (1.0, 0, 0)))
    rr = entry_r + min(1.0, max(.3, .5 * entry_r))
    seat = (kernel.point_state(sh, center + side * rr - axis * .05) == 'in'
            and kernel.point_state(sh, center + side * rr + axis * .05) == 'out')
    return dict(diameter=float(2 * rmin), entry_diameter=float(2 * entry_r), center=[float(c) for c in center],
                axis=[float(c) for c in axis], depth=float(hi - lo), through=bool(through), kind=kind,
                steps=[float(x) for x in steps], countersink=bool(cone), seat=bool(seat),
                ends=[[float(c) for c in o + d * lo], [float(c) for c in o + d * hi]])


def _env_side(env, axis):
    ax = np.asarray(env.axes, float)
    a = ax @ np.asarray(axis, float)
    i = int(np.argmax(np.abs(a)))
    return 'xyz'[i] + ('+' if a[i] > 0 else '-')


def accessible(point, axis, bodies, own=None, length=None):
    """Dostępność od strony obudowy: odcinek od wejścia wzdłuż kierunku mocowania nie trafia w żaden element."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    p = np.asarray(point, float) + np.asarray(axis, float) * .05
    q = p + np.asarray(axis, float) * float(length or 1000.0)
    edge = BRepBuilderAPI_MakeEdge(gp_Pnt(*map(float, p)), gp_Pnt(*map(float, q))).Edge()
    for body in bodies:
        if body.kind != 'solid':
            continue
        dist = BRepExtrema_DistShapeShape(edge, body.shape.wrapped)
        dist.Perform()
        if dist.IsDone() and dist.Value() < 1e-4:
            return False
    return True


def _with_env(hole, env, body, bodies):
    hole['side'] = _env_side(env, hole['axis']) if env is not None else ''
    span = float(np.max(np.asarray(env.size, float))) * 2 + 10 if env is not None else 1000.0
    hole['accessible'] = accessible(hole['center'], hole['axis'], bodies, length=span)
    hole['source'] = body.id
    hole['source_name'] = body.name
    return hole


def detect(bodies, ids, env=None):
    """Otwory montażowe w elementach o podanych id (bryły B-Rep). Zwraca listę opisów (status 'pending')."""
    by_id = {b.id: b for b in bodies}
    srcs = [by_id[i] for i in ids if i in by_id and by_id[i].kind == 'solid']
    out = []
    for body in srcs:
        for group in _groups(body.shape.wrapped):
            try:
                hole = analyse_group(body.shape.wrapped, group, body.name)
            except Exception:
                hole = None
            if hole is None:
                continue
            hole = _with_env(hole, env, body, srcs)
            hole.update(id=uuid.uuid4().hex, status='pending', manual=False)
            out.append(hole)
    return out


def from_face(body, face, bodies, env=None):
    """Ręcznie wskazana powierzchnia cylindryczna: otwór z jej grupy współosiowych ścian (bez filtrów heurystyki)."""
    info = _surface_info(face.wrapped if hasattr(face, 'wrapped') else face)
    if info is None or info['kind'] != 'cyl':
        raise kernel.CadError('Wskaż powierzchnię cylindryczną.')
    group = next((g for g in _groups(body.shape.wrapped) if _coaxial(g[0], info)), [info]) if info['concave'] else [info]
    hole = analyse_group(body.shape.wrapped, group, body.name) if info['concave'] else None
    if hole is None:                      # np. wałek albo niepełny otwór - punkt na osi z kierunkiem od elementu
        r = info['r0']
        mid = info['o'] + info['d'] * (info['t0'] + info['t1']) / 2
        hole = dict(diameter=2 * r, entry_diameter=2 * r, center=[float(c) for c in mid], axis=[float(c) for c in info['d']],
                    depth=info['t1'] - info['t0'], through=False, kind='blind' if info['concave'] else 'point', steps=[2 * r],
                    countersink=False, seat=False, ends=[list(map(float, info['o'] + info['d'] * info['t0'])),
                                                          list(map(float, info['o'] + info['d'] * info['t1']))])
    hole = _with_env(hole, env, body, [b for b in bodies if b.kind == 'solid'])
    hole.update(id=uuid.uuid4().hex, status='approved', manual=True)
    return hole


def manual_point(body, point, normal, bodies, env=None, diameter=3.0):
    """Ręczny punkt montażowy na ścianie elementu: kierunek mocowania - normalna ściany (od elementu na zewnątrz)."""
    hole = dict(diameter=float(diameter), entry_diameter=float(diameter), center=[float(c) for c in point],
                axis=[float(c) for c in _unit(normal)], depth=0.0, through=False, kind='point', steps=[], countersink=False,
                seat=True, ends=[list(map(float, point)), list(map(float, point))])
    hole = _with_env(hole, env, body, [b for b in bodies if b.kind == 'solid'])
    hole.update(id=uuid.uuid4().hex, status='approved', manual=True)
    return hole


def flipped(hole, env=None, bodies=()):
    """Zmiana kierunku mocowania: oś odwrócona; otwór przelotowy - wejście na drugim końcu."""
    h = dict(hole)
    h['axis'] = [-c for c in hole['axis']]
    if hole.get('through') and hole.get('ends'):
        a, b = (np.asarray(e, float) for e in hole['ends'])
        cur = np.asarray(hole['center'], float)
        h['center'] = [float(c) for c in (b if np.linalg.norm(cur - a) < np.linalg.norm(cur - b) else a)]
    if env is not None:
        h['side'] = _env_side(env, h['axis'])
        span = float(np.max(np.asarray(env.size, float))) * 2 + 10
        h['accessible'] = accessible(h['center'], h['axis'], [b for b in bodies if b.kind == 'solid'], length=span)
    return h


def passes(hole, flt):
    """Filtr: zakres średnic, kierunek osi (względem osi obudowy), rodzaje otworów. Ręczne punkty - zawsze."""
    if hole.get('manual'):
        return True
    f = dict(DEFAULT_FILTER, **(flt or {}))
    if not (f['dmin'] - 1e-9 <= hole['diameter'] <= f['dmax'] + 1e-9):
        return False
    if f['axis'] != 'all' and hole.get('side', ' ')[0] != f['axis']:
        return False
    return hole['kind'] in f['kinds']


def describe(hole):
    kind = KIND_LABELS.get(hole['kind'], hole['kind'])
    extra = ' przelotowy' if hole.get('through') and hole['kind'] == 'plain' else ''
    size = f'Ø{hole["diameter"]:.2f}' + (f'/Ø{hole["entry_diameter"]:.2f}' if hole['entry_diameter'] > hole['diameter'] + 1e-6 else '')
    acc = '' if hole.get('accessible', True) else ' · niedostępny'
    return f'{size} {kind}{extra} · {hole.get("source_name", "")} · {SIDE_WORDS.get(hole.get("side"), "")}{acc}'


def stored(hole):
    """Zatwierdzony punkt montażowy do zapisu w definicji obudowy (parametry geometryczne, bez stanu okna)."""
    keys = ('id', 'source', 'source_name', 'kind', 'diameter', 'entry_diameter', 'center', 'axis', 'depth', 'through', 'steps',
            'countersink', 'seat', 'side', 'accessible', 'manual', 'ends', 'post')
    return {k: hole[k] for k in keys if k in hole}


def marker_mesh(holes, size=1.0):
    """Tymczasowe znaczniki 3D: okrąg o średnicy otworu na wejściu i strzałka kierunku mocowania (same linie)."""
    edges = {}
    pts_all = []
    for n, h in enumerate(holes):
        c = np.asarray(h['center'], float)
        a = _unit(h['axis'])
        e1 = _unit(np.cross(a, (0, 0, 1.0) if abs(a[2]) < .9 else (1.0, 0, 0)))
        e2 = np.cross(a, e1)
        r = max(h['diameter'] / 2, .8 * size)
        ang = np.linspace(0, 2 * np.pi, 33)
        ring = np.array([c + r * (math.cos(t) * e1 + math.sin(t) * e2) for t in ang], np.float32)
        L = max(4.0 * size, 2.5 * r)
        tip = c + a * L
        head = [tip, tip - a * L * .3 + e1 * L * .14, tip, tip - a * L * .3 - e1 * L * .14]
        edges[(n, 0)] = ring
        edges[(n, 1)] = np.array([c, tip], np.float32)
        edges[(n, 2)] = np.array(head[:2], np.float32)
        edges[(n, 3)] = np.array(head[2:], np.float32)
        pts_all.append(ring)
    if not edges:
        return None
    v = np.concatenate(pts_all).astype(np.float32)
    return kernel.DisplayMesh(v, np.empty((0, 3), np.uint32), edges, tuple(map(float, v.mean(axis=0))),
                              float(np.linalg.norm(v.max(axis=0) - v.min(axis=0))))
