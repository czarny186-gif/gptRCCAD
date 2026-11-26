"""Generator obudów - etap 9: systemy zamykania podstawy i pokrywy.

Systemy (kilka naraz): śruby montażowe, zatrzaski elastyczne, pokrywa wsuwana, jaskółczy ogon, zawiasy, magnesy,
połączenia wciskane, rowek pod uszczelkę. Każdy system generuje elementy w obu częściach (podstawa / pokrywa) - bryły
dodawane (BRepAlgoAPI_Fuse) i narzędzia tnące (BRepAlgoAPI_Cut), wszystko w układzie przestrzeni elementów (oś podziału i
płaszczyzna z etapu 4), potem przeniesione do świata. Rozmieszczenie automatyczne (narożniki, boki, tylna ścianka) z
ręczną korektą każdego elementu (przesunięcie, włączenie). Kontrole: elementy nie wchodzą w komponenty, części po
złożeniu się nie przenikają (poza zamierzonym wciskiem), otwieranie / wysuwanie / unoszenie pokrywy sprawdzane w
położeniach pośrednich - kontrola próbkowana nie gwarantuje wykrycia wszystkich kolizji podczas ruchu. Program nie
deklaruje wytrzymałości zatrzasków ani szczelności obudowy - wymagają one obliczeń i prób fizycznych.

Zakres: obudowa prostokątna (także z zaokrąglonymi / sfazowanymi narożnikami), podział wzdłuż osi X / Y / Z."""
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


