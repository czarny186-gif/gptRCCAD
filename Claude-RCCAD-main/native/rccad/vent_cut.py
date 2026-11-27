"""Wentylacja - bryły narzędzi (CuttingToolBuilder), głębokość i kierunek, operacje Boolean (BooleanProcessor),
kontrola wyniku i statystyki (PatternStatistics).

Narzędzie otworu:
  * profil płaski w płaszczyźnie stycznej w środku otworu (zachowanie kształtu) - graniastosłup BRepPrimAPI_MakePrism
    albo loft przekrojów (BRepOffsetAPI_ThruSections) dla otworów stożkowych, stopniowanych, fazowanych, zaokrąglonych,
    o zmiennym przekroju;
  * albo profil odwzorowany na powierzchnię (zachowanie odstępów / proporcji) - obrys przeniesiony punkt po punkcie na
    ścianę i loft prostokreślny wzdłuż lokalnych normalnych.
Głębokość „przez lokalną ściankę”: promień od powierzchni w kierunku otworu (IntCurvesFace_ShapeIntersector) - pierwsze
wyjście z materiału; narzędzie kończy się tuż za nim, więc nie sięga przeciwległej ścianki. Gdy grubość w obrębie otworu
jest niejednoznaczna albo za ścianką jest element (słupek, żebro, przegroda) - otwór jest oznaczany i pomijany.
Cięcie: jedna operacja BRepAlgoAPI_Cut ze wszystkimi narzędziami (równolegle, prefiltr OBB), partiami przy bardzo dużej
liczbie; żaluzje - łopatki dołączane BRepAlgoAPI_Fuse."""
from __future__ import annotations

import math

import numpy as np

from . import kernel
from . import vent_shapes as vs

DIRECTIONS = ('normal', 'x', 'y', 'z', 'edge', 'axis', 'vector', 'angle', 'radial')
DIRECTION_LABELS = {'normal': 'Prostopadle do lokalnej powierzchni', 'x': 'Wzdłuż osi X', 'y': 'Wzdłuż osi Y', 'z': 'Wzdłuż osi Z',
                    'edge': 'Wzdłuż wskazanej krawędzi', 'axis': 'Wzdłuż wskazanej osi', 'vector': 'Wektor użytkownika',
                    'angle': 'Pod kątem do powierzchni', 'radial': 'Promieniowo względem osi'}
DEPTHS = ('wall', 'next', 'face', 'plane', 'depth', 'through', 'both', 'symmetric')
DEPTH_LABELS = {'wall': 'Przez lokalną ściankę', 'next': 'Do następnej powierzchni', 'face': 'Do wskazanej powierzchni',
                'plane': 'Do wskazanej płaszczyzny', 'depth': 'Na zadaną głębokość', 'through': 'Przez całą bryłę',
                'both': 'W dwóch kierunkach', 'symmetric': 'Symetrycznie względem powierzchni'}
HOLE_TYPES = ('through', 'blind', 'recess', 'conical', 'stepped', 'tilted', 'variable', 'chamfer1', 'chamfer2', 'rounded',
              'widen_in', 'widen_out', 'channel', 'louver_out', 'louver_in')
HOLE_TYPE_LABELS = {'through': 'Przelotowy', 'blind': 'Ślepy', 'recess': 'Zagłębienie dekoracyjne', 'conical': 'Stożkowy (wejście / wyjście)',
                    'stepped': 'Stopniowany', 'tilted': 'Ukośny', 'variable': 'O zmiennym przekroju', 'chamfer1': 'Fazowanie jednostronne',
                    'chamfer2': 'Fazowanie dwustronne', 'rounded': 'Zaokrąglone krawędzie', 'widen_in': 'Rozszerzający się do wnętrza',
                    'widen_out': 'Rozszerzający się na zewnątrz', 'channel': 'Kanał pod kątem', 'louver_out': 'Żaluzje wystające',
                    'louver_in': 'Żaluzje zagłębione'}
