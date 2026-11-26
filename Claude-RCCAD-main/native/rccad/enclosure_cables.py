"""Generator obudów - etap 20: automatyczne prowadzenie przewodów.

Trasa przewodu wewnątrz części obudowy od punktu początkowego do końcowego (z kierunkami wyjścia ze złączy i odcinkami
prostymi przy złączach, opcjonalnie przez punkty pośrednie i istniejące przepusty).

Algorytm:
1. Reprezentacja pomocnicza: siatka wokselowa wnętrza (rozdzielczość dobierana do wielkości obudowy). Zajętość z
   triangulacji brył (wnętrze obudowy, bryła części - ścianki, słupki, żebra, przegrody -, komponenty, inne części,
   inne przewody): wypełnianie kolumn wzdłuż Z parzystością przecięć promienia z trójkątami (numpy).
2. Przeszkody powiększone (dylatacja kulą) o promień przewodu + odstęp od przeszkód (+ odchyłka triangulacji); ścianki
   wnętrza - o promień + odstęp od ścianek. Pole odległości od przeszkód (BFS).
3. A* (sąsiedztwo 26 albo 6 - trasa ortogonalna) z kosztem: długość, zmiana kierunku, ciasne przejścia (odwrotność
   odległości od przeszkód), preferencja przy ściankach albo przy dnie. Tryby: najkrótsza, przy ściankach, przy dnie,
   ortogonalna, przestrzenna, przez punkty pośrednie, ręczna (łamana przez punkty - tylko sprawdzana), przez przepusty.
4. Uproszczenie (widoczność po siatce), zaokrąglenie załamań łukami o promieniu ≥ minimalnego promienia gięcia (gdy się
   nie mieści - błąd z miejscem), ponowne sprawdzenie łuków na siatce; opcjonalnie krzywa B-spline (GeomAPI_Interpolate)
   ze sprawdzeniem krzywizny.
5. Geometria B-Rep: krawędzie (odcinki, łuki / Geom_BSplineCurve) → BRepBuilderAPI_MakeWire, przekrój (okrągły,
   wielożyłowy, wiązka, płaski, taśma, w osłonie, rurka) prowadzony po ścieżce (BRepOffsetAPI_MakePipeShell; przewody
   płaskie - stała binormalna, bez skręcania taśmy). Dokładna kontrola na geometrii końcowej (BRepAlgoAPI_Common,
   BRepExtrema_DistShapeShape).
6. Uchwyty wzdłuż trasy co zadany rozstaw tam, gdzie w zasięgu jest powierzchnia montażowa części: klipsy otwarte,
   uchwyty zamknięte, mocowania opasek, kanały, prowadnice narożne, odciążenie przy złączu - połączone z częścią.
Gdy trasy nie ma - komunikat z obszarem blokującym (komponenty przecinające korytarz między punktami)."""
from __future__ import annotations

import heapq
import math

import numpy as np

from . import kernel

KINDS = ('round', 'multi', 'bundle', 'flat', 'ribbon', 'sleeved', 'tube')
KIND_LABELS = {'round': 'Przewód okrągły', 'multi': 'Przewód wielożyłowy', 'bundle': 'Wiązka przewodów', 'flat': 'Przewód płaski',
               'ribbon': 'Taśma elastyczna (FFC)', 'sleeved': 'Przewód w osłonie', 'tube': 'Rurka / wąż elastyczny'}
MODES = ('shortest', 'walls', 'floor', 'orthogonal', 'spatial', 'waypoints', 'manual', 'passes')
MODE_LABELS = {'shortest': 'Najkrótsza', 'walls': 'Przy ściankach', 'floor': 'Przy dnie', 'orthogonal': 'Ortogonalna', 'spatial': 'Przestrzenna',
               'waypoints': 'Przez punkty pośrednie', 'manual': 'Ręczna (łamana przez punkty)', 'passes': 'Przez przepusty'}
CLIPS = ('none', 'open', 'closed', 'tie', 'channel', 'corner', 'strain')
CLIP_LABELS = {'none': 'Bez uchwytów', 'open': 'Klipsy otwarte', 'closed': 'Uchwyty zamknięte', 'tie': 'Mocowania opasek zaciskowych',
               'channel': 'Kanały kablowe', 'corner': 'Prowadnice narożne', 'strain': 'Odciążenie przy złączach'}
DEFAULTS = dict(kind='round', diameter=3.0, width=10.0, thickness=1.0, count=3, sleeve=.5, inner=2.0, min_bend=6.0, clearance=1.0,
                wall_gap=1.0, straight=4.0, spare=10.0, max_len=0.0, mode='shortest', direction='', turn_cost=2.0, tight_cost=1.0,
                clip='none', clip_pitch=30.0, clip_t=1.2, clip_w=4.0, clip_gap=.3, reach=8.0, resolution=0.0, spline=False,
                avoid_cables=True, name='Przewód', color='#c0392b')
DIRECTION_LABELS = {'': 'Kierunek preferowany: brak', 'x': 'Preferuj odcinki wzdłuż X', 'y': 'Preferuj odcinki wzdłuż Y',
                    'z': 'Preferuj odcinki pionowe (Z)'}
MAX_CELLS = 400_000


def _pref(p, d, step):
    """Kara za ruch poza preferowanym kierunkiem (0 gdy brak preferencji)."""
    ax = {'x': 0, 'y': 1, 'z': 2}.get(p.get('direction') or '')
    return 0.0 if ax is None else .4 * (1 - abs(d[ax]) / step)


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def cable_radius(p):
    """Promień obwiedni przekroju (do planowania trasy)."""
    k = p['kind']
    d = float(p['diameter'])
    if k == 'bundle':
        return d * math.sqrt(max(1, int(p['count']))) * .58
    if k in ('flat', 'ribbon'):
        return math.hypot(float(p['width']), float(p['thickness'])) / 2
    if k == 'sleeved':
        return d / 2 + float(p['sleeve'])
    return d / 2


