"""Generator obudów - etap 17: mocowania zewnętrzne.

Mocowanie na wskazanej zewnętrznej płaskiej powierzchni części obudowy (układ: punkt, normalna na zewnątrz, osie u, v).
Rodzaje: uchwyt ścienny z otworami, kołnierz montażowy, ucho montażowe, otwory kluczowe (płyta z gniazdem łba),
otwory podłużne, uchwyt narożny, zaczep na szynę DIN (TH35-7,5 / TH35-15 wg IEC/EN 60715: szerokość 35, prześwit 27,
wysokość 7,5 / 15, blacha 1 mm - wartości edytowalne), mocowanie VESA (MIS-D 75 × 75 / 100 × 100, wkręty M4 - edytowalne),
nóżki, gniazda na gumowe nóżki, klips do paska, uchwyt pod opaskę zaciskową, obejma do rury / profilu, według szkicu.

Każdy rodzaj to profil parametryczny w układzie powierzchni wyciągnięty (BRepPrimAPI_MakePrism) albo walce, z
zaokrągleniami narożników (MakeFillet2d na profilu) i operacjami Boolean; otwory: okrągłe, podłużne, kluczowe, z
pogłębieniem pod łeb. Rozmieszczenie: pojedyncze, dwa symetryczne, cztery narożne, szyk liniowy, szyk prostokątny,
ręczne (lista punktów), według wskazanych punktów - każde z przesunięciem i obrotem.
Wynik: część integralna (Fuse z częścią obudowy), osobna bryła albo element odłączany (osobna bryła + współpracujące
otwory w obudowie). Kontrole: kolizje z komponentami, pokrywą i elementami zamknięcia (Common), miejsce na łeb śruby i
narzędzie (walec dostępu wolny od obudowy), otwory ślepe nie przebijają ścianki (zostaje minimalny materiał)."""
from __future__ import annotations

import math

import numpy as np

from . import kernel
from . import enclosure_holes as eh

KINDS = ('wall', 'flange', 'ear', 'keyhole', 'slot', 'corner', 'din', 'vesa', 'feet', 'rubber', 'belt', 'tie', 'pipe', 'sketch')
KIND_LABELS = {'wall': 'Uchwyt ścienny z otworami', 'flange': 'Kołnierz montażowy', 'ear': 'Ucho montażowe', 'keyhole': 'Otwory kluczowe',
               'slot': 'Otwory podłużne', 'corner': 'Uchwyt narożny', 'din': 'Zaczep na szynę DIN', 'vesa': 'Mocowanie VESA',
               'feet': 'Nóżki / podstawki', 'rubber': 'Gniazda na gumowe nóżki', 'belt': 'Klips do paska', 'tie': 'Uchwyt pod opaskę zaciskową',
               'pipe': 'Obejma do rury / profilu', 'sketch': 'Według szkicu'}
LAYOUTS = ('single', 'pair', 'corners', 'linear', 'grid', 'manual', 'points')
LAYOUT_LABELS = {'single': 'Pojedyncze', 'pair': 'Dwa symetryczne', 'corners': 'Cztery narożne', 'linear': 'Szyk liniowy',
                 'grid': 'Szyk prostokątny', 'manual': 'Ręczne (lista pozycji)', 'points': 'Według wskazanych punktów'}
