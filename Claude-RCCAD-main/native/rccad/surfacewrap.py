"""Szkic owinięty na bryle: walec, ścianka otworu, ostry albo zaokrąglony narożnik (wypukły i wklęsły).

Szkic leży na płaszczyźnie stycznej do bryły. Pod nim jest „pas” ścian biegnących wzdłuż jednej osi (a): płaskie ściany
i wycinki walców o osi równoległej do a, połączone krawędziami równoległymi do a. Taki pas da się rozwinąć na płaszczyznę
bez rozciągania, więc szkic przenosi się na bryłę dokładnie (izometrycznie): długości mierzone po powierzchni są takie
jak na szkicu. Współrzędne szkicu: t - wzdłuż osi pasa, s - w poprzek (po powierzchni).

Narzędzie wyciągnięcia / wycięcia składa się z kawałków: każda ściana pasa dostaje swoją część szkicu (płaska - przez
przesunięcie i obrót, walcowa - przez mapę na parametrach walca, krzywe zostają dokładne), pogrubioną prostopadle do
powierzchni. W ostrym narożniku, gdzie kawałki się rozchodzą (wypukły + dodanie, wklęsły + wycięcie), dochodzi klin,
który zamyka narożnik na ostro - jak przy odsunięciu ścian.

Kształty, których nie da się tak rozwinąć (stożek, kula, krawędź łukowa, wierzchołek), zwracają None - wtedy działa
dawne przybliżone rzutowanie (kernel)."""
from __future__ import annotations

import math

import cadquery as cq
import numpy as np

import threading

_LOCK = threading.Lock()
EPS = .01                 # narzędzie zachodzi tyle w bryłę (dodanie) albo zaczyna się tyle nad nią (wycięcie)
TOL = 1e-6
SNAP = .25                # tyle (mm) może początek szkicu odstawać od powierzchni (punkt wskazany na siatce, cięciwa walca)


class WrapError(Exception):
    """Błąd użytkowy (komunikat dla użytkownika)."""


def _unit(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def _vec(p):
    if hasattr(p, 'toTuple'):
        return np.asarray(p.toTuple(), float)
    if hasattr(p, 'X'):
        return np.array([p.X(), p.Y(), p.Z()], float)
    return np.asarray(p, float)


# ------------------------------------------------------------------ odcinki pasa
class Seg:
    """Jedna ściana pasa w zakresie s0..s1. plane: point = E + (s - s_ref) d + t a; arc: punkt na okręgu o środku C."""

    def __init__(self, kind, s0, s1, face, a, **kw):
        self.kind, self.s0, self.s1, self.face, self.a = kind, float(s0), float(s1), face, np.asarray(a, float)
        self.__dict__.update(kw)

    def point(self, s, t):
        if self.kind == 'plane':
            return self.E + (s - self.s_ref) * self.d + t * self.a
        phi = (s - self.s_ref) / self.r
        return self.C + self.r * (math.cos(phi) * self.e + math.sin(phi) * self.w) + t * self.a

    def normal(self, s):
        """Normalna na zewnątrz bryły."""
        if self.kind == 'plane':
            return self.n
        phi = (s - self.s_ref) / self.r
        return self.out * (math.cos(phi) * self.e + math.sin(phi) * self.w)

    def tangent(self, s):
        if self.kind == 'plane':
            return self.d
        phi = (s - self.s_ref) / self.r
        return -math.sin(phi) * self.e + math.cos(phi) * self.w


class Strip:
    def __init__(self, origin, a, sdir, nS, a2d, segs, folds, full=None):
        self.O, self.a, self.sdir, self.nS, self.a2d = origin, a, sdir, nS, a2d
        self.segs = sorted(segs, key=lambda g: g.s0)
        self.folds = folds          # (s, t_lo, t_hi, seg przed, seg za)
        self.full = full            # pełny walec: (s_min, s_max) - szkic szerszy nachodziłby na siebie

    def st(self, p):
        d = np.asarray(p, float) - self.O
        return float(d @ self.sdir), float(d @ self.a2d)

    def seg_at(self, s):
        for g in self.segs:
            if g.s0 - 1e-9 <= s <= g.s1 + 1e-9:
                return g
        return self.segs[0] if s < self.segs[0].s0 else self.segs[-1]

    def map_point(self, p, lift=0.0):
        s, t = self.st(p)
        g = self.seg_at(s)
        q = g.point(s, t)
        if not lift:
            return q
        n = g.normal(s)
        for s_b, _, _, gA, gB in self.folds:
            if abs(s - s_b) < lift * 2:          # przy krawędzi: w stronę dwusiecznej (we wklęsłym narożniku nie na drugiej ścianie)
                n = _unit(gA.normal(s_b) + gB.normal(s_b))
                break
        return q + n * lift

    def sketch_point(self, s, t):
        return self.O + s * self.sdir + t * self.a2d


# ------------------------------------------------------------------ topologia
def _faces_of_edge(shape):
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    data = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape.wrapped, TopAbs_EDGE, TopAbs_FACE, data)
    return data


def _neighbour(shape, emap, edge, face):
    """Druga ściana przy krawędzi."""
    from OCP.TopoDS import TopoDS
    key = emap.FindIndex(edge.wrapped)
    if not key:
        return None
    for f in emap.FindFromIndex(key):
        other = cq.Face(TopoDS.Face_s(f))
        if not other.wrapped.IsSame(face.wrapped):
            return other
    return None


def _line(edge):
    if edge.geomType() != 'LINE':
        return None
    p, q = _vec(edge.startPoint()), _vec(edge.endPoint())
    if np.linalg.norm(q - p) < 1e-9:
        return None
    return p, _unit(q - p)


def _cyl(face):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    ad = BRepAdaptor_Surface(face.wrapped)
    c = ad.Cylinder()
    ax = c.Axis()
    return _vec(ax.Location()), _unit(_vec(ax.Direction())), float(c.Radius())


