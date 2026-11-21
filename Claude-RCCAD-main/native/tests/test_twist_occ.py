"""TWIST – rzeczywiste skręcanie brył B-Rep o stałym przekroju (rccad/twist_occ.py), krok historii i eksport STEP."""
import math
import tempfile
import unittest
from pathlib import Path

import cadquery as cq
import numpy as np

from rccad import history as hist
from rccad import kernel as k
from rccad import twist as tw
from rccad import twist_occ as to
from rccad.document import Body

Z = dict(kind='global', axis='Z')


def corners(shape):
    return np.array(sorted(tuple(round(c, 6) + 0.0 for c in v.toTuple()) for v in shape.Vertices()), float)


def has_point(shape, p, tol=1e-6):
    return float(np.min(np.linalg.norm(corners(shape) - np.asarray(p, float), axis=1))) < tol


def inside(shape, p):
    return k.point_state(shape, p) == 'in'


class TwistSolidTests(unittest.TestCase):
    def setUp(self):
        self.box = k.box(20, 30, 80)                    # środek (10, 15, 40), oś Z przez środek

    def twisted(self, shape, angle, spec=Z, rf=0.0, rt=1.0, kind='linear'):
        field = tw.field(spec, shape, angle, rf, rt, kind)
        before = [v.toTuple() for v in shape.Vertices()]
        result = to.twist_solid(shape, field)
        self.assertEqual([v.toTuple() for v in shape.Vertices()], before)          # oryginał nietknięty
        return result, field

    def assert_good(self, result, original, field):
        report = to.check(result, original, field)
        self.assertTrue(report['ok'], report)
        self.assertTrue(report['valid'] and report['closed'] and report['self'])
        self.assertEqual(report['solids'], 1)
        self.assertLess(report['deviation'], to.TOLERANCE)
        self.assertAlmostEqual(result.Volume(), original.Volume(), delta=1e-4 * original.Volume())
        self.assertFalse(k.is_triangle_mesh(result))
        c = np.asarray(original.Center().toTuple(), float)
        for v in original.Vertices():                                                # orientacja: punkty materiału w środku bryły
            q = np.asarray(v.toTuple(), float) * .95 + c * .05
            if inside(original, q):
                self.assertTrue(inside(result, field.apply(q)))
        return report

    def test_required_angles(self):
        for angle in (90.0, 180.0, 360.0, -90.0, -180.0, 720.0):
            result, field = self.twisted(self.box, angle)
            self.assert_good(result, self.box, field)
            self.assertEqual(len(result.Faces()), 6, angle)
            types = sorted(f.geomType() for f in result.Faces())
            self.assertEqual(types.count('PLANE'), 2)                                  # podstawy
            self.assertEqual(types.count('BSPLINE'), 4)                                # skręcone boki - NURBS
            for p in [v.toTuple() for v in self.box.Vertices()]:                       # wierzchołki = silnik twist_math
                self.assertTrue(has_point(result, field.apply(p)), (angle, p))
        r90, _ = self.twisted(self.box, 90.0)
        self.assertTrue(has_point(r90, (25, 5, 80)) and has_point(r90, (-5, 25, 80)))   # góra obrócona o 90° w lewo
        self.assertTrue(has_point(r90, (0, 0, 0)) and has_point(r90, (20, 30, 0)))      # dół bez zmian
        rm, _ = self.twisted(self.box, -90.0)
        self.assertTrue(has_point(rm, (-5, 5, 80)) and has_point(rm, (25, 25, 80)))      # ujemny kąt - w prawo
        r360, _ = self.twisted(self.box, 360.0)
        np.testing.assert_allclose(corners(r360), corners(self.box), atol=1e-6)         # wierzchołki wracają, boki skręcone
        self.assertTrue(inside(r360, (24, 15, 20)) and not inside(self.box, (24, 15, 20)))   # na 1/4 wysokości przekrój obrócony o 90°
        self.assertFalse(inside(r360, (10, 29, 20)))

    def test_zero_angle_returns_copy(self):
        field = tw.field(Z, self.box, 0.0)
        result = to.twist_solid(self.box, field)
        self.assertFalse(result.wrapped.IsSame(self.box.wrapped))
        np.testing.assert_allclose(corners(result), corners(self.box))
        self.assertAlmostEqual(result.Volume(), self.box.Volume(), 9)

    def test_prisms_holes_axes_and_ranges(self):
        hexagon = cq.Workplane().polygon(6, 30).extrude(60).val()
        holed = cq.Workplane().box(20, 30, 80).faces('>Z').workplane().hole(8).val()
        cylinder = cq.Workplane().cylinder(50, 10).val()
        cases = [(hexagon, 120.0, Z, 0, 1, 'linear'), (holed, 90.0, Z, 0, 1, 'linear'), (cylinder, 90.0, Z, 0, 1, 'linear'),
                 (self.box, 90.0, dict(kind='global', axis='X'), 0, 1, 'linear'),
                 (self.box, 90.0, dict(kind='global', axis='Z', reverse=True), 0, 1, 'linear'),
                 (self.box, 90.0, Z, .25, .75, 'linear'), (self.box, 90.0, Z, 0, 1, 'smoothstep'),
                 (self.box, 180.0, Z, 0, 1, 'progressive'), (self.box, 60.0, dict(kind='local', axis='Z'), 0, 1, 'linear')]
        for shape, angle, spec, rf, rt, kind in cases:
            result, field = self.twisted(shape, angle, spec, rf, rt, kind)
            self.assert_good(result, shape, field)
        part, field = self.twisted(self.box, 90.0, Z, .25, .75)
        self.assertTrue(has_point(part, (20, 30, 0)))                                 # poniżej zakresu bez obrotu
        self.assertTrue(has_point(part, (20, 0, 20)))                                 # granica zakresu (krawędź pośrednia)
        self.assertTrue(has_point(part, (-5, 25, 80)))                                # powyżej zakresu pełny kąt
        back, _ = self.twisted(self.box, 90.0, dict(kind='global', axis='Z', reverse=True))
        self.assertTrue(has_point(back, (20, 30, 80)))                                # odwrócona oś: góra bez zmian...
        self.assertTrue(has_point(back, (25, 25, 0)))                                 # ...dół obrócony (w prawo patrząc od +Z)

    def test_unsupported_bodies_are_rejected(self):
        chamfered = cq.Workplane().box(20, 30, 80).edges('>Z').chamfer(3).val()
        pyramid = cq.Solid.makeCone(10, 0, 30)
        tilted = k.transform(self.box, (0, 0, 0), (10, 0, 0))
        two = cq.Compound.makeCompound([k.box(5, 5, 5), k.box(5, 5, 5).translate(cq.Vector(10, 0, 0))])
        for shape, spec in ((chamfered, Z), (pyramid, Z), (tilted, Z), (two, Z), (self.box, dict(kind='points', p=(0, 0, 0), d=(1, 1, 1)))):
            field = tw.field(spec, shape, 90.0)
            with self.assertRaises(to.TwistError):
                to.twist_solid(shape, field)
        self.assertTrue(issubclass(to.TwistError, k.CadError))

    def test_check_detects_wrong_result(self):
        f90 = tw.field(Z, self.box, 90.0)
        wrong = to.twist_solid(self.box, tw.field(Z, self.box, 91.0))
        report = to.check(wrong, self.box, f90)
        self.assertFalse(report['ok'])
        self.assertGreater(report['deviation'], to.TOLERANCE)
        self.assertIn('odbiega', to._failure(report))

    def test_step_export_and_import(self):
        result, field = self.twisted(cq.Workplane().box(20, 30, 80).faces('>Z').workplane().hole(8).val(), 180.0)
        path = Path(tempfile.mkdtemp()) / 'twist.step'
        k.export_shapes([result], path)
        loaded = k.import_shapes(path)
        self.assertEqual(len(loaded), 1)
        shape, kind = loaded[0]
        self.assertEqual(kind, 'solid')
        self.assertAlmostEqual(shape.Volume(), result.Volume(), delta=1e-6 * result.Volume())
        self.assertEqual(len(shape.Faces()), len(result.Faces()))
        self.assertTrue(to.check(shape, cq.Workplane().box(20, 30, 80).faces('>Z').workplane().hole(8).val(), field)['ok'])

    def test_history_step(self):
        a = Body('A', self.box).prepared()
        b = Body('B', k.box(5, 5, 5)).prepared()
        recipe = dict(type='twist', id=a.id, angle=90.0, axis=Z, range_from=0.0, range_to=1.0, kind='linear', power=2.0)
        out = hist.RUNNERS['twist']([a, b], recipe)
        self.assertEqual([x.id for x in out], [a.id, b.id])
        self.assertIs(out[1], b)
        self.assertTrue(has_point(out[0].shape, (25, 5, 80)))
        again = hist.RUNNERS['twist']([a, b], recipe)                                   # powtórzenie z przepisu - ten sam wynik
        np.testing.assert_allclose(corners(again[0].shape), corners(out[0].shape), atol=1e-9)
        self.assertEqual(set(hist.reads(recipe, [a, b])), {a.id})
        sketch = Body('S', k.sketch('rectangle', 'XY', 4, 4), 'sketch', 'XY').prepared()
        with self.assertRaises(k.CadError):
            hist.RUNNERS['twist']([sketch], dict(recipe, id=sketch.id))
        cone = Body('C', cq.Solid.makeCone(5, 0, 10)).prepared()
        with self.assertRaises(k.CadError):
            hist.RUNNERS['twist']([cone], dict(recipe, id=cone.id))



