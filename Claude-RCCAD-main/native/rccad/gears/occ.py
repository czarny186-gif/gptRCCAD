"""Zarys koła walcowego jako krzywe Open CASCADE (płaszczyzna XY, przekrój czołowy, środek koła w początku układu).

Ewolwenta i trochoida stopy: krzywe B-spline (GeomAPI_Interpolate) przechodzące dokładnie przez punkty liczone ze wzorów
(profile.py), z dokładnymi stycznymi na końcach - odchyłka od krzywej dokładnej poniżej 1e-6 mm. Okręgi głów i stóp oraz łuk przejścia koła wewnętrznego:
dokładne łuki (Geom_Circle). Kolejne krawędzie mają wspólne końce, więc zarys jest zamkniętym, poprawnym konturem.

Etap 2: zarys zęba i zarys 2D całego koła.
Etap 4: zęby skośne - boki zębów przeciągnięte śrubowo (obrót przekroju o skok linii zęba), także koła wewnętrzne.
Etap 3: bryła koła o zębach prostych (gear_solid) - przekrój czołowy z otworem i rowkiem wpustowym wyciągnięty jednym
ruchem (zęby i otwór bez operacji logicznych), piasta dołączona jedną sumą; sprawdzenie poprawności i szczelności."""
from __future__ import annotations

import math

import cadquery as cq
import numpy as np
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_Transform
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.GC import GC_MakeArcOfCircle
from OCP.GeomAPI import GeomAPI_Interpolate
from OCP.TColgp import TColgp_HArray1OfPnt
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

from .params import GearParams, derived, keyway_size
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


_WIRES = {}              # zarys koła (OCC) dla uzębienia - wspólny dla zmian szerokości, otworu, piasty


def outline_wire(params: GearParams) -> cq.Wire:
    """Zamknięty zarys całego koła w przekroju czołowym (pierwszy ząb na osi +X). Zapamiętany dla tego samego uzębienia."""
    from .profile import tooth_key
    prof = profile(params)
    key = tooth_key(params)
    if key in _WIRES:
        return _WIRES[key]
    wire = _outline_wire(prof)
    if len(_WIRES) >= 32:
        _WIRES.pop(next(iter(_WIRES)))
    _WIRES[key] = wire
    return wire


def _outline_wire(prof: ToothProfile) -> cq.Wire:
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


# ---------------------------------------------------------------------------------------------------------------
# bryła koła (etap 3: zęby proste)
# ---------------------------------------------------------------------------------------------------------------
def line_edge(a, b):
    return BRepBuilderAPI_MakeEdge(_pnt(a), _pnt(b)).Edge()


def bore_wire(params: GearParams):
    """Zarys otworu (okrąg) z rowkiem wpustowym w kierunku +X (pod osią pierwszego zęba) albo None, gdy bez otworu."""
    R = float(params.bore) / 2
    if params.internal or R <= 0:
        return None
    key = keyway_size(params)
    if key is None:
        return cq.Wire.makeCircle(R, cq.Vector(0, 0, 0), cq.Vector(0, 0, 1))
    width, depth = key
    h = width / 2
    x0 = math.sqrt(R * R - h * h)
    top = R + depth
    a, b = (x0, h), (x0, -h)
    builder = BRepBuilderAPI_MakeWire()
    for edge in (arc_edge(a, (-R, 0.0), b), line_edge(b, (top, -h)), line_edge((top, -h), (top, h)), line_edge((top, h), a)):
        builder.Add(edge)
    return cq.Wire(builder.Wire())


