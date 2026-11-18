"""Różnica z siatką STL: bryła (BREP) minus kształt siatki STL - tylko w tę stronę (siatka nie jest bryłą matematyczną).
Wynik zawsze zostaje bryłą matematyczną (BREP), na której działają wszystkie operacje programu.
Siatka jest zamieniana w zamkniętą objętość (manifold3d: zamknięte części siatki, połączone) i przycinana do kształtu bryły
poszerzonego minimalnie na zewnątrz (o ok. 0,05 mm) - zostaje tylko to, co naprawdę wchodzi w bryłę (zwykle tysiące, a nie
setki tysięcy trójkątów), a jej ściany nie leżą dokładnie na ścianach bryły. Kształt jest upraszczany z dokładnością 0,05 mm,
budowany od razu jako bryła z płaskich ścian (bez zszywania) i odejmowany operacją logiczną (równolegle). Podgląd liczony
samą operacją na siatkach (ułamek sekundy), a gotowy wynik zapamiętany - Zastosuj nie liczy drugi raz."""
from __future__ import annotations
import numpy as np
import cadquery as cq
from . import kernel
from .kernel import CadError

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


MAX_TRIANGLES = 120000        # tyle trójkątów siatki może wchodzić w bryłę (więcej - komunikat zamiast bardzo długiego liczenia)


def _target_volume(target):
    mf = _manifold()
    mesh = kernel.display_mesh(target, .05)
    data = mf.Mesh(vert_properties=np.asarray(mesh.vertices, np.float32), tri_verts=np.asarray(mesh.triangles, np.uint32))
    data.merge()
    body = mf.Manifold(data)
    if body.status() != mf.Error.NoError or not body.num_tri():
        raise CadError('Nie udało się przygotować bryły do wycinania siatką.')
    return body


def _triangle_solid(v, t):
    """Bryła z zamkniętej siatki: każdy trójkąt ścianą, zszyte w skorupę; ściany w jednej płaszczyźnie połączone (dokładnie)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeSolid
    from OCP.gp import gp_Pnt
    from OCP.TopoDS import TopoDS
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    sew = BRepBuilderAPI_Sewing(1e-6 * max(float(np.ptp(v, axis=0).max()), 1.0))
    points = [gp_Pnt(*p) for p in np.asarray(v, float).tolist()]
    for a, b, c in np.asarray(t, int).tolist():
        if a == b or b == c or a == c:
            continue
        polygon = BRepBuilderAPI_MakePolygon(points[a], points[b], points[c], True)
        if not polygon.IsDone():
            continue
        face = BRepBuilderAPI_MakeFace(polygon.Wire(), True)
        if face.IsDone():
            sew.Add(face.Face())
    sew.Perform()
    explorer = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
    maker = BRepBuilderAPI_MakeSolid()
    shells = 0
    while explorer.More():
        maker.Add(TopoDS.Shell_s(explorer.Current()))
        shells += 1
        explorer.Next()
    if not shells:
        raise CadError('Nie udało się zamienić siatki STL w bryłę.')
    solid = cq.Shape.cast(maker.Solid()).fix()
    try:
        solid = solid.clean()
    except Exception:
        pass
    if not kernel.is_valid(solid):
        raise CadError('Nie udało się zamienić siatki STL w poprawną bryłę.')
    return solid


SIMPLIFY_TOL = .05           # mm: kształt siatki upraszczany z tą dokładnością (niżej niż dokładność druku) - mniej ścian, szybciej
_RESULTS = {}


def _shell_solid(v, t):
    """Szybka bryła z zamkniętej siatki: wspólne wierzchołki i krawędzie budowane od razu (bez zszywania), każdy trójkąt
    płaską ścianą na dokładnej płaszczyźnie."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeVertex
    from OCP.TopoDS import TopoDS_Shell, TopoDS_Solid, TopoDS_Wire
    from OCP.gp import gp_Pnt, gp_Pln, gp_Dir
    v = np.asarray(v, float)
    t = np.asarray(t, np.int64)
    pa = v[t[:, 0]]
    normal = np.cross(v[t[:, 1]] - pa, v[t[:, 2]] - pa)
    length = np.linalg.norm(normal, axis=1)
    keep = length > 1e-12
    t, pa, normal = t[keep], pa[keep], normal[keep] / length[keep, None]
    builder = BRep_Builder()
    vertices = [BRepBuilderAPI_MakeVertex(gp_Pnt(*p)).Vertex() for p in v.tolist()]
    sides = np.stack([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]], 1).reshape(-1, 2)
    key = np.sort(sides, 1)
    unique, index = np.unique(key, axis=0, return_inverse=True)
    index = np.asarray(index).reshape(-1)
    edges = [BRepBuilderAPI_MakeEdge(vertices[a], vertices[b]).Edge() for a, b in unique.tolist()]
    forward = (sides[:, 0] == key[:, 0]).tolist()
    index = index.tolist()
    shell = TopoDS_Shell()
    builder.MakeShell(shell)
    for i, (p, n) in enumerate(zip(pa.tolist(), normal.tolist())):
        wire = TopoDS_Wire()
        builder.MakeWire(wire)
        for j in (3 * i, 3 * i + 1, 3 * i + 2):
            edge = edges[index[j]]
            builder.Add(wire, edge if forward[j] else edge.Reversed())
        builder.Add(shell, BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(*p), gp_Dir(*n)), wire, True).Face())
    shell.Closed(True)
    solid = TopoDS_Solid()
    builder.MakeSolid(solid)
    builder.Add(solid, shell)
    return cq.Shape.cast(solid)


