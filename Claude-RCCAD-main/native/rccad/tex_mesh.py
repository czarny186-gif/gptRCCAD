"""Tekstury geometryczne - tryb siatkowy (bardzo gęste wzory, druk 3D): bryła i narzędzia zamieniane na siatki trójkątów, operacje
logiczne na siatkach (manifold3d: równoległe, bez zawieszania), wynik to kształt-siatka (jak import STL) - eksport STL i 3MF, bez
zaokrągleń i STEP. Szczelność siatki jest sprawdzana (każda krawędź należy do dwóch trójkątów)."""
from __future__ import annotations

import io
import zipfile

import numpy as np

from . import kernel
from . import meshbool


def _mesh_arrays(shape, tol, ang=.5, copy=False):
    """Trójkąty kształtu (wspólne wierzchołki). Własna, rzadka siatka (tolerancja liniowa tol, kąt ang) - narzędzia mają tysiące
    kopii tej samej ściany, więc gęstość siatki decyduje o czasie i pamięci. copy: nie zmieniaj siatki oryginalnego kształtu."""
    import cadquery as cq
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools
    sh = shape if hasattr(shape, 'wrapped') else cq.Shape.cast(shape)
    if kernel.is_triangle_mesh(sh):
        V, T = kernel._stl_arrays(sh)
        return _weld(np.asarray(V, np.float64), np.asarray(T, np.int64))
    w = BRepBuilderAPI_Copy(sh.wrapped, True).Shape() if copy else sh.wrapped
    if copy:
        sh = cq.Shape.cast(w)
    BRepTools.Clean_s(w)
    BRepMesh_IncrementalMesh(w, max(float(tol), .01), False, float(ang), True)
    V, T = kernel._stl_arrays(sh)
    return _weld(np.asarray(V, np.float64), np.asarray(T, np.int64))


def _weld(V, T, q=1e-5):
    """Scala wierzchołki o tych samych współrzędnych (siatka ze ścian B-Rep ma osobne wierzchołki na każdej ścianie)."""
    key = np.round(V / q).astype(np.int64)
    _u, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    T2 = inv[T]
    keep = (T2[:, 0] != T2[:, 1]) & (T2[:, 1] != T2[:, 2]) & (T2[:, 0] != T2[:, 2])
    return V[first], T2[keep]


def _manifold(mf, shape, tol):
    import cadquery as cq
    V, T = _mesh_arrays(shape, tol, .25, copy=True)
    data = mf.Mesh(vert_properties=V.astype(np.float32), tri_verts=T.astype(np.uint32))
    data.merge()
    m = mf.Manifold(data)
    if m.status() != mf.Error.NoError or not m.num_tri():
        raise kernel.CadError('Siatka narzędzi nie jest szczelna - wzór nie nadaje się do trybu siatkowego (zmniejsz złożoność).')
    return m


def watertight(V, T):
    """Szczelność: każda krawędź wspólna dla dokładnie dwóch trójkątów (z kierunkami przeciwnymi) - liczba krawędzi nieszczelnych."""
    e = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    key = np.minimum(e[:, 0], e[:, 1]).astype(np.int64) * (len(V) + 1) + np.maximum(e[:, 0], e[:, 1])
    _u, cnt = np.unique(key, return_counts=True)
    return int((cnt != 2).sum())


def _tool_mesh_params(n, tol):
    """Gęstość siatki narzędzi maleje z liczbą elementów (pamięć i czas: dziesiątki tysięcy kopuł po kilkaset trójkątów to miliony trójkątów)."""
    if n > 30000:
        return max(tol, .12), 1.0
    if n > 8000:
        return max(tol, .08), .8
    return tol, .5