# ---------------------------------------------------------------------------------------------- woksele
class Grid:
    """Siatka wokselowa: początek, krok, wymiary; środki komórek."""

    def __init__(self, lo, hi, res):
        self.res = float(res)
        self.lo = np.asarray(lo, float)
        self.n = np.maximum(1, np.ceil((np.asarray(hi, float) - self.lo) / self.res).astype(int))
        self.shape = tuple(int(x) for x in self.n)

    def centre(self, idx):
        return self.lo + (np.asarray(idx, float) + .5) * self.res

    def index(self, p):
        return tuple(int(x) for x in np.clip(np.floor((np.asarray(p, float) - self.lo) / self.res), 0, self.n - 1))


def _mesh(shape):
    import cadquery as cq
    m = kernel.display_mesh(shape if isinstance(shape, cq.Shape) else cq.Shape.cast(shape))
    return np.asarray(m.vertices, float), np.asarray(m.triangles, int)


def voxelize(grid, shape):
    """Komórki, których środki leżą wewnątrz bryły: parzystość przecięć promieni wzdłuż +Z z trójkątami siatki."""
    V, T = _mesh(shape)
    occ = np.zeros(grid.shape, bool)
    if not len(T):
        return occ
    nx, ny, nz = grid.shape
    xs = grid.lo[0] + (np.arange(nx) + .5) * grid.res
    ys = grid.lo[1] + (np.arange(ny) + .5) * grid.res
    zs = grid.lo[2] + (np.arange(nz) + .5) * grid.res
    hits = {}
    A, B, C = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    for a, b, c in zip(A, B, C):
        x0, x1 = min(a[0], b[0], c[0]), max(a[0], b[0], c[0])
        y0, y1 = min(a[1], b[1], c[1]), max(a[1], b[1], c[1])
        i0, i1 = np.searchsorted(xs, x0), np.searchsorted(xs, x1, 'right')
        j0, j1 = np.searchsorted(ys, y0), np.searchsorted(ys, y1, 'right')
        if i0 >= i1 or j0 >= j1:
            continue
        det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(det) < 1e-12:
            continue
        X, Y = np.meshgrid(xs[i0:i1], ys[j0:j1], indexing='ij')
        l1 = ((b[1] - c[1]) * (X - c[0]) + (c[0] - b[0]) * (Y - c[1])) / det
        l2 = ((c[1] - a[1]) * (X - c[0]) + (a[0] - c[0]) * (Y - c[1])) / det
        l3 = 1 - l1 - l2
        inside = (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
        if not inside.any():
            continue
        Z = l1 * a[2] + l2 * b[2] + l3 * c[2]
        for ii, jj in zip(*np.nonzero(inside)):
            hits.setdefault((i0 + ii, j0 + jj), []).append(float(Z[ii, jj]))
    for (i, j), zl in hits.items():
        zl = np.unique(np.round(np.sort(zl), 6))
        for k in range(0, len(zl) - 1, 2):
            occ[i, j, (zs > zl[k]) & (zs < zl[k + 1])] = True
    return occ


def dilate(occ, r_cells):
    """Dylatacja kulą o promieniu r_cells (przesunięcia w kuli)."""
    r = int(math.ceil(r_cells))
    if r <= 0:
        return occ.copy()
    out = occ.copy()
    nx, ny, nz = occ.shape
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            for dz in range(-r, r + 1):
                if dx * dx + dy * dy + dz * dz > r_cells * r_cells + 1e-9 or (dx == dy == dz == 0):
                    continue
                src = occ[max(0, -dx):nx - max(0, dx), max(0, -dy):ny - max(0, dy), max(0, -dz):nz - max(0, dz)]
                out[max(0, dx):nx - max(0, -dx), max(0, dy):ny - max(0, -dy), max(0, dz):nz - max(0, -dz)] |= src
    return out


def distance_field(blocked):
    """Odległość (w komórkach, metryka Czebyszewa) od zajętych komórek - BFS wielu źródeł."""
    from collections import deque
    dist = np.full(blocked.shape, -1, int)
    q = deque()
    for idx in zip(*np.nonzero(blocked)):
        dist[idx] = 0
        q.append(idx)
    nx, ny, nz = blocked.shape
    while q:
        x, y, z = q.popleft()
        d = dist[x, y, z] + 1
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    a, b, c = x + dx, y + dy, z + dz
                    if 0 <= a < nx and 0 <= b < ny and 0 <= c < nz and dist[a, b, c] < 0:
                        dist[a, b, c] = d
                        q.append((a, b, c))
    dist[dist < 0] = max(nx, ny, nz)
    return dist


# ---------------------------------------------------------------------------------------------- A*
NEIGH26 = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) if (dx, dy, dz) != (0, 0, 0)]
NEIGH6 = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]


def astar(free, dist, start, goal, p, up_axis=2, cancel=None):
    """A* po wolnych komórkach; koszt: długość + zmiana kierunku + ciasne przejścia + preferencje trybu."""
    mode = p['mode']
    neigh = NEIGH6 if mode == 'orthogonal' else NEIGH26
    turn = float(p['turn_cost'])
    tight = float(p['tight_cost'])
    shape = free.shape
    g = {start: 0.0}
    came = {start: (None, None)}
    h = lambda c: math.dist(c, goal)
    heap = [(h(start), 0.0, start)]
    seen = 0
    while heap:
        _f, gc, cur = heapq.heappop(heap)
        if cur == goal:
            path = [cur]
            while came[path[-1]][0] is not None:
                path.append(came[path[-1]][0])
            return path[::-1]
        if gc > g.get(cur, math.inf) + 1e-9:
            continue
        seen += 1
        if cancel is not None and seen % 2000 == 0 and cancel():
            raise kernel.CadError('Wyznaczanie trasy przerwane.')
        pdir = came[cur][1]
        for d in neigh:
            nxt = (cur[0] + d[0], cur[1] + d[1], cur[2] + d[2])
            if not (0 <= nxt[0] < shape[0] and 0 <= nxt[1] < shape[1] and 0 <= nxt[2] < shape[2]) or not free[nxt]:
                continue
            step = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
            cost = step
            if pdir is not None and pdir != d:
                cost += turn * (4 if mode == 'orthogonal' else .5)
            dd = max(1, int(dist[nxt]))
            cost += tight / dd + _pref(p, d, step)
            if mode == 'walls':
                cost += .3 * (dd - 1)                    # bliżej ścianek / przeszkód taniej
            elif mode == 'floor':
                cost += .3 * nxt[up_axis]
            ng = gc + cost
            if ng < g.get(nxt, math.inf):
                g[nxt] = ng
                came[nxt] = (cur, d)
                heapq.heappush(heap, (ng + h(nxt), ng, nxt))
    return None


