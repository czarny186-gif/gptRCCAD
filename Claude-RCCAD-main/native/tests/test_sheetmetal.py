import math
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import ezdxf
from rccad import kernel as k
from rccad import history as hist
from rccad import sheetmetal as shm
from rccad.document import Body

T = 2.0


def plate():
    """Blacha 100 x 50 x 2 (narożnik w początku układu): góra z=2, dół z=0."""
    return k.box(100, 50, 2)


def face_at_z(shape, z):
    return next(f for f in shape.Faces() if abs(f.Center().z - z) < 1e-6 and f.geomType() == 'PLANE')


def base_of(shape):
    return shm.sheet_of_face(shape, face_at_z(shape, 2))


def spec(p0, p1, n, m, r=2.0, angle=90.0, length=20.0):
    return dict(kind='base', p0=list(p0), p1=list(p1), n=list(n), m=list(m), r=r, angle=angle, length=length)


UP = [(100, 0, 2), (100, 50, 2), (0, 0, 1), (1, 0, 0)]          # krawędź górna przy x=100
UP_Y50 = [(100, 50, 2), (0, 50, 2), (0, 0, 1), (0, 1, 0)]       # krawędź górna przy y=50
UP_X0 = [(0, 50, 2), (0, 0, 2), (0, 0, 1), (-1, 0, 0)]          # krawędź górna przy x=0
UP_Y0 = [(0, 0, 2), (100, 0, 2), (0, 0, 1), (0, -1, 0)]         # krawędź górna przy y=0
DOWN = [(100, 0, 0), (100, 50, 0), (0, 0, -1), (1, 0, 0)]       # krawędź dolna przy x=100


def build(sheet, specs, **rules):
    rec = dict(type='sheetbuild', id='b', base=sheet['base'], t=sheet['t'], flanges=specs, rules=rules)
    return shm.build_sheet(rec)


