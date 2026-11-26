"""Generator obudów - etap 11: obudowa dopasowana do konturu (stały przekrój w kierunku wyciągnięcia).

Algorytm (płaszczyzna u, v układu kształtu; w - kierunek wyciągnięcia):
1. geometria elementów przeniesiona do układu obudowy i zrzutowana na płaszczyznę (dokładny rzut ścian - krawędzie
   rzutowane dokładnie albo krzywą BSpline z dokładnością obrysu),
2. obszary rzutów połączone (Boolean Fuse 2D), drobne fragmenty usunięte, rozłączne obszary połączone (domknięcie
   morfologiczne o rosnącym promieniu) - albo komunikat,
3. tryb: obrys wypukły (Convex Hull punktów siatek), obrys wklęsły (domknięcie o regulowanym promieniu - stopień
   dopasowania), dokładna suma rzutów, wygładzony obrys (zaokrąglenie narożników wypukłych i wklęsłych promieniem
   minimalnym), własny kontur z istniejącego szkicu,
4. minimalna szerokość przewężeń (wąskie fragmenty poszerzone), uproszczenie konturu (tolerancja),
5. odstęp od elementów - odsunięcie (BRepOffsetAPI_MakeOffset), profil wewnętrzny zamknięty i bez samoprzecięć
   (BRepCheck_Analyzer), profil zewnętrzny - odsunięcie o grubość ścianki,
6. wyciągnięcie (BRepPrimAPI_MakePrism) - dno, ścianki i pokrywa z wyciągnięć profili i operacji Boolean.
Gdy dokładne dopasowanie nie daje poprawnego konturu, komunikat proponuje uproszczenie albo obrys wypukły - tryb nie
zmienia się sam. Pełne przestrzenne dopasowanie powłoki 3D - późniejsze rozszerzenie."""
from __future__ import annotations

import math

import numpy as np

from . import kernel

CMODES = ('convex', 'concave', 'exact', 'smooth', 'sketch')
CMODE_LABELS = {'convex': 'Obrys wypukły (Convex Hull)', 'concave': 'Obrys wklęsły (stopień dopasowania)', 'exact': 'Dokładna suma rzutów',
                'smooth': 'Wygładzony obrys', 'sketch': 'Własny kontur ze szkicu'}
DEFAULTS = dict(cmode='concave', degree=6.0, min_radius=2.0, min_neck=0.0, accuracy=.1, simplify=0.0, min_fragment=.5, connect=True, sketch=None)

_CACHE = {}


def _face_area(shape):
    import cadquery as cq
    return float(cq.Shape.cast(shape).Area())


def _faces(shape):
    import cadquery as cq
    return [f.wrapped for f in cq.Shape.cast(shape).Faces()]


def _fuse_all(faces):
    from .enclosure import _boolean, _unified
    if not faces:
        return None
    region = faces[0]
    for f in faces[1:]:
        region = _boolean('fuse', region, f, 'suma obszarów')
    return _unified(region)


