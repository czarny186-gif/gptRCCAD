"""Generator obudów - etap 22: pełne dopasowanie przestrzenne 3D.

22A - analiza przestrzenna i strefa ochronna: dla każdego komponentu strefa = bryła odsunięta o odstęp
(BRepOffsetAPI_MakeOffsetShape, łączenie łukami); gdy odsunięcie się nie uda albo daje niepoprawną bryłę - prostopadłościan
OBB powiększony o odstęp (zgłaszane w raporcie). Strefy łączone w jedną bryłę (albo kilka rozłącznych obszarów).
Analiza: objętości, ramki AABB / OBB, osie główne (PCA), najmniejsze odległości między komponentami (DistShapeShape),
grupy komponentów o nachodzących strefach (rozłączne obszary), wypełnienie (objętość komponentów / objętość strefy)."""
from __future__ import annotations

import math

import numpy as np

from . import kernel

DEFAULTS = dict(clearance=2.0, overrides={}, zone_mode='offset')
ZONE_MODES = ('offset', 'obb', 'aabb')
ZONE_LABELS = {'offset': 'Strefa: odsunięcie powierzchni (dokładna)', 'obb': 'Strefa: ramka OBB + odstęp', 'aabb': 'Strefa: ramka AABB + odstęp'}


def _cq(shape):
    import cadquery as cq
    return shape if hasattr(shape, 'wrapped') else cq.Shape.cast(shape)


def _box_solid(center, axes, size):
    import cadquery as cq
    size = np.maximum(np.asarray(size, float), 1e-3)
    box = cq.Solid.makeBox(*map(float, size), pnt=cq.Vector(*map(float, -size / 2)))
    return kernel.transformed(box, np.asarray(axes, float).T, np.asarray(center, float)).wrapped


def offset_solid(shape, d):
    """Bryła odsunięta na zewnątrz o d (łączenie łukami); None - gdy OCCT nie zbuduje poprawnej bryły."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
    from OCP.BRepOffset import BRepOffset_Skin
    from OCP.GeomAbs import GeomAbs_Arc
    from .enclosure import _solids, _volume, is_valid
    if d <= 1e-9:
        return shape
    try:
        mk = BRepOffsetAPI_MakeOffsetShape()
        mk.PerformByJoin(shape, float(d), 1e-4, BRepOffset_Skin, False, False, GeomAbs_Arc, False)
        if not mk.IsDone():
            return None
        res = mk.Shape()
    except Exception:
        return None
    solids = [s for s in _solids(res) if _volume(s)[0] > 1e-6]
    if len(solids) != 1:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
        from OCP.TopAbs import TopAbs_SHELL
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
        ex = TopExp_Explorer(res, TopAbs_SHELL)
        if not ex.More():
            return None
        try:
            ms = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(ex.Current()))
            solids = [ms.Solid()]
        except Exception:
            return None
    from OCP.TopoDS import TopoDS as _T
    s = _T.Solid_s(solids[0])
    if _volume(s)[0] < _volume(shape)[0] - 1e-6:                   # odwrócona orientacja powłoki
        from OCP.BRepLib import BRepLib
        BRepLib.OrientClosedSolid_s(s)
    if not is_valid(s) or _volume(s)[0] < _volume(shape)[0] - 1e-6:
        return None
    return s


def component_zone(shape, d, mode='offset'):
    """Strefa ochronna jednego komponentu: (bryła, sposób) - sposób 'offset' / 'obb' / 'aabb' (rzeczywiście użyty)."""
    from .enclosure import aabb, obb, _boolean, _volume
    sh = _cq(shape)
    if mode == 'offset':
        z = offset_solid(sh.wrapped, d)
        if z is not None and _volume(_boolean('cut', sh.wrapped, z, 'strefa a komponent'))[0] <= 1e-4:
            return z, 'offset'
        mode = 'obb'
    env = obb([sh]) if mode == 'obb' else aabb([sh])
    return _box_solid(env.center, env.axes, np.asarray(env.size, float) + 2 * d), mode


def _pca(points):
    c = points.mean(0)
    w, V = np.linalg.eigh((points - c).T @ (points - c) / max(1, len(points)))
    order = np.argsort(w)[::-1]
    return c, V[:, order].T, w[order]


def analyse(components, p, cancel=None):
    """22A: components - [(id, nazwa, kształt)]. Zwraca dict(zone, regions, rows, pairs, groups, report, stats, points)."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from .enclosure import aabb, obb, _boolean, _volume, _solids, is_valid
    from .enclosure_ribs import _multi
    from .enclosure_optimize import _points
    p = dict(DEFAULTS, **p)
    if not components:
        raise kernel.CadError('Wskaż komponenty do analizy przestrzennej.')
    rows, zones, report, pts = [], [], [], []
    for ident, name, shape in components:
        if cancel is not None and cancel():
            raise kernel.CadError('Analiza przerwana.')
        sh = _cq(shape)
        d = float((p.get('overrides') or {}).get(ident, p['clearance']))
        z, used = component_zone(sh.wrapped, d, p['zone_mode'])
        if used != p['zone_mode']:
            report.append(('warning', f'{name}: odsunięcie powierzchni nie powiodło się - strefa z ramki {used.upper()} (większa niż potrzeba).'))
        zones.append(z)
        a, o = aabb([sh]), obb([sh])
        q = _points(sh)
        pts.append(q)
        rows.append(dict(id=ident, name=name, volume=float(_volume(sh.wrapped)[0]), aabb=[float(x) for x in a.size], obb=[float(x) for x in o.size],
                         clearance=d, zone=used, zone_volume=float(_volume(z)[0])))
    zone = zones[0] if len(zones) == 1 else _multi('fuse', zones[0], zones[1:], 'strefa ochronna')
    regions = [s for s in _solids(zone) if _volume(s)[0] > 1e-6]
    if not regions or not all(is_valid(r) for r in regions):
        raise kernel.CadError('Strefa ochronna nie jest poprawną bryłą - zmień odstęp albo tryb strefy.')
    pairs = []                                                         # najmniejsze odległości między komponentami
    for i in range(len(components)):
        for j in range(i + 1, len(components)):
            dd = BRepExtrema_DistShapeShape(_cq(components[i][2]).wrapped, _cq(components[j][2]).wrapped)
            dd.Perform()
            if dd.IsDone():
                pairs.append((components[i][1], components[j][1], float(dd.Value())))
    groups = []                                                        # komponenty w tym samym rozłącznym obszarze strefy
    for r in regions:
        members = [rows[k]['name'] for k, z in enumerate(zones) if _volume(_boolean('common', z, r, 'obszar strefy'))[0] > 1e-6]
        groups.append(members)
    allp = np.vstack(pts)
    c, axes, var = _pca(allp)
    comp_vol = sum(r_['volume'] for r_ in rows)
    zvol = float(sum(_volume(r)[0] for r in regions))
    env = aabb([_cq(z) for z in regions])
    stats = dict(components=comp_vol, zone=zvol, fill=comp_vol / zvol if zvol > 0 else 0.0, aabb=[float(x) for x in env.size],
                 aabb_volume=float(np.prod(env.size)), regions=len(regions), axes=axes.tolist(), center=c.tolist(),
                 elongation=float(np.sqrt(var[0] / max(var[2], 1e-12))))
    report.append(('ok', f'Strefa ochronna: {zvol / 1000:.1f} cm³ ({len(regions)} obszar(y)), komponenty {comp_vol / 1000:.1f} cm³, '
                         f'wypełnienie {100 * stats["fill"]:.0f} %; ramka AABB strefy {env.size[0]:.1f} × {env.size[1]:.1f} × {env.size[2]:.1f} mm.'))
    tight = [(a, b, d) for a, b, d in pairs if d < 2 * float(p['clearance'])]
    if tight:
        report.append(('warning', 'Komponenty bliżej niż dwa odstępy: ' + ', '.join(f'{a} / {b} ({d:.1f} mm)' for a, b, d in tight[:4])))
    if len(regions) > 1:
        report.append(('warning', f'Strefa ma {len(regions)} rozłączne obszary: ' + '; '.join(', '.join(g) for g in groups)))
    return dict(zone=zone, regions=regions, rows=rows, pairs=pairs, groups=groups, report=report, stats=stats, points=allp)