EPS = .05                                                              # wysunięcie narzędzia ponad powierzchnię i za ściankę [mm]


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


class Thickness:
    """Grubość ścianki wzdłuż promienia: IntCurvesFace_ShapeIntersector na bryle (wczytanej raz)."""

    def __init__(self, solid):
        from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
        self.ix = IntCurvesFace_ShapeIntersector()
        self.ix.Load(solid, 1e-6)
        self.solid = solid

    def hits(self, P, d, reach=1e4):
        from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
        self.ix.Perform(gp_Lin(gp_Pnt(*map(float, P)), gp_Dir(*map(float, d))), 1e-4, float(reach))
        if not self.ix.IsDone():
            return []
        return sorted(self.ix.WParameter(i) for i in range(1, self.ix.NbPnt() + 1))

    def wall(self, P, d):
        """Odległość do pierwszego wyjścia z materiału idąc od P (na powierzchni) w kierunku d (do wnętrza): promień
        startuje tuż pod powierzchnią (1 µm w materiale), więc nie trafia w ścianę wejścia."""
        h = self.hits(np.asarray(P, float) + _unit(d) * 1e-3, d)
        return h[0] + 1e-3 if h else None


def direction(hole, P, N, X, p, axis=None):
    """Kierunek wykonania otworu (do wnętrza bryły)."""
    mode = p.get('direction', 'normal')
    if hole.get('dir') is not None:
        d = _unit(hole['dir'])
    elif mode == 'normal':
        d = -N
    elif mode in ('x', 'y', 'z'):
        d = np.eye(3)['xyz'.index(mode)].copy()
        if float(d @ N) > 0:
            d = -d
    elif mode in ('edge', 'axis', 'vector'):
        d = _unit(p.get('vector') or (axis[1] if axis is not None else [0, 0, -1.0]))
        if float(d @ N) > 0:
            d = -d
    elif mode == 'angle':
        a = math.radians(min(90.0, max(5.0, float(p.get('dir_angle', 60.0)))))   # kąt między osią otworu a powierzchnią
        d = _unit(-N * math.sin(a) + _unit(X) * math.cos(a))
    elif mode == 'radial':
        if axis is None:
            raise kernel.CadError('Kierunek promieniowy: wskaż oś.')
        o, a = np.asarray(axis[0], float), _unit(axis[1])
        r = P - o
        r = r - a * float(r @ a)
        d = _unit(r)
        if float(d @ N) > 0:
            d = -d
    else:
        raise kernel.CadError('Nieznany kierunek otworów.')
    tilt = float(hole.get('tilt', 0.0)) + (float(p.get('tilt', 0.0)) if p.get('hole_type') in ('tilted', 'channel') else 0.0)
    if abs(tilt) > 1e-9:                                                # nachylenie względem lokalnej osi Y otworu
        Y = _unit(np.cross(N, X))
        d = _unit(_rotate(d, Y, math.radians(tilt)))
    if p.get('reverse'):
        d = -d
    return d


def _rotate(v, k, a):
    k = _unit(k)
    return v * math.cos(a) + np.cross(k, v) * math.sin(a) + k * float(k @ v) * (1 - math.cos(a))


