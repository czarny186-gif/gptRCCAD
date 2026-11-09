"""Exact CAD geometry. No GUI or triangle-based Boolean operations."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import cadquery as cq
import numpy as np
from OCP.BRep import BRep_Tool
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.GeomAbs import GeomAbs_C0
from OCP.StlAPI import StlAPI_Reader
from OCP.TopoDS import TopoDS_Shape
from .perfcache import LRU
from .spatial import BoundsTree


class CadError(ValueError):
    """A recoverable modelling error: the document must remain unchanged."""


def positive(value, label="Wymiar"):
    value = float(value)
    if not isfinite(value) or not 1e-5 <= value <= 1e6:
        raise CadError(f"{label}: podaj dodatnią liczbę od 0,00001 do 1 000 000 mm.")
    return value


# Wielordzeniowe liczenie wewnątrz OpenCascade: operacje logiczne (połącz, wytnij, część wspólna, cięcie, gięcie blach),
# sprawdzanie poprawności brył i siatkowanie do wyświetlania dzielą pracę na wszystkie rdzenie procesora.
try:
    from OCP.BOPAlgo import BOPAlgo_Options
    BOPAlgo_Options.SetParallelMode_s(True)
except Exception:       # starsza biblioteka: zostaje liczenie na jednym rdzeniu
    pass


def is_valid(shape):
    """Sprawdzenie poprawności bryły na wielu rdzeniach (to samo co Shape.isValid, równolegle)."""
    from OCP.BRepCheck import BRepCheck_Analyzer
    try:
        return BRepCheck_Analyzer(shape.wrapped, True, True).IsValid()
    except TypeError:
        return shape.isValid()


def _brep_bytes(shape):
    """Kształt jako tekstowy BREP bez siatki (przesyłanie do procesów liczących). Zapis binarny cadquery (BinTools) nie
    odczytuje niektórych krawędzi blach („UnExpected BRep_PointRepresentation”) - BREP tekstowy czyta wszystko."""
    import io
    from OCP.BRepTools import BRepTools
    from OCP.TopTools import TopTools_FormatVersion
    buffer = io.BytesIO()
    BRepTools.Write_s(shape.wrapped, buffer, False, False, TopTools_FormatVersion.TopTools_FormatVersion_VERSION_1)
    return buffer.getvalue()


def _from_brep(data):
    import io
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape
    shape = TopoDS_Shape()
    BRepTools.Read_s(shape, io.BytesIO(data), BRep_Builder())
    return cq.Shape.cast(shape)


def _register_pickling():
    import copyreg
    for cls in (cq.Shape, cq.Solid, cq.Compound, cq.Face, cq.Wire, cq.Edge, cq.Shell, cq.Vertex, getattr(cq, 'CompSolid', None)):
        if cls is not None:
            copyreg.pickle(cls, lambda shape: (_from_brep, (_brep_bytes(shape),)))


_register_pickling()


PARALLEL_MESH = True        # w procesach liczących wyłączone: tam równoległość daje sama pula procesów


def mesh_parallel(shape, tolerance, angular=.12):
    """Siatka trójkątów liczona na wszystkich rdzeniach; tessellate() używa jej potem bez ponownego liczenia."""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools
    try:
        if not BRepTools.Triangulation_s(shape.wrapped, tolerance):
            BRepMesh_IncrementalMesh(shape.wrapped, tolerance, True, angular, PARALLEL_MESH)
    except Exception:
        pass


import threading as _threading
_defer = _threading.local()


class deferred_mesh:
    """Blok, w którym nowe bryły nie dostają od razu siatki do wyświetlania (np. przeliczanie historii: stany pośrednie
    nie są pokazywane). Siatkę uzupełnia potem Document.meshed - równolegle, tylko dla stanu, który widać."""

    def __enter__(self):
        _defer.depth = getattr(_defer, 'depth', 0) + 1
        return self

    def __exit__(self, *exc):
        _defer.depth -= 1
        return False


def mesh_deferred():
    return getattr(_defer, 'depth', 0) > 0


def valid(shape, solid=True):
    if shape is None or shape.wrapped.IsNull() or not is_valid(shape):
        raise CadError("Nie udało się utworzyć poprawnej geometrii. Model pozostaje bez zmian.")
    if solid and (not shape.Solids() or shape.Volume() <= 1e-8):
        raise CadError("Operacja nie utworzyła zamkniętej bryły. Sprawdź położenie i wymiary.")
    return shape


def point_state(shape, point, tol=1e-4):
    """'in' / 'on' / 'out' - położenie punktu względem bryły."""
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    from OCP.gp import gp_Pnt
    state = BRepClass3d_SolidClassifier(shape.wrapped, gp_Pnt(*[float(c) for c in point]), tol).State()
    return 'in' if state == TopAbs_IN else ('on' if state == TopAbs_ON else 'out')


def bounds(shape):
    # Measurements must not depend on the display tessellation's deflection.
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, box, False, False)
    return cq.BoundBox(box)


def box(x, y, z):
    return valid(cq.Solid.makeBox(*(positive(v) for v in (x, y, z))))


def cylinder(radius, height):
    return valid(cq.Solid.makeCylinder(positive(radius, "Promień"), positive(height, "Wysokość")))


def sketch(kind, plane, width, height=0, x=0, y=0, sides=6):
    if not plane_ok(plane):
        raise CadError("Nieznana płaszczyzna szkicu.")
    wp_ = wp(plane).center(float(x), float(y))
    width = positive(width)
    if kind == "rectangle":
        return wp_.rect(width, positive(height)).wire().val()
    if kind == "circle":
        return wp_.circle(width / 2).wire().val()
    if kind == "polygon":
        if not 3 <= int(sides) <= 128:
            raise CadError("Wielokąt musi mieć od 3 do 128 boków.")
        return wp_.polygon(int(sides), width).wire().val()
    raise CadError("Nieznany typ szkicu.")


PLANE_AXES = {"XY": (0, 1), "XZ": (0, 2), "YZ": (1, 2)}


@dataclass(frozen=True)
class Frame:
    """Dowolna płaszczyzna szkicu (np. ściana bryły): początek, oś U (xdir) i normalna; oś V = normalna × U."""
    origin: tuple
    xdir: tuple
    normal: tuple

    @property
    def ydir(self):
        n, x = np.array(self.normal, float), np.array(self.xdir, float)
        return tuple(float(c) for c in np.cross(n, x))

    def to_dict(self):
        return dict(origin=list(self.origin), xdir=list(self.xdir), normal=list(self.normal))

    @staticmethod
    def from_dict(d):
        def v3(x):
            t = tuple(float(c) for c in x)
            if len(t) != 3 or not all(isfinite(c) for c in t):
                raise CadError("Nieprawidłowa płaszczyzna szkicu.")
            return t
        f = Frame(v3(d["origin"]), v3(d["xdir"]), v3(d["normal"]))
        if abs(float(np.dot(f.xdir, f.normal))) > 1e-6 or abs(float(np.linalg.norm(f.normal)) - 1) > 1e-6 or abs(float(np.linalg.norm(f.xdir)) - 1) > 1e-6:
            raise CadError("Nieprawidłowa płaszczyzna szkicu.")
        return f


STANDARD = {
    "XY": Frame((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "XZ": Frame((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
    "YZ": Frame((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)),
}


def plane_ok(plane):
    return isinstance(plane, Frame) or plane in STANDARD


def frame_of(plane):
    if isinstance(plane, Frame):
        return plane
    if plane not in STANDARD:
        raise CadError("Nieznana płaszczyzna szkicu.")
    return STANDARD[plane]


def wp(plane):
    f = frame_of(plane)
    return cq.Workplane(cq.Plane(origin=f.origin, xDir=f.xdir, normal=f.normal))


def face_frame(origin, normal):
    """Płaszczyzna szkicu na ścianie: U poziomo (wzdłuż osi Z × normalna), a dla ścian poziomych wzdłuż X."""
    n = np.array(normal, float)
    n = n / np.linalg.norm(n)
    x = np.array([1.0, 0, 0]) if abs(n[2]) > .9 else np.cross([0, 0, 1.0], n)
    x = x / np.linalg.norm(x)
    r = lambda a: tuple(round(float(c), 12) for c in a)
    return Frame(r(origin), r(x), r(n))


def uv_of(plane, point):
    f = frame_of(plane)
    d = np.array(point, float) - np.array(f.origin, float)
    return float(d @ np.array(f.xdir)), float(d @ np.array(f.ydir))


def to_world(plane, u, v):
    """Współrzędne szkicu (U, V) -> punkt 3D (dla XY/XZ/YZ zgodne z cq.Workplane)."""
    f = frame_of(plane)
    p = np.array(f.origin) + np.array(f.xdir) * u + np.array(f.ydir) * v
    return float(p[0]), float(p[1]), float(p[2])


def sketch_from_drag(kind, plane, u0, v0, u1, v1, sides=6):
    """Argumenty dla sketch() z przeciągnięcia myszą: prostokąt = dwa rogi, okrąg i wielokąt = środek i punkt na obwodzie."""
    if not plane_ok(plane):
        raise CadError("Nieznana płaszczyzna szkicu.")
    u0, v0, u1, v1 = (float(x) for x in (u0, v0, u1, v1))
    if not all(isfinite(x) for x in (u0, v0, u1, v1)):
        raise CadError("Nieprawidłowe współrzędne szkicu.")
    if kind == "rectangle":
        if abs(u1 - u0) < 1e-4 or abs(v1 - v0) < 1e-4:
            raise CadError("Prostokąt jest za mały.")
        return dict(kind=kind, plane=plane, width=abs(u1 - u0), height=abs(v1 - v0), x=(u0 + u1) / 2, y=(v0 + v1) / 2)
    if kind in ("circle", "polygon"):
        radius = float(np.hypot(u1 - u0, v1 - v0))
        if radius < 1e-4:
            raise CadError("Figura jest za mała.")
        return dict(kind=kind, plane=plane, width=2 * radius, x=u0, y=v0, sides=int(sides))
    raise CadError("Nieznany typ szkicu.")


def edges_at_point(shape, point, tol=2e-3):
    """Indeksy krawędzi bryły schodzących się w wierzchołku `point` (zaokrąglenie / faza narożnika obejmuje wszystkie)."""
    p = np.asarray(point, dtype=float)
    out = []
    for i, edge in enumerate(shape.Edges()):
        if edge.Length() < 1e-6:
            continue
        if any(float(np.linalg.norm(np.array(edge.positionAt(t).toTuple()) - p)) < tol for t in (0.0, 1.0)):
            out.append(i)
    return out


def face_edge_indices(shape, point):
    """Ściana najbliższa punktowi i indeksy wszystkich jej krawędzi (do obróbki całego obwodu ściany naraz)."""
    vertex = cq.Vertex.makeVertex(*[float(c) for c in point])
    face = min(shape.Faces(), key=lambda f: f.distance(vertex))
    own = face.Edges()
    return face, [i for i, e in enumerate(shape.Edges()) if any(e.isSame(o) for o in own)]


def edge_chain(shape, index, max_angle=8.0):
    """Indeksy krawędzi tworzących łańcuch styczny (G1) z krawędzią `index` - jak Shift+klik w wersji HTML."""
    edges = shape.Edges()
    if not 0 <= index < len(edges):
        raise CadError("Nieprawidłowa krawędź.")
    key = lambda p: tuple(round(c, 4) for c in p.toTuple())
    joints = {}
    for i, edge in enumerate(edges):
        if edge.Length() < 1e-6:
            continue
        for param in (0.0, 1.0):
            joints.setdefault(key(edge.positionAt(param)), []).append((i, param))
    limit = np.cos(np.radians(max_angle))
    def direction(i, param):
        t = edges[i].tangentAt(param)
        v = np.array(t.toTuple(), dtype=float)
        n = np.linalg.norm(v)
        return v / n if n > 1e-12 else None
    chain, stack = {index}, [index]
    while stack:
        i = stack.pop()
        for param in (0.0, 1.0):
            here = direction(i, param)
            if here is None:
                continue
            for j, pj in joints.get(key(edges[i].positionAt(param)), []):
                if j in chain:
                    continue
                there = direction(j, pj)
                if there is not None and abs(float(here @ there)) >= limit:
                    chain.add(j)
                    stack.append(j)
    return chain


def sketch_shape(kind, plane, points, sides=5):
    """Zamknięty profil szkicu z punktów klikniętych w (U, V) - jak w wersji HTML.

    rect: dwa narożniki; centerRect: środek i narożnik; circle: środek i punkt na okręgu;
    circle2: końce średnicy; circle3: trzy punkty; ellipse: środek i narożnik opisanego prostokąta;
    slot: oba środki końców i punkt określający szerokość; polygon: środek i wierzchołek.
    """
    if not plane_ok(plane):
        raise CadError("Nieznana płaszczyzna szkicu.")
    pts = [(float(u), float(v)) for u, v in points]
    need = {"rect": 2, "centerRect": 2, "circle": 2, "circle2": 2, "circle3": 3, "ellipse": 2, "slot": 3, "polygon": 2}
    if kind not in need:
        raise CadError("Nieznany typ szkicu.")
    if len(pts) < need[kind] or not all(isfinite(c) for p in pts for c in p):
        raise CadError("Za mało punktów szkicu.")
    dist = lambda a, b: float(np.hypot(a[0] - b[0], a[1] - b[1]))
    tiny = 1e-4
    if kind in ("rect", "centerRect"):
        (u0, v0), (u1, v1) = pts[:2]
        if kind == "centerRect":
            u0, v0, u1, v1 = 2 * u0 - u1, 2 * v0 - v1, u1, v1
        return sketch(**sketch_from_drag("rectangle", plane, u0, v0, u1, v1))
    if kind == "circle":
        return sketch(**sketch_from_drag("circle", plane, *pts[0], *pts[1]))
    if kind == "polygon":                 # pierwszy wierzchołek dokładnie w klikniętym punkcie (obrót wielokąta)
        (u0, v0), (u1, v1) = pts[:2]
        n = int(sides)
        if not 3 <= n <= 128:
            raise CadError("Wielokąt musi mieć od 3 do 128 boków.")
        r = dist(pts[0], pts[1])
        if r < tiny:
            raise CadError("Figura jest za mała.")
        a0 = math.atan2(v1 - v0, u1 - u0)
        corners = [(u0 + r * math.cos(a0 + 2 * math.pi * k / n), v0 + r * math.sin(a0 + 2 * math.pi * k / n)) for k in range(n)]
        return polyline(plane, corners, True)
    wp_ = wp(plane)
    if kind == "circle2":
        (a, b) = pts[:2]
        d = dist(a, b)
        if d < tiny:
            raise CadError("Okrąg jest za mały.")
        return wp_.center((a[0] + b[0]) / 2, (a[1] + b[1]) / 2).circle(d / 2).wire().val()
    if kind == "circle3":
        (ax, ay), (bx, by), (cx, cy) = pts[:3]
        d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if abs(d) < 1e-9:
            raise CadError("Trzy punkty leżą na jednej prostej - nie wyznaczają okręgu.")
        ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)) / d
        uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)) / d
        return wp_.center(ux, uy).circle(float(np.hypot(ax - ux, ay - uy))).wire().val()
    if kind == "ellipse":
        (cx, cy), (ex, ey) = pts[:2]
        rx, ry = abs(ex - cx), abs(ey - cy)
        if rx < tiny or ry < tiny:
            raise CadError("Elipsa jest za mała.")
        return wp_.center(cx, cy).ellipse(rx, ry).wire().val()
    # slot: dwa środki końców i punkt szerokości (odległość od osi = promień zaokrąglenia)
    (ax, ay), (bx, by), (wx, wy) = pts[:3]
    length = dist((ax, ay), (bx, by))
    if length < tiny:
        raise CadError("Szczelina jest za krótka.")
    ux, uy = (bx - ax) / length, (by - ay) / length
    radius = abs((wx - ax) * -uy + (wy - ay) * ux)
    if radius < tiny:
        raise CadError("Szczelina jest za wąska.")
    angle = float(np.degrees(np.arctan2(by - ay, bx - ax)))
    return wp_.center((ax + bx) / 2, (ay + by) / 2).slot2D(length + 2 * radius, 2 * radius, angle).wire().val()


def mirror_plane(shape, normal, origin):
    """Odbicie względem dowolnej płaszczyzny (np. wskazanej ściany)."""
    n = np.asarray(normal, dtype=float)
    length = float(np.linalg.norm(n))
    if length < 1e-9:
        raise CadError("Nieprawidłowa płaszczyzna odbicia.")
    n /= length
    return valid(shape.mirror(tuple(float(x) for x in n), tuple(float(x) for x in origin)), bool(shape.Solids()))


NORMALS = {"XY": (0, 0, 1), "XZ": (0, -1, 0), "YZ": (1, 0, 0)}


def extrude(wire, plane, distance, symmetric=False):
    distance = float(distance)
    if not isfinite(distance) or abs(distance) < 1e-5:
        raise CadError("Odległość wyciągnięcia musi być różna od zera.")
    normal = cq.Vector(*frame_of(plane).normal).multiply(distance)
    base = wire.translate(normal.multiply(-.5)) if symmetric else wire
    if not base.IsClosed():
        raise CadError("Profil musi być zamknięty.")
    return valid(cq.Solid.extrudeLinear(base, [], normal))


def boolean(operation, base, tools):
    if not tools:
        raise CadError("Wybierz co najmniej dwie bryły w drzewie modelu.")
    try:
        if operation == "union":
            result = base.fuse(*tools)
        elif operation == "subtract":
            result = base.cut(*tools)
        elif operation == "intersect":
            result = base.intersect(*tools)
        else:
            raise CadError("Nieznana operacja na bryłach.")
        return valid(result.clean())
    except CadError:
        raise
    except Exception as exc:
        raise CadError("Operacja na bryłach nie powiodła się. Sprawdź ich przecięcie.") from exc


def _corner_directions(shape, point, size):
    """Kierunki (jednostkowe, od wierzchołka) trzech krawędzi schodzących się w narożniku."""
    p = np.asarray(point, dtype=float)
    dirs = []
    for i in edges_at_point(shape, p):
        edge = shape.Edges()[i]
        start = float(np.linalg.norm(np.array(edge.positionAt(0.0).toTuple()) - p)) < 2e-3
        t = np.array(edge.tangentAt(0.0 if start else 1.0).toTuple(), dtype=float)
        t = t if start else -t
        n = float(np.linalg.norm(t))
        if n < 1e-9:
            continue
        if edge.Length() < size * 1.0005:
            raise CadError("Wartość jest za duża dla krawędzi przy tym narożniku. Zmniejsz ją.")
        dirs.append(t / n)
    if len(dirs) != 3:
        raise CadError("Faza i zaokrąglenie narożnika działają dla narożników z trzema krawędziami.")
    return dirs


def vertex_handle(shape, point):
    """Wierzchołek i kierunek do wnętrza bryły (średnia kierunków krawędzi) - strzałka rozmiaru narożnika."""
    total = np.sum(_corner_directions(shape, point, 0.0), axis=0)
    n = float(np.linalg.norm(total))
    if n < 1e-6:
        raise CadError("Nie można wyznaczyć kierunku narożnika.")
    return tuple(float(c) for c in point), tuple(float(c) for c in total / n)


def _tetra(a, b, c, d):
    pts = [cq.Vector(*[float(x) for x in q]) for q in (a, b, c, d)]
    faces = [cq.Face.makeFromWires(cq.Wire.makePolygon([pts[i], pts[j], pts[k], pts[i]])) for i, j, k in ((0, 1, 2), (0, 1, 3), (1, 2, 3), (0, 2, 3))]
    solid = cq.Solid.makeSolid(cq.Shell.makeShell(faces))
    if solid.Volume() < 0:
        solid = cq.Solid(solid.wrapped.Reversed())
    return solid


def blend_vertices(shape, points, size, kind="fillet"):
    """Sam narożnik: faza = ścięcie rogu płaszczyzną przez punkty oddalone o `size` wzdłuż trzech krawędzi;
    zaokrąglenie = ścięcie kulistą czaszą przechodzącą przez te punkty. Krawędzie poza narożnikiem zostają ostre."""
    size = positive(size, "Rozmiar narożnika")
    result = shape
    for point in points:
        v = np.asarray(point, dtype=float)
        dirs = _corner_directions(result, v, size)
        p = [v + d * size for d in dirs]
        centroid = sum(p) / 3.0
        apex = v + (v - centroid)
        tool = _tetra(p[0], p[1], p[2], apex)
        if kind != "chamfer":
            a, b, c = p
            nrm = np.cross(b - a, c - a)
            ln = float(np.linalg.norm(nrm))
            if ln < 1e-9:
                raise CadError("Narożnik jest zdegenerowany.")
            nrm = nrm / ln
            if float(nrm @ (v - a)) > 0:
                nrm = -nrm                      # w głąb bryły, od wierzchołka
            # środek okręgu opisanego na trójkącie
            ab, ac = b - a, c - a
            cross = np.cross(ab, ac)
            circ = a + (np.cross(cross, ab) * float(ac @ ac) + np.cross(ac, cross) * float(ab @ ab)) / (2.0 * float(cross @ cross))
            r = float(np.linalg.norm(circ - a))
            big = r * 1.35
            center = circ + nrm * float(np.sqrt(max(big * big - r * r, 0.0)))
            ball = cq.Solid.makeSphere(big, cq.Vector(*[float(x) for x in center]), cq.Vector(0, 0, 1), -90, 90, 360)
            tool = boolean("subtract", tool, [ball])
        try:
            result = boolean("subtract", result, [tool])
        except CadError as exc:
            raise CadError("Nie udało się obrobić narożnika. Zmniejsz wartość.") from exc
    return valid(result)


def local_piece(shape, edge_indices=None, points=None, margin=10.0):
    """Fragment bryły wokół zaznaczonych krawędzi / narożników (część wspólna z prostopadłościanem): podgląd fazy i zaokrąglenia liczy się
    na małym kawałku zamiast na całej, skomplikowanej bryle - kilkadziesiąt razy szybciej."""
    lows, highs = [], []
    all_edges = shape.Edges()
    for i in edge_indices or ():
        bb = all_edges[i].BoundingBox()
        lows.append((bb.xmin, bb.ymin, bb.zmin))
        highs.append((bb.xmax, bb.ymax, bb.zmax))
    for q in points or ():
        lows.append(tuple(float(c) for c in q))
        highs.append(tuple(float(c) for c in q))
    if not lows:
        return None
    lo, hi = np.min(lows, axis=0) - margin, np.max(highs, axis=0) + margin
    box = cq.Solid.makeBox(*(float(c) for c in (hi - lo)), pnt=cq.Vector(*(float(c) for c in lo)))
    piece = shape.intersect(box)
    return piece if piece is not None and not piece.wrapped.IsNull() and piece.Solids() else None


def map_edges(shape, piece, indices, tol=1e-4):
    """Indeksy krawędzi `indices` bryły `shape` w fragmencie `piece` (dopasowanie po początku, środku i końcu)."""
    own = shape.Edges()
    local = piece.Edges()
    probe = lambda e: [np.array(e.positionAt(t).toTuple()) for t in (0.0, .5, 1.0)]
    cache = [probe(e) for e in local]
    out = []
    for i in indices:
        a = probe(own[i])
        for j, b in enumerate(cache):
            if all(float(np.linalg.norm(x - y)) < tol for x, y in zip(a, b)) or all(float(np.linalg.norm(x - y)) < tol for x, y in zip(a, b[::-1])):
                out.append(j)
                break
        else:
            return None
    return out


def _edge_faces(shape):
    """Mapa: krawędź (TShape) -> ściany przylegające."""
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    data = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape.wrapped, TopAbs_EDGE, TopAbs_FACE, data)
    return data


def _inside_face(face, point):
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    from OCP.gp import gp_Pnt
    state = BRepClass_FaceClassifier(face.wrapped, gp_Pnt(*map(float, point)), 1e-6).State()
    return state in (TopAbs_IN, TopAbs_ON)


def blend_frames(shape, indices):
    """Geometria potrzebna do szybkiego podglądu: dla każdej krawędzi (początek, koniec, kierunek w głąb jednej i drugiej
    ściany). None, gdy któraś krawędź nie jest prostą między dwiema płaskimi ścianami. Zależy tylko od zaznaczenia,
    więc przy zmianie promienia liczy się ją raz."""
    from OCP.TopoDS import TopoDS
    edges = shape.Edges()
    ancestors = _edge_faces(shape)
    result = []
    for index in sorted(indices):
        if index < 0 or index >= len(edges):
            return None
        edge = edges[index]
        if edge.geomType() != 'LINE':
            return None
        key = ancestors.FindIndex(edge.wrapped)
        if not key:
            return None
        faces = [cq.Face(TopoDS.Face_s(f)) for f in ancestors.FindFromIndex(key)]
        unique = []
        for f in faces:
            if not any(f.wrapped.IsSame(g.wrapped) for g in unique):
                unique.append(f)
        if len(unique) != 2 or any(f.geomType() != 'PLANE' for f in unique):
            return None
        a, b = np.array(edge.startPoint().toTuple(), float), np.array(edge.endPoint().toTuple(), float)
        t = b - a
        length = float(np.linalg.norm(t))
        if length < 1e-9:
            return None
        t /= length
        mid = (a + b) / 2
        directions = []
        for f in unique:
            n = np.array(f.normalAt(cq.Vector(*mid)).toTuple(), float)
            u = np.cross(n, t)
            u /= max(np.linalg.norm(u), 1e-12)
            probe = min(length * .25, .5)
            if not _inside_face(f, mid + probe * u):
                u = -u
                if not _inside_face(f, mid + probe * u):
                    return None
            directions.append(u)
        result.append((a, b, directions[0], directions[1]))
    return result


def quick_blend_mesh(shape, indices, size, kind="fillet", segments=10, frames=None):
    """Natychmiastowy podgląd zaokrąglenia / fazy bez liczenia bryły: dla prostej krawędzi między dwiema płaskimi ścianami
    powierzchnia zaokrąglenia to wycinek walca, a faza - płaski pasek; liczone wprost z geometrii (narożniki, gdzie
    spotyka się kilka zaokrągleń, są przybliżone). None, gdy któraś krawędź nie jest taka - wtedy czeka się na dokładny."""
    if frames is None:
        frames = blend_frames(shape, indices)
    if not frames:
        return None
    size = float(size)
    A = np.array([f[0] for f in frames], float)
    B = np.array([f[1] for f in frames], float)
    U1 = np.array([f[2] for f in frames], float)
    U2 = np.array([f[3] for f in frames], float)
    cos_a = np.clip(np.einsum('ij,ij->i', U1, U2), -1, 1)
    alpha = np.arccos(cos_a)
    if np.any(alpha < 1e-3) or np.any(alpha > math.pi - 1e-3):
        return None
    if kind == 'fillet':
        setback = size / np.tan(alpha / 2)
        W = U2 - cos_a[:, None] * U1
        W /= np.linalg.norm(W, axis=1)[:, None]
        C = setback[:, None] * U1 + size * W                    # środek łuku względem punktu krawędzi
        R1 = setback[:, None] * U1 - C
        R2 = setback[:, None] * U2 - C
        angle = np.arccos(np.clip(np.einsum('ij,ij->i', R1, R2) / (size * size), -1, 1))
        axis = np.cross(R1, R2)
        axis /= np.maximum(np.linalg.norm(axis, axis=1), 1e-12)[:, None]
        phi = angle[:, None] * (np.arange(segments + 1) / segments)[None, :]          # (n, k)
        cross = np.cross(axis, R1)
        dot = np.einsum('ij,ij->i', axis, R1)
        profile = (C[:, None, :] + R1[:, None, :] * np.cos(phi)[..., None] + cross[:, None, :] * np.sin(phi)[..., None]
                   + (axis * dot[:, None])[:, None, :] * (1 - np.cos(phi))[..., None])                  # (n, k, 3)
    else:
        profile = np.stack([size * U1, size * U2], axis=1)
    n, k = profile.shape[:2]
    vertices = np.empty((n, k, 2, 3))
    vertices[:, :, 0] = A[:, None, :] + profile
    vertices[:, :, 1] = B[:, None, :] + profile
    vertices = vertices.reshape(-1, 3).astype(np.float32)
    base = (np.arange(n)[:, None] * 2 * k + np.arange(k - 1)[None, :] * 2).reshape(-1)
    triangles = np.concatenate([np.stack([base, base + 1, base + 3], 1), np.stack([base, base + 3, base + 2], 1)]).astype(np.uint32)
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    return DisplayMesh(vertices, triangles, {}, tuple(float(c) for c in (lo + hi) / 2), float(max(np.max(hi - lo), 1)))


def blend(shape, indices, size, kind="fillet"):
    size = positive(size, "Promień / odległość")
    edges = shape.Edges()
    ids = sorted(set(indices))
    if not ids or any(i < 0 or i >= len(edges) for i in ids):
        raise CadError("Zaznacz krawędzie bryły. Shift + klik dodaje kolejne.")
    selected = [edges[i] for i in ids]
    try:
        # OpenCascade solves all selected edges and their common corners together.
        result = shape.fillet(size, selected) if kind == "fillet" else shape.chamfer(size, None, selected)
        return valid(result)
    except CadError:
        raise
    except Exception as exc:
        raise CadError("Ten promień / faza nie mieści się w geometrii. Zmniejsz wartość lub wybierz mniej krawędzi.") from exc


def _face_point(face):
    """Punkt leżący na pewno wewnątrz ściany: środek największego trójkąta jej siatki, rzutowany na powierzchnię."""
    from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
    from OCP.gp import gp_Pnt
    vertices, triangles = face.tessellate(.05, .2)
    if not triangles:
        c = face.Center()
        return np.array(c.toTuple(), float)
    pts = np.array([v.toTuple() for v in vertices], float)
    tri = np.array(triangles, int)
    area = np.linalg.norm(np.cross(pts[tri[:, 1]] - pts[tri[:, 0]], pts[tri[:, 2]] - pts[tri[:, 0]]), axis=1)
    p = pts[tri[int(np.argmax(area))]].mean(axis=0)
    try:
        proj = GeomAPI_ProjectPointOnSurf(gp_Pnt(*map(float, p)), BRep_Tool.Surface_s(face.wrapped))
        if proj.NbPoints():
            q = proj.NearestPoint()
            return np.array((q.X(), q.Y(), q.Z()), float)
    except Exception:
        pass
    return p


def compound(shapes):
    return cq.Compound.makeCompound(list(shapes))


def new_faces(before, after, tolerance=1e-4):
    """Ściany bryły `after`, których nie było w `before` (np. powierzchnia zaokrąglenia / fazy).
    Ściana zachowana albo tylko przycięta leży na ścianie bryły wyjściowej; nowa - nie."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    boundary = cq.Compound.makeCompound(before.Faces()).wrapped
    found = []
    for face in after.Faces():
        try:
            p = _face_point(face)
            vertex = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex()
            dist = BRepExtrema_DistShapeShape(vertex, boundary)
            if not dist.IsDone() or dist.Value() > tolerance:
                found.append(face)
        except Exception:
            continue
    return found