# ---------------------------------------------------------------------------------------------- 22B: otoczka wypukła 3D
def quickhull(points, eps=None):
    """Otoczka wypukła 3D (QuickHull): (punkty, trójkąty zorientowane na zewnątrz). Punkty współpłaszczyznowe / współliniowe -
    CadError (otoczka bryłowa nie istnieje)."""
    P = np.unique(np.round(np.asarray(points, float), 9), axis=0)
    if len(P) < 4:
        raise kernel.CadError('Za mało punktów do otoczki wypukłej 3D.')
    ext = float(np.ptp(P, axis=0).max())
    eps = eps if eps is not None else 1e-9 * max(ext, 1.0) * 10
    i0, i1 = int(P[:, 0].argmin()), int(P[:, 0].argmax())
    if np.linalg.norm(P[i1] - P[i0]) < eps:
        i1 = int(np.linalg.norm(P - P[i0], axis=1).argmax())
    d = P[i1] - P[i0]
    i2 = int(np.linalg.norm(np.cross(P - P[i0], d), axis=1).argmax())
    n = np.cross(P[i1] - P[i0], P[i2] - P[i0])
    if np.linalg.norm(n) < eps * ext:
        raise kernel.CadError('Punkty komponentów leżą na jednej prostej - otoczka 3D nie istnieje.')
    i3 = int(np.abs((P - P[i0]) @ n).argmax())
    if abs(float((P[i3] - P[i0]) @ n)) < eps * np.linalg.norm(n):
        raise kernel.CadError('Punkty komponentów leżą w jednej płaszczyźnie - otoczka 3D nie istnieje.')
    centre = P[[i0, i1, i2, i3]].mean(0)
    faces = {}
    fid = [0]

    def plane(a, b, c):
        nn = np.cross(P[b] - P[a], P[c] - P[a])
        ln = np.linalg.norm(nn)
        nn = nn / ln if ln > 0 else nn
        return nn, float(nn @ P[a])

    def add(a, b, c):
        nn, off = plane(a, b, c)
        if nn @ centre - off > 0:                                      # orientacja na zewnątrz
            b, c = c, b
            nn, off = -nn, -off
        k = fid[0]
        fid[0] += 1
        faces[k] = dict(v=(a, b, c), n=nn, d=off, out=[])
        return k
    for tri in ((i0, i1, i2), (i0, i1, i3), (i0, i2, i3), (i1, i2, i3)):
        add(*tri)
    rest = [i for i in range(len(P)) if i not in (i0, i1, i2, i3)]
    ids = list(faces)
    N = np.array([faces[k]['n'] for k in ids])
    D = np.array([faces[k]['d'] for k in ids])
    if rest:
        dist = P[rest] @ N.T - D
        best = dist.argmax(1)
        for r_, b_, dv in zip(rest, best, dist[np.arange(len(rest)), best]):
            if dv > eps:
                faces[ids[b_]]['out'].append(r_)
    while True:
        cand = [k for k, f in faces.items() if f['out']]
        if not cand:
            break
        k0 = cand[0]
        f0 = faces[k0]
        pts_ = np.array(f0['out'])
        far = int(pts_[np.argmax(P[pts_] @ f0['n'] - f0['d'])])
        p = P[far]
        visible = [k for k, f in faces.items() if p @ f['n'] - f['d'] > eps]
        edges = {}
        for k in visible:
            a, b, c = faces[k]['v']
            for e in ((a, b), (b, c), (c, a)):
                edges[e] = edges.get(e, 0) + 1
        horizon = [e for e in edges if (e[1], e[0]) not in edges]
        orphan = set()
        for k in visible:
            orphan.update(faces[k]['out'])
            del faces[k]
        orphan.discard(far)
        new = []
        for a, b in horizon:
            nn, off = plane(a, b, far)
            k = fid[0]
            fid[0] += 1
            faces[k] = dict(v=(a, b, far), n=nn, d=off, out=[])
            new.append(k)
        if orphan:
            orr = np.array(sorted(orphan))
            Nn = np.array([faces[k]['n'] for k in new])
            Dn = np.array([faces[k]['d'] for k in new])
            dist = P[orr] @ Nn.T - Dn
            best = dist.argmax(1)
            for r_, b_, dv in zip(orr, best, dist[np.arange(len(orr)), best]):
                if dv > eps:
                    faces[new[b_]]['out'].append(int(r_))
    tris = np.array([f['v'] for f in faces.values()], int)
    return P, tris


def hull_polygons(P, tris, tol=1e-7):
    """Trójkąty otoczki zgrupowane w płaskie wielokąty (współpłaszczyznowe sąsiednie trójkąty - jedna ściana)."""
    nrm = np.cross(P[tris[:, 1]] - P[tris[:, 0]], P[tris[:, 2]] - P[tris[:, 0]])
    nrm /= np.linalg.norm(nrm, axis=1)[:, None]
    off = np.einsum('ij,ij->i', nrm, P[tris[:, 0]])
    ext = max(float(np.ptp(P, axis=0).max()), 1.0)
    groups = []
    used = np.zeros(len(tris), bool)
    for i in range(len(tris)):
        if used[i]:
            continue
        same = np.where((~used) & (np.einsum('ij,j->i', nrm, nrm[i]) > 1 - 1e-9) & (np.abs(off - off[i]) < tol * ext))[0]
        used[same] = True
        groups.append(same)
    polys = []
    for g in groups:
        cnt = {}
        for t in tris[g]:
            for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                cnt[e] = cnt.get(e, 0) + 1
        bnd = [e for e in cnt if (e[1], e[0]) not in cnt]
        nxt = {a: b for a, b in bnd}
        start = bnd[0][0]
        loop, cur = [start], nxt[start]
        while cur != start and len(loop) <= len(bnd):
            loop.append(cur)
            cur = nxt[cur]
        clean = []                                                     # wierzchołki współliniowe usunięte
        for j in range(len(loop)):
            a, b, c = P[loop[j - 1]], P[loop[j]], P[loop[(j + 1) % len(loop)]]
            if np.linalg.norm(np.cross(b - a, c - b)) > 1e-12 * ext * ext:
                clean.append(loop[j])
        polys.append(clean)
    return polys


