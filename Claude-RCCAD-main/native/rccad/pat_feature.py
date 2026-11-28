"""Elementy bryły do szyku: wycięcia, kieszenie, otwory (przelotowe i nieprzelotowe) oraz wypukłości (czopy, żebra, kołnierze)
rozpoznawane z samej geometrii B-Rep - niezależnie od tego, jaką operacją powstały (wyciągnięcie, wycięcie, otwór, obrót).

Rozpoznanie: od klikniętej ściany rośnie obszar ścian połączonych krawędziami wklęsłymi (kieszeń / otwór) albo wypukłymi
(wypukłość). Granica obszaru zamyka się płaskimi „wiekami”, więc powstaje bryła elementu:
  * wycięcie  - objętość usunięta z bryły (np. walec otworu),
  * wypukłość - objętość dodana do bryły (np. czop).
Szyk powiela taką bryłę elementu, a wynik albo łączy się z bryłą (odejmowanie / dodawanie), albo zostaje osobnymi obiektami.
"""
from __future__ import annotations

import base64
import zlib

import cadquery as cq
import numpy as np

from . import kernel

SMOOTH = 0.02          # |sin| kąta między ścianami poniżej progu: krawędź gładka (styczna)
MAX_SHARE = 0.6        # element większy niż tyle objętości bryły nie jest elementem, tylko samą bryłą
_ADJ = {}


class FeatureError(kernel.CadError):
    pass


def _adjacency(shape):
    """Ściany bryły i ich sąsiedztwo przez krawędzie: (ściany, {indeks: [(krawędź, indeks sąsiada)]}), liczone raz na kształt."""
    hit = _ADJ.get(id(shape))
    if hit is not None and hit[0] is shape:
        return hit[1], hit[2], hit[3]
    from OCP.TopoDS import TopoDS
    data = kernel._edge_faces(shape)
    faces = shape.Faces()
    index = {}
    for i, f in enumerate(faces):
        index.setdefault(f.hashCode(), []).append(i)

    def find(face):
        for i in index.get(face.hashCode(), ()):
            if faces[i].wrapped.IsSame(face.wrapped):
                return i
        return None

    adj = {i: [] for i in range(len(faces))}
    for k in range(1, data.Extent() + 1):
        edge = cq.Edge(TopoDS.Edge_s(data.FindKey(k)))
        owners = []
        for f in data.FindFromIndex(k):
            i = find(cq.Face(TopoDS.Face_s(f)))
            if i is not None and i not in owners:
                owners.append(i)
        if len(owners) == 2:
            a, b = owners
            adj[a].append((edge, b))
            adj[b].append((edge, a))
    if len(_ADJ) > 6:
        _ADJ.clear()
    _ADJ[id(shape)] = (shape, faces, adj, find)
    return faces, adj, find


def _classify(f1, f2, edge, scale):
    """'convex' / 'concave' / 'smooth' dla krawędzi między dwiema ścianami (normalne na zewnątrz bryły)."""
    p = edge.positionAt(.5)
    n1 = np.array(f1.normalAt(p).toTuple(), float)
    n2 = np.array(f2.normalAt(p).toTuple(), float)
    t = np.array(edge.tangentAt(.5).toTuple(), float)
    d = np.cross(n2, t)
    norm = np.linalg.norm(d)
    if norm < 1e-12:
        return 'smooth'
    d /= norm
    eps = max(1e-4, 1e-3 * scale)
    pp = np.array(p.toTuple(), float)
    best = None
    for sign in (1.0, -1.0):
        q = cq.Vertex.makeVertex(*[float(c) for c in pp + sign * eps * d])
        dist = f2.distance(q)
        if best is None or dist < best[0]:
            best = (dist, sign)
    s = float(n1 @ (best[1] * d))
    if abs(s) < SMOOTH:
        return 'smooth'
    return 'convex' if s < 0 else 'concave'


_KIND = {}


def _kind(face):
    """'flat' (płaska), 'convex' (wypukła, np. zewnętrzny walec / zaokrąglenie krawędzi) albo 'concave' (wklęsła, np. ścianka otworu)."""
    key = face.hashCode()
    hit = _KIND.get(key)
    if hit is not None and hit[0].wrapped.IsSame(face.wrapped):
        return hit[1]
    from OCP.BRep import BRep_Tool
    from OCP.BRepTools import BRepTools
    from OCP.GeomLProp import GeomLProp_SLProps
    from OCP.TopAbs import TopAbs_REVERSED
    kind = 'flat'
    if face.geomType() != 'PLANE':
        try:
            u0, u1, v0, v1 = BRepTools.UVBounds_s(face.wrapped)
            pr = GeomLProp_SLProps(BRep_Tool.Surface_s(face.wrapped), (u0 + u1) / 2, (v0 + v1) / 2, 2, 1e-7)
            h = pr.MeanCurvature() if pr.IsCurvatureDefined() else 0.0
            if face.wrapped.Orientation() == TopAbs_REVERSED:
                h = -h
            kind = 'flat' if abs(h) < 1e-9 else ('convex' if h < 0 else 'concave')
        except Exception:
            kind = 'flat'
    if len(_KIND) > 20000:
        _KIND.clear()
    _KIND[key] = (face, kind)
    return kind


