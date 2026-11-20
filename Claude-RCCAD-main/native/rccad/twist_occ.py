"""TWIST – rzeczywiste skręcanie brył B-Rep (Open CASCADE), etap 5: bryły o stałym przekroju wzdłuż osi.

Obsługiwane są tylko graniastosłupy względem osi skręcenia: dwie płaskie podstawy prostopadłe do osi (ten sam przekrój,
także z otworami), wszystkie pozostałe ściany równoległe do osi (np. prostopadłościan, graniastosłup, walec z otworem
wzdłuż osi). Inne bryły są odrzucane z komunikatem - oryginał zostaje bez zmian.

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
def prism_profile(shape, origin, direction, tol=1e-6):
    """(dolna podstawa - cq.Face, t0, t1) dla bryły o stałym przekroju wzdłuż osi albo TwistError z opisem."""
    solids = shape.Solids() if hasattr(shape, 'Solids') else []
    if len(solids) != 1:
        raise TwistError('TWIST skręca jedną bryłę - ten obiekt nie jest pojedynczą bryłą.')
    solid = solids[0]
    d = np.asarray(direction, float)
    size = max(kernel.bounds(solid).xlen, kernel.bounds(solid).ylen, kernel.bounds(solid).zlen, 1.0)
    lin = max(tol, 1e-7 * size)
    t = _axial([v.toTuple() for v in solid.Vertices()], origin, d)
    if not len(t):
        raise TwistError('Bryła bez wierzchołków (np. kula lub torus) - TWIST obsługuje na razie tylko graniastosłupy wzdłuż osi.')
    t0, t1 = float(t.min()), float(t.max())
    if t1 - t0 < 1e-6:
        raise TwistError('Bryła nie ma długości wzdłuż osi skręcenia - wybierz inną oś.')
    caps = {0: [], 1: []}
    for face in solid.Faces():
        if face.geomType() == 'PLANE':
            n = np.asarray(face.normalAt(face.Center()).toTuple(), float)
            ft = _axial([v.toTuple() for v in face.Vertices()] or [face.Center().toTuple()], origin, d)
            if abs(abs(float(n @ d)) - 1) < 1e-7 and np.ptp(ft) < lin:
                if abs(float(ft[0]) - t0) < lin:
                    caps[0].append(face)
                    continue
                if abs(float(ft[0]) - t1) < lin:
                    caps[1].append(face)
                    continue
        if not _parallel_to_axis(face, d):
            raise TwistError('TWIST obsługuje na razie tylko bryły o stałym przekroju wzdłuż osi skręcenia '
                             '(np. prostopadłościan, graniastosłup) - ta bryła ma ściany ukośne albo zmienny przekrój względem tej osi.')
    if len(caps[0]) != 1 or len(caps[1]) != 1:
        raise TwistError('Bryła nie ma dwóch płaskich podstaw prostopadłych do osi skręcenia - wybierz oś wzdłuż graniastosłupa.')
    bottom, top = caps[0][0], caps[1][0]
    area = bottom.Area()
    if abs(top.Area() - area) > 1e-6 * max(area, 1.0) or abs(solid.Volume() - area * (t1 - t0)) > 1e-6 * max(solid.Volume(), 1.0):
        raise TwistError('Przekrój bryły zmienia się wzdłuż osi skręcenia - TWIST obsługuje na razie tylko stały przekrój.')
    shift = np.asarray(top.Center().toTuple(), float) - np.asarray(bottom.Center().toTuple(), float)
    if np.linalg.norm(shift - d * (t1 - t0)) > max(1e-5, 1e-7 * size):
        raise TwistError('Podstawy bryły są przesunięte względem osi skręcenia (graniastosłup pochyły) - wybierz oś wzdłuż bryły.')
    return bottom, t0, t1


def _parallel_to_axis(face, d):
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
            if abs(float(np.dot((normal.X(), normal.Y(), normal.Z()), d))) > 1e-6 * length:
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
    return cq.Shape.cast(raw)


def twist_solid(shape, field: tm.TwistField, tolerance=TOLERANCE):
    """Skręcona bryła B-Rep (nowy TopoDS_Shape w cq.Solid) albo TwistError. Oryginał nie jest zmieniany.
    Kąt 0 - kopia oryginału."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    if abs(field.angle) < 1e-12:
        return cq.Shape.cast(BRepBuilderAPI_Copy(shape.wrapped).Shape())
    o, d = np.asarray(field.origin, float), np.asarray(field.direction, float)
    bottom, t0, t1 = prism_profile(shape, o, d)
    box = kernel.bounds(shape)
    size = max(box.xlen, box.ylen, box.zlen, 1.0)
    pts = np.array([v.toTuple() for v in shape.Vertices()], float)
    radial = np.linalg.norm((pts - o) - np.outer((pts - o) @ d, d), axis=1)
    radius = max(float(radial.max()), .1 * size, 1.0)
    wires = [bottom.outerWire(), *bottom.innerWires()]
    faces = []
    for a, b, twisting in _segments(field, t0, t1):
        for wire in wires:
            faces += _lateral(wire, field, a, b, twisting, o, d, t0, radius)
    faces.append(_placed(bottom, _trsf(o, d, float(field.theta(t0)), 0.0)))
    faces.append(_placed(bottom, _trsf(o, d, float(field.theta(t1)), t1 - t0)))
    report = None
    for sew_tol in (1e-6, 1e-5, 1e-4):
        solid = _sew(faces, sew_tol)
        report = check(solid, shape, field, tolerance) if solid is not None else None
        if report is not None and report['ok']:
            return solid
    raise TwistError(_failure(report))


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
    report['valid'] = bool(BRepCheck_Analyzer(result.wrapped, True).IsValid())
    solids = result.Solids()
    shells = [sh for s in solids for sh in s.Shells()]
    report['solids'] = len(solids)
    report['closed'] = len(shells) == 1 and all(BRep_Tool.IsClosed_s(sh.wrapped) for sh in shells)
    report['self'] = bool(BRepAlgoAPI_Check(result.wrapped, True, True).IsValid()) if report['valid'] else False
    v0, v1 = original.Volume(), result.Volume()
    report['volume'] = abs(v1 - v0) / max(abs(v0), 1e-12)
    report['deviation'] = deviation(result, original, field)
    report['ok'] = (report['valid'] and report['solids'] == 1 and report['closed'] and report['self'] and v1 > 0
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
    if not report['valid'] or report['solids'] != 1 or not report['closed']:
        return 'Skręcona bryła nie jest poprawna (Open CASCADE: BRepCheck / powłoka niezamknięta) - oryginał bez zmian.'
    if not report['self']:
        return 'Skręcona bryła przecina samą siebie - zmniejsz kąt skręcenia; oryginał bez zmian.'
    if report['volume'] is not None and report['volume'] >= VOLUME_TOLERANCE:
        return f'Objętość skręconej bryły różni się o {report["volume"] * 100:.2g}% - wynik odrzucony, oryginał bez zmian.'
    return (f'Skręcona powierzchnia odbiega od dokładnej o {report["deviation"]:.3g} mm (dopuszczalne {TOLERANCE:g} mm) - '
            'zmniejsz kąt; oryginał bez zmian.')