def depth_of(hole, P, d, p, thick, ref=None):
    """(przód, tył, informacja): długość narzędzia za powierzchnią (w kierunku d) i przed nią."""
    mode = p.get('depth_mode', 'wall')
    k = float(hole.get('depth_k', 1.0))
    if mode in ('wall', 'next'):
        t = thick.wall(P, d)
        if t is None:
            return None, 0.0, 'brak drugiej strony ścianki w kierunku otworu'
        return t * (1 if p.get('hole_type') not in ('blind', 'recess') else 0) + (float(p['depth']) * k if p.get('hole_type') in ('blind', 'recess') else 0), EPS, ''
    if mode == 'face':
        if ref is None:
            raise kernel.CadError('Głębokość do powierzchni: wskaż powierzchnię końcową.')
        from OCP.IntCurvesFace import IntCurvesFace_Intersector
        from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
        ix = IntCurvesFace_Intersector(ref, 1e-6)
        ix.Perform(gp_Lin(gp_Pnt(*map(float, P)), gp_Dir(*map(float, d))), -1e-3, 1e5)
        if not ix.IsDone() or ix.NbPnt() == 0:
            return None, 0.0, 'kierunek otworu nie trafia we wskazaną powierzchnię'
        return min(ix.WParameter(i) for i in range(1, ix.NbPnt() + 1)) * k, EPS, ''
    if mode == 'plane':
        o, n = (np.asarray(x, float) for x in (p.get('plane') or ((0, 0, 0), (0, 0, 1))))
        den = float(d @ n)
        if abs(den) < 1e-9:
            return None, 0.0, 'kierunek równoległy do płaszczyzny końcowej'
        t = float((o - P) @ n) / den
        return (t * k, EPS, '') if t > 0 else (None, 0.0, 'płaszczyzna końcowa po złej stronie')
    if mode == 'depth':
        return float(p['depth']) * k, EPS, ''
    if mode == 'through':
        h = thick.hits(np.asarray(P, float) + d * 1e-3, d)
        return (h[-1] + EPS if h else float(p['depth'])), EPS, ''
    if mode == 'both':
        return float(p['depth']) * k, float(p.get('depth2', p['depth'])) * k, ''
    if mode == 'symmetric':
        return float(p['depth']) * k / 2, float(p['depth']) * k / 2, ''
    raise kernel.CadError('Nieznany tryb głębokości.')


def _wire_from(loops, frame):
    """Ściana profilu w płaszczyźnie (o, x, y) - współrzędne profilu względem środka otworu."""
    o, x, y, n = frame
    return vs.occ_face(loops, lambda q: o + x * q[0] + y * q[1], (o, n))


def _offset_face(face, d):
    """Profil płaski odsunięty w swojej płaszczyźnie o d (BRepOffsetAPI_MakeOffset, łączenie łukami); d < 0 - do środka."""
    if abs(d) < 1e-9:
        return face
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.GeomAbs import GeomAbs_Arc
    mk = BRepOffsetAPI_MakeOffset(face, GeomAbs_Arc)
    mk.Perform(float(d))
    if not mk.IsDone():
        raise kernel.CadError('Odsunięcie profilu (fazowanie / zaokrąglenie) nie powiodło się - zmniejsz wartość.')
    from OCP.TopAbs import TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    ex = TopExp_Explorer(mk.Shape(), TopAbs_WIRE)
    if not ex.More():
        raise kernel.CadError('Odsunięcie profilu nie dało konturu - zmniejsz fazowanie / zaokrąglenie.')
    return BRepBuilderAPI_MakeFace(TopoDS.Wire_s(ex.Current()), True).Face()


def _outer_wire(face):
    from OCP.BRepTools import BRepTools
    return BRepTools.OuterWire_s(face)


def _moved(shape, v):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Vec
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(*map(float, v)))
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


def _scaled(face, centre, k):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Pnt, gp_Trsf
    t = gp_Trsf()
    t.SetScale(gp_Pnt(*map(float, centre)), float(k))
    return BRepBuilderAPI_Transform(face, t, True).Shape()


