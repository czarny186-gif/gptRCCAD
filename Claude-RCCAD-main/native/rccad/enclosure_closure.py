"""Generator obudów - etap 9: systemy zamykania podstawy i pokrywy.

Systemy (kilka naraz): śruby montażowe, zatrzaski elastyczne, pokrywa wsuwana, jaskółczy ogon, zawiasy, magnesy,
połączenia wciskane, rowek pod uszczelkę. Każdy system generuje elementy w obu częściach (podstawa / pokrywa) - bryły
dodawane (BRepAlgoAPI_Fuse) i narzędzia tnące (BRepAlgoAPI_Cut), wszystko w układzie przestrzeni elementów (oś podziału i
płaszczyzna z etapu 4), potem przeniesione do świata. Rozmieszczenie automatyczne (narożniki, boki, tylna ścianka) z
ręczną korektą każdego elementu (przesunięcie, włączenie). Kontrole: elementy nie wchodzą w komponenty, części po
złożeniu się nie przenikają (poza zamierzonym wciskiem), otwieranie / wysuwanie / unoszenie pokrywy sprawdzane w sposób
ciągły (rccad.enclosure_check.sweep - postęp według odległości minimalnej, bez pomijania położeń pośrednich). Program nie
deklaruje wytrzymałości zatrzasków ani szczelności obudowy - wymagają one obliczeń i prób fizycznych.

Zakres: wszystkie kształty obudowy (prostokątna, zaokrąglona, sfazowana, cylinder, elipsa, wielokąt, trapez, pulpit,
kontur); podział wzdłuż osi X / Y / Z, płaszczyzną bazową albo ścianą elementu - prostopadły do jednej z osi przestrzeni.
Pokrywa wsuwana i jaskółczy ogon wymagają prostych, równoległych ścianek (obudowa prostokątna)."""
from __future__ import annotations

import math

import numpy as np

from . import kernel

SYSTEMS = ('screw', 'snap', 'slide', 'dovetail', 'hinge', 'magnet', 'press', 'gasket')
LABELS = {'screw': 'Śruby montażowe', 'snap': 'Zatrzaski elastyczne', 'slide': 'Pokrywa wsuwana', 'dovetail': 'Jaskółczy ogon',
          'hinge': 'Zawiasy', 'magnet': 'Magnesy', 'press': 'Połączenia wciskane', 'gasket': 'Rowek pod uszczelkę'}
DEFAULTS = {
    'screw': dict(screw='M3', fastening='pilot', boss=7.0, head=6.0, head_depth=2.0, gap=.2),
    'snap': dict(width=8.0, thickness=1.4, length=8.0, hook=.8, hook_h=1.5, ramp=30.0, gap=.2, per_side=2),
    'slide': dict(axis='a', open='+', depth=1.2, lip=1.0, gap=.2),
    'dovetail': dict(axis='a', open='+', depth=1.4, lip=1.2, angle=20.0, gap=.2),
    'hinge': dict(side='b+', count=2, knuckles=3, diameter=6.0, length=24.0, pin=2.0, gap=.3, angle=100.0),
    'magnet': dict(diameter=6.0, height=3.0, gap=.15, boss=10.0),
    'press': dict(pin=3.0, pin_h=3.0, fit=-.05, boss=7.0),
    'gasket': dict(width=1.5, depth=1.0),
}
CORNER_SYSTEMS = ('screw', 'magnet', 'press')
EPS = 1e-4


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _section(solid, i, s, a, b):
    """Przekrój bryły płaszczyzną (oś i = s) jako wielokąty 2D we współrzędnych (a, b) - największy obrys pierwszy."""
    import cadquery as cq
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
    from OCP.TopTools import TopTools_HSequenceOfShape
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    n, p = np.zeros(3), np.zeros(3)
    n[i], p[i] = 1.0, s
    sec = BRepAlgoAPI_Section(solid, gp_Pln(gp_Pnt(*map(float, p)), gp_Dir(*map(float, n))), False)
    sec.Build()
    if not sec.IsDone():
        raise kernel.CadError('Przekrój obudowy w płaszczyźnie podziału nie powiódł się.')
    edges = TopTools_HSequenceOfShape()
    for e in cq.Shape.cast(sec.Shape()).Edges():
        edges.Append(e.wrapped)
    wires = TopTools_HSequenceOfShape()
    ShapeAnalysis_FreeBounds.ConnectEdgesToWires_s(edges, 1e-5, False, wires)
    polys = []
    for k in range(1, wires.Length() + 1):
        w = cq.Wire(wires.Value(k))
        n_pts = max(64, 8 * len(w.Edges()))
        pts = np.array([w.positionAt(t).toTuple() for t in np.linspace(0, 1, n_pts, endpoint=False)])[:, [a, b]]
        area = .5 * float(np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1]))
        if abs(area) > 1e-6:
            polys.append(pts if area > 0 else pts[::-1])
    if not polys:
        raise kernel.CadError('Płaszczyzna podziału nie przecina wnętrza obudowy.')
    polys.sort(key=lambda q: -abs(.5 * float(np.sum(q[:, 0] * np.roll(q[:, 1], -1) - np.roll(q[:, 0], -1) * q[:, 1]))))
    return polys


def _ray(poly, origin, d):
    """Pierwsze przecięcie promienia z obrysem: (odległość, punkt, normalna zewnętrzna krawędzi)."""
    best = None
    q0, q1 = poly, np.roll(poly, -1, axis=0)
    e = q1 - q0
    den = d[0] * e[:, 1] - d[1] * e[:, 0]
    w = q0 - origin
    with np.errstate(divide='ignore', invalid='ignore'):
        t = (w[:, 0] * e[:, 1] - w[:, 1] * e[:, 0]) / den
        u = (w[:, 0] * d[1] - w[:, 1] * d[0]) / den
    ok = np.isfinite(t) & (t > 1e-9) & (u >= -1e-9) & (u <= 1 + 1e-9)
    if not ok.any():
        return None
    j = int(np.argmin(np.where(ok, t, np.inf)))
    nrm = np.array([e[j, 1], -e[j, 0]])                  # obrys przeciwnie do wskazówek zegara - normalna na zewnątrz
    nrm /= max(float(np.linalg.norm(nrm)), 1e-12)
    return float(t[j]), origin + d * t[j], nrm