class SheetMetalTests(unittest.TestCase):
    def recipe(self, specs, **rules):
        sheet = base_of(plate())
        return dict(type='sheetbuild', id='b', base=sheet['base'], t=sheet['t'], flanges=specs, rules=rules)

    def chain(self, angles=(30, 45, 60), sides=('out', 'in'), root=UP):
        return [spec(*root[:2], root[2], root[3], angle=angles[0])] + [
            dict(kind='tip', parent=i, side=sides[i], r=2., angle=angle, length=20.)
            for i, angle in enumerate(angles[1:])]

    def test_multibend_angles_directions_and_analytic_volume(self):
        for angles in ((30, 45, 60), (90, 90, 90), (45, 90, 120), (120, 60, 30)):
            for sides in (('out', 'in'), ('in', 'out'), ('out', 'out')):
                for root in (UP, DOWN):
                    with self.subTest(angles=angles, sides=sides, root=root):
                        recipe = self.recipe(self.chain(angles, sides, root))
                        shape = shm.build_sheet(recipe)
                        expected = 10000 + 50 * sum(math.radians(a) * ((2 + T)**2 - 2**2) / 2 + 20*T for a in angles)
                        self.assertTrue(shape.isValid())
                        self.assertEqual(len(shape.Solids()), 1)
                        self.assertAlmostEqual(shape.Volume(), expected, delta=.01)

    def test_outside_dimension_tip_pick_uses_actual_shortened_parent(self):
        parent = spec(*UP[:2], UP[2], UP[3], length=20)
        recipe = self.recipe([parent], outside=True)
        eff, _ = shm._effective([parent], T, True, True)
        a, b, _, _ = shm._tip_geom(eff[0], 'out', T)
        found = shm.spec_for_edge(recipe['base'], T, [parent], recipe['rules'], (a+b)/2, .01)
        self.assertEqual(found, dict(kind='tip', parent=0, side='out'))

    def test_each_flange_keeps_its_dimension_mode(self):
        parent = dict(spec(*UP[:2], UP[2], UP[3]), outside=False)
        eff, _ = shm._effective([parent], T, True, True)
        self.assertEqual(eff[0]['length'], 20)
        with self.assertRaises(k.CadError):
            shm.build_sheet(self.recipe([dict(parent, outside=True, angle=180)]))

    def test_duplicate_sides_and_invalid_parent_graph_are_refused(self):
        parent = spec(*UP[:2], UP[2], UP[3])
        for other in (spec(*DOWN[:2], DOWN[2], DOWN[3]),
                      dict(kind='tip', parent=-1, side='out', r=2, angle=90, length=20),
                      dict(kind='tip', parent=1, side='out', r=2, angle=90, length=20)):
            with self.subTest(other=other), self.assertRaises(k.CadError):
                shm.build_sheet(self.recipe([parent, other]))
        chain = self.chain()
        with self.assertRaises(k.CadError):
            shm.build_sheet(self.recipe(chain + [dict(chain[1], side='in')]))

    def test_self_intersecting_return_is_refused(self):
        parent = spec(*UP[:2], UP[2], UP[3], angle=180, length=10)
        child = dict(kind='tip', parent=0, side='in', r=2, angle=90, length=20)
        with self.assertRaisesRegex(k.CadError, 'nachodzą'):
            shm.build_sheet(self.recipe([parent, child]))

    def test_flat_length_uses_kfactor_and_bend_allowance(self):
        recipe = self.recipe(self.chain(), kfactor=.33)
        pattern = shm.flat_pattern(recipe)
        allowance = math.radians(30+45+60) * (2 + .33*T)
        self.assertAlmostEqual(pattern['area'], 5000 + 50*(60+allowance), delta=1e-5)
        self.assertEqual([b['direction'] for b in pattern['bends']], ['UP', 'DOWN', 'DOWN'])
        self.assertAlmostEqual(sum(b['allowance'] for b in pattern['bends']), allowance)
        other = shm.flat_pattern(self.recipe(self.chain(), kfactor=.5))
        self.assertGreater(other['area'], pattern['area'])

    def test_rotated_plate_has_same_developed_area(self):
        original = plate()
        rotated = original.rotate((0,0,0), (1,2,3), 37).translate((10,-5,8))
        face = face_at_z(original, 2).rotate((0,0,0), (1,2,3), 37).translate((10,-5,8))
        face = min(rotated.Faces(), key=lambda f: (f.Center()-face.Center()).Length)
        sheet = shm.sheet_of_face(rotated, face)
        # Long upper edge in the transformed local frame.
        edge = next(e for e in face.Edges() if abs(e.Length()-100) < 1e-5)
        n,m = shm.edge_side(rotated, edge, T)
        s = spec(edge.startPoint().toTuple(), edge.endPoint().toTuple(), n, m, angle=45)
        pattern = shm.flat_pattern(dict(base=sheet['base'], t=T, flanges=[s], rules={}))
        self.assertAlmostEqual(pattern['area'], 5000+100*(20+math.pi/4*(2+.44*T)), delta=.001)

    def test_five_bends_pick_replay_and_project_roundtrip(self):
        from rccad.document import Document
        specs = self.chain((15,25,35,40,30), ('out','in','out','in'))
        recipe = self.recipe(specs)
        folded = shm.build_sheet(recipe)
        eff, _ = shm._effective(specs, T, True)
        a,b,_,_ = shm._tip_geom(eff[-1], 'in', T)
        self.assertEqual(shm.spec_for_edge(recipe['base'], T, specs, {}, (a+b)/2, .01),
                         dict(kind='tip', parent=4, side='in'))
        doc = Document();body = Body('Blacha', plate()).prepared()
        recipe['id'] = body.id
        doc.commit([body])
        replay = hist.run_recipe([body], recipe)
        doc.commit(replay, label='Gięcia', op=recipe)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'five.rccadx';doc.save(path)
            restored = Document.load(path)
            self.assertAlmostEqual(restored.get(body.id).shape.Volume(), folded.Volume(), delta=.001)
            info = restored.infos()[0][-1]['op']
            self.assertEqual(info['flanges'], specs)
            self.assertAlmostEqual(shm.flat_pattern(info)['area'], shm.flat_pattern(recipe)['area'], delta=.001)

    def test_four_independent_sides_flatten_without_corner_extensions(self):
        specs = [spec(*e[:2], e[2], e[3]) for e in (UP, UP_Y50, UP_X0, UP_Y0)]
        pattern = shm.flat_pattern(self.recipe(specs, miter=False))
        self.assertEqual(len(pattern['bends']), 4)
        self.assertAlmostEqual(pattern['area'], 5000 + 300*(20 + math.pi/2*(2+.44*T)), delta=.001)

    def test_mixed_angle_adjacent_sides_require_untrimmed_corners(self):
        specs = [spec(*UP[:2], UP[2], UP[3], angle=45), spec(*UP_Y50[:2], UP_Y50[2], UP_Y50[3], angle=60)]
        with self.assertRaisesRegex(k.CadError, '90°'):
            shm.build_sheet(self.recipe(specs))
        pattern = shm.flat_pattern(self.recipe(specs, miter=False))
        self.assertAlmostEqual(pattern['area'], 5000 + 50*(20+math.pi/4*(2+.44*T)) + 100*(20+math.pi/3*(2+.44*T)), delta=.001)

    def test_flat_rejects_unsupported_geometry_and_invalid_k(self):
        parent = spec(*UP[:2], UP[2], UP[3])
        for factor in (-.1, .51, float('nan')):
            with self.subTest(factor=factor), self.assertRaises(k.CadError):
                shm.flat_pattern(self.recipe([parent], kfactor=factor))
        for recipe in (self.recipe([parent, spec(*UP_Y50[:2], UP_Y50[2], UP_Y50[3])]),
                       self.recipe([dict(parent, hem=dict(gap=.1, ret=5))]),
                       self.recipe([parent], relief='square', relief_size=1)):
            with self.subTest(recipe=recipe), self.assertRaisesRegex(k.CadError, 'rozwinąć'):
                shm.flat_pattern(recipe)

    def test_dxf_roundtrip_has_mm_closed_cut_and_separate_bends(self):
        recipe = self.recipe(self.chain())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'laser.dxf'
            pattern = shm.export_flat_dxf(recipe, path)
            doc = ezdxf.readfile(path)
            self.assertEqual(doc.units, ezdxf.units.MM)
            self.assertFalse(doc.audit().has_errors)
            cuts = list(doc.modelspace().query('LWPOLYLINE[layer=="CUT"]'))
            self.assertEqual(len(cuts), 1)
            self.assertTrue(cuts[0].closed)
            points = np.array(list(cuts[0].get_points('xy')))
            area = abs(np.dot(points[:,0], np.roll(points[:,1], 1))-np.dot(points[:,1], np.roll(points[:,0], 1)))/2
            self.assertAlmostEqual(area, pattern['area'], delta=1e-5)
            bends = list(doc.modelspace().query('LINE'))
            self.assertEqual(len(bends), 3)
            self.assertEqual([e.dxf.layer for e in bends], ['BEND_UP', 'BEND_DOWN', 'BEND_DOWN'])
            self.assertTrue(all(e.has_xdata('RCCAD') for e in bends))
            original = path.read_bytes()
            with patch('ezdxf.document.Drawing.saveas', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    shm.export_flat_dxf(recipe, path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_flat_export_rejects_untracked_holes_without_overwriting_file(self):
        recipe = self.recipe(self.chain())
        folded = shm.build_sheet(recipe)
        drilled = k.hole(folded, 3, 20, 20)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'laser.dxf'
            path.write_text('existing')
            with self.assertRaisesRegex(k.CadError, 'zmieniła'):
                shm.export_flat_dxf(recipe, path, drilled)
            self.assertEqual(path.read_text(), 'existing')

    def test_convert_reads_thickness_normal_and_base(self):
        s = plate()
        sheet = base_of(s)
        self.assertAlmostEqual(sheet['t'], 2, 6)
        self.assertEqual([round(c, 6) for c in sheet['N']], [0, 0, 1])
        self.assertEqual(sorted(round(d, 6) for d in sheet['dims']), [50, 100])
        self.assertAlmostEqual(shm.base_solid(sheet['base']).Volume(), 100 * 50 * 2, 4)

    def test_convert_rejects_non_box_and_non_rectangle(self):
        cyl = k.cylinder(5, 10)
        with self.assertRaises(k.CadError):
            shm.sheet_of_face(cyl, cyl.Faces()[0])

    def test_flange_up_and_down_volume_and_extent(self):
        sheet = base_of(plate())
        r, L = 2.0, 20.0
        area = math.pi / 4 * ((r + T) ** 2 - r ** 2) + L * T
        up = build(sheet, [spec(*UP[:2], UP[2], UP[3], r, 90, L)])
        self.assertAlmostEqual(up.Volume(), 100 * 50 * 2 + area * 50, delta=0.2)
        bb = up.BoundingBox()
        self.assertAlmostEqual(bb.zmax, T + r + L, delta=1e-3)
        self.assertAlmostEqual(bb.xmax, 100 + r + T, delta=1e-3)
        down = build(sheet, [spec(*DOWN[:2], DOWN[2], DOWN[3], r, 90, L)])
        self.assertAlmostEqual(down.BoundingBox().zmin, 2 - (T + r + L), delta=1e-3)

    def test_outside_dimension_shortens_straight_part_by_bend_setback(self):
        sheet = base_of(plate())
        L = 20.0
        up = build(sheet, [spec(*UP[:2], UP[2], UP[3], 2.0, 90, L)], outside=True)
        # 90°: odsadzenie gięcia = promień + grubość = 4 mm, więc prosta część 16 mm, zmax = 2 + 2 + 16 + ... wg wymiaru zewnętrznego
        self.assertAlmostEqual(up.BoundingBox().zmax, T + 2.0 + (L - (2.0 + T)), delta=1e-3)
        with self.assertRaises(k.CadError):
            build(sheet, [spec(*UP[:2], UP[2], UP[3], 2.0, 90, 3.0)], outside=True)

    def test_hem_hugs_top_surface_without_extra_flange(self):
        sheet = base_of(plate())
        h = spec(*UP[:2], UP[2], UP[3], 2.0, 90, 20.0)
        h['hem'] = dict(gap=0.1, ret=10.0)
        hem = build(sheet, [h])
        self.assertEqual(len(hem.Solids()), 1)
        # płyta ma wysokość 2 mm; odcinek powrotny leży 2r + szczelina nad płytą, zmax = 2t + 2r + szczelina
        self.assertAlmostEqual(hem.BoundingBox().zmax, 2 * T + 0.1, delta=1e-3)   # promień zmniejszony do 0,05
        # zawinięcie nie zależy od długości kołnierza: zmiana długości nie zmienia bryły
        h2 = dict(h, length=50.0)
        self.assertAlmostEqual(build(sheet, [h2]).Volume(), hem.Volume(), delta=1e-3)

    def test_hem_gap_widens_the_turn(self):
        sheet = base_of(plate())
        h = spec(*UP[:2], UP[2], UP[3], 2.0, 90, 20.0)
        h['hem'] = dict(gap=4.0, ret=10.0)
        hem = build(sheet, [h])
        self.assertAlmostEqual(hem.BoundingBox().zmax, 2 * T + 4.0, delta=1e-3)   # promień 2 = połowa szczeliny

    def test_hem_gap_below_minimum_is_refused(self):
        sheet = base_of(plate())
        h = spec(*UP[:2], UP[2], UP[3], 2.0, 90, 20.0)
        for gap in (0.0, 0.05):
            h['hem'] = dict(gap=gap, ret=10.0)
            with self.subTest(gap=gap), self.assertRaises(k.CadError):
                build(sheet, [h])

    def test_hem_on_flange_tip_adds_material(self):
        sheet = base_of(plate())
        parent = spec(*UP[:2], UP[2], UP[3])
        parent_only = build(sheet, [parent])
        hem_tip = dict(kind='tip', parent=0, side='out', r=2.0, angle=90.0, length=10.0, hem=dict(gap=0.1, ret=5.0))
        hemmed = build(sheet, [parent, hem_tip])
        self.assertEqual(len(hemmed.Solids()), 1)
        self.assertGreater(hemmed.Volume(), parent_only.Volume())

    def test_flange_on_flange_tip_bends_outward(self):
        sheet = base_of(plate())
        parent = spec(*UP[:2], UP[2], UP[3])
        child = dict(kind='tip', parent=0, side='out', r=2.0, angle=90.0, length=20.0)
        shape = build(sheet, [parent, child])
        self.assertAlmostEqual(shape.BoundingBox().xmax, 126, delta=1e-3)   # 102 + t + r + L
        self.assertEqual(len(shape.Solids()), 1)

    def test_box_four_flanges_close_with_miter_into_one_solid(self):
        sheet = base_of(plate())
        specs = [spec(*UP[:2], UP[2], UP[3]), spec(*UP_Y50[:2], UP_Y50[2], UP_Y50[3]),
                 spec(*UP_X0[:2], UP_X0[2], UP_X0[3]), spec(*UP_Y0[:2], UP_Y0[2], UP_Y0[3])]
        box = build(sheet, specs)
        self.assertEqual(len(box.Solids()), 1)
        bb = box.BoundingBox()
        self.assertAlmostEqual(bb.zmax, T + 2 + 20, delta=1e-3)
        self.assertAlmostEqual(bb.xmin, -4, delta=1e-3)
        self.assertAlmostEqual(bb.xmax, 104, delta=1e-3)
        self.assertAlmostEqual(bb.ymin, -4, delta=1e-3)
        self.assertAlmostEqual(bb.ymax, 54, delta=1e-3)

    def _butt_model(self):
        slab = k.box(100, 50, 1)
        top = next(f for f in slab.Faces() if abs(f.Center().z - 1) < 1e-6 and f.geomType() == 'PLANE')
        sheet = shm.sheet_of_face(slab, top)
        UP1 = [(100, 0, 1), (100, 50, 1), (0, 0, 1), (1, 0, 0)]
        UPY1 = [(100, 50, 1), (0, 50, 1), (0, 0, 1), (0, 1, 0)]
        A = spec(*UP1[:2], UP1[2], UP1[3], 0.5, 90, 5.0)
        B = spec(*UPY1[:2], UPY1[2], UPY1[3], 0.5, 90, 5.0)
        return sheet, A, B

    def _vol_in(self, shape, x0, x1, y0, y1, z0, z1):
        import cadquery as cq
        box = cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, pnt=cq.Vector(x0, y0, z0))
        return shape.intersect(box).Volume()   # pusta część wspólna to 0, a nie błąd walidacji

    def test_butt_corner_gap_is_empty(self):
        """Styk na styk, przypadek 100×50×1, szczelina 1 mm, promień 0,5 mm: między końcem ściany b (x≈99,5)
        a wewnętrzną powierzchnią ściany a (x≈100,5) nie może być materiału powyżej zagięć."""
        sheet, A, B = self._butt_model()
        full = build(sheet, [A, B], gap=1.0)
        self.assertLess(self._vol_in(full, 99.6, 100.4, 50.1, 50.9, 2.0, 4.0), 1e-3)

    def test_butt_outer_end_flush(self):
        """Zewnętrzny koniec ściany a kończy się na zewnętrznej powierzchni ściany b (y≈51,5), nie wychodzi dalej."""
        sheet, A, B = self._butt_model()
        full = build(sheet, [A, B], gap=1.0)
        self.assertLess(self._vol_in(full, 100.6, 101.4, 51.6, 52.5, 2.0, 4.0), 1e-3)

    def test_parallel_inward_tips_do_not_overlap(self):
        """Łączenie równoległe: wewnętrzne kołnierze z dwóch ścian w jednym narożniku nie nachodzą na siebie."""
        sheet, A, B = self._butt_model()
        tipA = dict(kind='tip', parent=0, side='in', r=0.5, angle=90.0, length=5.0)
        tipB = dict(kind='tip', parent=1, side='in', r=0.5, angle=90.0, length=5.0)
        onlyA = build(sheet, [A, B, tipA], gap=1.0)
        both = build(sheet, [A, B, tipA, tipB], gap=1.0)
        # obszar zajmowany przez kołnierz A przy narożniku (x 96–99,5; y 45–49,4): kołnierz B nie może tam wchodzić
        R = (96.0, 99.5, 45.0, 49.4, 4.0, 8.0)
        self.assertAlmostEqual(self._vol_in(both, *R), self._vol_in(onlyA, *R), delta=1e-3)

    def test_diagonal_joint_closes_box_into_one_solid(self):
        sheet = base_of(plate())
        specs = [spec(*UP[:2], UP[2], UP[3]), spec(*UP_Y50[:2], UP_Y50[2], UP_Y50[3]),
                 spec(*UP_X0[:2], UP_X0[2], UP_X0[3]), spec(*UP_Y0[:2], UP_Y0[2], UP_Y0[3])]
        box = build(sheet, specs, joint='diagonal')
        self.assertEqual(len(box.Solids()), 1)

    def test_gap_at_corner_reduces_material(self):
        sheet = base_of(plate())
        specs = [spec(*UP[:2], UP[2], UP[3]), spec(*UP_Y50[:2], UP_Y50[2], UP_Y50[3])]
        g0 = build(sheet, specs, gap=0.0)
        g2 = build(sheet, specs, gap=2.0)
        self.assertEqual(len(g2.Solids()), 1)
        self.assertLess(g2.Volume(), g0.Volume() - 1e-3)

    def test_corner_relief_removes_material(self):
        sheet = base_of(plate())
        specs = [spec(*UP[:2], UP[2], UP[3]), spec(*UP_Y50[:2], UP_Y50[2], UP_Y50[3])]
        none = build(sheet, specs, relief='none')
        sq = build(sheet, specs, relief='square', relief_size=4)
        rd = build(sheet, specs, relief='round', relief_size=4)
        self.assertLess(sq.Volume(), none.Volume())
        self.assertLess(rd.Volume(), none.Volume())
        self.assertEqual(len(sq.Solids()), 1)
        with self.assertRaises(k.CadError):
            build(sheet, specs, relief='trójkąt', relief_size=2)

    def test_invalid_numbers_are_refused(self):
        sheet = base_of(plate())
        for r, a, L in ((0, 90, 20), (2, 0, 20), (2, 200, 20), (2, 90, 0)):
            with self.subTest(r=r, a=a, L=L), self.assertRaises(k.CadError):
                build(sheet, [spec(*UP[:2], UP[2], UP[3], r, a, L)])

    def test_pick_finds_top_edge_and_refuses_vertical_edge(self):
        sheet = base_of(plate())
        found = shm.spec_for_edge(sheet['base'], sheet['t'], [], {}, (100, 25, 2), 1e-3)
        self.assertEqual(found['kind'], 'base')
        self.assertEqual([round(v, 6) for v in found['n']], [0, 0, 1])
        with self.assertRaises(k.CadError):
            shm.spec_for_edge(sheet['base'], sheet['t'], [], {}, (100, 0, 1), 1e-3)

    def test_recipe_replay_sheetbuild(self):
        s = plate()
        face = face_at_z(s, 2)
        body = Body('Blacha', s, 'solid', 'XY', id='b1')
        sheet = shm.sheet_of_face(s, face)
        conv = dict(type='sheet', id='b1', face=hist.face_ref(face, sheet['N'], face.Center().toTuple(), s), base=sheet['base'], t=sheet['t'])
        bodies = hist.run_recipe([body], conv)
        rec = dict(type='sheetbuild', id='b1', base=sheet['base'], t=sheet['t'], flanges=[spec(*UP[:2], UP[2], UP[3])], rules={})
        out = hist.run_recipe(list(bodies), rec)
        self.assertEqual(len(out), 1)
        self.assertGreater(out[0].shape.Volume(), 10000)
        self.assertIn('b1', hist.reads(rec, list(bodies)))


if __name__ == '__main__':
    unittest.main()