OUTPUTS = ('integral', 'separate', 'detachable')
OUTPUT_LABELS = {'integral': 'Integralna część obudowy', 'separate': 'Osobna bryła', 'detachable': 'Element odłączany (z otworami w obudowie)'}
# szyny DIN wg IEC/EN 60715 (dokumentacja producentów: Phoenix Contact NS 35/7,5, AutomationDirect DN-R35) - edytowalne
DIN_RAILS = {'TH35-7.5': dict(width=35.0, opening=27.0, depth=7.5, sheet=1.0), 'TH35-15': dict(width=35.0, opening=27.0, depth=15.0, sheet=1.0)}
# VESA FDMI MIS-D: 75 × 75 albo 100 × 100 mm, wkręty M4 - edytowalne
VESA = {'75': 75.0, '100': 100.0}
SCREWS = {'M3': (3.4, 6.0, 2.6), 'M4': (4.5, 8.0, 3.3), 'M5': (5.5, 9.5, 4.2), 'M6': (6.6, 11.0, 5.0)}    # przelot, łeb, otwór pod gwint
DEFAULTS = dict(kind='wall', width=20.0, height=12.0, length=16.0, thickness=3.0, hole=4.5, hole_pitch=0.0, slot_len=8.0, radius=2.0,
                edge=4.0, angle=0.0, count=2, rib=0.0, clearance=.3, counterbore=0.0, head=8.0, du=0.0, dv=0.0, pitch=40.0, pitch2=30.0,
                rows=2, cols=2, layout='single', output='integral', rail='TH35-7.5', vesa='100', screw='M4', blind=6.0, min_wall=.8,
                pipe=20.0, belt=4.0, belt_w=40.0, tie_w=5.0, tie_h=2.0, foot_d=10.0, foot_h=5.0, positions=[], sketch=None, tool_len=25.0)


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _rot(p, ang):
    c, s = math.cos(ang), math.sin(ang)
    return np.array([c * p[0] - s * p[1], s * p[0] + c * p[1]])


def frame_of(face):
    n = np.asarray(face['normal'], float)
    up = (0, 0, 1.0) if abs(n[2]) < .9 else (0, 1.0, 0)
    return eh.wall_frame(face['point'], n, up)[:4]


def face_bounds(target_shape, face):
    """Obrys powierzchni w układzie (u, v): (lo, hi) i ściana."""
    from .enclosure_ribs import pick_face
    fr = frame_of(face)
    f = pick_face(target_shape, face)
    lo, hi, _uv = eh._bbox_uv(f, fr)
    return np.asarray(lo, float), np.asarray(hi, float), f, fr


# ---------------------------------------------------------------------------------------------- rozmieszczenie
def positions(p, lo, hi):
    """Pozycje mocowań (u, v, kąt w stopniach) w układzie powierzchni."""
    lay = p['layout']
    c = (lo + hi) / 2 + np.array([float(p['du']), float(p['dv'])])
    a = float(p['angle'])
    e = float(p['edge'])
    if lay == 'single':
        return [(c[0], c[1], a)]
    if lay == 'pair':
        half = (hi[0] - lo[0]) / 2 - e
        return [(c[0] - half, c[1], a + 180.0), (c[0] + half, c[1], a)]
    if lay == 'corners':
        hx, hy = (hi[0] - lo[0]) / 2 - e, (hi[1] - lo[1]) / 2 - e
        return [(c[0] + sx * hx, c[1] + sy * hy, a + math.degrees(math.atan2(sy, sx))) for sx in (-1, 1) for sy in (-1, 1)]
    if lay == 'linear':
        n = max(1, int(p['count']))
        d = _rot((1.0, 0.0), math.radians(a))
        return [(*(c + d * (k - (n - 1) / 2) * float(p['pitch'])), a) for k in range(n)]
    if lay == 'grid':
        out = []
        for i in range(max(1, int(p['cols']))):
            for j in range(max(1, int(p['rows']))):
                q = c + _rot(((i - (int(p['cols']) - 1) / 2) * float(p['pitch']), (j - (int(p['rows']) - 1) / 2) * float(p['pitch2'])), math.radians(a))
                out.append((q[0], q[1], a))
        return out
    if lay in ('manual', 'points'):
        pts = p.get('positions') or []
        if not pts:
            raise kernel.CadError('Dodaj pozycje mocowań (lista) albo wskaż punkty na powierzchni.')
        return [(float(q[0]), float(q[1]), float(q[2]) if len(q) > 2 else a) for q in pts]
    raise kernel.CadError('Nieznany sposób rozmieszczenia.')


