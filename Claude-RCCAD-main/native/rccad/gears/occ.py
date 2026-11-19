"""Zarys koła walcowego jako krzywe Open CASCADE (płaszczyzna XY, przekrój czołowy, środek koła w początku układu).

Ewolwenta i trochoida stopy: krzywe B-spline (GeomAPI_Interpolate) przechodzące dokładnie przez punkty liczone ze wzorów
(profile.py), z dokładnymi stycznymi na końcach - odchyłka od krzywej dokładnej poniżej 1e-6 mm. Okręgi głów i stóp oraz łuk przejścia koła wewnętrznego:
dokładne łuki (Geom_Circle). Kolejne krawędzie mają wspólne końce, więc zarys jest zamkniętym, poprawnym konturem.

Etap 2: zarys zęba i zarys 2D całego koła (bez bryły 3D)."""
from __future__ import annotations

import math

import cadquery as cq
import numpy as np
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Transform
from OCP.GC import GC_MakeArcOfCircle
from OCP.GeomAPI import GeomAPI_Interpolate
from OCP.TColgp import TColgp_HArray1OfPnt
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

from .params import GearParams, derived
from .profile import GearError, ToothProfile, profile


def _pnt(xy):
    return gp_Pnt(float(xy[0]), float(xy[1]), 0.0)


def spline_edge(points, tangents=None):
    """Krawędź B-spline przez punkty (w podanej kolejności); tangents - dokładne styczne na początku i końcu."""
    pts = np.asarray(points, float)
    keep = np.ones(len(pts), bool)
    keep[1:] = np.linalg.norm(np.diff(pts, axis=0), axis=1) > 1e-9      # bez powtórzonych punktów
    pts = pts[keep]
    if len(pts) < 2:
        raise GearError('Za krótki fragment zarysu.')
    array = TColgp_HArray1OfPnt(1, len(pts))
    for i, p in enumerate(pts, 1):
        array.SetValue(i, _pnt(p))
    interp = GeomAPI_Interpolate(array, False, 1e-9)
    if tangents is not None:
        (ax, ay), (bx, by) = np.asarray(tangents, float)
        interp.Load(gp_Vec(ax, ay, 0), gp_Vec(bx, by, 0), False)      # styczne jednostkowe (Scale=True psuje dopasowanie)
    interp.Perform()
    if not interp.IsDone():
        raise GearError('Nie udało się zbudować krzywej zarysu.')
    return BRepBuilderAPI_MakeEdge(interp.Curve()).Edge()


def arc_edge(a, mid, b):
    """Łuk okręgu przez trzy punkty."""
    return BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(_pnt(a), _pnt(mid), _pnt(b)).Value()).Edge()


def _polar(R, theta):
    return np.array((R * math.cos(theta), R * math.sin(theta)))


def _fillet_edge(prof: ToothProfile, points, tangents):
    if prof.fillet_kind == 'arc':
        return arc_edge(*points)
    return spline_edge(points, tangents)


def _flip(tangents, mirror=False, reverse=False):
    """Styczne po odbiciu (dolny bok) i/lub odwróceniu kolejności punktów."""
    if tangents is None:
        return None
    t = np.asarray(tangents, float) * ((1, -1) if mirror else (1, 1))
    return -t[::-1] if reverse else t


def tooth_edges(prof: ToothProfile):
    """Krawędzie jednego zęba od dolnego początku przejścia stopy (dno wrębu) do górnego, przeciwnie do wskazówek zegara:
    przejście, ewolwenta, wierzchołek, ewolwenta, przejście."""
    low = ToothProfile.mirrored
    tip = (_polar(prof.ra, -prof.tip_angle), _polar(prof.ra, 0.0), _polar(prof.ra, prof.tip_angle))
    return [_fillet_edge(prof, low(prof.fillet), _flip(prof.fillet_tangents, mirror=True)),
            spline_edge(low(prof.flank), _flip(prof.flank_tangents, mirror=True)),
            arc_edge(*tip),
            spline_edge(prof.flank[::-1], _flip(prof.flank_tangents, reverse=True)),
            _fillet_edge(prof, prof.fillet[::-1], _flip(prof.fillet_tangents, reverse=True))]


def root_edge(prof: ToothProfile):
    """Dno wrębu za zębem (od górnego przejścia tego zęba do dolnego przejścia następnego) albo None, gdy przejścia się stykają."""
    gap = 2 * math.pi / prof.teeth - 2 * prof.root_angle
    if gap <= 1e-9:
        return None
    a = prof.root_angle
    return arc_edge(_polar(prof.rf, a), _polar(prof.rf, a + gap / 2), _polar(prof.rf, a + gap))


def _rotated(edge, angle):
    if not angle:
        return edge
    trsf = gp_Trsf()
    trsf.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), angle)
    return TopoDS.Edge_s(BRepBuilderAPI_Transform(edge, trsf, True).Shape())


def tooth_wire(params: GearParams) -> cq.Wire:
    """Otwarty zarys jednego zęba (oś zęba na +X)."""
    builder = BRepBuilderAPI_MakeWire()
    for edge in tooth_edges(profile(params)):
        builder.Add(edge)
    if not builder.IsDone():
        raise GearError('Krawędzie zarysu zęba nie łączą się.')
    return cq.Wire(builder.Wire())


def outline_wire(params: GearParams) -> cq.Wire:
    """Zamknięty zarys całego koła w przekroju czołowym (pierwszy ząb na osi +X)."""
    prof = profile(params)
    edges = tooth_edges(prof)
    root = root_edge(prof)
    one = edges + ([root] if root is not None else [])
    builder = BRepBuilderAPI_MakeWire()
    for i in range(prof.teeth):
        angle = 2 * math.pi * i / prof.teeth
        for edge in one:
            builder.Add(_rotated(edge, angle))
            if not builder.IsDone():
                raise GearError('Krawędzie zarysu koła nie łączą się.')
    wire = cq.Wire(builder.Wire())
    if not wire.IsClosed():
        raise GearError('Zarys koła nie jest zamknięty.')
    return wire


def section_face(params: GearParams) -> cq.Face:
    """Przekrój czołowy wieńca jako płaska ściana: koło zewnętrzne - obszar wewnątrz zarysu; koło wewnętrzne - pierścień
    między okręgiem wieńca a zarysem zębów. Bez otworu i piasty (to część bryły - kolejny etap)."""
    wire = outline_wire(params)
    if params.internal:
        rim = derived(params)['rim'] / 2
        outer = cq.Wire.makeCircle(rim, cq.Vector(0, 0, 0), cq.Vector(0, 0, 1))
        face = cq.Face.makeFromWires(outer, [wire])
    else:
        face = cq.Face.makeFromWires(wire)
    if not face.isValid():
        raise GearError('Przekrój koła nie jest poprawną ścianą.')
    return face