class Frame:
    """Układ podziału w przestrzeni elementów: oś podziału i, osie płaszczyzny a, b; płaszczyzna s; ramki wnętrza i
    zewnętrza; grubości ścianek po stronach; promień / faza wewnętrznych narożników.

    Płaszczyzna podziału może być dowolna (osie X / Y / Z, płaszczyzna bazowa, ściana elementu), byle prostopadła do
    jednej z osi przestrzeni elementów; gdy normalna wskazuje przeciwnie do osi, układ jest odwracany (macierz F).
    Kształty inne niż prostopadłościan wyciągnięty wzdłuż osi podziału (cylinder, elipsa, wielokąt, trapez, pulpit,
    kontur, zaokrąglenia w innej osi) - tryb 'profile': przekroje wnętrza i zewnętrza w płaszczyźnie podziału
    (BRepAlgoAPI_Section), elementy rozmieszczane na rzeczywistym obrysie, dodawane bryły przycinane do obrysu
    zewnętrznego obudowy (nigdy nie wystają), krzywizna i pochylenie ścianek sprawdzane dla zatrzasków i zawiasów."""

    def __init__(self, env, spec, lay, plane):
        import cadquery as cq
        if spec.mode == 'solid':
            raise kernel.CadError('Pełna bryła nie ma wnętrza - system zamykania wymaga obudowy pustej w środku.')
        self.env, self.spec, self.lay = env, spec, lay
        ax = np.asarray(env.axes, float)
        c = np.asarray(env.center, float)
        nw = _unit(plane[1])
        dots = ax @ nw
        i = int(np.argmax(np.abs(dots)))
        if abs(abs(dots[i]) - 1.0) > 1e-6:
            raise kernel.CadError('System zamykania wymaga płaszczyzny podziału prostopadłej do osi X, Y albo Z przestrzeni elementów '
                                  '(płaszczyzna bazowa / ściana równoległa do boku obudowy).')
        self.i = i
        self.a, self.b = [k for k in range(3) if k != i]
        F = np.eye(3)
        if dots[i] < 0:                                   # pokrywa po stronie -osi: układ odwrócony (i oraz a), prawoskrętny
            F[i, i] = F[self.a, self.a] = -1.0
        self.F = F
        self.axes = F @ ax
        self.s = float(self.axes[i] @ (np.asarray(plane[0], float) - c))
        fl = lambda lo, hi: (np.minimum(F @ lo, F @ hi), np.maximum(F @ lo, F @ hi))
        self.ilo, self.ihi = fl(*(np.asarray(x, float) for x in lay['inner']))
        self.olo, self.ohi = fl(*(np.asarray(x, float) for x in lay['outer']))
        g = lay.get('g_in') or {}
        self.kind = 'box'
        self.S_in = self.S_out = None
        if g and (g.get('t') != 'rrect' or int(np.argmax(np.abs(np.asarray(lay['P'], float)[2]))) != i):
            from . import enclosure_shapes as shapes
            self.kind = 'profile'
            to_f = lambda sh: kernel.transformed(cq.Shape.cast(sh), F, np.zeros(3)).wrapped
            self.S_in = to_f(shapes.solid(g, lay['P']))
            self.S_out = to_f(shapes.solid(lay['g_out'], lay['P']))
            self._sec = {}
            self.sec_in = self.section(self.S_in, self.s)
            self.sec_out = self.section(self.S_out, self.s)
            for k, poly, lo, hi in ((self.a, self.sec_in, self.ilo, self.ihi), (self.b, self.sec_in, self.ilo, self.ihi),
                                    (self.a, self.sec_out, self.olo, self.ohi), (self.b, self.sec_out, self.olo, self.ohi)):
                col = 0 if k == self.a else 1
                lo[k], hi[k] = float(poly[:, col].min()), float(poly[:, col].max())
        self.t_lo, self.t_hi = self.ilo - self.olo, self.ohi - self.ihi
        self.corner = float(g.get('r', 0.0)) * (1 - 1 / math.sqrt(2)) + float(g.get('c', 0.0)) / 2 if self.kind == 'box' else 0.0
        self.tmin = float(lay.get('tmin', min(self.t_lo[self.a], self.t_hi[self.a], self.t_lo[self.b], self.t_hi[self.b])))

    # ---------------------------------------------------------------- przekroje (tryb 'profile')
    def section(self, solid, height):
        key = (id(solid), round(float(height), 6))
        if key not in self._sec:
            self._sec[key] = _section(solid, self.i, height, self.a, self.b)[0]
        return self._sec[key]

    def extreme(self, k, sign):
        """Punkt obrysu wnętrza najdalej w kierunku k·znak (współrzędne a, b)."""
        poly = self.sec_in
        col = 0 if k == self.a else 1
        j = int(np.argmax(poly[:, col] * sign))
        return poly[j]

    def top_at(self, a, b):
        """Zewnętrzna powierzchnia obudowy nad punktem (a, b) wzdłuż osi podziału (pochyła góra, krzywizna)."""
        if self.kind == 'box':
            return float(self.ohi[self.i])
        from .enclosure_posts import wall_hit_exit
        p = self.local(a, b, self.s + .01)
        d = np.zeros(3)
        d[self.i] = 1.0
        dist = wall_hit_exit(self.S_out, p, d)
        if dist is None:
            raise kernel.CadError('Element zamknięcia poza obrysem pokrywy - przesuń go.')
        return float(self.s + .01 + dist)

    def clip(self, shape):
        """Dodawana bryła przycięta do obrysu zewnętrznego (tryb 'profile') - słupki i zaczepy nie wystają z obudowy."""
        if self.kind == 'box':
            return shape
        from .enclosure import _boolean
        return _boolean('common', shape, self.S_out, 'przycięcie do obrysu')

    def local(self, a, b, n):
        p = np.zeros(3)
        p[self.a], p[self.b], p[self.i] = a, b, n
        return p

    def world_shape(self, shape):
        import cadquery as cq
        return kernel.transformed(cq.Shape.cast(shape), self.axes.T, np.asarray(self.env.center, float)).wrapped

    def frame_shape(self, env_shape):
        """Bryła w układzie przestrzeni elementów → układ ramki (odwrócenie F)."""
        import cadquery as cq
        return kernel.transformed(cq.Shape.cast(env_shape), self.F, np.zeros(3)).wrapped

    def box(self, a0, a1, b0, b1, n0, n1):
        from .enclosure import _make_box
        lo, hi = self.local(min(a0, a1), min(b0, b1), min(n0, n1)), self.local(max(a0, a1), max(b0, b1), max(n0, n1))
        if float((hi - lo).min()) <= 1e-6:
            raise kernel.CadError('Element systemu zamykania ma zerowy wymiar - sprawdź parametry.')
        return _make_box(lo, hi)

    def cyl(self, a, b, r, n0, n1):
        """Walec o osi wzdłuż osi podziału: środek (a, b), od n0 do n1 (współrzędne przestrzeni)."""
        return self.cyl_axis(self.i, self.local(a, b, n0), r, 0.0, n1 - n0)

    def cyl_axis(self, axis, point, r, t0, t1):
        """Walec o osi równoległej do osi przestrzeni `axis`, przez punkt `point`, od t0 do t1 wzdłuż tej osi."""
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
        from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
        if r <= 1e-6 or t1 - t0 <= 1e-6:
            raise kernel.CadError('Element systemu zamykania ma zerowy wymiar - sprawdź parametry.')
        d = np.zeros(3)
        d[axis] = 1.0
        base = np.asarray(point, float) + d * t0
        mk = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*map(float, base)), gp_Dir(*map(float, d))), float(r), float(t1 - t0))
        mk.Build()
        return mk.Shape()

    def prism(self, pts_tn, axis, t0, t1, side_k, side_sign):
        """Graniastosłup z wielokąta w płaszczyźnie (m, n) ścianki (m - od wewnętrznej powierzchni ścianki na zewnątrz,
        n - wzdłuż osi podziału od płaszczyzny), wyciągnięty wzdłuż osi stycznej od t0 do t1."""
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
        from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
        from OCP.gp import gp_Pnt, gp_Vec
        surf = self.ihi[side_k] if side_sign > 0 else self.ilo[side_k]
        poly = BRepBuilderAPI_MakePolygon()
        for m, n in pts_tn:
            p = np.zeros(3)
            p[side_k] = surf + side_sign * m
            p[self.i] = self.s + n
            p[axis] = t0
            poly.Add(gp_Pnt(*map(float, p)))
        poly.Close()
        face = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
        v = np.zeros(3)
        v[axis] = t1 - t0
        return BRepPrimAPI_MakePrism(face, gp_Vec(*map(float, v))).Shape()

    def sides(self):
        """Ściany boczne przy płaszczyźnie podziału: (oś k, znak, oś styczna, zakres stycznej, grubość)."""
        out = []
        for k, o in ((self.a, self.b), (self.b, self.a)):
            for sign in (-1, 1):
                t = self.t_hi[k] if sign > 0 else self.t_lo[k]
                out.append((k, sign, o, (self.ilo[o], self.ihi[o]), float(t)))
        return out

    # ---------------------------------------------------------------- miejsca na ściance (zatrzaski, zawiasy)
    def anchor(self, k, sign, pos, width, depth=0.0, what='elementu', outer=False):
        """Miejsce elementu na ściance po stronie k·znak: punkt q na wewnętrznym obrysie (a, b), normalna na zewnątrz n,
        styczna t, grubość ścianki wzdłuż n, odejście obrysu `sag` na szerokości elementu. Prostopadłościan - ściana
        boczna jak dotąd (ułamek pos jej długości); tryb 'profile' - najdłuższy prosty odcinek obrysu zwrócony w tę
        stronę (np. bok wielokąta), a gdy go brak (cylinder, elipsa) - skrajny punkt obrysu z normalną krzywej. Ścianka
        musi być pionowa (równoległa do osi podziału) na głębokości `depth` - pochyłe boki trapezu / pulpitu są odrzucane."""
        ca, cb = (0, 1) if k == self.a else (1, 0)
        if self.kind == 'box':
            o = self.b if k == self.a else self.a
            span = (self.ilo[o], self.ihi[o])
            c = span[0] + (span[1] - span[0]) * float(pos)
            if c - width / 2 < span[0] + self.corner + .5 or c + width / 2 > span[1] - self.corner - .5:
                if not outer or c - width / 2 < self.olo[o] or c + width / 2 > self.ohi[o]:
                    raise kernel.CadError(f'Element {what} wychodzi poza ściankę - przesuń go albo zmniejsz.')
            q = np.zeros(2)
            q[ca] = self.ihi[k] if sign > 0 else self.ilo[k]
            q[cb] = c
            n = np.zeros(2)
            n[ca] = sign
            t = np.zeros(2)
            t[cb] = 1.0
            return dict(q=q, n=n, t=t, thick=float(self.t_hi[k] if sign > 0 else self.t_lo[k]), sag=0.0, half=width / 2)
        want = np.zeros(2)
        want[ca] = sign
        poly = self.sec_in
        seg = self._straight(poly, want, width)
        if seg is not None:
            q0, q1 = seg
            t = _unit(q1 - q0)
            n = np.array([t[1], -t[0]])
            length = float(np.linalg.norm(q1 - q0))
            q = (q0 + q1) / 2 + t * (float(pos) - .5) * max(0.0, length - width - 1.0)
        else:
            j = int(np.argmax(poly @ want))
            q = poly[j]
            t = _unit(poly[(j + 1) % len(poly)] - poly[j - 1])
            n = np.array([t[1], -t[0]])
            span = float(np.ptp(poly @ t))
            q = q + t * (float(pos) - .5) * span * .5
            hit = _ray(poly, q - n * 20.0, n)                    # rzut przesuniętego punktu z powrotem na obrys
            if hit is None:
                raise kernel.CadError(f'Nie znaleziono miejsca na element {what} na ściance.')
            q = hit[1]
        hit_out = _ray(self.sec_out, q + n * 1e-6, n)
        if hit_out is None:
            raise kernel.CadError(f'Nie znaleziono zewnętrznej powierzchni ścianki dla elementu {what}.')
        thick = float(hit_out[0])
        sag = 0.0
        if not outer:                                           # pionowość i krzywizna ścianki na wysokości elementu
            for dz in sorted({0.3, max(.3, depth * .5), max(.3, depth)}):
                sec = self.section(self.S_in, self.s - dz)
                for tt in np.linspace(-width / 2, width / 2, 7):
                    hit = _ray(sec, q + t * tt - n * 20.0, n)
                    if hit is None:
                        self._reject(what)
                    sag = max(sag, abs(20.0 - hit[0]))
            if sag > 1e-6:                                      # obrys wypukły: element odsunięty do środka o odejście,
                q = q - n * sag                                 # żeby jego końce nie wchodziły w ściankę
                thick += sag
        return dict(q=q, n=n, t=t, thick=thick, sag=float(sag), half=width / 2)

    def _reject(self, what):
        raise kernel.CadError(f'Ścianka w miejscu {what} jest pochyła albo za krótka - wybierz inną stronę albo inny system.')

    @staticmethod
    def _straight(poly, want, width):
        """Najdłuższy prosty odcinek obrysu (kolejne krawędzie współliniowe) z normalną zewnętrzną zwróconą w stronę `want`
        (cos > 0,8) i długością co najmniej szerokość + 1 mm."""
        e = np.roll(poly, -1, axis=0) - poly
        lens = np.linalg.norm(e, axis=1)
        dirs = e / np.maximum(lens, 1e-12)[:, None]
        best, i, nseg = None, 0, len(poly)
        visited = 0
        start = 0
        for j in range(nseg):                                   # zacznij od załamania, żeby nie dzielić odcinka na końcu listy
            if float(dirs[j] @ dirs[j - 1]) < .99995:
                start = j
                break
        j = start
        while visited < nseg:
            a0, length, d = poly[j], lens[j], dirs[j]
            jj = (j + 1) % nseg
            visited += 1
            while visited < nseg and float(dirs[jj] @ d) > .99995:
                length += lens[jj]
                jj = (jj + 1) % nseg
                visited += 1
            n = np.array([d[1], -d[0]])
            if float(n @ want) > .8 and length >= width + 1.0 and (best is None or length > best[0]):
                best = (length, a0, poly[jj])
            j = jj
        return None if best is None else (best[1], best[2])

    def wall_point(self, an, m, n_up, tt):
        q = an['q'] + an['n'] * m + an['t'] * tt
        return self.local(q[0], q[1], self.s + n_up)

    def wall_dir(self, an):
        d = np.zeros(3)
        d[self.a], d[self.b] = an['t'][0], an['t'][1]
        return d

    def prism_at(self, an, pts_mn, t0, t1):
        """Graniastosłup z wielokąta (m - od wewnętrznej powierzchni ścianki na zewnątrz wzdłuż normalnej, n - wzdłuż osi
        podziału od płaszczyzny) wyciągnięty wzdłuż stycznej ścianki od t0 do t1 (względem punktu miejsca)."""
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
        from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
        from OCP.gp import gp_Pnt, gp_Vec
        poly = BRepBuilderAPI_MakePolygon()
        for m, n in pts_mn:
            poly.Add(gp_Pnt(*map(float, self.wall_point(an, m, n, t0))))
        poly.Close()
        face = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
        v = self.wall_dir(an) * (t1 - t0)
        return BRepPrimAPI_MakePrism(face, gp_Vec(*map(float, v))).Shape()

    def cyl_dir(self, point, d, r, t0, t1):
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
        from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
        if r <= 1e-6 or t1 - t0 <= 1e-6:
            raise kernel.CadError('Element systemu zamykania ma zerowy wymiar - sprawdź parametry.')
        d = _unit(d)
        base = np.asarray(point, float) + d * t0
        mk = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*map(float, base)), gp_Dir(*map(float, d))), float(r), float(t1 - t0))
        mk.Build()
        return mk.Shape()

    def outer_sag(self, an, t0, t1, height):
        """Odejście zewnętrznej powierzchni ścianki od płaszczyzny stycznej w miejscu na odcinku [t0, t1] (skrzydełko zawiasu)."""
        if self.kind == 'box':
            return 0.0
        sec = self.section(self.S_out, height)
        worst = 0.0
        for tt in np.linspace(t0, t1, 7):
            ref = an['q'] + an['t'] * tt + an['n'] * an['thick']
            hit = _ray(sec, ref - an['n'] * 20.0, an['n'])
            if hit is None:
                return math.inf
            worst = max(worst, abs(hit[0] - 20.0))
        return worst

    def corners(self, inset):
        if self.kind == 'box':
            d = inset + self.corner
            return [(sa, sb, (self.ihi[self.a] - d) if sa > 0 else (self.ilo[self.a] + d), (self.ihi[self.b] - d) if sb > 0 else (self.ilo[self.b] + d))
                    for sa in (-1, 1) for sb in (-1, 1)]
        poly = self.sec_in                             # promień od środka obrysu w stronę narożnika ramki, środek elementu
        centre = poly.mean(axis=0)                     # odsunięty od trafionej krawędzi o inset wzdłuż jej normalnej
        half = np.array([self.ihi[self.a] - self.ilo[self.a], self.ihi[self.b] - self.ilo[self.b]]) / 2
        out = []
        for sa in (-1, 1):
            for sb in (-1, 1):
                d = _unit(np.array([sa * half[0], sb * half[1]]))
                hit = _ray(poly, centre, d)
                if hit is None:
                    raise kernel.CadError('Nie udało się znaleźć miejsca na element zamknięcia w obrysie obudowy.')
                _t, q, nrm = hit
                p = q - nrm * (inset + self.corner)
                out.append((sa, sb, float(p[0]), float(p[1])))
        return out


