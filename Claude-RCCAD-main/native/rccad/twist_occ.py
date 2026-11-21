"""TWIST – rzeczywiste skręcanie brył B-Rep (Open CASCADE), etap 5: bryły o stałym przekroju wzdłuż osi.

Obsługiwane bryły (względem osi skręcenia):
- etap 5: graniastosłupy - dwie płaskie podstawy prostopadłe do osi (ten sam przekrój, także z otworami przelotowymi),
  wszystkie pozostałe ściany równoległe do osi (prostopadłościan, graniastosłup, walec),
- etap 6: bryły „schodkowe” - każda ściana jest albo płaska i prostopadła do osi, albo równoległa do osi: otwory
  przelotowe i nieprzelotowe wzdłuż osi, kieszenie, pogłębienia, stopnie, wewnętrzne puste przestrzenie (osobne
  powłoki) o ścianach wzdłuż osi. Bryła dzielona jest na warstwy o stałym przekroju (granice warstw - poziomy ścian
  prostopadłych), przekrój warstwy to dokładny przekrój B-Rep płaszczyzną (BRepAlgoAPI_Common, łuki zostają łukami),
  każda warstwa skręca się jak graniastosłup, a warstwy łączą się operacją logiczną Open CASCADE (wspólne krawędzie
  i ściany odtworzone, ściany tej samej powierzchni scalone). Każdy otwór skręca się razem z bryłą o lokalny kąt.
Inne bryły (np. otwór poprzeczny do osi, ściany ukośne, kula) są odrzucane z komunikatem - oryginał zostaje bez zmian.

Budowa (bez siatki trójkątów):
1. przekrój = dolna podstawa (ściana B-Rep z obrysem i otworami),
2. długość bryły dzielona na odcinki stałego kąta (poza zakresem skręcenia) i odcinek skręcany,
3. każdy kontur przekroju: na odcinku stałym - zwykłe wyciągnięcie (BRepPrimAPI_MakePrism), na skręcanym -
   przeciągnięcie wzdłuż prostej osi z obrotem przekroju prowadzonym krzywą pomocniczą (BRepOffsetAPI_MakePipeShell):
   rozkład liniowy - linia śrubowa, inne rozkłady - krzywa B-spline z punktów silnika rccad.twist_math. Powstają
   powierzchnie B-spline (NURBS) - dokładne w tolerancji aproksymacji Open CASCADE,
4. podstawy: dolna i górna obrócone o kąt silnika na końcach bryły,
5. zszycie w jedną zamkniętą powłokę, bryła zorientowana na zewnątrz,
6. kontrola: BRepCheck_Analyzer, jedna bryła z jedną zamkniętą powłoką, samoprzecięcia (BRepAlgoAPI_Check), objętość
   (skręcanie jej nie zmienia), odchyłka od dokładnego skręcenia silnikiem twist_math w punktach kontrolnych."""
from __future__ import annotations

import math

import cadquery as cq
import numpy as np

from . import kernel
from . import twist_math as tm

TOLERANCE = 0.01            # mm - największa dopuszczalna odchyłka powierzchni od dokładnego skręcenia
VOLUME_TOLERANCE = 1e-3     # względna zmiana objętości (skręcanie zachowuje objętość)


class TwistError(kernel.CadError):
    """Skręcenie niemożliwe albo wynik niepoprawny (komunikat po polsku) - oryginał zostaje bez zmian."""


def _frame(direction):
    d = np.asarray(direction, float)
    e1 = np.cross(d, (0, 0, 1.0) if abs(d[2]) < .9 else (1.0, 0, 0))
    e1 /= np.linalg.norm(e1)
    return e1, np.cross(d, e1)


def _axial(points, origin, direction):
    return (np.asarray(points, float).reshape(-1, 3) - np.asarray(origin, float)) @ np.asarray(direction, float)


# ---------------------------------------------------------------------------------------------- rozpoznanie graniastosłupa
def _volume(shape):
    """Objętość z całkowaniem adaptacyjnym (eps 1e-9) - dokładna także dla ścian B-spline / NURBS z plików STEP."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, props, 1e-9, True)
    return props.Mass()


def _area(face):
    """Pole ściany z całkowaniem adaptacyjnym (jak _volume)."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face.wrapped, props, 1e-9, True)
    return props.Mass()