def _grow(shape, start, mode):
    """Obszar ścian elementu. mode 'cut': krawędzie wklęsłe (otwór, kieszeń), 'add': wypukłe (czop, żebro).
    Zaokrąglenia: gładkie przejście wchodzi w ścianę zakrzywioną; do ściany płaskiej (dno, góra) tylko ze ściany zakrzywionej
    własnego rodzaju (np. zaokrąglony obrzeże kieszeni); zaokrąglenie przeciwnego rodzaju (np. promień u podstawy czopa) wchodzi do elementu,
    ale na nim obszar się kończy - dalej jest już podstawa."""
    faces, adj, _ = _adjacency(shape)
    box = kernel.bounds(shape)
    scale = max(box.xlen, box.ylen, box.zlen, 1e-6)
    main = 'concave' if mode == 'cut' else 'convex'
    mine = 'concave' if mode == 'cut' else 'convex'
    region, terminal, queue = {start}, set(), [start]
    while queue:
        i = queue.pop()
        if i in terminal:
            continue
        ta = _kind(faces[i])
        for edge, j in adj[i]:
            if j in region:
                continue
            cls = _classify(faces[i], faces[j], edge, scale)
            tx = _kind(faces[j])
            if cls == 'smooth':
                if tx == 'flat':
                    ok = ta in (mine, 'flat')
                else:
                    ok = True
                    if tx != mine:
                        terminal.add(j)
            else:
                ok = cls == main
            if ok:
                region.add(j)
                queue.append(j)
            if len(region) > 4000:
                raise FeatureError('Element jest zbyt rozbudowany, aby go rozpoznać.')
    return region


def _boundary(shape, region):
    """Krawędzie granicy obszaru razem ze ścianą po drugiej stronie: [(krawędź, ściana)]."""
    faces, adj, _ = _adjacency(shape)
    out = []
    for i in region:
        for edge, j in adj[i]:
            if j in region:
                continue
            if any(edge.wrapped.IsSame(e.wrapped) for e, _f in out):
                continue
            out.append((edge, faces[j]))
    return out


