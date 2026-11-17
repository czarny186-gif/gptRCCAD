"""Różnica z siatką STL: bryła (BREP) minus kształt siatki STL - tylko w tę stronę (siatka nie jest bryłą matematyczną).
Siatka jest najpierw zamieniana w zamkniętą objętość (manifold3d: zamknięte części siatki, połączone), przycinana do obszaru
bryły, a potem:
- gdy przycięty kawałek ma rozsądną liczbę płaskich ścian (np. prosta część, wydruk) - zamieniany w bryłę z płaskich ścian
  i odejmowany zwykłą operacją logiczną: wynik zostaje bryłą (BREP);
- gdy jest bardzo złożony (setki tysięcy trójkątów, tysiące ścian) - odejmowanie liczy się na siatkach (szybko), a wynik
  jest siatką."""
from __future__ import annotations
import numpy as np
import cadquery as cq
from . import kernel
from .kernel import CadError

BREP_FACES = 1500          # do tylu płaskich ścian przycięty kawałek siatki staje się bryłą (powyżej - wynik siatką)
_VOLUMES = {}


def _manifold():
    try:
        import manifold3d
        return manifold3d
    except Exception as exc:              # pragma: no cover - zależy od instalacji
        raise CadError('Brak modułu operacji na siatkach (manifold3d).') from exc


def _components(tris, count):
    """Etykieta części spójnej (po wspólnych wierzchołkach) dla każdego trójkąta."""
    label = np.arange(count)
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    for _ in range(200):
        low = np.minimum(np.minimum(label[a], label[b]), label[c])
        nxt = label.copy()
        np.minimum.at(nxt, a, low)
        np.minimum.at(nxt, b, low)
        np.minimum.at(nxt, c, low)
        for _ in range(4):
            nxt = nxt[nxt]
        if np.array_equal(nxt, label):
            break
        label = nxt
    return label[a]


def mesh_volume(shape):
    """Zamknięta objętość siatki STL (manifold3d) - liczona raz na kształt. (objętość, liczba pominiętych otwartych części)."""
    hit = _VOLUMES.get(id(shape))
    if hit is not None and hit[0] is shape:
        return hit[1], hit[2]
    mf = _manifold()
    topo = kernel._mesh_topology(shape)
    v, t = topo['vertices'], topo['tris']
    parts, skipped = [], 0
    whole = mf.Mesh(vert_properties=v.astype(np.float32), tri_verts=t.astype(np.uint32))
    whole.merge()
    single = mf.Manifold(whole)
    if single.status() == mf.Error.NoError and single.num_tri():
        parts = [single]
    else:                                   # złożenie wielu części: każda zamknięta część osobno, potem suma
        comp = _components(t, len(v))
        ids, inverse = np.unique(comp, return_inverse=True)
        order = np.argsort(inverse, kind='stable')
        bounds = np.searchsorted(inverse[order], np.arange(len(ids) + 1))
        for k in range(len(ids)):
            tt = t[order[bounds[k]:bounds[k + 1]]]
            used, remap = np.unique(tt, return_inverse=True)
            mesh = mf.Mesh(vert_properties=v[used].astype(np.float32), tri_verts=remap.reshape(-1, 3).astype(np.uint32))
            mesh.merge()
            part = mf.Manifold(mesh)
            if part.status() != mf.Error.NoError or not part.num_tri():
                skipped += 1
                continue
            parts.append(part)
    if not parts:
        raise CadError('Siatka STL nie tworzy zamkniętej objętości (ma dziury) - nie da się nią wycinać.')
    volume = mf.Manifold.batch_boolean(parts, mf.OpType.Add) if len(parts) > 1 else parts[0]
    if len(_VOLUMES) > 4:
        _VOLUMES.clear()
    _VOLUMES[id(shape)] = (shape, volume, skipped)
    return volume, skipped


def _arrays(manifold):
    mesh = manifold.to_mesh()
    return np.asarray(mesh.vert_properties)[:, :3].astype(np.float64), np.asarray(mesh.tri_verts).astype(np.int64)