def params(system):
    p = dict(DEFAULTS[system['type']])
    p.update(system.get('params') or {})
    return p


def auto_items(fr, system):
    """Automatyczne rozmieszczenie: narożniki (śruby, magnesy, kołki), boki (zatrzaski), tylna ścianka (zawiasy)."""
    kind = system['type']
    p = params(system)
    if kind in CORNER_SYSTEMS:
        return [dict(key=f'c{sa:+d}{sb:+d}', da=0.0, db=0.0, enabled=True) for sa, sb, _a, _b in fr.corners(0)]
    if kind == 'snap':
        items = []
        for k, sign, o, (t0, t1), _t in fr.sides():
            n = max(1, int(p['per_side'])) if (t1 - t0) > 3 * p['width'] and fr.kind == 'box' else 1
            if fr.kind == 'profile':                 # tylko ścianki pionowe i dość proste (pochyłe boki trapezu - pominięte)
                try:
                    an = fr.anchor(k, sign, .5, float(p['width']), depth=float(p['length']) + float(p['hook_h']) + 1.0)
                    if an['sag'] > .35 * float(p['hook']):
                        continue
                except kernel.CadError:
                    continue
            for j in range(n):
                items.append(dict(key=f's{k}{sign:+d}_{j}', side=[k, sign], pos=(j + 1) / (n + 1), enabled=True))
        return items
    if kind == 'hinge':
        k = {'a': fr.a, 'b': fr.b}[p['side'][0]]
        sign = 1 if p['side'][1] == '+' else -1
        n = max(1, int(p['count']))
        if fr.kind == 'profile':                     # zakrzywiona ścianka: osie kilku zawiasów nie byłyby współliniowe
            want = np.zeros(2)
            want[0 if k == fr.a else 1] = sign
            if fr._straight(fr.sec_in, want, n * float(p['length']) + (n - 1) * 2.0) is None:
                n = 1
        return [dict(key=f'h{j}', side=[k, sign], pos=(j + 1) / (n + 1), enabled=True) for j in range(n)]
    return []


