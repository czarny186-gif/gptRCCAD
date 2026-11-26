"""Generator obudów - etap 16: żebra wzmacniające.

Żebra na jednej albo kilku wskazanych powierzchniach (wewnętrznych albo zewnętrznych, płaskich albo zakrzywionych) jednej
części obudowy. Układ powierzchni: punkt i normalna (od materiału), osie u, v (rccad.enclosure_holes.wall_frame).

Rodzaje: pojedyncze, równoległe, krzyżowe, siatka prostokątna, siatka trójkątna, struktura sześciokątna, promieniowe,
narożne, wzmocnienia słupków montażowych, według szkicu. Każde żebro to odcinek w płaszczyźnie (u, v):
- przekrój poprzeczny (grubość, pochylenie boków, zaokrąglenie podstawy - łuki styczne do podłoża i boku, wpuszczenie
  w ściankę) wyciągnięty wzdłuż odcinka (BRepPrimAPI_MakePrism),
- przy zmiennej wysokości (narastająca, ścięte końce) - część wspólna z profilem bocznym (BRepAlgoAPI_Common),
- ograniczenie do dozwolonego obszaru: rzut wskazanej powierzchni pomniejszony o margines (otwory i wentylacja w niej -
  wycięte razem z marginesem) oraz warstwa nad powierzchnią z danych generatora (wnętrze / zewnętrze obudowy odsunięte
  o wysokość) - żebro dokładnie przylega także do powierzchni zakrzywionych,
- przeszkody (BRepAlgoAPI_Cut): przestrzenie ochronne komponentów (ramka + odstęp; nad przeszkodą wysoko - żebro
  obniżone, nisko - skrócone / podzielone), inne części obudowy (pokrywa) z odstępem, otwory słupków montażowych,
- fragmenty krótsze niż minimalna długość i niepołączone ze ścianką są usuwane, reszta łączona z częścią (Fuse) w jedną
  bryłę i sprawdzana (BRepCheck_Analyzer).
Program nie deklaruje wzrostu wytrzymałości - wymaga to analizy mechanicznej."""
from __future__ import annotations

import math

import numpy as np

from . import kernel
from . import enclosure_holes as eh

PATTERNS = ('single', 'parallel', 'cross', 'grid', 'tri', 'hex', 'radial', 'corner', 'post', 'sketch')
PATTERN_LABELS = {'single': 'Żebro pojedyncze', 'parallel': 'Żebra równoległe', 'cross': 'Żebra krzyżowe', 'grid': 'Siatka prostokątna',
                  'tri': 'Siatka trójkątna', 'hex': 'Struktura sześciokątna', 'radial': 'Żebra promieniowe', 'corner': 'Żebra narożne',
                  'post': 'Wzmocnienia słupków', 'sketch': 'Według szkicu'}
HEIGHTS = ('constant', 'ramp', 'ends')
HEIGHT_LABELS = {'constant': 'Stała wysokość', 'ramp': 'Narastająca (od wysokości 2 do wysokości)', 'ends': 'Ścięte końce'}
OBSTACLES = ('auto', 'cut')
DEFAULTS = dict(pattern='parallel', thickness=1.6, height=6.0, height2=2.0, hmode='constant', taper_len=6.0, length=0.0, pitch=15.0,
                pitch2=0.0, count=0, angle=0.0, draft=1.0, fillet=0.8, margin=2.0, gap=1.0, min_len=4.0, embed=.3, cu=0.0, cv=0.0,
                obstacles='auto', min_h=1.0, sketch=None, removed=[])
MAX_RIBS = 400


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _cqs(x):
    import cadquery as cq
    return x if isinstance(x, cq.Shape) else cq.Shape.cast(x)


def _raw(x):
    return x.wrapped if hasattr(x, 'wrapped') else x


def _rot(p, ang):
    c, s = math.cos(ang), math.sin(ang)
    return np.array([c * p[0] - s * p[1], s * p[0] + c * p[1]])