def apply(solid, ups, downs, cancel=None, progress=None, tol=.05):
    """Bryła + wypustki − zagłębienia na siatkach. Zwraca dict(shape, triangles, report)."""
    import cadquery as cq
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    mf = meshbool._manifold()
    base = _manifold(mf, solid, tol)
    report = []

    def comp(tools):
        c = TopoDS_Compound()
        b = BRep_Builder()
        b.MakeCompound(c)
        for t in tools:
            b.Add(c, t)
        return c
    res = base
    if ups:
        if cancel is not None and cancel():
            raise kernel.CadError('Obliczenia przerwane - model bez zmian.')
        V, T = _mesh_arrays(comp(ups), *_tool_mesh_params(len(ups), tol))
        parts = _split(V, T, mf)
        res = mf.Manifold.batch_boolean([res] + parts, mf.OpType.Add)
        if progress:
            progress(.5)
    if downs:
        if cancel is not None and cancel():
            raise kernel.CadError('Obliczenia przerwane - model bez zmian.')
        V, T = _mesh_arrays(comp(downs), *_tool_mesh_params(len(downs), tol))
        parts = _split(V, T, mf)
        cutter = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
        res = res - cutter
        if progress:
            progress(1.0)
    out = res.to_mesh()
    V = np.asarray(out.vert_properties)[:, :3].astype(np.float64)
    T = np.asarray(out.tri_verts).astype(np.int64)
    if not len(T):
        raise kernel.CadError('Wynik w trybie siatkowym jest pusty - zostaje poprzednia geometria.')
    bad = watertight(V, T)
    if bad:
        raise kernel.CadError(f'Siatka wyniku jest nieszczelna ({bad} krawędzi) - zostaje poprzednia geometria.')
    report.append(('ok', f'Siatka szczelna: {len(T)} trójkątów, {len(V)} wierzchołków.'))
    return dict(shape=meshbool.triangles_shape(V, T), triangles=int(len(T)), report=report, V=V, T=T)


def _split(V, T, mf):
    """Spójne części siatki (każde narzędzie osobno) jako Manifold. Podział przez sortowanie po etykiecie - liniowo, nie kwadratowo."""
    lab = meshbool._components(T, len(V))
    order = np.argsort(lab, kind='stable')
    T = T[order]
    lab = lab[order]
    cuts = np.flatnonzero(np.diff(lab)) + 1
    out = []
    for sel in np.split(T, cuts):
        used, inv = np.unique(sel.ravel(), return_inverse=True)
        data = mf.Mesh(vert_properties=V[used].astype(np.float32), tri_verts=inv.reshape(-1, 3).astype(np.uint32))
        data.merge()
        m = mf.Manifold(data)
        if m.status() == mf.Error.NoError and m.num_tri():
            out.append(m)
    if not out:
        raise kernel.CadError('Siatka narzędzi jest pusta albo nieszczelna.')
    return out


def write_3mf(path, V, T, name='RCCAD'):
    """Zapis siatki do 3MF (OPC: [Content_Types].xml, _rels/.rels, 3D/3dmodel.model), jednostka milimetr."""
    V = np.asarray(V, float)
    T = np.asarray(T, int)
    verts = ''.join(f'<vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>' for x, y, z in V)
    tris = ''.join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in T)
    model = ('<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<resources><object id="1" type="model" name="{name}"><mesh><vertices>{verts}</vertices><triangles>{tris}</triangles></mesh></object></resources>'
             '<build><item objectid="1"/></build></model>')
    ct = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(str(path), 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', ct)
        z.writestr('_rels/.rels', rels)
        z.writestr('3D/3dmodel.model', model)


def shape_arrays(shapes, tol=.05):
    """Siatka (wierzchołki wspólne, trójkąty) wszystkich kształtów do eksportu 3MF / kontroli szczelności."""
    import cadquery as cq
    Vs, Ts, off = [], [], 0
    for s in shapes:
        sh = s if hasattr(s, 'wrapped') else cq.Shape.cast(s)
        if kernel.is_triangle_mesh(sh):
            V, T = kernel._stl_arrays(sh)
        else:
            V, T = _mesh_arrays(sh, tol)
        Vs.append(np.asarray(V, float))
        Ts.append(np.asarray(T, int) + off)
        off += len(V)
    return np.vstack(Vs), np.vstack(Ts)
