"""Przyciąganie kursora w szkicu: punkty styku, środki, krawędzie i okręgi szkiców, przecięcia, narożniki i krawędzie ściany
(albo innych brył) leżących na płaszczyźnie szkicu oraz narożniki kratek siatki.

Kursor NIE klei się do wszystkiego w ruchu: kandydat do przyciągnięcia jest wyznaczany przy każdym ruchu (szybko, rzutowanie
całych tablic punktów naraz), ale przyciąganie włącza się dopiero, gdy kursor chwilę (DWELL) zostanie przy tym samym miejscu
- patrz Dwell. Alt wyłącza przyciąganie."""
from __future__ import annotations
import math
import time
import numpy as np
from . import kernel

LEVELS = (.01, .02, .05, .1, .2, .5, 1, 2, 5, 10)
RADIUS = 12.0         # px - zasięg punktów i krawędzi
GRID_RADIUS = 6.0     # px - narożnik kratki tylko blisko (siatka jest wszędzie, więc mniejszy zasięg)
DWELL = 0.25          # s - tyle kursor musi zostać przy punkcie, żeby przyciąganie się włączyło
PLANE_TOL = 1e-4      # mm - krawędź bryły leży na płaszczyźnie szkicu

# priorytet (mniejszy wygrywa): punkty geometrii, środki, krawędzie, siatka
P_POINT, P_MID, P_EDGE, P_GRID = 0, 1, 3, 5