def _plane_normal(face):
    return _unit(_vec(face.normalAt(face.Center())))


def _on_face(face, p, tol=1e-5):
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    from OCP.gp import gp_Pnt
    try:
        if BRepClass_FaceClassifier(face.wrapped, gp_Pnt(*[float(c) for c in p]), tol).State() in (TopAbs_IN, TopAbs_ON):
            return face.distance(cq.Vertex.makeVertex(*[float(c) for c in p])) < max(tol * 10, 1e-4)
        return False
    except Exception:
        return False


def _material_out(shape, face, p, n):
    """+1, gdy n wskazuje na zewnątrz bryły w punkcie p ściany."""
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt
    for eps in (1e-3, 1e-2, 5e-2):
        q = np.asarray(p) - n * eps
        r = np.asarray(p) + n * eps
        inside = BRepClass3d_SolidClassifier(shape.wrapped, gp_Pnt(*q), 1e-7).State() == TopAbs_IN
        outside = BRepClass3d_SolidClassifier(shape.wrapped, gp_Pnt(*r), 1e-7).State() == TopAbs_IN
        if inside != outside:
            return 1 if inside else -1
    return 1


def _face_point(face):
    """Punkt leżący na ścianie (nie w jej otworze) - do ustalenia, po której stronie jest materiał.

    Face.positionAt bierze surowe parametry powierzchni, nie ułamki 0..1 - próbki trzeba przeliczyć na zakres UV ściany.
    (Dawniej punkty (.5, .5) itd. trafiały poza ścianę, gdy jej zakres nie obejmował 0..1 - np. wklęsłe zaokrąglenie
    o kącie 4,4..6,7 rad - i wklęsły walec był brany za wypukły: wyciągnięcie szło w drugą stronę.)"""
    from OCP.BRepTools import BRepTools
    try:
        u0, u1, v0, v1 = BRepTools.UVBounds_s(face.wrapped)
    except Exception:
        return None
    fractions = [(.5, .5), (.25, .5), (.75, .5), (.5, .25), (.5, .75), (.2, .2), (.8, .8), (.2, .8), (.8, .2), (.1, .5), (.9, .5)]
    fractions += [(a, b) for a in np.linspace(.05, .95, 10) for b in np.linspace(.05, .95, 10)]
    for fu, fv in fractions:
        p = _vec(face.positionAt(u0 + fu * (u1 - u0), v0 + fv * (v1 - v0)))
        if _on_face(face, p):
            return p
    return None


def _cyl_out(solid, face):
    """+1 - materiał wewnątrz promienia (walec), -1 - na zewnątrz (otwór)."""
    C0, ax, r = _cyl(face)
    p = _face_point(face)
    if p is None:
        return 1
    radial = _unit((p - C0) - float((p - C0) @ ax) * ax)
    return _material_out(solid, face, p, radial)


def _plane_out(solid, face, fallback):
    n0 = _plane_normal(face)
    p = _face_point(face)
    return n0 * _material_out(solid, face, p if p is not None else fallback, n0)


def _into(face, line_p, a, candidates, step):
    """Kierunek (z listy) od krawędzi do wnętrza ściany."""
    for d in candidates:
        for k in (1, 3, 10):
            if _on_face(face, line_p + d * step * k):
                return d
    return None


# ------------------------------------------------------------------ budowa pasa
_CACHE = []          # (bryła, początek, normalna, zasięg, pas) - litery jednego napisu mają wspólny pas
_CACHE_SIZE = 24


def build_strip(shape, origin, normal, extent):
    """Pas ścian pod szkicem (z pamięci, gdy ta sama bryła, początek i kierunek, a zasięg mieści się w policzonym)."""
    key = (tuple(round(float(c), 9) for c in origin), tuple(round(float(c), 9) for c in normal))
    with _LOCK:
        for item in _CACHE:
            if item[0] is shape and item[1] == key and item[2][0] <= extent[0] and item[2][1] >= extent[1]:
                return item[3]
        wider = next((item[2] for item in _CACHE if item[0] is shape and item[1] == key), None)
    if wider is not None:
        extent = (min(extent[0], wider[0]), max(extent[1], wider[1]))
    strip = _build_strip(shape, origin, normal, extent)
    with _LOCK:
        _CACHE[:] = [item for item in _CACHE if not (item[0] is shape and item[1] == key)]
        _CACHE.insert(0, (shape, key, extent, strip))
        del _CACHE[_CACHE_SIZE:]
    return strip