def _tolerances(solid):
    """(rozmiar, tolerancja liniowa, tolerancja kątowa) dla bryły - także z pliku STEP, gdzie tolerancje ścian i krawędzi
    bywają większe niż w bryłach RCCAD (ShapeAnalysis_ShapeTolerance: największa tolerancja w bryle)."""
    from OCP.ShapeAnalysis import ShapeAnalysis_ShapeTolerance
    box = kernel.bounds(solid)
    size = max(box.xlen, box.ylen, box.zlen, 1.0)
    shape_tol = ShapeAnalysis_ShapeTolerance().Tolerance(solid.wrapped, 1)
    lin = max(1e-6, 1e-7 * size, 2.0 * shape_tol)
    return size, lin, max(1e-6, 2.0 * lin / size)


def _plane_normal(face, lin):
    """Normalna płaskiej ściany (PLANE albo powierzchnia B-spline / NURBS, która jest płaszczyzną - tak zapisują
    płaskie ściany niektóre programy w STEP; GeomLib_IsPlanarSurface) albo None."""
    if face.geomType() == 'PLANE':
        return np.asarray(face.normalAt(face.Center()).toTuple(), float)
    if face.geomType() not in ('BSPLINE', 'BEZIER', 'OFFSET', 'OTHER'):
        return None
    from OCP.BRep import BRep_Tool
    from OCP.GeomLib import GeomLib_IsPlanarSurface
    planar = GeomLib_IsPlanarSurface(BRep_Tool.Surface_s(face.wrapped), lin)
    if not planar.IsPlanar():
        return None
    a = planar.Plan().Axis().Direction()
    return np.array([a.X(), a.Y(), a.Z()], float)


def _cap_level(face, origin, d, lin, ang):
    """Położenie t płaskiej ściany prostopadłej do osi albo None."""
    n = _plane_normal(face, lin)
    if n is None or abs(abs(float(n @ d)) - 1) > ang:
        return None
    ft = _axial([v.toTuple() for v in face.Vertices()] or [face.Center().toTuple()], origin, d)
    return float(ft.mean()) if np.ptp(ft) < lin else None


def prism_profile(shape, origin, direction, tol=1e-6):
    """(dolna podstawa - cq.Face, t0, t1) dla bryły o stałym przekroju wzdłuż osi albo TwistError z opisem."""
    solids = shape.Solids() if hasattr(shape, 'Solids') else []
    if len(solids) != 1:
        raise TwistError('TWIST skręca jedną bryłę - ten obiekt nie jest pojedynczą bryłą.')
    solid = solids[0]
    d = np.asarray(direction, float)
    size, lin, ang = _tolerances(solid)
    lin = max(lin, tol)
    t = _axial([v.toTuple() for v in solid.Vertices()], origin, d)
    if not len(t):
        raise TwistError('Bryła bez wierzchołków (np. kula lub torus) - TWIST obsługuje na razie tylko graniastosłupy wzdłuż osi.')
    t0, t1 = float(t.min()), float(t.max())
    if t1 - t0 < 1e-6:
        raise TwistError('Bryła nie ma długości wzdłuż osi skręcenia - wybierz inną oś.')
    caps = {0: [], 1: []}
    for face in solid.Faces():
        level = _cap_level(face, origin, d, lin, ang)
        if level is not None:
            if abs(level - t0) < lin:
                caps[0].append(face)
                continue
            if abs(level - t1) < lin:
                caps[1].append(face)
                continue
        if not _parallel_to_axis(face, d, ang):
            raise TwistError('TWIST obsługuje na razie tylko bryły o stałym przekroju wzdłuż osi skręcenia '
                             '(np. prostopadłościan, graniastosłup) - ta bryła ma ściany ukośne albo zmienny przekrój względem tej osi.')
    if len(caps[0]) != 1 or len(caps[1]) != 1:
        raise TwistError('Bryła nie ma dwóch płaskich podstaw prostopadłych do osi skręcenia - wybierz oś wzdłuż graniastosłupa.')
    bottom, top = caps[0][0], caps[1][0]
    area = _area(bottom)
    rel = max(1e-6, 4 * lin / size)
    if abs(_area(top) - area) > rel * max(area, 1.0) or abs(_volume(solid) - area * (t1 - t0)) > rel * max(_volume(solid), 1.0):
        raise TwistError('Przekrój bryły zmienia się wzdłuż osi skręcenia - TWIST obsługuje na razie tylko stały przekrój.')
    shift = np.asarray(top.Center().toTuple(), float) - np.asarray(bottom.Center().toTuple(), float)
    if np.linalg.norm(shift - d * (t1 - t0)) > max(1e-5, 4 * lin):
        raise TwistError('Podstawy bryły są przesunięte względem osi skręcenia (graniastosłup pochyły) - wybierz oś wzdłuż bryły.')
    return bottom, t0, t1


