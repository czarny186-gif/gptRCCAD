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


if __name__ == '__main__':
    unittest.main()
