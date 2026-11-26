"""Wentylacja - rozmieszczenie otworów (PatternLayout), gradienty (PatternGradient), tryby wypełniania, obsługa brzegów
i stref zabronionych, kontrola 2D (HoleValidator), ręczne zmiany pojedynczych otworów oraz generatory wzorów specjalnych
(Voronoi, Gyroid 2D, spirale, turbiny, fale, labirynty, plecionki, jodełka, zygzaki, łuki, rozgałęzienia, pęcherzyki,
łuski, fraktale, liście, kratki wentylatorów).

Wszystko w dziedzinie 2D obszaru (mm); odwzorowanie na powierzchnię - vent_surface. Otwór to dict:
  key    - stały identyfikator (np. ('g', i, j) w siatce) - zachowuje ręczne zmiany przy regeneracji
  kind, w, h, params - kształt (vent_shapes), c - środek, angle - obrót [rad]
  loops  - profil w dziedzinie (segmenty), poly - obrys zewnętrzny (wielokąt), depth_k, tilt - mnożnik głębokości, nachylenie [°]
  status - 'ok' (zielony), 'adjust' (żółty: zmniejszony / przesunięty / przycięty), 'bad' (czerwony), 'skip' (szary)"""
from __future__ import annotations

import math

import numpy as np

from . import kernel
from . import vent_geom2d as g2
from . import vent_shapes as vs

LAYOUTS = ('rect', 'square', 'offset_h', 'offset_v', 'triangular', 'hexagonal', 'diagonal', 'radial', 'concentric', 'spiral',
           'random', 'gradient', 'alternating', 'mirror', 'curve', 'sketch', 'adaptive')
LAYOUT_LABELS = {'rect': 'Prostokątny', 'square': 'Kwadratowy', 'offset_h': 'Przesunięty poziomo', 'offset_v': 'Przesunięty pionowo',
                 'triangular': 'Trójkątny', 'hexagonal': 'Sześciokątny', 'diagonal': 'Ukośny', 'radial': 'Promieniowy', 'concentric': 'Koncentryczny',
                 'spiral': 'Spiralny', 'random': 'Losowy', 'gradient': 'Gradientowy (zagęszczenie)', 'alternating': 'Naprzemienny',
                 'mirror': 'Lustrzany', 'curve': 'Według krzywej', 'sketch': 'Według szkicu (punkty)', 'adaptive': 'Adaptacyjny (wzdłuż granic)'}
FILLS = ('A', 'B', 'C', 'D', 'E', 'F')
FILL_LABELS = {'A': 'A - stały rozstaw', 'B': 'B - stała liczba otworów', 'C': 'C - maksymalne wypełnienie (heurystyka)',
               'D': 'D - docelowa powierzchnia otwarta', 'E': 'E - automatyczne centrowanie', 'F': 'F - adaptacyjne wypełnienie'}
EDGES = ('full', 'trim', 'shrink', 'push', 'skip', 'adaptive')
EDGE_LABELS = {'full': 'Tylko pełne otwory', 'trim': 'Przycinanie do granicy', 'shrink': 'Zmniejszanie przy krawędziach',
               'push': 'Odsuwanie od krawędzi', 'skip': 'Pomijanie (pokazane na szaro)', 'adaptive': 'Adaptacyjne (zmniejsz, potem odsuń)'}
GRAD_PARAMS = ('size', 'width', 'height', 'length', 'spacing', 'density', 'rotation', 'depth', 'tilt', 'aspect')
GRAD_PARAM_LABELS = {'size': 'średnica / wielkość', 'width': 'szerokość', 'height': 'wysokość', 'length': 'długość', 'spacing': 'rozstaw',
                     'density': 'zagęszczenie', 'rotation': 'obrót', 'depth': 'głębokość', 'tilt': 'nachylenie', 'aspect': 'proporcje'}
GRAD_DIRS = ('h', 'v', 'diag', 'radial', 'center_out', 'edge_in', 'curve', 'point')
GRAD_DIR_LABELS = {'h': 'poziomo', 'v': 'pionowo', 'diag': 'ukośnie (kąt)', 'radial': 'promieniowo', 'center_out': 'od środka na zewnątrz',
                   'edge_in': 'od krawędzi do środka', 'curve': 'wzdłuż krzywej', 'point': 'od wskazanego punktu'}
GRAD_FUNCS = ('linear', 'log', 'exp', 'sin', 'step', 'random', 'custom')
GRAD_FUNC_LABELS = {'linear': 'liniowa', 'log': 'logarytmiczna', 'exp': 'wykładnicza', 'sin': 'sinusoidalna', 'step': 'skokowa',
                    'random': 'losowa', 'custom': 'krzywa sterująca'}
MAX_HOLES = 20000
DEFAULTS = dict(kind='circle', w=4.0, h=4.0, corner=0.0, sides=6, arms=5, ratio=.45, arm=.3, bend=60.0, irregularity=.4,
                generator='', layout='hexagonal', px=0.0, py=0.0, link=True, rows=0, cols=0, count=0, angle=0.0, hole_angle=0.0,
                ox=0.0, oy=0.0, scale=1.0, shift_row=50.0, shift_col=0.0, seed=1, mirror_axis='x', alt_angle=90.0, curve=None, points=None,
                fill='A', target_open=30.0, adjust='size', size_min=1.0, size_max=20.0, margin=2.0, margin_holes=2.0, bridge=1.2,
                min_area=1.0, min_width=.8, min_scale=.4, edge_mode='full', obstacle_mode='skip', obstacle_gap=2.0, gradients=[], mixed=[],
                mix_mode='sequence', overrides={}, added=[], allow_islands=False,
                # wzory specjalne
                arms_n=6, turns=3.0, twist='ccw', pitch=0.0, amplitude=3.0, frequency=.1, phase=0.0, channel=2.0, branch_density=.5,
                branch_angle=30.0, level=3, cell=8.0, opening=.0, gyro_phase=0.0, relax=2, cell_min=0.0, cell_max=0.0, round_r=.5,
                smoothing=0, vmode='organic', fan=40, fan_style='concentric', fan_hub=0.0, fan_mount=True, fan_spacing=0.0, fan_hole=0.0,
                fan_d=0.0, irregular=.5)


def _key(*parts):
    return '/'.join(str(p) for p in parts)


# ---------------------------------------------------------------------------------------------- gradienty
def grad_t(gr, P, region, centre):
    """Parametr t ∈ [0, 1] gradientu w punktach P."""
    P = np.asarray(P, float).reshape(-1, 2)
    d = gr.get('dir', 'h')
    lo, hi = region.lo, region.hi
    if d in ('h', 'v', 'diag'):
        a = {'h': 0.0, 'v': 90.0}.get(d, float(gr.get('angle', 45.0)))
        u = np.array([math.cos(math.radians(a)), math.sin(math.radians(a))])
        corners = np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]]) @ u
        s = P @ u
        return np.clip((s - corners.min()) / max(np.ptp(corners), 1e-9), 0, 1)
    if d in ('radial', 'center_out', 'point'):
        c = np.asarray(gr.get('point') or centre, float) if d == 'point' else centre
        r = np.linalg.norm(P - c, axis=1)
        rmax = max(np.linalg.norm(np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]]) - c, axis=1).max(), 1e-9)
        return np.clip(r / rmax, 0, 1)
    if d == 'edge_in':
        e = region.edge_dist(P)
        return np.clip(e / max(float(region.edge_dist(np.array([centre]))[0]), 1e-9), 0, 1)
    if d == 'curve':
        cv = np.asarray(gr.get('curve') or [], float)
        if len(cv) < 2:
            raise kernel.CadError('Gradient wzdłuż krzywej: wskaż krzywą.')
        seg = np.linalg.norm(np.diff(cv, axis=0), axis=1)
        cum = np.r_[0, np.cumsum(seg)]
        D = g2.seg_dist(P, cv[:-1], cv[1:])
        k = D.argmin(1)
        a, b = cv[k], cv[k + 1]
        dd = b - a
        t = np.clip(((P - a) * dd).sum(1) / np.maximum((dd ** 2).sum(1), 1e-18), 0, 1)
        return (cum[k] + t * seg[k]) / max(cum[-1], 1e-9)
    raise kernel.CadError('Nieznany kierunek gradientu.')


def grad_f(gr, t, keys=None):
    f = gr.get('func', 'linear')
    t = np.asarray(t, float)
    if f == 'linear':
        return t
    if f == 'log':
        return np.log1p(9 * t) / math.log(10)
    if f == 'exp':
        return (np.exp(3 * t) - 1) / (math.e ** 3 - 1)
    if f == 'sin':
        n = float(gr.get('periods', 1.0))
        return .5 - .5 * np.cos(2 * math.pi * n * t)
    if f == 'step':
        n = max(2, int(gr.get('steps', 4)))
        return np.floor(t * n).clip(0, n - 1) / (n - 1)
    if f == 'random':
        rng = np.random.default_rng(int(gr.get('seed', 1)))
        return rng.random(len(t))
    if f == 'custom':
        pts = sorted((float(a), float(b)) for a, b in (gr.get('control') or [(0, 0), (1, 1)]))
        return np.interp(t, [a for a, _b in pts], [b for _a, b in pts])
    raise kernel.CadError('Nieznana funkcja gradientu.')


