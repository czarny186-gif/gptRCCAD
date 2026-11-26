"""Generator obudów - etap 5: kształty obudowy inne niż prostopadłościan.

Każdy kształt jest opisany w „układzie kształtu” (u, v, w) - permutacji / obrocie osi przestrzeni elementów
(orientacja kształtu). Wnętrze i zewnętrze to ta sama rodzina profili:
- 'rrect'   - prostokąt (u0..u1, v0..v1) z zaokrąglonymi (r) albo sfazowanymi (c) narożnikami, wyciągnięty wzdłuż w,
- 'ellipse' - elipsa / okrąg (półosie a, b) wyciągnięta wzdłuż w (okrąg: BRepPrimAPI_MakeCylinder),
- 'ngon'    - wielokąt foremny (n boków, apotema ap) wyciągnięty wzdłuż w,
- 'trap'    - trapez w płaszczyźnie (u, w) (ścianki boczne pochylone o kąt) wyciągnięty wzdłuż v,
- 'desk'    - pulpit: profil (v, w) z pochyloną górą, wyciągnięty wzdłuż u.
Profile 2D są budowane przed wyciągnięciem (zaokrąglenia narożników - BRepFilletAPI_MakeFillet2d na profilu, nie
zaokrąglanie krawędzi gotowej bryły), bryły - BRepPrimAPI_MakePrism / MakeCylinder, obudowa - Boolean Cut.

Dopasowanie do elementów nie korzysta z samej ramki: wierzchołki siatek elementów (w układzie kształtu) muszą leżeć
we wnętrzu pomniejszonym o odstęp (okrąg / elipsa / wielokąt / narożniki / pochylenia liczone dokładnie dla punktów),
a dokładna bryła sprawdzana jest operacją Boolean (część elementu poza wnętrzem musi mieć zerową objętość)."""
from __future__ import annotations

import math

import numpy as np

from . import kernel

SHAPES = ('box', 'rounded', 'chamfer', 'cylinder', 'ellipse', 'polygon', 'trapezoid', 'desk', 'contour')
SHAPE_LABELS = {'box': 'Prostokątna', 'rounded': 'Prostokątna z zaokrąglonymi narożnikami', 'chamfer': 'Prostokątna ze sfazowanymi narożnikami',
                'cylinder': 'Cylindryczna', 'ellipse': 'Eliptyczna', 'polygon': 'Wielokątna', 'trapezoid': 'Trapezowa',
                'desk': 'Pulpitowa (pochylona góra)', 'contour': 'Dopasowana do konturu'}
ORIENTS = {'rounded': ('z', 'x', 'y'), 'chamfer': ('z', 'x', 'y'), 'cylinder': ('z', 'x', 'y'), 'ellipse': ('z', 'x', 'y'),
           'polygon': ('z', 'x', 'y'), 'trapezoid': ('x', 'y'), 'desk': ('y-', 'y+', 'x-', 'x+'), 'contour': ('z', 'x', 'y')}
ORIENT_LABELS = {'z': 'Oś Z (pionowo)', 'x': 'Oś X (poziomo)', 'y': 'Oś Y (poziomo)', 'y-': 'Przód: Y−', 'y+': 'Przód: Y+',
                 'x-': 'Przód: X−', 'x+': 'Przód: X+'}
TRAP_ORIENT_LABELS = {'x': 'Pochylone ścianki X', 'y': 'Pochylone ścianki Y'}
SHAPE_DEFAULTS = dict(radius=5.0, chamfer=4.0, diameter=0.0, dx=0.0, dy=0.0, sides=6, angle=15.0, front=0.0, back=0.0,
                      orient='', auto=True, cmode='concave', degree=6.0, min_radius=2.0, min_neck=0.0, accuracy=.1, simplify=0.0,
                      min_fragment=.5, connect=True, sketch=None, layers=1)
MAX_ANGLE = 60.0
MIN_SIZE = 0.2
SQ2 = math.sqrt(2.0)

_P = {'z': np.eye(3), 'x': np.array([[0, 1, 0], [0, 0, 1], [1, 0, 0]], float), 'y': np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]], float),
      'y-': np.eye(3), 'y+': np.array([[-1, 0, 0], [0, -1, 0], [0, 0, 1]], float),
      'x-': np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float), 'x+': np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]], float)}
_TRAP_P = {'x': np.eye(3), 'y': np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]], float)}


def params_of(spec):
    p = dict(SHAPE_DEFAULTS)
    p.update(getattr(spec, 'shape_params', None) or {})
    kind = spec.shape or 'box'
    if kind in ORIENTS and p.get('orient') not in ORIENTS[kind]:
        p['orient'] = ORIENTS[kind][0]
    return p