def plane_face(outer, inners=(), z=0.0):
    """Płaska ściana w płaszczyźnie z = const z konturem zewnętrznym i otworami. Płaszczyzna podana wprost - OCC nie
    szuka jej sam po wszystkich krawędziach (przy kilkuset zębach to sekunda różnicy)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Dir, gp_Pln
    if z:
        outer = outer.translate(cq.Vector(0, 0, z))
        inners = [w.translate(cq.Vector(0, 0, z)) for w in inners]
    maker = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1)), outer.wrapped, True)
    for wire in inners:
        maker.Add(TopoDS.Wire_s(wire.wrapped.Reversed()))
    if not maker.IsDone():
        raise GearError('Nie udało się zbudować przekroju koła.')
    face = cq.Face(maker.Face())
    if face.Area() < 0:
        face = cq.Face(face.wrapped.Reversed())
    return face


def _circle(radius):
    return cq.Wire.makeCircle(float(radius), cq.Vector(0, 0, 0), cq.Vector(0, 0, 1))


def _prism(face, z0, height):
    if z0:
        face = face.translate(cq.Vector(0, 0, z0))
    return cq.Shape.cast(BRepPrimAPI_MakePrism(face.wrapped, gp_Vec(0, 0, float(height))).Shape())


def _outward(solid):
    """Bryła zorientowana na zewnątrz (dodatnia objętość). Koło: najniżej położona płaska ściana (dno wieńca) ma normalną
    w dół. Bez dna płaskiego - klasyfikacja punktu w nieskończoności (wolniejsza przy wielu ścianach)."""
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.TopAbs import TopAbs_OUT
    planes = [f for f in solid.Faces() if f.geomType() == 'PLANE']
    if planes:
        bottom = min(planes, key=lambda f: f.Center().z)
        normal = bottom.normalAt(bottom.Center())
        if abs(abs(normal.z) - 1) < 1e-9 and min(v.Z for v in solid.Vertices()) >= bottom.Center().z - 1e-7:
            return normal.z < 0
    classifier = BRepClass3d_SolidClassifier(solid.wrapped)
    classifier.PerformInfinitePoint(1e-7)
    return classifier.State() == TopAbs_OUT


def solid_report(shape):
    """Kontrola bryły: poprawność (BRepCheck, równolegle), jedna bryła z jedną powłoką, szczelność (powłoka zamknięta:
    każda krawędź wspólna dla dwóch ścian - BRep_Tool.IsClosed), orientacja na zewnątrz. 'ok' = wszystko spełnione."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepCheck import BRepCheck_Analyzer
    valid = BRepCheck_Analyzer(shape.wrapped, True, True).IsValid()
    solids = shape.Solids()
    shells = [sh for s in solids for sh in s.Shells()]
    closed = bool(shells) and all(BRep_Tool.IsClosed_s(sh.wrapped) for sh in shells)
    outward = len(solids) == 1 and _outward(solids[0])
    report = dict(valid=valid, solids=len(solids), shells=len(shells), closed=closed, outward=outward)
    report['ok'] = valid and len(solids) == 1 and len(shells) == 1 and closed and outward
    return report


def twist_angle(params: GearParams):
    """Kąt obrotu przekroju czołowego na całej szerokości koła (rad): 2·b·tg β / d; prawy skręt - dodatni (przeciwnie
    do wskazówek zegara patrząc od +Z, jak prawoskrętna linia śrubowa), lewy - ujemny. Zęby proste: 0."""
    if not params.helical:
        return 0.0
    d = derived(params)['d']
    angle = 2 * float(params.width) * math.tan(math.radians(params.beta)) / d
    return angle if params.hand == 'right' else -angle


def lead(params: GearParams):
    """Skok linii śrubowej zęba na średnicy podziałowej L = π·d / tg β (mm); zęby proste - None."""
    if not params.helical:
        return None
    return math.pi * derived(params)['d'] / math.tan(math.radians(params.beta))


def _lateral(wire, z0, height, params=None):
    """Ściany boczne konturu od z0 do z0 + height: proste wyciągnięcie albo (params skośne) przeciągnięcie śrubowe -
    przekrój obraca się wzdłuż osi zgodnie z pomocniczą linią śrubową o skoku zęba (BRepOffsetAPI_MakePipeShell),
    więc boki zębów są ewolwentowymi powierzchniami śrubowymi."""
    if z0:
        wire = wire.translate(cq.Vector(0, 0, z0))
    if params is None or not params.helical:
        return cq.Shape.cast(BRepPrimAPI_MakePrism(wire.wrapped, gp_Vec(0, 0, float(height))).Shape()).Faces()
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell
    spine = cq.Wire.assembleEdges([cq.Edge.makeLine(cq.Vector(0, 0, z0), cq.Vector(0, 0, z0 + height))])
    helix = cq.Wire.makeHelix(lead(params), float(height), 1.0, cq.Vector(0, 0, z0), cq.Vector(0, 0, 1),
                              lefthand=params.hand != 'right')
    pipe = BRepOffsetAPI_MakePipeShell(spine.wrapped)
    pipe.SetMode(helix.wrapped, False)               # obrót przekroju prowadzi linia śrubowa (bez równoważności łukowej)
    pipe.SetTolerance(1e-6, 1e-6, 1e-4)
    pipe.Add(wire.wrapped, False, False)
    pipe.Build()
    if not pipe.IsDone():
        raise GearError('Nie udało się zbudować śrubowych boków zębów.')
    return cq.Shape.cast(pipe.Shape()).Faces()


