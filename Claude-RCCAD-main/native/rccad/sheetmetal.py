"""Blacha: konwersja prostopadłościanu na blachę, kołnierze i ich przebudowa od podstaw (geometria, bez Qt).

Model: blacha = płyta bazowa (prostopadłościan z konwersji) + lista kołnierzy zapisana w kroku historii.
Każdy kołnierz to „base” (krawędź płyty) albo „tip” (krawędź końca innego kołnierza). Przy każdym przebudowaniu
geometria liczy się od nowa z tej listy, więc narożniki (ukos i szczelina) zawsze odpowiadają całej blasze.

Kierunek kołnierza: normalna na zewnątrz większej ściany krawędzi (dla płyty: górna w górę, dolna w dół).
"""
import math
import numpy as np
import cadquery as cq
from . import kernel

K_DEFAULT = 0.44          # współczynnik K — domyślny (reguły blach, na razie tylko zapis)
RELIEFS = ('none', 'square', 'round')
_TOL = 1e-4


def _unit(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise kernel.CadError("Nieprawidłowy kierunek blachy.")
    return v / n


def _arr(v):
    return np.asarray(v, float)


def _rect_dims(face):
    """Długości boków płaskiego prostokąta (cztery wierzchołki, kąty proste)."""
    verts = face.Vertices()
    if len(verts) != 4 or len(face.Edges()) != 4:
        return None
    pts = [np.array(v.toTuple(), float) for v in verts]
    dist = [[float(np.linalg.norm(a - b)) for b in pts] for a in pts]
    sides = sorted(dist[0][1:])
    if sides[0] < 1e-6:
        return None
    a, b, diag = sides[0], sides[1], sides[2]
    if abs(math.hypot(a, b) - diag) > 1e-4 * max(diag, 1.0):
        return None
    return a, b


def sheet_of_face(shape, face):
    """Konwersja: bryła musi być prostopadłościanem, a wybrana ściana prostokątem.
    Zwraca N (normalna „góry” blachy), t (grubość), dims i base (płyta bazowa: początek, osie i długości)."""
    faces = shape.Faces()
    if len(faces) != 6 or any(f.geomType() != 'PLANE' for f in faces):
        raise kernel.CadError("Konwersja na blachę wymaga prostopadłościanu (bryła z sześcioma płaskimi ścianami).")
    if face.geomType() != 'PLANE' or _rect_dims(face) is None:
        raise kernel.CadError("Wybierz płaską ścianę w kształcie prostokąta albo kwadratu.")
    n = _unit(face.normalAt().toTuple())
    c = np.array(face.Center().toTuple(), float)
    opposite = None
    for f in faces:
        if f.isSame(face):
            continue
        if float(_unit(f.normalAt().toTuple()) @ n) < -1 + 1e-6:
            opposite = f
            break
    if opposite is None:
        raise kernel.CadError("Nie znaleziono ściany przeciwległej do wybranej.")
    t = abs(float((c - np.array(opposite.Center().toTuple(), float)) @ n))
    if t < 1e-4:
        raise kernel.CadError("Blacha ma zerową grubość.")
    verts = [np.array(v.toTuple(), float) for v in face.Vertices()]
    p0 = verts[0]
    near = sorted(verts[1:], key=lambda q: float(np.linalg.norm(q - p0)))
    a, b = near[0] - p0, near[1] - p0            # dwa boki przy p0 (przekątna jest najdłuższa)
    z = _unit(np.cross(a, b))
    x = _unit(a)
    y = np.cross(z, x)
    cvec = -t * n                                 # grubość: od ściany wybranej w głąb bryły
    cz = float(cvec @ z)
    origin = p0 if cz > 0 else p0 + cvec
    base = dict(o=[float(v) for v in origin], x=[float(v) for v in x], y=[float(v) for v in y], z=[float(v) for v in z],
                lx=float(np.linalg.norm(a)), ly=float(np.linalg.norm(b)), lz=abs(cz))
    return dict(N=[float(v) for v in n], t=t, dims=list(_rect_dims(face)), base=base)


def base_solid(base):
    plane = cq.Plane(origin=tuple(base['o']), xDir=tuple(base['x']), normal=tuple(base['z']))
    return kernel.valid(cq.Workplane(plane).box(base['lx'], base['ly'], base['lz'], centered=False).val())


def _adjacent_faces(shape, edge):
    return [f for f in shape.Faces() if any(e.isSame(edge) for e in f.Edges())]


def edge_side(shape, edge, t):
    """Krawędź blachy: większa płaska ściana krawędzi daje kierunek kołnierza (jej normalna na zewnątrz), mniejsza
    ściana czołowa musi być prostopadła i sięgać grubości blachy t. Zwraca (n_out, m)."""
    faces = _adjacent_faces(shape, edge)
    if len(faces) != 2 or any(f.geomType() != 'PLANE' for f in faces):
        raise kernel.CadError("Kołnierz można dodać tylko do płaskiej krawędzi blachy.")
    big, end = sorted(faces, key=lambda f: f.Area(), reverse=True)
    if big.Area() <= end.Area() * 1.0001:
        raise kernel.CadError("Nie rozpoznano strony blachy przy tej krawędzi.")
    mid = edge.positionAt(.5)
    # normalne ściany na zewnątrz bryły: orientacja powierzchni nie jest zawsze zgodna, więc porównujemy z jej środkiem
    centre = np.array(shape.Center().toTuple(), float)

    def outward(face):
        v = _unit(face.normalAt(mid).toTuple())
        return v if float((np.array(face.Center().toTuple(), float) - centre) @ v) >= 0 else -v

    n = outward(big)
    m = outward(end)
    if abs(float(n @ m)) > 1e-6:
        raise kernel.CadError("Ta krawędź nie jest prostopadła do ściany blachy.")
    ref = np.array(mid.toTuple(), float)
    gaps = [abs(float((np.array(v.toTuple(), float) - ref) @ n)) for v in end.Vertices()]
    if not any(abs(g - t) <= 1e-3 * max(1.0, t) for g in gaps):
        raise kernel.CadError("Wybrana krawędź nie jest krawędzią blachy o tej grubości.")
    return n, m


def _frame(p0, p1, t, n, m):
    """Układ kołnierza: początek przy końcu krawędzi, osie X (wzdłuż m), Y (kierunek kołnierza n), Z (wzdłuż krawędzi)."""
    n = _unit(n)
    m = _unit(m)
    p0, p1 = _arr(p0), _arr(p1)
    span = float(np.linalg.norm(p1 - p0))
    d = (p1 - p0) / span
    zdir = np.cross(m, n)
    base = p0 if float(zdir @ d) > 0 else p1
    return base - t * n, m, n, zdir, span


def _check_numbers(radius, angle, length):
    if not math.isfinite(radius) or radius <= 0:
        raise kernel.CadError("Promień gięcia musi być dodatni.")
    if not math.isfinite(angle) or not (0 < angle <= 180):
        raise kernel.CadError("Kąt kołnierza musi być w zakresie (0, 180] stopni.")
    if not math.isfinite(length) or length <= 0:
        raise kernel.CadError("Długość kołnierza musi być dodatnia.")


def flange_solid(p0, p1, t, n_out, m, radius, angle, length):
    """Bryła kołnierza na krawędzi p0–p1: łuk gięcia (promień wewnętrzny = promień stempla) i prosty odcinek."""
    origin, X, Y, Z, span = _frame(p0, p1, t, n_out, m)
    plane = cq.Plane(origin=tuple(float(c) for c in origin), xDir=tuple(float(c) for c in X), normal=tuple(float(c) for c in Z))
    th = math.radians(angle)
    r = float(radius)
    cy = t + r

    def arc(R, phi):
        return (R * math.cos(phi), cy + R * math.sin(phi))

    phi0, phi1 = -math.pi / 2, -math.pi / 2 + th
    D = (math.cos(th), math.sin(th))
    ie, oe = arc(r, phi1), arc(r + t, phi1)
    inner_f = (ie[0] + length * D[0], ie[1] + length * D[1])
    outer_f = (oe[0] + length * D[0], oe[1] + length * D[1])
    prof = (cq.Workplane(plane)
            .moveTo(*arc(r, phi0))
            .threePointArc(arc(r, (phi0 + phi1) / 2), ie)
            .lineTo(*inner_f)
            .lineTo(*outer_f)
            .lineTo(*oe)
            .threePointArc(arc(r + t, (phi0 + phi1) / 2), arc(r + t, phi0))
            .close())
    return kernel.valid(prof.extrude(span).val())


HEM_MIN_GAP = 0.1


def _hem_R(radius, gap):
    """Wewnętrzny promień łuku zawinięcia: zmniejszany do połowy szczeliny, żeby odstęp od powierzchni był równy szczelinie."""
    return min(float(radius), float(gap) / 2.0)


def hem_solid(p0, p1, t, n_out, m, radius, ret, gap):
    """Zawinięcie 180° przylegające do powierzchni: krawędź zawija się od razu (bez dodatkowego kołnierza) na stronę n
    i wraca odcinkiem `ret` po tej powierzchni. Szczelina `gap` to odstęp od powierzchni do odcinka powrotnego;
    promień łuku jest zmniejszany do gap/2 (jeśli promień jest mniejszy, odstęp wynosi 2 × promień)."""
    origin, X, Y, Z, span = _frame(p0, p1, t, n_out, m)
    plane = cq.Plane(origin=tuple(float(c) for c in origin), xDir=tuple(float(c) for c in X), normal=tuple(float(c) for c in Z))
    R = _hem_R(radius, gap)
    cy = t + R
    bend = (cq.Workplane(plane).moveTo(0, 0).threePointArc((R + t, cy), (0, 2 * t + 2 * R))
            .lineTo(0, t + 2 * R).threePointArc((R, cy), (0, t)).close())
    leg = (cq.Workplane(plane).polyline([(0, t + 2 * R), (-float(ret), t + 2 * R), (-float(ret), 2 * t + 2 * R), (0, 2 * t + 2 * R)])
           .close())
    out = kernel.boolean('union', bend.extrude(span).val(), [leg.extrude(span).val()])
    return kernel.valid(out)


def _hem_end_geom(par, side, t):
    """Swobodny koniec odcinka powrotnego zawinięcia: krawędź zewnętrzna ('out', dalej od płyty) albo
    wewnętrzna ('in', przy płycie). Zwraca (p0, p1, n, m) dla kołnierza na tej krawędzi."""
    origin, X, Y, Z, span = _frame(par['p0'], par['p1'], t, par['n'], par['m'])
    R = _hem_R(par['r'], par['hem']['gap'])
    ue = -float(par['hem']['ret'])
    if side == 'out':
        ve, nloc = 2 * t + 2 * R, 1.0
    elif side == 'in':
        ve, nloc = t + 2 * R, -1.0
    else:
        raise kernel.CadError("Nieznana strona końca zawinięcia.")
    point = origin + ue * X + ve * Y
    m_w = -X                       # na zewnątrz końca odcinka powrotnego
    n_w = nloc * Y                 # kołnierz wychodzi od końca na zewnątrz (out) albo w stronę płyty (in)
    return point, point + span * Z, n_w, m_w


def _tip_geom(par, side, t):
    """Krawędź końca kołnierza `par` po stronie 'in' (wewnętrzna) albo 'out' (zewnętrzna): (p0, p1, n, m) dla kołnierza na niej."""
    origin, X, Y, Z, span = _frame(par['p0'], par['p1'], t, par['n'], par['m'])
    th = math.radians(par['angle'])
    r, L = float(par['r']), float(par['length'])
    cy = t + r
    D = np.array([math.cos(th), math.sin(th)])
    W = np.array([-math.sin(th), math.cos(th)])
    if side == 'in':
        uv = np.array([r * math.sin(th), cy - r * math.cos(th)]) + L * D
        nloc = W
    elif side == 'out':
        uv = np.array([(r + t) * math.sin(th), cy - (r + t) * math.cos(th)]) + L * D
        nloc = -W
    else:
        raise kernel.CadError("Nieznana strona końca kołnierza.")
    point = origin + uv[0] * X + uv[1] * Y
    n_w = nloc[0] * X + nloc[1] * Y
    m_w = D[0] * X + D[1] * Y
    return point, point + span * Z, n_w, m_w


def _seg_dist(p, a, b):
    ab = b - a
    L2 = float(ab @ ab)
    s = 0.0 if L2 < 1e-18 else min(1.0, max(0.0, float((p - a) @ ab) / L2))
    return float(np.linalg.norm(p - (a + s * ab)))


def _hem_of(s):
    """Zawinięcie z pola 'hem' kołnierza albo None: promień (z pola r), długość odcinka powrotnego i szczelina ≥ 0,1 mm."""
    h = s.get('hem')
    if not h:
        return None
    gap, ret = float(h['gap']), float(h['ret'])
    if not math.isfinite(gap) or gap < HEM_MIN_GAP - 1e-9:
        raise kernel.CadError("Szczelina zawinięcia nie może być mniejsza niż 0,1 mm.")
    if not math.isfinite(ret) or ret <= 0:
        raise kernel.CadError("Długość zawinięcia musi być dodatnia.")
    _check_numbers(float(s['r']), 90.0, ret)
    return dict(gap=gap, ret=ret)


def _straight(s, t, outside):
    """Długość prostej części kołnierza. Przy wymiarze zewnętrznym odejmujemy od podanej długości styczną
    łuku gięcia: (promień + grubość) * tg(kąt/2)."""
    L = float(s['length'])
    if not outside:
        return L
    a = math.radians(min(float(s['angle']), 179.0))
    L2 = L - (float(s['r']) + t) * math.tan(a / 2)
    if L2 <= 0:
        raise kernel.CadError("Wymiar zewnętrzny jest za mały dla tego promienia i kąta.")
    return L2


def _effective(specs, t, miter, outside=False):
    """Kołnierze z geometrią: końce krawędzi płyty w narożach z sąsiadem wydłużone o (promień + grubość),
    żeby ukos miał materiał do cięcia. Zwraca (lista, narożniki (P, i, j, N)), N = normalna płaszczyzny ukosu."""
    eff = [None] * len(specs)
    base_idx = [i for i, s in enumerate(specs) if s['kind'] == 'base']
    for i in base_idx:
        s = specs[i]
        eff[i] = dict(kind='base', p0=_arr(s['p0']), p1=_arr(s['p1']), n=_unit(s['n']), m=_unit(s['m']),
                      r=float(s['r']), angle=float(s['angle']), length=(_hem_of(s)['ret'] if s.get('hem') else _straight(s, t, outside)), hem=_hem_of(s))
    ends, corners = {}, []
    orig = {i: (eff[i]['p0'].copy(), eff[i]['p1'].copy()) for i in base_idx}   # długość krawędzi bez wydłużeń w rogach
    if miter:
        for i in base_idx:
            ends[i] = [False, False]
            for k, P in enumerate((eff[i]['p0'], eff[i]['p1'])):
                for j in base_idx:
                    if j == i:
                        continue
                    for Q in (eff[j]['p0'], eff[j]['p1']):
                        if float(np.linalg.norm(P - Q)) < _TOL and abs(float(eff[i]['m'] @ eff[j]['m'])) < 1e-6:
                            ends[i][k] = True
                            if i < j:
                                # dwusieczna kąta między ścianami: płaszczyzna ukosu przechodzi przez krawędź narożnika
                                corners.append((P.copy(), i, j, _unit(eff[i]['m'] - eff[j]['m'])))
        for i in base_idx:
            f = eff[i]
            ext = f['r'] + t
            d = _unit(f['p1'] - f['p0'])
            if ends[i][0]:
                f['p0'] = f['p0'] - ext * d
            if ends[i][1]:
                f['p1'] = f['p1'] + ext * d
    for i, s in enumerate(specs):
        if s['kind'] == 'tip':
            par = eff[int(s['parent'])]
            if par is None:
                raise kernel.CadError("Kołnierz na końcu nie ma kołnierza nadrzędnego.")
            if int(s['parent']) in orig:
                # zaczep biegnie po długości krawędzi, nie po wydłużeniu w narożniku (inaczej wystaje poza blachę)
                par = dict(par, p0=orig[int(s['parent'])][0], p1=orig[int(s['parent'])][1])
            if par.get('hem'):
                p0, p1, n, m = _hem_end_geom(par, s['side'], t)
            else:
                p0, p1, n, m = _tip_geom(par, s['side'], t)
            eff[i] = dict(kind='tip', p0=p0, p1=p1, n=n, m=m, r=float(s['r']), angle=float(s['angle']),
                          length=(_hem_of(s)['ret'] if s.get('hem') else _straight(s, t, outside)), hem=_hem_of(s))
    return eff, corners


def _cutter(P, N, sgn, c, Kh, Kv):
    """Półprzestrzeń po stronie drugiej ściany narożnika, ograniczona prostokątem: Kh wzdłuż linii ukosu wokół narożnika,
    Kv w pionie (cała wysokość). sgn=+1: (X−P)·N < c; sgn=−1: (X−P)·N > −c. c = połowa szczeliny."""
    N = _unit(N)
    v = np.array([0.0, 0.0, 1.0]) if abs(float(N[2])) < 0.9 else np.array([1.0, 0.0, 0.0])
    xd = _unit(v - float(v @ N) * N)
    Q = _arr(P) + sgn * c * N
    plane = cq.Plane(origin=tuple(float(x) for x in Q), xDir=tuple(float(x) for x in xd),
                     normal=tuple(float(x) for x in (-sgn * N)))
    return cq.Workplane(plane).rect(2 * Kv, 2 * Kh).extrude(2 * Kh).val()


def _miter(solid, P, N, sgn, c, Kh, Kv):
    """Ukos w narożniku: usuwa z kołnierza część po stronie ukosu w pasie wokół narożnika na całej wysokości.
    Końce kołnierzy i zawinięć idą wzdłuż płaszczyzny ukosu, a nie wychodzą poza nią."""
    region = _cutter(P, N, sgn, c, Kh, Kv)
    return kernel.valid(kernel.boolean('subtract', solid, [region]))


def _end_dir(spec, P):
    """Kierunek wzdłuż ściany wychodzący z jej oryginalnego końca w narożniku P (od krawędzi na zewnątrz ściany)."""
    p0, p1 = _arr(spec['p0']), _arr(spec['p1'])
    d = _unit(p1 - p0)
    return d if float(np.linalg.norm(_arr(P) - p1)) < float(np.linalg.norm(_arr(P) - p0)) else -d


def _endcut(solid, P, d, K):
    """Cięcie prostopadłe (90°) na końcu ściany: usuwa część po stronie d od płaszczyzny przechodzącej przez P."""
    d = _unit(d)
    v = np.array([0.0, 0.0, 1.0]) if abs(float(d[2])) < 0.9 else np.array([1.0, 0.0, 0.0])
    xd = _unit(v - float(v @ d) * d)
    plane = cq.Plane(origin=tuple(float(x) for x in _arr(P)), xDir=tuple(float(x) for x in xd), normal=tuple(float(x) for x in d))
    region = cq.Workplane(plane).rect(2 * K, 2 * K).extrude(2 * K).val()
    return kernel.valid(kernel.boolean('subtract', solid, [region]))


def _butt_cut(solid, P, m_a, offset, gap, K):
    """Styk na styk: część po stronie m_a za płaszczyzną odsuniętą o `offset` od P (wzdłuż m_a) minus szczelina.
    Dla ściany to wewnętrzna powierzchnia drugiej ściany (offset = promień gięcia); dla kołnierza wewnętrznego
    to najdalej wysunięty punkt kołnierza sąsiada (offset < 0)."""
    Q = _arr(P) + (float(offset) - float(gap)) * _unit(m_a)
    return _endcut(solid, Q, m_a, K)


def _free_offset(solid, P, m):
    """Najbardziej wysunięty w głąb (przeciwnie do m) punkt bryły, liczony od P wzdłuż m."""
    m = _unit(m)
    return min(float((np.array(v.toTuple(), float) - _arr(P)) @ m) for v in solid.Vertices())


def _union_all(solids):
    if len(solids) == 1:
        return solids[0]
    return kernel.boolean('union', solids[0], solids[1:])


def relief_cut(shape, point, d, normal, kind, size):
    """Wycięcie w narożniku: kwadrat albo okrąg o wielkości size, przez całą wysokość kołnierzy."""
    H = 1000.0
    n = _unit(normal)
    plane = cq.Plane(origin=tuple(float(x) for x in (_arr(point) - H * n)), xDir=tuple(float(x) for x in _unit(d)), normal=tuple(float(x) for x in n))
    wp = cq.Workplane(plane)
    wp = wp.rect(size, size) if kind == 'square' else wp.circle(size / 2)
    cutter = wp.extrude(2 * H).val()
    return kernel.valid(kernel.boolean('subtract', shape, [cutter]))


def build_sheet(recipe):
    """Blacha od podstaw: płyta bazowa + kołnierze z listy + ukosy i szczeliny w narożach + wycięcia w narożnikach."""
    base = base_solid(recipe['base'])
    t = float(recipe['t'])
    rules = recipe.get('rules') or {}
    gap = float(rules.get('gap', 0.0))
    relief = rules.get('relief', 'none')
    rsize = float(rules.get('relief_size', 0.0))
    miter = bool(rules.get('miter', True))
    joint = rules.get('joint', 'parallel')
    if joint not in ('parallel', 'diagonal'):
        raise kernel.CadError("Nieznany sposób łączenia kołnierzy w narożniku.")
    outside = bool(rules.get('outside', False))
    if relief not in RELIEFS:
        raise kernel.CadError("Nieznany rodzaj wycięcia w narożniku.")
    if not math.isfinite(gap) or gap < 0:
        raise kernel.CadError("Szczelina między kołnierzami nie może być ujemna.")
    specs = recipe.get('flanges') or []
    for s in specs:
        _check_numbers(float(s['r']), float(s['angle']), float(s['length']))
    if not specs:
        return base
    eff, corners = _effective(specs, t, miter, outside)
    # właściciel kołnierza = numer kołnierza płyty, z której wyrasta (kołnierz na kołnierzu dziedziczy właściciela)
    owner = []
    for i, s_ in enumerate(specs):
        owner.append(i if s_['kind'] == 'base' else owner[int(s_['parent'])])
    c = gap / 2.0
    K = max(f['length'] + (f['hem']['ret'] if f.get('hem') else 0.0) for f in eff) + 2 * (max(f['r'] for f in eff) + t) + 2 * t + 5.0

    pieces = {}
    for i, f in enumerate(eff):
        if f.get('hem'):
            pieces[i] = hem_solid(tuple(f['p0']), tuple(f['p1']), t, tuple(f['n']), tuple(f['m']), f['r'],
                                  f['hem']['ret'], f['hem']['gap'])
        else:
            pieces[i] = flange_solid(tuple(f['p0']), tuple(f['p1']), t, tuple(f['n']), tuple(f['m']), f['r'], f['angle'], f['length'])
    # każdy kawałek przycinamy płaszczyzną ukosu własnej ściany; kołnierze na kołnierzach w wąskim pasie wokół narożnika
    K_tip = max(f['r'] for f in eff) + 3 * t + gap + 2.0
    reach = {}
    for P, a, b, N in corners:
        offs = [_free_offset(pieces[i], P, eff[a]['m']) for i in pieces
                if owner[i] == a and specs[i]['kind'] == 'tip' and specs[i].get('side') == 'in']
        reach[(a, b)] = min(offs) if offs else None
    for i in pieces:
        for P, a, b, N in corners:
            if owner[i] not in (a, b):
                continue
            outward_tip = specs[i]['kind'] == 'tip' and specs[i].get('side') == 'out'
            if joint == 'diagonal':
                # łączenie skośne: ukos 45° w narożniku, kołnierz na zewnątrz kończy się prostopadle do ściany
                if outward_tip:
                    pieces[i] = _endcut(pieces[i], P, _end_dir(specs[owner[i]], P), K)
                elif owner[i] == a:
                    pieces[i] = _miter(pieces[i], P, N, 1, c, K, K)
                else:
                    pieces[i] = _miter(pieces[i], P, N, -1, c, K, K)
            else:
                # łączenie równoległe (styk na styk): pierwsza ściana (a) biegnie przez narożnik,
                # druga (b) kończy się przy jej powierzchni; wewnętrzne kołnierze a kończą się przy powierzchni b,
                # a wewnętrzne kołnierze b kończą się przed wolnym końcem kołnierzy a (żeby się nie nakładały)
                if owner[i] == b:
                    inner_tip = specs[i]['kind'] == 'tip' and specs[i].get('side') == 'in'
                    offset = reach.get((a, b)) if inner_tip and reach.get((a, b)) is not None else eff[a]['r']
                    pieces[i] = _butt_cut(pieces[i], P, eff[a]['m'], offset, gap, K)
                elif specs[i]['kind'] == 'tip' and specs[i].get('side') == 'in':
                    pieces[i] = _butt_cut(pieces[i], P, eff[b]['m'], eff[b]['r'], gap, K)

    base_idx = [i for i, s_ in enumerate(specs) if s_['kind'] == 'base']
    tip_idx = [i for i, s_ in enumerate(specs) if s_['kind'] != 'base']
    shape = base
    for i in base_idx:
        shape = kernel.boolean('union', shape, [pieces[i]])
    # wycięcie w narożniku tylko w warstwie płyt (dolnej): kołnierze wyższych warstw go nie przecinają
    if relief != 'none' and rsize > 0:
        for i in base_idx:
            d = _unit(_arr(specs[i]['p1']) - _arr(specs[i]['p0']))
            for P in (_arr(specs[i]['p0']), _arr(specs[i]['p1'])):
                shape = relief_cut(shape, P, d, eff[i]['n'], relief, rsize)
    for i in tip_idx:
        shape = kernel.boolean('union', shape, [pieces[i]])
    return kernel.valid(shape)


def spec_for_edge(base, t, specs, rules, mid, tol):
    """Kołnierz na wybranej krawędzi: krawędź końca istniejącego kołnierza („tip”) albo krawędź płyty („base”)."""
    eff, _ = _effective(specs, t, bool((rules or {}).get('miter', True)))
    mid = _arr(mid)
    taken_tips = {(int(s['parent']), s['side']) for s in specs if s['kind'] == 'tip'}
    # wybieramy najbliższą krawędź (tolerancja nie może być większa niż grubość, inaczej trafiamy w sąsiednią krawędź)
    best = None
    for i, f in enumerate(eff):
        for side in ('in', 'out'):
            if (i, side) in taken_tips:
                continue
            p0, p1, _, _ = (_hem_end_geom(f, side, t) if f.get('hem') else _tip_geom(f, side, t))
            d = _seg_dist(mid, p0, p1)
            if d < tol and (best is None or d < best[0]):
                best = (d, dict(kind='tip', parent=i, side=side))
    if best is not None:
        return best[1]
    shape = base_solid(base)
    cands = []
    for e in shape.Edges():
        a = np.array(e.positionAt(0).toTuple(), float)
        b = np.array(e.positionAt(1).toTuple(), float)
        d = _seg_dist(mid, a, b)
        if d < tol:
            cands.append((d, e, a, b))
    for d, e, a, b in sorted(cands, key=lambda c: c[0]):
        if any(s['kind'] == 'base' and (np.linalg.norm(_arr(s['p0']) - a) < _TOL and np.linalg.norm(_arr(s['p1']) - b) < _TOL
                                        or np.linalg.norm(_arr(s['p0']) - b) < _TOL and np.linalg.norm(_arr(s['p1']) - a) < _TOL)
               for s in specs):
            continue
        n, m = edge_side(shape, e, t)
        return dict(kind='base', p0=[float(x) for x in a], p1=[float(x) for x in b], n=[float(x) for x in n], m=[float(x) for x in m])
    raise kernel.CadError("Nie rozpoznano krawędzi blachy. Kliknij krawędź płyty albo krawędź kołnierza.")


def add_flange(shape, edge, sheet, radius, angle, length, gap=0.0, relief='none', relief_size=0.0):
    """Dodaje kołnierz do gotowej bryły blachy na krawędzi (wersja z kroku „flange”, zachowana dla starych projektów)."""
    _check_numbers(float(radius), float(angle), float(length))
    if not math.isfinite(gap) or gap < 0:
        raise kernel.CadError("Szczelina między kołnierzami nie może być ujemna.")
    if relief not in RELIEFS:
        raise kernel.CadError("Nieznany rodzaj wycięcia w narożniku.")
    t = float(sheet['t'])
    n_out, m = edge_side(shape, edge, t)
    p0, p1 = edge.positionAt(0), edge.positionAt(1)
    p0, p1 = np.array([p0.x, p0.y, p0.z], float), np.array([p1.x, p1.y, p1.z], float)
    span = float(np.linalg.norm(p1 - p0))
    if gap >= span:
        raise kernel.CadError("Szczelina jest większa od krawędzi.")
    d = (p1 - p0) / span
    q0, q1 = p0 + gap / 2 * d, p1 - gap / 2 * d
    out = kernel.boolean('union', shape, [flange_solid(tuple(q0), tuple(q1), t, tuple(n_out), tuple(m), radius, angle, length)])
    if relief != 'none' and relief_size > 0:
        for corner in (p0, p1):
            out = relief_cut(out, corner, d, n_out, relief, relief_size)
    return out