def _splitter(shape, tools):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter
    from OCP.TopTools import TopTools_ListOfShape
    args, tl = TopTools_ListOfShape(), TopTools_ListOfShape()
    args.Append(shape.wrapped)
    for t in tools:
        tl.Append(t.wrapped)
    sp = BRepAlgoAPI_Splitter()
    sp.SetArguments(args)
    sp.SetTools(tl)
    sp.SetRunParallel(True)
    sp.Build()
    if not sp.IsDone():
        raise CadError("Nie udało się przeciąć bryły.")
    return [s for s in cq.Shape.cast(sp.Shape()).Solids() if s.Volume() > 1e-9]


def _span(shape):
    b = bounds(shape)
    return max(b.xlen, b.ylen, b.zlen, 1.0)


def cut_plane_face(shape, normal, origin, margin=1.6):
    """Kwadratowa ściana płaszczyzny cięcia, większa od bryły (do podziału i do podglądu)."""
    n = np.asarray(normal, float)
    n = n / np.linalg.norm(n)
    o = np.asarray(origin, float)
    c = np.array(shape.Center().toTuple(), float)
    c = c - n * float((c - o) @ n)                      # środek bryły rzutowany na płaszczyznę
    size = _span(shape) * margin * 1.8
    return cq.Face.makePlane(size, size, cq.Vector(*c), cq.Vector(*n))


