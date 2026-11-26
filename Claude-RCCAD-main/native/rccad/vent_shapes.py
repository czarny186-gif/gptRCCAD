"""Wentylacja - kształty pojedynczych otworów (PatternGenerator).

Profil otworu to lista pętli (pierwsza zewnętrzna, kolejne - otwory wewnętrzne), każda pętla to ciąg segmentów
w lokalnym układzie otworu (środek w 0, bez obrotu):
  ('L', p0, p1)            odcinek
  ('A', p0, pm, p1)        łuk przez trzy punkty
  ('C', c, r)              pełny okrąg
  ('E', c, a, b)           pełna elipsa (półosie wzdłuż X i Y)
  ('S', pts)               zamknięta krzywa B-spline przez punkty (okresowa)
Z segmentów powstają: dokładny profil OCC (krawędzie analityczne / B-spline w płaszczyźnie) oraz obrys wielokątny do
kontroli 2D (nakładanie, mostki, marginesy, pole). Kształty nie zależą od rozmieszczenia (vent_layout)."""
from __future__ import annotations

import math

import numpy as np

from . import kernel

SHAPES = ('circle', 'square', 'rect', 'rrect', 'tri', 'tri_ratio', 'rhombus', 'trapezoid', 'pentagon', 'hex', 'octagon', 'ngon',
          'ellipse', 'capsule', 'bean', 'cross', 'star', 'drop', 'halfcircle', 'lens', 'quatrefoil', 'crescent', 'irregular', 'custom')
SHAPE_LABELS = {'circle': 'Okrąg', 'square': 'Kwadrat', 'rect': 'Prostokąt', 'rrect': 'Prostokąt zaokrąglony', 'tri': 'Trójkąt równoboczny',
                'tri_ratio': 'Trójkąt (proporcje)', 'rhombus': 'Romb', 'trapezoid': 'Trapez', 'pentagon': 'Pięciokąt', 'hex': 'Sześciokąt',
                'octagon': 'Ośmiokąt', 'ngon': 'Wielokąt foremny', 'ellipse': 'Elipsa', 'capsule': 'Kapsuła / szczelina zaokrąglona',
                'bean': 'Fasolka', 'cross': 'Krzyż', 'star': 'Gwiazda', 'drop': 'Kropla', 'halfcircle': 'Półokrąg', 'lens': 'Liść (soczewka)',
                'quatrefoil': 'Czteroliść (arabeska)', 'crescent': 'Łuska (sierp)', 'irregular': 'Wielokąt nieregularny', 'custom': 'Własny kształt'}
# parametry używane przez kształt (okno pokazuje tylko te)
SHAPE_PARAMS = {'circle': ('w',), 'square': ('w', 'corner'), 'rect': ('w', 'h', 'corner'), 'rrect': ('w', 'h', 'corner'), 'tri': ('w', 'corner'),
                'tri_ratio': ('w', 'h', 'corner'), 'rhombus': ('w', 'h', 'corner'), 'trapezoid': ('w', 'h', 'ratio', 'corner'),
                'pentagon': ('w', 'corner'), 'hex': ('w', 'corner'), 'octagon': ('w', 'corner'), 'ngon': ('w', 'sides', 'corner'),
                'ellipse': ('w', 'h'), 'capsule': ('w', 'h'), 'bean': ('w', 'h', 'bend'), 'cross': ('w', 'h', 'arm', 'corner'),
                'star': ('w', 'arms', 'ratio', 'corner'), 'drop': ('w', 'h'), 'halfcircle': ('w',), 'lens': ('w', 'h'),
                'quatrefoil': ('w',), 'crescent': ('w', 'ratio'), 'irregular': ('w', 'sides', 'irregularity'), 'custom': ('w',)}


def _rot(p, a):
    c, s = math.cos(a), math.sin(a)
    p = np.asarray(p, float)
    return np.array([c * p[..., 0] - s * p[..., 1], s * p[..., 0] + c * p[..., 1]]).T if p.ndim > 1 else np.array([c * p[0] - s * p[1], s * p[0] + c * p[1]])