def _axis_dir(v):
    if v is None:
        return None
    k = int(np.argmax(np.abs(v)))
    d = [0, 0, 0]
    d[k] = 1 if v[k] > 0 else -1
    return tuple(d)


def astar_ortho(free, dist, start, goal, p, m, sdir=None, gdir=None, cancel=None):
    """A* ortogonalny ze stanem (komórka, kierunek, przebieg od ostatniego załamania): kolejne załamanie dopiero po m
    komórkach - na odcinku mieszczą się styczne dwóch łuków o minimalnym promieniu. sdir - kierunek dojścia do startu
    (wyjście ze złącza: można skręcić od razu), gdir - kierunek, w którym trasa musi opuścić cel."""
    turn = float(p['turn_cost'])
    tight = float(p['tight_cost'])
    shape = free.shape
    s0 = (start, sdir, m)
    g = {s0: 0.0}
    came = {s0: None}
    h = lambda c: abs(c[0] - goal[0]) + abs(c[1] - goal[1]) + abs(c[2] - goal[2])
    heap = [(h(start), 0.0, 0, s0)]
    seen = 0
    while heap:
        _f, gc, _t, st = heapq.heappop(heap)
        cur, pdir, run = st
        if cur == goal and (gdir is None or pdir is None or pdir == gdir or run >= m):
            path = [st]
            while came[path[-1]] is not None:
                path.append(came[path[-1]])
            return [q[0] for q in path[::-1]]
        if gc > g.get(st, math.inf) + 1e-9:
            continue
        seen += 1
        if cancel is not None and seen % 2000 == 0 and cancel():
            raise kernel.CadError('Wyznaczanie trasy przerwane.')
        for d in NEIGH6:
            if pdir is not None and d != pdir:
                if run < m or d == (-pdir[0], -pdir[1], -pdir[2]):
                    continue
            nxt = (cur[0] + d[0], cur[1] + d[1], cur[2] + d[2])
            if not (0 <= nxt[0] < shape[0] and 0 <= nxt[1] < shape[1] and 0 <= nxt[2] < shape[2]) or not free[nxt]:
                continue
            nrun = min(run + 1, m) if d == pdir else 1
            cost = 1.0 + (turn * 4 if pdir is not None and d != pdir else 0.0) + tight / max(1, int(dist[nxt])) + _pref(p, d, 1.0)
            ns = (nxt, d, nrun)
            ng = gc + cost
            if ng < g.get(ns, math.inf):
                g[ns] = ng
                came[ns] = st
                seen += 0
                heapq.heappush(heap, (ng + h(nxt), ng, id(ns), ns))
    return None


def _snap_ortho(cor, end):
    """Łamana osiowa z dokładnym początkiem: koniec przesunięty do punktu end, odchyłka przejmowana kolejno przez odcinki
    od końca (każdy zachowuje swoją oś) - bez drobnych uskoków przy złączu."""
    cor = [np.asarray(q, float).copy() for q in cor]
    if len(cor) < 2:
        return cor
    axes = [int(np.argmax(np.abs(cor[j + 1] - cor[j]))) for j in range(len(cor) - 1)]
    cor[-1] = np.asarray(end, float).copy()
    for j in range(len(cor) - 2, 0, -1):
        other = [i for i in range(3) if i != axes[j]]
        if np.allclose(cor[j][other], cor[j + 1][other], atol=1e-9):
            break
        cor[j][other] = cor[j + 1][other]
    return cor


def _visible(free, grid, a, b):
    """Odcinek a-b (świat) przechodzi wyłącznie przez wolne komórki (próbkowanie co pół kroku)."""
    L = float(np.linalg.norm(b - a))
    n = max(2, int(L / (grid.res * .5)) + 1)
    for t in np.linspace(0, 1, n):
        idx = grid.index(a + (b - a) * t)
        if not free[idx]:
            return False
    return True


def simplify(free, grid, pts):
    out = [pts[0]]
    i = 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1 and not _visible(free, grid, pts[i], pts[j]):
            j -= 1
        out.append(pts[j])
        i = j
    return out


class _Tight(kernel.CadError):
    def __init__(self, index, msg, seg=None):
        super().__init__(msg)
        self.index = index
        self.seg = seg


def _collinear(pts):
    out = [pts[0]]
    for k in range(1, len(pts) - 1):
        if np.linalg.norm(np.cross(_unit(pts[k] - out[-1]), _unit(pts[k + 1] - pts[k]))) > 1e-6:
            out.append(pts[k])
    out.append(pts[-1])
    return out


