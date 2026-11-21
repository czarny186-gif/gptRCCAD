"""TWIST etap 10: anulowanie obliczeń, wielokrotne skręcanie, pamięć podglądu, czasy, samoprzecięcia, STEP, operacje logiczne."""
import math
import tempfile
import threading
import time
import tracemalloc
import unittest
from pathlib import Path

import cadquery as cq
import numpy as np

from rccad import history as hist
from rccad import kernel as k
from rccad import twist as tw
from rccad import twist_math as tm
from rccad import twist_occ as to
from rccad import twist_preview as tp
from rccad.document import Body

Z = dict(kind='global', axis='Z')
W = cq.Workplane


def corners(shape):
    return np.array(sorted(tuple(round(c, 5) + 0.0 for c in v.toTuple()) for v in shape.Vertices()))


def big_plate():
    """Duża bryła: 48 otworów przelotowych, 2 nieprzelotowe, zaokrąglone krawędzie wzdłuż osi (≈ 90 ścian)."""
    return (W().box(60, 80, 200).edges('|Z').fillet(5).faces('>Z').workplane().rarray(9, 9, 6, 8).hole(3)
            .faces('>Z').workplane().pushPoints([(-25, -36), (25, 36)]).hole(4, 60).val())


class CancelTests(unittest.TestCase):
    def test_long_computation_stops_quickly_when_cancelled(self):
        plate = big_plate()
        field = tw.field(Z, plate, 120.0)
        for delay in (.05, .8):
            stop, out = threading.Event(), {}

            def run():
                try:
                    to.twist_solid(plate, field, cancel=stop)
                    out['result'] = 'done'
                except to.TwistCancelled as exc:
                    out['result'] = str(exc)
            worker = threading.Thread(target=run)
            worker.start()
            time.sleep(delay)
            stop.set()
            asked = time.perf_counter()
            worker.join(30)
            self.assertFalse(worker.is_alive())
            self.assertLess(time.perf_counter() - asked, 8.0)           # przerwanie między krokami Open CASCADE
            self.assertIn('przerwane', out['result'])
        self.assertTrue(issubclass(to.TwistCancelled, k.CadError))
        a = Body('A', k.box(20, 30, 80)).prepared()
        stop = threading.Event()
        stop.set()
        with self.assertRaises(to.TwistCancelled):
            hist.run_twist([a], dict(type='twist', id=a.id, angle=90.0, axis=Z), cancel=stop)

    def test_source_is_copied_before_background_work(self):
        a = Body('A', k.box(20, 30, 80)).prepared()
        out = hist.run_twist([a], dict(type='twist', id=a.id, angle=90.0, axis=Z))[0]
        self.assertFalse(any(f.wrapped.IsSame(g.wrapped) for f in out.shape.Faces() for g in a.shape.Faces()))