class Frame:
    """Układ podziału w przestrzeni elementów: oś podziału i, osie płaszczyzny a, b; płaszczyzna s; ramki wnętrza i
    zewnętrza; grubości ścianek po stronach; promień / faza wewnętrznych narożników."""

    def __init__(self, env, spec, lay, plane):
        from .enclosure import split_of
        sp = split_of(spec)
        if sp['mode'] not in ('x', 'y', 'z'):
            raise kernel.CadError('System zamykania wymaga podziału wzdłuż osi X, Y albo Z obudowy.')
        if (spec.shape or 'box') not in ('box', 'rounded', 'chamfer'):
            raise kernel.CadError('System zamykania jest dostępny dla obudowy prostokątnej (także z zaokrąglonymi lub sfazowanymi narożnikami).')
        if spec.mode == 'solid':
            raise kernel.CadError('Pełna bryła nie ma wnętrza - system zamykania wymaga obudowy pustej w środku.')
        self.env, self.spec, self.lay = env, spec, lay
        self.i = 'xyz'.index(sp['mode'])
        self.a, self.b = [k for k in range(3) if k != self.i]
        c = np.asarray(env.center, float)
        ax = np.asarray(env.axes, float)
        self.s = float(ax[self.i] @ (np.asarray(plane[0], float) - c))
        self.ilo, self.ihi = (np.asarray(x, float) for x in lay['inner'])
        self.olo, self.ohi = (np.asarray(x, float) for x in lay['outer'])
        self.t_lo, self.t_hi = self.ilo - self.olo, self.ohi - self.ihi
        g = lay.get('g_in') or {}
        self.corner = float(g.get('r', 0.0)) * (1 - 1 / math.sqrt(2)) + float(g.get('c', 0.0)) / 2

    def local(self, a, b, n):
        p = np.zeros(3)
        p[self.a], p[self.b], p[self.i] = a, b, n
        return p

    def world_shape(self, shape):
        import cadquery as cq
        return kernel.transformed(cq.Shape.cast(shape), np.asarray(self.env.axes, float).T, np.asarray(self.env.center, float)).wrapped

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

    def corners(self, inset):
        d = inset + self.corner
        return [(sa, sb, (self.ihi[self.a] - d) if sa > 0 else (self.ilo[self.a] + d), (self.ihi[self.b] - d) if sb > 0 else (self.ilo[self.b] + d))
                for sa in (-1, 1) for sb in (-1, 1)]


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
            n = max(1, int(p['per_side'])) if (t1 - t0) > 3 * p['width'] else 1
            for j in range(n):
                items.append(dict(key=f's{k}{sign:+d}_{j}', side=[k, sign], pos=(j + 1) / (n + 1), enabled=True))
        return items
    if kind == 'hinge':
        k = {'a': fr.a, 'b': fr.b}[p['side'][0]]
        sign = 1 if p['side'][1] == '+' else -1
        n = max(1, int(p['count']))
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
    top = fr.ohi[fr.i]
    lid_inner = fr.ihi[fr.i] - fr.s
    for (sa, sb, ca, cb), it in zip(fr.corners(R * .8), items):
        if not it['enabled']:
            continue
        ca, cb = ca + it['da'], cb + it['db']
        out['base_add'].append(fr.cyl(ca, cb, R, fr.ilo[fr.i] - fr.s - .5 + fr.s, fr.s))
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
        o = fr.b if k == fr.a else fr.a
        t_side = fr.t_hi[k] if sign > 0 else fr.t_lo[k]
        if H + gap >= t_side:
            raise kernel.CadError('Zaczep zatrzasku głębszy niż ścianka - zmniejsz zaczep albo pogrub ściankę.')
        span = (fr.ilo[o], fr.ihi[o])
        c = span[0] + (span[1] - span[0]) * float(it['pos'])
        t0, t1 = c - W / 2, c + W / 2
        if t0 < span[0] + fr.corner + .5 or t1 > span[1] - fr.corner - .5:
            raise kernel.CadError('Zatrzask wychodzi poza ściankę - przesuń go.')
        m_arm = -gap
        # ramię (w pokrywie, wisi w podstawie przy ściance) + mostek do ścianki pokrywy
        out['lid_add'].append(fr.prism([(m_arm - T, -L), (m_arm, -L), (m_arm, 2.0), (m_arm - T, 2.0)], o, t0, t1, k, sign))
        out['lid_add'].append(fr.prism([(m_arm - T, 0.0), (.5, 0.0), (.5, 2.0), (m_arm - T, 2.0)], o, t0, t1, k, sign))
        # zaczep z powierzchnią najazdową (od dołu) i płaskim oparciem (od góry)
        out['lid_add'].append(fr.prism([(m_arm - .01, -L), (m_arm + H, -L + H / ramp), (m_arm + H, -L + H / ramp + Hh), (m_arm - .01, -L + H / ramp + Hh)],
                                       o, t0, t1, k, sign))
        # gniazdo w ściance podstawy (wnęka od środka na zaczep, z luzem)
        out['base_cut'].append(fr.prism([(-1.0, -L - gap), (H + gap, -L - gap), (H + gap, -L + H / ramp + Hh + gap), (-1.0, -L + H / ramp + Hh + gap)],
                                        o, t0 - gap, t1 + gap, k, sign))
        out['flex'].append(fr.prism([(m_arm - T - H - gap, -L), (m_arm - T, -L), (m_arm - T, 0.0), (m_arm - T - H - gap, 0.0)], o, t0, t1, k, sign))
    out['report'].append('Zatrzaski: ramiona ugięte przy montażu - wytrzymałość wymaga obliczeń i prób')