def _parallel_to_axis(face, d, ang=1e-6):
    """Ściana boczna graniastosłupa: normalna prostopadła do osi w siatce punktów ściany (BRepLProp przez cadquery)."""
    from OCP.BRepGProp import BRepGProp_Face
    from OCP.gp import gp_Pnt, gp_Vec
    props = BRepGProp_Face(face.wrapped)
    u0, u1, v0, v1 = face._uvBounds()
    for u in np.linspace(u0, u1, 5):
        for v in np.linspace(v0, v1, 5):
            point, normal = gp_Pnt(), gp_Vec()
            props.Normal(float(u), float(v), point, normal)
            length = normal.Magnitude()
            if length < 1e-12:
                continue                              # punkt osobliwy (np. biegun) - pomijany
            if abs(float(np.dot((normal.X(), normal.Y(), normal.Z()), d))) > ang * length:
                return False
    return True


# ---------------------------------------------------------------------------------------------- budowa
def _segments(field, t0, t1):
    """Odcinki [a, b] długości bryły: stałe (poza zakresem skręcenia) i skręcany."""
    cuts = sorted({t0, t1, *(c for c in (field.start, field.end) if t0 < c < t1)})
    out = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        twisting = field.start < (a + b) / 2 < field.end
        out.append((a, b, twisting))
    return out


def _trsf(origin, direction, angle, shift):
    """Obrót o angle (rad) wokół osi, po przesunięciu o shift wzdłuż osi."""
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
    d = np.asarray(direction, float)
    rot = gp_Trsf()
    rot.SetRotation(gp_Ax1(gp_Pnt(*map(float, origin)), gp_Dir(*map(float, d))), float(angle))
    move = gp_Trsf()
    move.SetTranslation(gp_Vec(*map(float, d * shift)))
    return rot.Multiplied(move)


def _placed(shape, trsf):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    return cq.Shape.cast(BRepBuilderAPI_Transform(shape.wrapped, trsf, True).Shape())


def _guide(field, a, b, origin, direction, radius):
    """Krzywa pomocnicza obrotu przekroju na odcinku [a, b]: punkt w odległości radius od osi pod kątem theta(t).
    Rozkład liniowy - dokładna linia śrubowa; inne - krzywa B-spline aproksymująca punkty silnika twist_math."""
    o, d = np.asarray(origin, float), np.asarray(direction, float)
    e1, e2 = _frame(d)
    span = float(field.theta(b) - field.theta(a))
    if field.kind == 'linear':
        pitch = (b - a) * 2 * math.pi / abs(span)
        return cq.Wire.makeHelix(pitch, b - a, radius, cq.Vector(*(o + d * a)), cq.Vector(*d), lefthand=span < 0)
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.GeomAPI import GeomAPI_PointsToBSpline
    from OCP.GeomAbs import GeomAbs_C2
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.gp import gp_Pnt
    count = max(64, int(abs(math.degrees(span)) / 2.0) + 1)
    ts = np.linspace(a, b, count)
    th = field.theta(ts)
    arr = TColgp_Array1OfPnt(1, count)
    for i, (t, angle) in enumerate(zip(ts, th), 1):
        p = o + d * t + radius * (math.cos(angle) * e1 + math.sin(angle) * e2)
        arr.SetValue(i, gp_Pnt(*map(float, p)))
    curve = GeomAPI_PointsToBSpline(arr, 3, 8, GeomAbs_C2, 1e-6 * max(radius, 1.0)).Curve()
    return cq.Wire.assembleEdges([cq.Edge(BRepBuilderAPI_MakeEdge(curve).Edge())])