def frame(kind, orient):
    """Macierz 3x3: wiersze - osie u, v, w kształtu zapisane w układzie przestrzeni elementów."""
    if kind == 'trapezoid':
        return _TRAP_P.get(orient, np.eye(3))
    return _P.get(orient, np.eye(3))


def _sides(P):
    """Strony przestrzeni (x-, x+, …) odpowiadające stronom -/+ każdej osi kształtu."""
    out = []
    for row in P:
        i = int(np.argmax(np.abs(row)))
        s = 1 if row[i] > 0 else -1
        out.append(('xyz'[i] + ('-' if s > 0 else '+'), 'xyz'[i] + ('+' if s > 0 else '-')))
    return out


def source_points(env, spec, bodies):
    """Wierzchołki siatek elementów źródłowych w układzie przestrzeni (N x 3). Elementy są w środku obudowy - punkty
    wystarczają do sprawdzenia zawierania w wypukłym wnętrzu dla siatek; bryły B-Rep dodatkowo sprawdza Boolean."""
    by_id = {b.id: b for b in bodies or []}
    c = np.asarray(env.center, float)
    ax = np.asarray(env.axes, float)
    chunks = []
    for src in spec.sources:
        body = by_id.get(src.id)
        if body is None:
            continue
        mesh = body.mesh
        if mesh is None:
            try:
                mesh = kernel.display_mesh(body.shape)
            except Exception:
                mesh = None
        if mesh is not None and len(mesh.vertices):
            chunks.append((np.asarray(mesh.vertices, float) - c) @ ax.T)
    return np.concatenate(chunks) if chunks else None


# ---------------------------------------------------------------------------------------------- opis geometrii
def grow(g, d):
    """Profil odsunięty równomiernie o d (d < 0 - do środka) - wnętrze powiększone dla połączeń (etap 4)."""
    g = dict(g)
    t = g['t']
    if t == 'rrect':
        g.update(u0=g['u0'] - d, u1=g['u1'] + d, v0=g['v0'] - d, v1=g['v1'] + d, w0=g['w0'] - d, w1=g['w1'] + d)
        if g['r'] > 0:
            g['r'] = max(g['r'] + d, 0.0)
        if g['c'] > 0:
            g['c'] = max(g['c'] + d * (2 - SQ2), 0.0)
    elif t == 'ellipse':
        g.update(a=g['a'] + d, b=g['b'] + d, w0=g['w0'] - d, w1=g['w1'] + d)
    elif t == 'ngon':
        g.update(ap=g['ap'] + d, w0=g['w0'] - d, w1=g['w1'] + d)
    elif t == 'trap':
        cos = 1 / math.sqrt(1 + g['tan'] ** 2)
        g.update(hb=g['hb'] + d / cos + d * g['tan'], w0=g['w0'] - d, w1=g['w1'] + d, v0=g['v0'] - d, v1=g['v1'] + d)
    elif t == 'face':
        from .enclosure_contour import offset
        g.update(face=offset(g['face'], d, 'odsunięcie profilu') if abs(d) > 1e-12 else g['face'], w0=g['w0'] - d, w1=g['w1'] + d)
    elif t == 'stack':                                     # warstwy: każda odsunięta i wydłużona (suma odsuniętych warstw)
        g['layers'] = [grow(dict(L, t='face'), d) for L in g['layers']]
        g.update(w0=g['w0'] - d, w1=g['w1'] + d)
    elif t == 'desk':
        cos = 1 / math.sqrt(1 + g['tan'] ** 2)
        g.update(h0=g['h0'] + d / cos - d * g['tan'] + d, u0=g['u0'] - d, u1=g['u1'] + d, v0=g['v0'] - d, v1=g['v1'] + d, w0=g['w0'] - d)
    return g


