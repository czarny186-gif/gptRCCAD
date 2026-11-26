"""Wentylacja (0.5.62): silnik bez okna - wzory z biblioteki, układy, tryby wypełniania i krawędzi, gradienty, wzór
mieszany, strefy zabronione, istniejące otwory, żebra za ścianką, wiele ścian, powierzchnie zakrzywione, cienkie i
zmienne ścianki, import STEP / SVG / DXF, własny szkic, przerwanie, zapis i odczyt projektu oraz testy wydajności
10 - 10 000 otworów (czas i pamięć wypisywane w raporcie testu)."""
import faulthandler
import math
import os
import sys
import tempfile
import time
import unittest

faulthandler.enable()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cadquery as cq
import numpy as np

from rccad import kernel as k
from rccad import vent_feature as VF, vent_layout as VLy, vent_library as VL, vent_cut as VC
from rccad.document import Body


def peak_mb():
    """Szczytowe zużycie pamięci procesu (MB) - Linux / macOS: resource, Windows: GetProcessMemoryInfo."""
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return r / 1024 / (1024 if sys.platform == 'darwin' else 1)
    except ImportError:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD), ('PeakWorkingSetSize', ctypes.c_size_t),
                        ('WorkingSetSize', ctypes.c_size_t), ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                        ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        k32 = ctypes.WinDLL('kernel32')
        psapi = ctypes.WinDLL('psapi')
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        try:
            psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        except Exception:
            return float('nan')                                         # pomiar pamięci niedostępny - test liczy dalej czas
        return c.PeakWorkingSetSize / 2 ** 20


def body(shape, ident):
    return Body(ident, shape, id=ident).prepared()


def faces(b, pred):
    return [f for f in b.shape.Faces() if pred(f)]


def recipe(b, fs, areas, **kw):
    return VF.new_recipe(b.id, VF.face_refs(b.shape, [f.wrapped for f in fs]), areas=areas, **kw)


C = dict(kind='circle', w=4.0, h=4.0, layout='hexagonal')


class VentEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plate = body(cq.Workplane().box(60, 40, 2).val(), 'P')
        cls.top = faces(cls.plate, lambda f: f.normalAt().z > .9)

    def cut(self, bodies, b, fs, areas, **kw):
        res = VF.build(bodies, recipe(b, fs, areas, **kw))
        self.assertTrue(res['shape'].isValid())
        self.assertEqual(len(res['shape'].Solids()), 1)
        self.assertGreater(res['stats']['count'], 0)
        self.assertLess(res['shape'].Volume(), b.shape.Volume() - 1e-3)
        return res

    def active(self, holes):
        return [h for h in holes if h['status'] in ('ok', 'adjust')]

    def test_library_every_pattern_plans_and_cuts_a_sample(self):
        ids = [e['id'] for e in VL.PATTERNS]
        self.assertGreaterEqual(len([e for e in VL.PATTERNS if not e['id'].startswith('fan_')]), 47)
        big = body(cq.Workplane().box(120, 80, 2).val(), 'B')
        top = faces(big, lambda f: f.normalAt().z > .9)
        for pid in ids:
            if pid == 'gyroid3d':
                continue
            a = dict(VL.preset(pid))
            a.pop('louver', None)
            pl = VF.plan([big], recipe(big, top, [a]))
            n = sum(len(self.active(x['holes'])) for x in pl['plans'])
            self.assertGreater(n, 0, pid)
        for pid in ('hex', 'slot_h', 'voronoi', 'gyroid2d', 'zigzag', 'fan_concentric', 'bubbles', 'star'):
            a = dict(VL.preset(pid))
            a.pop('louver', None)
            self.cut([big], big, top, [a])

    def test_fill_modes_edge_modes_gradients_and_mixed(self):
        P, top = self.plate, self.top
        base = self.cut([P], P, top, [dict(C, fill='A')])['stats']['count']
        nB = self.cut([P], P, top, [dict(C, fill='B', count=20)])['stats']['count']
        self.assertLessEqual(nB, 20)
        self.assertGreaterEqual(nB, 15)
        nC = self.cut([P], P, top, [dict(C, fill='C')])['stats']['count']
        self.assertGreaterEqual(nC, base)
        rD = self.cut([P], P, top, [dict(C, fill='D', target_open=20)])
        self.assertAlmostEqual(rD['stats']['open_percent'], 20, delta=4)
        for fl in ('E', 'F'):
            self.cut([P], P, top, [dict(C, fill=fl)])
        counts = {}
        for em in VLy.EDGES:
            counts[em] = self.cut([P], P, top, [dict(C, edge_mode=em, margin=0.0, w=7, h=7)])['stats']['count']
        self.assertGreater(counts['trim'], counts['full'])                                 # przycięte otwory przy brzegu
        g = self.cut([P], P, top, [dict(C, kind='hex', gradients=[dict(param='size', dir='h', func='linear', k0=1.0, k1=.4),
                                                                 dict(param='rotation', dir='radial', k0=0, k1=45)])])
        ws = [h['w'] for h in self.active(g['holes'])]
        self.assertGreater(max(ws) / min(ws), 1.8)                                          # gradient wielkości działa
        m = self.cut([P], P, top, [dict(C, mixed=[dict(kind='circle'), dict(kind='square'), dict(kind='hex')])])
        self.assertEqual({h['kind'] for h in self.active(m['holes'])}, {'circle', 'square', 'hex'})
        for lay in VLy.LAYOUTS:
            if lay in ('curve', 'sketch'):
                continue
            a = dict(C, layout=lay, gradients=[dict(param='spacing', dir='h', k0=1, k1=2)] if lay == 'gradient' else [])
            pl = VF.plan([P], recipe(P, top, [a]))
            self.assertGreater(len(self.active(pl['plans'][0]['holes'])), 0, lay)
        curve = [[-20, -10], [0, 10], [20, -10]]
        pl = VF.plan([P], recipe(P, top, [dict(C, layout='curve', curve=curve, px=6)]))
        self.assertGreater(len(self.active(pl['plans'][0]['holes'])), 3)
        pl = VF.plan([P], recipe(P, top, [dict(C, layout='sketch', points=[[-10, 0], [0, 0], [10, 0]])]))
        self.assertEqual(len(self.active(pl['plans'][0]['holes'])), 3)

    def test_bridges_margins_and_exclusion_zones(self):
        P, top = self.plate, self.top
        zones = [dict(type='rect', cx=0, cy=0, w=20, h=14, gap=1.5), dict(type='circle', cx=20, cy=10, d=10, gap=1.0)]
        res = self.cut([P], P, top, [dict(C, w=3, h=3)], exclusions=zones)
        for h in self.active(res['holes']):
            c = np.asarray(h['c'])
            self.assertFalse(abs(c[0]) < 10 + 1.5 and abs(c[1]) < 7 + 1.5, c)
            self.assertGreater(np.linalg.norm(c - (20, 10)), 5 + 1.0 + 1.5 - 1e-6)
        self.assertGreaterEqual(res['stats']['min_bridge'], 1.2 - 1e-6)
        comp = body(cq.Workplane().box(12, 12, 8).translate((-15, 0, 6)).val(), 'COMP')
        res = self.cut([P, comp], P, top, [dict(C, w=3, h=3)], exclusions=[dict(type='component', id='COMP', gap=2)])
        m = res['plan']['plans'][0]['mappers'][0]
        for h in self.active(res['holes']):
            c = m.to3d(h['c'])[0]                                                           # środek otworu w układzie świata
            self.assertFalse(abs(c[0] + 15) < 6 + 2 + 1.5 - 1e-6 and abs(c[1]) < 6 + 2 + 1.5 - 1e-6, c)

    def test_existing_holes_ribs_and_posts_behind_the_wall(self):
        ph = body(cq.Workplane().box(60, 40, 2).faces('>Z').workplane().hole(12).val(), 'PH')
        res = self.cut([ph], ph, faces(ph, lambda f: f.normalAt().z > .9), [dict(C, w=3, h=3)])
        for h in self.active(res['holes']):
            self.assertGreater(np.linalg.norm(h['poly'], axis=1).min(), 6 + 2 - 1e-6)     # margines od istniejącego otworu
        pr = body(cq.Workplane().box(60, 40, 2).union(cq.Workplane().box(3, 40, 8).translate((0, 0, -4)))
                  .union(cq.Workplane().cylinder(8, 3).translate((18, 10, -4))).val(), 'PR')
        res = self.cut([pr], pr, faces(pr, lambda f: f.normalAt().z > .9), [dict(C, w=3, h=3)])
        self.assertTrue(any('element konstrukcyjny' in t for _l, t in res['report']))
        skipped = [h for h in res['holes'] if 'słupek' in (h.get('reason') or '')]
        self.assertGreater(len(skipped), 3)
        m = res['plan']['plans'][0]['mappers'][0]
        for h in skipped:
            c = m.to3d(h['c'])[0]
            self.assertTrue(abs(c[0]) < 1.5 + 1.5 + 1e-6 or np.linalg.norm(c[:2] - (18, 10)) < 3 + 1.5 + 1e-6, c)

    def test_multi_face_modes_on_shelled_box_and_fillet(self):
        bx = body(cq.Workplane().box(80, 60, 40).faces('>Z').shell(-2).edges('|Z').fillet(4).val(), 'BX')
        front = faces(bx, lambda f: f.geomType() == 'PLANE' and f.normalAt().y < -.9 and f.Center().y < -29.5)
        side = faces(bx, lambda f: f.geomType() == 'PLANE' and f.normalAt().x > .9 and f.Center().x > 39.5)
        fil = [f for f in bx.shape.Faces() if f.geomType() == 'CYLINDER' and f.Center().x > 30 and f.Center().y < -20]
        fil = [max(fil, key=lambda f: f.Area())]
        self.assertEqual((len(front), len(side)), (1, 1))
        for m in ('independent', 'common', 'continue', 'fillets', 'outer'):
            res = self.cut([bx], bx, front + fil + side, [dict(C, w=3, h=3)], multi=m)
            self.assertFalse(any('nie przylega' in t for _l, t in res['report']), m)

    def test_curved_surfaces_cylinder_cone_sphere_and_wrap(self):
        cyl = body(cq.Workplane().cylinder(40, 15).faces('>Z or <Z').shell(-2).val(), 'CY')
        outer = [max(faces(cyl, lambda f: f.geomType() == 'CYLINDER'), key=lambda f: f.Area())]
        for mp in ('auto', 'geodesic', 'tangent', 'linear'):
            self.cut([cyl], cyl, outer, [dict(C, w=3, h=3)], mapping=mp)
        self.cut([cyl], cyl, outer, [dict(C, w=3, h=3)], multi='wrap')
        con = body(cq.Solid.makeCone(20, 10, 30).cut(cq.Solid.makeCone(18, 8, 30)), 'CO')
        self.cut([con], con, [max(faces(con, lambda f: f.geomType() == 'CONE'), key=lambda f: f.Area())], [dict(C, w=3, h=3)])
        sph = body(cq.Workplane().sphere(20).cut(cq.Workplane().sphere(18)).cut(cq.Workplane().box(60, 60, 30).translate((0, 0, -15))).val(), 'SP')
        self.cut([sph], sph, [max(faces(sph, lambda f: f.geomType() == 'SPHERE'), key=lambda f: f.Area())], [dict(C, w=3, h=3)])

    def test_thin_and_variable_walls_hole_types_and_step_import(self):
        th = body(cq.Workplane().box(40, 30, .6).val(), 'TH')
        self.cut([th], th, faces(th, lambda f: f.normalAt().z > .9), [C])
        wedge = body(cq.Solid.extrudeLinear(cq.Wire.makePolygon([(0, 0, 0), (60, 0, 0), (60, 0, 6), (0, 0, 1)], close=True), [], cq.Vector(0, 40, 0)), 'WG')
        res = self.cut([wedge], wedge, faces(wedge, lambda f: f.Center().z < .01 and f.normalAt().z < -.9), [C])
        n = len(self.active(res['holes']))
        area = math.pi * 4
        mean_t = 3.5
        self.assertAlmostEqual(res['stats']['removed'], n * area * mean_t, delta=.25 * n * area * mean_t)   # przelotowe przez zmienną ściankę
        P, top = self.plate, self.top
        for ht in ('blind', 'conical', 'stepped', 'chamfer2', 'louver_out'):
            r = recipe(P, top, [dict(C, layout='rect', w=4 if ht != 'louver_out' else 10, h=4 if ht != 'louver_out' else 2, kind='circle' if ht != 'louver_out' else 'rect')])
            r['cut']['hole_type'] = ht
            res = VF.build([P], r)
            self.assertTrue(res['shape'].isValid(), ht)
        d = tempfile.mkdtemp()
        path = os.path.join(d, 'plyta.step')
        cq.exporters.export(cq.Workplane().add(cq.Workplane().box(60, 40, 3).edges('|Z').fillet(5).val()), path)
        imp = body(cq.importers.importStep(path).val(), 'ST')
        self.cut([imp], imp, faces(imp, lambda f: f.normalAt().z > .9), [C])

    def test_custom_sketch_svg_dxf_import_and_cancel(self):
        from rccad import vent_ui
        P, top = self.plate, self.top
        sk = Body('Szkic', k.polyline('XY', [(0, 0), (6, 0), (3, 5), (0, 0)]), 'sketch', 'XY', id='SK').prepared()
        loops3 = VF._sketch_loops(sk)
        self.assertEqual(len(loops3), 1)
        loops = [[('S', [tuple(q[:2]) for q in loops3[0]])]]
        self.cut([P], P, top, [dict(C, kind='custom', loops=vent_ui._check_custom(loops), fit=True, w=5, h=5)])
        d = tempfile.mkdtemp()
        svg = os.path.join(d, 'w.svg')
        with open(svg, 'w') as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="20mm" viewBox="0 0 20 20">'
                    '<path d="M 2 2 L 18 2 L 10 16 Z"/><path d="M 2 2 L 18 2 L 10 16 Z"/><path d="M 1 18 L 5 18"/></svg>')
        loops, report = vent_ui.import_pattern(svg)
        self.assertEqual(len(loops), 1)
        self.assertTrue(any('nakładających' in t for _l, t in report))
        self.cut([P], P, top, [dict(C, kind='custom', loops=loops, fit=True, w=5, h=5)])
        import ezdxf
        dxf = os.path.join(d, 'w.dxf')
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_circle((0, 0), 3)
        msp.add_lwpolyline([(10, 0), (14, 0), (14, 4), (10, 4)], close=True)
        doc.saveas(dxf)
        loops, report = vent_ui.import_pattern(dxf)
        self.assertEqual(len(loops), 2)
        calls = []

        def cancel():
            calls.append(1)
            return len(calls) > 1
        with self.assertRaises(k.CadError):
            VF.build([P], recipe(P, top, [dict(C, w=1.5, h=1.5)]), cancel=cancel)

    def test_save_reopen_and_regenerate_vent_step(self):
        from rccad import history as hist
        from rccad.document import Document
        import uuid
        P = body(cq.Workplane().box(60, 40, 2).val(), uuid.uuid4().hex)
        top = faces(P, lambda f: f.normalAt().z > .9)
        r = recipe(P, top, [dict(C)])
        out = hist.run_recipe([P], r)
        v1 = out[0].shape.Volume()
        self.assertIn('vent', out[0].meta)
        thicker = body(cq.Workplane().box(60, 40, 4).val(), P.id)
        again = hist.run_recipe([thicker], r)                                                  # regeneracja po zmianie bryły
        self.assertAlmostEqual(thicker.shape.Volume() - again[0].shape.Volume(), 2 * (P.shape.Volume() - v1), delta=1.0)
        doc = Document()
        doc.commit([P])
        doc.commit(out, label='Wentylacja', op=r)
        path = os.path.join(tempfile.mkdtemp(), 'w.rccad')
        doc.save(path)
        back = Document.load(path)
        self.assertAlmostEqual(back.bodies[0].shape.Volume(), v1, 3)
        infos, cur = back.infos()
        self.assertEqual(infos[-1]['op']['type'], 'vent')

    def test_performance_10_to_10000_holes(self):
        """Czas i pamięć dla 10 / 100 / 500 / 1000 / 5000 / 10 000 otworów (płyta 400 × 300 × 2, okrągłe otwory)."""
        big = body(cq.Workplane().box(400, 300, 2).val(), 'BG')
        top = faces(big, lambda f: f.normalAt().z > .9)
        rows = []
        for n, w in ((10, 8.0), (100, 6.0), (500, 3.0), (1000, 2.0), (5000, 1.6), (10000, 1.2)):
            t0 = time.time()
            res = VF.build([big], recipe(big, top, [dict(C, w=w, h=w, fill='B', count=n, bridge=.5, margin=1, margin_holes=.5, min_area=.3)]))
            dt = time.time() - t0
            got = res['stats']['count']
            rss = peak_mb()
            rows.append((n, got, dt, rss))
            self.assertGreaterEqual(got, .9 * n)
            self.assertLessEqual(got, n)
            self.assertEqual(len(res['shape'].Solids()), 1)
            expect = big.shape.Volume() - got * math.pi * (w / 2) ** 2 * 2
            self.assertAlmostEqual(res['shape'].Volume(), expect, delta=1e-3 * expect)
            self.assertLess(dt, 60 + n * .05)                                                   # 10 000 otworów < ~9 min nawet na wolnym CI
        sys.stderr.write('\nWentylacja - wydajność (otwory zadane / wycięte / czas s / pamięć MB):\n' +
                         ''.join(f'  {a:>6} {b:>6} {c:8.1f} {d:8.0f}\n' for a, b, c, d in rows))


if __name__ == '__main__':
    unittest.main()
