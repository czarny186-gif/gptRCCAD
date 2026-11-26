"""Generator obudów - etap 8: narzędzie „Otwór na element”.

Narzędzie tnące powstaje z profilu 2D na płaszczyźnie wskazanej ścianki obudowy (układ ścianki: n - normalna na
zewnątrz, v - „góra” ścianki, u = v × n - w prawo patrząc z zewnątrz):
- dokładny rzut konturu: ściany elementu zwrócone do ścianki rzutowane prostopadle na płaszczyznę
  (BRepBuilderAPI_GTransform z macierzą rzutu - krzywe pozostają dokładne), połączone (Boolean Fuse 2D) i odsunięte
  o luz (BRepOffsetAPI_MakeOffset),
- obrys prostokątny / okrągły / prostokąt z zaokrąglonymi narożnikami - z ramki rzutu (luzy w każdym kierunku osobno),
- profil z biblioteki (USB-A, USB-C, Micro USB, HDMI, RJ45, gniazdo DC, karty SD, przyciski, przełączniki,
  wyświetlacze - wymiary do zmiany),
- własny szkic użytkownika (zamknięty kontur rzutowany na ściankę).
Profil można przesunąć i obrócić; wyciągnięcie (BRepPrimAPI_MakePrism) daje narzędzie: otwór przelotowy, zagłębienie od
zewnątrz, podfrezowanie od wewnątrz albo wycięcie stopniowane; opcjonalnie miejsce na wtyczkę (zagłębienie wokół otworu)
i dostęp palca. Z obudowy wycinane jest wyłącznie narzędzie (Boolean Cut) - nigdy bryła elementu. Kontrola: objętość
usuniętego materiału musi odpowiadać samej ściance (więcej - otwór uszkadza mocowanie, zamknięcie albo sąsiednią
ściankę; mniej - otwór wychodzi poza ściankę)."""
from __future__ import annotations

import math

import numpy as np

from . import kernel

MODES = ('exact', 'rect', 'circle', 'rrect', 'library', 'sketch')
MODE_LABELS = {'exact': 'Dokładny rzut konturu', 'rect': 'Obrys prostokątny', 'circle': 'Obrys okrągły',
               'rrect': 'Prostokąt z zaokrąglonymi narożnikami', 'library': 'Profil z biblioteki', 'sketch': 'Własny szkic'}
CUTS = ('through', 'recess', 'undercut', 'stepped')
CUT_LABELS = {'through': 'Otwór przelotowy', 'recess': 'Zagłębienie (od zewnątrz)', 'undercut': 'Podfrezowanie (od wewnątrz)',
              'stepped': 'Wycięcie stopniowane'}
