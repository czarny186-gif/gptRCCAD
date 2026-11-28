import os
import unittest
from dataclasses import replace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen' if not os.environ.get('DISPLAY') and os.name != 'nt' else '')

from PySide6.QtWidgets import QApplication
from rccad import kernel
from rccad.document import Body
from rccad.lod import build_mesh, select_level
from rccad.viewport import CadView


class DetailTests(unittest.TestCase):
    def test_profiles_and_hysteresis_use_frame_budget(self):
        self.assertEqual(select_level('quality', True, 40., 60, 500, 2), 0)
        self.assertEqual(select_level('auto', False, 40., 60, 500, 4), 2)
        self.assertEqual(select_level('auto', True, 15., 60, 500, 4), 4)
        self.assertEqual(select_level('auto', True, 15., 30, 500, 4), 2)
        self.assertEqual(select_level('balanced', True, 9., 60, 500, 2), 3)

    def test_detail_tessellations_keep_the_shape_and_vary_triangle_count(self):
        body = Body('Cylinder', kernel.cylinder(15, 40)).prepared()
        fine = build_mesh(body.shape, 0)
        coarse = build_mesh(body.shape, 4)
        self.assertLess(len(coarse.triangles), len(fine.triangles))
        self.assertAlmostEqual(body.shape.Volume(), 3.141592653589793 * 15**2 * 40)
        self.assertEqual(fine.edges, {})

    def test_graphics_variant_keeps_picking_mesh_and_excludes_sections_and_new_shapes(self):
        app = QApplication.instance() or QApplication([])
        view = CadView()
        try:
            body = Body('Cylinder', kernel.cylinder(15, 40)).prepared()
            view.set_models([body])
            original_pick = view._scene_index()
            line = view._parts[body.id]['lines'][0]
            coarse = build_mesh(body.shape, 4)
            view.set_detail_meshes({body.id: (body.shape, coarse)})
            self.assertIs(view.bodies[0].mesh, body.mesh)
            self.assertIs(view._scene_index(), original_pick)
            self.assertIs(view._parts[body.id]['lines'][0], line)
            self.assertIs(view._render_mesh(body), coarse)
            view.set_section_plane([0, 0, 1, -10])
            self.assertIs(view._render_mesh(body), body.mesh)
            view.set_section_plane(None)
            changed = replace(body.changed(kernel.box(10, 10, 10)), id=body.id)
            view.set_models([changed])
            self.assertIs(view._render_mesh(changed), changed.mesh)
        finally:
            view.close()
            view.deleteLater()
            app.processEvents()
