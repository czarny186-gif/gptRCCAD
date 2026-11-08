"""Konstrukcje ze sklejki (zakładka Sklejka): płyty, połączenia między nimi i części do cięcia.

Płyta to zwykła bryła z opisem meta['ply'] = {'t': grubość, 'method': metoda produkcji}. Połączenia program rozpoznaje sam
z tego, jak płyty się stykają:
  L - koniec płyty dotyka płaskiej strony drugiej płyty przy jej krawędzi (narożnik),
  T - koniec płyty dotyka płaskiej strony drugiej płyty z dala od krawędzi (półka, przegroda),
  X - płyty przechodzą przez siebie (krzyżują się).
Metoda produkcji decyduje, jakie połączenia da się wykonać (laser tnie tylko na wylot) i jak wyglądają szczegóły
(luz pasowania, „psie kości” pod frez).
"""
from __future__ import annotations

import math
import uuid

import cadquery as cq
import numpy as np

from . import kernel

# ---------------------------------------------------------------------------------------------------------------
# metody produkcji i rodzaje połączeń
# ---------------------------------------------------------------------------------------------------------------
METHODS = {
    'laser': dict(title='Cięcie laserowe', short='Laser', t=4.0, fit=0.0, kerf=0.15, tool=0.0,
                  note='Tnie tylko na wylot: wczepy, czopy w gniazdach przelotowych i nacięcia krzyżowe.'),
    'cnc': dict(title='Frezowanie CNC', short='Frezarka', t=18.0, fit=0.1, kerf=0.0, tool=6.0,
                note='Wszystkie połączenia; narożniki gniazd i nosków dostają wycięcia na frez (psie kości, T-kości albo bez) - frez nie może być szerszy niż gniazdo.'),
    'print': dict(title='Druk 3D', short='Druk 3D', t=4.0, fit=0.2, kerf=0.0, tool=0.0,
                  note='Wszystkie połączenia; luz pasowania zamiast szerokości cięcia.'),
}

JOINTS = {
    'finger': ('Wczepy', 'Noski na przemian na obu płytach (narożnik)'),
    'tab': ('Czopy i gniazda', 'Czopy na końcu płyty, gniazda przelotowe w drugiej płycie'),
    'blind': ('Gniazda nieprzelotowe', 'Czopy w gniazdach na głębokość - niewidoczne z zewnątrz'),
    'groove': ('Rowek', 'Cała krawędź płyty wsunięta w rowek (plecy, dno szuflady)'),
    'halving': ('Nacięcia krzyżowe', 'Obie płyty nacięte do połowy i wsunięte w siebie'),
    'none': ('Bez połączenia', 'Samo stykanie - pod wkręty, kołki albo klej'),
}

KIND_TITLES = {'L': 'Narożnik', 'T': 'Płyta w płycie', 'X': 'Krzyż', 'M': 'Narożnik pod kątem'}
KIND_JOINTS = {'L': ['finger', 'tab', 'blind', 'groove', 'none'], 'T': ['tab', 'blind', 'groove', 'none'], 'X': ['halving', 'none'],
               'M': ['finger', 'none']}
ALLOWED = {'laser': {'finger', 'tab', 'halving', 'none'},
           'cnc': {'finger', 'tab', 'blind', 'groove', 'halving', 'none'},
           'print': {'finger', 'tab', 'blind', 'groove', 'halving', 'none'}}
WHY_NOT = {'laser': 'laser tnie tylko na wylot - nie zrobi gniazda ani rowka na głębokość'}
# zamiana połączeń przy zmianie metody na taką, która ich nie potrafi
FALLBACK = {'blind': 'tab', 'groove': 'tab'}

TOL = 1e-3


def method(name):
    return METHODS.get(name) or METHODS['cnc']


def allowed(method_name, joint):
    return joint in ALLOWED.get(method_name, ALLOWED['cnc'])


def joint_for(method_name, kind, joint=None):
    """Połączenie dostępne dla metody i rodzaju styku: wskazane (gdy wolno), jego zamiennik albo domyślne."""
    choices = [j for j in KIND_JOINTS[kind] if allowed(method_name, j)]
    if joint in choices:
        return joint
    if joint in FALLBACK and FALLBACK[joint] in choices:
        return FALLBACK[joint]
    return choices[0]


def is_panel(body):
    return getattr(body, 'kind', None) == 'solid' and bool(body.meta) and isinstance(body.meta.get('ply'), dict)


def ply_meta(t, method_name):
    return {'ply': {'t': float(t), 'method': str(method_name)}}