# profil: kształt ('rrect' / 'circle' / 'trap'), szerokość w (u), wysokość h (v), promień r, dolna szerokość trapezu b.
# Wartości typowe - obudowy złączy różnią się między producentami, dlatego każda wartość jest do zmiany w oknie.
LIBRARY = {
    'usb_a': ('USB-A', dict(shape='rrect', w=13.2, h=5.8, r=.5)),
    'usb_c': ('USB-C', dict(shape='rrect', w=9.2, h=3.6, r=1.6)),
    'micro_usb': ('Micro USB', dict(shape='trap', w=8.0, h=3.2, b=6.4, r=.3)),
    'hdmi': ('HDMI', dict(shape='trap', w=15.4, h=6.0, b=11.8, r=.3)),
    'rj45': ('RJ45', dict(shape='rrect', w=16.2, h=13.8, r=.3)),
    'dc': ('Gniazdo DC (Ø8)', dict(shape='circle', w=8.2, h=8.2, r=0.0)),
    'dc_pcb': ('Gniazdo DC do płytki', dict(shape='rrect', w=9.4, h=11.4, r=.5)),
    'sd': ('Karta SD', dict(shape='rrect', w=25.0, h=3.0, r=.5)),
    'microsd': ('Karta microSD', dict(shape='rrect', w=12.0, h=2.0, r=.4)),
    'button12': ('Przycisk Ø12', dict(shape='circle', w=12.2, h=12.2, r=0.0)),
    'tact': ('Przycisk taktowy (nasadka Ø6)', dict(shape='circle', w=6.4, h=6.4, r=0.0)),
    'toggle': ('Przełącznik dźwigienkowy Ø6', dict(shape='circle', w=6.2, h=6.2, r=0.0)),
    'rocker': ('Przełącznik kołyskowy', dict(shape='rrect', w=13.2, h=19.4, r=.5)),
    'slide': ('Przełącznik suwakowy', dict(shape='rrect', w=9.0, h=4.0, r=.3)),
    'lcd1602': ('Wyświetlacz LCD 16x2 (okno)', dict(shape='rrect', w=64.5, h=16.0, r=.5)),
    'oled096': ('Wyświetlacz OLED 0,96" (okno)', dict(shape='rrect', w=23.0, h=12.0, r=.5)),
    'tft24': ('Wyświetlacz TFT 2,4" (okno)', dict(shape='rrect', w=49.0, h=37.0, r=.5)),
}
DEFAULTS = dict(mode='rrect', library='usb_c', lib=None, radius=1.0, clear=dict(l=.3, r=.3, b=.3, t=.3), du=0.0, dv=0.0, angle=0.0,
                cut='through', depth=1.0, step=1.0, step_depth=1.0, plug=0.0, plug_depth=1.0, finger=0.0, finger_du=0.0, finger_dv=0.0,
                flip=False)


def _cq_shape(shape):
    import cadquery as cq
    return cq.Shape.cast(shape)


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def wall_frame(origin, normal, up=(0, 0, 1.0), direction=None):
    """Układ ścianki: (o, u, v, n) - n na zewnątrz obudowy, v - „góra” (rzut kierunku up), u = v × n."""
    n = _unit(normal)
    v = np.asarray(up, float) - float(np.asarray(up, float) @ n) * n
    if np.linalg.norm(v) < 1e-6:
        v = np.array([0, 1.0, 0]) - n[1] * n
        if np.linalg.norm(v) < 1e-6:
            v = np.array([1.0, 0, 0]) - n[0] * n
    v = _unit(v)
    return np.asarray(origin, float), np.cross(v, n), v, n, (None if direction is None else _unit(direction))