def smooth(pts, R, keep, free, grid, dejog=True):
    """Zaokrąglenie łamanej; załamanie, w którym łuk się nie mieści, jest usuwane (gdy sąsiednie punkty się widzą)
    - punkty stałe (złącza, punkty pośrednie) zostają."""
    pts = [np.asarray(q, float) for q in pts]
    keep = set(keep)
    tol = 2.0 * grid.res                                       # drobne uskoki od środków komórek / dosunięcia do wolnej komórki
    changed = True
    while changed:
        changed = False
        for i in range(1, len(pts) - 1):
            bend = np.linalg.norm(np.cross(_unit(pts[i] - pts[i - 1]), _unit(pts[i + 1] - pts[i])))
            straight = bend < 1e-6 and float(_unit(pts[i] - pts[i - 1]) @ _unit(pts[i + 1] - pts[i])) > 0
            if straight:                                       # punkt na prostej (także stały) - zbędny
                del pts[i]
                keep = {q - 1 if q > i else q for q in keep if q != i}
                changed = True
                break
            if i in keep or not dejog:
                continue
            short = min(np.linalg.norm(pts[i] - pts[i - 1]), np.linalg.norm(pts[i + 1] - pts[i])) < tol
            if (short or bend < .05) and _visible(free, grid, pts[i - 1], pts[i + 1]):
                del pts[i]
                keep = {q - 1 if q > i else q for q in keep}
                changed = True
                break
    for _ in range(3 * len(pts) + 5):
        try:
            return fillet_polyline(pts, R), pts
        except _Tight as exc:
            j = exc.seg if exc.seg is not None else exc.index
            done = False
            a, b = j, j + 1                                    # dwa załamania za blisko: jedno załamanie w przecięciu prostych
            if 1 <= a and b <= len(pts) - 2 and a not in keep and b not in keep:
                p0, d0 = pts[a - 1], _unit(pts[a] - pts[a - 1])
                p1, d1 = pts[b + 1], _unit(pts[b] - pts[b + 1])
                w0 = p0 - p1
                aa, bb, cc, dd, ee = d0 @ d0, d0 @ d1, d1 @ d1, d0 @ w0, d1 @ w0
                den = aa * cc - bb * bb
                if abs(den) > 1e-9:
                    s_ = (bb * ee - cc * dd) / den
                    t_ = (aa * ee - bb * dd) / den
                    X = (p0 + d0 * s_ + p1 + d1 * t_) / 2
                    if s_ > 0 and t_ > 0 and _visible(free, grid, pts[a - 1], X) and _visible(free, grid, X, pts[b + 1]):
                        pts[a:b + 1] = [X]
                        keep = {i - 1 if i > a else i for i in keep}
                        done = True
            if not done:
                cand = [i for i in (exc.index, a, b) if 0 < i < len(pts) - 1 and i not in keep and _visible(free, grid, pts[i - 1], pts[i + 1])]
                if not cand:
                    raise
                i = cand[0]
                del pts[i]
                keep = {q - 1 if q > i else q for q in keep}
    raise kernel.CadError('Nie udało się wygładzić trasy przewodu.')


def fillet_polyline(pts, R):
    """Łamana z łukami o promieniu R w załamaniach: lista ('L', a, b) / ('A', a, m, b). Każdy odcinek musi zmieścić
    styczne łuków na obu końcach - inaczej _Tight z numerem załamania."""
    pts = [np.asarray(q, float) for q in pts]
    clean = [pts[0]]
    for q in pts[1:]:
        if np.linalg.norm(q - clean[-1]) > 1e-6:
            clean.append(q)
    pts = clean
    if len(pts) < 2:
        raise kernel.CadError('Trasa przewodu jest pusta.')
    n = len(pts)
    tl = [0.0] * n
    for k in range(1, n - 1):
        d1, d2 = _unit(pts[k] - pts[k - 1]), _unit(pts[k + 1] - pts[k])
        theta = math.acos(float(np.clip(d1 @ d2, -1, 1)))
        if theta > math.radians(179):
            raise _Tight(k, 'Trasa zawraca w miejscu - dodaj punkt pośredni.')
        tl[k] = R * math.tan(theta / 2) if theta > 1e-6 else 0.0
    for j in range(n - 1):
        if tl[j] + tl[j + 1] > float(np.linalg.norm(pts[j + 1] - pts[j])) + 1e-6:
            k = j if tl[j] >= tl[j + 1] else j + 1
            b = pts[k]
            raise _Tight(k, f'W okolicy punktu ({b[0]:.1f}, {b[1]:.1f}, {b[2]:.1f}) trasa wymaga gięcia ciaśniejszego niż minimalny promień '
                         f'{R:g} mm - zmniejsz promień, dodaj punkt pośredni albo zwiększ przestrzeń.', j)
    segs, cur = [], pts[0]
    for k in range(1, n - 1):
        if tl[k] <= 0:
            continue
        a, b, c = pts[k - 1], pts[k], pts[k + 1]
        d1, d2 = _unit(b - a), _unit(c - b)
        theta = math.acos(float(np.clip(d1 @ d2, -1, 1)))
        p1, p2 = b - d1 * tl[k], b + d2 * tl[k]
        bis = _unit(_unit(p1 - b) + _unit(p2 - b))
        centre = b + bis * (R / math.cos(theta / 2))
        mid = centre + _unit(b - centre) * R
        if np.linalg.norm(p1 - cur) > 1e-6:
            segs.append(('L', cur, p1))
        segs.append(('A', p1, mid, p2))
        cur = p2
    if np.linalg.norm(pts[-1] - cur) > 1e-6:
        segs.append(('L', cur, pts[-1]))
    return segs


def sample(segs, step):
    out = []
    for s in segs:
        if s[0] == 'L':
            n = max(2, int(np.linalg.norm(s[2] - s[1]) / step) + 1)
            out += [s[1] + (s[2] - s[1]) * t for t in np.linspace(0, 1, n)]
        else:
            a, m, b = s[1:]
            from OCP.GC import GC_MakeArcOfCircle
            from OCP.gp import gp_Pnt
            arc = GC_MakeArcOfCircle(gp_Pnt(*map(float, a)), gp_Pnt(*map(float, m)), gp_Pnt(*map(float, b))).Value()
            n = max(9, int((arc.LastParameter() - arc.FirstParameter()) * arc.BasisCurve().Radius() / step) + 1)
            for t in np.linspace(arc.FirstParameter(), arc.LastParameter(), n):
                q = arc.Value(t)
                out.append(np.array([q.X(), q.Y(), q.Z()]))
    return out


