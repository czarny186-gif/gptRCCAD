"""Gwinty (zakładka Edycja → Gwint).

Gwint jest „kosmetyczny”, jak w programach CAD do produkcji: bryła dostaje tylko właściwą średnicę (otwór pod gwint
= średnica wiertła, wałek = średnica nominalna), a sam gwint jest opisem przypisanym do bryły (norma, rozmiar, skok,
kierunek, zakres) i rysuje się na ekranie jako lekka linia śrubowa. Nie powstaje prawdziwa geometria zwojów - ta potrafi
spowolnić program dziesiątki razy (tysiące ścian śrubowych przy każdym przeliczeniu, cieniowaniu i eksporcie).
"""
from __future__ import annotations

import math

import numpy as np

# ---------------------------------------------------------------------------
# normy: (nazwa, średnica nominalna mm, skok mm)
# ---------------------------------------------------------------------------
INCH = 25.4


def _unified(rows):
    return [(name, round(d * INCH, 3), round(INCH / tpi, 4)) for name, d, tpi in rows]


STANDARDS = {
    'M': dict(title='Metryczny zwykły (M)', angle=60, sizes=[
        ('M1.6', 1.6, .35), ('M2', 2, .4), ('M2.5', 2.5, .45), ('M3', 3, .5), ('M4', 4, .7), ('M5', 5, .8), ('M6', 6, 1.0),
        ('M8', 8, 1.25), ('M10', 10, 1.5), ('M12', 12, 1.75), ('M14', 14, 2.0), ('M16', 16, 2.0), ('M18', 18, 2.5),
        ('M20', 20, 2.5), ('M22', 22, 2.5), ('M24', 24, 3.0), ('M27', 27, 3.0), ('M30', 30, 3.5), ('M33', 33, 3.5),
        ('M36', 36, 4.0), ('M42', 42, 4.5), ('M48', 48, 5.0), ('M56', 56, 5.5), ('M64', 64, 6.0)]),
    'MF': dict(title='Metryczny drobnozwojny (M×P)', angle=60, sizes=[
        ('M6×0.75', 6, .75), ('M8×1', 8, 1.0), ('M10×1', 10, 1.0), ('M10×1.25', 10, 1.25), ('M12×1.25', 12, 1.25),
        ('M12×1.5', 12, 1.5), ('M14×1.5', 14, 1.5), ('M16×1.5', 16, 1.5), ('M18×1.5', 18, 1.5), ('M20×1.5', 20, 1.5),
        ('M22×1.5', 22, 1.5), ('M24×2', 24, 2.0), ('M27×2', 27, 2.0), ('M30×2', 30, 2.0), ('M36×3', 36, 3.0),
        ('M42×3', 42, 3.0), ('M48×3', 48, 3.0)]),
    'UNC': dict(title='Calowy zwykły (UNC)', angle=60, sizes=_unified([
        ('#4-40', .112, 40), ('#6-32', .138, 32), ('#8-32', .164, 32), ('#10-24', .190, 24), ('1/4"-20', .25, 20),
        ('5/16"-18', .3125, 18), ('3/8"-16', .375, 16), ('7/16"-14', .4375, 14), ('1/2"-13', .5, 13), ('9/16"-12', .5625, 12),
        ('5/8"-11', .625, 11), ('3/4"-10', .75, 10), ('7/8"-9', .875, 9), ('1"-8', 1.0, 8), ('1 1/4"-7', 1.25, 7),
        ('1 1/2"-6', 1.5, 6)])),
    'UNF': dict(title='Calowy drobny (UNF)', angle=60, sizes=_unified([
        ('#4-48', .112, 48), ('#6-40', .138, 40), ('#8-36', .164, 36), ('#10-32', .190, 32), ('1/4"-28', .25, 28),
        ('5/16"-24', .3125, 24), ('3/8"-24', .375, 24), ('7/16"-20', .4375, 20), ('1/2"-20', .5, 20), ('9/16"-18', .5625, 18),
        ('5/8"-18', .625, 18), ('3/4"-16', .75, 16), ('7/8"-14', .875, 14), ('1"-12', 1.0, 12)])),
    'G': dict(title='Rurowy calowy (G, BSPP)', angle=55, sizes=[
        ('G1/8', 9.728, INCH / 28), ('G1/4', 13.157, INCH / 19), ('G3/8', 16.662, INCH / 19), ('G1/2', 20.955, INCH / 14),
        ('G5/8', 22.911, INCH / 14), ('G3/4', 26.441, INCH / 14), ('G1', 33.249, INCH / 11), ('G1 1/4', 41.910, INCH / 11),
        ('G1 1/2', 47.803, INCH / 11), ('G2', 59.614, INCH / 11)]),
    'Tr': dict(title='Trapezowy (Tr)', angle=30, sizes=[
        ('Tr8×1.5', 8, 1.5), ('Tr10×2', 10, 2.0), ('Tr12×3', 12, 3.0), ('Tr14×3', 14, 3.0), ('Tr16×4', 16, 4.0),
        ('Tr20×4', 20, 4.0), ('Tr24×5', 24, 5.0), ('Tr28×5', 28, 5.0), ('Tr32×6', 32, 6.0), ('Tr36×6', 36, 6.0),
        ('Tr40×7', 40, 7.0), ('Tr50×8', 50, 8.0)]),
}


