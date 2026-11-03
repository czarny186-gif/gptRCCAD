"""Inclined box corners: actual material, seam clearance and serial bends."""
import unittest
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from test_sheetmetal_sheet_joint import folded_fixture
from rccad import kernel, sheetmetal as s


def box(angles):
    recipe = folded_fixture(False)
    recipe['flanges'] = recipe['flanges'][:4]
    for spec, angle in zip(recipe['flanges'], angles):
        spec['angle'] = angle
    return recipe


class InclinedCornerTests(unittest.TestCase):
    def test_four_inclined_walls_keep_thickness_and_corner_clearance(self):
        for angle in (15, 30, 45, 60, 75, 105, 120, 135, 150, 165):
            with self.subTest(angle=angle):
                recipe = box([angle]*4)
                eff, corners = s._effective(recipe['flanges'], 1, True)
                parts = s._corner_parts(recipe, eff, corners)
                shape = s.build_sheet(recipe)
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Solids()), 1)
                radii = [BRepAdaptor_Surface(f.wrapped).Cylinder().Radius()
                         for f in shape.Faces() if f.geomType() == 'CYLINDER']
                self.assertEqual(len(radii), 8)
                self.assertEqual({round(r, 6) for r in radii}, {.5, 1.5})
                # Both bends and panels stay on their own side of the seam.
                # This checks the configured physical gap, not just validity.
                for point, a, b, normal in corners:
                    for owner, sign in ((a, 1), (b, -1)):
                        values = [sign*float((np.array(v.toTuple())-point)@normal)
                                  for piece in parts[owner] for v in piece.Vertices()]
                        self.assertAlmostEqual(min(values), .25, delta=1e-5)
                # Centre of each tangent leg keeps the requested material.
                for frame in eff:
                    inside, inside_end, _, direction = s._tip_geom(frame, 'in', 1)
                    outside, _, _, _ = s._tip_geom(frame, 'out', 1)
                    centre = (inside+outside)/2 - frame['length']/2*direction
                    centre += (inside_end-inside)/2
                    self.assertEqual(kernel.point_state(shape, centre), 'in')

    def test_mixed_angles_and_outward_second_bends(self):
        for angles in ([45, 90, 135, 120], [135]*4, [15, 60, 105, 165]):
            with self.subTest(angles=angles):
                recipe = box(angles)
                recipe['flanges'] += [dict(kind='tip', parent=i, side='out',
                                          r=.5, angle=45, length=5) for i in range(4)]
                # Build every UI prefix, not only the finished symmetric box.
                for count in range(1, 9):
                    partial = dict(recipe, flanges=recipe['flanges'][:count])
                    shape = s.build_sheet(partial)
                    self.assertTrue(shape.isValid())
                    self.assertEqual(len(shape.Solids()), 1)

    def test_inclined_returns_still_reject_real_material_collisions(self):
        recipe = box([135]*4)
        recipe['flanges'] += [dict(kind='tip', parent=i, side='in',
                                  r=.5, angle=135, length=10) for i in range(4)]
        with self.assertRaisesRegex(kernel.CadError, 'nachodzą'):
            s.build_sheet(recipe)