def _plane_face(pts2, frame):
    """Wielokąt w układzie ścianki -> ściana płaska."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt
    o, u, v, _n = frame[:4]
    poly = BRepBuilderAPI_MakePolygon()
    for a, b in pts2:
        poly.Add(gp_Pnt(*map(float, o + u * a + v * b)))
    poly.Close()
    mf = BRepBuilderAPI_MakeFace(poly.Wire(), True)
    if not mf.IsDone():
        raise kernel.CadError('Niepoprawny profil otworu.')
    return mf.Face()


def _fillet2d(face, r):
    if r <= 1e-6:
        return face
    from .enclosure_shapes import _fillet_profile
    return _fillet_profile(face, r)


def _circle_face(cu, cv, r, frame):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt
    o, u, v, n = frame[:4]
    if r <= 1e-6:
        raise kernel.CadError('Średnica otworu musi być większa od zera.')
    c = o + u * cu + v * cv
    edge = BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(gp_Pnt(*map(float, c)), gp_Dir(*map(float, n)), gp_Dir(*map(float, u))), float(r))).Edge()
    return BRepBuilderAPI_MakeFace(BRepBuilderAPI_MakeWire(edge).Wire(), True).Face()


def profile_shape(kind, cu, cv, w, h, r, frame, b=None):
    """Profil o środku (cu, cv): 'rrect' (zaokrąglenie r), 'circle' (średnica w), 'trap' (górna szerokość w, dolna b)."""
    if kind == 'circle':
        return _circle_face(cu, cv, w / 2, frame)
    if w <= 1e-6 or h <= 1e-6:
        raise kernel.CadError('Wymiary otworu muszą być większe od zera.')
    if kind == 'trap':
        b = float(b if b is not None else w)
        pts = [(cu - b / 2, cv - h / 2), (cu + b / 2, cv - h / 2), (cu + w / 2, cv + h / 2), (cu - w / 2, cv + h / 2)]
        return _fillet2d(_plane_face(pts, frame), min(r, .45 * min(b, h)))
    pts = [(cu - w / 2, cv - h / 2), (cu + w / 2, cv - h / 2), (cu + w / 2, cv + h / 2), (cu - w / 2, cv + h / 2)]
    rr = min(float(r), .5 * min(w, h) - 1e-3)
    return _fillet2d(_plane_face(pts, frame), max(rr, 0.0))


def _dir(frame):
    """Kierunek rzutu i wycięcia: prostopadle do ścianki (n) albo ukośnie (5. element układu)."""
    d = _unit(frame[4]) if len(frame) > 4 and frame[4] is not None else frame[3]
    if float(d @ frame[3]) < .2:
        raise kernel.CadError('Kierunek wycięcia jest prawie równoległy do ścianki.')
    return d


def _project_point(p, frame):
    o, _u, _v, n = frame[:4]
    d = _dir(frame)
    p = np.asarray(p, float)
    return p - float((p - o) @ n) / float(d @ n) * d


def _flat_wire(wire, frame):
    """Krawędzie konturu rzutowane na płaszczyznę ścianki: odcinki - dokładnie, łuki o osi prostopadłej do ścianki -
    dokładnie (łuk przez trzy rzutowane punkty), pozostałe krzywe - krzywa BSpline przez gęste punkty rzutu."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.GC import GC_MakeArcOfCircle
    from OCP.GeomAPI import GeomAPI_PointsToBSpline
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.gp import gp_Pnt
    _o, _u, _v, n = frame[:4]
    mk = BRepBuilderAPI_MakeWire()
    ex = BRepTools_WireExplorer(wire)
    count = 0
    while ex.More():
        edge = ex.Current()
        c = BRepAdaptor_Curve(edge)
        t0, t1 = c.FirstParameter(), c.LastParameter()
        P = lambda t: _project_point(c.Value(t).Coord(), frame)
        a, b = P(t0), P(t1)
        kind = c.GetType()
        made = None
        if kind == GeomAbs_Line:
            if np.linalg.norm(b - a) > 1e-7:
                made = BRepBuilderAPI_MakeEdge(gp_Pnt(*a), gp_Pnt(*b)).Edge()
        elif kind == GeomAbs_Circle and abs(abs(float(np.asarray(c.Circle().Axis().Direction().Coord()) @ n)) - 1) < 1e-9 and float(_dir(frame) @ n) > 1 - 1e-12:
            m = P((t0 + t1) / 2)
            if np.linalg.norm(b - a) < 1e-7:            # pełny okrąg
                from OCP.gp import gp_Ax2, gp_Circ, gp_Dir
                cen = _project_point(c.Circle().Location().Coord(), frame)
                made = BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(gp_Pnt(*cen), gp_Dir(*n)), c.Circle().Radius())).Edge()
            else:
                made = BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(gp_Pnt(*a), gp_Pnt(*m), gp_Pnt(*b)).Value()).Edge()
        else:
            ts = np.linspace(t0, t1, 33)
            pts = [P(t) for t in ts]
            if max(np.linalg.norm(q - pts[0]) for q in pts) > 1e-7:
                arr = TColgp_Array1OfPnt(1, len(pts))
                for i, q in enumerate(pts):
                    arr.SetValue(i + 1, gp_Pnt(*q))
                made = BRepBuilderAPI_MakeEdge(GeomAPI_PointsToBSpline(arr).Curve()).Edge()
        if made is not None:
            mk.Add(made)
            count += 1
        ex.Next()
    if count == 0 or not mk.IsDone():
        return None
    return mk.Wire()


