"""Conformal sketch material across cylindrical, sharp and rounded corners."""
import math
import tempfile
import unittest
from pathlib import Path

import cadquery as cq
import numpy as np
from rccad import history, kernel
from rccad.document import Body, Document


class SurfaceSketchTests(unittest.TestCase):
    def cases(self):
        n = 1 / math.sqrt(2)
        yield 'cylinder', cq.Workplane().cylinder(20, 10).val(), (10, 0, 0), (1, 0, 0), 3
        yield 'sharp convex', cq.Workplane().box(30, 30, 20).val(), (15, 15, 0), (n, n, 0), 3
        yield 'rounded convex', cq.Workplane().box(30, 30, 20).edges('|Z').fillet(4).val(), (11 + 4*n, 11 + 4*n, 0), (n, n, 0), 3
        yield 'sharp concave', cq.Workplane().box(40, 40, 20).faces('>Z').workplane().rect(20, 20).cutBlind(-15).val(), (10, 10, 2), (-n, -n, 0), 3
        shape = cq.Workplane().box(40, 40, 20).faces('>Z').workplane().rect(20, 20).cutBlind(-15).edges('|Z').fillet(3).val()
        corner = next(f for f in shape.Faces() if f.geomType() == 'CYLINDER' and 5 < f.Center().x < 12 and 5 < f.Center().y < 12)
        point = corner.positionAt(.5, .5)
        origin = (point.x, point.y, 2.5)
        yield 'rounded concave', shape, origin, corner.normalAt(cq.Vector(*origin)).toTuple(), 2

    def test_join_cut_and_replay_all_surface_types(self):
        for name, shape, origin, normal, radius in self.cases():
            with self.subTest(name=name):
                plane = kernel.face_frame(origin, normal)
                wire = cq.Workplane(cq.Plane(origin=origin, normal=normal)).circle(radius).val()
                solid = Body('target', shape, 'solid')
                surface = {'target': solid.id, 'normal': list(normal)}
                sketch = Body('circle', wire, 'sketch', plane, meta={'surface': surface})
                for operation in ('join', 'cut'):
                    recipe = {'profiles': [{'k': 'surface', 'id': sketch.id}], 'mode': operation, 'd1': .5, 'dir': 'one'}
                    result = history.run_extrude([solid, sketch], recipe)
                    changed = next(b.shape for b in result if b.kind == 'solid')
                    self.assertEqual(len(changed.Solids()), 1)
                    self.assertTrue(changed.isValid())
                    delta = changed.Volume() - shape.Volume()
                    self.assertGreater(delta if operation == 'join' else -delta, 1)

    def test_letter_hole_remains_open_on_cylinder(self):
        shape = cq.Workplane().cylinder(20, 10).val()
        solid = Body('cylinder', shape, 'solid')
        normal = (1, 0, 0)
        plane = kernel.face_frame((10, 0, 0), normal)
        wires = kernel.text_shape(plane, 'O', 0, 0, size=5, font='Arial', bold=False, italic=False, angle=0)
        group = history.new_text_group()
        identifiers = history.text_ids(group, len(wires))
        letters = [Body('O', w, 'sketch', plane, id=identifiers[i], meta={'surface': {'target': solid.id, 'normal': list(normal)}})
                   for i, w in enumerate(wires)]
        sources = history.resolve_profiles([solid, *letters], {'k': 'surfacetext', 'group': group})
        self.assertEqual(len(sources), 1)
        self.assertTrue(sources[0]['face'].innerWires())
        result = history.run_extrude([solid, *letters], {'profiles': [{'k': 'surfacetext', 'group': group}], 'mode': 'join', 'd1': .5})
        self.assertTrue(next(b.shape for b in result if b.kind == 'solid').isValid())

    def test_text_recipe_keeps_surface_binding(self):
        shape = cq.Workplane().cylinder(20, 10).val()
        solid = Body('cylinder', shape, 'solid')
        plane = kernel.face_frame((10, 0, 0), (1, 0, 0))
        group = history.new_text_group()
        recipe = {'plane': history.plane_to_json(plane), 'name': 'Text', 'out': history.text_ids(group, 2),
                  'surface': {'target': solid.id, 'normal': [1, 0, 0]},
                  'params': {'text': 'O', 'anchor': [0, 0], 'size': 5, 'font': 'Arial', 'bold': False,
                             'italic': False, 'angle': 0}}
        bodies = history.run_text([solid], recipe)
        self.assertEqual(len(bodies), 3)
        self.assertTrue(all(b.meta['surface']['target'] == solid.id for b in bodies[1:]))
        sources = history.resolve_profiles(bodies, {'k': 'surfacetext', 'group': group})
        self.assertEqual(len(sources), 1)
        self.assertTrue(sources[0]['face'].innerWires())

    def test_cylinder_projection_preserves_unfolded_width(self):
        shape = cq.Workplane().cylinder(20, 10).val()
        wire = cq.Workplane(cq.Plane(origin=(10, 0, 0), normal=(1, 0, 0))).circle(7).val()
        flat = kernel.display_mesh(wire)
        curved = kernel.project_surface_mesh(flat, shape, (1, 0, 0))
        original = next(iter(flat.edges.values()))
        mapped = next(iter(curved.edges.values()))
        self.assertTrue(np.allclose(np.hypot(mapped[:, 0], mapped[:, 1]), 10, atol=2e-4))
        self.assertTrue(np.allclose(10*np.arctan2(mapped[:, 1], mapped[:, 0]), original[:, 1], atol=.015))
        face = cq.Face.makeFromWires(wire)
        for operation in ('join', 'cut'):
            tool = kernel.surface_stamp_tool(shape, face, (1, 0, 0), .5, operation)
            self.assertTrue(tool.isValid())
            self.assertEqual(len(tool.Solids()), 1)

    def test_too_wide_surface_sketch_fails_instead_of_floating(self):
        shape = cq.Workplane().cylinder(20, 10).val()
        wire = cq.Workplane(cq.Plane(origin=(10, 0, 0), normal=(1, 0, 0))).circle(15).val()
        with self.assertRaises(kernel.CadError):
            kernel.project_surface_mesh(kernel.display_mesh(wire), shape, (1, 0, 0))

    def test_corner_projection_keeps_profile_radius(self):
        for name, shape, origin, normal, radius in self.cases():
            if name == 'cylinder':
                continue
            with self.subTest(name=name):
                wire = cq.Workplane(cq.Plane(origin=origin, normal=normal)).circle(radius).val()
                projected = kernel.project_surface_mesh(kernel.display_mesh(wire), shape, normal)
                points = np.concatenate(list(projected.edges.values()))
                # The farthest projected outline point remains close to the
                # requested radius; the old orthographic corner grew by √2.
                self.assertLess(float(np.max(np.linalg.norm(points-np.asarray(origin),axis=1))), radius+.15)

    def test_rectangular_profile_adds_and_cuts_across_corners(self):
        for name, shape, origin, normal, _ in self.cases():
            if name == 'cylinder':
                continue
            with self.subTest(name=name):
                wire = cq.Workplane(cq.Plane(origin=origin, normal=normal)).rect(4, 2).val()
                face = cq.Face.makeFromWires(wire)
                kernel.project_surface_mesh(kernel.display_mesh(wire), shape, normal)
                for operation in ('join', 'cut'):
                    tool = kernel.surface_stamp_tool(shape, face, normal, .5, operation)
                    result = kernel.boolean('union' if operation == 'join' else 'subtract', shape, [tool])
                    self.assertEqual(len(result.Solids()), 1)
                    self.assertTrue(result.isValid())

    def test_saved_sketch_reprojects_on_load(self):
        shape = cq.Workplane().cylinder(20, 10).val()
        solid = Body('cylinder', shape, 'solid').prepared()
        origin, normal = (10, 0, 0), (1, 0, 0)
        plane = kernel.face_frame(origin, normal)
        wire = cq.Workplane(cq.Plane(origin=origin, normal=normal)).circle(3).val()
        sketch = Body('circle', wire, 'sketch', plane, meta={'surface': {'target': solid.id, 'normal': list(normal)}}).prepared()
        sketch = Body(sketch.name, sketch.shape, sketch.kind, sketch.plane, id=sketch.id,
                      meta=sketch.meta, mesh=kernel.project_surface_mesh(sketch.mesh, shape, normal))
        document = Document()
        document.commit([solid, sketch])
        moved = sketch.changed(wire.translate(cq.Vector(0, 1, 0)))
        document.commit([solid, moved])
        self.assertEqual(document.bodies[1].meta['surface']['target'], solid.id)
        self.assertGreater(max(abs(float(points[:, 0].min()) - 10) for points in document.bodies[1].mesh.edges.values()), .1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'surface.rccadx'
            document.save(path)
            reopened = Document.load(path)
        restored = next(b for b in reopened.bodies if b.kind == 'sketch')
        self.assertEqual(restored.meta['surface']['target'], solid.id)
        self.assertGreater(max(abs(float(points[:, 0].min()) - 10) for points in restored.mesh.edges.values()), .1)


if __name__ == '__main__':
    unittest.main()