def split_plane(shape, normal, origin):
    """Podział płaszczyzną. Zwraca [(bryła, strona)]: strona 1 - po stronie normalnej, strona 2 - po przeciwnej."""
    if not shape.Solids():
        raise CadError("Przeciąć można tylko bryłę.")
    n = np.asarray(normal, float)
    n = n / np.linalg.norm(n)
    o = np.asarray(origin, float)
    parts = _splitter(shape, [cut_plane_face(shape, n, o)])
    if len(parts) < 2:
        raise CadError("Płaszczyzna nie przecina bryły. Zmień odsunięcie albo płaszczyznę.")
    return [(s, 1 if float((np.array(s.Center().toTuple()) - o) @ n) >= 0 else 2) for s in parts]


def sketch_plane(edges):
    """Normalna i punkt płaszczyzny szkicu (z jego krawędzi)."""
    from OCP.BRepLib import BRepLib_FindSurface
    from OCP.GeomAdaptor import GeomAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    finder = BRepLib_FindSurface(cq.Compound.makeCompound(edges).wrapped, 1e-4, True)
    if finder.Found():
        surf = GeomAdaptor_Surface(finder.Surface())
        if surf.GetType() == GeomAbs_Plane:
            pl = surf.Plane()
            d, l = pl.Axis().Direction(), pl.Location()
            return np.array((d.X(), d.Y(), d.Z())), np.array((l.X(), l.Y(), l.Z()))
    pts = np.array([v.toTuple() for e in edges for v in (e.startPoint(), e.endPoint())], float)
    if len(pts) >= 2:      # pojedyncza prosta linia: brak jednoznacznej płaszczyzny
        raise CadError("Nie można ustalić płaszczyzny szkicu - narysuj linię w szkicu na płaszczyźnie lub ścianie.")
    raise CadError("Szkic nie ma krawędzi.")