def _teeth_lateral(params: GearParams, width):
    """Boki wszystkich zębów: jeden ząb z dnem wrębu wyciągnięty (albo przeciągnięty śrubowo), pozostałe - obrócone kopie
    dzielące tę samą geometrię (położenie TopLoc). Przy kilkuset zębach skośnych: setne części sekundy zamiast sekund
    przeciągania całego zarysu."""
    from OCP.TopLoc import TopLoc_Location
    prof = profile(params)
    builder = BRepBuilderAPI_MakeWire()
    root = root_edge(prof)
    for edge in tooth_edges(prof) + ([root] if root is not None else []):
        builder.Add(edge)
    if not builder.IsDone():
        raise GearError('Krawędzie zarysu zęba nie łączą się.')
    first = _lateral(cq.Wire(builder.Wire()), 0.0, width, params)
    faces = []
    for k in range(prof.teeth):
        if k == 0:
            faces += first
            continue
        trsf = gp_Trsf()
        trsf.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 2 * math.pi * k / prof.teeth)
        location = TopLoc_Location(trsf)
        faces += [cq.Face(f.wrapped.Moved(location)) for f in first]
    return faces


def _rotated_wire(wire, angle):
    return wire if not angle else wire.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), math.degrees(angle))


def _sew(faces, tolerance=1e-5, cutting=False):
    """Ściany zszyte w jedną zamkniętą powłokę i bryłę zorientowaną na zewnątrz albo None. Krawędzie sąsiednich ścian koła
    pokrywają się jedna do jednej, więc bez dzielenia krawędzi (cutting) - kilka razy szybciej; gdy wynik nie jest
    poprawny, gear_solid zszywa jeszcze raz z dzieleniem."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.BRepLib import BRepLib
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    sewing = BRepBuilderAPI_Sewing(tolerance, True, True, cutting, False)
    for f in faces:
        sewing.Add(f.wrapped)
    sewing.Perform()
    explorer = TopExp_Explorer(sewing.SewedShape(), TopAbs_SHELL)
    if not explorer.More():
        return None
    shell = TopoDS.Shell_s(explorer.Current())
    explorer.Next()
    if explorer.More():                              # więcej niż jedna powłoka - zszycie się nie udało
        return None
    solid = cq.Shape.cast(BRepBuilderAPI_MakeSolid(shell).Solid())
    if not _outward(solid):                          # ściany są zorientowane na zewnątrz - to tylko zabezpieczenie
        raw = solid.wrapped
        BRepLib.OrientClosedSolid_s(raw)
        solid = cq.Shape.cast(raw)
    return solid


def gear_solid(params: GearParams) -> cq.Solid:
    """Bryła koła walcowego (zęby proste lub skośne, zewnętrzne lub wewnętrzne): oś Z, wieniec od z = 0 do z = szerokość,
    pierwszy ząb (w przekroju z = 0) na osi +X, piasta (koło zewnętrzne) po stronie +Z. Wyjątek GearError, gdy bryła
    nie jest poprawna i szczelna.

    Bez operacji logicznych: boki wszystkich zębów jednym wyciągnięciem (zęby proste) albo jednym przeciągnięciem
    śrubowym (skośne), dno - przekrój z otworem, góra - przekrój obrócony o kąt skrętu, otwór z rowkiem i piasta -
    proste wyciągnięcia; wszystko zszyte w jedną powłokę. Piasta szersza niż stopy zębów - jedna suma."""
    prof = profile(params)                           # walidacja parametrów i zarysu (GearError z opisem)
    width = float(params.width)
    outline = outline_wire(params)
    if not params.helical and not params.internal and not (params.hub and params.hub_length > 0):
        bore = bore_wire(params)                     # zęby proste bez piasty: jedno wyciągnięcie przekroju z otworem
        shape = _prism(plane_face(outline, [bore] if bore is not None else []), 0.0, width)
        if not solid_report(shape)['ok']:
            raise GearError('Bryła koła nie jest poprawna lub szczelna - zmień parametry.')
        remember_box(shape, params)
        return shape
    top_outline = _rotated_wire(outline, twist_angle(params))
    if params.helical:
        faces = _teeth_lateral(params, width)        # boki zębów: jeden ząb przeciągnięty śrubowo + obrócone kopie
    else:
        faces = _lateral(outline, 0.0, width, params)    # boki zębów: jedno wyciągnięcie całego zarysu
    wide_hub = None
    if params.internal:
        rim = _circle(derived(params)['rim'] / 2)
        faces += _lateral(rim, 0.0, width)
        faces += [plane_face(rim, [outline]), plane_face(rim, [top_outline], width)]
    else:
        bore = bore_wire(params)
        holes = [bore] if bore is not None else []
        hub = params.hub and params.hub_length > 0
        hub_radius, hub_length = float(params.hub_diameter) / 2, float(params.hub_length)
        faces.append(plane_face(outline, holes))      # dno
        height = width
        if hub and hub_radius < prof.rf - 1e-3:      # piasta wewnątrz stóp zębów: góra wieńca jako pierścień wokół piasty
            hub_circle = _circle(hub_radius)
            faces.append(plane_face(top_outline, [hub_circle], width))
            faces += _lateral(hub_circle, width, hub_length)
            faces.append(plane_face(hub_circle, holes, width + hub_length))
            height = width + hub_length
        else:
            faces.append(plane_face(top_outline, holes, width))
            if hub:
                wide_hub = _prism(plane_face(_circle(hub_radius), holes, width), 0.0, hub_length)
        if bore is not None:
            faces += _lateral(bore, 0.0, height)       # otwór z rowkiem przez wieniec i piastę - proste ściany
    shape = _sew(faces)
    checked = shape is not None and wide_hub is None and solid_report(shape)['ok']   # kontrola raz (przy wielu zębach - sekundy)
    if shape is None or (wide_hub is None and not checked):
        shape = _sew(faces, cutting=True)            # zapasowo: pełne zszycie z dzieleniem krawędzi
        checked = False
    if shape is None:
        raise GearError('Nie udało się zszyć bryły koła - zmień parametry.')
    if wide_hub is not None:
        shape = _fuse(shape, wide_hub)               # piasta szersza niż stopy zębów: jedna suma
    solids = shape.Solids()
    if len(solids) == 1:
        shape = solids[0]
    if not checked and not solid_report(shape)['ok']:
        raise GearError('Bryła koła nie jest poprawna lub szczelna - zmień parametry.')
    remember_box(shape, params)
    return shape


def remember_box(shape, params, place=None):
    """Prostopadłościan koła ze wzoru (gears.bounds) zapamiętany dla kształtu - kernel.bounds nie liczy go z powierzchni."""
    from .bounds import gear_box
    from rccad import kernel
    box = gear_box(params, place)
    if box is not None:
        kernel.remember_bounds(shape, *box)


def _fuse(a, b):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.BOPAlgo import BOPAlgo_GlueShift
    from OCP.TopTools import TopTools_ListOfShape
    arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    arguments.Append(a.wrapped)
    tools.Append(b.wrapped)
    op = BRepAlgoAPI_Fuse()
    op.SetArguments(arguments)
    op.SetTools(tools)
    op.SetGlue(BOPAlgo_GlueShift)                    # bryły tylko się stykają (wspólna płaszczyzna) - szybkie klejenie
    op.SetRunParallel(True)
    op.Build()
    if not op.IsDone():
        raise GearError('Nie udało się dołączyć piasty.')
    shape = cq.Shape.cast(op.Shape())
    try:
        shape = shape.clean()                        # jedna ściana otworu / rowka przez wieniec i piastę
    except Exception:
        pass
    return shape