def polyhedron(P, polys):
    """Wielościan B-Rep z płaskich wielokątów: MakePolygon → MakeFace → Sewing → MakeSolid (orientacja zamknięta)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.BRepLib import BRepLib
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt
    from .enclosure import is_valid
    from OCP.gp import gp_Dir, gp_Pln
    sew = BRepBuilderAPI_Sewing(5e-3)
    for poly in polys:
        q = P[poly]
        n = np.zeros(3)
        for j in range(len(q)):                                        # płaszczyzna Newella; wierzchołki dosunięte do niej
            a, b = q[j], q[(j + 1) % len(q)]
            n += np.array([(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])])
        n /= np.linalg.norm(n)
        o = q.mean(0)
        q = q - np.outer((q - o) @ n, n)
        mp = BRepBuilderAPI_MakePolygon()
        for x in q:
            mp.Add(gp_Pnt(*map(float, x)))
        mp.Close()
        mf = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(*map(float, o)), gp_Dir(*map(float, n))), mp.Wire(), True)
        if not mf.IsDone():
            raise kernel.CadError('Nie udało się zbudować ściany otoczki.')
        sew.Add(mf.Face())
    sew.Perform()
    ex = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
    if not ex.More():
        raise kernel.CadError('Ściany otoczki nie tworzą zamkniętej powłoki.')
    solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(ex.Current())).Solid()
    BRepLib.OrientClosedSolid_s(solid)
    if not is_valid(solid):
        raise kernel.CadError('Otoczka wypukła nie jest poprawną bryłą B-Rep.')
    return solid


def convex_planes(P, polys):
    """Płaszczyzny ścian wielościanu wypukłego: (normalne na zewnątrz, odległości)."""
    N, D = [], []
    c = P[np.unique(np.concatenate(polys))].mean(0)
    for poly in polys:
        q = P[poly]
        n = np.zeros(3)
        for j in range(len(q)):                                        # normalna Newella
            a, b = q[j], q[(j + 1) % len(q)]
            n += np.array([(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])])
        n /= np.linalg.norm(n)
        d = float(n @ q.mean(0))
        if n @ c > d:
            n, d = -n, -d
        N.append(n)
        D.append(d)
    return np.array(N), np.array(D), c


def offset_planes(N, D, c, d):
    """Wielościan wypukły {x: N·x ≤ D + d} - wierzchołki przez dualność biegunową (otoczka punktów dualnych), bez
    odsuwania w OCCT (odporne przy wielu małych ścianach). Zwraca (P, polygons)."""
    h = D + float(d) - N @ c
    if np.any(h <= 1e-9):
        raise kernel.CadError('Odsunięcie do wewnątrz większe niż wielościan.')
    Q = N / h[:, None]
    Pq, Tq = quickhull(Q)
    dpoly = hull_polygons(Pq, Tq)                                      # ściana dualna = wierzchołek pierwotny
    V = []
    for g in dpoly:
        q = Pq[g]
        n = np.cross(q[1] - q[0], q[2] - q[0])
        for j in range(2, len(q) - 1):
            if np.linalg.norm(n) > 1e-14:
                break
            n = np.cross(q[j] - q[0], q[j + 1] - q[0])
        n /= np.linalg.norm(n)
        o = float(n @ q.mean(0))
        if o < 0:
            n, o = -n, -o
        V.append(c + n / o)
    V = np.array(V)
    around = {}                                                        # wierzchołek dualny (płaszczyzna) → ściany dualne wokół
    for gi, g in enumerate(dpoly):
        for j, v in enumerate(g):
            around.setdefault(v, []).append((gi, g[j - 1], g[(j + 1) % len(g)]))
    polys = []
    for v, lst in around.items():
        by_prev = {pv: (gi, nx) for gi, pv, nx in lst}
        gi, _pv, nx = lst[0]
        loop = [gi]
        for _ in range(len(lst)):
            nxt = by_prev.get(nx)
            if nxt is None or nxt[0] == loop[0]:
                break
            loop.append(nxt[0])
            nx = nxt[1]
        if len(loop) != len(lst):
            raise kernel.CadError('Nie udało się odtworzyć ścian odsuniętego wielościanu.')
        polys.append(loop)
    return weld(V, polys)


def weld(V, polys, tol=2e-3):
    """Zgrzanie wierzchołków bliższych niż tol [mm] (prawie wspólne punkty kilku płaszczyzn dają krawędzie rzędu
    tysięcznych milimetra, które psują zszycie ścian); wielokąty bez powtórzeń, zdegenerowane pominięte."""
    V = np.asarray(V, float)
    parent = list(range(len(V)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    order = np.argsort(V[:, 0])
    for a_ in range(len(order)):
        i = order[a_]
        for b_ in range(a_ + 1, len(order)):
            j = order[b_]
            if V[j, 0] - V[i, 0] > tol:
                break
            if np.linalg.norm(V[i] - V[j]) <= tol:
                parent[find(j)] = find(i)
    roots = sorted({find(i) for i in range(len(V))})
    idx = {r: n for n, r in enumerate(roots)}
    groups = {}
    for i in range(len(V)):
        groups.setdefault(find(i), []).append(i)
    W = np.array([V[groups[r]].mean(0) for r in roots])
    out = []
    for poly in polys:
        q = []
        for i in poly:
            k = idx[find(i)]
            if not q or q[-1] != k:
                q.append(k)
        if len(q) > 1 and q[0] == q[-1]:
            q.pop()
        if len(q) >= 3 and len(set(q)) == len(q):
            out.append(q)
    return W, out


def support_planes(points, directions=160, keep_faces=True):
    """Otoczka wypukła jako płaszczyzny podparcia: normalne dużych ścian dokładnej otoczki QuickHull (płaskie ściany
    zostają dokładne) + kierunki równomierne na sferze (Fibonacci) w obszarach zakrzywionych. Wielościan
    {x: n·x ≤ max(P·n)} zawiera wszystkie punkty i ma ograniczoną liczbę dobrze ukształtowanych ścian."""
    P = np.asarray(points, float)
    dirs = []
    if keep_faces:
        Ph, Th = quickhull(P)
        polys = hull_polygons(Ph, Th)
        N, _D, _c = convex_planes(Ph, polys)
        area = []
        for poly in polys:
            q = Ph[poly]
            area.append(0.5 * np.linalg.norm(sum(np.cross(q[j], q[(j + 1) % len(q)]) for j in range(len(q)))))
        area = np.array(area)
        for i in np.argsort(area)[::-1][:60]:
            if area[i] >= .01 * area.max():
                dirs.append(N[i])
    k = np.arange(directions) + .5
    phi = np.arccos(1 - 2 * k / directions)
    th = np.pi * (1 + 5 ** .5) * k
    dirs += list(np.column_stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)]))
    out = []
    for d in dirs:
        d = d / np.linalg.norm(d)
        if all(float(d @ e) < math.cos(math.radians(1.5)) for e in out):
            out.append(d)
    N = np.array(out)
    return N, (P @ N.T).max(0), P.mean(0)


def mesh_points(shape, deflection):
    """Wierzchołki triangulacji B-Rep o zadanej odchyłce liniowej (BRepMesh) - do funkcji podparcia z gwarancją."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    sh = BRepBuilderAPI_Copy(shape).Shape()
    BRepMesh_IncrementalMesh(sh, float(deflection), False, .2, True)
    out = []
    ex = TopExp_Explorer(sh, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(f, loc)
        if tri is not None:
            tr = loc.Transformation()
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(tr)
                out.append((p.X(), p.Y(), p.Z()))
        ex.Next()
    return np.array(out, float)


def exact_support(shape, N, D, cancel=None):
    """Dokładna funkcja podparcia bryły B-Rep w kierunkach N: odległość (DistShapeShape) od dalekiej płaszczyzny
    prostopadłej do kierunku - płaszczyzna otoczki dotyka bryły, a nie tylko wierzchołków jej triangulacji."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    out = np.array(D, float)
    span = float(np.ptp(D)) + 100.0
    for i, n in enumerate(N):
        if cancel is not None and i % 20 == 0 and cancel():
            raise kernel.CadError('Obliczenia przerwane.')
        far = D[i] + span
        o = n * far
        pl = gp_Pln(gp_Pnt(*map(float, o)), gp_Dir(*map(float, n)))
        face = BRepBuilderAPI_MakeFace(pl, -1e5, 1e5, -1e5, 1e5).Face()
        d = BRepExtrema_DistShapeShape(shape, face)
        d.Perform()
        if d.IsDone():
            out[i] = max(D[i], far - d.Value())
    return out


def planes_solid(N, D, c, d=0.0):
    """Bryła B-Rep wielościanu {x: N·x ≤ D + d} (krawędzie ostre - przecięcia płaszczyzn)."""
    P2, polys2 = offset_planes(N, D, c, d)
    return polyhedron(P2, polys2)


def hull_enclosure(zone, points, wall, directions=160, cancel=None, local=None, axis=(0, 0, 1.0)):
    """22B: otoczka wypukła strefy ochronnej (QuickHull 3D → płaszczyzny podparcia) → bryła wnętrza (zawiera strefę -
    sprawdzane dokładnie na B-Rep, przy odchyłce triangulacji powiększana) i bryła zewnętrzna (płaszczyzny odsunięte o
    grubość ścianki). Zwraca dict(inner, outer, shell, report, planes)."""
    from .enclosure import _boolean, _volume, _single
    report = []
    N, D, c = support_planes(points, directions)
    if cancel is not None and cancel():
        raise kernel.CadError('Obliczenia przerwane.')
    defl = .02
    fine = mesh_points(zone, defl)                                      # gęsta triangulacja: powierzchnia w odległości ≤ defl od niej
    D = np.maximum(D, (fine @ N.T).max(0))
    grow = defl + .01
    inner = planes_solid(N, D, c, grow)
    out_v = _volume(_boolean('cut', zone, inner, 'strefa poza otoczką'))[0]
    if out_v > 1e-6:
        raise kernel.CadError(f'Otoczka nie obejmuje strefy ochronnej ({out_v:.4f} mm³ na zewnątrz).')
    D = D + grow
    a = _unit(axis)
    wv = np.full(len(N), float(wall))
    local = local or {}
    wv[N @ a < -.999] += float(local.get('bottom') or 0.0)             # inna grubość dna / pokrywy (ściany prostopadłe do osi)
    wv[N @ a > .999] += float(local.get('top') or 0.0)
    outer = planes_solid(N, D + wv, c, 0.0)
    shell = _single(_boolean('cut', outer, inner, 'ścianka otoczki'), 'Obudowa z otoczki')
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    ex, nf = TopExp_Explorer(inner, TopAbs_FACE), 0
    while ex.More():
        nf += 1
        ex.Next()
    report.append(('ok', f'Otoczka wypukła: {nf} ścian; wnętrze {_volume(inner)[0] / 1000:.1f} cm³, '
                         f'zewnątrz {_volume(outer)[0] / 1000:.1f} cm³, materiał {_volume(shell)[0] / 1000:.1f} cm³.'))
    return dict(inner=inner, outer=outer, shell=shell, report=report, faces=nf, planes=(N, D, c),
                grown=lambda d: planes_solid(N, D, c, d))


# ---------------------------------------------------------------------------------------------- 22C: zmienny przekrój
SECTION_SHAPES = ('hull', 'rect')
SECTION_LABELS = {'hull': 'Przekrój: otoczka wypukła (zaokrąglona)', 'rect': 'Przekrój: prostokąt (zaokrąglony)'}
DISJOINT = ('merge', 'bbox', 'separate')
DISJOINT_LABELS = {'merge': 'Rozłączne obszary: wspólna otoczka', 'bbox': 'Rozłączne obszary: wspólny prostokąt',
                   'separate': 'Rozłączne obszary: osobne bryły (stała liczba obszarów)'}


def hull2d(pts):
    """Otoczka wypukła 2D (monotone chain), przeciwnie do ruchu wskazówek."""
    P = np.unique(np.round(np.asarray(pts, float), 9), axis=0)
    if len(P) < 3:
        return P
    P = [tuple(q) for q in P[np.lexsort((P[:, 1], P[:, 0]))]]

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (p[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])) <= 1e-12:
                out.pop()
            out.append(p)
        return out
    lo, hi = half(P), half(P[::-1])
    return np.array(lo[:-1] + hi[:-1], float)


def _axis_frame(axis):
    a = _unit(axis)
    ref = np.array([1.0, 0, 0]) if abs(a[0]) < .9 else np.array([0, 1.0, 0])
    x = _unit(ref - a * float(ref @ a))
    return x, np.cross(a, x), a


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def section_curves(shape, origin, normal, samples=64):
    """Przekrój bryły płaszczyzną (BRepAlgoAPI_Section): punkty krzywych przekroju (próbkowane)."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    sec = BRepAlgoAPI_Section(shape, gp_Pln(gp_Pnt(*map(float, origin)), gp_Dir(*map(float, normal))), False)
    sec.ComputePCurveOn1(False)
    sec.Approximation(False)
    sec.Build()
    if not sec.IsDone():
        raise kernel.CadError('Przekrój strefy płaszczyzną nie powiódł się.')
    pts = []
    ex = TopExp_Explorer(sec.Shape(), TopAbs_EDGE)
    while ex.More():
        c = BRepAdaptor_Curve(TopoDS.Edge_s(ex.Current()))
        for t in np.linspace(c.FirstParameter(), c.LastParameter(), samples):
            p = c.Value(float(t))
            pts.append((p.X(), p.Y(), p.Z()))
        ex.Next()
    return np.array(pts, float).reshape(-1, 3)


def _support_curve(hull, r, M=48):
    """Zaokrąglony wielokąt wypukły (Minkowski z okręgiem r): gęsty obrys (łuki w narożnikach, odcinki) przepróbkowany
    równomiernie po długości do M punktów od punktu skrajnego w +X, przeciwnie do ruchu wskazówek - zgodne przekroje."""
    hull = np.asarray(hull, float)
    if len(hull) < 3:
        c = hull.mean(0) if len(hull) else np.zeros(2)
        th = np.linspace(0, 2 * np.pi, M, endpoint=False)
        return c + (r + (np.linalg.norm(hull - c, axis=1).max() if len(hull) else 0.0)) * np.c_[np.cos(th), np.sin(th)]
    n = len(hull)
    dense = []
    for i in range(n):
        p0, p1, p2 = hull[i - 1], hull[i], hull[(i + 1) % n]
        e0, e1 = p1 - p0, p2 - p1
        n0 = np.array([e0[1], -e0[0]]) / np.linalg.norm(e0)
        n1 = np.array([e1[1], -e1[0]]) / np.linalg.norm(e1)
        a0, a1 = math.atan2(n0[1], n0[0]), math.atan2(n1[1], n1[0])
        if a1 < a0:
            a1 += 2 * math.pi
        for t in np.linspace(a0, a1, max(2, int((a1 - a0) / .05) + 2)):
            dense.append(p1 + r * np.array([math.cos(t), math.sin(t)]))
    dense = np.array(dense)
    start = int(dense[:, 0].argmax())
    dense = np.roll(dense, -start, axis=0)
    closed = np.vstack([dense, dense[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    cum = np.r_[0, np.cumsum(seg)]
    tt = np.linspace(0, cum[-1], M, endpoint=False)
    return np.c_[np.interp(tt, cum, closed[:, 0]), np.interp(tt, cum, closed[:, 1])]


def _section_wire(pts2, x, y, origin, curves=None):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.GeomAPI import GeomAPI_Interpolate
    from OCP.TColgp import TColgp_HArray1OfPnt
    from OCP.gp import gp_Pnt
    arr = TColgp_HArray1OfPnt(1, len(pts2))
    for i, (a, b) in enumerate(pts2):
        q = origin + x * a + y * b
        arr.SetValue(i + 1, gp_Pnt(*map(float, q)))
    it = GeomAPI_Interpolate(arr, True, 1e-7)
    it.Perform()
    if not it.IsDone():
        raise kernel.CadError('Interpolacja przekroju nie powiodła się.')
    w = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(it.Curve()).Edge()).Wire()
    if curves is not None:
        curves.append(it.Curve())
    return w


def _loft(wires, ruled=False):
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from .enclosure import is_valid
    mk = BRepOffsetAPI_ThruSections(True, ruled, 1e-6)
    for w in wires:
        mk.AddWire(w)
    mk.CheckCompatibility(False)
    mk.Build()
    if not mk.IsDone():
        raise kernel.CadError('Loft przekrojów (ThruSections) nie powiódł się - zmień liczbę przekrojów.')
    s = mk.Shape()
    from .enclosure import _solids
    sol = _solids(s)
    if len(sol) != 1 or not is_valid(sol[0]):
        raise kernel.CadError('Loft przekrojów nie dał poprawnej bryły - zmień liczbę przekrojów albo zaokrąglenie.')
    return sol[0]


def _regions2d(pts2, gap):
    """Rozłączne skupiska punktów przekroju (odległość > gap) - liczba obszarów w przekroju."""
    n = len(pts2)
    if n == 0:
        return []
    lab = -np.ones(n, int)
    cur = 0
    for i in range(n):
        if lab[i] >= 0:
            continue
        stack = [i]
        lab[i] = cur
        while stack:
            j = stack.pop()
            d = np.linalg.norm(pts2 - pts2[j], axis=1)
            for k in np.where((d <= gap) & (lab < 0))[0]:
                lab[k] = cur
                stack.append(k)
        cur += 1
    return [pts2[lab == c] for c in range(cur)]


def section_profiles(zone, axis, p, cancel=None):
    """Przekroje strefy wzdłuż osi: stacje (równomierne albo edytowane), w każdej - otoczka 2D zawartości warstwy
    między sąsiednimi stacjami (punkty triangulacji z gwarancją odchyłki + krzywe BRepAlgoAPI_Section) z dodatkiem
    stacji. Zwraca dict(x, y, a, stations [(s, [hull2d...])], lo, hi)."""
    x, y, a = _axis_frame(axis)
    defl = .02
    pts = mesh_points(zone, defl)
    s_all = pts @ a
    lo, hi = float(s_all.min()), float(s_all.max())
    stations = p.get('stations') or []
    if stations:
        st = sorted(lo + (hi - lo) * min(1.0, max(0.0, float(q['t']))) for q in stations)
        extra = {round(lo + (hi - lo) * float(q['t']), 9): float(q.get('offset', 0.0)) for q in stations}
    else:
        n = max(2, int(p.get('sections', 8)))
        st = list(np.linspace(lo, hi, n))
        extra = {}
    if st[0] > lo + 1e-9:
        st = [lo] + st
    if st[-1] < hi - 1e-9:
        st = st + [hi]
    out = []
    for k, s in enumerate(st):
        if cancel is not None and cancel():
            raise kernel.CadError('Obliczenia przerwane.')
        s0 = st[k - 1] if k > 0 else s
        s1 = st[k + 1] if k + 1 < len(st) else s
        m = (s_all >= s0 - 1e-9) & (s_all <= s1 + 1e-9)
        q = pts[m]
        if lo + 1e-6 < s < hi - 1e-6:
            sec = section_curves(zone, a * s, a)
            if len(sec):
                q = np.vstack([q, sec])
        if not len(q):
            raise kernel.CadError('Pusta warstwa strefy - zmień liczbę przekrojów.')
        q2 = np.c_[q @ x, q @ y]
        hulls = []
        for rg in [q2]:
            h = hull2d(rg)
            if p.get('section') == 'rect' or p.get('disjoint') == 'bbox':
                mn, mx = rg.min(0), rg.max(0)
                h = np.array([[mn[0], mn[1]], [mx[0], mn[1]], [mx[0], mx[1]], [mn[0], mx[1]]])
            hulls.append(h)
        out.append((s, hulls, extra.get(round(s, 9), 0.0)))
    return dict(x=x, y=y, a=a, stations=out, lo=lo, hi=hi, defl=defl, points=pts)


def section_enclosure(zone, p, cancel=None):
    """22C: obudowa o zmiennym przekroju - przekroje (otoczki 2D warstw, zaokrąglenie r) połączone loftem
    (BRepOffsetAPI_ThruSections, gładki B-spline), zewnętrze z przekrojów odsuniętych o grubość ścianki i dna / pokrywy.
    Rozłączne obszary: wspólna otoczka, wspólny prostokąt albo osobne bryły (gdy liczba obszarów stała wzdłuż osi -
    inaczej komunikat; strategia nie jest zmieniana samoczynnie). Zawieranie strefy sprawdzane dokładnie."""
    from .enclosure import _boolean, _volume, _single, _solids
    from .enclosure_ribs import _multi
    p = dict(dict(sections=8, corner=2.0, wall=2.0, section='hull', disjoint='merge', axis=[0, 0, 1.0]), **p)
    if p['disjoint'] == 'separate':                                     # każdy rozłączny obszar strefy osobno
        from .enclosure import _solids as _sl
        regs = [q for q in _sl(zone) if _volume(q)[0] > 1e-6]
        if len(regs) > 1:
            res = [section_enclosure(q, dict(p, disjoint='merge'), cancel) for q in regs]
            for i in range(len(res)):
                for j in range(i + 1, len(res)):
                    if _volume(_boolean('common', res[i]['outer'], res[j]['outer'], 'osobne obudowy'))[0] > 1e-6:
                        raise kernel.CadError('Osobne obudowy obszarów nachodzą na siebie - wybierz wspólną otoczkę albo prostokąt.')
            shells = [q['shell'] for q in res]
            rep_ = [t for q in res for t in q['report']]
            rep_.append(('ok', f'Osobne bryły dla {len(regs)} rozłącznych obszarów strefy.'))
            return dict(inner=_multi('fuse', res[0]['inner'], [q['inner'] for q in res[1:]], 'wnętrza'),
                        outer=_multi('fuse', res[0]['outer'], [q['outer'] for q in res[1:]], 'zewnętrza'),
                        shell=shells[0], parts=shells, report=rep_, stations=res[0]['stations'], frame=res[0]['frame'],
                        grown=lambda d: _multi('fuse', res[0]['grown'](d), [q['grown'](d) for q in res[1:]], 'wnętrza'))
    axis = np.asarray(p['axis'], float)
    data = section_profiles(zone, axis, p, cancel)
    x, y, a = data['x'], data['y'], data['a']
    counts = {len(h) for _s, h, _e in data['stations']}
    if len(counts) != 1:
        raise kernel.CadError(f'Liczba rozłącznych obszarów zmienia się wzdłuż osi ({sorted(counts)}) - wybierz wspólną otoczkę albo prostokąt.')
    nreg = counts.pop()
    r = max(float(p['corner']), .2)
    wall = float(p['wall'])
    report = []
    inners, outers, growns = [], [], []
    for g in range(nreg):
        chain = []
        for s, hulls, ext in data['stations']:
            if g == 0 or nreg == 1:
                h = hulls[g]
            else:                                                       # dopasowanie obszarów po środku ciężkości
                ref = chain[-1][1].mean(0) if chain else None
                h = hulls[int(np.argmin([np.linalg.norm(q.mean(0) - ref) for q in hulls]))] if ref is not None else hulls[g]
            chain.append((s, h, ext))
        pts = data['points']
        if nreg > 1:                                                    # punkty strefy należące do tego łańcucha obszarów
            hh = hull2d(np.vstack([h for _s, h, _e in chain]))
            q2 = np.c_[pts @ x, pts @ y]
            pts = pts[_in_convex(q2, hh, r + 2 * wall)]
        for grow in (data['defl'] + .05, .3, 1.0, 2.5, 5.0):
            curves = []
            inner = _loft(_chain_wires(chain, x, y, a, r + grow, grow, curves), ruled=True)
            if _inside_all(curves, pts, (x, y, a), margin=data['defl'] + .01):
                break
        else:
            raise kernel.CadError('Loft przekrojów nie obejmuje strefy - zwiększ liczbę przekrojów albo zaokrąglenie.')
        if grow > data['defl'] + .03:
            report.append(('ok', f'Przekroje powiększone o {grow:g} mm (wybrzuszenie strefy między przekrojami).'))
        loc = p.get('local') or {}
        fac = 1.0
        for _ in range(4):                                             # odsunięcie w przekroju poprawiane do grubości normalnej
            outer = _loft(_chain_wires(chain, x, y, a, r + grow + wall * fac, grow + wall + float(loc.get('bottom') or 0), None,
                                       grow + wall + float(loc.get('top') or 0)), ruled=True)
            tw = min_wall(inner, outer)
            if tw >= wall - 1e-3:
                break
            fac *= min(3.0, wall / max(tw, .1)) * 1.02
        inners.append(inner)
        outers.append(outer)
        growns.append(lambda d, ch=chain, g=grow: _loft(_chain_wires(ch, x, y, a, r + g + d, g + d), ruled=True))
    inner = inners[0] if len(inners) == 1 else _multi('fuse', inners[0], inners[1:], 'wnętrza')
    outer = outers[0] if len(outers) == 1 else _multi('fuse', outers[0], outers[1:], 'zewnętrza')
    shell = _boolean('cut', outer, inner, 'ścianka loftu')
    parts = [q for q in _solids(shell) if _volume(q)[0] > 1e-6]
    if nreg == 1:
        shell = _single(shell, 'Obudowa o zmiennym przekroju')
    report.append(('ok', f'Zmienny przekrój: {len(data["stations"])} przekrojów, {nreg} obszar(y); wnętrze {_volume(inner)[0] / 1000:.1f} cm³, '
                         f'materiał {_volume(shell)[0] / 1000:.1f} cm³.'))
    grown = growns[0] if len(growns) == 1 else (lambda d: _multi('fuse', growns[0](d), [q(d) for q in growns[1:]], 'wnętrza'))
    return dict(inner=inner, outer=outer, shell=shell, parts=parts, report=report, stations=data['stations'], frame=(x, y, a), grown=grown)


def _chain_wires(chain, x, y, a, r, d, curves=None, d_hi=None):
    """Przekroje loftu: łańcuch przekrojów + skrajne przekroje powtórzone o d (dno) / d_hi (góra) dalej wzdłuż osi."""
    d_hi = d if d_hi is None else d_hi
    seq = [(chain[0][0] - d, chain[0][1], chain[0][2]), *chain, (chain[-1][0] + d_hi, chain[-1][1], chain[-1][2])]
    return [_section_wire(_support_curve(h, r + ext), x, y, a * s, curves) for s, h, ext in seq]


def _in_convex(q2, hull, margin):
    n = len(hull)
    ok = np.ones(len(q2), bool)
    for i in range(n):
        p0, p1 = hull[i], hull[(i + 1) % n]
        e = p1 - p0
        nn = np.array([e[1], -e[0]]) / max(np.linalg.norm(e), 1e-12)
        ok &= (q2 - p0) @ nn <= margin
    return ok


def _pip(q2, poly):
    """Punkty 2D wewnątrz wielokąta (parzystość przecięć), wektorowo."""
    x, y = q2[:, 0], q2[:, 1]
    inside = np.zeros(len(q2), bool)
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        cond = (y0 > y) != (y1 > y)
        with np.errstate(divide='ignore', invalid='ignore'):
            xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
        inside ^= cond & (x < xi)
    return inside


def _inside_all(curves, pts, frame, margin=0.0, samples=480):
    """Punkty strefy wewnątrz loftu prostokreślnego: przekrój między dwoma przekrojami to dokładnie interpolacja
    liniowa ich krzywych (ten sam parametr) - sprawdzenie 2D w każdej warstwie bez klasyfikatora 3D (gęste próbkowanie
    krzywych B-spline, punkt odsunięty o zapas margin od środka przekroju)."""
    x, y, a = frame
    polys, levels = [], []
    for c in curves:
        t = np.linspace(c.FirstParameter(), c.LastParameter(), samples, endpoint=False)
        q = np.array([[c.Value(float(u)).X(), c.Value(float(u)).Y(), c.Value(float(u)).Z()] for u in t])
        polys.append(np.c_[q @ x, q @ y])
        levels.append(float(q[0] @ a))
    levels = np.array(levels)
    s_pts = pts @ a
    q2 = np.c_[pts @ x, pts @ y]
    if s_pts.min() < levels[0] - 1e-9 or s_pts.max() > levels[-1] + 1e-9:
        return False
    idx = np.clip(np.searchsorted(levels, s_pts), 1, len(levels) - 1)
    for k in range(1, len(levels)):
        m = np.where(idx == k)[0]
        if not len(m):
            continue
        t_ = (s_pts[m] - levels[k - 1]) / max(levels[k] - levels[k - 1], 1e-12)
        for tv in np.unique(np.round(t_, 2)):                          # warstwa w krokach 1 % (przekrój monotoniczny w t)
            sel = m[np.abs(np.round(t_, 2) - tv) < 1e-9]
            for tt in (max(0.0, tv - .005), min(1.0, tv + .005)):
                poly = polys[k - 1] * (1 - tt) + polys[k] * tt
                c = poly.mean(0)
                d = q2[sel] - c
                test = q2[sel] + d / np.maximum(np.linalg.norm(d, axis=1)[:, None], 1e-9) * margin
                if not _pip(test, poly).all():
                    return False
    return True


def _extend_caps(solid, chain, x, y, a, r, d_lo, d_hi):
    """Loft między skrajnymi przekrojami + płaskie zakończenia: graniastosłupy pierwszego i ostatniego przekroju
    wydłużone o d_lo / d_hi wzdłuż osi (strefa dotyka skrajnych płaszczyzn)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    from .enclosure import _single
    from .enclosure_ribs import _multi
    tools = []
    for (s, h, ext), d in ((chain[0], d_lo), (chain[-1], d_hi)):
        if abs(d) < 1e-9:
            continue
        w = _section_wire(_support_curve(h, r + ext), x, y, a * s)
        f = BRepBuilderAPI_MakeFace(w, True).Face()
        tools.append(BRepPrimAPI_MakePrism(f, gp_Vec(*map(float, a * d))).Shape())
    if not tools:
        return solid
    return _single(_multi('fuse', solid, tools, 'zakończenia loftu'), 'Loft z zakończeniami')


def _part_zone(zone, chain, x, y, a, r):
    """Część strefy należąca do jednego łańcucha obszarów (przecięcie z graniastosłupami przekrojów)."""
    from .enclosure import _boolean
    lo, hi = chain[0][0], chain[-1][0]
    pts = np.vstack([h for _s, h, _e in chain])
    h = hull2d(pts)
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    w = _section_wire(_support_curve(h, r), x, y, a * (lo - 1.0))
    prism = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(w, True).Face(), gp_Vec(*map(float, a * (hi - lo + 2.0)))).Shape()
    return _boolean('common', zone, prism, 'obszar strefy')


# ---------------------------------------------------------------------------------------------- 22D: powierzchnie organiczne
def _blur(field, sigma):
    """Rozmycie Gaussa (rozdzielne, przesunięcia tablic) - sigma w komórkach."""
    if sigma <= 1e-6:
        return field.astype(float)
    k = int(math.ceil(3 * sigma))
    w = np.exp(-.5 * (np.arange(-k, k + 1) / sigma) ** 2)
    w /= w.sum()
    out = field.astype(float)
    for ax in range(3):
        pad = [(0, 0)] * 3
        pad[ax] = (k, k)
        f = np.pad(out, pad)
        acc = np.zeros_like(out)
        for i, wi in enumerate(w):
            sl = [slice(None)] * 3
            sl[ax] = slice(i, i + out.shape[ax])
            acc += wi * f[tuple(sl)]
        out = acc
    return out


def _bspline_solid(R, C, th, S, x, y, a):
    """Bryła z siatki promieni R[j, i] (stacje S[j], kąty th[i], środki C[j]): powierzchnia boczna B-spline
    (GeomAPI_PointsToBSplineSurface.Interpolate, okresowa po obwodzie, C2), płaskie dno i pokrywa z krzywych brzegowych
    (MakeFace), zszycie (Sewing) w bryłę. Zwraca (bryła, powierzchnia)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Sewing
    from OCP.BRepLib import BRepLib
    from OCP.GeomAPI import GeomAPI_PointsToBSplineSurface
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    from .enclosure import is_valid
    nv, nu = R.shape
    arr = TColgp_Array2OfPnt(1, nu, 1, nv)
    for j in range(nv):
        for i in range(nu):
            q = C[j] + R[j, i] * (math.cos(th[i]) * x + math.sin(th[i]) * y) + S[j] * a
            arr.SetValue(i + 1, j + 1, gp_Pnt(*map(float, q)))
    ap = GeomAPI_PointsToBSplineSurface()
    ap.Interpolate(arr, True)
    if not ap.IsDone():
        raise kernel.CadError('Rekonstrukcja powierzchni B-spline nie powiodła się - zmień rozdzielczość albo wygładzenie.')
    surf = ap.Surface()
    u0, u1, v0, v1 = surf.Bounds()
    side = BRepBuilderAPI_MakeFace(surf, 1e-7).Face()
    sew = BRepBuilderAPI_Sewing(1e-4)
    sew.Add(side)
    for v, s in ((v0, S[0]), (v1, S[-1])):
        iso = surf.VIso(v)
        w = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(iso).Edge()).Wire()
        f = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(*map(float, a * s)), gp_Dir(*map(float, a))), w, True)
        if not f.IsDone():
            raise kernel.CadError('Nie udało się zamknąć powierzchni organicznej płaskim dnem.')
        sew.Add(f.Face())
    sew.Perform()
    ex = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
    if not ex.More():
        raise kernel.CadError('Powierzchnie organiczne nie tworzą zamkniętej powłoki.')
    solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(ex.Current())).Solid()
    BRepLib.OrientClosedSolid_s(solid)
    if not is_valid(solid):
        raise kernel.CadError('Bryła organiczna nie jest poprawna (BRepCheck) - zwiększ wygładzenie albo zmniejsz liczbę punktów.')
    return solid, surf


