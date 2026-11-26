"""Wentylacja - geometria 2D w dziedzinie wzoru (współrzędne obszaru, mm): przynależność do wielokątów, odległości
od brzegów, siatka przestrzenna do wyszukiwania sąsiadów, izolinie (marching squares), próbkowanie Poissona,
pogrubianie łamanych (szczeliny wzdłuż krzywych), przycinanie profili (Boolean OCC w płaszczyźnie dziedziny)."""
from __future__ import annotations

import math

import numpy as np

from . import kernel


def pip(points, poly):
    """Punkty wewnątrz wielokąta (parzystość przecięć), wektorowo."""
    q = np.asarray(points, float).reshape(-1, 2)
    poly = np.asarray(poly, float)
    x, y = q[:, 0], q[:, 1]
    inside = np.zeros(len(q), bool)
    x0, y0 = poly[:, 0], poly[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
    for i in range(len(poly)):
        cond = (y0[i] > y) != (y1[i] > y)
        if not cond.any():
            continue
        with np.errstate(divide='ignore', invalid='ignore'):
            xi = x0[i] + (y - y0[i]) * (x1[i] - x0[i]) / (y1[i] - y0[i])
        inside ^= cond & (x < xi)
    return inside


def seg_dist(points, a, b):
    """Odległość punktów od odcinków a[i]-b[i] (macierz punkty × odcinki)."""
    P = np.asarray(points, float).reshape(-1, 1, 2)
    a = np.asarray(a, float)[None]
    d = np.asarray(b, float)[None] - a
    L2 = np.maximum((d ** 2).sum(-1), 1e-18)
    t = np.clip(((P - a) * d).sum(-1) / L2, 0, 1)
    return np.linalg.norm(P - (a + t[..., None] * d), axis=-1)


def dist_to_poly(points, poly, chunk=4000):
    """Najmniejsza odległość punktów od brzegu wielokąta."""
    P = np.asarray(points, float).reshape(-1, 2)
    poly = np.asarray(poly, float)
    a, b = poly, np.roll(poly, -1, axis=0)
    out = np.empty(len(P))
    for i in range(0, len(P), chunk):
        out[i:i + chunk] = seg_dist(P[i:i + chunk], a, b).min(1)
    return out


def poly_dist(A, B):
    """Najmniejsza odległość dwóch wielokątów (0 gdy się przecinają albo jeden zawiera drugi)."""
    if pip(A[:1], B).any() or pip(B[:1], A).any():
        return 0.0
    d1 = seg_dist(A, B, np.roll(B, -1, 0)).min()
    d2 = seg_dist(B, A, np.roll(A, -1, 0)).min()
    d = float(min(d1, d2))
    if d < 1e-9:
        return 0.0
    if _edges_cross(A, B):
        return 0.0
    return d


def _edges_cross(A, B):
    a0, a1 = A, np.roll(A, -1, 0)
    b0, b1 = B, np.roll(B, -1, 0)

    def orient(p, q, r):
        return (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0])
    p, q = a0[:, None], a1[:, None]
    r, s = b0[None], b1[None]
    o1, o2 = orient(p, q, r), orient(p, q, s)
    o3, o4 = orient(r, s, p), orient(r, s, q)
    return bool(np.any((o1 * o2 < 0) & (o3 * o4 < 0)))


def area(poly):
    x, y = poly[:, 0], poly[:, 1]
    return .5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


