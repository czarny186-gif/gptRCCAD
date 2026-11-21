"""TWIST – szybki podgląd skręcania na KOPII siatki wyświetlania (sam numpy, bez Open CASCADE i bez okna).

Siatka wyświetlania ma duże trójkąty (np. ściana prostopadłościanu = 2 trójkąty), więc samo obrócenie jej wierzchołków
nie pokazałoby skręcenia. Kopia siatki jest najpierw cięta płaszczyznami prostopadłymi do osi (warstwy w zakresie
skręcenia): każdy trójkąt przecinający płaszczyznę dzieli się na trzy. Podział zależy tylko od krawędzi, więc sąsiednie
trójkąty dostają te same punkty i po skręceniu nie powstają szczeliny. Linie krawędzi dostają punkty w tych samych
miejscach. Cięcie liczy się raz dla bryły, osi i zakresu (pamięć podręczna w oknie) - zmiana kąta (pole liczbowe,
przeciąganie pierścienia) tylko obraca gotowe punkty silnikiem rccad.twist_math, bez Open CASCADE.

Oryginalna siatka i bryła B-Rep nie są zmieniane."""
from __future__ import annotations

import math

import numpy as np

STEP_DEG = 4.0              # największy skok kąta między sąsiednimi warstwami podglądu
MIN_LAYERS, MAX_LAYERS = 8, 256
TRIANGLE_BUDGET = 600_000   # górna granica trójkątów podglądu (płynność także na zintegrowanej grafice)
SLOPE = {'linear': 1.0, 'smoothstep': 1.5}


def layer_count(angle, kind='linear', power=2.0, triangles=0):
    """Liczba warstw dla kąta (zaokrąglona w górę do potęgi dwójki, żeby przeciąganie pierścienia rzadko
    wymagało ponownego cięcia); ograniczona tak, żeby podgląd nie przekroczył budżetu trójkątów."""
    slope = SLOPE.get(kind, float(power))
    need = max(1, math.ceil(abs(float(angle)) * slope / STEP_DEG))
    n = MIN_LAYERS
    while n < need and n < MAX_LAYERS:
        n *= 2
    if triangles:
        while n > MIN_LAYERS and triangles * (2 * n + 1) > TRIANGLE_BUDGET:
            n //= 2
    return n


def cut_planes(start, end, layers):
    """Położenia płaszczyzn cięcia wzdłuż osi - wnętrze zakresu podzielone na równe warstwy."""
    return [start + (end - start) * k / layers for k in range(1, layers)]