def _surface_radius(surf, centres_s, x, y, a, nu, nv, S, C):
    """Promień powierzchni bocznej w siatce (stacja, kąt) z gęstej ewaluacji B-spline (do kontroli zawierania)."""
    u0, u1, v0, v1 = surf.Bounds()
    U = np.linspace(u0, u1, nu * 4, endpoint=False)
    V = np.linspace(v0, v1, nv * 4)
    pts = np.array([[surf.Value(float(u), float(v)).Coord() for u in U] for v in V])
    return pts.reshape(-1, 3)


def organic_enclosure(zone, p, cancel=None):
    """22D: obła obudowa z pola odległości: woksele strefy (pomocniczo), rozmycie Gaussa (łączenie i wygładzanie
    obszarów), promień powierzchni w siatce (stacja wzdłuż osi × kąt) z najdalszego przecięcia promienia, wygładzenie
    siatki promieni i jednolite dosunięcie tak, by obejmowała strefę; rekonstrukcja jako JEDNA powierzchnia B-spline
    (+ płaskie dno i pokrywa), nie tysiące trójkątów. Zewnętrze: ta sama konstrukcja z promieniami + grubość ścianki."""
    from .enclosure import _boolean, _single, _volume
    from .enclosure_cables import Grid, voxelize
    p = dict(dict(smooth=4.0, resolution=0.0, nu=36, nv=10, wall=2.0, axis=[0, 0, 1.0]), **p)
    x, y, a = _axis_frame(np.asarray(p['axis'], float))
    defl = .02
    pts = mesh_points(zone, defl)
    q3 = np.c_[pts @ x, pts @ y, pts @ a]
    lo, hi = q3.min(0), q3.max(0)
    sm = max(float(p['smooth']), 0.0)
    pad = sm + 1.0
    size = hi - lo + 2 * pad
    res = float(p['resolution']) or max(.4, float(np.prod(size) / 150_000) ** (1 / 3))
    E = np.vstack([x, y, a])                                           # świat → układ osi
    import cadquery as cq
    zl = kernel.transformed(cq.Shape.cast(zone), E, np.zeros(3)).wrapped
    grid = Grid(lo - pad, hi + pad, res)
    occ = voxelize(grid, zl)
    if cancel is not None and cancel():
        raise kernel.CadError('Obliczenia przerwane.')
    g = _blur(occ, sm / res / 2)
    mask = (g >= .25) | occ
    nu, nv = max(12, int(p['nu'])), max(4, int(p['nv']))
    S = np.linspace(lo[2], hi[2], nv)
    th = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    C2 = []
    for s in S:                                                        # środki warstw (wygładzone wzdłuż osi)
        m = np.abs(q3[:, 2] - s) <= (hi[2] - lo[2]) / (nv - 1) + 1e-9
        C2.append(q3[m, :2].mean(0) if m.any() else q3[:, :2].mean(0))
    C2 = np.array(C2)
    if nv >= 3:
        C2 = np.vstack([C2[:1], (C2[:-2] + 2 * C2[1:-1] + C2[2:]) / 4, C2[-1:]])
    Rmax = float(np.linalg.norm(size[:2]))
    steps = np.arange(0, Rmax, res / 2)
    R = np.zeros((nv, nu))
    for j, s in enumerate(S):
        for i, t in enumerate(th):
            d = np.array([math.cos(t), math.sin(t)])
            P = C2[j] + steps[:, None] * d
            idx = np.floor((np.c_[P, np.full(len(P), s)] - grid.lo) / res).astype(int)
            ok = np.all((idx >= 0) & (idx < np.array(grid.shape)), axis=1)
            vals = np.zeros(len(P), bool)
            vals[ok] = mask[idx[ok, 0], idx[ok, 1], idx[ok, 2]]
            R[j, i] = steps[np.nonzero(vals)[0].max()] + res if vals.any() else res
    # wymagany promień: najdalszy punkt strefy w sektorze kątowym i warstwie
    rel = q3[:, :2] - np.array([np.interp(q3[:, 2], S, C2[:, 0]), np.interp(q3[:, 2], S, C2[:, 1])]).T
    ang = np.mod(np.arctan2(rel[:, 1], rel[:, 0]), 2 * np.pi)
    rad = np.linalg.norm(rel, axis=1)
    bi = np.clip(np.round(ang / (2 * np.pi / nu)).astype(int) % nu, 0, nu - 1)
    bj = np.clip(np.round((q3[:, 2] - lo[2]) / max(hi[2] - lo[2], 1e-9) * (nv - 1)).astype(int), 0, nv - 1)
    need = np.zeros((nv, nu))
    np.maximum.at(need, (bj, bi), rad)
    # wygładzenie siatki promieni (okresowo po kącie, wzdłuż osi) i jednolite dosunięcie
    k_ = max(1, int(round(sm / max(2 * np.pi * R.mean() / nu, 1e-6))))
    Rs = R.copy()
    for _ in range(k_):
        Rs = (np.roll(Rs, 1, 1) + 2 * Rs + np.roll(Rs, -1, 1)) / 4
        if nv >= 3:
            Rs[1:-1] = (Rs[:-2] + 2 * Rs[1:-1] + Rs[2:]) / 4
    report = []
    for grow in (defl + .2, 1.0, 2.5, 5.0):
        delta = max(0.0, float((need - Rs).max())) + grow
        Ri = Rs + delta
        pad_s = grow + defl
        Sx = S.copy()
        Sx[0], Sx[-1] = S[0] - pad_s, S[-1] + pad_s
        inner, surf = _bspline_solid(Ri, np.c_[C2[:, 0], C2[:, 1]] @ np.vstack([x, y]), th, Sx, x, y, a)
        dense = _surface_radius(surf, None, x, y, a, nu, nv, Sx, C2)
        d3 = np.c_[dense @ x, dense @ y, dense @ a]
        rel_d = d3[:, :2] - np.array([np.interp(d3[:, 2], S, C2[:, 0]), np.interp(d3[:, 2], S, C2[:, 1])]).T
        ang_d = np.mod(np.arctan2(rel_d[:, 1], rel_d[:, 0]), 2 * np.pi)
        fb = 4 * nu
        bi_d = (np.floor(ang_d / (2 * np.pi / fb)).astype(int)) % fb
        bj_d = np.clip(np.floor((d3[:, 2] - Sx[0]) / max(Sx[-1] - Sx[0], 1e-9) * (4 * nv)).astype(int), 0, 4 * nv - 1)
        smin = np.full((4 * nv, fb), np.inf)
        np.minimum.at(smin, (bj_d, bi_d), np.linalg.norm(rel_d, axis=1))
        bi_p = (np.floor(ang / (2 * np.pi / fb)).astype(int)) % fb
        bj_p = np.clip(np.floor((q3[:, 2] - Sx[0]) / max(Sx[-1] - Sx[0], 1e-9) * (4 * nv)).astype(int), 0, 4 * nv - 1)
        lim = smin[bj_p, bi_p]
        for dj in (-1, 1):                                             # sąsiednie przedziały (zapas na dyskretyzację)
            lim = np.minimum(lim, smin[np.clip(bj_p + dj, 0, 4 * nv - 1), bi_p])
        for di in (-1, 1):
            lim = np.minimum(lim, smin[bj_p, (bi_p + di) % fb])
        if np.all(rad <= lim - defl):
            break
    else:
        raise kernel.CadError('Powierzchnia organiczna nie obejmuje strefy - zwiększ liczbę punktów obwodu albo zmniejsz wygładzenie.')
    report.append(('ok', f'Powierzchnia organiczna: 1 powierzchnia B-spline {nu} × {nv} punktów (+ dno i pokrywa), wygładzenie {sm:g} mm, '
                         f'woksele {res:.2f} mm (pomocniczo).'))
    wall = float(p['wall'])
    loc = p.get('local') or {}
    Cw0 = np.c_[C2[:, 0], C2[:, 1]] @ np.vstack([x, y])
    Sx2 = np.r_[Sx[0] - wall - float(loc.get('bottom') or 0), Sx, Sx[-1] + wall + float(loc.get('top') or 0)]
    Cw2 = np.vstack([Cw0[:1], Cw0, Cw0[-1:]])
    dRs = np.gradient(Ri, Sx, axis=0)                                  # nachylenie powierzchni: odsunięcie promieniowe = ścianka / cos
    dRt = (np.roll(Ri, -1, 1) - np.roll(Ri, 1, 1)) / (2 * (2 * np.pi / nu)) / np.maximum(Ri, 1e-6)
    slope = np.sqrt(1 + dRs ** 2 + dRt ** 2)
    fac = 1.0
    for _ in range(4):                                                 # promieniowe odsunięcie poprawiane do grubości normalnej
        R2 = np.vstack([Ri[:1], Ri, Ri[-1:]]) + wall * fac * np.vstack([slope[:1], slope, slope[-1:]])
        outer, _s2 = _bspline_solid(R2, Cw2, th, Sx2, x, y, a)
        tw = min_wall(inner, outer)
        if tw >= wall - 1e-3:
            break
        fac *= min(1.5, wall / max(tw, .1)) * 1.01
    shell = _single(_boolean('cut', outer, inner, 'ścianka organiczna'), 'Obudowa organiczna')
    report.append(('ok', f'Wnętrze {_volume(inner)[0] / 1000:.1f} cm³, materiał {_volume(shell)[0] / 1000:.1f} cm³.'))
    Cw = np.c_[C2[:, 0], C2[:, 1]] @ np.vstack([x, y])

    def grown(d):
        Sg = Sx.copy()
        Sg[0], Sg[-1] = Sx[0] - d, Sx[-1] + d
        return _bspline_solid(Ri + d, Cw, th, Sg, x, y, a)[0]
    return dict(inner=inner, outer=outer, shell=shell, report=report, surface=surf, grid=(Ri, C2, th, Sx), frame=(x, y, a), grown=grown)


