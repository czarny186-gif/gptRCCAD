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


def _grow(shape, start, allow):
    faces, adj, _ = _adjacency(shape)
    scale = max(kernel.bounds(shape).xlen, kernel.bounds(shape).ylen, kernel.bounds(shape).zlen, 1e-6)
    region, queue = {start}, [start]
    while queue:
        i = queue.pop()
        for edge, j in adj[i]:
            if j in region:
                continue
            if _classify(faces[i], faces[j], edge, scale) in allow:
                region.add(j)
                queue.append(j)
            if len(region) > 4000:
                raise FeatureError('Element jest zbyt rozbudowany, aby go rozpoznać.')
    return region


def _boundary(shape, region):
    faces, adj, _ = _adjacency(shape)
    out, seen = [], []
    for i in region:
        for edge, j in adj[i]:
            if j in region:
                continue
            if any(edge.wrapped.IsSame(e.wrapped) for e in seen):
                continue
            seen.append(edge)
            out.append(edge)
    return out


def _caps(edges):
    """Płaskie „wieka” zamykające granicę obszaru: jedno na każdą zamkniętą pętlę krawędzi."""
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
    from OCP.TopTools import TopTools_HSequenceOfShape
    from OCP.TopoDS import TopoDS
    seq = TopTools_HSequenceOfShape()
    for e in edges:
        seq.Append(e.wrapped)
    wires = TopTools_HSequenceOfShape()
    ShapeAnalysis_FreeBounds.ConnectEdgesToWires_s(seq, 1e-5, False, wires)
    caps = []
    for k in range(1, wires.Length() + 1):
        wire = cq.Wire(TopoDS.Wire_s(wires.Value(k)))
        if not wire.IsClosed():
            raise FeatureError('Granica elementu nie jest zamknięta - nie da się jej domknąć.')
        pts = np.array([v.toTuple() for v in wire.Vertices()], float)
        if len(pts) > 3:
            c = pts - pts.mean(axis=0)
            if np.linalg.svd(c, compute_uv=False)[-1] > 1e-3 * max(np.ptp(pts, axis=0).max(), 1e-6):
                # węzły nie leżą w jednej płaszczyźnie: obwód nieplanarny (np. element na walcu) - nie domykamy
                raise FeatureError('Element ma nieplanarną granicę (np. leży na powierzchni walcowej) - nie można go powielić jako bryły.')
        try:
            cap = cq.Face.makeFromWires(wire)
        except Exception as exc:
            raise FeatureError('Nie udało się domknąć granicy elementu płaską ścianą.') from exc
        caps.append(cap)
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
        if kernel.point_state(tool, point, 1e-6) != 'in':
            continue
        state = kernel.point_state(host, point, 1e-6)
        if state != 'on':
            votes.append(state == 'in')
    if len(votes) < 3:
        return None
    share = sum(votes) / len(votes)
    return True if share > .8 else (False if share < .2 else None)


def _candidate(shape, start, allow, kind):
    region = _grow(shape, start, allow)
    faces, _, _ = _adjacency(shape)
    if len(region) >= len(faces):
        return None
    edges = _boundary(shape, region)
    if not edges:
        return None
    try:
        tool = _solid_from([faces[i] for i in sorted(region)] + _caps(edges))
        tool = kernel.valid(tool)
    except kernel.CadError:
        return None
    inside = _inside_host(shape, tool)
    if inside is None or inside != (kind == 'add'):
        return None             # wypukłość leży w bryle, wycięcie jest pustką poza nią - inaczej to nie ten rodzaj elementu
    return dict(kind=kind, tool=tool, faces=sorted(region), volume=float(tool.Volume()))


def feature_from_face(shape, face):
    """Element bryły, do którego należy ściana: {'kind': 'cut' | 'add', 'tool': bryła, 'faces': [...], 'volume': ...}."""
    faces, _, find = _adjacency(shape)
    start = find(face)
    if start is None:
        raise FeatureError('Nie znaleziono wskazanej ściany w bryle.')
    total = float(shape.Volume())
    found = []
    for allow, kind in ((('concave', 'smooth'), 'cut'), (('convex', 'smooth'), 'add')):
        try:
            c = _candidate(shape, start, allow, kind)
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
