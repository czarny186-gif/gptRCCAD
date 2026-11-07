"""Gwinty kosmetyczne: normy, dopasowanie, otwór / wałek, krok historii, zapis, kopie."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('RCCAD_WORKERS', '0')

import cadquery as cq
import numpy as np

from rccad import history as hist, kernel as k, threads as th
from rccad.document import Body, Document


def plate(hole=8.0):
    return cq.Workplane().box(40, 40, 10).faces('>Z').workplane().hole(hole).val()


def cyl_index(shape):
    return next(i for i, f in enumerate(shape.Faces()) if f.geomType() == 'CYLINDER')


class ThreadCoreTests(unittest.TestCase):
    def test_tables_fit_and_cylinder_detection(self):
        self.assertEqual(th.size('M', 'M10'), ('M10', 10, 1.5))
        self.assertAlmostEqual(th.drill('M', 10, 1.5), 8.5)
        self.assertEqual(th.fit('M', 8.5, True), ('M10', True))           # otwór pod M10
        self.assertEqual(th.fit('M', 12, False), ('M12', True))           # wałek M12
        self.assertEqual(th.fit('M', 8.2, True)[1], False)                # nie pasuje dokładnie -> otwór do dopasowania
        self.assertAlmostEqual(th.size('UNC', '1/4"-20')[1], 6.35, 3)
        for key in ('M', 'MF', 'UNC', 'UNF', 'G', 'Tr'):
            self.assertTrue(th.STANDARDS[key]['sizes'])
        hole = th.cylinder_info(plate(), cyl_index(plate()))
        self.assertTrue(hole['internal'] and hole['full'])
        self.assertAlmostEqual(hole['t1'] - hole['t0'], 10, 6)
        shaft = cq.Workplane().cylinder(30, 6).val()
        self.assertFalse(th.cylinder_info(shaft, cyl_index(shaft))['internal'])

    def test_lines_are_light_even_for_long_threads(self):
        info = th.cylinder_info(plate(), cyl_index(plate()))
        thread = th.make_thread(info, 'M', 'M10', 'right', info['t0'], info['t1'])
        lines = th.thread_lines(thread)
        self.assertEqual(lines.shape[1:], (2, 3))
        r = np.linalg.norm(lines[:20, 0, :2], axis=1)
        self.assertTrue(np.allclose(r, 4.25 * .996, atol=1e-3))           # na średnicy wiertła (otwór)
        long = dict(thread, start=0, end=3000)                             # 2000 zwojów
        t = time.perf_counter()
        segs = th.thread_lines(long)
        self.assertLess(time.perf_counter() - t, .05)
        self.assertLess(len(segs), 4000)                                   # rysowanie ograniczone, nie geometria
        left = th.thread_lines(dict(thread, hand='left'))
        self.assertFalse(np.allclose(left, lines))

    def test_history_step_adjusts_hole_and_persists(self):
        body = Body('Płyta', plate(8.0)).prepared()
        info = th.cylinder_info(body.shape, cyl_index(body.shape))
        recipe = dict(type='thread', id=body.id, cylinder=dict(origin=info['origin'], axis=info['axis'], radius=info['radius'], internal=True),
                      spec=dict(standard='M', size='M10', hand='right', start=info['t0'], end=info['t1']), adjust=True)
        out = hist.run_recipe([body], recipe)
        new = out[0]
        self.assertEqual(len(new.threads), 1)
        self.assertEqual(new.threads[0]['size'], 'M10')
        self.assertAlmostEqual(th.cylinders(new.shape)[0]['radius'], 4.25, 4)          # rozwiercony do Ø8.5
        self.assertLess(len(new.shape.Faces()), 12)                                  # bez geometrii zwojów
        moved = hist.run_recipe(out, dict(type='transform', id=body.id, mode='move', v=[100, 0, 0]))
        self.assertAlmostEqual(moved[0].threads[0]['origin'][0], 100, 6)             # gwint idzie z bryłą
        copies = hist.run_pattern(out, dict(type='pattern', id=body.id, kind='rect', params=dict(counts=[2, 1, 1], spacing=[50, 0, 0]), join=False, out=[]))
        bb = copies[1].shape.BoundingBox()
        self.assertAlmostEqual(copies[1].threads[0]['origin'][0], (bb.xmin + bb.xmax) / 2, 6)   # kopia szyku ma gwint w swoim otworze
        mirrored = hist.run_mirror(out, dict(type='mirror', id=body.id, normal=[1, 0, 0], origin=[30, 0, 0], keep=True))
        self.assertEqual(mirrored[-1].threads[0]['hand'], 'left')                    # odbicie: gwint lewy
        doc = Document()
        doc.commit(out)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'g.rccadx'
            doc.save(path)
            again = Document.load(path)
        self.assertEqual(again.bodies[0].threads[0]['size'], 'M10')


if __name__ == '__main__':
    unittest.main()
