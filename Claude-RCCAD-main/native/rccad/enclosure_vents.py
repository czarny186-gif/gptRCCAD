"""Generator obudów - etap 10: wentylacja.

Wzór otworów na wskazanej płaskiej ściance obudowy, w prostokątnym obszarze (środek, szerokość, wysokość w układzie
ścianki - jak w „Otworze na element”). Wzory: okrągły, kwadratowy, prostokątny, sześciokątny (plaster miodu), szczeliny
podłużne, szczeliny zaokrąglone, promieniowy, żaluzje (szczeliny ukośne przez ściankę) i kratka pod wentylator (z biblioteki
25-140 mm, z edytowalnym rozstawem otworów montażowych). Parametry: wielkość otworów, odstępy, liczba rzędów i kolumn
(0 - wypełnienie automatyczne), kąt obrotu, margines od krawędzi obszaru, minimalna szerokość materiału między otworami.

Geometria: profile 2D otworów (ściany płaskie) wyciągnięte przez ściankę; cięcie zbiorcze - jedna operacja
BRepAlgoAPI_Cut z listą wszystkich narzędzi (równolegle, prefiltr OBB), wycinane wyłącznie w docelowej części. Kontrola jak w otworach
na element: usunięta objętość = sama ścianka (inaczej uszkodzenie mocowania / zamknięcia / sąsiedniej ścianki albo wyjście
poza ściankę). Powierzchnia otwarta liczona z rzeczywistych profili, udział - względem pola obszaru."""
from __future__ import annotations

import math

import numpy as np

from . import kernel
from . import enclosure_holes as eh

PATTERNS = ('circle', 'square', 'rect', 'hex', 'slot', 'rslot', 'radial', 'louver', 'fan')
PATTERN_LABELS = {'circle': 'Okrągłe otwory', 'square': 'Kwadratowe otwory', 'rect': 'Prostokątne otwory', 'hex': 'Sześciokątne (plaster miodu)',
                  'slot': 'Szczeliny podłużne', 'rslot': 'Szczeliny zaokrąglone', 'radial': 'Wzór promieniowy', 'louver': 'Żaluzje (szczeliny ukośne)',
                  'fan': 'Kratka pod wentylator'}
# rozmiar wentylatora: rozstaw otworów montażowych (mm) i średnica otworów - wartości typowe, do zmiany w oknie
FANS = {25: (20.0, 2.9), 30: (24.0, 3.3), 40: (32.0, 3.4), 60: (50.0, 4.4), 80: (71.5, 4.4), 92: (82.5, 4.4), 120: (105.0, 4.4), 140: (124.5, 4.4)}
DEFAULTS = dict(pattern='hex', size=4.0, length=12.0, pitch=0.0, pitch2=0.0, rows=0, cols=0, angle=0.0, margin=2.0, web=1.2,
                cu=0.0, cv=0.0, width=30.0, height=20.0, louver=45.0, fan=40, fan_spacing=None, fan_hole=None, fan_ring=True)
BATCH = 200
MAX_HOLES = 4000


def _rot(p, ang):
    c, s = math.cos(ang), math.sin(ang)
    return np.array([c * p[0] - s * p[1], s * p[0] + c * p[1]])