# ---------------------------------------------------------------------------------------------- prymitywy
def _poly_face(pts2, fr, z=0.0, radius=0.0):
    """Wielokąt (u, v) na wysokości z wzdłuż n, z zaokrągleniem narożników (MakeFillet2d)."""
    o, u, v, n = fr
    face = eh._plane_face(pts2, (o + n * z, u, v, n))
    if radius > 1e-6:
        try:
            face = eh._fillet2d(face, radius)
        except Exception:
            raise kernel.CadError('Promień narożników za duży dla mocowania.')
    return face


def _extrude(face, fr, h):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    return BRepPrimAPI_MakePrism(face, gp_Vec(*map(float, fr[3] * h))).Shape()


def _rect(cu, cv, w, l, ang, anchor='centre'):
    """Prostokąt w (u, v): szerokość w (oś x lokalna), długość l (oś y); anchor 'edge' - od punktu w kierunku +y."""
    y0, y1 = (-l / 2, l / 2) if anchor == 'centre' else (0.0, l)
    pts = [(-w / 2, y0), (w / 2, y0), (w / 2, y1), (-w / 2, y1)]
    return [tuple(np.array([cu, cv]) + _rot(q, ang)) for q in pts]


def _cyl(fr, cu, cv, r, z0, z1):
    o, u, v, n = fr
    return eh._prism(eh._circle_face(cu, cv, r, fr), fr, z1, z0)


def _slot_face(fr, cu, cv, d, L, ang, z):
    o, u, v, n = fr
    pts = _rect(cu, cv, L + d, d, ang)
    face = eh._plane_face(pts, (o + n * z, u, v, n))
    return eh._fillet2d(face, d / 2 - 1e-3)


def _hole_tools(fr, kind, cu, cv, ang, p, z0, z1):
    """Narzędzia otworu: okrągły / podłużny / kluczowy, z pogłębieniem pod łeb od strony +n."""
    d = float(p['hole'])
    out = []
    if kind == 'slot':
        out.append(eh._prism(_slot_face(fr, cu, cv, d, float(p['slot_len']), ang, 0.0), fr, z1 + 1, z0 - 1))
    elif kind == 'keyhole':
        head = float(p['head'])
        L = float(p['slot_len'])
        tip = np.array([cu, cv]) + _rot((0.0, L), ang)
        out.append(_cyl(fr, cu, cv, head / 2, z0 - 1, z1 + 1))                         # duży otwór na łeb
        out.append(eh._prism(_slot_face(fr, *(np.array([cu, cv]) + _rot((0.0, L / 2), ang)), d, L, ang + math.pi / 2, 0.0), fr, z1 + 1, z0 - 1))
        pocket = _slot_face(fr, *(np.array([cu, cv]) + _rot((0.0, L / 2), ang)), head, L, ang + math.pi / 2, 0.0)
        out.append(eh._prism(pocket, fr, z0 + (z1 - z0) * .5, z0 - 1))               # gniazdo łba (od strony ścianki)
        del tip
    else:
        out.append(_cyl(fr, cu, cv, d / 2, z0 - 1, z1 + 1))
    cb = float(p['counterbore'])
    if cb > 0:
        out.append(_cyl(fr, cu, cv, float(p['head']) / 2 + float(p['clearance']), z1 - cb, z1 + 1))
    return out


def _holes_pattern(p, cu, cv, ang, n_default=2):
    """Pozycje otworów na mocowaniu (lokalnie): liczba i rozstaw wzdłuż szerokości."""
    n = max(1, int(p.get('holes_n', n_default)))
    pitch = float(p['hole_pitch']) or (float(p['width']) / max(n, 1))
    return [tuple(np.array([cu, cv]) + _rot(((k - (n - 1) / 2) * pitch, 0.0), ang)) for k in range(n)]