# ---------------------------------------------------------------------------------------------------------------
# geometria pomocnicza
# ---------------------------------------------------------------------------------------------------------------
def _unit(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise kernel.CadError('Nieokreślony kierunek.')
    return v / n


def _canon(n):
    """Kierunek bez zwrotu (pierwsza niezerowa składowa dodatnia) - do grupowania ścian równoległych."""
    n = _unit(n)
    for c in n:
        if abs(c) > 1e-6:
            return n if c > 0 else -n
    return n


def frame_box(u, v, ru, rv, rw):
    """Prostopadłościan w układzie (u, v, w = u × v): zakresy współrzędnych ru, rv, rw."""
    u, v = _unit(u), _unit(v)
    w = np.cross(u, v)
    sizes = [float(r[1] - r[0]) for r in (ru, rv, rw)]
    if min(sizes) <= 1e-6:
        raise kernel.CadError('Płyta ma zerowy wymiar.')
    solid = cq.Solid.makeBox(*sizes, pnt=cq.Vector(float(ru[0]), float(rv[0]), float(rw[0])))
    return kernel.transformed(solid, np.column_stack([u, v, w]), np.zeros(3))


def _points(shape):
    pts = [v.toTuple() for v in shape.Vertices()]
    for e in shape.Edges():
        if e.geomType() != 'LINE':
            pts += [e.positionAt(t).toTuple() for t in (.25, .5, .75)]
    return np.asarray(pts, float)


def extent(shape, direction, pts=None):
    p = _points(shape) if pts is None else pts
    s = p @ _unit(direction)
    return float(s.min()), float(s.max())


def panel_info(shape, t=None):
    """Kierunek grubości płyty: normalna największych równoległych płaskich ścian; lo / hi - położenie obu stron."""
    groups = {}
    for f in shape.Faces():
        if f.geomType() != 'PLANE':
            continue
        try:
            n = np.array(f.normalAt().toTuple(), float)
        except Exception:
            continue
        c = _canon(n)
        key = tuple(np.round(c, 4))
        g = groups.setdefault(key, dict(n=c, area=0.0, offsets=[]))
        g['area'] += f.Area()
        g['offsets'].append(float(np.array(f.Center().toTuple()) @ c))
    best = None
    for g in groups.values():
        if len(g['offsets']) < 2:
            continue
        lo, hi = min(g['offsets']), max(g['offsets'])
        if hi - lo < 1e-6:
            continue
        score = g['area']
        if t is not None and abs((hi - lo) - float(t)) < 1e-3:
            score *= 1e6           # grubość z opisu płyty wygrywa (np. płyta węższa niż grubsza)
        if best is None or score > best[0]:
            best = (score, g['n'], lo, hi)
    if best is None:
        raise kernel.CadError('To nie jest płaska płyta.')
    _, n, lo, hi = best
    return dict(n=n, lo=lo, hi=hi, t=hi - lo)


def panels_of(bodies):
    out = []
    for b in bodies:
        if is_panel(b) and b.visible:
            info = panel_info(b.shape, b.meta['ply'].get('t'))
            out.append(dict(id=b.id, name=b.name, shape=b.shape, method=b.meta['ply'].get('method', 'cnc'),
                            joined=set(b.meta['ply'].get('joined', ())), **info))
    return out


# ---------------------------------------------------------------------------------------------------------------
# płyta na krawędzi (ścianka) i płyta pomiędzy (półka, przegroda)
# ---------------------------------------------------------------------------------------------------------------
def edge_wall(base_shape, edge, t, height, side='on', flip=False, base_t=None, extend=(0.0, 0.0)):
    """Ścianka na prostej krawędzi płaskiej strony płyty-podstawy.
    side: 'on' - stoi na podstawie (licuje z jej krawędzią), 'side' - przy boku podstawy (zakrywa jej brzeg).
    Wysokość liczona od strony podstawy, na której leży krawędź. Zwraca (bryła, kierunek do góry)."""
    info = panel_info(base_shape, base_t)
    n = info['n']
    if edge.geomType() != 'LINE':
        raise kernel.CadError('Ścianka powstaje na prostej krawędzi płyty.')
    a = np.array(edge.startPoint().toTuple(), float)
    b = np.array(edge.endPoint().toTuple(), float)
    if abs(float(_unit(b - a) @ n)) > 1e-3:
        raise kernel.CadError('Kliknij krawędź płaskiej strony płyty (nie krawędź grubości).')
    level = float(a @ n)
    if abs(level - info['hi']) < 1e-3:
        up = n.copy()
    elif abs(level - info['lo']) < 1e-3:
        up = -n
    else:
        raise kernel.CadError('Kliknij krawędź płaskiej strony płyty.')
    e = _unit(b - a)
    out = np.cross(e, up)                    # w płaszczyźnie płyty, prostopadle do krawędzi
    probe = (a + b) / 2 + out * 1e-2 - up * min(info['t'] / 2, 1e-2)
    if kernel.point_state(base_shape, tuple(probe)) == 'in':
        out = -out                           # na zewnątrz podstawy
    if flip:                                 # ścianka po drugiej stronie podstawy (od jej przeciwnej strony)
        a, b = a - up * info['t'], b - up * info['t']
        up = -up
    length = float(np.linalg.norm(b - a))
    thick = float(t)
    if side == 'on':
        rw = (-thick, 0.0)                   # od krawędzi w głąb podstawy
        rup = (0.0, float(height))
    else:
        rw = (0.0, thick)                    # na zewnątrz krawędzi, zakrywa brzeg podstawy
        rup = (-info['t'], float(height))
    # układ: u = e, v = out, w = e × out = up (prawoskrętny)
    w = np.cross(e, out)
    sign = 1.0 if float(w @ up) > 0 else -1.0
    ru = (float(a @ e) - float(extend[0]), float(a @ e) + length + float(extend[1]))
    rv = (float(a @ out) + rw[0], float(a @ out) + rw[1])
    base_w = float(a @ w)
    rz = sorted((base_w + sign * rup[0], base_w + sign * rup[1]))
    return frame_box(e, out, ru, rv, rz), up


def _halfspace(point, normal, size):
    """Duży prostopadłościan po stronie +normal płaszczyzny przez point (do przycinania)."""
    n = _unit(normal)
    helper = np.array((0, 0, 1.0)) if abs(n[2]) < .9 else np.array((1.0, 0, 0))
    v = _unit(np.cross(n, helper))
    w = np.cross(n, v)
    p = np.asarray(point, float)
    return frame_box(n, v, (float(p @ n), float(p @ n) + size), (float(p @ v) - size, float(p @ v) + size),
                     (float(p @ w) - size, float(p @ w) + size))


def edge_walls(base_shape, edges, t, height, side='on', flip=False, base_t=None):
    """Ścianki na kilku krawędziach naraz. W narożnikach pod kątem innym niż prosty (podstawa-wielokąt) ścianki są
    przedłużone i przycięte wzdłuż dwusiecznej - schodzą się dokładnie, bez nachodzenia i bez szczeliny (także przy boku).
    W narożnikach prostych dłuższa ścianka biegnie przez cały narożnik, krótsza do niej dochodzi (przy boku dłuższa jest
    wydłużona o grubość, żeby narożnik był pełny). Zwraca listę (bryła, kierunek do góry) w kolejności krawędzi."""
    info = panel_info(base_shape, base_t)
    size = 10.0 * (max(info['t'], float(t), float(height)) + sum(e.Length() for e in edges))
    data = []
    for e in edges:
        a = np.array(e.startPoint().toTuple(), float)
        b = np.array(e.endPoint().toTuple(), float)
        data.append(dict(edge=e, a=a, b=b, level=round(float(a @ info['n']), 4)))
    order = sorted(range(len(edges)), key=lambda i: -edges[i].Length())
    rank = {i: k for k, i in enumerate(order)}
    out = []
    for i, item in enumerate(data):
        ext = {'a': 0.0, 'b': 0.0}
        mitres = []
        for j, other in enumerate(data):
            if j == i or other['level'] != item['level']:
                continue
            for end in ('a', 'b'):
                V = item[end]
                far = item['b' if end == 'a' else 'a']
                shared = next((o for o in ('a', 'b') if np.linalg.norm(other[o] - V) < 1e-5), None)
                if shared is None:
                    continue
                ui = _unit(far - V)
                uj = _unit(other['b' if shared == 'a' else 'a'] - V)
                probe = V + (ui + uj) * min(1.0, .25 * float(t)) - info['n'] * (info['t'] / 2) * (1 if float(V @ info['n']) >= info['hi'] - 1e-6 else -1)
                if abs(float(ui @ uj)) < 1e-4 and _inside(base_shape, probe):   # narożnik prosty wypukły
                    if side != 'on' and rank[i] < rank[j]:
                        ext[end] = max(ext[end], float(t))  # przy boku: dłuższa ścianka zakrywa narożnik
                    continue
                if abs(abs(float(ui @ uj)) - 1) < 1e-6:
                    continue                               # krawędzie w jednej linii
                ext[end] = size / 10.0
                mitres.append((V, ui - uj))
        wall, up = edge_wall(base_shape, item['edge'], t, height, side, flip, base_t, extend=(ext['a'], ext['b']))
        for V, normal in mitres:
            wall = kernel.boolean('intersect', wall, [_halfspace(V, normal, size)])
        out.append((wall, up))
    return out


def face_extents(face, u, v):
    p = _points(face)
    su, sv = p @ u, p @ v
    return (float(su.min()), float(su.max())), (float(sv.min()), float(sv.max()))


def between_axes(na, prefer=None, turn=False):
    """Kierunek grubości półki (s) i jej szerokości (w) dla szczeliny o kierunku na."""
    g = _unit(na)
    candidates = [np.array(prefer, float)] if prefer is not None else []
    candidates += [np.array(c, float) for c in ((0, 0, 1), (0, 1, 0), (1, 0, 0))]
    for c in candidates:
        s = c - g * float(c @ g)
        if np.linalg.norm(s) > 1e-3:
            s = _unit(s)
            break
    w = np.cross(g, s)
    if turn:
        s, w = w, -s
    return g, s, w


def between_panels(face_a, point_a, normal_a, face_b, point_b, t, position=None, count=1, turn=False):
    """Półki / przegrody między dwiema równoległymi ścianami zwróconymi do siebie.
    position: odległość spodu (pierwszej) półki od dolnego brzegu wspólnego obszaru; None - środek.
    count > 1: tyle płyt rozłożonych równo. Zwraca (lista brył, opis do strzałki)."""
    g = _unit(normal_a)
    pa, pb = np.asarray(point_a, float), np.asarray(point_b, float)
    gap = float((pb - pa) @ g)
    if gap <= 1e-3:
        raise kernel.CadError('Druga ściana musi stać naprzeciw pierwszej (po stronie, w którą ona patrzy).')
    nb = np.array(face_b.normalAt().toTuple(), float)
    if abs(abs(float(_unit(nb) @ g)) - 1) > 1e-3:
        raise kernel.CadError('Ściany muszą być równoległe.')
    g, s, w = between_axes(g, turn=turn)
    (sa, wa), (sb, wb) = face_extents(face_a, s, w), face_extents(face_b, s, w)
    rs = (max(sa[0], sb[0]), min(sa[1], sb[1]))
    rw = (max(wa[0], wb[0]), min(wa[1], wb[1]))
    if rs[1] - rs[0] < t + 1e-3 or rw[1] - rw[0] < 1e-3:
        raise kernel.CadError('Ściany nie mają wspólnego obszaru, w którym zmieści się płyta.')
    t = float(t)
    span = rs[1] - rs[0]
    count = max(1, int(count))
    if count == 1:
        pos = (span - t) / 2 if position is None else min(max(float(position), 0.0), span - t)
        starts = [rs[0] + pos]
    else:
        step = (span - count * t) / (count + 1)
        if step < 0:
            raise kernel.CadError('Tyle płyt się nie zmieści.')
        starts = [rs[0] + step * (i + 1) + t * i for i in range(count)]
    rg = (float(pa @ g), float(pa @ g) + gap)
    # układ (g, s, g × s = w')
    w2 = np.cross(g, s)
    sign = 1.0 if float(w2 @ w) > 0 else -1.0
    rw2 = sorted((sign * rw[0], sign * rw[1]))
    solids = [frame_box(g, s, rg, (z, z + t), rw2) for z in starts]
    mid_w = (rw[0] + rw[1]) / 2
    centre = g * (rg[0] + rg[1]) / 2 + w * mid_w
    return solids, dict(s=s, low=rs[0], span=span, starts=starts, centre=centre, g=g, w=w, gap=gap, depth=rw[1] - rw[0])


# ---------------------------------------------------------------------------------------------------------------
# rozpoznawanie styków
# ---------------------------------------------------------------------------------------------------------------
def _boxes_near(a, b, tol=1e-2):
    ba, bb = a.BoundingBox(), b.BoundingBox()
    return not (ba.xmax < bb.xmin - tol or bb.xmax < ba.xmin - tol or ba.ymax < bb.ymin - tol or bb.ymax < ba.ymin - tol
                or ba.zmax < bb.zmin - tol or bb.zmax < ba.zmin - tol)


def _abut(A, B, pa, pb):
    """Koniec płyty A na płaskiej stronie płyty B: opis styku albo None."""
    na, nb = A['n'], B['n']
    d = _unit(np.cross(na, nb))
    m = np.cross(nb, d)                     # w płaszczyźnie B, prostopadle do linii styku (∥ ±na)
    a_lo, a_hi = extent(None, nb, pa) if pa is not None else extent(A['shape'], nb)
    if abs(a_lo - B['hi']) < TOL:
        plane, into = B['hi'], -1.0
    elif abs(a_hi - B['lo']) < TOL:
        plane, into = B['lo'], 1.0
    else:
        # płyta A sięga po obu stronach płaszczyzny B (np. podstawa-wielokąt wklęsły przy ściance „przy boku”):
        # styk jest tam, gdzie A ma ścianę końca na stronie B zwróconą do B
        plane = None
        for f in A['shape'].Faces():
            if f.geomType() != 'PLANE':
                continue
            fn = np.array(f.normalAt().toTuple(), float)
            o = float(np.array(f.Center().toTuple()) @ nb)
            if float(fn @ nb) < -1 + 1e-4 and abs(o - B['hi']) < TOL:
                plane, into = B['hi'], -1.0
            elif float(fn @ nb) > 1 - 1e-4 and abs(o - B['lo']) < TOL:
                plane, into = B['lo'], 1.0
            else:
                continue
            break
        if plane is None:
            return None
    # ściany końca A leżące na płaszczyźnie styku (zwrócone do płyty B)
    ends = []
    for f in A['shape'].Faces():
        if f.geomType() != 'PLANE':
            continue
        fn = np.array(f.normalAt().toTuple(), float)
        if abs(abs(float(fn @ nb)) - 1) > 1e-4 or float(fn @ nb) * into < 0:
            continue
        if abs(float(np.array(f.Center().toTuple()) @ nb) - plane) > TOL:
            continue
        ends.append(f)
    if not ends:
        return None
    ep = np.concatenate([_points(f) for f in ends])
    s0, s1 = float((ep @ d).min()), float((ep @ d).max())
    r0, r1 = float((ep @ m).min()), float((ep @ m).max())
    bd = extent(None, d, pb)
    bm = extent(None, m, pb)
    s0, s1 = max(s0, bd[0]), min(s1, bd[1])
    r0, r1 = max(r0, bm[0]), min(r1, bm[1])
    if s1 - s0 < 1e-2 or r1 - r0 < 1e-2:
        return None
    kind = 'L' if (r0 <= bm[0] + TOL or r1 >= bm[1] - TOL) else 'T'
    c = dict(a=A['id'], b=B['id'], kind=kind, d=d.tolist(), m=m.tolist(), nb=nb.tolist(), plane=plane, into=into,
             s=[s0, s1], r=[r0, r1], ta=A['t'], tb=B['t'])
    if sum(f.Area() for f in ends) < (s1 - s0) * (r1 - r0) - 1e-3:
        c['ends'] = ends                     # koniec płyty nie jest prostokątem (ścianka przycięta na skos)
    return c


def _mitre(A, B):
    """Narożnik na skos: boczne ściany obu płyt (nie ich płaskie strony) przylegają do siebie - ścianki na podstawie-wielokącie."""
    na, nb = A['n'], B['n']
    sides = lambda P: [f for f in P['shape'].Faces() if f.geomType() == 'PLANE'
                       and abs(abs(float(np.array(f.normalAt().toTuple()) @ na)) - 1) > 1e-6
                       and abs(abs(float(np.array(f.normalAt().toTuple()) @ nb)) - 1) > 1e-6]
    best = None
    for fa in sides(A):
        n1 = np.array(fa.normalAt().toTuple(), float)
        o1 = float(np.array(fa.Center().toTuple()) @ n1)
        for fb in sides(B):
            n2 = np.array(fb.normalAt().toTuple(), float)
            if float(n1 @ n2) > -1 + 1e-6 or abs(float(np.array(fb.Center().toTuple()) @ n1) - o1) > TOL:
                continue
            try:
                common = fa.intersect(fb)
                area = sum(f.Area() for f in common.Faces())
            except Exception:
                continue
            if area > 1e-2 and (best is None or area > best[0]):
                best = (area, common)
    if best is None:
        return None
    d = _unit(np.cross(na, nb))
    cp = _points(best[1])
    s0, s1 = float((cp @ d).min()), float((cp @ d).max())
    if s1 - s0 < 1e-2:
        return None
    return dict(a=A['id'], b=B['id'], kind='M', d=d.tolist(), na=na.tolist(), nb=nb.tolist(), s=[s0, s1],
                sa=[A['lo'], A['hi']], sb=[B['lo'], B['hi']], ta=A['t'], tb=B['t'],
                angle=round(math.degrees(math.acos(min(1.0, abs(float(na @ nb))))), 1))


def _cross(A, B, pa, pb):
    na, nb = A['n'], B['n']
    try:
        common = A['shape'].intersect(B['shape'])
        vol = common.Volume() if common.Solids() else 0.0
    except Exception:
        return None
    if vol <= 1e-6:
        return None
    d = _unit(np.cross(na, nb))
    cp = _points(common)
    ia, ib, s = extent(None, na, cp), extent(None, nb, cp), extent(None, d, cp)
    if abs((ia[1] - ia[0]) - A['t']) > 2e-3 or abs((ib[1] - ib[0]) - B['t']) > 2e-3:
        return dict(a=A['id'], b=B['id'], kind='overlap')
    return dict(a=A['id'], b=B['id'], kind='X', d=d.tolist(), na=na.tolist(), nb=nb.tolist(), s=list(s), ia=list(ia), ib=list(ib),
                ad=list(extent(None, d, pa)), bd=list(extent(None, d, pb)), ta=A['t'], tb=B['t'])


def cross_new(new_shape, t, others, meth='cnc', fit=None, tool=None, corner='dog'):
    """Nowa płyta przechodząca na wylot przez istniejące (przegrody na krzyż): od razu nacięcia krzyżowe do połowy
    w obu płytach. others: [(id, kształt, grubość)] - także płyty ukryte. Zwraca (nowa płyta, {id: zmieniona płyta}, [id])."""
    m = method(meth)
    fit = m['fit'] if fit is None else fit
    tool = m['tool'] if tool is None else tool
    changed, crossed = {}, []
    new = dict(id='__new__', shape=new_shape, **panel_info(new_shape, t))
    for oid, shape, ot in others:
        if not _boxes_near(new['shape'], shape, 0.0):
            continue
        try:
            other = dict(id=oid, shape=changed.get(oid, shape), **panel_info(shape, ot))
        except kernel.CadError:
            continue
        if abs(float(new['n'] @ other['n'])) > 1e-4:
            continue                         # tylko płyty prostopadłe
        pn, po = _points(new['shape']), _points(other['shape'])
        # prawdziwy krzyż: każda płyta wystaje po obu stronach drugiej (półka kończąca się w ściance to nie krzyż)
        en, eo = extent(None, other['n'], pn), extent(None, new['n'], po)
        if not (en[0] < other['lo'] - 1e-3 and en[1] > other['hi'] + 1e-3 and eo[0] < new['lo'] - 1e-3 and eo[1] > new['hi'] + 1e-3):
            continue
        c = _cross(new, other, pn, po)
        if c is None or c['kind'] != 'X':
            continue
        c['joint'], c['key'] = 'halving', f'__new__:{oid}'
        try:
            out = apply_joints({'__new__': (new['shape'], new['n']), oid: (other['shape'], other['n'])}, [c],
                               dict(method=meth, fit=fit, tool=tool, corner=corner))
        except kernel.CadError:
            continue                         # nie da się naciąć (płyty nie dochodzą do krawędzi) - zostanie przycięta
        new['shape'] = out['__new__']
        changed[oid] = out[oid]
        crossed.append(oid)
    return new['shape'], changed, crossed


def find_contacts(panels):
    """Styki między płytami: lista opisów (L, T, X, M - narożnik na skos). Płyty równoległe są pomijane."""
    out, skipped = [], []
    pts = {p['id']: _points(p['shape']) for p in panels}
    for i, A in enumerate(panels):
        for B in panels[i + 1:]:
            if not _boxes_near(A['shape'], B['shape']):
                continue
            if B['id'] in A.get('joined', ()) or A['id'] in B.get('joined', ()):
                continue                     # te płyty są już połączone (wcześniejszy krok)
            if abs(float(A['n'] @ B['n'])) > 1 - 1e-6:
                continue                     # równoległe: leżą na sobie albo obok siebie
            if abs(float(A['n'] @ B['n'])) > 1e-4:
                found = _mitre(A, B)        # pod innym kątem niż prosty: tylko narożnik na skos
                if found is not None:
                    out.append(found)
                elif A['shape'].distance(B['shape']) < TOL:      # tylko płyty, które naprawdę się stykają
                    skipped.append((A['id'], B['id'], 'Płyty pod kątem innym niż 90° stykają się bez skosu (jedna docięta prosto do drugiej) - połączenie pominięte. Usuń te ścianki i dodaj je ponownie narzędziem Ścianka, wtedy zejdą się na skos z noskami.'))
                continue
            found = _cross(A, B, pts[A['id']], pts[B['id']])
            if found is not None:
                if found['kind'] == 'overlap':
                    skipped.append((A['id'], B['id'], 'Płyty nachodzą na siebie - popraw ich położenie.'))
                else:
                    out.append(found)
                continue
            found = _abut(A, B, pts[A['id']], pts[B['id']]) or _abut(B, A, pts[B['id']], pts[A['id']]) or _mitre(A, B)
            if found is not None:
                out.append(found)
    for c in out:
        c['key'] = f"{c['a']}:{c['b']}"
    return out, skipped


# ---------------------------------------------------------------------------------------------------------------
# wykonanie połączeń
# ---------------------------------------------------------------------------------------------------------------
def finger_count(length, width):
    """Nieparzysta liczba odcinków (najmniej 3) o szerokości możliwie bliskiej zadanej."""
    n = max(3, int(round(length / max(width, 1e-6))))
    if n % 2 == 0:
        lower, upper = n - 1, n + 1
        n = upper if lower < 3 or abs(length / upper - width) < abs(length / lower - width) else lower
    return n


def default_width(t):
    return round(3.0 * float(t), 1)


def _seg_box(c, s0, s1, r0, r1, depth, pre=0.0, grow_s=0.0, grow_r=0.0):
    """Fragment obszaru styku: wzdłuż linii (s), w poprzek (r = grubość płyty A) i w głąb płyty B (od płaszczyzny styku;
    pre - zapas po stronie płyty A, żeby wycięcie zaczynało się poza płytą B)."""
    d, m = np.array(c['d']), np.array(c['m'])
    plane, into = float(c['plane']), float(c['into'])
    z = sorted((plane - into * pre, plane + into * depth))
    # układ (d, m, d × m): d × m = d × (nb × d) = nb
    return frame_box(d, m, (s0 - grow_s, s1 + grow_s), (r0 - grow_r, r1 + grow_r), z)


def _joint_parts(c, joint, width, fit, depth_ratio):
    """(dla A: bryły dodawane, dla B: bryły wycinane, obszar do „psich kości”) dla styku L / T."""
    s0, s1 = c['s']
    r0, r1 = c['r']
    tb = float(c['tb'])
    if joint == 'none':
        return [], [], None
    through = joint in ('finger', 'tab')
    depth = tb if through else max(.5, min(tb - .5, tb * depth_ratio))
    deeper = .05 if through else fit / 2         # wycięcie przelotowe wychodzi poza płytę, nieprzelotowe ma luz na dnie
    if joint == 'groove':
        add = [_seg_box(c, s0, s1, r0, r1, depth, 1e-4)]
        cut = [_seg_box(c, s0, s1, r0, r1, depth + deeper, .05, 0.0, fit / 2)]
        return add, cut, (s0, s1, r0, r1, depth)
    n = finger_count(s1 - s0, width)
    step = (s1 - s0) / n
    first = 0 if joint == 'finger' else 1       # wczepy: A zaczyna i kończy noskiem; czopy: końce zostają przy B
    add, cut = [], []
    for k in range(first, n, 2):
        a, b = s0 + k * step, s0 + (k + 1) * step
        add.append(_seg_box(c, a, b, r0, r1, depth, 1e-4))
        box = _seg_box(c, a - (fit / 2 if k > 0 else .05), b + (fit / 2 if k < n - 1 else .05), r0, r1, depth + deeper, .05, 0.0, fit / 2)
        cut.append(box)
    return add, cut, (s0, s1, r0, r1, depth)


def _halving_parts(c, fit):
    """Nacięcia krzyżowe: (wycięcie w A, wycięcie w B, obszar)."""
    d, na, nb = np.array(c['d']), np.array(c['na']), np.array(c['nb'])
    s0, s1 = c['s']
    mid = (s0 + s1) / 2
    ad, bd = c['ad'], c['bd']
    a_top, a_bot = s1 >= ad[1] - TOL, s0 <= ad[0] + TOL
    b_top, b_bot = s1 >= bd[1] - TOL, s0 <= bd[0] + TOL
    if a_top and b_bot:
        ra, rb = (mid, s1 + 1.0), (s0 - 1.0, mid)
    elif a_bot and b_top:
        ra, rb = (s0 - 1.0, mid), (mid, s1 + 1.0)
    else:
        raise kernel.CadError('Nacięcia krzyżowe: płyty muszą przecinać się aż do swoich krawędzi (jedna od góry, druga od dołu).')
    ia, ib = c['ia'], c['ib']
    # w A wycinamy pas grubości B (kierunek nb), przez całą grubość A (na); w B - pas grubości A, przez całą grubość B
    # układ (d, nb, d × nb = -na) - zakres na podany ze zmienionym znakiem
    cut_a = frame_box(d, nb, ra, (ib[0] - fit / 2, ib[1] + fit / 2), (-ia[1] - 1.0, -ia[0] + 1.0))
    cut_b = frame_box(d, nb, rb, (ib[0] - 1.0, ib[1] + 1.0), (-ia[1] - fit / 2, -ia[0] + fit / 2))
    return cut_a, cut_b, (ra, rb)


def _rhombus(c, s0, s1):
    """Część wspólna obu płyt przedłużonych w narożniku na skos (graniastosłup wzdłuż linii narożnika, od s0 do s1)."""
    d, na, nb = np.array(c['d']), np.array(c['na']), np.array(c['nb'])
    M = np.array([na, nb, d])
    pts = []
    for a, b in ((c['sa'][0], c['sb'][0]), (c['sa'][1], c['sb'][0]), (c['sa'][1], c['sb'][1]), (c['sa'][0], c['sb'][1])):
        pts.append(np.linalg.solve(M, np.array([a, b, s0], float)))
    wire = cq.Wire.makePolygon([cq.Vector(*p) for p in pts], close=True)
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(wire), cq.Vector(*(d * (s1 - s0))))