def size(standard, name):
    return next(s for s in STANDARDS[standard]['sizes'] if s[0] == name)


def drill(standard, d, pitch):
    """Średnica otworu pod gwint wewnętrzny (wiertło): dla gwintów 60° d - P, dla rurowego G - średnica rdzenia, dla Tr - d - P."""
    if standard == 'G':
        return round(d - 1.28 * pitch, 3)
    return round(d - pitch, 3)


def core(standard, d, pitch, internal):
    """Średnica rdzenia (dno zwojów) - do rysowania drugiej linii gwintu."""
    if standard == 'G':
        return d - 1.28 * pitch
    if standard == 'Tr':
        return d - pitch - (0 if internal else .5)
    return d - (1.0825 if internal else 1.2269) * pitch


def bore(standard, d, pitch, internal):
    """Średnica, jaką powinna mieć powierzchnia walcowa: otwór = wiertło, wałek = średnica nominalna."""
    return drill(standard, d, pitch) if internal else float(d)


def fit(standard, diameter, internal):
    """Rozmiar gwintu najlepiej pasujący do otworu / wałka o danej średnicy: (nazwa, pasuje?) - pasuje, gdy różnica
    jest w tolerancji wykonania (do 0.15 skoku, min. 0.05 mm)."""
    best, err = None, None
    for name, d, p in STANDARDS[standard]['sizes']:
        e = abs(bore(standard, d, p, internal) - diameter)
        if err is None or e < err:
            best, err, tol = name, e, max(.15 * p, .05)
    return best, err is not None and err <= tol


def label(spec):
    hand = '' if spec.get('hand', 'right') == 'right' else ' LH'
    return f"{spec['size']}{hand}"