def split_sketch(shape, sketch, normal=None):
    """Podział szkicem: jego krawędzie (linia, łuk, zamknięty profil…) przeciągnięte prostopadle do szkicu przez całą bryłę.
    Zwraca [(bryła, strona)]: zamknięty profil - strona 2 wewnątrz profilu, 1 na zewnątrz; otwarta linia - strony linii."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    if not shape.Solids():
        raise CadError("Przeciąć można tylko bryłę.")
    edges = sketch.Edges()
    if not edges:
        raise CadError("Szkic nie ma krawędzi.")
    if normal is None:
        normal, _ = sketch_plane(edges)
    n = np.asarray(normal, float)
    n = n / np.linalg.norm(n)
    L = _span(shape) * 2 + float(np.linalg.norm(np.array(shape.Center().toTuple()) - np.array(sketch.Center().toTuple()))) * 2
    def curtain(edge_list):
        back = cq.Compound.makeCompound(edge_list).translate(cq.Vector(*(-n * L)))
        return cq.Shape.cast(BRepPrimAPI_MakePrism(back.wrapped, gp_Vec(*(n * 2 * L))).Shape())

    parts = _splitter(shape, [curtain(edges)])
    if len(parts) < 2:
        longer = _extended_ends(edges, L)      # linia kończąca się na bryle: wolne końce prostych przedłużone przez całą bryłę
        if longer is not None:
            edges = longer
            parts = _splitter(shape, [curtain(edges)])
    if len(parts) < 2:
        raise CadError("Szkic nie przecina bryły na części - linia musi przejść przez całą bryłę (albo profil musi być zamknięty).")
    wires = [w for w in sketch.Wires() if w.IsClosed()] if hasattr(sketch, 'Wires') else []
    if wires:
        faces = []
        for w in wires:
            try:
                faces.append(cq.Face.makeFromWires(w))
            except Exception:
                pass
        if faces:
            prism = cq.Shape.cast(BRepPrimAPI_MakePrism(cq.Compound.makeCompound(faces).translate(cq.Vector(*(-n * L))).wrapped, gp_Vec(*(n * 2 * L))).Shape())
            return [(s, 2 if _inside_share(s, prism) > .5 else 1) for s in parts]
    # otwarta linia: strona wg położenia środka części względem najbliższego fragmentu linii (w płaszczyźnie szkicu)
    out = []
    for s in parts:
        c = np.array(s.Center().toTuple(), float)
        best = None
        for e in edges:
            for t in np.linspace(0, 1, 21):
                q = np.array(e.positionAt(t).toTuple(), float)
                d = float(np.linalg.norm((c - q) - n * float((c - q) @ n)))
                if best is None or d < best[0]:
                    tan = np.array(e.tangentAt(t).toTuple(), float)
                    best = (d, q, tan)
        _, q, tan = best
        out.append((s, 1 if float(np.cross(tan, c - q) @ n) >= 0 else 2))
    return out


def _extended_ends(edges, length):
    """Krawędzie otwartego szkicu z wolnymi końcami prostych odcinków przedłużonymi o length (None, gdy nie ma czego przedłużyć)."""
    def key(p):
        return tuple(np.round(np.asarray(p, float), 5))
    ends = {}
    for e in edges:
        for p in (e.startPoint().toTuple(), e.endPoint().toTuple()):
            ends[key(p)] = ends.get(key(p), 0) + 1
    out, changed = [], False
    for e in edges:
        if e.geomType() != "LINE":
            out.append(e)
            continue
        a, b = np.array(e.startPoint().toTuple(), float), np.array(e.endPoint().toTuple(), float)
        d = b - a
        if np.linalg.norm(d) < 1e-9:
            out.append(e)
            continue
        d = d / np.linalg.norm(d)
        a2 = a - d * length if ends.get(key(a), 0) == 1 else a
        b2 = b + d * length if ends.get(key(b), 0) == 1 else b
        changed = changed or a2 is not a or b2 is not b
        out.append(cq.Edge.makeLine(cq.Vector(*a2), cq.Vector(*b2)))
    return out if changed else None


def _inside_share(solid, tool):
    try:
        common = boolean("intersect", solid, [tool])
        return common.Volume() / max(solid.Volume(), 1e-12)
    except Exception:
        return 0.0


def split_body(shape, tool):
    """Podział inną bryłą (jej powierzchnią). Zwraca [(bryła, strona)]: strona 2 - wewnątrz bryły-narzędzia, 1 - na zewnątrz."""
    if not shape.Solids() or not tool.Solids():
        raise CadError("Przeciąć można tylko bryłę i tylko inną bryłą.")
    parts = _splitter(shape, [tool])
    if len(parts) < 2:
        raise CadError("Bryły się nie przecinają.")
    return [(s, 2 if _inside_share(s, tool) > .5 else 1) for s in parts]


def hole(shape, radius, x, y, depth=0):
    radius = positive(radius, "Promień otworu")
    box_bounds = bounds(shape)
    depth = float(depth)
    if depth < 0 or not isfinite(depth):
        raise CadError("Głębokość musi być dodatnia lub równa zero dla otworu przelotowego.")
    height = box_bounds.zlen + 2 if depth == 0 else positive(depth) + 1
    bottom = box_bounds.zmin - 1 if depth == 0 else box_bounds.zmax - depth
    tool = cq.Solid.makeCylinder(radius, height, (float(x), float(y), bottom))
    result = boolean("subtract", shape, [tool])
    if shape.Volume() - result.Volume() < 1e-6:
        raise CadError("Otwór nie przecina bryły. Sprawdź współrzędne środka.")
    return result


def transform(shape, translation=(0, 0, 0), rotation=(0, 0, 0), center=None):
    """center: punkt obrotu (domyślnie środek bryły; grupa obraca się wokół wspólnego środka)."""
    if not all(isfinite(float(v)) for v in (*translation, *rotation)):
        raise CadError("Współrzędne muszą być skończonymi liczbami.")
    center = tuple(float(c) for c in center) if center is not None else shape.Center().toTuple()
    result = shape
    for axis, angle in zip(((1, 0, 0), (0, 1, 0), (0, 0, 1)), rotation):
        if angle:
            end = tuple(center[i] + axis[i] for i in range(3))
            result = result.rotate(center, end, float(angle))
    return valid(result.translate(tuple(float(v) for v in translation)), bool(shape.Solids()))


def transform_matrix(shape, translation=(0, 0, 0), rotation=(0, 0, 0), center=None):
    """Macierz 3x4 tego samego przekształcenia co transform(): obroty wokół osi X, Y, Z przez środek bryły (albo center)
    (kolejno), potem przesunięcie. Służy do przeniesienia razem z bryłą danych w niej zapisanych (np. przepisu blachy)."""
    c = np.array(center if center is not None else shape.Center().toTuple(), float)
    R = np.eye(3)
    for axis, angle in zip(np.eye(3), rotation):
        if angle:
            a = math.radians(float(angle))
            K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
            R = (np.eye(3) + math.sin(a) * K + (1 - math.cos(a)) * (K @ K)) @ R
    t = c - R @ c + np.array([float(v) for v in translation])
    return np.column_stack([R, t])


PATTERN_MAX = 400


def _unit(v):
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise CadError("Nieprawidłowy kierunek.")
    return v / n


def pattern_ops(kind, p):
    """Kopie szyku (bez oryginału) jako lista operacji: ('t', (x, y, z)) - przesunięcie, ('r', oś, punkt, kąt°) - obrót.
    kind: 'rect' (counts, spacing), 'circ' (axis, pivot, count, angle) albo 'path' (points, count, fit, spacing)."""
    ops = []
    if kind == "rect":
        nx, ny, nz = (max(1, int(c)) for c in p["counts"])
        dx, dy, dz = (float(c) for c in p["spacing"])
        if nx * ny * nz > PATTERN_MAX:
            raise CadError(f"Zbyt wiele kopii (maksymalnie {PATTERN_MAX}).")
        # axes: kierunki trzech rzędów (np. osie płaszczyzny szkicu na pochylonej ścianie); domyślnie osie świata X, Y, Z
        ax, ay, az = (np.asarray(v, float) for v in p.get("axes", ((1, 0, 0), (0, 1, 0), (0, 0, 1))))
        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    if (i, j, k) != (0, 0, 0):
                        ops.append(("t", tuple(float(c) for c in i * dx * ax + j * dy * ay + k * dz * az)))
    elif kind == "circ":
        n = max(1, int(p["count"]))
        if n > PATTERN_MAX:
            raise CadError(f"Zbyt wiele kopii (maksymalnie {PATTERN_MAX}).")
        total = float(p["angle"])
        axis = tuple(float(c) for c in _unit(p["axis"]))
        step = total / n if abs(abs(total) - 360.0) < 1e-9 else (total / (n - 1) if n > 1 else 0.0)
        pivot = tuple(float(c) for c in p["pivot"])
        offset = tuple(float(c) for c in p.get("offset", (0.0, 0.0, 0.0)))
        for i in range(1, n):
            ops.append(("r", axis, pivot, i * step, offset))
    elif kind == "path":
        pts = np.asarray(p["points"], dtype=float)
        if len(pts) < 2:
            raise CadError("Wskaż linię lub krawędź jako ścieżkę.")
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        length = float(cum[-1])
        if length < 1e-9:
            raise CadError("Ścieżka ma zerową długość.")
        n = max(1, int(p["count"]))
        if n > PATTERN_MAX:
            raise CadError(f"Zbyt wiele kopii (maksymalnie {PATTERN_MAX}).")
        if p.get("fit", True):
            dist = np.linspace(0.0, length, n) if n > 1 else np.zeros(1)
        else:
            step = max(float(p.get("spacing", 10.0)), 1e-6)
            dist = np.arange(n) * step
            dist = dist[dist <= length + 1e-9]
        at = lambda d: np.array([np.interp(d, cum, pts[:, k]) for k in range(3)])
        base = at(0.0)
        for d in dist[1:]:
            ops.append(("t", tuple(float(c) for c in at(float(d)) - base)))
    else:
        raise CadError("Nieznany rodzaj szyku.")
    return ops


def op_matrix(op):
    """Macierz 4x4 operacji szyku (do natychmiastowego podglądu bez OCC)."""
    m = np.eye(4)
    if op[0] == "t":
        m[:3, 3] = op[1]
        return m
    axis, pivot, ang = _unit(op[1]), np.asarray(op[2], dtype=float), np.radians(op[3])
    k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    r = np.eye(3) + np.sin(ang) * k + (1 - np.cos(ang)) * (k @ k)
    m[:3, :3] = r
    m[:3, 3] = pivot - r @ pivot
    if len(op) > 4:      # najpierw przesunięcie promieniowe (odległość od środka), potem obrót
        m[:3, 3] = m[:3, 3] + r @ np.asarray(op[4], dtype=float)
    return m


def apply_op(shape, op):
    if op[0] == "t":
        return shape.translate(tuple(float(c) for c in op[1]))
    pivot = tuple(float(c) for c in op[2])
    end = tuple(pivot[i] + float(op[1][i]) for i in range(3))
    if len(op) > 4 and any(abs(float(c)) > 1e-12 for c in op[4]):
        shape = shape.translate(tuple(float(c) for c in op[4]))
    return shape.rotate(pivot, end, float(op[3]))


def pattern_mesh(mesh, ops, original=True):
    """Siatka podglądu szyku: kopie siatki bazowej przekształcone macierzami (czysty numpy, więc płynnie w czasie rzeczywistym).
    original=False pomija nieprzesunięty oryginał (gdy pierwszą operacją jest jego przesunięcie na zadaną odległość)."""
    vertices, triangles, edges = [], [], {}
    key, offset = 0, 0
    if original:
        vertices.append(mesh.vertices.astype(np.float32))
        triangles.append(mesh.triangles)
        offset = len(mesh.vertices)
        for points in mesh.edges.values():
            edges[key] = points
            key += 1
    for op in ops:
        m = op_matrix(op)
        vertices.append((mesh.vertices @ m[:3, :3].T + m[:3, 3]).astype(np.float32))
        triangles.append(mesh.triangles + offset)
        offset += len(mesh.vertices)
        for points in mesh.edges.values():
            edges[key] = (points @ m[:3, :3].T + m[:3, 3]).astype(np.float32)
            key += 1
    return DisplayMesh(np.vstack(vertices), np.vstack(triangles) if len(mesh.triangles) else mesh.triangles, edges, mesh.center, mesh.size)


def mirror(shape, plane):
    return valid(shape.mirror(plane), bool(shape.Solids()))


def import_shapes(path):
    path = Path(path)
    try:
        if path.suffix.lower() in (".step", ".stp"):
            root = cq.importers.importStep(str(path)).val()
            return [(valid(s), "solid") for s in root.Solids()]
        if path.suffix.lower() in (".brep", ".brp"):
            root = cq.importers.importBrep(str(path)).val()
            return [(valid(s), "solid") for s in root.Solids()]
        if path.suffix.lower() == ".stl":
            shape = TopoDS_Shape()
            if not StlAPI_Reader().Read(shape, str(path)):
                raise CadError("Nie można odczytać pliku STL.")
            return [(valid(cq.Shape.cast(shape), False), "mesh")]
        if path.suffix.lower() == ".dxf":           # jednostki z nagłówka, splajny, bloki - jak w rysunku technicznym
            from .import2d import sketch_wires
            return [(w, "sketch") for w in sketch_wires(path)]
        raise CadError("Obsługiwane formaty: STEP, BREP, STL i DXF.")
    except CadError:
        raise
    except Exception as exc:
        raise CadError(f"Nie można odczytać pliku {path.name}.") from exc


def export_shapes(shapes, path):
    if not shapes:
        raise CadError("Brak geometrii do eksportu.")
    path = Path(path)
    formats = {".step": "STEP", ".stp": "STEP", ".stl": "STL", ".brep": "BREP", ".dxf": "DXF"}
    fmt = formats.get(path.suffix.lower())
    if not fmt:
        raise CadError("Wybierz rozszerzenie STEP, STL, BREP lub DXF.")
    compound = shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)
    cq.exporters.export(compound, str(path), exportType=fmt, tolerance=.05, angularTolerance=.08)


@dataclass
class DisplayMesh:
    vertices: np.ndarray
    triangles: np.ndarray
    # Entries refer to the original topological edge IDs, not triangle edges.
    edges: dict[int, np.ndarray]
    center: tuple[float, float, float]
    size: float
    fine: bool = True          # False: zgrubna siatka pokazana od razu; dokładną liczy się w tle (refine)
    face_ids: np.ndarray | None = None


FINE_ANGLE = .2             # dokładna siatka: odchyłka kątowa (rad) - otwór R2 ma 32 odcinki na obwodzie, duże łuki prowadzi odchyłka liniowa
PREVIEW_ANGLE = .35         # podglądy na żywo (tolerancja liniowa >= .25): rzadsza siatka, liczona kilka razy szybciej
COARSE = (.5, .5)           # zgrubna siatka dużej bryły (liniowa mm, kątowa rad) - ok. 10x szybciej niż dokładna
HEAVY_FACES = 40            # od tylu ścian bryła dostaje najpierw zgrubną siatkę


def heavy(shape):
    """Bryła, której dokładna siatka liczy się zauważalnie długo (wiele ścian, np. otwory, zaokrąglenia, blacha z gięciami)."""
    try:
        from OCP.TopExp import TopExp
        from OCP.TopTools import TopTools_IndexedMapOfShape
        from OCP.TopAbs import TopAbs_FACE
        faces = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape.wrapped, TopAbs_FACE, faces)
        return faces.Extent() >= HEAVY_FACES
    except Exception:
        return False


def _fast_triangles(shape):
    """Trójkąty gotowej siatki OpenCascade prosto do tablic numpy: zapis binarnego STL w C++ i odczyt jednym ruchem
    (zamiast przepisywania każdego punktu w Pythonie - kilka razy szybciej). Punkty są wspólne tylko w obrębie ściany,
    więc krawędzie brył zostają ostre, a ściany zakrzywione gładkie - tak jak dotąd. None, gdy coś się nie zgadza."""
    import os, tempfile, uuid
    from OCP.StlAPI import StlAPI_Writer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    counts = []
    explorer = TopExp_Explorer(shape.wrapped, TopAbs_FACE)
    while explorer.More():
        poly = BRep_Tool.Triangulation_s(TopoDS.Face_s(explorer.Current()), TopLoc_Location())
        counts.append(poly.NbTriangles() if poly is not None else 0)
        explorer.Next()
    total = sum(counts)
    if not total:
        return None
    path = os.path.join(tempfile.gettempdir(), f'rccad-{os.getpid()}-{uuid.uuid4().hex}.stl')
    try:
        writer = StlAPI_Writer()
        writer.ASCIIMode = False
        if not writer.Write(shape.wrapped, path):
            return None
        data = np.fromfile(path, dtype=np.uint8)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if len(data) < 84 or int(np.frombuffer(data[80:84].tobytes(), dtype='<u4')[0]) != total or len(data) < 84 + 50 * total:
        return None
    record = np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')])
    points = np.frombuffer(data[84:84 + 50 * total].tobytes(), dtype=record)['v'].reshape(-1, 3)
    face = np.repeat(np.repeat(np.arange(len(counts), dtype=np.int32), counts), 3)
    keys = np.empty((len(points), 4), dtype=np.int32)
    keys[:, 0] = face
    keys[:, 1:] = points.view(np.int32)
    _, first, inverse = np.unique(np.ascontiguousarray(keys).view(np.dtype((np.void, 16))).ravel(), return_index=True, return_inverse=True)
    return points[first].astype(np.float32), inverse.reshape(-1, 3).astype(np.uint32), np.repeat(np.arange(len(counts),dtype=np.int32),counts)


def edge_points(edge, length=None):
    """Punkty linii krawędzi do wyświetlania. Długie krzywe (np. linie śrubowe gwintu) próbkowane wg ugięcia, nie stałą liczbą punktów
    - inaczej cięciwy przecinały bryłę i wyglądały jak siatka trójkątów."""
    if edge.geomType() == "LINE":
        points = edge.positions([0.0, 1.0])
        return np.asarray([p.toTuple() for p in points], dtype=np.float32)
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    length = edge.Length() if length is None else length
    count = min(96, max(16, int(length / 1.0)))
    curve = BRepAdaptor_Curve(edge.wrapped)
    if edge.geomType() not in ("CIRCLE", "ELLIPSE"):
        try:
            from OCP.GCPnts import GCPnts_TangentialDeflection
            sampler = GCPnts_TangentialDeflection(curve, .12, min(.02, max(length, 1e-3) * .002), 16)
            count = max(count, min(20000, sampler.NbPoints()))     # tyle punktów, ile potrzeba wg krzywizny
        except Exception:
            count = max(count, min(4000, int(length / .5)))
    # równo w parametrze krzywej: szybko i bez błędów odmierzania długości na zdegenerowanych krzywych (np. z SVG)
    t0, t1 = curve.FirstParameter(), curve.LastParameter()
    pts = [curve.Value(t) for t in np.linspace(t0, t1, count)]
    return np.asarray([(p.X(), p.Y(), p.Z()) for p in pts], dtype=np.float32)


def display_mesh(shape, tolerance=.12, angular=None, coarse=False):
    """Siatka do wyświetlania. angular domyślnie: dokładna dla zwykłej tolerancji, rzadsza dla podglądów (tolerancja >= .25).
    coarse=True: zgrubna siatka (fine=False) - pokazana od razu, dokładna przychodzi później."""
    if coarse:
        tolerance, angular = COARSE
    elif angular is None:
        angular = PREVIEW_ANGLE if tolerance >= .25 else FINE_ANGLE
    mesh_parallel(shape, tolerance, angular)
    fast = None
    try:
        fast = _fast_triangles(shape)
    except Exception:
        fast = None
    face_ids=None
    if fast is None:
        vertices, triangles = shape.tessellate(tolerance, angular)
        vertices = np.asarray([v.toTuple() for v in vertices], dtype=np.float32).reshape(-1, 3)
        triangles = np.asarray(triangles, dtype=np.uint32).reshape(-1, 3)
    else:
        vertices, triangles, face_ids = fast
    edge_faces = {}
    faces = shape.Faces()
    for face in faces:
        for edge in face.Edges():
            edge_faces.setdefault(edge.hashCode(), []).append(face)
    edges = {}
    for i, edge in enumerate(shape.Edges()):
        adjacent = edge_faces.get(edge.hashCode(), [])
        if len(adjacent) == 1 and BRep_Tool.IsClosed_s(edge.wrapped, adjacent[0].wrapped):
            continue  # Periodic seam of a cylinder/torus is not a physical edge.
        if len(adjacent) == 2:
            try:
                if BRep_Tool.Continuity_s(edge.wrapped, adjacent[0].wrapped, adjacent[1].wrapped) != GeomAbs_C0:
                    continue  # Do not draw/pick smooth fillet seams as sharp edges.
            except Exception:
                pass
        length = edge.Length()
        if length < 1e-6:
            continue
        edges[i] = edge_points(edge, length)
    box_bounds = bounds(shape)
    return DisplayMesh(vertices, triangles, edges, box_bounds.center.toTuple(), max(box_bounds.xlen, box_bounds.ylen, box_bounds.zlen, 1),
                       fine=not coarse,face_ids=face_ids)


# ---------- etap 2: linie, łuki, punkty, prostokąt 3-punktowy, okrąg styczny, tekst, SVG ----------
def _vec(plane, p):
    return cq.Vector(*to_world(plane, float(p[0]), float(p[1])))


def polyline(plane, points, closed=False):
    """Łamana (lub zamknięty wielokąt) z punktów (U, V)."""
    if not plane_ok(plane):
        raise CadError("Nieznana płaszczyzna szkicu.")
    pts = [(float(u), float(v)) for u, v in points]
    clean = [pts[0]]
    for p in pts[1:]:
        if np.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 1e-4:
            clean.append(p)
    if closed and len(clean) > 2 and np.hypot(clean[0][0] - clean[-1][0], clean[0][1] - clean[-1][1]) <= 1e-4:
        clean.pop()
    if len(clean) < 2 or (closed and len(clean) < 3):
        raise CadError("Za mało różnych punktów.")
    seq = clean + [clean[0]] if closed else clean
    edges = [cq.Edge.makeLine(_vec(plane, a), _vec(plane, b)) for a, b in zip(seq[:-1], seq[1:])]
    return cq.Wire.assembleEdges(edges)


def arc3(plane, points):
    (a, b, c) = points[:3]
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-9:
        raise CadError("Trzy punkty leżą na jednej prostej - nie wyznaczają łuku.")
    return cq.Wire.assembleEdges([cq.Edge.makeThreePointArc(_vec(plane, a), _vec(plane, b), _vec(plane, c))])


def rect3(plane, points):
    """Prostokąt 3-punktowy: dwa punkty podstawy i punkt określający wysokość."""
    (ax, ay), (bx, by), (cx, cy) = [(float(u), float(v)) for u, v in points[:3]]
    length = float(np.hypot(bx - ax, by - ay))
    if length < 1e-4:
        raise CadError("Podstawa prostokąta jest za krótka.")
    ux, uy = (bx - ax) / length, (by - ay) / length
    h = (cx - ax) * -uy + (cy - ay) * ux
    if abs(h) < 1e-4:
        raise CadError("Wysokość prostokąta jest za mała.")
    nx, ny = -uy * h, ux * h
    return polyline(plane, [(ax, ay), (bx, by), (bx + nx, by + ny), (ax + nx, ay + ny)], True)


def point_marker(plane, p, size=.6):
    return wp(plane).center(float(p[0]), float(p[1])).circle(size).wire().val()


def _line_uv(edge, plane):
    return uv_of(plane, edge.startPoint().toTuple()), uv_of(plane, edge.endPoint().toTuple())


def circle_tangent2(plane, line1, line2, hint):
    """Okrąg styczny do dwóch prostych (każda jako para punktów UV); środek na dwusiecznej bliższej punktowi `hint`."""
    def norm(l):
        (ax, ay), (bx, by) = l
        n = float(np.hypot(bx - ax, by - ay))
        if n < 1e-9:
            raise CadError("Linia jest zdegenerowana.")
        dx, dy = (bx - ax) / n, (by - ay) / n
        return ax, ay, dx, dy
    ax, ay, dx1, dy1 = norm(line1)
    bx, by, dx2, dy2 = norm(line2)
    det = dx1 * -dy2 - dy1 * -dx2
    if abs(det) < 1e-9:
        raise CadError("Linie są równoległe - okrąg styczny nie jest jednoznaczny.")
    t = ((bx - ax) * -dy2 - (by - ay) * -dx2) / det
    px, py = ax + t * dx1, ay + t * dy1
    best = None
    for s in (1, -1):
        bxv, byv = dx1 + s * dx2, dy1 + s * dy2
        n = float(np.hypot(bxv, byv))
        if n < 1e-9:
            continue
        bxv, byv = bxv / n, byv / n
        proj = (hint[0] - px) * bxv + (hint[1] - py) * byv
        cx, cy = px + bxv * proj, py + byv * proj
        dist = abs((cx - px) * -dy1 + (cy - py) * dx1)
        gap = float(np.hypot(hint[0] - cx, hint[1] - cy))
        if dist > 1e-4 and (best is None or gap < best[0]):
            best = (gap, cx, cy, dist)
    if best is None:
        raise CadError("Nie można wyznaczyć okręgu stycznego.")
    return wp(plane).center(best[1], best[2]).circle(best[3]).wire().val()


_STYLE_WORDS = {"bold", "italic", "oblique", "regular", "normal"}


def font_file(family, bold=False, italic=False):
    """Ścieżka pliku czcionki zainstalowanej w Windows (rejestr Fonts) dla rodziny i stylu; None, gdy brak / inny system."""
    import sys
    if sys.platform != "win32" or not family:
        return None
    try:
        import os
        import winreg
        wanted = ({"bold"} if bold else set()) | ({"italic"} if italic else set())
        best = None
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
            except OSError:
                continue
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                base = name.rsplit(" (", 1)[0]
                for part in base.split(" & "):
                    words = part.split()
                    low = [w.lower() for w in words]
                    k = len(words)
                    while k > 0 and low[k - 1] in _STYLE_WORDS:
                        k -= 1
                    if " ".join(words[:k]).lower() != family.lower():
                        continue
                    style = {w for w in low[k:] if w in _STYLE_WORDS} - {"regular", "normal"}
                    style = {"italic" if w == "oblique" else w for w in style}
                    path = value if os.path.isabs(value) else os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", value)
                    if not os.path.exists(path):
                        alt = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts", value)
                        path = alt if os.path.exists(alt) else None
                    if path is None:
                        continue
                    score = (style == wanted, -len(style ^ wanted), not path.lower().endswith(".ttc"))
                    if best is None or score > best[0]:
                        best = (score, path)
        return best[1] if best else None
    except Exception:
        return None


_TEXT_CACHE = {}
_TEXT_REF = 10.0   # wysokość odniesienia: napis liczymy raz, a rozmiar / obrót / położenie to tanie przekształcenia druty


def _text_direct(plane, text, size, font, bold, italic, halign):
    fr = frame_of(plane)
    n0, o0 = np.array(fr.normal), np.array(fr.origin)
    kind = "bold" if bold else ("italic" if italic else "regular")
    for name, path in ((font, font_file(font, bold, italic)), ("Arial", font_file("Arial", bold, italic)), ("Sans", None)):
        try:
            solid = wp(plane).text(text, float(size), 0.2, combine=False, font=name, fontPath=path, kind=kind,
                                   halign=halign, valign="bottom").val()
        except Exception:
            continue
        wires = [w for f in (solid.Faces() if solid is not None else [])
                 if abs(float((np.array(f.Center().toTuple()) - o0) @ n0)) < 1e-5 and abs(abs(float(np.array(f.normalAt().toTuple()) @ n0)) - 1) < 1e-3
                 for w in f.Wires()]
        if wires:
            return wires
    raise CadError("Nie udało się utworzyć tekstu (brak czcionki lub znaków w czcionce).")


def _text_base(plane, text, font, bold, italic, halign):
    key = (frame_of(plane), text, font, bool(bold), bool(italic), halign)
    wires = _TEXT_CACHE.get(key)
    if wires is None:
        wires = _text_direct(plane, text, _TEXT_REF, font, bold, italic, halign)
        if len(_TEXT_CACHE) > 24:
            _TEXT_CACHE.clear()
        _TEXT_CACHE[key] = wires
    return wires


def text_extent(plane, text, font="Arial", bold=False, italic=False, halign="left"):
    """Obrys napisu (umin, vmin, umax, vmax) w układzie szkicu dla wysokości odniesienia 10 mm i kotwicy w punkcie (0, 0)."""
    text = str(text).strip()
    if not text:
        raise CadError("Wpisz treść tekstu.")
    wires = _text_base(plane, text, font, bold, italic, halign)
    pts = np.array([uv_of(plane, e.positionAt(t).toTuple()) for w in wires for e in w.Edges() for t in (0.0, .25, .5, .75, 1.0)], dtype=float)
    return float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())


def text_shape(plane, text, u, v, size=10.0, font="Arial", bold=False, halign="left", angle=0.0, italic=False):
    """Kontury liter na płaszczyźnie szkicu: zewnętrzne i wewnętrzne (otwory w a, e, o, ą…) jako osobne druty.
    Czcionka: rodzina zainstalowana w systemie (w Windows z pliku czcionki, więc działają polskie znaki)."""
    text = str(text).strip()
    if not text:
        raise CadError("Wpisz treść tekstu.")
    size = float(size)
    if not isfinite(size) or size <= 0:
        raise CadError("Wysokość liter musi być dodatnia.")
    fr = frame_of(plane)
    n0, o0 = np.array(fr.normal, float), np.array(fr.origin, float)
    wires = _text_base(plane, text, font, bold, italic, halign)
    factor = size / _TEXT_REF
    try:
        back = cq.Vector(*o0)
        wires = [w.translate(back * -1).scale(factor).translate(back) for w in wires] if abs(factor - 1) > 1e-9 else list(wires)
    except Exception:
        wires = _text_direct(plane, text, size, font, bold, italic, halign)
    if abs(float(angle)) > 1e-9:
        pivot = cq.Vector(*o0)
        wires = [w.rotate(pivot, pivot + cq.Vector(*n0), float(angle)) for w in wires]
    shift = cq.Vector(*(np.array(to_world(plane, float(u), float(v)), float) - o0))
    return [w.translate(shift) for w in wires]


def profile_normal(shape, reference):
    """Rzeczywista normalna płaskiego profilu (także po obrocie / przesunięciu szkicu), zwrócona zgodnie z płaszczyzną odniesienia."""
    ref = np.asarray(reference, dtype=float)
    try:
        wires = shape.Wires() if hasattr(shape, "Wires") else [shape]
        n = np.array(cq.Face.makeFromWires(wires[0]).normalAt().toTuple(), dtype=float)
        n = n / np.linalg.norm(n)
    except Exception:
        return tuple(ref)
    if float(n @ ref) < 0:
        n = -n
    return tuple(float(c) for c in n)


def actual_frame(shape, plane, tol=1e-4):
    """Płaszczyzna, w której naprawdę leży szkic: ta sama, jeśli nie ruszano szkicu; po obrocie / przesunięciu - nowa Frame wyliczona z geometrii."""
    fr = frame_of(plane)
    n0, o0 = np.array(fr.normal, float), np.array(fr.origin, float)
    try:
        pts = np.array([e.positionAt(t).toTuple() for e in shape.Edges() for t in (0.0, .37, .71, 1.0)], dtype=float)
        if len(pts) and float(np.max(np.abs((pts - o0) @ n0))) < tol:
            return plane
        n = np.array(profile_normal(shape, n0), dtype=float)
        origin = n * float(n @ pts[0])
        x = np.array(fr.xdir, float) - n * float(np.array(fr.xdir, float) @ n)
        if np.linalg.norm(x) < 1e-6:
            x = np.cross(n, [0.0, 0.0, 1.0] if abs(n[2]) < .9 else [1.0, 0.0, 0.0])
        x = x / np.linalg.norm(x)
        r = lambda a: tuple(round(float(c), 9) + 0.0 for c in a)
        return Frame(r(origin), r(x), r(n))
    except Exception:
        return plane


def extrude2(wire, plane, d1, d2):
    """Wyciągnięcie w dwie strony niezależnie: d1 po normalnej, d2 przeciwnie."""
    d1, d2 = float(d1), float(d2)
    if not isfinite(d1) or not isfinite(d2) or d1 < 0 or d2 < 0 or d1 + d2 < 1e-5:
        raise CadError("Obie odległości muszą być nieujemne, a ich suma większa od zera.")
    n = cq.Vector(*frame_of(plane).normal)
    base = wire.translate(n.multiply(-d2))
    if not base.IsClosed():
        raise CadError("Profil musi być zamknięty.")
    return valid(cq.Solid.extrudeLinear(base, [], n.multiply(d1 + d2)))


def remove_edge(shape, index):
    """Nożyczki: usuwa jedną krawędź szkicu; zwraca listę pozostałych krawędzi złożonych w druty (może być pusta)."""
    edges = shape.Edges()
    if not 0 <= index < len(edges):
        raise CadError("Nieprawidłowa krawędź.")
    rest = [e for i, e in enumerate(edges) if i != index]
    if not rest:
        return []
    try:
        return [cq.Wire.assembleEdges(rest)]
    except Exception:
        return [cq.Wire.assembleEdges([e]) for e in rest]


def svg_profiles(path, plane="XY"):
    """Import SVG / DXF jako szkic: ścieżki z krzywymi Béziera i łukami, przekształcenia (transform), jednostki
    (mm, cm, in, pt, px - bez jednostki to piksele 96/cal). Kontury w mm, połączone w obwody."""
    from .import2d import sketch_wires
    wires = sketch_wires(path)
    if plane in ("XY", None):
        return wires
    frame = frame_of(plane)
    rot = np.column_stack([np.asarray(frame.xdir, float), np.cross(np.asarray(frame.normal, float), np.asarray(frame.xdir, float)),
                           np.asarray(frame.normal, float)])
    return [transformed(w, rot, np.asarray(frame.origin, float)) for w in wires]


def extrude_dir(wire, normal, d1, d2=0.0, symmetric=False):
    """Wyciągnięcie wzdłuż dowolnej normalnej (np. ściany bryły). d1 > 0 po normalnej, d1 < 0 przeciwnie."""
    d1, d2 = float(d1), float(d2)
    n = np.asarray(normal, dtype=float)
    n = n / np.linalg.norm(n)
    nv = cq.Vector(*[float(x) for x in n])
    if symmetric:
        base, total = wire.translate(nv.multiply(-d1 / 2)), d1
    else:
        base, total = wire.translate(nv.multiply(-d2)) if d2 else wire, d1 + d2
    if not isfinite(total) or abs(total) < 1e-5:
        raise CadError("Odległość wyciągnięcia musi być różna od zera.")
    if not base.IsClosed():
        raise CadError("Profil musi być zamknięty.")
    return valid(cq.Solid.extrudeLinear(base, [], nv.multiply(total)))


def is_planar_face(face, tol=1e-4):
    """Czy ściana jest płaska. Bryły z przeciągnięcia i wyciągnięcia złożonego mają płaskie ściany zapisane jako powierzchnie B-sklejane
    (typ inny niż PLANE) i z błędem aproksymacji, więc samo geomType() nie wystarcza - sprawdzamy geometrię (najpierw dokładnie,
    potem próbkując powierzchnię: odchylenie od płaszczyzny mniejsze niż ok. 0,005 mm uznajemy za płaską ścianę)."""
    if face.geomType() == "PLANE":
        return True
    try:
        from OCP.BRep import BRep_Tool
        from OCP.GeomLib import GeomLib_IsPlanarSurface
        if bool(GeomLib_IsPlanarSurface(BRep_Tool.Surface_s(face.wrapped), tol).IsPlanar()):
            return True
    except Exception:
        pass
    try:
        u0, u1, v0, v1 = face._uvBounds()
        adaptor = face._geomAdaptor()
        pts = np.array([adaptor.Value(u0 + (u1 - u0) * i / 7.0, v0 + (v1 - v0) * j / 7.0).Coord() for i in range(8) for j in range(8)], float)
        center = pts.mean(axis=0)
        normal = np.linalg.svd(pts - center)[2][-1]
        size = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
        return float(np.abs((pts - center) @ normal).max()) <= max(5e-3, 2e-5 * size)
    except Exception:
        return False


_FACE_INDEX=LRU(96*1024*1024,max_entries=128)


def _face_index(shape):
    cached=_FACE_INDEX.get(id(shape))
    if cached is not None and cached[0] is shape:return cached[1:]
    faces=shape.Faces();boxes=[bounds(face) for face in faces]
    low=np.array([[b.xmin,b.ymin,b.zmin] for b in boxes]);high=np.array([[b.xmax,b.ymax,b.zmax] for b in boxes])
    bb=bounds(shape);size=float(np.linalg.norm([bb.xlen,bb.ylen,bb.zlen]))
    tree=BoundsTree(low,high);_FACE_INDEX[id(shape)]=(shape,faces,tree,size,low,high)
    return faces,tree,size,low,high


def face_at(shape, normal, point, tol=1e-3, curved=False, face_hint=None):
    """Resolve an original CAD face using cached bounds and an optional display triangle hint.

    Hints are verified against exact geometry; approximate curved triangles fall
    back to the original distance/normal tie breaking among nearby faces.
    """
    n=np.asarray(normal,dtype=float);n=n/np.linalg.norm(n)
    vertex=cq.Vertex.makeVertex(*[float(x) for x in point]);pv=cq.Vector(*[float(x) for x in point])
    faces,tree,size,_,_=_face_index(shape)
    if face_hint is not None and 0<=face_hint<len(faces):
        face=faces[face_hint]
        if face.distance(vertex)<=tol:
            try:
                fn=np.asarray(face.normalAt(pv).toTuple());agree=abs(float(fn@n))
                planar=is_planar_face(face)
                if agree>=.95 and (planar or curved):
                    return face,np.asarray(face.normalAt().toTuple()) if planar else fn/np.linalg.norm(fn)
            except Exception:pass
    margin=max(.06,.01*size)
    near=sorted(((faces[i].distance(vertex),i,faces[i]) for i in tree.point(point,margin)),key=lambda t:(t[0],t[1]))
    if not near or near[0][0] > max(tol, 0.05, 0.01 * size):
        raise CadError("Wskazana ściana nie jest płaska.")
    limit = near[0][0] + max(tol, 1e-3, 1e-3 * size)
    best, score = None, -2.0
    for dist, _, face in near:
        if dist > limit:
            break
        try:
            fn = np.array(face.normalAt(cq.Vector(*[float(x) for x in point])).toTuple())
        except Exception:
            fn = np.array(face.normalAt().toTuple())
        agree = abs(float(fn @ n))
        if agree > score and is_planar_face(face):
            best, score = (face, np.array(face.normalAt().toTuple())), agree
    if best is None and curved:
        # ściana skręcona / zakrzywiona (np. wyciągnięcie złożone przez różne czworokąty): pracujemy na płaszczyźnie stycznej w klikniętym punkcie
        for dist, _, face in near:
            if dist > limit:
                break
            try:
                fn = np.array(face.normalAt(pv).toTuple(), float)
            except Exception:
                continue
            agree = abs(float(fn @ n))
            if agree > score:
                best, score = (face, fn / np.linalg.norm(fn)), agree
        if best is not None and score >= .8:
            return best
    if best is None or score < .95:
        raise CadError("Wskazana ściana nie jest płaska.")
    return best


def supporting_plane(face, point, normal_hint):
    """Płaszczyzna szkicu dla ściany skręconej / zakrzywionej: normalna dopasowana do całej ściany, a płaszczyzna przylega do niej od zewnątrz
    (przechodzi przez jej najbardziej wystający punkt). Dzięki temu wycięcie w głąb bryły przechodzi przez całą ścianę, a nie tylko jej część."""
    V = np.asarray(display_mesh(face).vertices, float)
    c = V.mean(axis=0)
    n = np.linalg.svd(V - c)[2][-1]
    if float(n @ np.asarray(normal_hint, float)) < 0:
        n = -n
    n = n / np.linalg.norm(n)
    off = float(((V - c) @ n).max())
    return tuple(float(x) for x in (c + n * off)), tuple(float(x) for x in n)


def edge_handle(shape, index):
    """Środek krawędzi i kierunek (do wnętrza bryły, po dwusiecznej ścian) - położenie strzałki zaokrąglenia / fazy."""
    edge = shape.Edges()[index]
    mid = edge.positionAt(.5)
    total = np.zeros(3)
    from OCP.TopoDS import TopoDS
    ancestors = _edge_faces(shape)
    key = ancestors.FindIndex(edge.wrapped)
    seen = []
    for f in (ancestors.FindFromIndex(key) if key else []):
        face = cq.Face(TopoDS.Face_s(f))
        if any(face.wrapped.IsSame(g.wrapped) for g in seen):
            continue
        seen.append(face)
        total += np.array(face.normalAt(mid).toTuple())
    n = np.linalg.norm(total)
    if n < 1e-6:
        t = np.array(edge.tangentAt(.5).toTuple())
        total = np.cross(t, (0, 0, 1.0) if abs(t[2]) < .9 else (1.0, 0, 0))
        n = np.linalg.norm(total)
    return mid.toTuple(), tuple(float(c) for c in -total / n)


# ---------- szkice łączą się jak w wersji HTML: obszary, przycinanie między przecięciami ----------
def _tolist(shapes):
    from OCP.TopTools import TopTools_ListOfShape
    lst = TopTools_ListOfShape()
    for s in shapes:
        lst.Append(s)
    return lst


def _fromlist(lst):
    return [s for s in lst]


def split_edges(edges):
    """General Fuse: dzieli krawędzie w punktach przecięcia. Zwraca dla każdej krawędzi wejściowej listę jej kawałków."""
    from OCP.BOPAlgo import BOPAlgo_Builder
    builder = BOPAlgo_Builder()
    for e in edges:
        builder.AddArgument(e.wrapped)
    builder.SetRunParallel(False)
    builder.Perform()
    if builder.HasErrors():
        raise CadError("Nie udało się połączyć szkiców.")
    out = []
    images = builder.Images()             # mapa obrazów: wielokrotnie szybsza niż Modified() dla każdej krawędzi
    for e in edges:
        pieces = [cq.Shape.cast(m) for m in images.Find(e.wrapped)] if images.IsBound(e.wrapped) else []
        pieces = [p for p in pieces if p.geomType() is not None and p.Length() > 1e-6]
        if pieces:
            out.append(pieces)
        elif builder.IsDeleted(e.wrapped):
            out.append([])
        else:
            out.append([e])
    return out


def _separate_wire_faces(edges,wires):
    """Skip General Fuse only for valid, complete, strictly separated closed wires."""
    from collections import Counter
    if not wires:return None
    parts=[w.Edges() for w in wires]
    if Counter(e.hashCode() for e in edges)!=Counter(e.hashCode() for part in parts for e in part):return None
    boxes=[bounds(w) for w in wires]
    low=np.array([[b.xmin,b.ymin,b.zmin] for b in boxes]);high=np.array([[b.xmax,b.ymax,b.zmax] for b in boxes])
    tree=BoundsTree(low,high)
    for i in range(len(wires)):
        if any(j!=i for j in tree.overlap(low[i],high[i],1e-6)):return None
    try:
        faces=[cq.Face.makeFromWires(w) for w in wires]
        return faces if all(w.IsClosed() and f.isValid() for w,f in zip(wires,faces)) else None
    except Exception:return None


def regions(plane, edges, wires=()):
    """Wszystkie obszary ograniczone krawędziami szkiców (jak 'region' w HTML): nakładające się kształty tną się nawzajem."""
    from OCP.BOPAlgo import BOPAlgo_BuilderFace
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pln, gp_Pnt
    if not edges:
        return []
    separate=_separate_wire_faces(edges,wires)
    if separate is not None:return separate
    unique, seen = [], set()
    for pieces in split_edges(edges):
        for p in pieces:
            if p not in seen:            # skrót + isSame (zamiast porównywania każdej z każdą - tysiące krawędzi z SVG)
                seen.add(p)
                unique.append(p)
    frame = frame_of(plane)
    pln = gp_Pln(gp_Ax3(gp_Pnt(*[float(c) for c in frame.origin]), gp_Dir(*[float(c) for c in frame.normal]), gp_Dir(*[float(c) for c in frame.xdir])))
    face = BRepBuilderAPI_MakeFace(pln, -1e4, 1e4, -1e4, 1e4).Face()
    builder = BOPAlgo_BuilderFace()
    builder.SetFace(face)
    both = [p.wrapped for p in unique] + [p.wrapped.Reversed() for p in unique]   # każda krawędź graniczy z dwoma obszarami
    builder.SetShapes(_tolist(both))
    builder.Perform()
    out = []
    for shape in ([] if builder.HasErrors() else _fromlist(builder.Areas())):
        f = cq.Shape.cast(shape)
        try:
            if 1e-6 < f.Area() < 1e7 and f.outerWire().IsClosed():
                out.append(f)
        except Exception:
            continue
    try:
        alt = _regions_from_wires(wires)
    except Exception:
        alt = []
    return alt if len(alt) > len(out) else out


def scale_matrix(factors, center):
    """Macierz 4x4 skalowania wokół punktu center (współczynniki X, Y, Z)."""
    f = np.asarray(factors, float)
    c = np.asarray(center, float)
    m = np.eye(4)
    m[:3, :3] = np.diag(f)
    m[:3, 3] = c - f * c
    return m


def scaled(shape, factors, center):
    """Kształt przeskalowany wokół center: jednakowo - dokładnie (łuki zostają łukami), różnie w osiach - przez
    przekształcenie ogólne (okrąg staje się elipsą)."""
    from OCP.gp import gp_Trsf, gp_GTrsf, gp_Pnt, gp_Mat, gp_XYZ
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform, BRepBuilderAPI_GTransform
    f = [float(v) for v in factors]
    if any(not isfinite(v) or v <= 0 for v in f):
        raise CadError('Skala musi być większa od zera.')
    c = [float(v) for v in center]
    if max(f) - min(f) < 1e-12:
        trsf = gp_Trsf()
        trsf.SetScale(gp_Pnt(*c), f[0])
        out = BRepBuilderAPI_Transform(shape.wrapped, trsf, True).Shape()
    else:
        g = gp_GTrsf()
        g.SetVectorialPart(gp_Mat(f[0], 0, 0, 0, f[1], 0, 0, 0, f[2]))
        g.SetTranslationPart(gp_XYZ(*(c[i] - f[i] * c[i] for i in range(3))))
        out = BRepBuilderAPI_GTransform(shape.wrapped, g, True).Shape()
    result = cq.Shape.cast(out)
    return valid(result, bool(shape.Solids())) if shape.Solids() else result


def mesh_moved(mesh, matrix):
    """Ta sama siatka po sztywnym przesunięciu / obrocie (macierz 4x4 albo 3x4) - bez ponownego liczenia z kształtu."""
    if mesh is None:
        return None
    m = np.asarray(matrix, float)
    r, t = m[:3, :3], m[:3, 3]
    move = lambda pts: np.asarray(pts, float) @ r.T + t if len(pts) else np.asarray(pts, float)
    centre = tuple(float(c) for c in r @ np.asarray(mesh.center, float) + t)
    return DisplayMesh(move(mesh.vertices).astype(np.asarray(mesh.vertices).dtype), mesh.triangles,
                       {k: move(v) for k, v in mesh.edges.items()}, centre, mesh.size, mesh.fine, mesh.face_ids)


def transformed(shape, rotation, translation):
    """Kształt obrócony macierzą 3x3 (bez skalowania) i przesunięty."""
    from OCP.gp import gp_Trsf
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    r = np.asarray(rotation, float)
    t = np.asarray(translation, float)
    trsf = gp_Trsf()
    trsf.SetValues(*[float(v) for v in (r[0, 0], r[0, 1], r[0, 2], t[0], r[1, 0], r[1, 1], r[1, 2], t[1], r[2, 0], r[2, 1], r[2, 2], t[2])])
    return cq.Shape.cast(BRepBuilderAPI_Transform(shape.wrapped, trsf, True).Shape())


def rotation_between(a, b):
    """Najmniejszy obrót przenoszący kierunek a na kierunek b (macierz 3x3)."""
    a = np.asarray(a, float) / max(np.linalg.norm(a), 1e-12)
    b = np.asarray(b, float) / max(np.linalg.norm(b), 1e-12)
    v, c = np.cross(a, b), float(a @ b)
    if c > 1 - 1e-12:
        return np.eye(3)
    if c < -1 + 1e-12:
        axis = np.cross(a, [1.0, 0, 0]) if abs(a[0]) < .9 else np.cross(a, [0, 1.0, 0])
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k / (1 + c)


def coplanar_faces(plane, solids, tol=1e-4):
    """Płaskie ściany brył leżące w płaszczyźnie szkicu (szkic narysowany na ścianie bryły)."""
    frame = frame_of(plane)
    n, o = np.array(frame.normal, float), np.array(frame.origin, float)
    out = []
    for solid in solids:
        try:
            box = solid.BoundingBox()
        except Exception:
            continue
        corners = np.array([[x, y, z] for x in (box.xmin, box.xmax) for y in (box.ymin, box.ymax) for z in (box.zmin, box.zmax)])
        side = (corners - o) @ n
        if side.min() > tol or side.max() < -tol:          # bryła w ogóle nie sięga płaszczyzny
            continue
        for face in solid.Faces():
            if face.geomType() != 'PLANE':
                continue
            fn = np.array(face.normalAt().toTuple(), float)
            if abs(abs(float(fn @ n)) - 1) > 1e-6:
                continue
            if abs(float((np.array(face.Center().toTuple()) - o) @ n)) > tol:
                continue
            out.append(face)
    return out


def split_by_faces(regions, faces):
    """Obszary szkicu podzielone obrysem ścian bryły, na której leży szkic: część na ścianie i część poza nią są osobnymi
    obszarami (każdą można wyciągnąć niezależnie). Obszary w całości na ścianie albo poza nią zostają bez zmian."""
    from OCP.BOPAlgo import BOPAlgo_Builder
    if not regions or not faces:
        return regions
    boundaries=[bounds(e) for face in faces for e in face.Edges()]
    tree=BoundsTree([[b.xmin,b.ymin,b.zmin] for b in boundaries],[[b.xmax,b.ymax,b.zmax] for b in boundaries])
    affected=set()
    for i,region in enumerate(regions):
        box=bounds(region)
        if not boundaries or tree.overlap([box.xmin,box.ymin,box.zmin],[box.xmax,box.ymax,box.zmax],1e-6):affected.add(i)
    if not affected:return regions
    builder = BOPAlgo_Builder()
    for f in [*[regions[i] for i in sorted(affected)], *faces]:
        builder.AddArgument(f.wrapped)
    builder.SetRunParallel(False)
    builder.SetFuzzyValue(1e-6)
    builder.Perform()
    if builder.HasErrors():
        return regions
    out = []
    for index,region in enumerate(regions):
        if index not in affected:
            out.append(region);continue
        pieces = []
        for piece in _fromlist(builder.Modified(region.wrapped)) or [region.wrapped]:
            f = cq.Face(piece) if piece.ShapeType() == 4 else None
            if f is not None and f.Area() > 1e-6 and not any(f.isSame(q) for q in pieces):
                pieces.append(f)
        out.extend(pieces or [region])
    return out


def _regions_from_wires(wires):
    """Obszary z zamkniętych konturów: ściany tną się nawzajem (General Fuse), więc część wspólna i reszty są osobnymi obszarami."""
    from OCP.BOPAlgo import BOPAlgo_Builder
    faces = []
    for w in wires:
        if w.IsClosed():
            try:
                faces.append(cq.Face.makeFromWires(w))
            except Exception:
                pass
    if not faces:
        return []
    builder = BOPAlgo_Builder()
    for f in faces:
        builder.AddArgument(f.wrapped)
    builder.SetRunParallel(False)
    builder.Perform()
    if builder.HasErrors():
        return []
    out, seen = [], set()
    for f in cq.Shape.cast(builder.Shape()).Faces():
        if f.Area() > 1e-6 and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def face_contains(face, point):
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON
    from OCP.gp import gp_Pnt
    try:
        return BRepClass_FaceClassifier(face.wrapped, gp_Pnt(*[float(c) for c in point]), 1e-5).State() in (TopAbs_IN, TopAbs_ON)
    except Exception:
        return face.distance(cq.Vertex.makeVertex(*[float(c) for c in point])) < 1e-5


def extrude_face(face, normal, d1, d2=0.0, symmetric=False):
    """Wyciągnięcie ściany / obszaru (z otworami) wzdłuż normalnej: d1 > 0 po normalnej, d1 < 0 przeciwnie."""
    d1, d2 = float(d1), float(d2)
    n = np.asarray(normal, dtype=float)
    n = n / np.linalg.norm(n)
    nv = cq.Vector(*[float(x) for x in n])
    shift, total = (-d1 / 2, d1) if symmetric else (-d2, d1 + d2)
    if not isfinite(total) or abs(total) < 1e-5:
        raise CadError("Odległość wyciągnięcia musi być różna od zera.")
    move = (lambda w: w.translate(nv.multiply(shift))) if shift else (lambda w: w)
    vec = nv.multiply(total)
    try:      # wyciągamy samą ścianę (jej powierzchnię), a nie nowo zbudowaną z konturów: ściany brył z przeciągnięcia mają krawędzie B-spline i taka przebudowa się nie udaje
        from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
        from OCP.gp import gp_Vec
        maker = BRepPrimAPI_MakePrism(move(face).wrapped, gp_Vec(vec.x, vec.y, vec.z), False, True)
        maker.Build()
        return valid(cq.Shape.cast(maker.Shape()))
    except Exception:
        return valid(cq.Solid.extrudeLinear(move(face.outerWire()), [move(w) for w in face.innerWires()], vec))


def revolve_face(face, point, direction, angle=360.0):
    """Obrót ściany / obszaru (z otworami) wokół osi (punkt, kierunek) o kąt w stopniach: bryła obrotowa (wałek, miska, gałka...)."""
    from math import radians
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt
    angle = float(angle)
    d = np.asarray(direction, dtype=float)
    p = np.asarray(point, dtype=float)
    if not isfinite(angle) or abs(angle) < 1e-6 or abs(angle) > 360 + 1e-6:
        raise CadError("Kąt obrotu musi mieścić się w zakresie 0-360°.")
    if not np.all(np.isfinite(d)) or float(np.linalg.norm(d)) < 1e-9:
        raise CadError("Nieprawidłowa oś obrotu.")
    d = d / np.linalg.norm(d)
    pts = [v.toTuple() for v in face.Vertices()]
    for edge in face.Edges():
        pts += [edge.positionAt(t).toTuple() for t in (.25, .5, .75)]
    pts = np.array(pts, dtype=float)
    normal = np.array(face.normalAt().toTuple(), dtype=float)
    side = np.cross(normal, d)
    if float(np.linalg.norm(side)) < 1e-6:
        raise CadError("Oś obrotu nie może być prostopadła do profilu.")
    side /= np.linalg.norm(side)
    dist = (pts - p) @ side
    if float(dist.max()) > 1e-4 and float(dist.min()) < -1e-4:
        raise CadError("Profil nie może przecinać osi obrotu - leży po obu jej stronach.")
    maker = BRepPrimAPI_MakeRevol(face.wrapped, gp_Ax1(gp_Pnt(*[float(c) for c in p]), gp_Dir(*[float(c) for c in d])), radians(abs(angle)) * (1 if angle > 0 else -1), True)
    maker.Build()
    return valid(cq.Shape.cast(maker.Shape()))


def shell_solid(shape, faces, thickness, inward=True):
    """Skorupa: bryła z ściankami o zadanej grubości; wskazane ściany zostają otwarte (bez nich bryła jest drążona w środku)."""
    t = float(thickness)
    if not isfinite(t) or t <= 1e-6:
        raise CadError("Grubość ścianki musi być większa od zera.")
    solids = shape.Solids()
    if len(solids) != 1:
        raise CadError("Skorupę można wykonać tylko na jednej bryle.")
    try:
        result = solids[0].shell(list(faces), -t if inward else t, kind='intersection')
    except Exception as exc:
        raise CadError("Nie udało się wykonać skorupy. Zmniejsz grubość ścianki albo zmień otwierane ściany.") from exc
    return valid(result)


def path_wire(shape):
    """Ścieżka (łamana, łuk, linia, krawędź) jako jeden drut."""
    edges = list(shape.Edges())
    if not edges:
        raise CadError("Ścieżka jest pusta.")
    try:
        return cq.Wire.assembleEdges(edges)
    except Exception as exc:
        raise CadError("Ścieżka musi być ciągłą linią (bez przerw).") from exc


def sweep_face(face, path, frenet=False):
    """Przeciągnięcie ściany / obszaru (z otworami) wzdłuż ścieżki: rura, prowadnica, uchwyt - przekrój stały."""
    wire = path_wire(path) if not isinstance(path, cq.Wire) else path
    error = None
    for mode in ('right', 'transformed', 'round'):      # ostre zagięcia dają różne wyniki zależnie od trybu przejścia; bierzemy pierwszy poprawny
        for frenet_now in ((bool(frenet),) if frenet else (False, True)):
            try:
                result = cq.Solid.sweep(face.outerWire(), face.innerWires(), wire, True, frenet_now, None, mode)
                if not result.wrapped.IsNull() and result.Solids() and result.Volume() < 0:      # odwrócona orientacja (profil zwrócony przeciwnie do ścieżki)
                    result = cq.Shape.cast(result.wrapped.Reversed())
                return valid(result)
            except Exception as exc:
                error = exc
    raise CadError("Nie udało się przeciągnąć profilu wzdłuż tej ścieżki. Profil powinien leżeć na początku ścieżki, prostopadle do niej.") from error


def _ordered_edges(wire):
    """Krawędzie drutu w kolejności obiegu, każda zorientowana zgodnie z obiegiem."""
    from OCP.BRepTools import BRepTools_WireExplorer
    explorer = BRepTools_WireExplorer(wire.wrapped)
    edges = []
    while explorer.More():
        edges.append(cq.Edge(explorer.Current()))
        explorer.Next()
    return edges


def _wire_points(wire):
    return [e.startPoint() for e in _ordered_edges(wire)]


def _wire_normal(points):
    n = np.zeros(3)
    for a, b in zip(points, points[1:] + points[:1]):
        n += np.cross([a.x, a.y, a.z], [b.x, b.y, b.z])
    return n


def align_profiles(wires):
    """Ujednolica profile do wyciągnięcia złożonego: ten sam kierunek obiegu i najbliższy sobie wierzchołek startowy.

    Dwa prostokąty narysowane od różnych rogów albo w przeciwnych kierunkach dawały skręconą bryłę z krzywymi ścianami."""
    try:
        out = [wires[0]]
        prev_pts = _wire_points(wires[0])
        ref = _wire_normal(prev_pts)
        for wire in wires[1:]:
            edges = _ordered_edges(wire)
            pts = [e.startPoint() for e in edges]
            if len(edges) < 2 or len(prev_pts) < 2:
                out.append(wire)
                continue
            if float(np.dot(_wire_normal(pts), ref)) < 0:
                edges = [cq.Edge(e.wrapped.Reversed()) for e in reversed(edges)]
                pts = [e.startPoint() for e in edges]
            c0 = np.mean([[p.x, p.y, p.z] for p in prev_pts], axis=0)
            c1 = np.mean([[p.x, p.y, p.z] for p in pts], axis=0)
            a0 = np.array([[p.x, p.y, p.z] for p in prev_pts]) - c0
            a1 = np.array([[p.x, p.y, p.z] for p in pts]) - c1
            ref_pt = a0[0]
            best = min(range(len(pts)), key=lambda i: float(np.linalg.norm(a1[i] / max(np.linalg.norm(a1[i]), 1e-9) - ref_pt / max(np.linalg.norm(ref_pt), 1e-9))))
            edges = edges[best:] + edges[:best]
            new = cq.Wire.assembleEdges(edges)
            out.append(new)
            prev_pts = _wire_points(new)
        return out
    except Exception:
        return list(wires)


def loft_wires(wires, point=None, ruled=False):
    """Wyciągnięcie złożone: gładka (albo prosta, ruled) bryła przez kolejne profile, opcjonalnie zbiegająca do punktu."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    if len(wires) + (1 if point is not None else 0) < 2:
        raise CadError("Wyciągnięcie złożone wymaga co najmniej dwóch profili albo profilu i punktu.")
    try:
        maker = BRepOffsetAPI_ThruSections(True, bool(ruled))
        for wire in align_profiles(list(wires)):
            maker.AddWire(wire.wrapped)
        if point is not None:
            maker.AddVertex(cq.Vertex.makeVertex(*[float(c) for c in point]).wrapped)
        maker.Build()
        result = cq.Shape.cast(maker.Shape())
    except Exception as exc:
        raise CadError("Nie udało się połączyć tych profili w bryłę. Profile muszą być zamknięte i różnić się położeniem.") from exc
    return valid(result)