def _planar_groups(v, t):
    """Trójkąty pogrupowane w płaskie, spójne obszary: (etykieta obszaru dla każdego trójkąta, normalne)."""
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    n = np.cross(b - a, c - a)
    n /= np.maximum(np.linalg.norm(n, axis=1), 1e-18)[:, None]
    scale = max(float(np.ptp(v, axis=0).max()), 1.0)
    key = np.c_[np.round(n * 2e3), np.round((n * a).sum(1) / (scale * 2e-5))].astype(np.int64)
    _, plane = np.unique(key, axis=0, return_inverse=True)
    # obszary spójne w obrębie płaszczyzny (po wspólnej krawędzi)
    count = len(t)
    edges = np.sort(np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]), axis=1)
    owner = np.tile(np.arange(count), 3)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    e, o = edges[order], owner[order]
    same = np.zeros(len(e), bool)
    same[1:] = (e[1:] == e[:-1]).all(axis=1)
    k = np.flatnonzero(same)
    p, q = o[k - 1], o[k]
    keep = plane[p] == plane[q]
    p, q = p[keep], q[keep]
    label = np.arange(count)
    for _ in range(400):
        low = np.minimum(label[p], label[q])
        nxt = label.copy()
        np.minimum.at(nxt, p, low)
        np.minimum.at(nxt, q, low)
        for _ in range(4):
            nxt = nxt[nxt]
        if np.array_equal(nxt, label):
            break
        label = nxt
    return label, n


def _loops(v, tris):
    """Obwody brzegu obszaru (krawędzie w jednym trójkącie obszaru, kierunek zgodny z trójkątami)."""
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    key = np.sort(edges, axis=1)
    _, inverse, counts = np.unique(key[:, 0] * (len(v) + 1) + key[:, 1], return_inverse=True, return_counts=True)
    border = edges[counts[inverse] == 1]
    nxt = {}
    for p, q in border.tolist():
        nxt.setdefault(p, []).append(q)
    loops, used = [], set()
    for start in list(nxt):
        for first in nxt[start]:
            if (start, first) in used:
                continue
            loop, prev, cur = [start], start, first
            used.add((start, first))
            while cur != start and len(loop) <= len(border):
                loop.append(cur)
                options = [x for x in nxt.get(cur, []) if (cur, x) not in used]
                if not options:
                    break
                prev, cur = cur, options[0]
                used.add((prev, cur))
            if cur == start and len(loop) >= 3:
                loops.append(loop)
    return loops


def _solid_from_mesh(v, t, limit=None):
    """Bryła z zamkniętej siatki: płaskie obszary jako ściany (wielokąty z otworami), zszyte w skorupę. None, gdy ścian
    byłoby więcej niż limit albo zszycie się nie uda."""
    label, normals = _planar_groups(v, t)
    groups, inverse = np.unique(label, return_inverse=True)
    if len(groups) > (BREP_FACES if limit is None else limit):
        return None
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid
    from OCP.TopoDS import TopoDS
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    sew = BRepBuilderAPI_Sewing(1e-6 * max(float(np.ptp(v, axis=0).max()), 1.0))
    order = np.argsort(inverse, kind='stable')
    bounds = np.searchsorted(inverse[order], np.arange(len(groups) + 1))
    for k in range(len(groups)):
        members = order[bounds[k]:bounds[k + 1]]
        n = normals[members[0]]
        x = np.cross(n, [0, 0, 1.0] if abs(n[2]) < .9 else [1.0, 0, 0])
        x /= np.linalg.norm(x)
        y = np.cross(n, x)
        wires = []
        for loop in _loops(v, t[members]):
            pts = v[loop]
            keep = [pts[i] for i in range(len(pts))
                    if np.linalg.norm(np.cross(pts[i] - pts[i - 1], pts[(i + 1) % len(pts)] - pts[i])) > 1e-12]
            pts = np.asarray(keep if len(keep) >= 3 else pts)
            uv = np.stack([pts @ x, pts @ y], axis=1)
            area = 0.5 * abs(float(np.sum(uv[:, 0] * np.roll(uv[:, 1], -1) - np.roll(uv[:, 0], -1) * uv[:, 1])))
            wires.append((area, cq.Wire.makePolygon([cq.Vector(*map(float, p)) for p in pts], close=True)))
        if not wires:
            return None
        wires.sort(key=lambda w: -w[0])
        try:
            face = cq.Face.makeFromWires(wires[0][1], [w for _, w in wires[1:]])
        except Exception:
            return None
        sew.Add(face.wrapped)
    sew.Perform()
    sewed = sew.SewedShape()
    explorer = TopExp_Explorer(sewed, TopAbs_SHELL)
    maker = BRepBuilderAPI_MakeSolid()
    shells = 0
    while explorer.More():
        maker.Add(TopoDS.Shell_s(explorer.Current()))
        shells += 1
        explorer.Next()
    if not shells:
        return None
    solid = cq.Shape.cast(maker.Solid()).fix()
    if not kernel.is_valid(solid) or not solid.Solids():
        return None
    if solid.Volume() < 0:
        solid = cq.Shape.cast(solid.wrapped.Reversed())
    return solid