def _poly(pts):
    pts = [np.asarray(q, float) for q in pts]
    return [('L', pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]


def _arc_mid(c, r, a0, a1):
    am = (a0 + a1) / 2
    return np.asarray(c, float) + r * np.array([math.cos(am), math.sin(am)])


def rounded(pts, r):
    """Wielokąt z zaokrąglonymi narożnikami promieniem r (odcinki + łuki styczne); r ograniczony do połowy krótszego boku."""
    pts = [np.asarray(q, float) for q in pts]
    n = len(pts)
    if r <= 1e-9:
        return _poly(pts)
    if _area(np.array(pts)) < 0:
        pts = pts[::-1]
    corners = []
    for i in range(n):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        d1, d2 = _unit(a - b), _unit(c - b)
        ang = math.acos(max(-1.0, min(1.0, float(d1 @ d2))))
        if ang < 1e-6 or abs(ang - math.pi) < 1e-6:
            corners.append((b, b, b, 0.0))
            continue
        L = min(np.linalg.norm(a - b), np.linalg.norm(c - b)) / 2
        t = min(r / math.tan(ang / 2), L * .999)
        rr = t * math.tan(ang / 2)
        p1, p2 = b + d1 * t, b + d2 * t
        bis = _unit(d1 + d2)
        centre = b + bis * (rr / math.sin(ang / 2))
        mid = centre - bis * rr
        corners.append((p1, mid, p2, rr))
    segs = []
    for i in range(n):
        p1, mid, p2, rr = corners[i]
        if rr > 0:
            segs.append(('A', p1, mid, p2))
        nxt = corners[(i + 1) % n][0]
        if np.linalg.norm(nxt - p2) > 1e-9:
            segs.append(('L', p2, nxt))
    return segs


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _area(poly):
    x, y = poly[:, 0], poly[:, 1]
    return .5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def regular(n, R, phase=None):
    phase = (math.pi / 2 - math.pi / n) if phase is None else phase
    return [R * np.array([math.cos(phase + 2 * math.pi * k / n), math.sin(phase + 2 * math.pi * k / n)]) for k in range(n)]


def profile(kind, w, h=None, p=None):
    """Profil otworu: lista pętli segmentów (zob. opis modułu). w, h - wymiary [mm]; p - parametry kształtu."""
    p = p or {}
    w = float(w)
    h = float(h if h not in (None, 0) else w)
    if w <= 1e-6 or h <= 1e-6:
        raise kernel.CadError('Wymiary otworu muszą być dodatnie.')
    r = max(0.0, float(p.get('corner', 0.0)))
    if kind == 'circle':
        return [[('C', np.zeros(2), w / 2)]]
    if kind == 'ellipse':
        return [[('E', np.zeros(2), w / 2, h / 2)]]
    if kind in ('square', 'rect', 'rrect'):
        hh = w if kind == 'square' else h
        pts = [(-w / 2, -hh / 2), (w / 2, -hh / 2), (w / 2, hh / 2), (-w / 2, hh / 2)]
        return [rounded(pts, r)]
    if kind == 'tri':
        return [rounded(regular(3, w / math.sqrt(3)), r)]
    if kind == 'tri_ratio':
        return [rounded([(-w / 2, -h / 3), (w / 2, -h / 3), (0, 2 * h / 3)], r)]
    if kind == 'rhombus':
        return [rounded([(0, -h / 2), (w / 2, 0), (0, h / 2), (-w / 2, 0)], r)]
    if kind == 'trapezoid':
        t = w * min(1.0, max(.05, float(p.get('ratio', .6))))
        return [rounded([(-w / 2, -h / 2), (w / 2, -h / 2), (t / 2, h / 2), (-t / 2, h / 2)], r)]
    if kind in ('pentagon', 'hex', 'octagon', 'ngon'):
        n = {'pentagon': 5, 'hex': 6, 'octagon': 8}.get(kind, max(3, int(p.get('sides', 6))))
        R = (w / 2) / math.cos(math.pi / n)                              # w - rozwartość między bokami
        return [rounded(regular(n, R, 0.0 if n % 2 == 0 else None), r)]
    if kind == 'capsule':
        a, b = max(w, h), min(w, h)
        rr = b / 2
        if a - b < 1e-9:
            return [[('C', np.zeros(2), rr)]]
        L = (a - b) / 2
        segs = [('L', np.array([-L, -rr]), np.array([L, -rr])), ('A', np.array([L, -rr]), np.array([L + rr, 0.0]), np.array([L, rr])),
                ('L', np.array([L, rr]), np.array([-L, rr])), ('A', np.array([-L, rr]), np.array([-L - rr, 0.0]), np.array([-L, -rr]))]
        if h > w:
            segs = [(s[0], *[_rot(q, math.pi / 2) for q in s[1:]]) for s in segs]
        return [segs]
    if kind == 'bean':                                                  # kapsuła wygięta po łuku (długość w, grubość h)
        bend = min(170.0, max(5.0, float(p.get('bend', 60.0))))
        th = math.radians(bend)
        if w <= h:
            return [[('C', np.zeros(2), w / 2)]]
        Rc = (w - h) / 2 / math.sin(th / 2)
        c = np.array([0.0, -Rc * math.cos(th / 2)])
        ro, ri = Rc + h / 2, Rc - h / 2
        if ri <= 1e-3:
            raise kernel.CadError('Fasolka: za duże wygięcie dla tej grubości.')
        a0, a1 = math.pi / 2 - th / 2, math.pi / 2 + th / 2
        P = lambda R_, a: c + R_ * np.array([math.cos(a), math.sin(a)])
        e0, e1 = P(Rc, a0), P(Rc, a1)
        cap1 = e1 + h / 2 * np.array([-math.sin(a1), math.cos(a1)])
        cap0 = e0 + h / 2 * np.array([math.sin(a0), -math.cos(a0)])
        segs = [('A', P(ro, a0), _arc_mid(c, ro, a0, a1), P(ro, a1)), ('A', P(ro, a1), cap1, P(ri, a1)),
                ('A', P(ri, a1), _arc_mid(c, ri, a0, a1), P(ri, a0)), ('A', P(ri, a0), cap0, P(ro, a0))]
        return [segs]
    if kind == 'cross':
        aw = w * min(.95, max(.05, float(p.get('arm', .3))))
        ah = h * min(.95, max(.05, float(p.get('arm', .3))))
        X, Y = w / 2, h / 2
        pts = [(-aw / 2, -Y), (aw / 2, -Y), (aw / 2, -ah / 2), (X, -ah / 2), (X, ah / 2), (aw / 2, ah / 2), (aw / 2, Y), (-aw / 2, Y),
               (-aw / 2, ah / 2), (-X, ah / 2), (-X, -ah / 2), (-aw / 2, -ah / 2)]
        return [rounded(pts, r)]
    if kind == 'star':
        n = max(3, int(p.get('arms', 5)))
        Ro, Ri = w / 2, w / 2 * min(.95, max(.1, float(p.get('ratio', .45))))
        pts = [(Ro if k % 2 == 0 else Ri) * np.array([math.cos(math.pi / 2 + math.pi * k / n), math.sin(math.pi / 2 + math.pi * k / n)]) for k in range(2 * n)]
        return [rounded(pts, r)]
    if kind == 'drop':                                                  # kropla: okrąg (średnica w) i ostrze na wysokości h
        rr = w / 2
        H = max(h, w * 1.25)                                            # ostrze dalej niż średnica
        c = np.array([0.0, rr - H / 2])
        tip = c + np.array([0.0, H - rr])
        d = float(np.linalg.norm(tip - c))
        al = math.acos(rr / d)
        base = math.atan2(*(tip - c)[::-1])
        t1 = c + rr * np.array([math.cos(base + al), math.sin(base + al)])
        t2 = c + rr * np.array([math.cos(base - al), math.sin(base - al)])
        bottom = c + rr * np.array([math.cos(base + math.pi), math.sin(base + math.pi)])
        return [[('L', t2, tip), ('L', tip, t1), ('A', t1, bottom, t2)]]
    if kind == 'halfcircle':
        rr = w / 2
        return [[('L', np.array([-rr, 0.0]), np.array([rr, 0.0])), ('A', np.array([rr, 0.0]), np.array([0.0, rr]), np.array([-rr, 0.0]))]]
    if kind == 'lens':                                                  # soczewka z dwóch łuków (liść)
        a, b = w / 2, h / 2
        if b > a:
            a, b = b, a
        p0, p1 = np.array([-a, 0.0]), np.array([a, 0.0])
        segs = [('A', p0, np.array([0.0, -b]), p1), ('A', p1, np.array([0.0, b]), p0)]
        if h > w:
            segs = [(s[0], *[_rot(q, math.pi / 2) for q in s[1:]]) for s in segs]
        return [segs]
    if kind == 'quatrefoil':                                            # cztery koła na krzyż (arabeska)
        rr = w / 2 / 1.7
        d = .7 * rr
        xi = (d + math.sqrt(2 * rr * rr - d * d)) / 2                     # przecięcia sąsiednich kół na przekątnych
        segs = []
        for k in range(4):
            R_ = lambda q: _rot(np.asarray(q, float), k * math.pi / 2)
            segs.append(('A', R_((xi, -xi)), R_((d + rr, 0.0)), R_((xi, xi))))
        return [segs]
    if kind == 'crescent':                                              # łuska: koło minus przesunięte koło (sierp)
        R = w / 2
        off = 2 * R * min(.9, max(.1, float(p.get('ratio', .5))))
        yy = off / 2
        hx = math.sqrt(max(R * R - yy * yy, 1e-12))
        A, B = np.array([-hx, yy]), np.array([hx, yy])
        return [[('A', A, np.array([0.0, -R]), B), ('A', B, np.array([0.0, off - R]), A)]]
    if kind == 'irregular':
        n = max(3, int(p.get('sides', 6)))
        rng = np.random.default_rng(int(p.get('seed', 1)))
        irr = min(.9, max(0.0, float(p.get('irregularity', .4))))
        angs = np.sort(rng.uniform(0, 2 * math.pi, n)) if irr > 0 else np.linspace(0, 2 * math.pi, n, endpoint=False)
        angs = (1 - irr) * np.linspace(0, 2 * math.pi, n, endpoint=False) + irr * angs
        rad = w / 2 * (1 - irr * .5 * rng.random(n))
        pts = [rad[k] * np.array([math.cos(angs[k]), math.sin(angs[k])]) for k in range(n)]
        hull = _hull(np.array(pts))
        return [rounded(list(hull), r)]
    if kind == 'custom':
        loops = p.get('loops')
        if not loops:
            raise kernel.CadError('Własny kształt nie ma konturów - wskaż szkic albo wczytaj plik.')
        return scale_custom(loops, w, p)
    raise kernel.CadError(f'Nieznany kształt otworu: {kind}.')


def _cap_mid(c, a, Rc, h, sgn):
    """Środek półokrągłego zakończenia fasolki na końcu łuku (kąt a)."""
    e = c + Rc * np.array([math.cos(a), math.sin(a)])
    t = np.array([-math.sin(a), math.cos(a)]) * sgn
    return e + t * h / 2


def _hull(P):
    P = P[np.lexsort((P[:, 1], P[:, 0]))]

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (p[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])) <= 1e-12:
                out.pop()
            out.append(p)
        return out
    lo, hi = half(list(P)), half(list(P[::-1]))
    return lo[:-1] + hi[:-1]