def factors(gradients, P, region, centre):
    """Mnożniki parametrów w punktach P ze wszystkich gradientów (kilka gradientów tego samego parametru mnoży się;
    obrót i nachylenie - dodają się w stopniach)."""
    n = len(P)
    out = {k: np.ones(n) for k in GRAD_PARAMS}
    out['rotation'] = np.zeros(n)
    out['tilt'] = np.zeros(n)
    for gr in gradients or []:
        prm = gr.get('param', 'size')
        if prm not in GRAD_PARAMS:
            continue
        f = grad_f(gr, grad_t(gr, P, region, centre))
        k0, k1 = float(gr.get('k0', 1.0)), float(gr.get('k1', .5))
        val = k0 + (k1 - k0) * f
        if prm in ('rotation', 'tilt'):
            out[prm] = out[prm] + val
        else:
            out[prm] = out[prm] * val
    return out


# ---------------------------------------------------------------------------------------------- układy
def _frame(p, region):
    c = region.centroid() + np.array([float(p['ox']), float(p['oy'])])
    return c, math.radians(float(p['angle'])), max(float(p['scale']), 1e-3)


def spacing(p, kind_size):
    w, h = kind_size
    br = float(p['bridge'])
    px = float(p['px']) or (w + br)
    py = float(p['py']) or ((px if p['link'] else h + br) if float(p['px']) else h + br)
    if p['link'] and float(p['px']):
        py = float(p['py']) or px
    return px, py


def lattice(p, region, size, sp):
    """Środki otworów układu (współrzędne dziedziny) z kluczami i kątem własnym otworu."""
    lay = p['layout']
    c, ang, sc = _frame(p, region)
    px, py = sp[0] * sc, sp[1] * sc
    R = float(np.linalg.norm(region.hi - region.lo)) / 2 + max(px, py) * 2
    pts, keys, rot = [], [], []
    rows = int(p['rows'])
    cols = int(p['cols'])

    def grid(dx_row=0.0, dy_col=0.0, sx=px, sy=py, extra=0.0):
        nx = cols if cols > 0 else int(2 * R / sx) + 3
        ny = rows if rows > 0 else int(2 * R / sy) + 3
        if nx * ny > MAX_HOLES * 8:
            raise kernel.CadError('Za dużo otworów w układzie - zwiększ otwory albo rozstaw.')
        for j in range(ny):
            for i in range(nx):
                x = (i - (nx - 1) / 2) * sx + ((j * dx_row) % 1.0 if dx_row else 0.0) * sx
                y = (j - (ny - 1) / 2) * sy + ((i * dy_col) % 1.0 if dy_col else 0.0) * sy
                pts.append((x, y))
                keys.append(_key('g', i, j))
                rot.append(extra if (i + j) % 2 else 0.0)
    if lay in ('rect', 'mirror', 'alternating'):
        grid(extra=math.radians(float(p['alt_angle'])) if lay == 'alternating' else 0.0)
    elif lay == 'square':
        grid(sx=px, sy=px)
    elif lay == 'offset_h':
        grid(dx_row=float(p['shift_row']) / 100.0)
    elif lay == 'offset_v':
        grid(dy_col=float(p['shift_col'] or p['shift_row']) / 100.0)
    elif lay == 'triangular':
        grid(dx_row=.5, sx=px, sy=px * math.sqrt(3) / 2)
    elif lay == 'hexagonal':
        grid(dx_row=.5, sx=px, sy=px * math.sqrt(3) / 2)
    elif lay == 'diagonal':
        ang += math.pi / 4
        grid()
    elif lay == 'radial':
        n = max(3, int(p['arms_n']) if int(p['arms_n']) else int(2 * math.pi * R / px / 4))
        pts.append((0.0, 0.0)), keys.append('c'), rot.append(0.0)
        k = 1
        while k * py <= R:
            for j in range(n):
                a = 2 * math.pi * j / n
                pts.append((k * py * math.cos(a), k * py * math.sin(a)))
                keys.append(_key('r', j, k))
                rot.append(a)
            k += 1
    elif lay == 'concentric':
        pts.append((0.0, 0.0)), keys.append('c'), rot.append(0.0)
        k = 1
        while k * py <= R:
            r = k * py
            n = max(3, int(2 * math.pi * r / px))
            for j in range(n):
                a = 2 * math.pi * j / n
                pts.append((r * math.cos(a), r * math.sin(a)))
                keys.append(_key('o', k, j))
                rot.append(a + math.pi / 2)
            k += 1
    elif lay == 'spiral':
        arms = max(1, int(p.get('spiral_arms') or 1))
        sgn = -1 if p.get('twist') == 'cw' else 1
        k = 0
        golden = math.radians(137.50776)
        while True:                                                     # spirala Fermata (filotaksja): równa gęstość
            r = px * .62 * math.sqrt(k)
            if r > R:
                break
            for m in range(arms):
                a = sgn * (k * golden) + 2 * math.pi * m / arms
                pts.append((r * math.cos(a), r * math.sin(a)))
                keys.append(_key('s', k, m))
                rot.append(a)
            k += 1
            if k > MAX_HOLES * 4:
                break
    elif lay in ('random', 'gradient'):
        lo, hi = region.lo, region.hi
        base = max(px, py)
        if lay == 'gradient' and p['gradients']:
            def rf(P):
                f = factors([dict(gr, param='spacing') for gr in p['gradients'] if gr.get('param') in ('spacing', 'density', 'size')][:1], P, region, region.centroid())
                return base * f['spacing']
        else:
            def rf(P):
                return np.full(len(P), base)
        P = g2.poisson(lo, hi, rf, seed=int(p['seed']), limit=MAX_HOLES)
        c = np.zeros(2)
        ang = 0.0
        sc = 1.0
        for n, q in enumerate(P):
            pts.append(tuple(q))
            keys.append(_key('p', n))
            rot.append(0.0)
    elif lay == 'curve':
        cv = np.asarray(p.get('curve') or [], float)
        if len(cv) < 2:
            raise kernel.CadError('Układ według krzywej: wskaż krzywą (szkic albo krawędź).')
        seg = np.linalg.norm(np.diff(cv, axis=0), axis=1)
        cum = np.r_[0, np.cumsum(seg)]
        nrow = max(1, rows or 1)
        for rr in range(nrow):
            off = (rr - (nrow - 1) / 2) * py
            s, n = 0.0, 0
            while s <= cum[-1] + 1e-9:
                k = min(int(np.searchsorted(cum, s, 'right') - 1), len(seg) - 1)
                t = (s - cum[k]) / max(seg[k], 1e-12)
                q = cv[k] + (cv[k + 1] - cv[k]) * t
                tg = (cv[k + 1] - cv[k]) / max(seg[k], 1e-12)
                nrm = np.array([-tg[1], tg[0]])
                pts.append(tuple(q + nrm * off))
                keys.append(_key('k', rr, n))
                rot.append(math.atan2(tg[1], tg[0]))
                s += px
                n += 1
        c, ang, sc = np.zeros(2), 0.0, 1.0
    elif lay == 'sketch':
        P = np.asarray(p.get('points') or [], float)
        if not len(P):
            raise kernel.CadError('Układ według szkicu: szkic nie ma punktów (środków okręgów / punktów).')
        for n, q in enumerate(P):
            pts.append(tuple(q))
            keys.append(_key('k', n))
            rot.append(0.0)
        c, ang, sc = np.zeros(2), 0.0, 1.0
    elif lay == 'adaptive':                                             # pierścienie równoległe do granic obszaru
        lo, hi = region.lo, region.hi
        step = max(min(px, py) / 4, .2)
        xs = np.arange(lo[0] - step, hi[0] + step * 2, step)
        ys = np.arange(lo[1] - step, hi[1] + step * 2, step)
        X, Y = np.meshgrid(xs, ys, indexing='ij')
        Q = np.c_[X.ravel(), Y.ravel()]
        D = region.edge_dist(Q)
        inside = region.contains(Q)
        F = np.where(inside, D, -D).reshape(X.shape)
        k = 0
        first = float(p['margin']) + size[0] / 2
        while True:
            lev = first + k * py
            lines = g2.contours(F, xs, ys, lev)
            if not lines:
                break
            for m, L in enumerate(lines):
                segl = np.linalg.norm(np.diff(L, axis=0), axis=1)
                cum = np.r_[0, np.cumsum(segl)]
                if cum[-1] < px * .5:
                    continue
                cnt = max(1, int(cum[-1] / px))
                for j in range(cnt):
                    s = (j + .5) * cum[-1] / cnt
                    kk = min(int(np.searchsorted(cum, s, 'right') - 1), len(segl) - 1)
                    t = (s - cum[kk]) / max(segl[kk], 1e-12)
                    q = L[kk] + (L[kk + 1] - L[kk]) * t
                    tg = L[kk + 1] - L[kk]
                    pts.append(tuple(q))
                    keys.append(_key('a', k, m, j))
                    rot.append(math.atan2(tg[1], tg[0]))
            k += 1
            if k > 400:
                break
        c, ang, sc = np.zeros(2), 0.0, 1.0
    else:
        raise kernel.CadError(f'Nieznany układ: {lay}.')
    P = np.array(pts, float).reshape(-1, 2)
    if len(P):
        cs, sn = math.cos(ang), math.sin(ang)
        P = c + np.c_[cs * P[:, 0] - sn * P[:, 1], sn * P[:, 0] + cs * P[:, 1]] * (sc if lay not in ('curve', 'sketch', 'adaptive', 'random', 'gradient') else 1.0)
    rot = np.array(rot, float) + (ang if lay in ('radial', 'concentric', 'spiral', 'alternating', 'rect', 'square', 'offset_h', 'offset_v',
                                               'triangular', 'hexagonal', 'diagonal', 'mirror') else 0.0)
    if lay == 'mirror':                                                # połowa obszaru + odbicie względem osi przez środek
        ctr = region.centroid()
        axis = p.get('mirror_axis', 'x')
        keep = P[:, 1] >= ctr[1] - 1e-9 if axis == 'x' else P[:, 0] >= ctr[0] - 1e-9
        P, rot, keys = P[keep], rot[keep], [k_ for k_, m in zip(keys, keep) if m]
        M = P.copy()
        if axis == 'x':
            M[:, 1] = 2 * ctr[1] - M[:, 1]
            mrot = -rot
        else:
            M[:, 0] = 2 * ctr[0] - M[:, 0]
            mrot = math.pi - rot
        far = np.linalg.norm(M - P, axis=1) > 1e-6
        P = np.vstack([P, M[far]])
        rot = np.r_[rot, mrot[far]]
        keys = keys + ['m' + k_ for k_, f in zip(keys, far) if f]
    # gradient rozstawu w układach siatkowych: odkształcenie współrzędnych wzdłuż kierunku gradientu
    sp_gr = [gr for gr in p['gradients'] or [] if gr.get('param') in ('spacing', 'density') and lay not in ('random', 'gradient')]
    if sp_gr and len(P):
        P = _warp(P, sp_gr, region)
    return P, keys, rot