def layout(p):
    """Otwory wzoru w układzie ścianki: lista (kształt, środek (u, v), wymiary, kąt) oraz pole obszaru.
    Otwory, które nie mieszczą się w obszarze pomniejszonym o margines, są pomijane."""
    pat = p['pattern']
    if pat not in PATTERNS:
        raise kernel.CadError('Nieznany wzór wentylacji.')
    W, H, m, web = float(p['width']), float(p['height']), float(p['margin']), float(p['web'])
    size, length = float(p['size']), float(p['length'])
    if W <= 0 or H <= 0:
        raise kernel.CadError('Obszar wentylacji musi mieć dodatnie wymiary.')
    if size <= 0 or web < 0 or m < 0:
        raise kernel.CadError('Wielkość otworów musi być dodatnia, a margines i materiał między otworami nieujemne.')
    ang = math.radians(float(p['angle']))
    cu, cv = float(p['cu']), float(p['cv'])
    holes = []
    if pat in ('radial', 'fan'):
        if pat == 'fan':
            F = int(p['fan'])
            spacing, hole_d = FANS.get(F, FANS[40])
            spacing = float(p['fan_spacing'] or spacing)
            hole_d = float(p['fan_hole'] or hole_d)
            R = F / 2 - m
            for sx in (-1, 1):
                for sy in (-1, 1):
                    holes.append(('circle', np.array([cu, cv]) + _rot((sx * spacing / 2, sy * spacing / 2), ang), (hole_d, hole_d), 0.0, 'mount'))
            if R <= size:
                raise kernel.CadError('Kratka wentylatora: margines za duży dla tego rozmiaru wentylatora.')
            area = math.pi * (F / 2) ** 2
        else:
            R = min(W, H) / 2 - m
            area = W * H
        pitch = float(p['pitch']) or (size + web)
        if pitch - size < web - 1e-9:
            raise kernel.CadError(f'Odstęp otworów {pitch:g} mm zostawia mniej materiału niż minimum {web:g} mm.')
        holes.append(('circle', np.array([cu, cv]), (size, size), 0.0, 'vent'))
        k = 1
        while k * pitch + size / 2 <= R + 1e-9:
            r = k * pitch
            n = max(1, int(2 * math.pi * r / pitch))
            for j in range(n):
                a = ang + 2 * math.pi * j / n
                holes.append(('circle', np.array([cu + r * math.cos(a), cv + r * math.sin(a)]), (size, size), 0.0, 'vent'))
            k += 1
        if pat == 'fan':                             # otwory kratki nie mogą wejść w otwory montażowe
            mounts = [h for h in holes if h[4] == 'mount']
            holes = mounts + [h for h in holes if h[4] == 'vent' and all(np.linalg.norm(h[1] - mh[1]) >= (size + mh[2][0]) / 2 + web for mh in mounts)]
        return holes, area
    if pat in ('slot', 'rslot', 'louver'):
        sx, sy = length, size
        if length <= size and pat == 'rslot':
            raise kernel.CadError('Szczelina zaokrąglona musi być dłuższa niż szeroka.')
        px = float(p['pitch']) or (length + web)
        py = float(p['pitch2']) or (size + web)
    elif pat == 'rect':
        sx, sy = length, size
        px = float(p['pitch']) or (length + web)
        py = float(p['pitch2']) or (size + web)
    else:
        sx = sy = size
        px = float(p['pitch']) or (size + web)
        py = float(p['pitch2']) or (px * math.sqrt(3) / 2 if pat == 'hex' else px)
    gap_x = px - sx                                    # sześciokąt: rozwartość `size`, sąsiedzi stykają się bokami
    gap_y = (px - sx) if pat == 'hex' else py - sy
    if min(gap_x, gap_y) < web - 1e-9:
        raise kernel.CadError(f'Odstępy otworów zostawiają mniej materiału niż minimum {web:g} mm - zwiększ odstęp.')
    rows, cols = int(p['rows']), int(p['cols'])
    inner_w, inner_h = W - 2 * m, H - 2 * m
    if inner_w <= 0 or inner_h <= 0:
        raise kernel.CadError('Margines większy niż połowa obszaru.')
    reach = math.hypot(sx, sy) / 2
    if cols <= 0:
        cols = max(1, int((max(inner_w, inner_h) * 2) // px) + 3)
    if rows <= 0:
        rows = max(1, int((max(inner_w, inner_h) * 2) // py) + 3)
    if rows * cols > MAX_HOLES * 4:
        raise kernel.CadError('Za dużo otworów - zwiększ otwory albo odstępy.')
    auto = int(p['rows']) <= 0 or int(p['cols']) <= 0
    for r in range(rows):
        for c in range(cols):
            x = (c - (cols - 1) / 2) * px + (px / 2 if (pat == 'hex' and r % 2) else 0.0)
            y = (r - (rows - 1) / 2) * py
            q = np.array([cu, cv]) + _rot((x, y), ang)
            # otwór musi mieścić się w obszarze pomniejszonym o margines (sprawdzenie narożnikami otworu)
            corners = [q + _rot((dx * sx / 2, dy * sy / 2), ang) for dx in (-1, 1) for dy in (-1, 1)] if pat not in ('circle', 'hex') else \
                [q + (dx * reach * (1 if pat == 'hex' else .7072), dy * reach * (1 if pat == 'hex' else .7072)) for dx in (-1, 1) for dy in (-1, 1)]
            if pat == 'circle':
                ok = abs(q[0] - cu) + sx / 2 <= inner_w / 2 + 1e-9 and abs(q[1] - cv) + sx / 2 <= inner_h / 2 + 1e-9
            else:
                ok = all(abs(cc[0] - cu) <= inner_w / 2 + 1e-9 and abs(cc[1] - cv) <= inner_h / 2 + 1e-9 for cc in corners)
            if ok:
                holes.append((pat, q, (sx, sy), ang, 'vent'))
    if not auto and len(holes) < rows * cols:
        raise kernel.CadError(f'{rows} × {cols} otworów nie mieści się w obszarze - zmniejsz liczbę, odstępy albo margines.')
    if len(holes) > MAX_HOLES:
        raise kernel.CadError(f'Za dużo otworów ({len(holes)}) - największa liczba to {MAX_HOLES}.')
    return holes, W * H


def hole_face(h, frame):
    """Profil jednego otworu (ściana płaska w płaszczyźnie ścianki)."""
    kind, q, (sx, sy), ang, _role = h
    if kind == 'circle':
        return eh._circle_face(q[0], q[1], sx / 2, frame)
    if kind == 'hex':
        R = sx / math.sqrt(3)                              # rozwartość sx (między bokami)
        pts = [q + _rot((R * math.cos(math.pi / 6 + k * math.pi / 3), R * math.sin(math.pi / 6 + k * math.pi / 3)), ang) for k in range(6)]
        return eh._plane_face(pts, frame)
    pts = [q + _rot((dx * sx / 2, dy * sy / 2), ang) for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    face = eh._plane_face(pts, frame)
    if kind == 'rslot':
        face = eh._fillet2d(face, min(sx, sy) / 2 - 1e-3)
    return face


def preview_mesh(holes, frame):
    """Uproszczony podgląd wzoru: same obrysy otworów jako linie (bez geometrii OCC)."""
    o, u, v, _n = frame[:4]
    edges = {}
    pts = []
    for n, h in enumerate(holes):
        kind, q, (sx, sy), ang, _r = h
        if kind == 'circle':
            loop = [q + (sx / 2 * math.cos(t), sx / 2 * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 17)]
        elif kind == 'hex':
            R = sx / math.sqrt(3)
            loop = [q + _rot((R * math.cos(math.pi / 6 + k * math.pi / 3), R * math.sin(math.pi / 6 + k * math.pi / 3)), ang) for k in range(7)]
        else:
            loop = [q + _rot((dx * sx / 2, dy * sy / 2), ang) for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1), (-1, -1))]
        w = np.array([o + u * a + v * b for a, b in loop], np.float32)
        edges[n] = w
        pts.append(w)
    if not pts:
        return None
    vv = np.concatenate(pts)
    return kernel.DisplayMesh(vv, np.empty((0, 3), np.uint32), edges, tuple(map(float, vv.mean(axis=0))), float(np.linalg.norm(vv.max(axis=0) - vv.min(axis=0))))


def area_region(p, frame):
    if p['pattern'] == 'fan':
        return eh._circle_face(float(p['cu']), float(p['cv']), int(p['fan']) / 2, frame)
    W, H = float(p['width']), float(p['height'])
    return eh.profile_shape('rrect', float(p['cu']), float(p['cv']), W, H, 0.0, frame)


def _cut_many(shape, tools):
    """Cięcie zbiorcze - wspólny silnik narzędzia Wentylacja (rccad.vent_cut.cut_many: jedna operacja Boolean ze
    wszystkimi narzędziami, równolegle, prefiltr OBB)."""
    from .vent_cut import cut_many
    return cut_many(shape, tools)


def tools(target_shape, frame, p):
    """Bryły narzędzi wszystkich otworów wzoru (bez cięcia)."""
    p = dict(DEFAULTS, **p)
    holes, _area = layout(p)
    t = eh.wall_thickness(target_shape.wrapped, frame, (float(p['cu']), float(p['cv'])))
    o, u, v, n = frame[:4]
    vent_frame = frame
    if p['pattern'] == 'louver':
        a = math.radians(max(-75.0, min(75.0, float(p['louver']))))
        vent_frame = (*frame[:4], n * math.cos(a) - v * math.sin(a))
    return [eh._prism(hole_face(h, frame), vent_frame if h[4] == 'vent' else frame, 1.0, -t - 1.0) for h in holes]


def build(target_shape, frame, p):
    """Otwory wentylacyjne w części obudowy. Zwraca (bryła cq, info: liczba otworów, powierzchnia otwarta, udział %)."""
    from .enclosure import _boolean, _single, _unified, _volume, check_solid, _make_box
    import cadquery as cq
    p = dict(DEFAULTS, **p)
    holes, area = layout(p)
    if not [h for h in holes if h[4] == 'vent']:
        raise kernel.CadError('Żaden otwór nie mieści się w obszarze - zmniejsz otwory albo margines.')
    region = area_region(p, frame)
    eh._inside_wall(target_shape, region, frame)
    t = eh.wall_thickness(target_shape.wrapped, frame, (float(p['cu']), float(p['cv'])))
    o, u, v, n = frame[:4]
    vent_frame = frame
    if p['pattern'] == 'louver':                        # żaluzje: szczeliny ukośne (kąt względem normalnej, w kierunku „góra”)
        a = math.radians(max(-75.0, min(75.0, float(p['louver']))))
        vent_frame = (*frame[:4], n * math.cos(a) - v * math.sin(a))
    open_area, all_area, tools = 0.0, 0.0, []
    for h in holes:
        f = hole_face(h, frame)
        fr = vent_frame if h[4] == 'vent' else frame
        tools.append(eh._prism(f, fr, 1.0, -t - 1.0))
        a = cq.Shape.cast(f).Area()
        all_area += a
        if h[4] == 'vent':
            open_area += a
    # objętość otworów w samej ściance: pole profilu × grubość (graniastosłup - także ukośny - przecina płaską ściankę
    # na wysokości t mierzonej wzdłuż normalnej; otwory rozłączne)
    expected = all_area * t
    before = _volume(target_shape.wrapped)[0]
    result = _cut_many(target_shape.wrapped, tools)
    removed = before - _volume(result)[0]
    if removed > expected * 1.01 + 1e-3:
        raise kernel.CadError('Otwory wentylacyjne uszkadzają mocowanie, zatrzask, inne wycięcie albo sąsiednią ściankę - zmień obszar.')
    if removed < expected * .99 - 1e-3:
        raise kernel.CadError('Otwory wentylacyjne wychodzą poza ściankę obudowy - zmniejsz obszar.')
    shape = check_solid(_single(_unified(result), 'Obudowa z wentylacją'))
    return shape, dict(count=sum(1 for h in holes if h[4] == 'vent'), mounts=sum(1 for h in holes if h[4] == 'mount'),
                       open_area=open_area, area=area, percent=100.0 * open_area / area, thickness=t)