def profile(g, samples=48):
    """Obrys profilu jako łamana: (punkty 2D, (oś a, oś b), oś wyciągnięcia, zakres, wierzchołki-narożniki)."""
    t = g['t']
    if t == 'rrect':
        u0, u1, v0, v1, r, c = g['u0'], g['u1'], g['v0'], g['v1'], g['r'], g['c']
        pts, corners = [], []
        for cx, cy, a0 in ((u1, v0, -90), (u1, v1, 0), (u0, v1, 90), (u0, v0, 180)):
            if r > 1e-9:
                ox, oy = cx - r * np.sign(cx - (u0 + u1) / 2), cy - r * np.sign(cy - (v0 + v1) / 2)
                for k in range(9):
                    a = math.radians(a0 + 90 * k / 8)
                    pts.append((ox + r * math.cos(a), oy + r * math.sin(a)))
            elif c > 1e-9:
                din, dout = {(-90): ((1, 0), (0, 1)), 0: ((0, 1), (-1, 0)), 90: ((-1, 0), (0, -1)), 180: ((0, -1), (1, 0))}[a0]
                pts += [(cx - din[0] * c, cy - din[1] * c), (cx + dout[0] * c, cy + dout[1] * c)]
                corners += [len(pts) - 2, len(pts) - 1]
            else:
                pts.append((cx, cy))
                corners.append(len(pts) - 1)
        if r > 1e-9:
            corners = list(range(0, len(pts), 9)) + list(range(8, len(pts), 9))
        return np.array(pts), (0, 1), 2, (g['w0'], g['w1']), corners
    if t == 'ellipse':
        a = np.linspace(0, 2 * np.pi, samples, endpoint=False)
        return np.c_[g['a'] * np.cos(a), g['b'] * np.sin(a)], (0, 1), 2, (g['w0'], g['w1']), [0, samples // 4, samples // 2, 3 * samples // 4]
    if t == 'ngon':
        n, ap = int(g['n']), g['ap']
        R = ap / math.cos(math.pi / n)
        a = -math.pi / 2 + math.pi / n + 2 * math.pi * np.arange(n) / n           # bok na dole (normalna -v)
        return np.c_[R * np.cos(a), R * np.sin(a)], (0, 1), 2, (g['w0'], g['w1']), list(range(n))
    if t == 'trap':
        hb, tan, w0, w1 = g['hb'], g['tan'], g['w0'], g['w1']
        ht = hb - (w1 - w0) * tan
        return np.array([(-hb, w0), (hb, w0), (ht, w1), (-ht, w1)]), (0, 2), 1, (g['v0'], g['v1']), [0, 1, 2, 3]
    if t == 'desk':
        v0, v1, w0, h0, tan = g['v0'], g['v1'], g['w0'], g['h0'], g['tan']
        return np.array([(v0, w0), (v1, w0), (v1, w0 + h0 + (v1 - v0) * tan), (v0, w0 + h0)]), (1, 2), 0, (g['u0'], g['u1']), [0, 1, 2, 3]
    if t == 'face':
        from .enclosure_contour import polyline
        pts = polyline(g['face'], max(.05, g.get('acc', .1)))
        step = max(1, len(pts) // 16)
        return pts, (0, 1), 2, (g['w0'], g['w1']), list(range(0, len(pts), step))
    raise kernel.CadError('Nieznany kształt obudowy.')


def _shape_pts(pts2, axes, along, value):
    out = np.zeros((len(pts2), 3))
    out[:, axes[0]] = pts2[:, 0]
    out[:, axes[1]] = pts2[:, 1]
    out[:, along] = value
    return out


def bbox(g, P):
    """Ramka profilu w układzie przestrzeni (lo, hi)."""
    if g['t'] == 'stack':
        boxes = [bbox(dict(L, t='face'), P) for L in g['layers']]
        return np.min([b[0] for b in boxes], axis=0), np.max([b[1] for b in boxes], axis=0)
    pts2, axes, along, (s0, s1), _ = profile(g)
    shape = np.vstack([_shape_pts(pts2, axes, along, s0), _shape_pts(pts2, axes, along, s1)])
    local = shape @ P                       # wiersze P - osie kształtu w układzie przestrzeni: local = s @ P
    return local.min(axis=0), local.max(axis=0)


def mesh(g, P, world, caps=(True, True), key0=0, faces=True):
    """Szybka siatka podglądu (bez OCC): graniastosłup z obrysu profilu (profile są wypukłe - wachlarz trójkątów)."""
    if g['t'] == 'stack':
        from .enclosure import merge_meshes
        return merge_meshes([mesh(dict(L, t='face'), P, world, caps, key0 + 1000 * n, faces) for n, L in enumerate(g['layers'])])
    pts2, axes, along, (s0, s1), corners = profile(g)
    n = len(pts2)
    a = _shape_pts(pts2, axes, along, s0) @ P
    b = _shape_pts(pts2, axes, along, s1) @ P
    v = np.array([world(p) for p in np.vstack([a, b])], np.float32)
    tris = []
    if g['t'] == 'face':
        caps = (False, False)                      # kontur może być wklęsły - podgląd bez den (same ścianki)
    if faces:
        for k in range(n):
            j = (k + 1) % n
            tris += [(k, j, n + j), (k, n + j, n + k)]
        if caps[0]:
            tris += [(0, k + 1, k) for k in range(1, n - 1)]
        if caps[1]:
            tris += [(n, n + k, n + k + 1) for k in range(1, n - 1)]
    edges = {key0: np.vstack([v[:n], v[:1]]), key0 + 1: np.vstack([v[n:], v[n:n + 1]])}
    for k in corners:
        edges[key0 + 2 + k] = v[[k, n + k]]
    return kernel.DisplayMesh(v, np.array(tris, np.uint32).reshape(-1, 3), edges, tuple(map(float, v.mean(axis=0))),
                              float(np.linalg.norm(v.max(axis=0) - v.min(axis=0))))


def solid(g, P):
    """Bryła profilu (TopoDS) w układzie przestrzeni: profil 2D (z zaokrągleniem narożników na profilu) wyciągnięty."""
    import cadquery as cq
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeWire
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism
    from OCP.gp import gp_Ax2, gp_Dir, gp_Elips, gp_Pnt, gp_Vec
    t = g['t']
    if t == 'stack':                                       # kontur warstwowy: suma wyciągnięć warstw (przekrój zmienny)
        from .enclosure import _unified
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
        from OCP.TopTools import TopTools_ListOfShape
        prisms = [solid(dict(L, t='face'), P) for L in g['layers']]
        if len(prisms) == 1:
            return prisms[0]
        args, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
        args.Append(prisms[0])
        for x in prisms[1:]:
            tools.Append(x)
        op = BRepAlgoAPI_Fuse()
        op.SetArguments(args)
        op.SetTools(tools)
        op.SetRunParallel(True)
        op.Build()
        if not op.IsDone():
            raise kernel.CadError('Suma warstw konturu nie powiodła się.')
        return _unified(op.Shape())
    pts2, axes, along, (s0, s1), _ = profile(g)
    if s1 - s0 < 1e-6:
        raise kernel.CadError('Obudowa ma zerową długość.')
    vec = np.zeros(3)
    vec[along] = s1 - s0
    if t == 'face':
        mk = BRepPrimAPI_MakePrism(_moved_face(g['face'], s0), gp_Vec(0, 0, float(s1 - s0)))
        mk.Build()
        if not mk.IsDone():
            raise kernel.CadError('Wyciągnięcie profilu konturu nie powiodło się.')
        return kernel.transformed(cq.Shape.cast(mk.Shape()), P.T, np.zeros(3)).wrapped
    if t == 'ellipse' and abs(g['a'] - g['b']) < 1e-9:
        if g['a'] <= 1e-6:
            raise kernel.CadError('Średnica obudowy musi być większa od zera.')
        mk = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, s0), gp_Dir(0, 0, 1)), g['a'], s1 - s0)
        mk.Build()
        if not mk.IsDone():
            raise kernel.CadError('Nie udało się utworzyć walca obudowy.')
        shape = mk.Shape()
    else:
        if t == 'ellipse':
            if min(g['a'], g['b']) <= 1e-6:
                raise kernel.CadError('Średnice elipsy muszą być większe od zera.')
            major, minor = max(g['a'], g['b']), min(g['a'], g['b'])
            xdir = gp_Dir(1, 0, 0) if g['a'] >= g['b'] else gp_Dir(0, 1, 0)
            edge = BRepBuilderAPI_MakeEdge(gp_Elips(gp_Ax2(gp_Pnt(0, 0, s0), gp_Dir(0, 0, 1), xdir), major, minor)).Edge()
            wire = BRepBuilderAPI_MakeWire(edge).Wire()
        else:
            poly = BRepBuilderAPI_MakePolygon()
            base = pts2 if t != 'rrect' or g['r'] <= 1e-9 else np.array([(g['u1'], g['v0']), (g['u1'], g['v1']), (g['u0'], g['v1']), (g['u0'], g['v0'])])
            for p in _shape_pts(base, axes, along, s0):
                poly.Add(gp_Pnt(*map(float, p)))
            poly.Close()
            if not poly.IsDone():
                raise kernel.CadError('Niepoprawny profil obudowy.')
            wire = poly.Wire()
        mf = BRepBuilderAPI_MakeFace(wire, True)
        if not mf.IsDone():
            raise kernel.CadError('Nie udało się utworzyć profilu obudowy.')
        face = mf.Face()
        if t == 'rrect' and g['r'] > 1e-9:
            face = _fillet_profile(face, g['r'])
        mk = BRepPrimAPI_MakePrism(face, gp_Vec(*map(float, vec)))
        mk.Build()
        if not mk.IsDone():
            raise kernel.CadError('Wyciągnięcie profilu obudowy nie powiodło się.')
        shape = mk.Shape()
    return kernel.transformed(cq.Shape.cast(shape), P.T, np.zeros(3)).wrapped