def tool(hole, mapping, p, thick, axis=None, ref=None):
    """Bryła narzędzia otworu (TopoDS_Shape) i informacja; None gdy otworu nie da się wykonać (z powodem)."""
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    from OCP.TopoDS import TopoDS
    c = np.asarray(hole['c'], float)
    P, N, X, Y = mapping.to3d(c)
    d = direction(hole, P, N, X, p, axis)
    front, back, why = depth_of(hole, P, d, p, thick, ref)
    if front is None:
        return None, why
    ht = p.get('hole_type', 'through')
    # obrys na powierzchni: narzędzie zaczyna się nad wszystkimi punktami obrysu (pochylenie, krzywizna) i - przy
    # wycięciu przez ściankę - kończy za wyjściem w każdym z nich; rozrzut grubości = niejednoznaczna ścianka
    through_wall = p.get('depth_mode', 'wall') in ('wall', 'next') and ht not in ('blind', 'recess')
    ring = vs.sample_loop(hole['loops'][0], 8)
    ups, exits = [], []
    for q in ring:
        try:
            S, Ns, _x, _y = mapping.to3d(q)
        except kernel.CadError:
            continue
        ups.append(float((S - P) @ -d))
        if through_wall:
            ts = thick.wall(S, d)
            if ts is not None:
                exits.append(float((S - P) @ d) + ts)
    if ups:
        back = max(back, max(ups) + EPS)
    if through_wall:
        if exits:
            spread = max(exits) - min(exits)
            if spread > max(.3, .25 * front) and spread > 1e-6:
                hole['ambiguous'] = spread
            front = max([front] + exits)
        front += EPS
    # profil: lokalny układ (styczny) - współrzędne względem środka otworu
    loc = vs.place(hole['loops'], -c, 0.0)
    if p.get('profile_mode', 'tangent') == 'mapped' and mapping.mode not in ('plane',):
        return _mapped_tool(hole, mapping, d, front, back, p), ''
    Yt = _unit(np.cross(-d, X)) if abs(float(_unit(X) @ d)) < .999 else Y
    Xt = _unit(np.cross(Yt, -d))
    base = P - d * back                                                # początek narzędzia nad powierzchnią
    frame = (base, Xt, Yt, -d)
    face = _wire_from(loc, frame)
    L = front + back
    simple = ht in ('through', 'blind', 'recess', 'tilted', 'channel') or (ht in ('chamfer1', 'chamfer2', 'rounded') and float(p.get('chamfer', 0)) <= 0)
    if simple:
        return BRepPrimAPI_MakePrism(face, gp_Vec(*map(float, d * L))).Shape(), ''
    sections = []                                                       # (odległość od początku, mnożnik skali | odsunięcie)
    s_in, s_out = float(p.get('size_in', 1.0)), float(p.get('size_out', .6))
    ch = float(p.get('chamfer', .5))
    if ht in ('conical', 'widen_out', 'widen_in'):
        if ht == 'widen_out':
            s_in, s_out = max(s_in, 1.0) * 1.0, min(s_out, 1.0)
        elif ht == 'widen_in':
            s_in, s_out = min(s_in, s_out), max(s_in, s_out)
        sections = [(0.0, ('scale', s_in)), (L, ('scale', s_out))]
    elif ht == 'variable':
        sections = [(0.0, ('scale', s_in)), (L / 2, ('scale', float(p.get('size_mid', .7)))), (L, ('scale', s_out))]
    elif ht == 'stepped':
        st = min(float(p.get('step_depth', front / 2)), L * .9) + back
        k = float(p.get('step_scale', 1.6))
        return _stepped(face, frame, d, L, st, k), ''
    elif ht in ('chamfer1', 'chamfer2', 'rounded'):
        ch = min(ch, L / 2.2)
        if ht == 'rounded':
            prof = [(back + ch * (1 - math.cos(a)), ('offset', ch * (1 - math.sin(a)))) for a in np.linspace(0, math.pi / 2, 5)]
            sections = [(0.0, ('offset', ch))] + prof + [(L, ('offset', 0.0))]
        else:
            sections = [(0.0, ('offset', ch)), (back + ch, ('offset', 0.0))]
            if ht == 'chamfer2':
                sections += [(L - ch - EPS, ('offset', 0.0)), (L, ('offset', ch))]
            else:
                sections += [(L, ('offset', 0.0))]
    mk = BRepOffsetAPI_ThruSections(True, True, 1e-6)
    last = None
    for z, (kind, val) in sections:
        if last is not None and z <= last + 1e-6:
            z = last + 1e-4
        last = z
        f = _scaled(face, base, val) if kind == 'scale' else _offset_face(face, val)
        mk.AddWire(_outer_wire(TopoDS.Face_s(_moved(f, d * z))))
    mk.CheckCompatibility(True)
    mk.Build()
    if not mk.IsDone():
        return None, 'loft przekrojów otworu nie powiódł się'
    return mk.Shape(), ''