def _flat_face(face, frame):
    """Rzut prostokątny ściany na płaszczyznę ścianki (sam obrys zewnętrzny) jako ściana płaska na gp_Pln."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepTools import BRepTools
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    import cadquery as cq
    o, _u, _v, n = frame[:4]
    wire = _flat_wire(BRepTools.OuterWire_s(face), frame)
    if wire is None:
        return None
    mf = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(*map(float, o)), gp_Dir(*map(float, n))), wire, True)
    if not mf.IsDone():
        return None
    f = mf.Face()
    if not BRepCheck_Analyzer(f).IsValid() or cq.Shape.cast(f).Area() <= 1e-6:
        return None
    return f


def _face_samples(face, n=24):
    """Punkty ściany: siatka parametrów (u, v) wewnątrz ściany (z jej krawędziami)."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_OUT
    from OCP.gp import gp_Pnt2d
    s = BRepAdaptor_Surface(face.wrapped, True)
    u0, u1, v0, v1 = s.FirstUParameter(), s.LastUParameter(), s.FirstVParameter(), s.LastVParameter()
    pts = [np.asarray(e.positionAt(t).toTuple(), float) for e in face.Edges() for t in np.linspace(0, 1, 17)]
    for u in np.linspace(u0, u1, n):
        for v in np.linspace(v0, v1, n):
            if BRepClass_FaceClassifier(face.wrapped, gp_Pnt2d(u, v), 1e-7).State() != TopAbs_OUT:
                pts.append(np.asarray(s.Value(u, v).Coord(), float))
    return np.array(pts)


def _hull_face(face, frame):
    """Obrys wypukły rzutu ściany na płaszczyznę ścianki (bezpieczny nadzbiór rzutu ściany zakrzywionej)."""
    from .enclosure_contour import convex_hull
    try:
        pts = _face_samples(face)
        o, u, v, n = frame[:4]
        q = np.array([_project_point(p, frame) for p in pts])
        uv = np.c_[(q - o) @ u, (q - o) @ v]
        hull = convex_hull(uv)
    except kernel.CadError:
        return None
    area = 0.5 * abs(float(np.dot(hull[:, 0], np.roll(hull[:, 1], -1)) - np.dot(hull[:, 1], np.roll(hull[:, 0], -1))))
    if area <= 1e-6:
        return None
    return _plane_face([tuple(p) for p in hull], frame)


def _uv(points, frame):
    o, u, v, _n = frame[:4]
    p = np.asarray(points, float) - o
    return np.c_[p @ u, p @ v]


def projected_faces(faces, frame):
    """Ściany elementu zwrócone do ścianki rzutowane prostopadle na jej płaszczyznę i połączone (Fuse) w jeden obszar."""
    from .enclosure import _boolean, _unified
    import cadquery as cq
    _o, _u, _v, n = frame[:4]
    flat = []
    for f in faces:
        face = cq.Face(f) if not isinstance(f, cq.Face) else f
        if face.geomType() == 'PLANE':
            try:
                nn = np.asarray(face.normalAt(face.Center()).toTuple(), float)
            except Exception:
                nn = None
            if nn is not None and abs(float(nn @ n)) < .05:
                continue                                    # ściana prostopadła do ścianki - rzut bez pola
        ff = None
        if face.geomType() == 'PLANE':
            try:
                ff = _flat_face(face.wrapped, frame)
            except Exception:
                ff = None
        if ff is None:                                      # ściana zakrzywiona: obrys wypukły rzutu punktów ściany (nadzbiór rzutu)
            ff = _hull_face(face, frame)
        if ff is not None:
            flat.append(ff)
    if not flat:
        raise kernel.CadError('Rzut elementu na ściankę nie ma pola - wskaż ściany zwrócone do ścianki albo inny tryb.')
    region = flat[0]
    for f in flat[1:]:
        try:
            region = _boolean('fuse', region, f, 'suma rzutów')
        except kernel.CadError:
            continue
    return _unified(region)