def _chains(edges, tol=1e-4):
    """Układa krawędzie w łańcuchy (druty) według wspólnych końców."""
    key = lambda p: (round(p.x / tol), round(p.y / tol), round(p.z / tol))
    left, chains = list(edges), []
    while left:
        chain = [left.pop(0)]
        grown = True
        while grown:
            grown = False
            for e in list(left):
                a, b = key(e.startPoint()), key(e.endPoint())
                head, tail = key(chain[0].startPoint()), key(chain[-1].endPoint())
                if a == tail or b == tail:
                    chain.append(e if a == tail else cq.Edge(e.wrapped.Reversed()))
                elif a == head or b == head:
                    chain.insert(0, e if b == head else cq.Edge(e.wrapped.Reversed()))
                else:
                    continue
                left.remove(e)
                grown = True
        chains.append(chain)
    wires = []
    for chain in chains:
        try:
            wires.append(cq.Wire.assembleEdges(chain))
        except Exception:
            wires += [cq.Wire.assembleEdges([e]) for e in chain]
    return wires


def closed_groups(shapes_edges, tol=1e-4):
    """Grupy otwartych szkiców, które razem tworzą zamknięty obrys (np. po przycięciu nożyczkami dwóch nachodzących
    kształtów): każdy koniec spotyka dokładnie jeden inny koniec. Zwraca listy numerów szkiców (co najmniej dwóch)."""
    key = lambda p: (round(p.x / tol), round(p.y / tol), round(p.z / tol))

    def ends(edges):
        degree = {}
        for e in edges:
            if e.IsClosed():
                continue
            for p in (e.startPoint(), e.endPoint()):
                k = key(p)
                degree[k] = degree.get(k, 0) + 1
        return degree

    items = []
    for i, edges in enumerate(shapes_edges):
        degree = ends(edges)
        free = {k for k, d in degree.items() if d % 2}
        if free and edges:                      # tylko szkice otwarte (zamknięte są już osobnym obrysem)
            items.append((i, free, degree))
    parent = {i: i for i, _, _ in items}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner = {}
    for i, free, _ in items:
        for k in free:
            if k in owner:
                parent[find(i)] = find(owner[k])
            else:
                owner[k] = i
    groups = {}
    for i, _, _ in items:
        groups.setdefault(find(i), []).append(i)
    out = []
    for members in groups.values():
        if len(members) < 2:
            continue
        total = {}
        for i, _, degree in items:
            if i in members:
                for k, d in degree.items():
                    total[k] = total.get(k, 0) + d
        if all(d == 2 for d in total.values()):
            out.append(sorted(members))
    return out