def _mitre_fingers(c, A, B, width, fit):
    """Wczepy w narożniku na skos: wspólny obszar narożnika dzielony wzdłuż linii narożnika na odcinki należące
    na przemian do jednej i drugiej płyty (z luzem między nimi)."""
    s0, s1 = c['s']
    whole = _rhombus(c, s0 - .01, s1 + .01)
    region = kernel.boolean('union', A.intersect(whole), [B.intersect(whole)])
    n = finger_count(s1 - s0, width)
    step = (s1 - s0) / n
    A2, B2 = kernel.boolean('subtract', A, [whole]), kernel.boolean('subtract', B, [whole])
    own = {0: [], 1: []}
    for k in range(n):
        lo = s0 + k * step + (fit / 2 if k > 0 else -.02)
        hi = s0 + (k + 1) * step - (fit / 2 if k < n - 1 else -.02)
        piece = region.intersect(_rhombus(c, lo, hi))
        if piece.Solids():
            own[k % 2].append(piece)
    if own[0]:
        A2 = kernel.boolean('union', A2, own[0])
    if own[1]:
        B2 = kernel.boolean('union', B2, own[1])
    return A2, B2


def _clip_polygon(poly, normal, lo, hi):
    """Wielokąt (punkty 3D w jednej płaszczyźnie) przycięty do pasa lo <= p·normal <= hi (Sutherland-Hodgman)."""
    def clip(points, keep):
        out = []
        for i, p in enumerate(points):
            q = points[(i + 1) % len(points)]
            fp, fq = keep(p), keep(q)
            if fp >= 0:
                out.append(p)
            if (fp >= 0) != (fq >= 0):
                out.append(p + (q - p) * (fp / (fp - fq)))
        return out
    poly = clip(poly, lambda p: float(p @ normal) - lo)
    return clip(poly, lambda p: hi - float(p @ normal)) if poly else poly