def frame_of(face):
    """Układ wskazanej powierzchni: dict(point, normal) -> (o, u, v, n)."""
    n = np.asarray(face['normal'], float)
    up = (0, 0, 1.0) if abs(n[2]) < .9 else (0, 1.0, 0)
    return eh.wall_frame(face['point'], n, up)[:4]


# ---------------------------------------------------------------------------------------------- obszar i układ żeber
def region(target_shape, face, p):
    """Dozwolony obszar żeber w płaszczyźnie (u, v): rzut wskazanej powierzchni części pomniejszony o margines."""
    import cadquery as cq
    fr = frame_of(face)
    f = pick_face(target_shape, face)
    flat = eh.projected_faces([f], fr)
    m = float(p['margin'])
    reg = _shrink(flat, m, fr) if m > 0 else flat
    if reg is None or cq.Shape.cast(reg).Area() <= 1e-6:
        raise kernel.CadError('Margines od krawędzi jest większy niż powierzchnia - zmniejsz margines.')
    return reg, fr, f


def _shrink(flat, m, fr):
    """Obszar pomniejszony o margines: obrys zewnętrzny odsunięty do środka, otwory (słupki, otwory, wentylacja w
    powierzchni) powiększone o margines i wycięte."""
    import cadquery as cq
    from .enclosure import _boolean
    out = None
    for f in _cqs(flat).Faces():
        outer = cq.Face.makeFromWires(f.outerWire()).wrapped
        part = eh.offset_region(outer, -m)
        holes = [eh.offset_region(cq.Face.makeFromWires(w).wrapped, m) for w in f.innerWires()]
        for hl in holes:
            part = _boolean('cut', part, hl, 'margines otworów')
        out = part if out is None else _boolean('fuse', out, part, 'obszar żeber')
    if out is None:
        raise kernel.CadError('Powierzchnia nie ma obszaru na żebra.')
    return out


def pick_face(target_shape, face):
    """Ściana części najbliższa zapisanemu punktowi o zgodnej normalnej (odporna na przebudowę części)."""
    import cadquery as cq
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.gp import gp_Pnt
    pt = np.asarray(face['point'], float)
    n = _unit(face['normal'])
    vert = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, pt))).Vertex()
    best = None
    for f in _cqs(target_shape).Faces():
        d = BRepExtrema_DistShapeShape(f.wrapped, vert)
        d.Perform()
        if not d.IsDone():
            continue
        dist = float(d.Value())
        if dist > .05:
            continue
        try:
            nn = np.asarray(f.normalAt(cq.Vector(*pt)).toTuple(), float)
        except Exception:
            nn = n
        score = dist + (0.0 if float(nn @ n) > .5 else 10.0)
        if best is None or score < best[0]:
            best = (score, f.wrapped)
    if best is None or best[0] >= 10.0:
        raise kernel.CadError('Wskazanej powierzchni nie ma już w części obudowy - wskaż ją ponownie.')
    return best[1]


def _bounds(reg, fr):
    lo, hi, _uv = eh._bbox_uv(reg, fr)
    return np.asarray(lo, float), np.asarray(hi, float)


def _family(lo, hi, c, ang, pitch, count, length):
    """Rodzina równoległych odcinków pod kątem ang (rad) przez obszar [lo, hi], odstęp pitch, liczba (0 - wypełnienie)."""
    d = np.array([math.cos(ang), math.sin(ang)])
    nrm = np.array([-d[1], d[0]])
    corners = np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]]) - c
    span_n = (corners @ nrm).min(), (corners @ nrm).max()
    span_d = (corners @ d).min(), (corners @ d).max()
    half = (length / 2) if length > 0 else max(abs(span_d[0]), abs(span_d[1])) + 1.0
    if count > 0:
        offs = (np.arange(count) - (count - 1) / 2) * pitch
    else:
        k0, k1 = int(math.floor(span_n[0] / pitch)), int(math.ceil(span_n[1] / pitch))
        offs = np.arange(k0, k1 + 1) * pitch
    return [(c + nrm * o - d * half, c + nrm * o + d * half) for o in offs]