def _outer_faces(shape):
    import cadquery as cq
    return [f.wrapped for f in cq.Shape.cast(shape).Faces()]


def offset_region(region, d):
    """Odsunięcie obszaru płaskiego o d (BRepOffsetAPI_MakeOffset, łuki w narożnikach) - nowe ściany."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
    from OCP.GeomAbs import GeomAbs_Arc
    from .enclosure import _boolean
    import cadquery as cq
    if abs(d) < 1e-9:
        return region
    out = None
    for face in cq.Shape.cast(region).Faces():
        mk = BRepOffsetAPI_MakeOffset(face.wrapped, GeomAbs_Arc)
        mk.Perform(float(d))
        if not mk.IsDone():
            raise kernel.CadError('Odsunięcie konturu nie powiodło się - zmień luz albo wybierz obrys.')
        wires = cq.Shape.cast(mk.Shape()).Wires()
        if not wires:
            raise kernel.CadError('Odsunięcie konturu nie dało zamkniętego profilu.')
        outer = max(wires, key=lambda w: cq.Face.makeFromWires(w).Area())
        mf = BRepBuilderAPI_MakeFace(outer.wrapped, True)
        if not mf.IsDone():
            raise kernel.CadError('Profil po odsunięciu jest niepoprawny (samoprzecięcie).')
        f = mf.Face()
        out = f if out is None else _boolean('fuse', out, f, 'suma profili')
    return out


def _check_region(region):
    """Profil płaski: niepusty, bez samoprzecięć (BRepCheck)."""
    from OCP.BRepCheck import BRepCheck_Analyzer
    import cadquery as cq
    if region is None or cq.Shape.cast(region).Area() <= 1e-6:
        raise kernel.CadError('Profil otworu jest pusty.')
    if not BRepCheck_Analyzer(region).IsValid():
        raise kernel.CadError('Profil otworu ma samoprzecięcia - zwiększ luz albo wybierz obrys prostokątny.')
    return region


def _bbox_uv(region, frame):
    import cadquery as cq
    sh = cq.Shape.cast(region)
    pts = []
    for e in sh.Edges():
        pts += [e.positionAt(t).toTuple() for t in np.linspace(0, 1, 24)]
    uv = _uv(pts, frame)
    return uv.min(axis=0), uv.max(axis=0), uv


def _moved(region, frame, du, dv, angle, centre):
    """Przesunięcie (du, dv) i obrót o kąt (°) wokół środka profilu w płaszczyźnie ścianki."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    o, u, v, n = frame[:4]
    shape = region
    if abs(angle) > 1e-9:
        c = o + u * centre[0] + v * centre[1]
        t = gp_Trsf()
        t.SetRotation(gp_Ax1(gp_Pnt(*map(float, c)), gp_Dir(*map(float, n))), math.radians(float(angle)))
        shape = BRepBuilderAPI_Transform(shape, t, True).Shape()
    if abs(du) > 1e-12 or abs(dv) > 1e-12:
        t = gp_Trsf()
        t.SetTranslation(gp_Vec(*map(float, u * du + v * dv)))
        shape = BRepBuilderAPI_Transform(shape, t, True).Shape()
    return shape