def _lateral(wire, field, a, b, twisting, origin, direction, t0, radius):
    """Ściany boczne jednego konturu na odcinku [a, b]."""
    d = np.asarray(direction, float)
    placed = _placed(wire, _trsf(origin, d, float(field.theta(a)), a - t0))
    if not twisting:
        from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
        from OCP.gp import gp_Vec
        return cq.Shape.cast(BRepPrimAPI_MakePrism(placed.wrapped, gp_Vec(*map(float, d * (b - a)))).Shape()).Faces()
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell
    o = np.asarray(origin, float)
    spine = cq.Wire.assembleEdges([cq.Edge.makeLine(cq.Vector(*(o + d * a)), cq.Vector(*(o + d * b)))])
    guide = _guide(field, a, b, o, d, radius)
    pipe = BRepOffsetAPI_MakePipeShell(spine.wrapped)
    pipe.SetMode(guide.wrapped, False)               # obrót przekroju prowadzi krzywa pomocnicza (bez równoważności łukowej)
    pipe.SetTolerance(1e-6, 1e-6, 1e-4)
    pipe.Add(placed.wrapped, False, False)
    pipe.Build()
    if not pipe.IsDone():
        raise TwistError('Open CASCADE nie zbudował skręconych ścian bocznych - zmniejsz kąt albo wybierz inną oś.')
    return cq.Shape.cast(pipe.Shape()).Faces()


def _sew(faces, tolerance):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.BRepLib import BRepLib
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    sewing = BRepBuilderAPI_Sewing(tolerance, True, True, True, False)
    for f in faces:
        sewing.Add(f.wrapped)
    sewing.Perform()
    explorer = TopExp_Explorer(sewing.SewedShape(), TopAbs_SHELL)
    if not explorer.More():
        return None
    shell = TopoDS.Shell_s(explorer.Current())
    explorer.Next()
    if explorer.More():
        return None
    raw = BRepBuilderAPI_MakeSolid(shell).Solid()
    BRepLib.OrientClosedSolid_s(raw)                 # ściany zorientowane na zewnątrz
    return _forward(cq.Shape.cast(raw))


def _twisted_faces(section, ta, tb, field, o, d, radius):
    """Ściany skręconej warstwy [ta, tb] o przekroju section (płaska ściana na poziomie ta, z otworami)."""
    wires = [section.outerWire(), *section.innerWires()]
    faces = []
    for a, b, twisting in _segments(field, ta, tb):
        for wire in wires:
            faces += _lateral(wire, field, a, b, twisting, o, d, ta, radius)
    faces.append(_placed(section, _trsf(o, d, float(field.theta(ta)), 0.0)))
    faces.append(_placed(section, _trsf(o, d, float(field.theta(tb)), tb - ta)))
    return faces


def _guide_radius(shape, o, d):
    box = kernel.bounds(shape)
    size = max(box.xlen, box.ylen, box.zlen, 1.0)
    pts = np.array([v.toTuple() for v in shape.Vertices()], float)
    radial = np.linalg.norm((pts - o) - np.outer((pts - o) @ d, d), axis=1) if len(pts) else np.zeros(1)
    return max(float(radial.max()), .1 * size, 1.0)


def _forward(solid):
    """Bryła z orientacją FORWARD bryły i powłok - każda ściana z orientacją wypadkową (jak widać ją z bryły).
    BRepLib.OrientClosedSolid może zostawić bryłę oznaczoną REVERSED: objętość i BRepCheck są wtedy poprawne, ale
    kolejne operacje (np. zaokrąglanie krawędzi) liczą ją jak wywróconą na lewą stronę."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS, TopoDS_Shell
    builder = BRep_Builder()
    maker = BRepBuilderAPI_MakeSolid()
    shells = TopExp_Explorer(solid.wrapped, TopAbs_SHELL)
    while shells.More():
        shell = TopoDS_Shell()
        builder.MakeShell(shell)
        faces = TopExp_Explorer(shells.Current(), TopAbs_FACE)   # orientacja ściany złożona z orientacji bryły i powłoki
        while faces.More():
            builder.Add(shell, faces.Current())
            faces.Next()
        shell.Closed(True)
        maker.Add(shell)
        shells.Next()
    return cq.Shape.cast(TopoDS.Solid_s(maker.Solid()))


def twist_solid(shape, field: tm.TwistField, tolerance=TOLERANCE):
    """Skręcona bryła B-Rep (nowy TopoDS_Shape w cq.Solid) albo TwistError. Oryginał nie jest zmieniany.
    Kąt 0 - kopia oryginału. Graniastosłup - jedno zszycie ścian (etap 5); bryła schodkowa - warstwy (etap 6)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    if abs(field.angle) < 1e-12:
        return cq.Shape.cast(BRepBuilderAPI_Copy(shape.wrapped).Shape())
    o, d = np.asarray(field.origin, float), np.asarray(field.direction, float)
    try:
        bottom, t0, t1 = prism_profile(shape, o, d)
    except TwistError as prism_error:
        layers = stepped_layers(shape, o, d, prism_error)
        return _twist_layers(shape, layers, field, o, d, tolerance)
    radius = _guide_radius(shape, o, d)
    faces = _twisted_faces(bottom, t0, t1, field, o, d, radius)
    report = None
    for sew_tol in (1e-6, 1e-5, 1e-4):
        solid = _sew(faces, sew_tol)
        report = check(solid, shape, field, tolerance) if solid is not None else None
        if report is not None and report['ok']:
            return solid
    raise TwistError(_failure(report))