W = cq.Workplane


class SteppedTwistTests(unittest.TestCase):
    """Etap 6: otwory przelotowe i nieprzelotowe, wiele otworów, kieszeń, pogłębienie, pusta przestrzeń wewnątrz."""

    def twist(self, shape, angle=90.0, rf=0.0, rt=1.0, kind='linear'):
        field = tw.field(Z, shape, angle, rf, rt, kind)
        before = (shape.Volume(), len(shape.Faces()))
        result = to.twist_solid(shape, field)
        self.assertEqual((shape.Volume(), len(shape.Faces())), before)                 # oryginał nietknięty
        report = to.check(result, shape, field)
        self.assertTrue(report['ok'], report)
        self.assertAlmostEqual(result.Volume(), shape.Volume(), delta=1e-4 * shape.Volume())
        self.assertFalse(k.is_triangle_mesh(result))
        return result, field

    def assert_open(self, result, field, points):
        """Otwór nie zamknięty: punkty na osi otworu (po skręceniu) są poza materiałem."""
        for p in points:
            self.assertFalse(inside(result, field.apply(p)), p)

    def test_single_blind_hole(self):
        blind = W().box(30, 40, 80).faces('>Z').workplane().hole(8, 30).val()        # bryła z = -40..40, otwór Ø8 z = 10..40
        result, field = self.twist(blind, 90.0)
        self.assert_open(result, field, [(0, 0, 15), (0, 0, 39), (3.5, 0, 25)])
        self.assertTrue(inside(result, field.apply((0, 0, 5))))                      # pod dnem otworu - materiał
        self.assertTrue(any(abs(f.Area() - math.pi * 16) < 1e-6 for f in result.Faces() if f.geomType() == 'PLANE'))  # płaskie dno
        part, field = self.twist(blind, 120.0, .2, .9, 'smoothstep')
        self.assert_open(part, field, [(0, 0, 20)])

    def test_through_hole_off_axis_follows_local_angle(self):
        shape = W().box(30, 40, 80).faces('>Z').workplane().pushPoints([(8, 12)]).hole(6).val()
        result, field = self.twist(shape, 180.0)
        for z in (-39, -20, 0, 20, 39):                                               # oś otworu skręca się o lokalny kąt
            q = field.apply((8, 12, z))
            self.assertFalse(inside(result, q), z)
            self.assertAlmostEqual(math.degrees(math.atan2(q[1], q[0])) % 360, (math.degrees(math.atan2(12, 8)) + 180 * (z + 40) / 80) % 360, 6)
        self.assertTrue(inside(result, field.apply((-8, -12, 0))))

    def test_many_holes_including_small_detail(self):
        shape = (W().box(30, 40, 80).faces('>Z').workplane().rarray(12, 16, 2, 2).hole(5)
                 .faces('>Z').workplane().pushPoints([(0, 0)]).hole(.4, 20).val())  # 4 przelotowe i jeden mały Ø0,4 nieprzelotowy
        result, field = self.twist(shape, 90.0)
        self.assert_open(result, field, [(6, 8, 0), (-6, 8, 0), (6, -8, 30), (-6, -8, -30), (0, 0, 35), (0, 0, 21)])
        small = [f for f in result.Faces() if f.geomType() == 'PLANE' and abs(f.Area() - math.pi * .04) < 1e-6]
        self.assertEqual(len(small), 1)                                               # mały szczegół (dno Ø0,4) został

    def test_pocket_counterbore_and_step(self):
        pocket = W().box(30, 40, 80).faces('>Z').workplane().rect(16, 20).cutBlind(-20).val()
        result, field = self.twist(pocket, -90.0)
        self.assert_open(result, field, [(0, 0, 30), (7, 9, 39), (-7, -9, 21)])
        self.assertTrue(inside(result, field.apply((0, 0, 15))))
        cbore = W().box(30, 40, 80).faces('>Z').workplane().cboreHole(6, 12, 10).val()
        result, field = self.twist(cbore, 180.0)
        self.assert_open(result, field, [(0, 0, -30), (5, 0, 35)])
        self.assertTrue(inside(result, field.apply((5, 0, 0))))                      # poza pogłębieniem materiał
        step = W().box(30, 40, 40).faces('>Z').workplane().rect(20, 20).extrude(30).val()
        self.twist(step, 90.0)

    def test_internal_void_keeps_inner_shell(self):
        void = W().box(30, 40, 80).cut(W().box(10, 10, 20)).val()
        self.assertEqual(len(void.Shells()), 2)
        result, field = self.twist(void, 90.0)
        self.assertEqual(len(result.Solids()), 1)
        self.assertEqual(len(result.Shells()), 2)                                     # pusta przestrzeń zostaje osobną powłoką
        self.assert_open(result, field, [(0, 0, 0), (4, 4, 9)])
        self.assertTrue(inside(result, field.apply((0, 0, 15))))
        self.assertTrue(to.check(result, void, field)['self'])

    def test_unsupported_details_are_rejected(self):
        cross = W().box(30, 40, 80).faces('>X').workplane().hole(8).val()          # otwór poprzeczny do osi
        tapered = W().box(30, 40, 80).faces('>Z').workplane().hole(8, 30).faces('>Z').edges('not %LINE').chamfer(1).val()
        sphere_void = W().box(30, 40, 80).cut(W().sphere(5)).val()
        for shape in (cross, tapered, sphere_void):
            volume = shape.Volume()
            with self.assertRaises(to.TwistError):
                to.twist_solid(shape, tw.field(Z, shape, 90.0))
            self.assertEqual(shape.Volume(), volume)

    def test_history_and_step_export(self):
        pocket = W().box(30, 40, 80).faces('>Z').workplane().rect(16, 20).cutBlind(-20).faces('<Z').workplane().hole(6).val()
        body = Body('P', pocket).prepared()
        recipe = dict(type='twist', id=body.id, angle=90.0, axis=Z, range_from=0.0, range_to=1.0, kind='linear', power=2.0)
        out = hist.RUNNERS['twist']([body], recipe)[0]
        self.assertAlmostEqual(out.shape.Volume(), pocket.Volume(), delta=1e-4 * pocket.Volume())
        path = Path(tempfile.mkdtemp()) / 'pocket.step'
        k.export_shapes([out.shape], path)
        shape, kind = k.import_shapes(path)[0]
        self.assertEqual(kind, 'solid')
        self.assertAlmostEqual(shape.Volume(), out.shape.Volume(), delta=1e-6 * out.shape.Volume())
        self.assertEqual(len(shape.Faces()), len(out.shape.Faces()))