def _stepped(face, frame, d, L, step, k):
    """Otwór stopniowany jako dwa narzędzia (szeroki płytki + wąski przelotowy) - bez osobnego Boolean na otwór."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    big = _scaled(face, frame[0], k)
    a = BRepPrimAPI_MakePrism(big, gp_Vec(*map(float, d * step))).Shape()
    b = BRepPrimAPI_MakePrism(_moved(face, d * (step - .02)), gp_Vec(*map(float, d * (L - step + .02)))).Shape()
    return [a, b]


def _mapped_tool(hole, mapping, d, front, back, p):
    """Profil odwzorowany punkt po punkcie na powierzchnię; przekroje nad powierzchnią i za ścianką wzdłuż lokalnych
    normalnych - loft prostokreślny (BRepOffsetAPI_ThruSections) przez zamknięte krzywe B-spline."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.GeomAPI import GeomAPI_Interpolate
    from OCP.TColgp import TColgp_HArray1OfPnt
    from OCP.gp import gp_Pnt
    poly = vs.sample_loop(hole['loops'][0], 48)
    pts, nrm = [], []
    for q in poly:
        P, N, _x, _y = mapping.to3d(q)
        pts.append(P)
        nrm.append(N)
    pts, nrm = np.array(pts), np.array(nrm)
    mk = BRepOffsetAPI_ThruSections(True, True, 1e-6)
    for off in (back, -front):
        Q = pts + nrm * off if p.get('direction', 'normal') == 'normal' else pts - d * (-off)
        arr = TColgp_HArray1OfPnt(1, len(Q))
        for i, q in enumerate(Q):
            arr.SetValue(i + 1, gp_Pnt(*map(float, q)))
        it = GeomAPI_Interpolate(arr, True, 1e-7)
        it.Perform()
        mk.AddWire(BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(it.Curve()).Edge()).Wire())
    mk.Build()
    if not mk.IsDone():
        raise kernel.CadError('Narzędzie odwzorowanego otworu nie powstało.')
    return mk.Shape()


