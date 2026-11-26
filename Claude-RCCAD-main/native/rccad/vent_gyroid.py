"""Wentylacja - przestrzenna struktura Gyroid 3D.

Pole niejawne (okresowe): f(x, y, z) = sin(x)cos(y) + sin(y)cos(z) + sin(z)cos(x) = c, z wielkością komórki, skalą
w osiach, orientacją (obroty) i fazą. Struktura „ścianowa” |f - c| ≤ grubość (w jednostkach pola, przeliczana z mm przez
średni gradient) albo „sieciowa” f ≤ c (porowatość). Ograniczenie do prostopadłościanu (część wspólna z polem odległości
ramki - struktura zamyka się płaskimi ścianami) i do bryły (Boolean).

Siatka wokseli i triangulacja (marching tetrahedra) są wyłącznie etapem pomocniczym. Wynik to poprawna bryła B-Rep:
powłoka z trójkątów połączonych topologicznie (BRepBuilderAPI_MakeShapeOnMesh), scalenie współpłaszczyznowych ścian
(ShapeUpgrade_UnifySameDomain), kontrola BRepCheck. To bryła FASETOWA (płaskie ściany) o dokładności = krok siatki -
raport podaje liczbę ścian; przy zbyt dużej liczbie ścian albo niepowodzeniu rekonstrukcji - komunikat zamiast
niepoprawnej geometrii. Nie jest to gładka reprezentacja NURBS."""
from __future__ import annotations

import math

import numpy as np

from . import kernel

DEFAULTS = dict(cell=10.0, thickness=1.2, iso=0.0, porosity=.5, kind='sheet', sx=1.0, sy=1.0, sz=1.0, rx=0.0, ry=0.0, rz=0.0, phase=0.0,
                accuracy=8, max_faces=60000, mode='remove')
KINDS = ('sheet', 'network')
KIND_LABELS = {'sheet': 'Gyroid ścianowy (|f - c| ≤ grubość)', 'network': 'Gyroid sieciowy (f ≤ c)'}
MODES = ('remove', 'separate')
MODE_LABELS = {'remove': 'Perforacja - usunięcie materiału', 'separate': 'Osobna bryła struktury'}

# 6 czworościanów sześcianu (wspólna przekątna 0-6), wierzchołki sześcianu w kolejności bitów (x, y, z)
_TETS = ((0, 5, 1, 6), (0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6))
_CORNERS = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]])


def _rotation(rx, ry, rz):
    a, b, c = (math.radians(v) for v in (rx, ry, rz))
    Rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    Ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    Rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def field(P, p):
    """Wartość pola (ujemna = materiał struktury) w punktach P (n×3, mm)."""
    p = dict(DEFAULTS, **p)
    k = 2 * math.pi / max(float(p['cell']), 1e-3)
    R = _rotation(p['rx'], p['ry'], p['rz'])
    Q = (np.asarray(P, float) @ R) * k * np.array([1 / float(p['sx']), 1 / float(p['sy']), 1 / float(p['sz'])]) + float(p['phase'])
    x, y, z = Q[:, 0], Q[:, 1], Q[:, 2]
    f = np.sin(x) * np.cos(y) + np.sin(y) * np.cos(z) + np.sin(z) * np.cos(x)
    if p['kind'] == 'network':
        c = float(p['iso']) if p.get('iso') else 1.5 * (2 * float(p['porosity']) - 1)
        return f - c
    grad = math.sqrt(2) * k                                             # średnia wielkość gradientu pola (≈ √2·k)
    tau = float(p['thickness']) / 2 * grad * .75
    return np.abs(f - float(p['iso'])) - tau


def _box_sdf(P, lo, hi):
    c, h = (lo + hi) / 2, (hi - lo) / 2
    q = np.abs(P - c) - h
    return np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(1), 0)