class StepImportTwistTests(unittest.TestCase):
    """Etap 7: bryły z pliku STEP - płaskie ściany zapisane jako NURBS, większe tolerancje, dalsza edycja wyniku."""

    def roundtrip(self, shapes):
        path = Path(tempfile.mkdtemp()) / 'model.step'
        cq.exporters.export(cq.Compound.makeCompound(shapes), str(path))
        parts = k.import_shapes(path)
        self.assertTrue(all(kind == 'solid' for _, kind in parts))
        return [s for s, _ in parts]

    def test_nurbs_planar_faces_from_step(self):
        from OCP.BRepBuilderAPI import BRepBuilderAPI_NurbsConvert
        src = W().box(20, 30, 60).faces('>Z').workplane().hole(6).faces('<Z').workplane().pushPoints([(5, 8)]).hole(4, 20).val()
        nurbs = cq.Shape.cast(BRepBuilderAPI_NurbsConvert(src.wrapped, True).Shape())
        shape = self.roundtrip([nurbs])[0]
        self.assertTrue(all(f.geomType() == 'BSPLINE' for f in shape.Faces()))
        field = tw.field(Z, shape, 90.0)
        result = to.twist_solid(shape, field)
        report = to.check(result, shape, field)
        self.assertTrue(report['ok'] and report['forward'], report)
        self.assertEqual(k.point_state(result, field.apply((0, 0, 0))), 'out')            # otwór przelotowy
        self.assertEqual(k.point_state(result, field.apply((5, -8, -25))), 'out')         # otwór nieprzelotowy od spodu

    def test_larger_tolerance_from_step(self):
        from OCP.ShapeFix import ShapeFix_ShapeTolerance
        shape = self.roundtrip([W().polygon(6, 30).extrude(50).val()])[0]
        ShapeFix_ShapeTolerance().LimitTolerance(shape.wrapped, 1e-4, 1e-4)
        ShapeFix_ShapeTolerance().SetTolerance(shape.wrapped, 1e-4)
        field = tw.field(Z, shape, 120.0)
        self.assertTrue(to.check(to.twist_solid(shape, field), shape, field)['ok'])

    def test_result_is_forward_and_editable(self):
        for shape in (k.box(20, 30, 80), W().polygon(6, 30).extrude(50).faces('>Z').workplane().hole(8).val()):
            result = to.twist_solid(shape, tw.field(Z, shape, 90.0))
            self.assertEqual(result.wrapped.Orientation().name, 'TopAbs_FORWARD')
            faces = result.Faces()
            for i, e in enumerate(result.Edges()):                                         # każda krawędź da się zaokrąglić
                if sum(1 for f in faces if any(e.isSame(x) for x in f.Edges())) < 2:
                    continue                                                               # szew powierzchni otworu - nie krawędź
                rounded = k.blend(result, {i}, .5, 'fillet')
                self.assertTrue(k.is_valid(rounded) and 0 < rounded.Volume() < result.Volume(), i)
            tool = k.box(10, 10, 200).translate(cq.Vector(0, 0, -50))
            for op in ('subtract', 'union', 'intersect'):
                out = k.boolean(op, result, [tool])
                self.assertTrue(k.is_valid(out) and out.Volume() > 0, op)


