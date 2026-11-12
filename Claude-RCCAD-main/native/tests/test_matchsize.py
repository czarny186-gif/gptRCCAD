"""Wyrównaj rozmiar (zakładka Szkic): takie same kształty przyjmują wymiary wzorca na żywo; Zastosuj / Zamknij."""
import os
os.environ.setdefault('RCCAD_HISTORY_HOLD', '0')      # starsze testy: zmiany w historii przeliczane od razu (bez „Zatwierdź zmianę”)
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen' if not os.environ.get('DISPLAY') and os.name != 'nt' else '')
os.environ['RCCAD_CONFIG_DIR'] = tempfile.mkdtemp(prefix='rccad-cfg-')
os.environ.setdefault('RCCAD_WORKERS', '0')

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from rccad import history as hist
from rccad import sketchmeta as sm
from rccad.document import Body
from rccad.studio import TABS, StudioWindow


def sketch(name, tool, points, plane='XY', **extra):
    meta = dict(tool=tool, points=[list(p) for p in points], **extra)
    return Body(name, hist.meta_shape(plane, meta), 'sketch', plane, meta=meta).prepared()


class MatchSizeMathTests(unittest.TestCase):
    def test_same_family_takes_reference_size_and_keeps_center(self):
        ref = dict(tool='rect', points=[[0, 0], [20, 10]])
        other = dict(tool='centerRect', points=[[50, 50], [52, 51]])
        out = sm.match_size(ref, other)
        self.assertEqual(sm.values(out), ['20.0', '10.0'])
        self.assertEqual(sm.center_of(out), (50, 50))
        rotated = sm.match_size(ref, dict(tool='rect3', points=[[0, 0], [3, 3], [-1, 1]]))
        self.assertEqual([float(v) for v in sm.values(rotated)], [20.0, 10.0])
        self.assertAlmostEqual(sm.center_of(rotated)[0], 1.0)
        diameter = sm.match_size(dict(tool='circle', points=[[0, 0], [5, 0]]), dict(tool='circle2', points=[[10, 0], [12, 0]]))
        self.assertEqual(sm.values(diameter), ['10.0'])           # promień 5 -> średnica 10
        self.assertEqual(sm.center_of(diameter), (11.0, 0.0))

    def test_different_shapes_are_refused(self):
        self.assertIsNone(sm.match_size(dict(tool='rect', points=[[0, 0], [2, 2]]), dict(tool='circle', points=[[0, 0], [1, 0]])))
        self.assertIsNone(sm.match_size(dict(tool='polygon', points=[[0, 0], [2, 0]], sides=6), dict(tool='polygon', points=[[0, 0], [1, 0]], sides=5)))
        self.assertIsNone(sm.match_size(dict(tool='text', points=[[0, 0]]), dict(tool='text', points=[[0, 0]])))


class MatchSizeToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = StudioWindow()
        self.w.resize(1400, 850)
        self.w.show()
        self.app.processEvents()
        self.p = patch.object(QMessageBox, 'warning', return_value=QMessageBox.Ok)
        self.p.start()
        self.ref = sketch('Okrąg 1', 'circle', [(0, 0), (6, 0)])
        self.a = sketch('Okrąg 2', 'circle', [(30, 0), (32, 0)])
        self.b = sketch('Okrąg 3', 'circle3', [(60, 2), (62, 0), (60, -2)])
        self.r = sketch('Prostokąt', 'rect', [(0, 30), (5, 35)])
        self.w.document.commit([self.ref, self.a, self.b, self.r])
        self.w.refresh()

    def tearDown(self):
        end = time.monotonic() + 20
        while self.w.busy and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.005)
        self.w.document._saved_revision = self.w.document._revision
        self.w.close()
        self.w.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.p.stop()

    def click(self, body):
        with patch.object(self.w.view, 'nearest_edge', return_value=(body.id, 0)):
            self.w.view_clicked(10, 10, False, False)

    def radius(self, bid, live=True):
        body = self.w.override.get(bid) if live else None
        body = body or self.w.document.get(bid)
        return float(sm.size_of(body.meta)[0])

    def test_tool_sits_next_to_corner_sketch(self):
        tab = TABS['Szkic']
        self.assertEqual(tab.index('matchsize'), tab.index('wrapcorner') + 1)
        self.w.tools['matchsize'].click()
        self.assertEqual(self.w.mode, 'matchsize')
        self.assertTrue(self.w.matchsize_panel.isVisible())

    def test_live_resize_then_apply_is_one_history_step(self):
        w = self.w
        w.set_mode('matchsize')
        self.click(self.ref)
        self.assertEqual(w.mz_ref, self.ref.id)
        self.click(self.a)
        self.assertAlmostEqual(self.radius(self.a.id), 6.0)            # od razu, na polu roboczym
        self.assertAlmostEqual(self.radius(self.a.id, live=False), 2.0)  # projekt jeszcze bez zmian
        self.click(self.b)
        self.click(self.r)                                              # prostokąt nie pasuje do okręgu
        self.assertNotIn(self.r.id, w.mz_pending)
        steps = w.document.history_length
        w.mz_apply.click()
        self.wait()
        self.assertEqual(w.document.history_length, steps)               # zapisane w krokach, które narysowały kształty - bez nowego kroku
        self.assertAlmostEqual(self.radius(self.a.id, live=False), 6.0)
        self.assertAlmostEqual(self.radius(self.b.id, live=False), 6.0)
        self.assertAlmostEqual(sm.center_of(w.document.get(self.b.id).meta)[0], 60.0, 6)
        self.assertEqual(w.mode, 'matchsize')
        replayed = hist.run_recipe([self.ref, self.a, self.b, self.r], dict(type='sketchmeta', id=self.b.id, meta=w.document.get(self.b.id).meta))
        self.assertAlmostEqual(float(sm.size_of(next(x for x in replayed if x.id == self.b.id).meta)[0]), 6.0)

    def wait(self):
        end = time.monotonic() + 20
        while self.w.busy and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.005)
        self.app.processEvents()

    def test_shape_under_cursor_is_highlighted_before_click(self):
        w = self.w
        w.set_mode('matchsize')
        def hover(body):
            with patch.object(w.view, 'nearest_edge', return_value=(body.id, 0) if body else None), \
                 patch.object(w.view, 'pick_body', return_value=None):
                w.view_hover(10, 10)
        hover(self.a)
        self.assertTrue(w.view.preview_items)
        self.assertEqual(w.mz_hover_label, 'wzorzec')
        self.click(self.ref)
        hover(self.a)
        self.assertEqual(w.mz_hover_label, 'pasuje')
        hover(self.r)
        self.assertEqual(w.mz_hover_label, 'inny kształt')
        hover(None)
        self.assertFalse(w.view.preview_items)

    def test_close_discards_and_second_click_restores(self):
        w = self.w
        w.set_mode('matchsize')
        self.click(self.ref)
        self.click(self.a)
        self.click(self.a)
        self.assertNotIn(self.a.id, w.mz_pending)
        self.click(self.a)
        w.set_mode(None)
        self.assertAlmostEqual(self.radius(self.a.id), 2.0)
        self.assertFalse(w.override)
        self.assertFalse(w.view.tints)


if __name__ == '__main__':
    unittest.main()