def element(fr, kind, cu, cv, a_deg, p, face_lo, face_hi):
    """Jedno mocowanie: (bryły dodawane, narzędzia tnące w mocowaniu, otwory współpracujące w obudowie, walce dostępu
    narzędzia, otwory ślepe (narzędzie, głębokość)). Współrzędne wysokości wzdłuż n od powierzchni (0)."""
    ang = math.radians(a_deg)
    t, w, L, r = float(p['thickness']), float(p['width']), float(p['length']), float(p['radius'])
    add, cut, mate, access, blind = [], [], [], [], []
    tool_len = float(p['tool_len'])
    if kind in ('wall', 'slot', 'keyhole'):
        add.append(_extrude(_poly_face(_rect(cu, cv, w, L, ang), fr, 0.0, r), fr, t))
        n_holes = 1 if kind == 'keyhole' else 2
        pitch = float(p['hole_pitch']) or w / 2
        for k in range(n_holes):
            q = np.array([cu, cv]) + _rot(((k - (n_holes - 1) / 2) * pitch, 0.0), ang)
            cut += _hole_tools(fr, kind, q[0], q[1], ang, p, 0.0 if kind == 'keyhole' else -2.0, t)
            access.append(_cyl(fr, q[0], q[1], float(p['head']) / 2 + .5, t + .01, t + tool_len))
            if kind != 'keyhole':
                mate.append(_cyl(fr, q[0], q[1], float(p['hole']) / 2, -float(p.get('_wall', 3.0)) - .5, .01))   # tylko przez ściankę
    elif kind in ('ear', 'flange'):
        if kind == 'ear':
            add.append(_extrude(_poly_face(_rect(cu, cv, w, L, ang, 'edge'), fr, 0.0, r), fr, t))
            q = np.array([cu, cv]) + _rot((0.0, L - w / 2), ang)
        else:                                                   # kołnierz: pas wokół krawędzi powierzchni na zewnątrz
            lo, hi = face_lo - L, face_hi + L
            outer = [(lo[0], lo[1]), (hi[0], lo[1]), (hi[0], hi[1]), (lo[0], hi[1])]
            add.append(_extrude(_poly_face(outer, fr, -t, r), fr, t))
            q = None
        pts = [q] if q is not None else [np.array([sx, sy]) for sx in (face_lo[0] - L / 2, face_hi[0] + L / 2) for sy in (face_lo[1] - L / 2, face_hi[1] + L / 2)]
        z0, z1 = (0.0, t) if kind == 'ear' else (-t, 0.0)
        for q in pts:
            cut += _hole_tools(fr, 'round', q[0], q[1], ang, p, z0, z1)
            access.append(_cyl(fr, q[0], q[1], float(p['head']) / 2 + .5, z1 + .01, z1 + tool_len))
    elif kind == 'corner':
        tri = [tuple(np.array([cu, cv]) + _rot(q, ang)) for q in ((0.0, 0.0), (L, 0.0), (0.0, L))]
        add.append(_extrude(_poly_face(tri, fr, 0.0, 0.0), fr, t))
        q = np.array([cu, cv]) + _rot((L / 3, L / 3), ang)
        cut += _hole_tools(fr, 'round', q[0], q[1], ang, p, -2.0, t)
        access.append(_cyl(fr, q[0], q[1], float(p['head']) / 2 + .5, t + .01, t + tool_len))
    elif kind == 'din':
        add += _din_clip(fr, cu, cv, ang, p)
    elif kind == 'vesa':
        s = VESA.get(str(p['vesa']), float(p['vesa']) if str(p['vesa']).replace('.', '').isdigit() else 100.0)
        boss = float(p['foot_d'])
        h = float(p['height'])
        pilot = SCREWS.get(p['screw'], SCREWS['M4'])[2]
        for sx in (-1, 1):
            for sy in (-1, 1):
                q = np.array([cu, cv]) + _rot((sx * s / 2, sy * s / 2), ang)
                add.append(_cyl(fr, q[0], q[1], boss / 2, -.3, h))
                depth = min(float(p['blind']), h + 5.0)
                tool = _cyl(fr, q[0], q[1], pilot / 2, h - depth, h + 1)
                cut.append(tool)
                blind.append((tool, h - depth))
    elif kind in ('feet', 'rubber'):
        d, h = float(p['foot_d']), float(p['foot_h'])
        if kind == 'feet':
            add.append(_cyl(fr, cu, cv, d / 2, -.3, h))
        else:
            depth = h
            tool = _cyl(fr, cu, cv, d / 2 + float(p['clearance']), -depth, .5)
            cut.append(('part', tool))
            blind.append((tool, -depth))
    elif kind == 'belt':
        bw, bt = float(p['belt_w']), float(p['belt'])
        base = _extrude(_poly_face(_rect(cu, cv, bw + 2 * t, t, ang), fr, 0.0, 0.0), fr, bt + t)     # słupek mocujący
        tongue = _extrude(_poly_face(_rect(*(np.array([cu, cv]) + _rot((0.0, L / 2 - t / 2), ang)), bw + 2 * t, L, ang), fr, bt, r), fr, t)
        add += [base, tongue]
    elif kind == 'tie':
        tw, th = float(p['tie_w']), float(p['tie_h'])
        span = tw + 2 * t
        bridge = _extrude(_poly_face(_rect(cu, cv, span, w * .5 if w > 0 else 6.0, ang), fr, 0.0, 0.0), fr, th + t)
        slot = _extrude(_poly_face(_rect(cu, cv, tw, (w * .5 if w > 0 else 6.0) + 2, ang), fr, -.01, 0.0), fr, th + .01)
        add.append(bridge)
        cut.append(slot)
    elif kind == 'pipe':
        add += _pipe_clamp(fr, cu, cv, ang, p)
    elif kind == 'sketch':
        pass
    else:
        raise kernel.CadError('Nieznany rodzaj mocowania.')
    if float(p['rib']) > 0 and kind in ('wall', 'ear', 'corner', 'slot', 'keyhole'):
        rb = float(p['rib'])
        gus = [(0.0, 0.0), (min(L, 10.0), 0.0), (0.0, min(L, 10.0) * .8)]
        for sx in (-1, 1):
            base = np.array([cu, cv]) + _rot((sx * (w / 2 - rb / 2), 0.0), ang)
            add.append(_gusset(fr, base, ang, rb, gus, t))
    return add, cut, mate, access, blind