def subtract(target, mesh_shape):
    """Bryła target minus kształt siatki STL. Zwraca (kształt, 'solid' | 'mesh', liczba pominiętych otwartych części siatki)."""
    mf = _manifold()
    volume, skipped = mesh_volume(mesh_shape)
    box = kernel.bounds(target)
    margin = max(1e-3, 1e-3 * max(box.xlen, box.ylen, box.zlen))
    crop = mf.Manifold.cube([box.xlen + 2 * margin, box.ylen + 2 * margin, box.zlen + 2 * margin]).translate(
        [box.xmin - margin, box.ymin - margin, box.zmin - margin])
    tool = volume ^ crop
    if tool.is_empty() or tool.volume() < 1e-9:
        raise CadError('Siatka STL nie wchodzi w tę bryłę - nie ma czego wyciąć.')
    v, t = _arrays(tool)
    solid = _solid_from_mesh(v, t)
    if solid is not None:
        result = kernel.boolean('subtract', target, [solid])
        return result, 'solid', skipped
    # bardzo złożony kawałek siatki: odejmowanie na siatkach, wynik jest siatką
    mesh = kernel.display_mesh(target, .05)
    tv, tt = np.asarray(mesh.vertices, np.float32), np.asarray(mesh.triangles, np.uint32)
    tm = mf.Mesh(vert_properties=tv, tri_verts=tt)
    tm.merge()
    body = mf.Manifold(tm)
    if body.status() != mf.Error.NoError:
        raise CadError('Nie udało się przygotować bryły do odejmowania siatki.')
    rv, rt = _arrays(body - tool)
    if not len(rt):
        raise CadError('Po wycięciu nic nie zostało z bryły.')
    return triangles_shape(rv, rt), 'mesh', skipped


def triangles_shape(vertices, triangles):
    """Kształt-siatka (jedna ściana z gotową siatką trójkątów, jak import STL) z tablic wierzchołków i trójkątów."""
    from OCP.Poly import Poly_Triangulation, Poly_Triangle
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.Poly import Poly_Array1OfTriangle
    from OCP.gp import gp_Pnt
    from OCP.TopoDS import TopoDS_Face
    from OCP.BRep import BRep_Builder
    nodes = TColgp_Array1OfPnt(1, len(vertices))
    for i, p in enumerate(np.asarray(vertices, float).tolist(), 1):
        nodes.SetValue(i, gp_Pnt(*p))
    tris = Poly_Array1OfTriangle(1, len(triangles))
    for i, (a, b, c) in enumerate(np.asarray(triangles, int).tolist(), 1):
        tris.SetValue(i, Poly_Triangle(a + 1, b + 1, c + 1))
    face = TopoDS_Face()
    BRep_Builder().MakeFace(face, Poly_Triangulation(nodes, tris))
    return cq.Shape.cast(face)