def items_of(fr, system):
    """Elementy systemu: zapisane (z ręczną korektą) albo rozmieszczone automatycznie."""
    auto = auto_items(fr, system)
    saved = {it['key']: it for it in system.get('items') or []}
    return [dict(it, **{k: v for k, v in saved.get(it['key'], {}).items() if k in ('da', 'db', 'pos', 'enabled')}) for it in auto]


# ---------------------------------------------------------------------------------------------- systemy
def _screws(fr, p, items, out):
    from .enclosure_posts import screw
    s = screw(p['screw'])
    R = float(p['boss']) / 2
    hole = {'pilot': s['pilot'], 'insert': s['insert'], 'nut': s['clear']}.get(p['fastening'], s['pilot'])
    if R <= hole / 2 + .4 or R <= s['clear'] / 2 + .4:
        raise kernel.CadError('Słupek śruby za cienki dla otworu - zwiększ średnicę słupka.')
    head = max(float(p['head']), s['clear'] + .4) + 2 * float(p['gap'])
    lid_inner = fr.ihi[fr.i] - fr.s
    for (sa, sb, ca, cb), it in zip(fr.corners(R * .8), items):
        if not it['enabled']:
            continue
        ca, cb = ca + it['da'], cb + it['db']
        top = fr.top_at(ca, cb)                    # zewnętrzna powierzchnia pokrywy nad śrubą (także pochyła / zakrzywiona)
        out['base_add'].append(fr.cyl(ca, cb, R, fr.ilo[fr.i] - .5, fr.s))
        if lid_inner > .2:
            out['lid_add'].append(fr.cyl(ca, cb, R, fr.s, fr.ihi[fr.i] + .5))
        depth = s['insert_len'] + 1 if p['fastening'] == 'insert' else min(fr.s - fr.ilo[fr.i] - .5, max(6.0, 2.5 * s['d']))
        out['base_cut'].append(fr.cyl(ca, cb, hole / 2, fr.s - depth, fr.s + .5))
        if p['fastening'] == 'nut':
            from .enclosure_posts import _hex
            import cadquery as cq
            nut = cq.Shape.cast(_hex(s['nut_af'] + 2 * p['gap'], 0.0, s['nut_h'] + p['gap']))
            m = np.eye(3)[[fr.a, fr.b, fr.i]].T
            pos = fr.local(ca, cb, fr.s - depth - s['nut_h'] - .2)
            out['base_cut'].append(kernel.transformed(nut, m, pos).wrapped)
        out['lid_cut'].append(fr.cyl(ca, cb, (s['clear'] + max(0.0, float(p['gap']) - .2)) / 2, fr.s - .5, top + 1))
        out['lid_cut'].append(fr.cyl(ca, cb, head / 2, top - float(p['head_depth']), top + 1))
        out['report'].append(f'Śruba {p["screw"]} ({ {"pilot": "wkręt", "insert": "insert", "nut": "nakrętka"}[p["fastening"]] })')