def _local(target, mesh_shape):
    """Część siatki wchodząca w bryłę (zamknięta objętość manifold3d) + objętość samej bryły (do podglądu)."""
    mf = _manifold()
    volume, skipped = mesh_volume(mesh_shape)
    body = _target_volume(target)
    box = kernel.bounds(target)
    eps = max(.05, 1e-3 * max(box.xlen, box.ylen, box.zlen))
    shifts = (np.eye(3) * eps).tolist() + (-np.eye(3) * eps).tolist()
    grown = mf.Manifold.batch_boolean([body] + [body.translate(d) for d in shifts], mf.OpType.Add)   # bryła poszerzona o eps
    local = volume ^ grown
    if local.is_empty() or (volume ^ body).volume() < 1e-9:
        raise CadError('Siatka STL nie wchodzi w tę bryłę - nie ma czego wyciąć.')
    return local, body, volume, skipped


def preview_mesh(target, mesh_shape):
    """Podgląd wyniku od razu (operacja na siatkach, ułamek sekundy) - bez budowania bryły."""
    _, body, volume, _ = _local(target, mesh_shape)
    v, t = _arrays(body - volume)
    if not len(t):
        raise CadError('Po wycięciu nic nie zostaje z bryły.')
    return kernel.triangle_mesh_display(triangles_shape(v, t))


def _cut(target, tool):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.TopTools import TopTools_ListOfShape
    arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    arguments.Append(target.wrapped)
    tools.Append(tool.wrapped)
    op = BRepAlgoAPI_Cut()
    op.SetArguments(arguments)
    op.SetTools(tools)
    op.SetRunParallel(True)
    op.SetUseOBB(True)
    op.SetNonDestructive(True)
    op.Build()
    if not op.IsDone():
        raise CadError('Wycięcie siatką STL nie powiodło się.')
    result = cq.Shape.cast(op.Shape())
    try:
        result = result.clean()
    except Exception:
        pass
    return result


def subtract(target, mesh_shape):
    """Bryła target minus kształt siatki STL. Zwraca (bryła, 'solid', liczba pominiętych otwartych części siatki).
    Kształt siatki upraszczany z dokładnością SIMPLIFY_TOL; wynik zapamiętany dla tej samej pary (bryła, siatka)."""
    hit = _RESULTS.get((id(target), id(mesh_shape)))
    if hit is not None and hit[0] is target and hit[1] is mesh_shape:
        return hit[2]
    local, _, _, skipped = _local(target, mesh_shape)
    if SIMPLIFY_TOL:
        local = local.simplify(SIMPLIFY_TOL)
    v, t = _arrays(local)
    if len(t) > MAX_TRIANGLES:
        raise CadError(f'W bryłę wchodzi bardzo dużo siatki ({len(t)} trójkątów) - zmniejsz obszar wspólny albo uprość siatkę STL.')
    result = None
    try:
        result = _cut(target, _shell_solid(v, t))       # poprawność sprawdzana na wyniku (nie osobno na narzędziu)
        if not kernel.is_valid(result) or not result.Solids():
            result = None
    except Exception:
        result = None
    if result is None:                      # zapasowo: zszywanie trójkątów i zwykła operacja logiczna
        result = kernel.boolean('subtract', target, [_triangle_solid(v, t)])
    out = (result, 'solid', skipped)
    if len(_RESULTS) > 8:
        _RESULTS.clear()
    _RESULTS[(id(target), id(mesh_shape))] = (target, mesh_shape, out)
    return out


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