# ---------------------------------------------------------------------------------------------- geometria
def _wire(segs, spline=False, step=None):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.GC import GC_MakeArcOfCircle, GC_MakeSegment
    from OCP.gp import gp_Pnt
    P = lambda q: gp_Pnt(*map(float, q))
    mw = BRepBuilderAPI_MakeWire()
    if spline:
        from OCP.GeomAPI import GeomAPI_Interpolate
        from OCP.TColgp import TColgp_HArray1OfPnt
        dense = np.array(sample(segs, .1))
        dl = np.r_[0, np.cumsum(np.linalg.norm(np.diff(dense, axis=0), axis=1))]
        h = min(2.0, max(.5, step / 3)) if step else 2.0
        tt = np.linspace(0, dl[-1], max(4, int(dl[-1] / h) + 1))         # równy rozstaw po długości - bez przeregulowania
        clean = [np.array([np.interp(t, dl, dense[:, i]) for i in range(3)]) for t in tt]
        arr = TColgp_HArray1OfPnt(1, len(clean))
        for i, q in enumerate(clean):
            arr.SetValue(i + 1, P(q))
        it = GeomAPI_Interpolate(arr, False, 1e-6)
        it.Perform()
        if not it.IsDone():
            raise kernel.CadError('Interpolacja B-spline trasy nie powiodła się.')
        mw.Add(BRepBuilderAPI_MakeEdge(it.Curve()).Edge())
        return mw.Wire(), it.Curve()
    for s in segs:
        if s[0] == 'L':
            mw.Add(BRepBuilderAPI_MakeEdge(GC_MakeSegment(P(s[1]), P(s[2])).Value()).Edge())
        else:
            mw.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(P(s[1]), P(s[2]), P(s[3])).Value()).Edge())
    if not mw.IsDone():
        raise kernel.CadError('Nie udało się zbudować ścieżki przewodu.')
    return mw.Wire(), None


def _exact_bspline(segs):
    """Łuki i odcinki trasy jako jedna krzywa B-spline (GeomConvert - wymierna, dokładna, promień bez zmian)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.GC import GC_MakeArcOfCircle, GC_MakeSegment
    from OCP.GeomConvert import GeomConvert, GeomConvert_CompCurveToBSplineCurve
    from OCP.gp import gp_Pnt
    P = lambda q: gp_Pnt(*map(float, q))
    cc = None
    for s in segs:
        c = GC_MakeSegment(P(s[1]), P(s[2])).Value() if s[0] == 'L' else GC_MakeArcOfCircle(P(s[1]), P(s[2]), P(s[3])).Value()
        bs = GeomConvert.CurveToBSplineCurve_s(c)
        if cc is None:
            cc = GeomConvert_CompCurveToBSplineCurve(bs)
        elif not cc.Add(bs, 1e-6):
            raise kernel.CadError('Nie udało się połączyć odcinków trasy w krzywą B-spline.')
    curve = cc.BSplineCurve()
    return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(curve).Edge()).Wire(), curve


def _min_radius(curve):
    """Najmniejszy promień krzywizny krzywej B-spline (próbkowanie)."""
    from OCP.GeomLProp import GeomLProp_CLProps
    r = math.inf
    for t in np.linspace(curve.FirstParameter(), curve.LastParameter(), 200):
        pr = GeomLProp_CLProps(curve, float(t), 2, 1e-9)
        k = pr.Curvature()
        if k > 1e-12:
            r = min(r, 1 / k)
    return r


def _profile(p, origin, tangent, binormal):
    """Przekrój przewodu w płaszczyźnie prostopadłej do początku ścieżki (ściana albo ściana z otworem)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt
    k = p['kind']
    o = gp_Pnt(*map(float, origin))
    t = gp_Dir(*map(float, tangent))
    if k in ('flat', 'ribbon'):
        w, th = float(p['width']), float(p['thickness'])
        side = _unit(binormal)                                # szerokość wzdłuż binormalnej - gięcie tylko przez grubość
        bn = _unit(np.cross(tangent, binormal))
        poly = BRepBuilderAPI_MakePolygon()
        for a, b in ((-w / 2, -th / 2), (w / 2, -th / 2), (w / 2, th / 2), (-w / 2, th / 2)):
            poly.Add(gp_Pnt(*map(float, origin + side * a + bn * b)))
        poly.Close()
        return poly.Wire(), None
    r = cable_radius(p)
    outer = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(o, t), r)).Edge()).Wire()
    inner = None
    if k == 'tube':
        ri = float(p['inner']) / 2
        if ri >= r:
            raise kernel.CadError('Średnica wewnętrzna rurki musi być mniejsza niż zewnętrzna.')
        inner = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(o, t), ri)).Edge()).Wire()
    return outer, inner


def sweep_solid(wire, p, start, tangent, binormal):
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell
    from OCP.gp import gp_Dir
    from .enclosure import _boolean

    def pipe(prof):
        mk = BRepOffsetAPI_MakePipeShell(wire)
        if p['kind'] in ('flat', 'ribbon'):
            mk.SetMode(gp_Dir(*map(float, binormal)))         # stała binormalna - taśma bez skręcania
        else:
            mk.SetMode(True)                                  # Frenet
        mk.Add(prof)
        mk.Build()
        if not mk.IsDone():
            raise kernel.CadError('Prowadzenie przekroju po ścieżce nie powiodło się - zwiększ promień gięcia.')
        mk.MakeSolid()
        return mk.Shape()
    outer, inner = _profile(p, start, tangent, binormal)
    solid = pipe(outer)
    if inner is not None:
        solid = _boolean('cut', solid, pipe(inner), 'rurka')
    return solid


def _length(wire):
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    g = GProp_GProps()
    BRepGProp.LinearProperties_s(wire, g)
    return float(g.Mass())