FLAT_MITRE = 12.0       # ścianki załamane o mniej niż tyle stopni: zwykły styk na skos (bez wczepów i prostowania końców)


def _square_corner(c, A, B, width, fit):
    """Narożnik pod kątem do cięcia prostopadłego (laser, frezarka): końce obu ścianek prostopadłe do ich stron.
    Wzdłuż linii narożnika pasy (wczepy) należą na przemian do jednej i drugiej ścianki: właściciel pasa sięga do
    zewnętrznego wierzchołka narożnika, a druga ścianka jest w tym pasie cofnięta tak, żeby się z nim nie zderzyć
    (z luzem). width None - jeden pas: ścianka A zachodzi na B na całej wysokości. Zwraca (A, B, obszar narożnika)."""
    d = _unit(c['d'])
    s0, s1 = c['s']
    walls = {}
    rh = [np.linalg.solve(np.array([c['na'], c['nb'], d]), np.array([a, b, s0], float))
          for a, b in ((c['sa'][0], c['sb'][0]), (c['sa'][1], c['sb'][0]), (c['sa'][1], c['sb'][1]), (c['sa'][0], c['sb'][1]))]
    centre = sum(rh) / 4
    for key, shape, n, slab in (('a', A, np.array(c['na'], float), c['sa']), ('b', B, np.array(c['nb'], float), c['sb'])):
        u = _unit(np.cross(d, n))
        body = np.array(shape.Center().toTuple(), float)
        if float((centre - body) @ u) < 0:
            u = -u                                  # w stronę narożnika
        walls[key] = dict(n=n, u=u, slab=slab)
    ua, ub = walls['a']['u'], walls['b']['u']
    outer = max(rh, key=lambda p: float(p @ (ua + ub)))       # zewnętrzny wierzchołek narożnika
    full, reach = {}, {}
    base = d * s0
    for key, w in walls.items():
        proj = [float(p @ w['u']) for p in rh]
        w['start'], w['end'] = min(proj) - 1.0, float(outer @ w['u'])
        # narożnik o kącie ostrym: koniec prostopadły przez zewnętrzny wierzchołek wystawałby wewnętrznym rogiem
        # poza zewnętrzną stronę sąsiedniej ścianki - koniec cofnięty do tej płaszczyzny (nic nie wystaje)
        o = walls['b' if key == 'a' else 'a']
        ob = float(outer @ o['n'])
        inner = o['slab'][1] if abs(o['slab'][0] - ob) < abs(o['slab'][1] - ob) else o['slab'][0]
        sigma = 1.0 if inner > ob else -1.0
        coef = float(o['n'] @ w['u'])
        if sigma * coef < -1e-9:
            for vv in w['slab']:
                c0 = float(o['n'] @ (base + w['n'] * (vv - float(base @ w['n']))))
                w['end'] = min(w['end'], (ob - c0) / coef)
        reach[key] = max(proj) + 5.0
        third = np.cross(w['u'], w['n'])
        sign = 1.0 if float(third @ d) > 0 else -1.0
        full[key] = frame_box(w['u'], w['n'], (w['start'], w['end']), tuple(w['slab']), sorted((sign * s0, sign * s1)))
        # przekrój końca ścianki dochodzącej do narożnika (prostokąt w płaszczyźnie prostopadłej do linii narożnika)
        w['section'] = [base + w['u'] * uu + w['n'] * (vv - float(base @ w['n'])) for uu, vv in
                        ((w['start'], w['slab'][0]), (w['end'], w['slab'][0]), (w['end'], w['slab'][1]), (w['start'], w['slab'][1]))]
    A2 = kernel.boolean('union', A, [full['a']])
    B2 = kernel.boolean('union', B, [full['b']])
    # gdzie druga ścianka musi się cofnąć, gdy właścicielem pasa jest ta ścianka
    back = {}
    for owner, other in (('a', 'b'), ('b', 'a')):
        o = walls[other]
        part = _clip_polygon(walls[owner]['section'], o['n'], o['slab'][0], o['slab'][1])
        back[other] = (min(float(p @ o['u']) for p in part) - fit) if part else None
    n = 1 if width is None else finger_count(s1 - s0, width)
    step = (s1 - s0) / n
    cuts = {'a': [], 'b': []}
    for k in range(n):
        owner = 'a' if k % 2 == 0 else 'b'
        other = 'b' if owner == 'a' else 'a'
        if back[other] is None:
            continue
        lo = s0 + k * step - (fit / 2 if k > 0 else 1.0)
        hi = s0 + (k + 1) * step + (fit / 2 if k < n - 1 else 1.0)
        w = walls[other]
        third = np.cross(w['u'], w['n'])
        sign = 1.0 if float(third @ d) > 0 else -1.0
        cuts[other].append(frame_box(w['u'], w['n'], (back[other], reach[other]), (w['slab'][0] - 1, w['slab'][1] + 1), sorted((sign * lo, sign * hi))))
    if cuts['a']:
        A2 = kernel.boolean('subtract', A2, cuts['a'])
    if cuts['b']:
        B2 = kernel.boolean('subtract', B2, cuts['b'])
    region = kernel.boolean('union', full['a'], [full['b']])
    bb = region.BoundingBox()
    box = cq.Solid.makeBox(bb.xlen + 2, bb.ylen + 2, bb.zlen + 2, pnt=cq.Vector(bb.xmin - 1, bb.ymin - 1, bb.zmin - 1))
    return A2, B2, box