def _snaps(fr, p, items, out):
    W, T, L, H, Hh, gap = (float(p[k]) for k in ('width', 'thickness', 'length', 'hook', 'hook_h', 'gap'))
    if min(W, T, L, H, Hh) <= 0:
        raise kernel.CadError('Wymiary zatrzasku muszą być większe od zera.')
    if L + 1 > fr.s - fr.ilo[fr.i]:
        raise kernel.CadError('Ramię zatrzasku jest dłuższe niż wysokość podstawy - skróć ramię albo przesuń podział.')
    ramp = math.tan(math.radians(max(5.0, min(75.0, float(p['ramp'])))))
    for it in items:
        if not it['enabled']:
            continue
        k, sign = it['side']
        an = fr.anchor(k, sign, it['pos'], W, depth=L + Hh + 1.0, what='zatrzasku')
        t_side, sag = an['thick'], an['sag']
        if sag > .35 * H:
            raise kernel.CadError('Ścianka w miejscu zatrzasku jest zbyt zakrzywiona albo pochyła - zmniejsz szerokość zatrzasku, '
                                  'przesuń go albo wybierz śruby / magnesy.')
        if H + gap + sag >= t_side:
            raise kernel.CadError('Zaczep zatrzasku głębszy niż ścianka - zmniejsz zaczep albo pogrub ściankę.')
        t0, t1 = -W / 2, W / 2
        m_arm = -gap
        P = lambda pts, a0=t0, a1=t1: fr.prism_at(an, pts, a0, a1)
        # ramię (w pokrywie, wisi w podstawie przy ściance) + mostek do ścianki pokrywy
        out['lid_add'].append(P([(m_arm - T, -L), (m_arm, -L), (m_arm, 2.0), (m_arm - T, 2.0)]))
        out['lid_add'].append(P([(m_arm - T, 0.0), (.5 + sag, 0.0), (.5 + sag, 2.0), (m_arm - T, 2.0)]))
        # zaczep z powierzchnią najazdową (od dołu) i płaskim oparciem (od góry)
        out['lid_add'].append(P([(m_arm - .01, -L), (m_arm + H, -L + H / ramp), (m_arm + H, -L + H / ramp + Hh), (m_arm - .01, -L + H / ramp + Hh)]))
        # gniazdo w ściance podstawy (wnęka od środka na zaczep, z luzem; na ściance zakrzywionej - pogłębione o odejście)
        out['base_cut'].append(P([(-1.0, -L - gap), (H + gap + sag, -L - gap), (H + gap + sag, -L + H / ramp + Hh + gap), (-1.0, -L + H / ramp + Hh + gap)],
                                 t0 - gap, t1 + gap))
        out['flex'].append(P([(m_arm - T - H - gap, -L), (m_arm - T, -L), (m_arm - T, 0.0), (m_arm - T - H - gap, 0.0)]))
    out['report'].append('Zatrzaski: ramiona ugięte przy montażu - wytrzymałość wymaga obliczeń i prób')


