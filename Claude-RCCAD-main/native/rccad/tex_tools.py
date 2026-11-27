"""Tekstury geometryczne - narzędzia przestrzenne (bryły elementów tekstury) budowane bezpośrednio w Open CASCADE.

Każdy element powstaje w układzie lokalnym (z - normalna powierzchni, x, y - styczne), a potem jest tylko przesuwany
(TopLoc_Location - bez kopiowania geometrii), dlatego tysiące elementów buduje się szybko. Rodzaje:
  prism   - wielokąt (z otworami) wyciągnięty wzdłuż normalnej; ze zwężeniem (piramida, ścięty stożek) i pochyleniem
  ridge   - listwa o profilu prostokątnym, trójkątnym, trapezowym albo półokrągłym wzdłuż odcinka
  dome    - bryła obrotowa: kulista, półkulista, walcowa, stożkowa (wypustka albo zagłębienie)
Dla zagłębień (sign = -1) bryła narzędzia sięga od małego naddatku nad powierzchnią w głąb, dla wypustek (sign = +1) od małego
zagłębienia w materiał (zakład gwarantuje trwałe połączenie przy sumowaniu) w górę."""
from __future__ import annotations

import math

import numpy as np

from . import kernel


def _pt(x, y, z=0.0):
    from OCP.gp import gp_Pnt
    return gp_Pnt(float(x), float(y), float(z))


def _fix(solid):
    """Bryła zawsze skierowana na zewnątrz (odbicia i obroty profilu mogą odwrócić orientację)."""
    from OCP.BRepLib import BRepLib
    from OCP.TopoDS import TopoDS
    from OCP.TopAbs import TopAbs_SOLID
    try:
        s = TopoDS.Solid_s(solid) if solid.ShapeType() == TopAbs_SOLID else solid
        BRepLib.OrientClosedSolid_s(s)
        return s
    except Exception:
        return solid


def ccw(P):
    P = np.asarray(P, float)
    x, y = P[:, 0], P[:, 1]
    return float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)) / 2


def _wire(P, z):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    mk = BRepBuilderAPI_MakePolygon()
    for q in P:
        mk.Add(_pt(q[0], q[1], z))
    mk.Close()
    return mk.Wire()


def _face(outer, holes, z):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    outer = np.asarray(outer, float)
    if ccw(outer) < 0:
        outer = outer[::-1]
    mk = BRepBuilderAPI_MakeFace(_wire(outer, z), True)
    for h in holes or ():
        h = np.asarray(h, float)
        if ccw(h) > 0:
            h = h[::-1]
        mk.Add(_wire(h, z))
    return mk.Face()


def clean_poly(P, tol=1e-6):
    """Wielokąt bez powtórzonych sąsiednich punktów (BRepBuilderAPI_MakePolygon odrzuca zerowe krawędzie)."""
    P = np.asarray(P, float)
    keep = [0]
    for i in range(1, len(P)):
        if np.linalg.norm(P[i] - P[keep[-1]]) > tol:
            keep.append(i)
    if len(keep) > 1 and np.linalg.norm(P[keep[-1]] - P[0]) <= tol:
        keep.pop()
    return P[keep]


def prism(outer, holes=(), z0=0.0, z1=1.0, k=1.0, shift=(0.0, 0.0), k0=1.0):
    """Wielokąt wyciągnięty od z0 do z1. k0 - skala dolnej podstawy, k - skala górnej względem środka (1 - prosty;
    0 - szczyt w punkcie; 0..1 - ścięta piramida), shift - przesunięcie górnej podstawy (pochylenie). z1 < z0 - w dół."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.gp import gp_Vec
    outer = clean_poly(outer)
    if len(outer) < 3 or abs(ccw(outer)) < 1e-9 or abs(z1 - z0) <= 1e-9:
        return None
    holes = [clean_poly(h) for h in (holes or ()) if len(h) >= 3]
    plain = abs(k - 1.0) < 1e-9 and abs(k0 - 1.0) < 1e-9 and not any(abs(s) > 1e-9 for s in shift)
    if plain or holes:
        return _fix(BRepPrimAPI_MakePrism(_face(outer, holes, z0), gp_Vec(0, 0, z1 - z0)).Shape())
    if ccw(outer) < 0:
        outer = outer[::-1]
    c = outer.mean(0)
    base = c + (outer - c) * k0
    apex = k <= 1e-6
    top = None if apex else c + (outer - c) * k + np.asarray(shift, float)
    return _loft_planar(base, z0, top, z1, (c + np.asarray(shift, float)) if apex else None)


def _loft_planar(base, z0, top, z1, apex):
    """Bryła o płaskich ścianach: dolny wielokąt (z0), górny wielokąt (z1) o tej samej liczbie wierzchołków, w przekroju podobny
    (skala + przesunięcie) - boki to płaskie trapezy; apex - szczyt w punkcie (boki trójkątne). Zszycie BRepBuilderAPI_Sewing.
    Ściany płaskie (nie B-Spline jak w ThruSections) - operacje logiczne kilkukrotnie szybsze."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.TopoDS import TopoDS
    n = len(base)
    sw = BRepBuilderAPI_Sewing(1e-6)

    def poly(pts):
        mk = BRepBuilderAPI_MakePolygon()
        for q in pts:
            mk.Add(_pt(*q))
        mk.Close()
        return BRepBuilderAPI_MakeFace(mk.Wire(), True).Face()
    B = [(q[0], q[1], z0) for q in base]
    sw.Add(poly(B[::-1]))
    if apex is not None:
        A = (apex[0], apex[1], z1)
        for i in range(n):
            sw.Add(poly([B[i], B[(i + 1) % n], A]))
    else:
        Tp = [(q[0], q[1], z1) for q in top]
        sw.Add(poly(Tp))
        for i in range(n):
            j = (i + 1) % n
            sw.Add(poly([B[i], B[j], Tp[j], Tp[i]]))
    sw.Perform()
    sh = sw.SewedShape()
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    ex = TopExp_Explorer(sh, TopAbs_SHELL)
    if not ex.More():
        return None
    mk = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(ex.Current()))
    return _fix(mk.Solid())