def _warp(P, grads, region):
    """Zmienny rozstaw: współrzędna wzdłuż kierunku gradientu zastąpiona całką mnożnika (rozstaw lokalnie × k)."""
    c = region.centroid()
    for gr in grads:
        d = gr.get('dir', 'h')
        k0, k1 = float(gr.get('k0', 1.0)), float(gr.get('k1', .5))
        if gr.get('param') == 'density':                                # zagęszczenie odwrotne do rozstawu
            k0, k1 = 1 / max(k0, 1e-3), 1 / max(k1, 1e-3)
        if d in ('h', 'v', 'diag'):
            a = {'h': 0.0, 'v': 90.0}.get(d, float(gr.get('angle', 45.0)))
            u = np.array([math.cos(math.radians(a)), math.sin(math.radians(a))])
            s = (P - c) @ u
            lo, hi = float(s.min()), float(s.max())
            grid = np.linspace(lo, hi, 400)
            t = (grid - lo) / max(hi - lo, 1e-9)
            f = k0 + (k1 - k0) * grad_f(gr, t)
            integ = np.r_[0, np.cumsum((f[1:] + f[:-1]) / 2 * np.diff(grid))]
            integ = integ - np.interp(0.0, grid, integ)
            s2 = np.interp(s, grid, integ)
            P = P + np.outer(s2 - s, u)
        elif d in ('radial', 'center_out', 'point'):
            cc = np.asarray(gr.get('point') or c, float) if d == 'point' else c
            r = np.linalg.norm(P - cc, axis=1)
            rmax = max(float(r.max()), 1e-9)
            grid = np.linspace(0, rmax, 400)
            f = k0 + (k1 - k0) * grad_f(gr, grid / rmax)
            integ = np.r_[0, np.cumsum((f[1:] + f[:-1]) / 2 * np.diff(grid))]
            r2 = np.interp(r, grid, integ)
            P = cc + (P - cc) * (r2 / np.maximum(r, 1e-9))[:, None]
    return P


# ---------------------------------------------------------------------------------------------- generatory specjalne
GENERATORS = ('voronoi', 'gyroid2d', 'zigzag', 'sine', 'spiral', 'turbine', 'arcs', 'labyrinth', 'weave', 'herringbone', 'branches',
              'bubbles', 'fishscale', 'fractal', 'leaves', 'fan', 'radial_slots', 'grid_rect', 'grid_diag', 'mixed_auto')


def _loops_from_polys(polys):
    """Wielokąty (zewnętrzny, otwory) → pętle segmentów 'L'."""
    return [vs._poly(list(np.asarray(q, float))) for q in polys]


def _poly_hole(key, polys, centre=None):
    polys = [np.asarray(q, float) for q in polys]
    polys = [g2.simplify(q, max(.005, .01 * float(np.ptp(q, axis=0).min()))) if len(q) > 24 else q for q in polys]
    c = polys[0].mean(0) if centre is None else np.asarray(centre, float)
    return dict(key=key, kind='poly', c=c, angle=0.0, w=float(np.ptp(polys[0][:, 0])), h=float(np.ptp(polys[0][:, 1])), params={},
                loops=_loops_from_polys(polys), fixed=True)


def voronoi_cells(seeds, lo, hi, k=14):
    """Komórki Voronoi (przycięte do prostokąta lo-hi): przecięcie półpłaszczyzn dwusiecznych z k najbliższymi ziarnami -
    rzeczywisty diagram (komórka wypukła), nie przybliżenie siatką."""
    S = np.asarray(seeds, float)
    cells = []
    box = np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]], float)
    for i, s in enumerate(S):
        d = np.linalg.norm(S - s, axis=1)
        order = np.argsort(d)[1:k + 1]
        poly = box.copy()
        for j in order:
            m = (s + S[j]) / 2
            n = S[j] - s
            poly = _clip_half(poly, m, n)
            if len(poly) < 3:
                break
        # dalsze ziarna mogą jeszcze ciąć komórkę, jeśli są bliżej niż 2× najdalszy wierzchołek
        if len(poly) >= 3:
            rmax = np.linalg.norm(poly - s, axis=1).max()
            for j in np.where((d > d[order[-1]] if len(order) else d > 0) & (d < 2 * rmax))[0]:
                poly = _clip_half(poly, (s + S[j]) / 2, S[j] - s)
                if len(poly) < 3:
                    break
        cells.append(poly)
    return cells


def _clip_half(poly, m, n):
    """Wielokąt wypukły ∩ półpłaszczyzna (x - m)·n ≤ 0 (Sutherland-Hodgman)."""
    out = []
    P = np.asarray(poly, float)
    v = (P - m) @ n
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        va, vb = v[i], v[(i + 1) % len(P)]
        if va <= 0:
            out.append(a)
        if (va < 0 < vb) or (vb < 0 < va):
            out.append(a + (b - a) * (va / (va - vb)))
    return np.array(out) if out else np.zeros((0, 2))


def inset_convex(poly, d):
    """Wypukły wielokąt pomniejszony o d (przesunięcie wszystkich boków do środka) - mostek o szerokości 2d."""
    P = np.asarray(poly, float)
    if g2.area(P) < 0:
        P = P[::-1]
    res = np.array([[-1e9, -1e9], [1e9, -1e9], [1e9, 1e9], [-1e9, 1e9]])
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        e = b - a
        n = np.array([e[1], -e[0]]) / max(np.linalg.norm(e), 1e-12)      # na zewnątrz (CCW)
        res = _clip_half(res, a - n * d, n)
        if len(res) < 3:
            return np.zeros((0, 2))
    return res


def chaikin(P, n):
    P = np.asarray(P, float)
    for _ in range(int(n)):
        Q = []
        for i in range(len(P)):
            a, b = P[i], P[(i + 1) % len(P)]
            Q += [a * .75 + b * .25, a * .25 + b * .75]
        P = np.array(Q)
    return P


def gen_voronoi(p, region):
    lo, hi = region.lo, region.hi
    rng = np.random.default_rng(int(p['seed']))
    cell = max(float(p['cell']), .5)
    mode = p.get('vmode', 'organic')
    irr = min(1.0, max(0.0, float(p.get('irregular', .5))))
    if mode == 'regular':                                               # sześciokątna siatka ziaren (+ nieregularność)
        P, _k, _r = lattice(dict(p, layout='hexagonal', px=cell, py=0.0, rows=0, cols=0, gradients=[]), region, (cell, cell), (cell, cell))
        P = P + (rng.random(P.shape) - .5) * cell * irr
    elif mode == 'gradient' and p['gradients']:
        def rf(Q):
            return cell * factors([dict(gr, param='spacing') for gr in p['gradients']][:1], Q, region, region.centroid())['spacing']
        P = g2.poisson(lo - cell, hi + cell, rf, seed=int(p['seed']))
    else:
        n = int(p.get('count') or 0) or max(4, int(region.area() / (cell * cell * .87)))
        P = lo - cell + rng.random((n, 2)) * (hi - lo + 2 * cell)
    for _ in range(int(p.get('relax', 2)) if mode in ('organic', 'random', 'gradient') else 0):   # relaksacja Lloyda
        cells = voronoi_cells(P, lo - 2 * cell, hi + 2 * cell)
        P = np.array([q.mean(0) if len(q) >= 3 else s for q, s in zip(cells, P)])
    cells = voronoi_cells(P, lo - 2 * cell, hi + 2 * cell)
    half = float(p['bridge']) / 2
    out = []
    cmin, cmax = float(p.get('cell_min') or 0), float(p.get('cell_max') or 0)
    for n, poly in enumerate(cells):
        if len(poly) < 3:
            continue
        q = inset_convex(poly, half)
        if len(q) < 3:
            continue
        a = abs(g2.area(q))
        size = math.sqrt(a)
        if (cmin and size < cmin) or (cmax and size > cmax):
            continue
        if float(p.get('round_r', 0)) > 0:
            loops = [vs.rounded(list(q), float(p['round_r']))]
        elif int(p.get('smoothing', 0)):
            loops = [[('S', list(chaikin(q, int(p['smoothing']))))]]
        else:
            loops = _loops_from_polys([q])
        out.append(dict(key=_key('v', n), kind='poly', c=q.mean(0), angle=0.0, w=float(np.ptp(q[:, 0])), h=float(np.ptp(q[:, 1])),
                        params={}, loops=loops, fixed=True))
    return out