def slice_triangles(vertices, triangles, origin, direction, planes):
    """Kopia siatki pocięta płaszczyznami t = const (t - współrzędna wzdłuż osi). Zwraca (wierzchołki, trójkąty).

    Każdy trójkąt (wierzchołki posortowane po t: v0, v1, v2) dzieli się od razu na pasy między kolejnymi płaszczyznami:
    na krawędzi v0-v2 i na łamanej v0-v1-v2 powstają punkty przecięcia, pas = czworokąt (2 trójkąty), a pas
    z wierzchołkiem v1 - pięciokąt (3 trójkąty). Liczba trójkątów rośnie liniowo z liczbą przeciętych płaszczyzn.
    Punkt na krawędzi liczy się zawsze od jej końca o mniejszym t - sąsiednie trójkąty dostają te same punkty."""
    V = np.array(vertices, dtype=float, copy=True).reshape(-1, 3)
    T = np.array(triangles, dtype=np.int64, copy=True).reshape(-1, 3)
    P = np.sort(np.asarray(planes, float))
    if not len(T) or not len(P):
        return V, T
    t = (V - np.asarray(origin, float)) @ np.asarray(direction, float)
    order = np.argsort(t[T], axis=1, kind='stable')
    S = np.take_along_axis(T, order, axis=1)                  # v0, v1, v2 posortowane po t
    t0, t1, t2 = t[S[:, 0]], t[S[:, 1]], t[S[:, 2]]
    lo = np.searchsorted(P, t0, 'right')
    hi = np.searchsorted(P, t2, 'left')
    n = np.maximum(hi - lo, 0)
    cut = n > 0
    if not cut.any():
        return V, T
    keep = T[~cut]
    S, t0, t1, t2, lo, n = S[cut], t0[cut], t1[cut], t2[cut], lo[cut], n[cut]
    even = np.isin(order[cut, 0] * 9 + order[cut, 1] * 3 + order[cut, 2], (0 * 9 + 1 * 3 + 2, 1 * 9 + 2 * 3 + 0, 2 * 9 + 0 * 3 + 1))
    m = len(S)
    # przekroje: 0 = v0, 1..n = płaszczyzny, n+1 = v2
    count = n + 2
    row = np.repeat(np.arange(m), count)
    first = np.cumsum(count) - count
    k = np.arange(len(row)) - first[row]
    c = np.where(k == 0, t0[row], np.where(k == count[row] - 1, t2[row], P[np.clip(lo[row] + k - 1, 0, len(P) - 1)]))
    v0, v1, v2 = V[S[row, 0]], V[S[row, 1]], V[S[row, 2]]
    tr0, tr1, tr2 = t0[row], t1[row], t2[row]
    with np.errstate(divide='ignore', invalid='ignore'):
        wl = np.where(tr2 > tr0, (c - tr0) / (tr2 - tr0), 0.0)
        low = c <= tr1
        ws = np.where(low, np.where(tr1 > tr0, (c - tr0) / (tr1 - tr0), 1.0), np.where(tr2 > tr1, (c - tr1) / (tr2 - tr1), 0.0))
    L = v0 + (v2 - v0) * wl[:, None]
    Sp = np.where(low[:, None], v0 + (v1 - v0) * ws[:, None], v1 + (v2 - v1) * ws[:, None])
    # wspólne wierzchołki (etap 10): punkt na krawędzi i płaszczyźnie jest ten sam dla obu sąsiednich trójkątów, a przekroje
    # 0 i ostatni to oryginalne wierzchołki v0 / v2 - bez powtórzeń (mniej pamięci, szybsze skręcanie i rysowanie)
    s0, s1, s2 = S[row, 0], S[row, 1], S[row, 2]
    plane = np.clip(lo[row] + k - 1, 0, len(P) - 1)
    first, last = k == 0, k == count[row] - 1
    inner = ~(first | last)
    ea_l, eb_l = np.minimum(s0, s2), np.maximum(s0, s2)
    ea_s = np.where(low, np.minimum(s0, s1), np.minimum(s1, s2))
    eb_s = np.where(low, np.maximum(s0, s1), np.maximum(s1, s2))
    nv = len(V)
    keys = np.concatenate([(ea_l[inner] * nv + eb_l[inner]) * len(P) + plane[inner],
                           (ea_s[inner] * nv + eb_s[inner]) * len(P) + plane[inner]])
    points = np.concatenate([L[inner], Sp[inner]])
    unique, first_at, inverse = np.unique(keys, return_index=True, return_inverse=True)
    base = len(V)
    V = np.concatenate([V, points[first_at]])
    n_inner = int(inner.sum())
    Li = np.where(first, s0, np.where(last, s2, 0))
    # łamana v0-v1-v2 na końcach pasa: v0 / v2, chyba że v1 leży na tym samym poziomie co koniec (wtedy przekrój wypada w v1)
    Si = np.where(first, np.where(tr1 <= tr0, s1, s0), np.where(last, np.where(tr1 >= tr2, s1, s2), 0))
    Li[inner] = base + inverse[:n_inner]
    Si[inner] = base + inverse[n_inner:]
    # pasy między przekrojem k i k+1 (ten sam trójkąt)
    a = np.nonzero(k[:-1] < count[row[:-1]] - 1)[0]           # indeks przekroju k, k+1 istnieje w tym samym wierszu
    b = a + 1
    r = row[a]
    v1i = S[r, 1]
    pent = (c[a] < t1[r]) & (t1[r] < c[b])
    tri1 = np.column_stack([Li[a], Li[b], Si[b]])
    tri2 = np.column_stack([Li[a], Si[b], Si[a]])
    tri2p = np.column_stack([Li[a], Si[b], v1i])
    tri3p = np.column_stack([Li[a], v1i, Si[a]])
    new = np.concatenate([tri1, tri2[~pent], tri2p[pent], tri3p[pent]])
    flip = np.concatenate([even[r], even[r][~pent], even[r][pent], even[r][pent]])
    new[flip] = new[flip][:, ::-1]                             # ta sama orientacja co trójkąt oryginalny
    new = new[(new[:, 0] != new[:, 1]) & (new[:, 1] != new[:, 2]) & (new[:, 0] != new[:, 2])]   # zdegenerowane (wierzchołek końca pasa)
    return V, np.concatenate([keep, new])