# ---------------------------------------------------------------------------------------------- bryły schodkowe (etap 6)
def stepped_layers(shape, origin, direction, prism_error=None):
    """Podział bryły schodkowej na warstwy o stałym przekroju: [(ta, tb, [ściany przekroju na poziomie ta])].
    Każda ściana bryły musi być płaska i prostopadła do osi (poziom stały) albo równoległa do osi; inaczej TwistError."""
    solids = shape.Solids() if hasattr(shape, 'Solids') else []
    if len(solids) != 1:
        raise TwistError('TWIST skręca jedną bryłę - ten obiekt nie jest pojedynczą bryłą.')
    solid = solids[0]
    d = np.asarray(direction, float)
    o = np.asarray(origin, float)
    size, lin, ang = _tolerances(solid)
    levels = []
    for face in solid.Faces():
        level = _cap_level(face, o, d, lin, ang)
        if level is not None:
            levels.append(level)
            continue
        if not _parallel_to_axis(face, d, ang):
            raise TwistError('TWIST obsługuje bryły z otworami, kieszeniami i stopniami tylko wtedy, gdy wszystkie ich ściany '
                             'biegną wzdłuż osi skręcenia albo są do niej prostopadłe - ta bryła ma ściany ukośne, zaokrąglone '
                             'w poprzek osi albo otwór poprzeczny. Bryła bez zmian.')
    t = _axial([v.toTuple() for v in solid.Vertices()], o, d)
    if not len(t) or float(t.max() - t.min()) < 1e-6:
        raise TwistError('Bryła nie ma długości wzdłuż osi skręcenia - wybierz inną oś.')
    cuts = []
    for level in sorted(levels + [float(t.min()), float(t.max())]):
        if not cuts or level - cuts[-1] > lin * 10:
            cuts.append(level)
    if len(cuts) < 2:
        raise prism_error or TwistError('Bryła nie ma podstaw prostopadłych do osi skręcenia.')
    reach = 4 * size
    layers = []
    for ta, tb in zip(cuts[:-1], cuts[1:]):
        sections = _section(solid, o, d, (ta + tb) / 2, reach)
        if not sections:
            raise TwistError('Bryła ma przerwę wzdłuż osi skręcenia - TWIST jej nie obsługuje. Bryła bez zmian.')
        shift = d * (ta - (ta + tb) / 2)
        layers.append((ta, tb, [f.translate(cq.Vector(*shift)) for f in sections]))
    _check_layers(solid, layers)
    return layers