def gen_gyroid2d(p, region):
    """Gyroid 2D: przekrój okresowej funkcji sin(x)cos(y) + sin(y)cos(z0) + sin(z0)cos(x) płaszczyzną z = z0 (faza);
    otwory = obszary f > c (stopień otwarcia), izolinie (marching squares) jako zamknięte profile."""
    cell = max(float(p['cell']), 1.0)
    k = 2 * math.pi / cell
    z0 = float(p.get('gyro_phase', 0.0))
    ang = math.radians(float(p['angle']))
    lo, hi = region.lo - cell, region.hi + cell
    step = cell / 24
    xs = np.arange(lo[0], hi[0] + step, step)
    ys = np.arange(lo[1], hi[1] + step, step)
    X, Y = np.meshgrid(xs, ys, indexing='ij')
    U = (X * math.cos(ang) + Y * math.sin(ang)) * k
    V = (-X * math.sin(ang) + Y * math.cos(ang)) * k
    F = np.sin(U) * np.cos(V) + np.sin(V) * math.cos(z0) + math.sin(z0) * np.cos(U)
    opening = min(.6, max(0.0, float(p.get('opening') or .35)))     # stopień otwarcia: niższy poziom = większe otwory
    level = 1.45 - 1.0 * opening
    # mostki: poziom podniesiony tak, by materiał między sąsiednimi otworami miał co najmniej bridge (|∇f| ≤ √2·k)
    level = level + float(p['bridge']) / 2 * math.sqrt(2) * k * .25
    out = []
    for n, L in enumerate(g2.contours(F, xs, ys, level)):
        if len(L) < 4 or np.linalg.norm(L[0] - L[-1]) > step * 1.5:
            continue                                                    # niezamknięte (na brzegu siatki) - pomijane
        poly = L[:-1]
        if g2.area(poly) == 0:
            continue
        c = poly.mean(0)
        idx = np.clip(((c - lo) / step).astype(int), 0, np.array(F.shape) - 1)
        if F[idx[0], idx[1]] < level:                                    # pętla wokół materiału (nie otworu)
            continue
        out.append(_poly_hole(_key('y', n), [poly]))
    return out