class RepeatedTwistTests(unittest.TestCase):
    def test_twice_equals_once_and_three_times_valid(self):
        box = k.box(20, 30, 80)
        a = Body('A', box).prepared()
        r = dict(type='twist', id=a.id, angle=60.0, axis=Z)
        b = hist.run_twist([a], r)[0]
        c = hist.run_twist([b], dict(r, angle=30.0))[0]
        self.assertEqual(len(c.meta['twist']['stack']), 1)
        np.testing.assert_allclose(corners(c.shape), corners(to.twist_solid(box, tw.field(Z, box, 90.0))), atol=1e-5)
        d = hist.run_twist([c], dict(r, angle=-45.0, range_from=.5, kind='smoothstep', anchor='end'))[0]
        self.assertEqual(len(d.meta['twist']['stack']), 2)
        f = tm.compose([tw.field(Z, box, 60.0), tw.field(Z, box, 30.0), tw.field(Z, box, -45.0, .5, 1.0, 'smoothstep', 2.0, 'end')], 80)
        self.assertTrue(to.check(d.shape, box, f)['ok'])                   # złożenie liczone od kształtu źródłowego
        self.assertAlmostEqual(d.shape.Volume(), box.Volume(), delta=1e-4 * box.Volume())
        with self.assertRaises(k.CadError) as err:
            hist.run_twist([b], dict(r, axis=dict(kind='global', axis='X')))
        self.assertIn('innej osi', str(err.exception))
        moved = c.placed(k.transformed(c.shape, np.eye(3), np.array([0, 0, 50.0])), np.column_stack([np.eye(3), (0, 0, 50.0)]))
        self.assertAlmostEqual(moved.meta['twist']['stack'][0]['origin'][2], 90.0)    # stos przesunięty razem z bryłą
        again = hist.run_twist([moved], dict(r, angle=10.0, axis=dict(kind='global', axis='Z')))[0]
        self.assertAlmostEqual(k.bounds(again.shape).zmin, 50.0, 5)

    def test_composite_field(self):
        box = k.box(20, 30, 80)
        a, b = tw.field(Z, box, 90.0), tw.field(Z, box, -45.0, .5, 1.0, 'smoothstep')
        comp = tm.compose([a, b], 80)
        ts = np.linspace(-50, 50, 41)
        np.testing.assert_allclose(comp.theta(ts), a.theta(ts) + b.theta(ts))
        self.assertEqual(comp.breaks, (-40.0, 0.0, 40.0))
        flipped = tm.make_field(a.origin, -np.asarray(a.direction), -90.0, -40.0, 40.0)    # ta sama prosta, odwrotny zwrot
        pts = np.random.default_rng(1).uniform(-20, 20, (50, 3))
        np.testing.assert_allclose(tm.compose([a, flipped], 80).apply(pts), flipped.apply(a.apply(pts)), atol=1e-9)
        with self.assertRaises(tm.TwistParamError):
            tm.compose([a, tm.make_field((0, 0, 0), (0, 0, 1), 10.0, 0, 1)], 80)          # przesunięta oś
        np.testing.assert_allclose(comp.inverse().apply(comp.apply(pts)), pts, atol=1e-9)


class PreviewMemoryTests(unittest.TestCase):
    def setUp(self):
        self.mesh = k.display_mesh(W().box(30, 40, 80).faces('>Z').workplane().rarray(10, 10, 2, 3).hole(4).val())

    def sliced(self, layers=32):
        return tp.SlicedMesh(self.mesh.vertices, self.mesh.triangles, self.mesh.edges, (0, 0, 0), (0, 0, 1), tp.cut_planes(-40, 40, layers))

    def test_shared_vertices_and_single_precision(self):
        s = self.sliced(32)
        self.assertEqual(s.vertices.dtype, np.float32)
        self.assertEqual(s.triangles.dtype, np.uint32)
        self.assertLess(len(s.vertices), .7 * len(s.triangles))            # wspólne wierzchołki (bez nich: ok. 2× trójkątów)
        used = np.unique(s.triangles)
        self.assertEqual(len(used), len(s.vertices) - len(set(range(len(self.mesh.vertices))) - set(used.tolist())))
        f = tm.make_field((0, 0, 0), (0, 0, 1), 90.0, -40, 40)
        _, edges = s.twisted(f)
        for key, p in s.edges.items():                                      # jedno obracanie wszystkich krawędzi = osobno
            np.testing.assert_allclose(edges[key], f.apply(p), atol=1e-4)

    def test_cache_reuses_limits_and_frees(self):
        cache = tp.SliceCache(entries=3)
        builds = []

        def build(n):
            builds.append(n)
            return self.sliced(n)
        for n in (8, 16, 8, 32, 8, 64, 16):
            cache.get(('m', n), lambda n=n: build(n), self.mesh)
        self.assertEqual(builds, [8, 16, 32, 64, 16])                      # powrót do 8 - z pamięci
        self.assertEqual(len(cache), 3)
        small = tp.SliceCache(entries=10, budget=1)                         # budżet pamięci: zostaje tylko ostatnia
        for n in (8, 16, 32):
            small.get(n, lambda n=n: self.sliced(n))
        self.assertEqual(len(small), 1)
        cache.clear()
        self.assertEqual((len(cache), cache.nbytes), (0, 0))

    def test_no_memory_growth_over_many_updates(self):
        s = self.sliced(64)
        f = tm.make_field((0, 0, 0), (0, 0, 1), 90.0, -40, 40)
        s.twisted(f)
        tracemalloc.start()
        base = tracemalloc.get_traced_memory()[0]
        for angle in range(91, 151):
            out = s.twisted(tm.make_field((0, 0, 0), (0, 0, 1), float(angle), -40, 40))
        del out
        grown = tracemalloc.get_traced_memory()[0] - base
        tracemalloc.stop()
        self.assertLess(grown, 2 * 2 ** 20)                                 # bez wycieku między aktualizacjami

    def test_update_speed(self):
        s = self.sliced(64)
        start = time.perf_counter()
        for angle in range(20):
            s.twisted(tm.make_field((0, 0, 0), (0, 0, 1), 90.0 + angle, -40, 40))
        self.assertLess((time.perf_counter() - start) / 20, .05)            # jedna aktualizacja podglądu < 50 ms