# ---------------------------------------------------------------------------
# walec: otwór albo wałek
# ---------------------------------------------------------------------------
def cylinder_info(shape, index):
    """Opis walcowej ściany bryły: oś (punkt, kierunek), promień, otwór czy wałek, zakres wzdłuż osi [t0, t1] i czy
    to pełny obwód (gwint tylko na pełnym walcu). None, gdy ściana nie jest walcem."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.BRepTools import BRepTools
    faces = shape.Faces()
    if index < 0 or index >= len(faces):
        return None
    face = faces[index]
    surf = BRepAdaptor_Surface(face.wrapped)
    if surf.GetType() != GeomAbs_Cylinder:
        return None
    cyl = surf.Cylinder()
    ax = cyl.Axis()
    origin = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()])
    axis = np.array([ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()])
    radius = float(cyl.Radius())
    umin, umax, vmin, vmax = BRepTools.UVBounds_s(face.wrapped)
    full = (umax - umin) > 2 * math.pi - 1e-3
    # zakres wzdłuż osi z wierzchołków / punktów ściany
    pts = np.array([v.toTuple() for v in face.Vertices()] or [face.Center().toTuple()], float)
    params = [vmin, vmax]
    t = (pts - origin) @ axis
    t0, t1 = float(min(min(params), t.min())), float(max(max(params), t.max()))
    # otwór: normalna ściany (na zewnątrz materiału) wskazuje w stronę osi
    try:                                        # punkt NA ścianie (środek masy walca leży na osi)
        point = face.positionAt(.5, .5)
        n = np.array(face.normalAt(point).toTuple())
        on = np.array(point.toTuple())
    except Exception:
        n, on = None, None
    internal = True
    if n is not None:
        foot = origin + axis * float((on - origin) @ axis)
        radial = on - foot
        if np.linalg.norm(radial) > 1e-9:
            internal = float(n @ radial) < 0
    return dict(index=index, origin=origin.tolist(), axis=axis.tolist(), radius=radius, internal=bool(internal),
                t0=t0, t1=t1, full=bool(full))


def cylinders(shape):
    """Wszystkie walcowe ściany bryły (opisy jak cylinder_info) - liczone raz dla kształtu."""
    out = []
    for i, face in enumerate(shape.Faces()):
        if face.geomType() == 'CYLINDER':
            info = cylinder_info(shape, i)
            if info is not None:
                out.append(info)
    return out


def cylinder_at(infos, point, tol):
    """Walec, na którym leży punkt: odległość od osi = promień i punkt w zakresie wzdłuż osi (czysty numpy)."""
    p = np.asarray(point, float)
    best = None
    for info in infos:
        o, a = np.asarray(info['origin']), np.asarray(info['axis'])
        t = float((p - o) @ a)
        if t < info['t0'] - tol or t > info['t1'] + tol:
            continue
        err = abs(float(np.linalg.norm(p - o - a * t)) - info['radius'])
        if err <= tol and (best is None or err < best[0]):
            best = (err, info)
    return None if best is None else best[1]


def face_index_at(shape, point, tol=None):
    """Numer walcowej ściany bryły, na której leży kliknięty punkt (None, gdy to nie walec)."""
    import cadquery as cq
    vertex = cq.Vertex.makeVertex(*[float(c) for c in point])
    bb = shape.BoundingBox()
    tol = tol if tol is not None else max(.02, 1e-3 * float(np.linalg.norm([bb.xlen, bb.ylen, bb.zlen])))
    best = None
    for i, face in enumerate(shape.Faces()):
        if face.geomType() != 'CYLINDER':
            continue
        d = face.distance(vertex)
        if d <= tol and (best is None or d < best[0]):
            best = (d, i)
    return None if best is None else best[1]


def same_axis(a, b, tol=1e-3):
    """Czy dwa opisy (gwint / walec) leżą na tej samej osi."""
    oa, aa = np.asarray(a['origin'], float), np.asarray(a['axis'], float)
    ob, ab = np.asarray(b['origin'], float), np.asarray(b['axis'], float)
    if abs(abs(float(aa @ ab)) - 1) > 1e-6:
        return False
    d = ob - oa
    return float(np.linalg.norm(d - aa * float(d @ aa))) <= tol


def thread_index(threads, ref, tol=1e-3):
    """Numer gwintu bryły odpowiadającego opisowi ref (oś, zakres) - do zamiany na prawdziwy."""
    for i, t in enumerate(threads):
        if same_axis(t, ref, tol) and abs(float(t['start']) - float(ref['start'])) < tol and abs(float(t['end']) - float(ref['end'])) < tol \
                and abs(float(t['d']) - float(ref['d'])) < tol:
            return i
    return None


def threads_on(threads, info):
    """Gwinty kosmetyczne leżące na wskazanym walcu (ta sama oś, zakres zachodzi na ścianę)."""
    out = []
    for t in threads:
        if not same_axis(t, info, max(1e-3, 1e-3 * info['radius'])):
            continue
        a = np.asarray(info['axis'], float)
        shift = float((np.asarray(info['origin'], float) - np.asarray(t['origin'], float)) @ np.asarray(t['axis'], float))
        sign = 1.0 if float(a @ np.asarray(t['axis'], float)) > 0 else -1.0
        lo, hi = sorted((shift + sign * info['t0'], shift + sign * info['t1']))
        if min(hi, float(t['end'])) - max(lo, float(t['start'])) > -1e-6 and abs(t['d'] / 2 - info['radius']) < t['d'] / 2:
            out.append(t)
    return out


def find_cylinder(shape, origin, axis, radius, tol=1e-3):
    """Numer walcowej ściany o danej osi i promieniu (odtwarzanie kroku historii)."""
    origin, axis = np.asarray(origin, float), np.asarray(axis, float)
    best = None
    for i, face in enumerate(shape.Faces()):
        if face.geomType() != 'CYLINDER':
            continue
        info = cylinder_info(shape, i)
        if info is None or abs(info['radius'] - radius) > max(tol, 1e-4 * radius):
            continue
        a = np.asarray(info['axis'])
        if abs(abs(float(a @ axis)) - 1) > 1e-6:
            continue
        d = np.asarray(info['origin']) - origin
        off = np.linalg.norm(d - axis * float(d @ axis))
        if off > max(tol, 1e-4 * radius):
            continue
        if best is None or info['t1'] - info['t0'] > best['t1'] - best['t0']:
            best = info
    return best


def find_cylinder_near(shape, origin, axis, radius, internal=None):
    """Walec pod gwint po zmianie otworu (inna średnica albo przesunięty otwór): pełny walec o równoległej osi, tego samego
    rodzaju (otwór / wałek), najbliżej zapisanej osi; przy kilku równie bliskich - o najbliższym promieniu. None - brak."""
    origin, axis = np.asarray(origin, float), np.asarray(axis, float)
    best = None
    for i, face in enumerate(shape.Faces()):
        if face.geomType() != 'CYLINDER':
            continue
        info = cylinder_info(shape, i)
        if info is None or not info.get('full', True):
            continue
        if internal is not None and bool(info['internal']) != bool(internal):
            continue
        a = np.asarray(info['axis'])
        if abs(abs(float(a @ axis)) - 1) > 1e-6:
            continue
        d = np.asarray(info['origin']) - origin
        off = float(np.linalg.norm(d - axis * float(d @ axis)))
        key = (round(off, 3), abs(info['radius'] - radius))
        if best is None or key < best[0]:
            best = (key, info)
    return None if best is None else best[1]


def set_diameter(shape, info, diameter):
    """Otwór / wałek na nową średnicę w zakresie ściany walcowej (szybka operacja logiczna z walcem lub tuleją)."""
    import cadquery as cq
    from . import kernel
    r, R = info['radius'], diameter / 2
    if abs(r - R) < 1e-4:
        return shape
    origin, axis = np.asarray(info['origin'], float), np.asarray(info['axis'], float)
    t0, t1 = info['t0'], info['t1']
    base = cq.Vector(*(origin + axis * t0))
    direction = cq.Vector(*axis)
    height = t1 - t0
    pad = max(.05, .02 * r)

    def cylinder(radius):
        return cq.Solid.makeCylinder(radius, height, base, direction)

    def tube(outer, inner):
        return cq.Solid.makeCylinder(outer, height, base, direction).cut(cq.Solid.makeCylinder(inner, height, base, direction))

    if info['internal']:
        if R > r:
            return kernel.boolean('subtract', shape, [cylinder(R)])          # otwór za mały: rozwiercenie
        return kernel.boolean('union', shape, [tube(r + pad, R)])            # otwór za duży: tuleja do średnicy wiertła
    if R > r:
        return kernel.boolean('union', shape, [tube(R, r - pad)])            # wałek za cienki: pogrubienie
    return kernel.boolean('subtract', shape, [tube(r + pad, R)])             # wałek za gruby: ztoczenie


# ---------------------------------------------------------------------------
# rysowanie: linia śrubowa (lekka, bez geometrii)
# ---------------------------------------------------------------------------
MAX_TURNS = 90          # więcej zwojów rysuje się rzadziej (ekran i tak ich nie rozróżni) - lekko także dla długich gwintów
SEGMENTS = 20           # odcinków na zwój


def thread_lines(thread):
    """Odcinki (N×2×3) przedstawiające gwint: linia śrubowa z prawdziwym kierunkiem zwojów, okręgi na końcach i druga
    (rdzeń) linia jako krótkie kreski - wygląd jak gwint, koszt jak kilka linii szkicu."""
    origin, axis = np.asarray(thread['origin'], float), np.asarray(thread['axis'], float)
    axis = axis / max(np.linalg.norm(axis), 1e-12)
    t0, t1 = float(thread['start']), float(thread['end'])
    if t1 - t0 < 1e-6:
        return np.zeros((0, 2, 3), np.float32)
    pitch = float(thread['pitch'])
    turns = (t1 - t0) / pitch
    shown = pitch if turns <= MAX_TURNS else (t1 - t0) / MAX_TURNS
    helper = np.array([1.0, 0, 0]) if abs(axis[0]) < .9 else np.array([0, 1.0, 0])
    e1 = np.cross(axis, helper)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    sign = 1.0 if thread.get('hand', 'right') == 'right' else -1.0
    internal = bool(thread['internal'])
    # promień rysowania: odrobinę od powierzchni w stronę patrzącego (bez migotania na ścianie)
    radius = float(thread['radius']) * (.996 if internal else 1.004)
    n = max(8, int(math.ceil((t1 - t0) / shown * SEGMENTS)))
    t = np.linspace(t0, t1, n + 1)
    phase = sign * 2 * math.pi * (t - t0) / shown
    pts = origin + np.outer(t, axis) + radius * (np.outer(np.cos(phase), e1) + np.outer(np.sin(phase), e2))
    segs = [np.stack([pts[:-1], pts[1:]], axis=1)]
    ring = np.linspace(0, 2 * math.pi, 49)
    for tt in (t0, t1):
        r = origin + axis * tt + radius * (np.outer(np.cos(ring), e1) + np.outer(np.sin(ring), e2))
        segs.append(np.stack([r[:-1], r[1:]], axis=1))
    # druga średnica (dno zwojów dla wałka / średnica nominalna dla otworu): przerywana linia wzdłuż osi w 4 miejscach
    other = float(thread['other']) / 2
    for k in range(4):
        a = k * math.pi / 2
        d = math.cos(a) * e1 + math.sin(a) * e2
        dash = np.linspace(t0, t1, max(2, int((t1 - t0) / max(pitch * 2, .5)) + 1))
        p = origin + np.outer(dash, axis) + other * d
        segs.append(np.stack([p[:-1:2], p[1::2]], axis=1) if len(p) > 2 else np.stack([p[:-1], p[1:]], axis=1))
    return np.concatenate(segs).astype(np.float32)


def make_thread(info, standard, name, hand, start, end):
    """Opis gwintu zapisywany przy bryle (wszystko w liczbach - zapis w pliku, przenoszenie z bryłą)."""
    _, d, pitch = size(standard, name)
    internal = bool(info['internal'])
    radius = bore(standard, d, pitch, internal) / 2
    other = d if internal else core(standard, d, pitch, internal)
    return dict(standard=standard, size=name, d=float(d), pitch=float(pitch), hand=hand, internal=internal,
                origin=[float(c) for c in info['origin']], axis=[float(c) for c in info['axis']],
                radius=float(radius), other=float(other), start=float(start), end=float(end))


def transformed(thread, matrix):
    """Gwint przeniesiony razem z bryłą (macierz 4×4: przesunięcie / obrót / lustro)."""
    m = np.asarray(matrix, float)
    out = dict(thread)
    out['origin'] = [float(c) for c in m[:3, :3] @ np.asarray(thread['origin']) + m[:3, 3]]
    axis = m[:3, :3] @ np.asarray(thread['axis'])
    out['axis'] = [float(c) for c in axis / np.linalg.norm(axis)]
    if np.linalg.det(m[:3, :3]) < 0:
        out['hand'] = 'left' if thread.get('hand', 'right') == 'right' else 'right'
    return out


# ---------------------------------------------------------------------------
# prawdziwy gwint - tylko przy eksporcie (STL do druku 3D, STEP), w procesie liczącym w tle
# ---------------------------------------------------------------------------
OVERLAP = .02          # zwoje wchodzą odrobinę w rdzeń / ściankę - pewne połączenie brył


def _ridge(pitch, length, r_root, r_crest, w_root, w_crest, left):
    """Zwoje jako bryła: cztery linie śrubowe (narożniki profilu) połączone powierzchniami prostokreślnymi i denkami.
    Tak zbudowane zwoje łączą się z bryłą pewnie (w przeciwieństwie do przeciągania profilu po linii śrubowej)."""
    import cadquery as cq
    from OCP.BRepFill import BRepFill
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopoDS import TopoDS
    profile = [(r_root, -w_root / 2), (r_crest, -w_crest / 2), (r_crest, w_crest / 2), (r_root, w_root / 2)]
    edges = []
    for r, z in profile:
        helix = cq.Wire.makeHelix(pitch, length, r, lefthand=left).translate((0, 0, z))
        edges.append(helix.Edges()[0])
    sew = BRepBuilderAPI_Sewing(1e-4)
    for i in range(4):
        sew.Add(BRepFill.Face_s(edges[i].wrapped, edges[(i + 1) % 4].wrapped))
    for end in (0, 1):
        sew.Add(cq.Face.makeFromWires(cq.Wire.makePolygon([e.positionAt(end) for e in edges], close=True)).wrapped)
    sew.Perform()
    solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(sew.SewedShape())).Solid()
    fix = ShapeFix_Solid(solid)
    fix.Perform()
    out = cq.Solid(fix.Solid())
    return cq.Solid(out.wrapped.Reversed()) if out.Volume() < 0 else out


def _profile(thread):
    """Wymiary zwoju: promień dna i wierzchołka, szerokości u dna i na wierzchołku (wg kąta gwintu)."""
    standard, d, p, internal = thread['standard'], thread['d'], thread['pitch'], thread['internal']
    angle = math.radians(STANDARDS.get(standard, {}).get('angle', 60) / 2)
    if internal:                        # zwój nakrętki: od średnicy nominalnej do średnicy otworu
        r_root, r_crest = d / 2 + OVERLAP, core(standard, d, p, True) / 2
        w_crest = p / 4
    else:                               # zwój śruby: od rdzenia do średnicy nominalnej
        r_root, r_crest = core(standard, d, p, False) / 2 - OVERLAP, d / 2
        w_crest = p / 8
    depth = abs(r_root - r_crest)
    w_root = min(.9 * p, w_crest + 2 * depth * math.tan(angle))
    return r_root, r_crest, w_root, w_crest


def real_shape(shape, threads):
    """Bryła z prawdziwymi zwojami w miejscu gwintów kosmetycznych (rdzeń do średnicy dna, potem zwoje)."""
    import cadquery as cq
    from . import kernel
    for thread in threads:
        length = float(thread['end']) - float(thread['start'])
        if length <= thread['pitch']:
            continue
        r_root, r_crest, w_root, w_crest = _profile(thread)
        axis = np.asarray(thread['axis'], float)
        axis = axis / np.linalg.norm(axis)
        base = np.asarray(thread['origin'], float) + axis * float(thread['start'])
        # rdzeń: otwór poszerzony do średnicy nominalnej / wałek ztoczony do rdzenia - na długości gwintu
        if thread['internal']:
            hollow = cq.Solid.makeCylinder(thread['d'] / 2, length, cq.Vector(*base), cq.Vector(*axis))
        else:
            outer = max(thread['d'] / 2, thread['radius']) + .5
            hollow = cq.Solid.makeCylinder(outer, length, cq.Vector(*base), cq.Vector(*axis)).cut(
                cq.Solid.makeCylinder(r_root + OVERLAP, length, cq.Vector(*base), cq.Vector(*axis)))
        shape = kernel.boolean('subtract', shape, [hollow])
        # zwoje w układzie osi Z, potem na oś gwintu; profil cały w zakresie gwintu
        ridge = _ridge(thread['pitch'], length - w_root, r_root, r_crest, w_root, w_crest, thread.get('hand', 'right') == 'left')
        ridge = ridge.translate((0, 0, w_root / 2))
        rotation = kernel.rotation_between([0, 0, 1], axis)
        ridge = kernel.transformed(ridge, rotation, base)
        shape = kernel.boolean('union', shape, [ridge])
    return shape


def export_job(items, path):
    """Eksport w procesie liczącym: bryły z gwintami dostają prawdziwe zwoje, potem zapis pliku. items: (kształt, gwinty)."""
    from . import kernel
    shapes, failed = [], 0
    for shape, threads in items:
        if threads:
            try:
                shape = real_shape(shape, threads)
            except Exception:
                failed += 1             # gwint, którego nie da się zbudować, zostaje kosmetyczny (sam otwór)
        shapes.append(shape)
    kernel.export_shapes(shapes, path)
    return failed


def cut_threads(base, tool_threads):
    """Wycięcie bryłą z gwintem zewnętrznym zostawia w wycinanej bryle otwór z gwintem wewnętrznym (ten sam rozmiar,
    skok i kierunek) - na tej długości, na której gwint przechodzi przez bryłę. base: kształt przed wycięciem."""
    import cadquery as cq
    out = []
    for t in tool_threads:
        if t.get('internal'):
            continue
        axis = np.asarray(t['axis'], float)
        origin = np.asarray(t['origin'], float)
        start, end = float(t['start']), float(t['end'])
        probe = cq.Solid.makeCylinder(t['d'] / 2, end - start, cq.Vector(*(origin + axis * start)), cq.Vector(*axis))
        try:
            common = base.intersect(probe)
            if common.Volume() < 1e-6:
                continue
            ts = [float((np.array(v.toTuple()) - origin) @ axis) for v in common.Vertices()]
            bb = common.BoundingBox()
            corners = np.array([[x, y, z] for x in (bb.xmin, bb.xmax) for y in (bb.ymin, bb.ymax) for z in (bb.zmin, bb.zmax)])
            ts += [] if ts else list((corners - origin) @ axis)
        except Exception:
            continue
        lo, hi = max(start, min(ts)), min(end, max(ts))
        if hi - lo <= t['pitch'] * .5:
            continue
        out.append(dict(t, internal=True, radius=float(t['d']) / 2, other=float(core(t['standard'], t['d'], t['pitch'], True)),
                        start=lo, end=hi))
    return out