def build_profile(p, frame, faces=None, sketch_faces=None):
    """Profil otworu (ściana / ściany płaskie na płaszczyźnie ścianki) według trybu i parametrów."""
    mode = p['mode']
    c = dict(DEFAULTS['clear'], **(p.get('clear') or {}))
    for k_, val in c.items():
        if not np.isfinite(val) or val < 0:
            raise kernel.CadError('Luzy otworu nie mogą być ujemne.')
    if mode in ('exact', 'rect', 'circle', 'rrect'):
        if not faces:
            raise kernel.CadError('Wskaż element (bryłę albo ściany), dla którego ma powstać otwór.')
        region = projected_faces(faces, frame)
        lo, hi, uv = _bbox_uv(region, frame)
        centre = (lo + hi) / 2
        if mode == 'exact':
            base = min(c.values())
            shape = offset_region(region, base) if base > 0 else region
            for key, vec in (('l', (-1, 0)), ('r', (1, 0)), ('b', (0, -1)), ('t', (0, 1))):     # dodatkowy luz w jednym kierunku
                extra = c[key] - base
                if extra > 1e-9:
                    from .enclosure import _boolean
                    moved = _moved(shape, frame, vec[0] * extra, vec[1] * extra, 0.0, centre)
                    half = _moved(shape, frame, vec[0] * extra / 2, vec[1] * extra / 2, 0.0, centre)
                    shape = _boolean('fuse', _boolean('fuse', shape, half, 'luz kierunkowy'), moved, 'luz kierunkowy')
        elif mode == 'circle':
            r = float(np.max(np.hypot(uv[:, 0] - centre[0], uv[:, 1] - centre[1]))) + max(c.values())
            shape = _circle_face(centre[0], centre[1], r, frame)
        else:
            w = hi[0] - lo[0] + c['l'] + c['r']
            h = hi[1] - lo[1] + c['b'] + c['t']
            cu = (lo[0] - c['l'] + hi[0] + c['r']) / 2
            cv = (lo[1] - c['b'] + hi[1] + c['t']) / 2
            shape = profile_shape('rrect', cu, cv, w, h, float(p['radius']) if mode == 'rrect' else 0.0, frame)
    elif mode == 'library':
        lib = dict(LIBRARY.get(p.get('library'), LIBRARY['usb_c'])[1], **(p.get('lib') or {}))
        centre = np.zeros(2)
        if faces:
            region = projected_faces(faces, frame)
            lo, hi, _uv_ = _bbox_uv(region, frame)
            centre = (lo + hi) / 2
        w = float(lib['w']) + c['l'] + c['r']
        h = float(lib['h']) + c['b'] + c['t']
        cu, cv = centre[0] + (c['r'] - c['l']) / 2, centre[1] + (c['t'] - c['b']) / 2
        shape = profile_shape(lib['shape'], cu, cv, w if lib['shape'] != 'circle' else max(w, h), h, float(lib.get('r', 0.0)), frame,
                              b=(float(lib.get('b', lib['w'])) + c['l'] + c['r']))
    elif mode == 'sketch':
        if not sketch_faces:
            raise kernel.CadError('Wskaż zamknięty szkic z konturem otworu.')
        region = projected_faces(sketch_faces, frame)
        lo, hi, _uv_ = _bbox_uv(region, frame)
        centre = (lo + hi) / 2
        base = min(c.values())
        shape = offset_region(region, base) if base > 0 else region
    else:
        raise kernel.CadError('Nieznany tryb otworu.')
    shape = _moved(shape, frame, float(p.get('du', 0.0)), float(p.get('dv', 0.0)), float(p.get('angle', 0.0)), centre)
    return _check_region(shape), np.asarray(centre, float) + [float(p.get('du', 0.0)), float(p.get('dv', 0.0))]