def _slide(fr, p, out, dovetail=False):
    """Pokrywa wsuwana / na jaskółczy ogon: prowadnice (rowki) w ściankach podstawy przedłużonych ponad podział, pokrywa -
    płytka z wypustami; koniec zamknięty - ogranicznik ruchu, koniec otwarty - wsuwanie; luz w rowkach z każdej strony."""
    from .enclosure import _boolean, split_of
    if fr.kind != 'box':
        raise kernel.CadError('Pokrywa wsuwana i jaskółczy ogon wymagają prostych, równoległych ścianek prowadnic - '
                              'wybierz obudowę prostokątną (także zaokrągloną / sfazowaną) albo inny system zamykania.')
    if split_of(fr.spec)['joint'] != 'flat':
        raise kernel.CadError('Pokrywa wsuwana wymaga płaskiego połączenia podziału (bez zakładki i pióra).')
    axis = fr.a if p['axis'] == 'a' else fr.b
    side_axis = fr.b if axis == fr.a else fr.a
    open_sign = 1 if p['open'] == '+' else -1
    closed = -open_sign
    d, lip, gap = float(p['depth']), float(p['lip']), float(p['gap'])
    if d <= gap or lip <= 0:
        raise kernel.CadError('Rowek prowadnicy musi być głębszy niż luz, a listwa nad pokrywą - grubsza od zera.')
    th = float(fr.ohi[fr.i] - fr.ihi[fr.i]) if fr.spec.mode != 'open' else 2.0
    if abs(fr.s - fr.ihi[fr.i]) > 1e-3:
        raise kernel.CadError('Pokrywa wsuwana: ustaw podział na wewnętrznej powierzchni górnej ścianki - pokrywa jest płytką.')
    for k, sign in ((side_axis, -1), (side_axis, 1), (axis, closed)):
        if d + .6 > (fr.t_hi[k] if sign > 0 else fr.t_lo[k]):
            raise kernel.CadError('Rowek prowadnicy za głęboki dla ścianki (zostaw co najmniej 0,6 mm).')
    dl = d * math.tan(math.radians(float(p.get('angle', 0.0)))) if dovetail else 0.0
    kk = (d - gap) / d
    groove = [(-1.0, -gap / 2), (0.0, -gap / 2), (d, -gap / 2 - dl), (d, th + gap / 2 + dl), (0.0, th + gap / 2), (-1.0, th + gap / 2)]
    tongue = [(-gap - .05, gap / 2), (d - gap, gap / 2 - dl * kk), (d - gap, th - gap / 2 + dl * kk), (-gap - .05, th - gap / 2)]
    # koniec zamknięty: wypust wysuwa się z rowka w kierunku jego głębokości - profil prosty (jaskółczy ogon by go zablokował)
    groove_end = [(-1.0, -gap / 2), (d, -gap / 2), (d, th + gap / 2), (-1.0, th + gap / 2)]
    tongue_end = [(-gap - .05, gap / 2), (d - gap, gap / 2), (d - gap, th - gap / 2), (-gap - .05, th - gap / 2)]
    top = th + lip
    side_lo, side_hi = fr.olo[side_axis], fr.ohi[side_axis]
    for sign in (-1, 1):                                  # przedłużone ścianki boczne (na całej długości)
        w0, w1 = (fr.olo[side_axis], fr.ilo[side_axis]) if sign < 0 else (fr.ihi[side_axis], fr.ohi[side_axis])
        out['base_add'].append(fr.box(*_order(axis, side_axis, fr, (fr.olo[axis], fr.ohi[axis]), (w0, w1)), fr.s - .5, fr.s + top))
    e0, e1 = (fr.olo[axis], fr.ilo[axis]) if closed < 0 else (fr.ihi[axis], fr.ohi[axis])
    out['base_add'].append(fr.box(*_order(axis, side_axis, fr, (e0, e1), (side_lo, side_hi)), fr.s - .5, fr.s + top))   # koniec zamknięty
    r0, r1 = (fr.ilo[axis] - d, fr.ohi[axis] + 1.0) if open_sign > 0 else (fr.olo[axis] - 1.0, fr.ihi[axis] + d)
    for sign in (-1, 1):
        out['base_cut'].append(fr.prism(groove, axis, r0, r1, side_axis, sign))
    out['base_cut'].append(fr.prism(groove_end, side_axis, fr.ilo[side_axis] - d, fr.ihi[side_axis] + d, axis, closed))     # ogranicznik
    p0, p1 = (fr.ilo[axis] - (d - gap), fr.ohi[axis]) if open_sign > 0 else (fr.olo[axis], fr.ihi[axis] + (d - gap))
    plate = fr.box(*_order(axis, side_axis, fr, (p0, p1) if open_sign > 0 else (p0, p1), (fr.ilo[side_axis] + gap, fr.ihi[side_axis] - gap)),
                   fr.s + gap / 2, fr.s + th - gap / 2)
    t0, t1 = (fr.ilo[axis] + (gap if closed < 0 else 0.0), fr.ohi[axis]) if open_sign > 0 else (fr.olo[axis], fr.ihi[axis] - gap)
    for sign in (-1, 1):
        plate = _boolean('fuse', plate, fr.prism(tongue, axis, t0 - (d - gap) if open_sign > 0 else t0, t1 if open_sign > 0 else t1 + (d - gap),
                                                 side_axis, sign), 'wypust pokrywy')
    plate = _boolean('fuse', plate, fr.prism(tongue_end, side_axis, fr.ilo[side_axis] + gap, fr.ihi[side_axis] - gap, axis, closed), 'wypust czołowy')
    out['replace_lid'] = plate
    out['motion'] = ('slide', axis, open_sign, float(fr.ohi[axis] - fr.olo[axis]))
    out['report'].append(('Jaskółczy ogon' if dovetail else 'Pokrywa wsuwana') + ' - koniec zamknięty ogranicza ruch, luz w rowkach ' + f'{gap:g} mm')


def _order(axis, side_axis, fr, r_axis, r_side):
    """Zakresy (a0, a1, b0, b1) dla fr.box z zakresów wzdłuż osi prowadnicy i osi bocznej."""
    if axis == fr.a:
        return r_axis[0], r_axis[1], r_side[0], r_side[1]
    return r_side[0], r_side[1], r_axis[0], r_axis[1]