def mesh(lo, hi, p, cancel=None):
    """Triangulacja powierzchni struktury w ramce lo-hi (marching tetrahedra): (wierzchołki, trójkąty)."""
    p = dict(DEFAULTS, **p)
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    step = float(p['cell']) / max(3, int(p['accuracy']))
    pad = step * 1.5
    xs, ys, zs = (np.arange(lo[i] - pad, hi[i] + pad + step, step) for i in range(3))
    n = len(xs) * len(ys) * len(zs)
    if n > 6_000_000:
        raise kernel.CadError('Gyroid 3D: za dużo punktów siatki - zwiększ komórkę albo zmniejsz dokładność.')
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    P = np.c_[X.ravel(), Y.ravel(), Z.ravel()]
    F = np.maximum(field(P, p), _box_sdf(P, lo, hi)).reshape(X.shape)   # zamknięcie strukturą ramki
    F[np.abs(F) < 1e-9] = 1e-9
    nx, ny, nz = F.shape
    I, J, K = np.meshgrid(np.arange(nx - 1), np.arange(ny - 1), np.arange(nz - 1), indexing='ij')
    base = np.c_[I.ravel(), J.ravel(), K.ravel()]
    verts, tris = [], []
    vid = {}

    def edge_point(a, b):
        key = (min(a, b), max(a, b))
        if key in vid:
            return vid[key]
        ia, ib = np.unravel_index(a, F.shape), np.unravel_index(b, F.shape)
        fa, fb = F[ia], F[ib]
        t = fa / (fa - fb)
        pa = np.array([xs[ia[0]], ys[ia[1]], zs[ia[2]]])
        pb = np.array([xs[ib[0]], ys[ib[1]], zs[ib[2]]])
        vid[key] = len(verts)
        verts.append(pa + (pb - pa) * t)
        return vid[key]
    flat = F.ravel()
    lin = lambda c: (c[:, 0] * ny + c[:, 1]) * nz + c[:, 2]
    corner_idx = [lin(base + _CORNERS[k]) for k in range(8)]
    neg_any = np.zeros(len(base), bool)
    pos_any = np.zeros(len(base), bool)
    for ci in corner_idx:
        neg_any |= flat[ci] < 0
        pos_any |= flat[ci] > 0
    cubes = np.nonzero(neg_any & pos_any)[0]
    if len(cubes) * 2 > int(p['max_faces']) * 3:
        raise kernel.CadError(f'Gyroid 3D: rekonstrukcja dałaby ponad {int(p["max_faces"])} ścian - zwiększ komórkę, zmniejsz dokładność albo obszar.')
    for nn, cu in enumerate(cubes):
        if cancel is not None and nn % 5000 == 0 and cancel():
            raise kernel.CadError('Obliczenia przerwane.')
        ids = [int(corner_idx[k][cu]) for k in range(8)]
        for tet in _TETS:
            v = [ids[k] for k in tet]
            neg = [x for x in v if flat[x] < 0]
            pos = [x for x in v if flat[x] > 0]
            if not neg or not pos:
                continue
            if len(neg) == 1 or len(pos) == 1:
                a = neg[0] if len(neg) == 1 else pos[0]
                others = pos if len(neg) == 1 else neg
                tri = [edge_point(a, o) for o in others]
                tris.append((tri, a, len(neg) == 1))
            else:
                a0, a1 = neg
                b0, b1 = pos
                q = [edge_point(a0, b0), edge_point(a0, b1), edge_point(a1, b1), edge_point(a1, b0)]
                tris.append(([q[0], q[1], q[2]], a0, True))
                tris.append(([q[0], q[2], q[3]], a0, True))
    V = np.array(verts, float)
    out = []
    for tri, ref, ref_neg in tris:                                      # orientacja: normalna od materiału (f < 0) na zewnątrz
        a, b, c = V[tri[0]], V[tri[1]], V[tri[2]]
        nrm = np.cross(b - a, c - a)
        if np.linalg.norm(nrm) < 1e-14:
            continue
        ir = np.unravel_index(ref, F.shape)
        pr = np.array([xs[ir[0]], ys[ir[1]], zs[ir[2]]])
        towards = (a + b + c) / 3 - pr                                  # od wierzchołka odniesienia
        outward = towards if ref_neg else -towards
        out.append(tri if float(nrm @ outward) > 0 else [tri[0], tri[2], tri[1]])
    return V, np.array(out, int)