def _moved_face(face, z):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Vec
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(0, 0, float(z)))
    return BRepBuilderAPI_Transform(face, t, True).Shape()


def _fillet_profile(face, r):
    """Zaokrąglenie narożników profilu przed wyciągnięciem (BRepFilletAPI_MakeFillet2d)."""
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet2d
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    mk = BRepFilletAPI_MakeFillet2d(face)
    ex = TopExp_Explorer(face, TopAbs_VERTEX)
    seen = []
    while ex.More():
        v = TopoDS.Vertex_s(ex.Current())
        if not any(v.IsSame(s) for s in seen):
            seen.append(v)
            mk.AddFillet(v, float(r))
        ex.Next()
    mk.Build()
    if not mk.IsDone():
        raise kernel.CadError('Zaokrąglenie narożników profilu nie powiodło się - zmniejsz promień.')
    return mk.Shape()


# ---------------------------------------------------------------------------------------------- dopasowanie
def _rounded_growth(S, U, V, r, cc):
    """Najmniejsze powiększenie d prostokąta, przy którym punkty mieszczą się w zaokrąglonych narożnikach (z odstępem)."""
    if r <= 1e-9 or S is None or not len(S):
        return 0.0

    def worst(d):
        out = -1.0
        for su in (-1, 1):
            for sv in (-1, 1):
                x, y = su * S[:, 0], sv * S[:, 1]
                cx, cy = (U[1 if su > 0 else 0] + d - r), (V[1 if sv > 0 else 0] + d - r)
                m = (x > cx) & (y > cy)
                if m.any():
                    out = max(out, float(np.max(np.hypot(x[m] - cx, y[m] - cy) + cc - r)))
        return out
    if worst(0.0) <= 0:
        return 0.0
    lo, hi = 0.0, r + cc + 1.0
    while worst(hi) > 0:
        hi *= 2
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if worst(mid) > 0 else (lo, mid)
    return hi