def _hinges(fr, p, items, out):
    D, Lh, pin, gap = float(p['diameter']), float(p['length']), float(p['pin']), float(p['gap'])
    N = max(2, int(p['knuckles']))
    R = D / 2
    if pin >= D - .8:
        raise kernel.CadError('Sworzeń zawiasu za gruby dla kostek zawiasu.')
    seg = (Lh - (N - 1) * gap) / N
    if seg <= .8:
        raise kernel.CadError('Zawias za krótki dla tylu kostek.')
    placed = []
    for it in items:
        if not it['enabled']:
            continue
        k, sign = it['side']
        an = fr.anchor(k, sign, it['pos'], Lh, depth=R, what='zawiasu', outer=True)
        for other in placed:                         # wszystkie zawiasy na jednej osi i bez nakładania
            off = an['q'] - other['q']
            if abs(float(an['t'] @ other['t'])) < 1 - 1e-6 or abs(float(off @ np.array([-other['t'][1], other['t'][0]]))) > 1e-4:
                raise kernel.CadError('Osie zawiasów nie są współliniowe (zakrzywiona ścianka) - zostaw jeden zawias.')
            if abs(float(off @ other['t'])) < Lh + gap:
                raise kernel.CadError('Zawiasy nachodzą na siebie - rozsuń je albo skróć.')
        placed.append(an)
        t_side = an['thick']
        m_axis = t_side + R                          # oś zawiasu na zewnątrz ścianki, na wysokości podziału
        axis_pt = fr.wall_point(an, m_axis, 0.0, 0.0)
        tdir = fr.wall_dir(an)
        for j in range(N):
            a0 = -Lh / 2 + j * (seg + gap)
            a1 = a0 + seg
            knuckle = fr.cyl_dir(axis_pt, tdir, R, a0, a1)             # kostki współosiowe (oś wzdłuż ścianki)
            leaf_n = (-R, 0.0) if j % 2 == 0 else (0.0, R)
            sag = fr.outer_sag(an, a0, a1, fr.s + (leaf_n[0] + leaf_n[1]) / 2)
            if not math.isfinite(sag) or sag > t_side + R:
                raise kernel.CadError('Ścianka w miejscu zawiasu jest zbyt zakrzywiona - skróć zawias albo przesuń go.')
            m0 = t_side - .5 - sag                         # skrzydełko sięga do ścianki także tam, gdzie się ona zakrzywia
            leaf = fr.prism_at(an, [(m0, leaf_n[0]), (m_axis, leaf_n[0]), (m_axis, leaf_n[1]), (m0, leaf_n[1])], a0, a1)
            if fr.kind != 'box':
                from .enclosure import _boolean
                leaf = _boolean('cut', leaf, fr.S_in, 'skrzydełko zawiasu')     # bez wchodzenia do wnętrza
            (out['base_raw'] if j % 2 == 0 else out['lid_raw']).extend([knuckle, leaf])      # na zewnątrz - bez przycinania
        pin_cut = fr.cyl_dir(axis_pt, tdir, pin / 2, -Lh / 2 - 1, Lh / 2 + 1)
        out['base_cut'].append(pin_cut)
        out['lid_cut'].append(pin_cut)
        out['motion'] = ('hinge', axis_pt, tdir, -sign, float(p['angle']))         # oś obrotu w układzie ramki
    out['report'].append(f'Zawiasy: sworzeń Ø{pin:g} mm (otwór współosiowy w kostkach obu części)')


def _pockets(fr, p, items, out, kind):
    if kind == 'magnet':
        d, h, gap, B = float(p['diameter']), float(p['height']), float(p['gap']), float(p['boss'])
        if B <= d + 1.0:
            raise kernel.CadError('Słupek magnesu za cienki dla gniazda.')
    else:
        d, h, fit, B = float(p['pin']), float(p['pin_h']), float(p['fit']), float(p['boss'])
        if B <= d + 1.0:
            raise kernel.CadError('Słupek kołka za cienki.')
    R = B / 2
    for (sa, sb, ca, cb), it in zip(fr.corners(R * .8), items):
        if not it['enabled']:
            continue
        ca, cb = ca + it['da'], cb + it['db']
        out['base_add'].append(fr.cyl(ca, cb, R, fr.ilo[fr.i] - .5, fr.s))
        if fr.ihi[fr.i] - fr.s > .2:
            out['lid_add'].append(fr.cyl(ca, cb, R, fr.s, fr.ihi[fr.i] + .5))
        if kind == 'magnet':
            out['base_cut'].append(fr.cyl(ca, cb, (d + 2 * gap) / 2, fr.s - h - gap, fr.s + .01))
            out['lid_cut'].append(fr.cyl(ca, cb, (d + 2 * gap) / 2, fr.s - .01, fr.s + h + gap))
        else:
            out['lid_add'].append(fr.cyl(ca, cb, d / 2, fr.s - h, fr.s + .5))
            out['base_cut'].append(fr.cyl(ca, cb, (d + fit) / 2, fr.s - h - .3, fr.s + .01))
            if fit < 0:
                out['interference'] = True
    out['report'].append('Magnesy: gniazda w obu częściach' if kind == 'magnet' else f'Połączenia wciskane: wcisk {-min(0.0, fit):g} mm')


def _gasket(fr, p, out, lay):
    from .enclosure import _boolean, _make_box
    w, dep = float(p['width']), float(p['depth'])
    tmin = min(fr.t_lo[fr.a], fr.t_hi[fr.a], fr.t_lo[fr.b], fr.t_hi[fr.b], fr.tmin)
    if w + 1.0 > tmin:
        raise kernel.CadError(f'Rowek uszczelki szerokości {w:g} mm nie mieści się w ściance {tmin:g} mm (min. 0,5 mm z każdej strony).')
    if dep >= fr.s - fr.ilo[fr.i]:
        raise kernel.CadError('Rowek uszczelki za głęboki.')
    a0 = (tmin - w) / 2
    grow = lambda g: (fr.ilo - g, fr.ihi + g)
    lo1, hi1 = grow(a0 + w)
    lo0, hi0 = grow(a0)
    if 'g_in' in lay:
        from . import enclosure_shapes as shapes
        outer = fr.frame_shape(shapes.solid(shapes.grow(lay['g_in'], a0 + w), lay['P']))
        inner = fr.frame_shape(shapes.solid(shapes.grow(lay['g_in'], a0), lay['P']))
    else:
        outer, inner = _make_box(lo1, hi1), _make_box(lo0, hi0)
    ring = _boolean('cut', outer, inner, 'rowek uszczelki')
    slab = fr.box(fr.olo[fr.a] - 1, fr.ohi[fr.a] + 1, fr.olo[fr.b] - 1, fr.ohi[fr.b] + 1, fr.s - dep, fr.s + .5)
    out['base_cut'].append(_boolean('common', ring, slab, 'rowek uszczelki'))
    out['report'].append(f'Rowek uszczelki {w:g} × {dep:g} mm (ciągły) - szczelność wymaga prób')