class AdvancedTwistTests(unittest.TestCase):
    """Etap 9: fragment bryły, zakotwiczenie, rozkłady, dowolna oś; gładkie przejście na granicach zakresu."""

    @staticmethod
    def boundary_creases(shape, levels):
        """Największy kąt (°) między normalnymi sąsiednich ścian bocznych na krawędziach leżących na poziomach levels."""
        faces = shape.Faces()
        worst = {}
        for e in shape.Edges():
            box = e.BoundingBox()
            level = next((z for z in levels if box.zlen < 1e-3 and abs(box.zmin - z) < 1e-3), None)
            if level is None:
                continue
            pair = [f for f in faces if any(e.isSame(x) for x in f.Edges())]
            if len(pair) != 2:
                continue
            for q in (.05, .3, .7, .95):
                p = e.positionAt(q)
                n1, n2 = (np.asarray(f.normalAt(p).toTuple()) for f in pair)
                angle = math.degrees(math.acos(min(1.0, abs(float(n1 @ n2)))))
                worst[level] = max(worst.get(level, 0.0), angle)
        return worst

    def test_smooth_distribution_has_no_crease_at_range_limits(self):
        box = k.box(20, 30, 80)
        for angle in (120.0, -200.0):
            field = tw.field(Z, box, angle, .2, .8, 'smoothstep')
            result = to.twist_solid(box, field)
            self.assertTrue(to.check(result, box, field)['ok'])
            creases = self.boundary_creases(result, (16.0, 64.0))
            self.assertEqual(set(creases), {16.0, 64.0})
            self.assertLess(max(creases.values()), .01, creases)                 # styczne przejście (praktycznie 0°)
        linear = to.twist_solid(box, tw.field(Z, box, 120.0, .2, .8, 'linear'))
        self.assertGreater(min(self.boundary_creases(linear, (16.0, 64.0)).values()), 5.0)   # liniowy: załamanie z natury rozkładu
        prog = self.boundary_creases(to.twist_solid(box, tw.field(Z, box, 120.0, .2, .8, 'progressive')), (16.0, 64.0))
        self.assertLess(prog[16.0], .01)                                         # progresywny: gładko na początku zakresu
        self.assertGreater(prog[64.0], 5.0)

    def test_fragment_anchor_and_any_axis(self):
        box = k.box(20, 30, 80)
        tilted = k.transform(box, (0, 0, 0), (0, 25, 40))                      # bryła obrócona - oś wzdłuż niej, dowolna w 3D
        center, axes = tw.principal_axes(tilted)
        spec = dict(kind='points', p=[float(c) for c in center], d=[float(c) for c in axes['Z']], reverse=False)
        for anchor in ('start', 'center', 'end'):
            for kind in ('linear', 'smoothstep', 'progressive'):
                field = tw.field(dict(spec, reverse=anchor == 'end'), tilted, 75.0, .15, .7, kind, 2.0, anchor)
                result = to.twist_solid(tilted, field)
                self.assertTrue(to.check(result, tilted, field)['ok'], (anchor, kind))
        field = tw.field(Z, box, 90.0, .25, .75, 'smoothstep', 2.0, 'end')
        result = to.twist_solid(box, field)
        self.assertTrue(has_point(result, (20, 30, 80)))                         # zakotwiczony koniec w miejscu
        self.assertTrue(has_point(result, (25, 5, 0)) or has_point(result, (-5, 25, 0)))   # początek obrócony o pełny kąt

if __name__ == '__main__':
    unittest.main()
