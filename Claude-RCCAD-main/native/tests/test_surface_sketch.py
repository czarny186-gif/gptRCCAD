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
        samples=[original[0]]
        for a,b in zip(original[:-1],original[1:]):
            count=max(1,int(np.ceil(float(np.linalg.norm(b-a))/.2)))
            samples.extend(a+(b-a)*j/count for j in range(1,count+1))
        self.assertTrue(np.allclose(np.hypot(mapped[:, 0], mapped[:, 1]), 10, atol=2e-4))
        self.assertTrue(np.allclose(10*np.arctan2(mapped[:, 1], mapped[:, 0]), np.asarray(samples)[:, 1], atol=.015))
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

    def test_complex_box_corner_joins_and_cuts_without_whole_solid_offset(self):
        shape = cq.Workplane().box(40, 40, 20).faces('>Z').workplane().rect(20, 20).cutBlind(-15).val()
        for z in (-4, 3):
            wall_x = cq.Workplane().box(2, 6, 5).translate((9, 7, z)).val()
            wall_y = cq.Workplane().box(6, 2, 5).translate((7, 9, z)).val()
            shape = shape.fuse(wall_x, wall_y).clean()
        self.assertGreaterEqual(len(shape.Faces()), 15)
        normal = (-1 / math.sqrt(2), -1 / math.sqrt(2), 0)
        for profile in ('circle', 'rectangle'):
            plane = cq.Workplane(cq.Plane(origin=(8, 8, -4), normal=normal))
            wire = (plane.circle(2) if profile == 'circle' else plane.rect(3, 3)).val()
            for operation in ('join', 'cut'):
                with self.subTest(profile=profile, operation=operation):
                    tool = kernel.surface_stamp_tool(shape, cq.Face.makeFromWires(wire), normal, .5, operation)
                    changed = kernel.boolean('union' if operation == 'join' else 'subtract', shape, [tool])
                    self.assertTrue(changed.isValid())
                    self.assertEqual(len(changed.Solids()), 1)
                    delta = changed.Volume() - shape.Volume()
                    self.assertGreater(delta if operation == 'join' else -delta, 2)

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


def _precise_volume(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, props, 1e-7, True)
    return props.Mass()


def _profile(origin, normal, make):
    frame = kernel.face_frame(origin, normal)
    plane = cq.Plane(origin=tuple(map(float, origin)), xDir=tuple(map(float, frame.xdir)), normal=tuple(map(float, normal)))
    return cq.Face.makeFromWires(make(cq.Workplane(plane)).val())