def _gusset(fr, base, ang, rb, prof, t):
    """Żebro wzmacniające mocowania: trójkąt w płaszczyźnie (y lokalne, n) o grubości rb."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Pnt, gp_Vec
    o, u, v, n = fr
    dy = _rot((0.0, 1.0), ang)
    dx = _rot((1.0, 0.0), ang)
    y3, x3 = u * dy[0] + v * dy[1], u * dx[0] + v * dx[1]
    origin = o + u * base[0] + v * base[1] - x3 * rb / 2
    poly = BRepBuilderAPI_MakePolygon()
    for y, z in prof:
        poly.Add(gp_Pnt(*map(float, origin + y3 * (y - prof[1][0] / 2) + n * (t + z - .01))))
    poly.Close()
    face = BRepBuilderAPI_MakeFace(poly.Wire(), True).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(*map(float, x3 * rb))).Shape()


def _profile_prism(fr, cu, cv, ang, prof, width):
    """Profil 2D w płaszczyźnie (y lokalne, n) wyciągnięty o szerokość wzdłuż x lokalnego (symetrycznie)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Pnt, gp_Vec
    o, u, v, n = fr
    dy, dx = _rot((0.0, 1.0), ang), _rot((1.0, 0.0), ang)
    y3, x3 = u * dy[0] + v * dy[1], u * dx[0] + v * dx[1]
    origin = o + u * cu + v * cv - x3 * width / 2
    poly = BRepBuilderAPI_MakePolygon()
    for y, z in prof:
        poly.Add(gp_Pnt(*map(float, origin + y3 * y + n * z)))
    poly.Close()
    mf = BRepBuilderAPI_MakeFace(poly.Wire(), True)
    if not mf.IsDone():
        raise kernel.CadError('Niepoprawny profil mocowania.')
    return BRepPrimAPI_MakePrism(mf.Face(), gp_Vec(*map(float, x3 * width))).Shape()


