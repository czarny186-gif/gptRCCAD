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


if __name__ == '__main__':
    unittest.main()