class ExactWrapTests(unittest.TestCase):
    """Szkic rozwijany dokładnie na pas ścian (walec, otwór, narożniki ostre i zaokrąglone)."""

    def stamp(self, shape, origin, normal, face, height, operation):
        tool = kernel.surface_stamp_tool(shape, face, normal, height, operation, origin=origin)
        result = kernel.boolean('union' if operation == 'join' else 'subtract', shape, [tool])
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids()), 1)
        return _precise_volume(result) - _precise_volume(shape)

    def test_rectangle_on_cylinder_and_hole_is_an_exact_annular_sector(self):
        h, r = .8, 10.0
        cylinder = cq.Workplane().cylinder(30, r).val()
        hole = cq.Workplane().box(40, 40, 30).faces('>Z').workplane().hole(2 * r).val()
        for shape, origin, normal, outer in ((cylinder, (r, 0, 0), (1, 0, 0), True), (hole, (r, 0, 0), (-1, 0, 0), False)):
            face = _profile(origin, normal, lambda wp: wp.rect(8, 5))
            for operation in ('join', 'cut'):
                with self.subTest(outer=outer, operation=operation):
                    grows = (operation == 'join') == outer
                    r2 = r + h if grows else r - h
                    sector = 8 / r / 2 * abs(r2 ** 2 - r ** 2) * 5
                    self.assertAlmostEqual(abs(self.stamp(shape, origin, normal, face, h, operation)), sector, 3)

    def test_sharp_corners_get_a_mitred_wedge_where_pieces_diverge(self):
        n = 1 / math.sqrt(2)
        box = cq.Workplane().box(30, 30, 20).val()
        pocket = cq.Workplane().box(40, 40, 20).faces('>Z').workplane().rect(20, 20).cutBlind(-15).val()
        h, area, wedge = .8, 8 * 5, .8 * .8 * 5
        cases = ((box, (15, 15, 0), (n, n, 0), area * h + wedge, -(area * h - wedge)),          # wypukły: klin przy dodaniu
                 (pocket, (10, 10, 2), (-n, -n, 0), area * h - wedge, -(area * h + wedge)))     # wklęsły: klin przy wycięciu
        for shape, origin, normal, join, cut in cases:
            face = _profile(origin, normal, lambda wp: wp.rect(8, 5))
            self.assertAlmostEqual(self.stamp(shape, origin, normal, face, h, 'join'), join, 3)
            self.assertAlmostEqual(self.stamp(shape, origin, normal, face, h, 'cut'), cut, 3)

    def test_horizontal_edge_is_not_stretched(self):
        n = 1 / math.sqrt(2)
        box = cq.Workplane().box(30, 30, 20).val()
        origin, normal = (15, 0, 10), (n, 0, n)
        face = _profile(origin, normal, lambda wp: wp.rect(8, 5))
        # dawniej rzut prostopadły rozciągał szkic o √2 na krawędzi poziomej
        across = 5 if abs(kernel.face_frame(origin, normal).xdir[1]) > .9 else 8
        along = 13 - across
        self.assertAlmostEqual(self.stamp(box, origin, normal, face, .8, 'join'), 40 * .8 + .64 * along, 3)

    def test_wide_sketch_runs_over_fillet_onto_both_walls(self):
        n = 1 / math.sqrt(2)
        h, r, width, height = .8, 4.0, 24.0, 5.0
        shape = cq.Workplane().box(30, 30, 20).edges('|Z').fillet(r).val()
        origin = (11 + r * n, 11 + r * n, 0)
        face = _profile(origin, (n, n, 0), lambda wp: wp.rect(width, height))
        arc = math.pi / 2 * r
        join = arc * height * h * (1 + h / (2 * r)) + (width - arc) * height * h
        cut = arc * height * h * (1 - h / (2 * r)) + (width - arc) * height * h
        self.assertAlmostEqual(self.stamp(shape, origin, (n, n, 0), face, h, 'join'), join, 2)
        self.assertAlmostEqual(self.stamp(shape, origin, (n, n, 0), face, h, 'cut'), -cut, 2)

    def test_letters_with_holes_on_cylinder_and_corner(self):
        n = 1 / math.sqrt(2)
        from rccad.document import Body as B
        cases = ((cq.Workplane().cylinder(30, 5).val(), (5, 0, 0), (1, 0, 0)),
                 (cq.Workplane().box(30, 30, 20).val(), (15, 15, 0), (n, n, 0)),
                 (cq.Workplane().box(40, 40, 20).faces('>Z').workplane().rect(20, 20).cutBlind(-15).val(), (10, 10, 2), (-n, -n, 0)))
        for shape, origin, normal in cases:
            frame = kernel.face_frame(origin, normal)
            wires = kernel.text_shape(frame, 'ROB', 0, 0, size=5, font='Arial', bold=False, italic=False, angle=0)
            faces = history.material_faces([B('t', w, 'sketch', frame) for w in wires])
            self.assertTrue(any(f.innerWires() for f in faces))
            for operation in ('join', 'cut'):
                with self.subTest(origin=origin, operation=operation):
                    tools = [kernel.surface_stamp_tool(shape, f, normal, .5, operation, origin=origin) for f in faces]
                    self.assertTrue(all(t.isValid() for t in tools))
                    result = kernel.boolean('union' if operation == 'join' else 'subtract', shape, tools)
                    self.assertTrue(result.isValid())
                    delta = result.Volume() - shape.Volume()
                    # wypełnione otwory liter dałyby wyraźnie więcej niż pole liter × wysokość
                    self.assertLess(abs(delta), sum(f.Area() for f in faces) * .5 * 1.25)
                    self.assertGreater(abs(delta), sum(f.Area() for f in faces) * .5 * .7)

    def test_height_above_fillet_radius_reports_the_radius(self):
        shape = cq.Workplane().box(40, 40, 20).faces('>Z').workplane().rect(20, 20).cutBlind(-15).edges('|Z').fillet(3).val()
        corner = next(f for f in shape.Faces() if f.geomType() == 'CYLINDER' and 5 < f.Center().x < 12 and 5 < f.Center().y < 12)
        p = corner.positionAt(.5, .5)
        origin = (p.x, p.y, 2.5)
        normal = corner.normalAt(cq.Vector(*origin)).toTuple()
        face = _profile(origin, normal, lambda wp: wp.circle(1.5))
        with self.assertRaises(kernel.CadError) as raised:
            kernel.surface_stamp_tool(shape, face, normal, 4, 'join', origin=origin)
        self.assertIn('3 mm', str(raised.exception))

    def test_display_mesh_lies_just_above_the_surface(self):
        n = 1 / math.sqrt(2)
        cases = ((cq.Workplane().cylinder(30, 10).val(), (10, 0, 0), (1, 0, 0)),
                 (cq.Workplane().box(40, 40, 30).faces('>Z').workplane().hole(20).val(), (10, 0, 0), (-1, 0, 0)),
                 (cq.Workplane().box(40, 40, 20).faces('>Z').workplane().rect(20, 20).cutBlind(-15).val(), (10, 10, 2), (-n, -n, 0)),
                 (cq.Workplane().box(30, 30, 20).val(), (15, 15, 0), (n, n, 0)))
        for shape, origin, normal in cases:
            with self.subTest(origin=origin):
                face = _profile(origin, normal, lambda wp: wp.circle(3))
                mesh = kernel.project_surface_mesh(kernel.display_mesh(face), shape, normal, origin=origin)
                self.assertGreater(len(mesh.triangles), 0)
                centres = mesh.vertices[mesh.triangles].mean(axis=1)
                for c in centres[::max(1, len(centres) // 25)]:
                    self.assertEqual(kernel.point_state(shape, c), 'out')
                    self.assertLess(shape.distance(cq.Vertex.makeVertex(*map(float, c))), .1)

    def test_many_faced_solid_is_fast(self):
        import time
        shape = (cq.Workplane().box(120, 80, 30).edges('|Z').fillet(6).faces('>Z').workplane().rarray(8, 8, 12, 8).hole(3, 10)
                 .faces('>Z').workplane().rect(60, 40).cutBlind(-12).val())
        self.assertGreater(len(shape.Faces()), 100)
        n = 1 / math.sqrt(2)
        origin, normal = (60 - 6 + 6 * n, 40 - 6 + 6 * n, 0), (n, n, 0)
        face = _profile(origin, normal, lambda wp: wp.rect(10, 5))
        start = time.monotonic()
        for operation in ('join', 'cut'):
            kernel.surface_stamp_tool(shape, face, normal, .8, operation, origin=origin)
        self.assertLess(time.monotonic() - start, 5)

    def test_second_shape_of_the_same_sketch_after_first_extrusion(self):
        # początek szkicu leży już pod pierwszym wyciągniętym kształtem - drugi i tak trafia na pierwotną powierzchnię
        n = 1 / math.sqrt(2)
        for shape, origin, normal, extra in ((cq.Workplane().box(30, 30, 20).val(), (15, 15, 0), (n, n, 0), .8 * .8 * 3),
                                             (cq.Workplane().cylinder(30, 10).val(), (10, 0, 0), (1, 0, 0), None)):
            with self.subTest(origin=origin):
                first = _profile(origin, normal, lambda wp: wp.rect(8, 5))
                second = _profile(origin, normal, lambda wp: wp.center(0, 7).circle(1.5))
                changed = kernel.boolean('union', shape, [kernel.surface_stamp_tool(shape, first, normal, .8, 'join', origin=origin)])
                delta = self.stamp(changed, origin, normal, second, .8, 'join')
                expected = second.Area() * .8 + extra if extra else second.Area() * .8 * (1 + .8 / 20)
                self.assertAlmostEqual(delta, expected, 3)

    def test_origin_picked_on_display_mesh_still_wraps_exactly(self):
        # Początek szkicu wskazany na siatce wyświetlania leży na cięciwie, setne milimetra pod powierzchnią walca
        # (w otworze - w powietrzu). Dawniej szkic przechodził wtedy na przybliżony rzut przez całą bryłę:
        # kształt powstawał także po drugiej stronie walca, a liczenie trwało wiele sekund.
        import time
        h, r, chord = .8, 10.0, .012
        cylinder = cq.Workplane().cylinder(30, r).val()
        hole = cq.Workplane().box(40, 40, 30).faces('>Z').workplane().hole(2 * r).val()
        for shape, normal, outer in ((cylinder, (1, 0, 0), True), (hole, (-1, 0, 0), False)):
            origin = (r - chord, 0, 0)
            face = _profile(origin, normal, lambda wp: wp.rect(8, 5))
            for operation in ('join', 'cut'):
                with self.subTest(outer=outer, operation=operation):
                    start = time.monotonic()
                    tool = kernel.surface_stamp_tool(shape, face, normal, h, operation, origin=origin)
                    self.assertLess(time.monotonic() - start, 2)
                    self.assertEqual(len(tool.Solids()), 1)
                    self.assertGreater(tool.BoundingBox().xmin, 0)          # nic po drugiej stronie osi
                    grows = (operation == 'join') == outer
                    r2 = r + h if grows else r - h
                    sector = 8 / r / 2 * abs(r2 ** 2 - r ** 2) * 5
                    self.assertAlmostEqual(abs(self.stamp(shape, origin, normal, face, h, operation)), sector, 3)

    def test_projection_fallback_stays_on_the_near_side(self):
        # przybliżony rzut (bez początku płaszczyzny szkicu) też nie dokłada kształtu po drugiej stronie walca
        r = 10.0
        cylinder = cq.Workplane().cylinder(30, r).val()
        face = _profile((r, 0, 0), (1, 0, 0), lambda wp: wp.rect(6, 4))
        for operation in ('join', 'cut'):
            with self.subTest(operation=operation):
                tool = kernel.surface_stamp_tool(cylinder, face, (1, 0, 0), .8, operation)
                self.assertTrue(tool.Solids())
                self.assertGreater(tool.BoundingBox().xmin, 0)

    def test_concave_fillet_is_not_mistaken_for_a_convex_cylinder(self):
        # Wklęsłe zaokrąglenie (wewnętrzny narożnik / wyoblenie): materiał leży na zewnątrz promienia. Dawniej punkt próbny
        # ściany liczony z ułamków 0..1 zamiast z zakresu parametrów ściany trafiał poza nią, gdy kąt ściany nie obejmował
        # 0..1 rad (tu: pi..1,5 pi), a wtedy walec uznawano za wypukły: wycięcie szło w powietrze, a dodanie w głąb bryły.
        from OCP.BRepTools import BRepTools
        h = .6
        for corner in ((20, 20), (-20, 20), (-20, -20), (20, -20)):
            with self.subTest(corner=corner):
                block = cq.Workplane().box(40, 40, 20).val()
                cove = cq.Solid.makeCylinder(6, 40, cq.Vector(corner[0], corner[1], -20))
                block = kernel.boolean('subtract', block, [cove])
                face_c = next(f for f in block.Faces() if f.geomType() == 'CYLINDER')
                u0, u1, v0, v1 = BRepTools.UVBounds_s(face_c.wrapped)
                origin = np.array(face_c.positionAt((u0 + u1) / 2, (v0 + v1) / 2).toTuple())
                normal = np.array(face_c.normalAt(cq.Vector(*origin)).toTuple())     # na zewnątrz bryły - w stronę osi
                self.assertGreater(float(normal @ (np.array([*corner, 0.]) - origin)), 0)
                face = _profile(origin, normal, lambda wp: wp.rect(4, 3))
                cut = kernel.surface_stamp_tool(block, face, normal, h, 'cut', origin=origin)
                self.assertGreater(kernel.boolean('intersect', block, [cut]).Volume(), cut.Volume() * .9)   # w materiale
                join = kernel.surface_stamp_tool(block, face, normal, h, 'join', origin=origin)
                self.assertLess(kernel.boolean('intersect', block, [join]).Volume(), join.Volume() * .1)    # w powietrzu
                self.assertLess(self.stamp(block, origin, normal, face, h, 'cut'), 0)
                self.assertGreater(self.stamp(block, origin, normal, face, h, 'join'), 0)