def _din_clip(fr, cu, cv, ang, p):
    """Zaczep na szynę DIN (przekrój w płaszczyźnie y-n): podstawa, stały hak zachodzący za krawędź szyny i sprężysty
    zatrzask z najazdem po drugiej stronie; prześwit pod blachę szyny = blacha + luz."""
    rail = dict(DIN_RAILS.get(p['rail'], DIN_RAILS['TH35-7.5']))
    for k in ('width', 'opening', 'depth', 'sheet'):
        if p.get(f'rail_{k}'):
            rail[k] = float(p[f'rail_{k}'])
    W, O, s, g = rail['width'], rail['opening'], rail['sheet'], float(p['clearance'])
    t = float(p['thickness'])
    lip = (W - O) / 2
    width = float(p['width'])
    half = W / 2 + g
    gap_h = s + g                                              # prześwit na blachę szyny
    hook = lip * .6
    base = [(-half - t - 2.0, 0.0), (half + t + 2.0, 0.0), (half + t + 2.0, t), (-half - t - 2.0, t)]
    fixed = [(-half - t, t), (-half, t), (-half, t + gap_h), (-half + hook, t + gap_h), (-half + hook, t + gap_h + t), (-half - t, t + gap_h + t)]
    latch = [(half, t), (half + t, t), (half + t, t + gap_h + t), (half - hook, t + gap_h + t * .4), (half - hook, t + gap_h), (half, t + gap_h)]
    return [_profile_prism(fr, cu, cv, ang, base, width), _profile_prism(fr, cu, cv, ang, fixed, width),
            _profile_prism(fr, cu, cv, ang, latch, width)]


def _pipe_clamp(fr, cu, cv, ang, p):
    """Obejma do rury: siodło z wycięciem półkolistym (średnica rury + luz), wyciągnięte o szerokość."""
    import cadquery as cq
    from .enclosure import _boolean
    D = float(p['pipe']) + 2 * float(p['clearance'])
    t = float(p['thickness'])
    width = float(p['width'])
    H = D / 2 + t
    block = _profile_prism(fr, cu, cv, ang, [(-D / 2 - t, 0.0), (D / 2 + t, 0.0), (D / 2 + t, H), (-D / 2 - t, H)], width)
    o, u, v, n = fr
    dx = _rot((1.0, 0.0), ang)
    x3 = u * dx[0] + v * dx[1]
    centre = o + u * cu + v * cv + n * (H + D * .1) - x3 * (width / 2 + 1)
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    cyl = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*map(float, centre)), gp_Dir(*map(float, x3))), D / 2, width + 2).Shape()
    return [_boolean('cut', block, cyl, 'gniazdo rury')]