# ---------------------------------------------------------------------------------------------- 22E: ścianki i podział
WALL_METHODS = ('construct', 'offset')
WALL_LABELS = {'construct': 'Ścianka: z odsuniętej konstrukcji (przekroje / płaszczyzny / promienie)',
               'offset': 'Ścianka: odsunięcie powierzchni wnętrza (MakeOffsetShape)'}
JOINTS = ('flat', 'lap')
JOINT_LABELS = {'flat': 'Połączenie płaskie', 'lap': 'Połączenie na zakładkę (wypust w podstawie)'}


def thick_wall(inner, wall, local=None, axis=None):
    """Zewnętrze przez odsunięcie powierzchni wnętrza o grubość ścianki (BRepOffset_MakeOffset, łączenie łukami);
    local - {'bottom': d, 'top': d}: inna grubość płaskiego dna / pokrywy (SetOffsetOnFace dla ścian prostopadłych do osi).
    Gdy OCCT nie zbuduje poprawnej bryły - CadError (bez cichej zmiany metody)."""
    from OCP.BRepOffset import BRepOffset_MakeOffset, BRepOffset_Skin
    from OCP.GeomAbs import GeomAbs_Arc
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from .enclosure import _solids, _volume, is_valid
    mk = BRepOffset_MakeOffset()
    mk.Initialize(inner, float(wall), 1e-4, BRepOffset_Skin, False, False, GeomAbs_Arc, False, False)
    if local and axis is not None:
        a = _unit(axis)
        ex = TopExp_Explorer(inner, TopAbs_FACE)
        while ex.More():
            f = TopoDS.Face_s(ex.Current())
            ad = BRepAdaptor_Surface(f)
            if ad.GetType() == GeomAbs_Plane:
                n = np.array(ad.Plane().Axis().Direction().Coord())
                from OCP.TopAbs import TopAbs_REVERSED
                if f.Orientation() == TopAbs_REVERSED:
                    n = -n
                key = 'top' if n @ a > .999 else ('bottom' if n @ a < -.999 else None)
                if key and float(local.get(key) or 0) > 0:
                    mk.SetOffsetOnFace(f, float(local[key]))
            ex.Next()
    mk.MakeOffsetShape()
    if not mk.IsDone():
        raise kernel.CadError('Odsunięcie powierzchni wnętrza (MakeOffsetShape) nie powiodło się - wybierz ściankę z konstrukcji.')
    sol = [s for s in _solids(mk.Shape()) if _volume(s)[0] > 1e-6]
    if len(sol) != 1:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
        from OCP.TopAbs import TopAbs_SHELL
        ex = TopExp_Explorer(mk.Shape(), TopAbs_SHELL)
        sol = [BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(ex.Current())).Solid()] if ex.More() else []
    if not sol:
        raise kernel.CadError('Odsunięcie powierzchni wnętrza nie dało bryły - wybierz ściankę z konstrukcji.')
    from OCP.BRepLib import BRepLib
    s = TopoDS.Solid_s(sol[0])
    BRepLib.OrientClosedSolid_s(s)
    if not is_valid(s) or _volume(s)[0] <= _volume(inner)[0]:
        raise kernel.CadError('Odsunięta ścianka nie jest poprawną bryłą - wybierz ściankę z konstrukcji albo zmień grubość.')
    return s