def fillet_top(solid, r, z_top):
    """Zaokrąglenie krawędzi górnej podstawy (ścięta piramida / graniastosłup) - BRepFilletAPI_MakeFillet."""
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.BRep import BRep_Tool
    mk = BRepFilletAPI_MakeFillet(solid)
    ex = TopExp_Explorer(solid, TopAbs_EDGE)
    n = 0
    while ex.More():
        e = TopoDS.Edge_s(ex.Current())
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        c = BRepAdaptor_Curve(e)
        a, b = c.Value(c.FirstParameter()), c.Value(c.LastParameter())
        if abs(a.Z() - z_top) < 1e-6 and abs(b.Z() - z_top) < 1e-6:
            mk.Add(r, e)
            n += 1
        ex.Next()
    if not n:
        return solid
    try:
        mk.Build()
        return mk.Shape() if mk.IsDone() else solid
    except Exception:
        return solid


def _arc_face(points):
    """Ściana z konturu: lista ('L', p) odcinków i ('A', p_mid, p_end) łuków przez trzy punkty (płaszczyzna XZ, y = 0)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.GC import GC_MakeArcOfCircle
    mw = BRepBuilderAPI_MakeWire()
    cur = points[0][1]
    for item in points[1:]:
        if item[0] == 'L':
            if np.linalg.norm(np.asarray(item[1]) - np.asarray(cur)) < 1e-9:
                continue
            mw.Add(BRepBuilderAPI_MakeEdge(_pt(cur[0], 0, cur[1]), _pt(item[1][0], 0, item[1][1])).Edge())
            cur = item[1]
        else:
            arc = GC_MakeArcOfCircle(_pt(cur[0], 0, cur[1]), _pt(item[1][0], 0, item[1][1]), _pt(item[2][0], 0, item[2][1])).Value()
            mw.Add(BRepBuilderAPI_MakeEdge(arc).Edge())
            cur = item[2]
    first = points[0][1]
    if np.linalg.norm(np.asarray(first) - np.asarray(cur)) > 1e-9:
        mw.Add(BRepBuilderAPI_MakeEdge(_pt(cur[0], 0, cur[1]), _pt(first[0], 0, first[1])).Edge())
    return BRepBuilderAPI_MakeFace(mw.Wire(), True).Face()


def ridge_profile(profile, w, h, embed, trap=.4):
    """Przekrój listwy w płaszczyźnie (poprzecznie, z): zbiór poleceń do _arc_face. h < 0 - rowek (profil odbity)."""
    s = 1.0 if h >= 0 else -1.0
    H = abs(h)
    e = embed
    a = w / 2
    if profile == 'tri':
        pts = [('L', (-a, -e)), ('L', (a, -e)), ('L', (a, 0.0)), ('L', (0.0, H)), ('L', (-a, 0.0))]
    elif profile == 'trap':
        t = max(.05, min(.95, trap)) * a
        pts = [('L', (-a, -e)), ('L', (a, -e)), ('L', (a, 0.0)), ('L', (t, H)), ('L', (-t, H)), ('L', (-a, 0.0))]
    elif profile == 'round':
        pts = [('L', (-a, -e)), ('L', (a, -e)), ('L', (a, 0.0)), ('A', (0.0, H), (-a, 0.0))]
        if H < 1e-9:
            return None
    else:
        pts = [('L', (-a, -e)), ('L', (a, -e)), ('L', (a, H)), ('L', (-a, H))]
    if s < 0:                                                         # rowek: lustro względem z = 0, naddatek nad powierzchnią
        flip = []
        for it in pts:
            flip.append(tuple([it[0]] + [(q[0], -q[1]) for q in it[1:]]))
        pts = flip
    return pts


def ridge(profile, w, h, length, embed, trap=.4):
    """Listwa wzdłuż osi y (od 0 do length) o przekroju profile; szerokość w (x), wysokość h (z; ujemna - rowek)."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    pts = ridge_profile(profile, w, h, embed, trap)
    if pts is None or length <= 1e-9:
        return None
    return _fix(BRepPrimAPI_MakePrism(_arc_face(pts), gp_Vec(0, length, 0)).Shape())