def _stroke_hole(key, P, width):
    """Otwór-szczelina wzdłuż łamanej: odcinek - dokładna kapsuła (odcinki + łuki); łamana o kilku załamaniach - obrys
    z odsunięcia OCC (łuki w zakrętach); krzywa gładka (wiele punktów) - zamknięta krzywa B-spline przez obrys (jedna
    ściana narzędzia zamiast setek - szybkie cięcie)."""
    P = g2.simplify_open(np.asarray(P, float), max(.005, width * .01))
    loops = None
    if len(P) == 2:
        a, b = P
        d = (b - a) / max(np.linalg.norm(b - a), 1e-12)
        n = np.array([-d[1], d[0]]) * width / 2
        loops = [[('L', a - n, b - n), ('A', b - n, b + d * width / 2, b + n), ('L', b + n, a + n), ('A', a + n, a - d * width / 2, a - n)]]
    if loops is None:
        polys = g2.stroke(P, width)
        if g2.self_intersects(polys[0]):
            raise kernel.CadError('Szczelina wzdłuż krzywej przecina samą siebie - zwiększ promień krzywej albo zmniejsz szerokość.')
        loops = [[('S', list(polys[0][::max(1, len(polys[0]) // 160)]))]]
    poly = vs.sample_loop(loops[0], 12)
    return dict(key=key, kind='poly', c=poly.mean(0), angle=0.0, w=float(np.ptp(poly[:, 0])), h=float(np.ptp(poly[:, 1])), params={},
                loops=loops, fixed=True)


def _slots_on_line(key, line, width, gap, out, seg_len=None):
    """Łamana podzielona na odcinki z mostkami (gap) i pogrubiona do szczelin - materiał pozostaje połączony. Ostre
    załamania (> 25°) dzielą łamaną: każda część to osobna szczelina, z mostkiem w załamaniu."""
    L = g2.simplify_open(np.asarray(line, float), max(.005, width * .01))
    if len(L) > 2:
        d = np.diff(L, axis=0)
        d /= np.maximum(np.linalg.norm(d, axis=1)[:, None], 1e-12)
        turn = np.degrees(np.arccos(np.clip((d[:-1] * d[1:]).sum(1), -1, 1)))
        cuts = [i + 1 for i, t in enumerate(turn) if t > 50.0]
        if cuts:
            sh = (gap * 1.08 + width) * .75
            ends = [0] + cuts + [len(L) - 1]
            for m in range(len(ends) - 1):
                seg = L[ends[m]:ends[m + 1] + 1].copy()
                if m > 0:                                               # odsunięcie od załamania (mostek)
                    e = seg[1] - seg[0]
                    ln = np.linalg.norm(e)
                    if ln <= sh + width * .6:
                        continue
                    seg[0] = seg[0] + e / ln * sh
                if m < len(ends) - 2:
                    e = seg[-1] - seg[-2]
                    ln = np.linalg.norm(e)
                    if ln <= sh + width * .6:
                        continue
                    seg[-1] = seg[-1] - e / ln * sh
                _slots_on_line(_key(key, 'c', m), seg, width, gap, out, seg_len)
            return
    seg = np.linalg.norm(np.diff(L, axis=0), axis=1)
    cum = np.r_[0, np.cumsum(seg)]
    total = cum[-1]
    if total < width:
        return
    piece = seg_len or total
    s = 0.0
    n = 0
    while s < total - 1e-6:
        e = min(total, s + piece)
        ts = np.linspace(s, e, max(2, int((e - s) / max(width / 3, .2)) + 2))
        P = np.c_[np.interp(ts, cum, L[:, 0]), np.interp(ts, cum, L[:, 1])]
        if e - s > width * .6:
            try:
                out.append(_stroke_hole(_key(key, n), P, width))
            except kernel.CadError:
                pass
        pe = np.array([np.interp(e, cum, L[:, 0]), np.interp(e, cum, L[:, 1])])
        s = e + gap * 1.08 + width
        while s < total:                                                # w zakręcie odległość w linii prostej jest mniejsza niż po łuku
            ps = np.array([np.interp(s, cum, L[:, 0]), np.interp(s, cum, L[:, 1])])
            if np.linalg.norm(ps - pe) >= gap * 1.08 + width:
                break
            s += width / 4
        n += 1


def gen_strokes(p, region):
    """Szczeliny wzdłuż krzywych: zygzaki, fale sinusoidalne, spirale, łuki koncentryczne, turbiny, labirynt, jodełka,
    plecionka, szczeliny promieniowe."""
    gen = p['generator']
    c, ang, sc = _frame(p, region)
    R = float(p.get('r_max') or 0) or float(np.linalg.norm(region.hi - region.lo)) / 2 + 5
    wch = float(p.get('channel', 2.0)) * sc
    br = float(p['bridge'])
    py = (float(p['py']) or (wch + br + (2 * float(p.get('amplitude', 3.0)) + .5 if gen in ('zigzag', 'sine') else 2.0))) * sc
    px = (float(p['px']) or 12.0) * sc
    out = []
    lines = []
    rot = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]])
    T = lambda P: c + np.asarray(P, float) @ rot.T
    if gen in ('zigzag', 'sine'):
        A = float(p.get('amplitude', 3.0)) * sc
        fr = float(p.get('frequency', .1)) / sc
        ph = float(p.get('phase', 0.0))
        nrow = int(2 * R / py) + 2
        for j in range(nrow):
            y0 = (j - nrow / 2) * py
            xs = np.arange(-R, R, .5)
            if gen == 'sine':
                ys = y0 + A * np.sin(2 * math.pi * fr * xs + math.radians(ph))
            else:
                tt = (xs * fr + ph / 360) % 1.0
                ys = y0 + A * (4 * np.abs(tt - .5) - 1)
            lines.append((_key(gen, j), np.c_[xs, ys]))
    elif gen == 'spiral':
        arms = max(1, int(p.get('arms_n', 1)))
        turns = max(.25, float(p.get('turns', 3.0)))
        pitch = float(p.get('pitch') or 0) * sc or max(R / turns, (wch + br) * arms * 1.15)
        sgn = -1 if p.get('twist') == 'cw' else 1
        r0 = max(2 * wch, arms * (wch + br) / math.pi)                  # ramiona startują tam, gdzie mieszczą się obok siebie
        for m in range(arms):
            th = np.linspace(0, 2 * math.pi * turns, int(turns * 120))
            r = r0 + pitch * th / (2 * math.pi)
            P = np.c_[r * np.cos(sgn * th + 2 * math.pi * m / arms), r * np.sin(sgn * th + 2 * math.pi * m / arms)]
            lines.append((_key('sp', m), P))
    elif gen in ('arcs', 'turbine', 'radial_slots'):
        arms = max(2, int(p.get('arms_n', 6)))
        k = 1
        while k * py < R:
            r = k * py
            for m in range(arms):
                a0 = 2 * math.pi * m / arms
                if gen == 'arcs':
                    th = np.linspace(a0, a0 + 2 * math.pi / arms - (br + wch) / r, 24)
                    lines.append((_key('ar', k, m), np.c_[r * np.cos(th), r * np.sin(th)]))
            k += 1
        if gen in ('turbine', 'radial_slots'):
            sgn = -1 if p.get('twist') == 'cw' else 1
            r0 = float(p.get('fan_hub') or 0) * sc or py
            for m in range(arms):
                a0 = 2 * math.pi * m / arms
                rr = np.linspace(r0, R, 40)
                bend = math.radians(float(p.get('branch_angle', 30.0))) * sgn if gen == 'turbine' else 0.0
                th = a0 + bend * (rr - r0) / max(R - r0, 1e-9)
                lines.append((_key('tb', m), np.c_[rr * np.cos(th), rr * np.sin(th)]))
    elif gen == 'labyrinth':                                            # labirynt (DFS na siatce) - ściany jako szczeliny z mostkami
        cellw = max(py, float(p.get('cell') or 0) * sc, 2 * (br + wch) / math.sqrt(2) * 1.05 + wch * 2)
        n = int(2 * R / cellw) + 1
        rng = np.random.default_rng(int(p['seed']))
        seen = np.zeros((n, n), bool)
        stack = [(n // 2, n // 2)]
        seen[n // 2, n // 2] = True
        edges = []
        while stack:
            i, j = stack[-1]
            nb = [(i + di, j + dj) for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)) if 0 <= i + di < n and 0 <= j + dj < n and not seen[i + di, j + dj]]
            if not nb:
                stack.pop()
                continue
            q = nb[int(rng.integers(len(nb)))]
            seen[q] = True
            edges.append(((i, j), q))
            stack.append(q)
        for a, b in edges:                                              # korytarze labiryntu = szczeliny (drzewo - bez wysp)
            pa = (np.array(a) - n / 2) * cellw
            pb = (np.array(b) - n / 2) * cellw
            d = pb - pa
            e = d / np.linalg.norm(d)
            sh = (br + wch) / math.sqrt(2) * 1.05                         # końce szczelin przy węźle: mostek ≥ br także po przekątnej
            if np.linalg.norm(pb - pa) > 2 * sh + wch * .5:
                lines.append((_key('lb', *a, *b), np.array([pa + e * sh, pb - e * sh])))
        px = 1e9
    elif gen in ('herringbone', 'weave'):
        L = px
        nrow = int(2 * R / py) + 2
        ncol = int(2 * R / (L * .8)) + 2
        for j in range(nrow):
            for i in range(ncol):
                q = np.array([(i - ncol / 2) * L * (.75 if gen == 'herringbone' else 1.0), (j - nrow / 2) * py])
                if gen == 'herringbone':
                    a = math.radians(45 if i % 2 else -45)
                    d = np.array([math.cos(a), math.sin(a)]) * (L / 2 - wch)
                else:                                                   # plecionka: na przemian poziome i pionowe
                    vert = (i + j) % 2
                    q = np.array([(i - ncol / 2) * (L / 2 + br), (j - nrow / 2) * (L / 2 + br)])
                    d = np.array([0.0, 1.0] if vert else [1.0, 0.0]) * (L / 4 - wch / 2)
                lines.append((_key(gen, i, j), np.array([q - d, q + d])))
        px = 1e9
    for key, P in lines:
        Pw = T(P)
        _slots_on_line(key, Pw, wch, br, out, px if gen not in ('labyrinth', 'herringbone', 'weave') else None)
    return out


def gen_branches(p, region):
    """Organiczne rozgałęzienia: drzewo rosnące od środka (kąt i gęstość rozgałęzień, losowość) - gałęzie jako
    zwężające się szczeliny z mostkami w węzłach (drzewo nie tworzy wysp materiału)."""
    rng = np.random.default_rng(int(p['seed']))
    c, ang, sc = _frame(p, region)
    R = float(np.linalg.norm(region.hi - region.lo)) / 2
    wch = float(p.get('channel', 2.0)) * sc
    br = float(p['bridge'])
    a_br = math.radians(float(p.get('branch_angle', 30.0)))
    seg = max((wch + br) / (2 * math.sin(max(a_br, math.radians(10)) / 2)) * 1.1 + 2.5 * wch, (float(p['px']) or 8.0) * sc)
    dens = min(1.0, max(0.0, float(p.get('branch_density', .5))))
    roots = max(1, int(p.get('arms_n', 5)))
    out, placed = [], []
    grid = g2.Hash(seg + wch)
    tips = [(c, ang + 2 * math.pi * m / roots, 0, _key('br', m)) for m in range(roots)]
    n = 0
    while tips and n < 4000:
        q, a, depth, key = tips.pop(0)
        jitter = (rng.random() - .5) * math.radians(20) * float(p.get('irregular', .5))
        a2 = a + jitter
        e = q + seg * np.array([math.cos(a2), math.sin(a2)])
        if np.linalg.norm(e - c) > R or not region.contains(e[None])[0]:
            continue
        d = e - q
        dn = d / np.linalg.norm(d)
        w = max(wch * (1 - depth * .08), wch * .4)
        off = (w + br) / (2 * math.sin(max(a_br, math.radians(10)) / 2)) * 1.1 if depth else br + w / 2   # rodzeństwo z mostkiem
        if seg <= off + w:
            continue
        P = np.array([q + dn * off, e - dn * (w / 2)])
        polys = g2.stroke(P, w)                                          # odcinek - obrys kapsuły (zawsze poprawny)
        lo_, hi_ = polys[0].min(0), polys[0].max(0)
        if any(g2.poly_dist(polys[0], placed[j]) < br * 1.05 for j in grid.near(lo_ - br, hi_ + br)):
            continue                                                    # gałąź przecięłaby inną - rośnie dalej tylko gdzie jest miejsce
        placed.append(polys[0])
        grid.add(len(placed) - 1, lo_, hi_)
        out.append(_poly_hole(_key(key, n), polys))
        n += 1
        tips.append((e, a2, depth + 1, key + 'a'))
        if rng.random() < dens:
            tips.append((e, a2 + a_br * (1 if rng.random() < .5 else -1), depth + 1, key + 'b'))
    return out


def gen_bubbles(p, region):
    """Losowe pęcherzyki: koła o losowych średnicach (od size_min do w), bez nakładania, mostek ≥ bridge."""
    rng = np.random.default_rng(int(p['seed']))
    dmax, dmin = float(p['w']), max(float(p['size_min']), .3)
    br = float(p['bridge'])
    lo, hi = region.lo, region.hi
    placed, out = [], []
    grid = g2.Hash(dmax + br)
    tries = int(region.area() / (dmin * dmin) * 3) + 200
    for t in range(min(tries, 200000)):
        q = lo + rng.random(2) * (hi - lo)
        d = dmin + (dmax - dmin) * rng.random() ** 2
        ok = True
        for j in grid.near(q - (dmax + br), q + (dmax + br)):
            c2, d2 = placed[j]
            if np.linalg.norm(c2 - q) < (d + d2) / 2 + br:
                ok = False
                break
        if ok:
            placed.append((q, d))
            grid.add(len(placed) - 1, q, q)
            out.append(dict(key=_key('b', len(placed)), kind='circle', c=q, angle=0.0, w=d, h=d, params={}))
        if len(placed) > MAX_HOLES:
            break
    return out


def gen_fishscale(p, region):
    """Rybie łuski: sierpowate otwory w rzędach przesuniętych o pół rozstawu."""
    w = float(p['w'])
    q = dict(p, kind='crescent', layout='offset_h', shift_row=50.0, ratio=p.get('ratio', .5), link=False)
    br = float(p['bridge'])
    P, keys, rot = lattice(q, region, (w, w), (float(p['px']) or w + br, float(p['py']) or w * .75 + br))
    return [dict(key=k_, kind='crescent', c=c_, angle=float(r_) + math.radians(float(p['hole_angle'])), w=w, h=w, params=dict(ratio=float(p.get('ratio', .5))))
            for c_, k_, r_ in zip(P, keys, rot)]


def gen_fractal(p, region):
    """Fraktale: dywan Sierpińskiego (kwadraty) - poziom rekurencji; trójkąt Sierpińskiego dla kształtu 'tri'."""
    lvl = max(1, min(6, int(p.get('level', 3))))
    c = region.centroid() + np.array([float(p['ox']), float(p['oy'])])
    size = float(np.min(region.hi - region.lo)) * float(p['scale']) - 2 * float(p['margin'])
    ang = math.radians(float(p['angle']))
    out = []
    if p.get('kind') == 'tri':
        def tri(a, b, cc, d, key):
            if d == 0:
                return
            ab, bc, ca = (a + b) / 2, (b + cc) / 2, (cc + a) / 2
            out.append(_poly_hole(key, [np.array([ab, bc, ca])]))
            tri(a, ab, ca, d - 1, key + '0')
            tri(ab, b, bc, d - 1, key + '1')
            tri(ca, bc, cc, d - 1, key + '2')
        R = size / math.sqrt(3)
        V = [c + R * np.array([math.cos(ang + math.pi / 2 + 2 * math.pi * k / 3), math.sin(ang + math.pi / 2 + 2 * math.pi * k / 3)]) for k in range(3)]
        tri(*V, lvl, 'f')
        return out

    def carpet(cc, s, d, key):
        if d == 0:
            return
        h = s / 3
        out.append(dict(key=key, kind='square', c=cc, angle=ang, w=h, h=h, params={}))
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                if i == 0 and j == 0:
                    continue
                off = np.array([math.cos(ang) * i * h - math.sin(ang) * j * h, math.sin(ang) * i * h + math.cos(ang) * j * h])
                carpet(cc + off, h, d - 1, key + f'{i + 1}{j + 1}')
    carpet(c, size, lvl, 'f')
    return out


def gen_leaves(p, region):
    """Struktury liści: soczewki ułożone parami wzdłuż żyłek (gałęzie co rozstaw), kąt liści względem żyłki."""
    out = []
    w = float(p['w'])
    q = dict(p, layout='offset_h', shift_row=50.0)
    br = float(p['bridge'])
    P, keys, rot = lattice(q, region, (w, w / 2.5), (float(p['px']) or w * .95 + br, float(p['py']) or w * .7 + br))
    a = math.radians(float(p.get('branch_angle', 35.0)))
    for c_, k_, r_ in zip(P, keys, rot):
        side = 1 if hash(k_) % 2 else -1
        out.append(dict(key=k_, kind='lens', c=c_, angle=float(r_) + side * a, w=w, h=w / 2.5, params={}))
    return out


FAN_SIZES = (25, 30, 40, 50, 60, 70, 80, 92, 120, 140, 180, 200)
# rozstaw otworów montażowych [mm] i średnica otworu - wartości typowe z kart katalogowych (np. Noctua, Sunon, EBM-papst:
# 40 mm - 32, 60 - 50, 80 - 71,5, 92 - 82,5, 120 - 105, 140 - 124,5); 180 i 200 mm nie mają jednego standardu - do
# wpisania z karty wentylatora (pole „Rozstaw otworów”), domyślnie wartości często spotykane (170 / 154).
FANS = {25: (20.0, 2.9), 30: (24.0, 3.3), 40: (32.0, 3.4), 50: (40.0, 3.8), 60: (50.0, 4.4), 70: (60.0, 4.4), 80: (71.5, 4.4), 92: (82.5, 4.4),
        120: (105.0, 4.4), 140: (124.5, 4.4), 180: (170.0, 4.5), 200: (154.0, 4.5)}
FAN_STYLES = ('concentric', 'radial', 'hex', 'spiral', 'turbine', 'cross', 'voronoi', 'round', 'slots', 'custom')
FAN_STYLE_LABELS = {'concentric': 'koncentryczna', 'radial': 'promieniowa', 'hex': 'sześciokątna', 'spiral': 'spiralna', 'turbine': 'turbinowa',
                    'cross': 'krzyżowa', 'voronoi': 'Voronoi', 'round': 'otwory okrągłe', 'slots': 'otwory podłużne', 'custom': 'własny wzór'}


def gen_fan(p, region):
    """Kratka wentylatora: obszar kołowy (średnica wentylatora albo własna), pełny środek (piasta), ramiona / pierścienie
    według stylu, otwory montażowe z rozstawu z karty (albo wpisanego)."""
    F = int(p.get('fan', 40))
    spacing_d, hole_d = FANS.get(F, (float(F) * .8, 4.4))
    spacing_d = float(p.get('fan_spacing') or 0) or spacing_d
    hole_d = float(p.get('fan_hole') or 0) or hole_d
    D = float(p.get('fan_d') or 0) or F - 2.0
    c = region.centroid() + np.array([float(p['ox']), float(p['oy'])])
    ang = math.radians(float(p['angle']))
    hub = float(p.get('fan_hub') or 0) or D * .3
    br = float(p['bridge'])
    circ = [c + D / 2 * np.array([math.cos(t), math.sin(t)]) for t in np.linspace(0, 2 * math.pi, 96, endpoint=False)]
    hubp = [c + hub / 2 * np.array([math.cos(t), math.sin(t)]) for t in np.linspace(0, 2 * math.pi, 64, endpoint=False)]
    sub = g2.Region([np.array(circ)], [np.array(hubp)])
    style = p.get('fan_style', 'concentric')
    m = float(p['margin'])
    q = dict(p, ox=0.0, oy=0.0, r_max=D / 2 - m - float(p.get('channel') or 3.0) / 2 - .15)
    if style == 'concentric':
        holes = gen_strokes(dict(q, generator='arcs', arms_n=int(p.get('arms_n') or 4), channel=float(p.get('channel') or 3.0)), sub)
    elif style in ('radial', 'turbine', 'spiral'):
        holes = gen_strokes(dict(q, generator={'radial': 'radial_slots', 'turbine': 'turbine', 'spiral': 'spiral'}[style],
                                 fan_hub=hub / 2 + m + float(p.get('channel') or 3.0) / 2 + .05,
                                 arms_n=int(p.get('arms_n') or 8), channel=float(p.get('channel') or 3.0)), sub)
    elif style == 'cross':
        holes = _sectors(c, D - 2 * m - .1, hub + 2 * m + .1, ang, br, int(p.get('arms_n') or 4))
    elif style == 'voronoi':
        holes = gen_voronoi(dict(q, cell=float(p.get('cell') or 8.0), edge_mode='trim'), sub)
        for hh in holes:
            hh['trim'] = True
    elif style in ('round', 'hex', 'slots'):
        kind = {'round': 'circle', 'hex': 'hex', 'slots': 'capsule'}[style]
        w = float(p['w'])
        h = float(p['h']) if style == 'slots' else w
        qq = dict(q, kind=kind, layout='hexagonal' if style != 'slots' else 'offset_h', w=w, h=h, generator='')
        P, keys, rot = lattice(qq, sub, (w, h), spacing(qq, (w, h)))
        holes = [dict(key=k_, kind=kind, c=c_, angle=ang, w=w, h=h, params={}) for c_, k_ in zip(P, keys)]
    else:
        w = float(p['w'])
        qq = dict(q, layout='hexagonal', generator='')
        P, keys, rot = lattice(qq, sub, (w, w), spacing(qq, (w, w)))
        holes = [dict(key=k_, kind=p.get('kind', 'circle'), c=c_, angle=ang, w=w, h=float(p['h']), params=_shape_params(p)) for c_, k_ in zip(P, keys)]
    for hh in holes:
        hh['region'] = sub
    if p.get('fan_mount', True):
        for sx in (-1, 1):
            for sy in (-1, 1):
                m = c + vs._rot(np.array([sx * spacing_d / 2, sy * spacing_d / 2]), ang)
                holes.append(dict(key=_key('mount', sx, sy), kind='circle', c=m, angle=0.0, w=hole_d, h=hole_d, params={}, role='mount'))
    return holes


def _sectors(c, D, hub, ang, br, n):
    """Kratka krzyżowa / szprychowa: n sektorów pierścienia między piastą a obwodem, rozdzielonych szprychami o stałej
    szerokości br (przycięcie półpłaszczyznami równoległymi do osi szprych)."""
    out = []
    c = np.asarray(c, float)
    for k in range(n):
        a0 = ang + 2 * math.pi * k / n
        a1 = ang + 2 * math.pi * (k + 1) / n
        outer = [c + D / 2 * np.array([math.cos(t), math.sin(t)]) for t in np.linspace(a0, a1, 48)]
        inner = [c + hub / 2 * np.array([math.cos(t), math.sin(t)]) for t in np.linspace(a1, a0, 24)]
        poly = np.array(outer + inner)
        for a_, sgn in ((a0, 1), (a1, -1)):                             # szprycha: pas ±br/2 wokół promienia pod kątem a_
            d = np.array([math.cos(a_), math.sin(a_)])
            nrm = np.array([-d[1], d[0]]) * sgn
            poly = _clip_half(poly, c + nrm * br / 2, -nrm)
            if len(poly) < 3:
                break
        if len(poly) >= 3:
            out.append(_poly_hole(_key('sec', k), [poly]))
    return out


def _shape_params(p):
    return {k: p[k] for k in ('corner', 'sides', 'arms', 'ratio', 'arm', 'bend', 'irregularity', 'loops', 'base', 'ref_angle', 'fit') if k in p}


def generate_raw(p, region):
    """Otwory przed walidacją: generator specjalny albo kształt × układ (z gradientami, wzorem mieszanym)."""
    gen = p.get('generator') or ''
    if gen == 'voronoi':
        return gen_voronoi(p, region)
    if gen == 'gyroid2d':
        return gen_gyroid2d(p, region)
    if gen in ('zigzag', 'sine', 'spiral', 'turbine', 'arcs', 'labyrinth', 'weave', 'herringbone', 'radial_slots'):
        return gen_strokes(p, region)
    if gen == 'branches':
        return gen_branches(p, region)
    if gen == 'bubbles':
        return gen_bubbles(p, region)
    if gen == 'fishscale':
        return gen_fishscale(p, region)
    if gen == 'fractal':
        return gen_fractal(p, region)
    if gen == 'leaves':
        return gen_leaves(p, region)
    if gen == 'fan':
        return gen_fan(p, region)
    if gen == 'grid_rect':
        p = dict(p, kind='square', layout='square')
    elif gen == 'grid_diag':
        p = dict(p, kind='square', layout='diagonal')
    kinds = _mix(p)
    size = _extent(kinds, p)                                            # rozstaw automatyczny z ramki obróconego obrysu
    sp = spacing(p, size)
    P, keys, rot = lattice(p, region, size, sp)
    if not len(P):
        return []
    fac = factors(p['gradients'], P, region, region.centroid())
    out = []
    rng = np.random.default_rng(int(p['seed']))
    shares = np.array([float(k_.get('share', 1.0)) for k_ in kinds])
    shares = shares / shares.sum() if shares.sum() > 0 else np.ones(len(kinds)) / len(kinds)
    for n, (c, key) in enumerate(zip(P, keys)):
        if len(kinds) == 1:
            sh = kinds[0]
        elif p.get('mix_mode') == 'percent':
            sh = kinds[int(rng.choice(len(kinds), p=shares))]
        elif p.get('mix_mode') == 'alternate':
            ij = [int(x) for x in key.split('/')[1:3]] if key.startswith('g/') else [n, 0]
            sh = kinds[(sum(ij)) % len(kinds)]
        else:
            sh = kinds[n % len(kinds)]
        asp = fac['aspect'][n]
        sw = sh['w'] * fac['size'][n] * fac['width'][n] * fac['length'][n] * float(p['scale'])
        shh = sh['h'] * fac['size'][n] * fac['height'][n] * float(p['scale']) / max(asp, 1e-3)
        a = float(rot[n]) + math.radians(float(p['hole_angle']) + float(sh.get('angle', 0.0)) + fac['rotation'][n])
        out.append(dict(key=key, kind=sh['kind'], c=c, angle=a, w=sw, h=shh, params=dict(sh.get('params') or {}),
                        depth_k=float(fac['depth'][n]), tilt=float(fac['tilt'][n])))
    return out


def _extent(kinds, p):
    """Rozstaw automatyczny: największa odległość między przeciwległymi krańcami obrysów wszystkich odmian otworu
    (kształty wzoru mieszanego, obrót naprzemienny) - sąsiednie otwory nie wchodzą na siebie."""
    polys = []
    for k_ in kinds:
        try:
            poly = vs.sample_loop(vs.profile(k_['kind'], k_['w'], k_['h'], k_.get('params'))[0], 32)
        except kernel.CadError:
            poly = np.array([[-k_['w'] / 2, -k_['h'] / 2], [k_['w'] / 2, k_['h'] / 2]])
        a = math.radians(float(p['hole_angle']) + float(k_.get('angle', 0.0)))
        alt = math.radians(float(p.get('alt_angle', 0.0))) if p.get('layout') == 'alternating' else 0.0
        for extra in sorted({0.0, alt}):
            polys.append(vs._rot(poly, a + extra))
    lo = np.array([q.min(0) for q in polys])
    hi = np.array([q.max(0) for q in polys])
    bw = float((hi[:, None, 0] - lo[None, :, 0]).max())
    bh = float((hi[:, None, 1] - lo[None, :, 1]).max())
    sc = float(p.get('scale', 1.0))
    return bw * sc, bh * sc


def _mix(p):
    mixed = [m for m in (p.get('mixed') or []) if m.get('kind')]
    if mixed:
        return [dict(kind=m['kind'], w=float(m.get('w', p['w'])), h=float(m.get('h', m.get('w', p['h']))), angle=float(m.get('angle', 0.0)),
                     share=float(m.get('share', 1.0)), params=dict(_shape_params(p), **(m.get('params') or {}))) for m in mixed]
    return [dict(kind=p['kind'], w=float(p['w']), h=float(p['h'] or p['w']), angle=0.0, share=1.0, params=_shape_params(p))]


# ---------------------------------------------------------------------------------------------- walidacja i brzegi
def _build(h, n=20):
    if 'loops' not in h or not h.get('fixed'):
        h['loops'] = vs.place(vs.profile(h['kind'], h['w'], h['h'], h.get('params')), h['c'], h['angle'])
    h['poly'] = vs.sample_loop(h['loops'][0], n)
    h['lo'], h['hi'] = h['poly'].min(0), h['poly'].max(0)
    return h


def _fits(h, region, p, zones):
    """Otwór w obszarze z marginesami i poza strefami zabronionymi (sprawdzenie na obrysie)."""
    P = h['poly']
    if not h.pop('_inside', False):                                     # szybka ścieżka: środek daleko od brzegów (policzone hurtem)
        if not region.contains(P).all() or not region.contains(h['c'][None]).all():
            return False, 'poza obszarem'
        m = float(p['margin'])
        if m > 0 and region.edge_dist(P).min() < m - 1e-9:
            return False, 'za blisko krawędzi'
        mh = float(p['margin_holes'])
        if region.holes and region.hole_dist(P).min() < mh - 1e-9:
            return False, 'za blisko istniejącego otworu'
    for z in zones:
        gap = float(z.get('gap', p['obstacle_gap']))
        zp = z['poly']
        if (h['hi'] < zp.min(0) - gap).any() or (h['lo'] > zp.max(0) + gap).any():
            continue
        if g2.poly_dist(P, zp) < gap - 1e-9:
            return False, 'strefa zabroniona: ' + z.get('name', '')
    return True, ''


def finalize(raw, p, region, zones=()):
    """Kontrola i obsługa brzegów: tryby krawędzi i przeszkód, mostki między otworami (siatka przestrzenna), ręczne
    zmiany (overrides / added), statusy. Zwraca (otwory, raport)."""
    p = dict(DEFAULTS, **p)
    edge = p['edge_mode']
    obst = p['obstacle_mode']
    zones = [dict(z, poly=np.asarray(z['poly'], float)) for z in zones]
    ov = p.get('overrides') or {}
    report = []
    holes = []
    for h in raw:
        o = ov.get(h['key']) or {}
        if not o:                                                       # otwory w całości poza obszarem nie są liczone
            reg = h.get('region') or region
            c = np.asarray(h['c'], float)
            ext = max(float(h.get('w', 0)), float(h.get('h', 0))) / 2 + 1e-9
            if (c + ext < reg.lo).any() or (c - ext > reg.hi).any():
                continue
        if o.get('deleted'):
            h = dict(h, status='skip', reason='usunięty ręcznie', manual=True)
            holes.append(_build(h))
            continue
        h = dict(h)
        if o:
            h['manual'] = True
            if 'dx' in o or 'dy' in o:
                h['c'] = np.asarray(h['c'], float) + np.array([float(o.get('dx', 0)), float(o.get('dy', 0))])
                h.pop('loops', None) if not h.get('fixed') else None
                if h.get('fixed'):
                    h['loops'] = vs.place(h['loops'], np.array([float(o.get('dx', 0)), float(o.get('dy', 0))]), 0.0)
            for k_ in ('w', 'h', 'kind'):
                if k_ in o:
                    h[k_] = o[k_]
                    h['fixed'] = False
            if 'rot' in o:
                h['angle'] = float(h['angle']) + math.radians(float(o['rot']))
                h['fixed'] = False if h['kind'] != 'poly' else h.get('fixed')
            for k_ in ('depth_k', 'tilt', 'dir', 'locked'):
                if k_ in o:
                    h[k_] = o[k_]
        holes.append(_build(h))
    for a in p.get('added') or []:                                       # otwory dodane ręcznie
        h = dict(key=a.get('key') or _key('add', len(holes)), kind=a.get('kind', p['kind']), c=np.asarray(a['c'], float), angle=math.radians(float(a.get('angle', 0.0))),
                 w=float(a.get('w', p['w'])), h=float(a.get('h', a.get('w', p['h']))), params=_shape_params(p), manual=True, added=True,
                 locked=bool(a.get('locked', True)), depth_k=float(a.get('depth_k', 1.0)), tilt=float(a.get('tilt', 0.0)))
        holes.append(_build(h))
    gone = [k_ for k_ in ov if k_ not in {h['key'] for h in holes}]
    if gone:
        report.append(('warning', f'Nie można zachować {len(gone)} ręcznych zmian - tych otworów nie ma w nowym wzorze: ' + ', '.join(map(str, gone[:6]))))
    # obsługa krawędzi / przeszkód; hurtem: otwory, których środek leży w obszarze dalej od brzegów niż promień obrysu
    # (plus margines), na pewno mieszczą się w obszarze - bez sprawdzania każdego punktu obrysu
    by_reg = {}
    for i, h in enumerate(holes):
        if h.get('status') != 'skip':
            by_reg.setdefault(id(h.get('region') or region), (h.get('region') or region, []))[1].append(i)
    for reg, idx in by_reg.values():
        C = np.array([holes[i]['c'] for i in idx], float).reshape(-1, 2)
        R = np.array([float(np.linalg.norm(holes[i]['poly'] - holes[i]['c'], axis=1).max()) for i in idx])
        ok = reg.contains(C) & (reg.edge_dist(C) - R >= max(float(p['margin']), 0.0) + 1e-6)
        if reg.holes:
            ok &= reg.hole_dist(C) - R >= max(float(p['margin_holes']), 0.0) + 1e-6
        for i, f in zip(idx, ok):
            if f:
                holes[i]['_inside'] = True
    out = []
    for h in holes:
        if h.get('status') == 'skip':
            out.append(h)
            continue
        reg = h.get('region') or region
        ok, why = _fits(h, reg, p, zones)
        if ok:
            h['status'] = 'ok'
            out.append(h)
            continue
        if h.get('role') == 'mount':
            h['status'] = 'ok' if region.contains(h['poly']).all() else 'bad'
            h['reason'] = '' if h['status'] == 'ok' else 'otwór montażowy poza obszarem'
            out.append(h)
            continue
        mode = 'trim' if h.get('trim') else (obst if why.startswith('strefa') else edge)
        if h.get('locked') and h.get('manual'):
            h.update(status='bad', reason=why + ' (otwór zablokowany)')
            out.append(h)
            continue
        fixed = _repair(h, reg, p, zones, mode)
        if fixed is None:
            h.update(status='skip', reason=why)
        else:
            h = fixed
        out.append(h)
    # mostki między otworami
    act = [h for h in out if h['status'] in ('ok', 'adjust')]
    br = float(p['bridge'])
    cell = max(max((float(np.ptp(h['poly'][:, 0])) for h in act), default=1.0), br) + br
    hs = g2.Hash(cell)
    for n, h in enumerate(act):
        hs.add(n, h['lo'] - br, h['hi'] + br)
    bad = set()
    min_br = math.inf
    for n, h in enumerate(act):
        for m in hs.near(h['lo'] - br, h['hi'] + br):
            if m <= n or m in bad or n in bad:
                continue
            o = act[m]
            if (h['hi'] < o['lo'] - br).any() or (h['lo'] > o['hi'] + br).any():
                continue
            d = g2.poly_dist(h['poly'], o['poly'])
            min_br = min(min_br, d)
            if d < br - 1e-6:
                victim = m if not o.get('locked') else n
                bad.add(victim)
    for n in bad:
        act[n].update(status='bad', reason=f'mostek < {br:g} mm (nakłada się z sąsiednim otworem)')
    if bad:
        report.append(('warning', f'{len(bad)} otworów narusza minimalny mostek {br:g} mm - pominięte (czerwone).'))
    stats = dict(min_bridge=None if min_br == math.inf else float(min_br))
    return out, report, stats


def _repair(h, region, p, zones, mode):
    """Dopasowanie otworu przy krawędzi / przeszkodzie według trybu; None - pominięty."""
    if mode in ('full', 'skip'):
        return None
    if mode in ('shrink', 'adaptive'):
        for s in np.linspace(.95, max(float(p['min_scale']), .05), 12):
            q = _build(dict(h, w=h['w'] * s, h=h['h'] * s, fixed=False) if h['kind'] != 'poly' else _scaled_poly(h, s))
            ok, _w = _fits(q, region, p, zones)
            if ok:
                q.update(status='adjust', reason=f'zmniejszony do {100 * s:.0f} %')
                return q
        if mode == 'shrink':
            return None
    if mode in ('push', 'adaptive'):
        step = max(float(p['bridge']) / 2, .2)
        c0 = np.asarray(h['c'], float)
        ctr = region.centroid()
        d = ctr - c0
        d = d / max(np.linalg.norm(d), 1e-9)
        for k in range(1, 30):
            q = _build(_moved(h, d * step * k))
            ok, _w = _fits(q, region, p, zones)
            if ok:
                q.update(status='adjust', reason=f'odsunięty o {step * k:.1f} mm')
                return q
        return None
    if mode == 'trim':
        inner = region.outers
        loops = [vs.sample_loop(lp, 32) for lp in h['loops']]
        res = g2.occ_clip(loops, [_inset(o, float(p['margin'])) for o in inner], [*region.holes, *[z['poly'] for z in zones]])
        if not res:
            return None
        best = max(res, key=lambda L: abs(g2.area(L[0])))
        a = abs(g2.area(best[0])) - sum(abs(g2.area(x)) for x in best[1:])
        if a < float(p['min_area']):
            return None
        ext = best[0].max(0) - best[0].min(0)
        if min(ext) < float(p['min_width']):
            return None
        q = dict(h, kind='poly', loops=_loops_from_polys(best), fixed=True, status='adjust', reason='przycięty do granicy')
        q['poly'] = best[0]
        q['lo'], q['hi'] = best[0].min(0), best[0].max(0)
        return q
    return None


def _inset(poly, m):
    """Kontur obszaru odsunięty do środka o margines (przybliżenie wielokątem: przesunięcie wierzchołków po dwusiecznych)."""
    P = np.asarray(poly, float)
    if m <= 0:
        return P
    if g2.area(P) < 0:
        P = P[::-1]
    out = []
    n = len(P)
    for i in range(n):
        a, b, c = P[i - 1], P[i], P[(i + 1) % n]
        e1, e2 = b - a, c - b
        n1 = np.array([-e1[1], e1[0]]) / max(np.linalg.norm(e1), 1e-12)
        n2 = np.array([-e2[1], e2[0]]) / max(np.linalg.norm(e2), 1e-12)
        bis = n1 + n2
        ln = np.linalg.norm(bis)
        if ln < 1e-9:
            out.append(b + n1 * m)
            continue
        bis /= ln
        out.append(b + bis * m / max(float(bis @ n1), .2))
    return np.array(out)


def _moved(h, d):
    q = dict(h, c=np.asarray(h['c'], float) + d)
    if h.get('fixed'):
        q['loops'] = vs.place(h['loops'], d, 0.0)
    else:
        q.pop('loops', None)
    return q


def _scaled_poly(h, s):
    c = np.asarray(h['c'], float)
    loops = vs.place(vs.place(h['loops'], -c, 0.0), c, 0.0, s)
    return dict(h, loops=loops, fixed=True)


# ---------------------------------------------------------------------------------------------- tryby wypełniania
def generate(p, region, zones=(), cancel=None):
    """Pełne generowanie wzoru w obszarze: tryb wypełniania A-F → otwory, raport, statystyki 2D."""
    p = dict(DEFAULTS, **p)
    fill = p.get('fill', 'A')
    report = []
    if fill == 'B' and not p.get('generator'):
        p = _fill_count(p, region, zones)
    elif fill == 'C' and not p.get('generator'):
        p, note = _fill_max(p, region, zones, cancel)
        report.append(('ok', note))
    elif fill == 'E' and not p.get('generator'):
        p = _fill_centre(p, region, zones)
    elif fill == 'F':
        p = dict(p, edge_mode='adaptive', obstacle_mode='adaptive')
    if fill == 'D':
        p, note = _fill_open(p, region, zones, cancel)
        report.append(('ok' if 'osiągnięto' in note else 'warning', note))
    holes, rep, st = finalize(generate_raw(p, region), p, region, zones)
    report += rep
    return holes, report, st, p


def _count(p, region, zones):
    holes, _r, _s = finalize(generate_raw(p, region), p, region, zones)
    act = [h for h in holes if h['status'] in ('ok', 'adjust') and h.get('role') != 'mount']
    return len(act), act


def _fill_count(p, region, zones):
    """Tryb B: liczba rzędów × kolumn - rozstaw z wymiarów obszaru; całkowita liczba - rozstaw dobrany bisekcją."""
    W = region.hi - region.lo - 2 * float(p['margin'])
    if int(p['rows']) > 0 and int(p['cols']) > 0:
        px = max((W[0] - float(p['w'])) / max(int(p['cols']) - 1, 1), float(p['w']) + float(p['bridge']))
        py = max((W[1] - float(p['h'] or p['w'])) / max(int(p['rows']) - 1, 1), float(p['h'] or p['w']) + float(p['bridge']))
        return dict(p, px=px, py=py, link=False, fill='A')
    N = int(p.get('count') or 0)
    if N <= 0:
        return p
    lo, hi = float(p['w']) + float(p['bridge']), float(np.max(W))
    # start z oszacowania (liczba ~ pole / px²), przedział zawężany, koniec po trafieniu w N albo przy zbieżności
    est = math.sqrt(max(region.area(), 1e-9) / max(N, 1))
    a_, b_ = max(lo, est * .7), min(hi, est * 1.4)
    if a_ < b_:
        na, _x = _count(dict(p, px=a_, py=0.0, link=True), region, zones)
        nb, _x = _count(dict(p, px=b_, py=0.0, link=True), region, zones)
        if na >= N >= nb:
            lo, hi = a_, b_
            if na == N:
                return dict(p, px=a_, py=0.0, link=True)
    for _ in range(30):
        mid = (lo + hi) / 2
        n, _a = _count(dict(p, px=mid, py=0.0, link=True), region, zones)
        if n == N:
            return dict(p, px=mid, py=0.0, link=True)
        if n > N:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-4 * hi:
            break
    return dict(p, px=hi, py=0.0, link=True)


def _fill_max(p, region, zones, cancel=None):
    """Tryb C: najmniejszy dopuszczalny rozstaw (otwór + mostek) i przegląd przesunięć / obrotów siatki - najlepszy
    znaleziony wariant (heurystyka - bez gwarancji maksimum)."""
    base = dict(p, px=0.0, py=0.0)
    best = (-1, base)
    sx = float(p['w']) + float(p['bridge'])
    for lay in ([p['layout']] + (['hexagonal', 'triangular'] if p['layout'] in ('rect', 'square') and p['kind'] in ('circle', 'hex') else [])):
        for ang in (float(p['angle']), float(p['angle']) + 90.0):
            for ox in np.linspace(0, sx, 4, endpoint=False):
                for oy in np.linspace(0, sx, 4, endpoint=False):
                    if cancel is not None and cancel():
                        raise kernel.CadError('Obliczenia przerwane.')
                    q = dict(base, layout=lay, angle=ang, ox=float(p['ox']) + ox, oy=float(p['oy']) + oy)
                    n, _a = _count(q, region, zones)
                    if n > best[0]:
                        best = (n, q)
    return best[1], f'Maksymalne wypełnienie (heurystyka): {best[0]} otworów - najlepszy znaleziony wariant przesunięcia i obrotu siatki.'


def _fill_centre(p, region, zones):
    """Tryb E: wzór symetryczny względem środka obszaru - węzeł albo środek komórki w środku, wybór z większą liczbą."""
    w = float(p['w'])
    px, py = spacing(p, (w, float(p['h'] or w)))
    cands = [dict(p, ox=0.0, oy=0.0), dict(p, ox=px / 2, oy=0.0), dict(p, ox=0.0, oy=py / 2), dict(p, ox=px / 2, oy=py / 2)]
    return max(cands, key=lambda q: _count(q, region, zones)[0])


def _fill_open(p, region, zones, cancel=None):
    """Tryb D: docelowa powierzchnia otwarta [%] - bisekcja wielkości otworów (albo rozstawu) w zadanych granicach."""
    target = float(p['target_open']) / 100.0
    A = region.area()
    adj = p.get('adjust', 'size')
    lo, hi = (float(p['size_min']), float(p['size_max'])) if adj == 'size' else (float(p['w']) + float(p['bridge']), float(p['size_max']) * 4)

    def open_of(v):
        q = dict(p, w=v, h=v * float(p['h'] or p['w']) / float(p['w'])) if adj == 'size' else dict(p, px=v, py=0.0, link=True)
        _n, act = _count(q, region, zones)
        return sum(vs.profile_area(h['loops']) for h in act) / A, q
    best = None
    for _ in range(24):
        if cancel is not None and cancel():
            raise kernel.CadError('Obliczenia przerwane.')
        mid = (lo + hi) / 2
        f, q = open_of(mid)
        if best is None or abs(f - target) < abs(best[0] - target):
            best = (f, q)
        if (f < target) == (adj == 'size'):
            lo = mid
        else:
            hi = mid
    f, q = best
    ok = abs(f - target) <= .01
    return q, (f'Docelowa powierzchnia otwarta {100 * target:.1f} %: osiągnięto {100 * f:.1f} %' if ok else
               f'Docelowa powierzchnia otwarta {100 * target:.1f} % niemożliwa w zadanych granicach - najbliżej {100 * f:.1f} %')
