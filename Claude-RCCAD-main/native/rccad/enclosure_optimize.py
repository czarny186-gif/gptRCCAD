"""Generator obudów - etap 21: optymalizacja obudowy i rozmieszczenia komponentów.

Tryb A - tylko obudowa: komponenty bez zmian, szukana orientacja układu obudowy (obrót wokół osi pionowej albo
dowolna orientacja: kierunki „do góry” z osi globalnych i ramki OBB, potem obrót wokół nich), która minimalizuje cel.
Tryb B - także rozmieszczenie: niezablokowane komponenty (albo całe zespoły) są przestawiane i obracane o dozwolone
kąty; wynik jest wyłącznie PROPOZYCJĄ - dokument nie zmienia się bez zatwierdzenia.

Szybki etap: prostopadłościany AABB komponentów w układzie obudowy (dla każdej dozwolonej orientacji liczone z punktów
siatki), dekoder „punktów skrajnych” (bin packing: kolejne elementy w najlepszym dopuszczalnym punkcie), wyżarzanie
symulowane po kolejności i orientacjach (ograniczony zbiór orientacji), dosuwanie do ścianek dla wymaganego dostępu do
złączy. Najlepsze warianty są sprawdzane DOKŁADNIE na bryłach B-Rep (wspólna objętość, odległości DistShapeShape,
strefy zabronione i serwisowe, dokładna ramka) - wariant naruszający ograniczenie nigdy nie jest pokazany jako poprawny.

Wynik ma znormalizowaną ocenę ważoną (cel / wartość obecna). To przeszukiwanie heurystyczne: najlepszy znaleziony wariant,
bez gwarancji optimum globalnego."""
from __future__ import annotations

import math
import time

import numpy as np

from . import kernel

GOALS = ('volume', 'area', 'material', 'mass', 'height', 'width', 'depth', 'cable', 'proportion')
GOAL_LABELS = {'volume': 'Objętość zewnętrzna', 'area': 'Powierzchnia zewnętrzna', 'material': 'Ilość materiału', 'mass': 'Masa',
               'height': 'Wysokość', 'width': 'Szerokość (X)', 'depth': 'Głębokość (Y)', 'cable': 'Długość przewodów',
               'proportion': 'Proporcje (najdłuższy / najkrótszy wymiar)'}
ROTATIONS = ('none', 'z90', 'all90')
ROTATION_LABELS = {'none': 'Bez obrotów komponentów', 'z90': 'Obroty o 90° wokół osi pionowej', 'all90': 'Obroty o 90° wokół wszystkich osi'}
ENC_ROT = ('z', 'all')
ENC_ROT_LABELS = {'z': 'Obudowa: obrót wokół osi pionowej', 'all': 'Obudowa: dowolna orientacja'}
ACCURACY = {'fast': 300, 'normal': 1500, 'accurate': 6000}
ACCURACY_LABELS = {'fast': 'Dokładność: szybka', 'normal': 'Dokładność: normalna', 'accurate': 'Dokładność: wysoka'}
SIDES = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')
DEFAULTS = dict(mode='A', weights={'volume': 1.0}, density=1.24, gap=2.0, rotations='z90', enc_rotation='z', max_dims=[0.0, 0.0, 0.0],
                locked_walls=[], forbidden=[], accuracy='normal', time_limit=10.0, top=5, seed=1)
PENALTY = 1e3
TOL = 1e-6


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _rot(axis, deg):
    a = math.radians(deg)
    k = _unit(axis)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(a) * K + (1 - math.cos(a)) * (K @ K)


def rotation_set(kind):
    """Dozwolone orientacje komponentu w układzie obudowy: 1, 4 (wokół Z) albo 24 (obroty sześcianu)."""
    if kind == 'none':
        return [np.eye(3)]
    if kind == 'z90':
        return [np.round(_rot((0, 0, 1), 90 * k)) for k in range(4)]
    out = []
    for up in ((0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)):
        base = np.round(_rot(np.cross((0, 0, 1), up), 90)) if abs(up[2]) != 1 else (np.eye(3) if up[2] == 1 else np.round(_rot((1, 0, 0), 180)))
        for k in range(4):
            m = np.round(_rot(up, 90 * k) @ base)
            if not any(np.allclose(m, q) for q in out):
                out.append(m)
    return out