# ---------------------------------------------------------------------------------------------- trasa
def route(cavity, obstacles, start, end, p, waypoints=(), start_dir=None, end_dir=None, names=(), cancel=None):
    """Trasa i bryła przewodu: dict(points, segments, wire, solid, length, report). obstacles - [(nazwa, bryła)]."""
    import cadquery as cq
    from .enclosure import _boolean, _volume
    p = dict(DEFAULTS, **p)
    r = cable_radius(p)
    if r <= 0:
        raise kernel.CadError('Średnica przewodu musi być większa od zera.')
    R = max(float(p['min_bend']), r * 1.01)
    start, end = np.asarray(start, float), np.asarray(end, float)
    sd = _unit(start_dir) if start_dir is not None else None
    ed = _unit(end_dir) if end_dir is not None else None
    L0 = max(float(p['straight']), 0.0)
    via = [np.asarray(w, float) for w in waypoints]
    if p['mode'] in ('waypoints', 'passes', 'manual') and not via and p['mode'] != 'manual':
        raise kernel.CadError('Wskaż punkty pośrednie / przepusty, przez które ma przejść przewód.')
    bb = cq.Shape.cast(cavity).BoundingBox()
    lo, hi = np.array([bb.xmin, bb.ymin, bb.zmin]), np.array([bb.xmax, bb.ymax, bb.zmax])
    res = float(p['resolution']) or max(.5, r * .9, float(np.prod(hi - lo) / MAX_CELLS) ** (1 / 3))
    if np.prod(np.ceil((hi - lo) / res)) > MAX_CELLS * 1.5:
        res = float(np.prod(hi - lo) / MAX_CELLS) ** (1 / 3)
    grid = Grid(lo - res, hi + res, res)
    inside = voxelize(grid, cavity)
    blocked_obs = np.zeros(grid.shape, bool)
    for _n, sh in obstacles:
        blocked_obs |= voxelize(grid, sh)
    margin = res * .5                                          # odchyłka siatki i triangulacji
    walls = dilate(~inside, (r + float(p['wall_gap']) + margin) / res)
    obs = dilate(blocked_obs, (r + float(p['clearance']) + margin) / res)
    free = ~(walls | obs)
    free_tight = ~(dilate(~inside, (r + float(p['wall_gap'])) / res) | dilate(blocked_obs, (r + float(p['clearance'])) / res))
    dist = distance_field(~free)
    report = []

    ortho = [p['mode'] == 'orthogonal']
    plane = [None, free]                                      # taśma: trasa w jednej płaszczyźnie (normalna = stała binormalna)

    def attempt(extra):
        a0 = start + sd * (L0 + max(r, R) + extra) if sd is not None else start   # odcinek prosty przy złączu + miejsce na łuk
        b0 = end + ed * (L0 + max(r, R) + extra) if ed is not None else end
        chain = [a0, *via, b0]
        cells = [grid.index(q) for q in chain]
        for q, c in zip(chain, cells):
            if not free[c]:                                       # punkt przy złączu w strefie odstępu - najbliższa wolna komórka
                cand = np.argwhere(free)
                if not len(cand):
                    raise kernel.CadError('Wnętrze obudowy nie ma miejsca na przewód tej średnicy.')
                best = cand[np.argmin(np.linalg.norm(cand - np.array(c), axis=1))]
                if np.linalg.norm((best - np.array(c)) * res) > r * 3 + 2 * res:
                    raise kernel.CadError(f'Punkt ({q[0]:.1f}, {q[1]:.1f}, {q[2]:.1f}) leży w przeszkodzie albo za blisko niej - przesuń go.')
        pts = [chain[0]]
        if p['mode'] == 'manual':
            for q in chain[1:]:
                if not _visible(free, grid, pts[-1], q):
                    raise kernel.CadError('Ręczna trasa przechodzi przez przeszkodę albo strefę odstępu - popraw punkty.')
                pts.append(q)
        else:
            for k in range(len(chain) - 1):
                fr = plane[1]
                a, b = _nearest_free(fr, grid, chain[k]), _nearest_free(fr, grid, chain[k + 1])
                if ortho[0]:
                    m = int(math.ceil((2 * R + 2 * res) / res))
                    sdir = _axis_dir(sd) if (k == 0 and sd is not None) else None
                    gdir = _axis_dir(-ed) if (k == len(chain) - 2 and ed is not None) else None
                    path = astar_ortho(fr, dist, a, b, p, m, sdir, gdir, cancel)
                else:
                    path = astar(fr, dist, a, b, p, 2, cancel)
                if path is None:
                    raise kernel.CadError('Nie znaleziono trasy przewodu' + _blockers(chain[k], chain[k + 1], r, obstacles) +
                                          ' - zmniejsz odstępy, przesuń punkty albo dodaj punkt pośredni.')
                cpts = [grid.centre(c) for c in path]
                if ortho[0]:                                      # przesunięcie o odchyłkę środka komórki - bez drobnych uskoków
                    off = chain[k] - cpts[0]
                    cpts = [c + off for c in cpts]
                if plane[0] is not None:
                    n_ = plane[0]
                    cpts = [c - n_ * float((c - start) @ n_) for c in cpts]
                if ortho[0] and plane[0] is None:
                    pts += _snap_ortho(_collinear(cpts), chain[k + 1])[1:]
                    continue
                cpts[0], cpts[-1] = chain[k], chain[k + 1]
                pts += (_collinear(cpts) if ortho[0] else simplify(free, grid, cpts))[1:]
        full = ([start] if sd is not None else []) + pts + ([end] if ed is not None else [])
        fixed = {0, len(full) - 1}
        if sd is not None:
            fixed.add(1)
        if ed is not None:
            fixed.add(len(full) - 2)
        if p['mode'] == 'manual':                                 # ręczna trasa: punkty pośrednie są wierzchołkami łamanej
            for w in via:
                for j, q in enumerate(full):
                    if np.linalg.norm(q - w) < 1e-9:
                        fixed.add(j)
        segs, full = smooth(full, R, fixed, free_tight, grid, dejog=not (ortho[0] and plane[0] is None))
        return segs, full
    def solve():
        err = None
        tries = [(0.0, True), (R, True), (2 * R, True), (4 * R, True)]
        if ortho[0]:                                              # bez miejsca na łuki pod kątem prostym - odcinki skośne (raport)
            tries += [(0.0, False), (R, False), (2 * R, False)]
        for extra, ortho[0] in [(e, o and ortho[0]) for e, o in tries]:                      # gięcie za ciasne przy złączu - dłuższy odcinek wyjścia
            try:
                segs, full = attempt(extra)
                break
            except _Tight as exc:
                err = exc
                if sd is None and ed is None:
                    raise
            except kernel.CadError:
                if err is None or str(err).startswith('Wyznaczanie trasy przerwane'):
                    raise
                raise err
        else:
            raise err
        return segs, full
    flat = p['kind'] in ('flat', 'ribbon')
    if not flat:
        segs, full = solve()
    else:
        span = end - start
        cands = []
        base = [*[np.cross(span, w - start) for w in via], np.cross(span, sd) if sd is not None else None, np.cross(sd, ed) if sd is not None and ed is not None else None,
                np.cross(span, [0, 0, 1.0]), np.cross(span, [0, 1.0, 0]), np.cross(span, [1.0, 0, 0]),
                np.array([0, 0, 1.0]), np.array([0, 1.0, 0]), np.array([1.0, 0, 0])]
        for v in base:
            if v is None or np.linalg.norm(v) < 1e-6:
                continue
            n_ = _unit(v)
            if any(abs(float(n_ @ d)) > .05 for d in (sd, ed) if d is not None) or abs(float(n_ @ span)) > .05 * max(1.0, float(np.linalg.norm(span))):
                continue
            if any(abs(float((w - start) @ n_)) > res for w in via):
                continue
            if all(abs(float(n_ @ c)) < .999 for c in cands):
                cands.append(n_)
        if not cands:
            raise kernel.CadError('Przewód płaski nie może biec bez skręcania: złącza i punkty pośrednie nie leżą w jednej płaszczyźnie - '
                                  'zmień punkty albo rodzaj przewodu.')
        centres = np.stack(np.meshgrid(*[grid.lo[i] + (np.arange(nn) + .5) * res for i, nn in enumerate(grid.shape)], indexing='ij'), -1)
        err2 = None
        for n_ in cands:
            plane[0] = n_
            plane[1] = free & (np.abs((centres - start) @ n_) <= .87 * res)
            try:
                segs, full = solve()
                break
            except kernel.CadError as exc:
                if str(exc).startswith('Wyznaczanie trasy przerwane'):
                    raise
                err2 = err2 or exc
        else:
            raise err2
    if p['mode'] == 'orthogonal' and not ortho[0]:
        report.append(('warning', f'Trasa ortogonalna nie mieści łuków o promieniu {R:g} mm - część odcinków poprowadzono skośnie.'))
    if via:                                                   # przez punkty pośrednie trasa przechodzi w ich pobliżu (łuk gięcia)
        samp = np.array(sample(segs, res * .5))
        tol_w = max(2 * res, r) + R * .5
        for w in via:
            dw = float(np.min(np.linalg.norm(samp - w, axis=1)))
            if dw > tol_w:
                report.append(('warning', f'Trasa mija punkt pośredni ({w[0]:.1f}, {w[1]:.1f}, {w[2]:.1f}) o {dw:.1f} mm (promień gięcia).'))
    for q in sample(segs, res * .5):                         # łuki po zaokrągleniu - ponowna kontrola na siatce
        c = grid.index(q)
        if not free_tight[c] and np.linalg.norm(q - start) > L0 + r + res and np.linalg.norm(q - end) > L0 + r + res:
            raise kernel.CadError(f'Po zaokrągleniu łuk przewodu wchodzi w strefę odstępu przy ({q[0]:.1f}, {q[1]:.1f}, {q[2]:.1f}) - '
                                  'zmniejsz promień gięcia albo zwiększ przestrzeń.')
    curve = None
    if p['spline']:                                           # B-spline przez trasę z łukami o promieniu z zapasem (krzywizna wygładzona)
        try:
            segs_s = fillet_polyline(full, R * 1.3)
        except _Tight:
            segs_s = segs
        wire, curve = _wire(segs_s, True, R)
        rmin = _min_radius(curve)
        if rmin >= R - 1e-6:
            report.append(('ok', f'Krzywa B-spline (interpolacja): najmniejszy promień {rmin:.1f} mm.'))
        else:                                                  # dokładna zamiana łuków i odcinków na jedną krzywą B-spline
            wire, curve = _exact_bspline(segs)
            report.append(('ok', f'Krzywa B-spline (dokładna z łuków {R:g} mm) - interpolacja dawała promień {rmin:.1f} mm.'))
    else:
        wire, _c = _wire(segs, False)
    t0 = _unit(full[1] - full[0])
    up = np.array([0, 0, 1.0]) if abs(t0[2]) < .9 else np.array([0, 1.0, 0])
    binormal = plane[0] if flat else up
    if flat:
        for s in segs:                                      # taśma: każdy odcinek prostopadły do stałej binormalnej (bez skręcania)
            d = _unit((s[2] if s[0] == 'L' else s[3]) - s[1])
            if abs(float(d @ binormal)) > .02:
                raise kernel.CadError('Taśma musiałaby się skręcić (odcinek równoległy do jej szerokości) - zmień punkty albo tryb.')
    solid = sweep_solid(wire, p, full[0], t0, binormal)
    length = _length(wire)
    total = length * (1 + float(p['spare']) / 100.0)
    if float(p['max_len']) > 0 and total > float(p['max_len']):
        raise kernel.CadError(f'Przewód ma {total:.1f} mm z zapasem - więcej niż dopuszczalne {float(p["max_len"]):g} mm.')
    # dokładna kontrola na geometrii końcowej
    for nm, sh in obstacles:
        if _volume(_boolean('common', solid, sh, 'przewód a przeszkoda'))[0] > 1e-4:
            raise kernel.CadError(f'Przewód koliduje z „{nm}” - zwiększ odstęp albo rozdzielczość trasy.')
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    tight = []
    for nm, sh in obstacles:
        d = BRepExtrema_DistShapeShape(solid, sh)
        d.Perform()
        if d.IsDone() and d.Value() < float(p['clearance']) * .5 - 1e-6 and nm not in names:
            tight.append(f'{nm} ({d.Value():.2f} mm)')
    if tight:
        report.append(('warning', 'Odstęp mniejszy niż zadany przy: ' + ', '.join(tight[:4])))
    outside = _volume(_boolean('cut', solid, cavity, 'przewód poza wnętrzem'))[0]
    if outside > 1e-3:
        raise kernel.CadError(f'Przewód wychodzi poza wnętrze obudowy ({outside:.2f} mm³) - przesuń punkty do środka.')
    report.append(('ok', f'Długość geometryczna {length:.1f} mm, z zapasem {total:.1f} mm; najmniejszy promień gięcia {R:g} mm.'))
    return dict(points=full, segments=segs, wire=wire, solid=solid, length=length, total=total, report=report, grid=grid)