def dome(kind, d, h, embed, trunc=.5):
    """Bryła obrotowa osi z. kind: 'sphere' (kula o średnicy d wystająca na h), 'hemisphere' (półkula o średnicy podstawy d),
    'cap' (czasza o średnicy podstawy d i wysokości h), 'cyl' (walec), 'cone' (stożek ścięty do trunc). h < 0 - zagłębienie."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt
    H = abs(h)
    s = 1.0 if h >= 0 else -1.0
    r = d / 2
    if H < 1e-9 or r < 1e-9:
        return None
    e = embed
    if kind in ('cyl', 'cylinder'):
        prof = [('L', (0.0, -e)), ('L', (r, -e)), ('L', (r, H)), ('L', (0.0, H))]
    elif kind == 'cone':
        t = max(0.0, min(.95, trunc))
        r_top = r * t
        slope = (r - r_top) / H
        prof = [('L', (0.0, -e)), ('L', (r + slope * e, -e)), ('L', (r_top, H)), ('L', (0.0, H))]
    else:
        if kind == 'hemisphere':
            H = r
        if kind == 'sphere':                                          # pełna kula o średnicy d, wysokość nad powierzchnią h
            R = r
            H = min(H, 2 * R)
            a = math.sqrt(max(R * R - (R - H) ** 2, 0.0)) if H < R else R
            zc = H - R
            mid = (R * math.sin(math.radians(45)) * (a / max(R, 1e-9) if H < R else 1.0), zc + math.sqrt(max(R * R - (R * math.sin(math.radians(45)) * (a / max(R, 1e-9) if H < R else 1.0)) ** 2, 0.0)))
            # punkt środkowy łuku: na okręgu między (a, z_a) i szczytem
            z_a = 0.0 if H < R else zc
            ang0 = math.atan2(z_a - zc, a)
            am = (ang0 + math.pi / 2) / 2
            mid = (R * math.cos(am), zc + R * math.sin(am))
            prof = [('L', (0.0, -e)), ('L', (a, -e)), ('L', (a, z_a)), ('A', mid, (0.0, H))]
        else:                                                         # czasza: łuk przez (a, 0), środek, (0, H)
            a = r
            R = (a * a + H * H) / (2 * H)
            zc = H - R
            ang0 = math.atan2(0.0 - zc, a)
            am = (ang0 + math.pi / 2) / 2
            mid = (R * math.cos(am), zc + R * math.sin(am))
            prof = [('L', (0.0, -e)), ('L', (a, -e)), ('L', (a, 0.0)), ('A', mid, (0.0, H))]
    if s < 0:
        prof = [tuple([it[0]] + [(q[0], -q[1]) for q in it[1:]]) for it in prof]
    face = _arc_face_xz(prof)
    return _fix(BRepPrimAPI_MakeRevol(face, gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))).Shape())


def _arc_face_xz(points):
    """Jak _arc_face, ale kontur leży w półpłaszczyźnie x ≥ 0 (do obrotu wokół osi z) i jest zamknięty osią."""
    return _arc_face(points)


def location(P, N, X, flip_y=False):
    """TopLoc_Location układu lokalnego (0,0,0; z = N; x = X) w układzie globalnym."""
    from OCP.TopLoc import TopLoc_Location
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt, gp_Trsf
    N = np.asarray(N, float)
    X = np.asarray(X, float)
    X = X - N * float(X @ N)
    nx = np.linalg.norm(X)
    if nx < 1e-9:
        X = np.cross(N, [0, 0, 1.0] if abs(N[2]) < .9 else [1.0, 0, 0])
        nx = np.linalg.norm(X)
    X = X / nx
    t = gp_Trsf()
    t.SetTransformation(gp_Ax3(gp_Pnt(*map(float, P)), gp_Dir(*map(float, N)), gp_Dir(*map(float, X))), gp_Ax3())
    return TopLoc_Location(t)


def placed(shape, P, N, X):
    """Bryła z układu lokalnego przeniesiona na powierzchnię (punkt P, normalna N, kierunek x X)."""
    if shape is None:
        return None
    return shape.Moved(location(P, N, X))


def placed_matrix(shape, M):
    """Bryła przekształcona macierzą 4x4 (sztywną)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf
    t = gp_Trsf()
    M = np.asarray(M, float)
    t.SetValues(*[float(v) for v in M[:3].ravel()])
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


def volume(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    return g.Mass()