def _prism(region, frame, a, b):
    """Narzędzie: profil przesunięty na wysokość a wzdłuż n i wyciągnięty do b (BRepPrimAPI_MakePrism)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Trsf, gp_Vec
    _o, _u, _v, n = frame[:4]
    d = _dir(frame)
    k = 1.0 / float(d @ n)                          # ukośnie: wysokości a, b mierzone wzdłuż normalnej ścianki
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(*map(float, d * a * k)))
    moved = BRepBuilderAPI_Transform(region, t, True).Shape()
    mk = BRepPrimAPI_MakePrism(moved, gp_Vec(*map(float, d * (b - a) * k)))
    mk.Build()
    if not mk.IsDone():
        raise kernel.CadError('Wyciągnięcie profilu otworu nie powiodło się.')
    return mk.Shape()


def wall_thickness(shape, frame, centre):
    """Grubość ścianki pod środkiem profilu: od płaszczyzny zewnętrznej do wnętrza (promień wzdłuż -n)."""
    from .enclosure_posts import wall_hit_exit
    o, u, v, n = frame[:4]
    p = o + u * centre[0] + v * centre[1] - n * 1e-3          # tuż pod zewnętrzną powierzchnią - pierwsze trafienie to wnętrze
    t = wall_hit_exit(shape, p, -n)
    if t is None:
        raise kernel.CadError('Pod profilem nie ma ścianki obudowy.')
    return float(t) + 1e-3 + 1e-4


def tool(region, frame, p, thickness):
    """Narzędzie tnące (lista brył) według rodzaju wycięcia; głębokości w mm od powierzchni ścianki."""
    from .enclosure import _boolean
    t = float(thickness)
    cut = p['cut']
    depth = float(p['depth'])
    parts = []
    if cut in ('through', 'stepped'):
        parts.append(_prism(region, frame, 1.0, -t - 1.0))
        if cut == 'stepped':
            sd = float(p['step_depth'])
            if not (0 < sd < t):
                raise kernel.CadError(f'Głębokość stopnia musi być od 0 do grubości ścianki ({t:.2f} mm).')
            parts.append(_prism(offset_region(region, float(p['step'])), frame, 1.0, -sd))
    elif cut == 'recess':
        if not (0 < depth < t):
            raise kernel.CadError(f'Głębokość zagłębienia musi być od 0 do grubości ścianki ({t:.2f} mm).')
        parts.append(_prism(region, frame, 1.0, -depth))
    elif cut == 'undercut':
        if not (0 < depth < t):
            raise kernel.CadError(f'Głębokość podfrezowania musi być od 0 do grubości ścianki ({t:.2f} mm).')
        parts.append(_prism(region, frame, -t - 1.0, -t + depth))
    else:
        raise kernel.CadError('Nieznany rodzaj wycięcia.')
    pd = float(p.get('plug_depth', 0.0))
    if float(p.get('plug', 0.0)) > 0:                        # miejsce na wtyczkę: zagłębienie wokół otworu od zewnątrz
        if not (0 < pd < t):
            raise kernel.CadError(f'Głębokość miejsca na wtyczkę musi być od 0 do grubości ścianki ({t:.2f} mm).')
        parts.append(_prism(offset_region(region, float(p['plug'])), frame, 1.0, -pd))
    if float(p.get('finger', 0.0)) > 0:                      # dostęp palca: okrągłe zagłębienie przy otworze
        if not (0 < pd < t):
            raise kernel.CadError(f'Głębokość zagłębienia na palec musi być od 0 do grubości ścianki ({t:.2f} mm).')
        lo, hi, _uv_ = _bbox_uv(region, frame)
        cc = (lo + hi) / 2 + [float(p.get('finger_du', 0.0)), float(p.get('finger_dv', 0.0))]
        parts.append(_prism(_circle_face(cc[0], cc[1], float(p['finger']) / 2, frame), frame, 1.0, -pd))
    out = parts[0]
    for extra in parts[1:]:
        out = _boolean('fuse', out, extra, 'narzędzie otworu')
    return out


def expected_removal(region, frame, p, thickness, target_face=None):
    """Objętość, jaką narzędzie powinno usunąć z samej ścianki (narzędzie ∩ warstwa ścianki)."""
    from .enclosure import _boolean, _make_box, _volume
    import cadquery as cq
    o, u, v, n = frame[:4]
    tl = tool(region, frame, p, thickness)
    size = 1e4
    slab = kernel.transformed(cq.Shape.cast(_make_box((-size, -size, -float(thickness)), (size, size, 0.0))), np.column_stack([u, v, n]), o).wrapped
    return _volume(_boolean('common', tl, slab, 'warstwa ścianki'))[0], tl


def _inside_wall(target_shape, region, frame):
    """Profil musi leżeć na płaskiej ściance (na jej płaszczyźnie i w jej obrysie) - inaczej narusza sąsiednie ścianki."""
    from .enclosure import _boolean
    import cadquery as cq
    o, _u, _v, n = frame[:4]
    faces = [f for f in target_shape.Faces() if f.geomType() == 'PLANE'
             and float(np.asarray(f.normalAt(f.Center()).toTuple()) @ n) > 1 - 1e-6
             and abs(float((np.asarray(f.Center().toTuple()) - o) @ n)) < 1e-4]
    if not faces:
        raise kernel.CadError('Wskazana ścianka nie leży na płaszczyźnie otworu.')
    area = cq.Shape.cast(region).Area()
    inside = 0.0
    for f in faces:
        try:
            inside += cq.Shape.cast(_boolean('common', region, f.wrapped, 'profil na ściance')).Area()
        except kernel.CadError:
            pass
    if inside < area * .999 - 1e-6:
        raise kernel.CadError('Otwór wychodzi poza ściankę obudowy (narusza krawędź albo sąsiednią ściankę) - przesuń lub zmniejsz profil.')


def cut(target_shape, region, frame, p):
    """Otwór w części obudowy: Boolean Cut samego narzędzia + kontrola usuniętej objętości. Zwraca (bryła cq, narzędzie, info)."""
    from .enclosure import _boolean, _single, _volume, check_solid, _unified
    import cadquery as cq
    lo, hi, _uv_ = _bbox_uv(region, frame)
    centre = (lo + hi) / 2
    _inside_wall(target_shape, region, frame)
    t = wall_thickness(target_shape.wrapped, frame, centre)
    expected, tl = expected_removal(region, frame, p, t)
    before = _volume(target_shape.wrapped)[0]
    result = _boolean('cut', target_shape.wrapped, tl, 'otwór na element')
    after = _volume(result)[0]
    removed = before - after
    if removed > expected * 1.01 + 1e-3:
        raise kernel.CadError('Otwór uszkadza mocowanie, system zamykania albo sąsiednią ściankę - przesuń lub zmniejsz profil.')
    if removed < expected * .99 - 1e-3:
        raise kernel.CadError('Otwór wychodzi poza ściankę obudowy - przesuń lub zmniejsz profil.')
    if removed <= 1e-6:
        raise kernel.CadError('Otwór nie trafia w ściankę obudowy.')
    shape = check_solid(_single(_unified(result), 'Obudowa z otworem'))
    area = cq.Shape.cast(region).Area()
    return shape, tl, dict(thickness=t, removed=removed, area=area, centre=[float(x) for x in centre])


def propose_wall(enclosures, point):
    """Najbliższa płaska ściana obudowy przed elementem: (id bryły, punkt na ścianie, normalna na zewnątrz)."""
    import cadquery as cq
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    from OCP.gp import gp_Pnt
    c = np.asarray(point, float)
    best = None
    for body in enclosures:
        for face in body.shape.Faces():
            if face.geomType() != 'PLANE':
                continue
            o = np.asarray(face.Center().toTuple(), float)
            n = np.asarray(face.normalAt(face.Center()).toTuple(), float)
            d = float((o - c) @ n)
            if d <= 1e-6:
                continue                         # ściana za elementem albo zwrócona do niego
            q = c + n * d
            cls = BRepClass_FaceClassifier(face.wrapped, gp_Pnt(*map(float, q)), 1e-6)
            if cls.State() not in (TopAbs_IN, TopAbs_ON):
                continue
            if kernel.point_state(body.shape, q + n * 1e-3) != 'out':
                continue                         # ściana wewnętrzna (np. wnęka) - nie zewnętrzna powierzchnia
            if best is None or d < best[0]:
                best = (d, body.id, q, n)
    if best is None:
        return None
    return best[1], best[2], best[3]