def layout(p, reg, fr, target_shape=None, sketch_edges=None):
    """Odcinki żeber w płaszczyźnie (u, v): lista (a, b) - przed przycięciem do obszaru."""
    lo, hi = _bounds(reg, fr)
    c = np.array([float(p['cu']), float(p['cv'])]) if (p.get('cu') or p.get('cv')) else (lo + hi) / 2
    pat = p['pattern']
    ang = math.radians(float(p['angle']))
    pitch = float(p['pitch'])
    pitch2 = float(p['pitch2']) or pitch
    count = int(p['count'])
    L = float(p['length'])
    if pat not in PATTERNS:
        raise kernel.CadError('Nieznany rodzaj żeber.')
    if pitch <= float(p['thickness']) and pat in ('parallel', 'cross', 'grid', 'tri', 'hex'):
        raise kernel.CadError('Rozstaw żeber musi być większy niż ich grubość.')
    segs = []
    if pat == 'single':
        segs = _family(lo, hi, c, ang, 1.0, 1, L)
    elif pat == 'parallel':
        segs = _family(lo, hi, c, ang, pitch, count, L)
    elif pat in ('cross', 'grid'):
        segs = _family(lo, hi, c, ang, pitch, count if pat == 'cross' else 0, L)
        segs += _family(lo, hi, c, ang + math.pi / 2, pitch2 if pat == 'grid' else pitch, count if pat == 'cross' else 0, L)
    elif pat == 'tri':
        for k in range(3):
            segs += _family(lo, hi, c, ang + k * math.pi / 3, pitch, 0, L)
    elif pat == 'hex':
        segs = _hex_edges(lo, hi, c, ang, pitch)
    elif pat == 'radial':
        n = count or 8
        R = L or float(np.linalg.norm(hi - lo))
        segs = [(c, c + _rot((R, 0.0), ang + 2 * math.pi * k / n)) for k in range(n)]
    elif pat == 'corner':
        segs = _corner_ribs(reg, fr, L or 3 * pitch / 2)
        if not segs:
            raise kernel.CadError('Powierzchnia nie ma wyraźnych narożników - wybierz inny rodzaj żeber.')
    elif pat == 'post':
        segs = _post_ribs(target_shape, fr, count or 4, L or 6.0, ang)
        if not segs:
            raise kernel.CadError('Na wskazanej powierzchni nie ma słupków montażowych (walców prostopadłych do niej).')
    elif pat == 'sketch':
        segs = sketch_edges or []
        if not segs:
            raise kernel.CadError('Wskaż szkic z liniami żeber.')
    removed = set(int(x) for x in (p.get('removed') or []))
    out = [(np.asarray(a, float), np.asarray(b, float)) for k, (a, b) in enumerate(segs) if k not in removed]
    out = [s for s in out if np.linalg.norm(s[1] - s[0]) > 1e-6]
    if len(out) > MAX_RIBS:
        raise kernel.CadError(f'Za dużo żeber ({len(out)}) - zwiększ rozstaw (największa liczba to {MAX_RIBS}).')
    return out, segs


def _hex_edges(lo, hi, c, ang, s):
    """Krawędzie plastra miodu (sześciokąty o rozwartości s) pokrywające obszar."""
    R = s / math.sqrt(3)
    out, seen = [], set()
    nx = int((hi[0] - lo[0]) / (1.5 * R)) + 4
    ny = int((hi[1] - lo[1]) / s) + 4
    for i in range(-nx, nx + 1):
        for j in range(-ny, ny + 1):
            centre = np.array([i * 1.5 * R, j * s + (s / 2 if i % 2 else 0.0)])
            pts = [centre + (R * math.cos(k * math.pi / 3), R * math.sin(k * math.pi / 3)) for k in range(6)]
            for k in range(6):
                a, b = pts[k], pts[(k + 1) % 6]
                key = tuple(sorted((tuple(np.round(a, 4)), tuple(np.round(b, 4)))))
                if key in seen:
                    continue
                seen.add(key)
                aa, bb = c + _rot(a, ang), c + _rot(b, ang)
                if min(aa[0], bb[0]) > hi[0] + s or max(aa[0], bb[0]) < lo[0] - s or min(aa[1], bb[1]) > hi[1] + s or max(aa[1], bb[1]) < lo[1] - s:
                    continue
                out.append((aa, bb))
    return out