def scale_custom(loops, w, p):
    """Własny kształt (pętle punktów albo segmentów ze szkicu / pliku) przeskalowany tak, by większy wymiar ramki = w,
    z punktem bazowym (środek ramki albo zapisany) i kierunkiem odniesienia (obrót)."""
    pts = np.vstack([np.asarray(sample_loop(lp, 64), float) for lp in loops])
    lo, hi = pts.min(0), pts.max(0)
    base = np.asarray(p.get('base') or (lo + hi) / 2, float)
    size = float(max(hi - lo)) or 1.0
    k = float(w) / size if p.get('fit', True) else 1.0
    ang = math.radians(float(p.get('ref_angle', 0.0)))
    out = []
    for lp in loops:
        segs = []
        for s in lp:
            f = lambda q: _rot((np.asarray(q, float) - base) * k, -ang)
            if s[0] == 'L':
                segs.append(('L', f(s[1]), f(s[2])))
            elif s[0] == 'A':
                segs.append(('A', f(s[1]), f(s[2]), f(s[3])))
            elif s[0] == 'C':
                segs.append(('C', f(s[1]), float(s[2]) * k))
            elif s[0] == 'E':
                segs.append(('S', [f(q) for q in sample_loop([s], 48)]))
            else:
                segs.append(('S', [f(q) for q in s[1]]))
        out.append(segs)
    return out