class Region:
    """Obszar generowania w dziedzinie: kontury zewnętrzne (wielokąty) i otwory; zapytania wektorowe."""

    def __init__(self, outers, holes=()):
        self.outers = [np.asarray(o, float) for o in outers if len(o) >= 3]
        self.holes = [np.asarray(h, float) for h in holes if len(h) >= 3]
        if not self.outers:
            raise kernel.CadError('Obszar wentylacji jest pusty.')
        pts = np.vstack(self.outers)
        self.lo, self.hi = pts.min(0), pts.max(0)

    def contains(self, P):
        P = np.asarray(P, float).reshape(-1, 2)
        ins = np.zeros(len(P), bool)
        for o in self.outers:
            ins ^= pip(P, o)
        for h in self.holes:
            ins &= ~pip(P, h)
        return ins

    def edge_dist(self, P):
        """Odległość od brzegu zewnętrznego (konturów obszaru)."""
        P = np.asarray(P, float).reshape(-1, 2)
        return np.min([dist_to_poly(P, o) for o in self.outers], axis=0)

    def hole_dist(self, P):
        P = np.asarray(P, float).reshape(-1, 2)
        if not self.holes:
            return np.full(len(P), np.inf)
        return np.min([dist_to_poly(P, h) for h in self.holes], axis=0)

    def area(self):
        return sum(abs(area(o)) for o in self.outers) - sum(abs(area(h)) for h in self.holes)

    def centroid(self):
        o = max(self.outers, key=lambda q: abs(area(q)))
        x, y = o[:, 0], o[:, 1]
        x1, y1 = np.roll(x, -1), np.roll(y, -1)
        cr = x * y1 - x1 * y
        A = cr.sum() / 2
        if abs(A) < 1e-12:
            return o.mean(0)
        return np.array([((x + x1) * cr).sum() / (6 * A), ((y + y1) * cr).sum() / (6 * A)])


class Hash:
    """Siatka przestrzenna 2D (komórki o boku cell) - kandydaci do sprawdzenia mostków / kolizji."""

    def __init__(self, cell):
        self.cell = max(float(cell), 1e-6)
        self.cells = {}

    def _keys(self, lo, hi):
        i0, j0 = np.floor(np.asarray(lo) / self.cell).astype(int)
        i1, j1 = np.floor(np.asarray(hi) / self.cell).astype(int)
        return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]

    def add(self, idx, lo, hi):
        for k in self._keys(lo, hi):
            self.cells.setdefault(k, []).append(idx)

    def near(self, lo, hi):
        out = set()
        for k in self._keys(lo, hi):
            out.update(self.cells.get(k, ()))
        return out


def contours(F, xs, ys, level):
    """Izolinie F = level (marching squares, interpolacja liniowa): lista łamanych (zamknięte - ostatni punkt = pierwszy)."""
    F = np.asarray(F, float) - level
    nx, ny = F.shape
    segs = []
    for i in range(nx - 1):
        for j in range(ny - 1):
            v = (F[i, j], F[i + 1, j], F[i + 1, j + 1], F[i, j + 1])
            idx = (v[0] > 0) | ((v[1] > 0) << 1) | ((v[2] > 0) << 2) | ((v[3] > 0) << 3)
            if idx in (0, 15):
                continue
            P = ((xs[i], ys[j]), (xs[i + 1], ys[j]), (xs[i + 1], ys[j + 1]), (xs[i], ys[j + 1]))

            def edge(k):
                a, b = k, (k + 1) % 4
                t = v[a] / (v[a] - v[b]) if v[a] != v[b] else .5
                return (P[a][0] + t * (P[b][0] - P[a][0]), P[a][1] + t * (P[b][1] - P[a][1]))
            table = {1: [(3, 0)], 2: [(0, 1)], 3: [(3, 1)], 4: [(1, 2)], 5: [(3, 2), (1, 0)], 6: [(0, 2)], 7: [(3, 2)], 8: [(2, 3)],
                     9: [(2, 0)], 10: [(2, 1), (0, 3)], 11: [(2, 1)], 12: [(1, 3)], 13: [(1, 0)], 14: [(0, 3)]}
            for a, b in table[idx]:
                segs.append((edge(a), edge(b)))
    # łączenie odcinków w łamane (w obu kierunkach)
    key = lambda p: (round(p[0], 7), round(p[1], 7))
    ends = {}
    for n, (a, b) in enumerate(segs):
        ends.setdefault(key(a), []).append(n)
        ends.setdefault(key(b), []).append(n)
    used = np.zeros(len(segs), bool)
    out = []
    for n in range(len(segs)):
        if used[n]:
            continue
        used[n] = True
        line = [segs[n][0], segs[n][1]]
        for forward in (True, False):
            while True:
                tip = line[-1] if forward else line[0]
                cand = [m for m in ends.get(key(tip), []) if not used[m]]
                if not cand:
                    break
                m = cand[0]
                used[m] = True
                a, b = segs[m]
                nxt = b if key(a) == key(tip) else a
                if forward:
                    line.append(nxt)
                else:
                    line.insert(0, nxt)
        out.append(np.array(line, float))
    return out