def offset(region, d, what='odsunięcie konturu'):
    """Odsunięcie obszaru płaskiego (wszystkich jego ścian) o d - BRepOffsetAPI_MakeOffset, narożniki łukami.
    Zwraca obszar (ściany) bez samoprzecięć albo CadError."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
    from OCP.GeomAbs import GeomAbs_Arc
    import cadquery as cq
    if abs(d) < 1e-9:
        return region
    out = []
    for face in _faces(region):
        mk = BRepOffsetAPI_MakeOffset(face, GeomAbs_Arc)
        mk.Perform(float(d))
        if not mk.IsDone():
            raise kernel.CadError(f'{what.capitalize()} nie powiodło się - spróbuj uproszczenia konturu albo obrysu wypukłego.')
        for w in cq.Shape.cast(mk.Shape()).Wires():
            if not w.IsClosed():
                continue
            mf = BRepBuilderAPI_MakeFace(w.wrapped, True)
            if not mf.IsDone():
                continue
            f = mf.Face()
            if BRepCheck_Analyzer(f).IsValid() and _face_area(f) > 1e-6:
                out.append(f)
    if not out:
        if d < 0:
            return None                                  # obszar zniknął przy zwężaniu (np. otwarcie morfologiczne)
        raise kernel.CadError(f'{what.capitalize()} dało samoprzecinający się kontur - spróbuj uproszczenia albo obrysu wypukłego.')
    # przy odsunięciu do środka zostają osobne obszary; przy odsunięciu na zewnątrz - największy obrys (dziury nie są otworami)
    if d > 0:
        biggest = max(out, key=_face_area)
        out = [biggest] + [f for f in out if f is not biggest and _face_area(f) > .01 * _face_area(biggest)]
    return _fuse_all(out)


def closing(region, r):
    if r <= 1e-9:
        return region
    grown = offset(region, r, 'domknięcie konturu')
    back = offset(grown, -r, 'domknięcie konturu')
    return back if back is not None else region


def opening(region, r):
    if r <= 1e-9:
        return region
    shrunk = offset(region, -r, 'otwarcie konturu')
    if shrunk is None:
        return None
    return offset(shrunk, r, 'otwarcie konturu')


def _polygon_face(pts):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt
    poly = BRepBuilderAPI_MakePolygon()
    for u, v in pts:
        poly.Add(gp_Pnt(float(u), float(v), 0.0))
    poly.Close()
    mf = BRepBuilderAPI_MakeFace(poly.Wire(), True)
    if not mf.IsDone():
        raise kernel.CadError('Niepoprawny obrys - samoprzecięcie albo zerowe pole.')
    return mf.Face()


def convex_hull(points):
    """Otoczka wypukła punktów 2D (łańcuch monotoniczny Andrew)."""
    P = sorted(set(map(tuple, np.round(np.asarray(points, float), 9))))
    if len(P) < 3:
        raise kernel.CadError('Za mało punktów do obrysu.')
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in P:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 1e-12:
            lower.pop()
        lower.append(p)
    for p in reversed(P):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 1e-12:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        raise kernel.CadError('Elementy rzutują się na odcinek - obrys nie ma pola.')
    return np.array(hull)


def _simplify(pts, tol):
    """Upraszczanie łamanej zamkniętej (Douglas-Peucker)."""
    if tol <= 0 or len(pts) < 5:
        return pts

    def dp(a):
        if len(a) < 3:
            return a
        s, e = a[0], a[-1]
        d = e - s
        L = float(np.hypot(*d)) or 1e-12
        dist = np.abs(d[0] * (a[:, 1] - s[1]) - d[1] * (a[:, 0] - s[0])) / L
        i = int(np.argmax(dist))
        if dist[i] > tol:
            return np.vstack([dp(a[:i + 1])[:-1], dp(a[i:])])
        return np.vstack([s, e])
    i = int(np.argmax(np.hypot(pts[:, 0] - pts[0, 0], pts[:, 1] - pts[0, 1])))
    a = dp(np.vstack([pts[:i + 1]]))
    b = dp(np.vstack([pts[i:], pts[:1]]))
    out = np.vstack([a[:-1], b[:-1]])
    return out if len(out) >= 3 else pts


def polyline(region, accuracy=.1):
    """Obrys zewnętrzny obszaru jako łamana (dokładność = największe odchylenie cięciwy)."""
    from OCP.BRepTools import BRepTools
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    faces = _faces(region)
    if not faces:
        raise kernel.CadError('Pusty obrys.')
    face = max(faces, key=_face_area)
    ex = BRepTools_WireExplorer(BRepTools.OuterWire_s(face), face)
    pts = []
    while ex.More():
        c = BRepAdaptor_Curve(ex.Current(), face)
        disc = GCPnts_QuasiUniformDeflection(c, max(1e-3, float(accuracy)))
        seg = [np.array(disc.Value(i).Coord()[:2]) for i in range(1, disc.NbPoints() + 1)] if disc.IsDone() else \
            [np.array(c.Value(t).Coord()[:2]) for t in np.linspace(c.FirstParameter(), c.LastParameter(), 9)]
        if ex.Orientation() == 1:                       # TopAbs_REVERSED
            seg = seg[::-1]
        pts += seg[:-1]
        ex.Next()
    return np.array(pts)


def _shape_frame(env, P):
    """Płaszczyzna konturu w świecie (dla rzutu): środek przestrzeni, osie u, v, w kształtu."""
    ax = np.asarray(env.axes, float)
    u, v, w = (ax.T @ P[k] for k in range(3))
    return np.asarray(env.center, float), u, v, w


def _to_shape(face, env, P):
    """Obszar rzutu (świat) -> układ kształtu (płaszczyzna w = 0)."""
    import cadquery as cq
    ax = np.asarray(env.axes, float)
    M = P @ ax
    return kernel.transformed(cq.Shape.cast(face), M, -M @ np.asarray(env.center, float)).wrapped


def base_region(env, spec, p, P, bodies, points):
    """Obszar dopasowany do elementów (bez odstępu) w płaszczyźnie kształtu (u, v)."""
    from . import enclosure_holes as eh
    key = (repr(sorted(p.items())), tuple(map(float, np.asarray(env.center).round(9))), tuple(map(float, np.asarray(env.axes).ravel().round(9))),
           tuple(s.id for s in spec.sources), tuple(id(b.shape) for b in (bodies or [])) if p['cmode'] in ('exact', 'concave', 'smooth', 'sketch') else 0,
           P.tobytes())
    if key in _CACHE:
        return _CACHE[key]
    cmode = p['cmode']
    if cmode == 'convex':
        if points is None or not len(points):
            raise kernel.CadError('Brak geometrii elementów do obrysu.')
        S = np.asarray(points, float) @ P.T
        tol = float(p['simplify'])
        hull = convex_hull(S[:, :2])
        region = _polygon_face(hull) if tol <= 0 else offset(_polygon_face(convex_hull(_simplify(hull, tol))), tol, 'uproszczenie obrysu')
    else:
        o, u, v, w = _shape_frame(env, P)
        frame = (o, u, v, w)
        if cmode == 'sketch':
            sk = {b.id: b for b in bodies or []}.get(p.get('sketch'))
            if sk is None or sk.kind != 'sketch':
                raise kernel.CadError('Wskaż szkic z zamkniętym konturem obudowy.')
            import cadquery as cq
            faces = [f.wrapped for f in sk.shape.Faces()] or [cq.Face.makeFromWires(wi).wrapped for wi in sk.shape.Wires() if wi.IsClosed()]
            if not faces:
                raise kernel.CadError('Szkic nie ma zamkniętego konturu.')
        else:
            if bodies is None:
                raise kernel.CadError('Obrys wymaga geometrii elementów.')
            by_id = {b.id: b for b in bodies}
            faces = []
            for src in spec.sources:
                b = by_id.get(src.id)
                if b is not None and b.kind in ('solid', 'mesh'):
                    faces += [f.wrapped for f in b.shape.Faces()]
        flat = eh.projected_faces(faces, frame)
        parts = [f for f in _faces(flat)]
        total = sum(_face_area(f) for f in parts)
        parts = [f for f in parts if _face_area(f) >= max(float(p['min_fragment']), 1e-9 * total)] or parts   # drobne fragmenty
        region = _to_shape(_fuse_all(parts), env, P)
        if cmode == 'concave':
            region = closing(region, float(p['degree']))
        elif cmode == 'smooth':                  # wklęsłe narożniki zaokrąglone domknięciem; wypukłe - odsunięciem (layout)
            region = closing(region, max(float(p['min_radius']), float(p['degree'])))
    count = len(_faces(region))
    if count > 1:                                          # rozłączne obszary
        if not p.get('connect', True):
            raise kernel.CadError(f'Obrys ma {count} rozłączne obszary - włącz łączenie obszarów albo zwiększ stopień dopasowania.')
        r = 1.0 if cmode == 'exact' else max(1.0, float(p['degree']))
        for _ in range(12):
            joined = closing(region, r)
            if len(_faces(joined)) == 1:
                region = joined
                break
            r *= 2
        else:
            raise kernel.CadError('Nie udało się połączyć rozłącznych obszarów - spróbuj obrysu wypukłego.')
    neck = float(p['min_neck'])
    if neck > 0 and cmode != 'convex':                                           # przewężenia węższe niż minimum - poszerzone
        opened = opening(region, neck / 2)
        thin = region if opened is None else None
        if opened is not None:
            from .enclosure import _boolean
            rest = _boolean('cut', region, opened, 'przewężenia')
            thin = rest if _face_area(rest) > 1e-6 else None
        if thin is not None:
            region = _fuse_all([region, offset(thin, neck / 2, 'poszerzenie przewężeń')])
    if float(p['simplify']) > 0 and cmode != 'convex':
        tol = float(p['simplify'])
        pts = _simplify(polyline(region, float(p['accuracy'])), tol)
        region = offset(_polygon_face(pts), tol + float(p['accuracy']), 'uproszczenie konturu')   # cięciwy nie odcinają elementów
        if not _contains(region, points, P):
            raise kernel.CadError('Uproszczenie konturu odcina część elementów - zmniejsz tolerancję uproszczenia.')
    _check(region)
    _CACHE[key] = region
    if len(_CACHE) > 32:
        _CACHE.pop(next(iter(_CACHE)))
    return region


def _contains(region, points, P):
    if points is None or not len(points):
        return True
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_OUT
    from OCP.gp import gp_Pnt
    S = np.asarray(points, float) @ P.T
    face = max(_faces(region), key=_face_area)
    step = max(1, len(S) // 4000)
    for u, v in S[::step, :2]:
        if BRepClass_FaceClassifier(face, gp_Pnt(float(u), float(v), 0.0), 1e-6).State() == TopAbs_OUT:
            return False
    return True


def _check(region):
    from OCP.BRepCheck import BRepCheck_Analyzer
    faces = _faces(region) if region is not None else []
    if len(faces) != 1:
        raise kernel.CadError('Kontur nie jest jednym zamkniętym obszarem - spróbuj obrysu wypukłego albo uproszczenia.')
    if not BRepCheck_Analyzer(faces[0]).IsValid():
        raise kernel.CadError('Kontur ma samoprzecięcia - zwiększ tolerancję uproszczenia albo wybierz obrys wypukły.')


def layout(env, spec, p, P, c_lo, c_hi, t_lo, t_hi, hs, bodies, points, margin):
    """Profil wewnętrzny (odstęp) i zewnętrzny (grubość ścianki) - opisy 'face' dla rccad.enclosure_shapes; przy
    `layers` > 1 - przekrój zmienny: opis 'stack' (warstwy wzdłuż osi kształtu, każda z własnym obrysem)."""
    cc = float(max(c_lo[0], c_hi[0], c_lo[1], c_hi[1])) + margin
    if p['cmode'] == 'smooth':
        cc = max(cc, float(p['min_radius']))            # wypukłe narożniki z promieniem co najmniej minimalnym
    tr = float(max(t_lo[0], t_hi[0], t_lo[1], t_hi[1]))
    w0, w1 = -hs[2] - c_lo[2] - margin, hs[2] + c_hi[2] + margin
    n_layers = int(p.get('layers') or 1)
    if n_layers > 1 and p['cmode'] != 'sketch':
        return _layered(env, spec, p, P, c_lo, c_hi, t_lo, t_hi, hs, bodies, margin, cc, tr, w0, w1, n_layers)
    region = base_region(env, spec, p, P, bodies, points)
    inner = offset(region, cc, 'odsunięcie o odstęp') if cc > 0 else region
    _check(inner)
    outer = offset(inner, tr, 'odsunięcie o grubość ścianki')
    _check(outer)
    g_in = dict(t='face', face=inner, w0=w0, w1=w1, acc=float(p['accuracy']))
    g_out = dict(t='face', face=outer, w0=w0 - t_lo[2], w1=w1 + t_hi[2], acc=float(p['accuracy']))
    return g_in, g_out, dict(area=_face_area(inner))


def _layered(env, spec, p, P, c_lo, c_hi, t_lo, t_hi, hs, bodies, margin, cc, tr, w0, w1, n_layers):
    """Przekrój zmienny: elementy cięte na warstwy wzdłuż osi kształtu (BRepAlgoAPI_Common z warstwą), obrys każdej
    warstwy osobno (z zapasem pionowym = odstęp, żeby stopnie wnętrza nie dotykały elementów), wnętrze = suma wyciągnięć
    obrysów + odstęp, zewnętrze = suma wyciągnięć obrysów + ścianka, każda warstwa zewnętrzna dłuższa o grubość dna /
    góry - półki między warstwami mają co najmniej tę grubość. Warstwy bez geometrii łączone z sąsiednimi."""
    import cadquery as cq
    from dataclasses import replace
    from .enclosure import _boolean, _make_box, _volume
    from .enclosure_shapes import source_points
    if bodies is None:
        raise kernel.CadError('Kontur warstwowy wymaga geometrii elementów.')
    n_layers = max(2, min(12, n_layers))
    by_id = {b.id: b for b in bodies}
    M = np.asarray(env.axes, float).T @ np.asarray(P, float).T             # układ kształtu -> świat
    c = np.asarray(env.center, float)
    big = 2.0 * float(np.linalg.norm(hs)) + 100.0
    vz = float(max(c_lo[2], c_hi[2])) + margin
    edges = np.linspace(-hs[2], hs[2], n_layers + 1)
    bands = []
    for k in range(n_layers):
        lo, hi = edges[k] - vz, edges[k + 1] + vz
        slab = kernel.transformed(cq.Shape.cast(_make_box((-big, -big, lo), (big, big, hi))), M, c).wrapped
        sliced = []
        for src in spec.sources:
            b = by_id.get(src.id)
            if b is None or b.kind not in ('solid', 'mesh'):
                continue
            piece = _boolean('common', b.shape.wrapped, slab, 'warstwa elementu')
            if _volume(piece)[0] > 1e-6:
                sliced.append(replace(b, shape=cq.Shape.cast(piece), mesh=None))
        if not sliced:
            if bands:
                bands[-1][1] = edges[k + 1]
            continue
        sub_ids = {x.id for x in sliced}
        sub_spec = replace(spec, sources=[s_ for s_ in spec.sources if s_.id in sub_ids])
        pts = source_points(env, sub_spec, sliced)
        region = base_region(env, sub_spec, dict(p, layers=1), P, sliced, pts)
        bands.append([edges[k], edges[k + 1], region])
    if not bands:
        raise kernel.CadError('Brak geometrii elementów do obrysu.')
    bands[0][0] = -hs[2]
    acc = float(p['accuracy'])
    lin, lout = [], []
    for n, (a, b, region) in enumerate(bands):
        inner = offset(region, cc, 'odsunięcie o odstęp') if cc > 0 else region
        _check(inner)
        outer = offset(inner, tr, 'odsunięcie o grubość ścianki')
        _check(outer)
        ia = w0 if n == 0 else a
        ib = w1 if n == len(bands) - 1 else b
        lin.append(dict(face=inner, w0=ia, w1=ib, acc=acc))
        lout.append(dict(face=outer, w0=ia - t_lo[2], w1=ib + t_hi[2], acc=acc))
    if len(lin) == 1:
        return dict(t='face', **lin[0]), dict(t='face', **lout[0]), dict(area=_face_area(lin[0]['face']), layer_count=1)
    g_in = dict(t='stack', layers=lin, w0=w0, w1=w1, acc=acc)
    g_out = dict(t='stack', layers=lout, w0=w0 - t_lo[2], w1=w1 + t_hi[2], acc=acc)
    return g_in, g_out, dict(area=max(_face_area(L['face']) for L in lin), layer_count=len(lin))