def _section(solid, o, d, t, reach):
    """Dokładny przekrój bryły płaszczyzną prostopadłą do osi w położeniu t: płaskie ściany (z otworami)."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    plane = gp_Pln(gp_Pnt(*map(float, o + d * t)), gp_Dir(*map(float, d)))
    disc = BRepBuilderAPI_MakeFace(plane, -reach, reach, -reach, reach).Face()
    common = BRepAlgoAPI_Common(solid.wrapped, disc)
    if not common.IsDone():
        raise TwistError('Nie udało się wyznaczyć przekroju bryły - bryła bez zmian.')
    return [f for f in cq.Shape.cast(common.Shape()).Faces() if _area(f) > 1e-12]


def _check_layers(solid, layers):
    """Warstwy odtwarzają bryłę: suma objętości warstw (pole przekroju × wysokość) równa objętości bryły."""
    total = sum(sum(_area(f) for f in sections) * (tb - ta) for ta, tb, sections in layers)
    volume = _volume(solid)
    if abs(total - volume) > 1e-6 * max(volume, 1.0):
        raise TwistError('Przekrój bryły zmienia się w sposób, którego TWIST jeszcze nie obsługuje (ściany ukośne do osi) - bryła bez zmian.')


def _twist_layers(shape, layers, field, o, d, tolerance):
    """Każda warstwa skręcona jak graniastosłup i zszyta w bryłę; warstwy złączone (BRepAlgoAPI_Fuse) i oczyszczone
    (ShapeUpgrade_UnifySameDomain - ściany tej samej płaszczyzny / powierzchni scalone, wspólne krawędzie jednej
    krawędzi). Kontrola całości jak dla graniastosłupa, z liczbą powłok równą oryginałowi (puste przestrzenie)."""
    radius = _guide_radius(shape, o, d)
    pieces = []
    for ta, tb, sections in layers:
        for section in sections:
            faces = _twisted_faces(section, ta, tb, field, o, d, radius)
            piece = None
            for sew_tol in (1e-6, 1e-5, 1e-4):
                piece = _sew(faces, sew_tol)
                if piece is not None and _piece_ok(piece, _area(section) * (tb - ta)):
                    break
                piece = None
            if piece is None:
                raise TwistError('Nie udało się zbudować skręconej warstwy bryły - zmniejsz kąt; bryła bez zmian.')
            pieces.append(piece)
    result = _fuse(pieces)
    report = check(result, shape, field, tolerance)
    if not report['ok']:
        raise TwistError(_failure(report))
    return result


def _piece_ok(piece, volume):
    from OCP.BRepCheck import BRepCheck_Analyzer
    return bool(BRepCheck_Analyzer(piece.wrapped, True).IsValid()) and abs(_volume(piece) - volume) < 1e-3 * max(volume, 1e-9)


def _fuse(pieces):
    """Złączenie warstw (stykają się płaskimi ścianami na granicach warstw) w jedną bryłę."""
    from OCP.BOPAlgo import BOPAlgo_GlueShift
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.TopTools import TopTools_ListOfShape
    if len(pieces) == 1:
        return pieces[0]
    args, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    args.Append(pieces[0].wrapped)
    for p in pieces[1:]:
        tools.Append(p.wrapped)
    fuse = BRepAlgoAPI_Fuse()
    fuse.SetArguments(args)
    fuse.SetTools(tools)
    fuse.SetGlue(BOPAlgo_GlueShift)                  # warstwy tylko się stykają - szybszy tryb sklejania
    fuse.SetFuzzyValue(1e-6)
    fuse.Build()
    if not fuse.IsDone():
        raise TwistError('Nie udało się połączyć skręconych warstw bryły - bryła bez zmian.')
    unify = ShapeUpgrade_UnifySameDomain(fuse.Shape(), True, True, False)
    unify.Build()
    shape = cq.Shape.cast(unify.Shape())
    solids = shape.Solids()
    if len(solids) != 1:
        raise TwistError('Skręcone warstwy nie tworzą jednej bryły - bryła bez zmian.')
    return _forward(solids[0])


# ---------------------------------------------------------------------------------------------- kontrola
def check(result, original, field, tolerance=TOLERANCE):
    """Raport kontroli wyniku: valid (BRepCheck_Analyzer), solids, closed (powłoka zamknięta), self (brak samoprzecięć -
    BRepAlgoAPI_Check), volume (zmiana objętości), deviation (największa odchyłka od dokładnego skręcenia), ok."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Check
    from OCP.BRepCheck import BRepCheck_Analyzer
    report = dict(valid=False, solids=0, closed=False, self=False, volume=None, deviation=None, ok=False)
    if result is None:
        return report
    from OCP.TopAbs import TopAbs_FORWARD
    report['valid'] = bool(BRepCheck_Analyzer(result.wrapped, True).IsValid())
    report['forward'] = all(s.wrapped.Orientation() == TopAbs_FORWARD for s in result.Solids())
    solids = result.Solids()
    shells = [sh for s in solids for sh in s.Shells()]
    report['solids'] = len(solids)
    expected = max(1, len([sh for s in original.Solids() for sh in s.Shells()]))      # wewnętrzne powłoki (puste przestrzenie) zostają
    report['shells'] = len(shells)
    report['closed'] = len(shells) == expected and all(BRep_Tool.IsClosed_s(sh.wrapped) for sh in shells)
    report['self'] = bool(BRepAlgoAPI_Check(result.wrapped, True, True).IsValid()) if report['valid'] else False
    v0, v1 = _volume(original), _volume(result)
    report['volume'] = abs(v1 - v0) / max(abs(v0), 1e-12)
    report['deviation'] = deviation(result, original, field)
    report['ok'] = (report['valid'] and report['forward'] and report['solids'] == 1 and report['closed'] and report['self'] and v1 > 0
                    and report['volume'] < VOLUME_TOLERANCE and report['deviation'] <= tolerance)
    return report