def poisson(region_lo, region_hi, radius_fn, seed=1, k=24, limit=20000):
    """Próbkowanie dysku Poissona (Bridson) o zmiennym promieniu radius_fn(p) - punkty nie bliżej niż promień."""
    rng = np.random.default_rng(int(seed))
    lo, hi = np.asarray(region_lo, float), np.asarray(region_hi, float)
    rmin = max(1e-3, float(radius_fn(np.array([(lo + hi) / 2]))[0]) * .3)
    pts = [lo + rng.random(2) * (hi - lo)]
    rads = [float(radius_fn(np.array([pts[0]]))[0])]
    grid = Hash(rmin * 2)
    grid.add(0, pts[0], pts[0])
    active = [0]
    while active and len(pts) < limit:
        i = active[int(rng.integers(len(active)))]
        found = False
        for _ in range(k):
            r = rads[i] * (1 + rng.random())
            a = rng.random() * 2 * math.pi
            q = pts[i] + r * np.array([math.cos(a), math.sin(a)])
            if np.any(q < lo) or np.any(q > hi):
                continue
            rq = float(radius_fn(np.array([q]))[0])
            reach = max(rq, max(rads)) * 1.0
            ok = True
            for j in grid.near(q - reach, q + reach):
                if np.linalg.norm(pts[j] - q) < max(rq, rads[j]):
                    ok = False
                    break
            if ok:
                pts.append(q)
                rads.append(rq)
                grid.add(len(pts) - 1, q, q)
                active.append(len(pts) - 1)
                found = True
                break
        if not found:
            active.remove(i)
    return np.array(pts)


def stroke(line, width, caps=True):
    """Łamana pogrubiona do szerokości width (przesunięcia w obie strony, łączenie ukośne, zaokrąglone końce)."""
    L = np.asarray(line, float)
    keep = [0]
    for i in range(1, len(L)):
        if np.linalg.norm(L[i] - L[keep[-1]]) > 1e-6:
            keep.append(i)
    L = L[keep]
    if len(L) < 2:
        raise kernel.CadError('Za krótka linia do szczeliny.')
    closed = np.linalg.norm(L[0] - L[-1]) < 1e-6
    h = width / 2
    T = np.diff(L, axis=0)
    T /= np.linalg.norm(T, axis=1)[:, None]
    N = np.c_[-T[:, 1], T[:, 0]]
    left, right = [], []
    for i in range(len(L)):
        if i == 0 or i == len(L) - 1:
            n = N[0] if i == 0 else N[-1]
            m = 1.0
        else:
            n = N[i - 1] + N[i]
            n /= max(np.linalg.norm(n), 1e-12)
            m = 1 / max(.3, float(n @ N[i]))
        left.append(L[i] + n * h * m)
        right.append(L[i] - n * h * m)
    if closed:
        return [np.array(left[:-1]), np.array(right[:-1])[::-1]]
    poly = list(left)
    if caps:
        a = math.atan2(*N[-1][::-1])
        poly += [L[-1] + h * np.array([math.cos(t), math.sin(t)]) for t in np.linspace(a, a - math.pi, 9)[1:-1]]
    poly += right[::-1]
    if caps:
        a = math.atan2(*(-N[0])[::-1])
        poly += [L[0] + h * np.array([math.cos(t), math.sin(t)]) for t in np.linspace(a, a - math.pi, 9)[1:-1]]
    return [np.array(poly)]