def _corner_ribs(reg, fr, L):
    """Żebra narożne: wzdłuż dwusiecznych wypukłych narożników obszaru (od narożnika do środka na długość L)."""
    import cadquery as cq
    faces = _cqs(reg).Faces()
    if not faces:
        return []
    wire = max(faces, key=lambda f: f.Area()).outerWire()
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.TopAbs import TopAbs_REVERSED
    samples = []
    ex = BRepTools_WireExplorer(wire.wrapped)
    while ex.More():                                        # krawędzie po kolei: odcinki - wierzchołki, łuki - próbki
        e = cq.Edge(ex.Current())
        ts = [0.0] if e.geomType() == 'LINE' else list(np.linspace(0, 1, 12, endpoint=False))
        if ex.Current().Orientation() == TopAbs_REVERSED:
            ts = [1.0 - x for x in ([0.0] if e.geomType() == 'LINE' else list(np.linspace(0, 1, 12, endpoint=False)))]
        samples += [e.positionAt(x).toTuple() for x in ts]
        ex.Next()
    raw = eh._uv(samples, fr)
    pts = [raw[0]]
    for q in raw[1:]:
        if np.linalg.norm(q - pts[-1]) > 1e-6:
            pts.append(q)
    if len(pts) > 1 and np.linalg.norm(pts[0] - pts[-1]) < 1e-6:
        pts.pop()
    pts = np.array(pts)
    cross2 = lambda a, b: float(a[0] * b[1] - a[1] * b[0])
    simple = [q for k, q in enumerate(pts) if abs(cross2(_unit(q - pts[k - 1]), _unit(pts[(k + 1) % len(pts)] - q))) > 1e-3]
    pts = np.array(simple) if len(simple) >= 3 else pts
    if len(pts) < 3:
        return []
    out = []
    n = len(pts)
    area = .5 * float(np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1]))
    sgn = 1 if area > 0 else -1
    for k in range(n):
        a, b, c = pts[k - 1], pts[k], pts[(k + 1) % n]
        e1, e2 = _unit(b - a), _unit(c - b)
        turn = float(e1[0] * e2[1] - e1[1] * e2[0]) * sgn
        if turn < math.sin(math.radians(30)):          # tylko wyraźne narożniki wypukłe
            continue
        bis = _unit(_unit(a - b) + _unit(c - b))
        out.append((b, b + bis * L))
    return out


def _post_ribs(target_shape, fr, count, L, ang):
    """Wzmocnienia słupków: walce części prostopadłe do powierzchni (oś ∥ n) - żebra promieniowe od ich obwodu."""
    import cadquery as cq
    o, u, v, n = fr
    out, done = [], []
    if target_shape is None:
        return out
    for f in _cqs(target_shape).Faces():
        if f.geomType() != 'CYLINDER':
            continue
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        cyl = BRepAdaptor_Surface(f.wrapped).Cylinder()
        axis = np.array(cyl.Axis().Direction().Coord())
        if abs(abs(float(axis @ n)) - 1) > 1e-6:
            continue
        loc = np.array(cyl.Location().Coord())
        r = float(cyl.Radius())
        uv = eh._uv([loc], fr)[0]
        if any(np.linalg.norm(uv - q) < 1e-3 and abs(r - rr) < 1e-3 for q, rr in done):
            continue
        bb = f.BoundingBox()
        # słupek: zewnętrzna powierzchnia walca (wypukła) - punkt na zewnątrz osi należy do wnętrza obudowy, nie materiału
        probe = loc + u * (r + .05) + n * float(((np.array(f.Center().toTuple()) - o) @ n))
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        from OCP.TopAbs import TopAbs_OUT
        from OCP.gp import gp_Pnt
        cl = BRepClass3d_SolidClassifier(_raw(target_shape), gp_Pnt(*map(float, probe)), 1e-6)
        if cl.State() != TopAbs_OUT:
            continue
        done.append((uv, r))
        for k in range(count):
            d = _rot((1.0, 0.0), ang + 2 * math.pi * k / count)
            out.append((uv + d * (r - .2), uv + d * (r + L)))
    return out


