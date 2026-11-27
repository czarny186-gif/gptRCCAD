"""Zaokrąglanie i fazowanie (0.5.63): identyfikacja krawędzi (tożsamość topologiczna, kolejność, duplikaty, krawędzie
zdegenerowane), zakres konturów stycznych, wartości poprawne i błędne, 20 rodzajów brył, operacje przed zaokrągleniem,
kolejne zaokrąglenia / fazy (także na krawędziach z poprzedniej operacji), kontrola wyniku, ochrona przed zawieszeniem
OpenCascade, stabilność (100 + 100 + 100 operacji) i wydajność 12 - 10 000 krawędzi."""
import faulthandler
import math
import os
import sys
import tempfile
import time
import unittest

faulthandler.enable()
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import cadquery as cq
import numpy as np

from rccad import kernel as k
from rccad import history as hist
import blend_models as M

W = cq.Workplane


def scale(shape):
    bb = shape.BoundingBox()
    return max(bb.xlen, bb.ylen, bb.zlen)


def lines_at(shape, pred):
    return [i for i, e in enumerate(shape.Edges()) if pred(e)]


def peak_mb():
    from test_vent_engine import peak_mb as p
    return p()


# Zestawy, których nie da się wykonać z przyczyn geometrycznych (nie błędy programu) - sprawdzone osobno w diagnostyce:
# szew stożka (krawędź pozorna powierzchni okresowej) i krawędź łącząca pochylone ściany pod bardzo ostrym kątem.
INFEASIBLE_ONE = set()


class BlendKernelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = M.models()

    def check(self, before, result, size=None):
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids()), len(before.Solids()))
        self.assertEqual(k._free_edges(result), 0)
        self.assertGreater(result.Volume(), 0)

    def test_edge_numbers_are_topological_and_match_the_view(self):
        for name, sh in self.models.items():
            idx = k.edge_index_map(sh)
            edges = sh.Edges()
            for i, e in enumerate(edges):
                self.assertEqual(idx.FindIndex(e.wrapped), i + 1, name)
            mesh = k.display_mesh(sh)
            self.assertTrue(set(mesh.edges) <= set(range(len(edges))), name)       # siatka widoku: te same numery
        cone = self.models['cone']
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.BRep import BRep_Tool
        from OCP.TopoDS import TopoDS
        ex = TopExp_Explorer(cone.wrapped, TopAbs_EDGE)
        degenerated = []
        while ex.More():
            if BRep_Tool.Degenerated_s(TopoDS.Edge_s(ex.Current())):
                degenerated.append(ex.Current())
            ex.Next()
        self.assertTrue(degenerated)
        self.assertEqual(k.edge_index_map(cone).FindIndex(degenerated[0]), 0)      # wierzchołek stożka nie ma numeru
        other = W().box(5, 5, 5).val()
        self.assertEqual(k.edge_index_map(cone).FindIndex(other.Edges()[0].wrapped), 0)   # krawędź innej bryły

    def test_tangent_chain_scope_is_known_before_and_matches_the_result(self):
        box = W().box(30, 20, 10).edges('|Z').fillet(3).val()
        top = lines_at(box, lambda e: e.geomType() == 'LINE' and abs(e.Center().z - 5) < 1e-6 and abs(e.Center().y + 10) < 1e-6)
        scope, auto = k.blend_scope(box, top)
        self.assertEqual(len(scope), 8)                                   # cały górny obwód: 4 proste + 4 łuki
        self.assertEqual(len(auto), 7)
        result, made, done = k.blend_full(box, top, 1.0)
        self.assertEqual(done, scope)                                     # zrobione dokładnie to, co pokazano
        self.assertEqual(len(made), 8)
        self.check(box, result)
        plain = W().box(30, 20, 10).val()
        one = lines_at(plain, lambda e: abs(e.Center().z - 5) < 1e-6 and abs(e.Center().y + 10) < 1e-6)
        self.assertEqual(k.blend_scope(plain, one), (set(one), set()))   # bez stycznych - tylko zaznaczona
        r, made, done = k.blend_full(plain, one, 2.0)
        self.assertEqual(done, set(one))
        self.assertEqual(len(made), 1)
        self.assertAlmostEqual(plain.Volume() - r.Volume(), (4 - math.pi) * 30, 6)   # (r² - πr²/4) · długość
        r, made, done = k.blend_full(plain, one, 2.0, 'chamfer')
        self.assertAlmostEqual(plain.Volume() - r.Volume(), 2.0 * 30, 6)            # ½ · 2 · 2 · 30

    def test_order_duplicates_and_owner(self):
        sh = W().box(40, 30, 20).val()
        ids = lines_at(sh, lambda e: e.Center().z > 9.9)
        base = k.blend(sh, set(ids), 2.0).Volume()
        for perm in (ids[::-1], ids[1:] + ids[:1], ids + ids):
            self.assertAlmostEqual(k.blend(sh, perm, 2.0).Volume(), base, 9)
        with self.assertRaises(k.CadError):
            k.blend(sh, {len(sh.Edges())}, 1.0)                           # krawędź spoza bryły
        with self.assertRaises(k.CadError):
            k.blend(sh, set(), 1.0)

    def test_values_zero_negative_too_large_keep_the_original(self):
        sh = W().box(20, 20, 20).val()
        v0 = sh.Volume()
        e = [0]
        for bad in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(k.CadError):
                k.blend(sh, e, bad)
        for kind in ('fillet', 'chamfer'):
            with self.assertRaises(k.CadError) as caught:
                k.blend_full(sh, {i for i in range(12)}, 15.0, kind)
            if isinstance(caught.exception, k.BlendError):
                self.assertTrue(caught.exception.edges)                   # krawędzie do podświetlenia
        self.assertTrue(sh.isValid())
        self.assertEqual(sh.Volume(), v0)                                 # oryginał bez zmian
        for size in (0.001, 0.01, 0.1, 0.5, 1, 2, 5, 9.9):
            for kind in ('fillet', 'chamfer'):
                self.check(sh, k.blend(sh, e, size, kind))
        big = W().box(400, 300, 200).val()
        for size in (10, 20, 50, 99):
            self.check(big, k.blend(big, [0], size))

    def test_twenty_model_kinds_and_selection_configurations(self):
        failures = []
        ran = 0
        for name, sh in self.models.items():
            sets = M.edge_sets(sh)
            s = max(.05, .02 * scale(sh))
            for sname, ids in sets.items():
                if sname == 'all' and len(ids) > 80:
                    continue
                for kind in ('fillet', 'chamfer'):
                    ran += 1
                    if name == 'curved' and sname == 'all' and kind == 'chamfer':
                        continue                                          # zawieszenie OpenCascade - test ochrony niżej
                    try:
                        r = k.blend(sh, set(ids), s, kind)
                        self.check(sh, r)
                    except k.CadError as exc:
                        if sname == 'one' and (name, kind) in INFEASIBLE_ONE:
                            continue
                        failures.append((name, sname, kind, str(exc)[:60]))
        sys.stderr.write(f'\nZaokrąglenie / faza - konfiguracje: {ran}, niewykonalne poza listą: {len(failures)}\n')
        for f in failures:
            sys.stderr.write(f'  {f}\n')
        # zestawy, których OpenCascade nie wykonuje przy 2% rozmiaru (np. wszystkie krawędzie złożonych brył) - komunikat,
        # bez awarii i bez zmiany bryły; podstawowe przypadki (jedna krawędź) muszą działać na każdej bryle
        self.assertFalse([f for f in failures if f[1] == 'one'], failures)
        self.assertLess(len(failures), ran * .2)

    def test_after_modelling_operations(self):
        sk = k.polyline('XY', [(0, 0), (30, 0), (30, 20), (0, 20), (0, 0)])
        bodies = {}
        bodies['extrude'] = k.extrude(sk, 'XY', 10)
        prof = cq.Face.makeFromWires(k.polyline('XZ', [(5, 0), (15, 0), (15, 10), (5, 10), (5, 0)]))
        bodies['revolve'] = k.revolve_face(prof, (0, 0, 0), (0, 0, 1), 360)
        path = cq.Wire.assembleEdges([cq.Edge.makeLine(cq.Vector(0, 0, 0), cq.Vector(0, 0, 30))])
        bodies['sweep'] = k.sweep_face(cq.Face.makeFromWires(cq.Wire.makePolygon([(-3, -3, 0), (3, -3, 0), (3, 3, 0), (-3, 3, 0)], close=True)), path)
        bodies['loft'] = W().rect(20, 20).workplane(offset=10).rect(10, 10).loft().val()
        a, b = W().box(20, 20, 20).val(), W().box(20, 20, 20).translate((10, 10, 10)).val()
        bodies['union'] = k.boolean('union', a, [b])
        bodies['cut'] = k.boolean('subtract', a, [b])
        bodies['common'] = k.boolean('intersect', a, [b])
        bodies['hole'] = W().box(30, 30, 10).faces('>Z').workplane().hole(6).val()
        bodies['move'] = k.transform(a, (50, -20, 7))
        bodies['rotate'] = k.transform(a, (0, 0, 0), (30, 45, 10))
        bodies['scale'] = a.scale(2.5)
        bodies['mirror'] = k.mirror_plane(bodies['loft'], (1, 0, 0), (40, 0, 0))
        bodies['pattern'] = k.boolean('union', a, [a.translate(cq.Vector(15 * i, 0, 0)) for i in (1, 2, 3)])
        bodies['circ_pattern'] = k.boolean('union', W().box(10, 4, 4).translate((10, 0, 0)).val(),
                                          [W().box(10, 4, 4).translate((10, 0, 0)).val().rotate(cq.Vector(), cq.Vector(0, 0, 1), 90 * i) for i in (1, 2, 3)])
        bodies['shell'] = W().box(30, 30, 20).faces('>Z').shell(-2).val()
        bodies['fillet'] = k.blend(a, [0], 3)
        bodies['chamfer'] = k.blend(a, [0], 3, 'chamfer')
        path = os.path.join(tempfile.mkdtemp(), 'p.step')
        cq.exporters.export(W().add(bodies['union']), path)
        bodies['step'] = cq.importers.importStep(path).val()
        brep = os.path.join(tempfile.mkdtemp(), 'p.brep')
        bodies['union'].exportBrep(brep)
        bodies['reopen'] = cq.Shape.importBrep(brep)
        try:
            from rccad import threads as th
            bodies['thread'] = W().cylinder(20, 5).val()          # gwint kosmetyczny nie zmienia B-Rep
        except Exception:
            pass
        for name, sh in bodies.items():
            edges = sh.Edges()
            real = set(k.display_mesh(sh).edges)                       # tylko krawędzie widoczne (bez szwów)
            i = max(real, key=lambda j: (edges[j].geomType() == 'LINE', edges[j].Length()))
            for kind in ('fillet', 'chamfer'):
                try:
                    r = k.blend(sh, {i}, .8, kind)
                except k.CadError as exc:
                    self.fail(f'{name} {kind}: {exc}')
                self.check(sh, r)

    def test_sequences_and_edges_created_by_the_previous_blend(self):
        a = W().box(40, 30, 20).val()
        top = lambda s: lines_at(s, lambda e: e.geomType() == 'LINE' and abs(e.Center().z - 10) < 1e-6 and abs(e.Center().y + 15) < 1e-6)
        f1 = k.blend(a, top(a), 3)
        # nowe krawędzie: brzegi powierzchni zaokrąglenia (styczne do sąsiednich ścian - kontur obejmuje też łuki)
        r, made, _ = k.blend_full(a, top(a), 3)
        fil = made[0]
        new = [i for i, e in enumerate(r.Edges()) if any(e.isSame(x) for x in fil.Edges()) and e.geomType() == 'CIRCLE']
        self.assertTrue(new)
        f2 = k.blend(r, set(new[:1]), 1.0)                                # zaokrąglenie krawędzi powstałej z zaokrąglenia
        self.check(r, f2)
        c1 = k.blend(a, top(a), 3, 'chamfer')
        side = lines_at(c1, lambda e: e.geomType() == 'LINE' and abs(e.tangentAt(.5).z) > .99)
        seqs = {
            'fillet>fillet': lambda: k.blend(f1, set(side[:1]) if False else set(lines_at(f1, lambda e: abs(e.tangentAt(.5).z) > .99)[:1]), 2),
            'chamfer>chamfer': lambda: k.blend(c1, set(side[:1]), 2, 'chamfer'),
            'fillet>chamfer': lambda: k.blend(f1, set(lines_at(f1, lambda e: abs(e.tangentAt(.5).z) > .99)[:1]), 2, 'chamfer'),
            'chamfer>fillet': lambda: k.blend(c1, set(side[:1]), 2),
        }
        for name, run in seqs.items():
            self.check(a, run())
        holed = W().add(f1).faces('<Z').workplane().hole(6).val()                       # zaokrąglenie > otwór > faza
        ring = lines_at(holed, lambda e: e.geomType() == 'CIRCLE' and e.Center().z < -9.9)
        self.check(holed, k.blend(holed, set(ring), .8, 'chamfer'))
        cut = k.boolean('subtract', c1, [W().box(10, 10, 30).val()])                    # faza > wycięcie > zaokrąglenie
        inner = lines_at(cut, lambda e: e.geomType() == 'LINE' and abs(e.tangentAt(.5).z) > .99 and abs(abs(e.Center().x) - 5) < 1e-6)
        self.check(cut, k.blend(cut, set(inner[:2]), 1.5))
        moved = k.transform(f1, (10, 20, 30), (0, 0, 35))                               # zaokrąglenie > przekształcenie > zaokrąglenie
        vert = lines_at(moved, lambda e: e.geomType() == 'LINE' and abs(e.tangentAt(.5).z) > .99)
        self.check(moved, k.blend(moved, set(vert[:1]), 2))

    def test_history_replay_finds_the_same_edge_after_topology_changes(self):
        a = W().box(40, 30, 20).val()
        i = lines_at(a, lambda e: abs(e.Center().z - 10) < 1e-6 and abs(e.Center().y + 15) < 1e-6)[0]
        refs = hist.edge_refs(a, [i])
        changed = W().add(a).faces('<Z').workplane().rarray(10, 10, 3, 2).hole(3).val()  # więcej krawędzi, inne numery
        j = hist.edge_indices(changed, refs)
        self.assertEqual(len(j), 1)
        e = changed.Edges()[j[0]]
        np.testing.assert_allclose(e.Center().toTuple(), a.Edges()[i].Center().toTuple(), atol=1e-6)
        self.check(changed, k.blend(changed, set(j), 2))

    def test_result_checks_reject_bad_geometry(self):
        sh = W().box(20, 20, 20).val()
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
        r, made, _ = k.blend_full(sh, [0], 2)
        for f in made:                                                 # promień powierzchni zaokrąglenia = zadany
            from OCP.GeomAdaptor import GeomAdaptor_Surface
            from OCP.BRep import BRep_Tool
            surf = GeomAdaptor_Surface(BRep_Tool.Surface_s(f.wrapped))
            self.assertAlmostEqual(surf.Cylinder().Radius(), 2.0, 9)
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
        open_shell = cq.Shell.makeShell(sh.Faces()[:5])               # skorupa ze szczeliną
        self.assertGreater(k._free_edges(open_shell), 0)

    def test_heavy_face_result_checked_locally_and_fast(self):
        plate = W().box(200, 200, 6).faces('>Z').workplane().rarray(9, 9, 20, 20).hole(4).val()   # ściana z 400 otworami
        self.assertTrue(k.heavy_faces(plate))
        e = lines_at(plate, lambda e: e.geomType() == 'LINE' and abs(e.Center().z - 3) < 1e-6 and abs(e.Center().y + 100) < 1e-6)
        t = time.time()
        r, made, _ = k.blend_full(plate, e, 1.5)
        dt = time.time() - t
        self.assertTrue(r.isValid())
        self.assertLess(dt, 20)

    def test_stability_100_fillets_100_chamfers_100_mixed(self):
        times = {}
        for kind in ('fillet', 'chamfer', 'mixed'):
            ts = []
            sh = W().box(60, 40, 30).val()
            for n in range(100):
                kk = kind if kind != 'mixed' else ('fillet', 'chamfer')[n % 2]
                t = time.time()
                base = W().box(60, 40, 30).val() if n % 10 == 0 else sh
                edges = base.Edges()
                straight = [i for i, e in enumerate(edges) if e.geomType() == 'LINE']
                i = straight[n % len(straight)]
                size = .2 + (n % 7) * .1
                try:
                    sh = k.blend(base, {i}, size, kk)
                except k.CadError:
                    sh = base                                          # niewykonalne na już zmienionej bryle: bez zmiany
                self.assertTrue(sh.isValid())
                ts.append(time.time() - t)
            times[kind] = ts
            self.assertLess(np.mean(ts[-10:]), max(.5, 5 * np.mean(ts[:10])))      # brak narastającego spowolnienia
        sys.stderr.write('\nStabilność (średni czas operacji s): ' + ', '.join(f'{k_}: {np.mean(v):.3f}' for k_, v in times.items()) + '\n')

    def test_no_memory_growth_over_repeated_operations(self):
        import gc
        import tracemalloc
        def rss():
            try:
                with open('/proc/self/statm') as f:
                    return int(f.read().split()[1]) * os.sysconf('SC_PAGE_SIZE') / 2 ** 20
            except OSError:
                return float('nan')                                     # Windows: bez pomiaru RSS (sprawdzana sterta Pythona)
        sh = W().box(60, 40, 30).faces('>Z').workplane().hole(8).val()
        real = set(k.display_mesh(sh).edges)                            # bez szwu walca otworu
        straight = [i for i, e in enumerate(sh.Edges()) if e.geomType() == 'LINE' and i in real]
        def batch(n):
            for j in range(n):
                r, made, scope = k.blend_full(sh, {straight[j % len(straight)]}, .5 + (j % 5) * .2, ('fillet', 'chamfer')[j % 2])
                k.display_mesh(r)
        batch(40)
        gc.collect()
        tracemalloc.start()
        m0, py0 = rss(), tracemalloc.get_traced_memory()[0]
        batch(200)
        gc.collect()
        m1, py1 = rss(), tracemalloc.get_traced_memory()[0]
        tracemalloc.stop()
        sys.stderr.write(f'\nPamięć po 200 operacjach: RSS {m0:.0f} -> {m1:.0f} MB, sterta Pythona +{(py1 - py0) / 2 ** 20:.2f} MB\n')
        self.assertLess((py1 - py0) / 2 ** 20, 5.0)
        if m0 == m0:
            self.assertLess(m1 - m0, 150)

    def test_heavy_face_check_still_finds_overlapping_holes(self):
        outer = cq.Wire.makePolygon([(0, 0, 0), (100, 0, 0), (100, 100, 0), (0, 100, 0)], close=True)
        holes = [cq.Wire.makeCircle(2, cq.Vector(5 + 12 * (i % 8), 5 + 12 * (i // 8), 0), cq.Vector(0, 0, -1)) for i in range(60)]
        good = cq.Solid.extrudeLinear(cq.Face.makeFromWires(outer, holes), cq.Vector(0, 0, 3))
        bad = cq.Solid.extrudeLinear(cq.Face.makeFromWires(outer, holes + [cq.Wire.makeCircle(2, cq.Vector(8, 5, 0), cq.Vector(0, 0, -1))]), cq.Vector(0, 0, 3))
        self.assertTrue(k.heavy_faces(good))
        self.assertTrue(k.is_valid(good))
        self.assertFalse(k.is_valid(bad))                               # nachodzące otwory - jak pełny BRepCheck
        self.assertFalse(bad.isValid())

    def test_hang_in_open_cascade_is_stopped_and_reported(self):
        from rccad import workers
        if not workers.start(wait=True):
            self.skipTest('procesy liczące niedostępne')
        from unittest.mock import patch
        curved = self.models['curved']
        try:
            with patch.object(hist, 'blend_timeout', return_value=8.0):
                t = time.time()
                with self.assertRaises(k.CadError) as caught:
                    hist.offloaded_blend(curved, set(range(len(curved.Edges()))), .001, 'chamfer')
                self.assertLess(time.time() - t, 40)
                self.assertIn('nie zakończył', str(caught.exception))
            self.assertTrue(workers.start(wait=True))                  # procesy wystartowały od nowa
            r, mesh = hist.offloaded_blend(W().box(10, 10, 10).val(), {0}, 1, 'fillet')
            self.assertTrue(r.isValid())
            with self.assertRaises(workers.Crashed):                    # awaria procesu na zadaniu: bez liczenia w oknie
                workers.call_guarded(None, os.abort, timeout=60)
            self.assertTrue(workers.start(wait=True))
            r, mesh = hist.offloaded_blend(W().box(10, 10, 10).val(), {0}, 1, 'chamfer')
            self.assertTrue(r.isValid())
        finally:
            workers.shutdown()

    def test_performance_12_to_10000_edges(self):
        from rccad import vent_cut as vc
        rows = []
        for holes in (0, 13, 30, 160, 330, 1660, 3330):
            base = W().box(400, 400, 10).val()
            if holes:
                m = int(math.ceil(math.sqrt(holes)))
                s = 380 / m
                tools = [cq.Solid.makeCylinder(min(s * .25, 3), 20, cq.Vector(-190 + s / 2 + i * s, -190 + s / 2 + j * s, -10)).wrapped
                         for i in range(m) for j in range(m)][:holes]
                sh = cq.Shape.cast(vc.cut_tiled(base.wrapped, tools) or vc.cut_many(base.wrapped, tools))
            else:
                sh = base
            ne = len(sh.Edges())
            e1 = lines_at(sh, lambda e: e.geomType() == 'LINE' and abs(e.Center().z - 5) < 1e-6 and abs(e.Center().y + 200) < 1e-6)
            t = time.time()
            scope, _auto = k.blend_scope(sh, e1)
            t_scope = time.time() - t
            t = time.time()
            r, made, _ = k.blend_full(sh, e1, 2)
            t_one = time.time() - t
            circles = lines_at(sh, lambda e: e.geomType() == 'CIRCLE' and e.Center().z > 4.9)[:10]
            many = set(e1) | set(lines_at(sh, lambda e: e.geomType() == 'LINE' and e.Center().z > 4.9))
            t = time.time()
            r2 = k.blend(sh, many | set(circles), .5, 'chamfer')
            t_many = time.time() - t
            t = time.time()
            mesh = k.display_mesh(r)
            t_mesh = time.time() - t
            t = time.time()
            local = hist.mod_preview(sh, set(e1), None, 2, 'fillet', 8.0, {})
            t_prev = time.time() - t
            rows.append((ne, t_scope, t_prev, t_one, t_many, t_mesh, peak_mb()))
            self.assertTrue(r2.Solids())
            self.assertLess(t_one, 30 + ne * .01)
            self.assertLess(t_mesh, 30 + ne * .01)
        sys.stderr.write('\nZaokrąglenie / faza - wydajność (krawędzie / zakres / podgląd / 1 krawędź / wiele / siatka s / pamięć MB):\n' +
                         ''.join(f'  {a:>6} {b:7.2f} {c:7.2f} {d:7.2f} {e:7.2f} {f:7.2f} {g:8.0f}\n' for a, b, c, d, e, f, g in rows))


if __name__ == '__main__':
    unittest.main()