def occ_clip(loops_xy, region_polys, holes_polys=(), inset=0.0):
    """Przycięcie profilu (pętle punktów) do obszaru (wielokąty, minus otwory) - Boolean OCC na ścianach płaskich w XY.
    Zwraca listę profili (każdy: [zewnętrzna, otwory...] jako tablice punktów) albo []."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.BRepTools import BRepTools
    face = _face_xy(loops_xy)
    reg = None
    for o in region_polys:
        f = _face_xy([o])
        reg = f if reg is None else _fuse(reg, f)
    if reg is None:
        return []
    for h in holes_polys:
        reg = BRepAlgoAPI_Cut(reg, _face_xy([h])).Shape()
    res = BRepAlgoAPI_Common(face, reg).Shape()
    out = []
    ex = TopExp_Explorer(res, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        outer = BRepTools.OuterWire_s(f)
        loops = []
        wx = TopExp_Explorer(f, TopAbs_WIRE)
        while wx.More():
            w = TopoDS.Wire_s(wx.Current())
            pts = []
            we = BRepTools_WireExplorer(w)
            while we.More():
                c = BRepAdaptor_Curve(we.Current())
                n = 2 if c.GetType() == 0 else 12
                ts = np.linspace(c.FirstParameter(), c.LastParameter(), n)
                if we.Orientation() == 1:
                    ts = ts[::-1]
                pts += [c.Value(float(t)).Coord()[:2] for t in ts[:-1]]
                we.Next()
            arr = np.array(pts, float)
            if len(arr) >= 3:
                (loops.insert(0, arr) if w.IsSame(outer) else loops.append(arr))
            wx.Next()
        if loops:
            out.append(loops)
        ex.Next()
    return out


def _fuse(a, b):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    return BRepAlgoAPI_Fuse(a, b).Shape()


def _face_xy(loops):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt, gp_Pln
    ws = []
    for lp in loops:
        mp = BRepBuilderAPI_MakePolygon()
        for q in np.asarray(lp, float):
            mp.Add(gp_Pnt(float(q[0]), float(q[1]), 0.0))
        mp.Close()
        ws.append(mp.Wire())
    mf = BRepBuilderAPI_MakeFace(gp_Pln(), ws[0], True)
    for w in ws[1:]:
        mf.Add(w)
    from OCP.ShapeFix import ShapeFix_Face
    fx = ShapeFix_Face(mf.Face())
    fx.FixOrientation()
    fx.Perform()
    return fx.Face()


def self_intersects(poly):
    """Wielokąt z samoprzecięciem (przecinające się niesąsiednie krawędzie)."""
    P = np.asarray(poly, float)
    n = len(P)
    if n < 4:
        return False
    a0, a1 = P, np.roll(P, -1, 0)

    def orient(p, q, r):
        return (q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0])
    o1 = orient(a0[:, None], a1[:, None], a0[None])
    o2 = orient(a0[:, None], a1[:, None], a1[None])
    o3 = orient(a0[None], a1[None], a0[:, None])
    o4 = orient(a0[None], a1[None], a1[:, None])
    cross = (o1 * o2 < 0) & (o3 * o4 < 0)
    idx = np.arange(n)
    adj = (np.abs(idx[:, None] - idx[None]) <= 1) | (np.abs(idx[:, None] - idx[None]) == n - 1)
    return bool(np.any(cross & ~adj))


def simplify(poly, tol):
    """Uproszczenie zamkniętego wielokąta (Douglas-Peucker, odchyłka ≤ tol) - mniej ścian narzędzi bez zmiany kształtu."""
    P = np.asarray(poly, float)
    if len(P) <= 8 or tol <= 0:
        return P
    i0 = 0
    i1 = int(np.argmax(np.linalg.norm(P - P[0], axis=1)))

    def dp(a, b):
        idx = list(range(a, b + 1))
        pts = P[idx]
        if len(pts) <= 2:
            return [a, b]
        d = seg_dist(pts[1:-1], pts[:1], pts[-1:])[:, 0] if np.linalg.norm(pts[-1] - pts[0]) > 1e-12 else np.linalg.norm(pts[1:-1] - pts[0], axis=1)
        k = int(np.argmax(d))
        if d[k] <= tol:
            return [a, b]
        m = a + 1 + k
        left = dp(a, m)
        return left[:-1] + dp(m, b)
    import sys
    lim = sys.getrecursionlimit()
    sys.setrecursionlimit(max(lim, 4 * len(P) + 100))
    try:
        first = dp(i0, i1)
        Q = np.vstack([P[i1:], P[:1]])
        second = dp(0, len(Q) - 1)
    finally:
        sys.setrecursionlimit(lim)
    out = [P[i] for i in first[:-1]] + [Q[i] for i in second[:-1]]
    return np.array(out)


def stroke_loops(line, width):
    """Szczelina wzdłuż łamanej: obrys odsunięty o pół szerokości w obie strony (BRepOffsetAPI_MakeOffset na otwartej
    krzywej, łączenie łukami) - poprawny także w ostrych zakrętach (bez samoprzecięć). Zwraca pętle segmentów L / A."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.GeomAbs import GeomAbs_Arc, GeomAbs_Line, GeomAbs_Circle
    from OCP.TopAbs import TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt
    L = np.asarray(line, float)
    keep = [0]
    for i in range(1, len(L)):
        if np.linalg.norm(L[i] - L[keep[-1]]) > 1e-4:
            keep.append(i)
    L = L[keep]
    if len(L) < 2:
        raise kernel.CadError('Za krótka linia do szczeliny.')
    mp = BRepBuilderAPI_MakePolygon()
    for q in L:
        mp.Add(gp_Pnt(float(q[0]), float(q[1]), 0.0))
    mk = BRepOffsetAPI_MakeOffset(mp.Wire(), GeomAbs_Arc, True)
    mk.Perform(float(width) / 2)
    if not mk.IsDone():
        raise kernel.CadError('Nie udało się zbudować szczeliny wzdłuż krzywej.')
    ex = TopExp_Explorer(mk.Shape(), TopAbs_WIRE)
    loops = []
    while ex.More():
        w = TopoDS.Wire_s(ex.Current())
        segs = []
        we = BRepTools_WireExplorer(w)
        while we.More():
            c = BRepAdaptor_Curve(we.Current())
            a, b = c.FirstParameter(), c.LastParameter()
            if we.Orientation() == 1:
                a, b = b, a
            P0, P1 = np.array(c.Value(a).Coord()[:2]), np.array(c.Value(b).Coord()[:2])
            if c.GetType() == GeomAbs_Line:
                segs.append(('L', P0, P1))
            elif c.GetType() == GeomAbs_Circle:
                segs.append(('A', P0, np.array(c.Value((a + b) / 2).Coord()[:2]), P1))
            else:
                pts = [np.array(c.Value(float(t)).Coord()[:2]) for t in np.linspace(a, b, 12)]
                segs += [('L', pts[k], pts[k + 1]) for k in range(len(pts) - 1)]
            we.Next()
        if segs:
            loops.append(segs)
        ex.Next()
    if not loops:
        raise kernel.CadError('Szczelina wzdłuż krzywej nie ma obrysu.')
    return loops


def simplify_open(line, tol):
    """Uproszczenie łamanej otwartej (Douglas-Peucker, końce zostają)."""
    P = np.asarray(line, float)
    if len(P) <= 3 or tol <= 0:
        return P
    keep = np.zeros(len(P), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(P) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        d = seg_dist(P[a + 1:b], P[a:a + 1], P[b:b + 1])[:, 0]
        k = int(np.argmax(d))
        if d[k] > tol:
            m = a + 1 + k
            keep[m] = True
            stack += [(a, m), (m, b)]
    return P[keep]