def section_face(solid, origin, normal):
    """Ściana przekroju bryły płaszczyzną: krawędzie BRepAlgoAPI_Section połączone w kontury (ShapeAnalysis_FreeBounds),
    największy kontur zewnętrzny, pozostałe jako otwory."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopTools import TopTools_HSequenceOfShape
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    import cadquery as cq
    pl = gp_Pln(gp_Pnt(*map(float, origin)), gp_Dir(*map(float, normal)))
    sec = BRepAlgoAPI_Section(solid, pl, False)
    sec.Build()
    edges = TopTools_HSequenceOfShape()
    ex = TopExp_Explorer(sec.Shape(), TopAbs_EDGE)
    while ex.More():
        edges.Append(ex.Current())
        ex.Next()
    if edges.Length() == 0:
        raise kernel.CadError('Płaszczyzna podziału nie przecina wnętrza obudowy.')
    wires = TopTools_HSequenceOfShape()
    ShapeAnalysis_FreeBounds.ConnectEdgesToWires_s(edges, 1e-5, False, wires)
    ws = []
    for i in range(1, wires.Length() + 1):
        w = TopoDS.Wire_s(wires.Value(i))
        area = abs(cq.Face.makeFromWires(cq.Wire(w)).Area())
        ws.append((area, w))
    ws.sort(key=lambda t: -t[0])
    mk = BRepBuilderAPI_MakeFace(pl, ws[0][1], True)
    for _a, w in ws[1:]:
        mk.Add(TopoDS.Wire_s(w.Reversed()))
    face = mk.Face()
    from OCP.ShapeFix import ShapeFix_Face
    fx = ShapeFix_Face(face)
    fx.Perform()
    return fx.Face()


def _prism_face(face, vec, shift=None):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    if shift is not None:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.gp import gp_Trsf
        t = gp_Trsf()
        t.SetTranslation(gp_Vec(*map(float, shift)))
        face = BRepBuilderAPI_Transform(face, t, True).Shape()
        vec = np.asarray(vec, float) - np.asarray(shift, float)
    return BRepPrimAPI_MakePrism(face, gp_Vec(*map(float, vec))).Shape()


def split_parts(shell, inner, grown, axis, p):
    """Podział skorupy płaszczyzną prostopadłą do osi (położenie w % wysokości wnętrza) na podstawę i pokrywę;
    zakładka: wypust w wewnętrznej połowie ścianki podstawy (wysokość h), w pokrywie wycięcie z luzem g.
    grown(d) - wnętrze powiększone o d (ta sama konstrukcja co bryła). Zwraca [(nazwa, bryła)] i raport."""
    from .enclosure import _boolean, _plane_split, _single
    a = _unit(axis)
    pts = mesh_points(inner, .05) @ a
    lo, hi = float(pts.min()), float(pts.max())
    t = min(.95, max(.05, float(p.get('split_at', 50.0)) / 100.0))
    s = lo + (hi - lo) * t
    base, lid = _plane_split(shell, a * s, a, 1e4)
    report = [('ok', f'Podział na wysokości {s - lo:.1f} mm od dna wnętrza.')]
    if p.get('joint') == 'lap':
        w = float(p.get('wall', 2.0))
        h = float(p.get('lip', 3.0))
        g = float(p.get('lip_gap', .2))
        if h <= 0 or w / 2 - g <= .2:
            raise kernel.CadError('Zakładka: za cienka ścianka dla wypustu z luzem - zwiększ grubość albo zmniejsz luz.')
        mid, mid_g = grown(w / 2), grown(w / 2 + g)
        # wypust i wycięcie jako graniastosłupy przekrojów w płaszczyźnie podziału - ściany równoległe do osi, więc
        # pokrywa zsuwa się prosto także przy pochylonych ściankach (brak podcięć)
        f_in, f_mid, f_mid_g = (section_face(q, a * (s + 1e-3), a) for q in (grown(.05), mid, mid_g))
        ring = _boolean('cut', f_mid, f_in, 'pierścień wypustu')                 # 2D w płaszczyźnie podziału
        from OCP.TopAbs import TopAbs_FACE
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS
        ex = TopExp_Explorer(ring, TopAbs_FACE)
        rf = []
        while ex.More():
            rf.append(TopoDS.Face_s(ex.Current()))
            ex.Next()
        if len(rf) != 1:
            raise kernel.CadError('Przekrój wypustu nie jest jednym pierścieniem - zmień położenie podziału.')
        lip = _prism_face(rf[0], a * h, shift=-a * .3)                        # zachodzi 0,3 mm w ściankę podstawy
        base = _single(_boolean('fuse', base, lip, 'podstawa z wypustem'), 'Podstawa z zakładką')
        pocket = _prism_face(f_mid_g, a * (h + g), shift=-a * 1e-2)
        lid = _single(_boolean('cut', lid, pocket, 'pokrywa z wycięciem'), 'Pokrywa z zakładką')
        report.append(('ok', f'Zakładka: wypust {h:g} mm, grubość {w / 2:g} mm, luz {g:g} mm.'))
    return [('Podstawa', base), ('Pokrywa', lid)], report, s


# ---------------------------------------------------------------------------------------------- 22F: walidacja
def validate(parts, components, p, axis=None, zone=None):
    """Kontrola wyniku: poprawność B-Rep, jedna bryła na część, brak wspólnej objętości z komponentami, odstęp od
    komponentów ≥ zadany (DistShapeShape), najmniejsza grubość ścianki (odległość powierzchni wnętrza od zewnętrza),
    zdejmowanie pokrywy wzdłuż osi (ciągła kontrola ruchu). Zwraca listę (poziom, tekst)."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from .enclosure import _boolean, _solids, _volume, is_valid
    out = []
    clear = float(p.get('clearance', 2.0))
    for name, sh in parts:
        sol = [s for s in _solids(sh) if _volume(s)[0] > 1e-6]
        if not is_valid(sh) or len(sol) != 1:
            out.append(('error', f'{name}: niepoprawna bryła B-Rep albo kilka fragmentów ({len(sol)}).'))
        if zone is not None:                                           # strefa = komponenty ⊕ odstęp: część nie może w nią wchodzić
            v = _volume(_boolean('common', zone, sh, 'strefa a ścianka'))[0]
            if v > 1e-6:
                bad = [cn for _ci, cn, cs in components if _volume(_boolean('common', cs.wrapped if hasattr(cs, 'wrapped') else cs, sh, 'kolizja'))[0] > 1e-6]
                out.append(('error', f'{name} koliduje z {", ".join(bad)}.') if bad else ('warning', f'{name}: ścianka wchodzi w strefę odstępu ({v:.3f} mm³).'))
            continue
        for cid, cname, cs in components:
            c = cs.wrapped if hasattr(cs, 'wrapped') else cs
            if _volume(_boolean('common', c, sh, 'kolizja'))[0] > 1e-6:
                out.append(('error', f'{name} koliduje z {cname}.'))
                continue
            d = BRepExtrema_DistShapeShape(c, sh)
            d.Perform()
            if d.IsDone() and d.Value() < clear - 1e-3:
                out.append(('warning', f'{name}: odstęp od {cname} {d.Value():.2f} mm < {clear:g} mm.'))
    if not any(l == 'error' for l, _t in out):
        out.append(('ok', f'Bryły poprawne, komponenty bez kolizji, odstęp ≥ {clear:g} mm.'))
    names = dict(parts)
    if 'Pokrywa' in names and 'Podstawa' in names and axis is not None:
        # zdejmowanie pokrywy: wypust i wycięcie to graniastosłupy wzdłuż osi, a pokrywa leży nad płaszczyzną podziału -
        # ruch wzdłuż osi jest wolny z konstrukcji; dodatkowo sprawdzenie części wspólnej w kilku położeniach
        a = _unit(axis)
        lid, base = names['Pokrywa'], names['Podstawa']
        import cadquery as cq
        steps = [.1, float(p.get('lip', 3.0)) / 2, float(p.get('lip', 3.0)) + float(p.get('lip_gap', .2)) + .1] if p.get('joint') == 'lap' else [.1]
        hit = None
        if not (_planar(lid) and _planar(base)):                      # powierzchnie B-spline: Boolean w ruchu bardzo kosztowny
            out.append(('ok', 'Pokrywa zdejmuje się wzdłuż osi - z konstrukcji (płaski podział, wypust i wycięcie równoległe do osi).'))
            return out
        for u in steps:
            moved = kernel.transformed(cq.Shape.cast(lid), np.eye(3), a * u).wrapped
            if _volume(_boolean('common', base, moved, 'zdejmowanie pokrywy'))[0] > 1e-4:
                hit = u
                break
        out.append(('error', f'Pokrywa zaczepia o podstawę po {hit:.1f} mm zdejmowania.') if hit is not None else
                   ('ok', 'Pokrywa zdejmuje się wzdłuż osi (połączenie równoległe do osi; sprawdzone położenia ' + ', '.join(f'{u:g}' for u in steps) + ' mm).'))
    return out