def densify_polyline(points, origin, direction, planes):
    """Linia krawędzi z dodatkowymi punktami tam, gdzie przecina płaszczyzny cięcia (skręca się razem z siatką)."""
    P = np.asarray(points, float).reshape(-1, 3)
    if len(P) < 2 or not len(planes):
        return P.copy()
    d = np.asarray(direction, float)
    t = (P - np.asarray(origin, float)) @ d
    planes = np.asarray(planes, float)
    lo, hi = np.minimum(t[:-1], t[1:]), np.maximum(t[:-1], t[1:])
    counts = np.searchsorted(planes, hi, 'left') - np.searchsorted(planes, lo, 'right')
    pieces = np.maximum(counts, 0) + 1
    if (pieces == 1).all():
        return P.copy()
    seg = np.repeat(np.arange(len(P) - 1), pieces)
    within = np.arange(len(seg)) - np.repeat(np.cumsum(pieces) - pieces, pieces)
    w = (within / np.repeat(pieces, pieces))[:, None]
    out = P[seg] + (P[seg + 1] - P[seg]) * w
    return np.concatenate([out, P[-1:]])


class SlicedMesh:
    """Pocięta kopia siatki: wierzchołki, trójkąty i linie krawędzi gotowe do skręcania dowolnym kątem.
    Przechowywana w pojedynczej precyzji (float32 / uint32 - jak siatka wyświetlania): o połowę mniej pamięci."""

    def __init__(self, vertices, triangles, edges, origin, direction, planes):
        v, t = slice_triangles(vertices, triangles, origin, direction, planes)
        self.vertices, self.triangles = v.astype(np.float32), t.astype(np.uint32)
        self.edges = {k: densify_polyline(p, origin, direction, planes).astype(np.float32) for k, p in (edges or {}).items()}
        self.planes = list(planes)
        # wszystkie linie krawędzi w jednej tablicy - jedno obracanie na zmianę kąta zamiast osobnego dla każdej krawędzi
        self._edge_keys = list(self.edges)
        lengths = [len(self.edges[k]) for k in self._edge_keys]
        self._edge_split = np.cumsum(lengths)[:-1] if lengths else np.zeros(0, int)
        self._edge_points = (np.concatenate([self.edges[k] for k in self._edge_keys]) if lengths and sum(lengths)
                             else np.zeros((0, 3), np.float32))

    @property
    def nbytes(self):
        return int(self.vertices.nbytes + self.triangles.nbytes + 2 * self._edge_points.nbytes)

    def twisted(self, field):
        """(wierzchołki, linie krawędzi) po skręceniu polem rccad.twist_math.TwistField - nowe tablice float32."""
        vertices = field.apply(self.vertices).astype(np.float32) if len(self.vertices) else self.vertices.copy()
        if not len(self._edge_points):
            return vertices, {k: p.copy() for k, p in self.edges.items()}
        moved = field.apply(self._edge_points).astype(np.float32)
        return vertices, dict(zip(self._edge_keys, np.split(moved, self._edge_split)))


class SliceCache:
    """Kilka ostatnich pociętych siatek (klucz: siatka, oś, zakres, liczba warstw) - powrót do wcześniejszych ustawień
    (np. przełączenie rozkładu tam i z powrotem, strzałka zakresu wraca) nie tnie siatki od nowa. Ograniczona liczbą
    wpisów i łączną pamięcią, żeby duże modele nie zajmowały RAM. Wpis trzyma też siatkę źródłową (owner), więc jej
    id() w kluczu nie może zostać użyte ponownie przez inną siatkę, dopóki wpis jest w pamięci."""

    def __init__(self, entries=4, budget=256 * 2 ** 20):
        self.entries, self.budget = entries, budget
        self._items = []                         # [(klucz, SlicedMesh, owner)] - od najstarszego
        self.hits = self.misses = 0

    def peek(self, key):
        """Siatka z pamięci (oznaczona jako ostatnio używana) albo None."""
        for i, item in enumerate(self._items):
            if item[0] == key:
                self._items.append(self._items.pop(i))
                self.hits += 1
                return item[1]
        return None

    def put(self, key, value, owner=None):
        self._items = [item for item in self._items if item[0] != key]
        self._items.append((key, value, owner))
        while len(self._items) > self.entries or (len(self._items) > 1 and self.nbytes > self.budget):
            self._items.pop(0)

    def get(self, key, build, owner=None):
        value = self.peek(key)
        if value is None:
            self.misses += 1
            value = build()
            self.put(key, value, owner)
        return value

    @property
    def nbytes(self):
        return sum(item[1].nbytes for item in self._items)

    def __len__(self):
        return len(self._items)

    def clear(self):
        self._items.clear()