def _build_strip(shape, origin, normal, extent):
    """Pas ścian pod szkicem. extent = (s_min, s_max) szkicu po rzucie (potrzebny zasięg). None - kształt nieobsługiwany."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    O = np.asarray(origin, float)
    nS = _unit(normal)
    solids = shape.Solids()
    if len(solids) != 1:
        return None
    solid = solids[0]
    dss = BRepExtrema_DistShapeShape(cq.Vertex.makeVertex(*O).wrapped, solid.wrapped)
    dss.Perform()
    if not dss.IsDone() or dss.NbSolution() < 1:
        return None
    P = _vec(dss.PointOnShape2(1))
    box = solid.BoundingBox()
    size = max(box.xlen, box.ylen, box.zlen)
    tol = max(1e-5, size * 1e-7)
    emap = _faces_of_edge(solid)
    seed = None              # ('edge', edge, fA, fB), ('vedge', None, fA, fB, a, punkt) albo ('face', f)
    faces = []
    if float(np.linalg.norm(P - O)) < tol * 10 and not dss.InnerSolution():
        faces = [f for f in solid.Faces() if f.distance(cq.Vertex.makeVertex(*P)) < tol * 10]
    if faces:
        if len(faces) == 1:
            seed = ('face', faces[0])
        elif len(faces) == 2:
            common = [e for e in faces[0].Edges() if any(e.wrapped.IsSame(g.wrapped) for g in faces[1].Edges())
                      and e.distance(cq.Vertex.makeVertex(*P)) < tol * 10]
            if len(common) != 1 or _line(common[0]) is None:
                return None
            seed = ('edge', common[0], faces[0], faces[1])
        else:
            return None
    else:
        # Początek szkicu nie leży dokładnie na bryle:
        # - punkt wskazano na siatce wyświetlania: na walcu siatka to cięciwy, więc punkt leży setne części milimetra
        #   pod powierzchnią (wypukły walec) albo nad nią (otwór) - dawniej szkic przechodził wtedy na przybliżony rzut,
        #   który przebijał bryłę na wylot i dokładał kształt także po drugiej stronie walca;
        # - albo przykrył go wcześniejszy wyciągnięty kształt z tego samego szkicu.
        # Pierwotne ściany, na których go narysowano, nadal przechodzą (prawie) przez ten punkt.
        reach = max(abs(extent[0]), abs(extent[1])) + 1
        snap = max(tol * 10, min(SNAP, size * 2e-3))
        through = []                 # (odchyłka od powierzchni, ściana)
        for f in solid.Faces():
            kind = f.geomType()
            if kind == 'PLANE':
                dev = abs(float((O - _vec(f.Center())) @ _plane_normal(f)))
            elif kind == 'CYLINDER':
                C0, ax, r = _cyl(f)
                d = (O - C0) - float((O - C0) @ ax) * ax
                dev = abs(float(np.linalg.norm(d)) - r)
            else:
                continue
            if dev < snap and f.distance(cq.Vertex.makeVertex(*O)) < reach:
                through.append((dev, f))
        best = min((dev for dev, _ in through), default=None)
        if best is not None:
            through = [f for dev, f in through if dev <= best + tol * 10]     # tylko powierzchnie najbliższe punktowi
        cyl = [f for f in through if f.geomType() == 'CYLINDER']
        planes = []
        for f in through:
            if f.geomType() == 'PLANE' and not any(abs(abs(float(_plane_normal(f) @ _plane_normal(g))) - 1) < 1e-6 for g in planes):
                planes.append(f)
        P = O
        if cyl and len({tuple(np.round(_cyl(f)[0], 6)) for f in cyl}) == 1:
            seed = ('face', max(cyl, key=lambda f: -f.distance(cq.Vertex.makeVertex(*O))))
            C0, ax, r = _cyl(seed[1])
            radial = (O - C0) - float((O - C0) @ ax) * ax
            P = O - radial + _unit(radial) * r                 # punkt na prawdziwej powierzchni walca
        elif len(planes) == 1:
            seed = ('face', planes[0])
            n0 = _plane_normal(planes[0])
            P = O - n0 * float((O - _vec(planes[0].Center())) @ n0)
        elif len(planes) == 2:
            line = np.cross(_plane_normal(planes[0]), _plane_normal(planes[1]))
            if np.linalg.norm(line) < 1e-6:
                return None
            seed = ('vedge', None, planes[0], planes[1], _unit(line), O)
        else:
            return None

    # oś pasa
    if seed[0] == 'edge':
        a = _line(seed[1])[1]
    elif seed[0] == 'vedge':
        a = seed[4]
    elif seed[1].geomType() == 'CYLINDER':
        a = _cyl(seed[1])[1]
    elif seed[1].geomType() == 'PLANE':
        a = None
    else:
        return None
    if a is None:
        # płaska ściana: szkic przenosi się bez zmian (rzut na ścianę), bez owijania
        f = seed[1]
        n = _plane_out(solid, f, P)
        x = np.cross(nS, [0, 0, 1.0]) if abs(nS[2]) < .9 else np.cross(nS, [1.0, 0, 0])
        a = _unit(np.cross(x, nS))
        a2d = a
        sdir = _unit(np.cross(a2d, nS))
        d = _unit(np.cross(a, n))
        if float(d @ sdir) < 0:
            d = -d
        E = P - float((P - O) @ a) * a - float((P - O) @ sdir) * d
        g = Seg('plane', -math.inf, math.inf, f, a, E=E, d=d, n=n, s_ref=0.0)
        return Strip(O, a, sdir, nS, a2d, [g], [])
    a = _unit(a)
    a2d = a - float(a @ nS) * nS
    if np.linalg.norm(a2d) < .999:
        return None                          # płaszczyzna szkicu nie zawiera osi pasa
    a2d = _unit(a2d)
    sdir = _unit(np.cross(a2d, nS))
    step = max(size * 1e-4, 1e-3)

    def t_of(p):
        return float((np.asarray(p) - O) @ a2d)

    def s_of(p):
        return float((np.asarray(p) - O) @ sdir)

    segs, folds = [], []
    smin, smax = extent
    margin = max(1e-3, (smax - smin) * .01)

    def plane_seg(face, Eb, s_b, direction, edge_dir_ok=True):
        """Płaska ściana od krawędzi (punkt Eb przy t=0, s=s_b) w stronę direction (+1/-1)."""
        n0 = _plane_normal(face)
        cands = [_unit(np.cross(n0, a)), -_unit(np.cross(n0, a))]
        din = None
        for t in _probe_ts(face):          # krawędź może przylegać tylko kawałkiem: szukaj wzdłuż niej
            din = _into(face, Eb + a * t, a, cands, step)
            if din is not None:
                break
        if din is None:
            return None, None
        n = _plane_out(solid, face, Eb + din * step * 3 + a * t)
        # najdalsza krawędź ściany równoległa do osi
        far, far_edge = None, None
        for e in face.Edges():
            ln = _line(e)
            if ln is None or abs(abs(float(ln[1] @ a)) - 1) > 1e-6:
                continue
            dist = float((ln[0] - Eb) @ din)
            if dist > tol * 100 and (far is None or dist > far + tol * 100 or (abs(dist - far) <= tol * 100 and e.Length() > far_edge.Length())):
                far, far_edge = dist, e
        L = far if far is not None else math.inf
        if direction > 0:
            g = Seg('plane', s_b, s_b + L, face, a, E=Eb, d=din, n=n, s_ref=s_b)
        else:
            g = Seg('plane', s_b - L, s_b, face, a, E=Eb, d=-din, n=n, s_ref=s_b)
        return g, far_edge

    def arc_seg(face, Pb, s_b, direction, seed_point=False):
        """Wycinek walca: od punktu Pb (na krawędzi albo punkt startowy) w stronę direction."""
        C0, ax, r = _cyl(face)
        if abs(abs(float(ax @ a)) - 1) > 1e-6:
            return None, None, None
        C = C0 + float((O - C0) @ a) * a
        rad = (Pb - C0) - float((Pb - C0) @ a) * a
        if abs(np.linalg.norm(rad) - r) > max(tol * 100, r * 1e-4):
            return None, None, None
        e = _unit(rad)
        tan = _unit(np.cross(a, e))
        out = _cyl_out(solid, face)
        # zakres kąta ściany (w układzie e, tan)
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepTools import BRepTools
        ad = BRepAdaptor_Surface(face.wrapped)
        cyl = ad.Cylinder()
        xd = _vec(cyl.XAxis().Direction())
        yd = _vec(cyl.YAxis().Direction())          # u liczone od X do Y (układ walca bywa lewoskrętny)
        axd = _vec(cyl.Axis().Direction())
        u0, u1, _, _ = BRepTools.UVBounds_s(face.wrapped)
        full = (u1 - u0) >= 2 * math.pi - 1e-6
        uP = math.atan2(float(e @ yd), float(e @ xd))
        while uP < u0 - 1e-7:
            uP += 2 * math.pi
        while uP > u1 + 1e-7:
            uP -= 2 * math.pi
        du = -math.sin(uP) * xd + math.cos(uP) * yd
        rel = 1.0 if float(tan @ du) > 0 else -1.0                     # kierunek tan względem rosnącego u
        lo, hi = sorted((rel * (u0 - uP), rel * (u1 - uP)))           # kąty względem e w stronę tan
        if seed_point:
            sigma = 1.0 if float(tan @ sdir) > 0 else -1.0
            w = tan * sigma
            lo_s, hi_s = (lo, hi) if sigma > 0 else (-hi, -lo)
            if full:
                lo_s, hi_s = -math.pi, math.pi
            g = Seg('arc', s_b + lo_s * r, s_b + hi_s * r, face, a, C=C, r=r, e=e, w=w, out=out, s_ref=s_b, full=full)
            return g, (lo_s, hi_s), (u0, u1, xd, yd, axd, rel, uP)
        # od krawędzi: wnętrze ściany po tej stronie, gdzie jest zakres kąta
        if hi > 1e-7 and lo > -1e-7:
            into, span = tan, hi
        elif lo < -1e-7 and hi < 1e-7:
            into, span = -tan, -lo
        else:
            return None, None, None
        w = into if direction > 0 else -into
        if direction > 0:
            g = Seg('arc', s_b, s_b + span * r, face, a, C=C, r=r, e=e, w=w, out=out, s_ref=s_b, full=False)
        else:
            g = Seg('arc', s_b - span * r, s_b, face, a, C=C, r=r, e=e, w=w, out=out, s_ref=s_b, full=False)
        return g, None, None

    def _probe_ts(face):
        ts = sorted({round(t_of(v.toTuple()), 9) for v in face.Vertices()})
        if len(ts) < 2:
            return [0.0]
        mids = [(p + q) / 2 for p, q in zip(ts[:-1], ts[1:])]
        mid = (ts[0] + ts[-1]) / 2
        return [mid, *sorted(mids, key=lambda m: abs(m - mid))]

    def boundary_edge(face, point, axis_dir):
        """Krawędź-prosta równoległa do osi przechodząca przez punkt (granica wycinka walca)."""
        best = None
        for e in face.Edges():
            ln = _line(e)
            if ln is None or abs(abs(float(ln[1] @ axis_dir)) - 1) > 1e-6:
                continue
            off = (point - ln[0]) - float((point - ln[0]) @ ln[1]) * ln[1]
            if np.linalg.norm(off) < max(tol * 100, 1e-4) and (best is None or e.Length() > best.Length()):
                best = e
        return best

    def edge_t_range(edge):
        return tuple(sorted((t_of(_vec(edge.startPoint())), t_of(_vec(edge.endPoint())))))

    def fold_point(edge):
        ln = _line(edge)
        p = ln[0]
        return p - float((p - O) @ a) * a

    def walk(seg, edge, direction):
        """Dalej po ścianach za krawędzią edge (koniec seg)."""
        for _ in range(16):
            if edge is None:
                return
            s_b = seg.s1 if direction > 0 else seg.s0
            if (direction > 0 and s_b > smax + margin) or (direction < 0 and s_b < smin - margin):
                return
            nxt = _neighbour(solid, emap, edge, seg.face)
            if nxt is None:
                return
            Eb = seg.point(s_b, 0.0)
            if nxt.geomType() == 'PLANE':
                g, far = plane_seg(nxt, Eb, s_b, direction)
            elif nxt.geomType() == 'CYLINDER':
                g, _, _ = arc_seg(nxt, Eb, s_b, direction)
                far = None
                if g is not None:
                    end = g.s1 if direction > 0 else g.s0
                    far = boundary_edge(nxt, g.point(end, 0.0), a)
            else:
                return
            if g is None:
                return
            lo, hi = edge_t_range(edge)
            folds.append((s_b, lo, hi, seg if direction > 0 else g, g if direction > 0 else seg))
            segs.append(g)
            seg, edge = g, far

    if seed[0] in ('edge', 'vedge'):
        edge, fA, fB = seed[1], seed[2], seed[3]
        if edge is not None:
            Eb = fold_point(edge)
        else:
            Eb = seed[5] - float((seed[5] - O) @ a) * a
        s_b = s_of(Eb)
        parts = []
        for f in (fA, fB):
            if f.geomType() == 'PLANE':
                n0 = _plane_normal(f)
                cands = [_unit(np.cross(n0, a)), -_unit(np.cross(n0, a))]
                din = None
                for t in [float((P - Eb) @ a), *_probe_ts(f)]:
                    din = _into(f, Eb + a * t, a, cands, step)
                    if din is not None:
                        break
                if din is None:
                    return None
                parts.append((f, 1 if float(din @ sdir) > 0 else -1))
            elif f.geomType() == 'CYLINDER':
                C0, ax, r = _cyl(f)
                rad = _unit((Eb - C0) - float((Eb - C0) @ ax) * ax)
                tan = _unit(np.cross(ax, rad))
                d = tan if _on_face(f, Eb + a * float((P - Eb) @ a) + tan * step * 3) else -tan
                parts.append((f, 1 if float(d @ sdir) > 0 else -1))
            else:
                return None
        if parts[0][1] == parts[1][1]:
            return None
        lo, hi = edge_t_range(edge) if edge is not None else (-1e4, 1e4)
        made = {}
        for f, side in parts:
            if f.geomType() == 'PLANE':
                g, far = plane_seg(f, Eb, s_b, side)
            else:
                g, _, _ = arc_seg(f, Eb, s_b, side)
                far = None
                if g is not None:
                    end = g.s1 if side > 0 else g.s0
                    far = boundary_edge(f, g.point(end, 0.0), a)
            if g is None:
                return None
            segs.append(g)
            made[side] = (g, far)
        folds.append((s_b, lo, hi, made[-1][0], made[1][0]))
        walk(made[1][0], made[1][1], 1)
        walk(made[-1][0], made[-1][1], -1)
    else:
        f = seed[1]
        g, span, info = arc_seg(f, P, s_of(P), 1, seed_point=True)
        if g is None:
            return None
        segs.append(g)
        if g.full:
            return Strip(O, a, sdir, nS, a2d, segs, [], full=(g.s0, g.s1))
        for direction in (1, -1):
            end = g.s1 if direction > 0 else g.s0
            walk(g, boundary_edge(f, g.point(end, 0.0), a), direction)
    return Strip(O, a, sdir, nS, a2d, segs, folds)


# ------------------------------------------------------------------ geometria 2D (płaszczyzna szkicu)
def _faces(shape):
    if shape is None:
        return []
    return [f for f in cq.Shape.cast(shape.wrapped if hasattr(shape, 'wrapped') else shape).Faces()] if not isinstance(shape, cq.Face) else [shape]


def _common(a, b):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    op = BRepAlgoAPI_Common(a.wrapped, b.wrapped)
    op.Build()
    if not op.IsDone():
        raise WrapError('common')
    return [f for f in cq.Shape.cast(op.Shape()).Faces() if f.Area() > 1e-9]


def _rect(strip, s0, s1, t0, t1):
    pts = [strip.sketch_point(s, t) for s, t in ((s0, t0), (s1, t0), (s1, t1), (s0, t1))]
    return cq.Face.makeFromWires(cq.Wire.makePolygon([cq.Vector(*p) for p in pts], close=True))


def _trsf(o1, x1, y1, o2, x2, y2):
    from OCP.gp import gp_Ax3, gp_Pnt, gp_Dir, gp_Trsf
    def ax(o, x, y):
        z = _unit(np.cross(x, y))
        return gp_Ax3(gp_Pnt(*[float(c) for c in o]), gp_Dir(*[float(c) for c in z]), gp_Dir(*[float(c) for c in x]))
    tr = gp_Trsf()
    tr.SetDisplacement(ax(o1, x1, y1), ax(o2, x2, y2))
    return tr


def _apply(shape, tr):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    return cq.Shape.cast(BRepBuilderAPI_Transform(shape.wrapped, tr, True).Shape())


def _plane_piece(strip, g, region):
    """Przesunięcie i obrót części szkicu na płaską ścianę."""
    tr = _trsf(strip.sketch_point(g.s_ref, 0.0), strip.sdir, strip.a2d, g.E, g.d, g.a)
    return [_apply(f, tr) for f in region], tr


def _bspline2d(edge, fn):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRep import BRep_Tool
    from OCP.Geom import Geom_TrimmedCurve
    from OCP.GeomConvert import GeomConvert
    from OCP.Geom2d import Geom2d_BSplineCurve
    from OCP.TColgp import TColgp_Array1OfPnt2d
    from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
    from OCP.gp import gp_Pnt2d
    ad = BRepAdaptor_Curve(edge)
    f, l = ad.FirstParameter(), ad.LastParameter()
    curve = BRep_Tool.Curve_s(edge, f, l)
    bs = GeomConvert.CurveToBSplineCurve_s(Geom_TrimmedCurve(curve, f, l))
    n = bs.NbPoles()
    poles = TColgp_Array1OfPnt2d(1, n)
    weights = TColStd_Array1OfReal(1, n)
    for i in range(1, n + 1):
        u, v = fn(_vec(bs.Pole(i)))
        poles.SetValue(i, gp_Pnt2d(u, v))
        weights.SetValue(i, bs.Weight(i))
    k = bs.NbKnots()
    knots = TColStd_Array1OfReal(1, k)
    mults = TColStd_Array1OfInteger(1, k)
    for i in range(1, k + 1):
        knots.SetValue(i, bs.Knot(i))
        mults.SetValue(i, bs.Multiplicity(i))
    return Geom2d_BSplineCurve(poles, weights, knots, mults, bs.Degree(), bs.IsPeriodic()), bs.FirstParameter(), bs.LastParameter()


def _arc_face(strip, g, face2d, radius):
    """Część szkicu na walcu (o promieniu radius - ten sam podział kąta co na powierzchni pasa)."""
    from OCP.Geom import Geom_CylindricalSurface
    from OCP.gp import gp_Ax3, gp_Pnt, gp_Dir
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.BRepLib import BRepLib
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.ShapeFix import ShapeFix_Face
    sigma = 1.0 if float(g.w @ np.cross(g.a, g.e)) > 0 else -1.0
    surf = Geom_CylindricalSurface(gp_Ax3(gp_Pnt(*[float(c) for c in g.C]), gp_Dir(*[float(c) for c in g.a]),
                                          gp_Dir(*[float(c) for c in g.e])), float(radius))

    def fn(p):
        s, t = strip.st(p)
        return sigma * (s - g.s_ref) / g.r, t

    def wire(w):
        mk = BRepBuilderAPI_MakeWire()
        ex = BRepTools_WireExplorer(w.wrapped)
        while ex.More():
            e = ex.Current()
            c2, f, l = _bspline2d(e, fn)
            edge = BRepBuilderAPI_MakeEdge(c2, surf, f, l).Edge()
            if e.Orientation() == TopAbs_REVERSED:
                edge.Reverse()
            mk.Add(edge)
            ex.Next()
        if not mk.IsDone():
            raise WrapError('wire')
        return mk.Wire()

    from OCP.BRepTopAdaptor import BRepTopAdaptor_FClass2d
    from OCP.TopAbs import TopAbs_IN, TopAbs_OUT
    from OCP.TopoDS import TopoDS

    def oriented(w, outer):
        # obrys zewnętrzny przeciwnie do ruchu wskazówek (punkt w nieskończoności na zewnątrz), otwory odwrotnie
        test = BRepBuilderAPI_MakeFace(surf, w, True).Face()
        state = BRepTopAdaptor_FClass2d(test, 1e-7).PerformInfinitePoint()
        if (outer and state == TopAbs_IN) or (not outer and state == TopAbs_OUT):
            return TopoDS.Wire_s(w.Reversed())
        return w

    maker = BRepBuilderAPI_MakeFace(surf, oriented(wire(face2d.outerWire()), True), True)
    for inner in face2d.innerWires():
        maker.Add(oriented(wire(inner), False))
    f = maker.Face()
    BRepLib.BuildCurves3d_s(f)
    fix = ShapeFix_Face(f)
    fix.Perform()
    return cq.Face(fix.Face())


def _region(strip, face, g):
    """Część szkicu na ścianie g (w płaszczyźnie szkicu), przycięta do ściany."""
    big = 1e4
    s0 = max(g.s0, -big)
    s1 = min(g.s1, big)
    bb = face.BoundingBox()
    span = max(bb.xlen, bb.ylen, bb.zlen) + 10
    tc = strip.st(face.Center().toTuple())[1]
    slab = _rect(strip, s0, s1, tc - span, tc + span)
    region = _common(face, slab)
    if not region:
        return []
    if g.kind == 'plane':
        tr = _trsf(strip.sketch_point(g.s_ref, 0.0), strip.sdir, strip.a2d, g.E, g.d, g.a)
        flat = _apply(g.face, tr.Inverted())
        out = []
        for r in region:
            out += _common(r, flat)
        return out
    ts = [strip.st(v.toTuple())[1] for v in g.face.Vertices()]
    for e in g.face.Edges():
        ts += [strip.st(e.positionAt(k).toTuple())[1] for k in (.25, .5, .75)]
    if not ts:
        return region
    lim = _rect(strip, s0 - 1, s1 + 1, min(ts), max(ts))
    out = []
    for r in region:
        out += _common(r, lim)
    return out


def _prism(face, vec):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    return cq.Shape.cast(BRepPrimAPI_MakePrism(face.wrapped, gp_Vec(*[float(c) for c in vec]), False, True).Shape())


def _thicken(face, direction, thickness):
    """Pogrubienie ściany w stronę direction (wektor w środku ściany)."""
    from OCP.BRepOffset import BRepOffset_MakeSimpleOffset
    c = face.Center()
    try:
        from OCP.BRepTools import BRepTools
        u0, u1, v0, v1 = BRepTools.UVBounds_s(face.wrapped)
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.gp import gp_Pnt, gp_Vec
        ad = BRepAdaptor_Surface(face.wrapped)
        p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
        ad.D1((u0 + u1) / 2, (v0 + v1) / 2, p, du, dv)
        n = _unit(np.cross(_vec(du), _vec(dv)))
        from OCP.TopAbs import TopAbs_REVERSED
        if face.wrapped.Orientation() == TopAbs_REVERSED:
            n = -n
    except Exception:
        n = _vec(face.normalAt(c))
    sign = 1.0 if float(n @ direction) > 0 else -1.0
    solid = None
    try:
        solid = face.thicken(sign * thickness)
    except Exception:
        solid = None
    if solid is None or not solid.isValid() or abs(solid.Volume()) < 1e-12:
        so = BRepOffset_MakeSimpleOffset(face.wrapped, sign * thickness)
        so.SetBuildSolidFlag(True)
        so.Perform()
        if not so.IsDone():
            raise WrapError('offset')
        found = cq.Shape.cast(so.GetResultShape()).Solids()
        if not found:
            raise WrapError('offset')
        solid = found[0]
    solid = solid.Solids()[0] if solid.Solids() else solid
    if solid.Volume() < 0:                  # bryła odwrócona na lewą stronę (zależnie od orientacji ściany)
        solid = cq.Solid(solid.wrapped.Reversed())
    return solid


def _in_face(face, p):
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt
    return BRepClass_FaceClassifier(face.wrapped, gp_Pnt(*[float(c) for c in p]), 1e-7).State() == TopAbs_IN


def _wedges(strip, face, height, operation):
    """Kliny w ostrych narożnikach, w których kawałki narzędzia się rozchodzą."""
    sign = 1.0 if operation == 'join' else -1.0
    out = []
    for s_b, lo, hi, gA, gB in strip.folds:
        nA, nB = gA.normal(s_b), gB.normal(s_b)
        if float(np.linalg.norm(np.cross(nA, nB))) < math.sin(math.radians(.5)):
            continue                                     # przejście styczne (zaokrąglenie)
        tB = gB.tangent(s_b)
        convex = float(nA @ tB) < 0
        if convex != (operation == 'join'):
            continue                                     # kawałki zachodzą na siebie - klin niepotrzebny
        line = cq.Edge.makeLine(cq.Vector(*strip.sketch_point(s_b, lo)), cq.Vector(*strip.sketch_point(s_b, hi)))
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
        op = BRepAlgoAPI_Common(face.wrapped, line.wrapped)
        op.Build()
        for e in cq.Shape.cast(op.Shape()).Edges():
            ta, tb = sorted((strip.st(e.startPoint().toTuple())[1], strip.st(e.endPoint().toTuple())[1]))
            if tb - ta < 1e-6:
                continue
            # szkic tylko dochodzi do krawędzi (nie przechodzi przez nią) - bez klina
            tm = (ta + tb) / 2
            delta = max(1e-4, min(.05, (tb - ta) * .01))
            if not (_in_face(face, strip.sketch_point(s_b - delta, tm)) and _in_face(face, strip.sketch_point(s_b + delta, tm))):
                continue
            E = gA.point(s_b, ta)
            c = float(nA @ nB)
            pts = [E, E + sign * height * nA]
            if c > -.8:
                X = E + sign * height / (1 + c) * (nA + nB)
                pts.append(X)
            pts.append(E + sign * height * nB)
            poly = cq.Face.makeFromWires(cq.Wire.makePolygon([cq.Vector(*p) for p in pts], close=True))
            out.append(_prism(poly, gA.a * (tb - ta)))
    return out


def _extent(strip, face):
    ss = [strip.st(v.toTuple())[0] for v in face.Vertices()]
    for e in face.Edges():
        ss += [strip.st(e.positionAt(k / 8).toTuple())[0] for k in range(9)]
    return min(ss), max(ss)


def sketch_extent(origin, normal, face_or_points):
    """Zakres s szkicu (zanim jest pas: kierunek s nieznany) - wystarczy promień obrysu wokół początku."""
    O = np.asarray(origin, float)
    if hasattr(face_or_points, 'Vertices'):
        pts = [v.toTuple() for v in face_or_points.Vertices()]
        pts += [e.positionAt(k / 8).toTuple() for e in face_or_points.Edges() for k in range(9)]
    else:
        pts = list(face_or_points)
    if not pts:
        return (-1.0, 1.0)
    r = max(float(np.linalg.norm(np.asarray(p, float) - O)) for p in pts)
    return (-r, r)


def _check_full(strip, face):
    if strip.full is None:
        return
    lo, hi = _extent(strip, face)
    if lo < strip.full[0] + 1e-6 or hi > strip.full[1] - 1e-6:
        raise WrapError('Szkic jest zbyt szeroki dla tego walca (obiegłby go całego). Zmniejsz obrys lub podziel go na kilka szkiców.')


def wrap_tool(shape, face, normal, height, operation, origin):
    """Narzędzie (bryła) owiniętego wyciągnięcia / wycięcia albo None, gdy kształtu pod szkicem nie da się rozwinąć."""
    h = abs(float(height))
    strip = build_strip(shape, origin, normal, sketch_extent(origin, normal, face))
    if strip is None:
        return None
    _check_full(strip, face)
    join = operation != 'cut'
    pieces = []                       # (ściana pasa, bryła)
    for g in strip.segs:
        region = _region(strip, face, g)
        if not region:
            continue
        if g.kind == 'plane':
            mapped, _ = _plane_piece(strip, g, region)
            for f in mapped:
                if join:
                    pieces.append((g, _prism(f.translate(cq.Vector(*(-g.n * EPS))), g.n * (h + EPS))))
                else:
                    pieces.append((g, _prism(f.translate(cq.Vector(*(g.n * EPS))), -g.n * (h + EPS))))
        else:
            # promień startowy: zachodzi w bryłę (dodanie) albo zaczyna się nad nią (wycięcie)
            start = g.r - g.out * EPS if join else g.r + g.out * EPS
            end = g.r + g.out * h if join else g.r - g.out * h
            if end <= 1e-6:
                mm = lambda v: f'{v:.2f}'.rstrip('0').rstrip('.').replace('.', ',')
                raise WrapError(f'Wysokość ({mm(h)} mm) musi być mniejsza niż promień zaokrąglenia lub walca w tym miejscu '
                                f'({mm(g.r)} mm). Zmniejsz wysokość.')
            for r2 in region:
                f = _arc_face(strip, g, r2, start)
                mid_s = strip.st(r2.Center().toTuple())[0]
                phi = (mid_s - g.s_ref) / g.r
                radial = math.cos(phi) * g.e + math.sin(phi) * g.w
                pieces.append((g, _thicken(f, radial * (1 if end > start else -1), abs(end - start))))
    pieces += _wedges(strip, face, h, operation)
    pieces = [p if not isinstance(p, tuple) else p[1] for p in pieces]
    if not pieces:
        raise WrapError('Szkic nie leży na powierzchni bryły.')
    if len(pieces) == 1:
        return pieces[0]
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.TopTools import TopTools_ListOfShape
    args, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    args.Append(pieces[0].wrapped)
    for p in pieces[1:]:
        tools.Append(p.wrapped)
    fuse = BRepAlgoAPI_Fuse()
    fuse.SetArguments(args)
    fuse.SetTools(tools)
    fuse.SetFuzzyValue(1e-6)
    fuse.Build()
    if not fuse.IsDone():
        raise WrapError('Nie udało się połączyć części wyciągnięcia na narożniku.')
    result = cq.Shape.cast(fuse.Shape())
    try:
        result = result.clean()
    except Exception:
        pass
    return result


def display_lift(strip):
    """Szkic na bryle rysowany minimalnie nad powierzchnią: siatka bryły to cięciwy (na wklęsłym walcu leżą przed
    prawdziwą powierzchnią), więc szkic dokładnie na powierzchni bywałby zasłonięty."""
    radii = [g.r for g in strip.segs if g.kind == 'arc']
    return max(.02, .006 * min(radii)) if radii else .02


def wrap_mesh(mesh, shape, normal, origin, lift=None):
    """Siatka szkicu (DisplayMesh) przeniesiona na bryłę tak samo jak narzędzie. None - kształt nieobsługiwany.
    lift=None - automatyczne uniesienie nad powierzchnię (display_lift)."""
    from .kernel import DisplayMesh
    pts = list(mesh.vertices) + [p for e in mesh.edges.values() for p in e]
    strip = build_strip(shape, origin, normal, sketch_extent(origin, normal, pts))
    if strip is None:
        return None
    if strip.full is not None:
        ss = [strip.st(p)[0] for p in pts]
        if ss and (min(ss) < strip.full[0] + 1e-6 or max(ss) > strip.full[1] - 1e-6):
            raise WrapError('Szkic jest zbyt szeroki dla tego walca (obiegłby go całego). Zmniejsz obrys lub podziel go na kilka szkiców.')
    if lift is None:
        lift = display_lift(strip)
    breaks = sorted({g.s0 for g in strip.segs[1:]})
    rmin = min([g.r for g in strip.segs if g.kind == 'arc'] or [math.inf])
    step = min(.5, rmin * .08)

    def dense(points):
        points = [np.asarray(p, float) for p in points]
        out = [points[0]] if points else []
        for p, q in zip(points[:-1], points[1:]):
            sp, sq = strip.st(p)[0], strip.st(q)[0]
            cuts = [(b - sp) / (sq - sp) for b in breaks if (sp - b) * (sq - b) < 0 and abs(sq - sp) > 1e-12]
            n = max(1, int(math.ceil(float(np.linalg.norm(q - p)) / step))) if strip.segs and any(g.kind == 'arc' for g in strip.segs) else 1
            ks = sorted(set([j / n for j in range(1, n + 1)] + cuts))
            out += [p + (q - p) * k for k in ks]
        return out

    edges = {}
    for i, e in mesh.edges.items():
        edges[i] = np.asarray([strip.map_point(p, lift) for p in dense(e)], np.float32).reshape(-1, 3)
    verts, tris = _subdivide(np.asarray(mesh.vertices, float), np.asarray(mesh.triangles, np.int64), strip, breaks, step)
    vertices = np.asarray([strip.map_point(p, lift) for p in verts], np.float32).reshape(-1, 3)
    center = tuple(float(c) for c in strip.map_point(mesh.center))
    return DisplayMesh(vertices, tris.astype(np.uint32).reshape(-1, 3), edges, center, mesh.size, mesh.fine, None)


def _subdivide(verts, tris, strip, breaks, step):
    """Trójkąty szkicu dzielone, aż są drobne (na walcu) - wypełnienie nie chowa się pod zakrzywioną powierzchnią."""
    if len(tris) == 0:
        return verts, tris
    verts = [np.asarray(v, float) for v in verts]
    work = [tuple(int(c) for c in t) for t in tris]
    for b in breaks:                    # trójkąty przecięte dokładnie na krawędziach pasa: każdy leży na jednej ścianie
        work = _split_line(verts, work, strip, b)
    limit = max(step * 3, 1e-3) if any(g.kind == 'arc' for g in strip.segs) else math.inf
    if not math.isfinite(limit):
        return np.asarray(verts), np.asarray(work, np.int64).reshape(-1, 3)
    index = {}

    def mid(i, j):
        key = (min(i, j), max(i, j))
        if key not in index:
            verts.append((verts[i] + verts[j]) / 2)
            index[key] = len(verts) - 1
        return index[key]

    for _ in range(8):
        nxt, split = [], False
        for i, j, k in work:
            lens = (np.linalg.norm(verts[i] - verts[j]), np.linalg.norm(verts[j] - verts[k]), np.linalg.norm(verts[k] - verts[i]))
            if max(lens) > limit and len(nxt) < 200000:
                a, b, c = mid(i, j), mid(j, k), mid(k, i)
                nxt += [(i, a, c), (a, j, b), (c, b, k), (a, b, c)]
                split = True
            else:
                nxt.append((i, j, k))
        work = nxt
        if not split:
            break
    return np.asarray(verts), np.asarray(work, np.int64)


def _split_line(verts, tris, strip, s_line):
    """Podział trójkątów (w płaszczyźnie szkicu) prostą s = s_line."""
    out = []
    cache = {}

    def cut(i, j):
        key = (min(i, j), max(i, j))
        if key not in cache:
            si, sj = strip.st(verts[i])[0], strip.st(verts[j])[0]
            k = (s_line - si) / (sj - si)
            verts.append(verts[i] + (verts[j] - verts[i]) * k)
            cache[key] = len(verts) - 1
        return cache[key]

    for tri in tris:
        ss = [strip.st(verts[i])[0] - s_line for i in tri]
        if all(v >= -1e-9 for v in ss) or all(v <= 1e-9 for v in ss):
            out.append(tri)
            continue
        # wierzchołek samotny po jednej stronie
        signs = [v > 0 for v in ss]
        lone = next(k for k in range(3) if signs.count(signs[k]) == 1)
        a, b, c = tri[lone], tri[(lone + 1) % 3], tri[(lone + 2) % 3]
        if abs(ss[(lone + 1) % 3]) <= 1e-9 or abs(ss[(lone + 2) % 3]) <= 1e-9:
            # prosta przechodzi przez wierzchołek: dwa trójkąty
            on = b if abs(ss[(lone + 1) % 3]) <= 1e-9 else c
            other = c if on == b else b
            m = cut(a, other)
            out += [(a, b, m), (m, b, c)] if on == b else [(a, m, c), (m, b, c)]
            continue
        p, q = cut(a, b), cut(c, a)
        out += [(a, p, q), (p, b, c), (p, c, q)]
    return out