def louver(hole, mapping, p, thick):
    """Żaluzja: szczelina przez ściankę + łopatka (płyta grubości t, wysokości h, pod kątem, na krawędzi szczeliny po
    stronie kierunku otwarcia) - prawdziwa geometria 3D (wystająca albo zagłębiona). Zwraca (narzędzie, łopatka)."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    c = np.asarray(hole['c'], float)
    P, N, X, Y = mapping.to3d(c)
    ang = float(hole.get('angle', 0.0))
    xa = _unit(X * math.cos(ang) + Y * math.sin(ang))
    ya = _unit(np.cross(N, xa))
    t = thick.wall(P, -N)
    if t is None:
        return None, None, 'brak drugiej strony ścianki'
    L, W = float(hole['w']), float(hole['h'])
    blade_t = float(p.get('louver_t', 1.0))
    a = math.radians(min(85.0, max(5.0, float(p.get('louver_angle', 35.0)))))
    H = float(p.get('louver_h', 3.0))
    side = -1.0 if p.get('louver_dir', 'up') == 'down' else 1.0
    out = p.get('hole_type', 'louver_out') == 'louver_out'
    # szczelina
    base = P + N * EPS
    frame = (base, xa, ya, N)
    loc = vs.place(hole['loops'], -c, 0.0)
    face = _wire_from(loc, frame)
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    cut = BRepPrimAPI_MakePrism(face, gp_Vec(*map(float, -N * (t + 2 * EPS)))).Shape()
    # łopatka: zawias na krawędzi szczeliny (y = side·W/2), obrót o kąt a od powierzchni na zewnątrz / do wewnątrz
    lb = H / math.sin(a)
    hinge = P + ya * side * W / 2 + (N * 0 if out else -N * t)
    dirb = _unit(-ya * side * math.cos(a) + (N if out else -N) * math.sin(a))
    nb = _unit(np.cross(xa, dirb))
    if float(nb @ (N if out else -N)) < 0:
        nb = -nb
    o = hinge - xa * L / 2 - nb * blade_t
    ax = gp_Ax2(gp_Pnt(*map(float, o)), gp_Dir(*map(float, nb)), gp_Dir(*map(float, xa)))
    blade = BRepPrimAPI_MakeBox(ax, float(L), float(lb), float(blade_t)).Shape()
    # oś Y pudełka = nb × xa; łopatka ma iść w kierunku dirb
    yb = np.cross(nb, xa)
    if float(yb @ dirb) < 0:
        ax = gp_Ax2(gp_Pnt(*map(float, o + xa * L)), gp_Dir(*map(float, nb)), gp_Dir(*map(float, -xa)))
        blade = BRepPrimAPI_MakeBox(ax, float(L), float(lb), float(blade_t)).Shape()
    return cut, blade, ''


# ---------------------------------------------------------------------------------------------- Boolean i kontrola
def cut_many(shape, tools, batch=3000, cancel=None, progress=None, track=None):
    """Cięcie wieloma narzędziami: jedna operacja BRepAlgoAPI_Cut (równolegle, OBB) na partię narzędzi. track - lista
    ścian, których następniki (historia Modified) są zwracane jako drugi wynik (pole powierzchni otwartej)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.TopTools import TopTools_ListOfShape
    flat = []
    for t in tools:
        flat += t if isinstance(t, list) else [t]
    tools = flat
    cur = shape
    tracked = list(track or [])
    for i in range(0, len(tools), batch):
        if cancel is not None and cancel():
            raise kernel.CadError('Wycinanie przerwane - model bez zmian.')
        args, tl = TopTools_ListOfShape(), TopTools_ListOfShape()
        args.Append(cur)
        for t in tools[i:i + batch]:
            tl.Append(t)
        op = BRepAlgoAPI_Cut()
        op.SetArguments(args)
        op.SetTools(tl)
        op.SetRunParallel(True)
        op.SetUseOBB(True)
        op.SetNonDestructive(True)
        op.Build()
        if not op.IsDone():
            raise kernel.CadError('Wycięcie otworów nie powiodło się (BRepAlgoAPI_Cut).')
        cur = op.Shape()
        if track is not None:
            nxt = []
            for f in tracked:
                if op.IsDeleted(f):
                    continue
                mod = op.Modified(f)
                if mod.Size() == 0:
                    nxt.append(f)
                else:
                    nxt += list(mod)
            tracked = nxt
        if progress is not None:
            progress(min(1.0, (i + batch) / max(len(tools), 1)))
    return (cur, tracked) if track is not None else cur


def _tool_boxes(tools):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    out = np.empty((len(tools), 6))
    for i, t in enumerate(tools):
        b = Bnd_Box()
        BRepBndLib.Add_s(t, b, False)
        out[i] = b.Get()
    return out


def _partition(B, idx, lo, hi, target, leaves, depth=0):
    """Podział przestrzeni na prostopadłościany wzdłuż przerw między narzędziami (żadne narzędzie nie przecina granicy)."""
    if len(idx) <= target or depth > 24:
        leaves.append((idx, lo, hi))
        return
    best = None
    for ax in range(3):
        a, b = B[idx, ax], B[idx, ax + 3]
        order = np.argsort(a)
        run = np.maximum.accumulate(b[order])
        gaps = np.nonzero(a[order][1:] > run[:-1] + .05)[0]            # między k i k+1 - wolny pas
        if not len(gaps):
            continue
        k = gaps[np.argmin(np.abs(gaps + 1 - len(idx) / 2))]
        bal = abs(k + 1 - len(idx) / 2)
        if best is None or bal < best[0]:
            best = (bal, ax, (run[k] + a[order][k + 1]) / 2, idx[order[:k + 1]], idx[order[k + 1:]])
    if best is None:
        leaves.append((idx, lo, hi))
        return
    _b, ax, x, left, right = best
    h1, l2 = hi.copy(), lo.copy()
    h1[ax] = x
    l2[ax] = x
    _partition(B, left, lo, h1, target, leaves, depth + 1)
    _partition(B, right, l2, hi, target, leaves, depth + 1)