def shape_layout(env, spec, points=None, margin=0.0, bodies=None):
    """Układ obudowy o kształcie spec.shape: profil wnętrza dopasowany do elementów (z odstępami) i profil zewnętrza
    (z grubościami ścianek). Zwraca dict jak box_layout (inner / outer - ramki w układzie przestrzeni, rozmiary) oraz
    g_in, g_out (opis profili), P (orientacja), info (wartości do pokazania w oknie). Złe wartości - CadError."""
    from .enclosure import clearance_of, walls_of, SIDE_LABELS, WALL_OF, MAX_VALUE, MIN_WALL, MODES
    kind = spec.shape
    if kind not in SHAPES or kind == 'box':
        raise kernel.CadError('Nieznany kształt obudowy.')
    if spec.mode not in MODES:
        raise kernel.CadError('Nieznany rodzaj obudowy.')
    p = params_of(spec)
    P = frame(kind, p['orient'])
    if spec.mode == 'open' and kind in ('rounded', 'chamfer', 'cylinder', 'ellipse', 'polygon', 'contour') and p['orient'] != 'z':
        raise kernel.CadError('Obudowa otwarta tego kształtu wymaga orientacji pionowej (oś Z).')
    c, w = clearance_of(spec), walls_of(spec)
    for key, value in c.items():
        if not np.isfinite(value) or value < 0 or value > MAX_VALUE:
            raise kernel.CadError(f'Odstęp {SIDE_LABELS[key]} musi być od 0 do {MAX_VALUE:g} mm.')
    for key, value in w.items():
        if spec.mode == 'open' and key == 'top':
            continue
        if not np.isfinite(value) or value < MIN_WALL or value > MAX_VALUE:
            raise kernel.CadError(f'Grubość ścianki {SIDE_LABELS[key]} musi być od {MIN_WALL:g} do {MAX_VALUE:g} mm.')
    wall = lambda side: 0.0 if (spec.mode == 'open' and side == 'z+') else w[WALL_OF[side]]
    sides = _sides(P)
    c_lo = np.array([c[s[0]] for s in sides])
    c_hi = np.array([c[s[1]] for s in sides])
    t_lo = np.array([wall(s[0]) for s in sides])
    t_hi = np.array([wall(s[1]) for s in sides])
    hs = np.abs(P) @ (np.asarray(env.size, float) / 2)
    S = None if points is None or not len(points) else np.asarray(points, float) @ P.T
    if S is None:                                     # bez siatek - narożniki przestrzeni
        S = np.array([[sx * hs[0], sy * hs[1], sz * hs[2]] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])
    lo = -hs - c_lo
    hi = hs + c_hi
    cc = float(max(c_lo[0], c_hi[0], c_lo[1], c_hi[1])) + margin       # odstęp w profilu (największy z bocznych)
    tr = float(max(t_lo[0], t_hi[0], t_lo[1], t_hi[1]))                 # grubość ścianki profilu (wymagana wszędzie)
    tmin = float(min(t_lo[0], t_hi[0], t_lo[1], t_hi[1]))
    auto = bool(p.get('auto', True))
    info = {}
    if kind in ('rounded', 'chamfer'):
        R = float(p['radius'] if kind == 'rounded' else p['chamfer'])
        if not np.isfinite(R) or R <= 0:
            raise kernel.CadError('Promień narożników musi być większy od zera.' if kind == 'rounded' else 'Fazowanie musi być większe od zera.')
        lo_m, hi_m = lo - margin, hi + margin
        r_in = max(R - tmin, 0.0) if kind == 'rounded' else 0.0
        c_in = max(R - tmin * (2 - SQ2), 0.0) if kind == 'chamfer' else 0.0
        U, V = (lo_m[0], hi_m[0]), (lo_m[1], hi_m[1])
        if kind == 'rounded':
            d = _rounded_growth(np.c_[S[:, 0], S[:, 1]], (-U[0], U[1]), (-V[0], V[1]), r_in, cc)
        else:
            d = 0.0
            if c_in > 0:
                for su in (-1, 1):
                    for sv in (-1, 1):
                        lim = (U[1] if su > 0 else -U[0]) + (V[1] if sv > 0 else -V[0]) - c_in
                        d = max(d, float(np.max((su * S[:, 0] + sv * S[:, 1] + cc * SQ2 - lim) / 2)))
        g_in = dict(t='rrect', u0=U[0] - d, u1=U[1] + d, v0=V[0] - d, v1=V[1] + d, w0=lo_m[2], w1=hi_m[2], r=r_in, c=c_in)
        ihalf = min(g_in['u1'] - g_in['u0'], g_in['v1'] - g_in['v0']) / 2
        g_in['r'] = min(g_in['r'], max(ihalf - .01, 0.0))
        g_in['c'] = min(g_in['c'], max(2 * ihalf - .01, 0.0))
        g_out = dict(t='rrect', u0=g_in['u0'] - t_lo[0], u1=g_in['u1'] + t_hi[0], v0=g_in['v0'] - t_lo[1], v1=g_in['v1'] + t_hi[1],
                     w0=g_in['w0'] - t_lo[2], w1=g_in['w1'] + t_hi[2], r=R if kind == 'rounded' else 0.0, c=R if kind == 'chamfer' else 0.0)
        half = min(g_out['u1'] - g_out['u0'], g_out['v1'] - g_out['v0']) / 2
        if (kind == 'rounded' and R > half - 1e-6) or (kind == 'chamfer' and R > 2 * half - 1e-6):
            raise kernel.CadError(f'{"Promień narożników" if kind == "rounded" else "Fazowanie"} jest za duży - najwyżej {(half if kind == "rounded" else 2 * half) - .01:.2f} mm.')
    elif kind in ('cylinder', 'ellipse', 'polygon'):
        if kind == 'cylinder':
            fit = float(np.max(np.hypot(S[:, 0], S[:, 1]))) + cc
            if auto:
                r_in = fit
            else:
                r_in = float(p['diameter']) / 2 - tr
                if r_in < fit - 1e-6:
                    raise kernel.CadError(f'Średnica za mała - elementy z odstępem wymagają co najmniej {2 * (fit + tr):.2f} mm.')
            a_in = b_in = r_in
            info['diameter'] = 2 * (r_in + tr)
            g_in = dict(t='ellipse', a=a_in, b=b_in, w0=lo[2] - margin, w1=hi[2] + margin)
        elif kind == 'ellipse':
            hx, hy = max(hs[0], 1e-3), max(hs[1], 1e-3)
            if auto:
                s = float(np.max(np.hypot(S[:, 0] / hx, S[:, 1] / hy)))
                a_in, b_in = s * hx + cc, s * hy + cc
            else:
                a_in, b_in = float(p['dx']) / 2 - tr, float(p['dy']) / 2 - tr
                if min(a_in, b_in) - cc <= 1e-6 or float(np.max(np.hypot(S[:, 0] / (a_in - cc), S[:, 1] / (b_in - cc)))) > 1 + 1e-9:
                    raise kernel.CadError('Elipsa za mała - elementy z odstępem się nie mieszczą (włącz dopasowanie albo zwiększ średnice).')
            info['dx'], info['dy'] = 2 * (a_in + tr), 2 * (b_in + tr)
            g_in = dict(t='ellipse', a=a_in, b=b_in, w0=lo[2] - margin, w1=hi[2] + margin)
        else:
            n = int(p['sides'])
            if n < 3 or n > 64:
                raise kernel.CadError('Wielokąt musi mieć od 3 do 64 boków.')
            ang = -math.pi / 2 + 2 * math.pi * np.arange(n) / n
            fit = float(np.max(S[:, 0][:, None] * np.cos(ang)[None] + S[:, 1][:, None] * np.sin(ang)[None])) + cc
            if auto:
                ap = fit
            else:
                ap = float(p['diameter']) / 2 * math.cos(math.pi / n) - tr
                if ap < fit - 1e-6:
                    raise kernel.CadError(f'Wielokąt za mały - średnica opisana co najmniej {2 * (fit + tr) / math.cos(math.pi / n):.2f} mm.')
            info['diameter'] = 2 * (ap + tr) / math.cos(math.pi / n)
            g_in = dict(t='ngon', n=n, ap=ap, w0=lo[2] - margin, w1=hi[2] + margin)
        g_out = grow(g_in, tr)
        g_out.update(w0=g_in['w0'] - t_lo[2], w1=g_in['w1'] + t_hi[2])
    elif kind == 'trapezoid':
        ang = float(p['angle'])
        if not np.isfinite(ang) or ang < 0 or ang >= MAX_ANGLE:
            raise kernel.CadError(f'Kąt pochylenia ścianek musi być od 0 do {MAX_ANGLE:g}°.')
        tan = math.tan(math.radians(ang))
        cos = math.cos(math.radians(ang))
        w0, w1 = lo[2] - margin, hi[2] + margin
        cu = float(max(c_lo[0], c_hi[0])) + margin
        tu = float(max(t_lo[0], t_hi[0]))
        hb = float(np.max(np.abs(S[:, 0]) + (S[:, 2] - w0) * tan)) + cu / cos
        g_in = dict(t='trap', hb=hb, tan=tan, w0=w0, w1=w1, v0=lo[1] - margin, v1=hi[1] + margin)
        if hb - (w1 - w0) * tan < MIN_SIZE:
            raise kernel.CadError('Kąt pochylenia za duży - górna część wnętrza znika.')
        g_out = dict(t='trap', hb=hb + tu / cos + t_lo[2] * tan, tan=tan, w0=w0 - t_lo[2], w1=w1 + t_hi[2], v0=g_in['v0'] - t_lo[1], v1=g_in['v1'] + t_hi[1])
        if g_out['hb'] - (g_out['w1'] - g_out['w0']) * tan < MIN_SIZE:
            raise kernel.CadError('Kąt pochylenia za duży - zwęża się górna ścianka.')
        info['top'] = 2 * (g_out['hb'] - (g_out['w1'] - g_out['w0']) * tan)
    elif kind == 'desk':
        v0, v1, w0 = lo[1] - margin, hi[1] + margin, lo[2] - margin
        v0o, v1o, w0o = v0 - t_lo[1], v1 + t_hi[1], w0 - t_lo[2]
        ttop = t_hi[2]
        ctop = c_hi[2] + margin
        if auto:
            ang = float(p['angle'])
            if not np.isfinite(ang) or abs(ang) >= MAX_ANGLE:
                raise kernel.CadError(f'Kąt pochylenia musi być od −{MAX_ANGLE:g} do {MAX_ANGLE:g}°.')
            tan = math.tan(math.radians(ang))
        else:
            hf, hb_ = float(p['front']), float(p['back'])
            if hf <= 0 or hb_ <= 0:
                raise kernel.CadError('Wysokości przedniej i tylnej ścianki muszą być większe od zera.')
            tan = (hb_ - hf) / max(v1o - v0o, 1e-9)
            if abs(math.degrees(math.atan(tan))) >= MAX_ANGLE:
                raise kernel.CadError(f'Różnica wysokości daje pochylenie większe niż {MAX_ANGLE:g}°.')
        cos = 1 / math.sqrt(1 + tan * tan)
        fit = float(np.max(S[:, 2] - w0 - (S[:, 1] - v0) * tan)) + ctop / cos
        if auto:
            h0 = fit
        else:
            h0 = (hf + w0o) - (w0 + ttop / cos + (v0o - v0) * tan)
            if h0 < fit - 1e-6:
                least = fit + w0 + ttop / cos + (v0o - v0) * tan - w0o
                raise kernel.CadError(f'Przednia ścianka za niska - elementy z odstępem wymagają co najmniej {least:.2f} mm.')
        if min(h0, h0 + (v1 - v0) * tan) < MIN_SIZE:
            raise kernel.CadError('Pochylenie za duże - wnętrze znika przy jednej ze ścianek.')
        g_in = dict(t='desk', u0=lo[0] - margin, u1=hi[0] + margin, v0=v0, v1=v1, w0=w0, h0=h0, tan=tan)
        h0o = (w0 + h0 + ttop / cos + (v0o - v0) * tan) - w0o
        g_out = dict(t='desk', u0=g_in['u0'] - t_lo[0], u1=g_in['u1'] + t_hi[0], v0=v0o, v1=v1o, w0=w0o, h0=h0o, tan=tan)
        info.update(front=h0o, back=h0o + (v1o - v0o) * tan, angle=math.degrees(math.atan(tan)))
    elif kind == 'contour':
        from . import enclosure_contour as contour
        g_in, g_out, info = contour.layout(env, spec, p, P, c_lo, c_hi, t_lo, t_hi, hs, bodies, points, margin)
    else:
        raise kernel.CadError('Nieznany kształt obudowy.')
    ilo, ihi = bbox(g_in, P)
    olo, ohi = bbox(g_out, P)
    if float((ihi - ilo).min()) <= 1e-6:
        raise kernel.CadError('Wnętrze obudowy musi mieć dodatnie wymiary.')
    return dict(inner=(ilo, ihi), outer=(olo, ohi), inner_size=ihi - ilo, outer_size=ohi - olo, g_in=g_in, g_out=g_out, P=P,
                kind=kind, info=info, tmin=tmin, tr=tr)