def _region_box(c, extra, info=None):
    """Prostopadłościan wokół miejsca styku (do wyboru krawędzi pod „psie kości”)."""
    if c['kind'] == 'X':
        d, nb = np.array(c['d']), np.array(c['nb'])
        s0, s1 = c['s']
        ia, ib = c['ia'], c['ib']
        return frame_box(d, nb, (s0 - extra - 1, s1 + extra + 1), (ib[0] - extra, ib[1] + extra), (-ia[1] - extra, -ia[0] + extra))
    s0, s1, r0, r1, depth = info
    return _seg_box(c, s0 - extra, s1 + extra, r0 - extra, r1 + extra, depth + extra, extra)


def _main_solid(shape):
    """Płyta po połączeniach jako jedna bryła: drobne odcięte okruchy (np. róg podstawy między dwoma noskami
    w narożniku wielokąta) odpadają - przy cięciu i tak by wypadły."""
    solids = shape.Solids()
    if len(solids) <= 1:
        return shape
    solids = sorted(solids, key=lambda x: -x.Volume())
    if sum(x.Volume() for x in solids[1:]) > .05 * solids[0].Volume():
        return shape                     # duże części - nie okruchy; zostawiamy (widać, że coś jest nie tak)
    return solids[0]


def _ends_on_plane(shape, c):
    nb, plane = np.array(c['nb'], float), float(c['plane'])
    out = []
    for f in shape.Faces():
        if f.geomType() != 'PLANE':
            continue
        if abs(abs(float(np.array(f.normalAt().toTuple()) @ nb)) - 1) > 1e-4:
            continue
        if abs(float(np.array(f.Center().toTuple()) @ nb) - plane) <= TOL:
            out.append(f)
    return out


def _footprint(c, depth, grow=0.0):
    """Koniec płyty A (ściany na płaszczyźnie styku) wyciągnięty w głąb płyty B."""
    nb = np.array(c['nb'], float) * float(c['into'])
    solids = []
    for f in c['ends']:
        face = f
        if grow > 0:
            try:
                face = cq.Face.makeFromWires(f.outerWire().offset2D(grow, 'intersection')[0])
            except Exception:
                face = f
        solids.append(cq.Solid.extrudeLinear(face.translate(cq.Vector(*(-nb * .05))), cq.Vector(*(nb * (depth + .05)))))
    return solids[0] if len(solids) == 1 else kernel.boolean('union', solids[0], solids[1:])


def _clip(pieces, others):
    out = []
    for seg in pieces:
        for o in others:
            if _boxes_near(seg, o, 0.0):
                try:
                    if seg.intersect(o).Volume() > 1e-6:
                        seg = kernel.boolean('subtract', seg, [o])
                except Exception:
                    pass
        if seg.Solids():
            out.append(seg)
    return out


def _common(a, b):
    """Część wspólna dwóch brył albo None, gdy się nie stykają (np. nosek wypadający poza koniec ścianki przyciętej
    w ostrym narożniku - po prostu go nie ma)."""
    if not _boxes_near(a, b, 0.0):
        return None
    try:
        x = kernel.boolean('intersect', a, [b])
    except kernel.CadError:
        return None
    return x if x.Solids() and x.Volume() > 1e-6 else None


def _inside(shape, p):
    return kernel.point_state(shape, tuple(float(x) for x in p), 1e-5) == 'in'


CORNERS = {
    'dog': ('Psie kości', 'Okrągłe wycięcie po skosie w narożniku - najprostsze, czop wchodzi do końca.'),
    'tbone': ('T-kości', 'Wycięcie wzdłuż dłuższego boku gniazda - mniej widoczne z zewnątrz połączenia.'),
    'none': ('Bez', 'Narożniki bez wycięć - frez zostawi zaokrąglenie, czopy trzeba dopasować ręcznie (pilnik, dłuto).'),
}
TOOLS = (0.8, 1.0, 1.5, 2.0, 2.5, 3.0, 3.175, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0)


def tool_check(t, fit, tool, width=0.0):
    """Czy frez zmieści się w gniazdach: najwęższe miejsce to szerokość gniazda (grubość płyty + luz) i odstęp między
    noskami. Zwraca (komunikat albo '', największy typowy frez, który się mieści, albo 0)."""
    t, fit, tool = float(t), max(0.0, float(fit)), float(tool)
    width = float(width) or default_width(t)
    room = min(t + fit, width + fit)
    fits = max((d for d in TOOLS if d <= room + 1e-9), default=0.0)
    if tool <= 0 or tool <= room + 1e-9:
        return '', fits
    if fits:
        return (f'Frez Ø{tool:g} mm jest szerszy niż gniazdo ({room:.2f} mm) - nie wyfrezuje go, a „psie kości” zjedzą '
                f'połączenie. Użyj frezu Ø{fits:g} mm albo mniejszego.'), fits
    return f'Gniazdo ma tylko {room:.2f} mm - za wąskie na frezowanie. Użyj grubszej płyty albo lasera.', 0.0


def _face_span(face, axis, mid):
    """Długość ściany w poprzek krawędzi (w jej płaszczyźnie, prostopadle do osi freza)."""
    fn = np.array(face.normalAt(cq.Vector(*mid)).toTuple(), float)
    u = _unit(np.cross(axis, fn))
    pts = _points(face)
    return float((pts @ u).max() - (pts @ u).min())