def control_points(original, count=7):
    """Punkty kontrolne na krawędziach i w środkach ścian oryginału."""
    pts = [v.toTuple() for v in original.Vertices()]
    for edge in original.Edges():
        pts += [edge.positionAt(s).toTuple() for s in np.linspace(0, 1, count)]
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.TopAbs import TopAbs_IN
    from OCP.gp import gp_Pnt2d
    for face in original.Faces():
        surface = BRepAdaptor_Surface(face.wrapped)
        u0, u1, v0, v1 = face._uvBounds()
        for u in np.linspace(u0, u1, 5)[1:-1]:
            for v in np.linspace(v0, v1, 5)[1:-1]:
                if BRepClass_FaceClassifier(face.wrapped, gp_Pnt2d(float(u), float(v)), 1e-7).State() == TopAbs_IN:
                    p = surface.Value(float(u), float(v))
                    pts.append((p.X(), p.Y(), p.Z()))
    return np.array(pts, float)


def deviation(result, original, field):
    """Największa odległość punktów kontrolnych po dokładnym skręceniu (silnik twist_math) od ścian wyniku.
    Punkt rzutowany na powierzchnie ścian (ShapeAnalysis_Surface) - liczy się tylko rzut leżący w obrębie ściany
    (BRepClass_FaceClassifier); gdy żaden nie trafia w ścianę - dokładna odległość od całej bryły (BRepExtrema)."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepClass import BRepClass_FaceClassifier
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.ShapeAnalysis import ShapeAnalysis_Surface
    from OCP.TopAbs import TopAbs_OUT
    from OCP.gp import gp_Pnt
    box = kernel.bounds(result)
    tol = 1e-7 * max(box.xlen, box.ylen, box.zlen, 1.0)
    faces = [(f.wrapped, ShapeAnalysis_Surface(BRep_Tool.Surface_s(f.wrapped))) for f in result.Faces()]
    worst = 0.0
    for p in field.apply(control_points(original)):
        point = gp_Pnt(*map(float, p))
        best = float('inf')
        for face, analysis in faces:
            uv = analysis.ValueOfUV(point, tol)
            gap = analysis.Gap()
            if gap < best and BRepClass_FaceClassifier(face, uv, 1e-6).State() != TopAbs_OUT:
                best = gap
        if best == float('inf'):
            dist = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(point).Vertex(), result.wrapped)
            best = dist.Value() if dist.IsDone() else float('inf')
        worst = max(worst, best)
    return worst


def _failure(report):
    if report is None:
        return 'Nie udało się zamknąć skręconej bryły (ściany się nie zszyły) - oryginał bez zmian.'
    if not report['valid'] or not report.get('forward', True) or report['solids'] != 1 or not report['closed']:
        return 'Skręcona bryła nie jest poprawna (Open CASCADE: BRepCheck / powłoka niezamknięta) - oryginał bez zmian.'
    if not report['self']:
        return 'Skręcona bryła przecina samą siebie - zmniejsz kąt skręcenia; oryginał bez zmian.'
    if report['volume'] is not None and report['volume'] >= VOLUME_TOLERANCE:
        return f'Objętość skręconej bryły różni się o {report["volume"] * 100:.2g}% - wynik odrzucony, oryginał bez zmian.'
    return (f'Skręcona powierzchnia odbiega od dokładnej o {report["deviation"]:.3g} mm (dopuszczalne {TOLERANCE:g} mm) - '
            'zmniejsz kąt; oryginał bez zmian.')