def _surface_cap(wire, outside):
    """Wieko leżące na powierzchni sąsiedniej ściany (np. na walcu, gdy element siedzi na walcu)."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.ShapeFix import ShapeFix_Face
    from OCP.TopoDS import TopoDS
    mk = BRepBuilderAPI_MakeFace(BRep_Tool.Surface_s(outside.wrapped), wire.wrapped, True)
    if not mk.IsDone():
        raise FeatureError('Nie udało się domknąć elementu na zakrzywionej powierzchni.')
    fix = ShapeFix_Face(mk.Face())
    fix.Perform()
    return cq.Face(TopoDS.Face_s(fix.Face()))


def _caps(boundary):
    """„Wieka” zamykające granicę obszaru: jedno na każdą zamkniętą pętlę krawędzi - płaskie albo na powierzchni sąsiedniej ściany."""
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
    from OCP.TopTools import TopTools_HSequenceOfShape
    from OCP.TopoDS import TopoDS
    seq = TopTools_HSequenceOfShape()
    for e, _f in boundary:
        seq.Append(e.wrapped)
    wires = TopTools_HSequenceOfShape()
    ShapeAnalysis_FreeBounds.ConnectEdgesToWires_s(seq, 1e-5, False, wires)
    caps = []
    for k in range(1, wires.Length() + 1):
        wire = cq.Wire(TopoDS.Wire_s(wires.Value(k)))
        if not wire.IsClosed():
            raise FeatureError('Granica elementu nie jest zamknięta - nie da się jej domknąć.')
        first = wire.Edges()[0]
        outside = next(f for e, f in boundary if e.wrapped.IsSame(first.wrapped))
        wire = wire.copy()       # głęboka kopia: budowa wieka dopisuje krzywe 2D i nie może zmienić krawędzi bryły
        try:
            if outside.geomType() == 'PLANE':
                caps.append(cq.Face.makeFromWires(wire))
            else:
                caps.append(_surface_cap(wire, outside))
        except FeatureError:
            raise
        except Exception as exc:
            raise FeatureError('Nie udało się domknąć granicy elementu.') from exc
    return caps


def _solid_from(faces):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    sew = BRepBuilderAPI_Sewing(1e-4)
    for f in faces:
        sew.Add(f.wrapped)
    sew.Perform()
    ex = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
    if not ex.More():
        raise FeatureError('Nie udało się zszyć ścian elementu.')
    shell = TopoDS.Shell_s(ex.Current())
    mk = BRepBuilderAPI_MakeSolid(shell)
    fix = ShapeFix_Solid(mk.Solid())
    fix.Perform()
    solid = cq.Solid(TopoDS.Solid_s(fix.Solid()))
    if solid.Volume() < 0:
        solid = cq.Solid(TopoDS.Solid_s(solid.wrapped.Reversed()))
    return solid


def _state(shape, point):
    """Położenie punktu względem bryły; kompozyt (wynik Boolean) klasyfikuje się po jego bryłach - klasyfikator na kompozycie bywa błędny."""
    states = [kernel.point_state(sol, point, 1e-6) for sol in (shape.Solids() or [shape])]
    return 'in' if 'in' in states else ('on' if 'on' in states else 'out')


def _inside_host(host, tool, samples=7):
    """True, gdy wnętrze bryły elementu leży w bryle (wypukłość), False - poza nią (wycięcie), None - niejednoznacznie."""
    box = kernel.bounds(tool)
    low = np.array([box.xmin, box.ymin, box.zmin])
    high = np.array([box.xmax, box.ymax, box.zmax])
    rng = np.random.default_rng(7)
    votes = []
    tries = 0
    while len(votes) < samples and tries < 400:
        tries += 1
        point = low + rng.random(3) * (high - low)
        if _state(tool, point) != 'in':
            continue
        state = _state(host, point)
        if state != 'on':
            votes.append(state == 'in')
    if len(votes) < 3:
        return None
    share = sum(votes) / len(votes)
    return True if share > .8 else (False if share < .2 else None)


def _host_axis(boundary):
    """Oś walca, na którym siedzi element (granica leży na ścianie walcowej): ((x, y, z), (dx, dy, dz)) albo None."""
    from OCP.BRep import BRep_Tool
    from OCP.Geom import Geom_CylindricalSurface
    for _e, outside in boundary:
        if outside.geomType() != 'CYLINDER':
            continue
        try:
            surf = Geom_CylindricalSurface.DownCast_s(BRep_Tool.Surface_s(outside.wrapped))
            ax = surf.Position().Axis()
            return ((ax.Location().X(), ax.Location().Y(), ax.Location().Z()), (ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()))
        except Exception:
            continue
    return None


def _candidate(shape, start, kind):
    region = _grow(shape, start, kind)
    faces, _, _ = _adjacency(shape)
    if len(region) >= len(faces):
        return None
    edges = _boundary(shape, region)
    if not edges:
        return None
    try:
        tool = _solid_from([faces[i].copy() for i in sorted(region)] + [c.copy() for c in _caps(edges)])   # kopie: zszywanie nie może zmienić bryły
        tool = kernel.valid(tool)
    except kernel.CadError:
        return None
    inside = _inside_host(shape, tool)
    if inside is None or inside != (kind == 'add'):
        return None             # wypukłość leży w bryle, wycięcie jest pustką poza nią - inaczej to nie ten rodzaj elementu
    return dict(kind=kind, tool=tool, faces=sorted(region), volume=float(tool.Volume()), axis=_host_axis(edges))


def feature_from_face(shape, face):
    """Element bryły, do którego należy ściana: {'kind': 'cut' | 'add', 'tool': bryła, 'faces': [...], 'volume': ...}."""
    faces, _, find = _adjacency(shape)
    start = find(face)
    if start is None:
        raise FeatureError('Nie znaleziono wskazanej ściany w bryle.')
    total = float(shape.Volume())
    found = []
    for kind in ('cut', 'add'):
        try:
            c = _candidate(shape, start, kind)
        except FeatureError:
            c = None
        if c is not None and 1e-9 < c['volume'] < MAX_SHARE * total:
            found.append(c)
    if not found:
        raise FeatureError('Nie rozpoznano elementu na tej ścianie. Kliknij ścianę wycięcia, otworu albo wypukłości '
                           '(element z zaokrągleniem u podstawy lub na obrzeżu może nie zostać rozpoznany).')
    return min(found, key=lambda c: c['volume'])


# ---------- zapis w przepisie ----------
def pack(shape):
    return base64.b64encode(zlib.compress(kernel._brep_bytes(shape), 9)).decode('ascii')


def unpack(text):
    return kernel._from_brep(zlib.decompress(base64.b64decode(text)))