def open_inner(lay, spec):
    """Wnętrze obudowy otwartej - wychodzi ponad górę (bez górnej ścianki)."""
    g = dict(lay['g_in'])
    T = 2.0 + float(np.max(lay['outer_size']))
    if g['t'] in ('rrect', 'ellipse', 'ngon', 'face'):
        g['w1'] += T
        return solid(g, lay['P'])
    if g['t'] == 'stack':
        top = max(range(len(g['layers'])), key=lambda n: g['layers'][n]['w1'])
        g['layers'] = [dict(L, w1=L['w1'] + T) if n == top else L for n, L in enumerate(g['layers'])]
        return solid(g, lay['P'])
    if g['t'] == 'desk':
        g['h0'] += T
        return solid(g, lay['P'])
    if g['t'] == 'trap':          # trapez: wnętrze + prostopadłościan nad jego górnym przekrojem
        from .enclosure import _boolean, _make_box
        ht = g['hb'] - (g['w1'] - g['w0']) * g['tan']
        top = dict(t='rrect', u0=-ht, u1=ht, v0=g['v0'], v1=g['v1'], w0=g['w1'] - 1e-3, w1=g['w1'] + T, r=0.0, c=0.0)
        return _boolean('fuse', solid(g, lay['P']), solid(top, lay['P']), 'otwarta góra')
    raise kernel.CadError('Nieznany kształt obudowy.')