def _planar(shape):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        if BRepAdaptor_Surface(TopoDS.Face_s(ex.Current())).GetType() != GeomAbs_Plane:
            return False
        ex.Next()
    return True


def min_wall(inner, outer):
    """Najmniejsza grubość ścianki: odległość powierzchni wnętrza od powierzchni zewnętrza (DistShapeShape powłok)."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    shells = []
    for s in (inner, outer):
        ex = TopExp_Explorer(s, TopAbs_SHELL)
        shells.append(ex.Current())
    d = BRepExtrema_DistShapeShape(shells[0], shells[1])
    d.Perform()
    return float(d.Value()) if d.IsDone() else 0.0


# ---------------------------------------------------------------------------------------------- całość (22A-22F)
FIT_MODES = ('zone', 'hull', 'sections', 'organic')


def fit(components, p, cancel=None):
    """Pełny przebieg: strefa (22A) → bryła wnętrza i zewnętrza wybraną metodą (22B / 22C / 22D; metoda nigdy nie jest
    zmieniana samoczynnie) → ścianki (22E: konstrukcja albo odsunięcie, grubość lokalna dna / pokrywy) → podział
    z połączeniem (22E) → walidacja (22F). Zwraca dict(parts=[(nazwa, bryła)], report, ...)."""
    from .enclosure import _boolean, _single, _volume
    from .enclosure_optimize import _points
    p = dict(DEFAULTS, **p)
    mode = p.get('mode', 'zone')
    if mode not in FIT_MODES:
        raise kernel.CadError('Nieznany tryb dopasowania.')
    res = analyse(components, p, cancel)
    if mode == 'zone':
        return dict(res, parts=[('Strefa ochronna', res['zone'])])
    axis = _unit(p.get('axis') or [0, 0, 1.0])
    wall = float(p.get('wall', 2.0))
    local = dict(bottom=float(p.get('wall_bottom', 0.0) or 0.0), top=float(p.get('wall_top', 0.0) or 0.0))
    q = dict(p, axis=list(axis), local=local)
    if mode == 'hull':
        h = hull_enclosure(res['zone'], np.vstack([_points(r) for r in res['regions']]), wall, int(p.get('directions', 160)), cancel, local, axis)
    elif mode == 'sections':
        h = section_enclosure(res['zone'], q, cancel)
    else:
        h = organic_enclosure(res['zone'], q, cancel)
    report = res['report'] + h['report']
    inner, outer = h['inner'], h['outer']
    if p.get('wall_method') == 'offset':
        outer = thick_wall(inner, wall, local, axis)
        h['shell'] = _single(_boolean('cut', outer, inner, 'ścianka odsunięta'), 'Obudowa (odsunięta ścianka)')
        report.append(('ok', f'Ścianka z odsunięcia powierzchni wnętrza (MakeOffsetShape): materiał {_volume(h["shell"])[0] / 1000:.1f} cm³.'))
    shell = h['shell']
    tw = min_wall(inner, outer)
    report.append(('ok' if tw >= wall - 1e-3 else 'warning', f'Najmniejsza grubość ścianki {tw:.2f} mm (zadana {wall:g} mm).'))
    if p.get('split'):
        parts, rep2, _s = split_parts(shell, inner, h['grown'], axis, p)
        report += rep2
    else:
        multi = h.get('parts') or [shell]
        parts = [('Obudowa dopasowana' if len(multi) == 1 else f'Obudowa dopasowana {n + 1}', s_) for n, s_ in enumerate(multi)]
    report += validate(parts, components, p, axis if p.get('split') else None, res['zone'])
    return dict(res, fit=h, parts=parts, report=report, min_wall=tw, inner=inner, outer=outer, material=sum(_volume(s_)[0] for _n, s_ in parts))