# ---------------------------------------------------------------------------------------------- obrys 2D
def sample_loop(segs, n=24):
    """Obrys pętli jako wielokąt (punkty bez powtórzenia pierwszego)."""
    out = []
    for s in segs:
        k = s[0]
        if k == 'L':
            out.append(np.asarray(s[1], float))
        elif k == 'A':
            out += _arc_points(s[1], s[2], s[3], max(4, n // 3))[:-1]
        elif k == 'C':
            c, r = np.asarray(s[1], float), float(s[2])
            m = max(12, n)
            out += [c + r * np.array([math.cos(t), math.sin(t)]) for t in np.linspace(0, 2 * math.pi, m, endpoint=False)]
        elif k == 'E':
            c, a, b = np.asarray(s[1], float), float(s[2]), float(s[3])
            m = max(12, n)
            out += [c + np.array([a * math.cos(t), b * math.sin(t)]) for t in np.linspace(0, 2 * math.pi, m, endpoint=False)]
        else:
            out += [np.asarray(q, float) for q in s[1]]
    return np.array(out, float)


def _arc_points(p0, pm, p1, n):
    p0, pm, p1 = (np.asarray(q, float) for q in (p0, pm, p1))
    c = _circumcentre(p0, pm, p1)
    if c is None:
        return [p0 + (p1 - p0) * t for t in np.linspace(0, 1, n)]
    r = float(np.linalg.norm(p0 - c))
    a0, am, a1 = (math.atan2(*(q - c)[::-1]) for q in (p0, pm, p1))
    # kierunek przez punkt środkowy
    def norm(a):
        return a % (2 * math.pi)
    d = norm(a1 - a0)
    if norm(am - a0) > d:
        d = d - 2 * math.pi
    return [c + r * np.array([math.cos(a0 + d * t), math.sin(a0 + d * t)]) for t in np.linspace(0, 1, n)]


def _circumcentre(a, b, c):
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-14:
        return None
    ux = ((a @ a) * (b[1] - c[1]) + (b @ b) * (c[1] - a[1]) + (c @ c) * (a[1] - b[1])) / d
    uy = ((a @ a) * (c[0] - b[0]) + (b @ b) * (a[0] - c[0]) + (c @ c) * (b[0] - a[0])) / d
    return np.array([ux, uy])


def outline(loops, n=24):
    """Obrysy wszystkich pętli profilu [wielokąt zewnętrzny, otwory...]."""
    return [sample_loop(lp, n) for lp in loops]


def place(loops, centre, angle, scale=1.0):
    """Profil przesunięty do środka i obrócony (kąt w radianach)."""
    c = np.asarray(centre, float)
    out = []
    for lp in loops:
        segs = []
        for s in lp:
            f = lambda q: c + _rot(np.asarray(q, float) * scale, angle)
            if s[0] == 'L':
                segs.append(('L', f(s[1]), f(s[2])))
            elif s[0] == 'A':
                segs.append(('A', f(s[1]), f(s[2]), f(s[3])))
            elif s[0] == 'C':
                segs.append(('C', f(s[1]), float(s[2]) * scale))
            elif s[0] == 'E':
                if abs(angle) < 1e-12:
                    segs.append(('E', f(s[1]), float(s[2]) * scale, float(s[3]) * scale))
                else:
                    segs.append(('S', [f(q) for q in sample_loop([s], 48)]))
            else:
                segs.append(('S', [f(q) for q in s[1]]))
        out.append(segs)
    return out


def loop_area(segs):
    return abs(_area(sample_loop(segs, 96)))


def profile_area(loops):
    """Pole profilu (zewnętrzna pętla minus otwory) z gęstego obrysu."""
    if not loops:
        return 0.0
    return loop_area(loops[0]) - sum(loop_area(lp) for lp in loops[1:])


# ---------------------------------------------------------------------------------------------- profil OCC
def _reverse(segs):
    out = []
    for s in reversed(segs):
        if s[0] == 'L':
            out.append(('L', s[2], s[1]))
        elif s[0] == 'A':
            out.append(('A', s[3], s[2], s[1]))
        elif s[0] == 'S':
            out.append(('S', list(reversed(list(s[1])))))
        else:
            out.append(s)
    return out


def oriented(loops):
    """Pętle profilu uporządkowane: zewnętrzna (największa) przeciwnie do ruchu wskazówek, otwory zgodnie z nim."""
    if not loops:
        return loops
    areas = [_area(sample_loop(lp, 24)) for lp in loops]
    order = sorted(range(len(loops)), key=lambda i: -abs(areas[i]))
    out = []
    for n, i in enumerate(order):
        lp, a = loops[i], areas[i]
        if (n == 0 and a < 0) or (n > 0 and a > 0):
            lp = _reverse(lp)
        out.append(lp)
    return out


def occ_face(loops, to3d, plane=None):
    """Ściana OCC profilu: to3d(xy) → punkt 3D (płaszczyzna ścianki albo styczna). Łuki i okręgi analityczne,
    krzywe - B-spline przez punkty. plane - (origin, normal) dla MakeFace (ściana płaska)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.GC import GC_MakeArcOfCircle, GC_MakeCircle, GC_MakeSegment
    from OCP.GeomAPI import GeomAPI_Interpolate
    from OCP.TColgp import TColgp_HArray1OfPnt
    from OCP.gp import gp_Ax2, gp_Dir, gp_Elips, gp_Pln, gp_Pnt
    P = lambda q: gp_Pnt(*map(float, to3d(q)))
    wires = []
    loops = oriented(loops)
    for lp in loops:
        mw = BRepBuilderAPI_MakeWire()
        for s in lp:
            k = s[0]
            if k == 'L':
                if np.linalg.norm(np.asarray(s[2]) - np.asarray(s[1])) < 1e-9:
                    continue
                mw.Add(BRepBuilderAPI_MakeEdge(GC_MakeSegment(P(s[1]), P(s[2])).Value()).Edge())
            elif k == 'A':
                mw.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(P(s[1]), P(s[2]), P(s[3])).Value()).Edge())
            elif k == 'C':
                c, r = np.asarray(s[1], float), float(s[2])
                a, b, d = P(c + [r, 0]), P(c + [0, r]), P(c + [-r, 0])
                mw.Add(BRepBuilderAPI_MakeEdge(GC_MakeCircle(a, b, d).Value()).Edge())
            elif k == 'E':
                c, a, b = np.asarray(s[1], float), float(s[2]), float(s[3])
                o = np.asarray(to3d(c), float)
                xa = _unit(np.asarray(to3d(c + [1.0, 0]), float) - o)
                ya = _unit(np.asarray(to3d(c + [0, 1.0]), float) - o)
                n = _unit(np.cross(xa, ya))
                major, minor, ax = (a, b, xa) if a >= b else (b, a, ya)
                el = gp_Elips(gp_Ax2(gp_Pnt(*map(float, o)), gp_Dir(*map(float, n)), gp_Dir(*map(float, ax))), float(major), float(minor))
                mw.Add(BRepBuilderAPI_MakeEdge(el).Edge())
            else:
                pts = [np.asarray(q, float) for q in s[1]]
                arr = TColgp_HArray1OfPnt(1, len(pts))
                for i, q in enumerate(pts):
                    arr.SetValue(i + 1, P(q))
                it = GeomAPI_Interpolate(arr, True, 1e-7)
                it.Perform()
                if not it.IsDone():
                    raise kernel.CadError('Nie udało się zbudować krzywej profilu otworu.')
                mw.Add(BRepBuilderAPI_MakeEdge(it.Curve()).Edge())
        if not mw.IsDone():
            raise kernel.CadError('Kontur otworu nie jest zamknięty.')
        wires.append(mw.Wire())
    if plane is not None:
        o, n = plane
        mf = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(*map(float, o)), gp_Dir(*map(float, n))), wires[0], True)
    else:
        mf = BRepBuilderAPI_MakeFace(wires[0], True)
    for w_ in wires[1:]:
        mf.Add(w_)
    if not mf.IsDone():
        raise kernel.CadError('Nie udało się zbudować profilu otworu.')
    from OCP.ShapeFix import ShapeFix_Face
    fx = ShapeFix_Face(mf.Face())
    fx.FixOrientation()
    fx.Perform()
    return fx.Face()