def _points(shape, limit=600):
    """Punkty kształtu do szybkiego etapu: wierzchołki triangulacji (skrajne wzdłuż wielu kierunków przy dużych siatkach)."""
    import cadquery as cq
    mesh = kernel.display_mesh(cq.Shape.cast(shape) if not hasattr(shape, 'wrapped') else shape)
    v = np.asarray(mesh.vertices, float)
    if len(v) > limit:
        rng = np.random.default_rng(0)
        dirs = rng.normal(size=(limit // 2, 3))
        dirs /= np.linalg.norm(dirs, axis=1)[:, None]
        proj = v @ dirs.T
        idx = np.unique(np.r_[proj.argmax(0), proj.argmin(0)])
        v = v[idx]
    return v


# ---------------------------------------------------------------------------------------------- miary
def metrics(content_lo, content_hi, clear, walls, density, cable=0.0):
    """Miary obudowy prostopadłościennej z zawartości (AABB komponentów w układzie obudowy) + odstępy + ścianki."""
    lo = np.asarray(content_lo, float) - np.array([clear['x-'], clear['y-'], clear['z-']])
    hi = np.asarray(content_hi, float) + np.array([clear['x+'], clear['y+'], clear['z+']])
    inner = np.maximum(hi - lo, 0.0)
    outer = inner + np.array([walls['x-'] + walls['x+'], walls['y-'] + walls['y+'], walls['bottom'] + walls['top']])
    vol = float(np.prod(outer))
    material = vol - float(np.prod(inner))
    return dict(dims=[float(x) for x in outer], inner=[float(x) for x in inner], volume=vol,
                area=float(2 * (outer[0] * outer[1] + outer[1] * outer[2] + outer[0] * outer[2])), material=material,
                mass=material * float(density) / 1000.0, height=float(outer[2]), width=float(outer[0]), depth=float(outer[1]),
                cable=float(cable), proportion=float(outer.max() / max(outer.min(), 1e-9)))


def score(m, base, weights):
    """Znormalizowana ocena ważona: Σ w·(cel / cel obecny) / Σ w (1 = jak teraz, mniej = lepiej)."""
    tot, acc = 0.0, 0.0
    for g, w in (weights or {}).items():
        w = float(w)
        if w <= 0 or g not in GOALS:
            continue
        b = float(base.get(g, 0.0))
        acc += w * (float(m[g]) / b if b > 1e-12 else (0.0 if float(m[g]) <= 1e-12 else 1.0 + float(m[g])))
        tot += w
    if tot <= 0:
        raise kernel.CadError('Ustaw wagę co najmniej jednego celu optymalizacji.')
    return acc / tot


# ---------------------------------------------------------------------------------------------- problem
class Problem:
    """Dane optymalizacji w układzie obudowy E (wiersze - osie obudowy w świecie)."""

    def __init__(self, items, axes, clear, walls, p, cables=(), cancel=None, progress=None):
        self.p = dict(DEFAULTS, **p)
        self.E = np.asarray(axes, float)
        self.clear, self.walls = clear, walls
        self.cancel, self.progress = cancel, progress
        self.gap = float(self.p['gap'])
        self.rots = rotation_set(self.p['rotations'])
        groups = {}
        for it in items:
            key = it.get('group') or ('#' + it['id'])
            groups.setdefault(key, []).append(it)
        self.units = []
        for key, members in groups.items():
            pts = np.vstack([np.asarray(m['points'], float) for m in members]) @ self.E.T      # do układu obudowy
            lo0, hi0 = pts.min(0), pts.max(0)
            c0 = (lo0 + hi0) / 2
            locked = any(m.get('lock') for m in members)
            rots = [np.eye(3)] if locked else self.rots
            boxes = []
            for R in rots:
                q = (pts - c0) @ R.T
                boxes.append((q.min(0), q.max(0)))
            acc, serv = [], []
            for m in members:
                for d in m.get('access') or []:
                    acc.append(self.E @ _unit(d))
                for d, depth in m.get('service') or []:
                    serv.append((self.E @ _unit(d), float(depth)))
            self.units.append(dict(ids=[m['id'] for m in members], names=[m.get('name', m['id']) for m in members], c0=c0, rots=rots,
                                   boxes=boxes, locked=locked, floor=any(m.get('floor') for m in members), access=acc, service=serv))
        self.forbidden = []
        for lo, hi in self.p.get('forbidden') or []:                   # strefy zabronione (świat) jako AABB w układzie obudowy
            corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float) @ self.E.T
            self.forbidden.append((corners.min(0), corners.max(0)))
        self.cables = []                                               # (jednostka a, punkt a w ukł. obudowy, jednostka b, punkt b)
        unit_of = {i: n for n, u in enumerate(self.units) for i in u['ids']}
        for pa, ida, pb, idb in cables:
            self.cables.append((unit_of.get(ida), self.E @ np.asarray(pa, float), unit_of.get(idb), self.E @ np.asarray(pb, float)))
        self.base_state = [(0, u['c0'].copy()) for u in self.units]
        lo, hi = self.content(self.base_state)
        self.pins = {}
        for s in self.p.get('locked_walls') or []:                     # zablokowana ścianka: płaszczyzna zawartości w obecnym miejscu
            ax, sg = {'x': 0, 'y': 1, 'z': 2}[s[0]], (1 if s[1] == '+' else -1)
            self.pins[(ax, sg)] = float(hi[ax] if sg > 0 else lo[ax])
        self.base = self.measure(self.base_state)

    # stan: [(indeks orientacji, środek)] dla każdej jednostki
    def box(self, n, st):
        k, c = st[n]
        lo, hi = self.units[n]['boxes'][k]
        return c + lo, c + hi

    def service_boxes(self, n, st):
        lo, hi = self.box(n, st)
        R = self.units[n]['rots'][st[n][0]]
        out = []
        for d, depth in self.units[n]['service']:
            dd = R @ d
            ax = int(np.argmax(np.abs(dd)))
            a, b = lo.copy(), hi.copy()
            if dd[ax] > 0:
                a[ax], b[ax] = hi[ax], hi[ax] + depth
            else:
                a[ax], b[ax] = lo[ax] - depth, lo[ax]
            out.append((a, b))
        return out

    def content(self, st):
        los, his = [], []
        for n in range(len(self.units)):
            lo, hi = self.box(n, st)
            los.append(lo)
            his.append(hi)
            for a, b in self.service_boxes(n, st):
                los.append(a)
                his.append(b)
        lo, hi = np.min(los, 0), np.max(his, 0)
        for (ax, sg), v in getattr(self, 'pins', {}).items():
            if sg > 0:
                hi[ax] = max(hi[ax], v)
            else:
                lo[ax] = min(lo[ax], v)
        return lo, hi

    def cable_len(self, st):
        tot = 0.0
        for ua, pa, ub, pb in self.cables:
            qa = self._map(ua, st, pa)
            qb = self._map(ub, st, pb)
            tot += float(np.linalg.norm(qb - qa))
        return tot

    def _map(self, n, st, q):
        if n is None:
            return q
        k, c = st[n]
        R = self.units[n]['rots'][k]
        return R @ (q - self.units[n]['c0']) + c

    def measure(self, st):
        lo, hi = self.content(st)
        return metrics(lo, hi, self.clear, self.walls, self.p['density'], self.cable_len(st))

    def violation(self, st):
        """Suma naruszeń ograniczeń szybkiego etapu [mm / mm³] - 0 = dopuszczalny."""
        v = 0.0
        g = self.gap
        boxes = [self.box(n, st) for n in range(len(self.units))]
        lo_all, hi_all = self.content(st)
        for i in range(len(boxes)):
            a0, a1 = boxes[i]
            for j in range(i + 1, len(boxes)):
                b0, b1 = boxes[j]
                ov = np.minimum(a1 + g, b1) - np.maximum(a0 - g, b0)       # odstęp g między ramkami
                if np.all(ov > TOL):
                    v += float(np.min(ov))
            for z0, z1 in self.forbidden:
                ov = np.minimum(a1, z1) - np.maximum(a0, z0)
                if np.all(ov > TOL):
                    v += float(np.min(ov))
            for s0, s1 in self.service_boxes(i, st):                       # strefa serwisowa wolna od innych komponentów
                for j, (b0, b1) in enumerate(boxes):
                    if j != i:
                        ov = np.minimum(s1, b1) - np.maximum(s0, b0)
                        if np.all(ov > TOL):
                            v += float(np.min(ov))
            u = self.units[i]
            if u['floor']:
                v += abs(float(a0[2] - lo_all[2]))
            R = u['rots'][st[i][0]]
            for d in u['access']:                                          # dostęp do złącza: ściana komponentu przy ściance obudowy
                dd = R @ d
                ax = int(np.argmax(np.abs(dd)))
                v += abs(float(a1[ax] - hi_all[ax])) if dd[ax] > 0 else abs(float(a0[ax] - lo_all[ax]))
            if u['locked']:
                v += float(np.linalg.norm(st[i][1] - u['c0'])) + (0.0 if st[i][0] == 0 else 1.0)
        for (ax, sg), val in self.pins.items():                            # zablokowana ścianka: nic za nią
            hi = max(b[1][ax] for b in boxes)
            lo = min(b[0][ax] for b in boxes)
            v += max(0.0, hi - val) if sg > 0 else max(0.0, val - lo)
        md = self.p.get('max_dims') or [0, 0, 0]
        m = self.measure(st)
        for i in range(3):
            if float(md[i]) > 0:
                v += max(0.0, m['dims'][i] - float(md[i]))
        return v

    def energy(self, st):
        m = self.measure(st)
        return score(m, self.base, self.p['weights']) + PENALTY * self.violation(st) / max(1.0, max(self.base['dims'])), m

    # ------------------------------------------------------------------ dekoder punktów skrajnych (bin packing)
    def decode(self, order, rot):
        n = len(self.units)
        st = [None] * n
        placed = []
        for i in range(n):                                                 # zablokowane - na swoim miejscu
            if self.units[i]['locked']:
                st[i] = (0, self.units[i]['c0'].copy())
                placed.append(i)
        g = self.gap
        floor = min((self.box(i, st)[0][2] for i in placed), default=None)
        for i in order:
            if self.units[i]['locked']:
                continue
            k = rot[i]
            lo, hi = self.units[i]['boxes'][k]
            size = hi - lo
            if not placed:
                st[i] = (k, -lo)                                           # pierwszy: narożnik w (0, 0, 0)
                placed.append(i)
                floor = 0.0 if floor is None else floor
                continue
            cands = []
            for j in placed:
                b0, b1 = self.box(j, st)
                cands += [np.array([b1[0] + g, b0[1], b0[2]]), np.array([b0[0], b1[1] + g, b0[2]]), np.array([b0[0], b0[1], b1[2] + g]),
                          np.array([b0[0] - g - size[0], b0[1], b0[2]]), np.array([b0[0], b0[1] - g - size[1], b0[2]])]
            if self.units[i]['floor'] and floor is not None:
                cands = [np.array([c[0], c[1], floor]) for c in cands]
            best = None
            for corner in cands:
                cand = (k, corner - lo)
                trial = list(st)
                trial[i] = cand
                ok = True
                a0, a1 = corner, corner + size
                for j in placed:
                    b0, b1 = self.box(j, trial)
                    ov = np.minimum(a1 + g, b1) - np.maximum(a0 - g, b0)
                    if np.all(ov > TOL):
                        ok = False
                        break
                if ok:
                    for z0, z1 in self.forbidden:
                        ov = np.minimum(a1, z1) - np.maximum(a0, z0)
                        if np.all(ov > TOL):
                            ok = False
                            break
                if not ok:
                    continue
                part = [*placed, i]
                los = np.min([self.box(j, trial)[0] for j in part], 0)
                his = np.max([self.box(j, trial)[1] for j in part], 0)
                m = metrics(los, his, self.clear, self.walls, self.p['density'])
                m['cable'] = self.base['cable']
                val = score(m, self.base, self.p['weights']) + 1e-6 * float(np.sum(corner))
                if best is None or val < best[0]:
                    best = (val, cand)
            if best is None:                                               # brak miejsca przy innych - nad wszystkimi
                top = max(self.box(j, st)[1][2] for j in placed)
                b0 = min(self.box(j, st)[0][0] for j in placed), min(self.box(j, st)[0][1] for j in placed)
                best = (0, (k, np.array([b0[0], b0[1], top + g]) - lo))
            st[i] = best[1]
            placed.append(i)
            if floor is None:
                floor = float(self.box(i, st)[0][2])
        return self.push_access(st)

    def push_access(self, st):
        """Komponenty z wymaganym dostępem do złącza dosunięte do ścianki zawartości (gdy droga wolna)."""
        st = list(st)
        for i, u in enumerate(self.units):
            if u['locked'] or not u['access']:
                continue
            for d in u['access']:
                lo_all, hi_all = self.content(st)
                a0, a1 = self.box(i, st)
                dd = u['rots'][st[i][0]] @ d
                ax = int(np.argmax(np.abs(dd)))
                shift = np.zeros(3)
                shift[ax] = (hi_all[ax] - a1[ax]) if dd[ax] > 0 else (lo_all[ax] - a0[ax])
                trial = list(st)
                trial[i] = (st[i][0], st[i][1] + shift)
                if self.violation(trial) <= self.violation(st) + TOL:
                    st = trial
        return st


# ---------------------------------------------------------------------------------------------- przeszukiwanie
def optimize_placement(prob, cancel=None, progress=None):
    """Tryb B: wyżarzanie symulowane po (kolejność, orientacje) z dekoderem punktów skrajnych. Zwraca listę wariantów."""
    p = prob.p
    rng = np.random.default_rng(int(p.get('seed', 1)))
    n = len(prob.units)
    free = [i for i in range(n) if not prob.units[i]['locked']]
    iters = ACCURACY.get(p.get('accuracy'), 1500)
    t_end = time.time() + float(p.get('time_limit', 10.0))
    pool = {}

    def keep(st, e, m):
        key = tuple((k, *np.round(c, 1)) for k, c in st)
        if key not in pool or pool[key][0] > e:
            pool[key] = (e, st, m)

    e0, m0 = prob.energy(prob.base_state)
    keep(prob.base_state, e0, m0)
    if not free:
        return _variants(prob, pool)
    vol = sorted(free, key=lambda i: -float(np.prod(prob.units[i]['boxes'][0][1] - prob.units[i]['boxes'][0][0])))
    starts = [vol, list(reversed(vol)), [int(x) for x in rng.permutation(free)]]
    best_e = e0
    done = 0
    for s_i, order in enumerate(starts):
        rot = [0] * n
        cur = prob.decode(order, rot)
        ce, cm = prob.energy(cur)
        keep(cur, ce, cm)
        T = .05
        steps = max(1, iters // len(starts))
        for it in range(steps):
            if cancel is not None and cancel():
                raise kernel.CadError('Optymalizacja przerwana.')
            if time.time() > t_end:
                break
            o2, r2 = list(order), list(rot)
            mv = rng.random()
            if mv < .45 and len(free) > 1:
                a, b = rng.choice(len(o2), 2, replace=False)
                o2[a], o2[b] = o2[b], o2[a]
            elif mv < .9:
                i = int(rng.choice(free))
                r2[i] = int(rng.integers(len(prob.units[i]['rots'])))
            else:
                i = int(rng.integers(len(o2)))
                x = o2.pop(i)
                o2.insert(int(rng.integers(len(o2) + 1)), x)
            st = prob.decode(o2, r2)
            e, m = prob.energy(st)
            if e < ce or rng.random() < math.exp(-(e - ce) / max(T, 1e-9)):
                order, rot, cur, ce = o2, r2, st, e
                keep(st, e, m)
            T *= .995
            done += 1
            best_e = min(best_e, e)
            if progress is not None and done % 10 == 0:
                progress(min(.95, (s_i + it / steps) / len(starts)), best_e)
    return _variants(prob, pool)


def _variants(prob, pool):
    items = sorted(pool.values(), key=lambda x: x[0])
    out = []
    for e, st, m in items:
        moved = rotated = 0
        tr = {}
        for n, u in enumerate(prob.units):
            k, c = st[n]
            Rf = u['rots'][k]
            Rw = prob.E.T @ Rf @ prob.E
            tw = prob.E.T @ (c - Rf @ u['c0'])
            mv, rt = np.linalg.norm(c - u['c0']) > 1e-6, not np.allclose(Rf, np.eye(3))
            if not (mv or rt):
                continue                                                   # bez zmian - bez przekształcenia w przepisie
            moved += len(u['ids']) if mv else 0
            rotated += len(u['ids']) if rt else 0
            for i in u['ids']:
                tr[i] = dict(R=Rw.tolist(), t=tw.tolist())
        out.append(dict(kind='B', axes=prob.E.tolist(), transforms=tr, metrics=m, score=float(score(m, prob.base, prob.p['weights'])),
                        fast_valid=prob.violation(st) <= 1e-6, moved=moved, rotated=rotated, energy=float(e)))
    return out


def optimize_frame(points, base_axes, clear, walls, p, cable=0.0, cancel=None, progress=None):
    """Tryb A: orientacja układu obudowy (komponenty bez zmian). Przegląd kątów co 1° wokół osi „do góry”, potem
    zawężanie (złoty podział) wokół najlepszych; osie „do góry”: oś pionowa obudowy albo także osie globalne i OBB."""
    p = dict(DEFAULTS, **p)
    pts = np.asarray(points, float)
    E0 = np.asarray(base_axes, float)

    def meas(E):
        q = pts @ E.T
        return metrics(q.min(0), q.max(0), clear, walls, p['density'], cable)
    base = meas(E0)
    ups = [E0[2]]
    if p.get('enc_rotation') == 'all':
        c = pts - pts.mean(0)
        _w, V = np.linalg.eigh(c.T @ c)
        ups += [np.eye(3)[i] * s for i in range(3) for s in (1, -1)] + [V[:, i] * s for i in range(3) for s in (1, -1)]
    uniq = []
    for u in ups:
        u = _unit(u)
        if not any(float(u @ w) > .9999 for w in uniq):
            uniq.append(u)

    def frame(up, deg):
        ref = E0[0] - up * float(E0[0] @ up)
        if np.linalg.norm(ref) < 1e-6:
            ref = E0[1] - up * float(E0[1] @ up)
        x = _rot(up, deg) @ _unit(ref)
        return np.vstack([x, np.cross(up, x), up])
    found = []
    t_end = time.time() + float(p.get('time_limit', 10.0))
    md = p.get('max_dims') or [0, 0, 0]

    def val(E):
        m = meas(E)
        pen = sum(max(0.0, m['dims'][i] - float(md[i])) for i in range(3) if float(md[i]) > 0)
        return score(m, base, p['weights']) + PENALTY * pen / max(1.0, max(base['dims'])), m
    total = len(uniq) * 180
    count = 0
    for up in uniq:
        for deg in range(0, 180):
            if cancel is not None and count % 20 == 0 and cancel():
                raise kernel.CadError('Optymalizacja przerwana.')
            E = frame(up, float(deg))
            e, m = val(E)
            found.append((e, up, float(deg)))
            count += 1
            if progress is not None and count % 30 == 0:
                progress(.8 * count / total, min(f[0] for f in found))
        if time.time() > t_end:
            break
    found.sort(key=lambda x: x[0])
    refined = []
    for e, up, deg in found[:3 * int(p.get('top', 5))]:
        a, b = deg - 1.0, deg + 1.0                                       # złoty podział w przedziale ±1°
        gr = (math.sqrt(5) - 1) / 2
        c_, d_ = b - gr * (b - a), a + gr * (b - a)
        for _ in range(20):
            if val(frame(up, c_))[0] < val(frame(up, d_))[0]:
                b = d_
            else:
                a = c_
            c_, d_ = b - gr * (b - a), a + gr * (b - a)
        dbest = (a + b) / 2
        e2, m2 = val(frame(up, dbest))
        if e2 > e:
            dbest, e2, m2 = deg, *val(frame(up, deg))
        refined.append((e2, up, dbest % 360, m2))
    refined.append((val(E0)[0], E0[2], None, base))
    out, seen = [], []
    for e, up, deg, m in sorted(refined, key=lambda x: x[0]):
        E = E0 if deg is None else frame(up, deg)
        if any(np.all(np.abs(np.diag(E @ F.T)) > math.cos(math.radians(3))) for F, m2_ in seen):
            continue                                                       # ten sam wariant (kąt w granicach 3°, te same wymiary)
        seen.append((E, m))
        pen = sum(max(0.0, m['dims'][i] - float(md[i])) for i in range(3) if float(md[i]) > 0)
        out.append(dict(kind='A', axes=E.tolist(), transforms={}, metrics=m, score=float(score(m, base, p['weights'])), fast_valid=pen <= 1e-6,
                        moved=0, rotated=0, energy=float(e), angle=None if deg is None else float(deg), up=[float(x) for x in up]))
    if progress is not None:
        progress(.9, out[0]['energy'] if out else 0.0)
    return out, base


# ---------------------------------------------------------------------------------------------- dokładna kontrola
def exact_check(variant, shapes, p, clear, walls, cable_fn=None):
    """Dokładna kontrola wariantu na bryłach B-Rep: kolizje (wspólna objętość), odstępy (DistShapeShape), strefy zabronione
    i serwisowe, maks. wymiary; dokładna ramka w układzie obudowy (framed_box) i miary. shapes: {id: cq.Shape}."""
    import cadquery as cq
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from .enclosure import _boolean, _volume, framed_box
    p = dict(DEFAULTS, **p)
    E = np.asarray(variant['axes'], float)
    moved = {}
    for i, sh in shapes.items():
        tr = variant['transforms'].get(i)
        moved[i] = kernel.transformed(sh, np.asarray(tr['R']), np.asarray(tr['t'])) if tr else sh
    issues = []
    ids = list(moved)
    gap = float(p['gap'])
    if variant['kind'] == 'B':
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                A, B = moved[ids[a]], moved[ids[b]]
                ba, bb = A.BoundingBox(), B.BoundingBox()
                if (ba.xmin > bb.xmax + gap + 1e-3 or bb.xmin > ba.xmax + gap + 1e-3 or ba.ymin > bb.ymax + gap + 1e-3 or bb.ymin > ba.ymax + gap + 1e-3
                        or ba.zmin > bb.zmax + gap + 1e-3 or bb.zmin > ba.zmax + gap + 1e-3):
                    continue
                if _volume(_boolean('common', A.wrapped, B.wrapped, 'kolizja komponentów'))[0] > 1e-3:
                    issues.append(('error', f'Kolizja: {p.get("names", {}).get(ids[a], ids[a])} / {p.get("names", {}).get(ids[b], ids[b])}'))
                    continue
                d = BRepExtrema_DistShapeShape(A.wrapped, B.wrapped)
                d.Perform()
                if d.IsDone() and d.Value() < gap - 1e-2:
                    issues.append(('error', f'Odstęp {d.Value():.2f} mm < {gap:g} mm: {p.get("names", {}).get(ids[a], ids[a])} / {p.get("names", {}).get(ids[b], ids[b])}'))
        for lo, hi in p.get('forbidden') or []:
            zone = cq.Solid.makeBox(*(np.asarray(hi, float) - np.asarray(lo, float)), pnt=cq.Vector(*map(float, lo)))
            for i in ids:
                if _volume(_boolean('common', moved[i].wrapped, zone.wrapped, 'strefa zabroniona'))[0] > 1e-3:
                    issues.append(('error', f'{p.get("names", {}).get(i, i)} wchodzi w strefę zabronioną'))
        for i, zones in (p.get('service_world') or {}).items():
            tr = variant['transforms'].get(i)
            for z in zones:
                corners = np.asarray(z, float)
                if tr:
                    corners = corners @ np.asarray(tr['R']).T + np.asarray(tr['t'])
                lo, hi = corners.min(0), corners.max(0)
                zone = cq.Solid.makeBox(*map(float, np.maximum(hi - lo, 1e-3)), pnt=cq.Vector(*map(float, lo)))
                for j in ids:
                    if j != i and _volume(_boolean('common', moved[j].wrapped, zone.wrapped, 'strefa serwisowa'))[0] > 1e-3:
                        issues.append(('error', f'{p.get("names", {}).get(j, j)} zajmuje strefę serwisową {p.get("names", {}).get(i, i)}'))
    env = framed_box(list(moved.values()), np.zeros(3), E[0], E[1], E[2])
    c = np.asarray(env.center, float) @ E.T
    h = np.asarray(env.size, float) / 2
    lo, hi = c - h, c + h
    own = {}
    for i in ids:                                                      # dokładne ramki komponentów w układzie obudowy
        e_ = framed_box([moved[i]], np.zeros(3), E[0], E[1], E[2])
        cc = np.asarray(e_.center, float) @ E.T
        own[i] = (cc - np.asarray(e_.size) / 2, cc + np.asarray(e_.size) / 2)
    for i, zones in (p.get('service_world') or {}).items():           # strefy serwisowe są częścią wnętrza
        tr = variant['transforms'].get(i)
        for z in zones:
            q = np.asarray(z, float)
            if tr:
                q = q @ np.asarray(tr['R']).T + np.asarray(tr['t'])
            q = q @ E.T
            lo, hi = np.minimum(lo, q.min(0)), np.maximum(hi, q.max(0))
    for ax, sg, val in p.get('pins') or []:                            # zablokowane ścianki
        if (sg > 0 and hi[ax] > val + 1e-3) or (sg < 0 and lo[ax] < val - 1e-3):
            issues.append(('error', f'Komponent wychodzi za zablokowaną ściankę {"xyz"[ax]}{"+" if sg > 0 else "-"}'))
        if sg > 0:
            hi[ax] = max(hi[ax], val)
        else:
            lo[ax] = min(lo[ax], val)
    if variant['kind'] == 'B':
        for i in p.get('floor_ids') or []:
            if i in own and abs(own[i][0][2] - lo[2]) > .05:
                issues.append(('error', f'{p.get("names", {}).get(i, i)} nie stoi na dnie ({own[i][0][2] - lo[2]:.2f} mm nad nim)'))
        for i, dirs in (p.get('access_world') or {}).items():
            tr = variant['transforms'].get(i)
            for d in dirs:
                dd = E @ ((np.asarray(tr['R']) @ _unit(d)) if tr else _unit(d))
                ax = int(np.argmax(np.abs(dd)))
                gapw = (hi[ax] - own[i][1][ax]) if dd[ax] > 0 else (own[i][0][ax] - lo[ax])
                if gapw > .05:
                    issues.append(('error', f'Złącze {p.get("names", {}).get(i, i)} nie jest przy ściance ({gapw:.2f} mm)'))
    cable = cable_fn(variant) if cable_fn else 0.0
    m = metrics(lo, hi, clear, walls, p['density'], cable)
    md = p.get('max_dims') or [0, 0, 0]
    for i, nm in enumerate('XYZ'):
        if float(md[i]) > 0 and m['dims'][i] > float(md[i]) + 1e-6:
            issues.append(('error', f'Wymiar {nm} {m["dims"][i]:.1f} mm > dopuszczalne {float(md[i]):g} mm'))
    return dict(valid=not any(l == 'error' for l, _t in issues), issues=issues, metrics=m, env=env)


# ---------------------------------------------------------------------------------------------- całość
def run_search(items, shapes, axes, clear, walls, p, cables=(), cancel=None, progress=None):
    """Pełne przeszukiwanie z dokładną kontrolą najlepszych: dict(base, variants) - warianty posortowane: poprawne,
    potem ocena; każdy z exact (valid, issues) i zmianą procentową miar względem stanu obecnego."""
    p = dict(DEFAULTS, **p)
    t0 = time.time()
    names = {it['id']: it.get('name', it['id']) for it in items}
    p['names'] = names
    if p['mode'] == 'A':
        pts = np.vstack([np.asarray(it['points'], float) for it in items]
                        + [np.asarray(_service_world(it['points'], d, depth), float) for it in items for d, depth in it.get('service') or []])
        p['service_world'] = {it['id']: [_service_world(it['points'], d, depth) for d, depth in it['service']] for it in items if it.get('service')}
        cab = sum(float(np.linalg.norm(np.asarray(b) - np.asarray(a))) for a, _ia, b, _ib in cables)
        variants, base = optimize_frame(pts, axes, clear, walls, p, cab, cancel, progress)
        cable_fn = lambda v: cab
    else:
        prob = Problem(items, axes, clear, walls, p, cables, cancel, progress)
        variants = optimize_placement(prob, cancel, progress)
        base = prob.base

        def cable_fn(v):
            tot = 0.0
            for a, ia, b, ib in cables:
                qa, qb = np.asarray(a, float), np.asarray(b, float)
                ta, tb = v['transforms'].get(ia), v['transforms'].get(ib)
                if ta:
                    qa = np.asarray(ta['R']) @ qa + np.asarray(ta['t'])
                if tb:
                    qb = np.asarray(tb['R']) @ qb + np.asarray(tb['t'])
                tot += float(np.linalg.norm(qb - qa))
            return tot
        from .enclosure import framed_box
        E_ = np.asarray(axes, float)
        e_ = framed_box(list(shapes.values()), np.zeros(3), E_[0], E_[1], E_[2])
        cc = np.asarray(e_.center, float) @ E_.T
        blo, bhi = cc - np.asarray(e_.size) / 2, cc + np.asarray(e_.size) / 2
        p['pins'] = [[ax, sg, float(bhi[ax] if sg > 0 else blo[ax])] for (ax, sg) in prob.pins]
        p['floor_ids'] = [it['id'] for it in items if it.get('floor')]
        p['access_world'] = {it['id']: it['access'] for it in items if it.get('access')}
        sw = {}
        for it in items:                                                # strefy serwisowe w świecie (narożniki pudełek)
            for d, depth in it.get('service') or []:
                sw.setdefault(it['id'], []).append(_service_world(it['points'], d, depth))
        p['service_world'] = sw
    ident = dict(kind=p['mode'], axes=np.asarray(axes, float).tolist(), transforms={})
    base = exact_check(ident, shapes, p, clear, walls, cable_fn)['metrics']          # stan obecny - dokładnie, jak warianty
    top = int(p.get('top', 5))
    fast_ok = [v for v in variants if v['fast_valid']]
    cand = (fast_ok + [v for v in variants if not v['fast_valid']])[:max(top * 2, top + 2)]
    checked = []
    for n, v in enumerate(cand):
        if cancel is not None and cancel():
            raise kernel.CadError('Optymalizacja przerwana.')
        ex = exact_check(v, shapes, p, clear, walls, cable_fn)
        v = dict(v, exact=dict(valid=bool(ex['valid'] and v['fast_valid']), issues=ex['issues'] + ([] if v['fast_valid'] else [('error', 'Naruszone ograniczenia (gniazda, ścianki, dostęp, strefy) w szybkim etapie.')])),
                 metrics=ex['metrics'], env=ex['env'])
        v['score'] = float(score(v['metrics'], base, p['weights']))
        v['change'] = {g: (100.0 * (v['metrics'][g] / base[g] - 1.0) if base.get(g) else 0.0) for g in ('volume', 'area', 'material', 'mass', 'height', 'width', 'depth', 'cable')}
        checked.append(v)
        if progress is not None:
            progress(.9 + .1 * (n + 1) / len(cand), checked[0]['score'])
    checked.sort(key=lambda v: (not v['exact']['valid'], v['score']))
    out, seen = [], set()
    for v in checked:                                                  # różne warianty: wymiary / liczba zmian
        key = (tuple(np.round(v['metrics']['dims'], 1)), v['moved'], v['rotated'], v['exact']['valid'], v.get('angle') is None)
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return dict(base=base, variants=out[:top], seconds=time.time() - t0)


def _service_world(points, d, depth):
    pts = np.asarray(points, float)
    lo, hi = pts.min(0), pts.max(0)
    d = _unit(d)
    ax = int(np.argmax(np.abs(d)))
    a, b = lo.copy(), hi.copy()
    if d[ax] > 0:
        a[ax], b[ax] = hi[ax] + 1e-3, hi[ax] + depth
    else:
        a[ax], b[ax] = lo[ax] - depth, lo[ax] - 1e-3
    return [[x, y, z] for x in (a[0], b[0]) for y in (a[1], b[1]) for z in (a[2], b[2])]
