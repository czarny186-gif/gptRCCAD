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

K_DEFAULT = 0.44          # położenie warstwy obojętnej jako ułamek grubości
RELIEFS = ('none', 'square', 'round')
_TOL = 1e-4


def _unit(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    if v.shape != (3,) or not np.all(np.isfinite(v)) or n < 1e-12:
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
    # Oriented faces of a valid solid already carry outward normals. A global
    # centre-of-mass test flips underside faces once folded material moves the
    # centroid below them (e.g. the third/fourth lower hem).
    n = _unit(big.normalAt(mid).toTuple())
    m = _unit(end.normalAt(mid).toTuple())
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
    if not math.isfinite(span) or span < _TOL:
        raise kernel.CadError("Krawędź gięcia ma zerową długość.")
    d = (p1 - p0) / span
    zdir = np.cross(m, n)
    if abs(float(m @ n)) > 1e-6 or abs(abs(float(zdir @ d)) - 1) > 1e-6:
        raise kernel.CadError("Krawędź i kierunki gięcia nie tworzą układu prostopadłego.")
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
    if float(s['angle']) >= 180:
        raise kernel.CadError("Dla gięcia 180° podaj długość prostej części, nie wymiar zewnętrzny.")
    a = math.radians(float(s['angle']))
    L2 = L - (float(s['r']) + t) * math.tan(a / 2)
    if L2 <= 0:
        raise kernel.CadError("Wymiar zewnętrzny jest za mały dla tego promienia i kąta.")
    return L2


def _effective(specs, t, miter, outside=False):
    """Nominal attachment frames and shared base corners, before corner trimming."""
    eff = [None] * len(specs)
    base_idx = [i for i, s in enumerate(specs) if s['kind'] == 'base']
    for i in base_idx:
        s = specs[i]
        eff[i] = dict(kind='base', p0=_arr(s['p0']), p1=_arr(s['p1']), n=_unit(s['n']), m=_unit(s['m']),
                      r=float(s['r']), angle=float(s['angle']), length=(_hem_of(s)['ret'] if s.get('hem') else _straight(s, t, s.get('outside', outside))), hem=_hem_of(s))
    corners = []
    if miter:
        for i in base_idx:
            for P in (eff[i]['p0'], eff[i]['p1']):
                for j in base_idx:
                    if j == i:
                        continue
                    for Q in (eff[j]['p0'], eff[j]['p1']):
                        if float(np.linalg.norm(P - Q)) < _TOL and abs(float(eff[i]['m'] @ eff[j]['m'])) < 1e-6:
                            # Corner ownership is independent of the bend
                            # angle, including the 180-degree turn of a hem.
                            if i < j:
                                # dwusieczna kąta między ścianami: płaszczyzna ukosu przechodzi przez krawędź narożnika
                                corners.append((P.copy(), i, j, _unit(eff[i]['m'] - eff[j]['m'])))
    for i, s in enumerate(specs):
        if s['kind'] == 'tip':
            par = eff[int(s['parent'])]
            if par is None:
                raise kernel.CadError("Kołnierz na końcu nie ma kołnierza nadrzędnego.")
            if par.get('hem'):
                p0, p1, n, m = _hem_end_geom(par, s['side'], t)
            else:
                p0, p1, n, m = _tip_geom(par, s['side'], t)
            eff[i] = dict(kind='tip', p0=p0, p1=p1, n=n, m=m, r=float(s['r']), angle=float(s['angle']),
                          length=(_hem_of(s)['ret'] if s.get('hem') else _straight(s, t, s.get('outside', outside))), hem=_hem_of(s))
    # Hems use the same analytic bend + tangent return as a 180-degree
    # flange. Keep the actual gap-limited radius in every corner/development
    # frame, rather than the tool radius and the UI's placeholder angle.
    for frame in eff:
        if frame.get('hem'):
            frame.update(r=_hem_R(frame['r'],frame['hem']['gap']),angle=180.,length=frame['hem']['ret'])
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


def _endcut(solid, P, d, K):
    """Cięcie prostopadłe (90°) na końcu ściany: usuwa część po stronie d od płaszczyzny przechodzącej przez P."""
    d = _unit(d)
    v = np.array([0.0, 0.0, 1.0]) if abs(float(d[2])) < 0.9 else np.array([1.0, 0.0, 0.0])
    xd = _unit(v - float(v @ d) * d)
    plane = cq.Plane(origin=tuple(float(x) for x in _arr(P)), xDir=tuple(float(x) for x in xd), normal=tuple(float(x) for x in d))
    region = cq.Workplane(plane).rect(2 * K, 2 * K).extrude(2 * K).val()
    return kernel.valid(kernel.boolean('subtract', solid, [region]))


def relief_cut(shape, point, d, normal, kind, size):
    """Wycięcie w narożniku: kwadrat albo okrąg o wielkości size, przez całą wysokość kołnierzy."""
    H = 1000.0
    n = _unit(normal)
    plane = cq.Plane(origin=tuple(float(x) for x in (_arr(point) - H * n)), xDir=tuple(float(x) for x in _unit(d)), normal=tuple(float(x) for x in n))
    wp = cq.Workplane(plane)
    wp = wp.rect(size, size) if kind == 'square' else wp.circle(size / 2)
    cutter = wp.extrude(2 * H).val()
    return kernel.valid(kernel.boolean('subtract', shape, [cutter]))


def _same_end(spec, a, b, t):
    """Compare both thickness-side edges of one physical flange attachment."""
    for offset in (0, t, -t):
        p = _arr(spec['p0']) + offset * _unit(spec['n'])
        q = _arr(spec['p1']) + offset * _unit(spec['n'])
        if (np.linalg.norm(p - a) < _TOL and np.linalg.norm(q - b) < _TOL or
                np.linalg.norm(p - b) < _TOL and np.linalg.norm(q - a) < _TOL):
            return True
    return False


def _validate_specs(specs, t):
    parents = set()
    for i, s in enumerate(specs):
        if s.get('kind') == 'base':
            _frame(s['p0'], s['p1'], t, s['n'], s['m'])
            if any(p['kind'] == 'base' and _same_end(p, _arr(s['p0']), _arr(s['p1']), t) for p in specs[:i]):
                raise kernel.CadError("Na tej krawędzi jest już gięcie. Nie można zagiąć jej drugi raz z przeciwnej strony.")
        elif s.get('kind') == 'tip':
            parent = s.get('parent')
            if type(parent) is not int or not 0 <= parent < i:
                raise kernel.CadError("Gięcie musi wskazywać wcześniejszy kołnierz nadrzędny.")
            if s.get('side') not in ('in', 'out'):
                raise kernel.CadError("Nieznany kierunek gięcia.")
            if parent in parents:
                raise kernel.CadError("Koniec kołnierza ma już kolejne gięcie.")
            parents.add(parent)
        else:
            raise kernel.CadError("Nieznany rodzaj kołnierza.")


def _join_sheet(shape, parts):
    """One Boolean per level, with a volume check for material folded into itself."""
    if not parts:
        return shape
    # Default quadrature can differ by several thousandths of a mm³ before
    # and after splitting a ruled relief surface. Use adaptive integration for
    # these surfaces and intersected cylinders so a clean join is not
    # reported as a material collision.
    volume = lambda piece: piece.Volume(1e-9)
    expected = volume(shape) + sum(volume(p) for p in parts)
    result = kernel.boolean('union', shape, parts)
    if expected - volume(result) > max(1e-4, expected * 1e-8):
        raise kernel.CadError("Gięcia nachodzą na siebie lub na płytę. Zmień kierunek, kąt albo długość kołnierza.")
    return result


def _corner_layout(specs, eff, corners, t):
    owners, depths = [], []
    for i, s in enumerate(specs):
        parent = s.get('parent')
        owners.append(i if s['kind'] == 'base' else owners[parent])
        depths.append(0 if s['kind'] == 'base' else depths[parent] + 1)
    # A later outward bend can reach much farther than R+t. Reserve enough
    # material at shared ends for the complete chain, then trim it exactly.
    reach = []
    for i, f in enumerate(eff):
        reach.append(f['length'] + 2*(f['r'] + t) + (reach[specs[i]['parent']] if specs[i]['kind'] == 'tip' else 0))
    extension = max(reach, default=0) + t
    frames = []
    for i, f in enumerate(eff):
        root = eff[owners[i]]
        axis = _unit(root['p1'] - root['p0'])
        d = _unit(f['p1'] - f['p0'])
        p0, p1 = f['p0'].copy(), f['p1'].copy()
        for P, a, b, _ in corners:
            if owners[i] not in (a, b):
                continue
            if abs(float((f['p0'] - P) @ axis)) < _TOL:
                p0 -= extension * d
            if abs(float((f['p1'] - P) @ axis)) < _TOL:
                p1 += extension * d
        frames.append(dict(f, p0=p0, p1=p1))
    return frames, owners, depths, extension


def _flange_parts(f, t):
    """Separate the bend and straight leg so butt joints cannot clip a bend as a box."""
    if f.get('hem'):
        f=dict(f,r=_hem_R(f['r'],f['hem']['gap']),angle=180.,length=f['hem']['ret'])
    origin, X, Y, Z, span = _frame(f['p0'], f['p1'], t, f['n'], f['m'])
    plane = cq.Plane(origin=tuple(origin), xDir=tuple(X), normal=tuple(Z))
    theta = math.radians(f['angle'])
    r = f['r']
    def point(radius, angle):
        return (radius * math.sin(angle), t + r - radius * math.cos(angle))
    inner, outer = point(r, theta), point(r+t, theta)
    bend = (cq.Workplane(plane).moveTo(0, t).threePointArc(point(r, theta/2), inner)
            .lineTo(*outer).threePointArc(point(r+t, theta/2), (0, 0)).close().extrude(span).val())
    delta = f['length'] * np.array([math.cos(theta), math.sin(theta)])
    leg = (cq.Workplane(plane).polyline([inner, tuple(_arr(inner)+delta), tuple(_arr(outer)+delta), outer])
           .close().extrude(span).val())
    return [kernel.valid(bend), kernel.valid(leg)]


def _leg_profile(f, root, P, normal, t):
    """Straight-leg cross section in a common corner coordinate system."""
    a, _, _, direction = _tip_geom(f, 'in', t)
    b, _, _, _ = _tip_geom(f, 'out', t)
    points = [a, b, a - f['length']*direction, b - f['length']*direction]
    return np.array(sorted((round(float((v-P) @ root['m']), 9), round(float((v-P) @ normal), 9)) for v in points))


def _curved_endcut(solid, frame, t, point, direction, start, end, reach, vertical_end=False):
    """Relieve a bend between its parent's square end and the next panel end.

    The transition follows the tangents of the circular bend. Only the end
    surface is ruled; cutting the analytic bend preserves its cylindrical faces.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    origin,X,Y,Z,_ = _frame(frame['p0'],frame['p1'],t,frame['n'],frame['m'])
    theta = math.radians(frame['angle'])
    denominator = math.sin(theta) if vertical_end else 1-math.cos(theta)
    axial = float(Z@direction)
    center = t+frame['r']
    def boundary(radius):
        slope = (end-start)/(denominator*radius*axial)
        offset = (start-float((origin-point)@direction)+
                  (0 if vertical_end else (end-start)*(1-center/radius)/denominator))/axial
        translation = origin+offset*Z
        columns = (X+slope*Z,Y,Z) if vertical_end else (X,Y+slope*Z,Z)
        transform = cq.Matrix([[float(columns[col][row]) for col in range(3)]+[float(translation[row])] for row in range(3)]+[[0,0,0,1]])
        edge = cq.Edge.makeCircle(radius,cq.Vector(0,center,0),cq.Vector(0,0,1),-90,-90+frame['angle'])
        return edge.transformGeometry(transform)
    face = cq.Face.makeRuledSurface(boundary(frame['r']*.5),boundary((frame['r']+t)*2))
    prism = BRepPrimAPI_MakePrism(face.wrapped,gp_Vec(*(float(v) for v in reach*direction)))
    cutter = kernel.valid(cq.Shape.cast(prism.Shape()))
    return kernel.boolean('subtract',solid,[cutter])


def _corner_parts(recipe, eff, corners, parallel_version=3):
    """Trim each bend and leg before fusing; keep material pieces independently valid."""
    specs, t = recipe['flanges'], float(recipe['t'])
    rules = recipe.get('rules') or {}
    gap = float(rules.get('gap', 0))
    frames, owners, depths, extension = _corner_layout(specs, eff, corners, t)
    lookup = {(owner, depth): i for i, (owner, depth) in enumerate(zip(owners, depths))}
    raw = {i: _flange_parts(f, t) for i, f in enumerate(frames)}
    parts = {i:list(pieces) for i,pieces in raw.items()}
    # The cutter must cover the full developed chain, including distant returns.
    K = sum(float(recipe['base'][key]) for key in ('lx','ly','lz')) + 4*extension + gap + 1
    normal = _unit(recipe['base']['z'])
    sheet_joint = rules.get('joint') == 'sheet'
    parallel = rules.get('joint','parallel') == 'parallel' and parallel_version>=2
    legacy_parallel = rules.get('joint','parallel') == 'parallel' and not parallel
    curtains_cache,curtains_world={},{}
    def curtain(owner,corner,far):
        from . import sheetcorner
        root=eff[owner]
        family=[j for j in raw if owners[j]==owner]
        signature=tuple((round(float(eff[j]['r']),10),round(float(eff[j]['angle']),10),round(float(eff[j]['length']),10),
                         tuple(round(float(v),10) for v in ((eff[j]['p0']-root['p0'])@root['m'],(eff[j]['p0']-root['p0'])@normal,
                                                          eff[j]['n']@root['m'],eff[j]['n']@normal,eff[j]['m']@root['m'],eff[j]['m']@normal)),
                         tuple(sorted((eff[j].get('hem') or {}).items()))) for j in family)
        if signature not in curtains_cache:
            curtains_cache[signature]=sheetcorner.curtains(root,[piece for j in family for piece in raw[j]],normal,K,gap,cache_key=(round(t,10),round(K,10),round(gap,10),signature),planar=parallel_version>=3)
        key=(owner,corner,far)
        if key not in curtains_world:
            axis=_unit(np.cross(root['m'],normal))
            plane=cq.Plane(origin=tuple(corners[corner][0]),xDir=tuple(root['m']),normal=tuple(axis))
            curtains_world[key]=curtains_cache[signature][0 if far else 1].transformShape(plane.rG)
        return curtains_world[key]
    caps = {}

    def straight_end(i, corner):
        """Continue the parent's real end as a plane when adjacent folds diverge."""
        key = (i,corner)
        if key in caps:
            return caps[key]
        if specs[i]['kind'] != 'tip':
            return None
        f, root = eff[i], eff[owners[i]]
        P = corners[corner][0]
        axis = _unit(root['p1']-root['p0'])
        direction = axis if np.linalg.norm(P-root['p1']) < np.linalg.norm(P-root['p0']) else -axis
        vertices = [np.array(v.toTuple()) for piece in parts[specs[i]['parent']] for v in piece.Vertices()]
        edge = [v for v in vertices if abs(float((v-f['p0'])@f['m'])) < _TOL
                and abs(float((v-f['p0'])@f['n'])) < _TOL]
        if not edge:
            return None
        cap = max(float((v-P)@direction) for v in edge)
        plane = (P+cap*direction,direction)
        caps[key] = (plane,[_endcut(piece,*plane,K) for piece in raw[i]])
        return caps[key]

    def overlap(left,right):
        for a in left:
            bb = a.BoundingBox()
            for b in right:
                cb = b.BoundingBox()
                if any(min(getattr(bb,dim+'max'),getattr(cb,dim+'max')) -
                       max(getattr(bb,dim+'min'),getattr(cb,dim+'min')) <= _TOL for dim in 'xyz'):
                    continue
                if abs(a.intersect(b).Volume()) > 1e-5:
                    return True
        return False

    def relieve_bend(i,corner):
        if not sheet_joint or depths[i]==0 or len(parts[i])!=2 or abs(eff[i]['angle']-90)>1e-6:
            return
        parent_end = straight_end(i,corner)
        if parent_end is None:
            return
        P = corners[corner][0]
        direction = parent_end[0][1]
        start = float((parent_end[0][0]-P)@direction)
        ends = []
        vertices = [np.array(v.toTuple()) for v in parts[i][1].Vertices()]
        for side in ('in','out'):
            point,_,n,d = _tip_geom(eff[i],side,t)
            point = point-eff[i]['length']*d
            edge = [v for v in vertices if abs(float((v-point)@n))<_TOL and abs(float((v-point)@d))<_TOL]
            if not edge:
                return
            ends.append(max(float((v-P)@direction) for v in edge))
        if abs(ends[0]-ends[1])>_TOL:
            return
        end = sum(ends)/2
        if abs(start-end)<_TOL:
            parts[i][0] = _endcut(parts[i][0],P+start*direction,direction,K)
        else:
            d = _tip_geom(eff[i],'out',t)[3]
            parts[i][0] = _curved_endcut(parts[i][0],frames[i],t,P,direction,start,end,K,
                                        vertical_end=abs(float(d@normal))>1-1e-6)

    # All parent edges must already be trimmed before their children inherit an end.
    for i in sorted(range(len(frames)),key=lambda index:depths[index]):
        f = frames[i]
        for corner,(P, a, b, N) in enumerate(corners):
            owner = owners[i]
            if owner not in (a, b):
                continue
            other = b if owner == a else a
            peer = lookup.get((other, depths[i]))
            profile = _leg_profile(eff[i], eff[owner], P, normal, t)
            peer_profile = _leg_profile(eff[peer], eff[other], P, normal, t) if peer is not None else None
            matching = (profile is not None and peer_profile is not None
                        and np.allclose(profile,peer_profile,atol=_TOL,rtol=0))
            direction = _tip_geom(eff[i], 'out', t)[3] if profile is not None else normal
            peer_direction = _tip_geom(eff[peer], 'out', t)[3] if peer_profile is not None else normal
            vertical_pair = (sheet_joint and profile is not None and peer_profile is not None
                             and abs(float(direction@normal))>1-1e-6
                             and abs(float(peer_direction@normal))>1-1e-6
                             and np.allclose([profile[:,0].min(),profile[:,0].max()],
                                             [peer_profile[:,0].min(),peer_profile[:,0].max()],atol=_TOL,rtol=0)
                             and min(profile[:,1].max(),peer_profile[:,1].max()) >
                                 max(profile[:,1].min(),peer_profile[:,1].min())+_TOL)
            if parallel:
                capped=straight_end(i,corner)
                if not matching and capped is not None:
                    peer_cap=straight_end(peer,corner) if peer is not None else None
                    neighbors=(peer_cap[1] if peer_cap is not None else raw[peer] if peer is not None else
                               [piece for j in parts if owners[j]==other and depths[j]<depths[i] for piece in parts[j]])
                    if not overlap(capped[1],neighbors):
                        parts[i]=[_endcut(piece,*capped[0],K) for piece in parts[i]]
                        continue
                if peer is None:
                    root=eff[owner];axis=_unit(root['p1']-root['p0'])
                    outward=axis if np.linalg.norm(P-root['p1'])<np.linalg.norm(P-root['p0']) else -axis
                    plane=capped[0] if capped is not None else (P,outward)
                    parts[i]=[_endcut(piece,*plane,K) for piece in parts[i]]
                else:
                    tool=curtain(other,corner,owner==a)
                    parts[i]=[kernel.boolean('subtract',piece,[tool]) for piece in parts[i]]
                continue
            if (legacy_parallel and profile is not None and peer_profile is not None):
                if not matching:
                    capped, peer_cap = straight_end(i,corner), straight_end(peer,corner)
                    if capped is not None and not overlap(capped[1],peer_cap[1] if peer_cap else raw[peer]):
                        parts[i] = [_endcut(piece,*capped[0],K) for piece in parts[i]]
                        continue
                # Butt ends belong to every level, not just terminal panels.
                # Reserve the complete bend end; the actual neighbouring
                # material trims it below instead of a diagonal seam plane.
                end = float(peer_profile[:,0].max()) if owner == a else float(peer_profile[:,0].min())-gap
                cut_direction = eff[other]['m']
                peer_outer,_,peer_normal,_ = _tip_geom(eff[peer],'out',t)
                if abs(float(peer_normal@cut_direction)) > 1e-6:
                    peer_inner = _tip_geom(eff[peer],'in',t)[0]
                    near, far = sorted((peer_inner,peer_outer),key=lambda point:float(point@cut_direction))
                    plane_normal = peer_normal if float(peer_normal@cut_direction)>0 else -peer_normal
                    plane_point = far if owner == a else near-gap*plane_normal
                    parts[i][1] = _endcut(parts[i][1],plane_point,plane_normal,K)
                    end = max(float((np.array(v.toTuple())-P)@cut_direction) for v in parts[i][1].Vertices())
                else:
                    parts[i][1] = _endcut(parts[i][1],P+end*cut_direction,cut_direction,K)
                parent_end = straight_end(i,corner)
                start = float((parent_end[0][0]-P)@cut_direction) if parent_end is not None else 0.
                if depths[i] == 0:
                    parts[i][0] = _endcut(parts[i][0],P,cut_direction,K)
                elif abs(start-end) < _TOL:
                    parts[i][0] = _endcut(parts[i][0],P+end*cut_direction,cut_direction,K)
                else:
                    parts[i][0] = _endcut(parts[i][0],P+max(start,end)*cut_direction,cut_direction,K)
                continue
            if sheet_joint and f.get('hem') and depths[i]==0:
                # The bend starts on the real plate edge. Miter extensions
                # here overlap after development when K<0.5 and gap=0.
                # Keep the root turn square; the inward return still receives
                # the sheet-style miter shared with its neighbour.
                sign=1 if owner==a else -1
                parts[i][0]=_endcut(parts[i][0],P,eff[other]['m'],K)
                parts[i][1]=_miter(parts[i][1],P,N,sign,gap/2,K,K)
                continue
            if vertical_pair:
                # Upright panels end square to their edge, not on a 45-degree
                # plane through their thickness. Both sides get equal clearance.
                offset = float(peer_profile[:,0].min())-gap/math.sqrt(2)
                parts[i][1] = _endcut(parts[i][1],P+offset*eff[other]['m'],eff[other]['m'],K)
                if depths[i] == 0:
                    # The first bend follows the real plate edge. Extending its
                    # curved cross section creates artificial bulges in corners.
                    parts[i][0] = _endcut(parts[i][0],P,eff[other]['m'],K)
                else:
                    sign = 1 if owner == a else -1
                    parts[i][0] = _miter(parts[i][0],P,N,sign,gap/2,K,K)
                    relieve_bend(i,corner)
                continue
            if not matching:
                capped = straight_end(i,corner)
                peer_cap = straight_end(peer,corner) if peer is not None else None
                neighbors = (peer_cap[1] if peer_cap is not None else raw[peer] if peer is not None else
                             [piece for j in parts if owners[j] == other and depths[j] < depths[i] for piece in parts[j]])
                if capped is not None and not overlap(capped[1],neighbors):
                    # A common root does not imply a common corner at every
                    # level. Non-intersecting returns keep straight end faces.
                    parts[i] = [_endcut(piece,*capped[0],K) for piece in parts[i]]
                    continue
            if peer is None and legacy_parallel:
                capped = straight_end(i,corner)
                root = eff[owner]
                axis = _unit(root['p1']-root['p0'])
                outward = axis if np.linalg.norm(P-root['p1']) < np.linalg.norm(P-root['p0']) else -axis
                plane = capped[0] if capped is not None else (P,outward)
                parts[i] = [_endcut(piece,*plane,K) for piece in parts[i]]
                continue
            if peer is None:
                # Keep the same seam as the preceding bend while a box is
                # assembled one edge at a time. A missing peer is not a wall
                # at the old base width and must not truncate the return.
                sign = 1 if owner == a else -1
                parts[i] = [_miter(part, P, N, sign, gap/2, K, K) for part in parts[i]]
                continue
            sign = 1 if owner == a else -1
            # The retained diagonal mode is needed to replay existing projects.
            parts[i] = [_miter(part,P,N,sign,gap/2,K,K) for part in parts[i]]
            relieve_bend(i,corner)
    if legacy_parallel:
        # Retained only for mapping edits from pre-0.4.8 project baselines.
        # A butt seam has a through wall and a wall ending against it. Trim
        # the latter against the real neighbouring material, including bends
        # on preceding levels; a fixed diagonal plane cannot describe it.
        for P,a,b,_ in corners:
            root = eff[b]
            axis = _unit(root['p1']-root['p0'])
            outward = axis if np.linalg.norm(P-root['p1']) < np.linalg.norm(P-root['p0']) else -axis
            tools = [tool for j in parts if owners[j]==a for piece in parts[j]
                     for tool in ((piece,piece.translate(tuple(-gap*outward))) if gap>_TOL else (piece,))]
            for i in parts:
                if owners[i] != b:
                    continue
                trimmed = []
                for piece in parts[i]:
                    bb = piece.BoundingBox()
                    candidates = []
                    for tool in tools:
                        cb = tool.BoundingBox()
                        if all(min(getattr(bb,d+'max'),getattr(cb,d+'max')) >
                               max(getattr(bb,d+'min'),getattr(cb,d+'min'))+_TOL for d in 'xyz'):
                            candidates.append(tool)
                    trimmed.append(kernel.boolean('subtract',piece,candidates) if candidates else piece)
                parts[i] = trimmed
    for i in parts:
        # Corner cuts must not silently shorten a flange until its requested
        # free end disappears (e.g. inward returns longer than the box opening).
        end, _, _, direction = (_hem_end_geom(eff[i], 'out', t) if eff[i].get('hem') else _tip_geom(eff[i], 'out', t))
        vertices = [np.array(v.toTuple()) for v in parts[i][-1].Vertices()
                    if abs(float((np.array(v.toTuple())-end) @ direction)) < _TOL]
        axis = _unit(eff[i]['p1']-eff[i]['p0'])
        if len(vertices) < 2 or np.ptp([float(v @ axis) for v in vertices]) < _TOL:
            raise kernel.CadError("Narożniki zabierają cały koniec kołnierza. Zmniejsz jego długość albo zmień kierunek gięcia.")
    return parts


def _build_corner_sheet(base, recipe, eff, corners, parallel_version=3):
    specs, t = recipe['flanges'], float(recipe['t'])
    rules = recipe.get('rules') or {}
    parts = _corner_parts(recipe, eff, corners,parallel_version)
    roots = [part for i in parts if specs[i]['kind'] == 'base' for part in parts[i]]
    shape = _join_sheet(base, roots)
    relief = rules.get('relief', 'none')
    size = float(rules.get('relief_size', 0))
    if relief != 'none' and size > 0:
        for i, s in enumerate(specs):
            if s['kind'] == 'base':
                direction = _unit(_arr(s['p1']) - _arr(s['p0']))
                for point in (s['p0'], s['p1']):
                    shape = relief_cut(shape, point, direction, eff[i]['n'], relief, size)
    shape = _join_sheet(shape, [part for i in parts if specs[i]['kind'] == 'tip' for part in parts[i]])
    if len(shape.Solids()) != 1:
        raise kernel.CadError("Gięcia nie tworzą jednej połączonej blachy. Sprawdź długości, promienie i narożniki.")
    return shape


def build_sheet(recipe, parallel_version=3):
    """Blacha od podstaw: płyta bazowa + kołnierze z listy + ukosy i szczeliny w narożach + wycięcia w narożnikach."""
    if parallel_version not in (1,2,3):
        raise kernel.CadError('Nieobsługiwana wersja konstrukcji narożników równoległych.')
    base = base_solid(recipe['base'])
    t = float(recipe['t'])
    if not math.isfinite(t) or t <= 0 or not math.isclose(t, float(recipe['base']['lz']), rel_tol=1e-6, abs_tol=1e-6):
        raise kernel.CadError("Grubość blachy musi odpowiadać grubości płyty bazowej.")
    rules = recipe.get('rules') or {}
    gap = float(rules.get('gap', 0.0))
    relief = rules.get('relief', 'none')
    rsize = float(rules.get('relief_size', 0.0))
    if not math.isfinite(rsize) or rsize < 0:
        raise kernel.CadError("Wielkość wycięcia musi być nieujemną liczbą.")
    miter = bool(rules.get('miter', True))
    joint = rules.get('joint', 'parallel')
    if joint not in ('parallel', 'diagonal', 'sheet'):
        raise kernel.CadError("Nieznany sposób łączenia kołnierzy w narożniku.")
    outside = bool(rules.get('outside', False))
    if relief not in RELIEFS:
        raise kernel.CadError("Nieznany rodzaj wycięcia w narożniku.")
    if not math.isfinite(gap) or gap < 0:
        raise kernel.CadError("Szczelina między kołnierzami nie może być ujemna.")
    specs = recipe.get('flanges') or []
    _validate_specs(specs, t)
    for s in specs:
        _check_numbers(float(s['r']), float(s['angle']), float(s['length']))
    if not specs:
        return base
    eff, corners = _effective(specs, t, miter, outside)
    if corners:
        return _build_corner_sheet(base, recipe, eff, corners,parallel_version)
    pieces = {}
    for i, f in enumerate(eff):
        if f.get('hem'):
            pieces[i] = hem_solid(tuple(f['p0']), tuple(f['p1']), t, tuple(f['n']), tuple(f['m']), f['r'],
                                  f['hem']['ret'], f['hem']['gap'])
        else:
            pieces[i] = flange_solid(tuple(f['p0']), tuple(f['p1']), t, tuple(f['n']), tuple(f['m']), f['r'], f['angle'], f['length'])
    base_idx = [i for i, s_ in enumerate(specs) if s_['kind'] == 'base']
    tip_idx = [i for i, s_ in enumerate(specs) if s_['kind'] != 'base']
    shape = base
    if base_idx:
        shape = _join_sheet(shape, [pieces[i] for i in base_idx])
    # wycięcie w narożniku tylko w warstwie płyt (dolnej): kołnierze wyższych warstw go nie przecinają
    if relief != 'none' and rsize > 0:
        for i in base_idx:
            d = _unit(_arr(specs[i]['p1']) - _arr(specs[i]['p0']))
            for P in (_arr(specs[i]['p0']), _arr(specs[i]['p1'])):
                shape = relief_cut(shape, P, d, eff[i]['n'], relief, rsize)
    if tip_idx:
        shape = _join_sheet(shape, [pieces[i] for i in tip_idx])
    if len(shape.Solids()) != 1:
        raise kernel.CadError("Gięcia nie tworzą jednej połączonej blachy. Sprawdź krawędzie i wycięcia.")
    return kernel.valid(shape)


def spec_for_edge(base, t, specs, rules, mid, tol):
    """Kołnierz na wybranej krawędzi: krawędź końca istniejącego kołnierza („tip”) albo krawędź płyty („base”)."""
    rules = rules or {}
    _validate_specs(specs, t)
    eff, corners = _effective(specs, t, bool(rules.get('miter', True)), bool(rules.get('outside', False)))
    if corners:
        eff, _, _, _ = _corner_layout(specs, eff, corners, t)
    tol = min(float(tol), float(t) * .25)
    mid = _arr(mid)
    taken_tips = {int(s['parent']) for s in specs if s['kind'] == 'tip'}
    # wybieramy najbliższą krawędź (tolerancja nie może być większa niż grubość, inaczej trafiamy w sąsiednią krawędź)
    best = None
    for i, f in enumerate(eff):
        for side in ('in', 'out'):
            if i in taken_tips:
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
        # Górna i dolna krawędź to ten sam fizyczny koniec blachy.
        if any(s['kind'] == 'base' and _same_end(s, a, b, t) for s in specs):
            continue
        n, m = edge_side(shape, e, t)
        return dict(kind='base', p0=[float(x) for x in a], p1=[float(x) for x in b], n=[float(x) for x in n], m=[float(x) for x in m])
    raise kernel.CadError("Nie rozpoznano krawędzi blachy. Kliknij krawędź płyty albo krawędź kołnierza.")


def flat_pattern(recipe):
    """Develop untrimmed edge-flange chains in mm using BA = angle * (R + K*t).

    Corner miters/reliefs and hems need a separate neutral-surface development;
    refuse them rather than exporting a plausible but incorrect laser contour.
    The returned solid has unit height solely for robust planar Boolean operations.
    """
    build_sheet(recipe)  # Includes connectivity and self-intersection checks.
    base, t = recipe['base'], float(recipe['t'])
    specs, rules = recipe.get('flanges') or [], recipe.get('rules') or {}
    kfactor = float(rules.get('kfactor', K_DEFAULT))
    if not math.isfinite(kfactor) or not 0 <= kfactor <= .5:
        raise kernel.CadError("Współczynnik K musi być w zakresie 0–0,5; dobierz go do materiału i giętarki.")
    eff, corners = _effective(specs, t, bool(rules.get('miter', True)), bool(rules.get('outside', False)))
    if corners or rules.get('relief', 'none') != 'none' or any(s.get('hem') for s in specs):
        raise kernel.CadError("Rozwinięcie DXF obsługuje niezależne łańcuchy kołnierzy bez zawinięć, ukosów i wycięć narożnych. Tego modelu nie można jeszcze bezpiecznie rozwinąć.")
    origin, x, y = _arr(base['o']), _unit(base['x']), _unit(base['y'])

    def xy(point):
        v = _arr(point) - origin
        return np.array([v @ x, v @ y], dtype=float)

    def slab(points):
        return cq.Workplane('XY').polyline([tuple(map(float, p)) for p in points]).close().extrude(1).val()

    blank = cq.Workplane('XY').box(base['lx'], base['ly'], 1, centered=False).val()
    frames, bends = [], []
    for i, (s, f) in enumerate(zip(specs, eff)):
        if s['kind'] == 'base':
            a, b = xy(f['p0']), xy(f['p1'])
            outward = np.array([f['m'] @ x, f['m'] @ y])
            direction = 1 if f['n'] @ _unit(base['z']) > 0 else -1
        else:
            parent = frames[s['parent']]
            par = eff[s['parent']]
            d3 = _unit(par['p1'] - par['p0'])
            d2 = (parent['b'] - parent['a']) / np.linalg.norm(parent['b'] - parent['a'])
            # _frame may reverse the edge axis; preserve endpoint correspondence.
            a = parent['end_a'] + float((f['p0'] - par['p0']) @ d3) * d2
            b = parent['end_a'] + float((f['p1'] - par['p0']) @ d3) * d2
            outward = parent['outward']
            # 'in' means towards the inner side of the preceding bend.
            direction = parent['direction'] * (1 if s['side'] == 'in' else -1)
        allowance = math.radians(f['angle']) * (f['r'] + kfactor * t)
        travel = allowance + f['length']
        end_a, end_b = a + travel * outward, b + travel * outward
        part = slab([a, b, end_b, end_a])
        blank = _join_sheet(blank, [part])
        frames.append(dict(a=a, b=b, end_a=end_a, end_b=end_b, outward=outward, direction=direction))
        bends.append(dict(index=i + 1, angle=f['angle'], radius=f['r'], allowance=allowance,
                          direction='UP' if direction > 0 else 'DOWN',
                          a=(a + allowance / 2 * outward).tolist(), b=(b + allowance / 2 * outward).tolist()))
    if len(blank.Solids()) != 1:
        raise kernel.CadError("Rozwinięcie nie tworzy jednej połączonej części.")
    return dict(shape=blank, bends=bends, thickness=t, kfactor=kfactor, area=blank.Volume())


def clip_line_to_faces(a, b, faces, min_length=1e-4):
    """Odcinek a-b (linia gięcia na rozwinięciu) przycięty do obrysu płaskich ścian: zwraca listę (początek, koniec) części leżących
    w materiale, w kolejności od a do b. Linia gięcia nie może wychodzić poza kontur cięcia (wycięcia, ukosy i szczeliny w narożnikach)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    span = float(np.linalg.norm(d[:2]))
    if span < min_length:
        return []
    pieces = []
    for face in faces:
        z = float(face.Center().z)
        edge = cq.Edge.makeLine(cq.Vector(float(a[0]), float(a[1]), z), cq.Vector(float(b[0]), float(b[1]), z))
        try:
            common = edge.intersect(face)
        except Exception:
            continue
        for piece in common.Edges():
            if piece.Length() < min_length:
                continue
            ends = [np.array(piece.startPoint().toTuple(), float), np.array(piece.endPoint().toTuple(), float)]
            ts = sorted(float((q[:2] - a[:2]) @ d[:2]) / (span * span) for q in ends)
            pieces.append((max(0.0, ts[0]), min(1.0, ts[1])))
    pieces.sort()
    merged = []
    for t0, t1 in pieces:            # części stykające się (np. na granicy dwóch ścian) łączą się w jedną linię
        if merged and t0 <= merged[-1][1] + min_length / span:
            merged[-1] = (merged[-1][0], max(merged[-1][1], t1))
        else:
            merged.append((t0, t1))
    return [(a + d * t0, a + d * t1) for t0, t1 in merged if (t1 - t0) * span >= min_length]


def export_flat_dxf(recipe, path, expected_shape=None):
    """Atomic, 1:1 millimetre DXF: closed CUT contours, non-cutting bend lines."""
    import os
    from pathlib import Path
    import tempfile
    import ezdxf

    if expected_shape is not None:
        folded = build_sheet(recipe)
        tolerance = max(1e-4, folded.Volume() * 1e-8)
        if (abs(folded.Volume() - expected_shape.Volume()) > tolerance or
                folded.cut(expected_shape).Volume() > tolerance or expected_shape.cut(folded).Volume() > tolerance):
            raise kernel.CadError("Bryła zmieniła się poza operacjami blachy. Rozwinięcie nie uwzględnia tych zmian; eksport został zatrzymany.")
    pattern = flat_pattern(recipe)
    doc = ezdxf.new('R2010')
    doc.units = ezdxf.units.MM
    for layer, color in [('CUT', 7), ('BEND_UP', 1), ('BEND_DOWN', 5)]:
        doc.layers.new(layer, dxfattribs={'color': color})
    space = doc.modelspace()
    top = next(f for f in pattern['shape'].Faces() if f.normalAt().z > .99)
    for wire in top.Wires():
        # All supported developed outlines are straight. Wire traversal keeps the contour ordered.
        from OCP.BRepTools import BRepTools_WireExplorer
        explorer = BRepTools_WireExplorer(wire.wrapped)
        points = []
        while explorer.More():
            v = cq.Vertex(explorer.CurrentVertex())
            points.append((v.X, v.Y))
            explorer.Next()
        space.add_lwpolyline(points, close=True, dxfattribs={'layer': 'CUT'})
    for bend in pattern['bends']:
        for start, end in clip_line_to_faces(bend['a'], bend['b'], [top]):      # linia gięcia tylko w obrysie blachy
            line = space.add_line(tuple(start), tuple(end), dxfattribs={'layer': 'BEND_' + bend['direction']})
            doc.appids.add('RCCAD') if 'RCCAD' not in doc.appids else None
            line.set_xdata('RCCAD', [(1070, bend['index']), (1040, bend['angle']), (1040, bend['radius']),
                                    (1040, pattern['thickness']), (1040, pattern['kfactor'])])
    target = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.rccad-flat-', suffix='.dxf', dir=target.parent)
    os.close(fd)
    try:
        doc.saveas(temporary)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return pattern


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