# ---------------------------------------------------------------------------------------------- geometria
def _section_wire(t, draft, fillet, h, embed):
    """Przekrój poprzeczny żebra (x - w poprzek, y - wysokość): boki pochylone o kąt, łuki zaokrąglenia przy podstawie
    styczne do podłoża, pod podłożem wpuszczenie w ściankę."""
    tb = t / 2 + h * math.tan(math.radians(max(0.0, draft)))          # pół szerokości u podstawy
    return dict(tb=tb, tt=t / 2, r=max(0.0, float(fillet)), h=h, e=embed)


def _profile_face(sec, fr, a2, d2):
    """Ściana przekroju w płaszczyźnie prostopadłej do odcinka (punkt a2, kierunek d2 w (u, v)) - z łukami zaokrągleń."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.GC import GC_MakeArcOfCircle, GC_MakeSegment
    from OCP.gp import gp_Pnt
    o, u, v, n = fr
    side = np.array([-d2[1], d2[0]])
    s3 = u * side[0] + v * side[1]
    base = o + u * a2[0] + v * a2[1]
    P = lambda x, y: gp_Pnt(*map(float, base + s3 * x + n * y))
    tb, tt, r, h, e = sec['tb'], sec['tt'], sec['r'], sec['h'], sec['e']
    wire = BRepBuilderAPI_MakeWire()
    seq = []
    if r > 1e-6:
        x0 = tb + r
        seq = [('L', (-x0, -e), (x0, -e)), ('L', (x0, -e), (x0, 0.0)),
               ('A', (x0, 0.0), (tb + r - r * math.sin(math.pi / 4), r - r * math.cos(math.pi / 4)), (tb, r)),
               ('L', (tb, r), (tt, h)), ('L', (tt, h), (-tt, h)), ('L', (-tt, h), (-tb, r)),
               ('A', (-tb, r), (-(tb + r - r * math.sin(math.pi / 4)), r - r * math.cos(math.pi / 4)), (-x0, 0.0)),
               ('L', (-x0, 0.0), (-x0, -e))]
    else:
        seq = [('L', (-tb, -e), (tb, -e)), ('L', (tb, -e), (tt, h)), ('L', (tt, h), (-tt, h)), ('L', (-tt, h), (-tb, -e))]
    for item in seq:
        if item[0] == 'L':
            if np.hypot(item[2][0] - item[1][0], item[2][1] - item[1][1]) < 1e-9:
                continue
            seg = GC_MakeSegment(P(*item[1]), P(*item[2])).Value()
        else:
            seg = GC_MakeArcOfCircle(P(*item[1]), P(*item[2]), P(*item[3])).Value()
        wire.Add(BRepBuilderAPI_MakeEdge(seg).Edge())
    if not wire.IsDone():
        raise kernel.CadError('Nie udało się zbudować przekroju żebra.')
    mf = BRepBuilderAPI_MakeFace(wire.Wire(), True)
    if not mf.IsDone():
        raise kernel.CadError('Przekrój żebra jest niepoprawny - zmniejsz zaokrąglenie albo pochylenie.')
    return mf.Face()


def _rib_solid(seg, fr, p, h):
    """Bryła jednego żebra (przed przycięciem): przekrój wyciągnięty wzdłuż odcinka; zmienna wysokość - część wspólna
    z profilem bocznym."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    from .enclosure import _boolean
    o, u, v, n = fr
    a, b = seg
    L = float(np.linalg.norm(b - a))
    d2 = (b - a) / L
    sec = _section_wire(float(p['thickness']), float(p['draft']), float(p['fillet']), h, float(p['embed']))
    face = _profile_face(sec, fr, a, d2)
    vec = (u * d2[0] + v * d2[1]) * L
    rib = BRepPrimAPI_MakePrism(face, gp_Vec(*map(float, vec))).Shape()
    mode = p['hmode']
    if mode in ('ramp', 'ends'):
        h2 = max(.2, min(h, float(p['height2'])))
        side = np.array([-d2[1], d2[0]])
        w = sec['tb'] + sec['r'] + 1.0
        if mode == 'ramp':
            prof = [(0.0, -sec['e'] - 1), (L, -sec['e'] - 1), (L, h), (0.0, h2)]
        else:
            tl = min(float(p['taper_len']), L / 2)
            prof = [(0.0, -sec['e'] - 1), (L, -sec['e'] - 1), (L, h2), (L - tl, h), (tl, h), (0.0, h2)]
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
        from OCP.gp import gp_Pnt
        poly = BRepBuilderAPI_MakePolygon()
        for (x, y) in prof:
            q = a + d2 * x - side * w
            poly.Add(gp_Pnt(*map(float, o + u * q[0] + v * q[1] + n * y)))
        poly.Close()
        sf = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
        s3 = u * side[0] + v * side[1]
        slab = BRepPrimAPI_MakePrism(sf, gp_Vec(*map(float, s3 * 2 * w))).Shape()
        rib = _boolean('common', rib, slab, 'zmienna wysokość żebra')
    return rib