def dogbones(shape, axis, regions, radius, style='dog'):
    """Wycięcia na frez w narożnikach wewnętrznych (krawędzie równoległe do osi freza) w obszarach połączeń - frez nie
    zrobi ostrego kąta wewnętrznego, więc czop nie wszedłby do końca gniazda.
    style: 'dog' - koło po skosie (psia kość), 'tbone' - koło wzdłuż dłuższego boku (T-kość), 'none' - bez wycięć."""
    if radius <= 0 or not regions or style == 'none':
        return shape
    axis = _unit(axis)
    cutters = []
    for edge in shape.Edges():
        if edge.geomType() != 'LINE':
            continue
        a = np.array(edge.startPoint().toTuple(), float)
        b = np.array(edge.endPoint().toTuple(), float)
        length = float(np.linalg.norm(b - a))
        if length < 1e-3 or abs(float(_unit(b - a) @ axis)) < 1 - 1e-6:
            continue
        mid = (a + b) / 2
        if not any(_inside(r, mid) for r in regions):
            continue
        faces = []
        for f in edge.ancestors(shape, 'Face').Faces():
            if f.geomType() != 'PLANE':
                continue
            fn = np.array(f.normalAt(cq.Vector(*mid)).toTuple(), float)
            if abs(float(fn @ axis)) < 1e-6:
                faces.append((f, fn))
        if len(faces) != 2:
            continue
        (f1, n1), (f2, n2) = faces
        eps = 2e-3
        inside = sum(_inside(shape, mid + eps * (s1 * n1 + s2 * n2)) for s1 in (-1, 1) for s2 in (-1, 1))
        if inside != 3:
            continue                     # tylko narożnik wewnętrzny (materiał z trzech stron)
        if style == 'tbone':
            # koło na przedłużeniu dłuższej ściany: wycięcie wchodzi w nią, krótsza (np. dno gniazda) zostaje prosta
            along = n2 if _face_span(f1, axis, mid) >= _face_span(f2, axis, mid) else n1
            centre = mid + _unit(along) * radius
        else:
            bis = n1 + n2
            if np.linalg.norm(bis) < 1e-6:
                continue
            centre = mid + _unit(bis) * radius
        lo, hi = sorted((float(a @ axis), float(b @ axis)))
        base = centre - axis * float(centre @ axis) + axis * lo
        cutters.append(cq.Solid.makeCylinder(radius, hi - lo, cq.Vector(*base), cq.Vector(*axis)))
    if not cutters:
        return shape
    return kernel.boolean('subtract', shape, cutters)


def apply_joints(panels, contacts, params, failures=None):
    """Wykonuje połączenia na kształtach płyt. panels: {id: (kształt, normalna)}; contacts: styki z polem 'joint'.
    params: method, width (0 = auto), fit, depth (ułamek grubości dla gniazd nieprzelotowych / rowków), tool (średnica freza).
    Zwraca {id: nowy kształt} (tylko zmienione płyty). failures: lista, do której trafiają (klucz styku, opis) połączeń,
    których nie udało się wykonać - wtedy pozostałe i tak się wykonują; bez listy błąd przerywa całość."""
    shapes = {pid: shp for pid, (shp, _) in panels.items()}
    axes = {pid: np.asarray(n, float) for pid, (_, n) in panels.items()}
    regions = {}
    fit = max(0.0, float(params.get('fit', 0.0)))
    ratio = min(max(float(params.get('depth', .5)), .1), .9)
    meth = params.get('method', 'cnc')
    changed = set()
    flat_cut = meth in ('laser', 'cnc')
    # narożniki na skos najpierw: przy laserze / frezarce zmieniają końce ścianek (cięcie prostopadłe), na których
    # potem opierają się noski do podstawy
    for c in sorted(contacts, key=lambda c: c['kind'] != 'M'):
        joint = c.get('joint') or 'none'
        a, b = c['a'], c['b']
        saved = (shapes[a], shapes[b], set(changed), {k: list(v) for k, v in regions.items()})
        try:
            if c['kind'] == 'M' and float(c.get('angle') or 90.0) < FLAT_MITRE:
                continue                     # ścianki prawie w jednej linii: zostaje styk na skos (skos ułamka mm), bez wczepów
            if c['kind'] == 'M' and flat_cut:
                # laser / frezarka tną prostopadle do płyty: skos zamieniony na końce proste - na przemian jedna ścianka
                # dochodzi do narożnika, druga jest cofnięta; „bez połączenia” - jedna ścianka zachodzi na całej wysokości
                width = float(params.get('width') or 0) or default_width(min(c['ta'], c['tb']))
                shapes[a], shapes[b], box = _square_corner(c, shapes[a], shapes[b], width if joint != 'none' else None, fit)
                regions.setdefault(a, []).append(box)
                regions.setdefault(b, []).append(box)
                changed |= {a, b}
                continue
            if joint == 'none':
                continue
            if not allowed(meth, joint):
                raise kernel.CadError(f"{JOINTS[joint][0]}: {WHY_NOT.get(meth, 'niedostępne dla tej metody')}.")
            if c['kind'] == 'M':
                width = float(params.get('width') or 0) or default_width(min(c['ta'], c['tb']))
                shapes[a], shapes[b] = _mitre_fingers(c, shapes[a], shapes[b], width, fit)
                changed |= {a, b}
                continue
            if c['kind'] == 'X':
                cut_a, cut_b, _ = _halving_parts(c, fit)
                shapes[a] = kernel.boolean('subtract', shapes[a], [cut_a])
                shapes[b] = kernel.boolean('subtract', shapes[b], [cut_b])
                box = _region_box(c, 1.0)
                regions.setdefault(a, []).append(box)
                regions.setdefault(b, []).append(box)
            else:
                width = float(params.get('width') or 0) or default_width(c['ta'])
                add, cut, info = _joint_parts(c, joint, width, fit, ratio)
                if c.get('ends') and add:
                    current = _ends_on_plane(shapes[a], c)      # koniec płyty po wcześniejszych zmianach (np. narożnik prostowany pod laser)
                    if current:
                        c = dict(c, ends=current)
                    foot = _footprint(c, info[4] + .05)     # nosek nie wychodzi poza koniec płyty przyciętej na skos
                    add = [x for x in (_common(seg, foot) for seg in add) if x is not None]
                    wide = _footprint(c, info[4] + .1, fit / 2)
                    cut = [x for x in (_common(seg, wide) for seg in cut) if x is not None]
                others = [shp for pid, shp in shapes.items() if pid not in (a, b)]
                add = _clip(add, others)                     # nosek nie wchodzi w trzecią płytę (narożnik trzech płyt)
                if joint != 'groove' and not add:
                    raise kernel.CadError('noski nie zmieściły się na końcu płyty')
                if cut:
                    shapes[b] = kernel.boolean('subtract', shapes[b], cut)
                if add:
                    shapes[a] = kernel.boolean('union', shapes[a], add)
                    if len(shapes[a].Solids()) > 1 and sum(x.Volume() for x in sorted(shapes[a].Solids(), key=lambda x: -x.Volume())[1:]) > 1e-3:
                        raise kernel.CadError('noski odstają od płyty')       # nie przylegają do jej końca
                box = _region_box(c, fit + 1.0, info)
                regions.setdefault(a, []).append(box)
                regions.setdefault(b, []).append(box)
            changed |= {a, b}
        except Exception as exc:
            if failures is None:
                raise
            shapes[a], shapes[b], changed, regions = saved      # to połączenie pominięte, płyty bez zmian
            failures.append((c.get('key', f'{a}:{b}'), str(exc) or exc.__class__.__name__))
    for pid in changed:
        shapes[pid] = _main_solid(shapes[pid])
    tool = float(params.get('tool', 0) or 0)
    if meth == 'cnc' and tool > 0:
        for pid in changed:
            shapes[pid] = dogbones(shapes[pid], axes[pid], regions.get(pid, []), tool / 2, params.get('corner', 'dog'))
    return {pid: shapes[pid] for pid in changed}


# ---------------------------------------------------------------------------------------------------------------
# części do cięcia: płasko, lista, DXF / STL
# ---------------------------------------------------------------------------------------------------------------
def flat_matrix(shape, t=None):
    """Macierz 4x4 kładąca płytę płasko: grubość wzdłuż Z (od 0 do t), najdłuższa prosta krawędź wzdłuż X, róg obrysu
    w (0, 0). Zwraca (macierz, grubość)."""
    info = panel_info(shape, t)
    n = info['n']
    rot = kernel.rotation_between(n, (0, 0, 1))
    best, length = None, 0.0
    for e in shape.Edges():
        if e.geomType() != 'LINE':
            continue
        a, b = np.array(e.startPoint().toTuple()), np.array(e.endPoint().toTuple())
        v = rot @ (b - a)
        if abs(v[2]) > 1e-6:
            continue
        L = float(np.linalg.norm(v))
        if L > length + 1e-6:
            best, length = v, L
    if best is not None:
        ang = -math.atan2(best[1], best[0])
        ca, sa = math.cos(ang), math.sin(ang)
        rot = np.array([[ca, -sa, 0], [sa, ca, 0], [0, 0, 1]]) @ rot
    bb = kernel.transformed(shape, rot, np.zeros(3)).BoundingBox()
    m = np.eye(4)
    m[:3, :3] = rot
    m[:3, 3] = (-bb.xmin, -bb.ymin, -bb.zmin)
    return m, info['t']


def apply_matrix(shape, m):
    m = np.asarray(m, float)
    return kernel.transformed(shape, m[:3, :3], m[:3, 3])