class SketchGeometry:
    """Punkty / odcinki / okręgi szkiców i brył leżących na płaszczyźnie szkicowania (we współrzędnych u, v), gotowe do szybkiego rzutowania."""

    def __init__(self, bodies, plane):
        self.plane = plane
        self.points = []     # (u, v, etykieta, priorytet)
        self.segments = []   # ((u, v), (u, v), etykieta)
        self.circles = []
        self.intersections = []
        frame = kernel.frame_of(plane)
        self._o, self._x, self._y, self._n = (np.array(v, float) for v in (frame.origin, frame.xdir, frame.ydir, frame.normal))
        sketch_segments = []
        for body in bodies:
            if not body.visible:
                continue
            try:
                if body.kind == 'sketch' and body.plane == plane:
                    before = len(self.segments)
                    self._add_sketch(body.shape)
                    sketch_segments += self.segments[before:]
                elif body.kind == 'solid':
                    self._add_solid(body.shape)
            except Exception:
                continue
        self._intersect(sketch_segments)
        self._arrays()

    # --- zbieranie geometrii ---
    def _uv(self, p):
        d = np.asarray(p, float) - self._o
        return float(d @ self._x), float(d @ self._y)

    def _on_plane(self, p):
        return abs(float((np.asarray(p, float) - self._o) @ self._n)) < PLANE_TOL

    def _add_edge(self, edge, end_label, edge_label):
        uv = lambda p: self._uv(p.toTuple())
        kind = edge.geomType()
        a, b = uv(edge.startPoint()), uv(edge.endPoint())
        if kind == 'LINE':
            self.points += [(*a, end_label, P_POINT), (*b, end_label, P_POINT), ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 'Środek', P_MID)]
            self.segments.append((a, b, edge_label))
        elif kind == 'CIRCLE':
            c = uv(edge.arcCenter())
            r = edge.radius()
            if edge.IsClosed():
                self.points.append((*c, 'Środek', P_POINT))
                self.circles.append((c, r))
            else:
                m = uv(edge.positionAt(.5))
                self.points += [(*a, end_label, P_POINT), (*b, end_label, P_POINT), (*m, 'Środek', P_MID), (*c, 'Środek łuku', P_MID)]
                pts = [uv(edge.positionAt(t)) for t in np.linspace(0, 1, 17)]
                self.segments += [(p, q, edge_label) for p, q in zip(pts[:-1], pts[1:])]
        else:
            pts = [uv(edge.positionAt(t)) for t in np.linspace(0, 1, 25)]
            if not edge.IsClosed():
                self.points += [(*pts[0], end_label, P_POINT), (*pts[-1], end_label, P_POINT)]
            self.segments += [(p, q, edge_label) for p, q in zip(pts[:-1], pts[1:])]

    def _add_sketch(self, shape):
        for edge in shape.Edges():
            self._add_edge(edge, 'Punkt styku', 'Krawędź')
        self.points.append((*self._uv(shape.Center().toTuple()), 'Środek', P_POINT))

    def _add_solid(self, shape):
        """Krawędzie i narożniki bryły leżące na płaszczyźnie szkicu - np. obrys ścianki, na której rysujemy."""
        bb = shape.BoundingBox()
        corners = np.array([[x, y, z] for x in (bb.xmin, bb.xmax) for y in (bb.ymin, bb.ymax) for z in (bb.zmin, bb.zmax)])
        side = (corners - self._o) @ self._n
        if side.min() > PLANE_TOL or side.max() < -PLANE_TOL:
            return          # bryła nie dotyka płaszczyzny szkicu
        seen = set()
        for face in shape.Faces():
            try:
                if not kernel.is_planar_face(face):
                    continue
                if abs(abs(float(np.array(face.normalAt().toTuple()) @ self._n)) - 1) > 1e-6 or not self._on_plane(face.Center().toTuple()):
                    continue
            except Exception:
                continue
            for edge in face.Edges():
                key = edge.hashCode()
                if key in seen:
                    continue
                seen.add(key)
                self._add_edge(edge, 'Narożnik', 'Krawędź ściany')
            self.points.append((*self._uv(face.Center().toTuple()), 'Środek ściany', P_MID))

    def _intersect(self, segs):
        segs = segs if len(segs) <= 160 else []
        for i in range(len(segs)):
            A, B, _ = segs[i]
            r = (B[0] - A[0], B[1] - A[1])
            for j in range(i + 1, len(segs)):
                C, D, _ = segs[j]
                q = (D[0] - C[0], D[1] - C[1])
                den = r[0] * q[1] - r[1] * q[0]
                if abs(den) < 1e-10:
                    continue
                ac = (C[0] - A[0], C[1] - A[1])
                t = (ac[0] * q[1] - ac[1] * q[0]) / den
                s = (ac[0] * r[1] - ac[1] * r[0]) / den
                if -1e-8 <= t <= 1 + 1e-8 and -1e-8 <= s <= 1 + 1e-8:
                    self.points.append((A[0] + t * r[0], A[1] + t * r[1], 'Punkt styku', P_POINT))

    def _arrays(self):
        self.pt_uv = np.array([(p[0], p[1]) for p in self.points], float).reshape(-1, 2)
        self.pt_label = [p[2] for p in self.points]
        self.pt_prio = np.array([p[3] for p in self.points], float)
        self.seg_a = np.array([s[0] for s in self.segments], float).reshape(-1, 2)
        self.seg_b = np.array([s[1] for s in self.segments], float).reshape(-1, 2)
        self.seg_label = [s[2] for s in self.segments]
        self.pt_world = self.world(self.pt_uv)
        self.seg_world = (self.world(self.seg_a), self.world(self.seg_b))

    def world(self, uv):
        uv = np.asarray(uv, float).reshape(-1, 2)
        return self._o + uv[:, :1] * self._x + uv[:, 1:2] * self._y


def _project(view, world):
    """Rzut wielu punktów naraz: (xy, maska widocznych)."""
    if not len(world):
        return np.zeros((0, 2)), np.zeros(0, bool)
    xy, _, w = view.project_points(np.asarray(world, float))
    if len(xy) != len(world):
        return np.zeros((len(world), 2)), np.zeros(len(world), bool)
    return np.asarray(xy, float), np.asarray(w, float) > 0


def grid_step(view, geometry):
    """Krok siatki dopasowany do powiększenia (min. 12 px między liniami), jak rysowana siatka."""
    s = _project(view, geometry.world([(0, 0), (1, 0)]))[0]
    px = float(np.hypot(*(s[1] - s[0]))) if len(s) == 2 else 1.0
    return next((g for g in LEVELS if g * px >= 12), 10)