def _prism_region(reg, fr, z0, z1):
    return eh._prism(reg, fr, z1, z0)


def band(part, spec, env, lay, fr, inner, h, e):
    """Warstwa nad powierzchnią (z danych generatora): wnętrze obudowy (powiększone o wpuszczenie e) minus wnętrze
    pomniejszone o wysokość żeber; dla powierzchni zewnętrznej - zewnętrze powiększone o wysokość minus zewnętrze
    pomniejszone o wpuszczenie. Żebro przycięte do warstwy przylega dokładnie także do powierzchni zakrzywionej."""
    import cadquery as cq
    from .enclosure import _boolean, _make_box
    ax = np.asarray(env.axes, float)
    c = np.asarray(env.center, float)
    W = lambda sh: kernel.transformed(cq.Shape.cast(sh), ax.T, c).wrapped
    if 'g_in' in lay:
        from . import enclosure_shapes as shapes
        g = lay['g_in'] if inner else lay['g_out']
        mk = lambda d: W(shapes.solid(shapes.grow(g, d), lay['P']))
    else:
        lo, hi = (np.asarray(x, float) for x in (lay['inner'] if inner else lay['outer']))
        mk = lambda d: W(_make_box(lo - d, hi + d))
    def shrunk(d):
        if 'g_in' not in lay:
            lo, hi = (np.asarray(x, float) for x in (lay['inner'] if inner else lay['outer']))
            if float((hi - lo).min()) <= 2 * d + 1e-6:
                return None                             # wnętrze cieńsze niż dwie wysokości - warstwa to całe wnętrze
            return mk(-d)
        try:
            return mk(-d)
        except kernel.CadError:
            return None
    if inner:
        cut = shrunk(h)
        return mk(e) if cut is None else _boolean('cut', mk(e), cut, 'warstwa żeber')
    cut = shrunk(e)
    return mk(h) if cut is None else _boolean('cut', mk(h), cut, 'warstwa żeber')