def trim_pieces(bodies_edges, target):
    """Kawałki krawędzi szkicu `target` między punktami przecięcia z pozostałymi szkicami (lista krawędzi)."""
    flat, owner = [], []
    for i, edges in enumerate(bodies_edges):
        for e in edges:
            flat.append(e)
            owner.append(i)
    per = split_edges(flat)
    return [p for pieces, o in zip(per, owner) if o == target for p in pieces]


def trim_result(pieces, index):
    """Druty po usunięciu kawałka `index`."""
    rest = [p for i, p in enumerate(pieces) if i != index]
    return _chains(rest) if rest else []


# ---------------------------------------------------------------------------
# Wyciąganie ściany walcowej (ścianka otworu albo zewnętrzna powierzchnia walca): zmiana promienia o odległość
# ---------------------------------------------------------------------------
import math


def cylinder_info(face, shape=None):
    """Dane ściany walcowej: oś (punkt, kierunek), promień, zakres kąta i wysokości oraz strona materiału.
    outward = +1, gdy materiał jest wewnątrz promienia (zewnętrzna powierzchnia walca), -1 dla ścianki otworu."""
    if face.geomType() != 'CYLINDER':
        raise CadError("To nie jest ściana walcowa.")
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    ad = BRepAdaptor_Surface(face.wrapped)
    cyl = ad.Cylinder()
    ax = cyl.Axis()
    origin = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()], float)
    axis = np.array([ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()], float)
    xdir = np.array([cyl.XAxis().Direction().X(), cyl.XAxis().Direction().Y(), cyl.XAxis().Direction().Z()], float)
    radius = float(cyl.Radius())
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face.wrapped)
    yd = cyl.YAxis().Direction()
    if float(np.dot([yd.X(), yd.Y(), yd.Z()], np.cross(axis, xdir))) < 0:
        # układ walca lewoskrętny: odwrócona oś daje prawoskrętny (kąty u bez zmian, wysokość v zmienia znak)
        axis = -axis
        v0, v1 = -v1, -v0
    # strona materiału: punkt tuż poza promieniem w środku ściany
    um, vm = (u0 + u1) / 2, (v0 + v1) / 2
    ydir = np.cross(axis, xdir)
    radial = math.cos(um) * xdir + math.sin(um) * ydir
    on = origin + axis * vm + radial * radius
    outward = 1
    if shape is not None:
        eps = max(1e-3, radius * 1e-3)
        outward = 1 if point_state(shape, on - radial * eps) == 'in' else -1
    full = (u1 - u0) >= 2 * math.pi - 1e-6
    fillet = False
    if shape is not None and not full and (u1 - u0) < math.pi - 1e-3:
        fillet = _is_fillet(face, shape, origin, axis, xdir, ydir, radius, float(u0), float(u1), vm)
    return dict(origin=origin, axis=axis, xdir=xdir, radius=radius, u0=float(u0), u1=float(u1), v0=float(v0), v1=float(v1),
                outward=outward, full=full, fillet=fillet)