def _slide(fr, p, out, dovetail=False):
    """Pokrywa wsuwana / na jaskółczy ogon: prowadnice (rowki) w ściankach podstawy przedłużonych ponad podział, pokrywa -
    płytka z wypustami; koniec zamknięty - ogranicznik ruchu, koniec otwarty - wsuwanie; luz w rowkach z każdej strony."""
    from .enclosure import _boolean, split_of
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
    out['base_cut'].append(fr.prism(groove, side_axis, fr.ilo[side_axis] - d, fr.ihi[side_axis] + d, axis, closed))     # ogranicznik
    p0, p1 = (fr.ilo[axis] - (d - gap), fr.ohi[axis]) if open_sign > 0 else (fr.olo[axis], fr.ihi[axis] + (d - gap))
    plate = fr.box(*_order(axis, side_axis, fr, (p0, p1) if open_sign > 0 else (p0, p1), (fr.ilo[side_axis] + gap, fr.ihi[side_axis] - gap)),
                   fr.s + gap / 2, fr.s + th - gap / 2)
    t0, t1 = (fr.ilo[axis] + (gap if closed < 0 else 0.0), fr.ohi[axis]) if open_sign > 0 else (fr.olo[axis], fr.ihi[axis] - gap)
    for sign in (-1, 1):
        plate = _boolean('fuse', plate, fr.prism(tongue, axis, t0 - (d - gap) if open_sign > 0 else t0, t1 if open_sign > 0 else t1 + (d - gap),
                                                 side_axis, sign), 'wypust pokrywy')
    plate = _boolean('fuse', plate, fr.prism(tongue, side_axis, fr.ilo[side_axis] + gap, fr.ihi[side_axis] - gap, axis, closed), 'wypust czołowy')
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
    for it in items:
        if not it['enabled']:
            continue
        k, sign = it['side']
        o = fr.b if k == fr.a else fr.a
        span = (fr.ilo[o], fr.ihi[o])
        c = span[0] + (span[1] - span[0]) * float(it['pos'])
        if c - Lh / 2 < fr.olo[o] or c + Lh / 2 > fr.ohi[o]:
            raise kernel.CadError('Zawias wychodzi poza ściankę - przesuń go albo skróć.')
        t_side = fr.t_hi[k] if sign > 0 else fr.t_lo[k]
        m_axis = t_side + R                          # oś zawiasu na zewnątrz ścianki, na wysokości podziału
        axis_pt = np.zeros(3)
        axis_pt[k] = (fr.ihi[k] if sign > 0 else fr.ilo[k]) + sign * m_axis
        axis_pt[fr.i] = fr.s
        for j in range(N):
            a0 = c - Lh / 2 + j * (seg + gap)
            a1 = a0 + seg
            knuckle = fr.cyl_axis(o, axis_pt, R, a0, a1)              # kostki współosiowe (oś wzdłuż ścianki)
            leaf_n = (-R, 0.0) if j % 2 == 0 else (0.0, R)
            leaf = fr.prism([(t_side - .5, leaf_n[0]), (m_axis, leaf_n[0]), (m_axis, leaf_n[1]), (t_side - .5, leaf_n[1])], o, a0, a1, k, sign)
            (out['base_add'] if j % 2 == 0 else out['lid_add']).extend([knuckle, leaf])
        pin_cut = fr.cyl_axis(o, axis_pt, pin / 2, c - Lh / 2 - 1, c + Lh / 2 + 1)
        out['base_cut'].append(pin_cut)
        out['lid_cut'].append(pin_cut)
        # oś obrotu w układzie przestrzeni: punkt i kierunek
        axis_pt = axis_pt.copy()
        axis_pt[o] = c
        d = np.zeros(3)
        d[o] = 1.0
        out['motion'] = ('hinge', axis_pt, d, -sign, float(p['angle']))
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
    tmin = min(fr.t_lo[fr.a], fr.t_hi[fr.a], fr.t_lo[fr.b], fr.t_hi[fr.b])
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
        outer = shapes.solid(shapes.grow(lay['g_in'], a0 + w), lay['P'])
        inner = shapes.solid(shapes.grow(lay['g_in'], a0), lay['P'])
    else:
        outer, inner = _make_box(lo1, hi1), _make_box(lo0, hi0)
    ring = _boolean('cut', outer, inner, 'rowek uszczelki')
    slab = fr.box(fr.olo[fr.a] - 1, fr.ohi[fr.a] + 1, fr.olo[fr.b] - 1, fr.ohi[fr.b] + 1, fr.s - dep, fr.s + .5)
    out['base_cut'].append(_boolean('common', ring, slab, 'rowek uszczelki'))
    out['report'].append(f'Rowek uszczelki {w:g} × {dep:g} mm (ciągły) - szczelność wymaga prób')


def features(env, spec, lay, plane):
    """Elementy wszystkich włączonych systemów: dict(base_add, base_cut, lid_add, lid_cut, flex, replace_lid, motion, report)."""
    fr = Frame(env, spec, lay, plane)
    out = dict(base_add=[], base_cut=[], lid_add=[], lid_cut=[], flex=[], replace_lid=None, motion=None, report=[], interference=False)
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


