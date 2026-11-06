"""Procesy liczące: siatki i sprawdzanie brył w osobnych procesach, a przeliczanie historii bez siatek stanów pośrednich."""
import os, tempfile, unittest
from unittest.mock import patch
import cadquery as cq
from rccad import kernel as k, history as hist, workers
from rccad.document import Body, Document


def plate(i):
    return k.hole(k.box(30, 30, 4), 3, 15, 15).translate((i * 40, 0, 0))


class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = patch.dict(os.environ, {'RCCAD_WORKERS': '2'})
        cls.env.start()
        workers.start(wait=True)

    @classmethod
    def tearDownClass(cls):
        workers.shutdown()
        cls.env.stop()

    def test_pool_meshes_like_the_main_process(self):
        self.assertTrue(workers.ready())
        self.assertEqual(workers.size(), 2)
        shapes = [plate(i) for i in range(3)]
        remote = workers.mesh_many([(s, True) for s in shapes])
        for shape, (mesh, error) in zip(shapes, remote):
            self.assertIsNone(error)
            local = k.display_mesh(shape)
            self.assertEqual(len(mesh.triangles), len(local.triangles))
            self.assertEqual(sorted(mesh.edges), sorted(local.edges))
        face = cq.Face.makePlane(10, 10)
        (_, ok), (none, error) = workers.mesh_many([(shapes[0], True), (face, True)])
        self.assertIsNone(ok)
        self.assertIsNone(none)
        self.assertIn('zamkniętej bryły', error)          # komunikat błędu wraca z procesu liczącego

    def test_document_meshes_many_bodies_in_parallel_on_open(self):
        d = Document()
        d.commit([Body(f'P{i}', plate(i)).prepared() for i in range(4)])
        path = os.path.join(tempfile.mkdtemp(), 'p.rccadx')
        d.save(path)
        with patch.object(workers, 'mesh_many', wraps=workers.mesh_many) as spy:
            loaded = Document.load(path)
        self.assertEqual(len(spy.call_args[0][0]), 4)            # cztery bryły jednym wywołaniem (procesy)
        self.assertTrue(all(b.mesh is not None and len(b.mesh.triangles) for b in loaded.bodies))

    def test_history_rebuild_meshes_only_shown_state(self):
        with k.deferred_mesh():
            self.assertIsNone(Body('A', k.box(1, 1, 1)).prepared().mesh)
        self.assertIsNotNone(Body('A', k.box(1, 1, 1)).prepared().mesh)
        d = Document()
        a = Body('A', k.box(10, 10, 10)).prepared()
        d.commit([a])
        for dx in (5, 7, 9):
            recipe = dict(type='transform', id=a.id, mode='move', v=[float(dx), 0.0, 0.0])
            d.commit(hist.run_recipe(d.bodies, recipe), label='Przekształcenie', op=recipe)
        states = d.states()
        edited = [Body('A', k.box(12, 10, 10), id=a.id).prepared()]
        new, failed = hist.recompute(states, 1, edited)
        self.assertEqual(failed, 0)
        self.assertTrue(all(b.mesh is None for b in new[-1][0]))          # bez siatek w trakcie przeliczania
        shown = d.meshed(new[-1][0])
        self.assertTrue(all(b.mesh is not None for b in shown))
        self.assertAlmostEqual(shown[0].shape.Volume(), 1200, 6)

    def test_sheet_corners_trimmed_in_processes_match_local(self):
        from rccad import sheetmetal as shm
        t = 1.0
        base = dict(o=[0, 0, 0], x=[1, 0, 0], y=[0, 1, 0], z=[0, 0, 1], lx=60, ly=40, lz=t)
        edges = [([60, 0, t], [60, 40, t], [1, 0, 0]), ([60, 40, t], [0, 40, t], [0, 1, 0]), ([0, 40, t], [0, 0, t], [-1, 0, 0]), ([0, 0, t], [60, 0, t], [0, -1, 0])]
        flanges = [dict(kind='base', p0=a, p1=b, n=[0, 0, 1], m=m, r=1, angle=90, length=10) for a, b, m in edges]
        flanges += [dict(kind='tip', parent=i, side='in', r=1, angle=90, length=4) for i in range(4)]

        def clear():
            for cache in (shm._BUILD_CACHE, shm._PARTS_CACHE, shm._OPS_CACHE):
                cache.clear()
            for order in (shm._BUILD_ORDER, shm._PARTS_ORDER, shm._OPS_ORDER):
                order.clear()
        for joint in ('parallel', 'sheet'):
            recipe = dict(base=base, t=t, flanges=flanges, rules=dict(gap=.1, relief='none', relief_size=3, joint=joint, miter=True, auto_corners=True, kfactor=.44))
            clear()
            with patch.object(workers, 'ready', return_value=False):
                local = shm.build_sheet(recipe)
            clear()
            with patch.object(workers, 'run_affine', wraps=workers.run_affine) as spy:
                remote = shm.build_sheet(recipe)
            self.assertTrue(spy.call_count >= 2, joint)                   # dwa poziomy kołnierzy, każdy w procesach
            self.assertLess(local.cut(remote).Volume() + remote.cut(local).Volume(), 1e-6, joint)
            self.assertEqual(len(remote.Solids()), 1)

    def test_fast_triangles_match_reference_and_coarse_mesh_is_refined(self):
        import numpy as np
        make = lambda: cq.Workplane().box(60, 60, 5).faces('>Z').workplane().rarray(8, 8, 6, 6).hole(3).edges('|Z').fillet(.4).val()
        big = make()
        self.assertTrue(k.heavy(big))
        fine = k.display_mesh(big)
        vertices, triangles = big.tessellate(.12, k.FINE_ANGLE)
        self.assertEqual(len(fine.triangles), len(triangles))
        tri = fine.vertices[fine.triangles]
        ref = np.array([v.toTuple() for v in vertices])[np.array(triangles)]
        signed = lambda p: float(np.einsum('ij,ij->i', p[:, 0], np.cross(p[:, 1], p[:, 2])).sum() / 6)
        self.assertAlmostEqual(signed(tri), signed(ref), 2)                  # te same trójkąty, ta sama orientacja ścian
        big = make()                                                           # świeży kształt bez siatki
        body = Body('P', big).prepared()
        self.assertFalse(body.mesh.fine)                                       # duża bryła: najpierw zgrubna siatka
        self.assertLess(len(body.mesh.triangles), len(fine.triangles))
        (refined,) = workers.fine_meshes([big])
        self.assertTrue(refined.fine)
        self.assertEqual(sorted(refined.edges), sorted(body.mesh.edges))       # krawędzie do wskazywania bez zmian
        self.assertEqual(len(refined.triangles), len(fine.triangles))

    def test_sheet_operations_run_in_the_sheet_process_and_match_local(self):
        import pickle
        from rccad import sheetedit as she
        t = 1.0
        base = dict(o=[0, 0, 0], x=[1, 0, 0], y=[0, 1, 0], z=[0, 0, 1], lx=60, ly=40, lz=t)
        rules = dict(gap=.1, relief='none', relief_size=3, joint='sheet', miter=True, auto_corners=True, kfactor=.44)
        plate = Body('Blacha', k.box(60, 40, t), meta={'sheet': she.state(dict(base=base, t=t, flanges=[], rules=rules))}).prepared()
        flanges = [dict(kind='base', p0=[60, 0, t], p1=[60, 40, t], n=[0, 0, 1], m=[1, 0, 0], r=1, angle=90, length=10),
                   dict(kind='base', p0=[60, 40, t], p1=[0, 40, t], n=[0, 0, 1], m=[0, 1, 0], r=1, angle=90, length=10)]
        recipe = dict(type='sheetbuild', id=plate.id, base=base, t=t, flanges=flanges, rules=rules)
        with patch.object(workers, 'call_affine', wraps=workers.call_affine) as spy:
            remote = hist.run_recipe([plate], recipe)[0]
        self.assertEqual(spy.call_args[0][0], ('sheet', plate.id))                 # proces tej blachy
        self.assertTrue(remote.mesh is not None and remote.mesh.fine)             # siatka policzona w procesie
        with patch.object(workers, 'ready', return_value=False):
            local = hist.run_recipe([plate], recipe)[0]
        self.assertLess(remote.shape.cut(local.shape).Volume() + local.shape.cut(remote.shape).Volume(), 1e-6)
        self.assertEqual(remote.meta['sheet']['recipe'], local.meta['sheet']['recipe'])
        flat = hist.run_recipe([remote], dict(type='sheetmode', id=plate.id, state=remote.meta['sheet'], flat=True, sync=False))[0]
        self.assertTrue(flat.meta['sheet']['flat'])
        again = pickle.loads(pickle.dumps(flat.shape))                             # przesyłanie kształtów blachy (BREP)
        self.assertAlmostEqual(again.Volume(), flat.shape.Volume(), 6)
        self.assertEqual(len(again.Edges()), len(flat.shape.Edges()))


if __name__ == '__main__':
    unittest.main()