def flat_part(shape, t=None):
    """Płyta położona płasko: grubość wzdłuż Z (od 0 do t), najdłuższa prosta krawędź wzdłuż X, róg obrysu w (0, 0)."""
    m, t = flat_matrix(shape, t)
    return apply_matrix(shape, m), t


def part_layers(flat, t):
    """Warstwy części płaskiej: CUT - obrys i otwory przelotowe; POCKET (głębokość) - gniazda / rowki z góry lub z dołu."""
    faces = []
    for f in flat.Faces():
        if f.geomType() != 'PLANE':
            continue
        nz = f.normalAt().z
        if abs(abs(nz) - 1) > 1e-6:
            continue
        faces.append((f, nz, f.Center().z))
    if not faces:
        raise kernel.CadError('Płyta nie ma płaskich stron.')
    flatten = lambda f: f.translate(cq.Vector(0, 0, -f.Center().z))
    union = flatten(faces[0][0])
    if len(faces) > 1:
        union = union.fuse(*[flatten(f) for f, *_ in faces[1:]]).clean()
    pockets = []
    for f, nz, z in faces:
        if nz > 0 and z < t - 1e-3:
            pockets.append((round(t - z, 3), 'top', flatten(f)))
        elif nz < 0 and z > 1e-3:
            pockets.append((round(z, 3), 'bottom', flatten(f)))
    return union, pockets


def _offset_wire(wire, delta):
    """Obwód przesunięty o delta: najpierw ostre narożniki, a gdy OpenCascade nie poradzi sobie z gęstymi noskami -
    narożniki zaokrąglone promieniem połowy szerokości cięcia (tak i tak tnie wiązka); w ostateczności bez przesunięcia."""
    for kind in ('intersection', 'arc'):
        try:
            out = wire.offset2D(delta, kind)
            if out:
                return out
        except Exception:
            continue
    return [wire]


def _offset_face(face, delta):
    """Obrys przesunięty na zewnątrz o delta (otwory do środka) - kompensacja szerokości cięcia lasera."""
    if abs(delta) < 1e-9:
        return [face.outerWire()], list(face.innerWires())
    area = lambda ws: sum(cq.Face.makeFromWires(x).Area() for x in ws)
    outer = _offset_wire(face.outerWire(), delta)
    try:
        if area(outer) < cq.Face.makeFromWires(face.outerWire()).Area():
            outer = _offset_wire(face.outerWire(), -delta)        # kierunek przesunięcia zależy od orientacji obwodu
    except Exception:
        pass
    inner = []
    for w in face.innerWires():
        grown = _offset_wire(w, -delta)
        try:
            if area(grown) > cq.Face.makeFromWires(w).Area():
                grown = _offset_wire(w, delta)
        except Exception:
            pass
        inner += grown
    return outer, inner


def _add_edges(space, edges, layer, dx, dy):
    for e in edges:
        kind = e.geomType()
        if kind == 'LINE':
            a, b = e.startPoint(), e.endPoint()
            space.add_line((a.x + dx, a.y + dy), (b.x + dx, b.y + dy), dxfattribs={'layer': layer})
        elif kind == 'CIRCLE':
            circ = e._geomAdaptor().Circle()
            c, r = circ.Location(), circ.Radius()
            if e.IsClosed():
                space.add_circle((c.X() + dx, c.Y() + dy), r, dxfattribs={'layer': layer})
                continue
            p0, p1, pm = e.startPoint(), e.endPoint(), e.positionAt(.5)
            a0 = math.degrees(math.atan2(p0.y - c.Y(), p0.x - c.X()))
            a1 = math.degrees(math.atan2(p1.y - c.Y(), p1.x - c.X()))
            am = math.degrees(math.atan2(pm.y - c.Y(), pm.x - c.X()))
            ccw = lambda s, x: (x - s) % 360
            if ccw(a0, am) > ccw(a0, a1):
                a0, a1 = a1, a0              # łuk zgodny z ruchem wskazówek: zamiana końców
            space.add_arc((c.X() + dx, c.Y() + dy), r, a0, a1, dxfattribs={'layer': layer})
        else:
            pts = [e.positionAt(t) for t in np.linspace(0, 1, max(8, int(e.Length() / .5)))]
            space.add_lwpolyline([(p.x + dx, p.y + dy) for p in pts], dxfattribs={'layer': layer})


def layout(parts, gap=10.0, width=1200.0):
    """Proste ułożenie części w rzędach o szerokości width (od lewej do prawej, potem kolejny rząd)."""
    x = y = row = 0.0
    out = []
    for item in parts:
        bb = item['flat'].BoundingBox()
        w, h = bb.xlen, bb.ylen
        if x > 0 and x + w > width:
            x, y, row = 0.0, y + row + gap, 0.0
        out.append((x, y))
        x += w + gap
        row = max(row, h)
    return out


def export_dxf(parts, path, meth='cnc', labels=True, sheet_width=1200.0, kerf=None):
    """Wszystkie płyty płasko w jednym pliku DXF 1:1 mm. Warstwy: CUT (cięcie na wylot), POCKET_<głębokość>_<strona>
    (gniazda, rowki), OPIS (nazwy płyt). Laser: obrysy przesunięte o połowę szerokości cięcia."""
    import os
    import tempfile
    from pathlib import Path
    import ezdxf
    doc = ezdxf.new('R2010')
    doc.units = ezdxf.units.MM
    doc.layers.new('CUT', dxfattribs={'color': 7})
    doc.layers.new('OPIS', dxfattribs={'color': 3})
    space = doc.modelspace()
    if kerf is None:
        kerf = float(method(meth).get('kerf', 0.0)) if meth == 'laser' else 0.0
    places = layout(parts, width=sheet_width)
    for item, (dx, dy) in zip(parts, places):
        try:
            union, pockets = part_layers(item['flat'], item['t'])
        except Exception as exc:
            raise kernel.CadError(f"Płyta „{item['name']}”: nie udało się wyznaczyć obrysu ({exc}).") from exc
        for face in union.Faces():
            outer, inner = _offset_face(face, kerf / 2)
            for w in [*outer, *inner]:
                _add_edges(space, w.Edges(), 'CUT', dx, dy)
        for depth, side, face in pockets:
            layer = f"POCKET_{depth:g}mm_{'GORA' if side == 'top' else 'DOL'}"
            if layer not in doc.layers:
                doc.layers.new(layer, dxfattribs={'color': 5 if side == 'top' else 1})
            for w in face.Wires():
                _add_edges(space, w.Edges(), layer, dx, dy)
        if labels:
            bb = item['flat'].BoundingBox()
            h = max(3.0, min(12.0, min(bb.xlen, bb.ylen) / 6))
            space.add_text(item['name'], height=h, dxfattribs={'layer': 'OPIS'}).set_placement((dx + bb.xlen / 2, dy + bb.ylen / 2),
                                                                                                  align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    target = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.rccad-ply-', suffix='.dxf', dir=target.parent)
    os.close(fd)
    try:
        doc.saveas(temporary)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def export_stl(parts, folder):
    """Druk 3D: każda płyta jako osobny plik STL, położona płasko na stole. Zwraca listę zapisanych plików."""
    from pathlib import Path
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    used, out = set(), []
    for item in parts:
        base = ''.join(ch if ch.isalnum() or ch in ' -_' else '_' for ch in item['name']).strip() or 'plyta'
        name, k = base, 2
        while name.lower() in used:
            name, k = f'{base} {k}', k + 1
        used.add(name.lower())
        path = folder / f'{name}.stl'
        kernel.export_shapes([item['flat']], str(path))
        out.append(path)
    return out


def cut_list(bodies):
    """Lista elementów: nazwa, wymiary w płaszczyźnie (dł. × szer.), grubość, metoda; takie same płyty zliczone razem."""
    rows = {}
    for b in bodies:
        if not is_panel(b):
            continue
        flat, t = flat_part(b.shape, b.meta['ply'].get('t'))
        bb = flat.BoundingBox()
        size = (round(max(bb.xlen, bb.ylen), 1), round(min(bb.xlen, bb.ylen), 1), round(t, 2))
        key = (size, round(flat.Volume(), 1))
        row = rows.setdefault(key, dict(names=[], size=size, count=0))
        row['names'].append(b.name)
        row['count'] += 1
    return sorted(rows.values(), key=lambda r: (-r['size'][2], -r['size'][0], -r['size'][1]))


def drawing_parts(items):
    """Płyty rozłożone płasko obok siebie do rysunku: (kształt złożony, [(x0, y0, x1, y1, nazwa)]). items: [(nazwa, kształt, grubość)]."""
    parts = [dict(name=n, flat=flat_part(s, t)[0]) for n, s, t in items]
    if not parts:
        raise kernel.CadError('Brak płyt do rysunku.')
    sizes = [p['flat'].BoundingBox() for p in parts]
    area = sum(b.xlen * b.ylen for b in sizes)
    widest = max(b.xlen for b in sizes)
    gap = max(15.0, .18 * max(max(b.xlen, b.ylen) for b in sizes))      # miejsce na wymiary i podpisy
    width = max(widest, math.sqrt(area) * 1.7)
    places = layout(parts, gap, width)
    shapes, boxes = [], []
    for p, (x, y), bb in zip(parts, places, sizes):
        shapes.append(p['flat'].translate(cq.Vector(x, y, 0)))
        boxes.append((x, y, x + bb.xlen, y + bb.ylen, p['name']))
    return (shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)), boxes


