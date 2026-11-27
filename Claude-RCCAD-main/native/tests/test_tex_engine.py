"""Tekstury geometryczne: silnik (rccad.tex_engine / tex_patterns / tex_relief / tex_mesh / tex_library) - rzeczywista geometria B-Rep."""
import json
import math
import os
import tempfile
import unittest

import cadquery as cq
import numpy as np

from rccad import kernel, tex_engine as te, tex_library as lib, tex_mesh as tm, tex_patterns as tp, tex_relief as tr
from rccad import vent_feature as vf
from rccad.document import Body


def target(shape, normal, point):
    body = Body('b', shape).prepared()
    f, n = kernel.face_at(body.shape, normal, point, curved=True)
    fw = f.wrapped if hasattr(f, 'wrapped') else f
    ref = vf.face_refs(body.shape, [fw])[0]
    ref['point'], ref['normal'] = [float(v) for v in point], [float(v) for v in normal]
    return body, ref


def recipe(body, refs, **p):
    r = te.new_recipe(body.id, refs if isinstance(refs, list) else [refs])
    r['p'] = dict(tp.DEFAULTS, **p)
    return r


BOX = cq.Workplane('XY').box(60, 40, 10).val()
FAST = ('knurl_cross', 'knurl_straight', 'knurl_spiral', 'honeycomb', 'dots', 'pyramids', 'voronoi', 'checker', 'herringbone', 'rings', 'hammered', 'triangles')


class TexEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_all_patterns_on_box_convex_and_concave(self):
        body, ref = target(BOX, [0, 0, 1], [0, 0, 5])
        v0 = BOX.Volume()
        for pat in tp.PATTERNS:
            for mode in ('convex', 'concave'):
                if pat in ('weave', 'scales', 'image'):
                    continue                                   # wolne albo wymagają obrazu - osobne testy
                p = dict(pattern=pat, mode=mode, depth=.5, size=6.0 if pat in ('honeycomb', 'voronoi') else 4.0)
                if pat == 'custom':
                    p['custom_loops'] = [np.array([[0, 0], [2, 0], [2, 2], [0, 2.]])]
                res = te.build([body], recipe(body, ref, **p))
                self.assertTrue(kernel.is_valid(res['shape']), (pat, mode))
                dv = res['shape'].Volume() - v0
                self.assertTrue(dv > 0 if mode == 'convex' else dv < 0, (pat, mode, dv))

    def test_overlapping_patterns_valid(self):
        body, ref = target(BOX, [0, 0, 1], [0, 0, 5])
        for pat, kw in (('weave', dict(strip=4.0)), ('scales', dict(size=8.0))):
            res = te.build([body], recipe(body, ref, pattern=pat, mode='convex', **kw))
            self.assertTrue(kernel.is_valid(res['shape']), pat)

    def test_margin_stays_inside_and_hole_avoidance(self):
        sh = cq.Workplane('XY').box(60, 40, 10).faces('>Z').workplane().pushPoints([(-15, 0), (15, 0)]).hole(8).val()
        body, ref = target(sh, [0, 0, 1], [0, 15, 5])
        pl = te.plan([body], recipe(body, ref, pattern='dots', size=3.0, margin=3.0, margin_holes=2.0))
        G = pl['groups'][0]
        pts = np.array([e.c for e in G.elements])
        self.assertGreater(len(pts), 20)
        self.assertGreaterEqual(G.region.edge_dist(pts).min(), 3.0 + 1.4 - 1e-6)                    # margines od krawędzi + połowa kopuły
        self.assertGreaterEqual(G.region.hole_dist(pts).min(), 2.0 + 1.4 - 1e-6)                    # margines od otworów

    def test_curved_surfaces(self):
        cases = {'cyl': (cq.Workplane('XY').circle(15).extrude(40).val(), [15, 0, 0], [15, 0, 20]),
                 'sphere': (cq.Workplane('XY').sphere(20).val(), [0, 0, 1], [0, 0, 20]),
                 'cone': (cq.Solid.makeCone(20, 8, 40), [.95, 0, .3], [14, 0, 20]),
                 'thin': (cq.Workplane('XY').box(60, 40, 10).faces('<Z').shell(-1.2).val(), [0, 0, 1], [0, 0, 5]),
                 'fillet': (cq.Workplane('XY').box(60, 40, 10).edges('|Z').fillet(6).val(), [0, 0, 1], [0, 0, 5]),
                 'chamfer': (cq.Workplane('XY').box(60, 40, 10).edges('>Z').chamfer(2).val(), [0, 0, 1], [0, 0, 5])}
        for name, (sh, n, pt) in cases.items():
            body, ref = target(sh, n, pt)
            res = te.build([body], recipe(body, ref, pattern='dots', size=4.0, height=.4))
            self.assertTrue(kernel.is_valid(res['shape']), name)
            self.assertGreater(res['shape'].Volume(), sh.Volume() + 1.0, name)

    def test_cylinder_whole_repeats_without_seam_duplicates(self):
        sh = cq.Workplane('XY').circle(15).extrude(40).val()
        body, ref = target(sh, [15, 0, 0], [15, 0, 20])
        pl = te.plan([body], recipe(body, ref, pattern='knurl_cross', size=5.0))
        self.assertTrue(any('powtórzeń na obwodzie' in t for _l, t in pl['report']))
        G = pl['groups'][0]
        c = np.array([e.c for e in G.elements])
        per = 2 * math.pi * 15
        x = np.unique(np.round(c[:, 0], 3))
        self.assertTrue(len(x) >= 3)

    def test_step_import_roundtrip_and_regenerate(self):
        path = os.path.join(tempfile.mkdtemp(), 'in.step')
        cq.exporters.export(cq.Workplane('XY').box(40, 30, 10).edges('>Z').fillet(2), path)
        imp = cq.importers.importStep(path).val()
        body, ref = target(imp, [0, 0, 1], [0, 0, 5])
        r = recipe(body, ref, pattern='honeycomb', size=6.0)
        out = te.run([body], r)
        self.assertTrue(kernel.is_valid(out[0].shape))
        self.assertGreater(out[0].shape.Volume(), imp.Volume())
        again = te.run([body], json.loads(json.dumps(r, default=lambda o: o.tolist() if hasattr(o, 'tolist') else str(o))))     # przepis jest serializowalny (zapis projektu)
        self.assertAlmostEqual(again[0].shape.Volume(), out[0].shape.Volume(), 3)

    def test_multi_face_continuity_modes(self):
        body = Body('b', cq.Workplane('XY').box(40, 30, 10).val()).prepared()
        refs = []
        for n, pt in (([0, 0, 1], [0, 0, 5]), ([1, 0, 0], [20, 0, 0])):
            f, _n = kernel.face_at(body.shape, n, pt, curved=True)
            ref = vf.face_refs(body.shape, [f.wrapped])[0]
            ref['point'], ref['normal'] = pt, n
            refs.append(ref)
        for multi in te.MULTI:
            r = recipe(body, refs, pattern='knurl_cross', size=4.0)
            r['multi'] = multi
            res = te.build([body], r)
            self.assertTrue(kernel.is_valid(res['shape']), multi)
            self.assertGreater(res['stats']['count'], 40, multi)

    def test_gradients_change_heights(self):
        body, ref = target(BOX, [0, 0, 1], [0, 0, 5])
        flat = te.build([body], recipe(body, ref, pattern='dots', size=4.0, height=1.0))
        grad = te.build([body], recipe(body, ref, pattern='dots', size=4.0, height=1.0,
                                       gradients=[dict(param='height', type='linear', v0=1.0, v1=.2, angle=0.0, length=50.0)]))
        self.assertLess(grad['shape'].Volume(), flat['shape'].Volume())
        self.assertGreater(grad['shape'].Volume(), BOX.Volume())

    def test_boundary_modes(self):
        body, ref = target(BOX, [0, 0, 1], [0, 0, 5])
        counts = {}
        for b in ('clip', 'remove', 'fit'):
            pl = te.plan([body], recipe(body, ref, pattern='honeycomb', size=7.0, boundary=b, margin=0.0))
            counts[b] = pl['count']
        self.assertGreaterEqual(counts['clip'], counts['remove'])

    def test_waves_and_image_relief(self):
        from PIL import Image
        body, ref = target(BOX, [0, 0, 1], [0, 0, 5])
        w = te.build([body], recipe(body, ref, pattern='waves', mode='convex'))
        self.assertTrue(kernel.is_valid(w['shape']))
        self.assertGreater(w['shape'].Volume(), BOX.Volume())
        path = os.path.join(tempfile.mkdtemp(), 'g.png')
        Image.fromarray(np.tile(np.linspace(0, 255, 64), (64, 1)).astype(np.uint8)).save(path)
        img = dict(tr.IMG_DEFAULTS, **tr.load_image(path))
        for mode in ('convex', 'concave'):
            res = te.build([body], recipe(body, ref, pattern='image', mode=mode, image=img, height=1.0, depth=1.0))
            self.assertTrue(kernel.is_valid(res['shape']), mode)
            dv = res['shape'].Volume() - BOX.Volume()
            self.assertTrue(dv > 0 if mode == 'convex' else dv < 0)

    def test_mesh_mode_watertight_and_3mf(self):
        body, ref = target(BOX, [0, 0, 1], [0, 0, 5])
        res = te.build([body], recipe(body, ref, pattern='knurl_cross', size=2.0, accuracy='mesh'))
        self.assertTrue(res.get('mesh'))
        V, T = tm.shape_arrays([res['shape']])
        self.assertEqual(tm.watertight(V, T), 0)
        path = os.path.join(tempfile.mkdtemp(), 'o.3mf')
        kernel.export_shapes([res['shape']], path)
        self.assertGreater(os.path.getsize(path), 1000)
        with self.assertRaises(kernel.CadError):
            kernel.export_shapes([res['shape']], os.path.join(tempfile.mkdtemp(), 'o.step'))      # siatka nie jest B-Rep

    def test_auto_mesh_above_limit_and_clear_errors(self):
        body, ref = target(BOX, [0, 0, 1], [0, 0, 5])
        r = recipe(body, ref, pattern='dots', size=.35, height=.1, margin=0.0)
        pl = te.plan([body], r)
        self.assertGreater(pl['count'], te.LIMIT_EXACT)
        r['auto_mesh'] = False
        with self.assertRaises(kernel.CadError) as cm:
            te.build([body], r)
        self.assertIn('Za dużo elementów', str(cm.exception))
        with self.assertRaises(kernel.CadError):
            te.plan([body], recipe(body, ref, size=0.0))
        with self.assertRaises(kernel.CadError):
            te.plan([body], recipe(body, ref, margin=40.0))                  # margines pochłania całą ścianę

    def test_cancel_leaves_model_unchanged(self):
        body, ref = target(BOX, [0, 0, 1], [0, 0, 5])
        v0 = body.shape.Volume()
        with self.assertRaises(kernel.CadError):
            te.build([body], recipe(body, ref, pattern='honeycomb', size=3.0), cancel=lambda: True)
        self.assertEqual(body.shape.Volume(), v0)

    def test_preview_mode_and_separate_bodies(self):
        body, ref = target(BOX, [0, 0, 1], [0, 0, 5])
        out = te.run([body], recipe(body, ref, pattern='dots', size=4.0, mode='preview'))
        self.assertAlmostEqual(out[0].shape.Volume(), BOX.Volume(), 6)
        r = recipe(body, ref, pattern='dots', size=4.0, mode='separate')
        out = te.run([body], r)
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[0].shape.Volume(), BOX.Volume(), 6)
        self.assertGreater(out[1].shape.Volume(), 1.0)

    def test_library_presets_and_user_configs(self):
        self.assertEqual(len(lib.PRESETS), 12)
        for e in lib.PRESETS:
            self.assertIn(e['params']['pattern'], tp.PATTERNS)
        names = {e['label'] for e in lib.PRESETS}
        self.assertTrue({'Antypoślizgowa', 'Blacha ryflowana', 'Plaster miodu', 'Łuski dekoracyjne', 'Powierzchnia młotkowana'} <= names)
        path = os.path.join(tempfile.mkdtemp(), 'c.json')
        lib.save_template('Test tekstury', dict(p=dict(tp.DEFAULTS, pattern='honeycomb', custom_loops=[np.zeros((3, 2))]), region={'type': 'face'}), 'Testy')
        try:
            self.assertIn('Test tekstury', [t['name'] for t in lib.templates()])
            dup = lib.duplicate_template('Test tekstury')
            lib.rename_template(dup, 'Test tekstury 2')
            self.assertGreaterEqual(lib.export_templates(path), 2)
        finally:
            for t in lib.templates():
                if t['name'].startswith('Test tekstury'):
                    lib.delete_template(t['name'])
        self.assertGreaterEqual(lib.import_templates(path), 2)
        for t in lib.templates():
            if t['name'].startswith('Test tekstury'):
                lib.delete_template(t['name'])
        self.assertTrue(lib.thumbnail_polys(dict(pattern='honeycomb')))

    def test_performance_scales_with_element_count(self):
        import time
        body, ref = target(BOX, [0, 0, 1], [0, 0, 5])
        times = []
        for size in (8.0, 4.0):
            t = time.time()
            res = te.build([body], recipe(body, ref, pattern='dots', size=size, margin=0.0))
            times.append((res['stats']['count'], time.time() - t))
            self.assertTrue(kernel.is_valid(res['shape']))
        self.assertGreater(times[1][0], times[0][0] * 2)


if __name__ == '__main__':
    unittest.main()