def contained(env, lay, spec, bodies):
    """Rzeczywiste zawieranie: część każdej bryły źródłowej poza wnętrzem (Boolean Cut) ma zerową objętość."""
    from .enclosure import _boolean, _volume, _cq
    by_id = {b.id: b for b in bodies or []}
    inner = None
    for src in spec.sources:
        body = by_id.get(src.id)
        if body is None or body.kind != 'solid':
            continue
        if inner is None:
            inner = kernel.transformed(_cq(solid(lay['g_in'], lay['P'])), np.asarray(env.axes, float).T, np.asarray(env.center, float)).wrapped
        vol = _volume(body.shape.wrapped)[0]
        rest = _volume(_boolean('cut', body.shape.wrapped, inner, 'zawieranie elementu'))[0]
        if rest > max(1e-6, 1e-7 * vol):
            return False
    return True


def fitted_layout(env, spec, points=None, bodies=None, verify=True):
    """Układ z dopasowaniem; z bryłami źródłowymi - sprawdzone zawieranie (przy niedokładnej siatce zakrzywionych
    powierzchni wnętrze powiększa się o małe zapasy aż do zawierania; ręczne wymiary - tylko sprawdzenie)."""
    if not verify:                                  # podgląd na żywo: bez sprawdzania Boolean (to robi dokładny wynik w tle)
        return shape_layout(env, spec, points, 0.0, bodies=bodies)
    auto = bool(params_of(spec).get('auto', True)) or spec.shape in ('rounded', 'chamfer', 'trapezoid', 'contour')
    for margin in ((0.0, .05, .15, .4, 1.0) if auto else (0.0,)):
        lay = shape_layout(env, spec, points, margin, bodies=bodies)
        if bodies is None or contained(env, lay, spec, bodies):
            return lay
    raise kernel.CadError('Elementy nie mieszczą się we wnętrzu obudowy - zwiększ wymiary kształtu.')