def cut_tiled(shape, tools, target=180, cancel=None, progress=None, op='cut'):
    """Bardzo wiele otworów: cięcie i kontrola BRepCheck na kawałkach bryły (prostopadłościany rozdzielone wolnymi pasami
    między otworami - żaden otwór nie leży na granicy), potem sklejenie (Glue) i scalenie ścian (UnifySameDomain).
    Ściana z tysiącami otworów w jednym kawałku jest liczona i sprawdzana kwadratowo dłużej. Zwraca bryłę albo None
    (brak przerw między otworami albo niezgodna objętość - wtedy zwykłe cięcie)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Fuse
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BOPAlgo import BOPAlgo_GlueShift
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.TopTools import TopTools_ListOfShape
    from OCP.gp import gp_Pnt
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.ShapeFix import ShapeFix_Shape
    from .enclosure import _volume, is_valid, _CHECKED
    flat = []
    for t in tools:
        flat += t if isinstance(t, list) else [t]
    B = _tool_boxes(flat)
    bb = Bnd_Box()
    BRepBndLib.Add_s(shape, bb, False)
    g = np.array(bb.Get())
    lo, hi = g[:3] - 1.0, g[3:] + 1.0
    leaves = []
    _partition(B, np.arange(len(flat)), lo, hi, target, leaves)
    if len(leaves) < 2:
        return None
    tiles, vol = [], 0.0
    for n, (idx, a, b) in enumerate(leaves):
        if cancel is not None and cancel():
            raise kernel.CadError('Wycinanie przerwane - model bez zmian.')
        box = BRepPrimAPI_MakeBox(gp_Pnt(*map(float, a)), gp_Pnt(*map(float, b))).Shape()
        com = BRepAlgoAPI_Common(shape, box)
        if not com.IsDone():
            return None
        tile = (cut_many if op == 'cut' else fuse_batches)(com.Shape(), [flat[i] for i in idx])
        if not is_valid(tile):
            fx = ShapeFix_Shape(tile)
            fx.Perform()
            tile = fx.Shape()
            if not is_valid(tile):
                return None
        v = _volume(tile)[0]
        if v > 1e-9:
            tiles.append(tile)
            vol += v
        if progress is not None:
            progress(.9 * (n + 1) / len(leaves))
    if not tiles:
        return None
    if len(tiles) == 1:
        return tiles[0]
    args, tl = TopTools_ListOfShape(), TopTools_ListOfShape()
    args.Append(tiles[0])
    for t in tiles[1:]:
        tl.Append(t)
    fu = BRepAlgoAPI_Fuse()
    fu.SetArguments(args)
    fu.SetTools(tl)
    fu.SetGlue(BOPAlgo_GlueShift)
    fu.SetRunParallel(True)
    fu.Build()
    if not fu.IsDone():
        return None
    un = ShapeUpgrade_UnifySameDomain(fu.Shape(), False, True, False)
    un.Build()
    res = un.Shape()
    if abs(_volume(res)[0] - vol) > 1e-6 * max(vol, 1.0) + 1e-6:
        return None
    _CHECKED.append(res)                                                # kawałki sprawdzone osobno; sklejenie bez zmian geometrii
    del _CHECKED[:-8]
    return res


def trust_result(shape):
    """Wynik cięcia kawałkami: kolejne kontrole (np. przy przesunięciu bryły) nie powtarzają BRepCheck całości."""
    kernel.trust(shape)


def fuse_many(shape, parts):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.TopTools import TopTools_ListOfShape
    if not parts:
        return shape
    args, tl = TopTools_ListOfShape(), TopTools_ListOfShape()
    args.Append(shape)
    for t in parts:
        tl.Append(t)
    op = BRepAlgoAPI_Fuse()
    op.SetArguments(args)
    op.SetTools(tl)
    op.SetRunParallel(True)
    op.Build()
    if not op.IsDone():
        raise kernel.CadError('Dołączenie łopatek żaluzji nie powiodło się.')
    return op.Shape()


def fuse_batches(shape, tools, batch=3000, cancel=None, progress=None):
    """Dołączenie wielu brył jedną operacją BRepAlgoAPI_Fuse na partię (równolegle, OBB) - odpowiednik cut_many."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.TopTools import TopTools_ListOfShape
    flat = []
    for t in tools:
        flat += t if isinstance(t, list) else [t]
    cur = shape
    for i in range(0, len(flat), batch):
        if cancel is not None and cancel():
            raise kernel.CadError('Dołączanie przerwane - model bez zmian.')
        args, tl = TopTools_ListOfShape(), TopTools_ListOfShape()
        args.Append(cur)
        for t in flat[i:i + batch]:
            tl.Append(t)
        op = BRepAlgoAPI_Fuse()
        op.SetArguments(args)
        op.SetTools(tl)
        op.SetRunParallel(True)
        op.SetUseOBB(True)
        op.SetNonDestructive(True)
        op.Build()
        if not op.IsDone():
            raise kernel.CadError('Dołączenie elementów tekstury nie powiodło się (BRepAlgoAPI_Fuse).')
        cur = op.Shape()
        if progress is not None:
            progress(min(1.0, (i + batch) / max(len(flat), 1)))
    return cur


