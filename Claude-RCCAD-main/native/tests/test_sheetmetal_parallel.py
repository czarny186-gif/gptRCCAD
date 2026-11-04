"""Butt seams continue through intermediate panels and their rounded bends."""
import unittest
from test_sheetmetal_boxes import box_recipe
from rccad import sheetmetal as s


class ParallelCornerTests(unittest.TestCase):
    def test_intermediate_panels_and_bends_have_no_diagonal_seam_faces(self):
        for turn in ('in', 'out'):
            with self.subTest(turn=turn):
                recipe = box_recipe(turn, 'out', 'parallel', gap=.5)
                frames, corners = s._effective(recipe['flanges'], 2, True)
                parts = s._corner_parts(recipe, frames, corners)
                for pieces in parts.values():
                    for piece in pieces:
                        for face in piece.Faces():
                            if face.geomType() == 'PLANE':
                                n = face.normalAt()
                                self.assertFalse(abs(n.x) > 1e-5 and abs(n.y) > 1e-5)
                shape = s.build_sheet(recipe)
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Solids()), 1)