def candidate(view, geometry, x, y, raw):
    """Najlepszy punkt do przyciągnięcia w pobliżu kursora: (u, v, etykieta) albo None."""
    best = None      # (priorytet, odległość px, u, v, etykieta)
    cursor = np.array([x, y], float)
    if len(geometry.pt_uv):
        xy, ok = _project(view, geometry.pt_world)
        d = np.linalg.norm(xy - cursor, axis=1)
        d[~ok] = np.inf
        near = np.where(d <= RADIUS)[0]
        if len(near):
            i = min(near, key=lambda k: (geometry.pt_prio[k], d[k]))
            best = (geometry.pt_prio[i], d[i], geometry.pt_uv[i][0], geometry.pt_uv[i][1], geometry.pt_label[i])
    if len(geometry.seg_a) and (best is None or best[0] > P_EDGE):
        pa, oka = _project(view, geometry.seg_world[0])
        pb, okb = _project(view, geometry.seg_world[1])
        delta = pb - pa
        l2 = (delta * delta).sum(axis=1)
        t = np.clip(((cursor - pa) * delta).sum(axis=1) / np.maximum(l2, 1e-9), 0, 1)
        d = np.linalg.norm(pa + delta * t[:, None] - cursor, axis=1)
        d[~(oka & okb) | (l2 < .001)] = np.inf
        j = int(np.argmin(d))
        if d[j] <= RADIUS:
            u, v = geometry.seg_a[j] + (geometry.seg_b[j] - geometry.seg_a[j]) * t[j]
            best = (P_EDGE, d[j], float(u), float(v), geometry.seg_label[j])
    if best is None or best[0] > P_EDGE:
        for c, r in geometry.circles:
            if r <= 1e-5:
                continue
            ang = math.atan2(raw[1] - c[1], raw[0] - c[0])
            u, v = c[0] + r * math.cos(ang), c[1] + r * math.sin(ang)
            s = _project(view, geometry.world([(u, v)]))
            if s[1].all():
                d = float(np.hypot(*(s[0][0] - cursor)))
                if d <= RADIUS and (best is None or (P_EDGE, d) < (best[0], best[1])):
                    best = (P_EDGE, d, u, v, 'Okrąg')
    if best is None:
        grid = grid_step(view, geometry)
        u, v = round(raw[0] / grid) * grid, round(raw[1] / grid) * grid
        s = _project(view, geometry.world([(u, v)]))
        if s[1].all() and float(np.hypot(*(s[0][0] - cursor))) <= GRID_RADIUS:
            best = (P_GRID, 0.0, u, v, 'Siatka')
    return None if best is None else (float(best[2]), float(best[3]), best[4])


class Dwell:
    """Przyciąganie z opóźnieniem: kandydat musi zostać pod kursorem przez DWELL sekund. Potem punkt jest trzymany, dopóki kursor
    nie odjedzie dalej niż RADIUS od miejsca włączenia (drżenie ręki go nie gubi); wzdłuż krawędzi punkt podąża za kursorem."""

    def __init__(self, delay=DWELL, clock=time.monotonic):
        self.delay, self.clock = delay, clock
        self.reset()

    def reset(self):
        self._pending = None     # (klucz, czas, ekranowe x, y)
        self._engaged = None     # (etykieta, ekranowe x, y)

    @staticmethod
    def _key(c):
        return (c[2], round(c[0], 6), round(c[1], 6)) if c[2] not in ('Krawędź', 'Krawędź ściany', 'Okrąg') else (c[2],)

    def update(self, c, x, y):
        """c = kandydat z candidate() albo None. Zwraca (punkt przyciągnięty albo None, czy trzeba odczekać i zapytać ponownie)."""
        now = self.clock()
        if self._engaged is not None:
            label, ex, ey = self._engaged
            if c is not None and c[2] == label and math.hypot(x - ex, y - ey) <= RADIUS:
                return c, False
            self._engaged = None
        if c is None:
            self._pending = None
            return None, False
        key = self._key(c)
        if self._pending is not None and self._pending[0] == key and math.hypot(x - self._pending[2], y - self._pending[3]) <= RADIUS:
            if now - self._pending[1] >= self.delay:
                self._engaged, self._pending = (c[2], x, y), None
                return c, False
            return None, True
        self._pending = (key, now, x, y)
        return None, True


def snap(view, plane, geometry, x, y, raw):
    """Natychmiastowe przyciąganie (bez opóźnienia): (u, v, etykieta); bez kandydata zwraca surowy punkt i etykietę None."""
    c = candidate(view, geometry, x, y, raw)
    return c if c is not None else (float(raw[0]), float(raw[1]), None)
