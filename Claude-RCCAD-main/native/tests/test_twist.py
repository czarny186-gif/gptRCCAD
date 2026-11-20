"""TWIST – geometria osi skręcenia (rccad/twist.py)."""
import math
import unittest

import cadquery as cq
import numpy as np

from rccad import kernel as k
from rccad import twist as tw


class TwistAxisTests(unittest.TestCase):
    def test_global_axis_through_box_center_and_reverse(self):
        box = k.box(10, 20, 40)
        o, d = tw.resolve(dict(kind='global', axis='Y'), box)
        np.testing.assert_allclose(o, (5, 10, 20))
        np.testing.assert_allclose(d, (0, 1, 0))
        o, d = tw.resolve(dict(kind='global', axis='Y', reverse=True), box)
        np.testing.assert_allclose(d, (0, -1, 0))

    def test_local_axes_follow_rotated_body(self):
        box = k.transform(k.box(10, 20, 40), (0, 0, 0), (0, 0, 30))
        center, axes = tw.principal_axes(box)
        np.testing.assert_allclose(axes['Z'], (0, 0, 1), atol=1e-9)
        np.testing.assert_allclose(axes['X'], (math.cos(math.radians(30)), math.sin(math.radians(30)), 0), atol=1e-9)
        np.testing.assert_allclose(axes['Y'], (-math.sin(math.radians(30)), math.cos(math.radians(30)), 0), atol=1e-9)
        cube_center, cube = tw.principal_axes(k.box(10, 10, 10))           # osie nieokreślone - globalne
        np.testing.assert_allclose(cube['X'], (1, 0, 0))
        np.testing.assert_allclose(cube_center, (5, 5, 5), atol=1e-9)

    def test_local_axes_of_cylinder_keep_symmetry_axis(self):
        cyl = cq.Solid.makeCylinder(5, 30, cq.Vector(0, 0, 0), cq.Vector(1, 0, 0))
        center, axes = tw.principal_axes(cyl)
        np.testing.assert_allclose(center, (15, 0, 0), atol=1e-9)
        np.testing.assert_allclose(axes['X'], (1, 0, 0), atol=1e-9)
        for n in 'XYZ':
            self.assertAlmostEqual(float(np.linalg.norm(axes[n])), 1, 12)
        self.assertAlmostEqual(float(np.dot(axes['Y'], axes['Z'])), 0, 12)

    def test_edge_cylinder_and_points(self):
        shape = cq.Workplane().box(20, 20, 60).faces('>Z').workplane().hole(8).val()
        line = next(e for e in shape.Edges() if e.geomType() == 'LINE')
        p, d = tw.edge_axis(line)
        self.assertAlmostEqual(float(np.linalg.norm(d)), 1, 12)
        with self.assertRaises(k.CadError):
            tw.edge_axis(next(e for e in shape.Edges() if e.geomType() == 'CIRCLE'))
        p, d = tw.cylinder_axis(next(f for f in shape.Faces() if f.geomType() == 'CYLINDER'))
        np.testing.assert_allclose(p[:2], (0, 0), atol=1e-9)
        self.assertAlmostEqual(abs(d[2]), 1, 12)
        with self.assertRaises(k.CadError):
            tw.cylinder_axis(next(f for f in shape.Faces() if f.geomType() == 'PLANE'))
        p, d = tw.points_axis((1, 1, 1), (1, 1, 5))
        np.testing.assert_allclose(d, (0, 0, 1))
        with self.assertRaises(k.CadError):
            tw.points_axis((1, 1, 1), (1, 1, 1))
        with self.assertRaises(k.CadError):
            tw.resolve(dict(kind='edge'), shape)                          # oś jeszcze nie wskazana

    def test_extent_and_ring_basis(self):
        t0, t1, r = tw.extent([(0, 0, 0), (10, 0, 5), (0, 10, 20)], np.zeros(3), np.array([0, 0, 1.0]))
        self.assertEqual((t0, t1, r), (0, 20, 10))
        for axis in ((0, 0, 1.0), (1.0, 0, 0), (0, .6, .8)):
            e1, e2 = tw.ring_basis(np.array(axis))
            np.testing.assert_allclose(np.cross(e1, e2), axis, atol=1e-12)    # prawoskrętnie: kąt dodatni wokół osi


if __name__ == '__main__':
    unittest.main()