def features(env, spec, lay, plane):
    """Elementy wszystkich włączonych systemów: dict(base_add, base_cut, lid_add, lid_cut, flex, replace_lid, motion, report)."""
    fr = Frame(env, spec, lay, plane)
    out = dict(base_add=[], base_cut=[], lid_add=[], lid_cut=[], base_raw=[], lid_raw=[], flex=[], replace_lid=None, motion=None, report=[],
               interference=False)
    systems = [s for s in (spec.closure or {}).get('systems', []) if s.get('enabled', True)]
    kinds = [s['type'] for s in systems]
    if 'slide' in kinds and 'dovetail' in kinds:
        raise kernel.CadError('Pokrywa wsuwana i jaskółczy ogon wykluczają się - wybierz jedno.')
    if ('slide' in kinds or 'dovetail' in kinds) and 'hinge' in kinds:
        raise kernel.CadError('Pokrywa wsuwana nie może mieć zawiasów.')
    for s in systems:
        if s['type'] not in SYSTEMS:
            raise kernel.CadError('Nieznany system zamykania.')
        p = params(s)
        items = items_of(fr, s)
        if s['type'] == 'screw':
            _screws(fr, p, items, out)
        elif s['type'] == 'snap':
            _snaps(fr, p, items, out)
        elif s['type'] in ('slide', 'dovetail'):
            _slide(fr, p, out, dovetail=s['type'] == 'dovetail')
        elif s['type'] == 'hinge':
            _hinges(fr, p, items, out)
        elif s['type'] in ('magnet', 'press'):
            _pockets(fr, p, items, out, s['type'])
        elif s['type'] == 'gasket':
            _gasket(fr, p, out, lay)
    return fr, out


def apply(env, spec, parts, bodies, lay, plane, check=True, seat=None):
    """Systemy zamykania dołączone do podstawy i pokrywy (dict 'base' / 'lid', bryły cq w świecie). Zwraca nowe części
    i raport kontroli (lista (poziom, tekst)). seat - gniazdo połączenia podziału (świat): słupki dodane do podstawy
    nie mogą go wypełnić, bo wchodzi w nie występ pokrywy."""
    from .enclosure import _boolean, _single, _unified, _volume, check_solid
    import cadquery as cq
    fr, f = features(env, spec, lay, plane)
    base, lid = parts['base'].wrapped, parts['lid'].wrapped
    W = fr.world_shape
    if f['replace_lid'] is not None:
        lid = W(f['replace_lid'])
    for s in f['base_add']:
        base = _boolean('fuse', base, W(fr.clip(s)), 'element zamknięcia w podstawie')
    for s in f['lid_add']:
        lid = _boolean('fuse', lid, W(fr.clip(s)), 'element zamknięcia w pokrywie')
    for s in f['base_raw']:
        base = _boolean('fuse', base, W(s), 'element zamknięcia w podstawie')
    for s in f['lid_raw']:
        lid = _boolean('fuse', lid, W(s), 'element zamknięcia w pokrywie')
    if seat is not None and (f['base_add'] or f['base_raw']):
        base = _boolean('cut', base, seat.wrapped if hasattr(seat, 'wrapped') else seat, 'gniazdo połączenia przy słupkach')
    for s in f['base_cut']:
        base = _boolean('cut', base, W(s), 'gniazdo zamknięcia w podstawie')
    for s in f['lid_cut']:
        lid = _boolean('cut', lid, W(s), 'gniazdo zamknięcia w pokrywie')
    base = check_solid(_single(_unified(base), 'Podstawa z zamknięciem'))
    lid = check_solid(_single(_unified(lid), 'Pokrywa z zamknięciem'))
    report = [('info', r) for r in f['report']]
    if check:
        report += checks(fr, f, base, lid, spec, bodies)
        errors = [t for lvl, t in report if lvl == 'error']
        if errors:
            raise kernel.CadError(errors[0])
    return {'base': base, 'lid': lid}, report


def checks(fr, f, base, lid, spec, bodies):
    """Kolizje z komponentami, przenikanie części po złożeniu, ruch pokrywy na całej drodze (kontrola ciągła)."""
    from .enclosure import _boolean, _volume
    import cadquery as cq
    out = []
    by_id = {b.id: b for b in bodies or []}
    for part, name in ((base, 'podstawa'), (lid, 'pokrywa')):
        for src in spec.sources:
            b = by_id.get(src.id)
            if b is None or b.kind != 'solid':
                continue
            if _volume(_boolean('common', part.wrapped, b.shape.wrapped, 'kolizja z elementem'))[0] > 1e-4:
                out.append(('error', f'Element zamknięcia ({name}) koliduje z elementem „{b.name}”.'))
    for s in f['flex']:
        for src in spec.sources:
            b = by_id.get(src.id)
            if b is not None and b.kind == 'solid' and _volume(_boolean('common', fr.world_shape(s), b.shape.wrapped, 'miejsce na ugięcie'))[0] > 1e-4:
                out.append(('error', f'Ramię zatrzasku nie ma miejsca na ugięcie - przeszkadza „{b.name}”.'))
    overlap = _volume(_boolean('common', base.wrapped, lid.wrapped, 'złożenie'))[0]
    if overlap > 1e-3:
        if f['interference']:
            out.append(('warning', f'Wcisk kołków: części nachodzą na siebie o {overlap:.3f} mm³ (zamierzony wcisk).'))
        else:
            out.append(('error', f'Po złożeniu podstawa i pokrywa przenikają się ({overlap:.3f} mm³) - sprawdź elementy zamknięcia.'))
    from .enclosure_check import _motion, sweep, MIN_STEP, ROT_STEP
    hit = None
    motion = None
    if f['motion'] is not None or not any(s.get('type') == 'snap' for s in (spec.closure or {}).get('systems', [])):
        plane = (fr.local(0, 0, fr.s), fr.axes[fr.i])
        motion = _motion(fr.env, spec, f, {'lid': lid.wrapped}, fr.lay, (np.asarray(fr.env.center) + fr.axes.T @ plane[0], plane[1]), fr)
    if motion is not None and not (f['interference'] and f['motion'] is None):
        fn, total, speed, label, xf, axis = motion
        found = sweep(base.wrapped, fn, total, speed, label, xf, axis)
        hit = found[0] if found else None
    if hit:
        out.append(('error', f'Pokrywa koliduje z podstawą {hit} - obudowy nie da się otworzyć.'))
    elif motion is not None:
        out.append(('ok', f'Otwieranie sprawdzone na całej drodze ruchu (odcinki bez możliwości kolizji pomijane z gwarancją, '
                          f'przy styku ramek ścian - co {MIN_STEP:g} mm przesunięcia / {ROT_STEP:g} mm lub 1° obrotu).'))
    if any(s.get('type') == 'snap' for s in (spec.closure or {}).get('systems', [])):
        out.append(('warning', 'Zatrzaski: zdejmowanie pokrywy wymaga ugięcia ramion - kontrola ruchu pomija zaczepy; wytrzymałości nie obliczono.'))
    if any(s.get('type') == 'gasket' for s in (spec.closure or {}).get('systems', [])):
        out.append(('warning', 'Rowek uszczelki wygenerowany - szczelność obudowy wymaga doboru uszczelki i prób.'))
    return out