def _is_fillet(face, shape, origin, axis, xdir, ydir, radius, u0, u1, vm):
    """Wycinek walca styczny na obu brzegach do płaskich ścian (zaokrąglenie krawędzi, wypukłe albo wklęsłe)."""
    tol = max(1e-4, radius * 1e-4)
    for u in (u0, u1):
        radial = math.cos(u) * xdir + math.sin(u) * ydir
        p = origin + axis * vm + radial * radius
        vp = cq.Vertex.makeVertex(*[float(c) for c in p])
        ok = False
        for other in shape.Faces():
            if other.isSame(face) or other.geomType() != 'PLANE':
                continue
            try:
                if other.distance(vp) > tol:
                    continue
                n = np.asarray(other.normalAt(cq.Vector(*p)).toTuple(), float)
            except Exception:
                continue
            if abs(float(n @ radial)) > 1 - 1e-6:
                ok = True
                break
        if not ok:
            return False
    return True


def _fillet_corner(info, rho, h):
    """Obszar między narożnikiem stycznych płaszczyzn a łukiem zaokrąglenia o promieniu rho (bryła o wysokości h)."""
    if rho <= 1e-6:
        return None
    u0, u1, r = info['u0'], info['u1'], info['radius']
    half = (u1 - u0) / 2
    b = np.array([math.cos(u0 + half), math.sin(u0 + half)])
    K = b * r / math.cos(half)
    C = K - b * rho / math.cos(half)
    T1 = C + rho * np.array([math.cos(u0), math.sin(u0)])
    T2 = C + rho * np.array([math.cos(u1), math.sin(u1)])
    base = info['origin'] + info['axis'] * info['v0']
    plane = cq.Plane(origin=tuple(float(c) for c in base), xDir=tuple(float(c) for c in info['xdir']), normal=tuple(float(c) for c in info['axis']))
    wp = cq.Workplane(plane)
    kite = wp.polyline([tuple(map(float, q)) for q in (K, T1, C, T2)]).close().extrude(h).val()
    disc = wp.center(float(C[0]), float(C[1])).circle(rho).extrude(h).val()
    return kite.cut(disc)