class GeometryAndTimingTests(unittest.TestCase):
    def test_brep_time_and_validity(self):
        cases = [(k.box(20, 30, 80), 90.0, 5.0), (W().polygon(6, 30).extrude(60).faces('>Z').workplane().hole(8).val(), 720.0, 15.0),
                 (big_plate(), 90.0, 90.0)]
        for shape, angle, limit in cases:
            field = tw.field(Z, shape, angle)
            start = time.perf_counter()
            result = to.twist_solid(shape, field)
            self.assertLess(time.perf_counter() - start, limit)
            report = to.check(result, shape, field)
            self.assertTrue(report['ok'] and report['self'] and report['closed'] and report['forward'], report)

    def test_self_intersection_rejected_and_original_kept(self):
        thin = W().box(20, 30, 80).faces('>Z').workplane().pushPoints([(0, 12.5)]).hole(5).val()    # otwór dotyka ścianki
        volume = thin.Volume()
        with self.assertRaises(to.TwistError) as err:
            to.twist_solid(thin, tw.field(Z, thin, 90.0))
        self.assertIn('przecina samą siebie', str(err.exception))
        self.assertEqual(thin.Volume(), volume)
        ok = W().box(20, 30, 80).faces('>Z').workplane().pushPoints([(0, 12.0)]).hole(5).val()
        self.assertTrue(to.check(to.twist_solid(ok, tw.field(Z, ok, 90.0)), ok, tw.field(Z, ok, 90.0))['ok'])

    def test_booleans_and_step_after_repeated_twist(self):
        a = Body('A', W().box(20, 30, 80).faces('>Z').workplane().hole(6, 30).val()).prepared()
        r = dict(type='twist', id=a.id, angle=70.0, axis=Z)
        twisted = hist.run_twist([hist.run_twist([a], r)[0]], dict(r, angle=50.0, kind='smoothstep'))[0].shape
        tool = k.box(10, 10, 200).translate(cq.Vector(5, 5, -50))
        for op in ('subtract', 'union', 'intersect'):
            out = k.boolean(op, twisted, [tool])
            self.assertTrue(k.is_valid(out) and out.Volume() > 0, op)
        path = Path(tempfile.mkdtemp()) / 'twist2.step'
        k.export_shapes([twisted], path)
        shape, kind = k.import_shapes(path)[0]
        self.assertEqual(kind, 'solid')
        self.assertAlmostEqual(shape.Volume(), twisted.Volume(), delta=1e-6 * twisted.Volume())


if __name__ == '__main__':
    unittest.main()