def _obstacles(fr, p, h, components, others, target_shape):
    """Bryły przeszkód (świat): komponenty (ramka + odstęp; wysoko nad powierzchnią - tylko część od ich spodu w górę,
    żeby żebro pod nimi zostało obniżone), inne części obudowy z odstępem, otwory słupków (walce wklęsłe ∥ n)."""
    import cadquery as cq
    from .enclosure import _make_box
    o, u, v, n = fr
    gap = float(p['gap'])
    min_h = float(p['min_h'])
    M = np.column_stack([u, v, n])
    out = []
    for b in components:
        pts = np.asarray([_cqs(b).BoundingBox().__getattribute__(k) for k in ('xmin', 'ymin', 'zmin', 'xmax', 'ymax', 'zmax')]).reshape(2, 3)
        corners = np.array([[pts[i & 1][0], pts[(i >> 1) & 1][1], pts[(i >> 2) & 1][2]] for i in range(8)]) - o
        loc = corners @ M
        lo, hi = loc.min(axis=0) - gap, loc.max(axis=0) + gap
        if hi[2] <= 0 or lo[2] >= h:
            continue
        if p['obstacles'] == 'auto' and lo[2] >= min_h:
            z0 = lo[2]                                     # komponent wysoko - żebro obniżone pod nim
        else:
            z0 = -10.0                                     # komponent nisko - żebro skrócone / podzielone
        out.append(kernel.transformed(cq.Shape.cast(_make_box((lo[0], lo[1], z0), (hi[0], hi[1], h + 10))), M, o).wrapped)
    for sh in others:
        out.append(sh)
        moved = _cqs(sh).translate(cq.Vector(*(-n * gap))).wrapped
        out.append(moved)
    for f in _cqs(target_shape).Faces():
        if f.geomType() != 'CYLINDER':
            continue
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        cyl = BRepAdaptor_Surface(f.wrapped).Cylinder()
        axis = np.array(cyl.Axis().Direction().Coord())
        if abs(abs(float(axis @ n)) - 1) > 1e-6:
            continue
        loc = np.array(cyl.Location().Coord())
        r = float(cyl.Radius())
        probe = loc + u * (r - .05) + n * float(((np.array(f.Center().toTuple()) - o) @ n))
        from OCP.BRepClass3d import BRepClass3d_SolidClassifier
        from OCP.TopAbs import TopAbs_OUT
        from OCP.gp import gp_Pnt
        if BRepClass3d_SolidClassifier(_raw(target_shape), gp_Pnt(*map(float, probe)), 1e-6).State() != TopAbs_OUT:
            continue                                       # walec wypukły (słupek) - żebro może się z nim połączyć
        uv = eh._uv([loc], fr)[0]
        if float(np.linalg.norm(uv)) < r:               # powierzchnia leży wewnątrz walca - to ścianka wnętrza, nie otwór
            continue
        hole = eh._circle_face(uv[0], uv[1], r + gap * .5, fr)
        out.append(eh._prism(hole, fr, h + 10, -10.0))   # otwór (np. pod wkręt) - wolny
    return out