# ---------------------------------------------------------------------------------------------- budowa i kontrola
def build(part, face, p, components=(), others=(), sketch_face=None):
    """Mocowania na powierzchni: dict(part=bryła po zmianach, separate=[bryły osobne], info, report)."""
    import cadquery as cq
    from .enclosure import _boolean, _single, _unified, _volume, check_solid
    from .enclosure_ribs import _multi
    p = dict(DEFAULTS, **p)
    kind = p['kind']
    if kind not in KINDS:
        raise kernel.CadError('Nieznany rodzaj mocowania.')
    for key in ('thickness', 'width', 'length'):
        if float(p[key]) <= 0 and not (key == 'length' and kind in ('din', 'vesa', 'feet', 'rubber', 'tie', 'pipe')):
            raise kernel.CadError('Wymiary mocowania muszą być większe od zera.')
    target = part.wrapped if hasattr(part, 'wrapped') else part
    lo, hi, f, fr = face_bounds(cq.Shape.cast(target), face)
    o, u, v, n = fr
    test = np.asarray(face['point'], float) + n * .05                     # powierzchnia zewnętrzna: na zewnątrz jest powietrze
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_OUT
    from OCP.gp import gp_Pnt
    if BRepClass3d_SolidClassifier(target, gp_Pnt(*map(float, test)), 1e-6).State() != TopAbs_OUT:
        raise kernel.CadError('Wskaż zewnętrzną powierzchnię obudowy.')
    try:
        p['_wall'] = _wall_at(target, fr)
    except kernel.CadError:
        p['_wall'] = 3.0
    adds, cuts, part_cuts, mates, access, blinds = [], [], [], [], [], []
    for cu, cv, a in positions(p, lo, hi):
        if kind == 'sketch':
            if sketch_face is None:
                raise kernel.CadError('Wskaż zamknięty szkic z obrysem mocowania.')
            flat = eh.projected_faces([sketch_face], fr)
            adds.append(eh._prism(flat, fr, float(p['thickness']), -.3))
            continue
        add, cut, mate, acc, blind = element(fr, kind, cu, cv, a, p, lo, hi)
        adds += add
        for c in cut:
            (part_cuts.append(c[1]) if isinstance(c, tuple) else cuts.append(c))
        mates += mate
        access += acc
        blinds += blind
    if not adds and not part_cuts:
        raise kernel.CadError('Mocowanie nie ma geometrii - sprawdź parametry.')
    report = []
    mount = None
    if adds:
        mount = adds[0] if len(adds) == 1 else _multi('fuse', adds[0], adds[1:], 'mocowanie')
        if cuts:
            mount = _multi('cut', mount, cuts, 'otwory mocowania')
        mount = _unified(mount)
    out_mode = p['output']
    new_part = target
    separate = []
    if mount is not None:
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        for k_, piece in enumerate(_solids_of(mount)):          # każde mocowanie musi stykać się z obudową
            d = BRepExtrema_DistShapeShape(piece, target)
            d.Perform()
            if d.IsDone() and d.Value() > 1e-4 and kind not in ('belt',):
                raise kernel.CadError(f'Mocowanie {k_ + 1} wychodzi poza powierzchnię (nie styka się z obudową) - zmniejsz rozstaw '
                                      'albo wybierz większą powierzchnię.')
        if out_mode == 'integral':
            new_part = _boolean('fuse', target, mount, 'mocowanie z obudową')
        else:
            gapped = mount
            if _volume(_boolean('common', mount, target, 'mocowanie a obudowa'))[0] > 1e-3:
                gapped = _boolean('cut', mount, target, 'mocowanie poza obudową')     # osobna bryła nie wchodzi w ściankę
            for s in _solids_of(gapped):
                separate.append(check_solid(s))
            if out_mode == 'detachable' and mates:
                new_part = _multi('cut', new_part, mates, 'otwory współpracujące')
                report.append(('info', f'Otwory współpracujące w obudowie: {len(mates)}'))
    if part_cuts:
        new_part = _multi('cut', new_part, part_cuts, 'gniazda w obudowie')
    shape = check_solid(_single(_unified(new_part), 'Obudowa z mocowaniem'))
    # --- kontrole
    probe = [shape.wrapped] + [s.wrapped for s in separate]
    for c in components:
        for sh in probe:
            if _volume(_boolean('common', sh, c, 'kolizja z komponentem'))[0] > 1e-4:
                raise kernel.CadError('Mocowanie albo jego otwory kolidują z komponentem wewnątrz obudowy.')
    for c in components:
        for tool in [*(mates if out_mode == 'detachable' else []), *part_cuts]:     # narzędzia, które naruszają obudowę
            if _volume(_boolean('common', tool, c, 'otwór a komponent'))[0] > 1e-4:
                raise kernel.CadError('Otwór mocowania trafia w komponent wewnątrz obudowy - przesuń mocowanie.')
    for o_ in others:
        for sh in probe:
            if _volume(_boolean('common', sh, o_, 'kolizja z pokrywą'))[0] > 1e-3:
                raise kernel.CadError('Mocowanie koliduje z inną częścią obudowy (pokrywą / zamknięciem).')
    blocked = 0
    for acc in access:
        if _volume(_boolean('common', acc, shape.wrapped, 'dostęp narzędzia'))[0] > 1e-3:
            blocked += 1
    if blocked:
        report.append(('warning', f'Brak miejsca na łeb śruby / narzędzie przy {blocked} otworach - przesuń mocowanie albo skróć elementy obok.'))
    elif access:
        report.append(('ok', f'Miejsce na łeb śruby i narzędzie: wolne ({len(access)} otworów, {float(p["tool_len"]):g} mm).'))
    for tool, depth in blinds:
        rest = float(p['min_wall'])
        if depth < 0:                                          # gniazdo wpuszczone w ściankę
            from .enclosure_posts import wall_hit_exit
            th = wall_hit_exit(target, o - n * 1e-3, -n)
            if th is not None and -depth > th - rest:
                raise kernel.CadError(f'Gniazdo ({-depth:g} mm) przebiłoby ściankę ({th:.2f} mm, minimum {rest:g} mm) - zmniejsz głębokość.')
        if _volume(_boolean('common', tool, target, 'otwór ślepy'))[0] > 1e-3 and depth >= 0:
            raise kernel.CadError('Otwór ślepy sięga w ściankę obudowy - zmniejsz głębokość albo zwiększ wysokość słupka.')
    report.append(('ok', f'{KIND_LABELS[kind]}: {len(positions(p, lo, hi)) if kind != "flange" else 1} szt.'))
    return dict(part=shape, separate=separate, report=report, frame=fr, bounds=(lo, hi))