def parts_for(bodies):
    return [dict(id=b.id, name=b.name, flat=flat_part(b.shape, b.meta['ply'].get('t'))[0], t=panel_info(b.shape, b.meta['ply'].get('t'))['t'])
            for b in bodies if is_panel(b)]


# ---------------------------------------------------------------------------------------------------------------
# rozłóż / złóż płyty (jak blacha): położenia zapamiętane w płytach, działają po przesunięciu i z biblioteki
# ---------------------------------------------------------------------------------------------------------------
def _mat(v):
    return np.asarray(v, float).reshape(4, 4) if v is not None else np.eye(4)


def _lst(m):
    return [[float(x) for x in row] for row in np.asarray(m, float)]


def fold_targets(items, flat, key=None):
    """Przekształcenia płyt przy rozkładaniu (flat=True) albo składaniu (flat=False).
    items: [dict(id, shape, t, fold)] - fold: zapamiętany stan z meta płyty (albo None).
    Stan płyty: key (wspólny dla pudełka), anchor (płyta, za którą idzie całość), flat (czy teraz leży płasko),
    M - przekształcenie z położenia w chwili przełączenia do drugiego położenia, acc - suma przesunięć / obrotów
    wykonanych potem na płycie. Druga postać płyty i = acc_kotwicy · M_i · acc_i⁻¹ · bieżąca: przesunięcie całości
    przenosi wynik razem z nią, a przestawienie pojedynczej płyty na rozkładzie (np. pod arkusz) nie psuje złożenia.
    Płyty bez pamięci przy rozkładaniu układane są same, obok siebie, w miejscu pudełka.
    Zwraca ({id: macierz 4x4}, {id: nowy stan})."""
    by_key = {}
    for it in items:
        f = it.get('fold')
        if f:
            by_key.setdefault(f.get('key'), []).append(it)
    anchors = {}
    for k, group in by_key.items():
        a = next((g for g in group if g['fold'].get('anchor')), group[0])
        anchors[k] = _mat(a['fold'].get('acc'))
    moves = {}
    for it in items:
        f = it.get('fold')
        if f and bool(f.get('flat')) != bool(flat):
            moves[it['id']] = anchors[f.get('key')] @ _mat(f.get('M')) @ np.linalg.inv(_mat(f.get('acc')))
    fresh = [it for it in items if it['id'] not in moves and flat and not (it.get('fold') and it['fold'].get('flat'))]
    if fresh:
        mats = {}
        sizes = {}
        for it in fresh:
            m, t = flat_matrix(it['shape'], it.get('t'))
            bb = apply_matrix(it['shape'], m).BoundingBox()
            mats[it['id']], sizes[it['id']] = m, (bb.xlen, bb.ylen, t)
        order = sorted(fresh, key=lambda it: -sizes[it['id']][0] * sizes[it['id']][1])
        gap = max(10.0, 2.0 * max(s[2] for s in sizes.values()))
        area = sum((s[0] + gap) * (s[1] + gap) for s in sizes.values())
        width = max(max(s[0] for s in sizes.values()), math.sqrt(area) * 1.6)
        if moves:            # obok płyt rozłożonych z pamięci
            boxes = [apply_matrix(it['shape'], moves[it['id']]).BoundingBox() for it in items if it['id'] in moves]
            origin = np.array([max(b.xmax for b in boxes) + gap, min(b.ymin for b in boxes), min(b.zmin for b in boxes)])
        else:                # w miejscu pudełka
            boxes = [it['shape'].BoundingBox() for it in fresh]
            origin = np.array([min(b.xmin for b in boxes), min(b.ymin for b in boxes), min(b.zmin for b in boxes)])
        x = y = row = 0.0
        for it in order:
            w, h, _t = sizes[it['id']]
            if x > 0 and x + w > width:
                x, y, row = 0.0, y + row + gap, 0.0
            shift = np.eye(4)
            shift[:3, 3] = origin + (x, y, 0.0)
            moves[it['id']] = shift @ mats[it['id']]
            x += w + gap
            row = max(row, h)
    if not moves:
        return {}, {}
    moved = [it for it in items if it['id'] in moves]
    keys = {(it.get('fold') or {}).get('key') for it in moved}
    old_anchor = next((it['id'] for it in moved if (it.get('fold') or {}).get('anchor')), None)
    if len(keys) == 1 and None not in keys and old_anchor is not None:
        new_key, anchor = keys.pop(), old_anchor
    else:
        new_key = key or uuid.uuid4().hex
        anchor = old_anchor or max(moved, key=lambda it: abs(it['shape'].Volume()) / max(float(it.get('t') or 1.0), 1e-9))['id']
    states = {it['id']: dict(key=new_key, anchor=it['id'] == anchor, flat=bool(flat), M=_lst(np.linalg.inv(moves[it['id']])),
                             acc=_lst(np.eye(4))) for it in moved}
    return moves, states


def fold_placed(state, matrix):
    """Stan rozłożenia po sztywnym przesunięciu / obrocie płyty (macierz 3x4 albo 4x4)."""
    mm = np.asarray(matrix, float)
    m = np.eye(4)
    m[:3, :4] = mm[:3, :4]
    return dict(state, acc=_lst(m @ _mat(state.get('acc'))))


# ---------------------------------------------------------------------------------------------------------------
# blacha: kołnierz na noski - płaska ścianka zamiast gięcia, połączona noskami z płytą, z której wychodzi
# ---------------------------------------------------------------------------------------------------------------
def edge_plate(shape, edge, t):
    """Płaska płyta, do której należy krawędź bryły (podstawa blachy, kołnierz, ścianka): największa płaska ściana przy
    krawędzi wyciągnięta w głąb materiału na grubość t. Zwraca (płyta, normalna na zewnątrz klikniętej strony)."""
    if edge.geomType() != 'LINE':
        raise kernel.CadError('Kliknij prostą krawędź blachy.')
    d = _unit(np.array(edge.endPoint().toTuple(), float) - np.array(edge.startPoint().toTuple(), float))
    best = None
    for f in edge.ancestors(shape, 'Face').Faces():
        if f.geomType() != 'PLANE':
            continue
        n = np.array(f.normalAt().toTuple(), float)
        if abs(float(n @ d)) > 1e-6:
            continue
        if best is None or f.Area() > best[0].Area():
            best = (f, n)
    if best is None:
        raise kernel.CadError('Kliknij krawędź płaskiej części blachy.')
    face, n = best
    plate = cq.Solid.extrudeLinear(face, cq.Vector(*(-n * float(t))))
    return kernel.valid(plate), n


def tab_wall(shape, edge, t, length, measure='outer', flip=False, plate=None):
    """Ścianka zamiast gięcia (kołnierz na noski), pod kątem prostym do płyty. Wymiary jak przy kołnierzu giętym:
    'outer' - zewnętrzna strona ścianki w krawędzi płyty, długość od zewnętrznej strony płyty (ścianka stoi na płycie);
    'inner' - wewnętrzna strona ścianki w krawędzi płyty, długość od wewnętrznej strony (ścianka przy boku płyty).
    Zwraca (ścianka, płyta, kierunek do góry)."""
    if plate is None:
        plate, _n = edge_plate(shape, edge, t)
    t, length = float(t), float(length)
    if measure == 'inner':
        wall, up = edge_wall(plate, edge, t, length, 'side', flip, t)
    else:
        if length <= t + 1e-6:
            raise kernel.CadError(f'Długość kołnierza mierzona od zewnątrz musi być większa niż grubość blachy ({t:g} mm).')
        wall, up = edge_wall(plate, edge, t, length - t, 'on', flip, t)
    return wall, plate, up


def hinge_matrix(wall, plate, t, gap=None):
    """Ścianka na noski położona płasko obok płyty, na której stoi (jak rozłożony kołnierz): obrót wokół zewnętrznej
    dolnej krawędzi ścianki do płaszczyzny płyty, na zewnątrz, z odstępem gap. Zwraca macierz 4x4."""
    t = float(t)
    nw = panel_info(wall, t)['n']
    npl = panel_info(plate, t)['n']
    e = _unit(np.cross(nw, npl))
    pw_, pp = _points(wall), _points(plate)
    wc, pc = pw_.mean(axis=0), pp.mean(axis=0)
    up = npl if float((wc - pc) @ npl) > 0 else -npl
    side = _unit(np.cross(up, e))
    out = side if float((wc - pc) @ side) > 0 else -side
    h = out * float((pw_ @ out).max()) + up * float((pp @ up).min()) + e * float(wc @ e)
    R = kernel.rotation_between(up, out)
    gap = max(1.0, t) if gap is None else float(gap)
    m = np.eye(4)
    m[:3, :3] = R
    m[:3, 3] = h - R @ h + out * gap
    return m


def frame_matrix(o, x, y, z):
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = _unit(x), _unit(y), _unit(z), np.asarray(o, float)
    return m
