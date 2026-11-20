"""TWIST – testy matematycznego silnika deformacji (rccad/twist_math.py) i połączenia z osią bryły (rccad/twist.py)."""
import math
import unittest

import numpy as np

from rccad import twist_math as tm


def z_field(angle, start=0.0, end=10.0, kind='linear', power=2.0, origin=(0, 0, 0)):
    return tm.make_field(origin, (0, 0, 1), angle, start, end, kind, power)


def rodrigues(p, o, d, theta):
    p, o, d = (np.asarray(x, float) for x in (p, o, d))
    v = p - o
    return o + v * math.cos(theta) + np.cross(d, v) * math.sin(theta) + d * float(d @ v) * (1 - math.cos(theta))


class TwistMathTests(unittest.TestCase):
    def test_z_axis_matches_the_formula(self):
        f = z_field(90.0)
        rng = np.random.default_rng(1)
        pts = rng.uniform(-20, 20, (200, 3))
        pts[:, 2] = rng.uniform(-5, 15, 200)
        out = f.apply(pts)
        theta = np.radians(90.0) * np.clip(pts[:, 2] / 10.0, 0, 1)
        x, y = pts[:, 0], pts[:, 1]
        np.testing.assert_allclose(out[:, 0], x * np.cos(theta) - y * np.sin(theta), atol=1e-12)
        np.testing.assert_allclose(out[:, 1], x * np.sin(theta) + y * np.cos(theta), atol=1e-12)
        np.testing.assert_array_equal(out[:, 2], pts[:, 2])            # z' = z
        np.testing.assert_allclose(f.apply((1, 0, 10)), (0, 1, 10), atol=1e-12)
        np.testing.assert_allclose(f.apply((1, 0, 5)), (math.cos(math.pi / 4), math.sin(math.pi / 4), 5), atol=1e-12)

    def test_zero_angle_is_identity(self):
        pts = np.random.default_rng(2).uniform(-50, 50, (100, 3))
        for kind in tm.DISTRIBUTIONS:
            np.testing.assert_array_equal(z_field(0.0, kind=kind).apply(pts), pts)

    def test_positive_negative_and_inverse(self):
        p = np.array([3.0, 1.0, 7.0])
        plus, minus = z_field(40.0).apply(p), z_field(-40.0).apply(p)
        np.testing.assert_allclose(plus, rodrigues(p, (0, 0, 0), (0, 0, 1), math.radians(28)), atol=1e-12)   # z = 7: 40° · 0,7
        np.testing.assert_allclose(minus, rodrigues(p, (0, 0, 0), (0, 0, 1), math.radians(-28)), atol=1e-12)
        f = z_field(123.0, kind='smoothstep')
        pts = np.random.default_rng(3).uniform(-10, 10, (50, 3))
        np.testing.assert_allclose(f.inverse().apply(f.apply(pts)), pts, atol=1e-11)

    def test_angles_above_360(self):
        f = z_field(720.0)
        np.testing.assert_allclose(f.apply((2, 0, 10)), (2, 0, 10), atol=1e-11)        # dwa pełne obroty
        np.testing.assert_allclose(f.apply((2, 0, 2.5)), (-2, 0, 2.5), atol=1e-11)     # 180° po 1/4 długości
        np.testing.assert_allclose(z_field(450.0).apply((2, 0, 10)), (0, 2, 10), atol=1e-11)
        self.assertAlmostEqual(float(z_field(1080.0).theta(10.0)), 6 * math.pi)

    def test_reversed_axis(self):
        p = np.array([4.0, 0.0, 10.0])
        up = tm.make_field((0, 0, 0), (0, 0, 1), 90.0, 0, 10)
        down = tm.make_field((0, 0, 0), (0, 0, -1), 90.0, -10, 0)        # ta sama bryła 0..10, oś odwrócona
        np.testing.assert_allclose(up.apply(p), (0, 4, 10), atol=1e-12)   # przy z = 10 pełny kąt, w lewo
        np.testing.assert_allclose(down.apply(p), (4, 0, 10), atol=1e-12)  # teraz z = 10 to początek zakresu - bez obrotu
        np.testing.assert_allclose(down.apply((4, 0, 0)), (0, -4, 0), atol=1e-12)  # pełny kąt na drugim końcu, w prawo
        # odwrócona oś i przeciwny kąt dają ten sam obrót w danym punkcie zakresu
        np.testing.assert_allclose(tm.make_field((0, 0, 0), (0, 0, -1), -90.0, -10, 0).apply((4, 0, 0)), (0, 4, 0), atol=1e-12)

    def test_partial_range_constant_outside_and_continuous(self):
        f = z_field(90.0, start=20.0, end=40.0)
        p = np.array([5.0, 0.0, 0.0])
        for z in (-10.0, 0.0, 19.999999):
            np.testing.assert_allclose(f.apply(p + (0, 0, z)), p + (0, 0, z), atol=1e-6)   # przed zakresem: bez obrotu
        for z in (40.0, 55.0, 1e3):
            np.testing.assert_allclose(f.apply(p + (0, 0, z)), (0, 5, z), atol=1e-12)      # za zakresem: pełny kąt, stały
        for kind in tm.DISTRIBUTIONS:
            g = z_field(270.0, 20.0, 40.0, kind)
            for edge in (20.0, 40.0):                                       # ciągłość na granicach
                a, b = g.apply(p + (0, 0, edge - 1e-7)), g.apply(p + (0, 0, edge + 1e-7))
                self.assertLess(float(np.linalg.norm(a - b)), 1e-5, kind)

    def test_distributions(self):
        u = np.linspace(0, 1, 101)
        for kind in tm.DISTRIBUTIONS:
            f = tm.distribution(u, kind)
            self.assertEqual((f[0], f[-1]), (0.0, 1.0))
            self.assertTrue(np.all(np.diff(f) >= 0), kind)                  # rośnie monotonicznie
        np.testing.assert_allclose(tm.distribution(u, 'linear'), u)
        np.testing.assert_allclose(tm.distribution(.5, 'smoothstep'), .5)
        self.assertEqual(float(tm.distribution_slope(0.0, 'smoothstep')), 0.0)   # łagodny początek i koniec
        self.assertEqual(float(tm.distribution_slope(1.0, 'smoothstep')), 0.0)
        np.testing.assert_allclose(tm.distribution(.5, 'progressive'), .25)
        np.testing.assert_allclose(tm.distribution(.5, 'progressive', 3.0), .125)
        self.assertLess(float(tm.distribution_slope(0.1, 'progressive')), float(tm.distribution_slope(0.9, 'progressive')))
        f = z_field(90.0, kind='smoothstep')
        self.assertAlmostEqual(float(f.theta(5.0)), math.pi / 4)           # w połowie - połowa kąta
        self.assertAlmostEqual(float(f.theta(2.5)), math.radians(90) * (3 * .0625 - 2 * .015625))

    def test_any_axis_in_3d(self):
        rng = np.random.default_rng(4)
        o = np.array([3.0, -2.0, 5.0])
        d = np.array([1.0, 2.0, -2.0]) / 3.0
        f = tm.make_field(o, d * 7, 150.0, -4.0, 9.0, 'smoothstep')        # kierunek normalizowany
        np.testing.assert_allclose(f.direction, d)
        pts = rng.uniform(-10, 10, (300, 3))
        original = pts.copy()
        out = f.apply(pts)
        t = (pts - o) @ d
        theta = np.radians(150.0) * tm.distribution((t - (-4.0)) / 13.0, 'smoothstep')
        expected = np.array([rodrigues(p, o, d, th) for p, th in zip(pts, theta)])
        np.testing.assert_allclose(out, expected, atol=1e-10)
        np.testing.assert_allclose((out - o) @ d, t, atol=1e-10)            # współrzędna wzdłuż osi bez zmian
        r0 = np.linalg.norm((pts - o) - np.outer(t, d), axis=1)
        r1 = np.linalg.norm((out - o) - np.outer(t, d), axis=1)
        np.testing.assert_allclose(r1, r0, atol=1e-10)                      # odległość od osi bez zmian
        np.testing.assert_array_equal(pts, original)                       # wejście nie zmienione

    def test_full_length_and_fractional_range(self):
        whole = tm.field_for_extent((0, 0, 0), (0, 0, 1), 90.0, 5.0, 25.0)
        self.assertEqual((whole.start, whole.end), (5.0, 25.0))
        part = tm.field_for_extent((0, 0, 0), (0, 0, 1), 90.0, 5.0, 25.0, .25, .75)
        self.assertEqual((part.start, part.end), (10.0, 20.0))
        for bad in ((.5, .5), (.6, .4), (-.1, .5), (.2, 1.1)):
            with self.assertRaises(tm.TwistParamError):
                tm.field_for_extent((0, 0, 0), (0, 0, 1), 90.0, 5.0, 25.0, *bad)
        with self.assertRaises(tm.TwistParamError):
            tm.field_for_extent((0, 0, 0), (0, 0, 1), 90.0, 5.0, 5.0)        # bryła płaska wzdłuż osi

    def test_validation(self):
        good = dict(origin=(0, 0, 0), direction=(0, 0, 1), angle=90.0, start=0.0, end=10.0)
        for change in (dict(direction=(0, 0, 0)), dict(angle=float('nan')), dict(angle=float('inf')), dict(angle=1e6),
                       dict(start=10.0, end=10.0), dict(start=10.0, end=0.0), dict(origin=(0, 0)), dict(direction='z'),
                       dict(origin=(0, float('nan'), 0))):
            with self.assertRaises(tm.TwistParamError, msg=str(change)):
                tm.make_field(**dict(good, **change))
        with self.assertRaises(tm.TwistParamError):
            tm.make_field(**good, kind='spiral')
        with self.assertRaises(tm.TwistParamError):
            tm.make_field(**good, kind='progressive', power=1.0)
        self.assertIsInstance(tm.make_field(**good, kind='progressive', power=3.0), tm.TwistField)
        self.assertTrue(issubclass(tm.TwistParamError, ValueError))

    def test_engine_has_no_cad_or_ui_imports(self):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(tm))
        names = {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {(n.module or '').split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse(names & {'OCP', 'cadquery', 'PySide6'}, names)


class TwistFieldForBodyTests(unittest.TestCase):
    def test_field_from_body_axis_and_extent(self):
        from rccad import kernel as k
        from rccad import twist as tw
        box = k.box(10, 20, 40)
        f = tw.field(dict(kind='global', axis='Z'), box, 90.0)
        np.testing.assert_allclose(f.origin, (5, 10, 20))
        self.assertAlmostEqual(f.start, -20.0, 6)
        self.assertAlmostEqual(f.end, 20.0, 6)
        np.testing.assert_allclose(f.apply((10, 10, 40)), (5, 15, 40), atol=1e-9)   # górny róg obrócony o 90° wokół środka
        np.testing.assert_allclose(f.apply((10, 10, 0)), (10, 10, 0), atol=1e-9)    # dolny bez zmian
        r = tw.field(dict(kind='global', axis='Z', reverse=True), box, 90.0)        # odwrócona oś: pełny kąt na dole
        np.testing.assert_allclose(r.apply((10, 10, 40)), (10, 10, 40), atol=1e-9)
        np.testing.assert_allclose(r.apply((10, 10, 0)), (5, 5, 0), atol=1e-9)
        half = tw.field(dict(kind='global', axis='Z'), box, 90.0, .5, 1.0, 'smoothstep')
        self.assertAlmostEqual(half.start, 0.0, 6)
        with self.assertRaises(k.CadError):
            tw.field(dict(kind='global', axis='Z'), box, 90.0, .7, .3)
        before = [v.toTuple() for v in box.Vertices()]
        tw.field(dict(kind='global', axis='X'), box, 45.0).apply(np.array(before))
        self.assertEqual([v.toTuple() for v in box.Vertices()], before)            # bryła nie zmieniona


if __name__ == '__main__':
    unittest.main()