def _wall_at(target, fr):
    """Grubość ścianki pod powierzchnią (promień od środka powierzchni w głąb)."""
    from .enclosure_posts import wall_hit_exit
    o, u, v, n = fr
    t = wall_hit_exit(target, o - n * 1e-3, -n)
    if t is None:
        raise kernel.CadError('Pod powierzchnią nie ma ścianki.')
    return float(t) + 1e-3


def _solids_of(shape):
    from .enclosure import _solids, _volume
    return [s for s in _solids(shape) if _volume(s)[0] > 1e-6]


def preview_mesh(p, fr, lo, hi):
    """Uproszczony podgląd: obrysy mocowań (prostokąty / okręgi w pozycjach) - bez OCC."""
    o, u, v, n = fr
    edges, pts = {}, []
    w, L = float(p['width']), max(float(p['length']), 2.0)
    for k, (cu, cv, a) in enumerate(positions(p, lo, hi)):
        loop = [np.array([cu, cv]) + _rot(q, math.radians(a)) for q in ((-w / 2, -L / 2), (w / 2, -L / 2), (w / 2, L / 2), (-w / 2, L / 2), (-w / 2, -L / 2))]
        P = np.array([o + u * q[0] + v * q[1] + n * float(p['thickness']) for q in loop], np.float32)
        edges[k] = P
        pts.append(P)
    if not pts:
        return None
    vv = np.concatenate(pts)
    return kernel.DisplayMesh(vv, np.empty((0, 3), np.uint32), edges, tuple(map(float, vv.mean(axis=0))), float(np.linalg.norm(vv.max(axis=0) - vv.min(axis=0))))