def fillet_radius_after(info, distance):
    """Nowy promień zaokrąglenia, gdy środek jego łuku przesuwa się o distance wzdłuż normalnej (+ dodaje materiał)."""
    k = 1 / math.cos((info['u1'] - info['u0']) / 2) - 1
    return info['radius'] - info['outward'] * float(distance) / k


def cylinder_normal(info, point):
    """Normalna ściany walcowej w punkcie, skierowana od materiału na zewnątrz."""
    p = np.asarray(point, float) - info['origin']
    radial = p - float(p @ info['axis']) * info['axis']
    radial /= max(np.linalg.norm(radial), 1e-12)
    return radial * info['outward']


def cylinder_offset_tool(info, distance):
    """Pierścień (albo jego wycinek) między promieniem ściany a promieniem zmienionym o distance wzdłuż normalnej ściany:
    distance > 0 - materiał do dodania (walec grubszy, otwór mniejszy), distance < 0 - materiał do wycięcia
    (walec cieńszy, otwór większy). Wysokość i zakres kąta jak ściana."""
    d = float(distance)
    if not isfinite(d) or abs(d) < 1e-5:
        raise CadError("Odległość musi być różna od zera.")
    r = info['radius']
    if info.get('fillet'):
        return _fillet_offset_tool(info, d)
    new = r + info['outward'] * d
    lo, hi = min(r, new), max(r, new)
    if info['outward'] > 0 and new <= 1e-6:
        raise CadError(f"Walec ma promień {r:g} mm - nie da się zmniejszyć go o {abs(d):g} mm.")
    lo = max(lo, 0.0)
    h = info['v1'] - info['v0']
    if h <= 1e-6:
        raise CadError("Ściana walcowa ma zerową wysokość.")
    base = info['origin'] + info['axis'] * info['v0']
    plane = cq.Plane(origin=tuple(float(c) for c in base), xDir=tuple(float(c) for c in info['xdir']), normal=tuple(float(c) for c in info['axis']))
    wp = cq.Workplane(plane)
    ring = wp.circle(hi).extrude(h).val()
    if lo > 1e-6:
        ring = ring.cut(wp.circle(lo).extrude(h).val())
    if not info['full']:
        # wycinek kąta [u0, u1]: wielokąt-klin (z zapasem promienia) wyciągnięty na całą wysokość
        reach = hi * 2 + 1
        steps = max(2, int(math.ceil((info['u1'] - info['u0']) / (math.pi / 8))))
        pts = [(0.0, 0.0)] + [(reach * math.cos(info['u0'] + (info['u1'] - info['u0']) * k / steps),
                                reach * math.sin(info['u0'] + (info['u1'] - info['u0']) * k / steps)) for k in range(steps + 1)]
        wedge = wp.polyline(pts).close().extrude(h).val()
        ring = ring.intersect(wedge)
    return valid(ring.clean())


# ---------------------------------------------------------------------------
# ofset szkicu: kształt odsunięty o stałą odległość w płaszczyźnie szkicu
# ---------------------------------------------------------------------------
def _offset_wires_of(shape):
    wires = list(shape.Wires()) if hasattr(shape, 'Wires') else []
    if not wires:
        edges = list(shape.Edges())
        if not edges:
            raise CadError("Ten element szkicu nie ma linii do odsunięcia.")
        wires = [cq.Wire.assembleEdges(edges)]
    return wires


def _wire_area(wire):
    try:
        return abs(cq.Face.makeFromWires(wire).Area())
    except Exception:
        return 0.0


def _raw_offset(wire, plane, d):
    """Odsunięcie jednego obrysu o d (znak jak w OCCT). Położenie (Location) obrysu jest zdejmowane na czas liczenia
    i nakładane z powrotem na wynik - BRepOffsetAPI_MakeOffset nakłada je inaczej dwa razy (okrąg poza środkiem
    układu lądował w podwójnej odległości)."""
    from OCP.TopLoc import TopLoc_Location
    loc = wire.wrapped.Location()
    if loc.IsIdentity():
        return _raw_offset_bare(wire, plane, d)
    bare = cq.Wire(wire.wrapped.Located(TopLoc_Location()))
    return [cq.Wire(w.wrapped.Moved(loc)) for w in _raw_offset_bare(bare, plane, d)]


def _raw_offset_bare(wire, plane, d):
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
    from OCP.GeomAbs import GeomAbs_Intersection
    if wire.IsClosed():
        # przez ścianę: offset2D samego okręgu potrafi przenieść wynik na płaszczyznę XY
        face = cq.Face.makeFromWires(wire)
        maker = BRepOffsetAPI_MakeOffset(face.wrapped, GeomAbs_Intersection)
        maker.Perform(d)
        if not maker.IsDone():
            return []
        res = cq.Shape.cast(maker.Shape())
        return [w for w in (res.Wires() if hasattr(res, 'Wires') else []) if w.Length() > 1e-6]
    edges = wire.Edges()
    if len(edges) == 1 and edges[0].geomType() == 'LINE':
        # sama prosta nie wyznacza płaszczyzny - przesunięcie prostopadle w płaszczyźnie szkicu
        f = frame_of(plane)
        t = np.asarray(edges[0].tangentAt(0).toTuple(), float)
        n = np.cross(np.asarray(f.normal, float), t)
        n /= np.linalg.norm(n)
        return [wire.translate(cq.Vector(*(n * d)))]
    maker = BRepOffsetAPI_MakeOffset(wire.wrapped, GeomAbs_Intersection, True)
    maker.Perform(d)
    if not maker.IsDone():
        raise CadError("Nie udało się odsunąć tej linii.")
    res = cq.Shape.cast(maker.Shape())
    return [w for w in (res.Wires() if hasattr(res, 'Wires') else []) if w.Length() > 1e-6]


def _outside_sign(wire, plane):
    """Znak odsunięcia OCCT, który daje stronę „na zewnątrz”: dla zamkniętego obrysu większe pole, dla otwartej linii
    strona wypukła (dłuższa linia); dla pojedynczego odcinka - lewa strona względem kierunku rysowania."""
    size = max(wire.BoundingBox().DiagonalLength, 1e-3)
    probe = min(1.0, size * .02)
    try:
        if wire.IsClosed():
            a = sum(_wire_area(w) for w in _raw_offset(wire, plane, probe))
            return 1.0 if a >= _wire_area(wire) else -1.0
        plus = sum(w.Length() for w in _raw_offset(wire, plane, probe))
        minus = sum(w.Length() for w in _raw_offset(wire, plane, -probe))
        return 1.0 if plus >= minus - 1e-9 else -1.0
    except Exception:
        return 1.0


def sketch_offset(shape, plane, distance):
    """Obrysy szkicu odsunięte o distance: > 0 na zewnątrz, < 0 do wewnątrz (lista nowych obrysów)."""
    d = float(distance)
    if not isfinite(d) or abs(d) < 1e-6:
        raise CadError("Odległość ofsetu musi być większa od zera.")
    # liczone w lokalnym układzie płaszczyzny (XY): OCCT gubi położenie okręgu umieszczonego przez Location
    f = frame_of(plane)
    cp = cq.Plane(origin=tuple(float(c) for c in f.origin), xDir=tuple(float(c) for c in f.xdir), normal=tuple(float(c) for c in f.normal))
    local = shape.transformShape(cp.fG)
    return [w.transformShape(cp.rG) for w in _sketch_offset_xy(local, d)]


def _sketch_offset_xy(shape, d):
    plane = 'XY'
    out = []
    for wire in _offset_wires_of(shape):
        try:
            res = _raw_offset(wire, plane, _outside_sign(wire, plane) * d)
        except CadError:
            raise
        except Exception:
            res = []
        if not res:
            raise CadError(f"Ofset {abs(d):g} mm do wewnątrz jest większy niż sam kształt." if d < 0 else "Nie udało się odsunąć kształtu.")
        out.extend(res)
    return out


def offset_anchor(shape, plane, point):
    """Punkt na kształcie najbliżej point i jednostkowy kierunek w płaszczyźnie szkicu, w którym rośnie ofset „na zewnątrz”
    (do strzałki do przeciągania): od punktu do najbliższego miejsca kształtu odsuniętego o mały krok na zewnątrz."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    def nearest(sh, p):
        ext = BRepExtrema_DistShapeShape(sh.wrapped, cq.Vertex.makeVertex(*[float(c) for c in p]).wrapped)
        ext.Perform()
        return np.array(cq.Vector(ext.PointOnShape1(1)).toTuple(), float), ext.Value()

    wires = _offset_wires_of(shape)
    wire = min(wires, key=lambda w: nearest(w, point)[1])
    base = nearest(wire, point)[0]
    pn = np.asarray(frame_of(plane).normal, float)
    probe = min(1.0, max(wire.BoundingBox().DiagonalLength, 1e-3) * .02)
    n = None
    try:
        moved = sketch_offset(wire, plane, probe)
        q = min((nearest(w, base) for w in moved), key=lambda r: r[1])[0]
        n = q - base
        n -= pn * float(np.dot(n, pn))
    except CadError:
        pass
    if n is None or np.linalg.norm(n) < 1e-9:
        n = np.asarray(frame_of(plane).xdir, float)
    return base, n / np.linalg.norm(n)


def _fillet_offset_tool(info, d):
    """Zaokrąglenie krawędzi: zmienia się jego promień, a łuk zostaje styczny do sąsiednich ścian (nic nie wystaje).
    Wypukłe: dodanie materiału = mniejszy promień (do ostrego narożnika), wycięcie = większy. Wklęsłe odwrotnie."""
    r = info['radius']
    new = fillet_radius_after(info, d)
    if new < -max(1e-3, r * 1e-3):
        k = 1 / math.cos((info['u1'] - info['u0']) / 2) - 1
        limit = f'{r * k:.2f}'.replace('.', ',')
        raise CadError(f"Do zaokrąglenia R{r:g} można dodać najwyżej {limit} mm - wtedy narożnik jest ostry.")
    h = info['v1'] - info['v0']
    if h <= 1e-6:
        raise CadError("Ściana walcowa ma zerową wysokość.")
    lo, hi = min(r, max(new, 0.0)), max(r, new)
    big, small = _fillet_corner(info, hi, h), _fillet_corner(info, lo, h)
    tool = big.cut(small) if small is not None else big
    return valid(tool.clean())