def _nearest_free(free, grid, q):
    c = grid.index(q)
    if free[c]:
        return c
    cand = np.argwhere(free)
    return tuple(int(x) for x in cand[np.argmin(np.linalg.norm(cand - np.array(c), axis=1))])


def _blockers(a, b, r, obstacles):
    """Obszar blokujący: przeszkody przecinające korytarz (walec o promieniu 3r) między punktami."""
    import cadquery as cq
    from .enclosure import _boolean, _volume
    d = np.asarray(b, float) - np.asarray(a, float)
    if np.linalg.norm(d) < 1e-6:
        return ''
    cor = cq.Solid.makeCylinder(max(3 * r, 2.0), float(np.linalg.norm(d)), cq.Vector(*a), cq.Vector(*_unit(d))).wrapped
    names = [nm for nm, sh in obstacles if _volume(_boolean('common', cor, sh, 'korytarz'))[0] > 1e-3]
    return (' - przejście blokuje: ' + ', '.join(names[:5])) if names else ''


def clips(part_shape, res, p, components=()):
    """Uchwyty wzdłuż trasy: co rozstaw, gdzie powierzchnia części jest w zasięgu - pierścień (otwarty / zamknięty /
    z mostkiem pod opaskę), kanał na odcinku, prowadnica w łuku, odciążenie przy złączu; podpora do powierzchni."""
    import cadquery as cq
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.gp import gp_Pnt
    from .enclosure import _boolean, _volume
    p = dict(DEFAULTS, **p)
    kind = p['clip']
    if kind == 'none':
        return []
    r = cable_radius(p)
    g, t, w = float(p['clip_gap']), float(p['clip_t']), float(p['clip_w'])
    Lc = w if kind != 'channel' else min(float(p['clip_pitch']) * .6, 20.0)
    marks, acc = [], 0.0                                       # punkty na odcinkach prostych (uchwyt prosty nie może siedzieć na łuku)
    for s in res['segments']:
        if s[0] == 'A':
            acc += float(np.linalg.norm(s[3] - s[1]))
            continue
        a_, b_ = s[1], s[2]
        ln = float(np.linalg.norm(b_ - a_))
        for t in np.arange(0.0, ln + 1e-9, .5):
            if Lc / 2 + .5 <= t <= ln - Lc / 2 - .5:
                marks.append((acc + t, a_ + (b_ - a_) * (t / ln), _unit(b_ - a_)))
        acc += ln
    total = acc
    stations = []
    if kind == 'strain':
        if marks:
            stations = [marks[0], marks[-1]]
    elif kind == 'corner':
        for s in res['segments']:
            if s[0] == 'A':
                stations.append(('arc', s))
    else:
        nxt = float(p['clip_pitch']) / 2
        for m_ in marks:
            if m_[0] >= nxt and m_[0] < total - float(p['straight']):
                stations.append(m_)
                nxt = m_[0] + float(p['clip_pitch'])
    out = []
    for st in stations:
        if st[0] == 'arc':
            a, m, b = st[1][1:]
            q, tang = m, _unit(b - a)
        else:
            q, tang = st[1], st[2]
        d = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, q))).Vertex(), part_shape)
        d.Perform()
        if not d.IsDone() or d.Value() > r + float(p['reach']):
            continue
        wpt = np.array(d.PointOnShape2(1).Coord())
        u_w = _unit(wpt - q)
        n = wpt - q
        n = n - tang * float(n @ tang)                            # prostopadle do przewodu - ortonormalna rama uchwytu
        if np.linalg.norm(n) < 1e-6:
            continue
        n = _unit(n)
        ring_r = r + g
        L = Lc
        if st[0] == 'arc':                                      # prowadnica w łuku: krótka, pierścień z luzem na strzałkę łuku
            L = min(w, 2.0)
            ring_r += L * L / (8 * max(float(p['min_bend']), r)) + .1
        base = q - tang * L / 2
        outer = cq.Solid.makeCylinder(ring_r + t, L, cq.Vector(*base), cq.Vector(*tang)).wrapped
        inner = cq.Solid.makeCylinder(ring_r, L + 2, cq.Vector(*(base - tang)), cq.Vector(*tang)).wrapped
        ring = _boolean('cut', outer, inner, 'uchwyt')
        if kind in ('open', 'channel', 'corner'):                 # otwarty od strony przeciwnej do powierzchni
            side = _unit(np.cross(tang, n))
            from .enclosure import _make_box
            opening = kernel.transformed(cq.Shape.cast(_make_box((-ring_r * .7, 0.0, -1.0), (ring_r * .7, ring_r + t + 1, L + 1))),
                                         np.column_stack([side, -n, tang]), base).wrapped
            ring = _boolean('cut', ring, opening, 'otwarcie klipsa')
        cosw = float(n @ u_w)
        if cosw < .3:
            continue
        span = float(np.linalg.norm(wpt - q)) / cosw              # do ścianki wzdłuż kierunku podpory
        side = _unit(np.cross(tang, n))
        from .enclosure import _make_box
        post = kernel.transformed(cq.Shape.cast(_make_box((-w / 2, ring_r + t * .5, 0.0), (w / 2, span + .5, L))),
                                  np.column_stack([side, n, tang]), base).wrapped
        post = _boolean('cut', post, inner, 'podpora uchwytu')
        body = _boolean('fuse', ring, post, 'uchwyt przewodu')
        if kind == 'tie':                                        # mostek pod opaskę: szczelina w podporze
            slot = kernel.transformed(cq.Shape.cast(_make_box((-w, ring_r + t + .5, L * .25), (w, ring_r + t + 1.5, L * .75))),
                                      np.column_stack([side, n, tang]), base).wrapped
            body = _boolean('cut', body, slot, 'szczelina opaski')
        if any(_volume(_boolean('common', body, c, 'uchwyt a komponent'))[0] > 1e-4 for c in (*components, res['solid'])):
            continue
        from .enclosure import _solids
        if len([x for x in _solids(body) if _volume(x)[0] > 1e-6]) != 1 or _volume(_boolean('common', body, part_shape, 'uchwyt a ścianka'))[0] <= 1e-4:
            continue                                              # uchwyt musi być jedną bryłą opartą na ściance
        out.append(body)
    return out