def build(part, spec, env, lay, faces, p, components=(), others=(), sketch_edges=None):
    """Żebra na wskazanych powierzchniach części: (bryła cq po połączeniu, info). components / others - bryły świata."""
    import cadquery as cq
    from .enclosure import _boolean, _single, _unified, _volume, check_solid, _solids
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.TopTools import TopTools_ListOfShape
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    p = dict(DEFAULTS, **p)
    t, h = float(p['thickness']), float(p['height'])
    if t <= 0 or h <= 0:
        raise kernel.CadError('Grubość i wysokość żebra muszą być większe od zera.')
    if float(p['draft']) < 0 or float(p['draft']) >= 30:
        raise kernel.CadError('Kąt pochylenia boków musi być od 0 do 30°.')
    if float(p['fillet']) < 0 or float(p['fillet']) > h:
        raise kernel.CadError('Promień zaokrąglenia podstawy musi być od 0 do wysokości żebra.')
    target = part.wrapped if hasattr(part, 'wrapped') else part
    ribs, info = [], dict(count=0, dropped=0, lowered=0, faces=len(faces))
    for face in faces:
        reg, fr, f = region(target, face, p)
        o, u, v, n = fr
        probe = np.asarray(face['point'], float) + n * .05
        inner = _inside_cavity(env, spec, lay, probe)
        segs, _all = layout(p, reg, fr, target, sketch_edges)
        allowed = _boolean('common', _prism_region(reg, fr, -float(p['embed']) - 2.0, h + 2.0),
                           band(target, spec, env, lay, fr, inner, h, float(p['embed'])), 'obszar żeber')
        obstacles = _obstacles(fr, p, h, components, others, target)
        raw = [_rib_solid(seg, fr, p, h) for seg in segs]
        if not raw:
            continue
        net = raw[0] if len(raw) == 1 else _multi('fuse', raw[0], raw[1:], 'sieć żeber')     # jedna operacja dla wszystkich
        net = _boolean('common', net, allowed, 'przycięcie żeber')
        if obstacles:
            net = _multi('cut', net, obstacles, 'przeszkody żeber')
        for piece in _solids(net):
            if _volume(piece)[0] <= 1e-6:
                continue
            pts = np.array([q.toTuple() for q in cq.Shape.cast(piece).Vertices()])
            uvp = (pts - o) @ np.column_stack([u, v]) if len(pts) else np.zeros((1, 2))
            extent = float(np.hypot(*np.ptp(uvp, axis=0)))
            if extent < float(p['min_len']):
                info['dropped'] += 1
                continue
            d = BRepExtrema_DistShapeShape(piece, target)
            d.Perform()
            if not d.IsDone() or d.Value() > 1e-6:        # fragment niepołączony ze ścianką
                info['dropped'] += 1
                continue
            ribs.append(piece)
    if not ribs:
        raise kernel.CadError('Po dopasowaniu do powierzchni i przeszkód nie zostało żadne żebro - zmniejsz margines, '
                              'odstęp od komponentów albo zmień rozstaw.')
    args, tl = TopTools_ListOfShape(), TopTools_ListOfShape()
    args.Append(target)
    for r in ribs:
        tl.Append(r)
    op = BRepAlgoAPI_Fuse()
    op.SetArguments(args)
    op.SetTools(tl)
    op.SetRunParallel(True)
    op.Build()
    if not op.IsDone():
        raise kernel.CadError('Połączenie żeber z częścią obudowy nie powiodło się.')
    before = _volume(target)[0]
    shape = check_solid(_single(_unified(op.Shape()), 'Obudowa z żebrami'))
    added = _volume(shape.wrapped)[0] - before
    expected = sum(_volume(r)[0] for r in ribs)
    if added < .5 * expected - 1e-6:                       # żebra wpuszczone w ściankę o `embed` - reszta musi przybyć
        raise kernel.CadError('Żebra nie połączyły się objętościowo ze ścianką.')
    info.update(count=len(ribs), volume=added)
    return shape, info, ribs


def _multi(kind, arg, tools, what):
    """Jedna operacja Boolean z listą narzędzi (równolegle)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
    from OCP.TopTools import TopTools_ListOfShape
    op = {'cut': BRepAlgoAPI_Cut, 'fuse': BRepAlgoAPI_Fuse}[kind]()
    args, tl = TopTools_ListOfShape(), TopTools_ListOfShape()
    args.Append(arg)
    for t in tools:
        tl.Append(t)
    op.SetArguments(args)
    op.SetTools(tl)
    op.SetRunParallel(True)
    op.Build()
    if not op.IsDone():
        raise kernel.CadError(f'Operacja Boolean nie powiodła się ({what}).')
    return op.Shape()


def _inside_cavity(env, spec, lay, point):
    from .enclosure_library import _cavity
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt
    cav = _cavity(env, spec, lay)
    return BRepClass3d_SolidClassifier(cav, gp_Pnt(*map(float, point)), 1e-6).State() == TopAbs_IN


def preview_mesh(segs, fr, h):
    """Uproszczony podgląd: każde żebro jako prostokąt (linia podstawy i góry) - bez geometrii OCC."""
    o, u, v, n = fr
    edges, pts = {}, []
    for k, (a, b) in enumerate(segs):
        A, B = o + u * a[0] + v * a[1], o + u * b[0] + v * b[1]
        loop = np.array([A, B, B + n * h, A + n * h, A], np.float32)
        edges[k] = loop
        pts.append(loop)
    if not pts:
        return None
    vv = np.concatenate(pts)
    return kernel.DisplayMesh(vv, np.empty((0, 3), np.uint32), edges, tuple(map(float, vv.mean(axis=0))), float(np.linalg.norm(vv.max(axis=0) - vv.min(axis=0))))