def check_result(shape, allow_islands=False, unify=True):
    """Kontrola po wycięciu: BRepCheck, liczba brył (niepołączone fragmenty), bardzo małe krawędzie i ściany. Próba
    naprawy ShapeFix_Shape przy niepoprawnej geometrii. Zwraca (bryła, raport) albo CadError."""
    from OCP.ShapeFix import ShapeFix_Shape
    from .enclosure import _solids, _volume, is_valid
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    report = []
    try:                                                                # scalenie podzielonych ścian (krawędzie bez zmian - wielokątne
        if unify:                                                       # obrysy szczelin nie są łączone w krzywe)
            un = ShapeUpgrade_UnifySameDomain(shape, False, True, False)
            un.Build()
            shape = un.Shape()
    except Exception:
        pass
    if not is_valid(shape):
        fx = ShapeFix_Shape(shape)
        fx.Perform()
        shape = fx.Shape()
        if not is_valid(shape):
            raise kernel.CadError('Wynik wycięcia nie jest poprawną bryłą B-Rep - zostaje poprzednia geometria (zmień parametry otworów).')
        report.append(('warning', 'Geometria naprawiona (ShapeFix) w granicach tolerancji.'))
    sol = [s for s in _solids(shape) if _volume(s)[0] > 1e-6]
    if not sol:
        raise kernel.CadError('Wynik wycięcia nie jest bryłą - zostaje poprzednia geometria.')
    if len(sol) > 1 and not allow_islands:
        raise kernel.CadError(f'Wzór odcina {len(sol) - 1} fragment(y) materiału - zwiększ mostki albo zezwól na fragmenty.')
    if len(sol) > 1:
        report.append(('warning', f'Wynik ma {len(sol)} rozłączne fragmenty (dozwolone).'))
    small = _small_edges(shape)
    if small:
        report.append(('warning', f'{small} bardzo małych krawędzi (< 0,01 mm).'))
    return shape, report


def _small_edges(shape, tol=1e-2):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    n = 0
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    seen = 0
    while ex.More() and seen < 200000:
        g = GProp_GProps()
        BRepGProp.LinearProperties_s(ex.Current(), g)
        if g.Mass() < tol:
            n += 1
        seen += 1
        ex.Next()
    return n // 2


def face_area(shape, faces):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    tot = 0.0
    for f in faces:
        g = GProp_GProps()
        BRepGProp.SurfaceProperties_s(f, g)
        tot += g.Mass()
    return tot