def apply(env, spec, parts, bodies, lay, plane, check=True):
    """Systemy zamykania dołączone do podstawy i pokrywy (dict 'base' / 'lid', bryły cq w świecie). Zwraca nowe części
    i raport kontroli (lista (poziom, tekst))."""
    from .enclosure import _boolean, _single, _unified, _volume, check_solid
    import cadquery as cq
    fr, f = features(env, spec, lay, plane)
    base, lid = parts['base'].wrapped, parts['lid'].wrapped
    W = fr.world_shape
    if f['replace_lid'] is not None:
        lid = W(f['replace_lid'])
    for s in f['base_add']:
        base = _boolean('fuse', base, W(s), 'element zamknięcia w podstawie')
    for s in f['lid_add']:
        lid = _boolean('fuse', lid, W(s), 'element zamknięcia w pokrywie')
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
    """Kolizje z komponentami, przenikanie części po złożeniu, ruch pokrywy w położeniach pośrednich (próbkowanie)."""
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
    motion = f['motion']
    ax = np.asarray(fr.env.axes, float)
    c = np.asarray(fr.env.center, float)
    lid_sh = cq.Shape.cast(lid.wrapped)
    hit = None
    if motion is not None and motion[0] == 'hinge':
        _k, pt, d, _sgn, angle = motion
        pw, dw = c + ax.T @ pt, ax.T @ d
        for sgn in (1, -1):                           # kierunek otwierania: ten, w którym pokrywa unosi się od podstawy
            probe = lid_sh.rotate(cq.Vector(*pw), cq.Vector(*(pw + dw)), sgn * 10.0)
            if float((probe.Center() - lid_sh.Center()).dot(cq.Vector(*(ax[fr.i])))) > 0:
                break
        for a in np.arange(10.0, float(angle) + 1e-9, 10.0):
            moved = lid_sh.rotate(cq.Vector(*pw), cq.Vector(*(pw + dw)), sgn * a)
            if _volume(_boolean('common', base.wrapped, moved.wrapped, 'otwieranie'))[0] > 1e-3:
                hit = f'przy otwarciu o {a:.0f}°'
                break
    elif motion is not None and motion[0] == 'slide':
        _k, axis, sign, length = motion
        v = ax[axis] * sign
        for frac in (.1, .25, .5, .75, 1.0):
            moved = lid_sh.translate(cq.Vector(*(v * length * frac * 1.05)))
            if _volume(_boolean('common', base.wrapped, moved.wrapped, 'wysuwanie'))[0] > 1e-3:
                hit = f'przy wysunięciu o {length * frac:.0f} mm'
                break
    elif not any(s.get('type') == 'snap' for s in (spec.closure or {}).get('systems', [])):
        v = ax[fr.i]
        for dist in (.5, 1.0, 2.0, 5.0, 10.0):
            moved = lid_sh.translate(cq.Vector(*(v * dist)))
            if _volume(_boolean('common', base.wrapped, moved.wrapped, 'zdejmowanie'))[0] > 1e-3 and not f['interference']:
                hit = f'przy uniesieniu o {dist:g} mm'
                break
    if hit:
        out.append(('error', f'Pokrywa koliduje z podstawą {hit} - obudowy nie da się otworzyć.'))
    elif motion is not None or not f['interference']:
        out.append(('ok', 'Otwieranie sprawdzone w położeniach pośrednich (kontrola próbkowana - nie gwarantuje wykrycia wszystkich kolizji w ruchu).'))
    if any(s.get('type') == 'snap' for s in (spec.closure or {}).get('systems', [])):
        out.append(('warning', 'Zatrzaski: zdejmowanie pokrywy wymaga ugięcia ramion - kontrola ruchu pomija zaczepy; wytrzymałości nie obliczono.'))
    if any(s.get('type') == 'gasket' for s in (spec.closure or {}).get('systems', [])):
        out.append(('warning', 'Rowek uszczelki wygenerowany - szczelność obudowy wymaga doboru uszczelki i prób.'))
    return out