def brep(V, T):
    """Powłoka B-Rep z trójkątów (topologia wspólnych krawędzi) → bryła; scalenie współpłaszczyznowych ścian."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeShapeOnMesh, BRepBuilderAPI_MakeSolid
    from OCP.BRepLib import BRepLib
    from OCP.Poly import Poly_Triangulation, Poly_Triangle
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.TopExp import TopExp_Explorer
    from OCP.gp import gp_Pnt
    from .enclosure import _solids, _volume, is_valid
    if not len(T):
        raise kernel.CadError('Gyroid 3D: struktura pusta w tym obszarze - zmień parametry.')
    # rozłączne fragmenty struktury - osobne powłoki (każda zamknięta) połączone przez wspólne krawędzie trójkątów
    parent = list(range(len(T)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    first = {}
    for n, t in enumerate(T):
        for a_, b_ in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            k = (min(a_, b_), max(a_, b_))
            if k in first:
                parent[find(n)] = find(first[k])
            else:
                first[k] = n
    groups = {}
    for n in range(len(T)):
        groups.setdefault(find(n), []).append(n)
    solids = []
    from OCP.BRep import BRep_Builder as _B
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS_Shell
    for idx in groups.values():
        Tg = T[idx]
        used = np.unique(Tg)
        remap = {int(v): i for i, v in enumerate(used)}
        tri = Poly_Triangulation(len(used), len(Tg), False)
        for i, v in enumerate(used):
            tri.SetNode(i + 1, gp_Pnt(*map(float, V[v])))
        for i, t in enumerate(Tg):
            tri.SetTriangle(i + 1, Poly_Triangle(remap[int(t[0])] + 1, remap[int(t[1])] + 1, remap[int(t[2])] + 1))
        mk = BRepBuilderAPI_MakeShapeOnMesh(tri)
        mk.Build()
        if not mk.IsDone():
            raise kernel.CadError('Gyroid 3D: nie udało się zbudować powłoki z triangulacji.')
        bld0 = _B()
        shell = TopoDS_Shell()
        bld0.MakeShell(shell)
        ex = TopExp_Explorer(mk.Shape(), TopAbs_FACE)
        while ex.More():
            bld0.Add(shell, ex.Current())
            ex.Next()
        shell.Closed(True)
        s0 = BRepBuilderAPI_MakeSolid(shell).Solid()
        BRepLib.OrientClosedSolid_s(s0)
        solids.append(s0)
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    if len(solids) == 1:
        shape = solids[0]
    else:
        comp = TopoDS_Compound()
        bld = BRep_Builder()
        bld.MakeCompound(comp)
        for s in solids:
            bld.Add(comp, s)
        shape = comp
    un = ShapeUpgrade_UnifySameDomain(shape, True, True, False)
    un.Build()
    shape = un.Shape()
    if not is_valid(shape):
        raise kernel.CadError('Gyroid 3D: rekonstrukcja nie dała poprawnej bryły B-Rep dla tych parametrów - zwiększ dokładność albo komórkę.')
    if sum(_volume(s)[0] for s in _solids(shape)) <= 0:
        raise kernel.CadError('Gyroid 3D: bryła o zerowej objętości.')
    return shape


def build(target, p, box=None, cancel=None):
    """Gyroid 3D w bryle target (TopoDS): mode 'remove' - bryła z usuniętą strukturą, 'separate' - osobna bryła
    struktury (część wspólna z bryłą). box - (lo, hi) ograniczenie (domyślnie ramka bryły). Zwraca (bryła, raport)."""
    import cadquery as cq
    from .enclosure import _boolean, _volume
    p = dict(DEFAULTS, **p)
    bb = cq.Shape.cast(target).BoundingBox()
    lo = np.array([bb.xmin, bb.ymin, bb.zmin]) if box is None else np.asarray(box[0], float)
    hi = np.array([bb.xmax, bb.ymax, bb.zmax]) if box is None else np.asarray(box[1], float)
    V, T = mesh(lo, hi, p, cancel)
    g = brep(V, T)
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    nf, ex = 0, TopExp_Explorer(g, TopAbs_FACE)
    while ex.More():
        nf += 1
        ex.Next()
    step = float(p['cell']) / max(3, int(p['accuracy']))
    report = [('ok', f'Gyroid 3D: bryła B-Rep fasetowa - {nf} płaskich ścian, dokładność odwzorowania powierzchni ≈ {step:.2f} mm (krok siatki pomocniczej).')]
    if p['mode'] == 'separate':
        res = _boolean('common', target, g, 'struktura Gyroid')
    else:
        res = _boolean('cut', target, g, 'perforacja Gyroid')
    v0, v1 = _volume(target)[0], _volume(res)[0]
    report.append(('ok', f'Objętość: {v1:.1f} mm³ ({100 * v1 / max(v0, 1e-9):.0f} % bryły).'))
    return res, report
